from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from citylearn.internal.loading import CityLearnLoadingService


def _service() -> CityLearnLoadingService:
    return CityLearnLoadingService(SimpleNamespace(topology_mode="static"))


def test_terminal_padding_adds_state_not_physical_interval(tmp_path):
    path = tmp_path / "energy.parquet"
    pd.DataFrame(
        {
            "month": [12, 12],
            "hour": [23, 23],
            "minutes": [30, 45],
            "day_type": [7, 7],
            "non_shiftable_load": [0.4, 0.5],
        }
    ).to_parquet(path, index=False)
    schema = {
        "simulation_start_time_step": 0,
        "simulation_end_time_step": 2,
        "seconds_per_time_step": 900,
        "terminal_observation_padding": True,
    }

    frame = _service()._read_simulation_dataframe(schema, path)

    assert len(frame) == 3
    # Two rows cannot tell which day of December this is, so the month is kept.
    assert frame.iloc[-1]["month"] == 12
    assert frame.iloc[-1]["hour"] == 0
    assert frame.iloc[-1]["minutes"] == 0
    assert frame.iloc[-1]["day_type"] == 1
    assert frame.iloc[-1]["non_shiftable_load"] == pytest.approx(0.5)


def test_terminal_padding_exposes_ev_departure_transition(tmp_path):
    path = tmp_path / "charger.parquet"
    pd.DataFrame(
        {
            "electric_vehicle_charger_state": [1],
            "electric_vehicle_id": ["EV_1"],
            "electric_vehicle_departure_time": [1.0],
            "electric_vehicle_required_soc_departure": [0.8],
            "electric_vehicle_current_soc": [0.75],
        }
    ).to_parquet(path, index=False)
    schema = {
        "simulation_start_time_step": 0,
        "simulation_end_time_step": 1,
        "seconds_per_time_step": 900,
        "terminal_observation_padding": True,
    }

    frame = _service()._read_simulation_dataframe(schema, path)

    assert frame["electric_vehicle_charger_state"].tolist() == [1, 3]
    assert np.isnan(frame.iloc[-1]["electric_vehicle_departure_time"])
    assert np.isnan(frame.iloc[-1]["electric_vehicle_required_soc_departure"])
    assert np.isnan(frame.iloc[-1]["electric_vehicle_current_soc"])


@pytest.mark.parametrize('departure', [-1.0, np.nan, 2.0])
def test_terminal_padding_keeps_ev_with_no_known_departure_connected(tmp_path, departure):
    path = tmp_path / 'charger.parquet'
    pd.DataFrame({'electric_vehicle_charger_state': [1],
                  'electric_vehicle_departure_time': [departure],
                  'electric_vehicle_required_soc_departure': [.8]}).to_parquet(path, index=False)
    schema = {'simulation_start_time_step': 0, 'simulation_end_time_step': 1,
              'seconds_per_time_step': 900, 'terminal_observation_padding': True}
    frame = _service()._read_simulation_dataframe(schema, path)
    assert frame.electric_vehicle_charger_state.tolist() == [1, 1]
    assert frame.electric_vehicle_required_soc_departure.tolist() == [.8, .8]


def test_terminal_padding_rejects_more_than_one_missing_state(tmp_path):
    path = tmp_path / "short.parquet"
    pd.DataFrame({"value": [1.0]}).to_parquet(path, index=False)
    schema = {
        "simulation_start_time_step": 0,
        "simulation_end_time_step": 2,
        "seconds_per_time_step": 900,
        "terminal_observation_padding": True,
    }

    with pytest.raises(ValueError, match="exactly one terminal state"):
        _service()._read_simulation_dataframe(schema, path)


def _padded_calendar(tmp_path, frame: pd.DataFrame, seconds: int, **schema):
    path = tmp_path / "energy.csv"
    frame.to_csv(path, index=False)
    schema = {
        "simulation_start_time_step": 0, "simulation_end_time_step": len(frame),
        "seconds_per_time_step": seconds, "terminal_observation_padding": True, **schema,
    }
    return _service()._read_simulation_dataframe(schema, path).iloc[-1]


def test_terminal_padding_keeps_the_1_to_24_hour_convention_and_the_weekday(tmp_path):
    # Hourly data, hours 1-24, eight days ending on a Sunday (7) at hour 24.
    days = np.repeat([7, 1, 2, 3, 4, 5, 6, 7], 24)
    frame = pd.DataFrame({"month": 6, "hour": np.tile(np.arange(1, 25), 8), "day_type": days, "non_shiftable_load": 1.0})
    row = _padded_calendar(tmp_path, frame, 3600)
    assert (row["hour"], row["day_type"], row["month"]) == (1, 1, 6)


def test_terminal_padding_after_a_holiday_takes_the_weekday_of_the_week_before(tmp_path):
    days = np.repeat([3, 4, 5, 6, 7, 1, 2, 8], 24)  # the last day, a Wednesday, is a holiday
    frame = pd.DataFrame({"month": 3, "hour": np.tile(np.arange(24), 8), "day_type": days, "non_shiftable_load": 1.0})
    row = _padded_calendar(tmp_path, frame, 3600)
    assert (row["hour"], row["day_type"]) == (0, 4)


def test_terminal_padding_advances_the_month_only_after_its_last_day(tmp_path):
    hours = np.tile(np.arange(24), 31)
    months = np.r_[np.full(24, 3), np.full(30 * 24, 4)]  # 31 March, then all of April
    days = np.repeat(np.arange(31) % 7 + 1, 24)
    frame = pd.DataFrame({"month": months, "hour": hours, "day_type": days, "non_shiftable_load": 1.0})
    assert _padded_calendar(tmp_path, frame, 3600)["month"] == 5
    # One day short of the end of April: the month is kept.
    assert _padded_calendar(tmp_path, frame.iloc[:-24], 3600)["month"] == 4


def test_terminal_padding_within_a_day_keeps_the_date(tmp_path):
    frame = pd.DataFrame({
        "month": 1, "hour": np.repeat(np.arange(24), 4)[:50], "minutes": np.tile([0, 15, 30, 45], 24)[:50],
        "day_type": 2, "non_shiftable_load": 1.0,
    })
    row = _padded_calendar(tmp_path, frame, 900)
    assert (row["hour"], row["minutes"], row["day_type"], row["month"]) == (12, 30, 2, 1)
