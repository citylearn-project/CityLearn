"""Control-versus-reference KPIs stay comparable for net exporters and power outages."""

from pathlib import Path

import numpy as np
import pytest

from citylearn.building import Building, DynamicsBuilding
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from test_independent_balances import commands, scenario

K = CityLearnKPIService
SCHEMA_2023 = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_challenge_2023_phase_2_local_evaluation/schema.json"
)


def _value(kpis, level, name, cost_function):
    rows = kpis[(kpis["level"] == level) & (kpis["name"] == name) & (kpis["cost_function"] == cost_function)]
    assert len(rows) == 1, (level, name, cost_function)
    return float(rows["value"].iloc[0])


def _market_rollout(tmp_path, *, outage=False):
    env = scenario(tmp_path, outage=outage)
    env.reset()
    while not env.terminated:
        env.step(commands(env, [-0.5, -0.5]))
    return env


@pytest.mark.parametrize("control,baseline", [(3.0, 4.0), (-1.0, 4.0), (0.0, 2.5), (5.0, 1.0e-3), (0.0, 0.0), (1.0, 0.0)])
def test_signed_ratio_is_the_plain_ratio_for_a_non_negative_baseline(control, baseline):
    assert K._signed_ratio(control, baseline) == K._safe_div(control, baseline)


def test_signed_ratio_is_lower_is_better_for_a_net_exporting_baseline():
    controls = [-30.0, -12.0, -10.0, -8.0, 0.0, 64.0]
    ratios = [K._signed_ratio(control, -10.0) for control in controls]

    assert np.all(np.diff(ratios) > 0.0)
    assert K._signed_ratio(-10.0, -10.0) == 1.0
    assert K._signed_ratio(-12.0, -10.0) == pytest.approx(0.8)
    # control / baseline would report -6.4 here, an apparent improvement.
    assert K._signed_ratio(64.0, -10.0) == pytest.approx(8.4)


def test_net_exchange_and_cost_ratios_do_not_flip_for_net_exporting_baselines(tmp_path):
    env = _market_rollout(tmp_path)

    try:
        kpis = env.evaluate_v2()
        legacy = env.evaluate()
        checks = [
            ("energy_grid_total_net_exchange_control_kwh", "energy_grid_total_net_exchange_baseline_kwh",
             "energy_grid_ratio_to_baseline_net_exchange_total_ratio", ["building"]),
            ("energy_grid_total_net_exchange_control_kwh", "energy_grid_total_net_exchange_business_as_usual_kwh",
             "energy_grid_ratio_to_business_as_usual_net_exchange_total_ratio", ["building", "district"]),
            ("cost_total_control_eur", "cost_total_baseline_eur", "cost_ratio_to_baseline_total_ratio",
             ["building", "district"]),
            ("cost_total_control_eur", "cost_total_business_as_usual_eur", "cost_ratio_to_business_as_usual_total_ratio",
             ["building", "district"]),
        ]
        worse_exporters = better_exporters = 0

        for control_metric, reference_metric, ratio_metric, levels in checks:
            for level in levels:
                names = [b.name for b in env.buildings] if level == "building" else ["District"]
                for name in names:
                    control = _value(kpis, level, name, f"{level}_{control_metric}")
                    reference = _value(kpis, level, name, f"{level}_{reference_metric}")
                    ratio = _value(kpis, level, name, f"{level}_{ratio_metric}")

                    if reference > 1.0e-3:
                        assert ratio == pytest.approx(control / reference)
                    elif reference < -1.0e-3:
                        worse_exporters += control > reference
                        better_exporters += control < reference
                        assert ratio == pytest.approx(1.0 + (control - reference) / abs(reference))
                        assert (ratio > 1.0) == (control > reference)

        # Both directions occur in this scenario, so a sign flip cannot go unnoticed.
        assert worse_exporters > 0 and better_exporters > 0

        for building in env.buildings:
            legacy_ratio = legacy[(legacy["cost_function"] == "zero_net_energy") & (legacy["name"] == building.name)]
            assert float(legacy_ratio["value"].iloc[0]) == pytest.approx(
                _value(kpis, "building", building.name, "building_energy_grid_ratio_to_baseline_net_exchange_total_ratio")
            )
    finally:
        env.close()


def test_counterfactual_series_exchange_no_energy_while_the_grid_is_down(tmp_path):
    env = _market_rollout(tmp_path, outage=True)

    try:
        kpis = env.evaluate_v2(include_business_as_usual=False)
        exchanged_before_fix = False

        for building in env.buildings:
            outage = np.asarray(building.power_outage_signal) > 0
            assert outage.any()
            # The controlled building is disconnected while the grid is down.
            assert np.all(building.net_electricity_consumption[outage] == 0.0)

            storage = np.sum([
                building.cooling_storage_electricity_consumption,
                building.heating_storage_electricity_consumption,
                building.dhw_storage_electricity_consumption,
                building.electrical_storage_electricity_consumption,
                building.chargers_electricity_consumption,
            ], axis=0)
            unrestricted = building.net_electricity_consumption - storage
            exchanged_before_fix |= bool(np.any(np.abs(unrestricted[outage]) > 1.0e-6))

            counterfactual = building.net_electricity_consumption_without_storage
            np.testing.assert_array_equal(counterfactual[~outage], unrestricted[~outage])

            for series in (
                counterfactual,
                building.net_electricity_consumption_cost_without_storage,
                building.net_electricity_consumption_emission_without_storage,
                building.net_electricity_consumption_without_storage_and_pv,
                building.net_electricity_consumption_cost_without_storage_and_pv,
                building.net_electricity_consumption_emission_without_storage_and_pv,
            ):
                assert np.all(np.asarray(series)[outage] == 0.0)

            assert _value(kpis, "building", building.name, "building_energy_grid_total_import_baseline_kwh") == pytest.approx(
                float(np.clip(counterfactual, 0.0, None).sum())
            )

        assert exchanged_before_fix
        outage = np.asarray(env.buildings[0].power_outage_signal) > 0
        assert np.all(np.asarray(env.net_electricity_consumption_without_storage)[outage] == 0.0)
    finally:
        env.close()


def test_partial_load_counterfactual_exchanges_no_energy_while_the_grid_is_down(monkeypatch):
    outage_steps = slice(6, 12)

    def forced_outage(self):
        signal = np.zeros(self.episode_tracker.episode_time_steps, dtype="float32")
        signal[outage_steps] = 1.0
        return signal

    monkeypatch.setattr(Building, "reset_power_outage_signal", forced_outage)
    env = CityLearnEnv(str(SCHEMA_2023), central_agent=True, episode_time_steps=24, random_seed=0)

    try:
        env.reset(seed=0)
        rng = np.random.default_rng(0)
        while not env.terminated:
            space = env.action_space[0]
            env.step([rng.uniform(space.low, space.high).tolist()])

        steps = np.arange(len(env.buildings[0].power_outage_signal))
        outage = (steps >= outage_steps.start) & (steps < outage_steps.stop)

        for building in env.buildings:
            assert isinstance(building, DynamicsBuilding)
            assert np.all((np.asarray(building.power_outage_signal) > 0) == outage)
            assert np.any(building.cooling_demand_without_partial_load[outage] + building.heating_demand_without_partial_load[outage] > 0.0)

            for series in (
                building.net_electricity_consumption_without_storage_and_partial_load,
                building.net_electricity_consumption_cost_without_storage_and_partial_load,
                building.net_electricity_consumption_emission_without_storage_and_partial_load,
                building.net_electricity_consumption_without_storage_and_partial_load_and_pv,
            ):
                assert np.all(np.asarray(series)[outage] == 0.0)

        assert np.all(np.asarray(env.net_electricity_consumption_without_storage_and_partial_load)[outage] == 0.0)
    finally:
        env.close()
