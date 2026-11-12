import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.power_outage import ReliabilityMetricsPowerOutage


@pytest.mark.parametrize('time_steps', [1, 11, 24, 25, 49, 50, 721, 8760])
def test_signals_for_partial_days(time_steps):
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    signals = model.get_signals(time_steps, 3600.0)

    assert signals.shape == (time_steps,)
    assert set(np.unique(signals)) <= {0, 1}


def _signals_before_partial_day_fix(time_steps, seconds_per_time_step, saifi, caidi, random_seed):
    """Verbatim copy of the original algorithm, valid only for whole days."""

    nprs = np.random.RandomState(random_seed)
    time_steps_per_day = 86400.0/seconds_per_time_step
    time_steps_per_minute = 60.0/seconds_per_time_step
    day_count = time_steps/time_steps_per_day
    outage_days = nprs.binomial(n=1, p=saifi/365.0, size=int(day_count))
    outage_day_ixs = outage_days*np.arange(day_count)
    outage_day_ixs = outage_day_ixs[outage_day_ixs != 0]
    outage_day_count = outage_days[outage_days == 1].shape[0]
    starts = nprs.choice(list(range(int(time_steps_per_day))), size=outage_day_count)
    durations = nprs.exponential(scale=caidi, size=outage_day_count)*time_steps_per_minute
    signals = np.zeros(time_steps, dtype=int)

    for i, j, k in zip(outage_day_ixs, starts, durations):
        start_ix = i*time_steps_per_day + j
        signals[int(start_ix):int(start_ix + k)] = 1

    return signals


@pytest.mark.parametrize(('time_steps', 'seconds'), [(24*30, 3600.0), (96*7, 900.0), (24*365, 3600.0)])
def test_whole_day_signals_unchanged_by_partial_day_fix(time_steps, seconds):
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    np.testing.assert_array_equal(
        model.get_signals(time_steps, seconds),
        _signals_before_partial_day_fix(time_steps, seconds, 200.0, 120.0, 3),
    )


def test_environment_with_stochastic_outages_and_partial_day_episode_resets():
    env = CityLearnEnv(
        'citylearn_challenge_2023_phase_2_local_evaluation', central_agent=True,
        simulation_start_time_step=0, simulation_end_time_step=48,
    )
    assert any(b.stochastic_power_outage for b in env.buildings)
    observations, _ = env.reset()
    assert len(observations) == 1


@pytest.mark.parametrize('model_name', [None, 'ReliabilityMetricsPowerOutage'])
def test_unseeded_outages_are_reproducible_and_match_native_bau(model_name):
    root = Path(__file__).resolve().parents[2] / 'data/datasets/citylearn_challenge_2023_phase_1'
    schema = json.loads((root / 'schema.json').read_text())
    schema['root_directory'] = str(root)
    for building in schema['buildings'].values():
        outage = {'simulate_power_outage': True, 'stochastic_power_outage': True}
        if model_name is not None:
            outage['stochastic_power_outage_model'] = {
                'type': f'citylearn.power_outage.{model_name}',
                'attributes': {'saifi': 365.0, 'caidi': 240.0},
            }
        building['power_outage'] = outage

    env = CityLearnEnv(
        schema, buildings=[1, 0], central_agent=True, random_seed=7,
        simulation_start_time_step=0, simulation_end_time_step=143,
        episode_time_steps=72, offline=True, physics_invariant_checks=True,
    )
    reference = None
    global_state = np.random.get_state()
    try:
        # Change the process RNG and reset the same, nonzero episode with a
        # seed different from the constructor's. The sidecar starts at index 0.
        np.random.seed(1)
        env.reset(seed=23, options={'episode_index': 1})
        initial = [b.power_outage_signal.copy() for b in env.buildings]
        np.random.seed(12)
        observations, _ = env.reset(seed=23, options={'episode_index': 1})
        for expected, building in zip(initial, env.buildings):
            np.testing.assert_array_equal(building.power_outage_signal, expected)

        agent = BusinessAsUsualAgent(env)
        while not env.terminated:
            observations, *_ = env.step(agent.predict(observations, deterministic=True))

        reference = env.run_business_as_usual_baseline().env
        for actual, baseline in zip(env.buildings, reference.buildings):
            assert actual.name == baseline.name
            assert np.any(actual.power_outage_signal)
            np.testing.assert_array_equal(actual.power_outage_signal, baseline.power_outage_signal)

        kpis = env.evaluate_v2()
        ratio = kpis.loc[kpis.cost_function == 'district_energy_grid_ratio_to_business_as_usual_import_total_ratio', 'value']
        assert ratio.item() == pytest.approx(1.0)
    finally:
        np.random.set_state(global_state)
        if reference is not None:
            reference.close()
        env.close()


def test_explicit_outage_seed_takes_precedence_over_episode_seed():
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    expected = model.get_signals(720, 3600.0)
    model._set_episode_seed(23, 'Building_1', 720, 1439)
    assert model.random_seed == 3
    np.testing.assert_array_equal(model.get_signals(720, 3600.0), expected)
