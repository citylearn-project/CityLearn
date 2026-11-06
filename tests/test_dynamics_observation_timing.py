"""Indoor temperature observation timing for LSTM dynamics buildings (CityLearn #165).

The LSTM prediction for the controlled interval is written at ``time_step``; the
agent's observation is assembled after the clock advances. These tests pin that
the observation returned by ``step()`` is the latest simulated temperature (so it
responds to the HVAC action), while the simulated trajectory itself, which the
reward and KPIs read, does not depend on the placeholder held for the next step.
"""

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'
OBSERVATION = 'indoor_dry_bulb_temperature'
STEPS = 40


def _actions(env, level):
    return [[
        level if name == 'cooling_device' else (-level if name == 'cooling_or_heating_device' else 0.0)
        for name in building.active_actions
    ] for building in env.buildings]


def _run(level, restore_dataset_placeholder=False):
    env = CityLearnEnv(DATASET, central_agent=False, random_seed=0)
    env.reset()
    observed, simulated = [], []

    for _ in range(STEPS):
        observations = env.step(_actions(env, level))[0]

        for building, values in zip(env.buildings, observations):
            if not building.simulate_dynamics or OBSERVATION not in building.active_observations:
                continue

            t = building.time_step
            series = building.energy_simulation.indoor_dry_bulb_temperature
            observed.append(values[list(building.active_observations).index(OBSERVATION)])
            simulated.append(series[t - 1])

            if restore_dataset_placeholder:
                # Pre-#165 state of the next slot: the uncontrolled dataset value.
                series[t] = building.energy_simulation.indoor_dry_bulb_temperature_without_control[t]

    trajectories = [b.energy_simulation.indoor_dry_bulb_temperature[:b.time_step].copy() for b in env.buildings]
    return np.asarray(observed), np.asarray(simulated), trajectories


def test_observation_is_latest_simulated_temperature_and_responds_to_action():
    idle_observed, idle_simulated, _ = _run(0.0)
    full_observed, full_simulated, _ = _run(1.0)

    assert idle_observed.size > 0
    np.testing.assert_allclose(idle_observed, idle_simulated, rtol=0.0, atol=1.0e-5)
    np.testing.assert_allclose(full_observed, full_simulated, rtol=0.0, atol=1.0e-5)
    # Full cooling must be visible to the agent, not only to the reward/KPIs.
    assert np.mean(full_observed) < np.mean(idle_observed) - 1.0


def test_simulated_trajectory_does_not_read_next_step_placeholder():
    _, _, held = _run(1.0)
    _, _, restored = _run(1.0, restore_dataset_placeholder=True)

    for held_series, restored_series in zip(held, restored):
        np.testing.assert_array_equal(held_series, restored_series)


class _NoInteraction:
    def predict(self, x):
        return [0]


def _quebec_temperatures(monkeypatch, steps=30):
    import citylearn.utilities as utilities

    original = utilities.FileHandler.read_pickle
    monkeypatch.setattr(
        utilities.FileHandler, 'read_pickle',
        staticmethod(lambda path, **kwargs: _NoInteraction() if str(path).endswith('.pkl') else original(path, **kwargs)),
    )
    env = CityLearnEnv('quebec_neighborhood_without_demand_response_set_points', central_agent=True, random_seed=0)
    env.reset()

    for _ in range(steps):
        env.step([[0.5] * env.action_space[0].shape[0]])

    assert all(not b.dynamics.training for b in env.buildings), 'dynamics must run in inference mode'
    return np.concatenate([b.energy_simulation.indoor_dry_bulb_temperature[:b.time_step].copy() for b in env.buildings])


def test_lstm_dynamics_with_dropout_are_deterministic(monkeypatch):
    # Quebec dynamics models are configured with dropout 0.1-0.5, which must not act during simulation.
    np.testing.assert_array_equal(_quebec_temperatures(monkeypatch), _quebec_temperatures(monkeypatch))
