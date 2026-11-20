import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import PV
from citylearn.internal.units import (
    energy_kwh_to_power_kw,
    normalized_capacity_action_to_energy_kwh,
    normalized_power_action_to_energy_kwh,
    power_kw_to_energy_kwh,
)


SCHEMA = Path(__file__).resolve().parents[2] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def test_thermal_storage_actions_use_matching_storage_capacities(monkeypatch):
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        building = env.buildings[0]

        building.cooling_storage.capacity = 100.0
        building.heating_storage.capacity = 10.0
        building.dhw_storage.capacity = 20.0

        for storage in [building.heating_storage, building.dhw_storage]:
            storage.efficiency = 1.0
            storage.loss_coefficient = 0.0
            storage.initial_soc = 0.0
            storage.reset()

        monkeypatch.setattr(building.heating_device, "get_max_output_power", lambda *args, **kwargs: 1.0e6)
        monkeypatch.setattr(building.heating_device, "get_input_power", lambda *args, **kwargs: 0.0)
        monkeypatch.setattr(building.dhw_device, "get_max_output_power", lambda *args, **kwargs: 1.0e6)
        monkeypatch.setattr(building.dhw_device, "get_input_power", lambda *args, **kwargs: 0.0)

        building.update_heating_storage(0.1)
        building.update_dhw_storage(0.1)

        expected_heating_kwh = normalized_capacity_action_to_energy_kwh(
            0.1,
            building.heating_storage.capacity,
            seconds_per_time_step=building.seconds_per_time_step,
            scale_with_time=True,
        )
        expected_dhw_kwh = normalized_capacity_action_to_energy_kwh(
            0.1,
            building.dhw_storage.capacity,
            seconds_per_time_step=building.seconds_per_time_step,
            scale_with_time=True,
        )

        assert building.heating_storage.energy_balance[building.time_step] == pytest.approx(expected_heating_kwh)
        assert building.dhw_storage.energy_balance[building.time_step] == pytest.approx(expected_dhw_kwh)
    finally:
        env.close()


def test_cooling_storage_actions_scale_with_subhour_control_step(monkeypatch):
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=4,
        seconds_per_time_step=900,
        random_seed=0,
        time_step_ratio_mode='compress',
    )

    try:
        env.reset()
        building = env.buildings[0]

        building.cooling_storage.capacity = 100.0
        building.cooling_storage.efficiency = 1.0
        building.cooling_storage.loss_coefficient = 0.0
        building.cooling_storage.initial_soc = 0.0
        building.cooling_storage.reset()

        monkeypatch.setattr(building.cooling_device, "get_max_output_power", lambda *args, **kwargs: 1.0e6)
        monkeypatch.setattr(building.cooling_device, "get_input_power", lambda *args, **kwargs: 0.0)

        building.update_cooling_storage(0.1)

        expected_cooling_kwh = normalized_capacity_action_to_energy_kwh(
            0.1,
            building.cooling_storage.capacity,
            seconds_per_time_step=building.seconds_per_time_step,
            scale_with_time=True,
        )

        assert building.cooling_storage.energy_balance[building.time_step] == pytest.approx(expected_cooling_kwh)
    finally:
        env.close()


def test_action_to_energy_helpers_are_consistent():
    assert normalized_power_action_to_energy_kwh(0.5, 4.0, 900.0) == pytest.approx(0.5)
    assert power_kw_to_energy_kwh(2.0, 1800.0) == pytest.approx(1.0)
    assert energy_kwh_to_power_kw(1.0, 1800.0) == pytest.approx(2.0)
    assert normalized_capacity_action_to_energy_kwh(
        0.25,
        8.0,
        seconds_per_time_step=1800.0,
        scale_with_time=True,
    ) == pytest.approx(1.0)


def test_pv_absolute_generation_mode_uses_input_as_kwh_step():
    pv = PV(nominal_power=50.0, generation_mode="absolute")
    generation = pv.get_generation(np.array([0.0, 0.25, 1.5], dtype=np.float32))

    np.testing.assert_array_equal(generation, np.array([0.0, 0.25, 1.5], dtype=np.float32))


def test_pv_per_kw_generation_mode_remains_default():
    pv = PV(nominal_power=50.0)
    generation = pv.get_generation(np.array([0.0, 500.0, 1000.0], dtype=np.float32))

    np.testing.assert_array_equal(generation, np.array([0.0, 25.0, 50.0], dtype=np.float32))


def test_pv_per_kw_generation_mode_scales_with_active_timestep():
    pv = PV(nominal_power=50.0, seconds_per_time_step=900)
    generation = pv.get_generation(np.array([0.0, 500.0, 1000.0], dtype=np.float32))

    np.testing.assert_array_equal(generation, np.array([0.0, 6.25, 12.5], dtype=np.float32))


def test_schema_can_load_absolute_pv_generation_mode():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(SCHEMA.parent)
    schema["buildings"]["Building_1"]["pv"]["attributes"]["generation_mode"] = "absolute"
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, random_seed=0)

    try:
        env.reset()
        building = env.buildings[0]
        raw_solar = building.energy_simulation.solar_generation
        nonzero_indices = np.flatnonzero(np.abs(raw_solar) > 1.0e-8)
        assert building.pv.generation_mode == "absolute"
        assert len(nonzero_indices) > 0

        solar_index = int(nonzero_indices[0])
        internal_generation = getattr(building, "_Building__solar_generation")
        ratio = 1.0 if building.time_step_ratio in (None, 0) else float(building.time_step_ratio)
        assert internal_generation[solar_index] == pytest.approx(-raw_solar[solar_index] * ratio)
    finally:
        env.close()
