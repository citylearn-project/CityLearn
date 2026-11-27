"""Explicit sample clocks, typed resampling and file evidence for reproducible runs."""

import datetime
import hashlib
import math
import time
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from citylearn.utilities import parse_bool

DEFINITION_VERSION = "temporal-evidence-v1"
# Calendar files with these suffixes (any case) are read as Parquet, others as CSV.
PARQUET_SUFFIXES = {".parquet", ".pq", ".parq"}
# Year of the export clock of a dataset without `start_date` when the calendar columns do not fix one.
DEFAULT_EXPORT_YEAR = 2024
# Rows of the calendar compared with the calendar columns of the data at load.
CALENDAR_CHECK_SAMPLE = 20000
_OFFSET = r"(?:Z|[+-]\d{2}(?::?\d{2})?)$"
FILE_TYPES = {
    ".csv",
    ".parquet",
    ".pq",
    ".parq",
    ".json",
    ".pkl",
    ".pickle",
    ".pt",
    ".pth",
    ".joblib",
    ".npy",
    ".npz",
    ".epw",
    ".txt",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(path):
    s = Path(path).stat()
    return (s.st_size, s.st_mtime_ns, s.st_ino)


# Digests of input files already hashed in this process, by resolved path. Every construction (and every
# business-as-usual reference) snapshots the same files, so each is read once while it stays unchanged.
_DIGEST_CACHE = {}
# A file written this recently could change again within the same timestamp tick without changing its
# stat fields, so it is always hashed (the "racily clean" rule git applies to its index).
_DIGEST_CACHE_MIN_AGE_NS = 2_000_000_000


def _cache_key(path):
    s = Path(path).stat()
    return (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino, s.st_dev)


def cached_sha256(path):
    """SHA-256 of `path`, reused while its size, times, inode and device are unchanged."""

    resolved = str(Path(path).resolve())
    key = _cache_key(resolved)
    hit = _DIGEST_CACHE.get(resolved)
    if hit is not None and hit[0] == key:
        return hit[1]
    digest = sha256(resolved)
    newest = max(key[1], key[2])
    if _cache_key(resolved) == key and time.time_ns() - newest >= _DIGEST_CACHE_MIN_AGE_NS:
        _DIGEST_CACHE[resolved] = (key, digest)
    return digest


def snapshot_inputs(schema):
    root = Path(schema.get("root_directory") or ".").resolve()
    files = {}

    def collect(value):
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif isinstance(value, str) and Path(value).suffix.lower() in FILE_TYPES:
            path = Path(value)
            path = path if path.is_absolute() else root / path
            if path.is_file():
                before = signature(path)
                digest = cached_sha256(path)
                if signature(path) != before:
                    raise RuntimeError("Input changed during snapshot: " + str(path))
                files[value] = dict(
                    path=str(path.resolve()), sha256=digest, signature=before
                )

    collect(schema)
    calendar = (schema.get("time_axis") or {}).get("calendar_file")
    if not calendar and str(schema.get("dataset_contract_version", "")).startswith("portugal-native") and (root / "shared/calendar.parquet").is_file():
        calendar = "shared/calendar.parquet"
    if calendar:
        collect(calendar)
    return files


def input_changes(snapshot):
    changed = {}
    for name, row in snapshot.items():
        path = Path(row["path"])
        if not path.is_file():
            changed[name] = "missing"
        elif (
            signature(path) != tuple(row["signature"]) and sha256(path) != row["sha256"]
        ):
            changed[name] = "changed_after_load"
    return changed


def runtime_versions():
    from importlib.metadata import version, PackageNotFoundError
    import platform

    result = dict(
        python=platform.python_version(),
        implementation=platform.python_implementation(),
        system=platform.system(),
        machine=platform.machine(),
    )
    for name in ("numpy", "pandas", "pyarrow", "gymnasium", "torch", "scikit-learn"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


class TimeAxis:
    def __init__(self, schema):
        self.schema = schema
        self.timezone = schema.get("timezone")
        if self.timezone:
            ZoneInfo(self.timezone)
        root = Path(schema.get("root_directory") or ".")
        filename = (schema.get("time_axis") or {}).get("calendar_file")
        if filename is None and str(schema.get("dataset_contract_version", "")).startswith("portugal-native") and (root / "shared/calendar.parquet").is_file():
            filename = "shared/calendar.parquet"
        self.filename = filename
        self.path = None
        self.utc = None
        self.seconds = None
        if filename:
            path = Path(filename)
            path = path if path.is_absolute() else root / path
            self.path = path
            frame = (
                pd.read_parquet(path)
                if path.suffix.lower() in PARQUET_SUFFIXES
                else pd.read_csv(path)
            )
            if not {"time_step", "timestamp_utc"} <= set(frame):
                raise ValueError(
                    "Canonical calendar requires time_step and timestamp_utc"
                )
            if not np.array_equal(frame.time_step.to_numpy(), np.arange(len(frame))):
                raise ValueError("Calendar indexes must be contiguous from zero")
            self.utc = pd.DatetimeIndex(
                pd.to_datetime(frame.timestamp_utc, utc=True, errors="raise")
            ).astype("datetime64[ns, UTC]")
            if self.utc.hasnans:
                raise ValueError("Calendar contains missing timestamps")
            differences = np.diff(self.utc.asi8) / 1e9
            if (
                len(differences) == 0
                or not np.isfinite(differences).all()
                or np.any(differences <= 0)
                or not np.all(differences == differences[0])
            ):
                raise ValueError(
                    "Calendar UTC timestamps must be unique, increasing and regular"
                )
            self.seconds = float(differences[0])
            if "timestamp_local" in frame:
                self._check_local(frame.timestamp_local)
        declared = schema.get("dataset_seconds_per_time_step")
        if declared is not None:
            if not np.isfinite(declared) or declared <= 0:
                raise ValueError("Dataset timestep must be positive and finite")
            if self.seconds is not None and float(declared) != self.seconds:
                raise ValueError("Declared dataset timestep disagrees with calendar")
            self.seconds = float(declared)

    def _check_local(self, values):
        """Check `timestamp_local` against `timestamp_utc`.

        Values with an offset (``2023-07-01T01:00:00+01:00``) must be the same instants. Values without one
        are wall-clock times in `timezone`, which is then required.
        """
        if isinstance(values.dtype, pd.DatetimeTZDtype):
            naive = False
        elif pd.api.types.is_datetime64_dtype(values.dtype):
            naive = True
        else:
            text = values.astype(str).str.strip()
            with_offset = text.str.contains(_OFFSET, regex=True)
            if with_offset.all():
                naive = False
            elif not with_offset.any():
                naive = True
            else:
                raise ValueError(
                    f"Calendar {self.filename}: timestamp_local mixes values with and without a UTC offset; "
                    "write every value with its offset (2023-07-01T01:00:00+01:00) or none."
                )
        if not naive:
            local = pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]").astype("int64")
            if not np.array_equal(np.asarray(local), self.utc.asi8):
                raise ValueError(f"Calendar {self.filename}: timestamp_local and timestamp_utc are different instants")
            return
        if not self.timezone:
            raise ValueError(
                f"Calendar {self.filename}: timestamp_local has no UTC offset, so the schema must declare "
                "`timezone` to read it as local wall-clock time (or write timestamp_local with its offset)."
            )
        wall = pd.DatetimeIndex(pd.to_datetime(values)).as_unit("ns")
        expected = self.utc.tz_convert(self.timezone).tz_localize(None).as_unit("ns")
        if not np.array_equal(wall.asi8, expected.asi8):
            index = int(np.flatnonzero(wall.asi8 != expected.asi8)[0])
            raise ValueError(
                f"Calendar {self.filename}: timestamp_local {wall[index]} at time_step {index} is not "
                f"timestamp_utc {self.utc[index].isoformat()} in {self.timezone} ({expected[index]})."
            )

    def validate(self, schema, building):
        """Check the calendar against the simulation window and `building`'s calendar columns, at load.

        The calendar must have a row for every global row up to `simulation_end_time_step` (with
        `terminal_observation_padding`, the last one may be missing: it is extended by one step). Converted to
        `timezone` (UTC without one), a sample of its rows must give the `month`, `hour` (1-24, hour 1 is
        00:00), `minutes` and `seconds` of the data; a `day_type` from 1 (Monday) to 7 (Sunday) that disagrees
        with the weekday gives a warning, since some datasets code their days differently.
        """
        if self.utc is None:
            return
        padding = parse_bool(
            schema.get("terminal_observation_padding", False), default=False, path="terminal_observation_padding",
        )
        start = int(schema.get("simulation_start_time_step", 0) or 0)
        end = int(schema.get("simulation_end_time_step", 0) or 0)
        needed = end + (0 if padding else 1)
        if len(self.utc) < needed:
            raise ValueError(
                f"time_axis.calendar_file {self.filename} has {len(self.utc)} rows (time_step 0 to "
                f"{len(self.utc) - 1}), but simulation_end_time_step is {end}: the calendar needs a row for "
                f"every data row up to it, at least {needed} rows"
                + (" (terminal_observation_padding supplies the last one)." if padding else ".")
            )
        simulation = getattr(building, "energy_simulation", None) if building is not None else None
        if simulation is None or getattr(simulation, "month", None) is None:
            return
        offset = int(getattr(simulation, "time_step_offset", start) or 0)
        rows = min(len(simulation.month), len(self.utc) - offset)
        if rows <= 0:
            return
        if rows > CALENDAR_CHECK_SAMPLE:
            sample = np.unique(np.linspace(0, rows - 1, CALENDAR_CHECK_SAMPLE).round().astype(int))
        else:
            sample = np.arange(rows)
        local = self.utc[offset + sample].tz_convert(self.timezone or "UTC")
        columns = {
            "month": (np.asarray(simulation.month)[sample], np.asarray(local.month)),
            "hour": (np.mod(np.rint(np.asarray(simulation.hour, dtype="float64")[sample]) - 1, 24),
                     np.asarray(local.hour)),
        }
        for name, actual in (("minutes", local.minute), ("seconds", local.second)):
            values = getattr(simulation, name, None)
            if values is not None and len(values) >= rows:
                columns[name] = (np.asarray(values)[sample], np.asarray(actual))
        bad = np.zeros(len(sample), dtype=bool)
        for data, expected in columns.values():
            bad |= np.asarray(data, dtype="float64") != np.asarray(expected, dtype="float64")
        zone = self.timezone or "UTC"
        if bad.any():
            i = int(np.flatnonzero(bad)[0])
            stamp = local[i]
            found = ", ".join(
                f"{name}={int(data[i]) + (1 if name == 'hour' else 0)}" for name, (data, _) in columns.items()
            )
            wanted = ", ".join(
                f"{name}={int(expected[i]) + (1 if name == 'hour' else 0)}" for name, (_, expected) in columns.items()
            )
            raise ValueError(
                f"time_axis.calendar_file {self.filename} disagrees with the calendar columns of "
                f"{building.name}'s energy_simulation at global row {offset + int(sample[i])}: the calendar gives "
                f"{stamp.isoformat()} in {zone}, which is {wanted} (hour 1 is 00:00), but the row has {found}. "
                "timestamp_utc must be UTC and `timezone` the time zone of the data's calendar columns."
            )
        day_type = getattr(simulation, "day_type", None)
        if day_type is not None and len(day_type) >= rows:
            day_type = np.rint(np.asarray(day_type, dtype="float64")[sample])
            weekday = np.asarray(local.dayofweek) + 1
            coded = (day_type >= 1) & (day_type <= 7)
            different = coded & (day_type != weekday)
            if different.any():
                import warnings
                i = int(np.flatnonzero(different)[0])
                warnings.warn(
                    f"time_axis.calendar_file {self.filename}: day_type {int(day_type[i])} of {building.name} at "
                    f"global row {offset + int(sample[i])} is not the weekday of {local[i].isoformat()} in {zone} "
                    f"({int(weekday[i])}, with 1 Monday and 7 Sunday); {int(different.sum())} of {int(coded.sum())} "
                    "checked rows differ. The calendar does not change day_type, which observations and "
                    "rule-based agents read as given.",
                    UserWarning,
                    stacklevel=2,
                )

    def at(self, index):
        if self.utc is None:
            return None
        if 0 <= index < len(self.utc):
            value = self.utc[index]
        elif index == len(self.utc) and parse_bool(
            self.schema.get("terminal_observation_padding", False),
            default=False,
            path="terminal_observation_padding",
        ):
            value = self.utc[-1] + pd.Timedelta(seconds=self.seconds)
        else:
            raise ValueError("Sample index is outside the canonical calendar")
        return value.tz_convert(self.timezone or "UTC").to_pydatetime()


def axis_metadata(env):
    axis = getattr(env, "_time_axis", None)
    tracker = env.episode_tracker
    source = (
        float(axis.seconds) if axis is not None and axis.seconds is not None else None
    )
    inferred = {
        b.name: float(b.energy_simulation.dataset_seconds_per_time_step)
        if b.energy_simulation.dataset_seconds_per_time_step
        else None
        for b in getattr(env, "buildings", [])
    }
    consistent = (
        all(v == env.seconds_per_time_step for v in inferred.values())
        if inferred and all(v is not None for v in inferred.values())
        else None
    )
    if source is not None:
        consistent = source == env.seconds_per_time_step
    steps = int(
        getattr(getattr(env, "_provenance_service", None), "steps", env.time_step)
    )
    return dict(
        definition_version=DEFINITION_VERSION,
        clock_source="canonical_calendar"
        if axis is not None and axis.utc is not None
        else "declared_interval"
        if source is not None
        else "legacy_inferred_clock",
        calendar_file=getattr(axis, "filename", None),
        timezone=getattr(axis, "timezone", None),
        dataset_seconds_per_time_step=source,
        inferred_dataset_seconds_by_member=inferred,
        control_seconds_per_time_step=float(env.seconds_per_time_step),
        clock_consistent=consistent,
        resampling="none_runtime_energy_scaling_only",
        episode_index=int(tracker.episode),
        episode_split_rng="sha256_seed_episode_v1",
        initialization_seed=getattr(env, "_initialization_seed", env.random_seed),
        environment_seed=env.random_seed,
        ev_drift_seed=getattr(env, "_ev_drift_seed", None),
        random_stream_version=getattr(env, "random_stream_version", None),
        physics_version=getattr(env, "physics_version", None),
        episode_split_boundary=getattr(env, "episode_split_boundary", None),
        ev_soc_carryover=bool(getattr(env, "ev_soc_carryover", False)),
        time_step_ratio_mode=getattr(env, "time_step_ratio_mode", None),
        random_stream_episode=getattr(tracker, "random_stream_episode", None),
        reset_seed_explicit=getattr(env, "_reset_seed_explicit", False),
        episode_index_explicit=bool(getattr(env, "_episode_index_explicit", False)),
        input_evidence_scope="schema_declared_files_plus_canonical_clock",
        observation_global_index=int(tracker.episode_start_time_step + env.time_step),
        executed_intervals=steps,
        executed_global_start=int(tracker.episode_start_time_step),
        executed_global_end=int(tracker.episode_start_time_step + steps - 1)
        if steps
        else None,
        terminal_padding=parse_bool(
            env.schema.get("terminal_observation_padding", False),
            default=False,
            path="terminal_observation_padding",
        ),
        terminal_is_observation=True,
        observation_timestamp_utc=(
            axis.at(tracker.episode_start_time_step + env.time_step)
            .astimezone(datetime.timezone.utc)
            .isoformat()
            if axis is not None and axis.utc is not None
            else None
        ),
        render_origin_override=bool(getattr(env, "_render_origin_overridden", False)),
        data_noise_generator="owned_indexed_stream_v1",
        storage_loss_coefficient="fraction_per_hour",
        storage_step_loss_fraction="fraction_per_control_step",
    )


def resample_series(values, source_seconds, target_seconds, *, kind, weights=None):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("Finite one-dimensional values are required")
    s, t = float(source_seconds), float(target_seconds)
    if not np.isfinite(s + t) or min(s, t) <= 0:
        raise ValueError("Intervals must be positive and finite")
    if kind not in {"energy", "power", "price", "intensity"}:
        raise ValueError("Categorical states/events require exact boundary mapping")
    duration = len(values) * s
    n = int(round(duration / t))
    if not math.isclose(n * t, duration, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Target interval does not cover the complete source duration")
    if weights is not None:
        weights = np.asarray(weights, dtype=float)
        if (
            kind not in {"price", "intensity"}
            or weights.shape != values.shape
            or not np.isfinite(weights).all()
            or (weights < 0).any()
        ):
            raise ValueError("Nonnegative energy weights apply only to price/intensity")
    result = np.zeros(n)
    denominator = np.zeros(n)
    i = j = 0
    while i < len(values) and j < n:
        overlap = min((i + 1) * s, (j + 1) * t) - max(i * s, j * t)
        weight = overlap if weights is None else overlap / s * weights[i]
        result[j] += values[i] * (overlap / s if kind == "energy" else weight)
        denominator[j] += weight
        if (i + 1) * s <= (j + 1) * t:
            i += 1
        else:
            j += 1
    if kind != "energy":
        result = np.divide(
            result, denominator, out=np.full(n, np.nan), where=denominator > 0
        )
    return result


def map_interval(start, end, source_seconds, target_seconds, *, end_inclusive=False):
    if (
        not np.isfinite(source_seconds + target_seconds)
        or min(source_seconds, target_seconds) <= 0
    ):
        raise ValueError("Invalid interval duration")
    if int(start) != start or int(end) != end or start < 0 or end < start:
        raise ValueError("Invalid event interval")

    def boundary(index):
        v = index * source_seconds / target_seconds
        if not math.isclose(v, round(v), rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Event boundary cannot be represented exactly")
        return int(round(v))

    return boundary(start), boundary(end + int(end_inclusive)) - int(end_inclusive)


def rescale_step_loss(loss, source_seconds, target_seconds):
    if (
        not 0 <= loss <= 1
        or not np.isfinite(source_seconds + target_seconds)
        or min(source_seconds, target_seconds) <= 0
    ):
        raise ValueError("Invalid loss or interval")
    return 1 - (1 - loss) ** (target_seconds / source_seconds)


def _time_of_day(simulation, rows):
    """Seconds after midnight of the first `rows` loaded rows: hour 1 starts at 00:00, as in the evaluation window."""
    hour = np.asarray(simulation.hour[:rows], dtype="float64")
    seconds = np.mod(np.rint(hour) - 1.0, 24.0) * 3600.0
    for name, scale in (("minutes", 60.0), ("seconds", 1.0)):
        values = getattr(simulation, name, None)
        if values is not None and len(values) >= rows:
            seconds = seconds + np.asarray(values[:rows], dtype="float64") * scale
    return seconds


def _calendar_date(simulation, seconds_per_time_step):
    """Date of the first loaded row derived from the `month` and `day_type` columns.

    If the month changes within 32 days, the first row of the new month is on its first day, which fixes
    the day of the month; otherwise the first row is on the first day of its month. The year is the latest
    one up to `DEFAULT_EXPORT_YEAR` in which that date falls on the weekday of `day_type` (1 Monday to 7
    Sunday) and the most month changes of the first 400 days of data, counted from the first, fall on a first
    day of the month (so a 365-day year that starts on a Monday is 2018, not the leap year 2024). Without a
    weekday (`day_type` 8 or none) only the second rule applies.
    """
    month = np.asarray(simulation.month, dtype="float64")
    first = int(month[0]) if len(month) and np.isfinite(month[0]) else 1
    if not 1 <= first <= 12:
        return datetime.date(DEFAULT_EXPORT_YEAR, 1, 1)
    rows = min(len(month), int(math.ceil(400 * 86400.0 / max(float(seconds_per_time_step), 1.0))) + 1)
    # Civil day of each row after the first: a day starts where the time of day falls back by more than
    # 12 hours (a daylight-saving change moves it by one hour only).
    day = np.concatenate([[0], np.cumsum(np.diff(_time_of_day(simulation, rows)) < -43200.0)])
    changes = np.flatnonzero(np.diff(month[:rows]) != 0) + 1
    changes = [int(k) for k in changes if 1 <= month[k] <= 12]
    target = days = None
    if changes and day[changes[0]] <= 31:
        target, days = int(month[changes[0]]), int(day[changes[0]])
    day_type = getattr(simulation, "day_type", None)
    weekday = int(round(float(day_type[0]))) if day_type is not None and len(day_type) else None
    weekday = weekday if weekday is not None and 1 <= weekday <= 7 else None

    def candidate(year):
        if target is None:
            return datetime.date(year, first, 1)
        value = datetime.date(year + (1 if target < first else 0), target, 1) - datetime.timedelta(days=days)
        return value if value.month == first else datetime.date(year, first, 1)

    def months_agreeing(value):
        """How many month changes in a row, from the first, fall on a first day of the month."""
        for count, k in enumerate(changes):
            date = value + datetime.timedelta(days=int(day[k]))
            if date.day != 1 or date.month != int(month[k]):
                return count
        return len(changes)

    years = range(DEFAULT_EXPORT_YEAR, DEFAULT_EXPORT_YEAR - 28, -1)
    matching = [candidate(year) for year in years if weekday is None or candidate(year).isoweekday() == weekday]
    if not matching:
        return candidate(DEFAULT_EXPORT_YEAR)
    # The latest year among those that place the most month changes on first days.
    return max(matching, key=lambda value: (months_agreeing(value), value.year))


def calendar_export_origin(simulation, seconds_per_time_step, *, start_date=None, timezone=None):
    """Time of global row 0 in exported timestamps of a dataset without a calendar file.

    The time of day comes from the `hour` (1-24, hour 1 starts at 00:00), `minutes` and `seconds` columns,
    the same reading as the evaluation window and the calendar observations. The date is `start_date` when
    one is given (the date of global row 0), otherwise it is derived from the `month` and `day_type` columns
    (see `_calendar_date`). With `timezone`, the result is an aware time in that zone and later rows are
    whole steps of elapsed time after it, so exported times follow its daylight-saving changes; otherwise
    it is naive. Returns None when `simulation` has no calendar columns.
    """
    if simulation is None or getattr(simulation, "hour", None) is None or not len(simulation.hour):
        return None
    step = float(seconds_per_time_step)
    offset = int(getattr(simulation, "time_step_offset", 0) or 0)
    first = float(_time_of_day(simulation, 1)[0])
    zone = ZoneInfo(timezone) if timezone else None
    if start_date is not None:
        # Global row 0 is on `start_date`, at the time of day that puts the first loaded row at its own
        # time of day after `offset` steps of elapsed time (daylight-saving changes included).
        midnight = datetime.datetime.combine(start_date, datetime.time())
        midnight = midnight.replace(tzinfo=zone) if zone else midnight
        reached = shift_clock(midnight, offset * step)
        reached = reached.hour * 3600.0 + reached.minute * 60.0 + reached.second + reached.microsecond * 1.0e-6
        return midnight + datetime.timedelta(seconds=float(np.mod(first - reached, 86400.0)))
    anchor = datetime.datetime.combine(_calendar_date(simulation, step), datetime.time()) + datetime.timedelta(
        seconds=first
    )
    if zone is None:
        return anchor - datetime.timedelta(seconds=offset * step)
    anchor = anchor.replace(tzinfo=zone).astimezone(datetime.timezone.utc)
    return (anchor - datetime.timedelta(seconds=offset * step)).astimezone(zone)


def shift_clock(origin, seconds):
    """`origin` plus `seconds` of elapsed time; aware times are moved in UTC and returned in their zone."""
    delta = datetime.timedelta(seconds=seconds)
    if origin.tzinfo is None:
        return origin + delta
    return (origin.astimezone(datetime.timezone.utc) + delta).astimezone(origin.tzinfo)
