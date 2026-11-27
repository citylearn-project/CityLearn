from __future__ import annotations

import datetime
import math
import numbers
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from gymnasium import Env

from citylearn.citylearn import CityLearnEnv, EvaluationCondition
from citylearn.internal.kpi import BATTERY_NOMINAL_CAPACITY_ATTR, CityLearnKPIService
from citylearn.internal.kpi_catalogue import kpi_status


__all__ = ["MultiCommunityEnv"]

# Table attribute with the rule of each portfolio row, keyed by its name; the export manifest records it.
PORTFOLIO_AGGREGATION_ATTR = "portfolio_aggregation"


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
    _COMMUNITY_KEYS = ("community_id", "schema", "env_kwargs", "weight")
    _SUM_SUFFIXES = ("_kwh", "_eur", "_kgco2", "_count")
    _WEIGHTED_MEAN_SUFFIXES = ("_ratio", "_percent")
    _MARKET_ENERGY = "district_energy_grid_community_market_"
    _MARKET_COST = "district_cost_community_market_"
    _MARKET_SHARE = "district_solar_self_consumption_community_market_"

    def __init__(
        self,
        *,
        communities: Sequence[Mapping[str, Any]],
        render_directory: Union[str, Path] = None,
        render_session_name: str = None,
        evaluation_window: Any = None,
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
                if evaluation_window is not None and "evaluation_window" not in child_kwargs:
                    child_kwargs["evaluation_window"] = evaluation_window
                child_kwargs["render_directory"] = self.render_output_root
                child_kwargs["render_session_name"] = str(Path(self.render_session_name) / config.community_id)
                # Communities with the same seed and the same member or EV names draw independent values (#462).
                child_kwargs.setdefault("random_stream_namespace", config.community_id)
                env = CityLearnEnv(config.schema, **child_kwargs)
                self.envs[config.community_id] = env
                created_envs.append(env)
            self._validate_constructor_homogeneity()
        except Exception:
            for env in created_envs:
                env.close()
            raise

        self._terminated = any(env._episode_end_flags()[0] for env in self.envs.values())
        self._truncated = any(env._episode_end_flags()[1] for env in self.envs.values())

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
    def done(self) -> bool:
        """Whether the episode is over in any child environment, whatever the reason."""

        return bool(self._terminated or self._truncated)

    @property
    def terminated(self) -> bool:
        """Whether the episode is over, the same as `done`.

        Kept with this meaning so that loops such as `while not env.terminated` keep working, as on
        :class:`CityLearnEnv`. Like theirs, the `terminated` flag that `step()` returns is always `False`.
        """

        return self.done

    @property
    def truncated(self) -> bool:
        """Whether any child environment ended its episode at its time limit, as `step()` reports it."""

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
        self._terminated = any(env._episode_end_flags()[0] for env in self.envs.values())
        self._truncated = any(env._episode_end_flags()[1] for env in self.envs.values())
        return observations, self._build_info(child_infos=child_infos)

    def step(self, actions: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Mapping[str, Any], bool, bool, Mapping[str, Any]]:
        """Apply one action payload per community and advance all child envs once."""

        if self.done:
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
        return observations, rewards, bool(self._terminated), bool(self._truncated), info

    def evaluate_v2(
        self,
        control_condition: EvaluationCondition = None,
        baseline_condition: EvaluationCondition = None,
        comfort_band: float = None,
        include_business_as_usual: bool = True,
        include_battery_health_audit: bool = False,
    ) -> pd.DataFrame:
        """Return each community's KPIs plus portfolio rows aggregated from their district KPIs.

        The table has the columns of :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate_v2` and a
        ``community_id`` column. Each community contributes its ``'building'`` and ``'district'`` rows under its
        own ``community_id``. The ``'portfolio'`` rows (``community_id`` ``'__portfolio__'``, names starting
        ``portfolio_``) aggregate the district rows: ratios of totals are recomputed from the summed totals;
        rates, including the EV departure, thermal-service, flexible-appliance and equity audit rates and the
        useful-PV ratios, are pooled by their count or energy denominators; battery equivalent full cycles,
        capacity fade and EV battery health ratios are pooled by nominal capacity; the ledger's max-residual
        diagnostics take the largest community value; other ``_kwh``/``_eur``/``_kgco2``/``_count`` rows are
        summed; other ratios and percentages are means weighted by the community ``weight``; and other rows
        (``_kw``, ``_c``, ``_hours``) have no portfolio row. Each portfolio ``description`` states its rule, and
        the table attribute ``portfolio_aggregation`` lists the rule of every portfolio row. When some
        communities have a community market and others do not, a community without a market enters the
        portfolio community-market rows with its plain grid settlement: no local trade, its members' grid
        import and export, and its control cost as settled and counterfactual cost. Its own district rows are
        unchanged. The KPI reference guide gives the rule of each family.
        """

        return self._combine_community_kpis({
            community_id: env.evaluate_v2(
                control_condition=control_condition,
                baseline_condition=baseline_condition,
                comfort_band=comfort_band,
                include_business_as_usual=include_business_as_usual,
                include_battery_health_audit=include_battery_health_audit,
            )
            for community_id, env in self.envs.items()
        })

    def _combine_community_kpis(self, community_kpis: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        capacities = {}

        for community_id, community_frame in community_kpis.items():
            frame = community_frame.copy()
            frame["community_id"] = community_id
            frames.append(frame)
            capacities[community_id] = frame.attrs.pop(BATTERY_NOMINAL_CAPACITY_ATTR, {})

        local = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        portfolio = self._portfolio_kpis(local, capacities)
        rules = portfolio.attrs.get(PORTFOLIO_AGGREGATION_ATTR, {})

        if portfolio.empty:
            local.attrs = {PORTFOLIO_AGGREGATION_ATTR: rules}
            return local

        combined = pd.concat([local, portfolio], ignore_index=True)
        # How each portfolio row was aggregated, for the export manifest.
        combined.attrs = {PORTFOLIO_AGGREGATION_ATTR: rules}
        return combined

    MANIFEST_DEFINITION_VERSION = "multi-community-export-v1"
    # Settings every community must share (see `_validate_constructor_homogeneity`), recorded in the manifest.
    _HOMOGENEOUS_SETTINGS = (
        "physics_version", "random_stream_version", "baseline_version", "business_as_usual_ev_charge_target",
        "ev_soc_carryover", "ev_departure_service_tolerance", "ev_departure_within_tolerance", "energy_provenance",
    )

    def set_experiment_identity(self, implementation, version, parameters, observation_access="agent_payload"):
        """Declare the controller of every community for exported paired comparisons.

        Calls :py:meth:`citylearn.citylearn.CityLearnEnv.set_experiment_identity` on each community with the same
        arguments, so each community export and the portfolio manifest record it as ``controller_identity``.
        """

        for env in self.envs.values():
            env.set_experiment_identity(implementation, version, parameters, observation_access=observation_access)

        self._controller_identity = next(iter(self.envs.values()))._controller_identity

    def scorecard(self, kpis: pd.DataFrame = None, level: str = None, **evaluate_kwargs: Any) -> pd.DataFrame:
        """Return the default scorecard rows of :py:meth:`evaluate_v2` for every community and the portfolio.

        The rows are those of `CityLearnEnv.SCORECARD_DEFAULT_KPIS`, with ``portfolio_`` in place of ``district_``
        for the portfolio rows, in that order, then communities in order with the portfolio last.

        Parameters
        ----------
        kpis: pandas.DataFrame, optional
            A table returned by :py:meth:`evaluate_v2`. When omitted, :py:meth:`evaluate_v2` is called with
            `evaluate_kwargs`.
        level: str, optional
            Keep only ``'portfolio'``, ``'district'`` or ``'building'`` rows.
        """

        if kpis is None:
            kpis = self.evaluate_v2(**evaluate_kwargs)
        elif evaluate_kwargs:
            raise TypeError("Pass either kpis or evaluate_v2() arguments to scorecard(), not both.")

        if level is not None and level not in ("portfolio", "district", "building"):
            raise ValueError(f"level must be 'portfolio', 'district', 'building' or None, not {level!r}.")

        order = {name: index for index, name in enumerate(CityLearnEnv.SCORECARD_DEFAULT_KPIS)}
        names = kpis["cost_function"].astype(str).str.replace(r"^portfolio_", "district_", regex=True)
        rows = kpis[names.isin(order)]
        if level is not None:
            rows = rows[rows["level"] == level]

        communities = {community_id: index for index, community_id in enumerate(self.community_ids)}
        communities[self.PORTFOLIO_COMMUNITY_ID] = len(communities)
        return (
            rows.assign(
                _order=names[rows.index].map(order),
                _community=rows["community_id"].map(communities),
            )
            .sort_values(["_order", "_community", "name"], kind="stable")
            .drop(columns=["_order", "_community"])
            .reset_index(drop=True)
        )

    def export_final_kpis(
        self,
        model: Any = None,
        filepath: str = "exported_kpis_multi_community.csv",
        include_business_as_usual: bool = True,
        export_business_as_usual_timeseries: bool = True,
        kpi_round_decimals: int = None,
        export_community_kpis: bool = True,
        community_filepath: str = "exported_kpis.csv",
        include_battery_health_audit: bool = False,
    ) -> Mapping[str, Any]:
        """Export each community's KPIs to its folder and the portfolio table with its manifest.

        The portfolio table has the long :py:meth:`evaluate_v2` format. It is Parquet (``.parquet``) when every
        community uses ``render_file_format='parquet'``, otherwise CSV. Next to it,
        ``<name>.manifest.json`` records the community ids and weights, the settings the communities share, the
        export settings, the rule of each portfolio row, the KPI definitions and, for each community, its
        manifest path and the evidence that :py:func:`citylearn.internal.comparison.compare_manifests` reads, so
        :py:func:`citylearn.internal.comparison.compare_exports` can pair two portfolio exports. Returns the
        manifest.
        """

        if model is not None:
            raise NotImplementedError("MultiCommunityEnv.export_final_kpis does not support model overrides in v1.")

        from citylearn.internal.comparison import manifest_evidence
        from citylearn.internal.experiment import experiment_manifest

        # Evaluate each community once: its own export and the portfolio rows use the same table.
        community_kpis = {
            community_id: env.evaluate_v2(
                include_business_as_usual=include_business_as_usual,
                include_battery_health_audit=include_battery_health_audit,
            )
            for community_id, env in self.envs.items()
        }

        self._ensure_output_dir()
        community_manifests: Dict[str, Mapping[str, Any]] = {}
        manifest_paths: Dict[str, Optional[str]] = {}
        for community_id, env in self.envs.items():
            if export_community_kpis:
                community_manifests[community_id] = env._episode_exporter.export_final_kpis(
                    filepath=community_filepath,
                    include_business_as_usual=include_business_as_usual,
                    export_business_as_usual_timeseries=export_business_as_usual_timeseries,
                    kpi_round_decimals=kpi_round_decimals,
                    include_battery_health_audit=include_battery_health_audit,
                    evaluated_kpis=community_kpis[community_id],
                )
                written = Path(env.new_folder_path) / env._episode_exporter._export_filename(community_filepath)
                manifest_paths[community_id] = self._relative_to_output(written.with_suffix(".manifest.json"))
            else:
                community_manifests[community_id] = experiment_manifest(env)
                manifest_paths[community_id] = None

        kpis = self._combine_community_kpis(community_kpis)
        rules = kpis.attrs.get(PORTFOLIO_AGGREGATION_ATTR, {})

        if kpi_round_decimals is not None:
            kpis = kpis.copy()
            kpis["value"] = pd.to_numeric(kpis["value"], errors="coerce").round(kpi_round_decimals)

        parquet = all(env._episode_exporter._render_file_format() == "parquet" for env in self.envs.values())
        path = self._export_path(filepath)
        path = path.with_suffix(".parquet") if parquet else path
        path.parent.mkdir(parents=True, exist_ok=True)
        if parquet:
            kpis.to_parquet(path, index=False)
        else:
            kpis.to_csv(path, index=False, encoding="utf-8", na_rep="")

        from citylearn import __version__
        from citylearn.utils.file_handler import FileHandler

        manifest = {
            "kind": "multi_community",
            "definition_version": self.MANIFEST_DEFINITION_VERSION,
            "simulator_version": __version__,
            "community_ids": self.community_ids,
            "weights": self.weights,
            "shared_settings": {
                "interface": self.interface,
                "central_agent": self.central_agent,
                "seconds_per_time_step": self.seconds_per_time_step,
                "episode_time_steps": self.episode_time_steps,
                "evaluation_window": dict(next(iter(self.envs.values()))._evaluation_window_effective),
                **{
                    setting: getattr(next(iter(self.envs.values())), setting)
                    for setting in self._HOMOGENEOUS_SETTINGS
                },
            },
            "kpi_export": {
                "include_business_as_usual": bool(include_business_as_usual),
                "include_battery_health_audit": bool(include_battery_health_audit),
                "kpi_round_decimals": kpi_round_decimals,
                "community_kpis_exported": bool(export_community_kpis),
                "file_format": "parquet" if parquet else "csv",
            },
            "controller_identity": getattr(self, "_controller_identity", None),
            "portfolio_aggregation": rules,
            "kpi_definitions": self._kpi_definitions(kpis),
            "communities": {
                community_id: {
                    "weight": self.weights[community_id],
                    "random_stream_namespace": self.envs[community_id].random_stream_namespace,
                    "manifest": manifest_paths[community_id],
                    "comparison_evidence": manifest_evidence(community_manifests[community_id]),
                }
                for community_id in self.community_ids
            },
        }
        FileHandler.write_json(str(path.with_suffix(".manifest.json")), manifest)
        return manifest

    @staticmethod
    def _kpi_definitions(kpis: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Unit and description of every KPI name in the table, portfolio rows with their own description."""

        definitions: Dict[str, Dict[str, Any]] = {}
        if "unit" not in kpis.columns:
            return definitions

        metadata = [column for column in ("unit", "description", "status", "replacement") if column in kpis.columns]
        for record in kpis.drop_duplicates("cost_function")[["cost_function", *metadata]].to_dict("records"):
            name = record.pop("cost_function")
            if record.get("unit") is None or (isinstance(record.get("unit"), float) and np.isnan(record["unit"])):
                continue
            definitions[name] = {
                key: (None if isinstance(value, float) and np.isnan(value) else value) for key, value in record.items()
            }
        return definitions

    def _relative_to_output(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(Path(self.new_folder_path).resolve()).as_posix()
        except ValueError:
            return str(path)

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
            "physics_version": next(iter(self.envs.values())).physics_version,
            "baseline_version": next(iter(self.envs.values())).baseline_version,
            "random_stream_version": next(iter(self.envs.values())).random_stream_version,
            "time_step": self.time_step,
            "render_directory": str(self.render_output_root),
            "render_session_name": self.render_session_name,
            "evaluation_window": dict(next(iter(self.envs.values()))._evaluation_window_effective),
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

            unknown_keys = [key for key in raw if key not in cls._COMMUNITY_KEYS]
            if unknown_keys:
                accepted = ", ".join(cls._COMMUNITY_KEYS)
                names = ", ".join(repr(key) for key in unknown_keys)
                raise ValueError(
                    f"communities[{index}] has unknown key(s) {names}; accepted keys are {accepted}."
                )

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
        if isinstance(value, (bool, np.bool_)):
            raise ValueError(f"communities[{index}].weight must be a non-negative finite number, not a boolean.")

        if not isinstance(value, numbers.Real):
            # float() would also accept numeric strings such as '2'.
            raise ValueError(
                f"communities[{index}].weight must be a non-negative finite number, not {type(value).__name__}."
            )

        try:
            weight = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"communities[{index}].weight must be a non-negative finite number.") from exc

        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(f"communities[{index}].weight must be a non-negative finite number.")

        return weight

    @staticmethod
    def _resolve_render_directory(render_directory: Union[str, Path]) -> Path:
        # Resolve against the working directory, as CityLearnEnv does (not the installed package folder).
        output_base = Path.cwd()

        if render_directory is None:
            return (output_base / "render_logs").resolve()

        path = Path(render_directory).expanduser()
        if not path.is_absolute():
            path = output_base / path

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

        # Portfolio KPIs add up district totals, so every community must use the same definitions.
        # The BAU EV target and the EV SoC carry-over change each community's BAU reference and EV
        # state, so portfolio BAU totals and ratios would otherwise mix two definitions.
        for setting in (
            "physics_version",
            "random_stream_version",
            "baseline_version",
            "business_as_usual_ev_charge_target",
            "ev_soc_carryover",
            # The EV departure thresholds set the min-acceptable and within-tolerance counts that the portfolio
            # adds up, and a community without the provenance ledger has no provenance rows to add.
            "ev_departure_service_tolerance",
            "ev_departure_within_tolerance",
            "energy_provenance",
        ):
            values = {community_id: getattr(env, setting) for community_id, env in self.envs.items()}
            if len(set(values.values())) != 1:
                raise ValueError(
                    f"MultiCommunityEnv requires all communities to share {setting}, got {values}."
                )

        window_configs = [getattr(env, "_evaluation_window_effective", None) or {} for env in self.envs.values()]
        if any(bool(cfg.get("enabled")) for cfg in window_configs):
            window_keys = {
                (bool(cfg.get("enabled")), cfg.get("start"), cfg.get("end"), cfg.get("timezone"))
                for cfg in window_configs
            }
            if len(window_keys) != 1:
                raise ValueError("MultiCommunityEnv requires all communities to share the same evaluation_window.")

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
            community_id: bool(env._episode_end_flags()[0])
            for community_id, env in self.envs.items()
        } if terminated_by_community is None else dict(terminated_by_community)
        truncated_by_community = {
            community_id: bool(env._episode_end_flags()[1])
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

    # How each portfolio row is built from the community district rows; written into the row description and the
    # export manifest. `{over}` names the rows that weight or compose it.
    _PORTFOLIO_RULES = {
        "sum": "sum of the community values",
        "ratio_of_sums": "ratio of the summed totals {over}, over the communities that report both",
        "pooled_mean": (
            "pooled over the communities: their values weighted by {over}, which is the ratio of the summed "
            "numerators and denominators; community weights are not used"
        ),
        "pooled_comparison": "computed from the portfolio values {over}",
        "capacity_pooled": "pooled over the nominal battery capacity of the communities",
        "max": "largest community value",
        "max_difference": "difference of the portfolio maxima {over}",
        "window_sum": "signed sum of the community values, undefined if one of them is undefined",
        "weighted_mean": "mean of the community values weighted by the community weight",
    }

    def _portfolio_kpis(
        self, local: pd.DataFrame, capacities: Mapping[str, Mapping[str, Optional[float]]],
    ) -> pd.DataFrame:
        if local.empty or "level" not in local.columns or "cost_function" not in local.columns:
            return pd.DataFrame(columns=list(local.columns))

        district = local[local["level"] == "district"].copy()
        if district.empty:
            return pd.DataFrame(columns=list(local.columns))

        district["numeric_value"] = pd.to_numeric(district.get("value"), errors="coerce")
        district = self._with_plain_grid_settlement(district, local)
        rows: List[Dict[str, Any]] = []
        rules: Dict[str, Dict[str, Any]] = {}
        total_ratios = CityLearnKPIService.total_ratio_components("district")
        pooled_means = CityLearnKPIService.pooled_mean_components("district")
        pooled_comparisons = CityLearnKPIService.pooled_mean_business_as_usual_comparisons("district")
        pooled_mean_values = {
            metric: self._pooled_mean(district, metric, weights)
            for metric, weights in pooled_means.items()
        }
        capacity_pooled = set()

        def community_capacity(run_name: str, index: pd.Index) -> pd.Series:
            return pd.Series({
                community_id: values.get(run_name, np.nan)
                for community_id, values in capacities.items()
            }, dtype="float64").reindex(index)

        for run_name, suffix in (("control", ""), ("business_as_usual", "_business_as_usual")):
            throughput_name = f"district_battery_total_throughput{suffix}_kwh"
            throughput = district[district["cost_function"] == throughput_name].set_index("community_id")["numeric_value"]
            capacity = community_capacity(run_name, throughput.index)
            nominal_capacity = capacity.sum()
            cycles = np.nan
            if nominal_capacity > 0 and np.isfinite(capacity).all() and np.isfinite(throughput).all():
                cycles = float(throughput.sum() / (2.0 * nominal_capacity))
            pooled_mean_values[f"district_battery_health_equivalent_full_cycles{suffix}_count"] = cycles
            capacity_pooled.add(f"district_battery_health_equivalent_full_cycles{suffix}_count")

            # Capacity fade is capacity lost over nominal capacity, so it pools by nominal capacity (#428).
            fade_name = f"district_battery_health_capacity_fade{suffix}_ratio"
            fade = district[district["cost_function"] == fade_name].set_index("community_id")["numeric_value"]
            if not fade.empty:
                capacity = community_capacity(run_name, fade.index)
                installed = (capacity > 0.0) & np.isfinite(fade)
                pooled_fade = np.nan
                if np.isfinite(capacity).all() and installed.any():
                    pooled_fade = float((fade[installed] * capacity[installed]).sum() / capacity[installed].sum())
                pooled_mean_values[fade_name] = pooled_fade
                capacity_pooled.add(fade_name)

        ev_fade_rows = district[district["cost_function"] == "district_ev_battery_health_capacity_fade_kwh"]
        if not ev_fade_rows.empty:
            ev_fade = ev_fade_rows.set_index("community_id")["numeric_value"]
            ev_cap_fade = community_capacity("ev_control", ev_fade.index)
            ev_nominal_capacity = ev_cap_fade.sum()
            ev_fade_ratio = np.nan
            ev_soh = np.nan
            if ev_nominal_capacity > 0.0 and np.isfinite(ev_cap_fade).all() and np.isfinite(ev_fade).all():
                ev_fade_total = float(np.clip(ev_fade, 0.0, None).sum())
                ev_fade_ratio = float(np.clip(ev_fade_total / ev_nominal_capacity, 0.0, 1.0))
                ev_soh = float(np.clip((ev_nominal_capacity - ev_fade_total) / ev_nominal_capacity, 0.0, 1.0))
            pooled_mean_values["district_ev_battery_health_capacity_fade_ratio"] = ev_fade_ratio
            pooled_mean_values["district_ev_battery_health_terminal_soh_ratio"] = ev_soh
            capacity_pooled.update(("district_ev_battery_health_capacity_fade_ratio",
                                    "district_ev_battery_health_terminal_soh_ratio"))

        ev_efc_name = "district_ev_battery_health_equivalent_full_cycles_count"
        ev_efc_rows = district[district["cost_function"] == ev_efc_name]
        if not ev_efc_rows.empty:
            ev_efc = ev_efc_rows.set_index("community_id")["numeric_value"]
            ev_cap = community_capacity("ev_control", ev_efc.index)
            positive_ev = ev_cap > 0.0
            ev_cycles = np.nan
            if np.isfinite(ev_cap).all() and positive_ev.any() and np.isfinite(ev_efc[positive_ev]).all():
                ev_cycles = float((ev_efc[positive_ev] * ev_cap[positive_ev]).sum() / ev_cap[positive_ev].sum())
            pooled_mean_values[ev_efc_name] = ev_cycles
            capacity_pooled.add(ev_efc_name)

        # The largest residual of the ledger over the communities, not their sum (#428).
        maxima = {}
        for group_name in ("storage", "bus"):
            for suffix in ("", "_business_as_usual"):
                metric = f"district_energy_provenance_{group_name}_max_residual{suffix}_kwh"
                values = district.loc[district["cost_function"] == metric, "numeric_value"].dropna()
                if not values.empty:
                    maxima[metric] = float(values.max())
        maximum_differences = {
            f"district_energy_provenance_{group_name}_max_residual_delta_to_business_as_usual_kwh": (
                f"district_energy_provenance_{group_name}_max_residual_kwh",
                f"district_energy_provenance_{group_name}_max_residual_business_as_usual_kwh",
            )
            for group_name in ("storage", "bus")
        }

        portfolio = self._portfolio_cost_function
        for cost_function, group in district.groupby("cost_function", sort=True):
            metric = str(cost_function)
            aggregate: Optional[float]

            if metric in total_ratios:
                aggregate = self._pooled_ratio(
                    district, *total_ratios[metric],
                    zero_over_zero=CityLearnKPIService.ratio_zero_over_zero(metric),
                )
                rule = ("ratio_of_sums", [portfolio(name) for name in total_ratios[metric][:2]])
            elif metric in pooled_mean_values:
                aggregate = pooled_mean_values[metric]
                rule = (
                    ("capacity_pooled", []) if metric in capacity_pooled
                    else ("pooled_mean", [portfolio(name) for name in pooled_means[metric]])
                )
            elif metric in pooled_comparisons:
                control_name, reference_name, operation = pooled_comparisons[metric]
                control = pooled_mean_values.get(control_name, np.nan)
                reference = pooled_mean_values.get(reference_name, np.nan)
                if operation == "delta":
                    aggregate = float(control - reference) if np.isfinite(control) and np.isfinite(reference) else np.nan
                else:
                    value = CityLearnKPIService._safe_div(
                        control, reference, zero_over_zero=CityLearnKPIService.ratio_zero_over_zero(metric),
                    )
                    aggregate = np.nan if value is None else float(value)
                rule = ("pooled_comparison", [portfolio(control_name), portfolio(reference_name)])
            elif metric in maxima or metric.endswith(("_max_residual_kwh", "_max_residual_business_as_usual_kwh")):
                aggregate = maxima.get(metric, np.nan)
                rule = ("max", [])
            elif metric in maximum_differences:
                control_name, reference_name = maximum_differences[metric]
                control, reference = maxima.get(control_name, np.nan), maxima.get(reference_name, np.nan)
                aggregate = float(control - reference) if np.isfinite(control) and np.isfinite(reference) else np.nan
                rule = ("max_difference", [portfolio(control_name), portfolio(reference_name)])
            elif (
                (metric.startswith("district_energy_grid_window_average_power_") and metric.endswith("_kw"))
                or metric == "district_ev_window_net_exchange_control_kwh"
            ):
                values = group["numeric_value"].dropna()
                if values.empty or len(values) != len(group):
                    aggregate = np.nan
                else:
                    aggregate = float(values.sum())
                rule = ("window_sum", [])
            elif metric.endswith(self._SUM_SUFFIXES):
                values = group["numeric_value"].dropna()
                if values.empty:
                    aggregate = np.nan
                else:
                    aggregate = float(values.sum())
                rule = ("sum", [])
            elif metric.endswith(self._WEIGHTED_MEAN_SUFFIXES):
                aggregate = self._weighted_mean(group)
                if aggregate is None:
                    aggregate = np.nan
                rule = ("weighted_mean", [])
            else:
                continue

            name = portfolio(metric)
            rules[name] = {"rule": rule[0], "over": list(rule[1])}
            row = {column: None for column in local.columns}
            row["cost_function"] = name
            row["value"] = aggregate
            row["name"] = self.PORTFOLIO_NAME
            row["level"] = "portfolio"
            row["community_id"] = self.PORTFOLIO_COMMUNITY_ID
            if "unit" in row:
                row["unit"] = group["unit"].iloc[0]
                row["description"] = self._portfolio_description(rules[name], group["description"].iloc[0])
            if "status" in row:
                # The status of the district row, with the portfolio name of its replacement (#433).
                row["status"], row["replacement"] = kpi_status(name)
            rows.append(row)

        frame = pd.DataFrame(rows, columns=list(local.columns))
        frame.attrs[PORTFOLIO_AGGREGATION_ATTR] = rules
        return frame

    @classmethod
    def _portfolio_description(cls, rule: Mapping[str, Any], district_description: Any) -> str:
        """Portfolio rule, then the district definition the communities report."""

        over = rule.get("over") or []
        text = cls._PORTFOLIO_RULES[rule["rule"]].format(
            over=" and ".join(f"`{name}`" for name in over) if len(over) <= 2 else ", ".join(f"`{n}`" for n in over),
        )
        description = f"Portfolio: {text}."
        if isinstance(district_description, str) and district_description:
            description += f" Each community: {district_description}"
        return description

    def _with_plain_grid_settlement(self, district: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
        """Give communities without a market their plain grid settlement in a mixed portfolio (#373).

        A community without a community market reports zeros in its community-market rows, which are not a
        measurement. Summed into the portfolio, those zeros left the community's grid flows and cost out of the
        portfolio market totals. When at least one community has a market and another has none, the community
        without a market enters the portfolio market rows as it settles with the grid: no local import or export,
        its members' own grid import and export as grid import and export after local trading, its control cost
        as settled and counterfactual cost (with no market, the members' cost is the grid cost), and zero savings
        and operator balance. Its shares of local trade are 0, pooled by its grid flows. Portfolios where every
        community has a market, or none has, are unchanged. Only the frame used for the portfolio rows changes.
        """

        market = {
            community_id: bool(getattr(env, "community_market_enabled", False))
            for community_id, env in self.envs.items()
        }
        without_market = [
            community_id for community_id in district["community_id"].unique()
            if community_id in market and not market[community_id]
        ]
        if not any(market.values()) or not without_market:
            return district

        buildings = local[local["level"] == "building"]
        building_values = pd.to_numeric(buildings.get("value"), errors="coerce")
        added: List[pd.DataFrame] = []

        for community_id in without_market:
            def building_total(name: str) -> float:
                mask = (buildings["community_id"] == community_id) & (buildings["cost_function"] == name)
                values = building_values[mask].dropna()
                return float(values.sum()) if not values.empty else np.nan

            control_cost = district.loc[
                (district["community_id"] == community_id)
                & (district["cost_function"] == "district_cost_total_control_eur"),
                "numeric_value",
            ]
            cost = float(control_cost.iloc[0]) if not control_cost.empty else np.nan
            grid_import = building_total("building_energy_grid_total_import_control_kwh")
            grid_export = building_total("building_energy_grid_total_export_control_kwh")
            days = CityLearnKPIService._simulated_days(self.envs[community_id])
            daily = (lambda value: value/days if days > 0.0 else np.nan)
            totals = {
                "local_import": 0.0,
                "local_export": 0.0,
                "grid_import_after_local": grid_import,
                "grid_export_after_local": grid_export,
            }
            costs = {"settled": cost, "counterfactual": cost, "savings": 0.0}
            values = {}
            for metric, value in totals.items():
                values[f"{self._MARKET_ENERGY}{metric}_total_kwh"] = value
                values[f"{self._MARKET_ENERGY}{metric}_daily_average_kwh"] = daily(value)
            for metric, value in costs.items():
                values[f"{self._MARKET_COST}{metric}_total_eur"] = value
                values[f"{self._MARKET_COST}{metric}_daily_average_eur"] = daily(value)
            values[f"{self._MARKET_COST}operator_balance_total_eur"] = 0.0
            for metric in ("import_share", "local_share_of_demand", "local_share_of_export"):
                values[f"{self._MARKET_SHARE}{metric}_ratio"] = 0.0

            for metric, value in values.items():
                own = (district["community_id"] == community_id) & (district["cost_function"] == metric)
                if own.any():
                    district.loc[own, "numeric_value"] = value
                    continue
                template = district[district["cost_function"] == metric]
                if template.empty:
                    continue
                row = template.iloc[[0]].copy()
                row["community_id"] = community_id
                row["value"] = value
                row["numeric_value"] = value
                added.append(row)

        if added:
            district = pd.concat([district, *added], ignore_index=True)

        return district

    @staticmethod
    def _pooled_mean(district: pd.DataFrame, metric: str, weight_names: Sequence[str]) -> float:
        """Mean of community values weighted by their additive denominators.

        Equals the ratio of the pooled numerator and denominator. Communities
        whose value is undefined carry no weight; NaN when none has weight.
        """

        def values(name: str) -> pd.Series:
            rows = district[district["cost_function"] == name]
            return rows.set_index("community_id")["numeric_value"]

        frame = pd.concat(
            [values(metric)] + [values(name) for name in weight_names],
            axis=1, keys=["value", *range(len(weight_names))], join="inner",
        )
        if frame.empty:
            return np.nan

        weights = frame.drop(columns="value").fillna(0.0).sum(axis=1)
        valid = np.isfinite(frame["value"]) & (weights > 0.0)
        if not valid.any():
            return np.nan

        return float((frame.loc[valid, "value"]*weights[valid]).sum()/weights[valid].sum())

    @staticmethod
    def _pooled_ratio(
        district: pd.DataFrame, control_name: str, reference_name: str, signed: bool,
        zero_over_zero: Optional[float] = 1.0,
    ) -> float:
        """Ratio of control and reference totals summed over communities that report both."""

        def totals(name: str) -> pd.Series:
            rows = district[district["cost_function"] == name]
            return rows.set_index("community_id")["numeric_value"]

        paired = pd.concat(
            [totals(control_name), totals(reference_name)], axis=1, keys=["control", "reference"], join="inner",
        ).dropna()

        if paired.empty:
            return np.nan

        control, reference = float(paired["control"].sum()), float(paired["reference"].sum())
        if signed:
            value = CityLearnKPIService._signed_ratio(control, reference, zero_over_zero=zero_over_zero)
        else:
            value = CityLearnKPIService._safe_div(control, reference, zero_over_zero=zero_over_zero)
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
