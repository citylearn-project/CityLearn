import logging
from typing import Any, List, Mapping
from gymnasium import spaces
import numpy as np
from citylearn import random_streams
from citylearn.base import Environment
from citylearn.citylearn import CityLearnEnv

LOGGER = logging.getLogger(__name__)


def __getattr__(name: str):
    # Deprecated names of renamed classes resolve to the same class, also for unpickling and import paths.
    if name == 'BaselineAgent':
        from citylearn.agents._renamed import renamed

        return renamed(__name__, 'BaselineAgent', 'NoControlAgent', NoControlAgent)

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

def get_env_attr(env, name: str):
    """Read an attribute from the outermost wrapper that defines it, else from the base environment.

    Gymnasium 1.x removed implicit attribute forwarding through wrappers; ``get_wrapper_attr`` replaces it
    (older gymnasium versions forward attributes through ``Wrapper.__getattr__``).
    """

    getter = getattr(env, 'get_wrapper_attr', None)
    return getter(name) if callable(getter) else getattr(env, name)


def is_entity_interface(env) -> bool:
    """Whether ``env`` (or the environment it wraps) uses the entity interface."""

    return str(getattr(env.unwrapped, 'interface', 'flat')).lower() == 'entity'


def require_flat_interface(env, agent_name: str):
    """Raise a clear error for agents that read flat observation vectors."""

    if is_entity_interface(env):
        raise ValueError(
            f"{agent_name} requires interface='flat': it reads flat observation vectors, while the entity "
            "interface returns entity tables. Use interface='flat', or a controller from "
            "citylearn.agents.baseline, which works with both interfaces."
        )


class Agent(Environment):
    r"""Base agent class.

    Under the entity interface, the environment's ``action_space`` and
    ``observation_space`` are ``spaces.Dict`` objects keyed by entity table. The
    agent then keeps the flat spaces (``flat_action_space`` and
    ``flat_observation_space``) in :attr:`action_space` and
    :attr:`observation_space` and returns flat-like action vectors in
    ``env.action_names`` order, which the entity interface also accepts. Agents
    that read flat observation vectors, such as the reinforcement learning
    controllers, require the flat interface.

    Parameters
    ----------
    env : CityLearnEnv
        CityLearn environment.

    Other Parameters
    ----------------
    **kwargs : dict
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        self.env = env
        self.observation_names = get_env_attr(self.env, 'observation_names')
        self.action_names = self.env.unwrapped.action_names

        if is_entity_interface(self.env):
            self.observation_space = self.env.unwrapped.flat_observation_space
            self.action_space = self.env.unwrapped.flat_action_space
        else:
            self.observation_space = self.env.observation_space
            self.action_space = self.env.action_space

        self.episode_time_steps = self.env.unwrapped.time_steps
        self.building_metadata = self.env.unwrapped.get_metadata()['buildings']
        super().__init__(
            seconds_per_time_step=self.env.unwrapped.seconds_per_time_step,
            random_seed=self.env.unwrapped.random_seed,
            episode_tracker=self.env.unwrapped.episode_tracker,
            time_step_ratio=self.env.unwrapped.time_step_ratio
        )
        # The agent's own random streams follow the derivation of its environment's streams. The default is not
        # stored, so agents saved before the setting existed load with the same attributes as new ones.
        random_stream_version = getattr(self.env.unwrapped, 'random_stream_version', None)

        if random_stream_version != random_streams.DEFAULT_RANDOM_STREAM_VERSION:
            self._set_random_stream(random_stream_version=random_stream_version)
        self.reset()

    @property
    def env(self) -> CityLearnEnv:
        """CityLearn environment."""

        return self.__env

    @property
    def observation_names(self) -> List[List[str]]:
        """Names of active observations that can be used to map observation values."""

        return self.__observation_names
    
    @property
    def action_names(self) -> List[List[str]]:
        """Names of active actions that can be used to map action values."""

        return self.__action_names

    @property
    def observation_space(self) -> List[spaces.Box]:
        """Format of valid observations."""

        return self.__observation_space

    @property
    def action_space(self) -> List[spaces.Box]:
        """Format of valid actions."""

        return self.__action_space
    
    @property
    def episode_time_steps(self) -> int:
        return self.__episode_time_steps

    @property
    def building_metadata(self) -> List[Mapping[str, Any]]:
        """Building(s) metadata."""

        return self.__building_metadata

    @property
    def action_dimension(self) -> List[int]:
        """Number of returned actions."""

        return [s.shape[0] for s in self.action_space]

    @property
    def actions(self) -> List[List[List[Any]]]:
        """Action history; dynamic rows follow :attr:`action_history_ids`."""

        return self.__actions

    @property
    def action_history_ids(self) -> List[str]:
        """Stable row identities, retaining departed members and appending arrivals.

        An empty vector marks a step without an action for that member. A
        centralized history has a single ``central_agent`` row.
        """
        return list(self.__action_history_ids)
    
    @env.setter
    def env(self, env: CityLearnEnv):
        self.__env = env

    @observation_names.setter
    def observation_names(self, observation_names: List[List[str]]):
        self.__observation_names = observation_names

    @action_names.setter
    def action_names(self, action_names: List[List[str]]):
        self.__action_names = action_names

    @observation_space.setter
    def observation_space(self, observation_space: List[spaces.Box]):
        self.__observation_space = observation_space

    @action_space.setter
    def action_space(self, action_space: List[spaces.Box]):
        self.__action_space = action_space

    @episode_time_steps.setter
    def episode_time_steps(self, episode_time_steps: int):
        """Number of time steps in one episode."""

        self.__episode_time_steps = episode_time_steps

    @building_metadata.setter
    def building_metadata(self, building_metadata: List[Mapping[str, Any]]):
        self.__building_metadata = building_metadata

    @actions.setter
    def actions(self, actions: List[List[Any]]):
        env = self.env.unwrapped
        if getattr(env, 'topology_mode', 'static') == 'dynamic':
            ids = ['central_agent'] if env.central_agent else [b.name for b in env.buildings]
            if len(actions) != len(ids):
                raise ValueError('Action vectors must match the current active members.')
            for member_id, action in zip(ids, actions):
                if member_id not in self.__action_history_ids:
                    self.__action_history_ids.append(member_id)
                    self.__actions.append([[] for _ in range(self.time_step + 1)])
                row = self.__actions[self.__action_history_ids.index(member_id)]
                row[self.time_step] = list(action)
            return
        for i in range(len(self.action_space)):
            self.__actions[i][self.time_step] = actions[i]

    def learn(self, episodes: int = None, deterministic: bool = None, deterministic_finish: bool = None, logging_level: int = None):
        """Train agent.

        Parameters
        ----------
        episodes: int, default: 1
            Number of training episode >= 1.
        deterministic: bool, default: False
            Indicator to take deterministic actions i.e. strictly exploit the learned policy.
        deterministic_finish: bool, default: False
            Indicator to take deterministic actions in the final episode.
        logging_level: int, default: 30
            Logging level where increasing the number silences lower level information.
        """
        
        episodes = 1 if episodes is None else episodes
        deterministic_finish = False if deterministic_finish is None else deterministic_finish
        deterministic = False if deterministic is None else deterministic
        self.__set_logger(logging_level)

        env = self.env.unwrapped
        previous_final_export_episode_index = (
            env.plan_final_episode_exports(episodes)
            if hasattr(env, 'plan_final_episode_exports') else None
        )

        try:
            for episode in range(episodes):
                deterministic = deterministic or (deterministic_finish and episode >= episodes - 1)
                observations, _ = self.env.reset()
                self.episode_time_steps = self.episode_tracker.episode_time_steps
                terminated = env.terminated
                truncated = env.truncated
                time_step = 0
                rewards_list = []
                rewards_by_member = {}
                dynamic = getattr(env, 'topology_mode', 'static') == 'dynamic'

                while not (terminated or truncated):
                    actions = self.predict(observations, deterministic=deterministic)
                    reward_ids = ['central_agent'] if env.central_agent else [b.name for b in env.buildings]

                    # apply actions to citylearn_env
                    next_observations, rewards, terminated, truncated, _ = self.env.step(actions)
                    rewards_list.append(rewards)
                    if dynamic:
                        # Rewards belong to the members that executed the step,
                        # before next-step topology events change the live view.
                        for member_id, reward in zip(reward_ids, rewards):
                            rewards_by_member.setdefault(member_id, []).append(float(reward))

                    # update
                    if not deterministic:
                        self.update(observations, actions, rewards, next_observations, terminated=terminated, truncated=truncated)
                    else:
                        pass

                    observations = next_observations

                    LOGGER.debug(
                        f'Time step: {time_step + 1}/{self.episode_time_steps},'\
                            f' Episode: {episode + 1}/{episodes},'\
                                f' Actions: {actions},'\
                                    f' Rewards: {rewards}'
                    )

                    time_step += 1

                if dynamic and rewards_by_member:
                    rewards_summary = {
                        label: {name: float(reduce(values)) for name, values in rewards_by_member.items()}
                        for label, reduce in [('min', np.min), ('max', np.max), ('sum', np.sum), ('mean', np.mean)]
                    }
                elif len(rewards_list) > 0:
                    rewards = np.array(rewards_list, dtype='float')
                    rewards_summary = {
                        'min': rewards.min(axis=0),
                        'max': rewards.max(axis=0),
                        'sum': rewards.sum(axis=0),
                        'mean': rewards.mean(axis=0)
                    }
                else:
                    reward_length = len(self.action_space)
                    empty = np.zeros(reward_length, dtype='float')
                    rewards_summary = {
                        'min': empty,
                        'max': empty,
                        'sum': empty,
                        'mean': empty,
                    }
                LOGGER.info(f'Completed episode: {episode + 1}/{episodes}, Reward: {rewards_summary}')
        finally:
            if hasattr(env, 'plan_final_episode_exports'):
                env._final_export_episode_index = previous_final_export_episode_index

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        """Provide actions for current time step.

        Return randomly sampled actions from `action_space`.
        
        Parameters
        ----------
        observations: List[List[float]]
            Environment observations
        deterministic: bool, default: False
            Wether to return purely exploitatative deterministic actions.

        Returns
        -------
        actions: List[List[float]]
            Action values
        """
        
        self._follow_entity_topology()
        actions = [list(s.sample()) for s in self.action_space]
        self.actions = actions
        self.next_time_step()
        return actions
    
    def _follow_entity_topology(self):
        """Refresh the flat action layout after dynamic topology changes under the entity interface."""

        env = self.env.unwrapped
        if is_entity_interface(env) and getattr(env, 'topology_mode', 'static') == 'dynamic':
            self.action_space = env.flat_action_space
            self.action_names = env.action_names

    def __set_logger(self, logging_level: int = None):
        """Set logging level."""

        if logging_level is None:
            return
        assert logging_level >= 0, 'logging_level must be >= 0'
        # Level of the package logger only; configure handlers (e.g. logging.basicConfig) to see the messages.
        logging.getLogger('citylearn').setLevel(logging_level)

    def update(self, *args, **kwargs):
        """Update replay buffer and networks.
        
        Notes
        -----
        This implementation does nothing but is kept to keep the API for all agents similar during simulation.
        """

        pass

    def _get_seed(self, *key: int) -> int:
        """Seed of one of the agent's random streams, derived from :attr:`random_seed` and `key`.

        Keys in use: ``(0, i)`` for action space ``i`` (see :meth:`_seed_action_spaces`), ``(1, i)`` for the SAC
        replay buffer of action space ``i``, ``(2,)`` for the SAC policy noise and ``(3, i)`` for the MARLISA PCA of
        action space ``i``.
        """

        return int(np.random.SeedSequence(int(self.random_seed), spawn_key=key).generate_state(1)[0])

    def _seed_action_spaces(self):
        """Seed the action spaces that exploration samples from, unless they are already seeded.

        An unseeded gymnasium space seeds itself from OS entropy on first use, so its samples would differ between
        runs with the same :attr:`random_seed`. Space ``i`` is seeded with :meth:`_get_seed` ``(0, i)``. Spaces the
        caller has seeded keep their stream.
        """

        for i, space in enumerate(self.action_space):
            if getattr(space, '_np_random', None) is None:
                space.seed(self._get_seed(0, i))

    def episode_random_generator(self, purpose: str) -> np.random.Generator:
        """Generator of `purpose` for the current episode (``random_stream_version='v2'``).

        The generator is derived from :py:attr:`random_seed`, `purpose` and the episode key of the shared
        episode tracker, and persists for the rest of the episode, so draws within an episode come from one
        stream and every episode starts a new, independent stream. Generators of earlier episodes are dropped.
        """

        episode = self.episode_tracker.random_stream_episode
        generators = getattr(self, '_random_generators', None) or {}

        for key in [k for k in generators if k[0] == purpose and k[1:] != (episode,)]:
            del generators[key]

        return self.random_generator(purpose, episode)

    def next_time_step(self):
        super().next_time_step()

        for history in self.__actions:
            history.append([])

    def reset(self):
        super().reset()
        env = self.env.unwrapped
        self.__action_history_ids = (
            ['central_agent'] if env.central_agent else [b.name for b in env.buildings]
        )
        count = len(self.__action_history_ids) if getattr(env, 'topology_mode', 'static') == 'dynamic' else len(self.action_space)
        self.__actions = [[[]] for _ in range(count)]

class NoControlAgent(Agent):
    r"""Passive no-control agent: every active control action is disabled.

    Up to CityLearn 3.6.0 this class was called ``BaselineAgent``. That name is a deprecated alias that will be
    removed in a later release: in CityLearn, "baseline" names the KPI counterfactual (the same buildings without
    storage, with PV), while this agent controls nothing.

    This agent will provide results for when there is no storage for load shifting and no heat pump partial load. 
    The storage actions prescribed will be 0.0 and the heat pump will have no action, i.e. `None`, causing it to 
    deliver the ideal load in the building time series files. 
    
    To ensure that the environment does not expect non-zero and non-null actions, the buildings in the parsed `env` 
    will be set to have no active actions. This means that you must initialize a new `env` if you want to simulate
    with a new agent type. 
    
    Use :class:`citylearn.agents.baseline.BusinessAsUsualAgent` for the native operational
    business-as-usual baseline that charges EVs, starts deferrables, and controls BESS.

    Parameters
    ----------
    env : CityLearnEnv
        CityLearn environment.

    Other Parameters
    ----------------
    **kwargs : dict
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        super().__init__(env, **kwargs)

    @Agent.env.setter
    def env(self, env: CityLearnEnv):
        Agent.env.fset(self, self.__deactivate_actions(env))

    def __deactivate_actions(self, env: CityLearnEnv) -> CityLearnEnv:
        unwrapped = env.unwrapped
        buildings = {id(b): b for b in list(getattr(unwrapped, '_all_buildings', None) or []) + list(unwrapped.buildings)}
        changed = False

        for b in buildings.values():
            if not b.active_actions:
                continue

            # The native BAU reference is rebuilt with the loaded actions; its configuration check compares them.
            if getattr(b, '_no_control_loaded_active_actions', None) is None:
                b._no_control_loaded_active_actions = sorted(b.active_actions)

            for a in b.action_metadata:
                b.action_metadata[a] = False

            b.action_space = b.estimate_action_space()
            b.observation_space = b.estimate_observation_space()
            changed = True

        if changed and hasattr(unwrapped, '_refresh_action_cache'):
            unwrapped._refresh_action_cache()

            if getattr(unwrapped, '_entity_service', None) is not None:
                unwrapped._entity_service.invalidate()

        return env

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        # A dynamic topology restores the schema's actions at reset and enables those of members and assets that
        # join; disable them again before acting (CityLearn #309).
        self.__deactivate_actions(self.env)
        self._follow_entity_topology()
        actions = [[] for _ in self.action_names]
        self.actions = actions
        self.next_time_step()
        
        return actions
