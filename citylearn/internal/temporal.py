"""Explicit sample clocks, typed resampling and file evidence for reproducible runs."""

import datetime
import hashlib
import math
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from citylearn.utilities import parse_bool

DEFINITION_VERSION = "temporal-evidence-v1"
FILE_TYPES = {
    ".csv",
    ".parquet",
    ".pq",
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
                digest = sha256(path)
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
        self.utc = None
        self.seconds = None
        if filename:
            path = Path(filename)
            path = path if path.is_absolute() else root / path
            frame = (
                pd.read_parquet(path)
                if path.suffix in {".parquet", ".pq"}
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
            if "timestamp_local" in frame and not np.array_equal(
                pd.to_datetime(frame.timestamp_local, utc=True)
                .astype("datetime64[ns, UTC]").astype("int64"),
                self.utc.asi8,
            ):
                raise ValueError("Local and UTC calendar instants disagree")
        declared = schema.get("dataset_seconds_per_time_step")
        if declared is not None:
            if not np.isfinite(declared) or declared <= 0:
                raise ValueError("Dataset timestep must be positive and finite")
            if self.seconds is not None and float(declared) != self.seconds:
                raise ValueError("Declared dataset timestep disagrees with calendar")
            self.seconds = float(declared)

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
        storage_loss_coefficient="fraction_per_control_step",
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
