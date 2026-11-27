"""Occupant set points stay within a plausible range (CityLearn #352).

`LogisticRegressionOccupantInteractionBuilding.update_set_points` adds each occupant change to the
current set point. Under arbitrary HVAC control the occupant keeps interacting, and the heating set
point of the Quebec neighbourhood random-walked to about -1342 C over one episode. Occupant changes now
stay within `set_point_limits`; physics version 1, which kept the unbounded behaviour of CityLearn 3.6.0,
was removed in CityLearn 3.8.1 (#466).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.building import LogisticRegressionOccupantInteractionBuilding
from citylearn.citylearn import CityLearnEnv

DATASET = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'quebec_neighborhood_with_demand_response_set_points'
STEPS = 24
DELTA = -1.5


def _schema(**building_options) -> dict:
    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)

    for index, building in enumerate(schema['buildings'].values()):
        building['include'] = index == 0
        building.update(building_options)

    return schema


def _env(**building_options) -> CityLearnEnv:
    return CityLearnEnv(_schema(**building_options), central_agent=True, episode_time_steps=STEPS, random_seed=0)


def _run_with_constant_occupant(env: CityLearnEnv, delta: float = DELTA) -> np.ndarray:
    """Run an episode where the occupant lowers (or raises) the active set point at every step."""

    env.reset()
    building = env.buildings[0]
    building.occupant.predict = lambda x: delta
    actions = [np.zeros(space.shape, dtype='float32') for space in env.action_space]

    while not env.terminated:
        env.step(actions)

    simulation = building.energy_simulation
    assert (simulation.hvac_mode[1:env.time_step + 1] == 2).all(), 'test window must be in heating mode'

    return np.asarray(simulation.indoor_dry_bulb_temperature_heating_set_point[:env.time_step + 1], dtype='float64')


def test_v2_occupant_heating_set_point_stops_at_the_lower_limit():
    env = _env()

    try:
        set_points = _run_with_constant_occupant(env)
        low, high = env.buildings[0].set_point_limits
        assert (low, high) == LogisticRegressionOccupantInteractionBuilding.DEFAULT_OCCUPANT_SET_POINT_LIMITS
        # Unbounded, the 11 steps of -1.5 C after the LSTM lookback would take it to about 3 C.
        assert set_points.min() == pytest.approx(low)
        assert (set_points >= low).all()
        assert env.observation_space[0].contains(np.asarray(env.observations[0], dtype='float32'))
    finally:
        env.close()


def test_v2_occupant_heating_set_point_stops_at_the_upper_limit():
    env = _env(set_point_limits=[16.0, 24.0])

    try:
        set_points = _run_with_constant_occupant(env, delta=1.5)
        assert env.buildings[0].set_point_limits == (16.0, 24.0)
        assert set_points.max() == pytest.approx(24.0)
    finally:
        env.close()


def test_v2_set_point_observation_bounds_are_the_limits():
    env = _env()

    try:
        building = env.buildings[0]
        low, high = building.set_point_limits
        space_low, space_high = building.estimate_observation_space_limits(include_all=True)

        for name in ('indoor_dry_bulb_temperature_heating_set_point', 'indoor_dry_bulb_temperature_cooling_set_point'):
            schedule = getattr(building.energy_simulation, f'{name}_without_control')
            # The schedule (18.5 to 21.6 C) is inside the default range, so the bounds are the limits.
            assert space_low[name] == pytest.approx(min(low, float(np.min(schedule))))
            assert space_high[name] == pytest.approx(max(high, float(np.max(schedule))))
            assert (space_low[name], space_high[name]) == pytest.approx((low, high))

        name = 'indoor_dry_bulb_temperature_heating_set_point'
        index = building.flat_observation_order.index(name)
        assert (building.observation_space.low[index], building.observation_space.high[index]) == pytest.approx((low, high))
    finally:
        env.close()


def test_a_schedule_outside_the_limits_is_not_moved_into_them():
    env = _env(set_point_limits=[22.0, 30.0])

    try:
        # The schedule (18.5 to 21.6 C) is below the range: a decrease is stopped where it starts,
        # and the schedule itself is not pulled up to 22 C.
        set_points = _run_with_constant_occupant(env)
        schedule = env.buildings[0].energy_simulation.indoor_dry_bulb_temperature_heating_set_point_without_control
        assert set_points[0] == pytest.approx(float(schedule[0]))
        assert (set_points < 22.0).all()
        assert (np.diff(set_points[1:]) >= -1.0e-6).all()
    finally:
        env.close()


@pytest.mark.parametrize('value', [[30.0, 15.0], [15.0], 'warm', [15.0, float('inf')]])
def test_invalid_set_point_limits_are_rejected(value):
    with pytest.raises(ValueError, match='set_point_limits'):
        _env(set_point_limits=value)


def test_business_as_usual_set_point_observation_stays_in_the_space():
    """Under the BAU agent the occupant took the Quebec heating set point to about 139 C within
    96 steps, far above its observation bound (CityLearn #357, set-point part)."""

    from citylearn.agents.baseline import BusinessAsUsualAgent

    schema = _schema()
    env = CityLearnEnv(schema, interface='flat', central_agent=True, episode_time_steps=96, random_seed=0)

    try:
        observations, _ = env.reset()
        agent = BusinessAsUsualAgent(env)
        space = env.observation_space[0]
        index = env.observation_names[0].index('indoor_dry_bulb_temperature_heating_set_point')
        values = []

        while not env.terminated:
            observations, *_ = env.step(agent.predict(observations))
            values.append(float(observations[0][index]))

        values = np.asarray(values)
        assert (values >= space.low[index]).all() and (values <= space.high[index]).all(), (values.min(), values.max())
    finally:
        env.close()
