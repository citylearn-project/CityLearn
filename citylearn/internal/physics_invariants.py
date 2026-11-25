from __future__ import annotations

import math
from typing import TYPE_CHECKING, Iterable

from citylearn.energy_model import ElectricHeater, HeatPump
from citylearn.internal.physics_version import physics_version_of
from citylearn.internal.units import power_kw_to_energy_kwh

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


class PhysicsInvariantError(AssertionError):
    """A hard physics invariant was violated.

    Subclasses ``AssertionError`` so existing handlers keep working, but is raised
    explicitly, so ``python -O`` does not disable the checks.
    """


class CityLearnPhysicsInvariantService:
    """Runtime physics/assertion checks evaluated per control step.

    The net balance rebuilds net consumption from the device series that produced it, so it cannot see a
    wrong device series. The device identities compare each series with the model's own inputs and states
    instead: thermal electricity with the heat output and the COP or efficiency, served energy with the
    demand, and battery energy changes with the terminal energy, the efficiency and the discharge reserve.
    """

    # Thermal end uses: (name, heating, device, storage, device output, demand, and the names in non-finite errors).
    THERMAL_SERVICES = tuple(
        (name, heating, f'{name}_device', f'{name}_storage', f'energy_from_{name}_device', f'{name}_demand',
         f'{name} device output', f'{name} storage balance', f'{name} demand')
        for name, heating in (('cooling', False), ('heating', True), ('dhw', True))
    )

    SOC_EPS = 1.0e-4
    ENERGY_EPS = 5.0e-4
    # Device series are stored in float32, whose relative rounding is about 6e-8.
    RELATIVE_EPS = 1.0e-5

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._battery_energy_before_actions = None
        # Thermal services of each building, kept only while assert_step_invariants runs: two checks read them.
        self._step_services = None

    def capture_battery_energy_before_actions(self, time_step: int):
        """Snapshot actual SOC after arrivals/losses and before control actions.

        Do not read ``energy_init``: the independent check must detect a model
        that silently replaces measured energy with its operational reserve.
        """
        batteries = [
            (f'{building.name}.electrical_storage', building.electrical_storage)
            for building in self.env.buildings
        ]
        batteries.extend((f'{ev.name}.battery', ev.battery)
                         for ev in self.env.electric_vehicles)
        seen = set()
        snapshot = []
        for name, battery in batteries:
            if battery is None or id(battery) in seen:
                continue
            seen.add(id(battery))
            energy = float(battery.soc[time_step]) * float(battery.capacity)
            terminal = self._battery_terminal_energy(battery, time_step)
            snapshot.append((name, battery, energy, battery.stored_energy_transfer, terminal))
        self._battery_energy_before_actions = (int(time_step), snapshot)

    def _assert_battery_energy_changes(self, time_step: int):
        snapshot = self._battery_energy_before_actions
        self._battery_energy_before_actions = None
        if snapshot is None or snapshot[0] != time_step:
            return
        for name, battery, energy_before, transfer_before, terminal_before in snapshot[1]:
            energy_after = float(battery.soc[time_step]) * float(battery.capacity)
            expected_change = battery.stored_energy_transfer - transfer_before
            if not (abs(energy_after - energy_before - expected_change) <= self.ENERGY_EPS):
                raise PhysicsInvariantError(
                    f"Stored battery energy mismatch for '{name}' at t={time_step}: "
                    f"before={energy_before:.6f} kWh, after={energy_after:.6f} kWh, "
                    f"expected_change={expected_change:.6f} kWh."
                )
            # The transfer journal above cannot see a wrong terminal energy, which is what the building nets.
            # The terminal energy must be the sum of the step's charge and discharge operations, and the stored
            # energy must follow each operation at its own efficiency (one history entry per operation).
            terminal = self._battery_terminal_energy(battery, time_step) - terminal_before
            operations = [float(event['terminal']) for event in getattr(battery, 'energy_provenance_events', None) or []
                          if event.get('kind') == 'transfer']
            operated = sum(operations)
            if not (abs(terminal - operated) <= self._energy_tolerance(terminal, operated)):
                raise PhysicsInvariantError(
                    f"Battery terminal energy does not match its charge and discharge operations for '{name}' "
                    f"at t={time_step}: terminal={terminal:.6f} kWh, operations={operated:.6f} kWh."
                )
            # Only the last entries are read: copying the whole history made each step cost grow with the episode.
            history = getattr(battery, 'efficiency_history', None)
            history = () if history is None else history
            efficiencies = (list(history[-len(operations):]) if operations and len(history) >= len(operations)
                            else [battery.efficiency]*len(operations))
            expected = 0.0
            for energy, efficiency in zip(operations, efficiencies):
                one_way = max(float(efficiency), 1.0e-12)**0.5
                expected += energy*one_way if energy >= 0.0 else energy/one_way
            change = energy_after - energy_before
            if not (abs(change - expected) <= self._energy_tolerance(change, expected)):
                raise PhysicsInvariantError(
                    f"Battery energy change does not match its terminal energy for '{name}' at t={time_step}: "
                    f"stored change={change:.6f} kWh, terminal={terminal:.6f} kWh, expected stored change={expected:.6f} kWh."
                )
            depth_of_discharge = getattr(battery, 'depth_of_discharge', None)
            if any(energy < 0.0 for energy in operations) and depth_of_discharge is not None:
                # A discharge stops at the reserve, or at the stored energy if standby losses already took it lower.
                reserve = min(max(1.0 - float(depth_of_discharge), 0.0)*float(battery.capacity), energy_before)
                if not (energy_after >= reserve - self.ENERGY_EPS):
                    raise PhysicsInvariantError(
                        f"Battery discharged below its depth-of-discharge reserve for '{name}' at t={time_step}: "
                        f"stored={energy_after:.6f} kWh, reserve={reserve:.6f} kWh."
                    )

    def _battery_terminal_energy(self, battery, time_step: int) -> float:
        """Net energy at the battery terminals at ``time_step``, in control-step kWh (charge positive)."""

        return self._state(battery.electricity_consumption, time_step, 'battery electricity')

    # The checks test their condition inline and format the message only for a violation: formatting it at
    # every step cost more than the checks themselves.
    @staticmethod
    def _require(condition: bool, message: str):
        if not condition:
            raise PhysicsInvariantError(message)

    @staticmethod
    def _state(values, idx: int, name: str, default: float = 0.0) -> float:
        """Read a simulated state value; a NaN or inf value is a violation, not zero."""

        try:
            value = values[idx]
        except (IndexError, KeyError, TypeError):
            return float(default)

        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not math.isfinite(scalar):
            raise PhysicsInvariantError(f'Non-finite {name}: {scalar!r}.')

        return scalar

    @staticmethod
    def _to_scalar(value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not math.isfinite(scalar):
            return float(default)

        return scalar

    @staticmethod
    def _safe_index(values, idx: int, default: float = 0.0) -> float:
        """Read a state value at ``idx``; missing values default, non-finite values are violations.

        The same as ``_state(values, idx, 'value', default)``, written out because it runs about ten times
        per building and step.
        """

        try:
            value = values[idx]
        except (IndexError, KeyError, TypeError):
            return float(default)

        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not math.isfinite(scalar):
            raise PhysicsInvariantError(f'Non-finite value: {scalar!r}.')

        return scalar

    def assert_step_invariants(self, time_step: int):
        """Raise ``PhysicsInvariantError`` (an ``AssertionError``) if hard physics invariants are violated."""

        t = int(max(time_step, 0))
        buildings = list(self.env.buildings)
        topology = getattr(self.env, "_topology_service", None)
        if (
            getattr(self.env, "topology_mode", "static") == "dynamic"
            and topology is not None
            and hasattr(topology, "active_member_ids_at")
        ):
            active_member_ids = set(topology.active_member_ids_at(t))
            buildings = [
                building
                for building in buildings
                if str(getattr(building, "name", "")) in active_member_ids
            ]

        checks = (
            self._assert_building_energy_balance,
            self._assert_thermal_device_conversion,
            self._assert_served_energy_within_demand,
            self._assert_outage_local_balance,
            self._assert_soc_bounds,
            self._assert_storage_power_bounds,
            self._assert_charger_power_bounds,
        )
        # The thermal services are read once per building and step and shared by the checks that use them.
        self._step_services = {}
        try:
            for building in buildings:
                for check in checks:
                    try:
                        check(building, t)
                    except PhysicsInvariantError as error:
                        if str(error).startswith('Non-finite'):
                            raise PhysicsInvariantError(
                                f"{error} Found by {check.__name__.lstrip('_')} for '{building.name}' at t={t}."
                            ) from None
                        raise
        finally:
            self._step_services = None
        self._assert_battery_energy_changes(t)

    def _assert_building_energy_balance(self, building, t: int):
        if bool(getattr(building, "power_outage", False)):
            return

        net = self._safe_index(building.net_electricity_consumption, t, 0.0)
        terms = (
            self._safe_index(building.cooling_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.heating_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.dhw_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.non_shiftable_load_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.electrical_storage.electricity_consumption, t, 0.0)
            + self._safe_index(building.solar_generation, t, 0.0)
            + self._safe_index(building.chargers_electricity_consumption, t, 0.0)
            + self._safe_index(building.deferrable_appliances_electricity_consumption, t, 0.0)
            + self._safe_index(getattr(building, 'escalators_electricity_consumption', []), t, 0.0)
        )

        if not (abs(net - terms) <= self.ENERGY_EPS):
            raise PhysicsInvariantError(
                f"Net energy balance mismatch for '{building.name}' at t={t}: "
                f"net={net:.6f} kWh, terms={terms:.6f} kWh."
            )

    def _energy_tolerance(self, *values: float) -> float:
        return self.ENERGY_EPS + self.RELATIVE_EPS*max([*map(abs, values), 0.0])

    @staticmethod
    def _step_ratio(owner) -> float:
        ratio = getattr(owner, 'time_step_ratio', None)
        return 1.0 if ratio in (None, 0) else float(ratio)

    def _thermal_services(self, building, t: int):
        """Thermal end uses at step ``t`` as (name, device, heating, output kWh, demand kWh, served kWh).

        Output is the device's heat to the building plus its storage charge, in control-step kWh; demand and
        served heat (device plus storage discharge) are in dataset-resolution kWh, the unit of the demand series.
        """

        # getattr: a service unpickled from an earlier release has no cache attribute.
        cache = getattr(self, '_step_services', None)
        if cache is not None:
            key = (id(building), t)
            services = cache.get(key)
            if services is None:
                services = cache[key] = self._read_thermal_services(building, t)
            return services
        return self._read_thermal_services(building, t)

    def _read_thermal_services(self, building, t: int):
        ratio = self._step_ratio(building)
        services = []
        state = self._state
        for (name, heating, device_attribute, storage_attribute, output_attribute, demand_attribute,
             output_label, balance_label, demand_label) in self.THERMAL_SERVICES:
            device = getattr(building, device_attribute, None)
            if device is None:
                continue
            storage = getattr(building, storage_attribute, None)
            from_device = state(getattr(building, output_attribute), t, output_label)
            balance = state(getattr(storage, 'energy_balance', []), t, balance_label)
            demand = state(getattr(building, demand_attribute), t, demand_label)
            output = from_device*ratio + max(balance, 0.0)
            served = from_device + max(-balance, 0.0)/ratio
            services.append((name, device, heating, output, demand, served))
        return services

    def _assert_thermal_device_conversion(self, building, t: int):
        """Electricity of each heat pump and electric heater times its COP or efficiency equals its heat output."""

        temperature = self._state(building.weather.outdoor_dry_bulb_temperature, t, 'outdoor dry bulb temperature')
        # A device that serves several end uses (a heat pump for heating and DHW, say) draws their sum.
        devices = {}
        for name, device, heating, output, _, _ in self._thermal_services(building, t):
            if isinstance(device, HeatPump):
                factor = float(device.get_cop(temperature, heating))
            elif isinstance(device, ElectricHeater):
                factor = float(device.efficiency)
            else:
                continue
            names, expected, _ = devices.get(id(device), ((), 0.0, device))
            devices[id(device)] = (names + (name,), expected + output/max(factor, 1.0e-12), device)

        # During an outage, the loads clipped to the islanded supply at the first step keep their heat output,
        # so electricity may only fall short of the heat output there.
        outage = bool(getattr(building, 'power_outage', False))
        for names, expected, device in devices.values():
            label = '/'.join(names)
            electricity = self._state(device.electricity_consumption, t, f'{label} device electricity')
            tolerance = self._energy_tolerance(electricity, expected)
            consistent = (electricity <= expected + tolerance if outage
                          else abs(electricity - expected) <= tolerance)
            if not consistent:
                raise PhysicsInvariantError(
                    f"Thermal device conversion mismatch for '{building.name}' ({label}) at t={t}: "
                    f"electricity={electricity:.6f} kWh, heat output/COP={expected:.6f} kWh."
                )

    def _assert_served_energy_within_demand(self, building, t: int):
        """Served cooling, heating, DHW and non-shiftable load never exceed their demand."""

        for name, _, _, _, demand, served in self._thermal_services(building, t):
            if not (served <= demand + self._energy_tolerance(served, demand)):
                raise PhysicsInvariantError(
                    f"Served {name} energy exceeds demand for '{building.name}' at t={t}: "
                    f"served={served:.6f} kWh, demand={demand:.6f} kWh."
                )

        device = getattr(building, 'non_shiftable_load_device', None)
        if device is None:
            return
        served = self._state(device.electricity_consumption, t, 'non-shiftable load electricity')
        demand = self._state(building.non_shiftable_load, t, 'non-shiftable load')*self._step_ratio(building)
        if not (served <= demand + self._energy_tolerance(served, demand)):
            raise PhysicsInvariantError(
                f"Served non-shiftable load exceeds demand for '{building.name}' at t={t}: "
                f"served={served:.6f} kWh, demand={demand:.6f} kWh."
            )

    def _assert_outage_local_balance(self, building, t: int):
        outage_signal = self._safe_index(getattr(building, "power_outage_signal", []), t, 0.0)
        if not bool(getattr(building, "simulate_power_outage", False)) or outage_signal == 0.0:
            return

        net = self._safe_index(building.net_electricity_consumption, t, 0.0)
        if not (abs(net) <= self.ENERGY_EPS):
            raise PhysicsInvariantError(
                f"Non-zero grid exchange during outage for '{building.name}' at t={t}: "
                f"net={net:.6f} kWh, expected=0 kWh."
            )

        solar_generation = self._safe_index(building.solar_generation, t, 0.0)
        storage_energy = self._safe_index(building.electrical_storage.electricity_consumption, t, 0.0)
        charger_energy = self._safe_index(building.chargers_electricity_consumption, t, 0.0)

        local_sources = (
            max(-solar_generation, 0.0)
            + max(-storage_energy, 0.0)
            + max(-charger_energy, 0.0)
        )
        local_loads = (
            self._safe_index(building.cooling_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.heating_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.dhw_device.electricity_consumption, t, 0.0)
            + self._safe_index(building.non_shiftable_load_device.electricity_consumption, t, 0.0)
            + max(storage_energy, 0.0)
            + max(charger_energy, 0.0)
            + self._safe_index(building.deferrable_appliances_electricity_consumption, t, 0.0)
            + self._safe_index(getattr(building, 'escalators_electricity_consumption', []), t, 0.0)
        )

        if not (local_loads <= local_sources + self.ENERGY_EPS):
            raise PhysicsInvariantError(
                f"Outage local energy balance violated for '{building.name}' at t={t}: "
                f"loads={local_loads:.6f} kWh, local_sources={local_sources:.6f} kWh."
            )

        if physics_version_of(building) >= 2:
            # Storage discharges only into the islanded load that PV leaves (#229); physics version 1
            # can discharge more and books the surplus as PV curtailment.
            storage_discharge = max(-storage_energy, 0.0) + max(-charger_energy, 0.0)
            uncovered_load = max(local_loads - max(-solar_generation, 0.0), 0.0)
            if not (storage_discharge <= uncovered_load + self.ENERGY_EPS):
                raise PhysicsInvariantError(
                    f"Outage storage discharge exceeds the load not covered by PV for '{building.name}' at t={t}: "
                    f"discharge={storage_discharge:.6f} kWh, uncovered_load={uncovered_load:.6f} kWh."
                )

    def _assert_soc_bounds(self, building, t: int):
        for name in ("cooling_storage", "heating_storage", "dhw_storage", "electrical_storage"):
            storage = getattr(building, name, None)
            if storage is None:
                continue

            soc = self._safe_index(getattr(storage, "soc", []), t, 0.0)
            if not (-self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS):
                raise PhysicsInvariantError(
                    f"{name} SOC out of bounds for '{building.name}' at t={t}: soc={soc:.6f}."
                )

        for charger in building.electric_vehicle_chargers or []:
            for ev in self._iter_charger_evs(charger):
                soc = self._safe_index(ev.battery.soc, t, 0.0)
                if not (-self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS):
                    raise PhysicsInvariantError(
                        f"EV SOC out of bounds for '{ev.name}' at t={t}: soc={soc:.6f}."
                    )

    def _assert_storage_power_bounds(self, building, t: int):
        step_seconds = max(self._to_scalar(building.seconds_per_time_step, 1.0), 1.0)
        battery = getattr(building, "electrical_storage", None)
        if battery is None:
            return

        nominal_power_kw = self._to_scalar(getattr(battery, "nominal_power", 0.0), 0.0)
        if nominal_power_kw <= 0.0:
            return

        energy_kwh = self._safe_index(building.electrical_storage_electricity_consumption, t, 0.0)
        max_abs_energy_kwh = power_kw_to_energy_kwh(nominal_power_kw, step_seconds)
        if not (abs(energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS):
            raise PhysicsInvariantError(
                f"Battery power bound exceeded for '{building.name}' at t={t}: "
                f"energy={energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
            )

    def _assert_charger_power_bounds(self, building, t: int):
        step_seconds = max(self._to_scalar(building.seconds_per_time_step, 1.0), 1.0)

        for charger in building.electric_vehicle_chargers or []:
            max_ch_kw = self._to_scalar(getattr(charger, "max_charging_power", 0.0), 0.0)
            max_dis_kw = self._to_scalar(getattr(charger, "max_discharging_power", 0.0), 0.0)
            max_power_kw = max(max_ch_kw, max_dis_kw)
            if max_power_kw <= 0.0:
                continue

            applied_energy_kwh = self._safe_index(charger.electricity_consumption, t, 0.0)
            commanded_energy_kwh = self._safe_index(charger.past_charging_action_values_kwh, t, 0.0)
            max_abs_energy_kwh = power_kw_to_energy_kwh(max_power_kw, step_seconds)

            if not (abs(applied_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS):
                raise PhysicsInvariantError(
                    f"Charger power bound exceeded at '{building.name}:{charger.charger_id}' t={t}: "
                    f"applied={applied_energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
                )
            if not (abs(commanded_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS):
                raise PhysicsInvariantError(
                    f"Charger command bound exceeded at '{building.name}:{charger.charger_id}' t={t}: "
                    f"commanded={commanded_energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
                )

    @staticmethod
    def _iter_charger_evs(charger) -> Iterable:
        yielded = set()
        for ev in (
            getattr(charger, "connected_electric_vehicle", None),
            getattr(charger, "incoming_electric_vehicle", None),
        ):
            if ev is None:
                continue
            ev_id = getattr(ev, "name", id(ev))
            if ev_id in yielded:
                continue
            yielded.add(ev_id)
            yield ev
