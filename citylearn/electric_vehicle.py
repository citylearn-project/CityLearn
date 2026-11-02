import logging
from typing import List, Mapping, Tuple
from gymnasium import spaces
import numpy as np
from citylearn.base import Environment, EpisodeTracker
from citylearn.energy_model import Battery
from citylearn.preprocessing import Normalize, PeriodicNormalization

ZERO_DIVISION_PLACEHOLDER = 0.000001
LOGGER = logging.getLogger()

class ElectricVehicle(Environment):

    def __init__(self, episode_tracker: EpisodeTracker,
                 battery: Battery = None, name: str = None, **kwargs):
        """
        Initialize the EVCar class.

        Parameters
        ----------
        battery : Battery
            An instance of the Battery class.
        name : str, optional
            Unique Electric_Vehicle name.

        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments used to initialize super class.
        """

        self.name = name

        super().__init__(
            seconds_per_time_step=kwargs.get('seconds_per_time_step'),
            random_seed=kwargs.get('random_seed'),
            episode_tracker=episode_tracker,
            time_step_ratio=battery.time_step_ratio
        )

        self.battery = battery
        self.__observation_epsilon = 0.0  # to avoid out of bound observations


    @property
    def name(self) -> str:
        """Unique building name."""

        return self.__name

    @property
    def battery(self) -> Battery:
        """Battery for Electric_Vehicle."""

        return self.__battery

    @name.setter
    def name(self, name: str):
        self.__name = name
    
    @battery.setter
    def battery(self, battery: Battery):
        if battery is None:
            raise AttributeError("Battery set to None")
        else:
            self.__battery = battery

    def next_time_step(self) -> Mapping[int, str]:
        self.battery.next_time_step()
        super().next_time_step()

    def reset(self):
        """
        Reset the EVCar to its initial state.
        """

        super().reset()
        self.battery.reset()
        self._arrival_soc_time_step = None

    def observation_soc_index(self, previous_index):
        """An exogenous arrival SOC is known before this step's control action."""
        return self.time_step if getattr(self, '_arrival_soc_time_step', None) == self.time_step else previous_index

    def observations(self) -> Mapping[str, float]:
        r"""Observations at current time step.

        Parameters
        ----------

        Returns
        -------
        observations
        """
        unwanted_keys = ["electric_vehicle_charger_state", "charger", "electric_vehicle_soc_arrival"]

        observations = {
            **{
                k.lstrip('_'): v[self.time_step]
                for k, v in vars(self).items()
                if isinstance(v, np.ndarray) and k.lstrip('_') not in unwanted_keys
                # Ensure filtering is done after stripping
            },
            'electric_vehicle_soc': self.battery.soc[self.time_step]
        }

        return observations

    # --- String / Object Representation Methods ---

    def __str__(self) -> str:
        """
        Return a text representation of the current state.
        """
        return str(self.as_dict())

    def as_dict(self) -> dict:
        """
        Return a dictionary representation of the current state for use in rendering or logging.
        """
        return {
            'name': self.name,
            'Battery capacity': self.battery.capacity,  
            **self.observations() 
        }

    def render_simulation_end_data(self) -> dict:
        """
        Return a dictionary containing all simulation data across all time steps.
        The returned dictionary is structured with a general simulation name and, for each time step,
        a dictionary with the simulation data and battery data.

        Returns
        -------
        result : dict
            A JSON-like dictionary with the simulation name and per-time-step data.
        """
        # Determine the number of time steps.
        num_steps = self.episode_tracker.episode_time_steps

        # Gather simulation attributes (only those that are numpy arrays).
        # Build a list of dictionaries for each time step.
        time_steps = []
        for i in range(num_steps):
            step_data = {"time_step": i, "battery": {}}

            # Add battery data for this time step.
            soc_value = self.battery.soc[i]
            if isinstance(soc_value, np.generic):
                soc_value = soc_value.item()
            step_data["battery"] = {
                "soc": soc_value,
                "capacity": self.battery.capacity  # capacity is assumed constant over time.
            }

            time_steps.append(step_data)

        result = {
            "simulation_name": self.name if self.name else "ElectricVehicleSimulation",
            "data": time_steps
        }
        return result
