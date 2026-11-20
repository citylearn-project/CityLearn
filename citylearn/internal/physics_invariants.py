from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

import numpy as np

from citylearn.energy_model import ElectricDevice, ElectricHeater, HeatPump
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
    """Runtime physics/assertion checks evaluated per control step."""

    SOC_EPS = 1.0e-4
    ENERGY_EPS = 5.0e-4
    INDEPENDENT_ENERGY_EPS = 3.0e-5
    FLOAT32_REL_EPS = 1.0e-6

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._battery_energy_before_actions = None
        self._battery_pre_transfer_soc: dict[tuple[int, int], float] = {}

    def capture_battery_energy_before_actions(self, time_step: int):
        """Snapshot actual SOC after arrivals/losses and before control actions.

        Do not read ``energy_init``: the independent check must detect a model
        that silently replaces measured energy with its operational reserve.
        """
        step = int(time_step)
        if step == 0:
            self._battery_pre_transfer_soc.clear()

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
            soc_before = float(battery.soc[step])
            if np.isfinite(soc_before):
                self._battery_pre_transfer_soc[(id(battery), step)] = soc_before
            energy = soc_before * float(battery.capacity)
            snapshot.append((name, battery, energy, battery.stored_energy_transfer))
        self._battery_energy_before_actions = (step, snapshot)

    def _assert_battery_energy_changes(self, time_step: int):
        snapshot = self._battery_energy_before_actions
        self._battery_energy_before_actions = None
        if snapshot is None or snapshot[0] != time_step:
            return
        for name, battery, energy_before, transfer_before in snapshot[1]:
            energy_after = float(battery.soc[time_step]) * float(battery.capacity)
            expected_change = battery.stored_energy_transfer - transfer_before
            self._require(abs(energy_after - energy_before - expected_change) <= self.ENERGY_EPS, (
                f"Stored battery energy mismatch for '{name}' at t={time_step}: "
                f"before={energy_before:.6f} kWh, after={energy_after:.6f} kWh, "
                f"expected_change={expected_change:.6f} kWh."
            ))

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

        if not np.isfinite(scalar):
            raise PhysicsInvariantError(f'Non-finite {name}: {scalar!r}.')

        return scalar

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
        """Read a state value at ``idx``; missing values default, non-finite values are violations."""

        return cls._state(values, idx, 'value', default)

    @classmethod
    def _independent_energy_tol(cls, *values: float) -> float:
        """Energy tolerance (3e-5 kWh base plus float32 relative ULP margin for large loads)."""

        scale = max((abs(float(v)) for v in values if np.isfinite(v)), default=0.0)
        return cls.INDEPENDENT_ENERGY_EPS + cls.FLOAT32_REL_EPS * scale

    @classmethod
    def _time_step_ratio(cls, owner) -> float:
        raw_ratio = getattr(owner, "time_step_ratio", None)
        if raw_ratio in (None, 0):
            return 1.0
        ratio = cls._to_scalar(raw_ratio, 1.0)
        return 1.0 if ratio <= 0.0 else ratio

    @classmethod
    def _series_at(cls, owner, attr: str, idx: int, default: float = 0.0) -> float:
        values = getattr(owner, attr, None)
        if values is not None:
            try:
                if idx >= len(values):
                    private_values = getattr(owner, f"_Building__{attr}", None)
                    if private_values is not None:
                        values = private_values
            except TypeError:
                pass
        else:
            values = getattr(owner, f"_Building__{attr}", None)

        if values is None:
            return float(default)

        return cls._state(values, idx, attr, default)

    @classmethod
    def _device_electricity_at(cls, device, idx: int, name: str, default: float = 0.0) -> float:
        if device is None:
            return float(default)
        if isinstance(device, ElectricDevice):
            raw = getattr(device, "_ElectricDevice__electricity_consumption", None)
            if raw is not None:
                return cls._state(raw, idx, name, default) * device._electricity_consumption_ratio()
        return cls._state(getattr(device, "electricity_consumption", []), idx, name, default)

    def _is_outage_step(self, building, t: int) -> bool:
        if not bool(getattr(building, "simulate_power_outage", False)):
            return False
        outage_signal = self._series_at(building, "power_outage_signal", t, 0.0)
        return outage_signal > 0.0

    def _is_pre_step_reset(self, t: int) -> bool:
        if t != 0:
            return False
        provenance = getattr(self.env, "_provenance_service", None)
        return provenance is not None and int(getattr(provenance, "last_step", 0)) < 0

    def _is_pre_step_reset_outage(self, building, t: int) -> bool:
        return self._is_pre_step_reset(t) and self._is_outage_step(building, t)

    def assert_step_invariants(self, time_step: int):
        """Raise ``PhysicsInvariantError`` (an ``AssertionError``) if hard physics invariants are violated."""

        t = int(max(time_step, 0))
        if self._is_pre_step_reset(t):
            self._battery_pre_transfer_soc.clear()

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
            for check in (
                self._assert_building_energy_balance,
                self._assert_thermal_device_energy_conversion,
                self._assert_served_energy_bounds,
                self._assert_outage_local_balance,
                self._assert_soc_bounds,
                self._assert_battery_dod_floor,
                self._assert_storage_power_bounds,
                self._assert_charger_power_bounds,
            ):
                try:
                    check(building, t)
                except PhysicsInvariantError as error:
                    if str(error).startswith('Non-finite'):
                        raise PhysicsInvariantError(
                            f"{error} Found by {check.__name__.lstrip('_')} for '{building.name}' at t={t}."
                        ) from None
                    raise
        self._assert_battery_energy_changes(t)

    def _assert_building_energy_balance(self, building, t: int):
        if self._is_outage_step(building, t):
            if getattr(building, "net_electricity_consumption", None) is None:
                return
            net = self._series_at(building, "net_electricity_consumption", t, 0.0)
            tol = self._independent_energy_tol(net)
            self._require(abs(net) <= tol, (
                f"[outage_grid_exchange] Non-zero grid electricity exchange during outage for '{building.name}' at t={t}: "
                f"expected=0.000000 kWh, actual={net:.6f} kWh, residual={net:.6f} kWh."
            ))
            return

        net = self._series_at(building, "net_electricity_consumption", t, 0.0)
        terms = (
            self._device_electricity_at(getattr(building, "cooling_device", None), t, "cooling_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "heating_device", None), t, "heating_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "dhw_device", None), t, "dhw_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "non_shiftable_load_device", None), t, "non_shiftable_load_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "electrical_storage", None), t, "electrical_storage.electricity_consumption", 0.0)
            + self._series_at(building, "solar_generation", t, 0.0)
            + self._series_at(building, "chargers_electricity_consumption", t, 0.0)
            + self._series_at(building, "deferrable_appliances_electricity_consumption", t, 0.0)
            + self._series_at(building, "escalators_electricity_consumption", t, 0.0)
        )

        self._require(abs(net - terms) <= self.ENERGY_EPS, (
            f"Net energy balance mismatch for '{building.name}' at t={t}: "
            f"net={net:.6f} kWh, terms={terms:.6f} kWh."
        ))

    def _assert_thermal_device_energy_conversion(self, building, t: int):
        ratio = self._time_step_ratio(building)
        weather = getattr(building, "weather", None)
        pre_step_outage = self._is_pre_step_reset_outage(building, t)

        for end_use, heating in (("cooling", False), ("heating", True), ("dhw", True)):
            device = getattr(building, f"{end_use}_device", None)
            if device is None or not isinstance(device, (HeatPump, ElectricHeater)):
                continue

            electricity_kwh = self._device_electricity_at(
                device, t, f"{end_use}_device.electricity_consumption", 0.0
            )
            tol_elec = self._independent_energy_tol(electricity_kwh)
            self._require(electricity_kwh >= -tol_elec, (
                f"[thermal_device_energy_conversion] Negative electricity consumption for "
                f"'{building.name}.{end_use}_device' at t={t}: "
                f"expected_min=0.000000 kWh, actual={electricity_kwh:.6f} kWh, residual={electricity_kwh:.6f} kWh."
            ))

            if isinstance(device, HeatPump):
                outdoor_temp = self._state(
                    getattr(weather, "outdoor_dry_bulb_temperature", []),
                    t,
                    "outdoor_dry_bulb_temperature",
                    0.0,
                )
                cop = self._state([device.get_cop(outdoor_temp, heating=heating)], 0, f"{end_use}_device.cop", np.nan)
            else:
                cop = self._state([getattr(device, "efficiency", np.nan)], 0, f"{end_use}_device.efficiency", np.nan)

            self._require(cop > 0.0, (
                f"[thermal_device_energy_conversion] Non-positive COP/efficiency for "
                f"'{building.name}.{end_use}_device' at t={t}: "
                f"expected_min=0.000000, actual={cop:.6f}, residual={cop:.6f}."
            ))

            device_to_load_kwh = self._series_at(building, f"energy_from_{end_use}_device", t, 0.0) * ratio
            storage = getattr(building, f"{end_use}_storage", None)
            storage_balance_kwh = (
                self._state(getattr(storage, "energy_balance", []), t, f"{end_use}_storage.energy_balance", 0.0)
                if storage is not None
                else 0.0
            )
            storage_charge_kwh = max(storage_balance_kwh, 0.0)

            expected_thermal_kwh = device_to_load_kwh + storage_charge_kwh
            actual_thermal_kwh = electricity_kwh * cop
            residual = actual_thermal_kwh - expected_thermal_kwh
            tol = self._independent_energy_tol(expected_thermal_kwh, actual_thermal_kwh)

            if pre_step_outage:
                self._require(-tol <= actual_thermal_kwh <= expected_thermal_kwh + tol, (
                    f"[thermal_device_energy_conversion] Pre-step outage thermal conversion out of bounds for "
                    f"'{building.name}.{end_use}_device' at t={t}: "
                    f"expected_max={expected_thermal_kwh:.6f} kWh, actual={actual_thermal_kwh:.6f} kWh, "
                    f"residual={residual:.6f} kWh."
                ))
            else:
                self._require(abs(residual) <= tol, (
                    f"[thermal_device_energy_conversion] Thermal energy conversion mismatch for "
                    f"'{building.name}.{end_use}_device' at t={t}: "
                    f"expected={expected_thermal_kwh:.6f} kWh "
                    f"(to_load={device_to_load_kwh:.6f} kWh + storage_charge={storage_charge_kwh:.6f} kWh), "
                    f"actual={actual_thermal_kwh:.6f} kWh "
                    f"(electricity={electricity_kwh:.6f} kWh * cop={cop:.6f}), "
                    f"residual={residual:.6f} kWh."
                ))

    def _assert_served_energy_bounds(self, building, t: int):
        ratio = self._time_step_ratio(building)
        pre_step_outage = self._is_pre_step_reset_outage(building, t)

        for end_use in ("cooling", "heating", "dhw"):
            has_demand = getattr(building, f"{end_use}_demand", None) is not None
            has_device_served = getattr(building, f"energy_from_{end_use}_device", None) is not None
            if not has_demand and not has_device_served:
                continue

            demand_kwh = self._series_at(building, f"{end_use}_demand", t, 0.0) * ratio
            device_served_kwh = self._series_at(building, f"energy_from_{end_use}_device", t, 0.0) * ratio
            storage = getattr(building, f"{end_use}_storage", None)
            storage_balance_kwh = (
                self._state(getattr(storage, "energy_balance", []), t, f"{end_use}_storage.energy_balance", 0.0)
                if storage is not None
                else 0.0
            )
            storage_discharge_kwh = max(-storage_balance_kwh, 0.0)
            served_kwh = device_served_kwh + storage_discharge_kwh
            tol = self._independent_energy_tol(demand_kwh, served_kwh, device_served_kwh)

            self._require(device_served_kwh >= -tol, (
                f"[served_energy_bounds] Negative {end_use} device delivery for '{building.name}' at t={t}: "
                f"expected_min=0.000000 kWh, actual={device_served_kwh:.6f} kWh, residual={device_served_kwh:.6f} kWh."
            ))
            self._require(served_kwh >= -tol, (
                f"[served_energy_bounds] Negative served {end_use} energy for '{building.name}' at t={t}: "
                f"expected_min=0.000000 kWh, actual={served_kwh:.6f} kWh, residual={served_kwh:.6f} kWh."
            ))
            if has_demand:
                residual = served_kwh - demand_kwh
                self._require(residual <= tol, (
                    f"[served_energy_bounds] Served {end_use} energy exceeds demand for '{building.name}' at t={t}: "
                    f"expected_max={demand_kwh:.6f} kWh, actual={served_kwh:.6f} kWh, residual={residual:.6f} kWh."
                ))

        has_ns_demand = getattr(building, "non_shiftable_load", None) is not None
        has_ns_served = getattr(building, "energy_to_non_shiftable_load", None) is not None
        ns_device = getattr(building, "non_shiftable_load_device", None)
        if not has_ns_demand and not has_ns_served and ns_device is None:
            return

        ns_demand_kwh = self._series_at(building, "non_shiftable_load", t, 0.0) * ratio

        if has_ns_served:
            ns_served_kwh = self._series_at(building, "energy_to_non_shiftable_load", t, 0.0) * ratio
            tol_ns = self._independent_energy_tol(ns_demand_kwh, ns_served_kwh)
            self._require(ns_served_kwh >= -tol_ns, (
                f"[served_energy_bounds] Negative served non_shiftable_load energy for '{building.name}' at t={t}: "
                f"expected_min=0.000000 kWh, actual={ns_served_kwh:.6f} kWh, residual={ns_served_kwh:.6f} kWh."
            ))
            if has_ns_demand:
                residual_ns = ns_served_kwh - ns_demand_kwh
                self._require(residual_ns <= tol_ns, (
                    f"[served_energy_bounds] Served non_shiftable_load exceeds demand for '{building.name}' at t={t}: "
                    f"expected_max={ns_demand_kwh:.6f} kWh, actual={ns_served_kwh:.6f} kWh, residual={residual_ns:.6f} kWh."
                ))

        if ns_device is not None:
            ns_device_kwh = self._device_electricity_at(
                ns_device, t, "non_shiftable_load_device.electricity_consumption", 0.0
            )
            tol_dev = self._independent_energy_tol(ns_demand_kwh, ns_device_kwh)
            self._require(ns_device_kwh >= -tol_dev, (
                f"[served_energy_bounds] Negative non_shiftable_load_device consumption for '{building.name}' at t={t}: "
                f"expected_min=0.000000 kWh, actual={ns_device_kwh:.6f} kWh, residual={ns_device_kwh:.6f} kWh."
            ))
            if has_ns_demand:
                residual_dev = ns_device_kwh - ns_demand_kwh
                self._require(residual_dev <= tol_dev, (
                    f"[served_energy_bounds] non_shiftable_load_device consumption exceeds demand for '{building.name}' at t={t}: "
                    f"expected_max={ns_demand_kwh:.6f} kWh, actual={ns_device_kwh:.6f} kWh, residual={residual_dev:.6f} kWh."
                ))
            if has_ns_served and not pre_step_outage:
                ns_served_kwh = self._series_at(building, "energy_to_non_shiftable_load", t, 0.0) * ratio
                residual_match = ns_device_kwh - ns_served_kwh
                tol_match = self._independent_energy_tol(ns_served_kwh, ns_device_kwh)
                self._require(abs(residual_match) <= tol_match, (
                    f"[served_energy_bounds] non_shiftable_load_device consumption mismatches served non_shiftable_load "
                    f"for '{building.name}' at t={t}: "
                    f"expected={ns_served_kwh:.6f} kWh, actual={ns_device_kwh:.6f} kWh, residual={residual_match:.6f} kWh."
                ))

    def _assert_outage_local_balance(self, building, t: int):
        if not self._is_outage_step(building, t):
            return

        solar_generation = self._series_at(building, "solar_generation", t, 0.0)
        pv_available = max(-solar_generation, 0.0)
        storage = getattr(building, "electrical_storage", None)
        storage_energy = self._device_electricity_at(
            storage, t, "electrical_storage.electricity_consumption", 0.0
        )

        chargers = getattr(building, "electric_vehicle_chargers", None) or []
        if chargers:
            charger_charge = 0.0
            v2b_discharge = 0.0
            for charger in chargers:
                charger_id = getattr(charger, "charger_id", "charger")
                c_energy = self._state(
                    getattr(charger, "electricity_consumption", []),
                    t,
                    f"charger[{charger_id}].electricity_consumption",
                    0.0,
                )
                charger_charge += max(c_energy, 0.0)
                v2b_discharge += max(-c_energy, 0.0)
        else:
            charger_energy = self._series_at(building, "chargers_electricity_consumption", t, 0.0)
            charger_charge = max(charger_energy, 0.0)
            v2b_discharge = max(-charger_energy, 0.0)

        if not bool(getattr(building, "outage_vehicle_to_building", False)):
            tol_v2b = self._independent_energy_tol(v2b_discharge)
            self._require(v2b_discharge <= tol_v2b, (
                f"[outage_local_load_bound] EV discharge during outage without outage_vehicle_to_building "
                f"for '{building.name}' at t={t}: "
                f"expected_max=0.000000 kWh, actual={v2b_discharge:.6f} kWh, residual={v2b_discharge:.6f} kWh."
            ))

        non_storage_loads = (
            self._device_electricity_at(getattr(building, "cooling_device", None), t, "cooling_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "heating_device", None), t, "heating_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "dhw_device", None), t, "dhw_device.electricity_consumption", 0.0)
            + self._device_electricity_at(getattr(building, "non_shiftable_load_device", None), t, "non_shiftable_load_device.electricity_consumption", 0.0)
            + charger_charge
            + self._series_at(building, "deferrable_appliances_electricity_consumption", t, 0.0)
            + self._series_at(building, "escalators_electricity_consumption", t, 0.0)
        )
        local_loads = non_storage_loads + max(storage_energy, 0.0)
        storage_discharge = max(-storage_energy, 0.0) + v2b_discharge
        local_sources = pv_available + storage_discharge

        tol_balance = self._independent_energy_tol(local_loads, local_sources)
        residual_balance = local_loads - local_sources
        self._require(residual_balance <= tol_balance, (
            f"[outage_local_balance] Outage local energy balance violated for '{building.name}' at t={t}: "
            f"expected_max={local_sources:.6f} kWh, actual={local_loads:.6f} kWh, residual={residual_balance:.6f} kWh."
        ))

        if physics_version_of(building) >= 2:
            # Storage discharges only into the islanded load that PV leaves (#229); physics version 1
            # can discharge more and books the surplus as PV curtailment.
            uncovered_load = max(non_storage_loads - pv_available, 0.0)
            tol_discharge = self._independent_energy_tol(storage_discharge, uncovered_load)
            residual_discharge = storage_discharge - uncovered_load
            self._require(residual_discharge <= tol_discharge, (
                f"[outage_local_load_bound] Outage storage discharge exceeds the load not covered by PV "
                f"for '{building.name}' at t={t}: "
                f"expected_max={uncovered_load:.6f} kWh, actual={storage_discharge:.6f} kWh, "
                f"residual={residual_discharge:.6f} kWh."
            ))

            if getattr(building, "pv_curtailment", None) is not None:
                curtailment = self._series_at(building, "pv_curtailment", t, 0.0)
                expected_curtailment = max(pv_available - (local_loads - storage_discharge), 0.0)
                tol_curtailment = self._independent_energy_tol(curtailment, expected_curtailment, pv_available)
                self._require(curtailment >= -tol_curtailment, (
                    f"[outage_local_load_bound] Negative PV curtailment during outage for '{building.name}' at t={t}: "
                    f"expected_min=0.000000 kWh, actual={curtailment:.6f} kWh, residual={curtailment:.6f} kWh."
                ))
                residual_curtailment_bound = curtailment - pv_available
                self._require(residual_curtailment_bound <= tol_curtailment, (
                    f"[outage_local_load_bound] Outage PV curtailment exceeds available PV for '{building.name}' at t={t}: "
                    f"expected_max={pv_available:.6f} kWh, actual={curtailment:.6f} kWh, "
                    f"residual={residual_curtailment_bound:.6f} kWh."
                ))
                residual_curtailment = curtailment - expected_curtailment
                self._require(abs(residual_curtailment) <= tol_curtailment, (
                    f"[outage_local_load_bound] Outage PV curtailment mismatch for '{building.name}' at t={t}: "
                    f"expected={expected_curtailment:.6f} kWh, actual={curtailment:.6f} kWh, "
                    f"residual={residual_curtailment:.6f} kWh."
                ))

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
            self._require(-self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS, (
                f"{name} SOC out of bounds for '{building.name}' at t={t}: soc={soc:.6f}."
            ))

        for charger in getattr(building, "electric_vehicle_chargers", None) or []:
            for ev in self._iter_charger_evs(charger):
                soc = self._safe_index(ev.battery.soc, t, 0.0)
                self._require(-self.SOC_EPS <= soc <= 1.0 + self.SOC_EPS, (
                    f"EV SOC out of bounds for '{ev.name}' at t={t}: soc={soc:.6f}."
                ))

    def _pre_transfer_soc(self, battery, t: int, capacity: float, dod_floor: float) -> float:
        cached = self._battery_pre_transfer_soc.get((id(battery), t))
        if cached is not None:
            return cached

        if getattr(battery, "_energy_event_step", None) == t:
            events = getattr(battery, "_energy_events", None) or []
            for event in events:
                if event.get("kind") == "transfer":
                    return self._to_scalar(event.get("before"), dod_floor * capacity) / capacity
            for event in reversed(events):
                if event.get("kind") in ("external", "standby"):
                    return self._to_scalar(event.get("after"), dod_floor * capacity) / capacity

        if t == 0:
            return self._to_scalar(getattr(battery, "initial_soc", dod_floor), dod_floor)

        prev_soc = self._safe_index(getattr(battery, "soc", []), t - 1, dod_floor)
        loss = min(max(self._to_scalar(getattr(battery, "loss_coefficient", 0.0), 0.0), 0.0), 1.0)
        return prev_soc * (1.0 - loss)

    def _assert_battery_dod_floor(self, building, t: int):
        candidates = [
            ("electrical_storage", getattr(building, "electrical_storage", None)),
        ]
        for charger in getattr(building, "electric_vehicle_chargers", None) or []:
            charger_step = int(getattr(charger, "time_step", t))
            if t == charger_step:
                ev = getattr(charger, "connected_electric_vehicle", None)
            else:
                past = getattr(charger, "past_connected_evs", None)
                ev = (
                    past[t]
                    if past is not None and 0 <= t < len(past)
                    else getattr(charger, "connected_electric_vehicle", None)
                )
            if ev is not None:
                charger_id = getattr(charger, "charger_id", "charger")
                ev_name = getattr(ev, "name", "ev")
                candidates.append((f"{charger_id}:{ev_name}.battery", getattr(ev, "battery", None)))

        seen = set()
        for label, battery in candidates:
            if battery is None or id(battery) in seen:
                continue
            seen.add(id(battery))

            capacity = self._to_scalar(getattr(battery, "capacity", 0.0), 0.0)
            if capacity <= 0.0:
                continue

            raw_dod = getattr(battery, "depth_of_discharge", None)
            if raw_dod is None:
                continue

            dod = self._state([raw_dod], 0, f"{label}.depth_of_discharge", 1.0)
            dod_floor = min(max(1.0 - dod, 0.0), 1.0)
            soc = self._state(getattr(battery, "soc", []), t, f"{label}.soc", 0.0)
            pre_transfer_soc = self._pre_transfer_soc(battery, t, capacity, dod_floor)
            admissible_floor = min(dod_floor, pre_transfer_soc)
            residual = soc - admissible_floor

            self._require(soc >= admissible_floor - self.SOC_EPS, (
                f"[battery_dod_floor] Battery SOC below depth-of-discharge reserve for "
                f"'{building.name}' ({label}) at t={t}: "
                f"expected_min={admissible_floor:.6f} (dod_reserve={dod_floor:.6f}), "
                f"actual={soc:.6f}, residual={residual:.6f}."
            ))

            energy_balance_kwh = self._state(
                getattr(battery, "energy_balance", []), t, f"{label}.energy_balance", 0.0
            )
            if energy_balance_kwh < -self.INDEPENDENT_ENERGY_EPS:
                discharge_residual = soc - dod_floor
                self._require(soc >= dod_floor - self.SOC_EPS, (
                    f"[battery_dod_floor] Battery discharged below depth-of-discharge reserve for "
                    f"'{building.name}' ({label}) at t={t}: "
                    f"expected_min={dod_floor:.6f}, actual={soc:.6f}, "
                    f"residual={discharge_residual:.6f} (energy_balance={energy_balance_kwh:.6f} kWh)."
                ))

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
        self._require(abs(energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
            f"Battery power bound exceeded for '{building.name}' at t={t}: "
            f"energy={energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
        ))

    def _assert_charger_power_bounds(self, building, t: int):
        step_seconds = max(self._to_scalar(building.seconds_per_time_step, 1.0), 1.0)

        for charger in getattr(building, "electric_vehicle_chargers", None) or []:
            max_ch_kw = self._to_scalar(getattr(charger, "max_charging_power", 0.0), 0.0)
            max_dis_kw = self._to_scalar(getattr(charger, "max_discharging_power", 0.0), 0.0)
            max_power_kw = max(max_ch_kw, max_dis_kw)
            if max_power_kw <= 0.0:
                continue

            applied_energy_kwh = self._safe_index(charger.electricity_consumption, t, 0.0)
            commanded_energy_kwh = self._safe_index(charger.past_charging_action_values_kwh, t, 0.0)
            max_abs_energy_kwh = power_kw_to_energy_kwh(max_power_kw, step_seconds)

            self._require(abs(applied_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
                f"Charger power bound exceeded at '{building.name}:{charger.charger_id}' t={t}: "
                f"applied={applied_energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
            ))
            self._require(abs(commanded_energy_kwh) <= max_abs_energy_kwh + self.ENERGY_EPS, (
                f"Charger command bound exceeded at '{building.name}:{charger.charger_id}' t={t}: "
                f"commanded={commanded_energy_kwh:.6f} kWh, limit={max_abs_energy_kwh:.6f} kWh/step."
            ))

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
