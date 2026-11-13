from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from citylearn.llm.client import BaseChatAPI
from citylearn.llm.json_parser import extract_json_from_polluted_string
from citylearn.llm.models import (
    ActionDecision,
    BuildingProfile,
    DayEnergyPlan,
    StepDecisionRecord,
)
from citylearn.llm.prompts import get_action_selection_prompt, get_day_schedule_prompt

LOGGER = logging.getLogger(__name__)


class PlanningModule:
    """Stage-2 daily schedule & Stage-3 action selection module modeled after GTA's ``PlanningModule``."""

    def __init__(
        self,
        llm_client: BaseChatAPI,
        *,
        max_retries: int = 1,
    ):
        self.llm_client = llm_client
        self.max_retries = max(int(max_retries), 0)

    def plan_day_schedule(
        self,
        *,
        profile: BuildingProfile,
        day_index: int,
        observations: Mapping[str, float],
    ) -> DayEnergyPlan:
        prompt = get_day_schedule_prompt(profile, day_index=day_index, observations=observations)
        day_type = int(round(float(observations.get("day_type", 1.0))))
        raw_text = ""

        for _ in range(self.max_retries + 1):
            try:
                raw_text = self.llm_client.get_completion(prompt)
                parsed = extract_json_from_polluted_string(raw_text)
                if isinstance(parsed, Mapping):
                    desc_raw = parsed.get("description_of_today") or parsed.get("schedule") or []
                    if isinstance(desc_raw, str):
                        schedule_blocks = [desc_raw]
                    elif isinstance(desc_raw, list):
                        schedule_blocks = [str(item) for item in desc_raw if str(item).strip()]
                    else:
                        schedule_blocks = []

                    if schedule_blocks:
                        return DayEnergyPlan(
                            building_name=profile.building_name,
                            day_index=int(day_index),
                            day_type=day_type,
                            description_of_today=schedule_blocks,
                            solar_charging_window=str(
                                parsed.get("solar_charging_window", "Charge storage during midday PV surplus.")
                            ),
                            peak_avoidance_strategy=str(
                                parsed.get("peak_avoidance_strategy", "Discharge storage during evening peak tariffs.")
                            ),
                            ev_charging_plan=str(
                                parsed.get("ev_charging_plan", "Complete EV charging prior to departure deadline.")
                            ),
                            raw_response=raw_text,
                            used_fallback=False,
                        )
            except Exception as exc:
                LOGGER.debug("PlanningModule day schedule retry for %s: %s", profile.building_name, exc)

        return DayEnergyPlan(
            building_name=profile.building_name,
            day_index=int(day_index),
            day_type=day_type,
            description_of_today=[
                "00:00-08:00: Off-peak EV charging and reserve preservation.",
                "08:00-16:00: Midday solar charging and flexible load execution.",
                "16:00-24:00: Evening peak shaving and late-night rebalancing.",
            ],
            solar_charging_window="10:00-16:00 solar self-consumption window.",
            peak_avoidance_strategy="17:00-21:00 peak shaving discharge.",
            ev_charging_plan="Deadline-aware EV charging.",
            raw_response=raw_text,
            used_fallback=True,
        )

    def select_actions(
        self,
        *,
        profile: BuildingProfile,
        day_plan: Optional[DayEnergyPlan],
        time_step: int,
        observations: Mapping[str, float],
        action_specs: Sequence[Mapping[str, Any]],
        recent_decisions: Optional[Sequence[StepDecisionRecord]] = None,
    ) -> Tuple[List[float], StepDecisionRecord]:
        hour = float(observations.get("hour", 0.0))
        day_type = int(round(float(observations.get("day_type", 1.0))))
        plan_summary = (
            "; ".join(day_plan.description_of_today[:2])
            if day_plan is not None and day_plan.description_of_today
            else None
        )

        if len(action_specs) == 0:
            empty_record = StepDecisionRecord(
                time_step=int(time_step),
                building_name=profile.building_name,
                hour=hour,
                day_type=day_type,
                decisions=[],
                action_vector=[],
                observations_snapshot={str(k): float(v) for k, v in observations.items()},
                day_plan_summary=plan_summary,
                raw_response="",
            )
            return [], empty_record

        prompt = get_action_selection_prompt(
            profile=profile,
            day_plan=day_plan,
            time_step=time_step,
            observations=observations,
            action_specs=action_specs,
            recent_decisions=recent_decisions,
        )

        raw_text = ""
        parsed_by_name: Dict[str, Tuple[Optional[float], str]] = {}
        parse_succeeded = False

        for _ in range(self.max_retries + 1):
            try:
                raw_text = self.llm_client.get_completion(prompt)
                parsed = extract_json_from_polluted_string(raw_text)
                extracted = self._normalize_parsed_decisions(parsed, action_specs)
                if extracted:
                    parsed_by_name = extracted
                    parse_succeeded = True
                    break
            except Exception as exc:
                LOGGER.debug("PlanningModule action selection retry for %s: %s", profile.building_name, exc)

        decisions: List[ActionDecision] = []
        action_vector: List[float] = []

        for spec in action_specs:
            name = str(spec["action_name"])
            low = float(spec["low"])
            high = float(spec["high"])
            safe_neutral = max(low, min(high, 0.0))

            if parse_succeeded and name in parsed_by_name:
                raw_val, reason = parsed_by_name[name]
                if raw_val is not None and math.isfinite(raw_val):
                    clamped_val = max(low, min(high, float(raw_val)))
                    decisions.append(
                        ActionDecision(
                            action_name=name,
                            value=clamped_val,
                            raw_value=float(raw_val),
                            low=low,
                            high=high,
                            reasoning=reason or "LLM control decision.",
                            clamped=bool(abs(clamped_val - float(raw_val)) > 1e-9),
                            used_fallback=False,
                        )
                    )
                    action_vector.append(clamped_val)
                    continue

            decisions.append(
                ActionDecision(
                    action_name=name,
                    value=safe_neutral,
                    raw_value=None,
                    low=low,
                    high=high,
                    reasoning="Fallback safe neutral action (missing or non-finite LLM output).",
                    clamped=False,
                    used_fallback=True,
                )
            )
            action_vector.append(safe_neutral)

        record = StepDecisionRecord(
            time_step=int(time_step),
            building_name=profile.building_name,
            hour=hour,
            day_type=day_type,
            decisions=decisions,
            action_vector=action_vector,
            observations_snapshot={str(k): float(v) for k, v in observations.items()},
            day_plan_summary=plan_summary,
            raw_response=raw_text,
            reused_previous_step=False,
        )
        return action_vector, record

    @staticmethod
    def _normalize_parsed_decisions(
        parsed: Any,
        action_specs: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Tuple[Optional[float], str]]:
        """Accept either GTA's structured ``decisions`` list or compact ``actions`` dicts."""
        result: Dict[str, Tuple[Optional[float], str]] = {}

        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, Mapping) and isinstance(parsed.get("decisions"), list):
            items = parsed["decisions"]
        else:
            items = None

        if items is not None:
            for entry in items:
                if not isinstance(entry, Mapping):
                    continue
                act_name = entry.get("action_name") or entry.get("name") or entry.get("action")
                if not act_name:
                    continue
                val_raw = entry.get("value")
                if val_raw is None:
                    val_raw = entry.get("action_value")
                try:
                    val_float: Optional[float] = float(val_raw)
                except (TypeError, ValueError):
                    val_float = None
                reason = str(entry.get("reasoning") or entry.get("reason") or "LLM decision.")
                result[str(act_name)] = (val_float, reason)
            if result:
                return result

        if isinstance(parsed, Mapping):
            actions_map = parsed.get("actions") if isinstance(parsed.get("actions"), Mapping) else parsed
            shared_reason = str(parsed.get("reasoning") or parsed.get("reason") or "LLM direct action map.")
            valid_names = {str(spec["action_name"]) for spec in action_specs}
            for name in valid_names:
                if name in actions_map:
                    entry_val = actions_map[name]
                    if isinstance(entry_val, Mapping):
                        try:
                            val_float = float(entry_val.get("value"))
                        except (TypeError, ValueError):
                            val_float = None
                        reason = str(entry_val.get("reasoning") or shared_reason)
                    else:
                        try:
                            val_float = float(entry_val)
                        except (TypeError, ValueError):
                            val_float = None
                        reason = shared_reason
                    result[name] = (val_float, reason)

        return result
