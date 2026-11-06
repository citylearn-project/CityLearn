from typing import Any, Iterable, List, Mapping, Optional, Set, Tuple, Union
import numpy as np
from citylearn.building import Building
from citylearn.data import ZERO_DIVISION_PLACEHOLDER
from citylearn.internal.scalars import numpy1_scalar
import logging

LOGGER = logging.getLogger()
class RewardFunction:
    r"""Base and default reward function class.

    The default reward is the electricity consumption from the grid at the current time step returned as a negative value.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    **kwargs : dict
        Other keyword arguments for custom reward calculation.
    """
    
    def __init__(self, env_metadata: Mapping[str, Any], exponent: float = None, **kwargs):
        penalty_coefficient = kwargs.pop('charging_constraint_penalty_coefficient', None)
        self.env_metadata = env_metadata
        self.exponent = exponent
        self.charging_constraint_penalty_coefficient = penalty_coefficient

    @property
    def env_metadata(self) -> Mapping[str, Any]:
        return self._env_metadata

    @env_metadata.setter
    def env_metadata(self, env_metadata: Mapping[str, Any]):
        self._env_metadata = env_metadata
    
    @property
    def central_agent(self) -> bool:
        """Expect 1 central agent to control all buildings."""

        return self.env_metadata['central_agent']
    
    @property
    def exponent(self) -> float:
        return self.__exponent

    @exponent.setter
    def exponent(self, exponent: float):
        self.__exponent = 1.0 if exponent is None else exponent

    @property
    def charging_constraint_penalty_coefficient(self) -> float:
        return getattr(self, '_charging_constraint_penalty_coefficient', 1.0)

    @charging_constraint_penalty_coefficient.setter
    def charging_constraint_penalty_coefficient(self, coefficient: float):
        if coefficient is None:
            self._charging_constraint_penalty_coefficient = 1.0
        else:
            self._charging_constraint_penalty_coefficient = float(coefficient)

    def reset(self):
        """Use to reset variables at the start of an episode."""

        pass

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        """Declare inputs of the built-in calculation; custom rewards remain unrestricted."""

        if type(self) is RewardFunction and 'calculate' not in self.__dict__:
            return ('net_electricity_consumption',)
        return None

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        r"""Calculates reward.

        Parameters
        ----------
        observations: List[Mapping[str, Union[int, float]]]
            List of all building observations at current :py:attr:`citylearn.citylearn.CityLearnEnv.
            time_step` that are got from calling :py:meth:`citylearn.building.Building.observations`.

        Returns
        -------
        reward: List[float]
            Reward for transition to current timestep.
        """

        net_electricity_consumption = [o['net_electricity_consumption'] for o in observations]
        reward_list = [-(max(o, 0)**numpy1_scalar(self.exponent)) for o in net_electricity_consumption]

        if self.central_agent:
            reward = [sum(reward_list, numpy1_scalar(0))]
        else:
            reward = reward_list

        return reward
    
class MultiBuildingRewardFunction(RewardFunction):
    def __init__(self, env, reward_functions: dict[str, RewardFunction]):
        self.env = env
        self.reward_functions = reward_functions
        super().__init__(env)

    def calculate(self, observations: list[dict]) -> list[float]:
        # Each building's function sees only that building, so it yields one value; collect them flat
        # and aggregate for a central agent like every other reward function.
        rewards = []
        for obs, (building_name, rf) in zip(observations, self.reward_functions.items()):
            if rf is None:
                raise ValueError(f"No reward function for building '{building_name}'")

            rewards.extend(float(value) for value in np.asarray(rf.calculate([obs]), dtype=float).reshape(-1))

        return [sum(rewards)] if self.central_agent else rewards

    def reset(self):
        for rf in self.reward_functions.values():
            rf.reset()

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        required: Set[str] = set()

        for rf in self.reward_functions.values():
            names = rf.get_required_observation_names()
            if names is None:
                return None
            required.update(names)

        return required

    @property
    def env_metadata(self):
        return self._env_metadata

    @env_metadata.setter
    def env_metadata(self, env_metadata: Mapping[str, Any]):
        self._env_metadata = env_metadata
        for rf in self.reward_functions.values():
            rf.env_metadata = env_metadata
    

class MARL(RewardFunction):
    """MARL reward function class.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    """

    def __init__(self, env_metadata: Mapping[str, Any]):
        super().__init__(env_metadata)

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        return ('net_electricity_consumption',)

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        net_electricity_consumption = [o['net_electricity_consumption'] for o in observations]
        district_electricity_consumption = sum(net_electricity_consumption, numpy1_scalar(0))
        building_electricity_consumption = np.array(net_electricity_consumption, dtype=float)*-1
        reward_list = np.sign(building_electricity_consumption)*0.01*building_electricity_consumption**2*np.nanmax([0, district_electricity_consumption])

        if self.central_agent:
            reward = [reward_list.sum()]
        else:
            reward = reward_list.tolist()
        
        return reward

class IndependentSACReward(RewardFunction):
    """Recommended for use with the `SAC` controllers.
    
    Returned reward assumes that the building-agents act independently of each other, without sharing information through the reward.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    """
    
    def __init__(self, env_metadata: Mapping[str, Any]):
        super().__init__(env_metadata)

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        return ('net_electricity_consumption',)

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        net_electricity_consumption = [o['net_electricity_consumption'] for o in observations]
        reward_list = [min(v*numpy1_scalar(-1**3), 0) for v in net_electricity_consumption]

        if self.central_agent:
            reward = [sum(reward_list, numpy1_scalar(0))]
        else:
            reward = reward_list

        return reward
    
class SolarPenaltyReward(RewardFunction):
    """The reward is designed to minimize electricity consumption and maximize solar generation to charge energy storage systems.

    The reward is calculated for each building, i and summed to provide the agent with a reward that is representative of all the
    building or buildings (in centralized case)it controls. It encourages net-zero energy use by penalizing grid load satisfaction 
    when there is energy in the energy storage systems as well as penalizing net export when the energy storage systems are not
    fully charged through the penalty term. There is neither penalty nor reward when the energy storage systems are fully charged
    during net export to the grid. Whereas, when the energy storage systems are charged to capacity and there is net import from the 
    grid the penalty is maximized.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    """

    def __init__(self, env_metadata: Mapping[str, Any]):
        super().__init__(env_metadata)

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        return (
            'net_electricity_consumption',
            'cooling_storage_soc',
            'heating_storage_soc',
            'dhw_storage_soc',
            'electrical_storage_soc',
        )

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        reward_list = []

        for o, m in zip(observations, self.env_metadata['buildings']):
            e = o['net_electricity_consumption']
            cc = m['cooling_storage']['capacity']
            hc = m['heating_storage']['capacity']
            dc = m['dhw_storage']['capacity']
            ec = m['electrical_storage']['capacity']
            cs = o.get('cooling_storage_soc', 0.0)
            hs = o.get('heating_storage_soc', 0.0)
            ds = o.get('dhw_storage_soc', 0.0)
            es = o.get('electrical_storage_soc', 0.0)
            reward = 0.0
            reward += -(1.0 + np.sign(e)*cs)*abs(e) if cc > ZERO_DIVISION_PLACEHOLDER else 0.0
            reward += -(1.0 + np.sign(e)*hs)*abs(e) if hc > ZERO_DIVISION_PLACEHOLDER else 0.0
            reward += -(1.0 + np.sign(e)*ds)*abs(e) if dc > ZERO_DIVISION_PLACEHOLDER else 0.0
            reward += -(1.0 + np.sign(e)*es)*abs(e) if ec > ZERO_DIVISION_PLACEHOLDER else 0.0
            reward_list.append(reward)

        if self.central_agent:
            reward = [sum(reward_list, numpy1_scalar(0))]
        else:
            reward = reward_list
        
        return reward
    
class ComfortReward(RewardFunction):
    """Reward for occupant thermal comfort satisfaction.

    The reward is calculated as the negative difference between the setpoint and indoor dry-bulb temperature raised to some exponent
    if outside the comfort band. If within the comfort band, the reward is the negative difference when in cooling mode and temperature
    is below the setpoint or when in heating mode and temperature is above the setpoint. The reward is 0 if within the comfort band
    and above the setpoint in cooling mode or below the setpoint and in heating mode.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    band: float, default: 2.0
        Setpoint comfort band (+/-). If not provided, the comfort band time series defined in the
        building file, or the default time series value of 2.0 is used.
    lower_exponent: float, default = 2.0
        Penalty exponent for when in cooling mode but temperature is above setpoint upper
        boundary or heating mode but temperature is below setpoint lower boundary.
    higher_exponent: float, default = 2.0
        Penalty exponent for when in cooling mode but temperature is below setpoint lower
        boundary or heating mode but temperature is above setpoint upper boundary.
    """
    
    def __init__(self, env_metadata: Mapping[str, Any], band: float = None, lower_exponent: float = None, higher_exponent: float = None):
        super().__init__(env_metadata)
        self.band = band
        self.lower_exponent = lower_exponent
        self.higher_exponent = higher_exponent

    @property
    def band(self) -> float:
        return self.__band
    
    @property
    def lower_exponent(self) -> float:
        return self.__lower_exponent
    
    @property
    def higher_exponent(self) -> float:
        return self.__higher_exponent
    
    @band.setter
    def band(self, band: float):
        self.__band = band

    @lower_exponent.setter
    def lower_exponent(self, lower_exponent: float):
        self.__lower_exponent = 2.0 if lower_exponent is None else lower_exponent

    @higher_exponent.setter
    def higher_exponent(self, higher_exponent: float):
        self.__higher_exponent = 2.0 if higher_exponent is None else higher_exponent

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        reward_list = []

        for o in observations:
            heating_demand = o.get('heating_demand', 0.0)
            cooling_demand = o.get('cooling_demand', 0.0)
            heating = heating_demand > cooling_demand
            hvac_mode = o['hvac_mode']
            indoor_dry_bulb_temperature = o['indoor_dry_bulb_temperature']

            if hvac_mode in [1, 2]:
                set_point = o['indoor_dry_bulb_temperature_cooling_set_point'] if hvac_mode == 1 else o['indoor_dry_bulb_temperature_heating_set_point']
                band =  self.band if self.band is not None else o['comfort_band']
                lower_bound_comfortable_indoor_dry_bulb_temperature = set_point - numpy1_scalar(band)
                upper_bound_comfortable_indoor_dry_bulb_temperature = set_point + numpy1_scalar(band)
                delta = abs(indoor_dry_bulb_temperature - set_point)
                
                if indoor_dry_bulb_temperature < lower_bound_comfortable_indoor_dry_bulb_temperature:
                    exponent = self.lower_exponent if hvac_mode == 2 else self.higher_exponent
                    reward = -(delta**numpy1_scalar(exponent))
                
                elif lower_bound_comfortable_indoor_dry_bulb_temperature <= indoor_dry_bulb_temperature < set_point:
                    reward = 0.0 if heating else -delta

                elif set_point <= indoor_dry_bulb_temperature <= upper_bound_comfortable_indoor_dry_bulb_temperature:
                    reward = -delta if heating else 0.0

                else:
                    exponent = self.higher_exponent if heating else self.lower_exponent
                    reward = -(delta**numpy1_scalar(exponent))

            else:
                cooling_set_point = o['indoor_dry_bulb_temperature_cooling_set_point']
                heating_set_point = o['indoor_dry_bulb_temperature_heating_set_point']
                band =  self.band if self.band is not None else o['comfort_band']
                lower_bound_comfortable_indoor_dry_bulb_temperature = heating_set_point - numpy1_scalar(band)
                upper_bound_comfortable_indoor_dry_bulb_temperature = cooling_set_point + numpy1_scalar(band)
                cooling_delta = indoor_dry_bulb_temperature - cooling_set_point
                heating_delta = indoor_dry_bulb_temperature - heating_set_point

                if indoor_dry_bulb_temperature < lower_bound_comfortable_indoor_dry_bulb_temperature:
                    exponent = self.higher_exponent if not heating else self.lower_exponent
                    reward = -(abs(heating_delta)**numpy1_scalar(exponent))

                elif lower_bound_comfortable_indoor_dry_bulb_temperature <= indoor_dry_bulb_temperature < heating_set_point:
                    reward = -(abs(heating_delta))

                elif heating_set_point <= indoor_dry_bulb_temperature <= cooling_set_point:
                    reward = 0.0

                elif cooling_set_point < indoor_dry_bulb_temperature < upper_bound_comfortable_indoor_dry_bulb_temperature:
                    reward = -(abs(cooling_delta))

                else:
                    exponent = self.higher_exponent if heating else self.lower_exponent
                    reward = -(abs(cooling_delta)**numpy1_scalar(exponent))

            reward_list.append(reward)

        if self.central_agent:
            reward = [sum(reward_list, numpy1_scalar(0))]

        else:
            reward = reward_list

        return reward

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        return (
            'heating_demand',
            'cooling_demand',
            'hvac_mode',
            'indoor_dry_bulb_temperature',
            'indoor_dry_bulb_temperature_cooling_set_point',
            'indoor_dry_bulb_temperature_heating_set_point',
            'comfort_band',
        )
    
class SolarPenaltyAndComfortReward(RewardFunction):
    """Addition of :py:class:`citylearn.reward_function.SolarPenaltyReward` and :py:class:`citylearn.reward_function.ComfortReward`.

    Parameters
    ----------
    env_metadata: Mapping[str, Any]:
        General static information about the environment.
    band: float, default = 2.0
        Setpoint comfort band (+/-). If not provided, the comfort band time series defined in the
        building file, or the default time series value of 2.0 is used.
    lower_exponent: float, default = 2.0
        Penalty exponent for when in cooling mode but temperature is above setpoint upper
        boundary or heating mode but temperature is below setpoint lower boundary.
    higher_exponent: float, default = 3.0
        Penalty exponent for when in cooling mode but temperature is below setpoint lower
        boundary or heating mode but temperature is above setpoint upper boundary.
    coefficients: Tuple, default = (1.0, 1.0)
        Coefficents for `citylearn.reward_function.SolarPenaltyReward` and :py:class:`citylearn.reward_function.ComfortReward` values respectively.
    """
    
    def __init__(self, env_metadata: Mapping[str, Any], band: float = None, lower_exponent: float = None, higher_exponent: float = None, coefficients: Tuple = None):
        self.__functions: List[RewardFunction] = [
            SolarPenaltyReward(env_metadata),
            ComfortReward(env_metadata, band=band, lower_exponent=lower_exponent, higher_exponent=higher_exponent)
        ]
        super().__init__(env_metadata)
        self.coefficients = coefficients

    @property
    def coefficients(self) -> Tuple:
        return self.__coefficients
    
    @RewardFunction.env_metadata.setter
    def env_metadata(self, env_metadata: Mapping[str, Any]) -> Mapping[str, Any]:
        RewardFunction.env_metadata.fset(self, env_metadata)

        for f in self.__functions:
            f.env_metadata = self.env_metadata
    
    @coefficients.setter
    def coefficients(self, coefficients: Tuple):
        coefficients = [1.0]*len(self.__functions) if coefficients is None else coefficients
        assert len(coefficients) == len(self.__functions), f'{type(self).__name__} needs {len(self.__functions)} coefficients.' 
        self.__coefficients = coefficients

    def calculate(self, observations: List[Mapping[str, Union[int, float]]]) -> List[float]:
        reward = np.array([f.calculate(observations) for f in self.__functions], dtype='float32')
        reward = reward*np.reshape(self.coefficients, (len(self.coefficients), 1))
        reward = reward.sum(axis=0).tolist()

        return reward

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        required: Set[str] = set()

        for function in self.__functions:
            names = function.get_required_observation_names()
            if names is None:
                return None
            required.update(names)

        return required


class Electric_Vehicles_Reward_Function(MARL):
    """
    Reward function for electric vehicle charging behavior in V2G settings.
    Only affects EV-related behavior; other building logic comes from the superclass.
    """

    def __init__(self, env_metadata: Mapping[str, Any], weights: Mapping[str, float] = None):
        super().__init__(env_metadata)

        # Default tunable weights for EV-related reward components
        self.weights = weights or {
            "no_car_charging": -5.0,
            "battery_limits": -2.0,
            "soc_impossible": -10.0,
            "soc_under": -5.0,
            "close_soc": 10.0,
            "self_ev_consumption": 5.0,
            "extra_self_production": 5.0,
        }
        self._last_base_reward_total = 0.0
        self._last_penalty_total = 0.0
        self._last_base_rewards_per_building: List[float] = []
        self._last_penalties_per_building: List[float] = []

    def calculate(self, observations: List[Mapping[str, Union[int, float, dict]]]) -> List[float]:
        current_reward = super().calculate(observations)
        reward_list = []
        base_rewards = []
        penalty_values = []

        for i, o in enumerate(observations):
            ev_info = o.get("electric_vehicles_chargers_dict", {})
            if not ev_info:
                reward = 0
            else:
                if self.central_agent:
                    reward_value = current_reward[0] if isinstance(current_reward, list) else current_reward
                    reward = self.calculate_ev_penalty(o, reward_value)
                else:
                    reward = self.calculate_ev_penalty(o, current_reward[i])

            base_rewards.append(reward)
            violation = float(o.get("charging_constraint_violation_kwh", 0.0) or 0.0)
            penalty = violation * self.charging_constraint_penalty_coefficient if violation > 0.0 else 0.0
            penalty_values.append(penalty)
            reward -= penalty

            reward_list.append(reward)

        self._last_base_rewards_per_building = base_rewards
        self._last_penalties_per_building = penalty_values
        total_reward = [sum(reward_list, numpy1_scalar(0))] if self.central_agent else reward_list
        self._last_base_reward_total = sum(base_rewards) if self.central_agent else base_rewards
        self._last_penalty_total = sum(penalty_values) if self.central_agent else penalty_values
        LOGGER.debug(f"Calculated EV reward: {total_reward}")
        return total_reward

    def get_required_observation_names(self) -> Optional[Iterable[str]]:
        return (
            'net_electricity_consumption',
            'electric_vehicles_chargers_dict',
            'charging_constraint_violation_kwh',
        )

    def calculate_ev_penalty(self, o: Mapping[str, Union[int, float, dict]], current_reward: float) -> float:

        penalty_total = 0.0
        ev_chargers: dict = o.get("electric_vehicles_chargers_dict", {})
        net_energy_before = o.get("net_electricity_consumption", 0)

        # Bounding the multiplier to avoid extreme scaling
        penalty_multiplier = 1.0 / (1.0 + abs(current_reward))

        for charger_id, data in ev_chargers.items():
            contributions = {k: 0.0 for k in self.weights.keys()}

            if not data["connected"]:
                last_charged_kwh = data.get("last_charged_kwh", 0.0) or 0.0
                if abs(last_charged_kwh) > 0.1:
                    contributions["no_car_charging"] += self.weights["no_car_charging"] * penalty_multiplier
                LOGGER.debug(f"Charger {charger_id} | EV not connected | Contributions: {contributions}")
                penalty_total += sum(contributions.values())
                continue

            # Extract values
            soc_prev = data.get("previous_battery_soc")
            soc_now = data.get("battery_soc")
            capacity = data.get("battery_capacity")
            min_capacity = data.get("min_capacity")
            last_charged_kwh = data.get("last_charged_kwh", 0)
            if last_charged_kwh is None:
                last_charged_kwh = 0.0
            required_soc = data.get("required_soc")
            hours_until_departure = data.get("hours_until_departure", 0)
            max_charging_power = data.get("max_charging_power", 0)
            max_discharging_power = data.get("max_discharging_power", 0)

            if soc_prev is None or soc_now is None or capacity is None:
                raise ValueError("Something went wrong, this values should not be none")
                continue
            # Battery limits
            current_energy = soc_prev * numpy1_scalar(capacity) + last_charged_kwh
            if current_energy > capacity or current_energy < min_capacity:
                contributions["battery_limits"] += self.weights["battery_limits"] * penalty_multiplier

            # SoC penalties/rewards
            if required_soc is not None and hours_until_departure >= 0:
                soc_diff = soc_now - required_soc
                soc_diff_kWh = soc_diff * numpy1_scalar(capacity)

                max_possible_charge = max(max_charging_power, 0.0) * max(hours_until_departure, 0.0)
                max_possible_discharge = max(max_discharging_power, 0.0) * max(hours_until_departure, 0.0)

                soc_deficit_kwh = max(required_soc - soc_now, 0.0) * numpy1_scalar(capacity)
                if soc_deficit_kwh > max_possible_charge:
                    contributions["soc_impossible"] += self.weights["soc_impossible"] * penalty_multiplier

                if hours_until_departure == 0:
                    if -0.25 < soc_diff <= -0.10:
                        contributions["soc_under"] += 2 * self.weights["soc_under"] * penalty_multiplier
                    elif soc_diff <= -0.25:
                        contributions["soc_under"] += (self.weights["soc_under"] ** 2) * penalty_multiplier
                    elif -0.10 < soc_diff <= 0.10:
                        contributions["close_soc"] += self.weights["close_soc"] * penalty_multiplier

                if abs(soc_diff_kWh) <= max(max_possible_charge, max_possible_discharge):
                    reward_multiplier = 1.0 / (hours_until_departure + 0.1)
                    contributions["close_soc"] += self.weights["close_soc"] * penalty_multiplier * reward_multiplier

            # Self-production reward
            if last_charged_kwh > 0 and net_energy_before < 0:
                contributions["extra_self_production"] += self.weights["extra_self_production"] * penalty_multiplier
            elif last_charged_kwh < 0 and net_energy_before < 0:
                contributions["extra_self_production"] += -0.5 * self.weights["extra_self_production"] * penalty_multiplier

            # Self-consumption reward
            if last_charged_kwh < 0 and net_energy_before > 0:
                contributions["self_ev_consumption"] += self.weights["self_ev_consumption"] * penalty_multiplier
            elif last_charged_kwh > 0 and net_energy_before > 0:
                contributions["self_ev_consumption"] += -0.5 * self.weights["self_ev_consumption"] * penalty_multiplier

            LOGGER.debug(f"Charger {charger_id} | Contributions: {contributions}")
            penalty_total += sum(contributions.values())

        return penalty_total
