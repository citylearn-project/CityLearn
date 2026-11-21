"""Tests for charging constraint enforcement."""

import json
import shutil
from pathlib import Path

from typing import Optional

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


DATASET_DIR = Path(__file__).resolve().parents[2] / 'data/datasets/citylearn_challenge_2022_phase_all_plus_evs'


def _clone_dataset(
    tmp_path,
    *,
    with_constraints: bool,
    observation_settings: Optional[dict] = None,
    include_phases: bool = True,
    phases: Optional[list] = None,
) -> Path:
    target_dir = tmp_path / ('with_constraints' if with_constraints else 'baseline')
    shutil.copytree(DATASET_DIR, target_dir)
    schema_path = target_dir / 'schema.json'

    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    building = schema['buildings']['Building_15']

    if with_constraints:
        constraints = {
            "building_limit_kw": 10.0,
        }

        if include_phases:
            constraints["phases"] = phases if phases is not None else [
                {"name": "phase_a", "limit_kw": 7.0, "chargers": ["charger_15_1"]},
                {"name": "phase_b", "limit_kw": 5.0, "chargers": ["charger_15_2"]},
            ]
        else:
            constraints["phases"] = []
        if observation_settings is None:
            observation_settings = {
                "headroom": True,
                "violation": True,
                "phase_encoding": True,
            }

        constraints["observations"] = observation_settings
        building['charging_constraints'] = constraints
    else:
        building.pop('charging_constraints', None)

    with open(schema_path, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=4)

    return schema_path


def _get_action_indices(env, charger_ids):
    names = env.action_names[0]
    return [names.index(f'electric_vehicle_storage_{cid}') for cid in charger_ids]


def _get_building(env, name):
    return next(building for building in env.buildings if building.name == name)


def test_charging_constraints_scaling_and_penalty(tmp_path):
    schema_with = _clone_dataset(tmp_path / 'with', with_constraints=True)

    env_with_penalty = CityLearnEnv(str(schema_with), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env_with_penalty.reset()

        charger_ids = ["charger_15_1", "charger_15_2"]
        indices = _get_action_indices(env_with_penalty, charger_ids)
        actions = np.zeros(len(env_with_penalty.action_names[0]), dtype='float32')
        for idx in indices:
            actions[idx] = 1.0

        reward_with_penalty = env_with_penalty.step([actions.copy()])[1]

        building_with = _get_building(env_with_penalty, 'Building_15')
        time_index = building_with.time_step - 1
        charger_energy = {
            charger.charger_id: charger.past_charging_action_values_kwh[time_index]
            for charger in building_with.electric_vehicle_chargers
        }
        total_energy = sum(charger_energy.values())
        limit_kw = building_with.charging_building_limit_kw
        assert limit_kw is not None
        assert total_energy <= limit_kw + 1e-3

        state = building_with._charging_constraints_state
        assert state is not None
        headroom = state['building_headroom_kw']
        assert headroom == pytest.approx(limit_kw - total_energy, rel=1e-3, abs=1e-3)

        phase_headroom = state['phase_headroom_kw']
        assert abs(phase_headroom['phase_b']) <= 1e-3

        penalty_kwh = building_with._charging_constraint_last_penalty_kwh
        assert penalty_kwh > 0.0

        obs = building_with.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert 'charging_constraint_violation_kwh' in obs
        one_hot_keys = [key for key in obs if key.startswith('charging_phase_one_hot_charger_15_1_')]
        assert one_hot_keys
        assert abs(sum(obs[k] for k in one_hot_keys) - 1.0) < 1e-6

        if isinstance(reward_with_penalty, list):
            reward_with_value = reward_with_penalty[0]
        else:
            reward_with_value = reward_with_penalty
        reward_fn = env_with_penalty.reward_function
        coeff = reward_fn.charging_constraint_penalty_coefficient
        # Version 2 of the EV reward: reward = base reward + EV terms - charging constraint penalty.
        unpenalised_value = reward_fn._last_base_reward_total + reward_fn._last_ev_terms_total
        penalty_from_reward = reward_fn._last_penalty_total

        expected_delta = penalty_kwh * coeff
        assert penalty_from_reward == pytest.approx(expected_delta, rel=1e-3, abs=1e-6)
        assert unpenalised_value - reward_with_value == pytest.approx(penalty_from_reward, rel=1e-3, abs=1e-6)
    finally:
        env_with_penalty.close()


def test_charging_constraints_hide_observations(tmp_path):
    schema_path = _clone_dataset(
        tmp_path / 'hidden',
        with_constraints=True,
        observation_settings={
            "headroom": False,
            "violation": False,
            "phase_encoding": False,
        },
    )
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4)

    try:
        env.reset()
        building = _get_building(env, 'Building_15')
        obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert 'charging_building_headroom_kw' not in obs
        assert 'charging_constraint_violation_kwh' not in obs
        assert not any(key.startswith('charging_phase_one_hot_') for key in obs)

        indices = _get_action_indices(env, ["charger_15_1"])
        actions = np.zeros(len(env.action_names[0]), dtype='float32')
        actions[indices[0]] = 1.0
        env.step([actions])

        obs_after = building.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert 'charging_building_headroom_kw' not in obs_after
        assert 'charging_constraint_violation_kwh' not in obs_after
        assert not any(key.startswith('charging_phase_one_hot_') for key in obs_after)
    finally:
        env.close()


def test_charging_constraints_building_only(tmp_path):
    schema_path = _clone_dataset(
        tmp_path / 'building_only',
        with_constraints=True,
        include_phases=False,
    )

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=1)

    try:
        env.reset()
        building = _get_building(env, 'Building_15')

        # Push both chargers to full power to trigger the building-level clamp.
        charger_ids = ["charger_15_1", "charger_15_2"]
        indices = _get_action_indices(env, charger_ids)
        actions = np.zeros(len(env.action_names[0]), dtype='float32')
        for idx in indices:
            actions[idx] = 1.0

        reward = env.step([actions])[1]
        assert reward is not None

        time_index = building.time_step - 1
        charger_energy = {
            charger.charger_id: charger.past_charging_action_values_kwh[time_index]
            for charger in building.electric_vehicle_chargers
        }
        total_energy = sum(charger_energy.values())
        limit_kw = building.charging_building_limit_kw
        assert limit_kw is not None
        assert total_energy <= limit_kw + 1e-3

        obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert 'charging_building_headroom_kw' in obs
        assert 'charging_phase_phase_a_headroom_kw' not in obs  # no phases configured

        one_hot_keys = [k for k in obs if k.startswith('charging_phase_one_hot_')]
        assert not one_hot_keys

    finally:
        env.close()


def test_charging_constraints_no_violation(tmp_path):
    schema_path = _clone_dataset(tmp_path / 'no_violation', with_constraints=True)

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        charger_ids = ["charger_15_1", "charger_15_2"]
        indices = _get_action_indices(env, charger_ids)
        actions = np.zeros(len(env.action_names[0]), dtype='float32')
        for idx in indices:
            actions[idx] = 0.25  # well below limits

        reward = env.step([actions.copy()])[1]
        assert reward is not None

        building = _get_building(env, 'Building_15')
        assert building._charging_constraint_last_penalty_kwh == pytest.approx(0.0, abs=1e-6)
        obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert obs.get('charging_constraint_violation_kwh', 0.0) == pytest.approx(0.0, abs=1e-6)

    finally:
        env.close()


def test_charging_constraints_single_phase_assignment(tmp_path):
    custom_phases = [
        {"name": "phase_a", "limit_kw": 7.0, "chargers": ["charger_15_1"]},
    ]
    schema_path = _clone_dataset(
        tmp_path / 'single_phase',
        with_constraints=True,
        observation_settings={
            "headroom": True,
            "violation": True,
            "phase_encoding": True,
        },
        phases=custom_phases,
    )

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        charger_ids = ["charger_15_1", "charger_15_2"]
        indices = _get_action_indices(env, charger_ids)
        actions = np.zeros(len(env.action_names[0]), dtype='float32')
        for idx in indices:
            actions[idx] = 1.0

        env.step([actions.copy()])

        building = _get_building(env, 'Building_15')
        obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)

        # Charger 15_1 should belong to phase_a, charger 15_2 should map to "unassigned".
        phase_a_key = 'charging_phase_one_hot_charger_15_1_phase_a'
        assert obs.get(phase_a_key) == pytest.approx(1.0, abs=1e-6)
        unassigned_key = 'charging_phase_one_hot_charger_15_2_unassigned'
        assert obs.get(unassigned_key) == pytest.approx(1.0, abs=1e-6)

    finally:
        env.close()
