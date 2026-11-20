from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv, EvaluationCondition
from citylearn.cost_function import CostFunction
from citylearn.data import ZERO_DIVISION_PLACEHOLDER


SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def _run_episode(schema: Path, action_value: float, episode_time_steps: int = 48) -> CityLearnEnv:
    env = CityLearnEnv(
        str(schema),
        central_agent=True,
        episode_time_steps=episode_time_steps,
        random_seed=0,
    )
    env.reset()
    ev_indices = [
        idx
        for idx, name in enumerate(env.action_names[0])
        if name.startswith("electric_vehicle_storage_")
    ]

    base_action = np.zeros(env.action_space[0].shape[0], dtype="float32")

    while not env.terminated:
        action = base_action.copy()
        if ev_indices:
            action[ev_indices] = action_value

        env.step([action])

    return env


def test_kpi_normalization_matches_baseline():
    env = _run_episode(SCHEMA, action_value=0.0)

    try:
        df = env.evaluate(
            control_condition=EvaluationCondition.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV,
            baseline_condition=EvaluationCondition.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV,
        )

        normalized_keys = {
            "ramping_average",
            "daily_one_minus_load_factor_average",
            "monthly_one_minus_load_factor_average",
            "daily_peak_average",
            "all_time_peak_average",
        }
        district = df[(df["level"] == "district") & (df["cost_function"].isin(normalized_keys))]
        vals = district["value"].to_numpy(dtype=float)

        assert np.all(np.isfinite(vals)), "District KPI contains non-finite values."
        assert np.allclose(vals, 1.0, atol=1e-5), "District KPI normalization deviates when control==baseline."
    finally:
        env.close()


def test_ev_charging_load_impacts_building_kpis():
    def _total_charger_consumption(sim_env: CityLearnEnv) -> float:
        return float(sum(np.sum(b.chargers_electricity_consumption) for b in sim_env.buildings))

    base_env = _run_episode(SCHEMA, action_value=0.0, episode_time_steps=24)
    try:
        base_df = base_env.evaluate()
        base_charger_consumption = _total_charger_consumption(base_env)
    finally:
        base_env.close()

    charged_env = _run_episode(SCHEMA, action_value=1.0, episode_time_steps=24)
    try:
        charged_df = charged_env.evaluate()
        charged_charger_consumption = _total_charger_consumption(charged_env)
    finally:
        charged_env.close()

    def _extract(df):
        subset = df[
            (df["level"] == "building")
            & (df["cost_function"] == "electricity_consumption_total")
        ]
        return subset.set_index("name")["value"]

    base_values = _extract(base_df)
    charged_values = _extract(charged_df)

    charged_values = charged_values.reindex(base_values.index)

    assert charged_charger_consumption > base_charger_consumption, \
        "EV load should increase charger electricity consumption."
    assert np.isfinite(charged_values.dropna()).all()


@pytest.mark.parametrize("seconds_per_time_step", [5, 10, 60, 300, 900])
def test_histories_and_kpi_consistency_with_subhour_steps(seconds_per_time_step: int):
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=6,
        seconds_per_time_step=seconds_per_time_step,
        random_seed=0,
        time_step_ratio_mode='compress',
    )

    try:
        env.reset()
        names = env.action_names[0]
        base_action = np.zeros(env.action_space[0].shape[0], dtype="float32")

        ev_indices = [idx for idx, name in enumerate(names) if name.startswith("electric_vehicle_storage_")]
        battery_indices = [idx for idx, name in enumerate(names) if "electrical_storage" in name]

        while not env.terminated:
            action = base_action.copy()
            if ev_indices:
                action[ev_indices] = 0.8
            if battery_indices:
                action[battery_indices] = 0.5

            env.step([action])
            t = env.time_step - 1

            assert 1 <= len(env.net_electricity_consumption) <= env.time_step + 1
            assert 1 <= len(env.net_electricity_consumption_cost) <= env.time_step + 1
            assert 1 <= len(env.net_electricity_consumption_emission) <= env.time_step + 1

            for building in env.buildings:
                lhs = building.net_electricity_consumption[t]
                rhs = (
                    building.cooling_electricity_consumption[t]
                    + building.heating_electricity_consumption[t]
                    + building.dhw_electricity_consumption[t]
                    + building.non_shiftable_load_electricity_consumption[t]
                    + building.electrical_storage_electricity_consumption[t]
                    + building.solar_generation[t]
                    + building.chargers_electricity_consumption[t]
                    + building.deferrable_appliances_electricity_consumption[t]
                )
                assert abs(lhs - rhs) < 1e-4

        final_t = env.time_step
        committed_len = final_t if final_t > 0 else 1
        for building in env.buildings:
            if building.electric_vehicle_chargers:
                charger_total = float(np.sum(building.chargers_electricity_consumption))
                charger_components = float(
                    sum(np.sum(c.electricity_consumption[: final_t + 1]) for c in building.electric_vehicle_chargers)
                )
                assert charger_total == pytest.approx(charger_components)

            assert len(building.solar_generation) == committed_len
            assert np.all(np.isfinite(building.solar_generation))

        for ev in env.electric_vehicles:
            soc = ev.battery.soc[: committed_len]
            assert np.all(np.isfinite(soc))
            assert np.all((soc >= 0.0) & (soc <= 1.0))

        control = EvaluationCondition.WITH_STORAGE_AND_PV
        baseline = EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV

        def _safe_div(control_value: float, baseline_value: float):
            eps = float(ZERO_DIVISION_PLACEHOLDER)
            if abs(baseline_value) <= eps:
                return 1.0 if abs(control_value) <= eps else np.nan
            return control_value / baseline_value

        building_ratios = []
        for building in env.buildings:
            ec_c = CostFunction.electricity_consumption(
                np.array(getattr(building, f"net_electricity_consumption{control.value}"), dtype=float).tolist()
            )[-1]
            ec_b = CostFunction.electricity_consumption(
                np.array(getattr(building, f"net_electricity_consumption{baseline.value}"), dtype=float).tolist()
            )[-1]
            building_ratios.append(_safe_div(float(ec_c), float(ec_b)))

        expected_ratio = float(np.nanmean(np.array(building_ratios, dtype=float)))

        df = env.evaluate(control_condition=control, baseline_condition=baseline)
        district_value = float(
            df[
                (df["level"] == "district")
                & (df["cost_function"] == "electricity_consumption_total")
            ]["value"].iloc[0]
        )

        assert district_value == pytest.approx(expected_ratio)
    finally:
        env.close()
