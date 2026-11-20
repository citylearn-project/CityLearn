"""Engineering gaps from the 3.6.0 audit (#256) and the community market operator balance (#239)."""

from __future__ import annotations

import importlib
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import HeatPump
from test_electrical_service_and_market import _build_two_building_market_schema


# Heat pump COP (#256: no direct unit test existed)


def _heat_pump(**kwargs) -> HeatPump:
    tracker = EpisodeTracker(0, 9)
    tracker.next_episode(10, False, False, 0)
    return HeatPump(nominal_power=5.0, efficiency=0.2, target_heating_temperature=45.0,
                    target_cooling_temperature=8.0, episode_tracker=tracker, random_seed=0, **kwargs)


def test_heat_pump_cop_follows_the_documented_carnot_fraction():
    heat_pump = _heat_pump()
    outdoor = np.array([0.0, 10.0, 30.0])

    expected_heating = 0.2 * (45.0 + 273.15) / (45.0 - outdoor)
    expected_cooling = 0.2 * (8.0 + 273.15) / (outdoor - 8.0)
    expected_cooling[expected_cooling < 0] = 20.0
    expected_cooling[expected_cooling > 20] = 20.0

    np.testing.assert_allclose(heat_pump.get_cop(outdoor, heating=True), np.minimum(expected_heating, 20.0))
    np.testing.assert_allclose(heat_pump.get_cop(outdoor, heating=False), expected_cooling)
    assert heat_pump.get_cop(10.0, heating=True) == pytest.approx(0.2 * 318.15 / 35.0)


def test_heat_pump_cop_is_capped_at_20_including_a_zero_temperature_difference():
    heat_pump = _heat_pump()

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        cop = heat_pump.get_cop(np.array([45.0, 50.0, 44.9]), heating=True)

    # Zero difference (infinite), negative (outdoor above target) and above 20 all cap at 20.
    np.testing.assert_allclose(cop, [20.0, 20.0, 20.0])


# Tests must not write to the user's dataset cache (#256)


def test_tests_use_a_private_dataset_cache():
    from platformdirs import user_cache_dir

    from citylearn.data import DataSet

    schema = Path(DataSet().get_dataset("citylearn_challenge_2022_phase_all"))
    user_cache = Path(user_cache_dir(appname="citylearn")).resolve()

    assert schema.is_file()
    assert user_cache not in schema.resolve().parents


# Optional end-use load profile modules (#256: never imported by the tests)


@pytest.mark.parametrize("module", ["clustering", "neighborhood", "simulate"])
def test_end_use_load_profile_modules_import_when_their_extras_are_installed(module):
    pytest.importorskip("doe_xstock")
    importlib.import_module(f"citylearn.end_use_load_profiles.{module}")


# Community market operator balance (#239)


def _market_env(tmp_path, tariffs):
    path = _build_two_building_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    if tariffs is not None:
        schema["community_market"].update(settlement_version=2, tariff_files={"Building_A": "a.csv", "Building_B": "b.csv"})
        for file, buy, sell in tariffs:
            pd.DataFrame({"grid_export_price": [.1, .1], "community_buy_price": [buy, buy],
                          "community_sell_price": [sell, sell]}).to_csv(path.parent / file, index=False)
    path.write_text(json.dumps(schema))
    env = CityLearnEnv(str(path), episode_time_steps=2)
    env.reset()
    env.step([np.zeros(len(env.action_names[0]))])
    return env


def _kpi(frame, name):
    rows = frame[frame["cost_function"] == name]
    return dict(zip(rows["name"], rows["value"]))


def test_operator_balance_kpi_reports_the_money_kept_by_the_market(tmp_path):
    env = _market_env(tmp_path, [("a.csv", .3, .2), ("b.csv", .6, .25)])
    rows = env._community_market_settlement_history[-1]
    expected = sum(r["operator_balance_eur"] for r in rows)
    assert expected == pytest.approx(.1)

    kpis = env.evaluate_v2(include_business_as_usual=False)
    names = [n for n in kpis["cost_function"].unique() if "operator_balance" in n]
    district = [n for n in names if n.startswith("district_")]
    assert district, names
    assert _kpi(kpis, district[0])["District"] == pytest.approx(expected)
    # Per member the value would only be its net local payment, so the KPI is district-only.
    assert not [n for n in names if n.startswith("building_")]


def test_operator_balance_reports_the_residual_of_different_member_pricing_files(tmp_path):
    # The #239 reproduction: no tariff_files, but Building_B has its own pricing file at twice the price.
    path = _build_two_building_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    schema["buildings"]["Building_B"]["pricing"] = "pricing_b.csv"
    path.write_text(json.dumps(schema))
    pricing = pd.read_csv(path.parent / "pricing.csv")
    (pricing * 2).to_csv(path.parent / "pricing_b.csv", index=False)

    env = CityLearnEnv(str(path), episode_time_steps=2)
    env.reset()
    env.step([np.zeros(len(env.action_names[0]))])
    rows = {r["building"]: r for r in env._community_market_settlement_history[-1]}
    traded = rows["Building_A"]["local_import_kwh"]
    assert traded > 0 and rows["Building_B"]["local_export_kwh"] == pytest.approx(traded)

    # The importer pays 0.8 x 0.5 and the exporter receives 0.8 x 1.0 for the same energy.
    expected = traded * 0.8 * (0.5 - 1.0)
    kpis = env.evaluate_v2(include_business_as_usual=False)
    name = next(n for n in kpis["cost_function"].unique() if n.startswith("district_") and "operator_balance" in n)
    assert _kpi(kpis, name)["District"] == pytest.approx(expected)
    assert expected < 0


def test_operator_balance_is_zero_with_a_single_tariff(tmp_path):
    env = _market_env(tmp_path, None)
    kpis = env.evaluate_v2(include_business_as_usual=False)
    name = next(n for n in kpis["cost_function"].unique() if n.startswith("district_") and "operator_balance" in n)
    assert _kpi(kpis, name)["District"] == pytest.approx(0.0, abs=1e-12)
