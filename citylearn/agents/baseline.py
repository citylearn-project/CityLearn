"""Non-learning reference controllers: business-as-usual (BAU) and rule-based baselines.

All controllers in this module read the same named, unnormalized observations,
built from the entity observation payload (see
:mod:`citylearn.agents._entity_observations`). They work with the flat and the
entity interface and return flat-like action vectors in
``env.action_names`` order.

==========================================  ==========================================================
Agent                                       Behaviour
==========================================  ==========================================================
:class:`BusinessAsUsualAgent`               Reference BAU. Charges a connected EV at once, at full
                                            power, to 100% (default) or up to the user's requested
                                            departure SOC (``ev_charge_target='requested'``);
                                            starts appliances at the first admissible step; the
                                            home battery stores PV surplus and serves local import.
:class:`RBCBasicPolicy`                     Current price and service urgency for EVs and
                                            appliances; battery self-consumption.
:class:`RBCSmartPolicy`                     Price and local PV-surplus forecasts schedule EVs and
                                            appliances; battery combines self-consumption,
                                            arbitrage and reserve. Uses only building-local and
                                            public observations.
:class:`RBCCommunityPolicy`                 Smart plus energy shareable between members. When the
                                            community market is enabled, batteries support expensive
                                            periods once community import reaches a trigger
                                            (15 kW by default). Without a market it shares no energy.
==========================================  ==========================================================

The policies are ported from the Soft-CPS Algorithms baselines and keep their
audited defaults. Keyword arguments override the engine hyperparameters, for
example ``RBCCommunityPolicy(env, community_import_threshold_kw=10.0)``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple

import numpy as np
from gymnasium import spaces

from citylearn.agents import _baseline_engine as engines
from citylearn.agents._entity_observations import EntityObservationFlattener
from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv


class _RuleBaselineAgent(Agent):
    """CityLearn agent wrapper around a rule-based baseline engine."""

    ENGINE_CLASS: ClassVar[type] = engines.NormalTargetPolicy
    DEFINITION_VERSION: ClassVar[str] = ''
    # Values the Algorithms configuration layer resolves for every rule policy;
    # without them the engines fall back to the BAU self-consumption threshold.
    DEFAULT_HYPERPARAMETERS: ClassVar[Mapping[str, Any]] = {
        'community_surplus_threshold_kw': 0.25,
        'storage_discharge_import_threshold_kw': 0.25,
    }

    def __init__(self, env: CityLearnEnv, **hyperparameters: Any):
        self._hyperparameters: Dict[str, Any] = dict(hyperparameters)
        self._engine = None
        self._flattener: Optional[EntityObservationFlattener] = None
        self._layouts: List[Any] = []
        self._attached_topology_version: Optional[int] = None
        super().__init__(env)
        # Entity-interface envs also accept flat-like action payloads. Keep
        # agent bookkeeping in flat space so the policy works in both modes.
        self.observation_space = self.env.unwrapped.flat_observation_space
        self.action_space = self.env.unwrapped.flat_action_space
        self.reset()
        # The engine parses the schema and the EV files once; resets keep it.
        self._engine = self._build_engine()
        # No observation payload exists yet, so the first attach builds one.
        # Later attaches reuse the payload passed to predict().
        self._attach(None)

    @property
    def hyperparameters(self) -> Dict[str, Any]:
        """Hyperparameters passed to the policy engine (explicit overrides only)."""

        return dict(self._hyperparameters)

    def _build_engine(self):
        env = self.env.unwrapped
        config = {
            'algorithm': {'hyperparameters': {**self.DEFAULT_HYPERPARAMETERS, **self._hyperparameters}},
            'simulator': {
                'schema': env.schema if isinstance(env.schema, dict) else None,
                'root_directory': getattr(env, 'root_directory', None),
            },
        }
        engine = self.ENGINE_CLASS(config)
        unknown = sorted(key for key in self._hyperparameters if not hasattr(engine, key))
        if unknown:
            raise ValueError(f'{type(self).__name__} got unknown hyperparameters: {unknown}.')
        return engine

    def _attach(self, payload: Optional[Mapping[str, Any]]):
        env = self.env.unwrapped
        if getattr(env, 'topology_mode', 'static') == 'dynamic':
            # Members and assets can change between steps and episodes.
            self.action_space = env.flat_action_space
            self.action_names = env.action_names
            self.observation_space = env.flat_observation_space
            self.observation_names = env.observation_names
            self.building_metadata = env.get_metadata()['buildings']
        self._flattener = EntityObservationFlattener(env.entity_specs)
        names, _ = self._flattener.flatten(self._payload(payload))
        buildings = env.buildings
        # The engines control batteries, EV chargers and flexible appliances.
        # Other active actions (HVAC, thermal storage, ...) receive zero,
        # clipped to their bounds, as in earlier CityLearn baselines.
        self._layouts = []
        engine_names, engine_spaces = [], []
        for building in buildings:
            active = list(building.active_actions)
            low = np.asarray(building.action_space.low, dtype='float64')
            high = np.asarray(building.action_space.high, dtype='float64')
            controlled = [i for i, name in enumerate(active) if self._is_controlled_action(name)]
            idx = np.asarray(controlled, dtype=int)
            self._layouts.append((controlled, np.clip(0.0, low, high)))
            engine_names.append([active[i] for i in controlled])
            engine_spaces.append(spaces.Box(low=low[idx], high=high[idx], dtype='float64'))
        self._engine.attach_environment(
            observation_names=names,
            action_names=engine_names,
            action_space=engine_spaces,
            observation_space=[None for _ in buildings],
            metadata={
                'seconds_per_time_step': env.seconds_per_time_step,
                'building_names': [b.name for b in buildings],
                'community_market': {
                    'enabled': bool(getattr(env, 'community_market_enabled', False)),
                    'local_price_ratio_to_grid_import': getattr(env, 'community_market_sell_ratio', 1.0),
                    'grid_export_price': getattr(env, 'community_market_grid_export_price', 0.0),
                },
            },
        )
        self._attached_topology_version = int(getattr(env, 'topology_version', 0))

    @staticmethod
    def _is_controlled_action(name: str) -> bool:
        return (
            name == 'electrical_storage'
            or name.startswith('electric_vehicle_storage')
            or name.startswith('deferrable_appliance')
        )

    def _payload(self, observations: Any) -> Mapping[str, Any]:
        if isinstance(observations, Mapping) and 'tables' in observations:
            return observations
        env = self.env.unwrapped
        payload = env._entity_service.observation_payload()
        if observations is not None and len(observations) > 0:
            # Flat interface: the env corrupts only the flat vectors, so apply
            # this step's robustness observation events as the entity interface
            # does. predict([]), used by the native BAU reference, stays uncorrupted.
            payload = env._robustness_service.entity_observation_view(payload)
        return payload

    def predict(self, observations: Any, deterministic: bool = None) -> List[List[float]]:
        env = self.env.unwrapped
        if env.time_step == 0 and self.time_step != 0:
            self.reset()
        payload = self._payload(observations)
        if int(getattr(env, 'topology_version', 0)) != self._attached_topology_version:
            self._attach(payload)

        _, values = self._flattener.flatten(payload)
        per_building = []
        for (controlled, zeros), vector in zip(self._layouts, self._engine.predict(values)):
            full = [float(v) for v in zeros]
            for position, value in zip(controlled, vector):
                full[position] = float(value)
            per_building.append(full)
        actions = [[v for vector in per_building for v in vector]] if env.central_agent else per_building
        self.actions = actions
        self.next_time_step()
        return actions

    def comparison_identity(self):
        from citylearn import __version__
        parameters = {'definition_version': self.DEFINITION_VERSION}
        if hasattr(self, 'ev_charge_target'):
            parameters['ev_charge_target'] = self.ev_charge_target
        for key, value in sorted(vars(self._engine).items()):
            if key.startswith('_') or not isinstance(value, (bool, int, float, str)):
                continue
            if isinstance(value, float) and not np.isfinite(value):
                continue
            parameters[key] = value
        return dict(
            implementation=type(self).__module__ + '.' + type(self).__qualname__,
            version=__version__, parameters=parameters, observation_access='entity_observations',
        )

    def reset(self):
        super().reset()
        engine = self._engine
        if engine is None:
            return
        # The dataset info and the attachment depend on the schema and the
        # observation layout, not on the episode. Clear only the caches.
        engine._dispatch_budgets = {}
        engine._obs_match_cache = {}
        engine._storage_suffix_cache = {}
        if getattr(self.env.unwrapped, 'topology_mode', 'static') == 'dynamic':
            # Reset restores the initial members and assets and replays the
            # topology events, so attach again to the next observation payload.
            self._attached_topology_version = None


class BusinessAsUsualAgent(_RuleBaselineAgent):
    """Reference BAU: immediate EV charging, earliest appliance start, PV self-consumption.

    A connected EV is charged at once and at maximum power. With
    ``ev_charge_target='full'`` (default, ``immediate-full-charge-v2``) it charges
    to 100%, as the BAU of CityLearn 3.1–3.3 did. With
    ``ev_charge_target='requested'`` (``immediate-user-target-v1``) it stops at the
    user's requested departure SOC: the last command is limited to the remaining
    energy gap, and when that command is below the charger minimum the EV stops
    slightly below the target instead of overshooting it. Appliances start at the first admissible
    step and the home battery stores local PV surplus and serves local import.

    Choose the BAU that ``evaluate_v2()`` uses with the environment's
    ``business_as_usual_ev_charge_target``.
    """

    EV_CHARGE_TARGETS: ClassVar[Mapping[str, Tuple[type, str]]] = {
        'requested': (engines.NormalTargetPolicy, 'immediate-user-target-v1'),
        'full': (engines.NormalPolicy, 'immediate-full-charge-v2'),
    }
    ENGINE_CLASS = engines.NormalPolicy
    DEFINITION_VERSION = 'immediate-full-charge-v2'

    def __init__(self, env: CityLearnEnv, ev_charge_target: str = 'full', **hyperparameters: Any):
        self.ENGINE_CLASS, self.DEFINITION_VERSION = self.definition(ev_charge_target)
        self.ev_charge_target = str(ev_charge_target)
        super().__init__(env, **hyperparameters)

    @classmethod
    def definition(cls, ev_charge_target: str) -> Tuple[type, str]:
        """Engine class and definition version of a BAU ``ev_charge_target``."""

        try:
            return cls.EV_CHARGE_TARGETS[str(ev_charge_target)]
        except KeyError:
            raise ValueError(
                f"ev_charge_target must be one of {sorted(cls.EV_CHARGE_TARGETS)}, got {ev_charge_target!r}."
            ) from None


class RBCBasicPolicy(_RuleBaselineAgent):
    """Current-price and service-urgency scheduling with battery self-consumption.

    EVs receive the minimum charge that meets their departure target, raised to
    ``ev_price_charge_rate`` when the current price is cheap. Appliances start
    when urgent or cheap. The default price thresholds
    (``basic_cheap_price_eur_kwh=0.0765``, ``basic_expensive_price_eur_kwh=0.1078``)
    are the terciles of the 2023 Portuguese day-ahead price; set them for other
    tariffs, or use ``basic_price_policy='forecast_relative'`` to compare the
    current price with the price forecast instead.
    """

    ENGINE_CLASS = engines.RBCBasicPolicy
    DEFINITION_VERSION = 'basic-v2'


class RBCSmartPolicy(_RuleBaselineAgent):
    """Forecast-aware, strictly building-local rule-based controller.

    Price and local PV-surplus forecasts schedule EV charging and appliance
    starts; the home battery combines self-consumption, price arbitrage and a
    service reserve. Community observations are ignored.
    """

    ENGINE_CLASS = engines.RBCSmartLocalPolicy
    DEFINITION_VERSION = 'smart-local-v2'


class RBCCommunityPolicy(_RuleBaselineAgent):
    """Smart controller extended with community energy sharing.

    With the community market enabled, shareable surplus from other members is
    treated as discounted energy, and batteries help during expensive periods
    once community import reaches ``community_import_threshold_kw`` (15 kW by
    default; a trigger, not a hard cap). Without a community market it uses the
    same economic rules as :class:`RBCSmartPolicy`, without sharing energy, but it
    is not restricted to building-local observations.
    """

    ENGINE_CLASS = engines.RBCCommunityPolicy
    DEFINITION_VERSION = 'community-v2'


class ZeroActionBaselineAgent(Agent):
    """Baseline that requests zero for every action dimension."""

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        actions = [np.zeros(space.shape, dtype='float32').tolist() for space in self.action_space]
        self.actions = actions
        self.next_time_step()
        return actions




__all__ = [
    'BusinessAsUsualAgent',
    'RBCBasicPolicy',
    'RBCSmartPolicy',
    'RBCCommunityPolicy',
    'ZeroActionBaselineAgent',
]
