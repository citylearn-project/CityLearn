"""Thermal storage discharge at the first control step.

The device serves the demand left after storage discharge. At t=0 the building
reconciles device electricity separately; it must not subtract the discharge a
second time (which under-reported electricity and could make it negative).
"""

import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet


def _env(initial_soc=1.0):
    schema = DataSet().get_schema('citylearn_challenge_2023_phase_2_local_evaluation')

    for building in schema['buildings'].values():
        building['type'] = 'citylearn.building.Building'
        building.pop('dynamics', None)
        building['power_outage'] = {'simulate_power_outage': False}
        building['dhw_storage']['attributes']['initial_soc'] = initial_soc

    return CityLearnEnv(schema, central_agent=False)


@pytest.mark.parametrize('action', [-1.0, -0.005])
def test_first_step_dhw_discharge_electricity_matches_device_output(action):
    env = _env()
    env.reset()
    building = env.buildings[0]
    actions = []

    for names in env.action_names:
        values = [0.0] * len(names)

        if 'dhw_storage' in names:
            values[names.index('dhw_storage')] = action

        actions.append(values)

    for t in (0, 1):
        env.step(actions)
        discharge = building.dhw_storage.energy_balance[t]
        device_output = building.energy_from_dhw_device[t]
        consumption = building.dhw_device.electricity_consumption[t]

        assert discharge < 0.0, 'scenario must discharge the tank'
        assert consumption >= 0.0
        assert consumption == pytest.approx(device_output / building.dhw_device.efficiency, rel=1.0e-5, abs=1.0e-7)
