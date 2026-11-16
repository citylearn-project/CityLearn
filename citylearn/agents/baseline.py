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
                                            power, up to the user's requested departure SOC; starts
                                            appliances at the first admissible step; the home battery
                                            stores PV surplus and serves local import.
:class:`FullChargeBusinessAsUsualAgent`     Same as BAU but charges every EV to 100%.
:class:`NormalNoBatteryPolicy`              Full-charge BAU without home battery control.
:class:`RBCBasicPolicy`                     Current price and service urgency for EVs and
                                            appliances; battery self-consumption.
:class:`RBCSmartPolicy`                     Price and local PV-surplus forecasts schedule EVs and
                                            appliances; battery combines self-consumption,
                                            arbitrage and reserve. Uses only building-local and
                                            public observations.
:class:`RBCCommunityPolicy`                 Smart plus energy shareable between members. When the
                                            community market is enabled, batteries support expensive
                                            periods once community import reaches a trigger
                                            (15 kW by default). Without a market it acts as Smart.
==========================================  ==========================================================

The policies are ported from the Soft-CPS Algorithms baselines and keep their
audited defaults. Keyword arguments override the engine hyperparameters, for
example ``RBCCommunityPolicy(env, community_import_threshold_kw=10.0)``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Mapping, Optional

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
        self._build_engine()

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
        self._engine = engine
        self._attached_topology_version = None
        self._attach(None)

    def _attach(self, payload: Optional[Mapping[str, Any]]):
        env = self.env.unwrapped
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
            self._layouts.append((len(active), controlled, np.clip(0.0, low, high)))
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
        return self.env.unwrapped._entity_service.observation_payload()

    def predict(self, observations: Any, deterministic: bool = None) -> List[List[float]]:
        env = self.env.unwrapped
        if env.time_step == 0 and self.time_step != 0:
            self.reset()
        payload = self._payload(observations)
        if int(getattr(env, 'topology_version', 0)) != self._attached_topology_version:
            self.action_space = env.flat_action_space
            self.action_names = env.action_names
            self.observation_space = env.flat_observation_space
            self.observation_names = env.observation_names
            self.building_metadata = env.get_metadata()['buildings']
            self._attach(payload)

        _, values = self._flattener.flatten(payload)
        per_building = []
        for (size, controlled, zeros), vector in zip(self._layouts, self._engine.predict(values)):
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
        if getattr(self, '_engine', None) is not None:
            self._build_engine()


class BusinessAsUsualAgent(_RuleBaselineAgent):
    """Reference BAU: immediate EV charging capped by the user's departure SOC.

    A connected EV is charged at once, at maximum power, until it reaches its
    requested departure SOC. The last command is limited to the remaining
    energy gap; when that command is below the charger minimum the EV stops
    slightly below the target instead of overshooting it. Appliances start at
    the first admissible step and the home battery stores local PV surplus and
    serves local import (self-consumption).
    """

    ENGINE_CLASS = engines.NormalTargetPolicy
    DEFINITION_VERSION = 'immediate-user-target-v1'


class FullChargeBusinessAsUsualAgent(_RuleBaselineAgent):
    """BAU variant that charges every connected EV immediately to 100%.

    Compared with :class:`BusinessAsUsualAgent`, the difference includes the
    extra energy delivered to the EVs above their requested departure SOC.
    """

    ENGINE_CLASS = engines.NormalPolicy
    DEFINITION_VERSION = 'immediate-full-charge-v2'


class NormalNoBatteryPolicy(_RuleBaselineAgent):
    """Full-charge BAU that leaves the home battery idle."""

    ENGINE_CLASS = engines.NormalNoBatteryPolicy
    DEFINITION_VERSION = 'immediate-full-charge-no-battery-v2'


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
    same local dispatch as :class:`RBCSmartPolicy`.
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


NormalPolicy = FullChargeBusinessAsUsualAgent
NormalTargetPolicy = BusinessAsUsualAgent
ServiceOnlyBaselineAgent = NormalNoBatteryPolicy
GridAwareBaselineAgent = RBCSmartPolicy
CommunityAwareBaselineAgent = RBCCommunityPolicy


__all__ = [
    'BusinessAsUsualAgent',
    'FullChargeBusinessAsUsualAgent',
    'NormalPolicy',
    'NormalTargetPolicy',
    'NormalNoBatteryPolicy',
    'ServiceOnlyBaselineAgent',
    'RBCBasicPolicy',
    'RBCSmartPolicy',
    'RBCCommunityPolicy',
    'GridAwareBaselineAgent',
    'CommunityAwareBaselineAgent',
    'ZeroActionBaselineAgent',
]
