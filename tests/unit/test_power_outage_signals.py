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


def test_v2_explicit_outage_seed_is_the_root_of_each_building_and_episode_stream():
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    model._set_episode_seed(23, 'Building_1', 720, 1439, random_stream_version='v2', random_stream_episode=0)
    first = model.get_signals(720, 3600.0)
    other_root = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=4)
    other_root._set_episode_seed(23, 'Building_1', 720, 1439, random_stream_version='v2', random_stream_episode=0)
    assert not np.array_equal(other_root.get_signals(720, 3600.0), first)
    # The environment seed (23) does not enter a seeded model's stream.
    model._set_episode_seed(99, 'Building_1', 720, 1439, random_stream_version='v2', random_stream_episode=0)
    np.testing.assert_array_equal(model.get_signals(720, 3600.0), first)
