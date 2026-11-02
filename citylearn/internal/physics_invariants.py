from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import numpy as np

from citylearn.internal.units import power_kw_to_energy_kwh

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


class CityLearnPhysicsInvariantService:
    """Runtime physics/assertion checks evaluated per control step."""

    SOC_EPS = 1.0e-4
    ENERGY_EPS = 5.0e-4

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._battery_energy_before_actions = None

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
            snapshot.append((name, battery, energy, battery.stored_energy_transfer))
        self._battery_energy_before_actions = (int(time_step), snapshot)

    def _assert_battery_energy_changes(self, time_step: int):
        snapshot = self._battery_energy_before_actions
        self._battery_energy_before_actions = None
        if snapshot is None or snapshot[0] != time_step:
            return
        for name, battery, energy_before, transfer_before in snapshot[1]:
            energy_after = float(battery.soc[time_step]) * float(battery.capacity)
            expected_change = battery.stored_energy_transfer - transfer_before
            assert abs(energy_after - energy_before - expected_change) <= self.ENERGY_EPS, (
                f"Stored battery energy mismatch for '{name}' at t={time_step}: "
                f"before={energy_before:.6f} kWh, after={energy_after:.6f} kWh, "
                f"expected_change={expected_change:.6f} kWh."
            )

    @staticmethod
    def _to_scalar(value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not np.isfinite(scalar):
            return float(default)

        return scalar

    @classmethod
    def _safe_index(cls, values, idx: int, default: float = 0.0) -> float:
        try:
            return cls._to_scalar(values[idx], default)
        except Exception:
            return float(default)

    def assert_step_invariants(self, time_step: int):
        """Raise ``AssertionError`` if hard physics invariants are violated."""

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

        for building in buildings:
            self._assert_building_energy_balance(building, t)
            self._assert_outage_local_balance(building, t)
            self._assert_soc_bounds(building, t)
            self._assert_storage_power_bounds(building, t)
            self._assert_charger_power_bounds(building, t)
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

        assert abs(net - terms) <= self.ENERGY_EPS, (
            f"Net energy balance mismatch for '{building.name}' at t={t}: "
            f"net={net:.6f} kWh, terms={terms:.6f} kWh."
        )

    def _assert_outage_local_balance(self, building, t: int):
        outage_signal = self._safe_index(getattr(building, "power_outage_signal", []), t, 0.0)
        if not bool(getattr(building, "simulate_power_outage", False)) or outage_signal < 1.0:
            return

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

        assert local_loads <= local_sources + self.ENERGY_EPS, (
            f"Outage local energy balance violated for '{building.name}' at t={t}: "
            f"loads={local_loads:.6f} kWh, local_sources={local_sources:.6f} kWh."
        )

    def _assert_soc_bounds(self, building, t: int):
        storages = [
            ("cooling_storage", getattr(building, "cooling_storage", None)),
            ("heating_storage", getattr(building, "heating_storage", None)),
            ("dhw_storage", getattr(building, "dhw_storage", None)),
            ("electrical_storage", getattr(building, "electrical_storage", None)),
        ]

        for name, storage in storages:
            if storage is None:
                continue

            soc = self._safe_index(getattr(storage, "soc", []), t, 0.0)
            assert -self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS, (
                f"{name} SOC out of bounds for '{building.name}' at t={t}: soc={soc:.6f}."
            )

        for charger in building.electric_vehicle_chargers or []:
            for ev in self._iter_charger_evs(charger):
                soc = self._safe_index(ev.battery.soc, t, 0.0)
                assert -self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS, (
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
        assert abs(energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
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

            assert abs(applied_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
                f"Charger power bound exceeded at '{building.name}:{charger.charger_id}' t={t}: "
                f"applied={applied_energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
            )
            assert abs(commanded_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
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
