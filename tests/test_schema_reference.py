"""The schema reference, the full reference schema and the loader agree (CityLearn #390)."""

import inspect
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SCHEMA = ROOT / "examples" / "schema_full_reference.json"
REFERENCE_PAGES = (ROOT / "docs" / "schema_reference.md", ROOT / "docs" / "pt" / "schema_reference.md")
WALKTHROUGH_PAGES = (ROOT / "docs" / "schema_full_reference.md", ROOT / "docs" / "pt" / "schema_full_reference.md")

# Every key the loader reads, by level. `test_loader_keys_are_in_the_inventory` checks this list against the code.
INVENTORY = {
    "root": {
        "root_directory", "random_seed", "random_stream_version", "physics_version", "baseline_version",
        "central_agent", "interface", "seconds_per_time_step", "time_step_ratio_mode", "simulation_start_time_step",
        "simulation_end_time_step", "episode_time_steps", "rolling_episode_split", "random_episode_split",
        "episode_split_boundary", "ev_soc_carryover", "episode_end", "evaluation_window", "district_electrical_service", "time_axis", "timezone", "dataset_seconds_per_time_step",
        "dataset_contract_version", "terminal_observation_padding", "start_date", "reward_function", "agent",
        "observations", "actions", "observation_bundles", "derived_forecasts", "topology_mode", "topology_events",
        "buildings", "electric_vehicles_def", "ev_departure_within_tolerance", "ev_departure_service_tolerance",
        "business_as_usual_ev_charge_target", "community_market", "demand_response", "robustness", "render_mode",
        "render", "render_file_format", "render_chunk_size", "render_session_name", "export_kpis_on_episode_end",
        "export_only_final_episode", "debug_timing", "check_observation_limits", "physics_invariant_checks",
        "energy_provenance", "metrics_log_interval",
    },
    "time_axis": {"calendar_file"},
    "reward_function": {"type", "attributes"},
    "agent": {"type", "attributes"},
    "observation": {"active", "shared_in_central_agent"},
    "action": {"active"},
    "observation_bundles": {
        "entity_core_electrical", "entity_community_operational", "entity_forecasts_existing",
        "entity_forecasts_derived", "entity_temporal_derived", "entity_action_feedback", "entity_demand_response",
        "entity_robustness",
    },
    "derived_forecasts": {"load_pv_method", "persistence_period_seconds", "cold_start", "price_source",
                          "price_horizon_steps"},
    "building": {
        "include", "type", "energy_simulation", "weather", "pricing", "carbon_intensity", "noise_std",
        "inactive_observations", "inactive_actions", "equity_group", "cooling_device", "heating_device", "dhw_device",
        "cooling_storage", "heating_storage", "dhw_storage", "electrical_storage", "pv", "chargers",
        "deferrable_appliances", "escalators", "electrical_service", "charging_constraints", "power_outage",
        "dynamics", "occupant", "set_point_hold_time_steps", "set_point_limits",
    },
    "device": {"type", "attributes", "autosize", "autosize_attributes"},
    "HeatPump": {"nominal_power", "efficiency", "target_heating_temperature", "target_cooling_temperature"},
    "ElectricHeater": {"nominal_power", "efficiency"},
    "StorageTank": {"capacity", "efficiency", "loss_coefficient", "initial_soc", "max_input_power", "max_output_power"},
    "Battery": {"capacity", "nominal_power", "efficiency", "depth_of_discharge", "initial_soc", "loss_coefficient",
                "capacity_loss_coefficient", "power_efficiency_curve", "capacity_power_curve",
                "discharge_power_curve", "phase_connection"},
    "PV": {"nominal_power", "generation_mode", "efficiency"},
    "HeatPump.autosize": {"safety_factor"},
    "ElectricHeater.autosize": {"safety_factor"},
    "StorageTank.autosize": {"safety_factor", "duration"},
    "Battery.autosize": {"duration", "parallel", "safety_factor"},
    "PV.autosize": {"epw_filepath", "use_sample_target", "zero_net_energy_proportion", "roof_area", "safety_factor"},
    "charger": {"type", "charger_simulation", "attributes", "autosize", "noise_std", "soc_unit"},
    "charger.attributes": {"nominal_power", "max_charging_power", "min_charging_power", "max_discharging_power",
                           "min_discharging_power", "efficiency", "charge_efficiency_curve",
                           "discharge_efficiency_curve", "phase_connection", "charger_type"},
    "deferrable_appliance": {"type", "cycle_profiles_file", "flexibility_schedule_file", "attributes"},
    "deferrable_appliance.attributes": {"trigger_threshold", "nominal_power", "efficiency"},
    "escalator": {"type", "simulation", "simulation_file", "attributes"},
    "escalator.attributes": {"standby_power", "slow_power", "normal_power", "minimum_state_steps",
                             "service_threshold_passengers"},
    "electrical_service": {"mode", "default_split", "limits", "available_grid_power", "observations",
                           "expose_observations"},
    "electrical_service.limits": {"total", "per_phase"},
    "limit": {"import_kw", "export_kw"},
    "electrical_service.available_grid_power": {"filename", "column"},
    "electrical_service.observations": {"headroom", "headroom_export", "violation", "phase_encoding",
                                        "available_grid_power"},
    "charging_constraints": {"building_limit_kw", "phases", "expose_observations", "observations"},
    "charging_constraints.phase": {"name", "limit_kw", "chargers"},
    "charging_constraints.observations": {"headroom", "headroom_export", "violation", "phase_encoding"},
    "power_outage": {"simulate_power_outage", "stochastic_power_outage", "stochastic_power_outage_model",
                     "vehicle_to_building"},
    "power_outage_model": {"type", "attributes"},
    "ReliabilityMetricsPowerOutage": {"saifi", "caidi", "start_time_steps", "random_seed"},
    "dynamics": {"type", "attributes"},
    "dynamics.attributes": {"filename", "input_observation_names", "input_normalization_minimum",
                            "input_normalization_maximum", "hidden_size", "num_layers", "lookback", "input_size",
                            "dropout"},
    "occupant": {"type", "parameters_filename", "attributes"},
    "occupant.attributes": {"setpoint_increase_model_filename", "setpoint_decrease_model_filename",
                            "delta_output_map"},
    "electric_vehicle": {"type", "include", "battery"},
    "electric_vehicle.battery": {"type", "attributes"},
    "electric_vehicle.battery.attributes": {
        "capacity", "nominal_power", "initial_soc", "depth_of_discharge", "loss_coefficient", "efficiency",
        "capacity_loss_coefficient", "power_efficiency_curve", "capacity_power_curve", "discharge_power_curve",
        "random_seed", "max_charge_kw", "max_discharge_kw", "min_soc", "max_soc", "charging_efficiency",
        "discharging_efficiency",
    },
    "community_market": {"enabled", "local_price_ratio_to_grid_import", "intra_community_sell_ratio",
                         "settlement_version", "grid_export_price", "tariff_files", "local_trading_enabled",
                         "import_member_weights", "kpis", "matching_granularity", "counterfactual"},
    "community_market.kpis": {"community_local_traded_enabled", "community_self_consumption_enabled"},
    "demand_response": {"enabled", "requests_file", "baseline_method", "baseline_window_seconds",
                        "allow_overlapping_requests", "request_purposes"},
    "robustness": {"enabled", "events_file", "random_seed", "missing_replacement_value", "modules",
                   "agent_observation_contract"},
    "robustness.modules": {"observations", "forecasts", "actions", "assets"},
    "robustness.agent_observation_contract": {"mode", "features"},
    "topology_event": {"id", "time_step", "operation", "target_member_id", "target_asset_type", "target_asset_id",
                       "source_member_id", "source_asset_id", "overrides"},
    "multi_community": {"community_id", "schema", "env_kwargs", "weight"},
}

# Keys of the inventory that the full reference schema leaves out, and why.
NOT_IN_REFERENCE_SCHEMA = {
    ("community_market", "intra_community_sell_ratio"): "legacy alias of local_price_ratio_to_grid_import",
    ("charger", "autosize"): "accepted and ignored",
    ("escalator", "*"): "an escalator needs its own passenger file",
    ("escalator.attributes", "*"): "an escalator needs its own passenger file",
    ("dynamics", "*"): "needs a PyTorch model and a dynamics building type",
    ("dynamics.attributes", "*"): "needs a PyTorch model and a dynamics building type",
    ("occupant", "*"): "needs occupant model files and an occupant building type",
    ("occupant.attributes", "*"): "needs occupant model files and an occupant building type",
    ("electrical_service", "expose_observations"): "fallback of observations.headroom, shown in charging_constraints",
    ("electrical_service.available_grid_power", "*"): "needs an availability file",
    ("topology_event", "*"): "the static reference schema has no events",
    ("multi_community", "*"): "MultiCommunityEnv entries are not schema keys",
    ("electric_vehicle.battery.attributes", "max_charge_kw"): "InventoryBattery only",
    ("electric_vehicle.battery.attributes", "max_discharge_kw"): "InventoryBattery only",
    ("electric_vehicle.battery.attributes", "min_soc"): "InventoryBattery only",
    ("electric_vehicle.battery.attributes", "max_soc"): "InventoryBattery only",
    ("electric_vehicle.battery.attributes", "charging_efficiency"): "InventoryBattery only",
    ("electric_vehicle.battery.attributes", "discharging_efficiency"): "InventoryBattery only",
}

# Strings the loader reads through a schema-like name that are not schema keys.
NOT_SCHEMA_KEYS = {
    "chargers_actions_helper", "chargers_observations_helper", "chargers_shared_observations_helper",
    "deferrable_appliance_actions_helper", "deferrable_appliance_observations_helper",
    "escalator_actions_helper", "escalator_observations_helper", "shared_observations",
    "default",  # the per-building reward form: {"default": ...}
    "method",  # older name of derived_forecasts.load_pv_method
    "env", "episode_index", "episode_tracker", "filepath", "load", "net", "path", "period_seconds", "parameters",
    "random_stream_key", "sha", "schema", "time_step_ratio", "id",
}

# Constructor arguments with no schema key (documented as such).
CONSTRUCTOR_ONLY = {"offline", "solar_generation", "time_step_ratio", "render_directory", "render_directory_name",
                    "electric_vehicles", "buildings", "reward_function_kwargs", "shared_observations",
                    "active_observations", "inactive_observations", "active_actions", "inactive_actions",
                    "simulate_power_outage"}

LOADER_FILES = (
    "citylearn.py", "building.py", "data.py", "community_dataset.py", "multi_community.py",
    "internal/loading.py", "internal/loading_components.py", "internal/loading_inputs.py", "internal/temporal.py",
    "internal/market_config.py", "internal/demand_response.py", "internal/robustness.py",
    "internal/observation_contract.py", "internal/topology.py", "internal/entity_interface.py",
    "internal/grid_availability.py",
)
SCHEMA_ACCESS = re.compile(
    r"\b[a-z_]*(?:schema|config|outage|occupant|attrs|attributes|modules|event|electrical_service|"
    r"charging_constraints|limits|purposes|raw|section|options|entry)[a-z_]*"
    r"(?:\[['\"]([A-Za-z_]+)['\"]\]|\.get\(['\"]([A-Za-z_]+)['\"])"
)


def all_inventory_keys():
    return set().union(*INVENTORY.values())


def code_tokens(path):
    """Every identifier written inside backticks on a Markdown page."""
    text = path.read_text(encoding="utf-8")
    tokens = set()
    for span in re.findall(r"`([^`\n]+)`", text):
        tokens.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", span))
    return tokens


def init_parameters(cls):
    names = set()
    for klass in cls.__mro__:
        if "__init__" in vars(klass):
            names.update(inspect.signature(klass.__init__).parameters)
    return names - {"self", "args", "kwargs"}


# Set by the environment or the loader, never by the schema.
LOADER_SET = {"seconds_per_time_step", "time_step_ratio", "random_seed", "random_stream_version", "random_stream_key",
              "episode_tracker", "name", "deferrable_appliance_simulation", "escalator_simulation"}


def test_loader_keys_are_in_the_inventory():
    found = set()
    for name in LOADER_FILES:
        text = (ROOT / "citylearn" / name).read_text(encoding="utf-8")
        for match in SCHEMA_ACCESS.finditer(text):
            found.add(match.group(1) or match.group(2))
    missing = sorted(found - all_inventory_keys() - NOT_SCHEMA_KEYS)
    assert not missing, f"schema keys read by the loader but missing from the reference inventory: {missing}"


def test_inventory_matches_the_code_constants():
    from citylearn.citylearn import CityLearnEnv
    from citylearn.electric_vehicle_charger import Charger
    from citylearn.energy_model import Battery, DeferrableAppliance, ElectricHeater, Escalator, HeatPump, PV, StorageTank
    from citylearn.internal import market_config
    from citylearn.internal.entity_interface import CityLearnEntityInterfaceService
    from citylearn.internal.loading_components import _CHARGER_KEYS
    from citylearn.multi_community import MultiCommunityEnv
    from citylearn.power_outage import ReliabilityMetricsPowerOutage

    assert set(market_config.KNOWN_KEYS) == INVENTORY["community_market"]
    assert set(market_config.KNOWN_KPI_KEYS) == INVENTORY["community_market.kpis"]
    assert set(_CHARGER_KEYS) == INVENTORY["charger"]
    assert set(Charger._attribute_names()) - LOADER_SET == INVENTORY["charger.attributes"]
    assert set(MultiCommunityEnv._COMMUNITY_KEYS) == INVENTORY["multi_community"]
    assert set(CityLearnEntityInterfaceService.DEFAULT_OBSERVATION_BUNDLES) == INVENTORY["observation_bundles"]
    for cls in (HeatPump, ElectricHeater, StorageTank, Battery, PV):
        expected = INVENTORY[cls.__name__] - ({"phase_connection"} if cls is Battery else set())
        assert init_parameters(cls) - LOADER_SET == expected, cls.__name__
        autosize = set(inspect.signature(cls.autosize).parameters)
        autosize -= {"self", "demand", "outdoor_dry_bulb_temperature", "cooling_demand", "heating_demand",
                     "sizing_data", "physics_version"}
        assert autosize == INVENTORY[f"{cls.__name__}.autosize"], cls.__name__
    assert init_parameters(DeferrableAppliance) - LOADER_SET == INVENTORY["deferrable_appliance.attributes"]
    # Escalator: nominal_power is set from normal_power, and efficiency is not used.
    assert init_parameters(Escalator) - LOADER_SET - {"nominal_power", "efficiency"} == INVENTORY["escalator.attributes"]
    assert init_parameters(ReliabilityMetricsPowerOutage) - {"random_stream_version"} == \
        INVENTORY["ReliabilityMetricsPowerOutage"]
    # Every constructor option is either a schema key or documented as constructor-only.
    options = set(CityLearnEnv._KNOWN_CONSTRUCTOR_OPTIONS)
    assert options - INVENTORY["root"] - CONSTRUCTOR_ONLY == set()


@pytest.mark.parametrize("page", REFERENCE_PAGES, ids=["en", "pt"])
def test_every_key_is_documented(page):
    tokens = code_tokens(page)
    missing = sorted(all_inventory_keys() - tokens)
    assert not missing, f"{page.relative_to(ROOT)} does not document: {missing}"
    missing_options = sorted(CONSTRUCTOR_ONLY - tokens)
    assert not missing_options, f"{page.relative_to(ROOT)} does not mention: {missing_options}"


def reference_levels(schema):
    """Map each inventory level to the objects of the full reference schema at that level."""
    buildings = list(schema["buildings"].values())
    devices = [b[k] for b in buildings for k in INVENTORY["building"] if isinstance(b.get(k), dict) and "type" in b[k]
               and k not in ("dynamics", "occupant")]
    by_class = {}
    for device in devices:
        by_class.setdefault(device["type"].rsplit(".", 1)[1], []).append(device)
    chargers = [c for b in buildings for c in (b.get("chargers") or {}).values()]
    deferrables = [d for b in buildings for d in (b.get("deferrable_appliances") or {}).values()]
    services = [b["electrical_service"] for b in buildings if b.get("electrical_service")]
    constraints = [b["charging_constraints"] for b in buildings if b.get("charging_constraints")]
    outages = [b["power_outage"] for b in buildings if b.get("power_outage")]
    evs = list(schema["electric_vehicles_def"].values())
    levels = {
        "root": [schema],
        "time_axis": [schema["time_axis"]],
        "reward_function": [schema["reward_function"]],
        "agent": [schema["agent"]],
        "observation": list(schema["observations"].values()),
        "action": list(schema["actions"].values()),
        "observation_bundles": [schema["observation_bundles"]],
        "derived_forecasts": [schema["derived_forecasts"]],
        "building": buildings,
        "device": devices,
        "charger": chargers,
        "charger.attributes": [c["attributes"] for c in chargers],
        "deferrable_appliance": deferrables,
        "deferrable_appliance.attributes": [d["attributes"] for d in deferrables],
        "electrical_service": services,
        "electrical_service.limits": [s["limits"] for s in services],
        "limit": [s["limits"]["total"] for s in services] + [p for s in services for p in s["limits"]["per_phase"].values()],
        "electrical_service.observations": [s["observations"] for s in services],
        "charging_constraints": constraints,
        "charging_constraints.phase": [p for c in constraints for p in c["phases"]],
        "charging_constraints.observations": [c["observations"] for c in constraints],
        "power_outage": outages,
        "power_outage_model": [o["stochastic_power_outage_model"] for o in outages],
        "ReliabilityMetricsPowerOutage": [o["stochastic_power_outage_model"]["attributes"] for o in outages],
        "electric_vehicle": evs,
        "electric_vehicle.battery": [e["battery"] for e in evs],
        "electric_vehicle.battery.attributes": [e["battery"]["attributes"] for e in evs],
        "community_market": [schema["community_market"]],
        "community_market.kpis": [schema["community_market"]["kpis"]],
        "demand_response": [schema["demand_response"]],
        "robustness": [schema["robustness"]],
        "robustness.modules": [schema["robustness"]["modules"]],
        "robustness.agent_observation_contract": [schema["robustness"]["agent_observation_contract"]],
    }
    for cls in ("HeatPump", "ElectricHeater", "StorageTank", "Battery", "PV"):
        levels[cls] = [d["attributes"] for d in by_class[cls]]
        levels[f"{cls}.autosize"] = [d["autosize_attributes"] for d in by_class[cls] if "autosize_attributes" in d]
    return levels


def test_full_reference_schema_sets_every_key():
    schema = json.loads(REFERENCE_SCHEMA.read_text(encoding="utf-8"))
    levels = reference_levels(schema)
    missing = []
    for level, keys in INVENTORY.items():
        for key in sorted(keys):
            if (level, key) in NOT_IN_REFERENCE_SCHEMA or (level, "*") in NOT_IN_REFERENCE_SCHEMA:
                continue
            objects = levels.get(level)
            if not objects or not any(key in obj for obj in objects):
                missing.append(f"{level}.{key}")
    assert not missing, f"examples/schema_full_reference.json does not set: {missing}"
    # Every observation and action name in the reference is documented on the reference pages.
    for page in REFERENCE_PAGES:
        tokens = code_tokens(page)
        names = set(schema["observations"]) | set(schema["actions"])
        undocumented = sorted(
            name for name in names
            if name not in tokens and name.replace("deferrable_appliance_", "").replace("escalator_", "") not in tokens
        )
        assert not undocumented, f"{page.relative_to(ROOT)} does not list: {undocumented}"


def merge(target, block, path=()):
    for key, value in block.items():
        if isinstance(value, dict) and value and isinstance(target.get(key), dict):
            merge(target[key], value, path + (key,))
        else:
            assert key not in target, f"{'.'.join(path + (key,))} appears in two blocks"
            target[key] = value


@pytest.mark.parametrize("page", WALKTHROUGH_PAGES, ids=["en", "pt"])
def test_walkthrough_blocks_are_the_reference_schema(page):
    blocks = re.findall(r"```json\n(.*?)\n```", page.read_text(encoding="utf-8"), re.S)
    merged = {}
    for block in blocks:
        merge(merged, json.loads(block))
    assert merged == json.loads(REFERENCE_SCHEMA.read_text(encoding="utf-8"))


@pytest.mark.parametrize("page", REFERENCE_PAGES, ids=["en", "pt"])
def test_reference_page_examples_are_valid_json(page):
    for block in re.findall(r"```json\n(.*?)\n```", page.read_text(encoding="utf-8"), re.S):
        json.loads(block)


def test_full_reference_schema_loads_and_runs():
    import numpy as np
    from citylearn.citylearn import CityLearnEnv

    schema = json.loads(REFERENCE_SCHEMA.read_text(encoding="utf-8"))
    env = CityLearnEnv(str(REFERENCE_SCHEMA), simulation_end_time_step=48, episode_time_steps=25)
    try:
        assert env.physics_version == schema["physics_version"]
        assert env.baseline_version == schema["baseline_version"]
        assert env.random_stream_version == schema["random_stream_version"]
        assert [b.name for b in env.buildings] == list(schema["buildings"])
        assert "electric_vehicle_storage_charger_1_1" in env.action_names[0]
        assert "deferrable_appliance_deferrable_appliance_1" in env.action_names[0]
        observations, _ = env.reset()
        terminated = truncated = False
        while not (terminated or truncated):
            actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
            observations, _, terminated, truncated, _ = env.step(actions)
        assert env.time_step == 24
        # The KPIs run the native BAU for the EV baseline of baseline_version 2.
        kpis = env.evaluate()
        assert len(kpis) > 0
        # Every observation a building of this schema can produce is listed in the reference catalogue.
        internal = {"electric_vehicles_chargers_dict", "deferrable_appliances_dict", "washing_machines_dict",
                    "deferrable_appliance_electricity_consumption", "washing_machine_electricity_consumption"}
        for building in env.buildings:
            names = set(building._get_observations_data(include_all=True))
            names = {n for n in names if not n.endswith("_without_control") and not n.startswith("charging_")}
            assert names - internal - {"available_grid_power"} <= set(schema["observations"]), building.name
    finally:
        env.close()
