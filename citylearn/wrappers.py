import itertools
from typing import Any, List, Mapping, Tuple
from gymnasium import ActionWrapper, Env, ObservationWrapper, RewardWrapper, spaces, Wrapper
import numpy as np
import pandas as pd

try:
    from ray.rllib.env import MultiAgentEnv
except (ModuleNotFoundError, ImportError) as e:
    from gymnasium import Env as MultiAgentEnv

from citylearn.citylearn import CityLearnEnv
from citylearn.building import Building

class ClippedObservationWrapper(ObservationWrapper):
    """Wrapper for observations min-max and periodic normalization.
    
    Observations are clipped to be within the observation space limits.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv) -> None:
        super().__init__(env)
        self.env: CityLearnEnv

    def observation(self, observations: List[List[float]]) -> List[List[float]]:
        """Returns normalized observations."""

        for i, (o, s) in enumerate(zip(observations, self.observation_space)):
            for j, (o_, l, u) in enumerate(zip(o, s.low, s.high)):
                observations[i][j] = min(max(o_, l), u)

        return observations

class NormalizedObservationWrapper(ObservationWrapper):
    """Wrapper for observations min-max and periodic normalization.
    
    Temporal observations including `hour`, `day_type` and `month` are periodically normalized using sine/cosine 
    transformations and then all observations are min-max normalized between 0 and 1.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv) -> None:
        super().__init__(env)
        self.env: CityLearnEnv

    @property
    def shared_observations(self) -> List[str]:
        """Names of common observations across all buildings i.e. observations that have the same value irrespective of the building.
        
        Includes extra three observations added during cyclic transformation of :code:`hour`, :code:`day_type` and :code:`month`.
        """

        shared_observations = []
        periodic_observation_names = list(Building.get_periodic_observation_metadata().keys())

        for o in self.env.unwrapped.shared_observations:
            if o in periodic_observation_names:
                shared_observations += [f'{o}_cos', f'{o}_sin']
            
            else:
                shared_observations.append(o)

        return shared_observations
    
    @property
    def observation_names(self) -> List[List[str]]:
        """Names of returned observations.

        Includes extra three observations added during cyclic transformation of :code:`hour`, :code:`day_type` and :code:`month`.

        Notes
        -----
        If `central_agent` is True, a list of 1 sublist containing all building observation names is returned in the same order as `buildings`. 
        The `shared_observations` names are only included in the first building's observation names. If `central_agent` is False, a list of sublists 
        is returned where each sublist is a list of 1 building's observation names and the sublist in the same order as `buildings`.
        """

        if self.env.unwrapped.central_agent:
            observation_names = []

            for i, b in enumerate(self.env.unwrapped.buildings):
                for k, _ in b.observations(normalize=True, periodic_normalization=True).items():
                    if i == 0 or k not in self.shared_observations or k not in observation_names:
                        observation_names.append(k)
                    
                    else:
                        pass

            observation_names = [observation_names]
        
        else:
            observation_names = [list(b.observations(normalize=True, periodic_normalization=True).keys()) for b in self.env.unwrapped.buildings]

        return observation_names


    @property
    def observation_space(self) -> List[spaces.Box]:
        """Returns observation space for normalized observations."""

        low_limit = []
        high_limit = []

        if self.env.unwrapped.central_agent:
            shared_observations = []

            for i, b in enumerate(self.env.unwrapped.buildings):
                s = b.estimate_observation_space(normalize=True)
                o = b.observations(normalize=True, periodic_normalization=True)

                for k, lv, hv in zip(o, s.low, s.high):                    
                    if i == 0 or k not in self.shared_observations or k not in shared_observations:
                        low_limit.append(lv)
                        high_limit.append(hv)

                    else:
                        pass

                    if k in self.shared_observations and k not in shared_observations:
                        shared_observations.append(k)
                    
                    else:
                        pass
            
            observation_space = [spaces.Box(low=np.array(low_limit), high=np.array(high_limit), dtype=np.float32)]

        else:
            observation_space = [b.estimate_observation_space(normalize=True) for b in self.env.unwrapped.buildings]
        
        return observation_space

    def observation(self, observations: List[List[float]]) -> List[List[float]]:
        """Returns normalized observations.

        Normalizes the values received from the wrapped environment, so changes made upstream (robustness
        sensor faults, other wrappers) reach the agent instead of being replaced by fresh building values.
        """

        env = self.env.unwrapped
        buildings = env.buildings
        raw_names = [list(b.observations(normalize=False, periodic_normalization=False).keys()) for b in buildings]

        if env.central_agent:
            values = list(observations[0])
            env_shared_observations = set(env.shared_observations)
            shared_values = {}
            building_observations = []
            cursor = 0

            # Mirror CityLearnEnv.observations: shared values appear once, in the first building that has them.
            for i, names in enumerate(raw_names):
                building_values = {}

                for k in names:
                    if i == 0 or k not in env_shared_observations or k not in shared_values:
                        if cursor >= len(values):
                            raise ValueError('Observation vector is shorter than the environment observation names.')

                        building_values[k] = values[cursor]
                        cursor += 1

                        if k in env_shared_observations:
                            shared_values.setdefault(k, building_values[k])

                    else:
                        building_values[k] = shared_values[k]

                building_observations.append(building_values)

            if cursor != len(values):
                raise ValueError('Observation vector is longer than the environment observation names.')

        else:
            building_observations = [dict(zip(names, values)) for names, values in zip(raw_names, observations)]

        normalized = [
            b.transform_observations(o, normalize=True, periodic_normalization=True)
            for b, o in zip(buildings, building_observations)
        ]

        if env.central_agent:
            norm_observations = []
            shared_observations = []

            for i, building_values in enumerate(normalized):
                for k, v in building_values.items():
                    if i == 0 or k not in self.shared_observations or k not in shared_observations:
                        norm_observations.append(v)

                    if k in self.shared_observations and k not in shared_observations:
                        shared_observations.append(k)

            norm_observations = [norm_observations]

        else:
            norm_observations = [list(building_values.values()) for building_values in normalized]

        return norm_observations
    
class NormalizedActionWrapper(ActionWrapper):
    """Wrapper for action min-max normalization.
    
    All observations are min-max normalized between 0 and 1.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv) -> None:
        super().__init__(env)
        self.env: CityLearnEnv
        
    @property
    def action_space(self) -> List[spaces.Box]:
        """Returns action space for normalized actions."""

        low_limit = []
        high_limit = []

        if self.env.unwrapped.central_agent:

            for b in self.env.unwrapped.buildings:
                low_limit += [0.0]*b.action_space.low.size
                high_limit += [1.0]*b.action_space.high.size
            
            action_space = [spaces.Box(low=np.array(low_limit), high=np.array(high_limit), dtype=np.float32)]

        else:
            action_space = [spaces.Box(
                low=np.array([0.0]*b.action_space.low.size), 
                high=np.array([1.0]*b.action_space.high.size), 
                dtype=np.float32) 
            for b in self.env.unwrapped.buildings]
        
        return action_space

    def action(self, actions: List[float]) -> List[List[float]]:
        """Returns denormalized actions."""

        transformed_actions = []

        for i, s in enumerate(self.env.unwrapped.action_space):
            transformed_actions_ = []
            
            for j, (l, h) in enumerate(zip(s.low, s.high)):
                a = actions[i][j]*(h - l) + l
                transformed_actions_.append(a)
            
            transformed_actions.append(transformed_actions_)

        return transformed_actions
    
class NormalizedSpaceWrapper(Wrapper):
    """Wrapper for normalized observation and action spaces.

    Wraps `env` in :py:class:`citylearn.wrappers.NormalizedObservationWrapper` and :py:class:`citylearn.wrappers.NormalizedActionWrapper`.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        env = NormalizedObservationWrapper(env)
        env = NormalizedActionWrapper(env)
        super().__init__(env)
        self.env: CityLearnEnv
    
class DiscreteObservationWrapper(ObservationWrapper):
    """Wrapper for observation space discretization.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active observation in each building.
    default_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building observation.
    """

    def __init__(self, env: CityLearnEnv, bin_sizes: List[Mapping[str, int]] = None, default_bin_size: int = None):
        super().__init__(env)
        self.env: CityLearnEnv
        assert bin_sizes is None or len(bin_sizes) == len(self.env.unwrapped.buildings), 'length of bin_size must equal number of buildings.'
        self.bin_sizes = [{} for _ in self.env.unwrapped.buildings] if bin_sizes is None else bin_sizes
        self.default_bin_size = 10 if default_bin_size is None else default_bin_size
        self.bin_sizes = [
            {o: s.get(o, self.default_bin_size) for o in b.active_observations} 
            for b, s in zip(self.env.unwrapped.buildings, self.bin_sizes)
        ]
        
    @property
    def observation_space(self) -> List[spaces.MultiDiscrete]:
        """Returns observation space for discretized observations."""

        if self.env.unwrapped.central_agent:
            bin_sizes = []
            shared_observations = []

            for i, b in enumerate(self.bin_sizes):
                for k, v in b.items():
                    if i == 0 or k not in self.env.unwrapped.shared_observations or k not in shared_observations:
                        bin_sizes.append(v)

                    else:
                        pass

                    if k in self.env.unwrapped.shared_observations and k not in shared_observations:
                        shared_observations.append(k)

                    else:
                        pass
            
            observation_space = [spaces.MultiDiscrete(bin_sizes)]

        else:
            observation_space = [spaces.MultiDiscrete(list(b.values())) for b in self.bin_sizes]
        
        return observation_space
    
    def observation(self, observations: List[List[float]]) -> np.ndarray:
        """Returns discretized observations."""

        transformed_observations = []

        for i, (cs, ds) in enumerate(zip(self.env.unwrapped.observation_space, self.observation_space)):
            transformed_observations_ = []

            for j, (ll, hl, b) in enumerate(zip(cs.low, cs.high, ds)):
                o = np.digitize(observations[i][j], np.linspace(ll, hl, b.n), right=True)
                transformed_observations_.append(o)

            transformed_observations.append(transformed_observations_)
                
        return transformed_observations
    
class DiscreteActionWrapper(ActionWrapper):
    """Wrapper for action space discretization.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active action in each building.
    default_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building action.
    """

    def __init__(self, env: CityLearnEnv, bin_sizes: List[Mapping[str, int]] = None, default_bin_size: int = None):
        super().__init__(env)
        self.env: CityLearnEnv
        assert bin_sizes is None or len(bin_sizes) == len(self.env.unwrapped.buildings), 'length of bin_size must equal number of buildings.'
        self.bin_sizes = [{} for _ in self.env.unwrapped.buildings] if bin_sizes is None else bin_sizes
        self.default_bin_size = 10 if default_bin_size is None else default_bin_size
        self.bin_sizes = [
            {a: s.get(a, self.default_bin_size) for a in b.active_actions} 
            for b, s in zip(self.env.unwrapped.buildings, self.bin_sizes)
        ]
        
    @property
    def action_space(self) -> List[spaces.MultiDiscrete]:
        """Returns action space for discretized actions."""

        if self.env.unwrapped.central_agent:
            bin_sizes = []

            for b in self.bin_sizes:
                for _, v in b.items():
                    bin_sizes.append(v)
            
            action_space = [spaces.MultiDiscrete(bin_sizes)]

        else:
            action_space = [spaces.MultiDiscrete(list(b.values())) for b in self.bin_sizes]

        return action_space

    def action(self, actions: List[float]) -> List[List[float]]:
        """Returns undiscretized actions."""

        transformed_actions = []

        for i, (cs, ds) in enumerate(zip(self.env.unwrapped.action_space, self.action_space)):
            transformed_actions_ = []
            
            for j, (ll, hl, b) in enumerate(zip(cs.low, cs.high, ds)):
                a = np.linspace(ll, hl, b.n)[actions[i][j]]
                transformed_actions_.append(a)
            
            transformed_actions.append(transformed_actions_)

        return transformed_actions
    
class DiscreteSpaceWrapper(Wrapper):
    """Wrapper for observation and action spaces discretization.

    Wraps `env` in :py:class:`citylearn.wrappers.DiscreteObservationWrapper` and :py:class:`citylearn.wrappers.DiscreteActionWrapper`.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    observation_bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active observation in each building.
    action_bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active action in each building.
    default_observation_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building observation.
    default_action_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building action.
    """

    def __init__(self, env: CityLearnEnv, observation_bin_sizes: List[Mapping[str, int]] = None, action_bin_sizes: List[Mapping[str, int]] = None, default_observation_bin_size: int = None, default_action_bin_size: int = None):
        env = DiscreteObservationWrapper(env, bin_sizes=observation_bin_sizes, default_bin_size=default_observation_bin_size)
        env = DiscreteActionWrapper(env, bin_sizes=action_bin_sizes, default_bin_size=default_action_bin_size)
        super().__init__(env)
        self.env: CityLearnEnv

class TabularQLearningObservationWrapper(ObservationWrapper):
    """Observation wrapper for :py:class:`citylearn.agents.q_learning.TabularQLearning` agent.

    Wraps `env` in :py:class:`citylearn.wrappers.DiscreteObservationWrapper`.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active observation in each building.
    default_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building observation.
    """

    def __init__(self, env: CityLearnEnv, bin_sizes: List[Mapping[str, int]] = None, default_bin_size: int = None) -> None:
        env = DiscreteObservationWrapper(env, bin_sizes=bin_sizes, default_bin_size=default_bin_size)
        super().__init__(env)
        self.env: CityLearnEnv
        self.combinations = self.set_combinations()

    @property
    def observation_space(self) -> List[spaces.Discrete]:
        """Returns observation space for discretized observations."""

        observation_space = []

        for c in self.combinations:
            observation_space.append(spaces.Discrete(len(c) - 1))
        
        return observation_space
    
    def observation(self, observations: List[List[int]]) -> List[List[int]]:
        """Returns discretized observations."""

        return [[c.index(tuple(o))] for o, c in zip(observations, self.combinations)]
    
    def set_combinations(self) -> List[List[int]]:
        """Returns all combinations of discrete observations."""

        combs_list = []

        for s in self.env.observation_space:
            options = [list(range(d.n + 1)) for d in s]
            combs = list(itertools.product(*options))
            combs_list.append(combs)

        return combs_list
    
class TabularQLearningActionWrapper(ActionWrapper):
    """Action wrapper for :py:class:`citylearn.agents.q_learning.TabularQLearning` agent.

    Wraps `env` in :py:class:`citylearn.wrappers.DiscreteActionWrapper`.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active action in each building.
    default_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building action.
    """

    def __init__(self, env: CityLearnEnv, bin_sizes: List[Mapping[str, int]] = None, default_bin_size: int = None) -> None:
        env = DiscreteActionWrapper(env, bin_sizes=bin_sizes, default_bin_size=default_bin_size)
        super().__init__(env)
        self.env: CityLearnEnv
        self.combinations = self.set_combinations()

    @property
    def action_space(self) -> List[spaces.Discrete]:
        """Returns action space for discretized actions."""

        action_space = []

        for c in self.combinations:
            action_space.append(spaces.Discrete(len(c)))
        
        return action_space
    
    def action(self, actions: List[float]) -> List[List[int]]:
        """Returns discretized actions."""

        return [list(c[a[0]]) for a, c in zip(actions, self.combinations)]
    
    def set_combinations(self) -> List[List[int]]:
        """Returns all combinations of discrete actions."""

        combs_list = []

        for s in self.env.action_space:
            options = [list(range(d.n)) for d in s]
            combs = list(itertools.product(*options))
            combs_list.append(combs)

        return combs_list
    
class TabularQLearningWrapper(Wrapper):
    """Wrapper for :py:class:`citylearn.agents.q_learning.TabularQLearning` agent.

    Discretizes observation and action spaces.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    observation_bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active observation in each building.
    action_bin_sizes: List[Mapping[str, int]], optional
        Then number of bins for each active action in each building.
    default_observation_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building observation.
    default_action_bin_size: int, default = 10
        The default number of bins if `bin_sizes` is unspecified for any active building action.
    """

    def __init__(self, env: CityLearnEnv, observation_bin_sizes: List[Mapping[str, int]] = None, action_bin_sizes: List[Mapping[str, int]] = None, default_observation_bin_size: int = None, default_action_bin_size: int = None):
        env = TabularQLearningObservationWrapper(env, bin_sizes=observation_bin_sizes, default_bin_size=default_observation_bin_size)
        env = TabularQLearningActionWrapper(env, bin_sizes=action_bin_sizes, default_bin_size=default_action_bin_size)
        super().__init__(env)
        self.env: CityLearnEnv

class StableBaselines3ObservationWrapper(ObservationWrapper):
    """Observation wrapper for :code:`stable-baselines3` algorithms.

    Wraps observations so that they are returned in a 1-dimensional numpy array.
    This wrapper is only compatible when the environment is controlled by a central agent
    i.e., :py:attr:`citylearn.citylearn.CityLearnEnv.central_agent` = True.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert env.unwrapped.central_agent, 'StableBaselines3ObservationWrapper is compatible only when env.central_agent = True.'\
            ' First set env.central_agent = True to use this wrapper.'
        
        super().__init__(env)
        self.env: CityLearnEnv
        
    @property
    def observation_space(self) -> spaces.Box:
        """Returns single spaces Box object."""

        return self.env.observation_space[0]
    
    def observation(self, observations: List[List[float]]) -> np.ndarray:
        """Returns observations as 1-dimensional numpy array."""

        return np.array(observations[0], dtype='float32')

class StableBaselines3ActionWrapper(ActionWrapper):
    """Action wrapper for :code:`stable-baselines3` algorithms.

    Wraps actions so that they are returned in a 1-dimensional numpy array.
    This wrapper is only compatible when the environment is controlled by a central agent
    i.e., :py:attr:`citylearn.citylearn.CityLearnEnv.central_agent` = True.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert env.unwrapped.central_agent, 'StableBaselines3ActionWrapper is compatible only when env.central_agent = True.'\
            ' First set env.central_agent = True to use this wrapper.'
        
        super().__init__(env)
        self.env: CityLearnEnv

    @property
    def action_space(self) -> spaces.Box:
        """Returns single spaces Box object."""

        return self.env.action_space[0]

    def action(self, actions: List[float]) -> List[List[float]]:
        """Returns actions as 1-dimensional numpy array."""

        return [actions]
    
class StableBaselines3RewardWrapper(RewardWrapper):
    """Reward wrapper for :code:`stable-baselines3` algorithms.

    Wraps rewards so that it is returned as float value.
    This wrapper is only compatible when the environment is controlled by a central agent
    i.e., :py:attr:`citylearn.citylearn.CityLearnEnv.central_agent` = True.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert env.unwrapped.central_agent, 'StableBaselines3RewardWrapper is compatible only when env.central_agent = True.'\
            ' First set env.central_agent = True to use this wrapper.'
        
        super().__init__(env)
        self.env: CityLearnEnv

    def reward(self, reward: List[float]) -> float:
        """Returns reward as float value."""

        return reward[0]

class StableBaselines3Wrapper(Wrapper):
    """Wrapper for :code:`stable-baselines3` algorithms.

    Wraps observations so that they are returned in a 1-dimensional numpy array.
    Wraps actions so that they are returned in a 1-dimensional numpy array.
    Wraps rewards so that it is returned as float value.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        env = StableBaselines3ActionWrapper(env)
        env = StableBaselines3RewardWrapper(env)
        env = StableBaselines3ObservationWrapper(env)
        super().__init__(env)
        self.env: CityLearnEnv

class RLlibSingleAgentWrapper(StableBaselines3Wrapper):
    """Wrapper for :code:`RLlib` single-agent algorithms.

    Uses the same wrapper as :code:`stable-baselines3` by wrapping
    `env` in :py:class:`citylearn.wrappers.StableBaselines3Wrapper`.
    
    Parameters
    ----------
    env_config: Mapping[str, Any]
        Dictionary providing initialization parameters for the environment.
        Must contain `env_kwargs` as a key where `env_kwargs` is a `dict` used to 
        initialize :py:class:`citylearn.citylearn.CityLearnEnv`. Thus it must 
        contain all with positional arguments needed for intialization and 
        optionally contain optional  intialization arguments. `env_config` can also 
        contain a `wrappers` key that is a list of :py:mod:`citylearn.wrappers` 
        classes to wrap :py:class:`citylearn.citylearn.CityLearnEnv` with. Wrapping
        with :py:class:`citylearn.wrappers.ClippedObservationWrapper` is recommended
        to avoid having the simulation terminating prematurely with an error due to
        out of bound observations relative to the observation space.

    Notes
    -----
    This wrapper is only compatible with an environment where 
    :py:attr:`citylearn.citylearn.central_agent`=`True` and will initialize the 
    environment as such, overriding any value for `central_agent` in `env_kwargs`.
    """

    def __init__(self, env_config: Mapping[str, Any]):
        env_kwargs = env_config['env_kwargs']
        env_kwargs['central_agent'] = True
        assert 'schema' in env_kwargs, 'missing schema key in env_kwargs.'
        env = CityLearnEnv(**env_kwargs)

        wrappers = env_config.get('wrappers')
        wrappers = [] if wrappers is None else wrappers

        for w in wrappers:
            env = w(env)

        super().__init__(env)

class RLlibMultiAgentObservationWrapper(ObservationWrapper):
    """Observation wrapper for :code:`RLlib` multi-agent algorithms.

    Wraps observation space and observations so that they are returned 
    as :py:class:`gymnasium.spaces.Dict` and `dict` objects respectively.
    The keys in these objects correspond to the agent IDs i.e., 
    policy IDs in the multi-agent.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert not env.unwrapped.central_agent, 'RLlibMultiAgentObservationWrapper is'\
            ' compatible only when env.central_agent = False.'\
                ' First set env.central_agent = False to use this wrapper.'

        super().__init__(env)
        self.env: CityLearnEnv

    @property
    def observation_space(self) -> spaces.Dict:
        """Parses observation space into a :py:class:`gymnasium.spaces.Dict`."""

        return spaces.Dict({f'agent_{i}': s for i, s in enumerate(self.env.observation_space)})

    def observation(
        self, observations: List[List[float]]
    ) -> Mapping[str, np.ndarray]:
        """Parses observation into a dictionary."""

        return {f'agent_{i}': np.array(o, dtype='float32') for i, o in enumerate(observations)}

class RLlibMultiAgentActionWrapper(ActionWrapper):
    """Action wrapper for :code:`RLlib` multi-agent algorithms.

    Wraps action space so that it is returned as :py:class:`gymnasium.spaces.Dict`. 
    The keys correspond to the agent IDs i.e., policy IDs in the multi-agent. 
    Also converts agent actions from `dict` to  data structure need by 
    :py:meth:`citylearn.citylearn.CityLearnEnv.step`.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert not env.unwrapped.central_agent, 'RLlibMultiAgentActionWrapper is'\
            ' compatible only when env.central_agent = False.'\
                ' First set env.central_agent = False to use this wrapper.'

        super().__init__(env)
        self.env: CityLearnEnv

    @property
    def action_space(self) -> spaces.Dict:
        """Parses action space into a :py:class:`gymnasium.spaces.Dict`."""

        return spaces.Dict({f'agent_{i}': s for i, s in enumerate(self.env.action_space)})

    def action(self, actions: Mapping[str, np.ndarray]) -> List[List[float]]:
        """Parses actions into data structure for :py:meth:`citylearn.citylearn.CityLearnEnv.step`."""

        return [list(v) for v in actions.values()]

class RLlibMultiAgentRewardWrapper(RewardWrapper):
    """Action wrapper for :code:`RLlib` multi-agent algorithms.

    Wraps action space so that it is returned as a `dict` mapping agent IDs to reward values.
    
    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    """

    def __init__(self, env: CityLearnEnv):
        assert not env.unwrapped.central_agent, 'RLlibMultiAgentRewardWrapper is'\
            ' compatible only when env.central_agent = False.'\
                ' First set env.central_agent = False to use this wrapper.'

        super().__init__(env)
        self.env: CityLearnEnv

    def reward(self, reward: List[float]) -> Mapping[str, float]:
        """Parses reward into a `dict`."""

        return {f'agent_{i}': r for i, r in enumerate(reward)}

class RLlibMultiAgentEnv(MultiAgentEnv):
    """Wrapper for :code:`RLlib` multi-agent algorithms.

    Converts, observation and action spaces to :py:class:`gymnasium.spaces.Dict`.
    Also converts `observations`, `actions`, `rewards`, `terminated`, and `truncated`
    to dictionaries where necessary. The dictionary keys correspond to the agent IDs i.e., 
    policy IDs in the multi-agent. Agent IDs are accessible through the `_agent_ids` property. 
    The initialized environment is a :py:class:`ray.rllib.env.MultiAgentEnv` object 
    and has an `env` attribute that is :py:class:`citylearn.citylearn.CityLearnEnv` object.
    
    Parameters
    ----------
    env_config: Mapping[str, Any]
        Dictionary providing initialization parameters for the environment.
        Must contain `env_kwargs` as a key where `env_kwargs` is a `dict` used to 
        initialize :py:class:`citylearn.citylearn.CityLearnEnv`. Thus it must 
        contain all with positional arguments needed for intialization and 
        optionally contain optional  intialization arguments. `env_config` can also 
        contain a `wrappers` key that is a list of :py:mod:`citylearn.wrappers` 
        classes to wrap :py:class:`citylearn.citylearn.CityLearnEnv` with. Wrapping
        with :py:class:`citylearn.wrappers.ClippedObservationWrapper` is recommended
        to avoid having the simulation terminating prematurely with an error due to
        out of bound observations relative to the observation space.

    Notes
    -----
    This wrapper is only compatible with an environment where 
    :py:attr:`citylearn.citylearn.central_agent`=`False` and will initialize the 
    environment as such, overriding any value for `central_agent` in `env_kwargs`.
    """
    
    def __init__(self, env_config: Mapping[str, Any]):
        if MultiAgentEnv == Env:
            raise Exception('This functionality requires you to install RLlib.'\
                'You can install RLlib from pip: pip install "ray[rllib]", '\
                    'or for more detailed instructions please visit https://docs.ray.io/en/latest/rllib/index.html.')
        
        else:
            pass

        super().__init__()
        env_kwargs = env_config['env_kwargs']
        env_kwargs['central_agent'] = False
        assert 'schema' in env_kwargs, 'missing schema key in env_kwargs.'
        env = CityLearnEnv(**env_kwargs)

        wrappers = env_config.get('wrappers')
        wrappers = [] if wrappers is None else wrappers

        for w in wrappers:
            env = w(env)

        env = RLlibMultiAgentActionWrapper(env)
        env = RLlibMultiAgentObservationWrapper(env)
        env = RLlibMultiAgentRewardWrapper(env)
        self.env: CityLearnEnv = env
        self._agent_ids = [f'agent_{i}' for i in range(len(self.buildings))]
        self.observation_space: spaces.Dict = self.env.observation_space
        self.action_space: spaces.Dict = self.env.action_space

    @property
    def time_step(self) -> int:
        """Convenience property for :py:meth:`citylearn.citylearn.CityLearnEnv.time_step`."""

        return self.env.unwrapped.time_step

    @property
    def buildings(self) -> List[Building]:
        """Convenience property for :py:meth:`citylearn.citylearn.CityLearnEnv.buildings`."""

        return self.env.unwrapped.buildings
    
    @property
    def terminated(self) -> bool:
        """Convenience property for :py:meth:`citylearn.citylearn.CityLearnEnv.terminated`."""

        return self.env.unwrapped.terminated

    def step(
            self, action_dict: Mapping[str, np.ndarray]
    ) -> Tuple[Mapping[str, np.ndarray], Mapping[str, float], Mapping[str, bool], Mapping[str, bool], Mapping[str, dict]]:
        """Calls :py:meth:`citylearn.citylearn.CityLearnEnv.step` and parses returned values into dictionaries."""

        observations, reward, terminated, truncated, info = self.env.step(action_dict)
        terminated = {'__all__': terminated, **{a: terminated for a in self._agent_ids}}
        truncated = {'__all__': truncated, **{a: truncated for a in self._agent_ids}}
        info = {a: info for a in self._agent_ids}

        return observations, reward, terminated, truncated, info

    def evaluate(self, **kwargs) -> pd.DataFrame:
        """Convenience method for :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate`."""

        return self.env.unwrapped.evaluate(**kwargs)

    def evaluate_v2(self, **kwargs) -> pd.DataFrame:
        """Convenience method for :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate_v2`."""

        return self.env.unwrapped.evaluate_v2(**kwargs)

    def reset(self, *, seed: int = None, options: Mapping[str, Any] = None) -> Tuple[Mapping[str, np.ndarray], Mapping[str, dict]]:
        """Calls :py:meth:`citylearn.citylearn.CityLearnEnv.reset` and parses returned values into dictionaries."""

        observations, info = self.env.reset(seed=seed, options=options)
        info = {a: info for a in self._agent_ids}

        return observations, info
