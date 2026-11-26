"""Operational rule-based baselines: BAU variants, Basic, Smart and Community.

Ported from the Soft-CPS Algorithms repository
(``algorithms/agents/baseline_policies.py`` and
``algorithms/configuration/baseline_defaults.py`` at commit 725a72a). The
public CityLearn agents in :mod:`citylearn.agents.baseline` wrap these engines.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from citylearn.agents._rule_engine import ChargerInfo, RulePolicyBase, StorageInfo


# The engines stop charging an EV this far below its target SOC. It sits inside the KPI tolerance,
# citylearn.electric_vehicle.EV_SERVICE_SOC_TOLERANCE, so their departures meet the target.
EV_CHARGE_STOP_SOC_TOLERANCE = 0.001

# Fixed reference tariff: Core30 2023 OMIE terciles, rounded to 4 decimals.
# Selection uses prices only, never controller outcomes or 2024 data.
BASIC_PRICE_DEFAULTS = {
    "basic_price_policy": "fixed_thresholds",
    "basic_cheap_price_eur_kwh": 0.0765,
    "basic_expensive_price_eur_kwh": 0.1078,
}
COMMUNITY_IMPORT_THRESHOLD_KW = 15.0

NORMAL_DEFAULTS = {
    "storage_charge_rate": 1.0,
    "storage_discharge_rate": 1.0,
    "pv_surplus_threshold_kw": 0.05,
    "normal_storage_discharge_import_threshold_kw": 0.05,
    "ev_service_soc_tolerance": EV_CHARGE_STOP_SOC_TOLERANCE,
}

SMART_DEFAULTS = {"price_charge_rate": 0.0}
ECONOMIC_SMART_DEFAULTS = {"price_charge_rate": 0.60}


def policy_defaults(name, hyperparameters=None):
    if name == "RBCBasicPolicy":
        hyper = hyperparameters or {}
        # Forecast-relative recipes are historical; preserve their battery rule
        # unless the caller explicitly opts into the new storage policy.
        legacy = hyper.get("basic_price_policy") == "forecast_relative"
        mode = hyper.get("basic_storage_policy", "price_only" if legacy else "self_consumption")
        return {
            **BASIC_PRICE_DEFAULTS,
            **(NORMAL_DEFAULTS if mode == "self_consumption" else {}),
            "basic_storage_policy": mode,
        }
    if name == "RBCCommunityPolicy":
        return {
            **ECONOMIC_SMART_DEFAULTS,
            "community_import_threshold_kw": COMMUNITY_IMPORT_THRESHOLD_KW,
        }
    if name in {"Smart", "RBCSmartLocalPolicy"}:
        return ECONOMIC_SMART_DEFAULTS
    if name == "NormalTargetPolicy":
        return {**NORMAL_DEFAULTS, "ev_normal_target_soc": 0.0}
    if name in {"NormalPolicy", "NormalNoBatteryPolicy"}:
        return NORMAL_DEFAULTS
    if name in {
        "RBCSmartPolicy",
        "SignalAwareRBC",
        "SignalAwareRBCSmartLocal",
        "SignalAwareRBCCommunity",
        "SignalDirectedRBC",
    }:
        return SMART_DEFAULTS
    return {}

class _OperationalBaselinePolicy(RulePolicyBase):
    """Shared helpers for deterministic non-learning baselines."""

    uses_community_dispatch = False

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        hyper = config.get("algorithm", {}).get("hyperparameters") or {}
        self.storage_min_soc: float = float(hyper.get("storage_min_soc", 0.20))
        self.storage_max_soc: float = float(hyper.get("storage_max_soc", 0.90))
        self.storage_target_soc: float = float(hyper.get("storage_target_soc", 0.50))
        self.storage_charge_rate: float = float(hyper.get("storage_charge_rate", 0.35))
        self.storage_discharge_rate: float = float(hyper.get("storage_discharge_rate", 0.35))
        self.price_charge_rate: float = float(hyper.get("price_charge_rate", 0.60))
        self.price_discharge_rate: float = float(hyper.get("price_discharge_rate", 0.45))
        self.pv_charge_rate: float = float(hyper.get("pv_charge_rate", 0.75))
        self.peak_discharge_rate: float = float(hyper.get("peak_discharge_rate", 0.65))
        self.pv_surplus_threshold_kw: float = float(hyper.get("pv_surplus_threshold_kw", 0.25))
        self.storage_price_charge_soc_ceiling: float = float(
            hyper.get("storage_price_charge_soc_ceiling", self.storage_max_soc)
        )
        self.storage_price_discharge_soc_floor: float = float(
            hyper.get("storage_price_discharge_soc_floor", self.storage_min_soc)
        )
        self.storage_peak_discharge_soc_floor: float = float(
            hyper.get("storage_peak_discharge_soc_floor", self.storage_min_soc)
        )
        self.normal_storage_discharge_import_threshold_kw: float = float(
            hyper.get("normal_storage_discharge_import_threshold_kw", self.pv_surplus_threshold_kw)
        )
        self.storage_discharge_import_threshold_kw: float = float(
            hyper.get(
                "storage_discharge_import_threshold_kw",
                self.normal_storage_discharge_import_threshold_kw,
            )
        )
        self.ev_normal_charge_rate: float = float(hyper.get("ev_normal_charge_rate", 1.0))
        self.ev_normal_target_soc: float = float(hyper.get("ev_normal_target_soc", 1.0))
        self.ev_price_charge_rate: float = float(hyper.get("ev_price_charge_rate", 0.70))
        self.ev_pv_charge_rate: float = float(hyper.get("ev_pv_charge_rate", 0.85))
        self.ev_v2g_discharge_rate: float = float(hyper.get("ev_v2g_discharge_rate", 0.30))
        self.allow_v2g: bool = bool(hyper.get("allow_v2g", False))
        self.import_peak_threshold_kw: float = float(hyper.get("import_peak_threshold_kw", 7.0))
        self.low_headroom_threshold_kw: float = float(hyper.get("low_headroom_threshold_kw", 2.0))
        self.ev_community_charge_rate: float = float(
            hyper.get("ev_community_charge_rate", self.ev_pv_charge_rate)
        )
        self.community_v2g_discharge_rate: float = float(
            hyper.get("community_v2g_discharge_rate", self.ev_v2g_discharge_rate)
        )
        self.community_storage_charge_rate: float = float(
            hyper.get("community_storage_charge_rate", self.pv_charge_rate)
        )
        self.community_storage_discharge_rate: float = float(
            hyper.get("community_storage_discharge_rate", self.peak_discharge_rate)
        )
        self.community_surplus_charge_soc_ceiling: float = float(
            hyper.get("community_surplus_charge_soc_ceiling", self.storage_max_soc)
        )
        self.community_surplus_threshold_kw: float = float(
            hyper.get("community_surplus_threshold_kw", self.pv_surplus_threshold_kw)
        )
        community_peak = hyper.get("community_import_threshold_kw")
        self.community_import_threshold_kw: float = float(
            self.import_peak_threshold_kw if community_peak is None else community_peak
        )
        self.ev_v2g_reserve_soc: float = float(hyper.get("ev_v2g_reserve_soc", 0.15))
        self.ev_service_margin_rate: float = max(
            0.0, float(hyper.get("ev_service_margin_rate", 0.05))
        )
        self.ev_service_floor_rate: float = max(
            0.0, float(hyper.get("ev_service_floor_rate", 0.25))
        )
        self.ev_service_lookahead_hours: float = max(
            0.0,
            float(hyper.get("ev_service_lookahead_hours", 4.0)),
        )
        self.ev_service_target_soc: float = float(
            np.clip(float(hyper.get("ev_service_target_soc", 0.0) or 0.0), 0.0, 1.0)
        )
        self.ev_deadline_buffer_hours: float = max(
            0.0, float(hyper.get("ev_deadline_buffer_hours", 0.25))
        )
        self.ev_v2g_min_departure_hours: float = max(
            0.0, float(hyper.get("ev_v2g_min_departure_hours", 2.0))
        )
        self.ev_v2g_service_margin_soc: float = max(
            0.0, float(hyper.get("ev_v2g_service_margin_soc", 0.05))
        )
        self.ev_v2g_buffer_soc: float = max(0.0, float(hyper.get("ev_v2g_buffer_soc", 0.0)))
        self.ev_subhour_service_guard_steps: float = max(
            0.0,
            float(hyper.get("ev_subhour_service_guard_steps", 8.0)),
        )
        self.ev_subhour_v2g_guard_steps: float = max(
            0.0,
            float(hyper.get("ev_subhour_v2g_guard_steps", 8.0)),
        )
        self.ev_subhour_deadline_buffer_steps: float = max(
            0.0,
            float(hyper.get("ev_subhour_deadline_buffer_steps", 2.0)),
        )
        self.ev_subhour_tight_feasibility_ratio: float = float(
            np.clip(float(hyper.get("ev_subhour_tight_feasibility_ratio", 0.90)), 0.0, 1.0)
        )
        self.ev_subhour_min_service_margin_rate: float = max(
            0.0,
            float(hyper.get("ev_subhour_min_service_margin_rate", 0.10)),
        )
        self.ev_subhour_v2g_reserve_soc: float = max(
            0.0,
            float(hyper.get("ev_subhour_v2g_reserve_soc", 0.05)),
        )
        self.ev_service_soc_tolerance: float = max(
            0.0,
            float(hyper.get("ev_service_soc_tolerance", EV_CHARGE_STOP_SOC_TOLERANCE)),
        )
        self.deferrable_safety_margin_steps: float = max(
            0.0,
            float(hyper.get("deferrable_safety_margin_steps", 1.0)),
        )
        self.deferrable_import_block_threshold_kw: float = float(
            hyper.get("deferrable_import_block_threshold_kw", float("inf"))
        )
        self.deferrable_community_import_block_threshold_kw: float = float(
            hyper.get(
                "deferrable_community_import_block_threshold_kw",
                self.deferrable_import_block_threshold_kw,
            )
        )
        self.community_local_price_ratio: float = float(
            hyper.get("community_local_price_ratio", 0.8)
        )
        self.community_grid_export_price: float = float(
            hyper.get("community_grid_export_price", 0.0)
        )
        self.community_market_enabled = bool(hyper.get("community_market_enabled", False))
        self._obs_match_cache: Dict[int, Dict[tuple, List[tuple[str, int]]]] = {}
        self._dispatch_budgets: Dict[int, Dict[str, float]] = {}
        self._shared_community_budget: Optional[Dict[str, float]] = None
        self._observed_storage_info: Dict[int, StorageInfo] = {}
        self._current_step_load_ratios: Sequence[float] = ()

    def attach_environment(
        self,
        *,
        observation_names: List[List[str]],
        action_names: List[List[str]],
        action_space: List[Any],
        observation_space: List[Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().attach_environment(
            observation_names=observation_names,
            action_names=action_names,
            action_space=action_space,
            observation_space=observation_space,
            metadata=metadata,
        )
        self._obs_match_cache = {}
        self._dispatch_budgets = {}
        self._shared_community_budget = None
        self._observed_storage_info = {}
        self._current_step_load_ratios = (metadata or {}).get("current_step_load_ratios", ())
        for agent_idx, names in enumerate(action_names):
            obs_map = self._obs_index[agent_idx] if agent_idx < len(self._obs_index) else {}
            unsupported = [
                name
                for name in names
                if not (
                    self._is_storage_action_name(str(name))
                    or "electric_vehicle" in str(name)
                    or self._is_deferrable_action_name(str(name), obs_map)
                )
            ]
            if unsupported:
                raise ValueError(
                    f"{type(self).__name__} does not define control for actions {unsupported}. "
                    "Supported assets: electrical storage, EV chargers and deferrable appliances."
                )

    def _policy_type(self) -> str:
        return self.__class__.__name__

    def predict(
        self,
        observations: List[np.ndarray],
        deterministic: bool | None = None,
        *,
        context: Any = None,
    ) -> List[List[float]]:
        """Predict with a lightweight per-agent dispatch budget.

        The base rule-based loop evaluates actions in action-space order. For
        the operational RBCs we deliberately evaluate EVs before stationary
        storage so local PV is first offered to connected cars, then remaining
        surplus serves appliances before the stationary battery. Decisions are
        recorded after action limiting, so the next device sees remaining power. Returned
        actions still preserve the original action order.
        """

        del deterministic, context
        actions: List[List[float]] = []
        self._dispatch_budgets = {}
        self._shared_community_budget = None
        self._observed_storage_info = {}

        for agent_idx, raw_obs in enumerate(observations):
            obs_map = self._obs_index[agent_idx] if agent_idx < len(self._obs_index) else {}
            self._refresh_storage_info(agent_idx, np.asarray(raw_obs, dtype=float), obs_map)
            self._init_dispatch_budget(agent_idx, np.asarray(raw_obs, dtype=float), obs_map)

        if self.uses_community_dispatch and observations:
            passive_nets = [
                self._observed_passive_net_kw(np.asarray(obs, dtype=float), self._obs_index[idx])
                for idx, obs in enumerate(observations)
            ]
            if all(value is not None for value in passive_nets):
                net = sum(passive_nets)
                self._shared_community_budget = {
                    "community_surplus_kw": max(0.0, -net),
                    "community_import_kw": max(0.0, net),
                }

        try:
            for agent_idx, raw_obs in enumerate(observations):
                obs = np.asarray(raw_obs, dtype=float)
                obs_map = self._obs_index[agent_idx] if agent_idx < len(self._obs_index) else {}
                action_names = (
                    self._action_labels[agent_idx] if agent_idx < len(self._action_labels) else []
                )
                agent_actions: List[float] = [0.0 for _ in action_names]
                residual_headroom: Dict[Tuple[int, str, bool], float] = {}

                def priority(position_and_name: tuple[int, str]) -> tuple[int, int]:
                    position, name = position_and_name
                    if "electric_vehicle" in str(name) and self.control_evs:
                        return (0, position)
                    if self.control_storage and self._is_storage_action_name(str(name)):
                        return (2, position)
                    if self.control_deferrables and self._is_deferrable_action_name(
                        str(name), obs_map
                    ):
                        return (1, position)
                    return (3, position)

                for action_position, action_name in sorted(enumerate(action_names), key=priority):
                    bounds = self._get_action_bounds(agent_idx, action_position)

                    if self.control_storage and self._is_storage_action_name(str(action_name)):
                        value = self._compute_storage_action(
                            agent_idx, obs, obs_map, str(action_name), bounds
                        )
                        value = self._apply_storage_dynamic_headroom_limit(
                            value,
                            obs,
                            obs_map,
                            self._get_storage_info(agent_idx),
                            bounds,
                            agent_idx,
                            residual_headroom,
                        )
                        value = self._apply_storage_soc_limit(value, obs, obs_map, bounds)
                        self._record_storage_dispatch(agent_idx, value)
                    elif "electric_vehicle" in str(action_name) and self.control_evs:
                        charger_info = self._get_charger_info(agent_idx, action_position)
                        ctx = self._connected_ev_context(
                            agent_idx, obs, obs_map, charger_info, str(action_name)
                        )
                        if charger_info is None:
                            charger_info = ChargerInfo(
                                str(ctx["charger_id"] or ""),
                                float(ctx["max_power"]),
                                0.0,
                                float(ctx["max_discharge_power"]),
                                0.0,
                                1.0,
                                float(ctx["capacity"]),
                            )
                        else:
                            charger_info = replace(
                                charger_info,
                                max_power=float(ctx["max_power"]),
                                max_discharge_power=float(ctx["max_discharge_power"]),
                            )
                        normalised = self._compute_ev_action(
                            agent_idx,
                            obs,
                            obs_map,
                            charger_info,
                            bounds,
                            str(action_name),
                        )
                        high = bounds[1]
                        value = normalised * high if high > 1.0 else normalised
                        value = self._apply_ev_dynamic_headroom_limit(
                            value,
                            obs,
                            obs_map,
                            charger_info,
                            bounds,
                            agent_idx,
                            residual_headroom,
                        )
                        ctx = self._connected_ev_context(
                            agent_idx, obs, obs_map, charger_info, str(action_name)
                        )
                        rate = value / high if high > 1.0 else value
                        if rate >= 0.0:
                            self._record_ev_charge_dispatch(agent_idx, ctx, rate)
                        else:
                            self._record_ev_discharge_dispatch(agent_idx, ctx, -rate)
                    elif self.control_deferrables and self._is_deferrable_action_name(
                        str(action_name), obs_map
                    ):
                        value = self._compute_deferrable_action(
                            agent_idx, obs, obs_map, str(action_name), bounds
                        )
                        self._record_deferrable_dispatch(
                            agent_idx, obs, obs_map, str(action_name), value
                        )
                    else:
                        value = 0.0

                    agent_actions[action_position] = max(bounds[0], min(bounds[1], value))

                actions.append(agent_actions)
        finally:
            self._dispatch_budgets = {}
            self._shared_community_budget = None

        self.actions = actions
        return actions

    def _get_storage_info(self, agent_idx: int) -> Optional[StorageInfo]:
        return self._observed_storage_info.get(agent_idx) or super()._get_storage_info(agent_idx)

    def _refresh_storage_info(self, agent_idx, obs, obs_map) -> None:
        """Commissioned/replaced batteries must use their current electrical scale."""
        initial = super()._get_storage_info(agent_idx)
        power = self._get_first_storage_value(obs, obs_map, "nominal_power_kw")
        capacity = self._get_first_storage_value(obs, obs_map, "capacity_kwh")
        if not (
            math.isfinite(power) and power >= 0.0 and math.isfinite(capacity) and capacity >= 0.0
        ):
            return
        phase_values = [
            self._get_first_storage_value(obs, obs_map, f"phase_connection_{p}")
            for p in ("L1", "L2", "L3")
        ]
        phase = initial.phase_connection if initial is not None else None
        if all(math.isfinite(v) and v >= 0.0 for v in phase_values):
            observed_phases = tuple(p for p, v in zip(("L1", "L2", "L3"), phase_values) if v > 0.0)
            if observed_phases and observed_phases != self._phase_connection_to_phases(phase):
                phase = "_".join(observed_phases)
        if initial is not None:
            # Preserve static-schema precision when observations are float32.
            if math.isclose(power, initial.nominal_power, rel_tol=1e-6, abs_tol=1e-6):
                power = initial.nominal_power
            if math.isclose(capacity, initial.capacity, rel_tol=1e-6, abs_tol=1e-6):
                capacity = initial.capacity
        self._observed_storage_info[agent_idx] = StorageInfo(power, capacity, phase)

    def _init_dispatch_budget(
        self, agent_idx: int, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> None:
        current_net = None
        if self._current_step_load_ratios:
            current_net = self._current_step_passive_net_kw(obs, obs_map, self._current_step_load_ratios[agent_idx])
        if current_net is None:
            local_surplus = self._pv_surplus_kw(obs, obs_map)
            local_import = self._get_import_power(obs, obs_map)
        else:
            local_surplus = -current_net
            local_import = current_net
        self._dispatch_budgets[agent_idx] = {
            "local_surplus_kw": max(0.0, local_surplus),
            "local_import_kw": max(0.0, local_import),
            "community_surplus_kw": max(0.0, self._community_surplus_kw(obs, obs_map)),
            "community_import_kw": max(0.0, self._get_community_import_power(obs, obs_map)),
        }

        if self.uses_community_dispatch and self._shared_community_budget is None:
            self._shared_community_budget = {
                key: self._dispatch_budgets[agent_idx][key]
                for key in ("community_surplus_kw", "community_import_kw")
            }

    def _budget_container(self, agent_idx, key):
        if self.uses_community_dispatch and key.startswith("community_"):
            return self._shared_community_budget
        return self._dispatch_budgets.get(agent_idx)

    def _budget_value(
        self,
        agent_idx: int,
        key: str,
        fallback: float,
    ) -> float:
        budget = self._budget_container(agent_idx, key)
        if budget is None:
            return max(0.0, fallback)
        return max(0.0, budget.get(key, fallback))

    def _consume_budget_kw(self, agent_idx: int, key: str, amount_kw: float) -> float:
        budget = self._budget_container(agent_idx, key)
        amount = max(0.0, amount_kw)
        if budget is None or amount <= self.energy_epsilon:
            return 0.0
        consumed = min(max(0.0, budget.get(key, 0.0)), amount)
        budget[key] = max(0.0, budget.get(key, 0.0) - consumed)
        return consumed

    def _consume_other_local_budgets(self, agent_idx: int, key: str, power_kw: float) -> None:
        """Reserve shared energy at its local source so it cannot be offered twice."""
        for other_idx in self._dispatch_budgets:
            if other_idx != agent_idx and power_kw > self.energy_epsilon:
                power_kw -= self._consume_budget_kw(other_idx, key, power_kw)

    def _record_ev_charge_dispatch(
        self,
        agent_idx: int,
        ctx: Mapping[str, float | bool | None],
        rate: float,
    ) -> None:
        charge_kw = max(0.0, rate) * float(ctx["max_power"])
        if charge_kw <= self.energy_epsilon:
            return
        local_used = self._consume_budget_kw(agent_idx, "local_surplus_kw", charge_kw)
        remaining = charge_kw - local_used
        if self.uses_community_dispatch and self._shared_community_budget is not None:
            shared_used = self._consume_budget_kw(agent_idx, "community_surplus_kw", charge_kw)
            self._shared_community_budget["community_import_kw"] += charge_kw - shared_used
            remote_used = min(remaining, max(0.0, shared_used - local_used))
            self._consume_other_local_budgets(agent_idx, "local_surplus_kw", remote_used)
            if self._community_energy_is_discounted():
                remaining -= remote_used
        budget = self._dispatch_budgets.get(agent_idx)
        if budget is not None and remaining > self.energy_epsilon:
            budget["local_import_kw"] = budget.get("local_import_kw", 0.0) + remaining

    def _record_ev_discharge_dispatch(
        self,
        agent_idx: int,
        ctx: Mapping[str, float | bool | None],
        rate: float,
    ) -> None:
        discharge_kw = max(0.0, rate) * float(ctx.get("max_discharge_power") or ctx["max_power"])
        if discharge_kw <= self.energy_epsilon:
            return
        local_used = self._consume_budget_kw(agent_idx, "local_import_kw", discharge_kw)
        if self.uses_community_dispatch and self._shared_community_budget is not None:
            shared_used = self._consume_budget_kw(agent_idx, "community_import_kw", discharge_kw)
            self._consume_other_local_budgets(
                agent_idx, "local_import_kw", max(0.0, shared_used - local_used)
            )
            # V2G/BESS energy is not fresh PV surplus for another battery.

    def _record_deferrable_dispatch(self, agent_idx, obs, obs_map, action_name, value):
        if value <= 0.0:
            return
        prefix = self._resolve_deferrable_observation_prefix(action_name, obs_map)
        if prefix is None:
            return
        power = self._get_deferrable_value(
            obs, obs_map, prefix, "start_power_kw", default=float("nan")
        )
        if not math.isfinite(power):
            energy = self._get_deferrable_value(
                obs, obs_map, prefix, "start_energy_kwh_step", default=float("nan")
            )
            power = energy / self.step_hours
        if not math.isfinite(power):
            power = self._get_deferrable_value(
                obs, obs_map, prefix, "cycle_peak_power_kw", default=0.0
            )
        self._record_ev_charge_dispatch(
            agent_idx,
            {"max_power": max(0.0, power)},
            1.0,
        )

    def _record_storage_dispatch(self, agent_idx: int, value: float) -> None:
        storage_info = self._get_storage_info(agent_idx)
        if storage_info is None or storage_info.nominal_power <= self.energy_epsilon:
            return
        ctx = {
            "max_power": storage_info.nominal_power,
            "max_discharge_power": storage_info.nominal_power,
        }
        if value > self.energy_epsilon:
            self._record_ev_charge_dispatch(agent_idx, ctx, value)
        elif value < -self.energy_epsilon:
            self._record_ev_discharge_dispatch(agent_idx, ctx, -value)

    def _cached_observation_matches(
        self,
        obs_map: Mapping[str, int],
        *,
        suffixes: Sequence[str] = (),
        include_tokens: Sequence[str] = (),
        exclude_tokens: Sequence[str] = (),
        prefix: str = "",
    ) -> List[tuple[str, int]]:
        """Return stable observation name/index matches for a static layout."""
        include = tuple(str(token).lower() for token in include_tokens)
        exclude = tuple(str(token).lower() for token in exclude_tokens)
        suffix_key = tuple(str(suffix) for suffix in suffixes)
        cache_key = (suffix_key, include, exclude, str(prefix))
        map_cache = self._obs_match_cache.setdefault(id(obs_map), {})
        cached = map_cache.get(cache_key)
        if cached is not None:
            return cached

        matches: List[tuple[str, int]] = []
        for raw_name, index in obs_map.items():
            name = str(raw_name)
            if prefix and not name.startswith(prefix):
                continue
            if suffix_key and not any(name.endswith(suffix) for suffix in suffix_key):
                continue
            lowered = name.lower()
            if include and not all(token in lowered for token in include):
                continue
            if exclude and any(token in lowered for token in exclude):
                continue
            matches.append((name, int(index)))

        map_cache[cache_key] = matches
        return matches

    def _get_first_value(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        names: Sequence[str],
        *,
        suffixes: Sequence[str] = (),
        default: float = 0.0,
    ) -> float:
        for name in names:
            value = self._get_value(obs, obs_map, name, default=float("nan"))
            if not math.isnan(value):
                return value

        if suffixes:
            for name, index in self._cached_observation_matches(obs_map, suffixes=suffixes):
                if index >= len(obs):
                    continue
                value = obs[index]
                try:
                    if math.isnan(value):
                        continue
                except TypeError:
                    pass
                return float(value)

        return default

    def _get_hour(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return (
            self._get_first_value(obs, obs_map, ["hour", "district__hour"], default=float("nan"))
            % 24.0
        )

    def _get_price_context(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> Dict[str, float | bool]:
        price = self._get_first_value(
            obs,
            obs_map,
            ["electricity_pricing", "district__electricity_pricing"],
            default=float("nan"),
        )
        forecasts = [
            self._get_first_value(
                obs,
                obs_map,
                [
                    f"electricity_pricing_predicted_{idx}",
                    f"district__electricity_pricing_predicted_{idx}",
                ],
                default=float("nan"),
            )
            for idx in (1, 2, 3)
        ]
        for _name, index in self._cached_observation_matches(
            obs_map, include_tokens=("forecast_price",)
        ):
            if index >= len(obs):
                continue
            value = obs[index]
            if not math.isnan(value):
                forecasts.append(float(value))
        valid = [value for value in forecasts if not math.isnan(value)]

        if math.isnan(price):
            hour = self._get_hour(obs, obs_map)
            cheap = hour <= 7.0 or hour >= 22.0
            expensive = 17.0 <= hour <= 21.0
            return {
                "price": 0.0,
                "cheap": cheap,
                "expensive": expensive,
                "near_forecast_peak": expensive,
            }

        if not valid:
            return {"price": price, "cheap": False, "expensive": False, "near_forecast_peak": False}

        forecast_mean = float(np.mean(valid))
        forecast_min = float(np.min(valid))
        forecast_max = float(np.max(valid))
        if max(abs(price - value) for value in valid) <= 1.0e-9:
            return {"price": price, "cheap": False, "expensive": False, "near_forecast_peak": False}
        spread = max(forecast_max - forecast_min, abs(forecast_mean) * 0.05, 1.0e-9)
        cheap = price <= forecast_mean - 0.20 * spread or price <= forecast_min + 0.10 * spread
        expensive = price >= forecast_mean + 0.20 * spread or price >= forecast_max - 0.10 * spread
        if cheap and expensive:
            cheap = expensive = False
        near_forecast_peak = expensive and price >= forecast_max - max(0.10 * spread, 0.005)
        return {
            "price": price,
            "cheap": cheap,
            "expensive": expensive,
            "near_forecast_peak": near_forecast_peak,
        }

    def _forecast_values(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        include_tokens: Sequence[str],
        *,
        exclude_tokens: Sequence[str] = (),
    ) -> List[float]:
        values: List[float] = []
        for _name, index in self._cached_observation_matches(
            obs_map,
            include_tokens=include_tokens,
            exclude_tokens=exclude_tokens,
        ):
            if index >= len(obs):
                continue
            value = obs[index]
            if math.isfinite(value):
                values.append(float(value))
        return values

    def _max_forecast_value(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        include_tokens: Sequence[str],
        *,
        exclude_tokens: Sequence[str] = (),
        default: float = 0.0,
    ) -> float:
        values = self._forecast_values(obs, obs_map, include_tokens, exclude_tokens=exclude_tokens)
        return max(values) if values else default

    def _min_forecast_value(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        include_tokens: Sequence[str],
        *,
        exclude_tokens: Sequence[str] = (),
        default: float = float("inf"),
    ) -> float:
        values = self._forecast_values(obs, obs_map, include_tokens, exclude_tokens=exclude_tokens)
        return min(values) if values else default

    def _forecast_local_surplus_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        candidates = self._forecast_values(
            obs,
            obs_map,
            ["forecast_pv_surplus_mean"],
            exclude_tokens=["community"],
        )
        candidates.extend(
            self._forecast_values(obs, obs_map, ["forecast_export"], exclude_tokens=["community"])
        )
        net_values = self._forecast_values(
            obs, obs_map, ["forecast_net"], exclude_tokens=["community"]
        )
        candidates.extend(-value for value in net_values if value < 0.0)
        positive = [max(0.0, value) for value in candidates]
        return max(positive) if positive else 0.0

    def _forecast_local_import_peak_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        candidates = self._forecast_values(
            obs, obs_map, ["forecast_import"], exclude_tokens=["community"]
        )
        net_values = self._forecast_values(
            obs, obs_map, ["forecast_net"], exclude_tokens=["community"]
        )
        candidates.extend(value for value in net_values if value > 0.0)
        positive = [max(0.0, value) for value in candidates]
        return max(positive) if positive else 0.0

    def _forecast_local_headroom_min_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return self._min_forecast_value(
            obs,
            obs_map,
            ["forecast_headroom"],
            exclude_tokens=["community"],
            default=float("inf"),
        )

    def _forecast_community_surplus_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        candidates = self._forecast_values(obs, obs_map, ["forecast_community_pv_surplus"])
        candidates.extend(self._forecast_values(obs, obs_map, ["forecast_community_export"]))
        net_values = self._forecast_values(obs, obs_map, ["forecast_community_net"])
        candidates.extend(-value for value in net_values if value < 0.0)
        positive = [max(0.0, value) for value in candidates]
        return max(positive) if positive else 0.0

    def _forecast_community_import_peak_kw(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> float:
        candidates = self._forecast_values(obs, obs_map, ["forecast_community_import"])
        net_values = self._forecast_values(obs, obs_map, ["forecast_community_net"])
        candidates.extend(value for value in net_values if value > 0.0)
        positive = [max(0.0, value) for value in candidates]
        return max(positive) if positive else 0.0

    def _forecast_community_headroom_min_kw(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> float:
        return self._min_forecast_value(
            obs,
            obs_map,
            ["forecast_community_headroom"],
            default=float("inf"),
        )

    def _forecast_solar_resource_expected(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> bool:
        pv_values = self._forecast_values(
            obs, obs_map, ["forecast_pv"], exclude_tokens=["community"]
        )
        community_pv_values = self._forecast_values(obs, obs_map, ["forecast_community_pv"])
        irradiance_values = self._forecast_values(obs, obs_map, ["solar_irradiance_predicted"])
        return (
            max((max(0.0, value) for value in pv_values), default=0.0)
            > self.pv_surplus_threshold_kw
            or max((max(0.0, value) for value in community_pv_values), default=0.0)
            > self.community_surplus_threshold_kw
            or max((max(0.0, value) for value in irradiance_values), default=0.0) > 100.0
        )

    def _get_storage_soc(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        value = self._storage_soc_ratio(
            np.asarray(obs, dtype=float), obs_map, default=self.storage_target_soc
        )
        if math.isnan(value):
            return float(np.clip(self.storage_target_soc, 0.0, 1.0))
        return value

    def _storage_strategy_limits(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> tuple[float, float]:
        observed_min, observed_max = self._observed_storage_soc_limits(
            np.asarray(obs, dtype=float), obs_map
        )
        min_soc = max(self.storage_min_soc, observed_min)
        max_soc = min(self.storage_max_soc, observed_max)
        if min_soc > max_soc:
            return observed_min, observed_max
        return min_soc, max_soc

    def _current_step_passive_net_kw(
        self, obs: np.ndarray, obs_map: Mapping[str, int], time_step_ratio: float,
    ) -> Optional[float]:
        """Use current-step load and PV only when both terms are observable."""
        load_kwh = self._get_value(obs, obs_map, "non_shiftable_load", default=float("nan"))
        if not math.isfinite(load_kwh):
            return None

        # The flattener can alias missing solar_generation to settled PV in kW.
        pv_kwh = float("nan")
        solar_idx = obs_map.get("solar_generation")
        if solar_idx is not None and solar_idx != obs_map.get("pv_power_kw"):
            pv_kwh = self._get_value(obs, obs_map, "solar_generation", default=float("nan"))
        if not math.isfinite(pv_kwh):
            if self._get_value(obs, obs_map, "active_pvs_count", default=float("nan")) != 0.0:
                return None
            pv_kwh = 0.0

        running_appliance_kw = sum(
            max(0.0, float(obs[idx]))
            for _, idx in self._cached_observation_matches(
                obs_map, prefix="deferrable_appliance::", suffixes=("::current_step_power_kw",)
            )
            if idx < len(obs) and math.isfinite(obs[idx])
        )
        # Raw load is dataset-step energy. Solar is already control-step energy.
        # Thermal device electricity observations describe the previous step.
        return (max(0.0, load_kwh) * time_step_ratio - max(0.0, pv_kwh)) / self.step_hours + running_appliance_kw

    def _get_pv_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return max(
            0.0,
            self._get_first_value(
                obs,
                obs_map,
                ["pv_power_kw"],
                suffixes=("::generation_power_kw",),
                default=self._get_first_value(obs, obs_map, ["solar_generation"], default=0.0)
                / self.step_hours,
            ),
        )

    def _get_load_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return max(
            0.0,
            self._get_first_value(
                obs,
                obs_map,
                ["load_power_kw"],
                default=self._get_first_value(obs, obs_map, ["non_shiftable_load"], default=0.0)
                / self.step_hours,
            ),
        )

    def _observed_passive_net_kw(self, obs, obs_map):
        """Remove previous EV/BESS commands before allocating their next commands.

        Simulator entity electrical metrics are simultaneous settled measurements.
        Net import already contains those controllable powers; adding the next
        EV command to that measurement would count its energy twice.
        """
        values = [
            self._get_first_value(obs, obs_map, [name], default=float("nan"))
            for name in ("net_power_kw", "bess_power_kw", "ev_charging_power_kw")
        ]
        if all(math.isfinite(value) for value in values):
            net, bess, ev = values
            return net - bess - ev
        return None

    def _get_import_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        passive_net = self._observed_passive_net_kw(obs, obs_map)
        if passive_net is not None:
            return max(0.0, passive_net)
        import_power = self._get_first_value(
            obs, obs_map, ["import_power_kw"], default=float("nan")
        )
        if not math.isnan(import_power):
            return max(0.0, import_power)
        net_power = self._get_first_value(obs, obs_map, ["net_power_kw"], default=float("nan"))
        if not math.isfinite(net_power):
            net_power = (
                self._get_first_value(obs, obs_map, ["net_electricity_consumption"], default=0.0)
                / self.step_hours
            )
        return max(0.0, net_power)

    def _get_export_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        export_power = self._get_first_value(
            obs, obs_map, ["export_power_kw"], default=float("nan")
        )
        if not math.isnan(export_power):
            return max(0.0, export_power)
        net_power = self._get_first_value(obs, obs_map, ["net_power_kw"], default=float("nan"))
        if not math.isfinite(net_power):
            net_power = (
                self._get_first_value(
                    obs, obs_map, ["net_electricity_consumption"], default=float("nan")
                )
                / self.step_hours
            )
        if not math.isnan(net_power):
            return max(0.0, -net_power)
        return 0.0

    def _get_headroom_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return self._get_first_value(
            obs,
            obs_map,
            [
                "charging_building_headroom_kw",
                "building_import_headroom_kw",
                "phase_headroom_kw",
                "district__community_building_headroom_kw",
                "district__community_phase_headroom_kw",
            ],
            default=float("inf"),
        )

    def _get_community_import_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        import_power = self._get_first_value(
            obs,
            obs_map,
            ["district__community_import_power_kw", "community_import_power_kw"],
            default=float("nan"),
        )
        if not math.isnan(import_power):
            return max(0.0, import_power)
        net_power = self._get_first_value(
            obs,
            obs_map,
            ["district__community_net_power_kw", "community_net_power_kw"],
            default=float("nan"),
        )
        if not math.isnan(net_power):
            return max(0.0, net_power)
        return 0.0

    def _get_community_export_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        export_power = self._get_first_value(
            obs,
            obs_map,
            ["district__community_export_power_kw", "community_export_power_kw"],
            default=float("nan"),
        )
        if not math.isnan(export_power):
            return max(0.0, export_power)
        net_power = self._get_first_value(
            obs,
            obs_map,
            ["district__community_net_power_kw", "community_net_power_kw"],
            default=float("nan"),
        )
        if not math.isnan(net_power):
            return max(0.0, -net_power)
        return 0.0

    def _get_community_pv_power(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return max(
            0.0,
            self._get_first_value(
                obs,
                obs_map,
                ["district__community_pv_power_kw", "community_pv_power_kw"],
                default=0.0,
            ),
        )

    def _get_community_headroom_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        return self._get_first_value(
            obs,
            obs_map,
            [
                "district__community_building_headroom_kw",
                "district__community_phase_headroom_kw",
                "community_building_headroom_kw",
                "community_phase_headroom_kw",
            ],
            default=float("inf"),
        )

    def _community_surplus_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        export_power = self._get_community_export_power(obs, obs_map)
        import_power = self._get_community_import_power(obs, obs_map)
        has_explicit_community_flow = any(
            name in obs_map
            for name in (
                "district__community_export_power_kw",
                "community_export_power_kw",
                "district__community_import_power_kw",
                "community_import_power_kw",
            )
        )
        if has_explicit_community_flow:
            return max(0.0, export_power - import_power)
        pv_power = self._get_community_pv_power(obs, obs_map)
        return max(0.0, pv_power - import_power)

    def _is_community_stressed(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        headroom = self._get_community_headroom_kw(obs, obs_map)
        if math.isfinite(headroom) and headroom <= self.low_headroom_threshold_kw:
            return True
        return self._get_community_import_power(obs, obs_map) >= self.community_import_threshold_kw

    def _is_community_stressed_or_forecast_stressed(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> bool:
        if self._is_community_stressed(obs, obs_map):
            return True
        headroom = self._forecast_community_headroom_min_kw(obs, obs_map)
        if math.isfinite(headroom) and headroom <= self.low_headroom_threshold_kw:
            return True
        return (
            self._forecast_community_import_peak_kw(obs, obs_map)
            >= self.community_import_threshold_kw
        )

    def _pv_surplus_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        passive_net = self._observed_passive_net_kw(obs, obs_map)
        if passive_net is not None:
            return min(self._get_pv_power(obs, obs_map), max(0.0, -passive_net))
        physical_surplus = max(
            0.0, self._get_pv_power(obs, obs_map) - self._get_load_power(obs, obs_map)
        )
        export_power = self._get_export_power(obs, obs_map)
        import_power = self._get_import_power(obs, obs_map)
        has_explicit_import_export = any(
            name in obs_map
            for name in (
                "export_power_kw",
                "import_power_kw",
            )
        )
        if has_explicit_import_export:
            # When the simulator exposes explicit import/export, trust the
            # measured net flow over passive PV-load for import. For export,
            # only count the part that is also explained by passive PV surplus:
            # export can be caused by a previous storage/V2G discharge and
            # should not be reclassified as fresh solar available to charge.
            if export_power > self.energy_epsilon:
                return (
                    min(export_power, physical_surplus)
                    if physical_surplus > self.energy_epsilon
                    else 0.0
                )
            if import_power > self.energy_epsilon:
                return 0.0
            return physical_surplus
        # Without explicit import/export (no entity_core_electrical bundle) the export of the last
        # interval may come from a storage discharge that overshot the load. Counting it as PV surplus
        # made the battery recharge from the grid in the next step; only PV above the load is surplus.
        return physical_surplus

    def _is_grid_stressed(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        if self._has_low_headroom(obs, obs_map):
            return True
        return self._get_import_power(obs, obs_map) >= self.import_peak_threshold_kw

    def _is_grid_stressed_or_forecast_stressed(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> bool:
        if self._is_grid_stressed(obs, obs_map):
            return True
        headroom = self._forecast_local_headroom_min_kw(obs, obs_map)
        if math.isfinite(headroom) and headroom <= self.low_headroom_threshold_kw:
            return True
        return self._forecast_local_import_peak_kw(obs, obs_map) >= self.import_peak_threshold_kw

    def _has_low_headroom(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        headroom = self._get_headroom_kw(obs, obs_map)
        return bool(math.isfinite(headroom) and headroom <= self.low_headroom_threshold_kw)

    def _has_positive_charge_headroom(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        headroom = self._get_headroom_kw(obs, obs_map)
        return not math.isfinite(headroom) or headroom > self.energy_epsilon

    def _has_useful_local_import(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        if self._get_export_power(obs, obs_map) > self.pv_surplus_threshold_kw:
            return False
        return self._get_import_power(obs, obs_map) > self.storage_discharge_import_threshold_kw

    def _has_useful_community_import(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> bool:
        return self._get_community_import_power(obs, obs_map) > self.community_surplus_threshold_kw

    def _community_energy_is_discounted(self) -> bool:
        return self.community_local_price_ratio < 1.0 - self.energy_epsilon

    def _clip_non_v2g_charge(self, value: float, bounds: Sequence[float]) -> float:
        low, high = bounds
        return float(np.clip(max(value, 0.0), max(0.0, low), max(0.0, high)))

    def _clip_storage_action(
        self,
        value: float,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        bounds: Sequence[float],
    ) -> float:
        if abs(value) <= self.energy_epsilon:
            return float(np.clip(0.0, bounds[0], bounds[1]))

        if value > 0.0:
            can_charge = self._get_first_storage_value(obs, obs_map, "can_charge")
            if not math.isnan(can_charge) and can_charge <= 0.5:
                return float(np.clip(0.0, bounds[0], bounds[1]))

            available = self._get_first_storage_value(
                obs, obs_map, "available_charge_action_normalized"
            )
            if not math.isnan(available):
                value = min(value, max(0.0, available))

        if value < 0.0:
            can_discharge = self._get_first_storage_value(obs, obs_map, "can_discharge")
            if not math.isnan(can_discharge) and can_discharge <= 0.5:
                return float(np.clip(0.0, bounds[0], bounds[1]))

            available = self._get_first_storage_value(
                obs, obs_map, "available_discharge_action_normalized"
            )
            if not math.isnan(available):
                value = -min(abs(value), max(0.0, available))

        return float(np.clip(value, bounds[0], bounds[1]))

    def _storage_power_limited_charge_rate(
        self,
        agent_idx: int,
        available_power_kw: float,
        requested_rate: float,
        *,
        obs: Optional[np.ndarray] = None,
        obs_map: Optional[Mapping[str, int]] = None,
        target_soc: Optional[float] = None,
    ) -> float:
        if requested_rate <= self.energy_epsilon or available_power_kw <= self.energy_epsilon:
            return 0.0
        storage_info = self._get_storage_info(agent_idx)
        if storage_info is None or storage_info.nominal_power <= self.energy_epsilon:
            return requested_rate
        rate = min(requested_rate, max(0.0, available_power_kw) / storage_info.nominal_power)
        if (
            obs is not None
            and obs_map is not None
            and target_soc is not None
            and storage_info.capacity > self.energy_epsilon
        ):
            soc = self._get_storage_soc(obs, obs_map)
            room_kwh = max(0.0, float(target_soc) - soc) * storage_info.capacity
            rate = min(rate, room_kwh / max(self.step_hours * storage_info.nominal_power, 1.0e-6))
        return max(0.0, rate)

    def _storage_power_limited_discharge_rate(
        self,
        agent_idx: int,
        useful_power_kw: float,
        requested_rate: float,
        *,
        obs: Optional[np.ndarray] = None,
        obs_map: Optional[Mapping[str, int]] = None,
        reserve_soc: Optional[float] = None,
    ) -> float:
        if requested_rate <= self.energy_epsilon or useful_power_kw <= self.energy_epsilon:
            return 0.0
        storage_info = self._get_storage_info(agent_idx)
        if storage_info is None or storage_info.nominal_power <= self.energy_epsilon:
            return requested_rate
        rate = min(requested_rate, max(0.0, useful_power_kw) / storage_info.nominal_power)
        if (
            obs is not None
            and obs_map is not None
            and reserve_soc is not None
            and storage_info.capacity > self.energy_epsilon
        ):
            soc = self._get_storage_soc(obs, obs_map)
            usable_kwh = max(0.0, soc - float(reserve_soc)) * storage_info.capacity
            rate = min(rate, usable_kwh / max(self.step_hours * storage_info.nominal_power, 1.0e-6))
        return max(0.0, rate)

    def _ev_power_limited_charge_rate(
        self,
        ctx: Mapping[str, float | bool | None],
        available_power_kw: float,
        requested_rate: float,
        *,
        service_rate: float = 0.0,
        allow_service_import: bool = False,
    ) -> float:
        if requested_rate <= self.energy_epsilon or available_power_kw <= self.energy_epsilon:
            return service_rate if allow_service_import else 0.0
        surplus_rate = max(0.0, available_power_kw) / float(ctx["max_power"])
        limited_rate = min(requested_rate, surplus_rate)
        if allow_service_import:
            limited_rate = max(service_rate, limited_rate)
        return limited_rate

    def _ev_power_limited_discharge_rate(
        self,
        ctx: Mapping[str, float | bool | None],
        useful_power_kw: float,
        requested_rate: float,
    ) -> float:
        if requested_rate <= self.energy_epsilon or useful_power_kw <= self.energy_epsilon:
            return 0.0
        max_discharge_power = float(ctx.get("max_discharge_power") or ctx["max_power"])
        return min(requested_rate, max(0.0, useful_power_kw) / max(max_discharge_power, 1.0e-6))

    def _get_first_storage_value(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        feature: str,
    ) -> float:
        suffix = f"::{feature}"
        for _name, index in self._cached_observation_matches(
            obs_map,
            suffixes=(suffix,),
            prefix="storage::",
        ):
            if index >= len(obs):
                continue
            value = obs[index]
            if not math.isnan(value):
                return float(value)
        return float("nan")

    def _connected_ev_context(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        charger_info: Optional[ChargerInfo],
        action_name: str,
    ) -> Dict[str, float | bool | None]:
        charger_id = self._resolve_ev_charger_id(action_name, charger_info)
        building_name = self._agent_buildings.get(agent_idx)
        state = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="connected_state",
            generic_names=[
                "electric_vehicle_charger_state",
                "electric_vehicle_charger_connected_state",
            ],
            default=0.0,
        )
        current_soc = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="soc",
            generic_names=["electric_vehicle_soc", "connected_electric_vehicle_at_charger_soc"],
            default=0.0,
        )
        required_soc = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="required_soc_departure",
            generic_names=[
                "electric_vehicle_required_soc_departure",
                "connected_electric_vehicle_at_charger_required_soc_departure",
            ],
            default=current_soc,
        )
        fallback_capacity = (
            self.default_capacity
            if charger_info is None
            else charger_info.capacity or self.default_capacity
        )
        capacity = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="battery_capacity",
            generic_names=["connected_electric_vehicle_at_charger_battery_capacity"],
            default=fallback_capacity,
        )
        if abs(current_soc) > 1.5:
            current_soc /= 100.0
        if abs(required_soc) > 1.5:
            required_soc /= 100.0
        hours = self._get_ev_departure_hours(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            default=self.flexibility_hours,
        )
        max_power = 7.4 if charger_info is None else charger_info.max_power or 7.4
        max_discharge_power = (
            max_power
            if charger_info is None
            else charger_info.max_discharge_power or charger_info.max_power or 7.4
        )
        min_power = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="min_charging_power_kw",
            generic_names=[],
            default=0.0 if charger_info is None else charger_info.min_power,
        )
        # Dynamic entity layouts can add or resize chargers after dataset loading.
        for feature, fallback in (
            ("max_charging_power_kw", max_power),
            ("max_discharging_power_kw", max_discharge_power),
        ):
            observed = self._get_ev_value(
                obs,
                obs_map,
                charger_id=charger_id,
                building_name=building_name,
                feature=feature,
                generic_names=[],
                default=float("nan"),
            )
            power = observed if math.isfinite(observed) and observed >= 0.0 else fallback
            if feature == "max_charging_power_kw":
                max_power = power
            else:
                max_discharge_power = power
        can_charge = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="can_charge",
            generic_names=[],
            default=float("nan"),
        )
        can_discharge = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="can_discharge",
            generic_names=[],
            default=float("nan"),
        )
        available_charge_action = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="available_charge_action_normalized",
            generic_names=[],
            default=float("nan"),
        )
        available_charge_power = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="available_charge_power_kw",
            generic_names=[],
            default=float("nan"),
        )
        available_discharge_action = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="available_discharge_action_normalized",
            generic_names=[],
            default=float("nan"),
        )
        min_required_action = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="min_required_action_normalized",
            generic_names=[],
            default=float("nan"),
        )
        departure_feasibility = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="departure_feasibility_ratio",
            generic_names=[],
            default=float("nan"),
        )
        departure_margin = self._get_ev_value(
            obs,
            obs_map,
            charger_id=charger_id,
            building_name=building_name,
            feature="departure_energy_margin_kwh",
            generic_names=[],
            default=float("nan"),
        )
        return {
            "connected": state > 0.0,
            "soc": float(np.clip(current_soc, 0.0, 1.0)),
            "required_soc": float(np.clip(required_soc, 0.0, 1.0)),
            "gap": max(required_soc - current_soc, 0.0),
            "hours_to_departure": max(hours, self.step_hours),
            "max_power": max(max_power, 1.0e-6),
            "min_power": max(0.0, min(min_power, max_power)),
            "max_discharge_power": max(float(max_discharge_power), 1.0e-6),
            "capacity": max(float(capacity), 1.0e-6),
            "charger_id": charger_id,
            "can_charge": can_charge,
            "can_discharge": can_discharge,
            "available_charge_action": available_charge_action,
            "available_charge_power": available_charge_power,
            "available_discharge_action": available_discharge_action,
            "min_required_action": min_required_action,
            "departure_feasibility": departure_feasibility,
            "departure_margin": departure_margin,
        }

    def _ev_service_gap(self, ctx: Mapping[str, float | bool | None]) -> float:
        target_soc = max(float(ctx["required_soc"]), self.ev_service_target_soc)
        return max(target_soc - float(ctx["soc"]), 0.0)

    def _uses_subhour_control_step(self) -> bool:
        return 0.0 < self.step_hours < 1.0 - self.energy_epsilon

    def _subhour_steps_to_hours(self, steps: float) -> float:
        if not self._uses_subhour_control_step():
            return 0.0
        return max(0.0, float(steps)) * max(self.step_hours, 1.0e-6)

    def _effective_ev_deadline_buffer_hours(self) -> float:
        return max(
            self.ev_deadline_buffer_hours,
            self._subhour_steps_to_hours(self.ev_subhour_deadline_buffer_steps),
        )

    def _effective_ev_service_lookahead_hours(self) -> float:
        return max(
            self.ev_service_lookahead_hours,
            self._subhour_steps_to_hours(self.ev_subhour_service_guard_steps),
        )

    def _effective_ev_v2g_min_departure_hours(self) -> float:
        return max(
            self.ev_v2g_min_departure_hours,
            self._subhour_steps_to_hours(self.ev_subhour_v2g_guard_steps),
        )

    def _effective_ev_service_margin_rate(self) -> float:
        if not self._uses_subhour_control_step():
            return self.ev_service_margin_rate
        return max(self.ev_service_margin_rate, self.ev_subhour_min_service_margin_rate)

    def _effective_ev_v2g_reserve_soc(self) -> float:
        if not self._uses_subhour_control_step():
            return self.ev_v2g_reserve_soc
        return max(self.ev_v2g_reserve_soc, self.ev_subhour_v2g_reserve_soc)

    @staticmethod
    def _ctx_float(ctx: Mapping[str, float | bool | None], key: str) -> float:
        value = ctx.get(key)
        if value is None:
            return float("nan")
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return float("nan")
        return parsed if math.isfinite(parsed) else float("nan")

    def _required_ev_charge_rate(
        self, ctx: Mapping[str, float | bool | None], *, margin_rate: float = 0.0
    ) -> float:
        if not ctx.get("connected"):
            return 0.0

        simulator_required = self._ctx_float(ctx, "min_required_action")
        service_gap = self._ev_service_gap(ctx)
        if service_gap <= self.energy_epsilon and (
            math.isnan(simulator_required) or simulator_required <= 0.0
        ):
            return 0.0

        hours = max(
            float(ctx["hours_to_departure"]) - self._effective_ev_deadline_buffer_hours(),
            self.step_hours,
        )
        required_rate = service_gap * float(ctx["capacity"]) / (hours * float(ctx["max_power"]))
        if not math.isnan(simulator_required):
            required_rate = max(required_rate, simulator_required)
        return float(np.clip(required_rate + max(0.0, margin_rate), 0.0, 1.0))

    def _ev_departure_is_infeasible(self, ctx: Mapping[str, float | bool | None]) -> bool:
        departure_margin = self._ctx_float(ctx, "departure_margin")
        if not math.isnan(departure_margin) and departure_margin < -self.energy_epsilon:
            return True

        departure_feasibility = self._ctx_float(ctx, "departure_feasibility")
        # Simulator ratio is required energy divided by maximum deliverable energy.
        # Values <= 1 are feasible; values > 1 indicate the charger cannot hit the target.
        return (
            not math.isnan(departure_feasibility)
            and departure_feasibility > 1.0 + self.energy_epsilon
        )

    def _ev_departure_is_tight(self, ctx: Mapping[str, float | bool | None]) -> bool:
        if self._ev_departure_is_infeasible(ctx):
            return True

        departure_feasibility = self._ctx_float(ctx, "departure_feasibility")
        tight_ratio = 0.95
        if self._uses_subhour_control_step():
            tight_ratio = min(tight_ratio, self.ev_subhour_tight_feasibility_ratio)
        if not math.isnan(departure_feasibility) and departure_feasibility >= tight_ratio:
            return True

        departure_margin = self._ctx_float(ctx, "departure_margin")
        return not math.isnan(departure_margin) and departure_margin <= self.energy_epsilon

    def _ev_can_wait_for_expected_solar(
        self,
        ctx: Mapping[str, float | bool | None],
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> bool:
        # Forecast solar cannot override the same service guard used by the
        # charging branch. Otherwise a large, currently feasible energy gap
        # can be deferred until charger/battery losses make departure infeasible.
        if self._ev_service_is_urgent(ctx):
            return False
        if float(ctx["hours_to_departure"]) <= max(
            self.emergency_hours, self._effective_ev_service_lookahead_hours()
        ):
            return False
        if self._ev_departure_is_tight(ctx):
            return False
        return self._forecast_solar_resource_expected(obs, obs_map)

    def _safe_ev_charge_rate(
        self,
        ctx: Mapping[str, float | bool | None],
        requested_rate: float,
        bounds: Sequence[float],
    ) -> float:
        if not ctx.get("connected"):
            return 0.0

        can_charge = self._ctx_float(ctx, "can_charge")
        if not math.isnan(can_charge) and can_charge <= 0.5:
            return 0.0

        available = self._ctx_float(ctx, "available_charge_action")
        if not math.isnan(available):
            requested_rate = min(requested_rate, max(0.0, available))

        target_soc = max(float(ctx["required_soc"]), self.ev_service_target_soc)
        tolerance = 1.0e-6 if target_soc >= 1.0 else self.ev_service_soc_tolerance
        if float(ctx["soc"]) >= target_soc - tolerance:
            return 0.0
        gap_to_target = max(target_soc - float(ctx["soc"]), 0.0)
        max_target_rate = (
            gap_to_target * float(ctx["capacity"]) / (self.step_hours * float(ctx["max_power"]))
        )
        # A command below the charger minimum does not trickle-charge: it is
        # zero output. Allow the final viable charging interval to cross the
        # requested SOC slightly, rather than permanently stopping below it.
        minimum_rate = float(ctx.get("min_power") or 0.0) / float(ctx["max_power"])
        max_target_rate = max(max_target_rate, minimum_rate)
        if target_soc >= 1.0:
            # BAU requests full charging; the simulator clips accepted energy
            # and tapers charging at the physical battery limit.
            max_target_rate = 1.0
        elif float(ctx.get("hours_to_departure", float("inf"))) <= self.step_hours + 1.0e-9:
            # In the last charging interval, the battery-side SOC gap is not
            # an AC energy cap: charger and battery losses can leave a deficit
            # with no later interval to correct it. Honour the service request
            # (already bounded by power/PV availability), accepting overshoot.
            max_target_rate = 1.0
        simulator_required = self._ctx_float(ctx, "min_required_action")
        if not math.isnan(simulator_required):
            max_target_rate = max(max_target_rate, simulator_required)
        requested_rate = min(requested_rate, max(0.0, max_target_rate))
        if requested_rate + 1.0e-9 < minimum_rate:
            return 0.0

        return self._clip_non_v2g_charge(requested_rate, bounds)

    def _ev_v2g_buffered_context(
        self, ctx: Mapping[str, float | bool | None]
    ) -> Dict[str, float | bool | None]:
        buffered = dict(ctx)
        if (
            self.allow_v2g
            and self.ev_v2g_buffer_soc > self.energy_epsilon
            and float(ctx["hours_to_departure"])
            > (
                self._effective_ev_v2g_min_departure_hours()
                + self._effective_ev_deadline_buffer_hours()
            )
        ):
            target_soc = max(float(ctx["required_soc"]), self.ev_service_target_soc)
            buffered["required_soc"] = min(1.0, target_soc + self.ev_v2g_buffer_soc)
        return buffered

    def _minimum_ev_service_charge_rate(self, ctx: Mapping[str, float | bool | None]) -> float:
        required_rate = self._required_ev_charge_rate(
            ctx, margin_rate=self._effective_ev_service_margin_rate()
        )
        if required_rate <= self.energy_epsilon:
            return 0.0

        hours = float(ctx["hours_to_departure"])
        if self._ev_departure_is_infeasible(ctx):
            return max(required_rate, self.emergency_charge_rate)
        if self._ev_departure_is_tight(ctx):
            return max(required_rate, self.ev_service_floor_rate)
        if hours <= self.emergency_hours or required_rate >= 0.80:
            return max(required_rate, self.emergency_charge_rate)
        if hours <= self._effective_ev_service_lookahead_hours():
            return max(required_rate, self.ev_service_floor_rate)
        return max(required_rate, self.flex_trickle_charge)

    def _ev_service_is_urgent(self, ctx: Mapping[str, float | bool | None]) -> bool:
        if not ctx.get("connected") or self._ev_service_gap(ctx) <= self.energy_epsilon:
            return False

        departure_margin = self._ctx_float(ctx, "departure_margin")
        if not math.isnan(departure_margin) and departure_margin < 0.0:
            return True

        if self._ev_departure_is_infeasible(ctx) or self._ev_departure_is_tight(ctx):
            return True

        hours = float(ctx["hours_to_departure"])
        if hours <= self._effective_ev_service_lookahead_hours():
            return True

        required_rate = self._required_ev_charge_rate(ctx, margin_rate=0.0)
        return required_rate >= max(self.ev_service_floor_rate, 0.25)

    def _safe_ev_v2g_rate(
        self,
        ctx: Mapping[str, float | bool | None],
        *,
        requested_rate: Optional[float] = None,
    ) -> float:
        if not ctx.get("connected"):
            return 0.0
        can_discharge = self._ctx_float(ctx, "can_discharge")
        if not math.isnan(can_discharge) and can_discharge <= 0.5:
            return 0.0

        hours = float(ctx["hours_to_departure"])
        if hours <= self._effective_ev_v2g_min_departure_hours():
            return 0.0
        if self._ev_departure_is_tight(ctx):
            return 0.0

        target_soc = max(float(ctx["required_soc"]), self.ev_service_target_soc)
        reserve_floor = (
            target_soc + self._effective_ev_v2g_reserve_soc() + self.ev_v2g_service_margin_soc
        )
        available_soc = float(ctx["soc"]) - reserve_floor
        if available_soc <= self.energy_epsilon:
            return 0.0

        max_discharge_power = float(ctx.get("max_discharge_power") or ctx["max_power"])
        available_rate = (
            available_soc * float(ctx["capacity"]) / (self.step_hours * max_discharge_power)
        )
        simulator_available = self._ctx_float(ctx, "available_discharge_action")
        if not math.isnan(simulator_available):
            available_rate = min(available_rate, max(0.0, simulator_available))
        desired_rate = self.ev_v2g_discharge_rate if requested_rate is None else requested_rate
        return float(np.clip(min(max(0.0, desired_rate), available_rate), 0.0, 1.0))

    def _deferrable_is_startable(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        prefix: str,
    ) -> bool:
        pending = self._get_deferrable_value(obs, obs_map, prefix, "pending", default=0.0)
        running = self._get_deferrable_value(obs, obs_map, prefix, "running", default=0.0)
        can_start = self._get_deferrable_value(obs, obs_map, prefix, "can_start", default=0.0)
        deadline_missed = self._get_deferrable_value(
            obs, obs_map, prefix, "deadline_missed", default=0.0
        )
        return pending > 0.5 and running <= 0.5 and can_start > 0.5 and deadline_missed <= 0.5

    def _deferrable_must_start_now(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
        prefix: str,
    ) -> bool:
        must_start_now = self._get_deferrable_value(
            obs, obs_map, prefix, "must_start_now", default=0.0
        )
        if must_start_now > 0.5:
            return True

        slack_steps = self._get_deferrable_value(
            obs, obs_map, prefix, "slack_steps", default=float("nan")
        )
        if not math.isnan(slack_steps) and slack_steps >= 0.0:
            return slack_steps <= self.deferrable_safety_margin_steps

        hours_until_latest = self._get_deferrable_value(
            obs,
            obs_map,
            prefix,
            "hours_until_latest_start",
            default=float("nan"),
        )
        if not math.isnan(hours_until_latest) and hours_until_latest >= 0.0:
            return hours_until_latest <= self.deferrable_safety_margin_steps * self.step_hours

        hours_until_deadline = self._get_deferrable_value(
            obs,
            obs_map,
            prefix,
            "hours_until_deadline",
            default=float("nan"),
        )
        remaining_steps = self._get_deferrable_value(
            obs,
            obs_map,
            prefix,
            "remaining_duration_steps",
            default=float("nan"),
        )
        if math.isnan(remaining_steps) or remaining_steps <= 0.0:
            remaining_steps = self._get_deferrable_value(
                obs,
                obs_map,
                prefix,
                "cycle_duration_steps",
                default=float("nan"),
            )
        if (
            not math.isnan(hours_until_deadline)
            and hours_until_deadline >= 0.0
            and not math.isnan(remaining_steps)
            and remaining_steps > 0.0
        ):
            required_hours = (
                remaining_steps + self.deferrable_safety_margin_steps
            ) * self.step_hours
            return hours_until_deadline <= required_hours

        return False

    def _deferrable_start_value(self, bounds: Sequence[float]) -> float:
        return float(np.clip(self.deferrable_start_action, bounds[0], bounds[1]))

    def _deferrable_grid_import_is_blocking(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> bool:
        threshold = self.deferrable_import_block_threshold_kw
        if not math.isfinite(threshold):
            return False
        return self._get_import_power(obs, obs_map) >= threshold

    def _deferrable_community_import_is_blocking(
        self, obs: np.ndarray, obs_map: Mapping[str, int]
    ) -> bool:
        local_threshold = self.deferrable_import_block_threshold_kw
        community_threshold = self.deferrable_community_import_block_threshold_kw
        local_block = (
            math.isfinite(local_threshold)
            and self._get_import_power(obs, obs_map) >= local_threshold
        )
        community_block = (
            math.isfinite(community_threshold)
            and self._get_community_import_power(obs, obs_map) >= community_threshold
        )
        return local_block or community_block

    def _agent_has_ev_service_demand(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> bool:
        """Return whether an EV on this agent needs energy now or soon.

        Storage actions are simultaneous with EV charging actions, so this is a
        local-demand signal rather than a guarantee that the battery will serve
        the EV in the simulator dispatch. It still prevents a baseline from
        leaving charged storage idle while the same building imports for EV
        service.
        """
        if agent_idx >= len(self._action_labels):
            return False

        for action_position, action_name in enumerate(self._action_labels[agent_idx]):
            if "electric_vehicle" not in str(action_name):
                continue
            charger_info = self._get_charger_info(agent_idx, action_position)
            ctx = self._connected_ev_context(
                agent_idx,
                obs,
                obs_map,
                charger_info,
                str(action_name),
            )
            if not ctx.get("connected"):
                continue
            if self._ev_can_wait_for_expected_solar(ctx, obs, obs_map):
                continue
            if self._minimum_ev_service_charge_rate(ctx) > self.energy_epsilon:
                return True
            if self._ev_service_gap(ctx) > self.energy_epsilon and (
                float(ctx["hours_to_departure"]) <= self.ev_service_lookahead_hours
                or self._ev_departure_is_infeasible(ctx)
            ):
                return True
        return False

    def _agent_has_deferrable_demand(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> bool:
        """Return whether this agent has an urgent deferrable load."""
        if agent_idx >= len(self._action_labels):
            return False

        for action_name in self._action_labels[agent_idx]:
            if "deferrable" not in str(action_name):
                continue
            prefix = self._resolve_deferrable_observation_prefix(str(action_name), obs_map)
            if prefix is None or not self._deferrable_is_startable(obs, obs_map, prefix):
                continue
            urgency = self._get_deferrable_value(obs, obs_map, prefix, "urgency_ratio", default=0.0)
            slack = self._get_deferrable_value(obs, obs_map, prefix, "slack_ratio", default=1.0)
            if (
                self._deferrable_must_start_now(obs, obs_map, prefix)
                or urgency >= self.deferrable_urgency_threshold
                or slack <= self.deferrable_slack_threshold
            ):
                return True
        return False


class NormalPolicy(_OperationalBaselinePolicy):
    """Day-to-day behaviour: immediate EV charge, earliest deferrable start, simple self-consumption BESS."""

    def __init__(self, config: Dict[str, Any]) -> None:
        config = dict(config)
        algorithm = dict(config.get("algorithm") or {})
        hyper = dict(algorithm.get("hyperparameters") or {})
        for key, default in NORMAL_DEFAULTS.items():
            hyper.setdefault(key, default)
        algorithm["hyperparameters"] = hyper
        config["algorithm"] = algorithm
        super().__init__(config)

    def _policy_type(self) -> str:
        return "normal_policy"

    def _compute_ev_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        charger_info: Optional[ChargerInfo],
        bounds: Sequence[float],
        action_name: str = "",
    ) -> float:
        ctx = self._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        target_soc = max(
            float(ctx["required_soc"]), float(np.clip(self.ev_normal_target_soc, 0.0, 1.0))
        )
        gap = max(target_soc - float(ctx["soc"]), 0.0)
        if not ctx["connected"] or gap <= 1.0e-6:
            return 0.0
        can_charge = self._ctx_float(ctx, "can_charge")
        if not math.isnan(can_charge) and can_charge <= 0.5:
            return 0.0
        # BAU requests maximum charging until full. The observation's available
        # action also includes a lossless SOC-gap estimate; using it here would
        # taper the command prematurely. Equipment physics clips accepted energy.
        return self._clip_non_v2g_charge(self.ev_normal_charge_rate, bounds)

    def _apply_ev_dynamic_headroom_limit(
        self, value, obs, obs_map, charger_info, bounds, agent_idx=None, residual_headroom=None
    ) -> float:
        # Submit simultaneous requests to the Simulator's proportional service
        # allocator. Sequential policy-side reservations would privilege the
        # first charger and prevent that allocator from sharing fairly.
        return value

    def _connected_ev_context(self, agent_idx, obs, obs_map, charger_info, action_name):
        ctx = super()._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        accepted_kw = self._ctx_float(ctx, "available_charge_power")
        if not math.isfinite(accepted_kw):
            # CityLearn: available_charge_power_kw is published only with the
            # entity_core_electrical bundle. Without it, estimate the power the
            # EV can accept from the observed SOC, battery capacity, charger
            # power and charger efficiency, as the Simulator computes that
            # observation. The estimate omits the service import limit, the
            # efficiency curve and capacity fade, which are not observable
            # without the bundle; the observation stops at the degraded capacity.
            efficiency = self._get_ev_value(
                obs,
                obs_map,
                charger_id=ctx["charger_id"],
                building_name=self._agent_buildings.get(agent_idx),
                feature="charger_efficiency_ratio",
                generic_names=[],
                default=1.0 if charger_info is None else charger_info.efficiency,
            )
            energy_to_full = max(1.0 - float(ctx["soc"]), 0.0) * float(ctx["capacity"])
            accepted_kw = min(
                float(ctx["max_power"]),
                energy_to_full / max(efficiency * self.step_hours, 1.0e-6),
            )
        ctx["accepted_charge_power"] = accepted_kw
        return ctx

    def _record_ev_charge_dispatch(self, agent_idx, ctx, rate) -> None:
        # Keep the EV command at maximum, but reserve only the power it can
        # accept. Near full SOC, nominal charger power would make the BESS
        # discharge against fictitious local demand. The observation or its
        # estimate is not exact; final accepted energy remains the Simulator's
        # decision.
        # Storage and deferrable dispatch reuse this method without the key.
        accepted_kw = self._ctx_float(ctx, "accepted_charge_power")
        if math.isfinite(accepted_kw):
            rate = min(rate, max(0.0, accepted_kw) / float(ctx["max_power"]))
        super()._record_ev_charge_dispatch(agent_idx, ctx, rate)

    def _compute_deferrable_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        del agent_idx
        prefix = self._resolve_deferrable_observation_prefix(action_name, obs_map)
        if prefix is None:
            return 0.0
        pending = self._get_deferrable_value(obs, obs_map, prefix, "pending", default=0.0)
        running = self._get_deferrable_value(obs, obs_map, prefix, "running", default=0.0)
        can_start = self._get_deferrable_value(obs, obs_map, prefix, "can_start", default=0.0)
        deadline_missed = self._get_deferrable_value(
            obs, obs_map, prefix, "deadline_missed", default=0.0
        )
        if pending > 0.5 and running <= 0.5 and can_start > 0.5 and deadline_missed <= 0.5:
            return float(np.clip(self.deferrable_start_action, bounds[0], bounds[1]))
        return 0.0

    def _compute_storage_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        del action_name
        soc = self._get_storage_soc(obs, obs_map)
        min_soc, max_soc = self._storage_strategy_limits(obs, obs_map)
        surplus = self._budget_value(
            agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map)
        )
        import_power = self._budget_value(
            agent_idx, "local_import_kw", self._get_import_power(obs, obs_map)
        )
        low, high = bounds

        if surplus > self.pv_surplus_threshold_kw and soc < max_soc:
            charge_rate = self._storage_power_limited_charge_rate(
                agent_idx,
                surplus,
                self.storage_charge_rate,
                obs=obs,
                obs_map=obs_map,
                target_soc=max_soc,
            )
            return self._clip_storage_action(charge_rate, obs, obs_map, bounds)
        if import_power > self.normal_storage_discharge_import_threshold_kw and soc > min_soc:
            discharge_rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.storage_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=min_soc,
            )
            return self._clip_storage_action(-discharge_rate, obs, obs_map, bounds)
        return float(np.clip(0.0, low, high))


class NormalTargetPolicy(NormalPolicy):
    """Immediate BAU charging capped by the connected EV's requested departure SOC.

    The last command is bounded by the remaining stored-energy gap, without
    assuming unobserved charger/battery efficiencies. If that command is below
    the charger minimum, the last step charges at the minimum power and crosses
    the target slightly, as the rule-based baselines do, rather than leaving
    the EV below it. Charging stops ``EV_CHARGE_STOP_SOC_TOLERANCE`` below the
    target, inside the KPI service tolerance.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        config = dict(config)
        algorithm = dict(config.get("algorithm") or {})
        hyper = dict(algorithm.get("hyperparameters") or {})
        if hyper.get("ev_normal_target_soc", 0.0) != 0.0:
            raise ValueError(
                "NormalTargetPolicy follows the user target; ev_normal_target_soc must be 0"
            )
        hyper["ev_normal_target_soc"] = 0.0
        algorithm["hyperparameters"] = hyper
        config["algorithm"] = algorithm
        super().__init__(config)

    def _policy_type(self) -> str:
        return "normal_target_policy"

    def _compute_ev_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        charger_info: Optional[ChargerInfo],
        bounds: Sequence[float],
        action_name: str = "",
    ) -> float:
        ctx = self._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        if not ctx["connected"]:
            return 0.0
        # A guessed capacity or SOC cannot support a strict user-selected cap.
        for feature, generic_names in (
            ("soc", ["electric_vehicle_soc", "connected_electric_vehicle_at_charger_soc"]),
            (
                "required_soc_departure",
                [
                    "electric_vehicle_required_soc_departure",
                    "connected_electric_vehicle_at_charger_required_soc_departure",
                ],
            ),
            ("battery_capacity", ["connected_electric_vehicle_at_charger_battery_capacity"]),
        ):
            value = self._get_ev_value(
                obs,
                obs_map,
                charger_id=ctx["charger_id"],
                building_name=self._agent_buildings.get(agent_idx),
                feature=feature,
                generic_names=generic_names,
                default=float("nan"),
            )
            if not math.isfinite(value) or (feature == "battery_capacity" and value <= 0.0):
                return 0.0
        can_charge = self._ctx_float(ctx, "can_charge")
        if math.isfinite(can_charge) and can_charge <= 0.5:
            return 0.0
        # Float32 observations/actions need a tiny SOC margin at the cap.
        gap = max(0.0, float(ctx["required_soc"]) - float(ctx["soc"]) - 1.0e-6)
        if gap <= EV_CHARGE_STOP_SOC_TOLERANCE:
            return 0.0
        energy_cap_rate = gap * float(ctx["capacity"]) / (self.step_hours * float(ctx["max_power"]))
        rate = min(self.ev_normal_charge_rate, energy_cap_rate, 1.0)
        minimum_rate = float(ctx["min_power"]) / float(ctx["max_power"])
        # A command below the charger minimum is zero output, so the EV would
        # leave below its target. Charge the last step at the minimum instead.
        rate = max(rate, minimum_rate)
        if rate <= 0.0:
            return 0.0
        clipped = self._clip_non_v2g_charge(rate, bounds)
        return clipped if clipped >= minimum_rate and clipped > 0.0 else 0.0


class RBCBasicPolicy(_OperationalBaselinePolicy):
    """Current-price/service scheduling with reactive battery self-consumption."""

    def __init__(self, config: Dict[str, Any]) -> None:
        # Smart/Community inherit helpers, but retain their own audited defaults.
        if type(self) is RBCBasicPolicy:
            config = dict(config)
            algorithm = dict(config.get("algorithm") or {})
            hyper = dict(algorithm.get("hyperparameters") or {})
            for key, value in policy_defaults("RBCBasicPolicy", hyper).items():
                hyper.setdefault(key, value)
            algorithm["hyperparameters"] = hyper
            config["algorithm"] = algorithm
        super().__init__(config)
        hyper = config.get("algorithm", {}).get("hyperparameters") or {}
        self.basic_storage_policy = hyper.get("basic_storage_policy", "price_only")
        if self.basic_storage_policy not in {"price_only", "self_consumption"}:
            raise ValueError("basic_storage_policy must be price_only or self_consumption")
        self.basic_price_policy = hyper.get(
            "basic_price_policy", BASIC_PRICE_DEFAULTS["basic_price_policy"]
        )
        self.basic_cheap_price_eur_kwh = float(
            hyper.get(
                "basic_cheap_price_eur_kwh", BASIC_PRICE_DEFAULTS["basic_cheap_price_eur_kwh"]
            )
        )
        self.basic_expensive_price_eur_kwh = float(
            hyper.get(
                "basic_expensive_price_eur_kwh",
                BASIC_PRICE_DEFAULTS["basic_expensive_price_eur_kwh"],
            )
        )
        if self.basic_price_policy not in {"fixed_thresholds", "forecast_relative"}:
            raise ValueError("basic_price_policy must be fixed_thresholds or forecast_relative")
        if not (
            math.isfinite(self.basic_cheap_price_eur_kwh)
            and math.isfinite(self.basic_expensive_price_eur_kwh)
            and 0 <= self.basic_cheap_price_eur_kwh < self.basic_expensive_price_eur_kwh
        ):
            raise ValueError("Basic price thresholds must be finite and 0 <= cheap < expensive")

    def _get_price_context(self, obs, obs_map):
        # Historical executable bundles have no mode field. Preserve their
        # forecast-relative decisions when loaded without calling __init__.
        if getattr(self, "basic_price_policy", "forecast_relative") == "forecast_relative":
            return super()._get_price_context(obs, obs_map)
        price = self._get_first_value(
            obs,
            obs_map,
            ["electricity_pricing", "district__electricity_pricing"],
            default=float("nan"),
        )
        available = math.isfinite(price)
        return {
            "price": price if available else 0.0,
            "cheap": available and price <= self.basic_cheap_price_eur_kwh,
            "expensive": available and price >= self.basic_expensive_price_eur_kwh,
            "near_forecast_peak": False,
        }

    def _policy_type(self) -> str:
        return "rbc_basic_policy"

    def _compute_ev_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        charger_info: Optional[ChargerInfo],
        bounds: Sequence[float],
        action_name: str = "",
    ) -> float:
        ctx = self._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        if not ctx["connected"]:
            return 0.0

        service_rate = self._minimum_ev_service_charge_rate(ctx)
        if service_rate <= self.energy_epsilon and self._ev_service_gap(ctx) <= self.energy_epsilon:
            return 0.0
        price_ctx = self._get_price_context(obs, obs_map)

        if bool(price_ctx["cheap"]):
            return self._safe_ev_charge_rate(
                ctx, max(service_rate, self.ev_price_charge_rate), bounds
            )
        return self._safe_ev_charge_rate(ctx, service_rate, bounds)

    def _compute_deferrable_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        del agent_idx
        prefix = self._resolve_deferrable_observation_prefix(action_name, obs_map)
        if prefix is None:
            return 0.0
        if not self._deferrable_is_startable(obs, obs_map, prefix):
            return 0.0

        urgency = self._get_deferrable_value(obs, obs_map, prefix, "urgency_ratio", default=0.0)
        slack = self._get_deferrable_value(obs, obs_map, prefix, "slack_ratio", default=1.0)
        price_ctx = self._get_price_context(obs, obs_map)
        if (
            self._deferrable_must_start_now(obs, obs_map, prefix)
            or urgency >= self.deferrable_urgency_threshold
            or slack <= self.deferrable_slack_threshold
            or bool(price_ctx["cheap"])
        ):
            return self._deferrable_start_value(bounds)
        return 0.0

    def _compute_storage_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        if getattr(self, "basic_storage_policy", "price_only") == "self_consumption":
            return NormalPolicy._compute_storage_action(
                self, agent_idx, obs, obs_map, action_name, bounds
            )
        del action_name
        soc = self._get_storage_soc(obs, obs_map)
        min_soc, max_soc = self._storage_strategy_limits(obs, obs_map)
        price_ctx = self._get_price_context(obs, obs_map)
        low, high = bounds
        if bool(price_ctx["cheap"]) and soc < min(max_soc, self.storage_price_charge_soc_ceiling):
            rate = self._storage_power_limited_charge_rate(
                agent_idx,
                float("inf"),
                self.price_charge_rate,
                obs=obs,
                obs_map=obs_map,
                target_soc=min(max_soc, self.storage_price_charge_soc_ceiling),
            )
            return self._clip_storage_action(rate, obs, obs_map, bounds)
        if bool(price_ctx["expensive"]) and soc > max(
            min_soc, self.storage_price_discharge_soc_floor
        ):
            import_power = self._budget_value(
                agent_idx, "local_import_kw", self._get_import_power(obs, obs_map)
            )
            rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.price_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_price_discharge_soc_floor),
            )
            return self._clip_storage_action(-rate, obs, obs_map, bounds)
        return float(np.clip(0.0, low, high))


class RBCSmartPolicy(RBCBasicPolicy):
    """Solar, price and peak-aware heuristic with conservative optional V2G."""

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        hyper = config.get("algorithm", {}).get("hyperparameters") or {}
        if "price_charge_rate" not in hyper:
            self.price_charge_rate = SMART_DEFAULTS["price_charge_rate"]

    def _policy_type(self) -> str:
        return "rbc_smart_policy"

    def _get_price_context(self, obs, obs_map):
        # Smart, Community and historical teachers keep the audited forecast
        # classifier. Basic's simpler tariff must not alter their inheritance.
        return _OperationalBaselinePolicy._get_price_context(self, obs, obs_map)

    def _compute_ev_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        charger_info: Optional[ChargerInfo],
        bounds: Sequence[float],
        action_name: str = "",
    ) -> float:
        ctx = self._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        if not ctx["connected"]:
            return 0.0
        service_gap = self._ev_service_gap(ctx)
        service_rate = self._minimum_ev_service_charge_rate(ctx)
        urgent_service = self._ev_service_is_urgent(ctx)
        wait_for_solar = self._ev_can_wait_for_expected_solar(ctx, obs, obs_map)
        price_ctx = self._get_price_context(obs, obs_map)
        surplus = self._budget_value(
            agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map)
        )
        forecast_surplus = self._forecast_local_surplus_kw(obs, obs_map)
        stressed = self._is_grid_stressed(obs, obs_map)
        stressed_or_forecast = self._is_grid_stressed_or_forecast_stressed(obs, obs_map)
        low, high = bounds
        safe_v2g_rate = self._safe_ev_v2g_rate(ctx)
        useful_local_import = self._has_useful_local_import(obs, obs_map)
        import_power = self._budget_value(
            agent_idx, "local_import_kw", self._get_import_power(obs, obs_map)
        )

        if (
            self.allow_v2g
            and low < 0.0
            and safe_v2g_rate > self.energy_epsilon
            and useful_local_import
            and (bool(price_ctx["expensive"]) or stressed_or_forecast)
            and surplus <= self.pv_surplus_threshold_kw
        ):
            v2g_rate = self._ev_power_limited_discharge_rate(ctx, import_power, safe_v2g_rate)
            if v2g_rate > self.energy_epsilon:
                return float(np.clip(-v2g_rate, low, high))

        if service_gap <= self.energy_epsilon and service_rate <= self.energy_epsilon:
            return 0.0
        if surplus > self.pv_surplus_threshold_kw and not stressed:
            buffered_ctx = self._ev_v2g_buffered_context(ctx)
            charge_rate = self._ev_power_limited_charge_rate(
                buffered_ctx,
                surplus,
                max(service_rate, 1.0),
                service_rate=service_rate,
                allow_service_import=urgent_service,
            )
            action = self._safe_ev_charge_rate(buffered_ctx, charge_rate, bounds)
            return action
        if wait_for_solar or not urgent_service:
            return 0.0
        if (
            bool(price_ctx["cheap"])
            and not stressed_or_forecast
            and surplus <= self.pv_surplus_threshold_kw
            and forecast_surplus <= self.pv_surplus_threshold_kw
        ):
            action = self._safe_ev_charge_rate(
                ctx, max(service_rate, self.ev_price_charge_rate), bounds
            )
            return action
        action = self._safe_ev_charge_rate(ctx, service_rate, bounds)
        return action

    def _compute_deferrable_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        prefix = self._resolve_deferrable_observation_prefix(action_name, obs_map)
        if prefix is None:
            return 0.0
        if not self._deferrable_is_startable(obs, obs_map, prefix):
            return 0.0

        urgency = self._get_deferrable_value(obs, obs_map, prefix, "urgency_ratio", default=0.0)
        slack = self._get_deferrable_value(obs, obs_map, prefix, "slack_ratio", default=1.0)
        surplus = self._budget_value(
            agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map)
        )
        stressed_or_forecast = self._is_grid_stressed_or_forecast_stressed(obs, obs_map)
        import_blocking = self._deferrable_grid_import_is_blocking(obs, obs_map)

        should_start = (
            self._deferrable_must_start_now(obs, obs_map, prefix)
            or (
                not import_blocking
                and (
                    urgency >= self.deferrable_urgency_threshold
                    or slack <= self.deferrable_slack_threshold
                )
            )
            or (surplus > self.pv_surplus_threshold_kw and not stressed_or_forecast)
        )
        if should_start:
            return self._deferrable_start_value(bounds)
        return 0.0

    def _compute_storage_action(
        self,
        agent_idx: int,
        obs: np.ndarray,
        obs_map: Dict[str, int],
        action_name: str,
        bounds: Sequence[float],
    ) -> float:
        del action_name
        soc = self._get_storage_soc(obs, obs_map)
        min_soc, max_soc = self._storage_strategy_limits(obs, obs_map)
        surplus = self._budget_value(
            agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map)
        )
        forecast_surplus = self._forecast_local_surplus_kw(obs, obs_map)
        price_ctx = self._get_price_context(obs, obs_map)
        import_power = self._budget_value(
            agent_idx, "local_import_kw", self._get_import_power(obs, obs_map)
        )
        has_ev_service_demand = self._agent_has_ev_service_demand(agent_idx, obs, obs_map)
        has_deferrable_demand = self._agent_has_deferrable_demand(agent_idx, obs, obs_map)
        low_headroom = self._has_low_headroom(obs, obs_map)
        stressed = low_headroom or import_power >= self.import_peak_threshold_kw
        stressed_or_forecast = self._is_grid_stressed_or_forecast_stressed(obs, obs_map)
        forecast_headroom = self._forecast_local_headroom_min_kw(obs, obs_map)
        forecast_stressed = (
            math.isfinite(forecast_headroom) and forecast_headroom <= self.low_headroom_threshold_kw
        ) or self._forecast_local_import_peak_kw(obs, obs_map) >= self.import_peak_threshold_kw
        low, high = bounds
        price_charge_ceiling = min(max_soc, self.storage_price_charge_soc_ceiling)
        local_surplus_now = surplus > self.pv_surplus_threshold_kw
        local_surplus_expected = forecast_surplus > self.pv_surplus_threshold_kw
        price_charge_allowed = (
            self.price_charge_rate > 0.0
            and soc < price_charge_ceiling
            and bool(price_ctx["cheap"])
            and not stressed
            and not stressed_or_forecast
            and not local_surplus_now
            and not local_surplus_expected
        )

        if soc < max_soc and local_surplus_now and self.pv_charge_rate > 0.0:
            charge_rate = self._storage_power_limited_charge_rate(
                agent_idx,
                surplus,
                1.0,
                obs=obs,
                obs_map=obs_map,
                target_soc=max_soc,
            )
            return self._clip_storage_action(charge_rate, obs, obs_map, bounds)
        if (
            (
                import_power > self.storage_discharge_import_threshold_kw
                or (
                    (has_ev_service_demand or has_deferrable_demand)
                    and import_power > self.energy_epsilon
                )
            )
            and not local_surplus_now
            and soc > max(min_soc, self.storage_price_discharge_soc_floor)
        ):
            discharge_rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.storage_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_price_discharge_soc_floor),
            )
            return self._clip_storage_action(-discharge_rate, obs, obs_map, bounds)
        if (
            forecast_stressed
            and not bool(price_ctx["cheap"])
            and import_power > self.storage_discharge_import_threshold_kw
            and not local_surplus_now
            and soc > max(min_soc, self.storage_peak_discharge_soc_floor)
        ):
            discharge_rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.peak_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_peak_discharge_soc_floor),
            )
            return self._clip_storage_action(-discharge_rate, obs, obs_map, bounds)
        if (
            bool(price_ctx["expensive"])
            and import_power > self.storage_discharge_import_threshold_kw
            and (stressed or import_power >= self.import_peak_threshold_kw)
            and not local_surplus_now
            and soc > max(min_soc, self.storage_peak_discharge_soc_floor)
        ):
            discharge_rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.peak_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_peak_discharge_soc_floor),
            )
            return self._clip_storage_action(-discharge_rate, obs, obs_map, bounds)
        if (
            bool(price_ctx["expensive"])
            and import_power > self.storage_discharge_import_threshold_kw
            and not local_surplus_now
            and soc > max(min_soc, self.storage_price_discharge_soc_floor)
        ):
            discharge_rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                import_power,
                self.price_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_price_discharge_soc_floor),
            )
            return self._clip_storage_action(-discharge_rate, obs, obs_map, bounds)
        if price_charge_allowed:
            return self._clip_storage_action(self.price_charge_rate, obs, obs_map, bounds)
        return float(np.clip(0.0, low, high))


class _EconomicSmartPolicy(RBCSmartPolicy):
    """Basic service/price decisions plus solar capture and current peak relief.

    Forecasts never replace the service schedule. In particular a cheap period
    is still usable before the departure becomes urgent. Stored energy is not
    discharged against cheap imports immediately before a price-driven recharge.
    """

    economic_dispatch = True

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        hyper = config.get("algorithm", {}).get("hyperparameters") or {}
        if self.economic_dispatch and "price_charge_rate" not in hyper:
            self.price_charge_rate = ECONOMIC_SMART_DEFAULTS["price_charge_rate"]

    def _usable_surplus_kw(self, agent_idx, obs, obs_map):
        return self._budget_value(agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map))

    def _expected_surplus_kw(self, obs, obs_map):
        return self._forecast_local_surplus_kw(obs, obs_map)

    def _compute_ev_action(self, agent_idx, obs, obs_map, charger_info, bounds, action_name=""):
        if not self.economic_dispatch:
            return RBCSmartPolicy._compute_ev_action(
                self, agent_idx, obs, obs_map, charger_info, bounds, action_name
            )
        ctx = self._connected_ev_context(agent_idx, obs, obs_map, charger_info, action_name)
        if not ctx["connected"]:
            return 0.0
        # Preserve the optional conservative V2G path; its reserve/service
        # guards remain common to the legacy teacher and the operational RBCs.
        if self.allow_v2g:
            legacy = RBCSmartPolicy._compute_ev_action(
                self, agent_idx, obs, obs_map, charger_info, bounds, action_name
            )
            if legacy < 0.0:
                return legacy
        service_rate = self._minimum_ev_service_charge_rate(ctx)
        surplus = self._usable_surplus_kw(agent_idx, obs, obs_map)
        if surplus > self.pv_surplus_threshold_kw:
            rate = self._ev_power_limited_charge_rate(
                ctx,
                surplus,
                1.0,
                service_rate=service_rate,
                allow_service_import=self._ev_service_is_urgent(ctx),
            )
            solar_action = self._safe_ev_charge_rate(ctx, rate, bounds)
            if solar_action > self.energy_epsilon:
                return solar_action
        return RBCBasicPolicy._compute_ev_action(
            self, agent_idx, obs, obs_map, charger_info, bounds, action_name
        )

    def _compute_deferrable_action(self, agent_idx, obs, obs_map, action_name, bounds):
        if not self.economic_dispatch:
            return RBCSmartPolicy._compute_deferrable_action(
                self, agent_idx, obs, obs_map, action_name, bounds
            )
        basic = RBCBasicPolicy._compute_deferrable_action(
            self, agent_idx, obs, obs_map, action_name, bounds
        )
        if basic > 0.0:
            return basic
        prefix = self._resolve_deferrable_observation_prefix(action_name, obs_map)
        if prefix is None or not self._deferrable_is_startable(obs, obs_map, prefix):
            return 0.0
        if self._usable_surplus_kw(
            agent_idx, obs, obs_map
        ) > self.pv_surplus_threshold_kw and not self._is_grid_stressed(obs, obs_map):
            return self._deferrable_start_value(bounds)
        return 0.0

    def _pv_expected_without_surplus_forecast(self, obs, obs_map) -> bool:
        """Whether PV is forecast for a building with PV while no PV-surplus forecast is observed.

        The cheap-price grid charge waits while a local PV surplus is forecast. That forecast comes from
        ``forecast_pv_surplus_mean``, ``forecast_export`` or ``forecast_net`` observations; CityLearn
        publishes ``forecast_net_next_*_kw`` only with the ``entity_forecasts_derived`` bundle. Without
        them the expected surplus read as zero, so the battery charged from the grid before sunrise and
        then exported the PV it could no longer store (#400). The solar resource forecast (PV or
        irradiance) then stands in for the missing surplus forecast.
        """
        if any(
            self._forecast_values(obs, obs_map, [token], exclude_tokens=["community"])
            for token in ("forecast_pv_surplus_mean", "forecast_export", "forecast_net")
        ):
            return False
        if self._get_value(obs, obs_map, "active_pvs_count", default=1.0) <= 0.0:
            return False
        return self._forecast_solar_resource_expected(obs, obs_map)

    def _storage_demand(self, agent_idx, obs, obs_map):
        local = self._budget_value(
            agent_idx, "local_import_kw", self._get_import_power(obs, obs_map)
        )
        return local, self._has_low_headroom(obs, obs_map) or local >= self.import_peak_threshold_kw

    def _compute_storage_action(self, agent_idx, obs, obs_map, action_name, bounds):
        if not self.economic_dispatch:
            return RBCSmartPolicy._compute_storage_action(
                self, agent_idx, obs, obs_map, action_name, bounds
            )
        del action_name
        soc = self._get_storage_soc(obs, obs_map)
        min_soc, max_soc = self._storage_strategy_limits(obs, obs_map)
        local_surplus = self._budget_value(
            agent_idx, "local_surplus_kw", self._pv_surplus_kw(obs, obs_map)
        )
        surplus = self._usable_surplus_kw(agent_idx, obs, obs_map)
        expected = self._expected_surplus_kw(obs, obs_map)
        price = self._get_price_context(obs, obs_map)
        demand, peak = self._storage_demand(agent_idx, obs, obs_map)
        ceiling = (
            max_soc
            if local_surplus > self.pv_surplus_threshold_kw
            else min(max_soc, self.community_surplus_charge_soc_ceiling)
        )
        if surplus > self.pv_surplus_threshold_kw:
            if soc < ceiling:
                rate = self._storage_power_limited_charge_rate(
                    agent_idx, surplus, 1.0, obs=obs, obs_map=obs_map, target_soc=ceiling
                )
                return self._clip_storage_action(rate, obs, obs_map, bounds)
            return 0.0
        # Current peaks take priority; a forecast peak alone is a reason to
        # retain energy, not to discharge it early into a small present load.
        if (
            peak
            or bool(price["expensive"])
            or (not price["cheap"] and expected > self.pv_surplus_threshold_kw)
        ):
            rate = self._storage_power_limited_discharge_rate(
                agent_idx,
                demand,
                self.peak_discharge_rate if peak else self.price_discharge_rate,
                obs=obs,
                obs_map=obs_map,
                reserve_soc=max(min_soc, self.storage_price_discharge_soc_floor),
            )
            return self._clip_storage_action(-rate, obs, obs_map, bounds)
        if (
            bool(price["cheap"])
            and not peak
            and expected <= self.pv_surplus_threshold_kw
            and not self._pv_expected_without_surplus_forecast(obs, obs_map)
            and soc < min(max_soc, self.storage_price_charge_soc_ceiling)
        ):
            # Reserve current connection capacity for the service actions that
            # were allocated first, instead of causing a synchronous BESS peak.
            room = max(0.0, self.import_peak_threshold_kw - demand)
            rate = self._storage_power_limited_charge_rate(
                agent_idx,
                room,
                self.price_charge_rate,
                obs=obs,
                obs_map=obs_map,
                target_soc=min(max_soc, self.storage_price_charge_soc_ceiling),
            )
            return self._clip_storage_action(rate, obs, obs_map, bounds)
        return 0.0


class RBCSmartLocalPolicy(_EconomicSmartPolicy):
    """Strict building-local variant of :class:`RBCSmartPolicy`.

    The regular smart policy remains backwards compatible and may use a
    community signal as a fallback when a local signal is absent.  That is a
    useful operational behaviour, but it is not an admissible baseline or
    teacher for experiments that claim strict per-building information.

    This variant deliberately makes every community accessor neutral and
    derives solar/headroom decisions only from local or public exogenous
    observations.  Keeping the restriction in the policy, rather than only in
    an encoder profile, is important because rule-based teachers consume raw
    observations.
    """

    def attach_environment(
        self,
        *,
        observation_names: List[List[str]],
        action_names: List[List[str]],
        action_space: List[Any],
        observation_space: List[Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().attach_environment(
            observation_names=observation_names,
            action_names=action_names,
            action_space=action_space,
            observation_space=observation_space,
            metadata=metadata,
        )
        # Keep the original raw-vector indices.  Only the lookup keys are
        # removed, so a community column before a local column cannot shift the
        # latter and corrupt raw observation access.
        self._obs_index = [
            {
                name: index
                for name, index in obs_map.items()
                if "community" not in str(name).casefold()
            }
            for obs_map in self._obs_index
        ]
        self._obs_match_cache = {}

    def _policy_type(self) -> str:
        return "rbc_smart_local_policy"

    def _forecast_solar_resource_expected(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> bool:
        pv_values = self._forecast_values(
            obs,
            obs_map,
            ["forecast_pv"],
            exclude_tokens=["community"],
        )
        irradiance_values = self._forecast_values(
            obs,
            obs_map,
            ["solar_irradiance_predicted"],
            exclude_tokens=["community"],
        )
        return (
            max((max(0.0, value) for value in pv_values), default=0.0)
            > self.pv_surplus_threshold_kw
            or max((max(0.0, value) for value in irradiance_values), default=0.0) > 100.0
        )

    def _get_headroom_kw(self, obs: np.ndarray, obs_map: Mapping[str, int]) -> float:
        exact_names = (
            "charging_building_headroom_kw",
            "building_import_headroom_kw",
            "phase_headroom_kw",
        )
        for name in exact_names:
            value = self._get_value(obs, obs_map, name, default=float("nan"))
            if math.isfinite(value):
                return value

        matches = self._cached_observation_matches(
            obs_map,
            include_tokens=("headroom",),
            exclude_tokens=("community", "export", "forecast"),
        )
        local_values: List[float] = []
        for name, index in matches:
            if index >= len(obs) or not (
                "building" in name.lower() or "phase" in name.lower() or "charging" in name.lower()
            ):
                continue
            value = self._get_value(obs, obs_map, name, default=float("nan"))
            if math.isfinite(value):
                local_values.append(value)
        return min(local_values) if local_values else float("inf")

    def _forecast_community_surplus_kw(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return 0.0

    def _forecast_community_import_peak_kw(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return 0.0

    def _forecast_community_headroom_min_kw(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return float("inf")

    def _get_community_import_power(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return 0.0

    def _get_community_export_power(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return 0.0

    def _get_community_pv_power(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return 0.0

    def _get_community_headroom_kw(
        self,
        obs: np.ndarray,
        obs_map: Mapping[str, int],
    ) -> float:
        del obs, obs_map
        return float("inf")


class RBCCommunityPolicy(_EconomicSmartPolicy):
    """Local economic policy with explicitly enabled sharing and peak support.

    Without a settlement market, cross-building battery export has no member
    cost benefit. In that case this policy uses the same local dispatch as
    Smart. The default aggregate battery-support trigger is 15 kW, independent
    of member count. It is not a hard import cap.
    """

    uses_community_dispatch = True

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        hyper = config.get("algorithm", {}).get("hyperparameters") or {}
        if hyper.get("community_import_threshold_kw") is None:
            self.community_import_threshold_kw = COMMUNITY_IMPORT_THRESHOLD_KW
        market = dict((self._dataset_info or {}).get("community_market") or {})
        market.update(config.get("simulator", {}).get("community_market") or {})
        self.community_market_enabled = bool(
            market.get("enabled", hyper.get("community_market_enabled", False))
        )
        self.community_local_price_ratio = float(
            market.get(
                "local_price_ratio_to_grid_import",
                market.get("intra_community_sell_ratio", self.community_local_price_ratio),
            )
        )
        self.community_grid_export_price = float(
            market.get("grid_export_price", self.community_grid_export_price)
        )

    def attach_environment(
        self, *, observation_names, action_names, action_space, observation_space, metadata=None
    ) -> None:
        super().attach_environment(
            observation_names=observation_names,
            action_names=action_names,
            action_space=action_space,
            observation_space=observation_space,
            metadata=metadata,
        )
        market = (metadata or {}).get("community_market")
        if isinstance(market, Mapping):
            self.community_market_enabled = bool(market.get("enabled", False))
            self.community_local_price_ratio = float(
                market.get("local_price_ratio_to_grid_import", self.community_local_price_ratio)
            )
            self.community_grid_export_price = float(
                market.get("grid_export_price", self.community_grid_export_price)
            )
        self.uses_community_dispatch = self.community_market_enabled
        hyper = self._config.get("algorithm", {}).get("hyperparameters") or {}
        if hyper.get("community_import_threshold_kw") is None:
            self.community_import_threshold_kw = COMMUNITY_IMPORT_THRESHOLD_KW
        if not self.community_market_enabled:
            self._obs_index = [
                {
                    name: index
                    for name, index in obs_map.items()
                    if "community" not in name.casefold()
                }
                for obs_map in self._obs_index
            ]

    def _policy_type(self) -> str:
        return "rbc_community_policy"

    def _community_energy_is_discounted(self) -> bool:
        return self.community_market_enabled and super()._community_energy_is_discounted()

    def _usable_surplus_kw(self, agent_idx, obs, obs_map):
        local = super()._usable_surplus_kw(agent_idx, obs, obs_map)
        if not self._community_energy_is_discounted():
            return local
        shared = self._budget_value(
            agent_idx, "community_surplus_kw", self._community_surplus_kw(obs, obs_map)
        )
        return max(local, shared)

    def _expected_surplus_kw(self, obs, obs_map):
        local = super()._expected_surplus_kw(obs, obs_map)
        if not self._community_energy_is_discounted():
            return local
        return max(local, self._forecast_community_surplus_kw(obs, obs_map))

    def _storage_demand(self, agent_idx, obs, obs_map):
        local, local_peak = super()._storage_demand(agent_idx, obs, obs_map)
        if not self.community_market_enabled:
            return local, local_peak
        shared = self._budget_value(
            agent_idx, "community_import_kw", self._get_community_import_power(obs, obs_map)
        )
        # Relieve a present community peak only during an expensive period.
        # Do not empty batteries to supply unrelated cheap member imports.
        if (
            shared >= self.community_import_threshold_kw
            and self._get_price_context(obs, obs_map)["expensive"]
        ):
            return max(local, shared - self.community_import_threshold_kw), True
        return local, local_peak


