import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.physics_invariants import CityLearnPhysicsInvariantService


SCHEMA = Path(__file__).resolve().parents[2] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def _zero_actions(env: CityLearnEnv):
    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def test_physics_invariants_disabled_by_default_when_not_set_in_schema():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        assert env.physics_invariant_checks is False
    finally:
        env.close()


def test_physics_invariants_enabled_when_explicit_in_schema():
    schema = json.loads(SCHEMA.read_text())
    schema["root_directory"] = str(SCHEMA.parent)
    schema["physics_invariant_checks"] = True
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        assert env.physics_invariant_checks is True
    finally:
        env.close()


def test_physics_invariants_pass_in_normal_rollout():
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=12,
        random_seed=0,
        physics_invariant_checks=True,
    )

    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            env.step(_zero_actions(env))
    finally:
        env.close()


def test_physics_invariants_detect_building_energy_balance_mismatch():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0, physics_invariant_checks=False)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        t = int(env.time_step)
        building._Building__net_electricity_consumption[t] += 5.0

        with pytest.raises(AssertionError, match="Net energy balance mismatch"):
            env._physics_invariant_service.assert_step_invariants(t)
    finally:
        env.close()


def test_physics_invariants_detect_soc_out_of_bounds():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0, physics_invariant_checks=False)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        t = int(env.time_step)
        building.electrical_storage._StorageDevice__soc[t] = 1.2

        with pytest.raises(AssertionError, match="SOC out of bounds"):
            env._physics_invariant_service.assert_step_invariants(t)
    finally:
        env.close()


def test_physics_invariants_detect_charger_power_limit_violation():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0, physics_invariant_checks=False)

    try:
        env.reset(seed=0)
        charger = None
        for building in env.buildings:
            if building.electric_vehicle_chargers:
                charger = building.electric_vehicle_chargers[0]
                break

        if charger is None:
            pytest.skip("Dataset does not contain EV chargers.")

        t = int(env.time_step)
        charger._Charger__electricity_consumption[t] = 1.0e6

        with pytest.raises(AssertionError, match="Charger power bound exceeded"):
            env._physics_invariant_service.assert_step_invariants(t)
    finally:
        env.close()


def test_physics_invariants_use_historical_membership_after_topology_change():
    active = SimpleNamespace(name="active")
    newly_added = SimpleNamespace(name="newly_added")
    topology = SimpleNamespace(active_member_ids_at=lambda _time_step: ["active"])
    env = SimpleNamespace(
        buildings=[active, newly_added],
        topology_mode="dynamic",
        _topology_service=topology,
    )
    service = CityLearnPhysicsInvariantService(env)
    checked = []

    service._assert_building_energy_balance = lambda building, _time_step: checked.append(building.name)
    service._assert_outage_local_balance = lambda _building, _time_step: None
    service._assert_thermal_device_conversion = lambda _building, _time_step: None
    service._assert_served_energy_within_demand = lambda _building, _time_step: None
    service._assert_soc_bounds = lambda _building, _time_step: None
    service._assert_storage_power_bounds = lambda _building, _time_step: None
    service._assert_charger_power_bounds = lambda _building, _time_step: None

    service.assert_step_invariants(999)

    assert checked == ["active"]
