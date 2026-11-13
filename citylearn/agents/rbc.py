from typing import Any, Mapping, List, Union
from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.building import Building

class RBC(Agent):
    r"""Base rule based controller class.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        if str(getattr(env.unwrapped, 'interface', 'flat')).lower() != 'flat':
            raise ValueError("RBC controllers require interface='flat'.")
        super().__init__(env, **kwargs)

class HourRBC(RBC):
    r"""A hour-of-use rule-based controller.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    action_map: Union[Mapping[int, float], Mapping[str, Mapping[int, float]], List[Mapping[str, Mapping[int, float]]]], optional
        A 24-hour action map for each controlled device where the key is the hour between 1-24 and the value is the action.
        For storage systems, the value is negative for discharge and positive for charge where it ranges between [0, 1]. 
        Whereas, for cooling or heating devices, the value is positive for proportion of nominal power to make available and 
        ranges between [0, 1]. The action map can be parsed as a dictionary of hour keys mapped to action values 
        (:code:`Mapping[int, float]`). Alternatively, it can be parsed as a dictionary of devices 
        (:code:`Mapping[str, Mapping[int, float]]`) with their specific hour key to action value mapping 
        (:code:`Mapping[int, float]`). Finally, the action map can be defined for each agent especially in decentralized 
        setup as a list of device dictionary where each device dictionary (:code:`Mapping[str, Mapping[int, float]]`) 
        is for a specific decentralized (or centralized) agent. The HourRBC will return random actions if no map is provided.
    
    Other Parameters
    ----------------
    **kwargs: Any
        Other keyword arguments used to initialize super class.
    """
    
    
    def __init__(self, env: CityLearnEnv, action_map: Union[List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]] = None, **kwargs: Any):
        super().__init__(env, **kwargs)
        self.action_map = action_map

    @property
    def action_map(self) -> List[Mapping[str, Mapping[int, float]]]:
        return self.__action_map
    
    @action_map.setter
    def action_map(self, action_map: Union[List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]]):
        if isinstance(action_map, list):
            assert len(action_map) == len(self.action_dimension), f'List of action maps must have same length as number of agents: {len(self.action_dimension)}.'

            for i, (m, n) in enumerate(zip(action_map, self.action_names)):
                n = list(set(n))
                self.__verify_action_map(n, m, index=i)
        
        elif isinstance(action_map, dict):
            if len(action_map) == 0:
                action_names = list({a_ for a in self.action_names for a_ in a})
                self.__verify_action_map(action_names, action_map)
                action_map = [{} for _ in self.action_names]
            elif isinstance(list(action_map.values())[0], dict):
                action_names = [a_ for a in self.action_names for a_ in a]
                action_names = list(set(action_names))
                self.__verify_action_map(action_names, action_map)
                action_map = [{n_: action_map[n_] for n_ in list(set(n))} for n in self.action_names]

            else:
                action_map = [{n_: action_map for n_ in list(set(n))} for n in self.action_names]
        
        else:
            pass

        self.__action_map = action_map

    def predict(self, observations: List[List[float]], deterministic: bool = None) -> List[List[float]]:
        """Provide actions for current time step.

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

        actions = []

        if self.action_map is None:
            actions = super().predict(observations, deterministic=deterministic)
        
        else:
            for m, a, n, o in zip(self.action_map, self.action_names, self.observation_names, observations):
                hour_observation = o[n.index('hour')]
                hour = int(round(hour_observation))
                # Support both 0-23 and 1-24 hour encodings.
                hour_candidates = []

                for candidate in (hour, hour % 24, ((hour - 1) % 24) + 1):
                    if candidate not in hour_candidates:
                        hour_candidates.append(candidate)

                actions_ = []

                for a_ in a:
                    for candidate in hour_candidates:
                        hour_map = m[a_]

                        if candidate in hour_map:
                            actions_.append(hour_map[candidate])
                            break
                    else:
                        raise KeyError(f'Hour {hour_observation} not defined in action map for action {a_}.')
                
                actions.append(actions_)

            self.actions = actions
            self.next_time_step()
        
        return actions
    
    def __verify_action_map(self, action_names: List[str], action_map: Mapping[str, Mapping[int, float]], index: int = None):
        missing_actions = [a for a in action_names if a not in list(action_map.keys())]
        message = f'Undefined maps for actions: {missing_actions}'
        message += '.' if index is None else f' in building with index: {index}.'
        assert len(missing_actions) == 0, message

class BasicRBC(HourRBC):
    r"""A hour-of-use rule-based controller for heat-pump charged thermal energy storage systems that charges when COP is high.

    The actions are designed such that the agent charges the controlled storage system(s) by 9.1% of its maximum capacity every
    hour between 10:00 PM and 08:00 AM, and discharges 8.0% of its maximum capacity at every other hour. Cooling device is set
    to 40.0% of nominal power between between 10:00 PM and 08:00 AM and 80.0% at every other hour. Heating device is to 80.0% 
    of nominal power between between 10:00 PM and 08:00 AM and 40.0% at every other hour.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        super().__init__(env, **kwargs)

    @HourRBC.action_map.setter
    def action_map(self, action_map: Union[List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]]):
        if action_map is None:
            action_map = {}
            action_names = [a_ for a in self.action_names for a_ in a]
            action_names = list(set(action_names))

            for n in action_names:
                action_map[n] = {}
                
                if 'storage' in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = -0.08
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.091
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = 0.8
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.4
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = 0.4
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.8
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_or_heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if hour < 7:
                            value = 0.4
                        
                        elif hour < 21:
                            value = -0.4

                        else:
                            value = 0.8

                        action_map[n][hour] = value
                
                else:
                    raise ValueError(f'Unknown action name: {n}')

        HourRBC.action_map.fset(self, action_map)

class OptimizedRBC(BasicRBC):
    r"""A hour-of-use rule-based controller that is an optimized version of :py:class:`citylearn.agents.rbc.BasicRBC`
    where control actions have been selected through a search grid.

    The actions are designed such that the agent discharges the controlled storage system(s) by 2.0% of its 
    maximum capacity every hour between 07:00 AM and 03:00 PM, discharges by 4.4% of its maximum capacity 
    between 04:00 PM and 06:00 PM, discharges by 2.4% of its maximum capacity between 07:00 PM and 10:00 PM, 
    charges by 3.4% of its maximum capacity between 11:00 PM to midnight and charges by 5.532% of its maximum 
    capacity at every other hour.

    Cooling device makes available 70.0% of its nominal power every hour between 07:00 AM and 03:00 PM, 60.0% between 
    04:00 PM and 06:00 PM, 80.0% between 07:00 PM and 10:00 PM, 40.0% between 11:00 PM to midnight and 20.0% other hour.

    Heating device makes available 30.0% of its nominal power every hour between 07:00 AM and 03:00 PM, 40.0% between 
    04:00 PM and 06:00 PM, 60.0% between 07:00 PM and 10:00 PM, 70.0% between 11:00 PM to midnight and 80.0% other hour.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        super().__init__(env, **kwargs)

    @HourRBC.action_map.setter
    def action_map(self, action_map: Union[List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]]):
        if action_map is None:
            action_map = {}
            action_names = [a_ for a in self.action_names for a_ in a]
            action_names = list(set(action_names))

            for n in action_names:
                action_map[n] = {}
                
                if 'storage' in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 7 <= hour <= 15:
                            value = -0.02
                        elif 16 <= hour <= 18:
                            value = -0.044
                        elif 19 <= hour <= 22:
                            value = -0.024
                        elif 23 <= hour <= 24:
                            value = 0.034
                        elif 1 <= hour <= 6:
                            value = 0.05532
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 7 <= hour <= 15:
                            value = 0.7
                        elif 16 <= hour <= 18:
                            value = 0.6
                        elif 19 <= hour <= 22:
                            value = 0.8
                        elif 23 <= hour <= 24:
                            value = 0.4
                        elif 1 <= hour <= 6:
                            value = 0.2
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 7 <= hour <= 15:
                            value = 0.3
                        elif 16 <= hour <= 18:
                            value = 0.4
                        elif 19 <= hour <= 22:
                            value = 0.6
                        elif 23 <= hour <= 24:
                            value = 0.7
                        elif 1 <= hour <= 6:
                            value = 0.8
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_or_heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if hour < 7:
                            value = 0.4
                        
                        elif hour < 21:
                            value = -0.4

                        else:
                            value = 0.8

                        action_map[n][hour] = value
                
                else:
                    raise ValueError(f'Unknown action name: {n}')

        HourRBC.action_map.fset(self, action_map)

class BasicBatteryRBC(BasicRBC):
    r"""A hour-of-use rule-based controller that is designed to take advantage of solar generation for charging.

    The actions are optimized for electrical storage (battery) such that the agent charges the controlled
    storage system(s) by 11.0% of its maximum capacity every hour between 06:00 AM and 02:00 PM, 
    and discharges 6.7% of its maximum capacity at every other hour. Cooling device is set
    to 70.0% of nominal power between between 06:00 AM and 02:00 PM and 30.0% at every other hour. 
    Heating device is to 30.0% of nominal power between between 06:00 AM and 02:00 PM and 70.0% at every other hour

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.
    
    Other Parameters
    ----------------
    **kwargs: Any
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        super().__init__(env, **kwargs)

    @HourRBC.action_map.setter
    def action_map(self, action_map: Union[List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]]):
        if action_map is None:
            action_map = {}
            action_names = [a_ for a in self.action_names for a_ in a]
            action_names = list(set(action_names))

            for n in action_names:
                action_map[n] = {}

                if 'storage' in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 6 <= hour <= 14:
                            value = 0.11
                        else:
                            value = -0.067

                        action_map[n][hour] = value

                elif n == 'cooling_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 6 <= hour <= 14:
                            value = 0.7
                        else:
                            value = 0.3

                        action_map[n][hour] = value

                elif n == 'heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 6 <= hour <= 14:
                            value = 0.3
                        else:
                            value = 0.7

                        action_map[n][hour] = value

                elif n == 'cooling_or_heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if hour < 7:
                            value = 0.4
                        
                        elif hour < 21:
                            value = -0.4

                        else:
                            value = 0.8

                        action_map[n][hour] = value
                
                else:
                    raise ValueError(f'Unknown action name: {n}')

        HourRBC.action_map.fset(self, action_map)

class BasicElectricVehicleRBC_ReferenceController(BasicRBC): #change the name
    r"""A rule-based controller that charges EVs to the maximum of the chargers and to the maximum of the battery upon connection.

    The EV battery is charged at the maximum available charging power whenever it is connected.

    Parameters
    ----------
    env: CityLearnEnv
        CityLearn environment.

    Other Parameters
    ----------------
    **kwargs: Any
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, env: CityLearnEnv, **kwargs: Any):
        super().__init__(env, **kwargs)

    @HourRBC.action_map.setter
    def action_map(self, action_map: Union[
        List[Mapping[str, Mapping[int, float]]], Mapping[str, Mapping[int, float]], Mapping[int, float]]):
        if action_map is None:
            action_map = {}
            action_names = [a_ for a in self.action_names for a_ in a]
            action_names = list(set(action_names))

            for n in action_names:
                action_map[n] = {}

                if n in ("electrical_storage", "cooling_storage", "heating_storage"):
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = -0.08
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.091
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = 0.8
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.4
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if 9 <= hour <= 21:
                            value = 0.4
                        elif (1 <= hour <= 8) or (22 <= hour <= 24):
                            value = 0.8
                        else:
                            value = 0.0

                        action_map[n][hour] = value

                elif n == 'cooling_or_heating_device':
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if hour < 7:
                            value = 0.4

                        elif hour < 21:
                            value = -0.4

                        else:
                            value = 0.8

                        action_map[n][hour] = value

                elif "electric_vehicle" in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        if hour < 7:
                            value = 0.4

                        elif hour < 10:
                            value = 1

                        elif hour < 15:
                            value = -1

                        elif hour < 20:
                            value = -0.6

                        else:
                            value = 0.8
                            
                        action_map[n][hour] = value

                elif "dhw_storage" in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        value = 1
                        action_map[n][hour] = value

                elif "deferrable_appliance" in n:
                    for hour in Building.get_periodic_observation_metadata()['hour']:
                        value = 1
                        action_map[n][hour] = value        

                else:
                    raise ValueError(f'Unknown action name: {n}')

        HourRBC.action_map.fset(self, action_map)
