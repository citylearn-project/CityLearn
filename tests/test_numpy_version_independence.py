"""Simulation results do not depend on the installed NumPy version.

NumPy 2 (NEP 50) evaluates ``float32_scalar <op> python_number`` in float32 where NumPy 1 used
float64, and compares such operands in float32. Unhandled, that shifts every result by float32
rounding from the first step on. One reference per physics version was recorded with NumPy 1.26;
CI runs this test under NumPy 1.x and 2.x, so both NumPy versions must reproduce each reference.

Version 1 is the physics and random streams of CityLearn 3.6.0, and its reference stays frozen.
Regenerate the reference of version 2 (NumPy 1.x only, after a reviewed change of results):
``python tests/test_numpy_version_independence.py --write --physics-version 2``.
"""

import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    1: Path(__file__).resolve().parent/'data'/'numpy_version_reference.json',
    2: Path(__file__).resolve().parent/'data'/'numpy_version_reference_physics_v2.json',
}
# Version 1 keeps the 3.6.0 random streams of its reference; version 2 uses the 'v2' streams (SeedSequence and
# PCG64), whose output NumPy keeps identical across versions.
RANDOM_STREAMS = {1: 'v1', 2: 'v2'}
# The frozen 3.6.0 reference also records the 3.6.0 rewards, which reward version 1 keeps (#278). Both datasets use
# Electric_Vehicles_Reward_Function, whose schema attributes hold only the version.
REWARD_VERSIONS = {1: 1, 2: 2}
# The frozen 3.6.0 reference also records the 3.6.0 baseline ratios, which baseline version 1 keeps (#365).
BASELINE_VERSIONS = {1: 1, 2: 2}
STEPS = 48
# Far above cross-platform rounding noise, far below the float32 drift NumPy 2 introduced.
RTOL = 1.0e-9
DATASETS = ['citylearn_challenge_2022_phase_all_plus_evs', 'citylearn_three_phase_electrical_service_demo']
KPIS = [
    'district_cost_ratio_to_baseline_total_ratio',
    'district_emissions_ratio_to_baseline_total_ratio',
    'district_energy_grid_ratio_to_baseline_import_total_ratio',
    'district_energy_grid_import_control_total_kwh',
    'district_cost_total_control_eur',
]


def _action(t: int, j: int, low: float, high: float) -> float:
    value = 0.8*math.sin(0.7*t + 1.3*j)
    return min(max(value, float(low)), float(high))


def _rollout(name: str, physics_version: int) -> dict:
    with warnings.catch_warnings():
        # Reward version 1 is deprecated; the frozen reference still needs it.
        warnings.simplefilter('ignore', DeprecationWarning)
        env = CityLearnEnv(str(ROOT/'data'/'datasets'/name/'schema.json'), central_agent=True,
                           episode_time_steps=STEPS + 1, random_seed=0, physics_version=physics_version,
                           random_stream_version=RANDOM_STREAMS[physics_version],
                           baseline_version=BASELINE_VERSIONS[physics_version],
                           reward_function_kwargs={'version': REWARD_VERSIONS[physics_version]})
    env.reset(seed=0)
    rewards = []
    t = 0

    while not env.terminated:
        if env.interface == 'entity':
            action = {'tables': {
                table: np.array([_action(t, j, lo, hi) for j, (lo, hi) in enumerate(zip(box.low.ravel(), box.high.ravel()))],
                                dtype='float32').reshape(box.shape)
                for table, box in env.action_space['tables'].spaces.items()
            }}
        else:
            action = [[_action(t, j, lo, hi) for j, (lo, hi) in enumerate(zip(box.low, box.high))] for box in env.action_space]

        _, reward, *_ = env.step(action)
        rewards.append([float(r) for r in np.asarray(reward, dtype='float64').ravel()])
        t += 1

    kpis = env.evaluate_v2(include_business_as_usual=False)
    district = kpis[kpis['name'] == 'District'].set_index('cost_function')['value']
    return {
        'rewards': rewards,
        'district_net_electricity_consumption': [float(v) for v in env.net_electricity_consumption[:env.time_step]],
        'building_net_electricity_consumption': {
            b.name: [float(v) for v in b.net_electricity_consumption[:env.time_step]] for b in env.buildings[:4]
        },
        'battery_soc': {b.name: [float(v) for v in b.electrical_storage.soc[:env.time_step]] for b in env.buildings[:4]},
        'kpis': {k: float(district[k]) for k in KPIS if k in district.index},
    }


@pytest.mark.parametrize('physics_version', sorted(REFERENCES))
@pytest.mark.parametrize('name', DATASETS)
def test_rollout_matches_numpy1_reference(name, physics_version):
    expected = json.loads(REFERENCES[physics_version].read_text(encoding='utf-8'))[name]
    actual = _rollout(name, physics_version)

    np.testing.assert_allclose(np.asarray(actual['rewards']), np.asarray(expected['rewards']), rtol=RTOL, atol=0.0)
    np.testing.assert_allclose(actual['district_net_electricity_consumption'],
                               expected['district_net_electricity_consumption'], rtol=RTOL, atol=1.0e-12)

    for key in ('building_net_electricity_consumption', 'battery_soc'):
        assert actual[key].keys() == expected[key].keys()
        for building, values in expected[key].items():
            np.testing.assert_allclose(actual[key][building], values, rtol=RTOL, atol=1.0e-12, err_msg=f'{key} {building}')

    assert actual['kpis'].keys() == expected['kpis'].keys()
    for kpi, value in expected['kpis'].items():
        assert actual['kpis'][kpi] == pytest.approx(value, rel=RTOL, abs=1.0e-12), kpi


if __name__ == '__main__' and '--write' in sys.argv:
    if int(np.__version__.split('.')[0]) != 1:
        raise SystemExit('The reference must be recorded with NumPy 1.x.')
    if '--physics-version' not in sys.argv:
        raise SystemExit('Give the physics version whose reference to write: --physics-version 2.')
    version = int(sys.argv[sys.argv.index('--physics-version') + 1])
    if version == 1:
        raise SystemExit('The physics version 1 reference is frozen: it is the physics of CityLearn 3.6.0.')
    reference = REFERENCES[version]
    reference.write_text(json.dumps({name: _rollout(name, version) for name in DATASETS}, indent=1) + '\n',
                         encoding='utf-8')
    print(f'wrote {reference}')
