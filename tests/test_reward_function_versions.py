"""Per-building reward metadata, the version 2 EV and comfort rewards (#249) and their default (#278)."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.reward_function import (
    ComfortReward, Electric_Vehicles_Reward_Function, MultiBuildingRewardFunction, SolarPenaltyAndComfortReward,
    SolarPenaltyReward,
)

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'


# 1. MultiBuildingRewardFunction gives each function its own building's metadata and pairs by name.

def _building_metadata(name, battery_capacity):
    storage = lambda capacity: {'capacity': capacity}
    return {
        'name': name, 'cooling_storage': storage(0.0), 'heating_storage': storage(0.0), 'dhw_storage': storage(0.0),
        'electrical_storage': storage(battery_capacity),
    }


def _solar_observation():
    return {'net_electricity_consumption': 5.0, 'electrical_storage_soc': 0.5}


def test_per_building_reward_reads_each_buildings_own_metadata():
    # B1 has no battery and B2 has a 10 kWh battery. Up to 3.6.0 both functions read B1's metadata: [0.0, 0.0].
    metadata = {
        'central_agent': False, 'buildings': [_building_metadata('B1', 0.0), _building_metadata('B2', 10.0)],
    }
    direct = SolarPenaltyReward(metadata).calculate([_solar_observation(), _solar_observation()])
    wrapper = MultiBuildingRewardFunction(None, {'B1': SolarPenaltyReward(None), 'B2': SolarPenaltyReward(None)})
    wrapper.env_metadata = metadata

    assert direct == [0.0, -7.5]
    assert wrapper.calculate([_solar_observation(), _solar_observation()]) == direct
    assert [b['name'] for b in wrapper.reward_functions['B2'].env_metadata['buildings']] == ['B2']


def test_per_building_reward_pairs_functions_with_buildings_by_name():
    # The functions are keyed in another order than the buildings, and B1 is not an active member.
    wrapper = MultiBuildingRewardFunction(None, {'B2': SolarPenaltyReward(None), 'B1': SolarPenaltyReward(None)})
    wrapper.env_metadata = {
        'central_agent': False, 'buildings': [_building_metadata('B1', 0.0), _building_metadata('B2', 10.0)],
    }
    assert wrapper.calculate([_solar_observation(), _solar_observation()]) == [0.0, -7.5]

    wrapper.env_metadata = {'central_agent': False, 'buildings': [_building_metadata('B2', 10.0)]}
    assert wrapper.calculate([_solar_observation()]) == [-7.5]
    assert wrapper.reward_functions['B1'].env_metadata['buildings'] == []


def _schema():
    # Read the schema in place: loading the dataset by name copies it into the shared cache, which races under xdist.
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    return schema


@pytest.mark.parametrize('central_agent', [False, True])
def test_per_building_schema_matches_the_single_reward_function(central_agent):
    schema = _schema()
    rewards = []

    for reward_type in ({'default': 'citylearn.reward_function.SolarPenaltyReward'},
                        'citylearn.reward_function.SolarPenaltyReward'):
        schema['reward_function'] = {'type': reward_type, 'attributes': {}}
        env = CityLearnEnv(schema, central_agent=central_agent, episode_time_steps=4, random_seed=0)
        env.reset()

        if isinstance(env.reward_function, MultiBuildingRewardFunction):
            for name, rf in env.reward_function.reward_functions.items():
                assert [b['name'] for b in rf.env_metadata['buildings']] == [name]

        episode = []
        while not env.terminated:
            _, reward, *_ = env.step([[0.5] * space.shape[0] for space in env.action_space])
            episode.append(reward)

        rewards.append(np.asarray(episode, dtype='float64'))
        env.close()

    np.testing.assert_allclose(rewards[0], rewards[1], rtol=1e-6)


# 2. Electric_Vehicles_Reward_Function version 2: monotone departure penalty and base reward added.

def _ev_observation(battery_soc, net=0.0):
    return {
        'net_electricity_consumption': net,
        'charging_constraint_violation_kwh': 0.0,
        'electric_vehicles_chargers_dict': {'charger_1': {
            'connected': True, 'last_charged_kwh': 0.0, 'previous_battery_soc': battery_soc,
            'battery_soc': battery_soc, 'battery_capacity': 40.0, 'min_capacity': 0.0, 'required_soc': 0.8,
            'hours_until_departure': 0, 'max_charging_power': 7.0, 'max_discharging_power': 7.0,
        }},
    }


DEPARTURE_SOCS = [0.8, 0.65, 0.5, 0.2]


def _departure_rewards(version):
    reward = Electric_Vehicles_Reward_Function({'central_agent': False}, version=version)
    return [reward.calculate([_ev_observation(soc)])[0] for soc in DEPARTURE_SOCS]


def test_ev_reward_version_1_is_unchanged_and_deprecated():
    # Severe under-charging scores better than moderate under-charging in version 1.
    with pytest.warns(DeprecationWarning, match='only to reproduce runs made with CityLearn 3.6.0'):
        assert _departure_rewards(1) == pytest.approx([110.0, -20.0, 15.0, 15.0])


def test_ev_reward_version_2_penalizes_deeper_departure_deficits_more():
    rewards = _departure_rewards(2)

    assert _departure_rewards(None) == rewards
    assert rewards == pytest.approx([110.0, -20.0, -35.0, -35.0])
    assert all(a >= b for a, b in zip(rewards, rewards[1:]))


def test_ev_reward_version_2_adds_the_base_reward():
    no_charger = {'net_electricity_consumption': 50.0, 'charging_constraint_violation_kwh': 0.0}
    # MARL base reward of a lone building importing 50 kWh: -0.01 * 50 ** 2 * 50.
    with pytest.warns(DeprecationWarning):
        assert Electric_Vehicles_Reward_Function({'central_agent': False}, version=1).calculate([no_charger]) == [0.0]
    assert Electric_Vehicles_Reward_Function({'central_agent': False}, version=2).calculate([no_charger]) == [-1250.0]

    base = -0.01
    observation = _ev_observation(0.8, net=1.0)
    reward = Electric_Vehicles_Reward_Function({'central_agent': False}, version=2)
    assert reward.calculate([observation]) == pytest.approx([base + 110.0 / (1.0 + abs(base))])

    central = Electric_Vehicles_Reward_Function({'central_agent': True}, version=2)
    observations = [observation, no_charger]
    assert central.calculate(observations) == pytest.approx([sum(reward.calculate(observations))])


# 3. ComfortReward version 2 follows the HVAC mode.

def _comfort_observation(hvac_mode, temperature, heating_demand=0.0, cooling_demand=0.0):
    return {
        'hvac_mode': hvac_mode, 'indoor_dry_bulb_temperature': temperature, 'heating_demand': heating_demand,
        'cooling_demand': cooling_demand, 'indoor_dry_bulb_temperature_heating_set_point': 20.0,
        'indoor_dry_bulb_temperature_cooling_set_point': 24.0, 'comfort_band': 2.0,
    }


@pytest.mark.parametrize('observation,version_1,version_2', [
    # Heating mode, 21.5 C within the band above the 20 C set point, heater off and on.
    (_comfort_observation(2, 21.5), 0.0, -1.5),
    (_comfort_observation(2, 21.5, heating_demand=5.0), -1.5, -1.5),
    # Heating mode, overheated beyond the band with the heater off: the higher exponent applies in version 2.
    (_comfort_observation(2, 25.0), -25.0, -125.0),
    # Cooling mode, 23 C within the band below the 24 C set point, while a heating demand dominates.
    (_comfort_observation(1, 23.0, heating_demand=5.0), 0.0, -1.0),
    # Off and automatic modes keep the version 1 rule.
    (_comfort_observation(0, 17.0), -27.0, -27.0),
    (_comfort_observation(3, 22.0), 0.0, 0.0),
])
def test_comfort_reward_version_2_follows_the_hvac_mode(observation, version_1, version_2):
    metadata = {'central_agent': False}
    kwargs = dict(lower_exponent=2.0, higher_exponent=3.0)

    with pytest.warns(DeprecationWarning):
        assert ComfortReward(metadata, version=1, **kwargs).calculate([observation]) == pytest.approx([version_1])

    assert ComfortReward(metadata, version=2, **kwargs).calculate([observation]) == pytest.approx([version_2])
    assert ComfortReward(metadata, **kwargs).calculate([observation]) == pytest.approx([version_2])


def test_reward_versions_are_validated_and_recorded():
    with pytest.raises(ValueError, match='version must be one of'):
        ComfortReward(None, version=3)

    with pytest.raises(ValueError, match='version must be one of'):
        Electric_Vehicles_Reward_Function(None, version='2')

    assert SolarPenaltyAndComfortReward(None, version=2).version == 2

    # Rewards pickled by CityLearn 3.6.0 have no version attribute and keep version 1.
    for reward in (ComfortReward(None, version=2), Electric_Vehicles_Reward_Function(None, version=2)):
        del reward.__dict__['version']
        assert reward.version == 1

    # The bundled schema selects version 2, which is also the class default.
    env = CityLearnEnv(_schema(), episode_time_steps=4)
    evidence = env.get_metadata()['reward_evidence']

    assert type(env.reward_function) is ComfortReward and env.reward_function.version == 2
    assert evidence['configured_attributes']['version'] == 2
    assert evidence['effective_public_parameters']['version'] == 2
    env.close()

    with pytest.warns(DeprecationWarning, match='version 1 is deprecated'):
        env = CityLearnEnv(_schema(), reward_function_kwargs={'version': 1}, episode_time_steps=4)

    assert env.reward_function.version == 1
    env.close()


def test_bundled_schemas_select_reward_version_2():
    import glob

    names = {'citylearn.reward_function.ComfortReward', 'citylearn.reward_function.Electric_Vehicles_Reward_Function'}
    selected = []

    for path in glob.glob(str(Path(__file__).resolve().parents[1] / 'data' / 'datasets' / '*' / 'schema.json')):
        reward = json.loads(Path(path).read_text(encoding='utf-8'))['reward_function']

        if reward['type'] in names:
            selected.append(Path(path).parent.name)
            assert (reward.get('attributes') or {}).get('version') == 2, path

    assert len(selected) == 18
