from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

import numpy as np

from citylearn.energy_model import HeatPump
from citylearn.preprocessing import Normalize, PeriodicNormalization
from citylearn.internal.units import energy_kwh_to_power_kw, power_kw_to_energy_kwh
from citylearn.internal.electrical_limits import allocate_electrical_service, electrical_service_violation_kw

if TYPE_CHECKING:
    from citylearn.building import Building

LOGGER = logging.getLogger()


class BuildingOpsService:
    """Internal observation/action operations for `Building`."""

    def __init__(self, building: "Building"):
        self.building = building

    def observations(
        self,
        include_all: bool = None,
        normalize: bool = None,
        periodic_normalization: bool = None,
        check_limits: bool = None,
        observation_names: Optional[Iterable[str]] = None,
    ) -> Mapping[str, float]:
        """Observations at current time step."""

        building = self.building

        normalize = False if normalize is None else normalize
        periodic_normalization = False if periodic_normalization is None else periodic_normalization
        include_all = False if include_all is None else include_all
        check_limits = False if check_limits is None else check_limits

        if observation_names is not None:
            valid_observations = list(observation_names)
            data = self.get_observations_data(include_all=include_all, observation_names=valid_observations)
        elif include_all:
            data = self.get_observations_data(include_all=include_all)
            valid_observations = list(set(data.keys()) | set(building.active_observations))
        else:
            valid_observations = building.active_observations
            data = self.get_observations_data(include_all=include_all, observation_names=valid_observations)

        valid_observation_set = set(valid_observations)

        observations = {k: data[k] for k in valid_observations if k in data}

        observations = self.update_ev_charger_observations(
            observations,
            valid_observation_set,
            building.electric_vehicle_chargers,
            include_all=include_all,
        )

        observations = self.update_deferrable_appliance_observations(
            observations,
            valid_observation_set,
            building.deferrable_appliances,
        )

        observations = self.update_escalator_observations(
            observations,
            valid_observation_set,
            building.escalators,
        )

        unknown_observations = set(observations.keys()).difference(set(valid_observations))
        assert len(unknown_observations) == 0, f'Unknown observations: {unknown_observations}'

        if check_limits:
            non_periodic_low_limit, non_periodic_high_limit = building.non_periodic_normalized_observation_space_limits
            for key in building.active_observations:
                value = observations[key]
                lower = non_periodic_low_limit[key]
                upper = non_periodic_high_limit[key]
                if not lower <= value <= upper:
                    report = {
                        'Building': building.name,
                        'episode': building.episode_tracker.episode,
                        'time_step': f'{building.time_step + 1}/{building.episode_tracker.episode_time_steps}',
                        'observation': key,
                        'value': value,
                        'lower': lower,
                        'upper': upper,
                    }
                    LOGGER.debug(f'Observation outside space limit: {report}')

        if periodic_normalization:
            periodic_observations = building.get_periodic_observation_metadata()
            observations_copy = {k: v for k, v in observations.items()}
            observations = {}
            periodic_normalizer = PeriodicNormalization(x_max=0)

            for key, value in observations_copy.items():
                if key in periodic_observations:
                    periodic_normalizer.x_max = max(periodic_observations[key])
                    sin_x, cos_x = value * periodic_normalizer
                    observations[f'{key}_cos'] = cos_x
                    observations[f'{key}_sin'] = sin_x
                else:
                    observations[key] = value

        if normalize:
            periodic_low_limit, periodic_high_limit = building.periodic_normalized_observation_space_limits
            normalizer = Normalize(0.0, 1.0)

            for key, value in observations.items():
                normalizer.x_min = periodic_low_limit[key]
                normalizer.x_max = periodic_high_limit[key]
                observations[key] = value * normalizer

        return observations

    def update_ev_charger_observations(self, observations, valid_observations, ev_chargers, include_all: bool = False):
        """Update observations for each electric vehicle charger."""

        building = self.building

        for charger in ev_chargers:
            charger_id = charger.charger_id
            sim = charger.charger_simulation
            t = building.time_step
            endogenous_t = t if include_all else max(t - 1, 0)

            connected_state_key = f'electric_vehicle_charger_{charger_id}_connected_state'
            incoming_state_key = f'electric_vehicle_charger_{charger_id}_incoming_state'
            departure_key = f'connected_electric_vehicle_at_charger_{charger_id}_departure_time'
            req_soc_key = f'connected_electric_vehicle_at_charger_{charger_id}_required_soc_departure'
            soc_key = f'connected_electric_vehicle_at_charger_{charger_id}_soc'
            capacity_key = f'connected_electric_vehicle_at_charger_{charger_id}_battery_capacity'
            arrival_key = f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_arrival_time'
            soc_arrival_key = f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_soc_arrival'
            charger_keys = (
                connected_state_key,
                incoming_state_key,
                departure_key,
                req_soc_key,
                soc_key,
                capacity_key,
                arrival_key,
                soc_arrival_key,
            )

            if not any(key in valid_observations for key in charger_keys):
                continue

            state = sim.electric_vehicle_charger_state[t] if t < len(sim.electric_vehicle_charger_state) else np.nan

            if charger.connected_electric_vehicle and state == 1:
                if connected_state_key in valid_observations:
                    observations[connected_state_key] = 1
                if departure_key in valid_observations:
                    observations[departure_key] = int(sim.electric_vehicle_departure_time[t])
                if req_soc_key in valid_observations:
                    observations[req_soc_key] = float(sim.electric_vehicle_required_soc_departure[t])
                if soc_key in valid_observations:
                    ev = charger.connected_electric_vehicle
                    observations[soc_key] = ev.battery.soc[ev.observation_soc_index(endogenous_t)]
                if capacity_key in valid_observations:
                    observations[capacity_key] = float(charger.connected_electric_vehicle.battery.capacity)
            else:
                if connected_state_key in valid_observations:
                    observations[connected_state_key] = 0
                if departure_key in valid_observations:
                    observations[departure_key] = -1
                if req_soc_key in valid_observations:
                    observations[req_soc_key] = -0.1
                if soc_key in valid_observations:
                    observations[soc_key] = -0.1
                if capacity_key in valid_observations:
                    observations[capacity_key] = -1.0

            if charger.incoming_electric_vehicle and state == 2:
                if incoming_state_key in valid_observations:
                    observations[incoming_state_key] = 1
                if arrival_key in valid_observations:
                    observations[arrival_key] = int(sim.electric_vehicle_estimated_arrival_time[t])
                if soc_arrival_key in valid_observations:
                    observations[soc_arrival_key] = float(sim.electric_vehicle_estimated_soc_arrival[t])
            else:
                if incoming_state_key in valid_observations:
                    observations[incoming_state_key] = 0
                if arrival_key in valid_observations:
                    observations[arrival_key] = -1
                if soc_arrival_key in valid_observations:
                    observations[soc_arrival_key] = -0.1

        return observations

    def update_deferrable_appliance_observations(self, observations, valid_observations, deferrable_appliances):
        """Update flat observations for each deferrable appliance."""

        for appliance in deferrable_appliances or []:
            prefix = f'deferrable_appliance_{appliance.name}_'
            if not any(key.startswith(prefix) for key in valid_observations):
                continue

            appliance_observations = self.deferrable_appliance_observations(appliance)
            for name, value in appliance_observations.items():
                key = f'deferrable_appliance_{appliance.name}_{name}'
                if key in valid_observations:
                    observations[key] = value

        return observations

    def deferrable_appliance_observations(self, appliance) -> Mapping[str, float]:
        """Return deferrable observations with feasibility-aware start readiness."""

        observations = dict(appliance.observations())
        if self._safe_scalar(observations.get('can_start', 0.0), 0.0) <= 0.0:
            return observations

        profile = self._deferrable_start_profile_kwh(appliance, 1.0)
        if profile.size <= 0 or not self._deferrable_profile_feasible(profile):
            observations['can_start'] = 0.0

        return observations

    def update_washing_machine_observations(self, observations, valid_observations, washing_machines):
        """Backward-compatible wrapper for old washing-machine integrations."""

        return self.update_deferrable_appliance_observations(observations, valid_observations, washing_machines)
        return observations

    def update_escalator_observations(self, observations, valid_observations, escalators):
        """Update flat observations for each aggregate escalator."""

        for escalator in escalators or []:
            prefix = f'escalator_{escalator.name}_'
            if not any(key.startswith(prefix) for key in valid_observations):
                continue
            for name, value in escalator.observations().items():
                key = f'{prefix}{name}'
                if key in valid_observations:
                    observations[key] = value

        return observations

    def get_observations_data(
        self,
        include_all: bool = False,
        observation_names: Optional[Iterable[str]] = None,
    ) -> Mapping[str, Union[float, int]]:
        """Build base observation dictionary without normalization."""

        building = self.building
        requested: Optional[Set[str]] = None if observation_names is None else set(observation_names)

        def wants(name: str) -> bool:
            return requested is None or name in requested

        electric_vehicle_chargers_dict = {}
        deferrable_appliances_dict = {}
        t = building.time_step
        endogenous_t = t if include_all else max(t - 1, 0)

        if wants('electric_vehicles_chargers_dict'):
            for charger in building.electric_vehicle_chargers or []:
                charger_id = charger.charger_id
                connected_car = charger.connected_electric_vehicle

                if connected_car is not None:
                    last_charged_kwh = 0.0
                    if 0 <= endogenous_t < len(charger.past_charging_action_values_kwh):
                        last_charged_kwh = float(charger.past_charging_action_values_kwh[endogenous_t])

                    battery_soc = connected_car.battery.soc[connected_car.observation_soc_index(endogenous_t)]
                    previous_battery_soc = connected_car.battery.initial_soc if endogenous_t == 0 else connected_car.battery.soc[endogenous_t - 1]

                    required_soc = charger.charger_simulation.electric_vehicle_required_soc_departure[t]
                    departure_steps = charger.charger_simulation.electric_vehicle_departure_time[t]
                    step_hours = building.seconds_per_time_step / 3600.0
                    hours_until_departure = (
                        float(departure_steps) * step_hours if departure_steps >= 0 else -1.0
                    )

                    battery_capacity = connected_car.battery.capacity
                    min_capacity = (1 - connected_car.battery.depth_of_discharge) * battery_capacity

                    electric_vehicle_chargers_dict[charger_id] = {
                        'connected': True,
                        'last_charged_kwh': last_charged_kwh,
                        'previous_battery_soc': previous_battery_soc,
                        'battery_soc': battery_soc,
                        'battery_capacity': battery_capacity,
                        'min_capacity': min_capacity,
                        'required_soc': required_soc,
                        'hours_until_departure': hours_until_departure,
                        'max_charging_power': charger.max_charging_power,
                        'max_discharging_power': charger.max_discharging_power,
                    }

                else:
                    last_charged_kwh = 0.0
                    if 0 <= endogenous_t < len(charger.past_charging_action_values_kwh):
                        last_charged_kwh = float(charger.past_charging_action_values_kwh[endogenous_t])

                    electric_vehicle_chargers_dict[charger_id] = {
                        'connected': False,
                        'last_charged_kwh': last_charged_kwh,
                        'previous_battery_soc': None,
                        'battery_soc': None,
                        'battery_capacity': None,
                        'min_capacity': None,
                        'required_soc': None,
                        'hours_until_departure': None,
                        'max_charging_power': charger.max_charging_power,
                        'max_discharging_power': charger.max_discharging_power,
                    }

        if wants('deferrable_appliances_dict') or wants('washing_machines_dict'):
            for appliance in building.deferrable_appliances or []:
                deferrable_appliances_dict[appliance.name] = dict(appliance.observations())

        observations = {}
        for key, series in building._energy_simulation_observation_sources:
            if wants(key) and t < len(series):
                observations[key] = series[t]

        for key, series in building._weather_observation_sources:
            if wants(key) and t < len(series):
                observations[key] = series[t]

        for key, series in building._pricing_observation_sources:
            if wants(key) and t < len(series):
                observations[key] = series[t]

        for key, series in building._carbon_observation_sources:
            if wants(key) and t < len(series):
                observations[key] = series[t]

        if wants('solar_generation'):
            observations['solar_generation'] = abs(building.solar_generation[t])
        if wants('cooling_storage_soc'):
            observations['cooling_storage_soc'] = building.cooling_storage.soc[endogenous_t]
        if wants('heating_storage_soc'):
            observations['heating_storage_soc'] = building.heating_storage.soc[endogenous_t]
        if wants('dhw_storage_soc'):
            observations['dhw_storage_soc'] = building.dhw_storage.soc[endogenous_t]
        if wants('electrical_storage_soc'):
            observations['electrical_storage_soc'] = building.electrical_storage.soc[endogenous_t]
        if wants('cooling_demand'):
            observations['cooling_demand'] = building.energy_from_cooling_device[endogenous_t] + abs(min(building.cooling_storage.energy_balance[endogenous_t], 0.0))
        if wants('heating_demand'):
            observations['heating_demand'] = building.energy_from_heating_device[endogenous_t] + abs(min(building.heating_storage.energy_balance[endogenous_t], 0.0))
        if wants('dhw_demand'):
            observations['dhw_demand'] = building.energy_from_dhw_device[endogenous_t] + abs(min(building.dhw_storage.energy_balance[endogenous_t], 0.0))
        if wants('net_electricity_consumption'):
            observations['net_electricity_consumption'] = building.net_electricity_consumption[endogenous_t]
        if wants('cooling_electricity_consumption'):
            observations['cooling_electricity_consumption'] = building.cooling_electricity_consumption[endogenous_t]
        if wants('heating_electricity_consumption'):
            observations['heating_electricity_consumption'] = building.heating_electricity_consumption[endogenous_t]
        if wants('dhw_electricity_consumption'):
            observations['dhw_electricity_consumption'] = building.dhw_electricity_consumption[endogenous_t]
        if wants('cooling_storage_electricity_consumption'):
            observations['cooling_storage_electricity_consumption'] = building.cooling_storage_electricity_consumption[endogenous_t]
        if wants('heating_storage_electricity_consumption'):
            observations['heating_storage_electricity_consumption'] = building.heating_storage_electricity_consumption[endogenous_t]
        if wants('dhw_storage_electricity_consumption'):
            observations['dhw_storage_electricity_consumption'] = building.dhw_storage_electricity_consumption[endogenous_t]
        if wants('electrical_storage_electricity_consumption'):
            observations['electrical_storage_electricity_consumption'] = building.electrical_storage_electricity_consumption[endogenous_t]
        if wants('deferrable_appliance_electricity_consumption'):
            observations['deferrable_appliance_electricity_consumption'] = building.deferrable_appliances_electricity_consumption[endogenous_t]
        if wants('washing_machine_electricity_consumption'):
            observations['washing_machine_electricity_consumption'] = building.deferrable_appliances_electricity_consumption[endogenous_t]
        if wants('cooling_device_efficiency'):
            observations['cooling_device_efficiency'] = building.cooling_device.get_cop(building.weather.outdoor_dry_bulb_temperature[t], heating=False)
        if wants('heating_device_efficiency'):
            observations['heating_device_efficiency'] = building.heating_device.get_cop(building.weather.outdoor_dry_bulb_temperature[t], heating=True) \
                if isinstance(building.heating_device, HeatPump) else building.heating_device.efficiency
        if wants('dhw_device_efficiency'):
            observations['dhw_device_efficiency'] = building.dhw_device.get_cop(building.weather.outdoor_dry_bulb_temperature[t], heating=True) \
                if isinstance(building.dhw_device, HeatPump) else building.dhw_device.efficiency
        if wants('indoor_dry_bulb_temperature_cooling_set_point'):
            observations['indoor_dry_bulb_temperature_cooling_set_point'] = building.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[t]
        if wants('indoor_dry_bulb_temperature_heating_set_point'):
            observations['indoor_dry_bulb_temperature_heating_set_point'] = building.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[t]
        if wants('indoor_dry_bulb_temperature_cooling_delta'):
            observations['indoor_dry_bulb_temperature_cooling_delta'] = building.energy_simulation.indoor_dry_bulb_temperature[t] - building.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[t]
        if wants('indoor_dry_bulb_temperature_heating_delta'):
            observations['indoor_dry_bulb_temperature_heating_delta'] = building.energy_simulation.indoor_dry_bulb_temperature[t] - building.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[t]
        if wants('comfort_band'):
            observations['comfort_band'] = building.energy_simulation.comfort_band[t]
        if wants('occupant_count'):
            observations['occupant_count'] = building.energy_simulation.occupant_count[t]
        if wants('power_outage'):
            observations['power_outage'] = building.power_outage_signal[t]
        if wants('electric_vehicles_chargers_dict'):
            observations['electric_vehicles_chargers_dict'] = electric_vehicle_chargers_dict
        if wants('deferrable_appliances_dict'):
            observations['deferrable_appliances_dict'] = deferrable_appliances_dict
        if wants('washing_machines_dict'):
            observations['washing_machines_dict'] = deferrable_appliances_dict

        if (
            getattr(building, '_charging_constraints_enabled', False)
            and getattr(building, '_expose_charging_constraints', False)
            and isinstance(building._charging_constraints_state, dict)
        ):
            state = building._charging_constraints_state
            headroom = state.get('building_headroom_kw')
            if headroom is not None and wants('charging_building_headroom_kw'):
                observations['charging_building_headroom_kw'] = headroom
            export_headroom = state.get('building_export_headroom_kw')
            if export_headroom is not None and wants('charging_building_export_headroom_kw'):
                observations['charging_building_export_headroom_kw'] = export_headroom
            for phase_name, value in (state.get('phase_headroom_kw') or {}).items():
                key = f'charging_phase_{phase_name}_headroom_kw'
                if value is not None and wants(key):
                    observations[key] = value
            for phase_name, value in (state.get('phase_export_headroom_kw') or {}).items():
                key = f'charging_phase_{phase_name}_export_headroom_kw'
                if value is not None and wants(key):
                    observations[key] = value

        if getattr(building, '_charging_constraints_enabled', False):
            if getattr(building, '_expose_charging_violation', False) and wants('charging_constraint_violation_kwh'):
                observations['charging_constraint_violation_kwh'] = building._charging_constraint_last_penalty_kwh
            if getattr(building, '_phase_encoding_observations', None):
                observations.update({
                    key: value
                    for key, value in building._phase_encoding_observations.items()
                    if wants(key)
                })

        return observations

    def apply_actions(
        self,
        cooling_or_heating_device_action: float = None,
        cooling_device_action: float = None,
        heating_device_action: float = None,
        cooling_storage_action: float = None,
        heating_storage_action: float = None,
        dhw_storage_action: float = None,
        electrical_storage_action: float = None,
        deferrable_appliance_actions: dict = None,
        washing_machine_actions: dict = None,
        escalator_actions: dict = None,
        electric_vehicle_storage_actions: dict = None,
    ):
        """Update demand and charge/discharge storage devices."""

        building = self.building
        action_cache = self._get_apply_action_cache()
        active_action_set = action_cache['active_action_set']

        if electric_vehicle_storage_actions is not None:
            electric_vehicle_storage_actions = dict(electric_vehicle_storage_actions)

        if 'cooling_or_heating_device' in active_action_set:
            assert 'cooling_device' not in active_action_set and 'heating_device' not in active_action_set, \
                'cooling_device and heating_device actions must be set to False when cooling_or_heating_device is True.' \
                ' They will be implicitly set based on the polarity of cooling_or_heating_device.'
            cooling_device_action = abs(min(cooling_or_heating_device_action, 0.0))
            heating_device_action = abs(max(cooling_or_heating_device_action, 0.0))

        else:
            assert not ('cooling_device' in active_action_set and 'heating_device' in active_action_set), \
                'cooling_device and heating_device actions cannot both be set to True to avoid both actions having' \
                ' values > 0.0 in the same time step. Use cooling_or_heating_device action instead to control' \
                ' both cooling_device and heating_device in a building.'
            cooling_device_action = np.nan if 'cooling_device' not in active_action_set else cooling_device_action
            heating_device_action = np.nan if 'heating_device' not in active_action_set else heating_device_action

        cooling_storage_action = 0.0 if 'cooling_storage' not in active_action_set else cooling_storage_action
        heating_storage_action = 0.0 if 'heating_storage' not in active_action_set else heating_storage_action
        dhw_storage_action = 0.0 if 'dhw_storage' not in active_action_set else dhw_storage_action
        electrical_storage_action = 0.0 if 'electrical_storage' not in active_action_set else electrical_storage_action

        if deferrable_appliance_actions is None:
            deferrable_appliance_actions = washing_machine_actions
        requested_electric_vehicle_storage_actions = (
            None if electric_vehicle_storage_actions is None else dict(electric_vehicle_storage_actions)
        )
        requested_electrical_storage_action = electrical_storage_action
        requested_deferrable_appliance_actions = (
            None if deferrable_appliance_actions is None else dict(deferrable_appliance_actions)
        )
        requested_escalator_actions = None if escalator_actions is None else dict(escalator_actions)
        if deferrable_appliance_actions is not None:
            deferrable_appliance_actions = self._apply_deferrable_profile_constraints(deferrable_appliance_actions)

        if building._charging_constraints_enabled:
            electric_vehicle_storage_actions, electrical_storage_action = self.apply_charging_constraints_to_actions(
                electric_vehicle_storage_actions,
                electrical_storage_action,
                deferrable_appliance_actions,
            )
        else:
            building._charging_constraint_penalty_kwh = 0.0
            building._charging_constraint_last_penalty_kwh = 0.0

        if requested_electric_vehicle_storage_actions is not None:
            charger_by_id = action_cache['charger_by_id']
            for charger_id, requested_action in requested_electric_vehicle_storage_actions.items():
                charger = charger_by_id.get(charger_id)
                if charger is None:
                    continue
                limited_action = (electric_vehicle_storage_actions or {}).get(charger_id, 0.0)
                self._record_charger_action_feedback(charger, requested_action, limited_action)

        if requested_electrical_storage_action is not None:
            self._record_storage_action_feedback(requested_electrical_storage_action, electrical_storage_action)

        if requested_deferrable_appliance_actions is not None:
            appliance_by_action = action_cache['deferrable_appliance_by_action']
            for action_name, requested_action in requested_deferrable_appliance_actions.items():
                appliance = appliance_by_action.get(action_name)
                if appliance is None:
                    continue
                limited_action = (deferrable_appliance_actions or {}).get(action_name, 0.0)
                self._record_deferrable_action_feedback(appliance, requested_action, limited_action)

        actions = {
            'cooling_demand': (building.update_cooling_demand, (cooling_device_action,)),
            'heating_demand': (building.update_heating_demand, (heating_device_action,)),
            'cooling_device': (building.update_energy_from_cooling_device, ()),
            'cooling_storage': (building.update_cooling_storage, (cooling_storage_action,)),
            'heating_device': (building.update_energy_from_heating_device, ()),
            'heating_storage': (building.update_heating_storage, (heating_storage_action,)),
            'dhw_device': (building.update_energy_from_dhw_device, ()),
            'dhw_storage': (building.update_dhw_storage, (dhw_storage_action,)),
            'non_shiftable_load': (building.update_non_shiftable_load, ()),
            'electrical_storage': (building.update_electrical_storage, (electrical_storage_action,)),
        }

        priority_list = list(actions.keys())

        if electric_vehicle_storage_actions is not None:
            electric_vehicle_priority_list = []
            charger_by_id = action_cache['charger_by_id']
            for charger_id, action in electric_vehicle_storage_actions.items():
                action_key = f'electric_vehicle_storage_{charger_id}'
                if action_key not in active_action_set:
                    raise ValueError('This action should not be applied. Verify')
                charger = charger_by_id.get(charger_id)
                if charger is not None:
                    actions[action_key] = (charger.update_connected_electric_vehicle_soc, (action,))
                    electric_vehicle_priority_list.append(action_key)
            priority_list = priority_list + electric_vehicle_priority_list

        if deferrable_appliance_actions is not None:
            deferrable_appliance_priority_list = []
            appliance_by_action = action_cache['deferrable_appliance_by_action']
            for action_name, action in deferrable_appliance_actions.items():
                action_key = f'{action_name}'
                if action_key not in active_action_set:
                    raise ValueError('This action should not be applied. Verify')
                appliance = appliance_by_action.get(action_key)
                if appliance is not None:
                    actions[action_key] = (appliance.start_cycle, (action,))
                    deferrable_appliance_priority_list.append(action_key)
            priority_list = priority_list + deferrable_appliance_priority_list

        if requested_escalator_actions is not None:
            escalator_priority_list = []
            escalator_by_action = action_cache['escalator_by_action']
            for action_name, action in requested_escalator_actions.items():
                action_key = f'{action_name}'
                if action_key not in active_action_set:
                    raise ValueError('This action should not be applied. Verify')
                escalator = escalator_by_action.get(action_key)
                if escalator is not None:
                    actions[action_key] = (escalator.set_state, (action,))
                    escalator_priority_list.append(action_key)
            priority_list = priority_list + escalator_priority_list

        if electrical_storage_action < 0.0:
            key = 'electrical_storage'
            priority_list.remove(key)
            priority_list = [key] + priority_list

        for key in ['cooling', 'heating', 'dhw']:
            storage = f'{key}_storage'
            device = f'{key}_device'

            if actions[storage][1][0] < 0.0:
                storage_ix = priority_list.index(storage)
                device_ix = priority_list.index(device)
                priority_list[storage_ix] = device
                priority_list[device_ix] = storage

        limit_control_actions = bool(building.power_outage)
        for key in priority_list:
            func, args = actions[key]
            if args and (limit_control_actions or key.startswith('deferrable_appliance_') or key.startswith('escalator_')):
                original_args = args
                args = self._limit_outage_control_action(key, func, args)
                if args != original_args:
                    owner = getattr(func, '__self__', None)
                    if key.startswith('electric_vehicle_storage_') and owner is not None:
                        requested = self._safe_index(getattr(owner, 'action_feedback_requested_action_normalized', []), building.time_step, 0.0)
                        self._record_charger_action_feedback(owner, requested, args[0])
                        self._set_feedback_reason(owner, 'outage')
                    elif key.startswith('deferrable_appliance_') and owner is not None:
                        requested = self._safe_index(getattr(owner, 'action_feedback_last_start_requested', []), building.time_step, 0.0)
                        self._record_deferrable_action_feedback(owner, requested, args[0])
                        self._set_feedback_reason(owner, 'outage')

            try:
                func(*args)
                owner = getattr(func, '__self__', None)
                if key.startswith('electric_vehicle_storage_') and owner is not None:
                    self._record_charger_post_apply_feedback(owner)
                elif key == 'electrical_storage':
                    self._record_storage_post_apply_feedback()
                elif key.startswith('deferrable_appliance_') and owner is not None:
                    self._record_deferrable_post_apply_feedback(owner)
            except NotImplementedError:
                pass

    def _get_apply_action_cache(self) -> Mapping[str, object]:
        building = self.building
        active_actions = tuple(building.active_actions)
        chargers = tuple(building.electric_vehicle_chargers or ())
        appliances = tuple(building.deferrable_appliances or ())
        escalators = tuple(building.escalators or ())
        signature = (
            active_actions,
            tuple((id(charger), charger.charger_id) for charger in chargers),
            tuple((id(appliance), appliance.name) for appliance in appliances),
            tuple((id(escalator), escalator.name) for escalator in escalators),
        )
        cache = getattr(self, '_apply_action_cache', None)

        if cache is not None and cache.get('signature') == signature:
            return cache

        appliance_by_action = {}
        for appliance in appliances:
            appliance_by_action[appliance.name] = appliance
            appliance_by_action[f'deferrable_appliance_{appliance.name}'] = appliance

        escalator_by_action = {}
        for escalator in escalators:
            escalator_by_action[escalator.name] = escalator
            escalator_by_action[f'escalator_{escalator.name}'] = escalator

        cache = {
            'signature': signature,
            'active_action_set': set(active_actions),
            'charger_by_id': {charger.charger_id: charger for charger in chargers},
            'deferrable_appliance_by_action': appliance_by_action,
            'escalator_by_action': escalator_by_action,
        }
        self._apply_action_cache = cache
        return cache

    def _safe_scalar(self, value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not np.isfinite(scalar):
            return float(default)

        return scalar

    def _safe_index(self, values, idx: int, default: float = 0.0) -> float:
        try:
            return self._safe_scalar(values[idx], default)
        except Exception:
            return float(default)

    def _ensure_feedback_array(self, owner, name: str):
        expected = int(getattr(self.building.episode_tracker, 'episode_time_steps', 0) or 0)
        cache = getattr(owner, '_action_feedback_array_cache', None)
        if cache is None:
            cache = {}
            setattr(owner, '_action_feedback_array_cache', cache)

        dtype = self._feedback_array_dtype(name)
        cache_key = (name, expected, np.dtype(dtype).str)
        values = cache.get(cache_key)
        if values is not None:
            return values

        values = getattr(owner, name, None)
        if values is None or len(values) != expected or getattr(values, 'dtype', None) != np.dtype(dtype):
            values = np.zeros(expected, dtype=dtype)
            setattr(owner, name, values)
        cache[cache_key] = values
        return values

    @staticmethod
    def _feedback_array_dtype(name: str):
        if (
            'clip_reason_' in name
            or name.endswith('last_start_requested')
            or name.endswith('last_start_applied')
            or name.endswith('start_blocked')
        ):
            return np.bool_

        return np.float32

    def _set_feedback_value(self, owner, name: str, value: float):
        t = int(self.building.time_step)
        values = self._ensure_feedback_array(owner, name)
        if 0 <= t < len(values):
            values[t] = self._safe_scalar(value, 0.0)

    def _clear_feedback_reasons(self, owner, prefix: str = 'action_feedback_'):
        for reason in (
            'availability',
            'power_limit',
            'soc_limit',
            'building_headroom',
            'phase_headroom',
            'export_headroom',
            'outage',
            'deferrable_window',
        ):
            self._set_feedback_value(owner, f'{prefix}clip_reason_{reason}', 0.0)

    def _set_feedback_reason(self, owner, reason: str, prefix: str = 'action_feedback_'):
        self._set_feedback_value(owner, f'{prefix}clip_reason_{reason}', 1.0)

    def _constraint_clip_reasons(self, requested_power_kw: float, limited_power_kw: float) -> List[str]:
        if abs(requested_power_kw - limited_power_kw) <= 1.0e-6:
            return []

        building = self.building
        state = getattr(building, '_charging_constraints_state', {}) or {}
        reasons: List[str] = []
        building_headroom = self._safe_scalar(state.get('building_headroom_kw'), np.nan)
        export_headroom = self._safe_scalar(state.get('building_export_headroom_kw'), np.nan)
        phase_headrooms = [
            self._safe_scalar(value, np.nan)
            for value in (state.get('phase_headroom_kw') or {}).values()
        ]
        phase_export_headrooms = [
            self._safe_scalar(value, np.nan)
            for value in (state.get('phase_export_headroom_kw') or {}).values()
        ]

        if requested_power_kw > limited_power_kw and np.isfinite(building_headroom) and building_headroom <= 1.0e-6:
            reasons.append('building_headroom')
        if requested_power_kw < limited_power_kw and np.isfinite(export_headroom) and export_headroom <= 1.0e-6:
            reasons.append('export_headroom')
        if any(np.isfinite(value) and value <= 1.0e-6 for value in phase_headrooms):
            reasons.append('phase_headroom')
        if any(np.isfinite(value) and value <= 1.0e-6 for value in phase_export_headrooms):
            reasons.append('export_headroom')
        if not reasons:
            reasons.append('power_limit')
        return reasons

    def _record_charger_action_feedback(self, charger, requested_action: float, limited_action: float):
        requested_action = float(np.clip(self._safe_scalar(requested_action, 0.0), -1.0, 1.0))
        limited_action = float(np.clip(self._safe_scalar(limited_action, 0.0), -1.0, 1.0))
        requested_power = self._charger_requested_power_kw(charger, requested_action)
        limited_power = self._charger_requested_power_kw(charger, limited_action)

        self._set_feedback_value(charger, 'action_feedback_requested_action_normalized', requested_action)
        self._set_feedback_value(charger, 'action_feedback_limited_action_normalized', limited_action)
        self._set_feedback_value(charger, 'action_feedback_requested_power_kw', requested_power)
        self._set_feedback_value(charger, 'action_feedback_limited_power_kw', limited_power)
        self._clear_feedback_reasons(charger)

        if abs(requested_action) > 1.0e-9 and abs(requested_power) <= 1.0e-9:
            self._set_feedback_reason(charger, 'power_limit')
        if abs(requested_power) > 1.0e-9 and charger.connected_electric_vehicle is None:
            self._set_feedback_reason(charger, 'availability')
        for reason in self._constraint_clip_reasons(requested_power, limited_power):
            self._set_feedback_reason(charger, reason)

    def _record_charger_post_apply_feedback(self, charger):
        t = int(self.building.time_step)
        limited_power = self._safe_index(getattr(charger, 'action_feedback_limited_power_kw', []), t, 0.0)
        applied_energy = self._safe_index(charger.electricity_consumption, t, 0.0)
        applied_power = self._control_step_energy_to_power_kw(applied_energy)
        if abs(limited_power) > 1.0e-6 and abs(applied_power - limited_power) > 1.0e-6:
            if charger.connected_electric_vehicle is None:
                self._set_feedback_reason(charger, 'availability')
            else:
                self._set_feedback_reason(charger, 'soc_limit')

    def _record_storage_action_feedback(self, requested_action: float, limited_action: float):
        building = self.building
        prefix = 'action_feedback_electrical_storage_'
        requested_action = float(np.clip(self._safe_scalar(requested_action, 0.0), -1.0, 1.0))
        limited_action = float(np.clip(self._safe_scalar(limited_action, 0.0), -1.0, 1.0))
        requested_power = self._storage_requested_power_kw(requested_action)
        limited_power = self._storage_requested_power_kw(limited_action)

        self._set_feedback_value(building, f'{prefix}requested_action_normalized', requested_action)
        self._set_feedback_value(building, f'{prefix}limited_action_normalized', limited_action)
        self._set_feedback_value(building, f'{prefix}requested_power_kw', requested_power)
        self._set_feedback_value(building, f'{prefix}limited_power_kw', limited_power)
        self._clear_feedback_reasons(building, prefix=prefix)
        for reason in self._constraint_clip_reasons(requested_power, limited_power):
            self._set_feedback_reason(building, reason, prefix=prefix)

    def _record_storage_post_apply_feedback(self):
        building = self.building
        prefix = 'action_feedback_electrical_storage_'
        t = int(building.time_step)
        limited_power = self._safe_index(getattr(building, f'{prefix}limited_power_kw', []), t, 0.0)
        applied_energy = self._safe_index(building.electrical_storage.electricity_consumption, t, 0.0)
        applied_power = self._control_step_energy_to_power_kw(applied_energy)
        if abs(limited_power) > 1.0e-6 and abs(applied_power - limited_power) > 1.0e-6:
            if building.power_outage and limited_power < 0.0:
                self._set_feedback_reason(building, 'outage', prefix=prefix)
            else:
                self._set_feedback_reason(building, 'soc_limit', prefix=prefix)

    def _record_deferrable_action_feedback(self, appliance, requested_action: float, limited_action: float):
        requested_action = self._safe_scalar(requested_action, 0.0)
        limited_action = self._safe_scalar(limited_action, 0.0)
        requested_start = 1.0 if getattr(appliance, '_is_start_command')(requested_action) else 0.0
        limited_start = 1.0 if getattr(appliance, '_is_start_command')(limited_action) else 0.0
        self._set_feedback_value(appliance, 'action_feedback_last_start_requested', requested_start)
        self._set_feedback_value(appliance, 'action_feedback_last_start_applied', 0.0)
        self._set_feedback_value(appliance, 'action_feedback_start_blocked', 1.0 if requested_start and not limited_start else 0.0)
        self._clear_feedback_reasons(appliance)

        if requested_start and not limited_start:
            reasons = self._deferrable_block_reasons(appliance, requested_action)
            for reason in reasons:
                self._set_feedback_reason(appliance, reason)

    def _record_deferrable_post_apply_feedback(self, appliance):
        t = int(self.building.time_step)
        requested = self._safe_index(getattr(appliance, 'action_feedback_last_start_requested', []), t, 0.0)
        if requested <= 0.0:
            return
        current_energy = self._safe_index(appliance.electricity_consumption, t, 0.0)
        applied = 1.0 if current_energy > 1.0e-9 else 0.0
        self._set_feedback_value(appliance, 'action_feedback_last_start_applied', applied)
        self._set_feedback_value(appliance, 'action_feedback_start_blocked', 1.0 if applied <= 0.0 else 0.0)
        if applied <= 0.0:
            for reason in self._deferrable_block_reasons(appliance, 1.0):
                self._set_feedback_reason(appliance, reason)

    def _dataset_energy_to_control_step(self, energy_kwh: float) -> float:
        ratio = getattr(self.building, 'time_step_ratio', None)
        ratio = 1.0 if ratio in (None, 0) else float(ratio)
        return float(energy_kwh) * ratio

    def _control_step_energy_to_power_kw(self, energy_kwh: float) -> float:
        return energy_kwh_to_power_kw(energy_kwh, self.building.seconds_per_time_step)

    def _limit_outage_control_action(self, action_key: str, func, args: Tuple) -> Tuple:
        building = self.building
        if not args:
            return args

        action = self._safe_scalar(args[0], 0.0)

        if action_key.startswith('deferrable_appliance_'):
            appliance = getattr(func, '__self__', None)
            if appliance is None:
                return (0.0,)

            profile = self._deferrable_start_profile_kwh(appliance, action)
            if profile.size <= 0:
                return args
            if building.power_outage and profile[0] > building.downward_electrical_flexibility + 1.0e-9:
                return (0.0,)
            return args if self._deferrable_profile_feasible(profile) else (0.0,)

        if action_key.startswith('escalator_'):
            return (0.0,) if building.power_outage else args

        if not building.power_outage:
            return args

        if action_key.startswith('electric_vehicle_storage_'):
            charger = getattr(func, '__self__', None)
            if charger is None or action <= 0.0:
                return (0.0,)

            available_energy_kwh = max(self._safe_scalar(building.downward_electrical_flexibility, 0.0), 0.0)
            available_power_kw = self._control_step_energy_to_power_kw(available_energy_kwh)
            requested_power_kw = max(self._charger_requested_power_kw(charger, action), 0.0)
            target_power_kw = min(requested_power_kw, available_power_kw)
            return (self._charger_action_from_power_kw(charger, target_power_kw),)
        return args

    def _current_phase_names(self):
        building = self.building
        if getattr(building, '_electrical_service_mode', 'single_phase') == 'three_phase':
            return ['L1', 'L2', 'L3']
        return ['L1']

    def _split_unassigned_power(self, power_kw: float) -> Dict[str, float]:
        building = self.building
        phase_names = self._current_phase_names()

        if len(phase_names) == 1:
            return {'L1': float(power_kw)}

        split_mode = str(getattr(building, '_electrical_service_default_split', 'balanced')).strip().lower()
        if split_mode in {'l1', 'l2', 'l3'}:
            return {phase: float(power_kw if phase.lower() == split_mode else 0.0) for phase in phase_names}

        share = float(power_kw) / len(phase_names)
        return {phase: share for phase in phase_names}

    def _split_power_by_connection(self, power_kw: float, phase_connection: Optional[str]) -> Dict[str, float]:
        phase_names = self._current_phase_names()

        if len(phase_names) == 1:
            return {'L1': float(power_kw)}

        if phase_connection in {'L1', 'L2', 'L3'}:
            return {phase: float(power_kw if phase == phase_connection else 0.0) for phase in phase_names}

        if phase_connection == 'all_phases':
            share = float(power_kw) / len(phase_names)
            return {phase: share for phase in phase_names}

        return self._split_unassigned_power(power_kw)

    def _find_deferrable_appliance(self, action_name: str):
        return self._get_apply_action_cache()['deferrable_appliance_by_action'].get(str(action_name))

    def _deferrable_start_profile_kwh(self, appliance, action: float) -> np.ndarray:
        preview_profile = getattr(appliance, 'preview_start_profile_kwh', None)
        if callable(preview_profile):
            return np.array(preview_profile(action), dtype='float64')

        energy = self._safe_scalar(appliance.preview_start_energy_kwh(action), 0.0)
        return np.array([energy], dtype='float64') if energy > 0.0 else np.zeros(0, dtype='float64')

    def _apply_deferrable_profile_constraints(self, actions: Mapping[str, float]) -> Mapping[str, float]:
        adjusted = dict(actions)
        reserved_energy_by_step: Dict[int, float] = {}

        for action_name, action in actions.items():
            appliance = self._find_deferrable_appliance(action_name)
            if appliance is None:
                continue

            profile = self._deferrable_start_profile_kwh(appliance, action)
            if profile.size <= 0:
                continue

            if self._deferrable_profile_feasible(profile, reserved_energy_by_step=reserved_energy_by_step):
                current_step = int(self.building.time_step)
                for offset, energy_kwh in enumerate(profile):
                    step = current_step + offset
                    reserved_energy_by_step[step] = reserved_energy_by_step.get(step, 0.0) + float(energy_kwh)
            else:
                adjusted[action_name] = 0.0

        return adjusted

    def _power_outage_at_step(self, step: int) -> bool:
        building = self.building
        if not getattr(building, 'simulate_power_outage', False):
            return False
        signal = getattr(building, '_Building__power_outage_signal', None)
        if signal is None:
            signal = getattr(building.energy_simulation, 'power_outage', [])
        return bool(self._safe_index(signal, step, 0.0))

    def _solar_generation_energy_at_step(self, step: int) -> float:
        building = self.building
        solar_generation = getattr(building, '_Building__solar_generation', None)
        if solar_generation is not None:
            return self._safe_index(solar_generation, step, 0.0)

        raw_generation = self._safe_index(getattr(building.energy_simulation, 'solar_generation', []), step, 0.0)
        converted = building._pv_generation_to_control_step([raw_generation])
        return -self._safe_index(converted, 0, 0.0)

    def _building_series_value(self, private_name: str, public_name: str, step: int, default: float = 0.0) -> float:
        values = getattr(self.building, f'_Building__{private_name}', None)
        if values is None:
            values = getattr(self.building, public_name, [])
        return self._safe_index(values, step, default)

    def _estimate_base_power_at_step(self, step: int) -> Tuple[float, Dict[str, float]]:
        building = self.building
        phase_names = self._current_phase_names()
        temperature = self._safe_index(building.weather.outdoor_dry_bulb_temperature, step, 0.0)

        cooling_demand = self._dataset_energy_to_control_step(
            self._building_series_value('energy_from_cooling_device', 'energy_from_cooling_device', step, 0.0)
        ) + self._safe_index(building.cooling_storage.energy_balance, step, 0.0)
        cooling_energy = self._safe_scalar(
            building.cooling_device.get_input_power(cooling_demand, temperature, heating=False),
            0.0,
        )
        cooling_kw = self._control_step_energy_to_power_kw(cooling_energy)

        heating_demand = self._dataset_energy_to_control_step(
            self._building_series_value('energy_from_heating_device', 'energy_from_heating_device', step, 0.0)
        ) + self._safe_index(building.heating_storage.energy_balance, step, 0.0)
        if isinstance(building.heating_device, HeatPump):
            heating_energy = self._safe_scalar(
                building.heating_device.get_input_power(heating_demand, temperature, heating=True),
                0.0,
            )
        else:
            heating_energy = self._safe_scalar(building.heating_device.get_input_power(heating_demand), 0.0)
        heating_kw = self._control_step_energy_to_power_kw(heating_energy)

        dhw_demand = self._dataset_energy_to_control_step(
            self._building_series_value('energy_from_dhw_device', 'energy_from_dhw_device', step, 0.0)
        ) + self._safe_index(building.dhw_storage.energy_balance, step, 0.0)
        if isinstance(building.dhw_device, HeatPump):
            dhw_energy = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand, temperature, heating=True), 0.0)
        else:
            dhw_energy = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand), 0.0)
        dhw_kw = self._control_step_energy_to_power_kw(dhw_energy)

        non_shiftable_energy = self._dataset_energy_to_control_step(
            self._building_series_value('energy_to_non_shiftable_load', 'energy_to_non_shiftable_load', step, 0.0)
        )
        non_shiftable_kw = self._control_step_energy_to_power_kw(non_shiftable_energy)
        solar_kw = self._control_step_energy_to_power_kw(self._solar_generation_energy_at_step(step))
        deferrable_kw = sum(
            self._control_step_energy_to_power_kw(self._safe_index(appliance.electricity_consumption, step, 0.0))
            for appliance in building.deferrable_appliances or []
        )

        base_total_kw = cooling_kw + heating_kw + dhw_kw + non_shiftable_kw + solar_kw + deferrable_kw
        return float(base_total_kw), {phase: value for phase, value in self._split_unassigned_power(base_total_kw).items() if phase in phase_names}

    def _electrical_service_allows(self, total_kw: float, phase_kw: Mapping[str, float]) -> bool:
        building = self.building
        if not getattr(building, '_electrical_service_enabled', False):
            return True

        total_limits = building._electrical_service_limits.get('total', {})
        import_limit = self._safe_scalar(total_limits.get('import_kw'), np.nan)
        export_limit = self._safe_scalar(total_limits.get('export_kw'), np.nan)
        tolerance = 1.0e-6
        if np.isfinite(import_limit) and total_kw > import_limit + tolerance:
            return False
        if np.isfinite(export_limit) and -total_kw > export_limit + tolerance:
            return False

        per_phase_limits = building._electrical_service_limits.get('per_phase', {})
        for phase_name in self._current_phase_names():
            phase_total = self._safe_scalar(phase_kw.get(phase_name, 0.0), 0.0)
            phase_limits = per_phase_limits.get(phase_name, {})
            phase_import_limit = self._safe_scalar(phase_limits.get('import_kw'), np.nan)
            phase_export_limit = self._safe_scalar(phase_limits.get('export_kw'), np.nan)
            if np.isfinite(phase_import_limit) and phase_total > phase_import_limit + tolerance:
                return False
            if np.isfinite(phase_export_limit) and -phase_total > phase_export_limit + tolerance:
                return False

        return True

    def _deferrable_profile_feasible(
        self,
        profile_kwh: np.ndarray,
        reserved_energy_by_step: Optional[Mapping[int, float]] = None,
    ) -> bool:
        reserved_energy_by_step = reserved_energy_by_step or {}
        current_step = int(self.building.time_step)
        episode_steps = int(getattr(self.building.episode_tracker, 'episode_time_steps', 0) or 0)

        for offset, energy_kwh in enumerate(profile_kwh):
            step = current_step + offset
            if step >= episode_steps:
                return False

            total_extra_energy = float(energy_kwh) + float(reserved_energy_by_step.get(step, 0.0))
            total_extra_kw = self._control_step_energy_to_power_kw(total_extra_energy)
            base_total_kw, base_phase_kw = self._estimate_base_power_at_step(step)
            extra_phase_kw = self._split_unassigned_power(total_extra_kw)
            total_kw = base_total_kw + total_extra_kw
            phase_kw = {
                phase: base_phase_kw.get(phase, 0.0) + extra_phase_kw.get(phase, 0.0)
                for phase in self._current_phase_names()
            }

            if self._power_outage_at_step(step) and total_kw > 1.0e-9:
                return False
            if not self._electrical_service_allows(total_kw, phase_kw):
                return False

        return True

    def _deferrable_block_reasons(self, appliance, action: float) -> List[str]:
        try:
            is_start = bool(appliance._is_start_command(action))
        except Exception:
            is_start = self._safe_scalar(action, 0.0) > 0.0
        if not is_start:
            return []

        observations = {}
        try:
            observations = dict(appliance.observations())
        except Exception:
            observations = {}

        if self._safe_scalar(observations.get('can_start', 0.0), 0.0) <= 0.0:
            return ['deferrable_window']

        profile = self._deferrable_start_profile_kwh(appliance, action)
        if profile.size <= 0:
            return ['deferrable_window']
        if self._deferrable_profile_feasible(profile):
            return []

        current_step = int(self.building.time_step)
        for offset in range(len(profile)):
            if self._power_outage_at_step(current_step + offset):
                return ['outage']
        if getattr(self.building, '_electrical_service_enabled', False):
            return ['building_headroom', 'phase_headroom']
        return ['deferrable_window']

    def _prospective_deferrable_start_power_kw(self, deferrable_appliance_actions: Optional[Mapping[str, float]]) -> float:
        if not deferrable_appliance_actions:
            return 0.0

        prospective_energy_kwh = 0.0

        for action_name, action in deferrable_appliance_actions.items():
            appliance = self._find_deferrable_appliance(action_name)
            if appliance is not None:
                prospective_energy_kwh += self._safe_scalar(appliance.preview_start_energy_kwh(action), 0.0)

        return self._control_step_energy_to_power_kw(prospective_energy_kwh)

    def _estimate_non_controllable_base_power(
        self,
        deferrable_appliance_actions: Optional[Mapping[str, float]] = None,
    ) -> Tuple[float, Dict[str, float]]:
        building = self.building
        t = building.time_step
        phase_names = self._current_phase_names()

        if building.power_outage:
            return 0.0, {phase: 0.0 for phase in phase_names}

        temperature = self._safe_index(building.weather.outdoor_dry_bulb_temperature, t, 0.0)

        cooling_demand = self._dataset_energy_to_control_step(
            self._safe_index(building.energy_from_cooling_device, t, 0.0)
        ) + self._safe_index(building.cooling_storage.energy_balance, t, 0.0)
        cooling_energy = self._safe_scalar(
            building.cooling_device.get_input_power(cooling_demand, temperature, heating=False),
            0.0,
        )
        cooling_kw = self._control_step_energy_to_power_kw(cooling_energy)

        heating_demand = self._dataset_energy_to_control_step(
            self._safe_index(building.energy_from_heating_device, t, 0.0)
        ) + self._safe_index(building.heating_storage.energy_balance, t, 0.0)
        if isinstance(building.heating_device, HeatPump):
            heating_energy = self._safe_scalar(
                building.heating_device.get_input_power(heating_demand, temperature, heating=True),
                0.0,
            )
        else:
            heating_energy = self._safe_scalar(building.heating_device.get_input_power(heating_demand), 0.0)
        heating_kw = self._control_step_energy_to_power_kw(heating_energy)

        dhw_demand = self._dataset_energy_to_control_step(
            self._safe_index(building.energy_from_dhw_device, t, 0.0)
        ) + self._safe_index(building.dhw_storage.energy_balance, t, 0.0)
        if isinstance(building.dhw_device, HeatPump):
            dhw_energy = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand, temperature, heating=True), 0.0)
        else:
            dhw_energy = self._safe_scalar(building.dhw_device.get_input_power(dhw_demand), 0.0)
        dhw_kw = self._control_step_energy_to_power_kw(dhw_energy)

        non_shiftable_energy = self._dataset_energy_to_control_step(
            self._safe_index(building.energy_to_non_shiftable_load, t, 0.0)
        )
        non_shiftable_kw = self._control_step_energy_to_power_kw(non_shiftable_energy)
        solar_kw = self._control_step_energy_to_power_kw(self._safe_index(building.solar_generation, t, 0.0))
        deferrable_kw = sum(
            self._control_step_energy_to_power_kw(self._safe_index(appliance.electricity_consumption, t, 0.0))
            for appliance in building.deferrable_appliances or []
        )
        deferrable_kw += self._prospective_deferrable_start_power_kw(deferrable_appliance_actions)

        base_total_kw = cooling_kw + heating_kw + dhw_kw + non_shiftable_kw + solar_kw + deferrable_kw
        base_phase_kw = self._split_unassigned_power(base_total_kw)

        return float(base_total_kw), base_phase_kw

    def _charger_requested_power_kw(self, charger, action: float) -> float:
        if action is None:
            return 0.0

        charger_request = getattr(charger, 'get_requested_power_kw', None)
        if callable(charger_request):
            return self._safe_scalar(charger_request(action), 0.0)

        action = self._safe_scalar(action, 0.0)
        action = float(np.clip(action, -1.0, 1.0))
        if action > 0.0:
            max_power = self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0)
            min_power = self._safe_scalar(getattr(charger, 'min_charging_power', 0.0), 0.0)
            request = action * max_power if max_power > 0.0 else 0.0
            return request if request >= min(min_power, max_power) else 0.0
        if action < 0.0:
            max_power = self._safe_scalar(getattr(charger, 'max_discharging_power', 0.0), 0.0)
            min_power = self._safe_scalar(getattr(charger, 'min_discharging_power', 0.0), 0.0)
            request = abs(action) * max_power if max_power > 0.0 else 0.0
            return -request if request >= min(min_power, max_power) else 0.0
        return 0.0

    def _charger_action_from_power_kw(self, charger, target_power_kw: float) -> float:
        target_power_kw = self._safe_scalar(target_power_kw, 0.0)

        if target_power_kw > 0.0:
            max_power = self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0)
            min_power = self._safe_scalar(getattr(charger, 'min_charging_power', 0.0), 0.0)
            if max_power <= 0.0:
                return 0.0
            if min_power > 0.0 and target_power_kw < min_power:
                return 0.0
            return float(np.clip(target_power_kw / max_power, 0.0, 1.0))

        if target_power_kw < 0.0:
            max_power = self._safe_scalar(getattr(charger, 'max_discharging_power', 0.0), 0.0)
            min_power = self._safe_scalar(getattr(charger, 'min_discharging_power', 0.0), 0.0)
            requested = abs(target_power_kw)
            if max_power <= 0.0:
                return 0.0
            if min_power > 0.0 and requested < min_power:
                return 0.0
            return float(-np.clip(requested / max_power, 0.0, 1.0))

        return 0.0

    def _storage_requested_power_kw(self, action: Optional[float]) -> float:
        building = self.building
        if action is None:
            return 0.0
        action = self._safe_scalar(action, 0.0)
        action = float(np.clip(action, -1.0, 1.0))
        nominal_power = self._safe_scalar(getattr(building.electrical_storage, 'nominal_power', 0.0), 0.0)
        return action * nominal_power if nominal_power > 0.0 else 0.0

    def _storage_action_from_power_kw(self, target_power_kw: float) -> float:
        building = self.building
        nominal_power = self._safe_scalar(getattr(building.electrical_storage, 'nominal_power', 0.0), 0.0)
        if nominal_power <= 0.0:
            return 0.0
        return float(np.clip(target_power_kw / nominal_power, -1.0, 1.0))

    def _electrical_service_violation_kw(
        self,
        total_kw: float,
        phase_kw: Mapping[str, float],
        total_limits: Mapping[str, float],
        per_phase_limits: Mapping[str, Mapping[str, float]],
        phase_names: List[str],
    ) -> float:
        # Retain the internal audit entry point; the formula lives with allocation.
        return electrical_service_violation_kw(
            total_kw, phase_kw, total_limits, per_phase_limits, phase_names)

    def _apply_legacy_charging_constraints(self, actions: Optional[Mapping[str, float]]) -> Optional[Mapping[str, float]]:
        building = self.building

        if not actions:
            building._set_default_charging_headroom()
            return actions

        positive_requests = {}
        scales = {}
        for charger_id, action in actions.items():
            if action is None or action <= 0.0:
                continue
            charger = building._charger_lookup.get(charger_id)
            if charger is None:
                continue
            requested_power = max(self._charger_requested_power_kw(charger, action), 0.0)
            if requested_power <= 0.0:
                continue
            positive_requests[charger_id] = requested_power
            scales[charger_id] = 1.0

        violation_kw = 0.0

        if positive_requests:
            total_kw = sum(positive_requests.values())
            building_limit = building._building_charger_limit_kw
            building_limit = self._safe_scalar(building_limit, np.nan)
            if np.isfinite(building_limit) and building_limit >= 0.0 and total_kw > building_limit:
                scale = 0.0 if building_limit == 0 else building_limit / total_kw
                for charger_id in scales:
                    scales[charger_id] *= scale
                violation_kw += total_kw - building_limit

            for phase in building._phase_limits:
                limit = phase.get('limit_kw')
                limit = self._safe_scalar(limit, np.nan)
                if not np.isfinite(limit) or limit < 0.0:
                    continue
                chargers = phase.get('chargers', []) or []
                phase_sum = sum(
                    positive_requests.get(charger_id, 0.0) * scales.get(charger_id, 1.0)
                    for charger_id in chargers
                    if charger_id in positive_requests
                )
                if phase_sum > limit:
                    phase_scale = 0.0 if limit == 0 else limit / phase_sum
                    for charger_id in chargers:
                        if charger_id in scales:
                            scales[charger_id] *= phase_scale
                    violation_kw += phase_sum - limit

            scaled_positive_kw = {
                charger_id: positive_requests[charger_id] * scales.get(charger_id, 1.0)
                for charger_id in positive_requests
            }
            used_kw = sum(scaled_positive_kw.values())

            actions = dict(actions)
            for charger_id, action in list(actions.items()):
                if action is None or action <= 0.0:
                    continue
                charger = building._charger_lookup.get(charger_id)
                if charger is None:
                    continue
                max_power = getattr(charger, 'max_charging_power', 0.0) or 0.0
                if max_power <= 0.0:
                    actions[charger_id] = 0.0
                    continue
                target_kw = scaled_positive_kw.get(charger_id, 0.0)
                actions[charger_id] = max(0.0, min(action, target_kw / max_power))

            if getattr(building, '_expose_charging_constraints', False):
                building_limit = self._safe_scalar(building._building_charger_limit_kw, np.nan)
                building_headroom = None if not np.isfinite(building_limit) else building_limit - used_kw
                phase_headroom = {}
                for phase in building._phase_limits:
                    limit = phase.get('limit_kw')
                    limit = self._safe_scalar(limit, np.nan)
                    if not np.isfinite(limit):
                        phase_headroom[phase['name']] = None
                    else:
                        used = sum(scaled_positive_kw.get(charger_id, 0.0) for charger_id in phase.get('chargers', []))
                        phase_headroom[phase['name']] = limit - used

                building._charging_constraints_state = {
                    'building_headroom_kw': building_headroom,
                    'building_export_headroom_kw': None,
                    'phase_headroom_kw': phase_headroom,
                    'phase_export_headroom_kw': {},
                    'total_power_kw': used_kw,
                    'phase_power_kw': {},
                }

            penalty_kwh = self._safe_scalar(power_kw_to_energy_kwh(violation_kw, building.seconds_per_time_step), 0.0)
            building._charging_constraint_penalty_kwh = penalty_kwh
            building._charging_constraint_last_penalty_kwh = penalty_kwh
            phase_power = {}
            if getattr(building, '_electrical_service_enabled', False):
                phase_power = dict((building._charging_constraints_state or {}).get('phase_power_kw') or {})
            building._record_charging_constraint_state(
                violation_kwh=penalty_kwh,
                total_power_kw=float((building._charging_constraints_state or {}).get('total_power_kw', used_kw)),
                phase_power_kw=phase_power,
            )

        else:
            building._set_default_charging_headroom()
            building._record_charging_constraint_state(
                violation_kwh=0.0,
                total_power_kw=0.0,
                phase_power_kw={},
            )

        return actions

    def _apply_electrical_service_constraints(
        self,
        actions: Optional[Mapping[str, float]],
        electrical_storage_action: Optional[float],
        deferrable_appliance_actions: Optional[Mapping[str, float]] = None,
    ) -> Tuple[Optional[Mapping[str, float]], Optional[float]]:
        building = self.building
        phase_names = self._current_phase_names()
        base_total_kw, base_phase_kw = self._estimate_non_controllable_base_power(deferrable_appliance_actions)
        base_phase_kw = {phase: base_phase_kw.get(phase, 0.0) for phase in phase_names}

        controls = {}
        adjusted_actions = None if actions is None else dict(actions)

        for charger_id, action in (actions or {}).items():
            charger = building._charger_lookup.get(charger_id)
            if charger is None:
                continue

            request_total_kw = self._charger_requested_power_kw(charger, action)
            if abs(request_total_kw) <= 1e-9:
                continue

            phase_connection = building._charger_phase_map.get(charger_id)
            request_phase_kw = self._split_power_by_connection(request_total_kw, phase_connection)
            controls[charger_id] = {
                'request_total_kw': request_total_kw,
                'request_phase_kw': request_phase_kw,
            }

        storage_control_id = '__electrical_storage__'
        request_storage_kw = self._storage_requested_power_kw(electrical_storage_action)
        if abs(request_storage_kw) > 1e-9:
            request_phase_kw = self._split_power_by_connection(request_storage_kw, building.electrical_storage_phase_connection)
            controls[storage_control_id] = {
                'request_total_kw': request_storage_kw,
                'request_phase_kw': request_phase_kw,
            }

        total_limits = building._electrical_service_limits.get('total', {})
        per_phase_limits = building._electrical_service_limits.get('per_phase', {})
        allocation = allocate_electrical_service(
            base_total_kw, base_phase_kw, controls, total_limits, per_phase_limits, phase_names,
        )
        scales = allocation.scales
        total_kw, phase_kw = allocation.total_kw, allocation.phase_kw

        if adjusted_actions is not None:
            for charger_id in adjusted_actions:
                charger = building._charger_lookup.get(charger_id)
                if charger is None:
                    continue
                control = controls.get(charger_id)
                target_kw = 0.0 if control is None else control['request_total_kw'] * scales.get(charger_id, 1.0)
                adjusted_actions[charger_id] = self._charger_action_from_power_kw(charger, target_kw)

        adjusted_storage_action = electrical_storage_action
        if electrical_storage_action is not None:
            storage_control = controls.get(storage_control_id)
            target_kw = 0.0 if storage_control is None else storage_control['request_total_kw'] * scales.get(storage_control_id, 1.0)
            adjusted_storage_action = self._storage_action_from_power_kw(target_kw)

        import_limit = self._safe_scalar(total_limits.get('import_kw'), np.nan)
        export_limit = self._safe_scalar(total_limits.get('export_kw'), np.nan)
        violation_kw = max(allocation.requested_violation_kw, allocation.residual_violation_kw)

        phase_headroom = {}
        phase_export_headroom = {}
        for phase_name in phase_names:
            phase_total = self._safe_scalar(phase_kw.get(phase_name, 0.0), 0.0)
            phase_limit = per_phase_limits.get(phase_name, {})
            phase_import_limit = self._safe_scalar(phase_limit.get('import_kw'), np.nan)
            phase_export_limit = self._safe_scalar(phase_limit.get('export_kw'), np.nan)

            phase_headroom[phase_name] = None if not np.isfinite(phase_import_limit) else (phase_import_limit - phase_total)
            phase_export_headroom[phase_name] = None if not np.isfinite(phase_export_limit) else (phase_export_limit + phase_total)

        building_headroom = None if not np.isfinite(import_limit) else (import_limit - total_kw)
        building_export_headroom = None if not np.isfinite(export_limit) else (export_limit + total_kw)
        building._charging_constraints_state = {
            'building_headroom_kw': building_headroom,
            'building_export_headroom_kw': building_export_headroom,
            'phase_headroom_kw': phase_headroom,
            'phase_export_headroom_kw': phase_export_headroom,
            'total_power_kw': total_kw,
            'phase_power_kw': phase_kw,
        }

        penalty_kwh = self._safe_scalar(power_kw_to_energy_kwh(violation_kw, building.seconds_per_time_step), 0.0)
        building._charging_constraint_penalty_kwh = penalty_kwh
        building._charging_constraint_last_penalty_kwh = penalty_kwh
        building._record_charging_constraint_state(
            violation_kwh=penalty_kwh,
            total_power_kw=float(total_kw),
            phase_power_kw=phase_kw,
        )

        return adjusted_actions, adjusted_storage_action

    def apply_charging_constraints_to_actions(
        self,
        actions: Optional[Mapping[str, float]],
        electrical_storage_action: Optional[float] = None,
        deferrable_appliance_actions: Optional[Mapping[str, float]] = None,
    ) -> Tuple[Optional[Mapping[str, float]], Optional[float]]:
        """Apply configured electrical constraints and return adjusted EV/storage actions."""

        building = self.building

        building._charging_constraint_penalty_kwh = 0.0
        building._charging_constraint_last_penalty_kwh = 0.0

        if not building._charging_constraints_enabled:
            return actions, electrical_storage_action

        if getattr(building, '_electrical_service_enabled', False):
            return self._apply_electrical_service_constraints(
                actions,
                electrical_storage_action,
                deferrable_appliance_actions,
            )

        adjusted_actions = self._apply_legacy_charging_constraints(actions)
        return adjusted_actions, electrical_storage_action
