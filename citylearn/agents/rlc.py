from typing import Any, List
import warnings
import numpy as np
from citylearn.citylearn import CityLearnEnv
from citylearn.preprocessing import Encoder, PeriodicNormalization, Normalize, OnehotEncoding

# conditional imports
try:
    import torch
except (ModuleNotFoundError, ImportError) as e:
    raise Exception("This functionality requires you to install torch. You can install torch by : pip install torch torchvision, or for more detailed instructions please visit https://pytorch.org.")

from citylearn.agents.base import Agent

class RLC(Agent):
    r"""Base reinforcement learning controller class.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    hidden_dimension : List[float], default: [256, 256]
        Hidden dimension.
    discount : float, default: 0.99
        Discount factor.
    tau : float, default: 5e-3
        Decay rate.
    alpha: float, default: 0.2
        Temperature; exploration-exploitation balance term.
    lr : float, default: 3e-4
        Learning rate.
    batch_size : int, default: 256
        Batch size.
    replay_buffer_capacity : int, default: 1e5
        Replay buffer capacity.
    standardize_start_time_step : int, optional
        Time step to calculate mean and standard deviation, and begin standardization of observations and rewards in replay buffer. Defaults to :py:attr:`citylearn.citylearn.CityLearnEnv.time_steps` - 2.
    end_exploration_time_step : int, optional
        Time step to stop random or RBC-guided exploration. Defaults to :py:attr:`citylearn.citylearn.CityLearnEnv.time_steps` - 1.
    action_scaling_coefficient : float, default: 0.5
        Action scaling coefficient.
    reward_scaling : float, default: 5.0
        Reward scaling.
    update_per_time_step : int, default: 2
        Number of updates per time step.
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
            
    def __init__(
        self, env: CityLearnEnv, hidden_dimension: List[float] = None, 
        discount: float = None, tau: float = None, alpha: float = None, lr: float = None, batch_size: int = None,
        replay_buffer_capacity: int = None, standardize_start_time_step: int = None, end_exploration_time_step: int = None, 
        action_scaling_coefficient: float = None, reward_scaling: float = None,
        update_per_time_step: int = None, **kwargs: Any
    ):
        # Earlier releases only accepted the misspelled keyword, so the documented
        # spelling was swallowed by **kwargs and the 0.5 default always applied.
        misspelled = kwargs.pop('action_scaling_coefficienct', None)
        if misspelled is not None:
            warnings.warn(
                '`action_scaling_coefficienct` is deprecated; use `action_scaling_coefficient`.',
                DeprecationWarning,
                stacklevel=2,
            )
            if action_scaling_coefficient is not None and action_scaling_coefficient != misspelled:
                raise TypeError(
                    'Got conflicting `action_scaling_coefficient` and deprecated `action_scaling_coefficienct` values.'
                )
            action_scaling_coefficient = misspelled

        super().__init__(env, **kwargs)
        self.hidden_dimension = hidden_dimension
        self.discount = discount
        self.tau = tau
        self.alpha = alpha
        self.lr = lr
        self.batch_size = batch_size
        self.replay_buffer_capacity = replay_buffer_capacity
        self.standardize_start_time_step = standardize_start_time_step
        self.end_exploration_time_step = end_exploration_time_step
        self.action_scaling_coefficient = action_scaling_coefficient
        self.reward_scaling = reward_scaling
        self.update_per_time_step = update_per_time_step
        self.encoders = self.set_encoders()

    @property
    def observation_dimension(self) -> int:
        """Number of observations after applying `encoders`."""

        return [len([j for j in np.hstack(e*np.ones(len(s.low))) if j != None]) for e, s in zip(self.encoders, self.observation_space)]

    @property
    def hidden_dimension(self) -> List[float]:
        """Hidden dimension."""

        return self.__hidden_dimension

    @property
    def discount(self) -> float:
        """Discount factor."""

        return self.__discount

    @property
    def tau(self) -> float:
        """Decay rate."""

        return self.__tau

    @property
    def alpha(self) -> float:
        """Temperature; exploration-exploitation balance term."""

        return self.__alpha
    
    @property
    def lr(self) -> float:
        """Learning rate."""

        return self.__lr

    @property
    def batch_size(self) -> int:
        """Batch size."""

        return self.__batch_size

    @property
    def replay_buffer_capacity(self) -> int:
        """Replay buffer capacity."""

        return self.__replay_buffer_capacity

    @property
    def standardize_start_time_step(self) -> int:
        """Time step to calculate mean and standard deviation, and begin standardization of observations and rewards in replay buffer. Defaults to :py:attr:`citylearn.citylearn.CityLearnEnv.time_steps` - 2."""

        return self.__standardize_start_time_step

    @property
    def end_exploration_time_step(self) -> int:
        """Time step to stop exploration.  Defaults to :py:attr:`citylearn.citylearn.CityLearnEnv.time_steps` - 1."""

        return self.__end_exploration_time_step

    @property
    def action_scaling_coefficient(self) -> float:
        """Action scaling coefficient."""

        return self.__action_scaling_coefficient

    @property
    def reward_scaling(self) -> float:
        """Reward scaling."""

        return self.__reward_scaling

    @property
    def update_per_time_step(self) -> int:
        """Number of updates per time step."""

        return self.__update_per_time_step

    @hidden_dimension.setter
    def hidden_dimension(self,  hidden_dimension: List[float]):
        self.__hidden_dimension = [256, 256] if hidden_dimension is None else hidden_dimension

    @discount.setter
    def discount(self, discount: float):
        self.__discount = 0.99 if discount is None else discount

    @tau.setter
    def tau(self, tau: float):
        self.__tau = 5e-3 if tau is None else tau
    
    @alpha.setter
    def alpha(self, alpha: float):
        self.__alpha = 0.2 if alpha is None else alpha
    
    @lr.setter
    def lr(self, lr: float):
        self.__lr = 3e-4 if lr is None else lr

    @batch_size.setter
    def batch_size(self, batch_size: int):
        self.__batch_size = 256 if batch_size is None else batch_size

    @replay_buffer_capacity.setter
    def replay_buffer_capacity(self, replay_buffer_capacity: int):
        self.__replay_buffer_capacity = 1e5 if replay_buffer_capacity is None else replay_buffer_capacity

    @standardize_start_time_step.setter
    def standardize_start_time_step(self, standardize_start_time_step: int):
        self.__standardize_start_time_step = self.episode_time_steps - 1 if standardize_start_time_step is None else standardize_start_time_step

    @end_exploration_time_step.setter
    def end_exploration_time_step(self, end_exploration_time_step: int):
        self.__end_exploration_time_step = self.episode_time_steps if end_exploration_time_step is None else end_exploration_time_step

    @action_scaling_coefficient.setter
    def action_scaling_coefficient(self, action_scaling_coefficient: float):
        self.__action_scaling_coefficient = 0.5 if action_scaling_coefficient is None else action_scaling_coefficient

    @reward_scaling.setter
    def reward_scaling(self, reward_scaling: float):
        self.__reward_scaling = 5.0 if reward_scaling is None else reward_scaling

    @update_per_time_step.setter
    def update_per_time_step(self, update_per_time_step: int):
        update_per_time_step = 2 if update_per_time_step is None else update_per_time_step
        assert isinstance(update_per_time_step,int), f'update_per_time_step mut be int type. {update_per_time_step} is of {type(update_per_time_step)} type'
        self.__update_per_time_step = update_per_time_step

    @Agent.random_seed.setter
    def random_seed(self, seed: int):
        Agent.random_seed.fset(self, seed)
        torch.manual_seed(self.random_seed)

    def set_encoders(self) -> List[List[Encoder]]:
        r"""Get observation value transformers/encoders for use in agent algorithm.

        The encoder classes are defined in the `preprocessing.py` module and include `PeriodicNormalization` for cyclic observations,
        `OnehotEncoding` for categorical obeservations, `RemoveFeature` for non-applicable observations given available storage systems and devices
        and `Normalize` for observations with known minimum and maximum boundaries.
        
        Returns
        -------
        encoders : List[List[Encoder]]
            Encoder classes for observations ordered with respect to `active_observations`.
        """

        encoders = []

        for o, s in zip(self.observation_names, self.observation_space):
            e = []

            for i, n in enumerate(o):
                if n in ['month', 'hour']:
                    e.append(PeriodicNormalization(s.high[i]))
            
                elif n == 'day_type':
                    e.append(OnehotEncoding([1, 2, 3, 4, 5, 6, 7, 8]))
            
                elif n == "daylight_savings_status":
                    e.append(OnehotEncoding([0, 1]))
            
                else:
                    e.append(Normalize(s.low[i], s.high[i]))

            encoders.append(e)

        return encoders