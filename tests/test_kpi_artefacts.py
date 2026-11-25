"""KPI artefacts found in the final verification of the 3.7.0 release candidate.

- The EV target counts as met within 0.005 SOC, wider than the 0.001 at which the rule-based engines stop.
- A building without set-point data has no comfort KPIs, instead of being judged against 0 °C.
- Cost and emissions ratios of two zero totals are undefined, not 1.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents import _baseline_engine
from citylearn.citylearn import CityLearnEnv
from citylearn.data import EnergySimulation
from citylearn.electric_vehicle import EV_SERVICE_SOC_TOLERANCE
from citylearn.internal import ev_departure_audit
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.multi_community import MultiCommunityEnv

DATASETS = Path(__file__).resolve().parents[1] / "data" / "datasets"
QUEBEC = "quebec_neighborhood_without_demand_response_set_points"
PT_REC_4 = "pt_rec_4"
PLUS_EVS = "citylearn_challenge_2022_phase_all_plus_evs"
# Summer midday at 900 s steps, as in the multi-community tests.
PT_REC_4_WINDOW = [17324, 17335]


def _value(kpis: pd.DataFrame, cost_function: str, name: str = "District"):
    rows = kpis[(kpis["cost_function"] == cost_function) & (kpis["name"] == name)]
    assert len(rows) == 1, cost_function
    value = pd.to_numeric(rows["value"], errors="coerce").iloc[0]
    return None if pd.isna(value) else float(value)


def _schema(dataset: str, *, first_building_only: bool = False) -> dict:
    source = DATASETS / dataset
    schema = json.loads((source / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(source)
    if first_building_only:
        first = next(name for name, building in schema["buildings"].items() if building.get("include", True))
        schema["buildings"] = {first: {**schema["buildings"][first], "include": True}}
    return schema


def _run_zero(env: CityLearnEnv) -> CityLearnEnv:
    env.reset(seed=0)
    while not env.terminated:
        env.step([[0.0] * space.shape[0] for space in env.action_space])
    return env


# EV target met (P3)

def _departure(actual_soc: float, target_soc: float = 0.80):
    ev = SimpleNamespace(battery=SimpleNamespace(soc=[float(actual_soc), float(actual_soc)]))
    charger = SimpleNamespace(
        charger_id="charger",
        electricity_consumption=np.zeros(2, dtype="float64"),
        charger_simulation=SimpleNamespace(
            electric_vehicle_charger_state=np.array([1.0, 0.0], dtype="float64"),
            electric_vehicle_required_soc_departure=np.array([float(target_soc)] * 2, dtype="float64"),
        ),
        past_connected_evs=[ev, None],
    )
    return SimpleNamespace(name="Building_1", time_step=1, electric_vehicle_chargers=[charger])


def test_kpis_use_one_ev_service_tolerance_wider_than_the_rule_engines():
    assert EV_SERVICE_SOC_TOLERANCE == 0.005
    assert CityLearnKPIService.EV_TARGET_SOC_TOLERANCE is EV_SERVICE_SOC_TOLERANCE
    # The engines stop charging inside the KPI tolerance.
    assert _baseline_engine.EV_CHARGE_STOP_SOC_TOLERANCE == 0.001
    assert _baseline_engine.NORMAL_DEFAULTS["ev_service_soc_tolerance"] == _baseline_engine.EV_CHARGE_STOP_SOC_TOLERANCE
    assert _baseline_engine.EV_CHARGE_STOP_SOC_TOLERANCE < EV_SERVICE_SOC_TOLERANCE
    assert not hasattr(_baseline_engine, "EV_SERVICE_SOC_TOLERANCE")


def test_departure_within_the_service_tolerance_meets_the_target():
    """An RBC car stops charging 0.1 % short of its target; that departure meets the target."""

    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))
    metrics = service._compute_ev_metrics(_departure(0.80 - 0.0049))

    assert metrics["departures_total"] == 1.0
    assert metrics["departures_met"] == 1.0
    assert metrics["ev_departure_success_rate"] == 1.0
    assert metrics["ev_departure_success_feasible_rate"] == 1.0
    assert metrics["_departure_audit"]["target_service_met_count"] == 1
    # The deficit and shortfall stay exact.
    assert metrics["ev_departure_soc_deficit_mean"] == pytest.approx(0.0049)
    assert metrics["ev_departure_shortfall_beyond_tolerance_mean"] == 0.0


def test_departure_beyond_the_service_tolerance_misses_the_target():
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))
    metrics = service._compute_ev_metrics(_departure(0.80 - 0.006))

    assert metrics["departures_met"] == 0.0
    assert metrics["_departure_audit"]["target_service_met_count"] == 0
    assert metrics["ev_departure_soc_deficit_mean"] == pytest.approx(0.006)


def test_target_tolerance_never_exceeds_the_service_tolerance():
    """With ev_departure_service_tolerance=0, met stays below min_acceptable."""

    env = SimpleNamespace(topology_mode="static", ev_departure_service_tolerance=0.0)
    service = CityLearnKPIService(env)
    metrics = service._compute_ev_metrics(_departure(0.80 - 0.0009))

    assert service._ev_departure_target_tolerance() == 0.0
    assert metrics["departures_met"] == metrics["departures_min_acceptable"] == 0.0


def test_departure_audit_label_records_the_new_target_test(quebec_env):
    """Exports from before the 0.005 tolerance carry v1, so comparing them with new ones is flagged."""

    assert ev_departure_audit.DEFINITION_VERSION == "ev-departure-audit-v2"
    audit = quebec_env._provenance_service.get_metadata()["ev_departure_audit"]
    assert audit["definition_version"] == ev_departure_audit.DEFINITION_VERSION


# Comfort without set points (P4)

def test_energy_simulation_records_whether_set_points_were_supplied():
    base = dict(
        month=[1, 1], hour=[1, 2], day_type=[1, 1], indoor_dry_bulb_temperature=[21.0, 21.0],
        non_shiftable_load=[1.0, 1.0], dhw_demand=[0.0, 0.0], cooling_demand=[0.0, 0.0],
        heating_demand=[0.0, 0.0], solar_generation=[0.0, 0.0],
    )
    without = EnergySimulation(**base)
    with_set_points = EnergySimulation(
        **base, indoor_dry_bulb_temperature_cooling_set_point=[24.0, 24.0],
        indoor_dry_bulb_temperature_heating_set_point=[20.0, 20.0],
    )

    assert without.set_point_data_available is False
    # The simulation keeps its 0 °C default.
    assert np.all(without.indoor_dry_bulb_temperature_cooling_set_point == 0.0)
    assert with_set_points.set_point_data_available is True


@pytest.fixture(scope="module")
def pt_rec_4_kpis():
    env = CityLearnEnv(
        _schema(PT_REC_4), central_agent=True, random_seed=0, render_mode="none", interface="flat",
        episode_time_steps=[PT_REC_4_WINDOW],
    )
    try:
        _run_zero(env)
        yield env, env.evaluate_v2(include_business_as_usual=False), env.evaluate()
    finally:
        env.close()


def test_buildings_without_set_points_have_no_comfort_kpis(pt_rec_4_kpis):
    env, kpis, legacy = pt_rec_4_kpis
    assert not any(b.energy_simulation.set_point_data_available for b in env.buildings)
    # The members are occupied: on master every occupied interval counted as 21 °C too hot.
    assert all(np.nansum(b.occupant_count) > 0 for b in env.buildings)

    for name in [b.name for b in env.buildings] + ["District"]:
        assert _value(kpis, f"{'district' if name == 'District' else 'building'}_thermal_service_audit_discomfort_ratio", name) is None
        level = "district" if name == "District" else "building"
        assert _value(kpis, f"{level}_comfort_resilience_discomfort_overall_ratio", name) is None
        assert _value(kpis, f"{level}_comfort_resilience_discomfort_hot_delta_max_c", name) is None
        assert _value(kpis, f"{level}_thermal_service_audit_thermal_coverage_ratio", name) == 0.0

    legacy_district = legacy[(legacy["name"] == "District") & (legacy["cost_function"] == "discomfort_proportion")]
    assert pd.isna(legacy_district["value"]).all()


@pytest.fixture(scope="module")
def quebec_env():
    """One Quebec building: HVAC actions, set points and zero carbon intensity."""

    env = CityLearnEnv(
        _schema(QUEBEC, first_building_only=True), central_agent=True, random_seed=0, render_mode="none",
        episode_time_steps=12,
    )
    try:
        yield _run_zero(env)
    finally:
        env.close()


def test_buildings_with_set_points_keep_their_comfort_kpis(quebec_env):
    building = quebec_env.buildings[0]
    assert building.energy_simulation.set_point_data_available is True
    service = quebec_env._kpi_service
    cooling, heating = service._comfort_set_points(building)
    np.testing.assert_array_equal(
        cooling, service._thermal_values(building, building.indoor_dry_bulb_temperature_cooling_set_point))
    np.testing.assert_array_equal(
        heating, service._thermal_values(building, building.indoor_dry_bulb_temperature_heating_set_point))

    kpis = quebec_env.evaluate_v2(include_business_as_usual=False)
    assert _value(kpis, "district_thermal_service_audit_discomfort_ratio") is not None
    assert _value(kpis, "district_thermal_service_audit_thermal_coverage_ratio") > 0.0


# Cost and emissions ratios of two zero totals (P6)

def test_zero_emissions_give_undefined_emissions_ratios(quebec_env):
    kpis = quebec_env.evaluate_v2()

    building = quebec_env.buildings[0].name
    assert _value(kpis, "district_emissions_total_control_kgco2") == 0.0
    assert _value(kpis, "district_emissions_total_baseline_kgco2") == 0.0
    for level, name in (("district", "District"), ("building", building)):
        assert _value(kpis, f"{level}_emissions_ratio_to_baseline_total_ratio", name) is None
        assert _value(kpis, f"{level}_emissions_ratio_to_business_as_usual_total_ratio", name) is None
    # Nonzero totals keep their ratio.
    assert _value(kpis, "district_cost_ratio_to_baseline_total_ratio") is not None


def test_ratio_zero_over_zero_is_undefined_for_cost_and_emissions():
    undefined = CityLearnKPIService.ratio_zero_over_zero
    for name in ("district_cost_ratio_to_baseline_total_ratio", "building_cost_ratio_to_business_as_usual_total_ratio",
                 "district_emissions_ratio_to_baseline_total_ratio",
                 "district_emissions_ratio_to_business_as_usual_total_ratio",
                 "district_deferrable_appliance_ratio_to_business_as_usual_missed_cycles_ratio"):
        assert undefined(name) is None, name
    for name in ("district_energy_grid_ratio_to_baseline_import_total_ratio",
                 "district_energy_grid_ratio_to_business_as_usual_export_total_ratio"):
        assert undefined(name) == 1.0, name


def test_portfolio_cost_ratio_of_zero_totals_is_undefined():
    district = pd.DataFrame([
        {"community_id": community, "cost_function": name, "numeric_value": 0.0}
        for community in ("a", "b")
        for name in ("district_cost_total_control_eur", "district_cost_total_baseline_eur")
    ])
    components = CityLearnKPIService.total_ratio_components("district")["district_cost_ratio_to_baseline_total_ratio"]
    zero_over_zero = CityLearnKPIService.ratio_zero_over_zero("district_cost_ratio_to_baseline_total_ratio")

    assert np.isnan(MultiCommunityEnv._pooled_ratio(district, *components, zero_over_zero=zero_over_zero))


def test_zero_carbon_intensity_without_hvac_gives_undefined_emissions_ratios(tmp_path):
    """The same 0/0 rule on a dataset with storage and EVs."""

    root = tmp_path / PLUS_EVS
    shutil.copytree(DATASETS / PLUS_EVS, root)
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    for building in schema["buildings"].values():
        path = root / building["carbon_intensity"]
        frame = pd.read_csv(path)
        frame.iloc[:, 0] = 0.0
        frame.to_csv(path, index=False)
    schema["root_directory"] = str(root)
    env = CityLearnEnv(schema, central_agent=True, random_seed=0, render_mode="none", episode_time_steps=12)
    try:
        _run_zero(env)
        kpis = env.evaluate_v2()
    finally:
        env.close()

    assert _value(kpis, "district_emissions_ratio_to_baseline_total_ratio") is None
    assert _value(kpis, "district_emissions_ratio_to_business_as_usual_total_ratio") is None
    assert _value(kpis, "district_cost_ratio_to_baseline_total_ratio") is not None
