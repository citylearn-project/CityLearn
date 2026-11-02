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
    assert frame.iloc[-1]["month"] == 1
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
