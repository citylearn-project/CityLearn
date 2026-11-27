"""`time_axis.calendar_file` is checked against the data at load (#464)."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv

MINUTE_SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"
ORIGIN = "2024-07-01T00:00:00Z"  # a Monday: day_type 1
ZONE = "Europe/Lisbon"


def _dataset(tmp_path, *, rows=8, shift_hours=0, local_text="offset", calendar="calendar.csv", day_type=None):
    """minute_ev_demo with calendar columns that follow a UTC calendar of `rows` rows read in Lisbon time."""
    root = tmp_path / "data"
    shutil.copytree(MINUTE_SCHEMA.parent, root)
    clock = pd.date_range(ORIGIN, periods=8, freq="15min")
    local = clock.tz_convert(ZONE)
    frame = pd.read_csv(root / "Building_1.csv")
    frame["month"] = local.month
    frame["hour"] = (local + pd.Timedelta(hours=shift_hours)).hour + 1
    frame["minutes"] = local.minute
    frame["day_type"] = local.dayofweek + 1 if day_type is None else day_type
    frame.to_csv(root / "Building_1.csv", index=False)
    clock = clock[:rows]
    local = clock.tz_convert(ZONE)
    table = pd.DataFrame({
        "time_step": range(rows),
        "timestamp_utc": clock.astype(str),
        "timestamp_local": local.astype(str) if local_text == "offset" else local.tz_localize(None).astype(str),
    })
    if Path(calendar).suffix == ".csv":
        table.to_csv(root / calendar, index=False)
    else:
        table.to_parquet(root / calendar, index=False)
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    schema.update(root_directory=str(root), timezone=ZONE, time_axis={"calendar_file": calendar})
    schema.pop("start_date", None)
    return schema


def _env(schema, **kwargs):
    return CityLearnEnv(schema, central_agent=True, render_mode="none", random_seed=0, offline=True, **kwargs)


def test_a_calendar_that_agrees_with_the_data_loads(tmp_path):
    env = _env(_dataset(tmp_path))
    try:
        env.reset(seed=0)
        assert env._time_axis.at(1).isoformat() == "2024-07-01T01:15:00+01:00"
    finally:
        env.close()


def test_a_calendar_shorter_than_the_window_fails_at_load(tmp_path):
    with pytest.raises(ValueError, match=r"has 6 rows .* simulation_end_time_step is 7.* at least 8 rows"):
        _env(_dataset(tmp_path, rows=6))


def test_a_calendar_on_another_clock_than_the_calendar_columns_fails_at_load(tmp_path):
    # The data's hour is one hour ahead of the calendar converted to Lisbon time (UTC read as local time, say).
    with pytest.raises(ValueError, match=r"disagrees with the calendar columns of Building_1's energy_simulation"):
        _env(_dataset(tmp_path, shift_hours=1))


def test_a_day_type_that_is_not_the_weekday_warns(tmp_path):
    with pytest.warns(UserWarning, match="day_type 3 of Building_1"):
        env = _env(_dataset(tmp_path, day_type=3))
    env.close()


@pytest.mark.parametrize("suffix", [".parq", ".PARQUET", ".pq"])
def test_parquet_calendars_are_read_by_suffix(tmp_path, suffix):
    env = _env(_dataset(tmp_path, calendar=f"calendar{suffix}"))
    try:
        assert env._time_axis.seconds == 900.0
    finally:
        env.close()


def test_naive_local_timestamps_are_wall_clock_times_in_the_timezone(tmp_path):
    schema = _dataset(tmp_path, local_text="naive")
    env = _env(schema)
    env.close()
    schema.pop("timezone")
    with pytest.raises(ValueError, match="timestamp_local has no UTC offset"):
        _env(schema)
