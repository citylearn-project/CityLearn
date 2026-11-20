"""Physics version 2 corrections to battery discharge (tracking issue #226, theme 4).

#227: battery discharge was limited by the charging taper of `capacity_power_curve`.
#229: during an outage the battery discharged more than the islanded load, and the surplus was booked as PV
curtailment.

Each test reproduces its issue under physics version 1, which keeps the behaviour of CityLearn 3.6.0, and checks
the correction under version 2.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.community_dataset import InventoryBattery
from citylearn.energy_model import Battery

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'
TAPER = [[0.0, 1.0], [0.8, 1.0], [1.0, 0.25]]


def _tracker(steps: int = 10) -> EpisodeTracker:
    tracker = EpisodeTracker(0, steps - 1)
    tracker.next_episode(steps, False, False, 0)
    return tracker


def _battery(soc: float, legacy: bool, **kwargs) -> Battery:
    battery = Battery(capacity=10.0, nominal_power=5.0, initial_soc=soc, efficiency=1.0, loss_coefficient=0.0,
                      capacity_loss_coefficient=0.0, episode_tracker=_tracker(), seconds_per_time_step=3600,
                      random_seed=0, capacity_power_curve=TAPER, power_efficiency_curve=[[0, 1.0], [1, 1.0]],
                      **kwargs)
    battery.legacy_discharge_power_limit = legacy
    battery.reset()
    return battery


# --- #227 ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('soc, legacy_kwh', [(1.0, -1.25), (0.9, -3.125), (0.5, -5.0)])
def test_issue_227_discharge_is_not_limited_by_the_charging_taper(soc, legacy_kwh):
    legacy = _battery(soc, legacy=True)
    corrected = _battery(soc, legacy=False)
    # Charging still follows the taper.
    assert corrected.get_max_input_power() == pytest.approx(legacy.get_max_input_power())

    legacy.charge(-5.0)
    corrected.charge(-5.0)

    assert float(legacy.energy_balance[0]) == pytest.approx(legacy_kwh)
    assert float(corrected.energy_balance[0]) == pytest.approx(-5.0)


def test_issue_227_discharge_power_curve_can_derate_at_low_soc():
    battery = _battery(0.1, legacy=False, discharge_power_curve=[[0.0, 0.2], [0.2, 1.0], [1.0, 1.0]])

    assert battery.get_max_output_power() == pytest.approx(5.0 * 0.6)
    assert battery.get_metadata()['discharge_power_curve'].tolist() == [[0.0, 0.2, 1.0], [0.2, 1.0, 1.0]]


def test_issue_227_inventory_battery_keeps_its_declared_discharge_limit():
    kwargs = dict(max_charge_kw=4.0, max_discharge_kw=3.0, capacity=10.0, initial_soc=1.0, capacity_power_curve=TAPER,
                  episode_tracker=_tracker(), seconds_per_time_step=3600, random_seed=0)
    legacy = InventoryBattery(**kwargs)
    legacy.legacy_discharge_power_limit = True
    legacy.reset()
    corrected = InventoryBattery(**kwargs)
    corrected.reset()

    assert legacy.get_max_output_power() == pytest.approx(4.0 * 0.25)
    assert corrected.get_max_output_power() == pytest.approx(3.0)


@pytest.mark.parametrize('physics_version', [1, 2])
def test_issue_227_environment_sets_the_discharge_limit_from_the_physics_version(physics_version):
    schema = json.loads((DATASETS / 'citylearn_challenge_2022_phase_all_plus_evs' / 'schema.json').read_text())
    schema['root_directory'] = str(DATASETS / 'citylearn_challenge_2022_phase_all_plus_evs')
    env = CityLearnEnv(schema, episode_time_steps=2, simulation_end_time_step=1, physics_version=physics_version)
    batteries = [building.electrical_storage for building in env.buildings]
    batteries += [ev.battery for ev in env.electric_vehicles]

    assert batteries
    assert all(battery.legacy_discharge_power_limit == (physics_version == 1) for battery in batteries)


# --- #229 ---------------------------------------------------------------------------------------------

def _outage_env(tmp_path: Path, physics_version: int) -> CityLearnEnv:
    """`citylearn_challenge_2021` at 900 s with an outage window, as in the issue's repro (hourly rows, compressed)."""

    source = DATASETS / 'citylearn_challenge_2021'
    dataset = tmp_path / f'outage_v{physics_version}'
    shutil.copytree(source, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    start = 4000

    for index, (name, building) in enumerate(schema['buildings'].items()):
        building['include'] = index < 3
        if index >= 3:
            continue
        frame = pd.read_csv(dataset / building['energy_simulation'])
        outage = np.zeros(len(frame), dtype=int)
        outage[start + 8:start + 40] = 1
        frame['power_outage'] = outage
        frame.to_csv(dataset / building['energy_simulation'], index=False)
        building['power_outage'] = {'simulate_power_outage': True}
        # Full storage, so the battery and the thermal storage can discharge during the outage.
        for storage in ('electrical_storage', 'cooling_storage', 'dhw_storage'):
            if building.get(storage):
                building[storage]['attributes']['initial_soc'] = 1.0

    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), central_agent=True, seconds_per_time_step=900, simulation_start_time_step=start,
                        simulation_end_time_step=start + 47, episode_time_steps=48, random_seed=0,
                        physics_version=physics_version, physics_invariant_checks=physics_version >= 2,
                        time_step_ratio_mode='compress')


def _run_outage(env: CityLearnEnv) -> list:
    env.reset()
    names = env.action_names[0]
    actions = np.zeros(len(names), dtype='float32')
    for index, name in enumerate(names):
        # Discharge every storage, so the thermal storage covers part of the thermal demand during the outage.
        if name.endswith('_storage'):
            actions[index] = -1.0
    rows = []

    while not env.terminated:
        t = env.time_step
        env.step([actions.tolist()])
        for building in env.buildings:
            if not building.power_outage_signal[t]:
                continue
            pv = max(-float(building.solar_generation[t]), 0.0)
            discharge = max(-float(building.electrical_storage.electricity_consumption[t]), 0.0)
            loads = sum(float(getattr(building, f'{name}_electricity_consumption')[t]) for name in (
                'cooling', 'heating', 'dhw', 'non_shiftable_load'))
            rows.append(dict(building=building.name, t=t, pv=pv, discharge=discharge, loads=loads,
                             curtailment=float(building.pv_curtailment[t])))

    return rows


def test_issue_229_physics_version_1_books_battery_surplus_as_pv_curtailment(tmp_path):
    rows = _run_outage(_outage_env(tmp_path, physics_version=1))

    assert rows
    surplus = [row for row in rows if row['curtailment'] > row['pv'] + 1.0e-3]
    assert surplus, 'the 3.6.0 repro no longer books battery surplus as PV curtailment'


def test_issue_229_outage_discharge_serves_only_the_load_that_pv_leaves(tmp_path):
    # `physics_invariant_checks` also asserts this at every step.
    rows = _run_outage(_outage_env(tmp_path, physics_version=2))

    assert rows
    assert any(row['discharge'] > 0.0 for row in rows)
    for row in rows:
        assert row['discharge'] <= max(row['loads'] - row['pv'], 0.0) + 1.0e-4, row
        assert row['curtailment'] <= row['pv'] + 1.0e-4, row
