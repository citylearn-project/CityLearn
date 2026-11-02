from typing import List, Tuple, Union
import numpy as np
import pandas as pd
from citylearn.data import EnergySimulation

class CostFunction:
    r"""Cost and energy flexibility functions that may be used to evaluate environment performance."""

    @staticmethod
    def ramping(net_electricity_consumption: List[float], down_ramp: bool = None, net_export: bool = None) -> List[float]:
        r"""Rolling sum of absolute difference in net electric consumption between consecutive time steps.

        Parameters
        ----------
        net_electricity_consumption: List[float]
            Electricity consumption time series.

        down_ramp: bool
            Include cases where there is reduction in consumption between consecutive time steps  
            in the summation if `True`, otherwise set ramp value to zero for such cases.

        net_export: bool
            Include cases where net electric consumption is negative (net export) in the summation 
             if `True`, otherwise set ramp value to zero for such cases.

        Returns
        -------
        ramping : List[float]
            Ramping cost.

        Notes
        -----        
        .. math:: 
            \textrm{ramping} = \sum_{i=1}^{n}{\lvert E_i - E_{i-1} \rvert}
            
        Where :math:`E_i` is the :math:`i^{\textrm{th}}` element in `net_electricity_consumption`, :math:`E`, that has a length of :math:`n`.
        """

        down_ramp = False if down_ramp is None else down_ramp
        net_export = True if net_export is None else net_export

        data = pd.DataFrame({'net_electricity_consumption':net_electricity_consumption})
        data['ramping'] = data['net_electricity_consumption'] - data['net_electricity_consumption'].shift(1)

        if down_ramp:
            data['ramping'] = data['ramping'].abs()

        else:
            data['ramping'] = data['ramping'].clip(lower=0)
 
        if not net_export:
            data.loc[data['net_electricity_consumption']<0, 'ramping'] = 0
        
        else:
            pass

        data['ramping'] = data['ramping'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['ramping'].tolist()

    @staticmethod
    def one_minus_load_factor(net_electricity_consumption: List[float], window: int = None) -> List[float]:
        r"""Difference between 1 and the load factor i.e., ratio of rolling mean demand 
        to rolling peak demand over a specified period.

        Parameters
        ----------
        net_electricity_consumption : List[float]
            Electricity consumption time series.
        window : int, default: 730
            Period window/time steps.

        Returns
        -------
        1 - load_factor : List[float]
            1 - load factor cost.
        """

        window = 730 if window is None else window
        data = pd.DataFrame({'net_electricity_consumption':net_electricity_consumption})
        data['group'] = (data.index/window).astype(int)
        data = data.groupby(['group'])[['net_electricity_consumption']].agg(['mean','max'])
        data['load_factor'] = 1 - (data[('net_electricity_consumption','mean')]/data[('net_electricity_consumption','max')])
        data['load_factor'] = data['load_factor'].rolling(window=data.shape[0],min_periods=1).mean()
        
        return data['load_factor'].tolist()

    @staticmethod
    def peak(net_electricity_consumption: List[float], window: int = None) -> List[float]:
        r"""Net electricity consumption peak.

        Parameters
        ----------
        net_electricity_consumption : List[float]
            Electricity consumption time series.
        window : int, default: 24
            Period window/time steps to find peaks.
            
        Returns
        -------
        peak : List[float]
            Average daily peak cost.
        """

        window = 24 if window is None else window
        data = pd.DataFrame({'net_electricity_consumption':net_electricity_consumption})
        data['group'] = (data.index/window).astype(int)
        data = data.groupby(['group'])[['net_electricity_consumption']].max()
        data['net_electricity_consumption'] = data['net_electricity_consumption'].rolling(window=data.shape[0],min_periods=1).mean()
        
        return data['net_electricity_consumption'].tolist()

    @staticmethod
    def electricity_consumption(net_electricity_consumption: List[float]) -> List[float]:
        r"""Rolling sum of positive electricity consumption.

        It is the sum of electricity that is consumed from the grid.

        Parameters
        ----------
        net_electricity_consumption : List[float]
            Electricity consumption time series.
            
        Returns
        -------
        electricity_consumption : List[float]
            Electricity consumption cost.
        """

        data = pd.DataFrame({'net_electricity_consumption':np.array(net_electricity_consumption).clip(min=0)})
        data['electricity_consumption'] = data['net_electricity_consumption'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['electricity_consumption'].tolist()

    @staticmethod
    def zero_net_energy(net_electricity_consumption: List[float]) -> List[float]:
        r"""Rolling sum of net electricity consumption.

        It is the net sum of electricty that is consumed from the grid and self-generated from renenewable sources.
        This calculation of zero net energy does not consider TDV and all time steps are weighted equally.

        Parameters
        ----------
        net_electricity_consumption : List[float]
            Electricity consumption time series.
            
        Returns
        -------
        zero_net_energy : List[float]
            Zero net energy cost.
        """

        data = pd.DataFrame({'net_electricity_consumption':np.array(net_electricity_consumption)})
        data['zero_net_energy'] = data['net_electricity_consumption'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['zero_net_energy'].tolist()

    @staticmethod
    def carbon_emissions(carbon_emissions: List[float]) -> List[float]:
        r"""Rolling sum of carbon emissions.

        Parameters
        ----------
        carbon_emissions : List[float]
            Carbon emissions time series.
            
        Returns
        -------
        carbon_emissions : List[float]
            Carbon emissions cost.
        """

        data = pd.DataFrame({'carbon_emissions':np.array(carbon_emissions).clip(min=0)})
        data['carbon_emissions'] = data['carbon_emissions'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['carbon_emissions'].tolist()

    @staticmethod
    def cost(cost: List[float]) -> List[float]:
        r"""Rolling sum of electricity monetary cost.

        Parameters
        ----------
        cost : List[float]
            Cost time series.
            
        Returns
        -------
        cost : List[float]
            Cost of electricity.
        """

        data = pd.DataFrame({'cost':np.array(cost).clip(min=0)})
        data['cost'] = data['cost'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['cost'].tolist()

    @staticmethod
    def quadratic(net_electricity_consumption: List[float]) -> List[float]:
        r"""Rolling sum of net electricity consumption raised to the power of 2.

        Parameters
        ----------
        net_electricity_consumption : List[float]
            Electricity consumption time series.
            
        Returns
        -------
        quadratic : List[float]
            Quadratic cost.

        Notes
        -----
        Net electricity consumption values are clipped at a minimum of 0 before calculating the quadratic cost.
        """

        data = pd.DataFrame({'net_electricity_consumption':np.array(net_electricity_consumption).clip(min=0)})
        data['quadratic'] = data['net_electricity_consumption']**2
        data['quadratic'] = data['quadratic'].rolling(window=data.shape[0],min_periods=1).sum()
        
        return data['quadratic'].tolist()
    
    @staticmethod
    def discomfort(indoor_dry_bulb_temperature: List[float], dry_bulb_temperature_cooling_set_point: List[float], dry_bulb_temperature_heating_set_point: List[float], band: Union[float, List[float]] = None, occupant_count: List[int] = None) -> Tuple[list]:
        r"""Rolling percentage of discomfort (total, too cold, and too hot) time steps as well as rolling minimum, maximum and average temperature delta.

        Parameters
        ----------
        indoor_dry_bulb_temperature: List[float]
            Average building dry bulb temperature time series.
        dry_bulb_temperature_cooling_set_point: List[float]
            Building thermostat cooling setpoint time series.
        dry_bulb_temperature_heating_set_point: List[float]
            Building thermostat heating setpoint time series.
        band: Union[float, List[float]], optional
            Comfort band above dry_bulb_temperature_cooling_set_point and below dry_bulb_temperature_heating_set_point beyond which occupant is assumed to be uncomfortable.
            Defaults to :py:attr:`citylearn.data.EnergySimulation.DEFUALT_COMFORT_BAND`.
        occupant_count: List[float], optional
            Occupant count time series. If provided, the comfort cost is 
            evaluated for occupied time steps only.
            
        Returns
        -------
        discomfort: List[float]
            Rolling proportion of occupied timesteps where the condition 
            (dry_bulb_temperature_heating_set_point - band) <= indoor_dry_bulb_temperature <= (dry_bulb_temperature_cooling_set_point + band) is not met.
        discomfort_cold: List[float]
            Rolling proportion of occupied timesteps where the condition indoor_dry_bulb_temperature < (dry_bulb_temperature_heating_set_point - band) is met.
        discomfort_hot: List[float]
            Rolling proportion of occupied timesteps where the condition indoor_dry_bulb_temperature > (dry_bulb_temperature_cooling_set_point + band) is met.
        discomfort_cold_delta_minimum: List[float]
            Rolling minimum of indoor_dry_bulb_temperature - dry_bulb_temperature_heating_set_point where the condition indoor_dry_bulb_temperature < (dry_bulb_temperature_heating_set_point - band) is met.
        discomfort_cold_delta_maximum: List[float]
            Rolling maximum of indoor_dry_bulb_temperature - dry_bulb_temperature_heating_set_point where the condition indoor_dry_bulb_temperature < (dry_bulb_temperature_heating_set_point - band) is met.
        discomfort_cold_delta_average: List[float]
            Rolling average of indoor_dry_bulb_temperature - dry_bulb_temperature_heating_set_point where the condition indoor_dry_bulb_temperature < (dry_bulb_temperature_heating_set_point - band) is met.
        discomfort_hot_delta_minimum: List[float]
            Rolling minimum of indoor_dry_bulb_temperature - dry_bulb_temperature_cooling_set_point where the condition indoor_dry_bulb_temperature > (dry_bulb_temperature_cooling_set_point + band) is met.
        discomfort_hot_delta_maximum: List[float]
            Rolling maximum of indoor_dry_bulb_temperature - dry_bulb_temperature_cooling_set_point where the condition indoor_dry_bulb_temperature > (dry_bulb_temperature_cooling_set_point + band) is met.
        discomfort_hot_delta_average: List[float]
            Rolling average of indoor_dry_bulb_temperature - dry_bulb_temperature_cooling_set_point where the condition indoor_dry_bulb_temperature > (dry_bulb_temperature_cooling_set_point + band) is met.
        """

        temperature, cooling, heating = [np.asarray(v, dtype=float) for v in
            (indoor_dry_bulb_temperature, dry_bulb_temperature_cooling_set_point, dry_bulb_temperature_heating_set_point)]
        if len(temperature) == 0:
            return tuple([] for _ in range(9))
        occupants = np.ones(len(temperature)) if occupant_count is None else np.asarray(occupant_count, dtype=float)
        bands = np.broadcast_to(np.asarray(EnergySimulation.DEFUALT_COMFORT_BAND if band is None else band, dtype=float), temperature.shape)
        valid = (np.isfinite(temperature) & np.isfinite(cooling) & np.isfinite(heating)
                 & np.isfinite(bands) & (bands >= 0) & (heating <= cooling)
                 & np.isfinite(occupants) & (occupants > 0))
        cold = valid & (temperature < heating-bands)
        hot = valid & (temperature > cooling+bands)
        denominator = pd.Series(np.cumsum(valid)).replace(0, np.nan)
        ratios = [(pd.Series(np.cumsum(mask))/denominator).tolist() for mask in (cold | hot, cold, hot)]
        deltas = []
        for mask, values in ((cold, heating-temperature), (hot, temperature-cooling)):
            observed = pd.Series(np.where(mask, values, np.nan)).expanding(min_periods=1)
            deltas.extend([observed.min().tolist(), observed.max().tolist(), observed.mean().tolist()])
        return tuple(ratios+deltas)

    @staticmethod
    def one_minus_thermal_resilience(power_outage: List[int], **kwargs):
        r"""Rolling percentage of discomfort time steps during power outage.

        Parameters
        ----------
        power_outage: List[float]
            Signal for power outage. If 0, there is no outage and building can draw energy from grid. 
            If 1, there is a power outage and building can only use its energy resources to meet loads.
        
        Other Parameters
        ----------------
        **kwargs : Any
            Parameters parsed to :py:meth:`citylearn.CostFunction.discomfort`.
            
        Returns
        -------
        thermal_resilience: List[float]
            Rolling proportion of occupied timesteps where the condition 
            (dry_bulb_temperature_set_point - band) <= indoor_dry_bulb_temperature <= (dry_bulb_temperature_set_point + band) 
            is not met during a power outage.
        """

        occupant_count = [1]*len(power_outage) if kwargs.get('occupant_count', None) is None else kwargs['occupant_count']
        occupant_count = np.array(occupant_count, dtype='float32')
        power_outage = np.array(power_outage, dtype='float32')
        occupant_count[~np.isfinite(power_outage) | (power_outage <= 0.0)] = 0.0
        kwargs['occupant_count'] = occupant_count
        thermal_resilience = CostFunction.discomfort(**kwargs)[0]

        return thermal_resilience
    
    @staticmethod
    def normalized_unserved_energy(expected_energy: List[float], served_energy: List[float], power_outage: List[int] = None):
        r"""Proportion of unmet demand due to supply shortage e.g. power outage.

        Parameters
        ----------
        expected_energy: List[float]
            Total expected energy time series to be met in the absence of power outage.
        served_energy: List[float]
            Total delivered energy time series when considering power outage.
        power_outage: List[float], optional
            Signal for power outage. If 0, there is no outage and building can draw energy from grid. 
            If >= 1, there is a power outage and building can only use its energy resources to meet loads.
            If provided, the cost funtion is only calculated for time steps when there is an outage 
            otherwise all time steps are considered.
            
        Returns
        -------
        normalized_unserved_energy: List[float]
            Unmet demand.
        """

        if len(expected_energy) == 0:
            return []

        data = pd.DataFrame({
            'expected_energy': np.asarray(expected_energy, dtype='float64'),
            'served_energy': np.asarray(served_energy, dtype='float64'),
            'power_outage': [1]*len(served_energy) if power_outage is None else power_outage,
        })
        data['expected_energy'] = data['expected_energy'].where(np.isfinite(data['expected_energy']), 0.0).clip(lower=0.0)
        data['served_energy'] = data['served_energy'].where(np.isfinite(data['served_energy']), 0.0).clip(lower=0.0)
        data['power_outage'] = pd.to_numeric(data['power_outage'], errors='coerce').fillna(0.0)
        data['unserved_energy'] = (data['expected_energy'] - data['served_energy']).clip(lower=0.0)
        data.loc[data['power_outage'] == 0, ['unserved_energy', 'expected_energy']] = 0.0
        data['unserved_energy'] = data['unserved_energy'].rolling(window=data.shape[0], min_periods=1).sum()
        expected_energy = data['expected_energy'].sum()

        if expected_energy <= 0.0:
            return [0.0]*data.shape[0]

        data['unserved_energy'] = data['unserved_energy']/expected_energy

        return data['unserved_energy'].tolist()
