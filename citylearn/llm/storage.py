from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from citylearn.llm.models import BuildingProfile, DayEnergyPlan, StepDecisionRecord


class AgentArtifactStorage:
    """Persist GTA-style generative agent artifacts for inspection and replay.

    When ``storage_dir`` is provided, writes three structured JSON files matching
    the three-stage Generative-Traffic-Agents pipeline:

    - ``1_descriptions.json``: per-building grounded persona descriptions
    - ``2_day_schedules.json``: daily energy management schedules
    - ``3_decisions.json``: step-by-step control decisions and rationales
    """

    DESCRIPTIONS_FILENAME = "1_descriptions.json"
    DAY_SCHEDULES_FILENAME = "2_day_schedules.json"
    DECISIONS_FILENAME = "3_decisions.json"

    def __init__(
        self,
        storage_dir: Optional[Union[str, Path]] = None,
        *,
        auto_flush: bool = True,
    ):
        self.storage_dir: Optional[Path] = None if storage_dir is None else Path(storage_dir)
        self.auto_flush = bool(auto_flush)
        self.descriptions: Dict[str, Dict[str, Any]] = {}
        self.day_schedules: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []

        if self.storage_dir is not None:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def descriptions_path(self) -> Optional[Path]:
        return None if self.storage_dir is None else self.storage_dir / self.DESCRIPTIONS_FILENAME

    @property
    def day_schedules_path(self) -> Optional[Path]:
        return None if self.storage_dir is None else self.storage_dir / self.DAY_SCHEDULES_FILENAME

    @property
    def decisions_path(self) -> Optional[Path]:
        return None if self.storage_dir is None else self.storage_dir / self.DECISIONS_FILENAME

    def reset_episode_logs(self, *, keep_descriptions: bool = True) -> None:
        if not keep_descriptions:
            self.descriptions.clear()
        self.day_schedules.clear()
        self.decisions.clear()
        if self.auto_flush:
            self.flush()

    def record_profile(self, profile: BuildingProfile) -> None:
        self.descriptions[profile.building_name] = profile.to_dict()
        if self.auto_flush and self.descriptions_path is not None:
            self._write_json(self.descriptions_path, self.descriptions)

    def record_day_plan(self, day_plan: DayEnergyPlan) -> None:
        self.day_schedules.append(day_plan.to_dict())
        if self.auto_flush and self.day_schedules_path is not None:
            self._write_json(self.day_schedules_path, self.day_schedules)

    def record_step_decision(self, record: StepDecisionRecord) -> None:
        self.decisions.append(record.to_dict())
        if self.auto_flush and self.decisions_path is not None:
            self._write_json(self.decisions_path, self.decisions)

    def flush(self) -> None:
        if self.storage_dir is None:
            return
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.descriptions_path, self.descriptions)
        self._write_json(self.day_schedules_path, self.day_schedules)
        self._write_json(self.decisions_path, self.decisions)

    def summarize_decisions(self) -> Dict[str, Any]:
        action_totals: Dict[str, List[float]] = {}
        fallback_count = 0
        clamped_count = 0
        sample_rationales: List[Dict[str, Any]] = []

        for record in self.decisions:
            for decision in record.get("decisions", []):
                name = str(decision.get("action_name", ""))
                val = float(decision.get("value", 0.0))
                action_totals.setdefault(name, []).append(val)
                if decision.get("used_fallback"):
                    fallback_count += 1
                if decision.get("clamped"):
                    clamped_count += 1
                if len(sample_rationales) < 5 and not record.get("reused_previous_step", False):
                    sample_rationales.append(
                        {
                            "time_step": record.get("time_step"),
                            "building_name": record.get("building_name"),
                            "action_name": name,
                            "value": val,
                            "reasoning": decision.get("reasoning", ""),
                        }
                    )

        mean_actions = {
            name: (sum(vals) / len(vals) if vals else 0.0)
            for name, vals in sorted(action_totals.items())
        }
        return {
            "buildings_profiled": len(self.descriptions),
            "day_schedules_recorded": len(self.day_schedules),
            "step_records_recorded": len(self.decisions),
            "fallback_decisions": fallback_count,
            "clamped_decisions": clamped_count,
            "mean_action_by_name": mean_actions,
            "sample_rationales": sample_rationales,
        }

    @staticmethod
    def _write_json(path: Optional[Path], payload: Any) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
