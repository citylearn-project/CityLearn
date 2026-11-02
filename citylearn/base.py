import hashlib
import random
from typing import Any, List, Mapping, Tuple, Union
import uuid
import numpy as np

class EpisodeTracker:
    """Class for keeping track of current episode time steps for reading observations from data files.

    An EpisodeTracker object is shared amongst the environment, buildings in environment and all descendant 
    building devices. The object however, should be updated at the environment level only so that its changes 
    propagate to all other evironment decscendants. `simulation_start_time_step` and `simulation_end_time_step`
    are useful to separate training data from test data in the same data file. There may be one or more episodes betweeen 
    `simulation_start_time_step` and `simulation_end_time_step` and their values should be defined in `schema` 
    or parsed to :py:class:`citylearn.citylearn.CityLearnEnv.__init__`. Both `simulation_start_time_step` and 
    `simulation_end_time_step` are used to select time series for building device and storage sizing as well as 
    action and observation space estimation in :py:class:`citylearn.buiLding.Building`.

    Parameters
    ----------
    simulation_start_time_step: int
        Time step to start reading from data files. 
    simulation_end_time_step: int
        Time step to end reading from data files.
    """
    
    def __init__(self, simulation_start_time_step: int, simulation_end_time_step: int):
        self.__episode = None
        self.__episode_start_time_step = None
        self.__episode_end_time_step = None
        self.__simulation_start_time_step = simulation_start_time_step
        self.__simulation_end_time_step = simulation_end_time_step
        self.reset_episode_index()

    @property
    def episode(self):
        """Current episode index"""

        return self.__episode
    
    @property
    def episode_time_steps(self):
        """Number of time steps in current episode split."""

        return (self.episode_end_time_step - self.episode_start_time_step) + 1
    
    @property
    def simulation_time_steps(self):
        """Number of time steps between `simulation_start_time_step` and `simulation_end_time_step`."""

        return (self.__simulation_end_time_step - self.__simulation_start_time_step) + 1
    
    @property
    def simulation_start_time_step(self):
        """Time step to start reading from data files."""

        return self.__simulation_start_time_step
    
    @property
    def simulation_end_time_step(self):
        """Time step to end reading from data files."""

        return self.__simulation_end_time_step
    
    @property
    def episode_start_time_step(self):
        """Start time step in current episode split."""

        return self.__episode_start_time_step
    
    @property
    def episode_end_time_step(self):
        """End time step in current episode split."""

        return self.__episode_end_time_step

    def next_episode(self, episode_time_steps: Union[int, List[Tuple[int, int]]], rolling_episode_split: bool, random_episode_split: bool, random_seed: int):
        """Advance to next episode and set `episode_start_time_step` and `episode_end_time_step` for reading data files.
        
        Parameters
        ----------
        episode_time_steps: Union[int, List[Tuple[int, int]]], optional
            If type is `int`, it is the number of time steps in an episode. If type is `List[Tuple[int, int]]]` is provided, it is a list of 
            episode start and end time steps between `simulation_start_time_step` and `simulation_end_time_step`. Defaults to (`simulation_end_time_step` 
        - `simulation_start_time_step`) + 1. Will ignore `rolling_episode_split` if `episode_splits` is of type `List[Tuple[int, int]]]`.
        rolling_episode_split: bool, default: False
            True if episode sequences are split such that each time step is a candidate for `episode_start_time_step` otherwise, False to split episodes 
            in steps of `episode_time_steps`.
        random_episode_split: bool, default: False
            True if episode splits are to be selected at random during training otherwise, False to select sequentially.
        """

        self.__episode += 1
        self.__next_episode_time_steps(
            episode_time_steps,
            rolling_episode_split,
            random_episode_split,
            random_seed,
        )
        
    def __next_episode_time_steps(self, episode_time_steps: Union[int, List[Tuple[int, int]]], rolling_episode_split: bool, random_episode_split: bool, random_seed: int):
        """Sets `episode_start_time_step` and `episode_end_time_step` for reading data files."""

        splits = None

        if isinstance(episode_time_steps, list):
            splits = episode_time_steps

        else:
            if episode_time_steps <= 0:
                raise ValueError(f'episode_time_steps must be >= 1, got {episode_time_steps}.')

            earliest_start_time_step = self.__simulation_start_time_step 
            latest_start_time_step = (self.__simulation_end_time_step + 1) - episode_time_steps

            if latest_start_time_step < earliest_start_time_step:
                raise ValueError(
                    f'episode_time_steps ({episode_time_steps}) exceeds available simulation window '
                    f'({self.simulation_time_steps}). Reduce episode_time_steps or adjust '
                    'simulation_start_time_step/simulation_end_time_step.'
                )
            
            if rolling_episode_split:
                start_time_steps = range(earliest_start_time_step, latest_start_time_step + 1)
            else:
                start_time_steps = range(earliest_start_time_step, latest_start_time_step + 1, episode_time_steps)

            end_time_steps = np.array(start_time_steps, dtype=int) + episode_time_steps - 1
            splits = np.array([start_time_steps, end_time_steps], dtype=int).T
            splits = splits.tolist()

        if len(splits) == 0:
            raise ValueError('No valid episode splits could be created from the provided episode_time_steps.')

        if random_episode_split:
            # A bounded seed per episode also varies for zero and cannot overflow.
            payload = f'{int(random_seed)}:{self.episode}'.encode('ascii')
            seed = int.from_bytes(hashlib.sha256(payload).digest()[:4], 'big')
            nprs = np.random.RandomState(seed)
            ix = 0 if len(splits) == 1 else int(nprs.choice(len(splits)))

        else:
            ix = self.episode%len(splits)

        self.__episode_start_time_step, self.__episode_end_time_step = splits[ix]

    def reset_episode_index(self):
        """Resets episode index to -1 before any simulation."""

        self.__episode = -1

    def set_next_episode_index(self, index):
        """Select a reproducible episode split on the next environment reset."""
        if isinstance(index, bool) or int(index) != index or index < 0:
            raise ValueError('episode_index must be a nonnegative integer')
        self.__episode = int(index)-1

class Environment:
    """Base class for all `citylearn` classes that have a spatio-temporal dimension.

    Parameters
    ----------
    seconds_per_time_step: float, default: 3600.0
        Number of seconds in 1 `time_step` and must be set to >= 1.
    random_seed : int, optional
        Pseudorandom number generator seed for repeatable results.
    simulation_start_time_step: int, optional
        Time step to start reading from data files. Should be set at the :py:class:`citylearn.citylearn.CityLearnEnv` level so that it propagates to other descendant objects.
    simulation_end_time_step: int, optional
        Time step to end reading from data files. Should be set at the :py:class:`citylearn.citylearn.CityLearnEnv` level so that it propagates to other descendant objects.
    episode_tracker: EpisodeTracker, optional
        :py:class:`citylearn.base.EpisodeTracker` object used to keep track of current episode time steps for reading observations from data files.
    """

    DEFAULT_SECONDS_PER_TIME_STEP = 3600.0
    DEFAULT_RANDOM_SEED_RANGE = (0, 100_000_000)
    
    def __init__(self, seconds_per_time_step: float = None, random_seed: int = None, episode_tracker: EpisodeTracker = None, time_step_ratio: int = None):
        self.seconds_per_time_step = seconds_per_time_step
        self.__uid = uuid.uuid4().hex
        self.random_seed = random_seed
        self.__time_step = None
        self.episode_tracker = episode_tracker
        self.time_step_ratio = time_step_ratio

    @property
    def uid(self) -> str:
        r"""Unique environment ID."""

        return self.__uid
    
    @property
    def random_seed(self) -> int:
        """Pseudorandom number generator seed for repeatable results."""

        return self.__random_seed
    
    @property
    def episode_tracker(self) -> EpisodeTracker:
        """:py:class:`citylearn.base.EpisodeTracker` object used to keep track of 
        current episode time steps for reading observations from data files."""

        return self.__episode_tracker
    
    @property
    def time_step_ratio(self) -> int:
        """:py:class:`citylearn.base.EpisodeTracker` object used to keep track of 
        current episode time steps for reading observations from data files."""

        return self.__time_step_ratio

    @property
    def time_step(self) -> int:
        r"""Current environment time step."""

        return self.__time_step

    @property
    def seconds_per_time_step(self) -> float:
        r"""Number of seconds in 1 time step."""

        return self.__seconds_per_time_step
    
    @property
    def numpy_random_state(self) -> np.random.RandomState:
        """Nupy random state object."""

        return np.random.RandomState(self.random_seed)
    
    @random_seed.setter
    def random_seed(self, random_seed: int):
        random_seed = random.randint(*self.DEFAULT_RANDOM_SEED_RANGE) if random_seed is None else random_seed
        self.__random_seed = random_seed

    @seconds_per_time_step.setter
    def seconds_per_time_step(self, seconds_per_time_step: float):
        if seconds_per_time_step is None:
            self.seconds_per_time_step = self.DEFAULT_SECONDS_PER_TIME_STEP
        else:
            assert seconds_per_time_step >= 1, 'seconds_per_time_step >= 1'
            self.__seconds_per_time_step = seconds_per_time_step

    @episode_tracker.setter
    def episode_tracker(self, episode_tracker: EpisodeTracker):
        self.__episode_tracker = episode_tracker
    
    @time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: int):
        self.__time_step_ratio = time_step_ratio

    @time_step.setter
    def time_step(self, time_step: int):
        self.__time_step = time_step    

    def get_metadata(self) -> Mapping[str, Any]:
        """Returns general static information."""

        return {
            'uid': self.uid,
            'random_seed': self.random_seed,
            'simulation_time_steps': self.episode_tracker.simulation_time_steps,
            'seconds_per_time_step': self.seconds_per_time_step,
            'time_step_ratio': self.time_step_ratio,
        }

    def next_time_step(self):
        r"""Advance to next `time_step` value.

        Notes
        -----
        Override in subclass for custom implementation when advancing to next `time_step`.
        """

        self.__time_step += 1

    def reset(self):
        r"""Reset environment to initial state.

        Calls `reset_time_step`.

        Notes
        -----
        Override in subclass for custom implementation when reseting environment.
        """

        self.reset_time_step()

    def reset_time_step(self):
        r"""Reset `time_step` to initial state.

        Sets `time_step` to 0.
        """

        self.__time_step = 0
