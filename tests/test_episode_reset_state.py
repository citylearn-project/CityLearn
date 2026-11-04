"""State that must not leak from one episode into the next."""

import numpy as np
import pytest

import citylearn.utilities as utilities
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet


def _full_series(data, name):
    """Return the whole underlying series, ignoring the current episode window."""

    start, end = data.start_time_step, data.end_time_step
    data.start_time_step, data.end_time_step = None, None

    try:
        return np.array(getattr(data, name), copy=True)
    finally:
        data.start_time_step, data.end_time_step = start, end


def _run(env, action_for, steps=None):
    done, executed = False, 0

    while not done and (steps is None or executed < steps):
        _, _, terminated, truncated, _ = env.step(action_for(env))
        done = terminated or truncated
        executed += 1


def test_storage_action_feedback_is_recorded_after_reset():
    schema = DataSet().get_schema('citylearn_challenge_2023_phase_2_local_evaluation')
    names = list(schema['buildings'])

    for name, building in schema['buildings'].items():
        building['type'] = 'citylearn.building.Building'
        building.pop('dynamics', None)
        building['power_outage'] = {'simulate_power_outage': False}
        building['include'] = name == names[0]

    env = CityLearnEnv(schema, central_agent=False)
    building = env.buildings[0]
    index = env.action_names[0].index('electrical_storage')
    attribute = 'action_feedback_electrical_storage_requested_action_normalized'

    for value in (0.5, 0.7):
        env.reset()

        def action(env, value=value):
            values = [0.0] * len(env.action_names[0])
            values[index] = value
            return [values]

        _run(env, action, steps=3)
        np.testing.assert_allclose(getattr(building, attribute)[:3], value)


def test_charging_constraint_violation_observation_resets():
    schema = DataSet().get_schema('citylearn_three_phase_electrical_service_demo')

    for name, building in schema['buildings'].items():
        building['include'] = name == 'Building_15'

    schema.update(simulation_start_time_step=0, simulation_end_time_step=23, episode_time_steps=None)
    env = CityLearnEnv(schema, central_agent=False)
    building = env.buildings[0]
    env.reset()
    _run(env, lambda env: [[1.0 if 'storage' in name else 0.0 for name in env.action_names[0]]])
    assert building._charging_constraint_last_penalty_kwh > 0.0, 'scenario must produce a violation'

    env.reset()
    assert building.observations()['charging_constraint_violation_kwh'] == 0.0


def test_dynamic_variables_restored_when_episode_lengths_differ():
    schema = DataSet().get_schema('vt_chittenden_county_neighborhood')
    names = list(schema['buildings'])

    for name in names[1:]:
        schema['buildings'][name]['include'] = False

    schema['buildings'][names[0]]['pv'] = {
        'type': 'citylearn.energy_model.PV', 'autosize': False, 'attributes': {'nominal_power': 2.0},
    }
    schema.update(
        simulation_start_time_step=0, simulation_end_time_step=149, episode_time_steps=[[0, 99], [100, 149]],
        rolling_episode_split=False, random_episode_split=False,
    )
    env = CityLearnEnv(schema, central_agent=True)
    building = env.buildings[0]
    index = env.action_names[0].index('cooling_or_heating_device')

    def action(env):
        values = [0.0] * len(env.action_names[0])
        values[index] = 0.3
        return [values]

    env.reset()
    _run(env, action)
    data = building.energy_simulation
    modified = ~np.isclose(_full_series(data, 'heating_demand')[:100], _full_series(data, 'heating_demand_without_control')[:100])
    assert modified.any(), 'scenario must modify the first window'

    env.reset()  # shorter second episode in another window

    for name in ('heating_demand', 'cooling_demand', 'indoor_dry_bulb_temperature'):
        np.testing.assert_array_equal(_full_series(data, name), _full_series(data, f'{name}_without_control'))


class _NoInteraction:
    def predict(self, x):
        return [0]


def test_occupant_buildings_restore_simulated_series_between_episodes(monkeypatch):
    # The occupant models are pickles tied to old scikit-learn versions; this test is about the reset.
    original = utilities.FileHandler.read_pickle
    monkeypatch.setattr(
        utilities.FileHandler, 'read_pickle',
        staticmethod(lambda path, **kwargs: _NoInteraction() if str(path).endswith('.pkl') else original(path, **kwargs)),
    )
    env = CityLearnEnv('quebec_neighborhood_without_demand_response_set_points', central_agent=True, random_seed=0)
    env.reset()
    building = env.buildings[0]
    _run(env, lambda env: [[0.5] * env.action_space[0].shape[0]], steps=30)
    data = building.energy_simulation
    assert not np.array_equal(
        _full_series(data, 'indoor_dry_bulb_temperature'),
        _full_series(data, 'indoor_dry_bulb_temperature_without_control'),
    ), 'scenario must simulate dynamics'

    env.reset()  # moves to the next episode window

    for name in ('heating_demand', 'cooling_demand', 'indoor_dry_bulb_temperature'):
        np.testing.assert_array_equal(_full_series(data, name), _full_series(data, f'{name}_without_control'))
