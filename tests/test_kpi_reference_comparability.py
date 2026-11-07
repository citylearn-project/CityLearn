"""Control-versus-reference KPIs stay comparable for net exporters."""

import numpy as np
import pytest

from citylearn.internal.kpi import CityLearnKPIService
from test_independent_balances import commands, scenario

K = CityLearnKPIService


def _value(kpis, level, name, cost_function):
    rows = kpis[(kpis["level"] == level) & (kpis["name"] == name) & (kpis["cost_function"] == cost_function)]
    assert len(rows) == 1, (level, name, cost_function)
    return float(rows["value"].iloc[0])


def _market_rollout(tmp_path):
    env = scenario(tmp_path)
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
