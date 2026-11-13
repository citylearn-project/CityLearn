from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.llm.client import (
    BaseChatAPI,
    CallableChatAPI,
    HuggingfaceChatAPI,
    OpenAICompatibleChatAPI,
    RuleGuidedMockChatAPI,
)
from citylearn.llm.models import BuildingProfile, DayEnergyPlan, StepDecisionRecord
from citylearn.llm.planning import PlanningModule
from citylearn.llm.profile import BuildingSeedGenerator, ProfileModule
from citylearn.llm.storage import AgentArtifactStorage


class LLMAgent(Agent):
    """Generative LLM building controller inspired by ``ciao-group/Generative-Traffic-Agents``.

    Implements a three-stage generative control loop for CityLearn buildings:

    1. **Persona synthesis** (:class:`~citylearn.llm.profile.ProfileModule`): creates a
       grounded natural-language building profile from static equipment metadata
       (saved to ``1_descriptions.json``).
    2. **Daily schedule planning** (:class:`~citylearn.llm.planning.PlanningModule`):
       synthesizes a 24-hour energy operating strategy at the start of each day
       (saved to ``2_day_schedules.json``).
    3. **Step-level action selection** (:class:`~citylearn.llm.planning.PlanningModule`):
       selects bounded continuous actions with explicit rationales at control steps
       (saved to ``3_decisions.json``).

    Supports centralized and decentralized flat mode, ``interface="entity"``, and
    ``topology_mode="dynamic"``.
    """

    def __init__(
        self,
        env: CityLearnEnv,
        llm_client: Optional[Union[BaseChatAPI, Any]] = None,
        backend: str = "mock",
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        n_predict: int = 700,
        gpu_id: int = 0,
        storage_dir: Optional[Union[str, Path]] = None,
        enable_day_planning: bool = True,
        decision_interval_steps: int = 1,
        persona_overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
        include_all_observations: bool = False,
        max_retries: int = 1,
        auto_flush_storage: bool = True,
        **kwargs: Any,
    ):
        self.backend = str(backend or "mock").strip().lower()
        self.model_id = model_id
        self.base_url = base_url
        self.temperature = float(temperature)
        self.n_predict = int(n_predict)
        self.gpu_id = int(gpu_id)
        self.enable_day_planning = bool(enable_day_planning)
        self.decision_interval_steps = max(int(decision_interval_steps), 1)
        self.include_all_observations = bool(include_all_observations)
        self.max_retries = max(int(max_retries), 0)

        self.llm_client: BaseChatAPI = self._resolve_llm_client(
            llm_client=llm_client,
            backend=self.backend,
            model_id=model_id,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            temperature=self.temperature,
            n_predict=self.n_predict,
            gpu_id=self.gpu_id,
        )
        self.seed_generator = BuildingSeedGenerator(persona_overrides=persona_overrides)
        self.profile_module = ProfileModule(
            self.llm_client,
            seed_generator=self.seed_generator,
            max_retries=self.max_retries,
        )
        self.planning_module = PlanningModule(
            self.llm_client,
            max_retries=self.max_retries,
        )
        self.storage = AgentArtifactStorage(
            storage_dir=storage_dir,
            auto_flush=auto_flush_storage,
        )

        self._day_plans_by_building: Dict[str, DayEnergyPlan] = {}
        self._last_day_key_by_building: Dict[str, int] = {}
        self._decision_history_by_building: Dict[str, List[StepDecisionRecord]] = {}
        self._last_step_record_by_building: Dict[str, StepDecisionRecord] = {}
        self._action_specs_cache: Dict[int, Tuple[Tuple[str, ...], List[Dict[str, Any]]]] = {}
        self._llm_topology_version: int = int(getattr(env.unwrapped, "topology_version", 0))

        super().__init__(env, **kwargs)
        # Bind agent spaces to flat_observation_space / flat_action_space so the same
        # agent works seamlessly in both interface="flat" and interface="entity".
        self.observation_space = self.env.unwrapped.flat_observation_space
        self.action_space = self.env.unwrapped.flat_action_space
        self.reset()

    @staticmethod
    def _resolve_llm_client(
        *,
        llm_client: Optional[Union[BaseChatAPI, Any]],
        backend: str,
        model_id: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        system_prompt: Optional[str],
        temperature: float,
        n_predict: int,
        gpu_id: int,
    ) -> BaseChatAPI:
        if isinstance(llm_client, BaseChatAPI):
            return llm_client
        if callable(llm_client):
            return CallableChatAPI(llm_client, system_prompt=system_prompt)
        if llm_client is not None:
            raise TypeError(
                "llm_client must be a BaseChatAPI instance, a callable, or None."
            )

        if backend in {"mock", "rule_guided_mock", "offline"}:
            return RuleGuidedMockChatAPI(system_prompt=system_prompt)
        if backend in {"huggingface", "hf", "transformers"}:
            return HuggingfaceChatAPI(
                model_id=model_id,
                system_prompt=system_prompt,
                n_predict=n_predict,
                gpu_id=gpu_id,
                temperature=temperature,
            )
        if backend in {"openai_compatible", "openai", "ollama", "vllm", "openrouter"}:
            return OpenAICompatibleChatAPI(
                model_id=model_id,
                base_url=base_url,
                api_key=api_key,
                system_prompt=system_prompt,
                n_predict=n_predict,
                temperature=temperature,
            )
        raise ValueError(
            f"Unsupported LLMAgent backend {backend!r}. Expected one of: "
            "'mock', 'huggingface', or 'openai_compatible'."
        )

    def reset(self):
        super().reset()
        if not hasattr(self, "_day_plans_by_building"):
            return

        self._day_plans_by_building.clear()
        self._last_day_key_by_building.clear()
        self._decision_history_by_building.clear()
        self._last_step_record_by_building.clear()
        self._action_specs_cache.clear()
        self.storage.reset_episode_logs(keep_descriptions=True)

        env = self.env.unwrapped
        self._llm_topology_version = int(getattr(env, "topology_version", 0))
        for building in env.buildings:
            self._ensure_building_profile(building)

    def comparison_identity(self) -> Dict[str, Any]:
        from citylearn import __version__

        return {
            "implementation": f"{type(self).__module__}.{type(self).__qualname__}",
            "version": __version__,
            "parameters": {
                "backend": self.backend,
                "client_class": type(self.llm_client).__qualname__,
                "model_id": getattr(self.llm_client, "model_id", self.model_id),
                "temperature": self.temperature,
                "n_predict": self.n_predict,
                "enable_day_planning": self.enable_day_planning,
                "decision_interval_steps": self.decision_interval_steps,
                "include_all_observations": self.include_all_observations,
            },
            "observation_access": (
                "all_building_observations" if self.include_all_observations else "active_only"
            ),
        }

    def predict(
        self,
        observations: Any,
        deterministic: Optional[bool] = None,
    ) -> List[List[float]]:
        env = self.env.unwrapped
        if env.time_step == 0 and self.time_step != 0:
            self.reset()

        if getattr(env, "topology_mode", "static") == "dynamic":
            version = int(getattr(env, "topology_version", 0))
            if version != self._llm_topology_version:
                self.action_space = env.flat_action_space
                self.action_names = env.action_names
                self.observation_space = env.flat_observation_space
                self.observation_names = env.observation_names
                self.building_metadata = env.get_metadata()["buildings"]
                self._action_specs_cache.clear()
                self._llm_topology_version = version

        steps_per_day = max(1, int(round(86400.0 / max(float(env.seconds_per_time_step), 1.0))))
        day_index = int(env.time_step // steps_per_day)

        per_building_actions: List[List[float]] = []
        for building in env.buildings:
            vector = self._predict_building_actions(
                building=building,
                time_step=int(env.time_step),
                day_index=day_index,
            )
            per_building_actions.append(vector)

        if env.central_agent:
            actions = [[val for vec in per_building_actions for val in vec]]
        else:
            actions = per_building_actions

        self.actions = actions
        self.next_time_step()
        return actions

    def _ensure_building_profile(self, building: Any) -> BuildingProfile:
        existed = building.name in self.profile_module.profiles
        profile = self.profile_module.get_or_create_profile(building)
        if not existed or building.name not in self.storage.descriptions:
            self.storage.record_profile(profile)
        return profile

    def _predict_building_actions(
        self,
        *,
        building: Any,
        time_step: int,
        day_index: int,
    ) -> List[float]:
        profile = self._ensure_building_profile(building)
        obs_dict = self._building_observations_dict(building)
        action_specs = self._building_action_specs(building)

        day_plan: Optional[DayEnergyPlan] = None
        if self.enable_day_planning:
            if self._last_day_key_by_building.get(building.name) != day_index:
                day_plan = self.planning_module.plan_day_schedule(
                    profile=profile,
                    day_index=day_index,
                    observations=obs_dict,
                )
                self._day_plans_by_building[building.name] = day_plan
                self._last_day_key_by_building[building.name] = day_index
                self.storage.record_day_plan(day_plan)
            else:
                day_plan = self._day_plans_by_building.get(building.name)

        prev_record = self._last_step_record_by_building.get(building.name)
        should_reuse = (
            self.decision_interval_steps > 1
            and (time_step % self.decision_interval_steps) != 0
            and prev_record is not None
            and len(prev_record.action_vector) == len(action_specs)
        )

        if should_reuse:
            reclamped = [
                max(float(spec["low"]), min(float(spec["high"]), float(val)))
                for val, spec in zip(prev_record.action_vector, action_specs)
            ]
            record = StepDecisionRecord.clone_for_reused_step(
                prev_record,
                time_step=time_step,
                observations=obs_dict,
                clamped_vector=reclamped,
            )
            vector = reclamped
        else:
            recent = self._decision_history_by_building.get(building.name, [])
            vector, record = self.planning_module.select_actions(
                profile=profile,
                day_plan=day_plan,
                time_step=time_step,
                observations=obs_dict,
                action_specs=action_specs,
                recent_decisions=recent,
            )

        history = self._decision_history_by_building.setdefault(building.name, [])
        history.append(record)
        if len(history) > 8:
            del history[:-8]
        self._last_step_record_by_building[building.name] = record
        self.storage.record_step_decision(record)
        return vector

    def _building_observations_dict(self, building: Any) -> Dict[str, float]:
        raw = building.observations(
            include_all=self.include_all_observations,
            normalize=False,
            periodic_normalization=False,
        )
        cleaned: Dict[str, float] = {}
        for key, value in (raw or {}).items():
            try:
                scalar = float(value)
                cleaned[str(key)] = scalar if math.isfinite(scalar) else 0.0
            except (TypeError, ValueError):
                continue
        return cleaned

    def _building_action_specs(self, building: Any) -> List[Dict[str, Any]]:
        active_actions = tuple(str(a) for a in (getattr(building, "active_actions", []) or []))
        cached = self._action_specs_cache.get(id(building))
        if cached is not None and cached[0] == active_actions:
            return cached[1]

        space = building.action_space
        charger_by_action: Dict[str, Any] = {}
        for charger in getattr(building, "electric_vehicle_chargers", None) or []:
            cid = str(getattr(charger, "charger_id", ""))
            charger_by_action[f"electric_vehicle_storage_{cid}"] = charger

        bess = getattr(building, "electrical_storage", None)
        bess_dod = float(getattr(bess, "depth_of_discharge", 1.0) or 1.0)
        bess_min_soc = max(0.0, min(1.0, 1.0 - bess_dod)) if 0.0 <= bess_dod <= 1.0 else 0.0

        specs: List[Dict[str, Any]] = []
        for idx, act_name in enumerate(active_actions):
            low = float(space.low[idx])
            high = float(space.high[idx])
            spec: Dict[str, Any] = {
                "action_name": act_name,
                "low": low,
                "high": high,
            }
            if act_name == "electrical_storage" and bess is not None:
                spec["capacity_kwh"] = float(getattr(bess, "capacity", 0.0) or 0.0)
                spec["nominal_power_kw"] = float(getattr(bess, "nominal_power", 0.0) or 0.0)
                spec["min_soc"] = bess_min_soc
            elif act_name in charger_by_action:
                charger = charger_by_action[act_name]
                max_p = float(getattr(charger, "max_charging_power", 0.0) or 0.0)
                min_p = float(getattr(charger, "min_charging_power", 0.0) or 0.0)
                spec["max_charging_power_kw"] = max_p
                spec["min_charging_power_kw"] = min_p
                spec["min_effective_action"] = (min_p / max_p) if max_p > 0.0 and min_p > 0.0 else 0.0
            specs.append(spec)

        self._action_specs_cache[id(building)] = (active_actions, specs)
        return specs


GenerativeBuildingAgent = LLMAgent

__all__ = ["GenerativeBuildingAgent", "LLMAgent"]
