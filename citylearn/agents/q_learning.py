import math
from typing import Any, List, Tuple
import numpy as np
from citylearn import random_streams
from citylearn.agents.base import Agent, require_flat_interface
from citylearn.citylearn import CityLearnEnv

class TabularQLearning(Agent):
    """Implementation of Tabular Q-Learning algorithm for discrete observation and action space and epsilon-greedy action selection.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    epsilon: float, default: 1.0
        Exploration rate.
    minimum_epsilon: float, default: 0.01
        Minimum value exporation rate can decay to.
    epsilon_decay: float, default: 0.0001
        :code:`epsilon` exponential decay rate.
    learning_rate: float, default: 0.05
        Defines to what degree new knowledge overrides old knowledge: for :code:`learning_rate` = 0, no
        learning happens, while for :code:`learning_rate` = 1, all prior knowledge is lost.
    discount_factor: float, default: 0.90
        Balance between an agent that considers only immediate rewards (:code:`discount_factor` = 0) and
        one that strives towards long term rewards (:code:`discount_factor` = 1)
    q_init_value: float, default: np.nan
        Q-Table initialization value.

    Other Parameters
    ----------------
    **kwargs: Any
        Other keyword arguments used to initialize :py:class:`citylearn.agents.base.Agent` super class.

    Notes
    -----
    Random exploration actions, and the fallback action for observations whose Q-values are all still NaN, are
    sampled from the action spaces. Spaces that are not already seeded are seeded from :attr:`random_seed`, the
    environment's seed, so runs with the same seed are repeatable.
    """
    
    def __init__(
        self, env: CityLearnEnv, epsilon: float = None, minimum_epsilon: float = None, epsilon_decay: float = None, 
        learning_rate: float = None, discount_factor: float = None, q_init_value: float = None, **kwargs: Any,
    ):
        require_flat_interface(env, type(self).__name__)
        super().__init__(env, **kwargs)
        self.epsilon = 1.0 if epsilon is None else epsilon
        self.epsilon_init = self.epsilon
        self.minimum_epsilon = 0.01 if minimum_epsilon is None else minimum_epsilon
        self.epsilon_decay = 0.0001 if epsilon_decay is None else epsilon_decay
        self.learning_rate = 0.05 if learning_rate is None else learning_rate
        self.discount_factor = 0.90 if discount_factor is None else discount_factor
        self.q_init_value = np.nan if q_init_value is None else q_init_value
        self._seed_action_spaces()
        self.q, self.q_exploration, self.q_exploitation = self.__initialize_q()
        self.__explored = False

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        """Provide actions for current time step.

        If `deterministic` = True or, randomly generated number is greater than `epsilon`, return
        deterministic action from Q-Table i.e. action with max Q-value for given observations 
        otherwise, return randomly sampled action.
        
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
        
        deterministic = False if deterministic is None else deterministic
        actions = None

        if deterministic or self.__exploration_draw() > self.epsilon:
            # Use q-function to decide action
            actions = self.__exploit(observations)
            self.__explored = False
        
        else:
            # Explore random action
            actions = [[s.sample()] for s in self.action_space]
            self.__explored = True

        # exponential decay
        episode = int(self.time_step/self.episode_time_steps)
        self.epsilon = max(self.minimum_epsilon, self.epsilon_init*np.exp(-self.epsilon_decay*episode))

        self.actions = actions
        self.next_time_step()
        return actions

    def __exploration_draw(self) -> float:
        """Uniform draw that decides between exploration and exploitation at this time step.

        With ``random_stream_version='v1'`` it is the first value of ``RandomState(random_seed + time_step)``, as in
        CityLearn 3.6.0, so seed ``s`` at time step ``t + 1`` repeats seed ``s + 1`` at time step ``t``. With ``'v2'``
        it is the next value of one generator per episode, derived from :py:attr:`random_seed` and the episode.
        """

        if self.random_stream_version == random_streams.LEGACY_RANDOM_STREAM_VERSION:
            return np.random.RandomState(self.random_seed + self.time_step).random()

        return self.episode_random_generator(random_streams.AGENT_EXPLORATION).random()

    def __exploit(self, observations: List[List[float]]) -> List[List[float]]:
        """Select deterministic actions from Q-Table i.e. action with max Q-value for given observations."""
        
        actions = []

        for i, o in enumerate(observations):
            o = o[0]

            try:
                a = np.nanargmax(self.q[i][o])
            
            except ValueError:
                # when all values for observation are still NaN
                a = self.action_space[i].sample()

            actions.append([a])
        
        return actions

    def update(self, observations: List[List[float]], actions: List[List[float]], reward: List[float], next_observations: List[List[float]], terminated: bool, truncated: bool):
        r"""Update Q-Table using Bellman equation.

        Parameters
        ----------
        observations : List[List[float]]
            Previous time step observations.
        actions : List[List[float]]
            Previous time step actions.
        reward : List[float]
            Current time step reward.
        next_observations : List[List[float]]
            Current time step observations.
        terminated : bool
            Indication that episode has ended.
        truncated : bool
            If episode truncates due to a time limit or a reason that is not defined as part of the task MDP.
        """

        # Compute temporal difference target and error to udpate q-function
        
        for i, (o, a, r, n) in enumerate(zip(observations, actions, reward, next_observations)):
            o, n, a = o[0], n[0], a[0]
            current_q = self.q[i][o, a]
            current_q = 0.0 if math.isnan(current_q) else current_q

            next_q = self.q[i][n]
            # Bellman target uses the best next-state value, not its action index;
            # terminal transitions and unvisited (all-NaN) states contribute zero.
            next_max_q = 0.0 if terminated or np.all(np.isnan(next_q)) else float(np.nanmax(next_q))
            
            # update q
            new_q = current_q + self.learning_rate*(r + self.discount_factor*next_max_q - current_q)
            self.q[i][o, a] = new_q

            # update exploration-exploitation count
            if self.__explored:
                self.q_exploration[i][o, a] += 1
            else:
                self.q_exploitation[i][o, a] += 1

    def __initialize_q(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Initialize all values in Q-Table with `q_init_value`."""
        
        q = [None for _ in self.observation_space]
        q_exploration = [None for _ in self.observation_space]
        q_exploitation = [None for _ in self.observation_space]

        for i, (od, ad) in enumerate(zip(self.observation_space, self.action_space)):
            shape = (od.n, ad.n)
            q[i] = np.ones(shape=shape)*self.q_init_value
            q_exploration[i] = np.zeros(shape=shape)
            q_exploitation[i] = np.zeros(shape=shape)
        
        return q, q_exploration, q_exploitation