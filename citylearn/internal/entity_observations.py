"""Populate entity observation tables and relation masks for one time boundary.

The facade owns topology-aware buffers and feature helpers. Population uses the
current exogenous index and previous settled endogenous index, then sanitises
buffers and returns independent copies. Fault/information masking remains in the
observation contract and robustness services at their established outer stages.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Mapping

import numpy as np

if TYPE_CHECKING:
    from citylearn.internal.entity_interface import CityLearnEntityInterfaceService


@dataclass(frozen=True)
class ObservationContext:
    time_step: int
    endogenous_time_step: int
    step_hours: float
    core: bool
    community: bool
    forecast: bool
    derived_forecast: bool
    temporal: bool
    action_feedback: bool
    demand_response: bool
    robustness: bool


def context_for(entity: "CityLearnEntityInterfaceService") -> ObservationContext:
    t = int(entity.env.time_step)
    return ObservationContext(
        t, max(t - 1, 0), entity._step_hours(),
        entity._bundle_enabled(entity.CORE_BUNDLE),
        entity._bundle_enabled(entity.COMMUNITY_BUNDLE),
        entity._bundle_enabled(entity.FORECAST_BUNDLE),
        entity._bundle_enabled(entity.DERIVED_FORECAST_BUNDLE),
        entity._bundle_enabled(entity.TEMPORAL_BUNDLE),
        entity._bundle_enabled(entity.ACTION_FEEDBACK_BUNDLE),
        entity._bundle_enabled(entity.DEMAND_RESPONSE_BUNDLE),
        entity._bundle_enabled(entity.ROBUSTNESS_BUNDLE),
    )


def reset_buffers(entity: "CityLearnEntityInterfaceService") -> None:
    entity._district_obs.fill(0.0)
    entity._building_obs.fill(0.0)
    entity._charger_obs[...] = entity._charger_static_obs
    entity._ev_obs.fill(0.0)
    entity._storage_obs[...] = entity._storage_static_obs
    entity._pv_obs[...] = entity._pv_static_obs
    entity._deferrable_appliance_obs.fill(0.0)


def fill_building_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext):
    env = entity.env
    t, endogenous_t, step_hours = context.time_step, context.endogenous_time_step, context.step_hours
    core_bundle_enabled, community_bundle_enabled = context.core, context.community
    temporal_bundle_enabled, derived_forecast_bundle_enabled = context.temporal, context.derived_forecast
    requires_building_electrical_metrics = core_bundle_enabled or community_bundle_enabled
    building_electrical_metrics: List[Mapping[str, float]] = []
    derived_forecast_community_values = (
        {
            label: {signal: 0.0 for signal in entity.DERIVED_FORECAST_DISTRICT_SIGNALS}
            for label, _ in entity.FORECAST_HORIZONS
        }
        if derived_forecast_bundle_enabled else None
    )
    first_building_data: Mapping[str, Any] = {}

    for i, building in enumerate(env.buildings):
        row = entity._building_obs[i]
        # Exogenous signals are read at current t, while endogenous values come from
        # the latest settled transition (max(t-1, 0)) to avoid uninitialized buffers.
        observation_names = (
            entity._first_building_base_observation_names
            if i == 0
            else entity._building_base_observation_names
        )
        data = building._ops_service.get_observations_data(
            include_all=False,
            observation_names=observation_names,
        )

        if i == 0:
            first_building_data = data

        entity._fill_obs_row_sparse(row, entity._building_feature_cols, data)
        electrical_metrics = None
        if requires_building_electrical_metrics:
            electrical_metrics = entity._build_electrical_building_metrics(
                building=building,
                endogenous_t=endogenous_t,
                control_t=t,
                step_hours=step_hours,
            )

        if core_bundle_enabled and electrical_metrics is not None:
            entity._fill_obs_row_sparse(row, entity._building_feature_cols, electrical_metrics)

        if community_bundle_enabled and electrical_metrics is not None:
            building_electrical_metrics.append(electrical_metrics)

        if temporal_bundle_enabled:
            entity._fill_obs_row_sparse(
                row,
                entity._building_feature_cols,
                entity._build_temporal_building_metrics(
                    building=building,
                    endogenous_t=endogenous_t,
                ),
            )
            entity._fill_obs_row_sparse(
                row,
                entity._building_feature_cols,
                entity._build_calendar_temporal_metrics(building=building, time_step=t),
            )

        if derived_forecast_bundle_enabled:
            forecast_values = entity._build_derived_forecast_building_metrics(building=building, time_step=t)
            entity._fill_obs_row_sparse(row, entity._building_feature_cols, forecast_values)
            for label, _ in entity.FORECAST_HORIZONS:
                target = derived_forecast_community_values[label]
                for signal in entity.DERIVED_FORECAST_DISTRICT_SIGNALS:
                    target[signal] += entity._safe_scalar(
                        forecast_values.get(f"forecast_{signal}_next_{label}_kw", 0.0),
                        0.0,
                    )
    return first_building_data, building_electrical_metrics, derived_forecast_community_values


def fill_district_row(entity: "CityLearnEntityInterfaceService", context: ObservationContext, building_data):
    env = entity.env
    t, endogenous_t = context.time_step, context.endogenous_time_step
    first_building_data, building_electrical_metrics, derived_forecast_community_values = building_data
    forecast_bundle_enabled, derived_forecast_bundle_enabled = context.forecast, context.derived_forecast
    community_bundle_enabled, temporal_bundle_enabled = context.community, context.temporal
    demand_response_bundle_enabled, robustness_bundle_enabled = context.demand_response, context.robustness
    district_row = entity._district_obs[0]
    entity._fill_obs_row_sparse(district_row, entity._district_feature_cols, first_building_data)

    if forecast_bundle_enabled:
        entity._fill_obs_row_sparse(
            district_row,
            entity._district_feature_cols,
            entity._build_forecast_district_metrics(first_building_data),
        )

    if derived_forecast_bundle_enabled:
        entity._fill_obs_row_sparse(
            district_row,
            entity._district_feature_cols,
            entity._build_derived_forecast_district_metrics(
                time_step=t,
                community_values=derived_forecast_community_values,
            ),
        )

    if community_bundle_enabled:
        entity._fill_obs_row_sparse(
            district_row,
            entity._district_feature_cols,
            entity._build_community_district_metrics(building_electrical_metrics),
        )

    if temporal_bundle_enabled:
        entity._fill_obs_row_sparse(
            district_row,
            entity._district_feature_cols,
            entity._build_temporal_district_metrics(
                endogenous_t=endogenous_t,
            ),
        )
        if len(env.buildings) > 0:
            entity._fill_obs_row_sparse(
                district_row,
                entity._district_feature_cols,
                entity._build_calendar_temporal_metrics(building=env.buildings[0], time_step=t),
            )

    if demand_response_bundle_enabled:
        service = getattr(env, "_demand_response_service", None)
        values = service.observation_values() if service is not None else {}
        entity._fill_obs_row_sparse(district_row, entity._district_feature_cols, values)

    if robustness_bundle_enabled:
        service = getattr(env, "_robustness_service", None)
        values = service.observation_values() if service is not None else {}
        entity._fill_obs_row_sparse(district_row, entity._district_feature_cols, values)


def fill_charger_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env = entity.env
    t, endogenous_t, step_hours = context.time_step, context.endogenous_time_step, context.step_hours
    core_bundle_enabled, action_feedback_bundle_enabled = context.core, context.action_feedback
    for ref in entity._charger_refs:
        charger = env.buildings[ref.building_index]._charger_lookup[ref.charger_id]
        sim = charger.charger_simulation
        row = entity._charger_obs[ref.row]
        static_values = entity._charger_static_values.get(ref.row, {})
        state = entity._safe_index(sim.electric_vehicle_charger_state, t, np.nan)
        connected = charger.connected_electric_vehicle is not None and state == 1
        incoming = charger.incoming_electric_vehicle is not None and state == 2
        commanded_energy = entity._safe_index(charger.past_charging_action_values_kwh, endogenous_t, 0.0)
        applied_energy = (
            entity._safe_index(charger.electricity_consumption, endogenous_t, 0.0)
            if core_bundle_enabled else 0.0
        )
        required_soc = entity._safe_index(sim.electric_vehicle_required_soc_departure, t, -0.1)
        departure_steps = entity._safe_index(sim.electric_vehicle_departure_time, t, -1.0)
        max_charging_power = entity._safe_scalar(static_values.get("max_charging_power_kw"), 0.0)
        max_discharging_power = entity._safe_scalar(static_values.get("max_discharging_power_kw"), 0.0)
        charge_efficiency_at_max = entity._safe_scalar(static_values.get("charge_efficiency_at_max_ratio"), 1.0)
        discharge_efficiency_at_max = entity._safe_scalar(static_values.get("discharge_efficiency_at_max_ratio"), 1.0)
        incoming_required_soc = required_soc if incoming else -0.1
        incoming_departure_steps = departure_steps if incoming else -1.0
        incoming_hours_until_departure = (
            incoming_departure_steps * step_hours
            if incoming and incoming_departure_steps >= 0.0
            else -1.0
        )

        if connected:
            connected_ev = charger.connected_electric_vehicle
            current_soc = entity._safe_scalar(connected_ev.battery.soc[connected_ev.observation_soc_index(endogenous_t)], -0.1)
            battery_capacity = entity._safe_scalar(connected_ev.battery.capacity, -1.0)
            hours_until_departure = departure_steps * step_hours if departure_steps >= 0.0 else -1.0
            if core_bundle_enabled:
                energy_to_required_soc = max((required_soc - current_soc) * max(battery_capacity, 0.0), 0.0)
                required_average_power = energy_to_required_soc / max(hours_until_departure, 1.0e-6) if energy_to_required_soc > 0.0 else 0.0
                avg_power_to_departure = required_average_power
                charging_slack = max_charging_power - required_average_power
                if hours_until_departure < 0.0:
                    # Unknown deadline: no prescribed average rate or urgency.
                    required_average_power = avg_power_to_departure = 0.0
                    charging_slack = charging_priority = 0.0
                elif energy_to_required_soc <= 0.0:
                    charging_priority = 0.0
                elif hours_until_departure <= 0.0 or max_charging_power <= 0.0:
                    charging_priority = 1.0
                else:
                    charging_priority = np.clip(required_average_power / max(max_charging_power, 1.0e-6), 0.0, 1.0)
            else:
                energy_to_required_soc = 0.0
                avg_power_to_departure = 0.0
                required_average_power = 0.0
                charging_slack = 0.0
                charging_priority = 0.0
        else:
            current_soc = -0.1
            battery_capacity = -1.0
            hours_until_departure = -1.0
            energy_to_required_soc = 0.0
            avg_power_to_departure = 0.0
            required_average_power = 0.0
            charging_slack = 0.0
            charging_priority = 0.0

        entity._set_obs_value(row, entity._charger_feature_cols, "connected_state", 1.0 if connected else 0.0)
        entity._set_obs_value(row, entity._charger_feature_cols, "incoming_state", 1.0 if incoming else 0.0)
        entity._set_obs_value(row, entity._charger_feature_cols, "connected_ev_soc", current_soc)
        entity._set_obs_value(row, entity._charger_feature_cols, "connected_ev_required_soc_departure", required_soc if connected else -0.1)
        entity._set_obs_value(row, entity._charger_feature_cols, "connected_ev_battery_capacity_kwh", battery_capacity)
        entity._set_obs_value(
            row,
            entity._charger_feature_cols,
            "connected_ev_departure_time_step",
            entity._safe_index(sim.electric_vehicle_departure_time, t, -1.0) if connected else -1.0,
        )
        entity._set_obs_value(
            row,
            entity._charger_feature_cols,
            "incoming_ev_estimated_soc_arrival",
            entity._safe_index(sim.electric_vehicle_estimated_soc_arrival, t, -0.1) if incoming else -0.1,
        )
        entity._set_obs_value(
            row,
            entity._charger_feature_cols,
            "incoming_ev_estimated_arrival_time_step",
            entity._safe_index(sim.electric_vehicle_estimated_arrival_time, t, -1.0) if incoming else -1.0,
        )
        entity._set_obs_value(row, entity._charger_feature_cols, "last_charged_kwh", commanded_energy)
        if core_bundle_enabled:
            charger_decision_metrics = entity._charger_core_decision_metrics(
                building=env.buildings[ref.building_index],
                charger=charger,
                connected=connected,
                current_soc=current_soc,
                battery_capacity=battery_capacity,
                required_soc=required_soc,
                energy_to_required_soc=energy_to_required_soc,
                required_average_power=required_average_power,
                hours_until_departure=hours_until_departure,
                max_charging_power=max_charging_power,
                max_discharging_power=max_discharging_power,
                charge_efficiency_at_max=charge_efficiency_at_max,
                discharge_efficiency_at_max=discharge_efficiency_at_max,
                step_hours=step_hours,
                current_power_kw=applied_energy / step_hours,
            )
            entity._set_obs_value(row, entity._charger_feature_cols, "commanded_power_kw", commanded_energy / step_hours)
            entity._set_obs_value(row, entity._charger_feature_cols, "applied_power_kw", applied_energy / step_hours)
            entity._set_obs_value(row, entity._charger_feature_cols, "applied_energy_kwh_step", applied_energy)
            entity._set_obs_value(row, entity._charger_feature_cols, "hours_until_departure", hours_until_departure)
            entity._set_obs_value(
                row,
                entity._charger_feature_cols,
                "time_until_departure_ratio",
                np.clip(hours_until_departure / 24.0, 0.0, 1.0) if connected and hours_until_departure >= 0.0 else -1.0,
            )
            entity._set_obs_value(row, entity._charger_feature_cols, "energy_to_required_soc_kwh", energy_to_required_soc)
            entity._set_obs_value(row, entity._charger_feature_cols, "required_average_power_kw", required_average_power)
            entity._set_obs_value(row, entity._charger_feature_cols, "avg_power_to_departure_kw", avg_power_to_departure)
            entity._set_obs_value(row, entity._charger_feature_cols, "charging_slack_kw", charging_slack)
            entity._set_obs_value(row, entity._charger_feature_cols, "charging_priority_ratio", charging_priority)
            entity._fill_obs_row_sparse(row, entity._charger_feature_cols, charger_decision_metrics)
            entity._set_obs_value(row, entity._charger_feature_cols, "incoming_ev_required_soc_departure", incoming_required_soc)
            entity._set_obs_value(row, entity._charger_feature_cols, "incoming_ev_departure_time_step", incoming_departure_steps)
            entity._set_obs_value(row, entity._charger_feature_cols, "incoming_ev_hours_until_departure", incoming_hours_until_departure)
            entity._set_obs_value(
                row,
                entity._charger_feature_cols,
                "incoming_ev_time_until_departure_ratio",
                (
                    np.clip(incoming_hours_until_departure / 24.0, 0.0, 1.0)
                    if incoming and incoming_hours_until_departure >= 0.0
                    else -1.0
                ),
            )
        if action_feedback_bundle_enabled:
            entity._fill_obs_row_sparse(
                row,
                entity._charger_feature_cols,
                entity._charger_action_feedback_metrics(charger, endogenous_t, step_hours),
            )


def fill_ev_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env = entity.env
    endogenous_t, core_bundle_enabled = context.endogenous_time_step, context.core
    for i, ev in enumerate(env.electric_vehicles):
        row = entity._ev_obs[i]
        soc = entity._safe_scalar(ev.battery.soc[ev.observation_soc_index(endogenous_t)], 0.0)
        capacity = entity._safe_scalar(ev.battery.capacity, 0.0)
        depth_of_discharge = entity._safe_scalar(ev.battery.depth_of_discharge, 0.0)
        entity._set_obs_value(row, entity._ev_feature_cols, "soc", soc)
        entity._set_obs_value(row, entity._ev_feature_cols, "battery_capacity_kwh", capacity)
        entity._set_obs_value(row, entity._ev_feature_cols, "depth_of_discharge_ratio", depth_of_discharge)
        if core_bundle_enabled:
            soc_max = float(np.clip(entity._safe_scalar(getattr(ev.battery, "max_soc", 1.0), 1.0), 0.0, 1.0))
            soc_min = float(np.clip(1.0 - depth_of_discharge, 0.0, soc_max))
            energy_available = max((soc - soc_min) * max(capacity, 0.0), 0.0)
            energy_to_full = max((soc_max - soc) * max(capacity, 0.0), 0.0)
            entity._set_obs_value(row, entity._ev_feature_cols, "soc_ratio", soc)
            entity._set_obs_value(row, entity._ev_feature_cols, "soc_min_ratio", soc_min)
            entity._set_obs_value(row, entity._ev_feature_cols, "soc_max_ratio", soc_max)
            entity._set_obs_value(row, entity._ev_feature_cols, "energy_available_kwh", energy_available)
            entity._set_obs_value(row, entity._ev_feature_cols, "energy_to_full_kwh", energy_to_full)


def fill_storage_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env = entity.env
    endogenous_t, step_hours = context.endogenous_time_step, context.step_hours
    core_bundle_enabled, action_feedback_bundle_enabled = context.core, context.action_feedback
    for ref in entity._storage_refs:
        building = env.buildings[ref.building_index]
        storage = building.electrical_storage
        row = entity._storage_obs[ref.row]
        capacity = entity._safe_scalar(getattr(storage, "capacity", 0.0), 0.0)
        nominal_power = entity._safe_scalar(getattr(storage, "nominal_power", 0.0), 0.0)
        soc = entity._safe_scalar(storage.soc[endogenous_t], 0.0)
        efficiency_history = getattr(storage, "efficiency_history", None)
        if efficiency_history is not None and len(efficiency_history) > 0:
            base_efficiency = entity._safe_scalar(efficiency_history[0], 1.0)
        else:
            base_efficiency = entity._safe_scalar(getattr(storage, "efficiency", 1.0), 1.0)
        round_trip_efficiency = entity._safe_scalar(
            getattr(storage, "round_trip_efficiency", base_efficiency ** 0.5),
            base_efficiency ** 0.5,
        )
        entity._set_obs_value(row, entity._storage_feature_cols, "soc", soc)
        entity._set_obs_value(row, entity._storage_feature_cols, "capacity_kwh", capacity)
        entity._set_obs_value(row, entity._storage_feature_cols, "nominal_power_kw", nominal_power)
        entity._set_obs_value(
            row,
            entity._storage_feature_cols,
            "electricity_consumption_kwh",
            entity._safe_scalar(building.electrical_storage_electricity_consumption[endogenous_t], 0.0),
        )
        entity._set_obs_value(
            row,
            entity._storage_feature_cols,
            "min_charge_power_kw",
            entity._safe_scalar(getattr(storage, "min_charge_power", 0.0), 0.0),
        )
        entity._set_obs_value(
            row,
            entity._storage_feature_cols,
            "min_discharge_power_kw",
            entity._safe_scalar(getattr(storage, "min_discharge_power", 0.0), 0.0),
        )
        entity._set_obs_value(row, entity._storage_feature_cols, "efficiency_ratio", base_efficiency)
        entity._set_obs_value(row, entity._storage_feature_cols, "round_trip_efficiency_ratio", round_trip_efficiency)
        if core_bundle_enabled:
            depth_of_discharge = entity._safe_scalar(getattr(storage, "depth_of_discharge", 1.0), 1.0)
            soc_max = float(np.clip(entity._safe_scalar(getattr(storage, "max_soc", 1.0), 1.0), 0.0, 1.0))
            soc_min = float(np.clip(1.0 - depth_of_discharge, 0.0, soc_max))
            current_energy = soc * max(capacity, 0.0)
            max_energy = max(capacity, 0.0) if soc_max == 1.0 else soc_max * max(capacity, 0.0)
            energy_to_full = max(max_energy - current_energy, 0.0)
            energy_available = max((soc - soc_min) * max(capacity, 0.0), 0.0)
            max_charge_power = (
                entity._safe_scalar(storage.get_max_input_power(), nominal_power)
                if hasattr(storage, "get_max_input_power")
                else nominal_power
            )
            max_discharge_power = (
                entity._safe_scalar(storage.get_max_output_power(), nominal_power)
                if hasattr(storage, "get_max_output_power")
                else nominal_power
            )
            decision_metrics = entity._storage_core_decision_metrics(
                building=building,
                storage=storage,
                soc=soc,
                capacity=capacity,
                nominal_power=nominal_power,
                soc_min=soc_min,
                soc_max=soc_max,
                energy_to_full=energy_to_full,
                energy_available=energy_available,
                max_charge_power=max_charge_power,
                max_discharge_power=max_discharge_power,
                efficiency=entity._safe_scalar(getattr(storage, "efficiency", base_efficiency), base_efficiency),
                step_hours=step_hours,
                include_headroom=True,
                current_power_kw=entity._safe_scalar(
                    building.electrical_storage_electricity_consumption[endogenous_t],
                    0.0,
                ) / step_hours,
            )
            entity._set_obs_value(row, entity._storage_feature_cols, "electrical_storage_soc_ratio", soc)
            entity._set_obs_value(row, entity._storage_feature_cols, "max_charge_power_kw", max_charge_power)
            entity._set_obs_value(row, entity._storage_feature_cols, "max_discharge_power_kw", max_discharge_power)
            entity._set_obs_value(row, entity._storage_feature_cols, "energy_to_full_kwh", energy_to_full)
            entity._set_obs_value(row, entity._storage_feature_cols, "energy_available_kwh", energy_available)
            entity._fill_obs_row_sparse(row, entity._storage_feature_cols, decision_metrics)
            entity._set_obs_value(
                row,
                entity._storage_feature_cols,
                "current_efficiency_ratio",
                entity._safe_scalar(getattr(storage, "efficiency", base_efficiency), base_efficiency),
            )
            entity._set_obs_value(
                row,
                entity._storage_feature_cols,
                "degraded_capacity_kwh",
                entity._safe_scalar(getattr(storage, "degraded_capacity", capacity), capacity),
            )
            entity._set_obs_value(row, entity._storage_feature_cols, "soc_min_ratio", soc_min)
        if action_feedback_bundle_enabled:
            entity._fill_obs_row_sparse(
                row,
                entity._storage_feature_cols,
                entity._storage_action_feedback_metrics(building, endogenous_t, step_hours),
            )


def fill_pv_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env = entity.env
    endogenous_t, step_hours = context.endogenous_time_step, context.step_hours
    if entity._pv_features:
        for ref in entity._pv_refs:
            building = env.buildings[ref.building_index]
            row = entity._pv_obs[ref.row]
            generation_energy = abs(entity._safe_index(building.solar_generation, endogenous_t, 0.0))
            installed_power = entity._safe_scalar(getattr(building.pv, "nominal_power", 0.0), 0.0)
            generation_power = generation_energy / step_hours
            entity._set_obs_value(row, entity._pv_feature_cols, "generation_power_kw", generation_power)
            entity._set_obs_value(row, entity._pv_feature_cols, "generation_energy_kwh_step", generation_energy)
            entity._set_obs_value(row, entity._pv_feature_cols, "installed_power_kw", installed_power)
            entity._set_obs_value(
                row,
                entity._pv_feature_cols,
                "generation_capacity_factor_ratio",
                generation_power / installed_power if installed_power > 0.0 else 0.0,
            )


def fill_deferrable_rows(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env = entity.env
    endogenous_t, action_feedback_bundle_enabled = context.endogenous_time_step, context.action_feedback
    for ref in entity._deferrable_appliance_refs:
        building = env.buildings[ref.building_index]
        appliance = entity._deferrable_appliance_by_building_and_id.get((ref.building_index, ref.appliance_id))
        if appliance is None:
            continue
        row = entity._deferrable_appliance_obs[ref.row]
        values = building._ops_service.deferrable_appliance_observations(appliance)
        entity._fill_obs_row_sparse(row, entity._deferrable_appliance_feature_cols, values)
        entity._fill_obs_row_sparse(
            row,
            entity._deferrable_appliance_feature_cols,
            entity._deferrable_core_decision_metrics(appliance, values),
        )
        if action_feedback_bundle_enabled:
            entity._fill_obs_row_sparse(
                row,
                entity._deferrable_appliance_feature_cols,
                entity._deferrable_action_feedback_metrics(appliance, endogenous_t),
            )


def fill_relation_masks(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> None:
    env, t = entity.env, context.time_step
    entity._charger_to_ev_connected.fill(-1)
    entity._charger_to_ev_connected_mask.fill(0.0)
    entity._charger_to_ev_incoming.fill(-1)
    entity._charger_to_ev_incoming_mask.fill(0.0)
    for ref in entity._charger_refs:
        charger = env.buildings[ref.building_index]._charger_lookup[ref.charger_id]
        sim = charger.charger_simulation
        state = entity._safe_index(sim.electric_vehicle_charger_state, t, np.nan)
        if state == 1 and charger.connected_electric_vehicle is not None:
            ev_row = entity._ev_row_by_name.get(charger.connected_electric_vehicle.name)
            if ev_row is not None:
                entity._charger_to_ev_connected[ref.row, 0] = ref.row
                entity._charger_to_ev_connected[ref.row, 1] = ev_row
                entity._charger_to_ev_connected_mask[ref.row] = 1.0

        if state == 2 and charger.incoming_electric_vehicle is not None:
            ev_row = entity._ev_row_by_name.get(charger.incoming_electric_vehicle.name)
            if ev_row is not None:
                entity._charger_to_ev_incoming[ref.row, 0] = ref.row
                entity._charger_to_ev_incoming[ref.row, 1] = ev_row
                entity._charger_to_ev_incoming_mask[ref.row] = 1.0


def sanitize_tables(entity: "CityLearnEntityInterfaceService") -> None:
    for table in (
        entity._district_obs,
        entity._building_obs,
        entity._charger_obs,
        entity._ev_obs,
        entity._storage_obs,
        entity._pv_obs,
        entity._deferrable_appliance_obs,
    ):
        np.nan_to_num(table, copy=False, nan=0.0, posinf=0.0, neginf=0.0)


def snapshot_payload(entity: "CityLearnEntityInterfaceService", context: ObservationContext) -> Mapping[str, Any]:
    env = entity.env
    t, endogenous_t = context.time_step, context.endogenous_time_step
    payload = {
        "tables": {
            "district": entity._district_obs.copy(),
            "building": entity._building_obs.copy(),
            "charger": entity._charger_obs.copy(),
            "ev": entity._ev_obs.copy(),
            "storage": entity._storage_obs.copy(),
            "pv": entity._pv_obs.copy(),
            "deferrable_appliance": entity._deferrable_appliance_obs.copy(),
        },
        "edges": {
            "district_to_building": entity._district_to_building.copy(),
            "building_to_charger": entity._building_to_charger.copy(),
            "building_to_storage": entity._building_to_storage.copy(),
            "building_to_pv": entity._building_to_pv.copy(),
            "building_to_deferrable_appliance": entity._building_to_deferrable_appliance.copy(),
            "charger_to_ev_connected": entity._charger_to_ev_connected.copy(),
            "charger_to_ev_connected_mask": entity._charger_to_ev_connected_mask.copy(),
            "charger_to_ev_incoming": entity._charger_to_ev_incoming.copy(),
            "charger_to_ev_incoming_mask": entity._charger_to_ev_incoming_mask.copy(),
        },
        "meta": {
            "time_step": t,
            "endogenous_time_step": endogenous_t,
            "seconds_per_time_step": float(getattr(env, "seconds_per_time_step", 3600.0)),
            "spec_version": "entity_v1",
            "temporal_semantics": {
                "exogenous": "t",
                "endogenous": "t_minus_1_settled",
            },
            "forecast_config": entity._forecast_config_meta(),
            "topology_version": int(getattr(env, "topology_version", 0)),
            "demand_response": (
                env._demand_response_service.observation_meta()
                if getattr(env, "_demand_response_service", None) is not None
                else {"enabled": False, "active_request_id": None}
            ),
            "robustness": (
                env._robustness_service.observation_meta()
                if getattr(env, "_robustness_service", None) is not None
                else {"enabled": False, "active_event_ids": []}
            ),
            "runtime_status": entity._runtime_status_payload(),
        },
    }
    return payload
