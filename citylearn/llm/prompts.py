from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from citylearn.llm.models import (
    BuildingProfile,
    BuildingSeedProfile,
    DayEnergyPlan,
    StepDecisionRecord,
)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert generative building energy management agent operating in a "
    "CityLearn renewable energy community. Reason carefully about occupant comfort, "
    "solar self-consumption, electricity tariffs, carbon intensity, battery reserve "
    "margins, EV departure deadlines, and electrical service limits. Always respond "
    "with strictly valid JSON matching the requested schema."
)

CONTEXT_START_MARKER = "<<<CITYLEARN_CONTEXT_JSON"
CONTEXT_END_MARKER = "CITYLEARN_CONTEXT_JSON>>>"


def _round_clean(value: Any, digits: int = 4) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else 0.0
    if isinstance(value, Mapping):
        return {str(k): _round_clean(v, digits=digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_clean(v, digits=digits) for v in value]
    try:
        scalar = float(value)
        return round(scalar, digits) if math.isfinite(scalar) else 0.0
    except (TypeError, ValueError):
        return str(value)


def _format_context_block(payload: Mapping[str, Any]) -> str:
    cleaned = _round_clean(payload)
    serialized = json.dumps(cleaned, indent=2, sort_keys=True)
    return f"{CONTEXT_START_MARKER}\n{serialized}\n{CONTEXT_END_MARKER}"


def get_description_prompt(seed_profile: BuildingSeedProfile) -> str:
    """Build Stage-1 persona prompt modeled after GTA's ``ProfileModule``."""
    context = {
        "prompt_stage": "persona_description",
        "seed_profile": seed_profile.to_dict(),
    }
    return (
        f"Generate a realistic, physically grounded energy-management persona for "
        f"building '{seed_profile.building_name}' based on its installed equipment, "
        f"annual load profile, and occupant archetype.\n\n"
        f"{_format_context_block(context)}\n\n"
        "Return a JSON object with exactly these keys:\n"
        '{\n'
        '  "persona_description": "<2-4 sentences describing household/facility occupancy, comfort habits, and DER flexibility>",\n'
        '  "energy_priorities": ["<priority 1>", "<priority 2>", "<priority 3>"],\n'
        '  "comfort_preference": "<concise thermal/appliance comfort guideline>",\n'
        '  "ev_flexibility_preference": "<concise EV departure readiness and charging strategy>"\n'
        '}'
    )


def get_day_schedule_prompt(
    profile: BuildingProfile,
    day_index: int,
    observations: Mapping[str, float],
) -> str:
    """Build Stage-2 daily energy schedule prompt modeled after GTA's ``PlanningModule``."""
    day_type = int(round(float(observations.get("day_type", 1.0))))
    context = {
        "prompt_stage": "day_schedule",
        "building_name": profile.building_name,
        "day_index": int(day_index),
        "day_type": day_type,
        "persona_description": profile.persona_description,
        "energy_priorities": profile.energy_priorities,
        "current_observations": dict(observations),
    }
    return (
        f"Create a high-level 24-hour energy operating schedule for building "
        f"'{profile.building_name}' on simulation day {day_index} (day_type={day_type}).\n\n"
        f"{_format_context_block(context)}\n\n"
        "Return a JSON object with exactly these keys:\n"
        '{\n'
        '  "description_of_today": [\n'
        '    "00:00-06:00: <overnight off-peak EV/battery plan>",\n'
        '    "06:00-10:00: <morning ramp plan>",\n'
        '    "10:00-16:00: <midday solar self-consumption & pre-conditioning plan>",\n'
        '    "16:00-22:00: <evening peak shaving & comfort protection plan>",\n'
        '    "22:00-24:00: <late evening recovery plan>"\n'
        '  ],\n'
        '  "solar_charging_window": "<target hours and SoC goal for PV charging>",\n'
        '  "peak_avoidance_strategy": "<how battery/thermal/loads avoid high tariff imports>",\n'
        '  "ev_charging_plan": "<how EV departure SoC targets are guaranteed>"\n'
        '}'
    )


def get_action_selection_prompt(
    *,
    profile: BuildingProfile,
    day_plan: Optional[DayEnergyPlan],
    time_step: int,
    observations: Mapping[str, float],
    action_specs: Sequence[Mapping[str, Any]],
    recent_decisions: Optional[Sequence[StepDecisionRecord]] = None,
) -> str:
    """Build Stage-3 step-level control decision prompt modeled after GTA's ``PlanningModule``."""
    history_tail: List[Dict[str, Any]] = []
    for rec in (recent_decisions or [])[-2:]:
        history_tail.append(
            {
                "time_step": rec.time_step,
                "hour": rec.hour,
                "actions": {d.action_name: d.value for d in rec.decisions},
            }
        )

    context = {
        "prompt_stage": "action_selection",
        "building_name": profile.building_name,
        "time_step": int(time_step),
        "persona_description": profile.persona_description,
        "energy_priorities": profile.energy_priorities,
        "day_plan": None if day_plan is None else {
            "day_index": day_plan.day_index,
            "description_of_today": day_plan.description_of_today,
            "solar_charging_window": day_plan.solar_charging_window,
            "peak_avoidance_strategy": day_plan.peak_avoidance_strategy,
            "ev_charging_plan": day_plan.ev_charging_plan,
        },
        "observations": dict(observations),
        "action_specs": [dict(spec) for spec in action_specs],
        "recent_decisions": history_tail,
    }

    return (
        f"Select continuous control actions for building '{profile.building_name}' "
        f"at time_step={time_step}.\n\n"
        "Physical action semantics:\n"
        "- Storage actions (`electrical_storage`, `cooling_storage`, `heating_storage`, `dhw_storage`): "
        "fraction of storage capacity charged (>0) or discharged (<0) in this step, bounded by `[low, high]`.\n"
        "- EV charger actions (`electric_vehicle_storage_<id>`): fraction of charger power (>0 charges, "
        "<0 V2G discharge when supported). Note `min_effective_action`: positive values strictly below "
        "`min_effective_action` fall inside the hardware deadband and deliver 0 kW, so use `0.0` or "
        "`>= min_effective_action`.\n"
        "- Deferrable appliances (`deferrable_appliance_<idx>`): `>= 0.5` starts a cycle if pending.\n"
        "- HVAC device actions (`cooling_device`, `heating_device`, `cooling_or_heating_device`): "
        "fraction of nominal device power.\n\n"
        f"{_format_context_block(context)}\n\n"
        "Return a JSON object containing one entry per item in `action_specs`:\n"
        '{\n'
        '  "decisions": [\n'
        '    {\n'
        '      "action_name": "<exact action_name from action_specs>",\n'
        '      "reasoning": "<1 concise sentence citing current observations/plan>",\n'
        '      "value": 0.0\n'
        '    }\n'
        '  ]\n'
        '}'
    )
