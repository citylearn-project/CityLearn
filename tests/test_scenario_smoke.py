from pathlib import Path
import csv

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def _charging_action(env: CityLearnEnv) -> np.ndarray:
    names = env.action_names[0]
    action = np.zeros(env.action_space[0].shape[0], dtype="float32")

    ev_indices = [i for i, name in enumerate(names) if name.startswith("electric_vehicle_storage_")]
    battery_indices = [i for i, name in enumerate(names) if "electrical_storage" in name]

    if ev_indices:
        action[ev_indices] = 0.7

    if battery_indices:
        action[battery_indices] = 0.5

    return action


@pytest.mark.parametrize("seconds_per_time_step", [5, 60])
def test_scenario_smoke_ev_battery_pv_none_mode(seconds_per_time_step: int):
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=11,
        seconds_per_time_step=seconds_per_time_step,
        render_mode="none",
        random_seed=0,
        time_step_ratio_mode='compress',
    )

    try:
        env.reset()

        while not env.terminated:
            action = _charging_action(env)
            _, _, terminated, truncated, _ = env.step([action])

            if terminated or truncated:
                break

        assert env.time_step == env.episode_time_steps - 1
        assert len(env.electric_vehicles) > 0
        assert any(len(b.electric_vehicle_chargers) > 0 for b in env.buildings)
        assert any(b.electrical_storage.capacity > 0 for b in env.buildings)
        assert any(b.pv.nominal_power > 0 for b in env.buildings)

        final_t = env.time_step
        expected_building_series_len = final_t if final_t > 0 else 1

        for building in env.buildings:
            assert len(building.net_electricity_consumption) == expected_building_series_len
            storage_soc = float(building.electrical_storage.soc[building.time_step])
            assert 0.0 <= storage_soc <= 1.0

        for ev in env.electric_vehicles:
            ev_soc = float(ev.battery.soc[ev.time_step])
            assert 0.0 <= ev_soc <= 1.0

        kpis = env.evaluate()
        district_total = kpis[
            (kpis["level"] == "district")
            & (kpis["cost_function"] == "electricity_consumption_total")
        ]["value"]
        assert not district_total.empty
        assert np.isfinite(district_total.to_numpy(dtype=float)).all()
    finally:
        env.close()


def test_scenario_smoke_ev_battery_pv_end_mode_exports(tmp_path):
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=11,
        seconds_per_time_step=60,
        render_mode="end",
        render_directory=tmp_path,
        render_session_name="scenario_smoke_end",
        random_seed=0,
        time_step_ratio_mode='compress',
    )

    class _Model:
        pass

    model = _Model()
    model.env = env

    try:
        env.reset()

        while not env.terminated:
            action = _charging_action(env)
            _, _, terminated, truncated, _ = env.step([action])

            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        assert outputs_path.is_dir()

        community_file = outputs_path / "exported_data_community_ep0.csv"
        assert community_file.is_file()
        assert any(outputs_path.glob("exported_data_*_battery_ep0.csv"))

        for ev in env.electric_vehicles:
            ev_file = outputs_path / f"exported_data_{ev.name.lower()}_ep0.csv"
            assert ev_file.is_file()

        with community_file.open(newline="") as handle:
            rows = list(csv.reader(handle))

        assert len(rows) > 2

        env.export_final_kpis(model, filepath="exported_kpis_smoke.csv")
        assert (outputs_path / "exported_kpis_smoke.csv").is_file()
    finally:
        env.close()
