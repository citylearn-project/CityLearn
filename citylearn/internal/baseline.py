from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import pandas as pd

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


@dataclass
class BusinessAsUsualBaselineResult:
    """Cached result for an operational business-as-usual sidecar run."""

    env: "CityLearnEnv"
    kpis_v2: pd.DataFrame
    episode: int
    time_step: int


class CityLearnBusinessAsUsualBaselineService:
    """Runs and caches the native business-as-usual baseline for an env."""

    def __init__(self, env: "CityLearnEnv"):
        self.env = env

    def run(self, force: bool = False) -> BusinessAsUsualBaselineResult:
        from citylearn.agents.baseline import BusinessAsUsualAgent

        env = self.env
        from citylearn.internal.temporal import input_changes
        if input_changes(getattr(env, '_input_snapshot', {})):
            raise ValueError('Native BAU inputs changed since loading; restore inputs or evaluate without the native reference')
        target_time_step = int(getattr(env, 'time_step', 0))
        episode = int(getattr(env.episode_tracker, 'episode', 0))
        cache_key = (episode, target_time_step)
        cache: Dict[Tuple[int, int], BusinessAsUsualBaselineResult] = getattr(
            env,
            '_business_as_usual_baseline_cache',
            {},
        )

        if not force and cache_key in cache:
            return cache[cache_key]

        # Keep only the latest result. Within an episode the time step only moves forward and reset
        # clears the cache, so an earlier entry is never read again, yet each holds a whole sidecar
        # env. Dropping it before building the next one also keeps at most one sidecar alive.
        self.clear()
        baseline_env = self._new_sidecar_env()
        baseline_env.random_seed = env.random_seed
        agent = BusinessAsUsualAgent(baseline_env)
        baseline_env.reset()
        # Pair the away-EV stochastic stream with the source episode, including
        # repeated resets; a freshly constructed sidecar has a different episode index.
        import numpy as np
        baseline_env._ev_drift_seed = env._ev_drift_seed
        baseline_env._ev_drift_random_state = np.random.RandomState(env._ev_drift_seed)
        from citylearn import __version__
        from citylearn.internal.comparison import equipment, equipment_differences, inventory
        if inventory(baseline_env) != env._comparison_initial_inventory:
            raise ValueError('Native BAU initial inventory differs from the evaluated episode')
        # The inventory covers batteries and EVs only; heat pumps, heaters and storage tanks are sized too.
        differences = equipment_differences(env._comparison_initial_equipment, equipment(baseline_env))
        if differences:
            shown = '; '.join(differences[:3]) + ('; ...' if len(differences) > 3 else '')
            raise ValueError(
                f'Native BAU equipment differs from the evaluated env in {len(differences)} parameter(s) '
                f'(evaluated vs reference): {shown}. The reference rebuilds devices from the schema, so it '
                'cannot follow devices changed after loading; evaluate without the native reference '
                '(include_business_as_usual=False) in that case.'
            )
        baseline_env._native_reference_metadata = dict(
            implementation='citylearn.agents.baseline.BusinessAsUsualAgent', simulator_version=__version__,
            definition_version=agent.DEFINITION_VERSION, observation_access='privileged_simulator_state',
            resolved_parameters={key: getattr(agent, key) for key in (
                'ev_target_soc', 'ev_follow_required_soc', 'ev_service_margin_rate', 'ev_service_floor_rate',
                'storage_min_soc', 'storage_max_soc', 'storage_deadband_kw', 'deferrable_start_action')},
        )

        while int(baseline_env.time_step) < target_time_step and not (baseline_env.terminated or baseline_env.truncated):
            actions = agent.predict([], deterministic=True)
            baseline_env._runtime_service.step_without_feedback(actions)

        kpis_v2 = baseline_env.evaluate_v2(include_business_as_usual=False)
        result = BusinessAsUsualBaselineResult(
            env=baseline_env,
            kpis_v2=kpis_v2,
            episode=episode,
            time_step=target_time_step,
        )
        env._business_as_usual_baseline_cache = {cache_key: result}
        return result

    def clear(self):
        self.env._business_as_usual_baseline_cache = {}

    def _new_sidecar_env(self) -> "CityLearnEnv":
        env = self.env
        schema = deepcopy(env.schema)
        if isinstance(schema, dict):
            schema['render'] = False
            schema['render_mode'] = 'none'
            schema['export_kpis_on_episode_end'] = False
            schema['debug_timing'] = False
            schema['metrics_log_interval'] = 0

        source_buildings = list(getattr(env, '_all_buildings', None) or env.buildings)
        source_evs = list(getattr(env, '_all_electric_vehicles', None) or env.electric_vehicles)
        building_names: Optional[List[str]] = [building.name for building in source_buildings] if source_buildings else None
        ev_names: Optional[List[str]] = [ev.name for ev in source_evs] if source_evs else None

        tracker = env.episode_tracker
        start = int(getattr(tracker, 'episode_start_time_step', 0) or 0)
        end = int(getattr(tracker, 'episode_end_time_step', max(start, getattr(env, 'time_steps', 1) - 1)) or start)
        simulation_start, simulation_end = start, end

        if self._autosizes_equipment(schema, building_names):
            # Autosizing (batteries, PV, heat pumps, storage) reads the whole loaded data window, so
            # loading only this episode sizes different equipment than the evaluated env. Load the
            # source's window instead; the one explicit split still restricts the run to the episode.
            simulation_start = int(getattr(tracker, 'simulation_start_time_step', start))
            simulation_end = int(getattr(tracker, 'simulation_end_time_step', end))

        requires_entity_interface = (
            getattr(env, 'topology_mode', None) == 'dynamic'
            or bool(getattr(getattr(env, '_demand_response_service', None), 'enabled', False))
        )

        baseline_env = env.__class__(
            schema,
            root_directory=getattr(env, 'root_directory', None),
            buildings=building_names,
            electric_vehicles=ev_names,
            simulation_start_time_step=simulation_start,
            simulation_end_time_step=simulation_end,
            episode_time_steps=[(start, end)],
            rolling_episode_split=False,
            random_episode_split=False,
            seconds_per_time_step=float(getattr(env, 'seconds_per_time_step', 3600.0)),
            central_agent=True,
            random_seed=getattr(env, '_initialization_seed', env.random_seed),
            offline=getattr(env, 'offline', False),
            time_step_ratio=getattr(env, 'time_step_ratio', None),
            interface='entity' if requires_entity_interface else 'flat',
            topology_mode=getattr(env, 'topology_mode', None),
            render_mode='none',
            export_kpis_on_episode_end=False,
            ev_departure_within_tolerance=env.ev_departure_within_tolerance,
            ev_departure_service_tolerance=env.ev_departure_service_tolerance,
            check_observation_limits=False,
            physics_invariant_checks=bool(getattr(env, 'physics_invariant_checks', False)),
            # The effective setting, which a constructor override may have changed from the schema's.
            energy_provenance=bool(getattr(env, 'energy_provenance', True)),
            **deepcopy(getattr(env, '_constructor_overrides', {})),
        )
        baseline_env._business_as_usual_sidecar = True
        return baseline_env

    @staticmethod
    def _autosizes_equipment(schema, building_names: Optional[List[str]]) -> bool:
        """Whether a building the sidecar loads sizes a device from its data.

        Without autosizing, equipment does not depend on the loaded window, so the sidecar can
        load just the episode, which is much cheaper for long or fine-grained datasets.
        """
        from citylearn.utilities import parse_bool

        buildings = schema.get('buildings', {}) if isinstance(schema, dict) else {}
        for name in (buildings if building_names is None else building_names):
            config = buildings.get(name)
            if not isinstance(config, dict):
                return True  # Unknown configuration: load the source's window to be safe.
            for device in config.values():
                if not isinstance(device, dict):
                    continue
                try:
                    if parse_bool(device.get('autosize', False), default=False):
                        return True
                except (TypeError, ValueError):
                    return True
        return False
