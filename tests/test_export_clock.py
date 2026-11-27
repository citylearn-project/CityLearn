"""Exported timestamps agree with the calendar columns of the data (#460)."""

import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.temporal import calendar_export_origin, shift_clock

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data" / "datasets"
COLUMNS = ("month", "hour", "minutes", "seconds", "day_type")
# The Quebec datasets repeat one January-March period three times, so only the first period is one calendar.
REPEATED_PERIODS = {
    "quebec_neighborhood_with_demand_response_set_points": 90,
    "quebec_neighborhood_without_demand_response_set_points": 90,
}


def _calendar(name):
    schema = json.loads((DATASETS / name / "schema.json").read_text(encoding="utf-8"))
    path = DATASETS / name / next(iter(schema["buildings"].values()))["energy_simulation"]
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq
        names = set(pq.ParquetFile(path).schema.names)
        frame = pd.read_parquet(path, columns=[c for c in COLUMNS if c in names])
    else:
        frame = pd.read_csv(path, usecols=lambda column: column in COLUMNS)
    return schema, frame


@pytest.mark.parametrize("name", sorted(path.name for path in DATASETS.iterdir() if (path / "schema.json").is_file()))
def test_export_clock_of_every_bundled_dataset_agrees_with_its_calendar_columns(name):
    schema, frame = _calendar(name)
    step = float(schema["seconds_per_time_step"])
    simulation = SimpleNamespace(
        **{column: frame[column].to_numpy() if column in frame else None for column in COLUMNS}, time_step_offset=0,
    )
    start_date = schema.get("start_date")
    origin = calendar_export_origin(
        simulation, step, start_date=None if start_date is None else datetime.date.fromisoformat(start_date),
        timezone=schema.get("timezone"),
    )
    # The first year (the first period of the repeated ones): the 2021 dataset has no 29 February in 2016.
    rows = min(len(frame), int(REPEATED_PERIODS.get(name, 365) * 86400 / step))
    for index in np.unique(np.linspace(0, rows - 1, 500).astype(int)):
        stamp = shift_clock(origin, float(index) * step)
        row = frame.iloc[index]
        assert stamp.month == row["month"], (index, stamp)
        assert stamp.hour == (int(row["hour"]) - 1) % 24, (index, stamp)  # hour 1 is 00:00
        if "minutes" in frame:
            assert stamp.minute == row["minutes"], (index, stamp)
        if 1 <= row["day_type"] <= 7:
            assert stamp.isoweekday() == row["day_type"], (index, stamp)


def test_plus_evs_first_row_is_the_same_hour_as_the_other_2022_datasets():
    for path in sorted((DATASETS / "citylearn_challenge_2022_phase_all_plus_evs").glob("Building_*.csv")):
        reference = DATASETS / "citylearn_challenge_2022_phase_all" / path.name
        assert pd.read_csv(path, nrows=2)[["month", "hour", "day_type"]].equals(
            pd.read_csv(reference, nrows=2)[["month", "hour", "day_type"]]
        ), path.name


def _exported_timestamps(tmp_path, dataset, **kwargs):
    env = CityLearnEnv(
        str(DATASETS / dataset / "schema.json"), central_agent=True, render_mode="end",
        render_directory=tmp_path, render_session_name="clock", random_seed=0, **kwargs,
    )
    try:
        env.reset(seed=0)
        while not env.terminated:
            if env.interface == "entity":
                actions = {"tables": {k: np.zeros(s.shape, dtype="float32") for k, s in env.action_space["tables"].items()}}
            else:
                actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
            env.step(actions)
        community = next(Path(env.new_folder_path).glob("exported_data_community_ep*.*"))
        frame = pd.read_parquet(community) if community.suffix == ".parquet" else pd.read_csv(community)
        return frame["timestamp"].astype(str).tolist(), env.buildings[0].energy_simulation
    finally:
        env.close()


def test_2022_exports_start_at_the_hour_of_their_first_row(tmp_path):
    stamps, simulation = _exported_timestamps(tmp_path, "citylearn_challenge_2022_phase_all", episode_time_steps=3)
    # Row 0 is month 7, hour 24, day_type 7: 23:00 on a Sunday in July, then midnight on Monday 1 August.
    assert stamps[:2] == ["2022-07-31T23:00:00", "2022-08-01T00:00:00"]
    assert (int(simulation.month[1]), int(simulation.hour[1]), int(simulation.day_type[1])) == (8, 1, 1)


def test_start_date_sets_the_date_but_not_the_time_of_day(tmp_path):
    stamps, _ = _exported_timestamps(
        tmp_path, "citylearn_challenge_2022_phase_all", episode_time_steps=3, start_date="2030-01-01",
    )
    assert stamps[0] == "2030-01-01T23:00:00"


def test_portugal_exports_are_lisbon_civil_time(tmp_path):
    # Global row 17000 is 2023-06-27 02:00 UTC, 03:00 in Lisbon summer time (hour 4).
    stamps, simulation = _exported_timestamps(
        tmp_path, "pt_rec_4", simulation_start_time_step=17000, simulation_end_time_step=17004,
        episode_time_steps=4,
    )
    assert stamps[0] == "2023-06-27T03:00:00+01:00"
    for stamp, hour, minute in zip(stamps, simulation.hour, simulation.minutes):
        local = datetime.datetime.fromisoformat(stamp)
        assert (local.hour, local.minute) == ((int(hour) - 1) % 24, int(minute))
