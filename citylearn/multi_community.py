from __future__ import annotations

import datetime
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from gymnasium import Env

from citylearn.citylearn import CityLearnEnv, EvaluationCondition
from citylearn.internal.kpi import CityLearnKPIService


__all__ = ["MultiCommunityEnv"]


@dataclass(frozen=True)
class _CommunityConfig:
    community_id: str
    schema: Union[str, Path, Mapping[str, Any]]
    env_kwargs: Mapping[str, Any]
    weight: float


class MultiCommunityEnv(Env):
    """Synchronize multiple independent :class:`CityLearnEnv` communities.

    V1 is an orchestration layer only: every child environment keeps its own
    physics, demand response state, reward and KPIs. The wrapper coordinates
    reset/step calls and adds portfolio-level KPI rows from district totals.
    """

    PORTFOLIO_COMMUNITY_ID = "__portfolio__"
    PORTFOLIO_NAME = "Portfolio"
    _COMMUNITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
    _SUM_SUFFIXES = ("_kwh", "_eur", "_kgco2", "_count")
    _WEIGHTED_MEAN_SUFFIXES = ("_ratio", "_percent")

    def __init__(
        self,
        *,
        communities: Sequence[Mapping[str, Any]],
        render_directory: Union[str, Path] = None,
        render_session_name: str = None,
    ):
        self.render_output_root = self._resolve_render_directory(render_directory)
        self.render_session_name = self._resolve_render_session_name(render_session_name)
        self._render_dir_initialized = False
        self.new_folder_path: Optional[str] = None

        configs = self._parse_communities(communities)
        self._community_configs: "OrderedDict[str, _CommunityConfig]" = OrderedDict(
            (config.community_id, config) for config in configs
        )
        self.envs: "OrderedDict[str, CityLearnEnv]" = OrderedDict()

        created_envs: List[CityLearnEnv] = []
        try:
            for config in configs:
                child_kwargs = dict(config.env_kwargs)
                child_kwargs["render_directory"] = self.render_output_root
                child_kwargs["render_session_name"] = str(Path(self.render_session_name) / config.community_id)
                env = CityLearnEnv(config.schema, **child_kwargs)
                self.envs[config.community_id] = env
                created_envs.append(env)
            self._validate_constructor_homogeneity()
        except Exception:
            for env in created_envs:
                env.close()
            raise

        self._terminated = any(env.terminated for env in self.envs.values())
        self._truncated = any(env.truncated for env in self.envs.values())

    @property
    def community_ids(self) -> List[str]:
        """Community identifiers in deterministic execution order."""

        return list(self.envs.keys())

    @property
    def weights(self) -> Dict[str, float]:
        """Portfolio aggregation weights by community id."""

        return {
            community_id: self._community_configs[community_id].weight
            for community_id in self.community_ids
        }

    @property
    def interface(self) -> str:
        """Common child environment interface mode."""

        return next(iter(self.envs.values())).interface

    @property
    def central_agent(self) -> bool:
        """Common child environment central-agent mode."""

        return bool(next(iter(self.envs.values())).central_agent)

    @property
    def seconds_per_time_step(self) -> float:
        """Common step duration in seconds."""

        return float(next(iter(self.envs.values())).seconds_per_time_step)

    @property
    def episode_time_steps(self) -> int:
        """Effective episode length in synchronized child environments."""

        return int(next(iter(self.envs.values())).episode_tracker.episode_time_steps)

    @property
    def time_steps(self) -> int:
        """Number of time steps in the synchronized episode."""

        return self.episode_time_steps

    @property
    def time_step(self) -> int:
        """Current synchronized time step."""

        return int(next(iter(self.envs.values())).time_step)

    @property
    def terminated(self) -> bool:
        """Whether any child environment has terminated."""

        return bool(self._terminated)

    @property
    def truncated(self) -> bool:
        """Whether any child environment has truncated."""

        return bool(self._truncated)

    @property
    def action_space(self) -> Mapping[str, Any]:
        """Action spaces keyed by community id."""

        return {community_id: env.action_space for community_id, env in self.envs.items()}

    @property
    def observation_space(self) -> Mapping[str, Any]:
        """Observation spaces keyed by community id."""

        return {community_id: env.observation_space for community_id, env in self.envs.items()}

    @property
    def entity_specs(self) -> Mapping[str, Any]:
        """Entity interface specifications keyed by community id."""

        return {community_id: env.entity_specs for community_id, env in self.envs.items()}

    @property
    def observations(self) -> Mapping[str, Any]:
        """Current child observations keyed by community id."""

        return {community_id: env.observations for community_id, env in self.envs.items()}

    @property
    def rewards(self) -> Mapping[str, Any]:
        """Child reward histories keyed by community id."""

        return {community_id: env.rewards for community_id, env in self.envs.items()}

    @property
    def unwrapped(self) -> "MultiCommunityEnv":
        return self

    def reset(self, seed: int = None, options: Mapping[str, Any] = None) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
        """Reset every child environment and return observations by community."""

        observations: Dict[str, Any] = {}
        child_infos: Dict[str, Mapping[str, Any]] = {}

        for community_id, env in self.envs.items():
            child_options = self._child_options(options, community_id)
            observation, info = env.reset(seed=seed, options=child_options)
            observations[community_id] = observation
            child_infos[community_id] = info

        self._validate_reset_synchronization()
        self._terminated = any(env.terminated for env in self.envs.values())
        self._truncated = any(env.truncated for env in self.envs.values())
        return observations, self._build_info(child_infos=child_infos)

    def step(self, actions: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Mapping[str, Any], bool, bool, Mapping[str, Any]]:
        """Apply one action payload per community and advance all child envs once."""

        if self.terminated or self.truncated:
            raise RuntimeError("Cannot call step() after termination/truncation. Call reset() first.")

        if not isinstance(actions, Mapping):
            raise TypeError("MultiCommunityEnv.step actions must be a mapping keyed by community_id.")

        self._validate_action_keys(actions)
        observations: Dict[str, Any] = {}
        rewards: Dict[str, Any] = {}
        child_infos: Dict[str, Mapping[str, Any]] = {}
        terminated_by_community: Dict[str, bool] = {}
        truncated_by_community: Dict[str, bool] = {}

        for community_id, env in self.envs.items():
            observation, reward, terminated, truncated, info = env.step(actions[community_id])
            observations[community_id] = observation
            rewards[community_id] = reward
            child_infos[community_id] = info
            terminated_by_community[community_id] = bool(terminated)
            truncated_by_community[community_id] = bool(truncated)

        self._terminated = any(terminated_by_community.values())
        self._truncated = any(truncated_by_community.values())
        self._validate_step_synchronization()
        info = self._build_info(
            child_infos=child_infos,
            rewards=rewards,
            terminated_by_community=terminated_by_community,
            truncated_by_community=truncated_by_community,
        )
        return observations, rewards, self.terminated, self.truncated, info

    def evaluate_v2(
        self,
        control_condition: EvaluationCondition = None,
        baseline_condition: EvaluationCondition = None,
        comfort_band: float = None,
        include_business_as_usual: bool = True,
    ) -> pd.DataFrame:
        """Return local child KPIs plus portfolio rows aggregated from district KPIs."""

        frames: List[pd.DataFrame] = []

        for community_id, env in self.envs.items():
            frame = env.evaluate_v2(
                control_condition=control_condition,
                baseline_condition=baseline_condition,
                comfort_band=comfort_band,
                include_business_as_usual=include_business_as_usual,
            ).copy()
            frame["community_id"] = community_id
            frames.append(frame)

        local = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        portfolio = self._portfolio_kpis(local)

        if portfolio.empty:
            return local

        return pd.concat([local, portfolio], ignore_index=True)

    def export_final_kpis(
        self,
        model: Any = None,
        filepath: str = "exported_kpis_multi_community.csv",
        include_business_as_usual: bool = True,
        export_business_as_usual_timeseries: bool = True,
        kpi_round_decimals: int = None,
        export_community_kpis: bool = True,
        community_filepath: str = "exported_kpis.csv",
    ):
        """Export child KPIs to child folders and global multi-community KPIs."""

        if model is not None:
            raise NotImplementedError("MultiCommunityEnv.export_final_kpis does not support model overrides in v1.")

        if export_community_kpis:
            for env in self.envs.values():
                env.export_final_kpis(
                    filepath=community_filepath,
                    include_business_as_usual=include_business_as_usual,
                    export_business_as_usual_timeseries=export_business_as_usual_timeseries,
                    kpi_round_decimals=kpi_round_decimals,
                )

        self._ensure_output_dir()
        kpis = self.evaluate_v2(include_business_as_usual=include_business_as_usual)

        if kpi_round_decimals is not None:
            kpis = kpis.copy()
            kpis["value"] = pd.to_numeric(kpis["value"], errors="coerce").round(kpi_round_decimals)

        path = self._export_path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        kpis.to_csv(path, index=False, encoding="utf-8", na_rep="")

    def render(self) -> Mapping[str, Any]:
        """Render every child environment into its own community subfolder."""

        return {community_id: env.render() for community_id, env in self.envs.items()}

    def close(self):
        """Close child environments and flush their render buffers."""

        for env in self.envs.values():
            env.close()
        return super().close()

    def get_metadata(self) -> Mapping[str, Any]:
        """Static wrapper metadata and child metadata."""

        return {
            "community_ids": self.community_ids,
            "weights": self.weights,
            "interface": self.interface,
            "central_agent": self.central_agent,
            "seconds_per_time_step": self.seconds_per_time_step,
            "episode_time_steps": self.episode_time_steps,
            "time_step": self.time_step,
            "render_directory": str(self.render_output_root),
            "render_session_name": self.render_session_name,
            "communities": {
                community_id: env.get_metadata()
                for community_id, env in self.envs.items()
            },
        }

    @classmethod
    def _parse_communities(cls, communities: Sequence[Mapping[str, Any]]) -> List[_CommunityConfig]:
        if not isinstance(communities, Sequence) or isinstance(communities, (str, bytes)):
            raise TypeError("communities must be a non-empty sequence of mappings.")

        if len(communities) == 0:
            raise ValueError("communities must contain at least one community.")

        configs: List[_CommunityConfig] = []
        seen = set()

        for index, raw in enumerate(communities):
            if not isinstance(raw, Mapping):
                raise TypeError(f"communities[{index}] must be a mapping.")

            community_id = cls._validate_community_id(raw.get("community_id"), index=index)
            if community_id in seen:
                raise ValueError(f"Duplicate community_id: {community_id!r}.")
            seen.add(community_id)

            if "schema" not in raw:
                raise ValueError(f"communities[{index}].schema is required.")

            env_kwargs = raw.get("env_kwargs", {}) or {}
            if not isinstance(env_kwargs, Mapping):
                raise TypeError(f"communities[{index}].env_kwargs must be a mapping.")

            weight = cls._validate_weight(raw.get("weight", 1.0), index=index)
            configs.append(
                _CommunityConfig(
                    community_id=community_id,
                    schema=raw["schema"],
                    env_kwargs=dict(env_kwargs),
                    weight=weight,
                )
            )

        if sum(config.weight for config in configs) <= 0.0:
            raise ValueError("At least one community weight must be greater than zero.")

        return configs

    @classmethod
    def _validate_community_id(cls, value: Any, *, index: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"communities[{index}].community_id must be a non-empty string.")

        community_id = value.strip()
        if community_id == "":
            raise ValueError(f"communities[{index}].community_id must be a non-empty string.")

        path = Path(community_id)
        if path.is_absolute() or ".." in path.parts or "/" in community_id or "\\" in community_id:
            raise ValueError(f"community_id {community_id!r} must be safe for a relative path.")

        if not cls._COMMUNITY_ID_PATTERN.fullmatch(community_id):
            raise ValueError(
                f"community_id {community_id!r} must contain only letters, numbers, '_', '-' or '.'."
            )

        return community_id

    @staticmethod
    def _validate_weight(value: Any, *, index: int) -> float:
        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"communities[{index}].weight must be a non-negative finite number.") from exc

        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(f"communities[{index}].weight must be a non-negative finite number.")

        return weight

    @staticmethod
    def _resolve_render_directory(render_directory: Union[str, Path]) -> Path:
        project_root = Path(__file__).resolve().parents[1]

        if render_directory is None:
            return (project_root / "render_logs").resolve()

        path = Path(render_directory).expanduser()
        if not path.is_absolute():
            path = project_root / path

        return path.resolve()

    @staticmethod
    def _resolve_render_session_name(render_session_name: str) -> str:
        if render_session_name is None:
            return datetime.datetime.now().strftime("multi_community_%Y-%m-%d_%H-%M-%S")

        session = str(render_session_name).strip()
        if session == "":
            raise ValueError("render_session_name must be non-empty when provided.")

        path = Path(session)
        if path.is_absolute():
            raise ValueError("render_session_name must be a relative path.")

        if ".." in path.parts:
            raise ValueError("render_session_name cannot contain parent directory references ('..').")

        return session

    def _validate_constructor_homogeneity(self):
        interfaces = {env.interface for env in self.envs.values()}
        if len(interfaces) != 1:
            raise ValueError("MultiCommunityEnv v1 requires all communities to use the same interface.")

        central_agent_modes = {bool(env.central_agent) for env in self.envs.values()}
        if len(central_agent_modes) != 1:
            raise ValueError("MultiCommunityEnv v1 requires all communities to use the same central_agent mode.")

        seconds_per_step = {float(env.seconds_per_time_step) for env in self.envs.values()}
        if len(seconds_per_step) != 1:
            raise ValueError("MultiCommunityEnv requires all communities to share seconds_per_time_step.")

        episode_lengths = {int(env.episode_tracker.episode_time_steps) for env in self.envs.values()}
        if len(episode_lengths) != 1:
            raise ValueError("MultiCommunityEnv requires all communities to share the same effective episode length.")

    def _validate_reset_synchronization(self):
        self._validate_constructor_homogeneity()
        time_steps = {int(env.time_step) for env in self.envs.values()}

        if len(time_steps) != 1:
            raise RuntimeError("MultiCommunityEnv reset produced desynchronized child time_step values.")

        durations = {
            int(env.episode_tracker.episode_end_time_step) - int(env.episode_tracker.episode_start_time_step) + 1
            for env in self.envs.values()
        }
        if len(durations) != 1:
            raise ValueError("MultiCommunityEnv reset produced different child episode durations.")

    def _validate_step_synchronization(self):
        time_steps = {int(env.time_step) for env in self.envs.values()}
        if len(time_steps) != 1:
            raise RuntimeError("MultiCommunityEnv child environments became temporally desynchronized.")

    def _validate_action_keys(self, actions: Mapping[str, Any]):
        expected = set(self.community_ids)
        actual = set(actions.keys())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)

        if missing or extra:
            parts = []
            if missing:
                parts.append(f"missing={missing}")
            if extra:
                parts.append(f"unknown={extra}")
            raise KeyError("MultiCommunityEnv.step actions must match community_ids: " + ", ".join(parts))

    def _child_options(self, options: Mapping[str, Any], community_id: str):
        if not isinstance(options, Mapping):
            return options

        if community_id in options and isinstance(options[community_id], Mapping):
            return options[community_id]

        return options

    def _build_info(
        self,
        *,
        child_infos: Mapping[str, Mapping[str, Any]],
        rewards: Mapping[str, Any] = None,
        terminated_by_community: Mapping[str, bool] = None,
        truncated_by_community: Mapping[str, bool] = None,
    ) -> Mapping[str, Any]:
        rewards = {} if rewards is None else rewards
        terminated_by_community = {
            community_id: bool(env.terminated)
            for community_id, env in self.envs.items()
        } if terminated_by_community is None else dict(terminated_by_community)
        truncated_by_community = {
            community_id: bool(env.truncated)
            for community_id, env in self.envs.items()
        } if truncated_by_community is None else dict(truncated_by_community)
        community_rewards_scalar = {
            community_id: self._finite_reward_sum(reward)
            for community_id, reward in rewards.items()
        }
        reward_total = sum(
            self._community_configs[community_id].weight * value
            for community_id, value in community_rewards_scalar.items()
        )
        weight_total = sum(config.weight for config in self._community_configs.values())
        reward_mean_weighted = reward_total / weight_total if weight_total > 0.0 else float("nan")

        return {
            "communities": {
                community_id: {
                    "weight": self._community_configs[community_id].weight,
                    "time_step": int(env.time_step),
                    "episode_start_time_step": int(env.episode_tracker.episode_start_time_step),
                    "episode_end_time_step": int(env.episode_tracker.episode_end_time_step),
                    "info": dict(child_infos.get(community_id, {})),
                }
                for community_id, env in self.envs.items()
            },
            "time_step": self.time_step,
            "community_rewards_scalar": community_rewards_scalar,
            "reward_total": float(reward_total),
            "reward_mean_weighted": float(reward_mean_weighted),
            "terminated_by_community": terminated_by_community,
            "truncated_by_community": truncated_by_community,
        }

    @classmethod
    def _finite_reward_sum(cls, reward: Any) -> float:
        if reward is None:
            return 0.0

        if isinstance(reward, Mapping):
            return sum(cls._finite_reward_sum(value) for value in reward.values())

        try:
            values = np.asarray(reward, dtype="float64").reshape(-1)
        except (TypeError, ValueError):
            try:
                value = float(reward)
            except (TypeError, ValueError):
                return 0.0
            return value if math.isfinite(value) else 0.0

        if values.size == 0:
            return 0.0

        finite = values[np.isfinite(values)]
        return float(finite.sum()) if finite.size else 0.0

    def _portfolio_kpis(self, local: pd.DataFrame) -> pd.DataFrame:
        if local.empty or "level" not in local.columns or "cost_function" not in local.columns:
            return pd.DataFrame(columns=list(local.columns))

        district = local[local["level"] == "district"].copy()
        if district.empty:
            return pd.DataFrame(columns=list(local.columns))

        district["numeric_value"] = pd.to_numeric(district.get("value"), errors="coerce")
        rows: List[Dict[str, Any]] = []
        total_ratios = CityLearnKPIService.total_ratio_components("district")

        for cost_function, group in district.groupby("cost_function", sort=True):
            metric = str(cost_function)
            aggregate: Optional[float]

            if metric in total_ratios:
                aggregate = self._pooled_ratio(district, *total_ratios[metric])
            elif metric.endswith(self._SUM_SUFFIXES):
                values = group["numeric_value"].dropna()
                if values.empty:
                    aggregate = np.nan
                else:
                    aggregate = float(values.sum())
            elif metric.endswith(self._WEIGHTED_MEAN_SUFFIXES):
                aggregate = self._weighted_mean(group)
                if aggregate is None:
                    aggregate = np.nan
            else:
                continue

            row = {column: None for column in local.columns}
            row["cost_function"] = self._portfolio_cost_function(metric)
            row["value"] = aggregate
            row["name"] = self.PORTFOLIO_NAME
            row["level"] = "portfolio"
            row["community_id"] = self.PORTFOLIO_COMMUNITY_ID
            rows.append(row)

        return pd.DataFrame(rows, columns=list(local.columns))

    @staticmethod
    def _pooled_ratio(district: pd.DataFrame, control_name: str, reference_name: str, signed: bool) -> float:
        """Ratio of control and reference totals summed over communities that report both."""

        def totals(name: str) -> pd.Series:
            rows = district[district["cost_function"] == name]
            return rows.set_index("community_id")["numeric_value"]

        paired = pd.concat(
            [totals(control_name), totals(reference_name)], axis=1, keys=["control", "reference"], join="inner",
        ).dropna()

        if paired.empty:
            return np.nan

        ratio = CityLearnKPIService._signed_ratio if signed else CityLearnKPIService._safe_div
        value = ratio(float(paired["control"].sum()), float(paired["reference"].sum()))
        return np.nan if value is None else float(value)

    def _weighted_mean(self, group: pd.DataFrame) -> Optional[float]:
        weighted_sum = 0.0
        weight_sum = 0.0

        for _, row in group.iterrows():
            value = row.get("numeric_value")
            if not np.isfinite(value):
                continue

            community_id = row.get("community_id")
            weight = self._community_configs.get(community_id, _CommunityConfig("", "", {}, 0.0)).weight
            if weight <= 0.0:
                continue

            weighted_sum += float(value) * weight
            weight_sum += weight

        if weight_sum <= 0.0:
            return None

        return weighted_sum / weight_sum

    @staticmethod
    def _portfolio_cost_function(cost_function: str) -> str:
        if cost_function.startswith("district_"):
            return "portfolio_" + cost_function[len("district_"):]

        return "portfolio_" + cost_function

    def _ensure_output_dir(self):
        path = Path(self.render_output_root) / Path(self.render_session_name)
        path = path.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)

        if not self._render_dir_initialized:
            for file_path in path.glob("exported_*.csv"):
                if file_path.is_file():
                    file_path.unlink()
            for file_path in path.glob("exported_*.parquet"):
                if file_path.is_file():
                    file_path.unlink()
            self._render_dir_initialized = True

        self.new_folder_path = str(path)

    def _export_path(self, filepath: str) -> Path:
        path = Path(filepath)
        if path.is_absolute():
            return path

        if ".." in path.parts:
            raise ValueError("filepath cannot contain parent directory references ('..').")

        return Path(self.new_folder_path) / path
