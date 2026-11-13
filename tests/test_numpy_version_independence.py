"""Simulation results do not depend on the installed NumPy version.

NumPy 2 (NEP 50) evaluates ``float32_scalar <op> python_number`` in float32 where NumPy 1 used
float64, and compares such operands in float32. Unhandled, that shifts every result by float32
rounding from the first step on. The reference below was recorded with NumPy 1.26; CI runs this
test under NumPy 1.x and 2.x.

Regenerate (NumPy 1.x only, after a reviewed change of results):
``python tests/test_numpy_version_independence.py --write``.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(__file__).resolve().parent/'data'/'numpy_version_reference.json'
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


def _rollout(name: str) -> dict:
    env = CityLearnEnv(str(ROOT/'data'/'datasets'/name/'schema.json'), central_agent=True,
                       episode_time_steps=STEPS + 1, random_seed=0)
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


@pytest.mark.parametrize('name', DATASETS)
def test_rollout_matches_numpy1_reference(name):
    expected = json.loads(REFERENCE.read_text(encoding='utf-8'))[name]
    actual = _rollout(name)

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
    REFERENCE.write_text(json.dumps({name: _rollout(name) for name in DATASETS}, indent=1) + '\n', encoding='utf-8')
    print(f'wrote {REFERENCE}')
