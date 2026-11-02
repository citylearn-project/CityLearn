"""Canonical entity observation/action contract for CityLearnEnv."""

from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from gymnasium import spaces
import numpy as np

from citylearn.internal import entity_layout, entity_observations


@dataclass(frozen=True)
class ChargerRef:
    """Resolved charger location inside the environment."""

    row: int
    building_index: int
    building_name: str
    charger_id: str
    global_id: str


@dataclass(frozen=True)
class StorageRef:
    """Resolved storage location inside the environment."""

    row: int
    building_index: int
    building_name: str
    storage_id: str
    global_id: str


@dataclass(frozen=True)
class PVRef:
    """Resolved PV location inside the environment."""

    row: int
    building_index: int
    building_name: str
    pv_id: str
    global_id: str


@dataclass(frozen=True)
class DeferrableApplianceRef:
    """Resolved deferrable appliance location inside the environment."""

    row: int
    building_index: int
    building_name: str
    appliance_id: str
    global_id: str


class CityLearnEntityInterfaceService:
    """Build and parse canonical entity payloads."""

    BASE_BUNDLE = "entity_base"
    CORE_BUNDLE = "entity_core_electrical"
    COMMUNITY_BUNDLE = "entity_community_operational"
    FORECAST_BUNDLE = "entity_forecasts_existing"
    DERIVED_FORECAST_BUNDLE = "entity_forecasts_derived"
    TEMPORAL_BUNDLE = "entity_temporal_derived"
    ACTION_FEEDBACK_BUNDLE = "entity_action_feedback"
    DEMAND_RESPONSE_BUNDLE = "entity_demand_response"
    ROBUSTNESS_BUNDLE = "entity_robustness"
    DEFAULT_OBSERVATION_BUNDLES = {
        CORE_BUNDLE: False,
        COMMUNITY_BUNDLE: False,
        FORECAST_BUNDLE: False,
        DERIVED_FORECAST_BUNDLE: False,
        TEMPORAL_BUNDLE: False,
        ACTION_FEEDBACK_BUNDLE: False,
        DEMAND_RESPONSE_BUNDLE: False,
        ROBUSTNESS_BUNDLE: False,
    }
    FORECAST_HORIZONS = (
        ("15m", 15 * 60),
        ("1h", 60 * 60),
        ("3h", 3 * 60 * 60),
        ("6h", 6 * 60 * 60),
        ("24h", 24 * 60 * 60),
    )
    DERIVED_FORECAST_BUILDING_SIGNALS = ("load", "pv", "net")
    DERIVED_FORECAST_DISTRICT_SIGNALS = ("load", "pv", "net")

    LEGACY_CHARGER_FEATURES = [
        "connected_state",
        "incoming_state",
        "connected_ev_soc",
        "connected_ev_required_soc_departure",
        "connected_ev_battery_capacity_kwh",
        "connected_ev_departure_time_step",
        "incoming_ev_estimated_soc_arrival",
        "incoming_ev_estimated_arrival_time_step",
        "last_charged_kwh",
        "max_charging_power_kw",
        "max_discharging_power_kw",
    ]
    BASE_CHARGER_FEATURES = [
        "min_charging_power_kw",
        "min_discharging_power_kw",
        "charger_efficiency_ratio",
    ]
    EXTRA_CHARGER_FEATURES = [
        "commanded_power_kw",
        "applied_power_kw",
        "applied_energy_kwh_step",
        "hours_until_departure",
        "time_until_departure_ratio",
        "energy_to_required_soc_kwh",
        "required_average_power_kw",
        "avg_power_to_departure_kw",
        "charging_slack_kw",
        "charging_priority_ratio",
        "connected_ev_soc_min_ratio",
        "connected_ev_energy_available_kwh",
        "connected_ev_energy_to_full_kwh",
        "can_charge",
        "can_discharge",
        "available_charge_power_kw",
        "available_discharge_power_kw",
        "available_charge_action_normalized",
        "available_discharge_action_normalized",
        "max_deliverable_energy_until_departure_kwh",
        "departure_energy_margin_kwh",
        "departure_feasibility_ratio",
        "min_required_action_normalized",
        "charge_efficiency_at_max_ratio",
        "discharge_efficiency_at_max_ratio",
        "incoming_ev_required_soc_departure",
        "incoming_ev_departure_time_step",
        "incoming_ev_hours_until_departure",
        "incoming_ev_time_until_departure_ratio",
    ]
    ACTION_FEEDBACK_FEATURES = [
        "last_requested_action_normalized",
        "last_limited_action_normalized",
        "last_requested_power_kw",
        "last_limited_power_kw",
        "last_applied_power_kw",
        "last_projection_error_kw",
        "applied_energy_prev_15m_kwh",
        "applied_power_mean_prev_15m_kw",
        "time_since_last_nonzero_action_hours",
        "clip_reason_availability",
        "clip_reason_power_limit",
        "clip_reason_soc_limit",
        "clip_reason_building_headroom",
        "clip_reason_phase_headroom",
        "clip_reason_export_headroom",
        "clip_reason_outage",
        "clip_reason_deferrable_window",
    ]
    DEFERRABLE_ACTION_FEEDBACK_FEATURES = [
        "last_start_requested",
        "last_start_applied",
        "start_blocked",
        "clip_reason_availability",
        "clip_reason_power_limit",
        "clip_reason_soc_limit",
        "clip_reason_building_headroom",
        "clip_reason_phase_headroom",
        "clip_reason_export_headroom",
        "clip_reason_outage",
        "clip_reason_deferrable_window",
    ]
    LEGACY_EV_FEATURES = [
        "soc",
        "battery_capacity_kwh",
        "depth_of_discharge_ratio",
    ]
    EXTRA_EV_FEATURES = [
        "soc_ratio",
        "soc_min_ratio",
        "soc_max_ratio",
        "energy_available_kwh",
        "energy_to_full_kwh",
    ]
    LEGACY_STORAGE_FEATURES = [
        "soc",
        "capacity_kwh",
        "nominal_power_kw",
        "electricity_consumption_kwh",
    ]
    EXTRA_STORAGE_FEATURES = [
        "electrical_storage_soc_ratio",
        "max_charge_power_kw",
        "max_discharge_power_kw",
        "energy_to_full_kwh",
        "energy_available_kwh",
        "can_charge",
        "can_discharge",
        "available_charge_power_kw",
        "available_discharge_power_kw",
        "available_charge_action_normalized",
        "available_discharge_action_normalized",
        "available_charge_energy_kwh_step",
        "available_discharge_energy_kwh_step",
        "max_charge_energy_kwh_step",
        "max_discharge_energy_kwh_step",
        "charge_headroom_ratio",
        "discharge_available_ratio",
        "usable_soc_ratio",
        "current_efficiency_ratio",
        "degraded_capacity_kwh",
        "soc_min_ratio",
    ]
    BASE_STORAGE_FEATURES = [
        "min_charge_power_kw",
        "min_discharge_power_kw",
        "efficiency_ratio",
        "round_trip_efficiency_ratio",
    ]
    PV_FEATURES = [
        "generation_power_kw",
        "generation_energy_kwh_step",
        "installed_power_kw",
        "generation_capacity_factor_ratio",
    ]
    DEFERRABLE_APPLIANCE_FEATURES = [
        "pending",
        "running",
        "can_start",
        "deadline_missed",
        "earliest_start_time_step",
        "latest_start_time_step",
        "deadline_time_step",
        "hours_until_latest_start",
        "hours_until_deadline",
        "slack_steps",
        "slack_ratio",
        "urgency_ratio",
        "cycle_duration_steps",
        "cycle_energy_kwh",
        "remaining_energy_kwh",
        "current_step_energy_kwh",
        "priority",
        "must_run",
        "cycle_average_power_kw",
        "cycle_peak_power_kw",
        "cycle_load_factor_ratio",
        "cycle_peak_step_offset_ratio",
        "remaining_duration_steps",
        "remaining_duration_hours",
        "cycle_remaining_fraction_ratio",
        "hours_until_earliest_start",
        "start_window_width_hours",
        "start_energy_kwh_step",
        "start_power_kw",
        "must_start_now",
        "remaining_average_power_kw",
        "current_step_power_kw",
    ]
    CORE_BUILDING_EXTRA_FEATURES = [
        "net_power_kw",
        "net_energy_kwh_step",
        "import_power_kw",
        "import_energy_kwh_step",
        "export_power_kw",
        "export_energy_kwh_step",
        "load_power_kw",
        "load_energy_kwh_step",
        "pv_power_kw",
        "pv_energy_kwh_step",
        "pv_surplus_power_kw",
        "pv_surplus_energy_kwh_step",
        "bess_power_kw",
        "bess_energy_kwh_step",
        "ev_charging_power_kw",
        "ev_charging_energy_kwh_step",
        "electrical_storage_soc_ratio",
        "charging_total_service_power_kw",
        "building_import_headroom_kw",
        "building_export_headroom_kw",
        "import_phase_headroom_kw",
        "export_phase_headroom_kw",
        "flexible_charge_power_capacity_kw",
        "flexible_discharge_power_capacity_kw",
        "flexible_charge_energy_capacity_kwh_step",
        "flexible_discharge_energy_capacity_kwh_step",
        "flexible_energy_to_full_kwh",
        "flexible_energy_available_kwh",
    ]
    COMMUNITY_DISTRICT_EXTRA_FEATURES = [
        "community_net_power_kw",
        "community_net_energy_kwh_step",
        "community_import_power_kw",
        "community_import_energy_kwh_step",
        "community_export_power_kw",
        "community_export_energy_kwh_step",
        "community_pv_power_kw",
        "community_pv_energy_kwh_step",
        "community_bess_power_kw",
        "community_bess_energy_kwh_step",
        "community_ev_power_kw",
        "community_ev_energy_kwh_step",
        "community_building_headroom_kw",
        "community_building_export_headroom_kw",
        "community_phase_headroom_kw",
        "community_phase_export_headroom_kw",
        "community_flexible_charge_power_capacity_kw",
        "community_flexible_discharge_power_capacity_kw",
        "community_flexible_charge_energy_capacity_kwh_step",
        "community_flexible_discharge_energy_capacity_kwh_step",
        "community_flexible_energy_to_full_kwh",
        "community_flexible_energy_available_kwh",
        "active_buildings_count",
        "active_chargers_count",
        "active_evs_count",
        "topology_version",
    ]
    TEMPORAL_BUILDING_FEATURES = [
        "net_energy_prev_1_kwh_step",
        "net_energy_prev_3_mean_kwh_step",
        "import_energy_prev_1_kwh_step",
        "export_energy_prev_1_kwh_step",
        "hour_sin",
        "hour_cos",
        "day_type_sin",
        "day_type_cos",
        "month_sin",
        "month_cos",
        "seconds_of_day_sin",
        "seconds_of_day_cos",
        "is_weekend",
    ]
    TEMPORAL_DISTRICT_FEATURES = [
        "community_net_prev_1_kwh_step",
        "community_net_prev_3_mean_kwh_step",
        "hour_sin",
        "hour_cos",
        "day_type_sin",
        "day_type_cos",
        "month_sin",
        "month_cos",
        "seconds_of_day_sin",
        "seconds_of_day_cos",
        "is_weekend",
    ]
    DEMAND_RESPONSE_DISTRICT_FEATURES = [
        "dr_active",
        "dr_issuer_code",
        "dr_direction",
        "dr_target_power_kw",
        "dr_baseline_power_kw",
        "dr_time_remaining_hours",
        "dr_activation_price_eur_per_kwh",
        "dr_shortfall_penalty_eur_per_kwh",
        "dr_previous_delivered_power_kw",
        "dr_previous_shortfall_power_kw",
    ]
    ROBUSTNESS_DISTRICT_FEATURES = [
        "robustness_active",
        "robustness_observation_corruption_count_previous",
        "robustness_forecast_corruption_count_previous",
        "robustness_action_corruption_count_previous",
        "robustness_asset_unavailable_count",
    ]

    def __init__(self, env):
        self.env = env
        self._initialized = False
        self._layout_topology_version = -1
        self._observation_bundles = self._resolve_observation_bundles()
        self._action_feedback_series_cache: Dict[int, Dict[str, Any]] = {}

    def reset(self):
        """Rebuild specs and reusable buffers for the current episode layout."""

        self._action_feedback_series_cache = {}
        self._build_entity_layout()
        self._build_spaces()
        self._build_specs()
        self._initialized = True
        self._layout_topology_version = int(getattr(self.env, 'topology_version', 0))

    def invalidate(self):
        """Mark specs/layout as stale and rebuild on next access."""

        self._initialized = False
        self._action_feedback_series_cache = {}

    @property
    def observation_space(self) -> spaces.Dict:
        self._ensure_initialized()
        return self._observation_space

    @property
    def action_space(self) -> spaces.Dict:
        self._ensure_initialized()
        return self._action_space

    @property
    def specs(self) -> Mapping[str, Any]:
        self._ensure_initialized()
        return self._specs

    def observation_payload(self) -> Mapping[str, Any]:
        """Build canonical observations, preserving timing and copy ownership."""
        self._ensure_initialized()
        env = self.env
        context = entity_observations.context_for(self)
        debug_timing = bool(getattr(env, "debug_timing", False))
        timings: Dict[str, float] = {}
        section_start = time.perf_counter() if debug_timing else 0.0

        def finish_section(name: str):
            nonlocal section_start
            if not debug_timing:
                return
            now = time.perf_counter()
            timings[f"entity_observation_{name}_time"] = now - section_start
            section_start = now

        entity_observations.reset_buffers(self)
        finish_section("buffer_reset")
        building_data = entity_observations.fill_building_rows(self, context)
        finish_section("building")
        entity_observations.fill_district_row(self, context, building_data)
        finish_section("district")
        entity_observations.fill_charger_rows(self, context)
        finish_section("charger")
        entity_observations.fill_ev_rows(self, context)
        finish_section("ev")
        entity_observations.fill_storage_rows(self, context)
        finish_section("storage")
        entity_observations.fill_pv_rows(self, context)
        finish_section("pv")
        entity_observations.fill_deferrable_rows(self, context)
        finish_section("deferrable_appliance")
        entity_observations.fill_relation_masks(self, context)
        finish_section("edges")
        entity_observations.sanitize_tables(self)
        finish_section("sanitize")
        copy_start = time.perf_counter() if debug_timing else 0.0
        payload = entity_observations.snapshot_payload(self, context)
        if debug_timing:
            timings["entity_observation_copy_time"] = time.perf_counter() - copy_start
            env._last_entity_observation_debug_timing = timings
        else:
            env._last_entity_observation_debug_timing = {}
        return payload

    def _runtime_status_payload(self) -> Mapping[str, Any]:
        """Return raw connection/quality evidence for typed consumers.

        This payload intentionally contains no policy health classification.
        Consumers such as the Typed Interface Compiler own that derivation.
        """

        service = getattr(self.env, "_robustness_service", None)
        if service is not None:
            status = dict(service.runtime_status())
        else:
            status = {
                "version": "runtime_status_v1",
                "emits_health_state": False,
                "active_events": [],
                "asset_connections": [],
                "asset_availability": [],
                "sensor_channels": [],
                "actuator_channels": [],
                "communication_links": [],
                "value_quality": [],
            }
        status["asset_connections"] = self._asset_connection_status_records()
        return status

    def _asset_connection_status_records(self) -> List[Mapping[str, Any]]:
        records: List[Mapping[str, Any]] = []
        for ref in self._charger_refs:
            connected = bool(
                ref.row < len(self._charger_to_ev_connected_mask)
                and self._charger_to_ev_connected_mask[ref.row] > 0.5
            )
            ev_id = None
            if connected and ref.row < len(self._charger_to_ev_connected):
                ev_row = int(self._charger_to_ev_connected[ref.row, 1])
                if 0 <= ev_row < len(self._ev_ids):
                    ev_id = str(self._ev_ids[ev_row])
            records.append(
                {
                    "relation": "charger_to_ev_connected",
                    "source_type": "charger",
                    "source_id": str(ref.global_id),
                    "target_type": "ev",
                    "target_id": ev_id,
                    "building_id": str(ref.building_name),
                    "connection": "CONNECTED" if connected else "DISCONNECTED",
                    "availability": "AVAILABLE",
                    "quality": "NOMINAL",
                    "fault_mode": None,
                    "event_ids": [],
                }
            )
        return records

    def parse_actions(self, actions: Any) -> List[Mapping[str, float]]:
        """Parse canonical entity action payload into per-building action dicts."""

        self._ensure_initialized()
        if self._is_flat_like(actions):
            vectors = self._parse_flat_like(actions)
            return self._map_vectors_to_action_dicts(vectors)

        if not isinstance(actions, Mapping):
            raise AssertionError("Entity interface expects mapping payload with action tables.")

        tables = actions.get("tables", actions)
        if not isinstance(tables, Mapping):
            raise AssertionError("Entity action 'tables' must be a mapping of entity tables.")

        building_table = self._action_table_candidate(actions, tables, "building")
        charger_table = self._action_table_candidate(actions, tables, "charger")
        deferrable_appliance_table = self._action_table_candidate(actions, tables, "deferrable_appliance")

        building_table = self._to_2d_array(building_table, rows=len(self._building_ids), cols=len(self._building_action_features))
        charger_table = self._to_2d_array(charger_table, rows=len(self._charger_refs), cols=len(self._charger_action_features))
        deferrable_appliance_table = self._to_2d_array(
            deferrable_appliance_table,
            rows=len(self._deferrable_appliance_refs),
            cols=len(self._deferrable_appliance_action_features),
        )
        if self._has_action_overrides(actions):
            building_overrides, charger_overrides, deferrable_appliance_overrides = self._resolve_map_overrides(actions)
        else:
            building_overrides, charger_overrides, deferrable_appliance_overrides = {}, {}, {}

        parsed_actions = []
        for building_idx, building in enumerate(self.env.buildings):
            per_building_map = building_overrides.get(building.name, {})
            action_dict = {}
            electric_vehicle_actions = {}
            deferrable_appliance_actions = {}

            for action_name, low, high in zip(building.active_actions, building.action_space.low, building.action_space.high):
                value = 0.0
                if action_name in self._building_action_col_by_name:
                    col = self._building_action_col_by_name[action_name]
                    if building_table is not None:
                        value = building_table[building_idx, col]
                    if isinstance(per_building_map, Mapping) and action_name in per_building_map:
                        value = self._safe_scalar(per_building_map[action_name], float(value))

                elif action_name.startswith("electric_vehicle_storage_"):
                    row = self._charger_row_by_ev_action_name.get((building_idx, action_name))
                    if row is not None and row >= 0 and charger_table is not None and charger_table.shape[1] > 0:
                        value = charger_table[row, 0]
                    charger_ref = self._charger_refs[row] if row is not None and row >= 0 else None
                    if charger_ref is not None:
                        charger_payload = charger_overrides.get(charger_ref.global_id, {})
                        if isinstance(charger_payload, Mapping) and "electric_vehicle_storage" in charger_payload:
                            value = self._safe_scalar(charger_payload["electric_vehicle_storage"], float(value))

                elif action_name.startswith("deferrable_appliance_"):
                    row = self._deferrable_appliance_row_by_action_name.get((building_idx, action_name))
                    if row is not None and row >= 0 and deferrable_appliance_table is not None and deferrable_appliance_table.shape[1] > 0:
                        value = deferrable_appliance_table[row, 0]
                    ref = self._deferrable_appliance_refs[row] if row is not None and row >= 0 else None
                    if ref is not None:
                        payload = deferrable_appliance_overrides.get(ref.global_id, {})
                        if isinstance(payload, Mapping) and "start" in payload:
                            value = self._safe_scalar(payload["start"], float(value))
                    if isinstance(per_building_map, Mapping) and action_name in per_building_map:
                        value = self._safe_scalar(per_building_map[action_name], float(value))

                value = float(np.clip(value, low, high))
                if action_name.startswith("electric_vehicle_storage_"):
                    charger_id = action_name.replace("electric_vehicle_storage_", "")
                    electric_vehicle_actions[charger_id] = value
                elif action_name.startswith("deferrable_appliance_"):
                    deferrable_appliance_actions[action_name] = value
                else:
                    action_dict[f"{action_name}_action"] = value

            if electric_vehicle_actions:
                action_dict["electric_vehicle_storage_actions"] = electric_vehicle_actions
            if deferrable_appliance_actions:
                action_dict["deferrable_appliance_actions"] = deferrable_appliance_actions

            parsed_actions.append(action_dict)

        return parsed_actions

    @staticmethod
    def _action_table_candidate(actions: Mapping[str, Any], tables: Mapping[str, Any], name: str) -> Any:
        value = tables.get(name)
        if tables is actions and isinstance(value, Mapping):
            return None
        return value

    @staticmethod
    def _has_action_overrides(actions: Mapping[str, Any]) -> bool:
        raw_map = actions.get("map")
        if raw_map is not None:
            if not isinstance(raw_map, Mapping):
                raise AssertionError("Entity action 'map' must be a mapping keyed by canonical entity ids.")
            if len(raw_map) > 0:
                return True

        for key in ("building", "charger", "deferrable_appliance"):
            value = actions.get(key)
            if isinstance(value, Mapping) and len(value) > 0:
                return True

        return False

    def _resolve_map_overrides(self, actions: Mapping[str, Any]) -> Tuple[Mapping[str, Mapping[str, Any]], Mapping[str, Mapping[str, Any]], Mapping[str, Mapping[str, Any]]]:
        raw_map = actions.get("map")
        if raw_map is None:
            raw_map = {}
            legacy_building_map = actions.get("building") or {}
            legacy_charger_map = actions.get("charger") or {}
            legacy_deferrable_map = actions.get("deferrable_appliance") or {}
            if isinstance(legacy_building_map, Mapping):
                for key, payload in legacy_building_map.items():
                    raw_map[f"building:{key}"] = payload
            if isinstance(legacy_charger_map, Mapping):
                for key, payload in legacy_charger_map.items():
                    raw_map[f"charger:{key}"] = payload
            if isinstance(legacy_deferrable_map, Mapping):
                for key, payload in legacy_deferrable_map.items():
                    raw_map[f"deferrable_appliance:{key}"] = payload

        if not isinstance(raw_map, Mapping):
            raise AssertionError("Entity action 'map' must be a mapping keyed by canonical entity ids.")

        building_ids = set(self._building_ids)
        charger_global_ids = {ref.global_id for ref in self._charger_refs}
        charger_raw_to_global = {ref.charger_id: ref.global_id for ref in self._charger_refs}
        deferrable_global_ids = {ref.global_id for ref in self._deferrable_appliance_refs}
        deferrable_raw_to_global = {ref.appliance_id: ref.global_id for ref in self._deferrable_appliance_refs}
        building_overrides: Dict[str, Mapping[str, Any]] = {}
        charger_overrides: Dict[str, Mapping[str, Any]] = {}
        deferrable_appliance_overrides: Dict[str, Mapping[str, Any]] = {}

        for raw_id, payload in raw_map.items():
            if not isinstance(payload, Mapping):
                raise AssertionError(f"Entity action map entry for '{raw_id}' must be a mapping of action values.")

            raw_key = str(raw_id)
            entity_kind, entity_id = self._split_map_id(raw_key)

            if entity_kind is None:
                if raw_key in building_ids:
                    entity_kind, entity_id = "building", raw_key
                elif raw_key in charger_global_ids:
                    entity_kind, entity_id = "charger", raw_key
                elif raw_key in charger_raw_to_global:
                    entity_kind, entity_id = "charger", charger_raw_to_global[raw_key]
                elif raw_key in deferrable_global_ids:
                    entity_kind, entity_id = "deferrable_appliance", raw_key
                elif raw_key in deferrable_raw_to_global:
                    entity_kind, entity_id = "deferrable_appliance", deferrable_raw_to_global[raw_key]
                else:
                    raise AssertionError(f"Unknown entity id '{raw_key}' in action map.")

            if entity_kind == "building":
                if entity_id not in building_ids:
                    raise AssertionError(f"Unknown building id '{entity_id}' in action map.")
                building_overrides[entity_id] = dict(payload)
                continue

            if entity_kind == "charger":
                if entity_id in charger_raw_to_global:
                    entity_id = charger_raw_to_global[entity_id]
                if entity_id not in charger_global_ids:
                    raise AssertionError(f"Unknown charger id '{entity_id}' in action map.")
                charger_overrides[entity_id] = dict(payload)
                continue

            if entity_kind == "deferrable_appliance":
                if entity_id in deferrable_raw_to_global:
                    entity_id = deferrable_raw_to_global[entity_id]
                if entity_id not in deferrable_global_ids:
                    raise AssertionError(f"Unknown deferrable_appliance id '{entity_id}' in action map.")
                deferrable_appliance_overrides[entity_id] = dict(payload)
                continue

            raise AssertionError(f"Unknown entity kind '{entity_kind}' in action map id '{raw_key}'.")

        self._validate_override_keys(building_overrides, charger_overrides, deferrable_appliance_overrides)
        return building_overrides, charger_overrides, deferrable_appliance_overrides

    @staticmethod
    def _split_map_id(raw_key: str) -> Tuple[Optional[str], Optional[str]]:
        if ":" not in raw_key:
            return None, None
        entity_kind, entity_id = raw_key.split(":", 1)
        entity_kind = entity_kind.strip().lower()
        entity_id = entity_id.strip()
        if entity_kind == "" or entity_id == "":
            return None, None
        return entity_kind, entity_id

    def _validate_override_keys(
        self,
        building_overrides: Mapping[str, Mapping[str, Any]],
        charger_overrides: Mapping[str, Mapping[str, Any]],
        deferrable_appliance_overrides: Mapping[str, Mapping[str, Any]],
    ):
        for building in self.env.buildings:
            payload = building_overrides.get(building.name, {})
            if not payload:
                continue
            unknown = [key for key in payload.keys() if key not in set(building.active_actions)]
            if unknown:
                raise AssertionError(
                    f"Unknown building action keys for '{building.name}': {sorted(unknown)}."
                )

        for charger_global_id, payload in charger_overrides.items():
            unknown = [key for key in payload.keys() if key != "electric_vehicle_storage"]
            if unknown:
                raise AssertionError(
                    f"Unknown charger action keys for '{charger_global_id}': {sorted(unknown)}."
                )

        for appliance_global_id, payload in deferrable_appliance_overrides.items():
            unknown = [key for key in payload.keys() if key != "start"]
            if unknown:
                raise AssertionError(
                    f"Unknown deferrable_appliance action keys for '{appliance_global_id}': {sorted(unknown)}."
                )

    def _parse_flat_like(self, actions: Any) -> List[List[float]]:
        env = self.env

        def _is_scalar(value: Any) -> bool:
            return bool(np.isscalar(value))

        def _to_vector(value: Any, *, context: str) -> List[float]:
            if isinstance(value, np.ndarray):
                if value.ndim == 1:
                    return value.tolist()
                if value.ndim == 2 and value.shape[0] == 1:
                    return value[0].tolist()
                raise AssertionError(f"{context} must be a 1D action vector.")

            if isinstance(value, (list, tuple)):
                if len(value) == 0:
                    return []
                if all(_is_scalar(v) for v in value):
                    return list(value)
                if len(value) == 1 and isinstance(value[0], (list, tuple, np.ndarray)):
                    return _to_vector(value[0], context=context)
                raise AssertionError(f"{context} must be a 1D action vector.")

            raise AssertionError(f"{context} must be a 1D action vector.")

        vectors: List[List[float]]
        if env.central_agent:
            merged = _to_vector(actions, context="central_agent actions")
            expected = env._expected_central_action_count
            if len(merged) != expected:
                raise AssertionError(f"Expected {expected} actions but {len(merged)} were parsed to env.step.")
            vectors = []
            cursor = 0
            for building in env.buildings:
                size = building.action_space.shape[0]
                vectors.append(merged[cursor:cursor + size])
                cursor += size
        else:
            if isinstance(actions, np.ndarray):
                if actions.ndim != 2:
                    raise AssertionError("Expected one action vector per building when central_agent=False.")
                vectors = [row.tolist() for row in actions]
            elif isinstance(actions, (list, tuple)):
                vectors = [_to_vector(row, context=f"building action vector at index {idx}") for idx, row in enumerate(actions)]
            else:
                raise AssertionError("Expected one action vector per building when central_agent=False.")

            expected = len(env.buildings)
            if len(vectors) != expected:
                raise AssertionError(f"Expected {expected} building action vectors but {len(vectors)} were provided.")

        for building, vector in zip(env.buildings, vectors):
            expected = building.action_space.shape[0]
            if len(vector) != expected:
                raise AssertionError(f"Expected {expected} for {building.name} but {len(vector)} actions were provided.")

        return vectors

    def _map_vectors_to_action_dicts(self, vectors: Sequence[Sequence[float]]) -> List[Mapping[str, float]]:
        parsed_actions = []
        active_actions = self.env._active_actions_cache

        for i, _building in enumerate(self.env.buildings):
            action_dict = {}
            electric_vehicle_actions = {}
            deferrable_appliance_actions = {}

            for action_name, action in zip(active_actions[i], vectors[i]):
                if "electric_vehicle_storage" in action_name:
                    charger_id = action_name.replace("electric_vehicle_storage_", "")
                    electric_vehicle_actions[charger_id] = action
                elif action_name.startswith("deferrable_appliance_"):
                    deferrable_appliance_actions[action_name] = action
                else:
                    action_dict[f"{action_name}_action"] = action

            if electric_vehicle_actions:
                action_dict["electric_vehicle_storage_actions"] = electric_vehicle_actions
            if deferrable_appliance_actions:
                action_dict["deferrable_appliance_actions"] = deferrable_appliance_actions

            parsed_actions.append(action_dict)

        return parsed_actions

    def _resolve_observation_bundles(self) -> Mapping[str, bool]:
        schema = self.env.schema if isinstance(self.env.schema, Mapping) else {}
        raw = schema.get("observation_bundles", {}) if isinstance(schema, Mapping) else {}
        if not isinstance(raw, Mapping):
            raw = {}

        resolved = dict(self.DEFAULT_OBSERVATION_BUNDLES)
        for bundle_name in resolved:
            value = raw.get(bundle_name, False)
            if isinstance(value, Mapping):
                value = value.get("active", False)
            if isinstance(value, str):
                resolved[bundle_name] = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                resolved[bundle_name] = bool(value)

        return resolved

    def _bundle_enabled(self, bundle_name: str) -> bool:
        return bool(self._observation_bundles.get(bundle_name, False))

    def _step_hours(self) -> float:
        return max(float(self.env.seconds_per_time_step) / 3600.0, 1.0e-6)

    @staticmethod
    def _append_unique(target: List[str], values: Sequence[str]):
        for value in values:
            if value not in target:
                target.append(value)

    @classmethod
    def _derived_forecast_building_features(cls) -> List[str]:
        features: List[str] = []
        for label, _ in cls.FORECAST_HORIZONS:
            for signal in cls.DERIVED_FORECAST_BUILDING_SIGNALS:
                features.append(f"forecast_{signal}_next_{label}_kw")
        return features

    @classmethod
    def _derived_forecast_district_features(cls) -> List[str]:
        features: List[str] = []
        for label, _ in cls.FORECAST_HORIZONS:
            features.append(f"forecast_price_next_{label}")
            for signal in cls.DERIVED_FORECAST_DISTRICT_SIGNALS:
                features.append(f"forecast_community_{signal}_next_{label}_kw")
        return features

    def _forecast_config_meta(self) -> Mapping[str, Any]:
        config = self._derived_forecast_config()
        method = config["method"]
        return {
            "source": "actual_future" if method == "actual_future" else "mixed_causal",
            "type": "point",
            "load_pv_method": method,
            "price_source": config["price_source"],
            "price_horizon_steps": list(config["price_horizon_steps"]),
            "price_intermediate_horizon_alignment": (
                "realized_target"
                if config["price_source"] == "known_future_market_input"
                else "earliest_declared_horizon_with_historical_issue_time"
            ),
            "persistence_period_seconds": config["period_seconds"],
            "cold_start": config["cold_start"],
            "horizons": [label for label, _ in self.FORECAST_HORIZONS],
            "building_signals": list(self.DERIVED_FORECAST_BUILDING_SIGNALS),
            "district_signals": ["price", *[f"community_{signal}" for signal in self.DERIVED_FORECAST_DISTRICT_SIGNALS]],
        }

    def _derived_forecast_config(self) -> Mapping[str, Any]:
        schema = getattr(self.env, "schema", {}) or {}
        raw = schema.get("derived_forecasts", {}) if isinstance(schema, Mapping) else {}
        raw = raw if isinstance(raw, Mapping) else {}
        method = str(raw.get("load_pv_method", raw.get("method", "actual_future"))).strip().lower()
        if method not in {"actual_future", "daily_persistence"}:
            raise ValueError(
                "derived_forecasts.load_pv_method must be one of "
                "{'actual_future', 'daily_persistence'}."
            )

        period_seconds = float(raw.get("persistence_period_seconds", 24 * 60 * 60))
        if not np.isfinite(period_seconds) or period_seconds <= 0.0:
            raise ValueError("derived_forecasts.persistence_period_seconds must be > 0.")

        cold_start = str(raw.get("cold_start", "current_step")).strip().lower()
        if cold_start != "current_step":
            raise ValueError("derived_forecasts.cold_start currently supports only 'current_step'.")

        price_source = str(
            raw.get("price_source", "known_future_market_input")
        ).strip().lower()
        if price_source not in {
            "known_future_market_input",
            "publication_aware_day_ahead_market_input",
            "daily_persistence",
        }:
            raise ValueError(
                "derived_forecasts.price_source must be one of "
                "{'known_future_market_input', "
                "'publication_aware_day_ahead_market_input', "
                "'daily_persistence'}."
            )

        raw_price_horizons = raw.get("price_horizon_steps", [1, 2, 3])
        try:
            price_horizon_steps = tuple(int(value) for value in raw_price_horizons)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "derived_forecasts.price_horizon_steps must be an ordered sequence of positive integers."
            ) from exc
        if (
            len(price_horizon_steps) != 3
            or any(value <= 0 for value in price_horizon_steps)
            or tuple(sorted(price_horizon_steps)) != price_horizon_steps
            or len(set(price_horizon_steps)) != len(price_horizon_steps)
        ):
            raise ValueError(
                "derived_forecasts.price_horizon_steps must contain three strictly increasing positive integers."
            )

        return {
            "method": method,
            "period_seconds": period_seconds,
            "cold_start": cold_start,
            "price_source": price_source,
            "price_horizon_steps": price_horizon_steps,
        }

    @staticmethod
    def _series_mean(values: Sequence[float], indices: Sequence[int], fallback: float) -> float:
        filtered: List[float] = []
        for idx in indices:
            if idx < 0:
                continue
            try:
                value = float(values[idx])
            except Exception:
                continue
            if np.isfinite(value):
                filtered.append(value)
        if len(filtered) == 0:
            return float(fallback)
        return float(np.mean(filtered))

    @classmethod
    def _infer_unit(cls, name: str) -> str:
        key = str(name).lower()
        if key.endswith("_power_kw") or "headroom_kw" in key:
            return "kw"
        if key.endswith("_kw"):
            return "kw"
        if key.endswith("_hours") or key.startswith("hours_until_") or key in {"hours_until_departure"}:
            return "h"
        if key.endswith("_kwh_step"):
            return "kwh_step"
        if key.endswith("_capacity_kwh") or key.endswith("_kwh"):
            return "kwh"
        if key.endswith("_normalized"):
            return "ratio"
        if key in {"can_charge", "can_discharge", "must_start_now", "is_weekend", "start_blocked", "dr_active"} or key.startswith("clip_reason_"):
            return "flag"
        if key.endswith("_eur_per_kwh"):
            return "eur_per_kwh"
        if key.endswith("_soc_ratio") or key.endswith("_ratio") or key.endswith("_soc"):
            return "ratio"
        if key.endswith("_time_step"):
            return "time_step"
        if key.endswith("_count"):
            return "count"
        if key in {"hour", "day_type", "month", "minutes", "seconds"}:
            return "index"
        if "consumption" in key or "generation" in key or "demand" in key:
            return "kwh"
        return "scalar"

    def _feature_metadata_for_table(self, table_name: str, features: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
        bundle_map = self._table_feature_bundle.get(table_name, {})
        legacy_map = self._table_feature_legacy.get(table_name, {})
        metadata: Dict[str, Mapping[str, Any]] = {}

        for feature in features:
            metadata[feature] = {
                "unit": self._infer_unit(feature),
                "bundle": bundle_map.get(feature, "legacy"),
                "legacy": bool(legacy_map.get(feature, True)),
            }

        return metadata

    def _build_electrical_building_metrics(
        self,
        *,
        building,
        endogenous_t: int,
        control_t: int,
        step_hours: float,
    ) -> Mapping[str, float]:
        net_energy = self._safe_index(building.net_electricity_consumption, endogenous_t, 0.0)
        import_energy = max(net_energy, 0.0)
        export_energy = max(-net_energy, 0.0)
        pv_energy = abs(self._safe_index(building.solar_generation, endogenous_t, 0.0))
        bess_energy = self._safe_index(building.electrical_storage_electricity_consumption, endogenous_t, 0.0)
        ev_energy = self._safe_index(building.chargers_electricity_consumption, endogenous_t, 0.0)
        cooling = self._safe_index(building.cooling_electricity_consumption, endogenous_t, 0.0)
        heating = self._safe_index(building.heating_electricity_consumption, endogenous_t, 0.0)
        dhw = self._safe_index(building.dhw_electricity_consumption, endogenous_t, 0.0)
        non_shiftable = self._safe_index(building.non_shiftable_load_electricity_consumption, endogenous_t, 0.0)
        deferrable = self._safe_index(building.deferrable_appliances_electricity_consumption, endogenous_t, 0.0)
        load_energy = max(cooling + heating + dhw + non_shiftable + deferrable + ev_energy, 0.0)
        pv_surplus_energy = max(pv_energy - load_energy, 0.0)

        constraint_state = getattr(building, "_charging_constraints_state", {}) or {}
        building_headroom = constraint_state.get("building_headroom_kw")
        building_export_headroom = constraint_state.get("building_export_headroom_kw")
        phase_headroom = constraint_state.get("phase_headroom_kw") or {}
        phase_export_headroom = constraint_state.get("phase_export_headroom_kw") or {}
        phase_power = constraint_state.get("phase_power_kw") or {}
        total_service_power = self._safe_scalar(constraint_state.get("total_power_kw"), np.nan)
        if not np.isfinite(total_service_power):
            total_service_power = 0.0
        phase_headroom_sum = sum(
            self._safe_scalar(value, 0.0)
            for value in phase_headroom.values()
            if value is not None
        )
        phase_export_headroom_sum = sum(
            self._safe_scalar(value, 0.0)
            for value in phase_export_headroom.values()
            if value is not None
        )
        flexible_metrics = self._building_flexible_capacity_metrics(
            building=building,
            control_t=control_t,
            endogenous_t=endogenous_t,
            step_hours=step_hours,
        )

        metrics = {
            "net_power_kw": net_energy / step_hours,
            "net_energy_kwh_step": net_energy,
            "import_power_kw": import_energy / step_hours,
            "import_energy_kwh_step": import_energy,
            "export_power_kw": export_energy / step_hours,
            "export_energy_kwh_step": export_energy,
            "load_power_kw": load_energy / step_hours,
            "load_energy_kwh_step": load_energy,
            "pv_power_kw": pv_energy / step_hours,
            "pv_energy_kwh_step": pv_energy,
            "pv_surplus_power_kw": pv_surplus_energy / step_hours,
            "pv_surplus_energy_kwh_step": pv_surplus_energy,
            "bess_power_kw": bess_energy / step_hours,
            "bess_energy_kwh_step": bess_energy,
            "ev_charging_power_kw": ev_energy / step_hours,
            "ev_charging_energy_kwh_step": ev_energy,
            "electrical_storage_soc_ratio": self._safe_index(
                building.electrical_storage.soc,
                endogenous_t,
                0.0,
            ),
            "charging_total_service_power_kw": total_service_power,
            "building_import_headroom_kw": self._safe_scalar(building_headroom, 0.0),
            "building_export_headroom_kw": self._safe_scalar(building_export_headroom, 0.0),
            "import_phase_headroom_kw": phase_headroom_sum,
            "export_phase_headroom_kw": phase_export_headroom_sum,
            **flexible_metrics,
            "_building_headroom_kw": self._safe_scalar(building_headroom, np.nan),
            "_building_export_headroom_kw": self._safe_scalar(building_export_headroom, np.nan),
            "_phase_headroom_kw": phase_headroom_sum,
            "_phase_export_headroom_kw": phase_export_headroom_sum,
            "_control_time_step": float(control_t),
        }
        for phase_name in self._phase_names:
            metrics[f"charging_phase_{phase_name}_power_kw"] = self._safe_scalar(
                phase_power.get(phase_name, 0.0),
                0.0,
            )
        return metrics

    def _build_temporal_building_metrics(self, *, building, endogenous_t: int) -> Mapping[str, float]:
        prev_1 = max(endogenous_t, 0)
        net_prev_1 = self._safe_index(building.net_electricity_consumption, prev_1, 0.0)
        import_prev_1 = max(net_prev_1, 0.0)
        export_prev_1 = max(-net_prev_1, 0.0)
        indices = list(range(max(endogenous_t - 2, 0), endogenous_t + 1))
        if len(indices) == 0:
            indices = [prev_1]

        net_prev_3_mean = self._series_mean(
            building.net_electricity_consumption,
            indices,
            fallback=net_prev_1,
        )

        return {
            "net_energy_prev_1_kwh_step": net_prev_1,
            "net_energy_prev_3_mean_kwh_step": net_prev_3_mean,
            "import_energy_prev_1_kwh_step": import_prev_1,
            "export_energy_prev_1_kwh_step": export_prev_1,
        }

    def _build_calendar_temporal_metrics(self, *, building, time_step: int) -> Mapping[str, float]:
        hour = self._safe_index(getattr(building.energy_simulation, "hour", []), time_step, 1.0)
        minutes = self._safe_index(getattr(building.energy_simulation, "minutes", []), time_step, 0.0)
        seconds = self._safe_index(getattr(building.energy_simulation, "seconds", []), time_step, 0.0)
        day_type = self._safe_index(getattr(building.energy_simulation, "day_type", []), time_step, 1.0)
        month = self._safe_index(getattr(building.energy_simulation, "month", []), time_step, 1.0)

        hour_zero_based = (hour - 1.0) % 24.0
        seconds_of_day = hour_zero_based * 3600.0 + minutes * 60.0 + seconds

        def cyc(value: float, period: float) -> Tuple[float, float]:
            angle = 2.0 * np.pi * (float(value) % period) / period
            return float(np.sin(angle)), float(np.cos(angle))

        hour_sin, hour_cos = cyc(seconds_of_day, 24.0 * 3600.0)
        day_sin, day_cos = cyc(day_type - 1.0, 7.0)
        month_sin, month_cos = cyc(month - 1.0, 12.0)

        return {
            "hour_sin": hour_sin,
            "hour_cos": hour_cos,
            "day_type_sin": day_sin,
            "day_type_cos": day_cos,
            "month_sin": month_sin,
            "month_cos": month_cos,
            "seconds_of_day_sin": hour_sin,
            "seconds_of_day_cos": hour_cos,
            "is_weekend": 1.0 if int(round(day_type)) in {6, 7} else 0.0,
        }

    def _build_forecast_district_metrics(self, first_building_data: Mapping[str, Any]) -> Mapping[str, float]:
        forecasts: Dict[str, float] = {}
        for key, value in first_building_data.items():
            if "_predicted_" not in str(key):
                continue
            forecasts[str(key)] = self._safe_scalar(value, 0.0)
        return forecasts

    def _headroom_power_limit_for_connection(self, building, phase_connection: Optional[str], *, export: bool = False) -> float:
        state = getattr(building, "_charging_constraints_state", {}) or {}
        total_key = "building_export_headroom_kw" if export else "building_headroom_kw"
        phase_key = "phase_export_headroom_kw" if export else "phase_headroom_kw"
        limits: List[float] = []

        total_headroom = self._safe_scalar(state.get(total_key), np.nan)
        if np.isfinite(total_headroom):
            limits.append(max(total_headroom, 0.0))

        phase_headrooms = state.get(phase_key) or {}
        if isinstance(phase_headrooms, Mapping) and len(phase_headrooms) > 0:
            phase_names = [
                str(name)
                for name, value in phase_headrooms.items()
                if value is not None and np.isfinite(self._safe_scalar(value, np.nan))
            ]
            connection = None if phase_connection is None else str(phase_connection)

            if connection in phase_names:
                limits.append(max(self._safe_scalar(phase_headrooms.get(connection), 0.0), 0.0))
            else:
                split_mode = str(getattr(building, "_electrical_service_default_split", "balanced")).upper()
                if split_mode in phase_names and connection not in {"all_phases", "unassigned"}:
                    limits.append(max(self._safe_scalar(phase_headrooms.get(split_mode), 0.0), 0.0))
                elif len(phase_names) > 0:
                    finite_headrooms = [
                        max(self._safe_scalar(phase_headrooms.get(name), 0.0), 0.0)
                        for name in phase_names
                    ]
                    if len(finite_headrooms) > 0:
                        limits.append(min(finite_headrooms) * len(finite_headrooms))

        if len(limits) == 0:
            return float("inf")
        return float(min(limits))

    def _setpoint_power_limit_from_headroom(
        self,
        headroom_limit_kw: float,
        current_signed_power_kw: float,
        *,
        export: bool = False,
    ) -> float:
        """Convert remaining headroom into the admissible absolute setpoint for one asset."""

        headroom_limit_kw = self._safe_scalar(headroom_limit_kw, np.nan)
        if not np.isfinite(headroom_limit_kw):
            return float("inf")

        current_signed_power_kw = self._safe_scalar(current_signed_power_kw, 0.0)
        adjusted_limit = (
            headroom_limit_kw - current_signed_power_kw
            if export
            else headroom_limit_kw + current_signed_power_kw
        )
        return max(adjusted_limit, 0.0)

    def _charger_core_decision_metrics(
        self,
        *,
        building,
        charger,
        connected: bool,
        current_soc: float,
        battery_capacity: float,
        required_soc: float,
        energy_to_required_soc: float,
        required_average_power: float,
        hours_until_departure: float,
        max_charging_power: float,
        max_discharging_power: float,
        charge_efficiency_at_max: float,
        discharge_efficiency_at_max: float,
        step_hours: float,
        current_power_kw: float = 0.0,
    ) -> Mapping[str, float]:
        if not connected or battery_capacity <= 0.0 or current_soc < 0.0:
            return {
                "connected_ev_soc_min_ratio": -1.0,
                "connected_ev_energy_available_kwh": 0.0,
                "connected_ev_energy_to_full_kwh": 0.0,
                "can_charge": 0.0,
                "can_discharge": 0.0,
                "available_charge_power_kw": 0.0,
                "available_discharge_power_kw": 0.0,
                "available_charge_action_normalized": 0.0,
                "available_discharge_action_normalized": 0.0,
                "max_deliverable_energy_until_departure_kwh": 0.0,
                "departure_energy_margin_kwh": 0.0,
                "departure_feasibility_ratio": -1.0,
                "min_required_action_normalized": 0.0,
            }

        battery = getattr(charger.connected_electric_vehicle, "battery", None)
        depth_of_discharge = self._safe_scalar(getattr(battery, "depth_of_discharge", 1.0), 1.0)
        soc_min = float(np.clip(1.0 - depth_of_discharge, 0.0, 1.0))
        energy_available = max((current_soc - soc_min) * battery_capacity, 0.0)
        energy_to_full = max((1.0 - current_soc) * battery_capacity, 0.0)
        outage = bool(getattr(building, "power_outage", False))

        charge_efficiency = max(self._safe_scalar(charge_efficiency_at_max, 1.0), 1.0e-6)
        discharge_efficiency = max(self._safe_scalar(discharge_efficiency_at_max, 1.0), 1.0e-6)
        charge_power_by_soc = energy_to_full / max(charge_efficiency * step_hours, 1.0e-6)
        discharge_power_by_soc = energy_available * discharge_efficiency / max(step_hours, 1.0e-6)

        current_power_kw = self._safe_scalar(current_power_kw, 0.0)
        import_limit = self._setpoint_power_limit_from_headroom(
            self._headroom_power_limit_for_connection(building, getattr(charger, "phase_connection", None), export=False),
            current_power_kw,
            export=False,
        )
        export_limit = self._setpoint_power_limit_from_headroom(
            self._headroom_power_limit_for_connection(building, getattr(charger, "phase_connection", None), export=True),
            current_power_kw,
            export=True,
        )
        charge_candidates = [max(max_charging_power, 0.0), charge_power_by_soc]
        discharge_candidates = [max(max_discharging_power, 0.0), discharge_power_by_soc]
        if np.isfinite(import_limit):
            charge_candidates.append(import_limit)
        if np.isfinite(export_limit):
            discharge_candidates.append(export_limit)

        available_charge_power = 0.0 if outage else max(min(charge_candidates), 0.0)
        available_discharge_power = 0.0 if outage else max(min(discharge_candidates), 0.0)
        # Battery headroom limits energy actually accepted in the last interval,
        # not the minimum viable charger command. Below the charger deadband a
        # positive command produces no energy at all. Permit the minimum command
        # when the electrical envelope allows it; battery physics clips the fill.
        available_charge_request = available_charge_power
        minimum_charge_power = max(self._safe_scalar(getattr(charger, 'min_charging_power', 0.0), 0.0), 0.0)
        command_limit = max(max_charging_power, 0.0)
        if np.isfinite(import_limit):
            command_limit = min(command_limit, max(import_limit, 0.0))
        if available_charge_power > 0.0:
            if command_limit + 1.0e-9 < minimum_charge_power:
                available_charge_request = 0.0
            else:
                available_charge_request = min(max(available_charge_power, minimum_charge_power), command_limit)
        max_deliverable = min(
            available_charge_power * max(hours_until_departure, 0.0) * charge_efficiency,
            energy_to_full,
        )
        departure_margin = max_deliverable - max(energy_to_required_soc, 0.0)
        departure_feasibility = (
            max(energy_to_required_soc, 0.0) / max(max_deliverable, 1.0e-6)
            if energy_to_required_soc > 0.0
            else 0.0
        )
        min_required_action = (
            required_average_power / max(max_charging_power, 1.0e-6)
            if required_average_power > 0.0
            else 0.0
        )
        if hours_until_departure < 0.0:
            max_deliverable = departure_margin = min_required_action = 0.0
            departure_feasibility = -1.0

        return {
            "connected_ev_soc_min_ratio": soc_min,
            "connected_ev_energy_available_kwh": energy_available,
            "connected_ev_energy_to_full_kwh": energy_to_full,
            "can_charge": 1.0 if available_charge_request > 1.0e-9 else 0.0,
            "can_discharge": 1.0 if available_discharge_power > 1.0e-9 else 0.0,
            "available_charge_power_kw": available_charge_power,
            "available_discharge_power_kw": available_discharge_power,
            "available_charge_action_normalized": available_charge_request / max(max_charging_power, 1.0e-6),
            "available_discharge_action_normalized": available_discharge_power / max(max_discharging_power, 1.0e-6),
            "max_deliverable_energy_until_departure_kwh": max_deliverable,
            "departure_energy_margin_kwh": departure_margin,
            "departure_feasibility_ratio": departure_feasibility,
            "min_required_action_normalized": min_required_action,
        }

    def _storage_core_decision_metrics(
        self,
        *,
        building,
        storage,
        soc: float,
        capacity: float,
        nominal_power: float,
        soc_min: float,
        energy_to_full: float,
        energy_available: float,
        max_charge_power: float,
        max_discharge_power: float,
        efficiency: float,
        step_hours: float,
        include_headroom: bool = True,
        current_power_kw: float = 0.0,
    ) -> Mapping[str, float]:
        efficiency = max(self._safe_scalar(efficiency, 1.0), 1.0e-6)
        charge_power_by_soc = energy_to_full / max(efficiency * step_hours, 1.0e-6)
        discharge_power_by_soc = energy_available * efficiency / max(step_hours, 1.0e-6)

        charge_candidates = [max(max_charge_power, 0.0), charge_power_by_soc]
        discharge_candidates = [max(max_discharge_power, 0.0), discharge_power_by_soc]
        if include_headroom:
            connection = getattr(building, "electrical_storage_phase_connection", None)
            current_power_kw = self._safe_scalar(current_power_kw, 0.0)
            import_limit = self._setpoint_power_limit_from_headroom(
                self._headroom_power_limit_for_connection(building, connection, export=False),
                current_power_kw,
                export=False,
            )
            export_limit = self._setpoint_power_limit_from_headroom(
                self._headroom_power_limit_for_connection(building, connection, export=True),
                current_power_kw,
                export=True,
            )
            if np.isfinite(import_limit):
                charge_candidates.append(import_limit)
            if np.isfinite(export_limit):
                discharge_candidates.append(export_limit)

        outage = bool(getattr(building, "power_outage", False))
        available_charge_power = 0.0 if outage else max(min(charge_candidates), 0.0)
        available_discharge_power = 0.0 if outage else max(min(discharge_candidates), 0.0)
        usable_denominator = max(1.0 - soc_min, 1.0e-6)

        return {
            "can_charge": 1.0 if available_charge_power > 1.0e-9 else 0.0,
            "can_discharge": 1.0 if available_discharge_power > 1.0e-9 else 0.0,
            "available_charge_power_kw": available_charge_power,
            "available_discharge_power_kw": available_discharge_power,
            "available_charge_action_normalized": available_charge_power / max(nominal_power, 1.0e-6),
            "available_discharge_action_normalized": available_discharge_power / max(nominal_power, 1.0e-6),
            "available_charge_energy_kwh_step": available_charge_power * step_hours,
            "available_discharge_energy_kwh_step": available_discharge_power * step_hours,
            "max_charge_energy_kwh_step": max(max_charge_power, 0.0) * step_hours,
            "max_discharge_energy_kwh_step": max(max_discharge_power, 0.0) * step_hours,
            "charge_headroom_ratio": energy_to_full / max(capacity, 1.0e-6),
            "discharge_available_ratio": energy_available / max(capacity, 1.0e-6),
            "usable_soc_ratio": float(np.clip((soc - soc_min) / usable_denominator, 0.0, 1.0)),
        }

    def _building_flexible_capacity_metrics(
        self,
        *,
        building,
        control_t: int,
        endogenous_t: int,
        step_hours: float,
    ) -> Mapping[str, float]:
        charge_power = 0.0
        discharge_power = 0.0
        energy_to_full = 0.0
        energy_available = 0.0

        storage = getattr(building, "electrical_storage", None)
        if storage is not None:
            capacity = self._safe_scalar(getattr(storage, "capacity", 0.0), 0.0)
            nominal_power = self._safe_scalar(getattr(storage, "nominal_power", 0.0), 0.0)
            soc = self._safe_index(getattr(storage, "soc", []), endogenous_t, 0.0)
            depth_of_discharge = self._safe_scalar(getattr(storage, "depth_of_discharge", 1.0), 1.0)
            soc_min = max(1.0 - depth_of_discharge, 0.0)
            current_energy = soc * max(capacity, 0.0)
            storage_energy_to_full = max(capacity - current_energy, 0.0)
            storage_energy_available = max((soc - soc_min) * max(capacity, 0.0), 0.0)
            max_charge_power = (
                self._safe_scalar(storage.get_max_input_power(), nominal_power)
                if hasattr(storage, "get_max_input_power")
                else nominal_power
            )
            max_discharge_power = (
                self._safe_scalar(storage.get_max_output_power(), nominal_power)
                if hasattr(storage, "get_max_output_power")
                else nominal_power
            )
            storage_metrics = self._storage_core_decision_metrics(
                building=building,
                storage=storage,
                soc=soc,
                capacity=capacity,
                nominal_power=nominal_power,
                soc_min=soc_min,
                energy_to_full=storage_energy_to_full,
                energy_available=storage_energy_available,
                max_charge_power=max_charge_power,
                max_discharge_power=max_discharge_power,
                efficiency=self._safe_scalar(getattr(storage, "efficiency", 1.0), 1.0),
                step_hours=step_hours,
                include_headroom=False,
            )
            charge_power += self._safe_scalar(storage_metrics.get("available_charge_power_kw", 0.0), 0.0)
            discharge_power += self._safe_scalar(storage_metrics.get("available_discharge_power_kw", 0.0), 0.0)
            energy_to_full += storage_energy_to_full
            energy_available += storage_energy_available

        for charger in building.electric_vehicle_chargers or []:
            sim = getattr(charger, "charger_simulation", None)
            state = self._safe_index(getattr(sim, "electric_vehicle_charger_state", []), control_t, np.nan)
            if state != 1 or charger.connected_electric_vehicle is None:
                continue

            ev = charger.connected_electric_vehicle
            battery = getattr(ev, "battery", None)
            capacity = self._safe_scalar(getattr(battery, "capacity", 0.0), 0.0)
            soc = self._safe_index(getattr(battery, "soc", []), endogenous_t, 0.0)
            if capacity <= 0.0 or soc < 0.0:
                continue

            depth_of_discharge = self._safe_scalar(getattr(battery, "depth_of_discharge", 1.0), 1.0)
            soc_min = max(1.0 - depth_of_discharge, 0.0)
            ev_energy_to_full = max((1.0 - soc) * capacity, 0.0)
            ev_energy_available = max((soc - soc_min) * capacity, 0.0)
            max_charge_power = self._safe_scalar(getattr(charger, "max_charging_power", 0.0), 0.0)
            max_discharge_power = self._safe_scalar(getattr(charger, "max_discharging_power", 0.0), 0.0)
            charge_efficiency = self._safe_scalar(
                charger.get_efficiency(1.0, True) if hasattr(charger, "get_efficiency") else getattr(charger, "efficiency", 1.0),
                1.0,
            )
            discharge_efficiency = self._safe_scalar(
                charger.get_efficiency(1.0, False) if hasattr(charger, "get_efficiency") else getattr(charger, "efficiency", 1.0),
                1.0,
            )
            charge_power += min(
                max(max_charge_power, 0.0),
                ev_energy_to_full / max(charge_efficiency * step_hours, 1.0e-6),
            )
            discharge_power += min(
                max(max_discharge_power, 0.0),
                ev_energy_available * max(discharge_efficiency, 1.0e-6) / max(step_hours, 1.0e-6),
            )
            energy_to_full += ev_energy_to_full
            energy_available += ev_energy_available

        return {
            "flexible_charge_power_capacity_kw": charge_power,
            "flexible_discharge_power_capacity_kw": discharge_power,
            "flexible_charge_energy_capacity_kwh_step": charge_power * step_hours,
            "flexible_discharge_energy_capacity_kwh_step": discharge_power * step_hours,
            "flexible_energy_to_full_kwh": energy_to_full,
            "flexible_energy_available_kwh": energy_available,
        }

    def _deferrable_core_decision_metrics(self, appliance, observations: Mapping[str, float]) -> Mapping[str, float]:
        step_hours = self._step_hours()
        current_global_fn = getattr(appliance, "_current_global_time_step", None)
        try:
            current_step = int(current_global_fn()) if callable(current_global_fn) else int(getattr(appliance, "time_step", self.env.time_step))
        except Exception:
            current_step = int(getattr(self.env, "time_step", 0))

        earliest = self._safe_scalar(observations.get("earliest_start_time_step", -1.0), -1.0)
        latest = self._safe_scalar(observations.get("latest_start_time_step", -1.0), -1.0)
        pending = self._safe_scalar(observations.get("pending", 0.0), 0.0) > 0.0
        cycle_energy = self._safe_scalar(observations.get("cycle_energy_kwh", 0.0), 0.0)
        remaining_energy = self._safe_scalar(observations.get("remaining_energy_kwh", 0.0), 0.0)
        remaining_duration_steps = self._safe_scalar(observations.get("remaining_duration_steps", 0.0), 0.0)

        try:
            start_energy = self._safe_scalar(appliance.preview_start_energy_kwh(1.0), 0.0)
        except Exception:
            start_energy = 0.0

        hours_until_earliest = max(earliest - current_step, 0.0) * step_hours if pending and earliest >= 0.0 else -1.0
        start_window_width = max(latest - earliest, 0.0) * step_hours if pending and earliest >= 0.0 and latest >= 0.0 else 0.0
        must_start_now = 1.0 if pending and latest >= 0.0 and latest <= float(current_step) else 0.0

        return {
            "remaining_duration_hours": max(remaining_duration_steps, 0.0) * step_hours,
            "cycle_remaining_fraction_ratio": remaining_energy / max(cycle_energy, 1.0e-6) if cycle_energy > 0.0 else 0.0,
            "hours_until_earliest_start": hours_until_earliest,
            "start_window_width_hours": start_window_width,
            "start_energy_kwh_step": start_energy,
            "start_power_kw": start_energy / step_hours,
            "must_start_now": must_start_now,
        }

    def _feedback_reason_metrics(self, owner, index: int) -> Mapping[str, float]:
        metrics = {}
        for reason in (
            "availability",
            "power_limit",
            "soc_limit",
            "building_headroom",
            "phase_headroom",
            "export_headroom",
            "outage",
            "deferrable_window",
        ):
            key = f"clip_reason_{reason}"
            values = getattr(owner, f"action_feedback_{key}", [])
            metrics[key] = self._safe_index(values, index, 0.0)
        return metrics

    def _feedback_window_indices(self, index: int, window_seconds: float = 15 * 60) -> List[int]:
        step_seconds = max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
        steps = max(int(np.ceil(float(window_seconds) / step_seconds)), 1)
        end = max(int(index), 0)
        start = max(end - steps + 1, 0)
        return list(range(start, end + 1))

    def _action_feedback_last_nonzero_index(
        self,
        values: Sequence[float],
        index: int,
        cache_key: Any,
    ) -> Tuple[int, int]:
        try:
            length = len(values)
        except Exception:
            length = 0
        if length <= 0:
            return -1, -1

        target = min(max(int(index), 0), length - 1)
        cache_key = id(values) if cache_key is None else cache_key
        cached = self._action_feedback_series_cache.get(cache_key)
        if cached is None or int(cached.get("target", -1)) > target:
            last_nonzero = -1
            for previous in range(target, -1, -1):
                if abs(self._safe_index(values, previous, 0.0)) > 1.0e-9:
                    last_nonzero = previous
                    break
            self._action_feedback_series_cache[cache_key] = {
                "target": target,
                "last_nonzero": last_nonzero,
            }
            return last_nonzero, target

        current_target = int(cached.get("target", -1))
        last_nonzero = int(cached.get("last_nonzero", -1))
        while current_target < target:
            current_target += 1
            if abs(self._safe_index(values, current_target, 0.0)) > 1.0e-9:
                last_nonzero = current_target

        cached["target"] = target
        cached["last_nonzero"] = last_nonzero
        return last_nonzero, target

    def _action_feedback_applied_window_metrics(
        self,
        values: Sequence[float],
        index: int,
        step_hours: float,
        *,
        window_seconds: float = 15 * 60,
        cache_key: Any = None,
    ) -> Tuple[float, float, float]:
        try:
            length = len(values)
        except Exception:
            length = 0
        if length <= 0:
            return 0.0, 0.0, -1.0

        target = min(max(int(index), 0), length - 1)
        step_seconds = max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
        steps = max(int(np.ceil(float(window_seconds) / step_seconds)), 1)
        start = max(target - steps + 1, 0)
        stop = target + 1
        window_values = np.asarray(values[start:stop], dtype="float64")
        window_energy = float(np.nan_to_num(window_values, nan=0.0, posinf=0.0, neginf=0.0).sum())
        window_count = max(stop - start, 1)
        mean_power = window_energy / max(float(window_count) * step_hours, 1.0e-12)
        last_nonzero, _ = self._action_feedback_last_nonzero_index(values, target, cache_key)
        time_since = float((target - last_nonzero) * step_hours) if last_nonzero >= 0 else -1.0
        return window_energy, mean_power, time_since

    def _charger_action_feedback_metrics(self, charger, index: int, step_hours: float) -> Mapping[str, float]:
        applied_values = getattr(charger, "electricity_consumption", [])
        requested_action = self._safe_index(getattr(charger, "action_feedback_requested_action_normalized", []), index, 0.0)
        limited_action = self._safe_index(getattr(charger, "action_feedback_limited_action_normalized", []), index, 0.0)
        requested_power = self._safe_index(getattr(charger, "action_feedback_requested_power_kw", []), index, 0.0)
        limited_power = self._safe_index(getattr(charger, "action_feedback_limited_power_kw", []), index, 0.0)
        applied_energy = self._safe_index(applied_values, index, 0.0)
        applied_power = applied_energy / step_hours
        window_energy, window_power_mean, time_since_nonzero = self._action_feedback_applied_window_metrics(
            applied_values,
            index,
            step_hours,
            cache_key=(id(charger), "charger_applied_energy"),
        )

        return {
            "last_requested_action_normalized": requested_action,
            "last_limited_action_normalized": limited_action,
            "last_requested_power_kw": requested_power,
            "last_limited_power_kw": limited_power,
            "last_applied_power_kw": applied_power,
            "last_projection_error_kw": requested_power - applied_power,
            "applied_energy_prev_15m_kwh": window_energy,
            "applied_power_mean_prev_15m_kw": window_power_mean,
            "time_since_last_nonzero_action_hours": time_since_nonzero,
            **self._feedback_reason_metrics(charger, index),
        }

    def _storage_action_feedback_metrics(self, building, index: int, step_hours: float) -> Mapping[str, float]:
        applied_values = getattr(building, "electrical_storage_electricity_consumption", [])
        requested_action = self._safe_index(getattr(building, "action_feedback_electrical_storage_requested_action_normalized", []), index, 0.0)
        limited_action = self._safe_index(getattr(building, "action_feedback_electrical_storage_limited_action_normalized", []), index, 0.0)
        requested_power = self._safe_index(getattr(building, "action_feedback_electrical_storage_requested_power_kw", []), index, 0.0)
        limited_power = self._safe_index(getattr(building, "action_feedback_electrical_storage_limited_power_kw", []), index, 0.0)
        applied_energy = self._safe_index(applied_values, index, 0.0)
        applied_power = applied_energy / step_hours
        window_energy, window_power_mean, time_since_nonzero = self._action_feedback_applied_window_metrics(
            applied_values,
            index,
            step_hours,
            cache_key=(id(building), "storage_applied_energy"),
        )

        metrics = {
            "last_requested_action_normalized": requested_action,
            "last_limited_action_normalized": limited_action,
            "last_requested_power_kw": requested_power,
            "last_limited_power_kw": limited_power,
            "last_applied_power_kw": applied_power,
            "last_projection_error_kw": requested_power - applied_power,
            "applied_energy_prev_15m_kwh": window_energy,
            "applied_power_mean_prev_15m_kw": window_power_mean,
            "time_since_last_nonzero_action_hours": time_since_nonzero,
        }
        for reason in (
            "availability",
            "power_limit",
            "soc_limit",
            "building_headroom",
            "phase_headroom",
            "export_headroom",
            "outage",
            "deferrable_window",
        ):
            key = f"clip_reason_{reason}"
            metrics[key] = self._safe_index(
                getattr(building, f"action_feedback_electrical_storage_{key}", []),
                index,
                0.0,
            )
        return metrics

    def _deferrable_action_feedback_metrics(self, appliance, index: int) -> Mapping[str, float]:
        return {
            "last_start_requested": self._safe_index(
                getattr(appliance, "action_feedback_last_start_requested", []),
                index,
                0.0,
            ),
            "last_start_applied": self._safe_index(
                getattr(appliance, "action_feedback_last_start_applied", []),
                index,
                0.0,
            ),
            "start_blocked": self._safe_index(
                getattr(appliance, "action_feedback_start_blocked", []),
                index,
                0.0,
            ),
            **self._feedback_reason_metrics(appliance, index),
        }

    def _dataset_energy_to_control_step_for_building(self, building, energy_kwh: float) -> float:
        ratio = getattr(building, "time_step_ratio", None)
        ratio = 1.0 if ratio in (None, 0) else float(ratio)
        return self._safe_scalar(energy_kwh, 0.0) * ratio

    def _forecast_point_index(self, time_step: int, horizon_seconds: float, length: int) -> int:
        if length <= 0:
            return -1

        step_seconds = max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
        steps_ahead = max(int(np.ceil(float(horizon_seconds) / step_seconds)), 1)
        return self._forecast_point_index_from_steps(time_step, steps_ahead, length)

    @staticmethod
    def _forecast_point_index_from_steps(time_step: int, steps_ahead: int, length: int) -> int:
        if length <= 0:
            return -1

        return min(max(int(time_step) + int(steps_ahead), 0), length - 1)

    def _derived_forecast_point_index_from_steps(
        self,
        time_step: int,
        steps_ahead: int,
        length: int,
    ) -> int:
        """Resolve a load/PV forecast source without accidental future leakage."""

        target = self._forecast_point_index_from_steps(time_step, steps_ahead, length)
        if target < 0:
            return target

        config = self._derived_forecast_config()
        if config["method"] == "actual_future":
            return target

        step_seconds = max(
            float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0),
            1.0,
        )
        period_steps = max(1, int(round(config["period_seconds"] / step_seconds)))
        source = target - period_steps
        current = min(max(int(time_step), 0), length - 1)
        if source < 0 or source > current:
            return current

        return source

    def _derived_price_forecast_value(
        self,
        pricing,
        time_step: int,
        steps_ahead: int,
    ) -> float:
        """Return a price forecast without reading unpublished future truth.

        Publication-aware datasets expose three declared forecast horizons.
        A requested intermediate horizon is aligned to the shortest available
        horizon that can target the same delivery step, issued far enough in
        the past that its array index is no later than the current step.  This
        makes 15-minute and 3-hour entity features causal even though the base
        CityLearn pricing contract stores only three forecast columns.
        """

        actual = getattr(pricing, "electricity_pricing", [])
        length = len(actual)
        target = self._forecast_point_index_from_steps(
            time_step,
            steps_ahead,
            length,
        )
        if target < 0:
            return 0.0

        config = self._derived_forecast_config()
        price_source = config["price_source"]
        if price_source == "known_future_market_input":
            return self._safe_index(actual, target, 0.0)

        current = min(max(int(time_step), 0), length - 1)
        if price_source == "publication_aware_day_ahead_market_input":
            forecast_series = (
                getattr(pricing, "electricity_pricing_predicted_1", []),
                getattr(pricing, "electricity_pricing_predicted_2", []),
                getattr(pricing, "electricity_pricing_predicted_3", []),
            )
            for declared_horizon, values in zip(
                config["price_horizon_steps"],
                forecast_series,
            ):
                if declared_horizon < int(steps_ahead):
                    continue

                issue_step = current - (declared_horizon - int(steps_ahead))
                if issue_step >= 0 and len(values) == length:
                    return self._safe_index(values, issue_step, 0.0)

        period_steps = max(
            1,
            int(round(
                config["period_seconds"]
                / max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
            )),
        )
        source = target - period_steps
        if source < 0 or source > current:
            source = current
        return self._safe_index(actual, source, 0.0)

    def _building_forecast_components_at_step(
        self,
        building,
        step: int,
        *,
        include_deferrable: bool = True,
    ) -> Tuple[float, float, float]:
        step_hours = self._step_hours()
        temperature = self._safe_index(getattr(building.weather, "outdoor_dry_bulb_temperature", []), step, 0.0)
        energy_simulation = building.energy_simulation

        non_shiftable = self._dataset_energy_to_control_step_for_building(
            building,
            self._safe_index(getattr(energy_simulation, "non_shiftable_load", []), step, 0.0),
        )
        cooling_demand = self._dataset_energy_to_control_step_for_building(
            building,
            self._safe_index(getattr(energy_simulation, "cooling_demand", []), step, 0.0),
        )
        heating_demand = self._dataset_energy_to_control_step_for_building(
            building,
            self._safe_index(getattr(energy_simulation, "heating_demand", []), step, 0.0),
        )
        dhw_demand = self._dataset_energy_to_control_step_for_building(
            building,
            self._safe_index(getattr(energy_simulation, "dhw_demand", []), step, 0.0),
        )

        cooling = self._safe_scalar(building.cooling_device.get_input_power(cooling_demand, temperature, heating=False), 0.0)
        if building.heating_device.__class__.__name__ == "HeatPump":
            heating = self._safe_scalar(building.heating_device.get_input_power(heating_demand, temperature, heating=True), 0.0)
        else:
            heating = self._safe_scalar(building.heating_device.get_input_power(heating_demand), 0.0)
        if building.dhw_device.__class__.__name__ == "HeatPump":
            dhw = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand, temperature, heating=True), 0.0)
        else:
            dhw = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand), 0.0)
        deferrable = 0.0
        if include_deferrable:
            deferrable = sum(
                self._safe_index(getattr(appliance, "electricity_consumption", []), step, 0.0)
                for appliance in building.deferrable_appliances or []
            )
        load_energy = max(non_shiftable + cooling + heating + dhw + deferrable, 0.0)
        try:
            solar_generation = building._pv_generation_to_control_step([
                self._safe_index(getattr(energy_simulation, "solar_generation", []), step, 0.0)
            ])
            pv_energy = abs(self._safe_index(solar_generation, 0, 0.0))
        except Exception:
            pv_energy = abs(self._safe_index(getattr(building, "solar_generation", []), step, 0.0))

        load_kw = load_energy / step_hours
        pv_kw = pv_energy / step_hours
        net_kw = load_kw - pv_kw
        return load_kw, pv_kw, net_kw

    def _build_derived_forecast_building_metrics(self, *, building, time_step: int) -> Mapping[str, float]:
        metrics: Dict[str, float] = {}
        length = len(getattr(building.energy_simulation, "non_shiftable_load", []))

        for label, steps_ahead in self._forecast_step_offsets:
            point_index = self._derived_forecast_point_index_from_steps(
                time_step,
                steps_ahead,
                length,
            )
            load_kw, pv_kw, net_kw = (
                self._building_forecast_components_at_step(building, point_index, include_deferrable=True)
                if point_index >= 0 else (0.0, 0.0, 0.0)
            )
            metrics[f"forecast_load_next_{label}_kw"] = load_kw
            metrics[f"forecast_pv_next_{label}_kw"] = pv_kw
            metrics[f"forecast_net_next_{label}_kw"] = net_kw

        return metrics

    def _build_derived_forecast_district_metrics(
        self,
        *,
        time_step: int,
        community_values: Optional[Mapping[str, Mapping[str, float]]] = None,
    ) -> Mapping[str, float]:
        metrics: Dict[str, float] = {}
        if len(self.env.buildings) == 0:
            return metrics
        first = self.env.buildings[0]

        for label, steps_ahead in self._forecast_step_offsets:
            metrics[f"forecast_price_next_{label}"] = self._derived_price_forecast_value(
                first.pricing,
                time_step,
                steps_ahead,
            )
            if community_values is None:
                label_values = {signal: 0.0 for signal in self.DERIVED_FORECAST_DISTRICT_SIGNALS}
                for building in self.env.buildings:
                    length = len(getattr(building.energy_simulation, "non_shiftable_load", []))
                    point_index = self._derived_forecast_point_index_from_steps(
                        time_step,
                        steps_ahead,
                        length,
                    )
                    if point_index < 0:
                        continue
                    load_kw, pv_kw, net_kw = self._building_forecast_components_at_step(
                        building,
                        point_index,
                        include_deferrable=True,
                    )
                    label_values["load"] += load_kw
                    label_values["pv"] += pv_kw
                    label_values["net"] += net_kw
            else:
                label_values = community_values.get(label, {})

            for signal in self.DERIVED_FORECAST_DISTRICT_SIGNALS:
                value = self._safe_scalar(label_values.get(signal, 0.0), 0.0)
                metrics[f"forecast_community_{signal}_next_{label}_kw"] = float(value)

        return metrics

    def _build_community_district_metrics(
        self,
        building_electrical_metrics: Sequence[Mapping[str, float]],
    ) -> Mapping[str, float]:
        step_hours = self._step_hours()
        net_energy = sum(self._safe_scalar(m.get("net_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        import_energy = sum(self._safe_scalar(m.get("import_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        export_energy = sum(self._safe_scalar(m.get("export_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        pv_energy = sum(self._safe_scalar(m.get("pv_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        bess_energy = sum(self._safe_scalar(m.get("bess_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        ev_energy = sum(self._safe_scalar(m.get("ev_charging_energy_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_charge_power = sum(self._safe_scalar(m.get("flexible_charge_power_capacity_kw", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_discharge_power = sum(self._safe_scalar(m.get("flexible_discharge_power_capacity_kw", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_charge_energy = sum(self._safe_scalar(m.get("flexible_charge_energy_capacity_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_discharge_energy = sum(self._safe_scalar(m.get("flexible_discharge_energy_capacity_kwh_step", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_energy_to_full = sum(self._safe_scalar(m.get("flexible_energy_to_full_kwh", 0.0), 0.0) for m in building_electrical_metrics)
        flexible_energy_available = sum(self._safe_scalar(m.get("flexible_energy_available_kwh", 0.0), 0.0) for m in building_electrical_metrics)

        building_headroom = [
            self._safe_scalar(m.get("_building_headroom_kw"), np.nan) for m in building_electrical_metrics
        ]
        building_export_headroom = [
            self._safe_scalar(m.get("_building_export_headroom_kw"), np.nan) for m in building_electrical_metrics
        ]
        community_building_headroom = sum(v for v in building_headroom if np.isfinite(v))
        community_building_export_headroom = sum(v for v in building_export_headroom if np.isfinite(v))
        community_phase_headroom = sum(
            self._safe_scalar(m.get("_phase_headroom_kw", 0.0), 0.0) for m in building_electrical_metrics
        )
        community_phase_export_headroom = sum(
            self._safe_scalar(m.get("_phase_export_headroom_kw", 0.0), 0.0) for m in building_electrical_metrics
        )

        return {
            "community_net_power_kw": net_energy / step_hours,
            "community_net_energy_kwh_step": net_energy,
            "community_import_power_kw": import_energy / step_hours,
            "community_import_energy_kwh_step": import_energy,
            "community_export_power_kw": export_energy / step_hours,
            "community_export_energy_kwh_step": export_energy,
            "community_pv_power_kw": pv_energy / step_hours,
            "community_pv_energy_kwh_step": pv_energy,
            "community_bess_power_kw": bess_energy / step_hours,
            "community_bess_energy_kwh_step": bess_energy,
            "community_ev_power_kw": ev_energy / step_hours,
            "community_ev_energy_kwh_step": ev_energy,
            "community_building_headroom_kw": community_building_headroom,
            "community_building_export_headroom_kw": community_building_export_headroom,
            "community_phase_headroom_kw": community_phase_headroom,
            "community_phase_export_headroom_kw": community_phase_export_headroom,
            "community_flexible_charge_power_capacity_kw": flexible_charge_power,
            "community_flexible_discharge_power_capacity_kw": flexible_discharge_power,
            "community_flexible_charge_energy_capacity_kwh_step": flexible_charge_energy,
            "community_flexible_discharge_energy_capacity_kwh_step": flexible_discharge_energy,
            "community_flexible_energy_to_full_kwh": flexible_energy_to_full,
            "community_flexible_energy_available_kwh": flexible_energy_available,
            "active_buildings_count": float(len(self.env.buildings)),
            "active_chargers_count": float(sum(len(b.electric_vehicle_chargers or []) for b in self.env.buildings)),
            "active_evs_count": float(len(self.env.electric_vehicles)),
            "topology_version": float(getattr(self.env, "topology_version", 0)),
        }

    def _build_temporal_district_metrics(
        self,
        *,
        endogenous_t: int,
    ) -> Mapping[str, float]:
        prev_1 = max(endogenous_t, 0)
        community_net_prev_1 = sum(
            self._safe_index(building.net_electricity_consumption, prev_1, 0.0)
            for building in self.env.buildings
        )
        indices = list(range(max(endogenous_t - 2, 0), endogenous_t + 1))
        if len(indices) == 0:
            indices = [prev_1]

        aggregate_window = []
        for idx in indices:
            aggregate_window.append(
                sum(self._safe_index(building.net_electricity_consumption, idx, 0.0) for building in self.env.buildings)
            )

        community_net_prev_3_mean = float(np.mean(aggregate_window)) if len(aggregate_window) > 0 else community_net_prev_1
        return {
            "community_net_prev_1_kwh_step": community_net_prev_1,
            "community_net_prev_3_mean_kwh_step": community_net_prev_3_mean,
        }

    def _build_entity_layout(self):
        env = self.env
        self._building_ids = [b.name for b in env.buildings]
        self._ev_ids = [ev.name for ev in env.electric_vehicles]
        self._ev_row_by_name = {name: i for i, name in enumerate(self._ev_ids)}

        self._charger_refs: List[ChargerRef] = []
        row = 0
        for b_idx, building in enumerate(env.buildings):
            for charger in building.electric_vehicle_chargers or []:
                global_id = f"{building.name}/{charger.charger_id}"
                self._charger_refs.append(
                    ChargerRef(
                        row=row,
                        building_index=b_idx,
                        building_name=building.name,
                        charger_id=charger.charger_id,
                        global_id=global_id,
                    )
                )
                row += 1

        self._storage_refs: List[StorageRef] = []
        storage_row = 0
        for b_idx, building in enumerate(env.buildings):
            if self._has_electrical_storage(building):
                storage_id = "electrical_storage"
                global_id = f"{building.name}/{storage_id}"
                self._storage_refs.append(
                    StorageRef(
                        row=storage_row,
                        building_index=b_idx,
                        building_name=building.name,
                        storage_id=storage_id,
                        global_id=global_id,
                    )
                )
                storage_row += 1

        self._pv_refs: List[PVRef] = []
        pv_row = 0
        for b_idx, building in enumerate(env.buildings):
            if not self._has_pv_asset(building):
                continue
            pv_id = "pv"
            global_id = f"{building.name}/{pv_id}"
            self._pv_refs.append(
                PVRef(
                    row=pv_row,
                    building_index=b_idx,
                    building_name=building.name,
                    pv_id=pv_id,
                    global_id=global_id,
                )
            )
            pv_row += 1

        self._deferrable_appliance_refs: List[DeferrableApplianceRef] = []
        deferrable_row = 0
        for b_idx, building in enumerate(env.buildings):
            for appliance in building.deferrable_appliances or []:
                global_id = f"{building.name}/{appliance.name}"
                self._deferrable_appliance_refs.append(
                    DeferrableApplianceRef(
                        row=deferrable_row,
                        building_index=b_idx,
                        building_name=building.name,
                        appliance_id=appliance.name,
                        global_id=global_id,
                    )
                )
                deferrable_row += 1

        self._charger_row_by_global_id = {ref.global_id: ref.row for ref in self._charger_refs}
        self._charger_row_by_raw_id = {ref.charger_id: ref.row for ref in self._charger_refs}
        self._charger_row_by_building_and_raw_id = {
            (ref.building_index, ref.charger_id): ref.row for ref in self._charger_refs
        }
        self._phase_names: List[str] = []
        for building in env.buildings:
            if not getattr(building, "_include_phase_encoding", False):
                continue
            phase_names = [
                str(phase.get("name"))
                for phase in getattr(building, "_phase_limits", []) or []
                if isinstance(phase, Mapping) and phase.get("name")
            ]
            if not phase_names:
                phase_names = [
                    str(phase_name)
                    for phase_name in getattr(building, "_phase_encoding_phase_names", []) or []
                    if str(phase_name) not in {"all_phases", "unassigned"}
                ]
            for phase_name in phase_names:
                if phase_name not in self._phase_names:
                    self._phase_names.append(phase_name)
        self._charger_phase_names = list(self._phase_names)
        self._storage_phase_names = list(self._phase_names)
        self._charger_row_by_ev_action_name = {}
        self._deferrable_appliance_by_building_and_id = {}
        for b_idx, building in enumerate(env.buildings):
            for appliance in building.deferrable_appliances or []:
                self._deferrable_appliance_by_building_and_id[(b_idx, appliance.name)] = appliance
        self._deferrable_appliance_row_by_global_id = {ref.global_id: ref.row for ref in self._deferrable_appliance_refs}
        self._deferrable_appliance_row_by_raw_id = {ref.appliance_id: ref.row for ref in self._deferrable_appliance_refs}
        self._deferrable_appliance_row_by_building_and_raw_id = {
            (ref.building_index, ref.appliance_id): ref.row for ref in self._deferrable_appliance_refs
        }
        self._deferrable_appliance_row_by_action_name = {}

        shared = set(env.shared_observations)
        self._district_features = []
        if len(env.buildings) > 0:
            for name in env.buildings[0].active_observations:
                if name in shared and not self._is_entity_specific_observation(name):
                    self._district_features.append(name)

        self._building_features = []
        for building in env.buildings:
            for name in building.active_observations:
                if name in shared or self._is_entity_specific_observation(name):
                    continue
                if name not in self._building_features:
                    self._building_features.append(name)

        self._table_feature_bundle: Dict[str, Dict[str, str]] = {
            "district": {},
            "building": {},
            "charger": {},
            "ev": {},
            "storage": {},
            "pv": {},
            "deferrable_appliance": {},
        }
        self._table_feature_legacy: Dict[str, Dict[str, bool]] = {
            "district": {},
            "building": {},
            "charger": {},
            "ev": {},
            "storage": {},
            "pv": {},
            "deferrable_appliance": {},
        }

        for name in self._district_features:
            bundle_name = self.FORECAST_BUNDLE if "_predicted_" in str(name) else "legacy"
            self._table_feature_bundle["district"][name] = bundle_name
            self._table_feature_legacy["district"][name] = True

        for name in self._building_features:
            self._table_feature_bundle["building"][name] = "legacy"
            self._table_feature_legacy["building"][name] = True

        if self._bundle_enabled(self.CORE_BUNDLE):
            self._append_unique(self._building_features, self.CORE_BUILDING_EXTRA_FEATURES)
            for name in self.CORE_BUILDING_EXTRA_FEATURES:
                self._table_feature_bundle["building"][name] = self.CORE_BUNDLE
                self._table_feature_legacy["building"][name] = False
            self._building_phase_power_features = [f"charging_phase_{phase_name}_power_kw" for phase_name in self._phase_names]
            self._append_unique(self._building_features, self._building_phase_power_features)
            for name in self._building_phase_power_features:
                self._table_feature_bundle["building"][name] = self.CORE_BUNDLE
                self._table_feature_legacy["building"][name] = False
        else:
            self._building_phase_power_features = []

        if self._bundle_enabled(self.TEMPORAL_BUNDLE):
            self._append_unique(self._building_features, self.TEMPORAL_BUILDING_FEATURES)
            for name in self.TEMPORAL_BUILDING_FEATURES:
                self._table_feature_bundle["building"][name] = self.TEMPORAL_BUNDLE
                self._table_feature_legacy["building"][name] = False

        if self._bundle_enabled(self.COMMUNITY_BUNDLE):
            self._append_unique(self._district_features, self.COMMUNITY_DISTRICT_EXTRA_FEATURES)
            for name in self.COMMUNITY_DISTRICT_EXTRA_FEATURES:
                self._table_feature_bundle["district"][name] = self.COMMUNITY_BUNDLE
                self._table_feature_legacy["district"][name] = False

        if self._bundle_enabled(self.TEMPORAL_BUNDLE):
            self._append_unique(self._district_features, self.TEMPORAL_DISTRICT_FEATURES)
            for name in self.TEMPORAL_DISTRICT_FEATURES:
                self._table_feature_bundle["district"][name] = self.TEMPORAL_BUNDLE
                self._table_feature_legacy["district"][name] = False

        if self._bundle_enabled(self.DEMAND_RESPONSE_BUNDLE):
            self._append_unique(self._district_features, self.DEMAND_RESPONSE_DISTRICT_FEATURES)
            for name in self.DEMAND_RESPONSE_DISTRICT_FEATURES:
                self._table_feature_bundle["district"][name] = self.DEMAND_RESPONSE_BUNDLE
                self._table_feature_legacy["district"][name] = False

        if self._bundle_enabled(self.ROBUSTNESS_BUNDLE):
            self._append_unique(self._district_features, self.ROBUSTNESS_DISTRICT_FEATURES)
            for name in self.ROBUSTNESS_DISTRICT_FEATURES:
                self._table_feature_bundle["district"][name] = self.ROBUSTNESS_BUNDLE
                self._table_feature_legacy["district"][name] = False

        if self._bundle_enabled(self.DERIVED_FORECAST_BUNDLE):
            derived_district_features = self._derived_forecast_district_features()
            self._append_unique(self._district_features, derived_district_features)
            for name in derived_district_features:
                self._table_feature_bundle["district"][name] = self.DERIVED_FORECAST_BUNDLE
                self._table_feature_legacy["district"][name] = False

            derived_building_features = self._derived_forecast_building_features()
            self._append_unique(self._building_features, derived_building_features)
            for name in derived_building_features:
                self._table_feature_bundle["building"][name] = self.DERIVED_FORECAST_BUNDLE
                self._table_feature_legacy["building"][name] = False

        if self._bundle_enabled(self.FORECAST_BUNDLE) and len(env.buildings) > 0:
            current = env.buildings[0]._get_observations_data(include_all=False)
            forecast_keys = [key for key in current if "_predicted_" in str(key)]
            self._append_unique(self._district_features, forecast_keys)
            for name in forecast_keys:
                self._table_feature_bundle["district"][name] = self.FORECAST_BUNDLE
                self._table_feature_legacy["district"][name] = True

        self._charger_features = list(self.LEGACY_CHARGER_FEATURES)
        for name in self.LEGACY_CHARGER_FEATURES:
            self._table_feature_bundle["charger"][name] = "legacy"
            self._table_feature_legacy["charger"][name] = True
        self._append_unique(self._charger_features, self.BASE_CHARGER_FEATURES)
        for name in self.BASE_CHARGER_FEATURES:
            self._table_feature_bundle["charger"][name] = self.BASE_BUNDLE
            self._table_feature_legacy["charger"][name] = False
        if self._bundle_enabled(self.CORE_BUNDLE):
            self._append_unique(self._charger_features, self.EXTRA_CHARGER_FEATURES)
            for name in self.EXTRA_CHARGER_FEATURES:
                self._table_feature_bundle["charger"][name] = self.CORE_BUNDLE
                self._table_feature_legacy["charger"][name] = False
        if self._bundle_enabled(self.ACTION_FEEDBACK_BUNDLE):
            self._append_unique(self._charger_features, self.ACTION_FEEDBACK_FEATURES)
            for name in self.ACTION_FEEDBACK_FEATURES:
                self._table_feature_bundle["charger"][name] = self.ACTION_FEEDBACK_BUNDLE
                self._table_feature_legacy["charger"][name] = False
        self._charger_phase_features = [f"phase_connection_{phase_name}" for phase_name in self._charger_phase_names]
        self._append_unique(self._charger_features, self._charger_phase_features)
        for name in self._charger_phase_features:
            self._table_feature_bundle["charger"][name] = self.BASE_BUNDLE
            self._table_feature_legacy["charger"][name] = False

        self._ev_features = list(self.LEGACY_EV_FEATURES)
        for name in self.LEGACY_EV_FEATURES:
            self._table_feature_bundle["ev"][name] = "legacy"
            self._table_feature_legacy["ev"][name] = True
        if self._bundle_enabled(self.CORE_BUNDLE):
            self._append_unique(self._ev_features, self.EXTRA_EV_FEATURES)
            for name in self.EXTRA_EV_FEATURES:
                self._table_feature_bundle["ev"][name] = self.CORE_BUNDLE
                self._table_feature_legacy["ev"][name] = False

        self._storage_features = list(self.LEGACY_STORAGE_FEATURES)
        for name in self.LEGACY_STORAGE_FEATURES:
            self._table_feature_bundle["storage"][name] = "legacy"
            self._table_feature_legacy["storage"][name] = True
        self._append_unique(self._storage_features, self.BASE_STORAGE_FEATURES)
        for name in self.BASE_STORAGE_FEATURES:
            self._table_feature_bundle["storage"][name] = self.BASE_BUNDLE
            self._table_feature_legacy["storage"][name] = False
        if self._bundle_enabled(self.CORE_BUNDLE):
            self._append_unique(self._storage_features, self.EXTRA_STORAGE_FEATURES)
            for name in self.EXTRA_STORAGE_FEATURES:
                self._table_feature_bundle["storage"][name] = self.CORE_BUNDLE
                self._table_feature_legacy["storage"][name] = False
        if self._bundle_enabled(self.ACTION_FEEDBACK_BUNDLE):
            self._append_unique(self._storage_features, self.ACTION_FEEDBACK_FEATURES)
            for name in self.ACTION_FEEDBACK_FEATURES:
                self._table_feature_bundle["storage"][name] = self.ACTION_FEEDBACK_BUNDLE
                self._table_feature_legacy["storage"][name] = False
        self._storage_phase_features = [f"phase_connection_{phase_name}" for phase_name in self._storage_phase_names]
        self._append_unique(self._storage_features, self._storage_phase_features)
        for name in self._storage_phase_features:
            self._table_feature_bundle["storage"][name] = self.BASE_BUNDLE
            self._table_feature_legacy["storage"][name] = False

        self._pv_features = list(self.PV_FEATURES) if self._bundle_enabled(self.CORE_BUNDLE) else []
        for name in self._pv_features:
            self._table_feature_bundle["pv"][name] = self.CORE_BUNDLE
            self._table_feature_legacy["pv"][name] = False

        self._deferrable_appliance_features = list(self.DEFERRABLE_APPLIANCE_FEATURES)
        for name in self._deferrable_appliance_features:
            self._table_feature_bundle["deferrable_appliance"][name] = self.BASE_BUNDLE
            self._table_feature_legacy["deferrable_appliance"][name] = False
        if self._bundle_enabled(self.ACTION_FEEDBACK_BUNDLE):
            self._append_unique(self._deferrable_appliance_features, self.DEFERRABLE_ACTION_FEEDBACK_FEATURES)
            for name in self.DEFERRABLE_ACTION_FEEDBACK_FEATURES:
                self._table_feature_bundle["deferrable_appliance"][name] = self.ACTION_FEEDBACK_BUNDLE
                self._table_feature_legacy["deferrable_appliance"][name] = False

        self._building_action_features = []
        self._charger_action_features = []
        self._deferrable_appliance_action_features = []
        for b_idx, building in enumerate(env.buildings):
            for action_name in building.active_actions:
                if action_name.startswith("electric_vehicle_storage_"):
                    charger_id = action_name.replace("electric_vehicle_storage_", "")
                    resolved_row = self._charger_row_by_building_and_raw_id.get((b_idx, charger_id))
                    if resolved_row is None:
                        resolved_row = self._charger_row_by_raw_id.get(charger_id)
                    if resolved_row is not None:
                        self._charger_row_by_ev_action_name[(b_idx, action_name)] = resolved_row
                    if "electric_vehicle_storage" not in self._charger_action_features:
                        self._charger_action_features.append("electric_vehicle_storage")
                elif action_name.startswith("deferrable_appliance_"):
                    appliance_id = action_name.replace("deferrable_appliance_", "", 1)
                    resolved_row = self._deferrable_appliance_row_by_building_and_raw_id.get((b_idx, appliance_id))
                    if resolved_row is None:
                        resolved_row = self._deferrable_appliance_row_by_raw_id.get(appliance_id)
                    if resolved_row is not None:
                        self._deferrable_appliance_row_by_action_name[(b_idx, action_name)] = resolved_row
                    if "start" not in self._deferrable_appliance_action_features:
                        self._deferrable_appliance_action_features.append("start")
                elif action_name not in self._building_action_features:
                    self._building_action_features.append(action_name)

        self._building_action_col_by_name = {name: i for i, name in enumerate(self._building_action_features)}
        self._charger_action_col_by_name = {name: i for i, name in enumerate(self._charger_action_features)}
        self._deferrable_appliance_action_col_by_name = {name: i for i, name in enumerate(self._deferrable_appliance_action_features)}
        self._district_base_observation_names = tuple(
            name for name in self._district_features
            if self._table_feature_legacy["district"].get(name, False)
        )
        self._building_base_observation_names = tuple(
            name for name in self._building_features
            if self._table_feature_legacy["building"].get(name, False)
        )
        self._first_building_base_observation_names = tuple(
            dict.fromkeys(self._building_base_observation_names + self._district_base_observation_names)
        )

        self._district_obs = np.zeros((1, len(self._district_features)), dtype=np.float32)
        self._building_obs = np.zeros((len(self._building_ids), len(self._building_features)), dtype=np.float32)
        self._charger_obs = np.zeros((len(self._charger_refs), len(self._charger_features)), dtype=np.float32)
        self._ev_obs = np.zeros((len(self._ev_ids), len(self._ev_features)), dtype=np.float32)
        self._storage_obs = np.zeros((len(self._storage_refs), len(self._storage_features)), dtype=np.float32)
        self._pv_obs = np.zeros((len(self._pv_refs), len(self._pv_features)), dtype=np.float32)
        self._deferrable_appliance_obs = np.zeros((len(self._deferrable_appliance_refs), len(self._deferrable_appliance_features)), dtype=np.float32)
        self._district_feature_cols = {name: i for i, name in enumerate(self._district_features)}
        self._building_feature_cols = {name: i for i, name in enumerate(self._building_features)}
        self._charger_feature_cols = {name: i for i, name in enumerate(self._charger_features)}
        self._ev_feature_cols = {name: i for i, name in enumerate(self._ev_features)}
        self._storage_feature_cols = {name: i for i, name in enumerate(self._storage_features)}
        self._pv_feature_cols = {name: i for i, name in enumerate(self._pv_features)}
        self._deferrable_appliance_feature_cols = {
            name: i for i, name in enumerate(self._deferrable_appliance_features)
        }
        step_seconds = max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
        self._forecast_step_offsets = tuple(
            (label, max(int(np.ceil(float(seconds) / step_seconds)), 1))
            for label, seconds in self.FORECAST_HORIZONS
        )
        self._build_static_observation_rows()

        self._district_to_building = np.zeros((len(self._building_ids), 2), dtype=np.int32)
        if len(self._building_ids) > 0:
            self._district_to_building[:, 1] = np.arange(len(self._building_ids), dtype=np.int32)

        self._building_to_charger = np.full((len(self._charger_refs), 2), -1, dtype=np.int32)
        for ref in self._charger_refs:
            self._building_to_charger[ref.row] = np.array([ref.building_index, ref.row], dtype=np.int32)

        self._building_to_storage = np.full((len(self._storage_refs), 2), -1, dtype=np.int32)
        for ref in self._storage_refs:
            self._building_to_storage[ref.row] = np.array([ref.building_index, ref.row], dtype=np.int32)

        self._building_to_pv = np.full((len(self._pv_refs), 2), -1, dtype=np.int32)
        for ref in self._pv_refs:
            self._building_to_pv[ref.row] = np.array([ref.building_index, ref.row], dtype=np.int32)

        self._building_to_deferrable_appliance = np.full((len(self._deferrable_appliance_refs), 2), -1, dtype=np.int32)
        for ref in self._deferrable_appliance_refs:
            self._building_to_deferrable_appliance[ref.row] = np.array([ref.building_index, ref.row], dtype=np.int32)

        self._charger_to_ev_connected = np.full((len(self._charger_refs), 2), -1, dtype=np.int32)
        self._charger_to_ev_connected_mask = np.zeros((len(self._charger_refs),), dtype=np.float32)
        self._charger_to_ev_incoming = np.full((len(self._charger_refs), 2), -1, dtype=np.int32)
        self._charger_to_ev_incoming_mask = np.zeros((len(self._charger_refs),), dtype=np.float32)

    def _build_static_observation_rows(self):
        entity_layout.build_static_observation_rows(self)

    def _build_spaces(self):
        entity_layout.build_spaces(self)

    def _build_specs(self):
        entity_layout.build_specs(self)

    def _default_bounds_for_feature(self, name: str) -> Tuple[float, float]:
        key = str(name).lower()
        if key.endswith("_sin") or key.endswith("_cos"):
            return -1.0, 1.0
        if key in {
            "is_weekend",
            "start_blocked",
            "last_start_requested",
            "last_start_applied",
            "can_charge",
            "can_discharge",
            "must_start_now",
            "dr_active",
        }:
            return 0.0, 1.0
        if key == "dr_direction":
            return -1.0, 1.0
        if key == "dr_issuer_code":
            return 0.0, 2.0
        if key.endswith("_eur_per_kwh"):
            return 0.0, 1.0e6
        if key.startswith("clip_reason_"):
            return 0.0, 1.0
        if key in {"departure_feasibility_ratio", "min_required_action_normalized"}:
            return -1.0, 1.0e6
        if key in {"available_charge_action_normalized", "available_discharge_action_normalized"}:
            return 0.0, 1.0
        if key.endswith("_action_normalized") or key in {"last_requested_action_normalized", "last_limited_action_normalized"}:
            return -1.0, 1.0
        if key.startswith("time_since_"):
            return -1.0, float(max(self.env.time_steps, 1)) * self._step_hours()
        if key.endswith("_soc_ratio") or key.endswith("_ratio"):
            return 0.0, 1.0
        if key.endswith("_time_step"):
            return -1.0, float(max(self.env.time_steps, 1))
        if key.endswith("_count"):
            upper = float(max(len(self._building_ids), len(self._charger_refs), len(self._ev_ids), 1))
            return 0.0, upper
        if key.endswith("_power_kw") or "headroom_kw" in key:
            return -1.0e6, 1.0e6
        if key.endswith("_kwh_step"):
            return -1.0e6, 1.0e6
        if key.endswith("_capacity_kwh") or key.endswith("_kwh"):
            return -1.0e6, 1.0e6
        return -1.0e6, 1.0e6

    def _charger_time_high_limit(self) -> float:
        high = float(max(getattr(self.env, 'time_steps', 0) or 0, 1))
        for ref in self._charger_refs:
            building = self.env.buildings[ref.building_index]
            charger = building._charger_lookup.get(ref.charger_id)
            simulation = getattr(charger, 'charger_simulation', None)
            if simulation is None:
                continue
            for attribute in (
                'electric_vehicle_departure_time',
                'electric_vehicle_estimated_arrival_time',
            ):
                raw_values = np.array(getattr(simulation, attribute, []), dtype='float64')
                values = raw_values[np.isfinite(raw_values) & (raw_values >= 0.0)]
                if values.size > 0:
                    high = max(high, float(np.nanmax(values)))
        return high

    def _deferrable_time_high_limit(self) -> float:
        high = float(max(getattr(self.env, 'time_steps', 0) or 0, 1))
        for ref in self._deferrable_appliance_refs:
            appliance = self._deferrable_appliance_by_building_and_id.get((ref.building_index, ref.appliance_id))
            simulation = getattr(appliance, 'deferrable_appliance_simulation', None)
            for cycle in getattr(simulation, 'flexibility_schedule', []) or []:
                for key in ('earliest_start_time_step', 'latest_start_time_step', 'deadline_time_step'):
                    try:
                        value = float(cycle.get(key, -1.0))
                    except Exception:
                        value = -1.0
                    if np.isfinite(value) and value >= 0.0:
                        high = max(high, value)
        return high

    def _observation_bounds_for_features(self, names: Sequence[str], *, owner: str, per_building: bool = False):
        if owner == "district":
            if len(names) == 0:
                return np.zeros((1, 0), dtype=np.float32), np.zeros((1, 0), dtype=np.float32)
            if len(self.env.buildings) == 0:
                zeros = np.zeros((1, len(names)), dtype=np.float32)
                return zeros.copy(), zeros
            building = self.env.buildings[0]
            low_map, high_map = building.estimate_observation_space_limits(include_all=True, periodic_normalization=False)
            low_values: List[float] = []
            high_values: List[float] = []
            for name in names:
                default_low, default_high = self._default_bounds_for_feature(name)
                key = str(name).lower()
                if (
                    getattr(self.env, "topology_mode", "static") == "dynamic"
                    and key in {"solar_generation", "electrical_storage_soc"}
                ):
                    low_values.append(float(default_low))
                    high_values.append(float(default_high))
                    continue
                if "headroom_kw" in key:
                    low_values.append(float(default_low))
                    high_values.append(float(default_high))
                    continue
                low_values.append(self._safe_scalar(low_map.get(name, default_low), default_low))
                high_values.append(self._safe_scalar(high_map.get(name, default_high), default_high))
            low = np.array([low_values], dtype=np.float32)
            high = np.array([high_values], dtype=np.float32)
            return low, high

        if not per_building:
            return np.zeros((len(self._building_ids), 0), dtype=np.float32), np.zeros((len(self._building_ids), 0), dtype=np.float32)

        rows = len(self._building_ids)
        cols = len(names)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)
        if cols == 0:
            return low, high

        for i, building in enumerate(self.env.buildings):
            low_map, high_map = building.estimate_observation_space_limits(include_all=True, periodic_normalization=False)
            for j, name in enumerate(names):
                default_low, default_high = self._default_bounds_for_feature(name)
                key = str(name).lower()
                if (
                    getattr(self.env, "topology_mode", "static") == "dynamic"
                    and key in {"solar_generation", "electrical_storage_soc"}
                ):
                    low[i, j] = float(default_low)
                    high[i, j] = float(default_high)
                    continue
                if "headroom_kw" in key:
                    low[i, j] = float(default_low)
                    high[i, j] = float(default_high)
                    continue
                low[i, j] = self._safe_scalar(low_map.get(name, default_low), default_low)
                high[i, j] = self._safe_scalar(high_map.get(name, default_high), default_high)

        return low, high

    def _charger_observation_bounds(self):
        rows = len(self._charger_refs)
        cols = len(self._charger_features)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)
        if rows == 0:
            return low, high

        step_hours = self._step_hours()
        max_departure = self._charger_time_high_limit()
        max_capacity = max([self._safe_scalar(ev.battery.capacity, 0.0) for ev in self.env.electric_vehicles] + [0.0])
        charging_limits = [
            self._safe_scalar(charger.max_charging_power, 0.0)
            for building in self.env.buildings
            for charger in (building.electric_vehicle_chargers or [])
        ]
        min_charging_limits = [
            self._safe_scalar(getattr(charger, "min_charging_power", 0.0), 0.0)
            for building in self.env.buildings
            for charger in (building.electric_vehicle_chargers or [])
        ]
        discharging_limits = [
            self._safe_scalar(charger.max_discharging_power, 0.0)
            for building in self.env.buildings
            for charger in (building.electric_vehicle_chargers or [])
        ]
        min_discharging_limits = [
            self._safe_scalar(getattr(charger, "min_discharging_power", 0.0), 0.0)
            for building in self.env.buildings
            for charger in (building.electric_vehicle_chargers or [])
        ]
        max_charge_kw = max(charging_limits + [0.0])
        max_discharge_kw = max(discharging_limits + [0.0])
        max_min_charge_kw = max(min_charging_limits + [0.0])
        max_min_discharge_kw = max(min_discharging_limits + [0.0])
        max_abs_power_kw = max(max_charge_kw, max_discharge_kw, 1.0)
        max_energy_step = max_abs_power_kw * step_hours
        max_theoretical_avg_power = max(max_capacity / max(step_hours, 1.0e-6), max_abs_power_kw, 1.0)

        bounds = {
            "connected_state": (0.0, 1.0),
            "incoming_state": (0.0, 1.0),
            "connected_ev_soc": (-0.1, 1.0),
            "connected_ev_required_soc_departure": (-0.1, 1.0),
            "connected_ev_battery_capacity_kwh": (-1.0, max(max_capacity, 1.0)),
            "connected_ev_departure_time_step": (-1.0, max_departure),
            "incoming_ev_estimated_soc_arrival": (-0.1, 1.0),
            "incoming_ev_estimated_arrival_time_step": (-1.0, max_departure),
            "last_charged_kwh": (-max_energy_step, max_energy_step),
            "max_charging_power_kw": (0.0, max(max_charge_kw, 1.0)),
            "max_discharging_power_kw": (0.0, max(max_discharge_kw, 1.0)),
            "min_charging_power_kw": (0.0, max(max_min_charge_kw, 1.0)),
            "min_discharging_power_kw": (0.0, max(max_min_discharge_kw, 1.0)),
            "charger_efficiency_ratio": (0.0, 1.0),
            "commanded_power_kw": (-max_abs_power_kw, max_abs_power_kw),
            "applied_power_kw": (-max_abs_power_kw, max_abs_power_kw),
            "applied_energy_kwh_step": (-max_energy_step, max_energy_step),
            "hours_until_departure": (-1.0, max_departure * step_hours),
            "time_until_departure_ratio": (-1.0, 1.0),
            "energy_to_required_soc_kwh": (0.0, max(max_capacity, 1.0)),
            "required_average_power_kw": (0.0, max_theoretical_avg_power),
            "avg_power_to_departure_kw": (0.0, max_theoretical_avg_power),
            "charging_slack_kw": (-max_theoretical_avg_power, max(max_charge_kw, 1.0)),
            "charging_priority_ratio": (0.0, 1.0),
            "connected_ev_soc_min_ratio": (-1.0, 1.0),
            "connected_ev_energy_available_kwh": (0.0, max(max_capacity, 1.0)),
            "connected_ev_energy_to_full_kwh": (0.0, max(max_capacity, 1.0)),
            "can_charge": (0.0, 1.0),
            "can_discharge": (0.0, 1.0),
            "available_charge_power_kw": (0.0, max(max_charge_kw, 1.0)),
            "available_discharge_power_kw": (0.0, max(max_discharge_kw, 1.0)),
            "available_charge_action_normalized": (0.0, 1.0),
            "available_discharge_action_normalized": (0.0, 1.0),
            "max_deliverable_energy_until_departure_kwh": (0.0, max(max_capacity, max_charge_kw * max_departure * step_hours, 1.0)),
            "departure_energy_margin_kwh": (-max(max_capacity, 1.0), max(max_capacity, max_charge_kw * max_departure * step_hours, 1.0)),
            "departure_feasibility_ratio": (-1.0, 1.0e6),
            "min_required_action_normalized": (0.0, 1.0e6),
            "charge_efficiency_at_max_ratio": (0.0, 1.0),
            "discharge_efficiency_at_max_ratio": (0.0, 1.0),
            "incoming_ev_required_soc_departure": (-0.1, 1.0),
            "incoming_ev_departure_time_step": (-1.0, max_departure),
            "incoming_ev_hours_until_departure": (-1.0, max_departure * step_hours),
            "incoming_ev_time_until_departure_ratio": (-1.0, 1.0),
        }

        for j, feature in enumerate(self._charger_features):
            if str(feature).startswith("phase_connection_"):
                feature_low, feature_high = 0.0, 1.0
            else:
                feature_low, feature_high = bounds.get(feature, self._default_bounds_for_feature(feature))
            low[:, j] = feature_low
            high[:, j] = feature_high

        return low, high

    def _ev_observation_bounds(self):
        rows = len(self._ev_ids)
        cols = len(self._ev_features)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)
        if rows == 0:
            return low, high

        max_capacity = max([self._safe_scalar(ev.battery.capacity, 0.0) for ev in self.env.electric_vehicles] + [0.0])

        bounds = {
            "soc": (0.0, 1.0),
            "soc_ratio": (0.0, 1.0),
            "soc_min_ratio": (0.0, 1.0),
            "soc_max_ratio": (0.0, 1.0),
            "battery_capacity_kwh": (0.0, max(max_capacity, 1.0)),
            "depth_of_discharge_ratio": (0.0, 1.0),
            "energy_available_kwh": (0.0, max(max_capacity, 1.0)),
            "energy_to_full_kwh": (0.0, max(max_capacity, 1.0)),
        }

        for j, feature in enumerate(self._ev_features):
            feature_low, feature_high = bounds.get(feature, self._default_bounds_for_feature(feature))
            low[:, j] = feature_low
            high[:, j] = feature_high

        return low, high

    def _storage_observation_bounds(self):
        rows = len(self._storage_refs)
        cols = len(self._storage_features)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)

        if rows == 0:
            return low, high

        step_hours = self._step_hours()
        for ref in self._storage_refs:
            building = self.env.buildings[ref.building_index]
            storage = building.electrical_storage
            capacity = self._safe_scalar(getattr(storage, "capacity", 0.0), 0.0)
            nominal_power = self._safe_scalar(getattr(storage, "nominal_power", 0.0), 0.0)
            energy_limit = max(nominal_power * step_hours, 1.0)
            row = ref.row

            for col, feature in enumerate(self._storage_features):
                feature_low, feature_high = self._default_bounds_for_feature(feature)
                if feature in {"soc", "electrical_storage_soc_ratio"}:
                    feature_low, feature_high = 0.0, 1.0
                elif feature in {"capacity_kwh", "energy_to_full_kwh", "energy_available_kwh"}:
                    feature_low, feature_high = 0.0, max(capacity, 1.0)
                elif feature in {"nominal_power_kw", "max_charge_power_kw", "max_discharge_power_kw", "min_charge_power_kw", "min_discharge_power_kw"}:
                    feature_low, feature_high = 0.0, max(nominal_power, 1.0)
                elif feature in {"available_charge_power_kw", "available_discharge_power_kw"}:
                    feature_low, feature_high = 0.0, max(nominal_power, 1.0)
                elif feature in {"available_charge_action_normalized", "available_discharge_action_normalized"}:
                    feature_low, feature_high = 0.0, 1.0
                elif feature in {
                    "available_charge_energy_kwh_step",
                    "available_discharge_energy_kwh_step",
                    "max_charge_energy_kwh_step",
                    "max_discharge_energy_kwh_step",
                }:
                    feature_low, feature_high = 0.0, energy_limit
                elif feature in {"can_charge", "can_discharge", "charge_headroom_ratio", "discharge_available_ratio", "usable_soc_ratio"}:
                    feature_low, feature_high = 0.0, 1.0
                elif feature == "electricity_consumption_kwh":
                    feature_low, feature_high = -energy_limit, energy_limit
                elif feature in {"efficiency_ratio", "round_trip_efficiency_ratio", "current_efficiency_ratio", "soc_min_ratio"}:
                    feature_low, feature_high = 0.0, 1.0
                elif feature == "degraded_capacity_kwh":
                    feature_low, feature_high = 0.0, max(capacity, 1.0)
                elif str(feature).startswith("phase_connection_"):
                    feature_low, feature_high = 0.0, 1.0
                low[row, col] = feature_low
                high[row, col] = feature_high

        return low, high

    def _pv_observation_bounds(self):
        rows = len(self._pv_refs)
        cols = len(self._pv_features)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)
        if rows == 0:
            return low, high

        step_hours = self._step_hours()
        for ref in self._pv_refs:
            building = self.env.buildings[ref.building_index]
            installed_power = self._safe_scalar(getattr(building.pv, "nominal_power", 0.0), 0.0)
            row = ref.row
            for col, feature in enumerate(self._pv_features):
                if feature == "generation_power_kw":
                    low[row, col], high[row, col] = 0.0, max(installed_power, 1.0)
                elif feature == "generation_energy_kwh_step":
                    low[row, col], high[row, col] = 0.0, max(installed_power * step_hours, 1.0)
                elif feature == "installed_power_kw":
                    low[row, col], high[row, col] = 0.0, max(installed_power, 1.0)
                elif feature == "generation_capacity_factor_ratio":
                    max_generation_power = 0.0
                    try:
                        max_generation_power = float(np.nanmax(np.abs(building.solar_generation)) / step_hours)
                    except Exception:
                        max_generation_power = installed_power
                    high_ratio = max_generation_power / installed_power if installed_power > 0.0 else 1.0
                    low[row, col], high[row, col] = 0.0, max(high_ratio, 1.0)
                else:
                    low[row, col], high[row, col] = self._default_bounds_for_feature(feature)
        return low, high

    def _deferrable_appliance_observation_bounds(self):
        rows = len(self._deferrable_appliance_refs)
        cols = len(self._deferrable_appliance_features)
        low = np.full((rows, cols), -1.0e6, dtype=np.float32)
        high = np.full((rows, cols), 1.0e6, dtype=np.float32)
        if rows == 0:
            return low, high

        max_time_step = self._deferrable_time_high_limit()
        max_energy = 1.0
        max_duration = 1.0
        max_power = 1.0
        for ref in self._deferrable_appliance_refs:
            appliance = self._deferrable_appliance_by_building_and_id.get((ref.building_index, ref.appliance_id))
            if appliance is None:
                continue
            for cycle in appliance.deferrable_appliance_simulation.flexibility_schedule:
                max_energy = max(max_energy, float(cycle.get('total_energy_kwh', 0.0)))
                max_duration = max(max_duration, float(cycle.get('duration_steps', 0.0)))
                for time_key in ('earliest_start_time_step', 'latest_start_time_step', 'deadline_time_step'):
                    max_time_step = max(max_time_step, float(cycle.get(time_key, -1.0)))
                profile = np.array(cycle.get('load_profile', []), dtype='float64')
                if profile.size > 0:
                    max_power = max(max_power, float(np.nanmax(profile)) / self._step_hours())
        max_power = max_power + 1.0e-6

        bounds = {
            "pending": (0.0, 1.0),
            "running": (0.0, 1.0),
            "can_start": (0.0, 1.0),
            "deadline_missed": (0.0, 1.0),
            "earliest_start_time_step": (-1.0, max_time_step),
            "latest_start_time_step": (-1.0, max_time_step),
            "deadline_time_step": (-1.0, max_time_step),
            "hours_until_latest_start": (-1.0, max_time_step * self._step_hours()),
            "hours_until_deadline": (-1.0, max_time_step * self._step_hours()),
            "slack_steps": (-1.0, max_time_step),
            "slack_ratio": (-1.0, 1.0),
            "urgency_ratio": (-1.0, 1.0),
            "cycle_duration_steps": (0.0, max_duration),
            "cycle_energy_kwh": (0.0, max_energy),
            "remaining_energy_kwh": (0.0, max_energy),
            "current_step_energy_kwh": (0.0, max_energy),
            "priority": (0.0, 1.0),
            "must_run": (0.0, 1.0),
            "cycle_average_power_kw": (0.0, max_power),
            "cycle_peak_power_kw": (0.0, max_power),
            "cycle_load_factor_ratio": (0.0, 1.0),
            "cycle_peak_step_offset_ratio": (-1.0, 1.0),
            "remaining_duration_steps": (0.0, max_duration),
            "remaining_duration_hours": (0.0, max_duration * self._step_hours()),
            "cycle_remaining_fraction_ratio": (0.0, 1.0),
            "hours_until_earliest_start": (-1.0, max_time_step * self._step_hours()),
            "start_window_width_hours": (0.0, max_time_step * self._step_hours()),
            "start_energy_kwh_step": (0.0, max_energy),
            "start_power_kw": (0.0, max_power),
            "must_start_now": (0.0, 1.0),
            "remaining_average_power_kw": (0.0, max_power),
            "current_step_power_kw": (0.0, max_power),
        }
        for j, feature in enumerate(self._deferrable_appliance_features):
            feature_low, feature_high = bounds.get(feature, self._default_bounds_for_feature(feature))
            low[:, j] = feature_low
            high[:, j] = feature_high
        return low, high

    def _building_action_bounds(self):
        rows = len(self._building_ids)
        cols = len(self._building_action_features)
        low = np.zeros((rows, cols), dtype=np.float32)
        high = np.zeros((rows, cols), dtype=np.float32)
        for i, building in enumerate(self.env.buildings):
            for action_name, a_low, a_high in zip(building.active_actions, building.action_space.low, building.action_space.high):
                col = self._building_action_col_by_name.get(action_name)
                if col is None:
                    continue
                low[i, col] = float(a_low)
                high[i, col] = float(a_high)
        return low, high

    def _charger_action_bounds(self):
        rows = len(self._charger_refs)
        cols = len(self._charger_action_features)
        low = np.zeros((rows, cols), dtype=np.float32)
        high = np.zeros((rows, cols), dtype=np.float32)
        if cols == 0:
            return low, high

        for ref in self._charger_refs:
            building = self.env.buildings[ref.building_index]
            for action_name, a_low, a_high in zip(building.active_actions, building.action_space.low, building.action_space.high):
                expected = f"electric_vehicle_storage_{ref.charger_id}"
                if action_name == expected:
                    low[ref.row, 0] = float(a_low)
                    high[ref.row, 0] = float(a_high)
                    break

        return low, high

    def _deferrable_appliance_action_bounds(self):
        rows = len(self._deferrable_appliance_refs)
        cols = len(self._deferrable_appliance_action_features)
        low = np.zeros((rows, cols), dtype=np.float32)
        high = np.zeros((rows, cols), dtype=np.float32)
        if cols == 0:
            return low, high

        for ref in self._deferrable_appliance_refs:
            building = self.env.buildings[ref.building_index]
            expected = f"deferrable_appliance_{ref.appliance_id}"
            for action_name, a_low, a_high in zip(building.active_actions, building.action_space.low, building.action_space.high):
                if action_name == expected:
                    low[ref.row, 0] = float(a_low)
                    high[ref.row, 0] = float(a_high)
                    break

        return low, high

    def _ensure_initialized(self):
        if not self._initialized:
            self.reset()
            return

        current_topology_version = int(getattr(self.env, 'topology_version', 0))
        if current_topology_version != self._layout_topology_version:
            self.reset()

    @staticmethod
    def _safe_scalar(value: Any, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)
        if not np.isfinite(scalar):
            return float(default)
        return scalar

    @classmethod
    def _safe_index(cls, values: Any, index: int, default: float = 0.0) -> float:
        try:
            return cls._safe_scalar(values[index], default)
        except Exception:
            return float(default)

    @staticmethod
    def _fill_obs_row_from_mapping(row: np.ndarray, feature_names: Sequence[str], values: Mapping[str, Any]) -> None:
        if len(feature_names) == 0:
            return

        for index, name in enumerate(feature_names):
            try:
                row[index] = values.get(name, 0.0)
            except (TypeError, ValueError):
                row[index] = 0.0

        np.nan_to_num(row, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

    @classmethod
    def _set_obs_value(
        cls,
        row: np.ndarray,
        feature_cols: Mapping[str, int],
        name: str,
        value: Any,
        default: float = 0.0,
    ) -> None:
        col = feature_cols.get(name)
        if col is None:
            return

        try:
            row[col] = value
        except (TypeError, ValueError):
            row[col] = default

    @classmethod
    def _fill_obs_row_sparse(
        cls,
        row: np.ndarray,
        feature_cols: Mapping[str, int],
        values: Mapping[str, Any],
    ) -> None:
        for name, value in values.items():
            cls._set_obs_value(row, feature_cols, name, value)

    @staticmethod
    def _to_2d_array(value: Any, *, rows: int, cols: int) -> Optional[np.ndarray]:
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32)
        if arr.ndim == 1 and cols > 0 and arr.shape[0] == cols and rows == 1:
            return arr.reshape(1, cols)
        if arr.ndim != 2:
            raise AssertionError("Entity action tables must be 2D arrays.")
        if arr.shape[0] != rows or arr.shape[1] != cols:
            raise AssertionError(f"Entity action table shape mismatch: expected ({rows}, {cols}) got {arr.shape}.")
        return arr

    @staticmethod
    def _has_electrical_storage(building) -> bool:
        storage = getattr(building, "electrical_storage", None)
        if storage is None:
            return False
        capacity = float(getattr(storage, "capacity", 0.0))
        nominal_power = float(getattr(storage, "nominal_power", 0.0))
        return capacity > 0.0 and nominal_power > 0.0

    @staticmethod
    def _has_pv_asset(building) -> bool:
        pv = getattr(building, "pv", None)
        if pv is None:
            return False
        nominal_power = float(getattr(pv, "nominal_power", 0.0))
        return nominal_power > 0.0

    @staticmethod
    def _is_entity_specific_observation(name: str) -> bool:
        key = str(name)
        return (
            key.startswith("electric_vehicle_charger_")
            or key.startswith("connected_electric_vehicle_at_charger_")
            or key.startswith("incoming_electric_vehicle_at_charger_")
            or key.startswith("charging_phase_one_hot_")
            or key.startswith("deferrable_appliance_")
        )

    @staticmethod
    def _is_flat_like(actions: Any) -> bool:
        if isinstance(actions, np.ndarray):
            return True
        if isinstance(actions, (list, tuple)):
            if len(actions) == 0:
                return True
            first = actions[0]
            return np.isscalar(first) or isinstance(first, (list, tuple, np.ndarray))
        return False
