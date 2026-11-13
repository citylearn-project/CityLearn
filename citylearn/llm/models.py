from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class BuildingSeedProfile:
    """Static equipment and load-profile attributes extracted for one building."""

    building_name: str
    occupant_archetype: str
    equipment_summary: Dict[str, Any]
    active_actions: List[str]
    action_bounds: Dict[str, List[float]]
    annual_demands_kwh: Dict[str, float]
    pv_nominal_power_kw: float = 0.0
    battery_capacity_kwh: float = 0.0
    battery_nominal_power_kw: float = 0.0
    battery_min_soc: float = 0.0
    ev_chargers: List[Dict[str, Any]] = field(default_factory=list)
    deferrable_appliances: List[Dict[str, Any]] = field(default_factory=list)
    custom_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_name": self.building_name,
            "occupant_archetype": self.occupant_archetype,
            "equipment_summary": dict(self.equipment_summary),
            "active_actions": list(self.active_actions),
            "action_bounds": {k: list(v) for k, v in self.action_bounds.items()},
            "annual_demands_kwh": dict(self.annual_demands_kwh),
            "pv_nominal_power_kw": float(self.pv_nominal_power_kw),
            "battery_capacity_kwh": float(self.battery_capacity_kwh),
            "battery_nominal_power_kw": float(self.battery_nominal_power_kw),
            "battery_min_soc": float(self.battery_min_soc),
            "ev_chargers": [dict(item) for item in self.ev_chargers],
            "deferrable_appliances": [dict(item) for item in self.deferrable_appliances],
            "custom_attributes": dict(self.custom_attributes),
        }


@dataclass
class BuildingProfile:
    """Grounded natural-language persona and operating priorities for a building."""

    building_name: str
    persona_description: str
    energy_priorities: List[str]
    comfort_preference: str
    ev_flexibility_preference: str
    seed_profile: BuildingSeedProfile
    raw_response: str = ""
    used_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_name": self.building_name,
            "persona_description": self.persona_description,
            "energy_priorities": list(self.energy_priorities),
            "comfort_preference": self.comfort_preference,
            "ev_flexibility_preference": self.ev_flexibility_preference,
            "seed_profile": self.seed_profile.to_dict(),
            "used_fallback": bool(self.used_fallback),
        }


@dataclass
class DayEnergyPlan:
    """Daily high-level operating plan analogous to GTA's ``2_day_schedules.json``."""

    building_name: str
    day_index: int
    day_type: int
    description_of_today: List[str]
    solar_charging_window: str
    peak_avoidance_strategy: str
    ev_charging_plan: str
    raw_response: str = ""
    used_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "building_name": self.building_name,
            "day_index": int(self.day_index),
            "day_type": int(self.day_type),
            "description_of_today": list(self.description_of_today),
            "solar_charging_window": self.solar_charging_window,
            "peak_avoidance_strategy": self.peak_avoidance_strategy,
            "ev_charging_plan": self.ev_charging_plan,
            "used_fallback": bool(self.used_fallback),
        }


@dataclass
class ActionDecision:
    """Validated single-actuator decision and natural-language rationale."""

    action_name: str
    value: float
    raw_value: Optional[float]
    low: float
    high: float
    reasoning: str
    clamped: bool = False
    used_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_name": self.action_name,
            "value": float(self.value),
            "raw_value": None if self.raw_value is None else float(self.raw_value),
            "low": float(self.low),
            "high": float(self.high),
            "reasoning": self.reasoning,
            "clamped": bool(self.clamped),
            "used_fallback": bool(self.used_fallback),
        }


@dataclass
class StepDecisionRecord:
    """Step-level decision log analogous to GTA's ``3_decisions.json``."""

    time_step: int
    building_name: str
    hour: float
    day_type: int
    decisions: List[ActionDecision]
    action_vector: List[float]
    observations_snapshot: Dict[str, float]
    day_plan_summary: Optional[str] = None
    raw_response: str = ""
    reused_previous_step: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_step": int(self.time_step),
            "building_name": self.building_name,
            "hour": float(self.hour),
            "day_type": int(self.day_type),
            "action_vector": [float(v) for v in self.action_vector],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "observations_snapshot": {k: float(v) for k, v in self.observations_snapshot.items()},
            "day_plan_summary": self.day_plan_summary,
            "reused_previous_step": bool(self.reused_previous_step),
        }

    @classmethod
    def clone_for_reused_step(
        cls,
        previous: "StepDecisionRecord",
        *,
        time_step: int,
        observations: Mapping[str, float],
        clamped_vector: List[float],
    ) -> "StepDecisionRecord":
        cloned_decisions: List[ActionDecision] = []
        for idx, decision in enumerate(previous.decisions):
            val = clamped_vector[idx] if idx < len(clamped_vector) else decision.value
            cloned_decisions.append(
                ActionDecision(
                    action_name=decision.action_name,
                    value=float(val),
                    raw_value=decision.raw_value,
                    low=decision.low,
                    high=decision.high,
                    reasoning=decision.reasoning,
                    clamped=bool(val != decision.value or decision.clamped),
                    used_fallback=decision.used_fallback,
                )
            )
        return cls(
            time_step=int(time_step),
            building_name=previous.building_name,
            hour=float(observations.get("hour", previous.hour)),
            day_type=int(round(float(observations.get("day_type", previous.day_type)))),
            decisions=cloned_decisions,
            action_vector=list(clamped_vector),
            observations_snapshot={str(k): float(v) for k, v in observations.items()},
            day_plan_summary=previous.day_plan_summary,
            raw_response="",
            reused_previous_step=True,
        )
