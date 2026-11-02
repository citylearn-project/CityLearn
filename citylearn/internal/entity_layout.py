"""Build entity static rows, spaces and declarative interface specifications.

Topology identity/reference discovery remains in the interface facade; this
module constructs the layout-dependent numeric and serialisable structures.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Sequence

import numpy as np
from gymnasium import spaces

if TYPE_CHECKING:
    from citylearn.internal.entity_interface import CityLearnEntityInterfaceService


def build_static_observation_rows(entity: "CityLearnEntityInterfaceService") -> None:
    """Pre-fill static entity feature values for the current topology layout."""

    entity._charger_static_obs = np.zeros_like(entity._charger_obs)
    entity._storage_static_obs = np.zeros_like(entity._storage_obs)
    entity._pv_static_obs = np.zeros_like(entity._pv_obs)
    entity._charger_static_values: Dict[int, Mapping[str, float]] = {}

    for ref in entity._charger_refs:
        building = entity.env.buildings[ref.building_index]
        charger = building._charger_lookup[ref.charger_id]
        row = entity._charger_static_obs[ref.row]
        max_charging_power = entity._safe_scalar(charger.max_charging_power, 0.0)
        max_discharging_power = entity._safe_scalar(charger.max_discharging_power, 0.0)
        min_charging_power = entity._safe_scalar(getattr(charger, "min_charging_power", 0.0), 0.0)
        min_discharging_power = entity._safe_scalar(getattr(charger, "min_discharging_power", 0.0), 0.0)
        charger_efficiency = entity._safe_scalar(getattr(charger, "efficiency", 1.0), 1.0)
        charge_efficiency_at_max = (
            entity._safe_scalar(charger.get_efficiency(1.0, True), charger_efficiency)
            if hasattr(charger, "get_efficiency")
            else charger_efficiency
        )
        discharge_efficiency_at_max = (
            entity._safe_scalar(charger.get_efficiency(1.0, False), charger_efficiency)
            if hasattr(charger, "get_efficiency")
            else charger_efficiency
        )
        static_values = {
            "max_charging_power_kw": max_charging_power,
            "max_discharging_power_kw": max_discharging_power,
            "min_charging_power_kw": min_charging_power,
            "min_discharging_power_kw": min_discharging_power,
            "charger_efficiency_ratio": charger_efficiency,
            "charge_efficiency_at_max_ratio": charge_efficiency_at_max,
            "discharge_efficiency_at_max_ratio": discharge_efficiency_at_max,
        }
        assigned_phase = getattr(building, "_charger_phase_map", {}).get(ref.charger_id)
        for phase_name, feature_name in zip(entity._charger_phase_names, entity._charger_phase_features):
            static_values[feature_name] = 1.0 if assigned_phase in {phase_name, "all_phases"} else 0.0
        entity._fill_obs_row_sparse(row, entity._charger_feature_cols, static_values)
        entity._charger_static_values[ref.row] = static_values

    for ref in entity._storage_refs:
        building = entity.env.buildings[ref.building_index]
        row = entity._storage_static_obs[ref.row]
        assigned_phase = getattr(building, "electrical_storage_phase_connection", None)
        for phase_name, feature_name in zip(entity._storage_phase_names, entity._storage_phase_features):
            entity._set_obs_value(
                row,
                entity._storage_feature_cols,
                feature_name,
                1.0 if assigned_phase in {phase_name, "all_phases"} else 0.0,
            )

    for ref in entity._pv_refs:
        building = entity.env.buildings[ref.building_index]
        installed_power = entity._safe_scalar(getattr(building.pv, "nominal_power", 0.0), 0.0)
        entity._set_obs_value(entity._pv_static_obs[ref.row], entity._pv_feature_cols, "installed_power_kw", installed_power)


def build_spaces(entity: "CityLearnEntityInterfaceService") -> None:
    district_low, district_high = entity._observation_bounds_for_features(entity._district_features, owner="district")
    building_low, building_high = entity._observation_bounds_for_features(entity._building_features, owner="building", per_building=True)
    charger_low, charger_high = entity._charger_observation_bounds()
    ev_low, ev_high = entity._ev_observation_bounds()
    storage_low, storage_high = entity._storage_observation_bounds()
    pv_low, pv_high = entity._pv_observation_bounds()
    deferrable_appliance_low, deferrable_appliance_high = entity._deferrable_appliance_observation_bounds()

    entity._observation_space = spaces.Dict(
        {
            "tables": spaces.Dict(
                {
                    "district": spaces.Box(low=district_low, high=district_high, dtype=np.float32),
                    "building": spaces.Box(low=building_low, high=building_high, dtype=np.float32),
                    "charger": spaces.Box(low=charger_low, high=charger_high, dtype=np.float32),
                    "ev": spaces.Box(low=ev_low, high=ev_high, dtype=np.float32),
                    "storage": spaces.Box(low=storage_low, high=storage_high, dtype=np.float32),
                    "pv": spaces.Box(low=pv_low, high=pv_high, dtype=np.float32),
                    "deferrable_appliance": spaces.Box(low=deferrable_appliance_low, high=deferrable_appliance_high, dtype=np.float32),
                }
            ),
            "edges": spaces.Dict(
                {
                    "district_to_building": spaces.Box(
                        low=np.zeros((len(entity._building_ids), 2), dtype=np.int32),
                        high=np.maximum(np.array([[0, max(len(entity._building_ids) - 1, 0)]], dtype=np.int32), 0).repeat(len(entity._building_ids), axis=0),
                        dtype=np.int32,
                    ),
                    "building_to_charger": spaces.Box(
                        low=np.full((len(entity._charger_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._building_ids) - 1, 0), max(len(entity._charger_refs) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._charger_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "building_to_storage": spaces.Box(
                        low=np.full((len(entity._storage_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._building_ids) - 1, 0), max(len(entity._storage_refs) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._storage_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "building_to_pv": spaces.Box(
                        low=np.full((len(entity._pv_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._building_ids) - 1, 0), max(len(entity._pv_refs) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._pv_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "building_to_deferrable_appliance": spaces.Box(
                        low=np.full((len(entity._deferrable_appliance_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._building_ids) - 1, 0), max(len(entity._deferrable_appliance_refs) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._deferrable_appliance_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "charger_to_ev_connected": spaces.Box(
                        low=np.full((len(entity._charger_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._charger_refs) - 1, 0), max(len(entity._ev_ids) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._charger_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "charger_to_ev_connected_mask": spaces.Box(
                        low=np.zeros((len(entity._charger_refs),), dtype=np.float32),
                        high=np.ones((len(entity._charger_refs),), dtype=np.float32),
                        dtype=np.float32,
                    ),
                    "charger_to_ev_incoming": spaces.Box(
                        low=np.full((len(entity._charger_refs), 2), -1, dtype=np.int32),
                        high=np.array(
                            [[max(len(entity._charger_refs) - 1, 0), max(len(entity._ev_ids) - 1, 0)]],
                            dtype=np.int32,
                        ).repeat(len(entity._charger_refs), axis=0),
                        dtype=np.int32,
                    ),
                    "charger_to_ev_incoming_mask": spaces.Box(
                        low=np.zeros((len(entity._charger_refs),), dtype=np.float32),
                        high=np.ones((len(entity._charger_refs),), dtype=np.float32),
                        dtype=np.float32,
                    ),
                }
            ),
        }
    )

    building_action_low, building_action_high = entity._building_action_bounds()
    charger_action_low, charger_action_high = entity._charger_action_bounds()
    deferrable_appliance_action_low, deferrable_appliance_action_high = entity._deferrable_appliance_action_bounds()
    entity._action_space = spaces.Dict(
        {
            "tables": spaces.Dict(
                {
                    "building": spaces.Box(low=building_action_low, high=building_action_high, dtype=np.float32),
                    "charger": spaces.Box(low=charger_action_low, high=charger_action_high, dtype=np.float32),
                    "deferrable_appliance": spaces.Box(
                        low=deferrable_appliance_action_low,
                        high=deferrable_appliance_action_high,
                        dtype=np.float32,
                    ),
                }
            )
        }
    )


def build_specs(entity: "CityLearnEntityInterfaceService") -> None:
    def _units_for(names: Sequence[str]) -> List[str]:
        return [entity._infer_unit(name) for name in names]

    def _table_spec(table_name: str, ids: Sequence[str], features: Sequence[str]) -> Mapping[str, Any]:
        feature_metadata = entity._feature_metadata_for_table(table_name, features)
        return {
            "ids": list(ids),
            "features": list(features),
            "units": _units_for(features),
            "feature_metadata": feature_metadata,
        }

    entity._specs = {
        "version": "entity_v1",
        "runtime_status_contract": {
            "version": "runtime_status_v1",
            "emits_health_state": False,
            "fault_mode_semantics": "raw_cause_not_health_state",
            "sparse_defaults": {
                "availability": "AVAILABLE",
                "quality": "NOMINAL",
            },
            "event_domains": [
                "ASSET_CONNECTION",
                "ASSET_AVAILABILITY",
                "SENSOR_CHANNEL",
                "ACTUATOR_CHANNEL",
                "COMMUNICATION_LINK",
                "VALUE_QUALITY",
            ],
            "collections": [
                "active_events",
                "asset_connections",
                "asset_availability",
                "sensor_channels",
                "actuator_channels",
                "communication_links",
                "value_quality",
            ],
        },
        "action_execution_contract": {
            "version": "entity_action_execution_v1",
            "nullable_unobservable_fields": True,
            "stages": [
                "requested_value",
                "post_channel_value",
                "limited_value",
                "applied_value",
                "applied_power_kw",
            ],
        },
        "temporal_semantics": {
            "exogenous": "t",
            "endogenous": "t_minus_1_settled",
            "event_boundary": "events_at_k_apply_after_transition_k_minus_1_to_k_before_observation_k",
        },
        "normalization": {
            "simulator_applies_normalization": False,
            "policy": "external_running_stats",
            "encoding": {
                "ids": "stable_canonical_ids",
                "categorical": "numeric_or_binary_from_dataset",
                "time": "raw_indices_unwrapped",
            },
            "dynamic_topology": {
                "variable_size_tables": bool(getattr(entity.env, "topology_mode", "static") == "dynamic"),
                "stable_ids": True,
                "relation_masks": [
                    "charger_to_ev_connected_mask",
                    "charger_to_ev_incoming_mask",
                ],
                "running_stats_recommendation": "maintain_per_feature_stats_externally_and_ignore_inactive_ids",
            },
        },
        "observation_bundles": {
            entity.BASE_BUNDLE: {"active": True},
            **{
                bundle_name: {"active": bool(active)}
                for bundle_name, active in entity._observation_bundles.items()
            },
        },
        "tables": {
            "district": _table_spec("district", ["district_0"], entity._district_features),
            "building": _table_spec("building", entity._building_ids, entity._building_features),
            "charger": _table_spec("charger", [ref.global_id for ref in entity._charger_refs], entity._charger_features),
            "ev": _table_spec("ev", entity._ev_ids, entity._ev_features),
            "storage": _table_spec("storage", [ref.global_id for ref in entity._storage_refs], entity._storage_features),
            "pv": _table_spec("pv", [ref.global_id for ref in entity._pv_refs], entity._pv_features),
            "deferrable_appliance": _table_spec(
                "deferrable_appliance",
                [ref.global_id for ref in entity._deferrable_appliance_refs],
                entity._deferrable_appliance_features,
            ),
        },
        "actions": {
            "building": {
                "ids": list(entity._building_ids),
                "features": list(entity._building_action_features),
                "units": _units_for(entity._building_action_features),
            },
            "charger": {
                "ids": [ref.global_id for ref in entity._charger_refs],
                "features": list(entity._charger_action_features),
                "units": _units_for(entity._charger_action_features),
            },
            "deferrable_appliance": {
                "ids": [ref.global_id for ref in entity._deferrable_appliance_refs],
                "features": list(entity._deferrable_appliance_action_features),
                "units": _units_for(entity._deferrable_appliance_action_features),
            },
        },
        "edges": {
            "district_to_building": {
                "source": "district",
                "target": "building",
            },
            "building_to_charger": {
                "source": "building",
                "target": "charger",
            },
            "building_to_storage": {
                "source": "building",
                "target": "storage",
            },
            "building_to_pv": {
                "source": "building",
                "target": "pv",
            },
            "building_to_deferrable_appliance": {
                "source": "building",
                "target": "deferrable_appliance",
            },
            "charger_to_ev_connected": {
                "source": "charger",
                "target": "ev",
            },
            "charger_to_ev_incoming": {
                "source": "charger",
                "target": "ev",
            },
        },
        "topology": {
            "mode": getattr(entity.env, "topology_mode", "static"),
            "version": int(getattr(entity.env, "topology_version", 0)),
            "active_ids": {
                "building": list(entity._building_ids),
                "ev": list(entity._ev_ids),
                "charger": [ref.global_id for ref in entity._charger_refs],
                "storage": [ref.global_id for ref in entity._storage_refs],
                "pv": [ref.global_id for ref in entity._pv_refs],
                "deferrable_appliance": [ref.global_id for ref in entity._deferrable_appliance_refs],
            },
            "lifecycle_fields": ["born_at", "removed_at", "active"],
            "member_lifecycle": getattr(entity.env, "topology_member_lifecycle", {}),
        },
    }


