"""LSTM dynamics HVAC actions request a fraction of nominal power, converted to energy exactly once."""

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.building import DynamicsBuilding
from citylearn.citylearn import CityLearnEnv

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
ACTION = 0.5
MEASURED_STEP = 20  # after the LSTM lookback warm-up
CASES = {
    # (dataset, action name, action value, device)
    'cooling': ('citylearn_challenge_2023_phase_1', 'cooling_device', ACTION, 'cooling_device'),
    'heating': ('vt_chittenden_county_neighborhood', 'cooling_or_heating_device', ACTION, 'heating_device'),
}


def _referenced_files(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _referenced_files(item)
    elif isinstance(value, list):
        for item in value:
            yield from _referenced_files(item)
    elif isinstance(value, str) and value.endswith(('.csv', '.pth')):
        yield value


def _schema(dataset, tmp_path, native_quarter_hour):
    """First building only; optionally relabel its hourly rows as native 15-minute data."""
    source = DATASETS/dataset
    schema = json.loads((source/'schema.json').read_text(encoding='utf-8'))
    first = next(name for name, building in schema['buildings'].items() if building.get('include', True))
    schema['buildings'] = {first: {**schema['buildings'][first], 'include': True}}
    schema['root_directory'] = str(source)

    if native_quarter_hour:
        target = tmp_path/dataset
        target.mkdir()
        for filename in set(_referenced_files(schema['buildings'][first])):
            shutil.copy(source/filename, target/filename)

        energy_simulation = target/schema['buildings'][first]['energy_simulation']
        frame = pd.read_csv(energy_simulation)
        index = np.arange(len(frame))
        frame['hour'] = (index//4)%24
        frame.insert(frame.columns.get_loc('hour') + 1, 'minutes', (index%4)*15)
        for col in ('cooling_demand', 'heating_demand', 'dhw_demand', 'non_shiftable_load'):
            if col in frame.columns:
                frame[col] = frame[col] * 0.25
        frame.to_csv(energy_simulation, index=False)
        schema['root_directory'] = str(target)

    return schema


@pytest.mark.parametrize('kind', list(CASES))
@pytest.mark.parametrize('resolution, seconds, expected_ratio', [
    ('native_hourly', 3600, 1.0),
    ('hourly_data_900s_control', 900, 0.25),
    ('native_quarter_hour', 900, 1.0),
])
def test_hvac_action_delivers_requested_fraction_of_nominal_power(tmp_path, kind, resolution, seconds, expected_ratio):
    dataset, action_name, action_value, device_name = CASES[kind]
    schema = _schema(dataset, tmp_path, native_quarter_hour=resolution == 'native_quarter_hour')
    env = CityLearnEnv(
        schema, central_agent=True, seconds_per_time_step=seconds, episode_time_steps=MEASURED_STEP + 2,
        simulation_start_time_step=200, solar_generation=False, random_seed=0,
    )
    env.reset()
    building = env.buildings[0]
    assert isinstance(building, DynamicsBuilding)
    assert building.time_step_ratio == pytest.approx(expected_ratio)
    device = getattr(building, device_name)
    action = np.zeros(len(env.action_names[0]))
    action[env.action_names[0].index(action_name)] = action_value

    while env.time_step <= MEASURED_STEP:
        env.step([action.tolist()])

    mode = building.energy_simulation.hvac_mode[MEASURED_STEP]
    assert mode in ([1, 3] if kind == 'cooling' else [2, 3])
    # `electricity_consumption` is energy per control step: 50% of nominal power for the step's duration.
    expected = action_value*device.nominal_power*seconds/3600.0
    assert device.electricity_consumption[MEASURED_STEP] == pytest.approx(expected, rel=1.0e-6)
