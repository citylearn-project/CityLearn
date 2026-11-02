from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.electrical_limits import allocate_electrical_service


class _OperationalBaselineAgent(Agent):
    """Shared equipment dispatch and deadline-based EV service for native RBCs."""

    def __init__(
        self,
        env: CityLearnEnv,
        ev_target_soc: float = 1.0,
        ev_follow_required_soc: bool = False,
        ev_service_margin_rate: float = 0.02,
        ev_service_floor_rate: float = 0.0,
        storage_min_soc: float = 0.20,
        storage_max_soc: float = 0.90,
        storage_deadband_kw: float = 0.05,
        deferrable_start_action: float = 1.0,
        **kwargs: Any,
    ):
        self._building_action_layout_cache: Dict[int, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
        self.ev_target_soc = float(np.clip(1.0 if ev_target_soc is None else ev_target_soc, 0.0, 1.0))
        self.ev_follow_required_soc = bool(ev_follow_required_soc)
        self.ev_service_margin_rate = max(float(0.02 if ev_service_margin_rate is None else ev_service_margin_rate), 0.0)
        self.ev_service_floor_rate = max(float(0.0 if ev_service_floor_rate is None else ev_service_floor_rate), 0.0)
        self.storage_min_soc = float(np.clip(0.20 if storage_min_soc is None else storage_min_soc, 0.0, 1.0))
        self.storage_max_soc = float(np.clip(0.90 if storage_max_soc is None else storage_max_soc, 0.0, 1.0))
        if self.storage_max_soc < self.storage_min_soc:
            self.storage_min_soc, self.storage_max_soc = self.storage_max_soc, self.storage_min_soc
        self.storage_deadband_kw = max(float(0.05 if storage_deadband_kw is None else storage_deadband_kw), 0.0)
        self.deferrable_start_action = float(np.clip(1.0 if deferrable_start_action is None else deferrable_start_action, 0.0, 1.0))
        super().__init__(env, **kwargs)

        # Entity-interface envs still accept flat-like action payloads. Keep
        # agent bookkeeping in flat space so the same policy works in both modes.
        self.observation_space = self.env.unwrapped.flat_observation_space
        self.action_space = self.env.unwrapped.flat_action_space
        self.reset()

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        env = self.env.unwrapped
        if env.time_step == 0 and self.time_step != 0:
            self.reset()
        if getattr(env, 'topology_mode', 'static') == 'dynamic':
            version = env.topology_version
            if version != self._baseline_topology_version:
                self.action_space = env.flat_action_space
                self.action_names = env.action_names
                self.observation_space = env.flat_observation_space
                self.observation_names = env.observation_names
                self.building_metadata = env.get_metadata()['buildings']
                self._building_action_layout_cache.clear()
                self._baseline_topology_version = version
        per_building_actions = [
            self._building_action_vector(building)
            for building in env.buildings
        ]

        if env.central_agent:
            actions = [[value for vector in per_building_actions for value in vector]]
        else:
            actions = per_building_actions

        self.actions = actions
        self.next_time_step()
        return actions

    def comparison_identity(self):
        from citylearn import __version__
        keys = ('ev_target_soc', 'ev_follow_required_soc', 'ev_service_margin_rate', 'ev_service_floor_rate',
                'storage_min_soc', 'storage_max_soc', 'storage_deadband_kw', 'deferrable_start_action',
                'low_price_quantile', 'high_price_quantile', 'price_charge_rate', 'price_discharge_rate',
                'ev_price_charge_rate', 'pv_charge_rate', 'storage_discharge_rate', 'import_peak_threshold_kw',
                'ev_urgency_hours', 'community_surplus_charge_soc_ceiling', 'community_import_threshold_kw',
                'community_storage_discharge_rate', 'community_surplus_threshold_kw')
        return dict(implementation=type(self).__module__+'.'+type(self).__qualname__, version=__version__,
                    parameters={key: getattr(self, key) for key in keys if hasattr(self, key)},
                    observation_access='privileged_simulator_state')

    def _building_action_vector(self, building) -> List[float]:
        layout = self._building_action_layout(building)
        active_actions = layout['active_actions']
        bounds = layout['bounds']
        preliminary: Dict[str, float] = {}
        ev_requested_kw = 0.0
        deferrable_requested_kw = 0.0

        for action_name, (low, high) in zip(active_actions, bounds):
            if action_name.startswith('electric_vehicle_storage_'):
                charger = layout['charger_by_action'].get(action_name)
                value = self._ev_action_for_charger(charger, low, high, building=building)
                preliminary[action_name] = value
                ev_requested_kw += self._charger_requested_kw_for_charger(charger, value)

            elif action_name.startswith('deferrable_appliance_'):
                appliance = layout['appliance_by_action'].get(action_name)
                value = self._deferrable_action_for_appliance(appliance, low, high)
                preliminary[action_name] = value
                deferrable_requested_kw += self._deferrable_start_power_kw_for_appliance(building, appliance, value)

        actions = []
        for action_name, (low, high) in zip(active_actions, bounds):
            if action_name == 'electrical_storage':
                value = self._storage_action(
                    building,
                    low,
                    high,
                    prospective_ev_kw=ev_requested_kw,
                    prospective_deferrable_kw=deferrable_requested_kw,
                )
            elif action_name in preliminary:
                value = preliminary[action_name]
            else:
                value = 0.0

            actions.append(float(np.clip(value, low, high)))

        return self._apply_electrical_service_limits(building, active_actions, bounds, actions)

    def _building_action_layout(self, building) -> Dict[str, Any]:
        active_actions = tuple(building.active_actions)
        bounds = tuple(
            (float(low), float(high))
            for low, high in zip(building.action_space.low, building.action_space.high)
        )
        chargers = tuple((getattr(charger, 'charger_id', None), id(charger)) for charger in getattr(building, 'electric_vehicle_chargers', []) or [])
        appliances = tuple((getattr(appliance, 'name', None), id(appliance)) for appliance in getattr(building, 'deferrable_appliances', []) or [])
        key = (active_actions, bounds, chargers, appliances)
        cache_key = id(building)
        cached = self._building_action_layout_cache.get(cache_key)
        if cached is not None and cached[0] == key:
            return cached[1]

        charger_by_id = {
            getattr(charger, 'charger_id', None): charger
            for charger in getattr(building, 'electric_vehicle_chargers', []) or []
        }
        appliance_by_name = {
            getattr(appliance, 'name', None): appliance
            for appliance in getattr(building, 'deferrable_appliances', []) or []
        }
        charger_by_action = {}
        appliance_by_action = {}

        for action_name in active_actions:
            if action_name.startswith('electric_vehicle_storage_'):
                charger_id = action_name.replace('electric_vehicle_storage_', '', 1)
                charger_by_action[action_name] = charger_by_id.get(charger_id)
            elif action_name.startswith('deferrable_appliance_'):
                appliance_name = action_name.replace('deferrable_appliance_', '', 1)
                appliance_by_action[action_name] = appliance_by_name.get(appliance_name) or appliance_by_name.get(action_name)

        layout = {
            'active_actions': active_actions,
            'bounds': bounds,
            'charger_by_action': charger_by_action,
            'appliance_by_action': appliance_by_action,
        }
        self._building_action_layout_cache[cache_key] = (key, layout)
        return layout

    def _ev_action(self, building, charger_id: str, low: float, high: float) -> float:
        charger = self._charger(building, charger_id)
        return self._ev_action_for_charger(charger, low, high, building=building)

    def _ev_action_for_charger(self, charger, low: float, high: float, *, building=None) -> float:
        ev = None if charger is None else getattr(charger, 'connected_electric_vehicle', None)

        if ev is None:
            return 0.0

        service_context = self._ev_service_context_for_charger(building, charger)
        soc = service_context.get('soc')
        if soc is None:
            soc = self._current_soc(getattr(ev, 'battery', None))
        if soc is None or soc >= self.ev_target_soc - 1.0e-6:
            return 0.0

        max_power = self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0)
        if max_power <= 0.0:
            return 0.0

        required_soc = service_context.get('required_soc')
        if self.ev_follow_required_soc:
            target_soc = self.ev_target_soc if required_soc is None else required_soc
            target_soc = float(np.clip(target_soc, 0.0, self.ev_target_soc))
        else:
            target_soc = max(self.ev_target_soc, 0.0 if required_soc is None else required_soc)
            target_soc = float(np.clip(target_soc, 0.0, 1.0))

        if soc >= target_soc - 0.01:
            return 0.0

        departure_hours = max(service_context.get('departure_hours') or 1.0, 1.0e-6)
        capacity_kwh = service_context.get('capacity_kwh')
        if capacity_kwh is None:
            capacity_kwh = self._safe_scalar(getattr(getattr(ev, 'battery', None), 'capacity', 0.0), 0.0)

        if capacity_kwh > 0.0:
            required_rate = (target_soc - soc) * capacity_kwh / (departure_hours * max_power)
        else:
            required_rate = 1.0

        min_rate = self._safe_scalar(getattr(charger, 'min_charging_power', 0.0), 0.0) / max_power
        requested = max(required_rate + self.ev_service_margin_rate, self.ev_service_floor_rate, min_rate)
        return float(np.clip(requested, max(0.0, low), max(0.0, high)))

    def _ev_service_context_for_charger(self, building, charger) -> Dict[str, Optional[float]]:
        if building is None or charger is None:
            return {}

        try:
            observations = building.observations()
        except Exception:
            return {}

        charger_id = getattr(charger, 'charger_id', None)
        if charger_id is None:
            return {}

        prefix = f'connected_electric_vehicle_at_charger_{charger_id}_'
        return {
            'soc': self._optional_observation(observations, f'{prefix}soc'),
            'required_soc': self._optional_observation(observations, f'{prefix}required_soc_departure'),
            'capacity_kwh': self._optional_observation(observations, f'{prefix}battery_capacity'),
            'departure_hours': self._optional_observation(observations, f'{prefix}departure_time'),
        }

    def _deferrable_action(self, building, action_name: str, low: float, high: float) -> float:
        appliance = self._deferrable_appliance(building, action_name)
        return self._deferrable_action_for_appliance(appliance, low, high)

    def _deferrable_action_for_appliance(self, appliance, low: float, high: float) -> float:
        if appliance is None:
            return 0.0

        observations = appliance.observations()
        pending = self._safe_scalar(observations.get('pending'), 0.0)
        running = self._safe_scalar(observations.get('running'), 0.0)
        can_start = self._safe_scalar(observations.get('can_start'), 0.0)
        deadline_missed = self._safe_scalar(observations.get('deadline_missed'), 0.0)

        if pending > 0.5 and running <= 0.5 and can_start > 0.5 and deadline_missed <= 0.5:
            return float(np.clip(self.deferrable_start_action, low, high))

        return 0.0

    def _storage_action(
        self,
        building,
        low: float,
        high: float,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> float:
        storage = getattr(building, 'electrical_storage', None)
        nominal_power_kw = self._safe_scalar(getattr(storage, 'nominal_power', 0.0), 0.0)
        capacity = self._safe_scalar(getattr(storage, 'capacity', 0.0), 0.0)

        if storage is None or nominal_power_kw <= 0.0 or capacity <= 0.0:
            return 0.0

        soc = self._current_soc(storage)
        if soc is None:
            return 0.0

        load_kw = self._base_load_kw(building) + max(prospective_ev_kw, 0.0) + max(prospective_deferrable_kw, 0.0)
        pv_kw = self._pv_generation_kw(building)
        net_kw = load_kw - pv_kw

        if net_kw < -self.storage_deadband_kw and soc < self.storage_max_soc:
            return float(np.clip(min(-net_kw, nominal_power_kw) / nominal_power_kw, low, high))

        if net_kw > self.storage_deadband_kw and soc > self.storage_min_soc:
            return float(np.clip(-min(net_kw, nominal_power_kw) / nominal_power_kw, low, high))

        return float(np.clip(0.0, low, high))

    def _apply_electrical_service_limits(
        self,
        building,
        active_actions: Tuple[str, ...],
        bounds: Tuple[Tuple[float, float], ...],
        actions: List[float],
    ) -> List[float]:
        if not getattr(building, '_electrical_service_enabled', False):
            return actions

        ops = getattr(building, '_ops_service', None)
        if ops is None:
            return actions

        try:
            adjusted = list(actions)
            ev_action_indices: Dict[str, int] = {}
            ev_actions: Dict[str, float] = {}
            deferrable_actions: Dict[str, float] = {}
            storage_index: Optional[int] = None
            storage_action: Optional[float] = None

            for index, action_name in enumerate(active_actions):
                value = adjusted[index]
                if action_name.startswith('electric_vehicle_storage_'):
                    charger_id = action_name.replace('electric_vehicle_storage_', '', 1)
                    ev_action_indices[charger_id] = index
                    ev_actions[charger_id] = value
                elif action_name.startswith('deferrable_appliance_'):
                    deferrable_actions[action_name] = value
                elif action_name == 'electrical_storage':
                    storage_index = index
                    storage_action = value

            if not ev_actions and storage_action is None:
                return actions

            phase_names = ops._current_phase_names()
            base_total_kw, base_phase_kw = ops._estimate_non_controllable_base_power(deferrable_actions)
            base_phase_kw = {phase: base_phase_kw.get(phase, 0.0) for phase in phase_names}
            controls: Dict[str, Dict[str, Any]] = {}

            for charger_id, action in ev_actions.items():
                charger = getattr(building, '_charger_lookup', {}).get(charger_id)
                if charger is None:
                    continue

                requested_kw = ops._charger_requested_power_kw(charger, action)
                if abs(requested_kw) <= 1.0e-9:
                    continue

                phase_connection = getattr(building, '_charger_phase_map', {}).get(charger_id)
                controls[charger_id] = {
                    'request_total_kw': requested_kw,
                    'request_phase_kw': ops._split_power_by_connection(requested_kw, phase_connection),
                }

            storage_control_id = '__electrical_storage__'
            requested_storage_kw = ops._storage_requested_power_kw(storage_action)
            if abs(requested_storage_kw) > 1.0e-9:
                controls[storage_control_id] = {
                    'request_total_kw': requested_storage_kw,
                    'request_phase_kw': ops._split_power_by_connection(
                        requested_storage_kw,
                        getattr(building, 'electrical_storage_phase_connection', None),
                    ),
                }

            if not controls:
                return actions

            limits = getattr(building, '_electrical_service_limits', {}) or {}
            # Prediction uses prospective loads; runtime repeats this calculation
            # with its own state and remains responsible for final device limits.
            allocation = allocate_electrical_service(
                base_total_kw, base_phase_kw, controls,
                limits.get('total', {}) or {}, limits.get('per_phase', {}) or {}, phase_names,
            )
            scales = allocation.scales

            for charger_id, index in ev_action_indices.items():
                charger = getattr(building, '_charger_lookup', {}).get(charger_id)
                if charger is None:
                    continue
                control = controls.get(charger_id)
                target_kw = 0.0 if control is None else control['request_total_kw'] * scales.get(charger_id, 1.0)
                adjusted[index] = ops._charger_action_from_power_kw(charger, target_kw)

            if storage_index is not None:
                control = controls.get(storage_control_id)
                target_kw = 0.0 if control is None else control['request_total_kw'] * scales.get(storage_control_id, 1.0)
                adjusted[storage_index] = ops._storage_action_from_power_kw(target_kw)

            return [
                float(np.clip(value, low, high))
                for value, (low, high) in zip(adjusted, bounds)
            ]
        except Exception:
            return actions

    def _base_load_kw(self, building) -> float:
        t = int(building.time_step)
        step_hours = max(float(building.seconds_per_time_step), 1.0) / 3600.0
        load_kwh = building._dataset_energy_to_control_step(self._series_value(building.non_shiftable_load, t))

        try:
            temperature = self._series_value(building.weather.outdoor_dry_bulb_temperature, t)
            cooling = building._dataset_energy_to_control_step(self._series_value(building.cooling_demand, t))
            heating = building._dataset_energy_to_control_step(self._series_value(building.heating_demand, t))
            dhw = building._dataset_energy_to_control_step(self._series_value(building.dhw_demand, t))
            load_kwh += max(self._safe_scalar(building.cooling_device.get_input_power(cooling, temperature, heating=False), 0.0), 0.0)

            try:
                heating_load = building.heating_device.get_input_power(heating, temperature, heating=True)
            except TypeError:
                heating_load = building.heating_device.get_input_power(heating)
            load_kwh += max(self._safe_scalar(heating_load, 0.0), 0.0)

            try:
                dhw_load = building.dhw_device.get_input_power(dhw, temperature, heating=True)
            except TypeError:
                dhw_load = building.dhw_device.get_input_power(dhw)
            load_kwh += max(self._safe_scalar(dhw_load, 0.0), 0.0)
        except Exception:
            pass

        return max(load_kwh, 0.0) / step_hours

    def _pv_generation_kw(self, building) -> float:
        t = int(building.time_step)
        step_hours = max(float(building.seconds_per_time_step), 1.0) / 3600.0
        return max(abs(self._series_value(building.solar_generation, t)), 0.0) / step_hours

    def _charger_requested_kw(self, building, charger_id: str, action: float) -> float:
        return self._charger_requested_kw_for_charger(self._charger(building, charger_id), action)

    def _charger_requested_kw_for_charger(self, charger, action: float) -> float:
        if action <= 0.0:
            return 0.0

        if charger is None:
            return 0.0

        return max(action, 0.0) * max(self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0), 0.0)

    def _deferrable_start_power_kw(self, building, action_name: str, action: float) -> float:
        return self._deferrable_start_power_kw_for_appliance(
            building,
            self._deferrable_appliance(building, action_name),
            action,
        )

    def _deferrable_start_power_kw_for_appliance(self, building, appliance, action: float) -> float:
        if action <= 0.0:
            return 0.0

        if appliance is None:
            return 0.0

        energy_kwh = self._safe_scalar(appliance.preview_start_energy_kwh(action), 0.0)
        step_hours = max(float(building.seconds_per_time_step), 1.0) / 3600.0
        return max(energy_kwh, 0.0) / step_hours

    @staticmethod
    def _charger(building, charger_id: str):
        for charger in getattr(building, 'electric_vehicle_chargers', []) or []:
            if getattr(charger, 'charger_id', None) == charger_id:
                return charger
        return None

    @staticmethod
    def _deferrable_appliance(building, action_name: str):
        appliance_name = action_name.replace('deferrable_appliance_', '', 1)
        for appliance in getattr(building, 'deferrable_appliances', []) or []:
            if getattr(appliance, 'name', None) == appliance_name or action_name == getattr(appliance, 'name', None):
                return appliance
        return None

    @staticmethod
    def _current_soc(storage) -> Optional[float]:
        if storage is None:
            return None

        try:
            t = int(storage.time_step)
            soc_series = getattr(storage, 'soc')
            if hasattr(soc_series, '__len__') and not np.isscalar(soc_series):
                value = soc_series[min(max(t, 0), len(soc_series) - 1)]
            else:
                value = soc_series
        except Exception:
            return None

        try:
            soc = float(value)
        except (TypeError, ValueError):
            return None

        if not np.isfinite(soc):
            return None

        if abs(soc) > 1.5:
            soc /= 100.0

        return float(np.clip(soc, 0.0, 1.0))

    @staticmethod
    def _series_value(values, index: int) -> float:
        try:
            return float(values[min(max(index, 0), len(values) - 1)])
        except Exception:
            return 0.0

    @classmethod
    def _optional_observation(cls, observations: Dict[str, Any], key: str) -> Optional[float]:
        if key not in observations:
            return None

        value = cls._safe_scalar(observations.get(key), np.nan)
        return float(value) if np.isfinite(value) else None

    @staticmethod
    def _safe_scalar(value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not np.isfinite(scalar):
            return float(default)

        return scalar

    def reset(self):
        super().reset()
        self._building_action_layout_cache.clear()
        self._baseline_topology_version = None


class BusinessAsUsualAgent(_OperationalBaselineAgent):
    """Immediate EV charging to 100%, earliest appliance start and PV storage.

    The request is maximum charging power while connected, independent of the
    departure target, time, price and solar forecast. Charger/battery physics
    and the existing electrical-service limiter determine delivered power.
    """

    DEFINITION_VERSION = 'immediate-full-charge-v1'

    def __init__(
        self, env: CityLearnEnv, ev_target_soc: float = 1.0,
        ev_follow_required_soc: bool = False, ev_service_margin_rate: float = 0.02,
        ev_service_floor_rate: float = 0.0, storage_min_soc: float = 0.20,
        storage_max_soc: float = 0.90, storage_deadband_kw: float = 0.05,
        deferrable_start_action: float = 1.0, **kwargs: Any,
    ):
        # Keep CityLearn's explicit public signature and positional arguments.
        # Departure-target scheduling belongs to RBCs; BAU requests full charge.
        if (ev_target_soc is not None and float(ev_target_soc) != 1.0) or ev_follow_required_soc:
            raise ValueError('BusinessAsUsualAgent always charges to 100%; use an RBC for departure targets.')
        for name, value, default in (
            ('ev_service_margin_rate', ev_service_margin_rate, 0.02),
            ('ev_service_floor_rate', ev_service_floor_rate, 0.0),
        ):
            if value is not None and float(value) != default:
                raise ValueError(f'{name} configures deadline charging; use an RBC instead of BAU.')
        super().__init__(
            env, ev_target_soc=1.0, ev_follow_required_soc=False,
            storage_min_soc=storage_min_soc, storage_max_soc=storage_max_soc,
            storage_deadband_kw=storage_deadband_kw,
            deferrable_start_action=deferrable_start_action, **kwargs,
        )

    def _ev_action_for_charger(self, charger, low: float, high: float, *, building=None) -> float:
        ev = None if charger is None else getattr(charger, 'connected_electric_vehicle', None)
        if ev is None:
            return 0.0
        soc = self._current_soc(getattr(ev, 'battery', None))
        if soc is None or soc >= 1.0 - 1.0e-6:
            return 0.0
        if self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0) <= 0.0:
            return 0.0
        # Do not reduce this request to the small remaining energy: doing so can
        # fall into the charger's minimum-power deadband and strand the EV below
        # full charge. The battery clips the final interval to its capacity.
        return float(np.clip(1.0, max(0.0, low), max(0.0, high)))

    def _charger_requested_kw_for_charger(self, charger, action: float) -> float:
        """Estimate accepted EV power before dispatching self-consumption BESS.

        A full-power request near 100% is clipped by the EV battery. Reserving
        nominal charger power instead would discharge the house battery into
        an export. Mirror the native positive-charge limits without mutating
        battery SOC, efficiency, capacity history or provenance.
        """
        ev = None if charger is None else getattr(charger, 'connected_electric_vehicle', None)
        if ev is None or action <= 0.0:
            return 0.0
        power = max(charger.get_requested_power_kw(action), 0.0)
        if power <= 0.0:
            return 0.0
        hours = max(float(charger.seconds_per_time_step) / 3600.0, 1.0e-12)
        charger_efficiency = max(charger.get_efficiency(power / charger.max_charging_power, True), 1.0e-9)
        battery = ev.battery
        initial = battery.energy_init
        requested = power * hours * charger_efficiency
        maximum = max(battery.get_max_input_power(energy_init=initial), 0.0) * hours
        remaining = max(battery.degraded_capacity - initial, 0.0)
        accepted = min(requested, maximum)
        for _ in range(2):
            efficiency = max(battery.get_current_efficiency(accepted / hours) ** 0.5, 1.0e-9)
            accepted = min(requested, maximum, remaining / efficiency)
        return accepted / (hours * charger_efficiency)


class ZeroActionBaselineAgent(Agent):
    """Baseline that requests zero for every action dimension."""

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        actions = [np.zeros(space.shape, dtype='float32').tolist() for space in self.action_space]
        self.actions = actions
        self.next_time_step()
        return actions


class ServiceOnlyBaselineAgent(BusinessAsUsualAgent):
    """Serve EV and schedulable loads without using stationary storage."""

    def _storage_action(
        self,
        building,
        low: float,
        high: float,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> float:
        return float(np.clip(0.0, low, high))


class NormalPolicy(BusinessAsUsualAgent):
    """Day-to-day baseline with full EV charging, earliest schedulable service and PV self-consumption."""


class NormalNoBatteryPolicy(ServiceOnlyBaselineAgent):
    """Day-to-day baseline without stationary battery control."""


class RBCBasicPolicy(_OperationalBaselineAgent):
    """Basic rule-based controller with service-aware EV charging and simple price response."""

    def __init__(
        self,
        env: CityLearnEnv,
        low_price_quantile: float = 0.35,
        high_price_quantile: float = 0.75,
        price_charge_rate: float = 0.60,
        price_discharge_rate: float = 0.45,
        ev_price_charge_rate: float = 0.70,
        ev_service_floor_rate: float = 0.25,
        ev_service_margin_rate: float = 0.05,
        **kwargs: Any,
    ):
        self.low_price_quantile = float(np.clip(low_price_quantile, 0.0, 1.0))
        self.high_price_quantile = float(np.clip(high_price_quantile, 0.0, 1.0))
        self.price_charge_rate = float(np.clip(price_charge_rate, 0.0, 1.0))
        self.price_discharge_rate = float(np.clip(price_discharge_rate, 0.0, 1.0))
        self.ev_price_charge_rate = float(np.clip(ev_price_charge_rate, 0.0, 1.0))
        self._price_thresholds: Dict[int, Tuple[float, float]] = {}
        super().__init__(
            env,
            ev_follow_required_soc=True,
            ev_service_floor_rate=ev_service_floor_rate,
            ev_service_margin_rate=ev_service_margin_rate,
            **kwargs,
        )

    def _ev_action_for_charger(self, charger, low: float, high: float, *, building=None) -> float:
        service_action = super()._ev_action_for_charger(charger, low, high, building=building)

        if service_action <= 0.0 or building is None:
            return service_action

        price = self._price_value(building)
        low_price, _ = self._price_thresholds_for_building(building)

        if price <= low_price:
            return float(np.clip(max(service_action, self.ev_price_charge_rate), max(0.0, low), max(0.0, high)))

        return service_action

    def _storage_action(
        self,
        building,
        low: float,
        high: float,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> float:
        storage = getattr(building, 'electrical_storage', None)
        nominal_power_kw = self._safe_scalar(getattr(storage, 'nominal_power', 0.0), 0.0)
        capacity = self._safe_scalar(getattr(storage, 'capacity', 0.0), 0.0)

        if storage is None or nominal_power_kw <= 0.0 or capacity <= 0.0:
            return 0.0

        soc = self._current_soc(storage)
        if soc is None:
            return 0.0

        load_kw = self._base_load_kw(building) + max(prospective_ev_kw, 0.0) + max(prospective_deferrable_kw, 0.0)
        pv_kw = self._pv_generation_kw(building)
        net_kw = load_kw - pv_kw
        price = self._price_value(building)
        low_price, high_price = self._price_thresholds_for_building(building)

        if price <= low_price and soc < self.storage_max_soc:
            return float(np.clip(self.price_charge_rate, low, high))

        if price >= high_price and net_kw > self.storage_deadband_kw and soc > self.storage_min_soc:
            return float(np.clip(-self.price_discharge_rate, low, high))

        return float(np.clip(0.0, low, high))

    def _price_thresholds_for_building(self, building) -> Tuple[float, float]:
        cache_key = id(building)
        cached = self._price_thresholds.get(cache_key)
        if cached is not None:
            return cached

        values = np.asarray(getattr(getattr(building, 'pricing', None), 'electricity_pricing', []), dtype='float64')
        values = values[np.isfinite(values)]

        if values.size == 0:
            thresholds = (0.0, 0.0)
        else:
            thresholds = (
                float(np.quantile(values, self.low_price_quantile)),
                float(np.quantile(values, self.high_price_quantile)),
            )

        self._price_thresholds[cache_key] = thresholds
        return thresholds

    def _price_value(self, building) -> float:
        t = int(building.time_step)
        return self._series_value(getattr(getattr(building, 'pricing', None), 'electricity_pricing', []), t)

    def reset(self):
        super().reset()
        self._price_thresholds.clear()


class RBCSmartPolicy(RBCBasicPolicy):
    """Solar, price and peak-aware rule-based controller with conservative EV service."""

    def __init__(
        self,
        env: CityLearnEnv,
        pv_charge_rate: float = 1.0,
        storage_discharge_rate: float = 0.65,
        import_peak_threshold_kw: float = 7.0,
        price_charge_rate: float = 0.0,
        ev_service_floor_rate: float = 0.0,
        ev_service_margin_rate: float = 0.03,
        ev_urgency_hours: float = 2.0,
        **kwargs: Any,
    ):
        self.pv_charge_rate = float(np.clip(pv_charge_rate, 0.0, 1.0))
        self.storage_discharge_rate = float(np.clip(storage_discharge_rate, 0.0, 1.0))
        self.import_peak_threshold_kw = max(float(import_peak_threshold_kw), 0.0)
        self.ev_urgency_hours = max(float(ev_urgency_hours), 0.0)
        super().__init__(
            env,
            price_charge_rate=price_charge_rate,
            ev_service_floor_rate=ev_service_floor_rate,
            ev_service_margin_rate=ev_service_margin_rate,
            **kwargs,
        )

    def _ev_action_for_charger(self, charger, low: float, high: float, *, building=None) -> float:
        ev = None if charger is None else getattr(charger, 'connected_electric_vehicle', None)

        if ev is None:
            return 0.0

        service_context = self._ev_service_context_for_charger(building, charger)
        soc = service_context.get('soc')
        if soc is None:
            soc = self._current_soc(getattr(ev, 'battery', None))
        required_soc = service_context.get('required_soc')

        if soc is None or required_soc is None:
            return super()._ev_action_for_charger(charger, low, high, building=building)

        if soc >= required_soc - 0.01:
            return 0.0

        max_power = self._safe_scalar(getattr(charger, 'max_charging_power', 0.0), 0.0)
        if max_power <= 0.0:
            return 0.0

        departure_hours = max(service_context.get('departure_hours') or 1.0, 1.0e-6)
        capacity_kwh = service_context.get('capacity_kwh')
        if capacity_kwh is None:
            capacity_kwh = self._safe_scalar(getattr(getattr(ev, 'battery', None), 'capacity', 0.0), 0.0)

        required_rate = 1.0 if capacity_kwh <= 0.0 else (required_soc - soc) * capacity_kwh / (departure_hours * max_power)
        service_rate = max(required_rate + self.ev_service_margin_rate, self.ev_service_floor_rate)
        price = self._price_value(building) if building is not None else 0.0
        low_price, _ = self._price_thresholds_for_building(building) if building is not None else (0.0, 0.0)
        urgent_service = departure_hours <= self.ev_urgency_hours or required_rate >= 0.80

        if building is not None:
            surplus_kw = self._pv_generation_kw(building) - self._base_load_kw(building)
            if surplus_kw > self.storage_deadband_kw:
                service_rate = min(1.0, max(service_rate, surplus_kw / max_power))
                return float(np.clip(service_rate, max(0.0, low), max(0.0, high)))

        if building is not None and price <= low_price:
            service_rate = max(service_rate, self.ev_price_charge_rate)
            return float(np.clip(service_rate, max(0.0, low), max(0.0, high)))

        if not urgent_service:
            return 0.0

        return float(np.clip(service_rate, max(0.0, low), max(0.0, high)))

    def _storage_action(
        self,
        building,
        low: float,
        high: float,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> float:
        storage = getattr(building, 'electrical_storage', None)
        nominal_power_kw = self._safe_scalar(getattr(storage, 'nominal_power', 0.0), 0.0)
        capacity = self._safe_scalar(getattr(storage, 'capacity', 0.0), 0.0)

        if storage is None or nominal_power_kw <= 0.0 or capacity <= 0.0:
            return 0.0

        soc = self._current_soc(storage)
        if soc is None:
            return 0.0

        load_kw = self._base_load_kw(building) + max(prospective_ev_kw, 0.0) + max(prospective_deferrable_kw, 0.0)
        pv_kw = self._pv_generation_kw(building)
        net_kw = load_kw - pv_kw
        price = self._price_value(building)
        _, high_price = self._price_thresholds_for_building(building)

        if net_kw < -self.storage_deadband_kw and soc < self.storage_max_soc:
            charge_rate = min(-net_kw, nominal_power_kw) / nominal_power_kw
            return float(np.clip(min(max(charge_rate, 0.0), self.pv_charge_rate), low, high))

        if net_kw > self.storage_deadband_kw and soc > self.storage_min_soc:
            if net_kw >= self.import_peak_threshold_kw or price >= high_price:
                discharge_rate = min(net_kw, nominal_power_kw) / nominal_power_kw
                return float(np.clip(-min(max(discharge_rate, 0.0), self.storage_discharge_rate), low, high))

        return float(np.clip(0.0, low, high))


class RBCCommunityPolicy(RBCSmartPolicy):
    """Community-aware rule-based controller that uses REC surplus and import context."""

    def __init__(
        self,
        env: CityLearnEnv,
        community_surplus_charge_soc_ceiling: float = 0.65,
        community_import_threshold_kw: float = 1.0,
        community_storage_discharge_rate: float = 0.75,
        community_surplus_threshold_kw: float = 0.05,
        **kwargs: Any,
    ):
        self.community_surplus_charge_soc_ceiling = float(np.clip(community_surplus_charge_soc_ceiling, 0.0, 1.0))
        self.community_import_threshold_kw = max(float(community_import_threshold_kw), 0.0)
        self.community_storage_discharge_rate = float(np.clip(community_storage_discharge_rate, 0.0, 1.0))
        self.community_surplus_threshold_kw = max(float(community_surplus_threshold_kw), 0.0)
        super().__init__(env, **kwargs)

    def _storage_action(
        self,
        building,
        low: float,
        high: float,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> float:
        storage = getattr(building, 'electrical_storage', None)
        nominal_power_kw = self._safe_scalar(getattr(storage, 'nominal_power', 0.0), 0.0)

        if storage is None or nominal_power_kw <= 0.0:
            return 0.0

        soc = self._current_soc(storage)
        if soc is None:
            return 0.0

        local_load_kw = self._base_load_kw(building) + max(prospective_ev_kw, 0.0) + max(prospective_deferrable_kw, 0.0)
        local_net_kw = local_load_kw - self._pv_generation_kw(building)
        local_surplus_kw = max(-local_net_kw, 0.0)
        local_import_kw = max(local_net_kw, 0.0)
        community_surplus_kw, community_import_kw = self._community_net_context_kw(
            building,
            prospective_ev_kw=prospective_ev_kw,
            prospective_deferrable_kw=prospective_deferrable_kw,
        )

        if local_surplus_kw > self.storage_deadband_kw and soc < self.storage_max_soc:
            return float(np.clip(min(local_surplus_kw, nominal_power_kw) / nominal_power_kw, low, high))

        if (
            (local_import_kw > self.storage_deadband_kw or community_import_kw > self.community_import_threshold_kw)
            and soc > self.storage_min_soc
        ):
            useful_kw = max(local_import_kw, community_import_kw)
            return float(np.clip(-min(useful_kw, nominal_power_kw) / nominal_power_kw * self.community_storage_discharge_rate, low, high))

        return super()._storage_action(
            building,
            low,
            high,
            prospective_ev_kw=prospective_ev_kw,
            prospective_deferrable_kw=prospective_deferrable_kw,
        )

    def _community_net_context_kw(
        self,
        target_building,
        *,
        prospective_ev_kw: float,
        prospective_deferrable_kw: float,
    ) -> Tuple[float, float]:
        total_net_kw = 0.0

        for building in self.env.unwrapped.buildings:
            extra_ev_kw = prospective_ev_kw if building is target_building else 0.0
            extra_deferrable_kw = prospective_deferrable_kw if building is target_building else 0.0
            total_net_kw += (
                self._base_load_kw(building)
                + max(extra_ev_kw, 0.0)
                + max(extra_deferrable_kw, 0.0)
                - self._pv_generation_kw(building)
            )

        return max(-total_net_kw, 0.0), max(total_net_kw, 0.0)


class GridAwareBaselineAgent(RBCSmartPolicy):
    """Backward-compatible alias for the CityLearn v3 smart RBC baseline."""


class CommunityAwareBaselineAgent(RBCCommunityPolicy):
    """Backward-compatible alias for the CityLearn v3 community RBC baseline."""


__all__ = [
    'BusinessAsUsualAgent',
    'ZeroActionBaselineAgent',
    'ServiceOnlyBaselineAgent',
    'NormalPolicy',
    'NormalNoBatteryPolicy',
    'RBCBasicPolicy',
    'RBCSmartPolicy',
    'RBCCommunityPolicy',
    'GridAwareBaselineAgent',
    'CommunityAwareBaselineAgent',
]
