"""Tests for per-outage-event service resilience metrics (#219)."""

from __future__ import annotations

from copy import deepcopy
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.outage_resilience import EVENT_COLUMNS, SUMMARY_COLUMNS
from citylearn.internal.service_energy import unserved_energy

ROOT = Path(__file__).resolve().parents[1]
MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
CHALLENGE_2023 = ROOT / 'data' / 'datasets' / 'citylearn_challenge_2023_phase_2_local_evaluation' / 'schema.json'


def _build_minute_outage_env(
    tmp_path: Path,
    *,
    seconds_per_time_step: int = 900,
    steps: int = 8,
    simulate_power_outage: bool = True,
    outage_steps_b1: tuple[int, ...] = (),
    outage_steps_b2: tuple[int, ...] | None = None,
    loads_b1: dict[str, list[float] | float] | None = None,
    loads_b2: dict[str, list[float] | float] | None = None,
    solar_b1: list[float] | float = 0.0,
    solar_b2: list[float] | float = 0.0,
) -> CityLearnEnv:
    dataset = tmp_path / 'outage_demo'
    shutil.copytree(MINUTE_DATASET, dataset)

    def _write_building_csv(filename: str, outage_steps: tuple[int, ...], loads: dict | None, solar):
        frame = pd.read_csv(dataset / 'Building_1.csv').iloc[: max(steps + 2, 10)].copy()
        outage = np.zeros(len(frame), dtype=int)
        for idx in outage_steps:
            if 0 <= idx < len(outage):
                outage[idx] = 1
        frame['power_outage'] = outage
        frame['solar_generation'] = 0.0
        if isinstance(solar, (int, float)):
            frame.loc[: steps - 1, 'solar_generation'] = float(solar)
        else:
            frame.loc[: len(solar) - 1, 'solar_generation'] = list(solar)

        defaults = {
            'non_shiftable_load': 1.0,
            'cooling_demand': 0.0,
            'heating_demand': 0.0,
            'dhw_demand': 0.0,
        }
        if loads:
            defaults.update(loads)
        for col, val in defaults.items():
            frame[col] = 0.0
            if isinstance(val, (int, float)):
                frame.loc[: steps - 1, col] = float(val)
            else:
                frame.loc[: len(val) - 1, col] = list(val)
        frame.to_csv(dataset / filename, index=False)

    _write_building_csv('Building_1.csv', outage_steps_b1, loads_b1, solar_b1)

    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    schema['seconds_per_time_step'] = seconds_per_time_step
    schema['simulation_start_time_step'] = 0
    schema['simulation_end_time_step'] = steps - 1

    def _configure_building(b_cfg: dict, filename: str):
        b_cfg['energy_simulation'] = filename
        b_cfg['power_outage'] = {'simulate_power_outage': simulate_power_outage}
        b_cfg['electrical_storage']['attributes']['initial_soc'] = 0.0
        b_cfg['pv'] = {
            'type': 'citylearn.energy_model.PV',
            'autosize': False,
            'attributes': {'generation_mode': 'absolute', 'nominal_power': 50.0},
        }
        b_cfg['cooling_device'] = {
            'type': 'citylearn.energy_model.HeatPump',
            'autosize': False,
            'attributes': {'nominal_power': 50.0, 'efficiency': 0.3, 'target_cooling_temperature': 8.0},
        }
        b_cfg['dhw_device'] = {
            'type': 'citylearn.energy_model.ElectricHeater',
            'autosize': False,
            'attributes': {'nominal_power': 50.0, 'efficiency': 0.9},
        }

    _configure_building(schema['buildings']['Building_1'], 'Building_1.csv')
    if outage_steps_b2 is not None:
        _write_building_csv('Building_2.csv', outage_steps_b2, loads_b2, solar_b2)
        b2 = deepcopy(schema['buildings']['Building_1'])
        b2['chargers'] = {}
        _configure_building(b2, 'Building_2.csv')
        schema['buildings']['Building_2'] = b2

    # The demo rows are 900 s; other steps reuse them as rows of that step (tests then set time_step_ratio).
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=steps, random_seed=0, offline=True,
                       time_step_ratio_mode=None if seconds_per_time_step == 900 else 'compress')
    env.reset(seed=0)
    return env


def _step_zeros(env: CityLearnEnv, count: int | None = None):
    steps = 0
    while not env.terminated and (count is None or steps < count):
        zeros = [np.zeros(len(names), dtype='float32').tolist() for names in env.action_names]
        env.step(zeros)
        steps += 1


def test_no_outages_returns_empty_events_and_null_ratios(tmp_path):
    # Even if CSV rows contain outage flags, simulate_power_outage=False disables outages;
    # and with simulate_power_outage=True and zero outage steps, both yield 0 events.
    for simulate_flag, outage_steps in ((False, (1, 2)), (True, ())):
        env = _build_minute_outage_env(
            tmp_path / str(simulate_flag),
            steps=6,
            simulate_power_outage=simulate_flag,
            outage_steps_b1=outage_steps,
        )
        try:
            # Before any step is executed, executed_time_steps == 0 -> 0 events.
            pre_audit = env.get_outage_resilience_audit()
            assert pre_audit['executed_time_steps'] == 0
            assert pre_audit['events'] == []

            _step_zeros(env)
            audit = env.get_outage_resilience_audit()
            events_df, summary_df = env.evaluate_outage_events()

            assert list(events_df.columns) == list(EVENT_COLUMNS)
            assert list(summary_df.columns) == list(SUMMARY_COLUMNS)
            assert events_df.empty
            assert audit['events'] == []
            assert audit['coincident_events'] == []

            for target in (audit['buildings']['Building_1'], audit['district']):
                assert target['events_count'] == 0
                assert target['fully_served_events_count'] == 0
                assert target['fully_served_events_ratio'] is None
                assert target['outage_steps_count'] == 0
                assert target['outage_hours'] == 0.0
                assert target['expected_energy_kwh'] == 0.0
                assert target['served_energy_kwh'] == 0.0
                assert target['unserved_energy_kwh'] == 0.0
                assert target['unserved_energy_ratio'] is None
                assert target['worst_event_unserved_energy_kwh'] == 0.0
                assert target['peak_unserved_power_kw'] == 0.0
        finally:
            env.close()


def test_single_multistep_outage_boundaries_energy_and_end_use_split(tmp_path):
    # 8 steps at 900 s (0.25 h each); contiguous outage on steps 2, 3, 4 (3 steps = 0.75 h).
    # Zero local supply -> all demand during steps 2..4 is unserved.
    env = _build_minute_outage_env(
        tmp_path,
        seconds_per_time_step=900,
        steps=8,
        outage_steps_b1=(2, 3, 4),
        loads_b1={
            'non_shiftable_load': [0.5, 0.5, 1.0, 2.0, 0.5, 0.5, 0.5, 0.5],
            'cooling_demand': [0.0, 0.0, 0.6, 0.4, 0.2, 0.0, 0.0, 0.0],
            'dhw_demand': [0.0, 0.0, 0.1, 0.3, 0.0, 0.0, 0.0, 0.0],
            'heating_demand': 0.0,
        },
        solar_b1=0.0,
    )
    try:
        _step_zeros(env)
        audit = env.get_outage_resilience_audit()
        events_df, summary_df = env.evaluate_outage_events()

        assert len(events_df) == 1
        ev = events_df.iloc[0]
        assert ev['building'] == 'Building_1'
        assert ev['event_index'] == 0
        assert ev['start_time_step'] == 2
        assert ev['end_time_step'] == 4
        assert ev['duration_steps'] == 3
        assert ev['duration_hours'] == pytest.approx(0.75)

        # Step totals during steps 2, 3, 4:
        # step 2: 1.0 + 0.6 + 0.1 = 1.7 kWh
        # step 3: 2.0 + 0.4 + 0.3 = 2.7 kWh  (max step -> 2.7 / 0.25 = 10.8 kW)
        # step 4: 0.5 + 0.2 + 0.0 = 0.7 kWh
        assert ev['non_shiftable_expected_energy_kwh'] == pytest.approx(3.5)
        assert ev['non_shiftable_unserved_energy_kwh'] == pytest.approx(3.5)
        assert ev['cooling_expected_energy_kwh'] == pytest.approx(1.2)
        assert ev['cooling_unserved_energy_kwh'] == pytest.approx(1.2)
        assert ev['dhw_expected_energy_kwh'] == pytest.approx(0.4)
        assert ev['dhw_unserved_energy_kwh'] == pytest.approx(0.4)
        assert ev['heating_expected_energy_kwh'] == pytest.approx(0.0)
        assert ev['heating_unserved_energy_kwh'] == pytest.approx(0.0)
        assert ev['expected_energy_kwh'] == pytest.approx(5.1)
        assert ev['served_energy_kwh'] == pytest.approx(0.0)
        assert ev['unserved_energy_kwh'] == pytest.approx(5.1)
        assert ev['unserved_energy_ratio'] == pytest.approx(1.0)
        assert ev['peak_unserved_power_kw'] == pytest.approx(2.7 / 0.25)
        assert bool(ev['fully_served']) is False

        b_row = summary_df[summary_df['name'] == 'Building_1'].iloc[0]
        assert b_row['events_count'] == 1
        assert b_row['outage_hours'] == pytest.approx(0.75)
        assert b_row['worst_event_unserved_energy_kwh'] == pytest.approx(5.1)
        assert b_row['fully_served_events_ratio'] == pytest.approx(0.0)
        assert audit['district']['coincident_events_count'] == 1
    finally:
        env.close()


def test_two_separated_outages_and_coincident_district_aggregation(tmp_path):
    # Building_1 has two outages: steps (1, 2) fully covered by PV, and steps (5, 6) unserved.
    # Building_2 has one outage at step 5 (simultaneous with Building_1 at step 5!).
    env = _build_minute_outage_env(
        tmp_path,
        seconds_per_time_step=900,
        steps=8,
        outage_steps_b1=(1, 2, 5, 6),
        outage_steps_b2=(5,),
        loads_b1={'non_shiftable_load': [0.5, 1.0, 1.0, 0.5, 0.5, 1.5, 0.5, 0.5]},
        loads_b2={'non_shiftable_load': [0.5, 0.5, 0.5, 0.5, 0.5, 2.0, 0.5, 0.5]},
        solar_b1=[0.0, 1.5, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0],
        solar_b2=0.0,
    )
    try:
        _step_zeros(env)
        audit = env.get_outage_resilience_audit()
        events_df, summary_df = env.evaluate_outage_events()

        b1_events = events_df[events_df['building'] == 'Building_1'].reset_index(drop=True)
        assert len(b1_events) == 2
        assert list(b1_events['start_time_step']) == [1, 5]
        assert list(b1_events['end_time_step']) == [2, 6]
        assert bool(b1_events.loc[0, 'fully_served']) is True
        assert b1_events.loc[0, 'unserved_energy_kwh'] == pytest.approx(0.0, abs=1e-7)
        assert bool(b1_events.loc[1, 'fully_served']) is False
        assert b1_events.loc[1, 'unserved_energy_kwh'] == pytest.approx(2.0)

        b1_summary = audit['buildings']['Building_1']
        assert b1_summary['events_count'] == 2
        assert b1_summary['fully_served_events_count'] == 1
        assert b1_summary['fully_served_events_ratio'] == pytest.approx(0.5)
        assert b1_summary['outage_hours'] == pytest.approx(1.0)
        assert b1_summary['worst_event_unserved_energy_kwh'] == pytest.approx(2.0)
        assert b1_summary['peak_unserved_power_kw'] == pytest.approx(1.5 / 0.25)

        # District: 3 member-events (2 on Building_1 + 1 on Building_2), 2 coincident community windows
        # ((1..2) hitting 1 building and (5..6) hitting both buildings at step 5 with 1.5 + 2.0 = 3.5 kWh = 14 kW).
        district = audit['district']
        assert district['events_count'] == 3
        assert district['fully_served_events_count'] == 1
        assert district['fully_served_events_ratio'] == pytest.approx(1.0 / 3.0)
        assert district['coincident_events_count'] == 2
        assert district['coincident_outage_hours'] == pytest.approx(1.0)
        assert district['worst_event_unserved_energy_kwh'] == pytest.approx(2.0)
        assert district['worst_coincident_event_unserved_energy_kwh'] == pytest.approx(4.0)
        assert district['max_building_peak_unserved_power_kw'] == pytest.approx(2.0 / 0.25)
        assert district['peak_unserved_power_kw'] == pytest.approx(3.5 / 0.25)
        assert audit['coincident_events'][1]['max_simultaneous_buildings_count'] == 2
        assert audit['coincident_events'][1]['affected_buildings'] == ['Building_1', 'Building_2']
    finally:
        env.close()


@pytest.mark.parametrize('seconds_per_time_step, expected_hours, expected_peak_kw', [
    (3600, 2.0, 1.5),
    (900, 0.5, 6.0),
])
def test_step_duration_converts_hours_and_peak_unserved_kw(
    tmp_path, seconds_per_time_step, expected_hours, expected_peak_kw
):
    # Native dataset energy per row is 1.5 kWh at step 1 and 0.5 kWh at step 2 (dataset matches seconds_per_time_step).
    env = _build_minute_outage_env(
        tmp_path / f's_{seconds_per_time_step}',
        seconds_per_time_step=seconds_per_time_step,
        steps=4,
        outage_steps_b1=(1, 2),
        loads_b1={'non_shiftable_load': [0.5, 1.5, 0.5, 0.5]},
    )
    try:
        # Ensure building time_step_ratio is 1.0 so each row represents 1.5 kWh and 0.5 kWh in control-step energy.
        env.time_step_ratio = 1.0
        _step_zeros(env)
        events_df, _ = env.evaluate_outage_events()
        assert len(events_df) == 1
        ev = events_df.iloc[0]
        assert ev['duration_hours'] == pytest.approx(expected_hours)
        assert ev['unserved_energy_kwh'] == pytest.approx(2.0)
        assert ev['peak_unserved_power_kw'] == pytest.approx(expected_peak_kw)
    finally:
        env.close()


def test_event_totals_match_existing_outage_kpi_and_leave_evaluate_v2_unchanged():
    schema = json.loads(CHALLENGE_2023.read_text(encoding='utf-8'))
    schema['root_directory'] = str(CHALLENGE_2023.parent)
    schema['central_agent'] = True
    for building in schema['buildings'].values():
        building['power_outage'] = {
            'simulate_power_outage': True,
            'stochastic_power_outage': True,
            'stochastic_power_outage_model': {
                'type': 'citylearn.power_outage.PowerOutage',
                'attributes': {'random_seed': 7},
            },
        }

    env = CityLearnEnv(
        schema,
        central_agent=True,
        simulation_start_time_step=0,
        simulation_end_time_step=47,
        random_seed=0,
        offline=True,
    )
    try:
        env.reset(seed=0)
        while not env.terminated:
            actions = [
                [float(low) if 'storage' in name else float((low + high) / 2.0)
                 for name, low, high in zip(names, space.low, space.high)]
                for names, space in zip(env.action_names, env.action_space)
            ]
            env.step(actions)

        kpis_before = env.evaluate_v2(include_business_as_usual=False)
        audit = env.get_outage_resilience_audit()
        events_df, summary_df = env.evaluate_outage_events()
        kpis_after = env.evaluate_v2(include_business_as_usual=False)

        pd.testing.assert_frame_equal(kpis_before, kpis_after, check_exact=True)
        assert len(events_df) > 0

        kpi_ratio_by_building = kpis_before[
            (kpis_before['level'] == 'building')
            & (kpis_before['cost_function'] == 'building_comfort_resilience_resilience_unserved_energy_outage_normalized_ratio')
        ].set_index('name')['value'].to_dict()

        for building in env.buildings:
            b_events = events_df[events_df['building'] == building.name]
            b_summary = audit['buildings'][building.name]
            step_unserved_sum = sum(unserved_energy(building, t) for t in range(env.time_step))

            assert b_events['unserved_energy_kwh'].sum() == pytest.approx(step_unserved_sum, rel=1e-9, abs=1e-9)
            assert b_summary['unserved_energy_kwh'] == pytest.approx(step_unserved_sum, rel=1e-9, abs=1e-9)

            end_use_unserved_sum = sum(
                b_summary[f'{eu}_unserved_energy_kwh']
                for eu in ('cooling', 'heating', 'dhw', 'non_shiftable')
            )
            assert end_use_unserved_sum == pytest.approx(b_summary['unserved_energy_kwh'], rel=1e-12, abs=1e-12)

            expected_ratio = 0.0 if b_summary['expected_energy_kwh'] <= 0.0 else (
                b_summary['unserved_energy_kwh'] / b_summary['expected_energy_kwh']
            )
            assert expected_ratio == pytest.approx(kpi_ratio_by_building[building.name], rel=1e-9, abs=1e-9)
    finally:
        env.close()


def test_dynamic_topology_raises_not_implemented():
    env = CityLearnEnv(
        'citylearn_three_phase_dynamic_topology_demo',
        interface='entity',
        topology_mode='dynamic',
        episode_time_steps=4,
        offline=True,
    )
    try:
        env.reset(seed=0)
        with pytest.raises(NotImplementedError, match='static topology'):
            env.get_outage_resilience_audit()
        with pytest.raises(NotImplementedError, match='static topology'):
            env.evaluate_outage_events()
    finally:
        env.close()
