import logging
from typing import Any, List, Mapping
from gymnasium import spaces
import numpy as np
from citylearn.base import Environment
from citylearn.citylearn import CityLearnEnv

LOGGER = logging.getLogger()

class Agent(Environment):
    r"""Base agent class.

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
        self.observation_names = self.env.observation_names
        self.action_names = self.env.unwrapped.action_names
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
                terminated = self.env.terminated
                truncated = self.env.truncated
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

                    logging.debug(
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
                logging.info(f'Completed episode: {episode + 1}/{episodes}, Reward: {rewards_summary}')
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
        
        actions = [list(s.sample()) for s in self.action_space]
        self.actions = actions
        self.next_time_step()
        return actions
    
    def __set_logger(self, logging_level: int = None):
        """Set logging level."""

        logging_level = 30 if logging_level is None else logging_level
        assert logging_level >= 0, 'logging_level must be >= 0'
        LOGGER.setLevel(logging_level)

    def update(self, *args, **kwargs):
        """Update replay buffer and networks.
        
        Notes
        -----
        This implementation does nothing but is kept to keep the API for all agents similar during simulation.
        """

        pass

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

class BaselineAgent(Agent):
    r"""Passive no-control baseline where active control actions are disabled.

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
        for b in env.unwrapped.buildings:
            for a in b.action_metadata:
                b.action_metadata[a] = False

            b.action_space = b.estimate_action_space()
            b.observation_space = b.estimate_observation_space()

        return env

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        actions = [[] for _ in self.action_names]
        self.actions = actions
        self.next_time_step()
        
        return actions
