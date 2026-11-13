import ast
from array import array
import logging
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
import numpy as np
from citylearn.internal.scalars import as_float, clip_scalar
import pandas as pd
try:
    from PySAM import Pvwattsv8
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    Pvwattsv8 = None
from citylearn.base import Environment, EpisodeTracker
from citylearn.data import (
    DataSet,
    ZERO_DIVISION_PLACEHOLDER,
    DeferrableApplianceSimulation,
    EnergySimulation,
    EscalatorSimulation,
    WashingMachineSimulation,
)
from citylearn.internal.units import power_kw_to_energy_kwh, seconds_to_hours, to_dataset_resolution_energy
from citylearn.internal.deferrable_cycles import CycleIndex
np.seterr(divide='ignore', invalid='ignore')

LOGGER = logging.getLogger()

# Zero-size devices stand in for absent equipment. Without a seed, each would draw one from Python's
# global `random`, so its (unused) random parameters changed between constructions and building an
# env advanced the caller's random stream.
PLACEHOLDER_DEVICE_RANDOM_SEED = 0

class Device(Environment):
    r"""Base device class.

    Parameters
    ----------
    efficiency : Union[float, Tuple[float, float]], default: (0.8, 1.0)
        Technical efficiency. Must be set to > 0.

    Other Parameters
    ----------------
    **kwargs : dict
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, efficiency: Union[float, Tuple[float, float]] = None, **kwargs):
        kwargs.pop("dynamics",None)
        kwargs.pop("occupant",None)
        super().__init__(**kwargs)
        self.efficiency = efficiency
        self._autosize_config = None
        self.time_step_ratio = self.time_step_ratio if self.time_step_ratio is not None else 1
       
    @property
    def efficiency(self) -> float:
        """Technical efficiency."""

        return self.__efficiency

    @property
    def autosize_config(self) -> Mapping[str, Union[str, float]]:
        """Reference for configuration parameters used during autosizing."""

        return self._autosize_config

    @efficiency.setter
    def efficiency(self, efficiency: Union[float, Tuple[float, float]]):
        efficiency = self._get_property_value(efficiency, (0.8, 1.0))
        assert efficiency > 0, 'efficiency must be > 0.'
        self.__efficiency = efficiency

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'efficiency': self.efficiency,
            'autosize_config': self.autosize_config,
        }
    
    def _get_property_value(self, value: Union[float, None, Tuple[float, float]], default_value: Union[float, Tuple[float, float]]):
        """Returns `value` if it is a float or a number in the uniform distribution whose limits are defined by `value`. If `value`
        is `None`, the defalut value is used. Ideal and primarily used for stochastically setting device parameters."""

        if value is None or math.isnan(value):
            if isinstance(default_value, tuple):
                value = self.numpy_random_state.uniform(*default_value)

            else:
                value = default_value

        else:
            if isinstance(value, tuple):
                value = self.numpy_random_state.uniform(*value)
            
            else:
                pass

        return value

class ElectricDevice(Device):
    r"""Base electric device class.

    Parameters
    ----------
    nominal_power : float, default: 0.0
        Electric device nominal power >= 0.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, nominal_power: float = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.nominal_power = nominal_power

    @property
    def nominal_power(self) -> float:
        r"""Nominal power."""

        return self.__nominal_power
    
    @nominal_power.setter
    def nominal_power(self, nominal_power: float):
        nominal_power = 0.0 if nominal_power is None else nominal_power
        assert nominal_power >= 0, 'nominal_power must be >= 0.'
        self.__nominal_power = nominal_power

    def _electricity_consumption_ratio(self) -> float:
        ratio = self.time_step_ratio
        return 1.0 if ratio is None else float(ratio)

    @property
    def electricity_consumption(self) -> np.ndarray:
        r"""Electricity consumption time series [kWh]."""
        ratio = self._electricity_consumption_ratio()

        if ratio == 1.0:
            return self.__electricity_consumption

        return self.__electricity_consumption * ratio

    @property
    def available_nominal_power(self) -> float:
        r"""Difference between `nominal_power` and `electricity_consumption` at current `time_step`."""

        if self.nominal_power is None:
            return None

        consumption = float(self.__electricity_consumption[self.time_step]) * self._electricity_consumption_ratio()
        return as_float(self.nominal_power) - consumption


    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'nominal_power': self.nominal_power,
        }

    def update_electricity_consumption(self, electricity_consumption: float, enforce_polarity: bool = None):
        r"""Updates `electricity_consumption` at current `time_step`.
        
        Parameters
        ----------
        electricity_consumption: float
            Value to add to current `time_step` `electricity_consumption`. Must be >= 0.
        enforce_polarity: bool, default: True
            Whether to allow only positive `electricity_consumption` values. Some electric
            devices like :py:class:`citylearn.energy_model.Battery` may be bi-directional and
            allow electricity discharge thus, cause negative electricity consumption.
        """

        enforce_polarity = True if enforce_polarity is None else enforce_polarity
        assert not enforce_polarity or electricity_consumption >= 0.0,\
            f'electricity_consumption must be >= 0 but value: {electricity_consumption} was provided.'
        # Add in float64 before storing: NumPy 2 (NEP 50) would otherwise add a Python float in float32.
        self.__electricity_consumption[self.time_step] = float(self.__electricity_consumption[self.time_step]) + as_float(electricity_consumption)

    def set_electricity_consumption(
        self,
        electricity_consumption: float,
        time_step: int = None,
        enforce_polarity: bool = None,
    ):
        r"""Set `electricity_consumption` at a specific `time_step`.

        Parameters
        ----------
        electricity_consumption: float
            Absolute `electricity_consumption` value to store in [kWh] for `time_step`.
        time_step: int, default: current `time_step`
            Time step index to overwrite.
        enforce_polarity: bool, default: True
            Whether to allow only positive values.
        """

        enforce_polarity = True if enforce_polarity is None else enforce_polarity
        assert not enforce_polarity or electricity_consumption >= 0.0, \
            f'electricity_consumption must be >= 0 but value: {electricity_consumption} was provided.'

        step = self.time_step if time_step is None else int(time_step)
        ratio = self.time_step_ratio if self.time_step_ratio not in (None, 0) else 1.0
        self.__electricity_consumption[step] = float(electricity_consumption) / ratio
        # An explicit replacement of the terminal reading also replaces its
        # gross trace. Ordered physical operations use the transfer journal;
        # a manually supplied net reading cannot reconstruct those operations.
        charge = getattr(self, 'gross_energy_charge', None)
        discharge = getattr(self, 'gross_energy_discharge', None)
        if charge is not None and discharge is not None:
            charge[step] = max(float(electricity_consumption), 0.0)
            discharge[step] = max(-float(electricity_consumption), 0.0)

    def reset(self):
        r"""Reset `ElectricDevice` to initial state and set `electricity_consumption` at `time_step` 0 to = 0.0."""

        super().reset()
        self.__electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')

class HeatPump(ElectricDevice):
    r"""Base heat pump class.

    Parameters
    ----------
    nominal_power: float, default: 0.0
        Maximum amount of electric power that the heat pump can consume from the power grid (given by the nominal power of the compressor).
    efficiency : Union[float, Tuple[float, float]], default: (0.2, 0.3)
        Technical efficiency.
    target_heating_temperature : Union[float, Tuple[float, float]], default: (45.0, 50.0)
        Target heating supply dry bulb temperature in [C].
    target_cooling_temperature : Union[float, Tuple[float, float]], default: (7.0, 10.0)
        Target cooling supply dry bulb temperature in [C].

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, nominal_power: float = None, efficiency: float = None, target_heating_temperature: Union[float, Tuple[float, float]] = None, target_cooling_temperature: Union[float, Tuple[float, float]] = None, **kwargs: Any):
        super().__init__(nominal_power = nominal_power, efficiency = efficiency, **kwargs)
        self.target_heating_temperature = target_heating_temperature
        self.target_cooling_temperature = target_cooling_temperature

    @property
    def target_heating_temperature(self) -> float:
        r"""Target heating supply dry bulb temperature in [C]."""

        return self.__target_heating_temperature

    @property
    def target_cooling_temperature(self) -> float:
        r"""Target cooling supply dry bulb temperature in [C]."""

        return self.__target_cooling_temperature

    @target_heating_temperature.setter
    def target_heating_temperature(self, target_heating_temperature: Union[float, Tuple[float, float]]):
        target_heating_temperature = self._get_property_value(target_heating_temperature, (45.0, 50.0))
        self.__target_heating_temperature = target_heating_temperature

    @target_cooling_temperature.setter
    def target_cooling_temperature(self, target_cooling_temperature: Union[float, Tuple[float, float]]):
        target_cooling_temperature = self._get_property_value(target_cooling_temperature, (7.0, 10.0))
        self.__target_cooling_temperature = target_cooling_temperature

    @ElectricDevice.efficiency.setter
    def efficiency(self, efficiency: Union[float, Tuple[float, float]]):
        efficiency = self._get_property_value(efficiency, (0.2, 0.3))
        ElectricDevice.efficiency.fset(self, efficiency)

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'target_heating_temperature': self.target_heating_temperature,
            'target_cooling_temperature': self.target_cooling_temperature,
        }

    def get_cop(self, outdoor_dry_bulb_temperature: Union[float, Iterable[float]], heating: bool) -> Union[float, Iterable[float]]:
        r"""Return coefficient of performance.

        Calculate the Carnot cycle COP for heating or cooling mode. COP is set to 20 if < 0 or > 20.

        Parameters
        ----------
        outdoor_dry_bulb_temperature : Union[float, Iterable[float]]
            Outdoor dry bulb temperature in [C].
        heating : bool
            If `True` return the heating COP else return cooling COP.

        Returns
        -------
        cop : Union[float, Iterable[float]]
            COP as single value or time series depending on input parameter types.

        Notes
        -----
        heating_cop = (`t_target_heating` + 273.15)*`efficiency`/(`t_target_heating` - outdoor_dry_bulb_temperature)
        cooling_cop = (`t_target_cooling` + 273.15)*`efficiency`/(outdoor_dry_bulb_temperature - `t_target_cooling`)
        """

        if np.isscalar(outdoor_dry_bulb_temperature):
            outdoor_temperature = float(outdoor_dry_bulb_temperature)

            if heating:
                denominator = self.target_heating_temperature - outdoor_temperature
                cop = np.nan if np.isnan(denominator) else (
                    np.inf if denominator == 0.0
                    else self.efficiency*(self.target_heating_temperature + 273.15)/denominator
                )
            else:
                denominator = outdoor_temperature - self.target_cooling_temperature
                cop = np.nan if np.isnan(denominator) else (
                    np.inf if denominator == 0.0
                    else self.efficiency*(self.target_cooling_temperature + 273.15)/denominator
                )

            if cop < 0 or cop > 20:
                cop = 20
            return cop

        c_to_k = lambda x: x + 273.15
        outdoor_dry_bulb_temperature = np.array(outdoor_dry_bulb_temperature)

        if heating:
            cop = self.efficiency*c_to_k(self.target_heating_temperature)/(self.target_heating_temperature - outdoor_dry_bulb_temperature)
        else:
            cop = self.efficiency*c_to_k(self.target_cooling_temperature)/(outdoor_dry_bulb_temperature - self.target_cooling_temperature)
        
        cop = np.array(cop)
        cop[cop < 0] = 20
        cop[cop > 20] = 20
        return cop

    def get_max_output_power(self, outdoor_dry_bulb_temperature: Union[float, Iterable[float]], heating: bool, max_electric_power: Union[float, Iterable[float]] = None) -> Union[float, Iterable[float]]:
        r"""Return maximum output power.

        Calculate maximum output power from heat pump given `cop`, `available_nominal_power` and `max_electric_power` limitations.

        Parameters
        ----------
        outdoor_dry_bulb_temperature : Union[float, Iterable[float]]
            Outdoor dry bulb temperature in [C].
        heating : bool
            If `True` use heating COP else use cooling COP.
        max_electric_power : Union[float, Iterable[float]], optional
            Maximum amount of electric power that the heat pump can consume from the power grid.

        Returns
        -------
        max_output_power : Union[float, Iterable[float]]
            Maximum output power as single value or time series depending on input parameter types.

        Notes
        -----
        max_output_power = min(max_electric_power, `available_nominal_power`)*cop
        """

        cop = self.get_cop(outdoor_dry_bulb_temperature, heating)
        available_nominal_power = self.available_nominal_power

        if max_electric_power is None:
            return available_nominal_power*cop
        if np.isscalar(max_electric_power) and np.isscalar(available_nominal_power):
            return as_float(min(max_electric_power, available_nominal_power))*cop

        return np.minimum(max_electric_power, available_nominal_power)*cop

    def get_input_power(self, output_power: Union[float, Iterable[float]], outdoor_dry_bulb_temperature: Union[float, Iterable[float]], heating: bool) -> Union[float, Iterable[float]]:
        r"""Return input power.

        Calculate power needed to meet `output_power` given `cop` limitations.

        Parameters
        ----------
        output_power : Union[float, Iterable[float]]
            Output power from heat pump
        outdoor_dry_bulb_temperature : Union[float, Iterable[float]]
            Outdoor dry bulb temperature in [C].
        heating : bool
            If `True` use heating COP else use cooling COP.

        Returns
        -------
        input_power : Union[float, Iterable[float]]
            Input power as single value or time series depending on input parameter types.

        Notes
        -----
        input_power = output_power/cop
        """

        return as_float(output_power)/self.get_cop(outdoor_dry_bulb_temperature, heating)

    def autosize(self, outdoor_dry_bulb_temperature: Iterable[float], cooling_demand: Iterable[float] = None, heating_demand: Iterable[float] = None, safety_factor: Union[float, Tuple[float, float]] = None) -> float:
        r"""Autosize `nominal_power`.

        Set `nominal_power` to the minimum power needed to always meet `cooling_demand` + `heating_demand`.

        Parameters
        ----------
        outdoor_dry_bulb_temperature : Union[float, Iterable[float]]
            Outdoor dry bulb temperature in [C].
        cooling_demand : Union[float, Iterable[float]], optional
            Cooling energy in [kWh] at dataset resolution, converted to average
            control-step power in [kW] for sizing.
        heating_demand : Union[float, Iterable[float]], optional
            Heating energy in [kWh] at dataset resolution.
        safety_factor : Union[float, Tuple[float, float]], default: 1.0
            `nominal_power` is oversized by factor of `safety_factor`.

        Returns
        -------
        nominal_power : float
            Autosized nominal power

        Notes
        -----
        `nominal_power` = max((cooling_demand/cooling_cop) + (heating_demand/heating_cop))*safety_factor
        """
        
        safety_factor = self._get_property_value(safety_factor, 1.0)


        if cooling_demand is not None:
            cooling_demand = np.asarray(cooling_demand) * float(self.time_step_ratio) / seconds_to_hours(self.seconds_per_time_step)
            cooling_nominal_power = np.array(cooling_demand)/self.get_cop(outdoor_dry_bulb_temperature, False)
        else:
            cooling_nominal_power = 0
        
        if heating_demand is not None:
            heating_demand = np.asarray(heating_demand) * float(self.time_step_ratio) / seconds_to_hours(self.seconds_per_time_step)
            heating_nominal_power = np.array(heating_demand)/self.get_cop(outdoor_dry_bulb_temperature, True)
        else:
            heating_nominal_power = 0

        nominal_power = as_float(np.nanmax(cooling_nominal_power + heating_nominal_power))*safety_factor

        return nominal_power

class ElectricHeater(ElectricDevice):
    r"""Base electric heater class.

    Parameters
    ----------
    nominal_power : float, default: (0.9, 0.99)
        Maximum amount of electric power that the electric heater can consume from the power grid.
    efficiency : Union[float, Tuple[float, float]], default: 0.9
        Technical efficiency.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, nominal_power: float = None, efficiency: Union[float, Tuple[float, float]] = None, **kwargs: Any):
        super().__init__(nominal_power = nominal_power, efficiency = efficiency, **kwargs)

    @ElectricDevice.efficiency.setter
    def efficiency(self, efficiency: float):
        efficiency = self._get_property_value(efficiency, (0.9, 0.99))
        ElectricDevice.efficiency.fset(self, efficiency)

    def get_max_output_power(self, max_electric_power: Union[float, Iterable[float]] = None) -> Union[float, Iterable[float]]:
        r"""Return maximum output power.

        Calculate maximum output power from heat pump given `max_electric_power` limitations.

        Parameters
        ----------
        max_electric_power : Union[float, Iterable[float]], optional
            Maximum amount of electric power that the heat pump can consume from the power grid.

        Returns
        -------
        max_output_power : Union[float, Iterable[float]]
            Maximum output power as single value or time series depending on input parameter types.

        Notes
        -----
        max_output_power = min(max_electric_power, `available_nominal_power`)*`efficiency`
        """

        if max_electric_power is None:
            return self.available_nominal_power*self.efficiency
        else:
            return np.min([max_electric_power, self.available_nominal_power], axis=0)*self.efficiency

    def get_input_power(self, output_power: Union[float, Iterable[float]]) -> Union[float, Iterable[float]]:
        r"""Return input power.

        Calculate power demand to meet `output_power`.

        Parameters
        ----------
        output_power : Union[float, Iterable[float]] 
            Output power from heat pump

        Returns
        -------
        input_power : Union[float, Iterable[float]]
            Input power as single value or time series depending on input parameter types.

        Notes
        -----
        input_power = output_power/`efficiency`
        """

        # A scalar stays a float64 scalar, as under NumPy 1; NEP 50 would keep a float32 input in float32.
        return as_float(output_power)/self.efficiency if np.ndim(output_power) == 0 else np.array(output_power)/self.efficiency

    def autosize(self, demand: Iterable[float], safety_factor: Union[float, Tuple[float, float]] = None) -> float:
        r"""Autosize `nominal_power`.

        Set `nominal_power` to the minimum power needed to always meet `demand`.

        Parameters
        ----------
        demand : Union[float, Iterable[float]], optional
            Heating energy in [kWh] at dataset resolution, converted to average
            control-step power in [kW] for sizing.
        safety_factor : Union[float, Tuple[float, float]], default: 1.0
            `nominal_power` is oversized by factor of `safety_factor`.

        Returns
        -------
        nominal_power : float
            Autosized nominal power

        Notes
        -----
        `nominal_power` = max(demand/`efficiency`)*safety_factor
        """
        demand = np.asarray(demand) * float(self.time_step_ratio) / seconds_to_hours(self.seconds_per_time_step)
        safety_factor = self._get_property_value(safety_factor, 1.0)
        nominal_power = as_float(np.nanmax(np.array(demand)/self.efficiency))*safety_factor

        return nominal_power

class PV(ElectricDevice):
    r"""Base photovoltaic array class.

    Parameters
    ----------
    nominal_power : float, default: 0.0
        PV array output power in [kW]. Must be >= 0.
    generation_mode : str, default: 'per_kw'
        How to interpret the `solar_generation` input passed to
        :meth:`get_generation`. In ``'per_kw'`` mode, the input is inverter AC
        output per kW of installed PV capacity in [W/kW]. In ``'absolute'``
        mode, the input is already absolute PV generation in [kWh/step].

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """

    def __init__(self, nominal_power: float = None, generation_mode: str = None, **kwargs: Any):
        super().__init__(nominal_power=nominal_power, **kwargs)
        self.generation_mode = generation_mode

    @property
    def generation_mode(self) -> str:
        """Mode used to interpret the PV generation input series."""

        return self.__generation_mode

    @generation_mode.setter
    def generation_mode(self, generation_mode: str):
        generation_mode = 'per_kw' if generation_mode is None else str(generation_mode).strip().lower()
        generation_mode = generation_mode.replace('-', '_')
        aliases = {
            'profile': 'per_kw',
            'per_kw': 'per_kw',
            'w_per_kw': 'per_kw',
            'absolute': 'absolute',
            'absolute_kwh': 'absolute',
            'kwh': 'absolute',
            'kwh_step': 'absolute',
            'energy': 'absolute',
        }
        assert generation_mode in aliases, (
            "generation_mode must be one of {'per_kw', 'w_per_kw', 'profile', "
            "'absolute', 'absolute_kwh', 'kwh', 'kwh_step', 'energy'}."
        )
        self.__generation_mode = aliases[generation_mode]

    def get_generation(self, inverter_ac_power_per_kw: Union[float, Iterable[float]]) -> Union[float, Iterable[float]]:
        r"""Get solar generation output in kWh per active time step.

        Parameters
        ----------
        inverter_ac_power_perk_w : Union[float, Iterable[float]]
            Inverter AC power output per kW of PV capacity in [W/kW] when
            ``generation_mode='per_kw'``. Absolute PV generation in [kWh/step]
            when ``generation_mode='absolute'``.

        Returns
        -------
        generation : Union[float, Iterable[float]]
            Solar generation in [kWh/step] as single value or time series depending on input parameter types.

        Notes
        -----
        .. math::
            \textrm{generation} = \frac{\textrm{capacity} \times \textrm{inverter_ac_power_per_w}}{1000} \times \Delta t
        """

        if self.generation_mode == 'absolute':
            return np.array(inverter_ac_power_per_kw)

        return self.nominal_power*np.array(inverter_ac_power_per_kw)/1000.0*seconds_to_hours(self.seconds_per_time_step)

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'generation_mode': self.generation_mode,
        }

    def autosize(self, demand: float, epw_filepath: Union[Path, str], use_sample_target: bool = None, zero_net_energy_proportion: Union[float, Tuple[float, float]] = None, roof_area: float = None, safety_factor: Union[float, Tuple[float, float]] = None, sizing_data: pd.DataFrame = None) -> Tuple[float, np.ndarray]:
        r"""Autosize `nominal_power` and `inverter_ac_power_per_kw`.

        Samples PV data from Tracking the Sun dataset to set PV system design parameters in System Adivosry Model's `PVWattsNone` model.
        The PV is sized to generate `zero_net_energy_proportion` of `annual_demand` limited by the `roof_area`. It is assumed that
        the building's roof is suitable for the installation tilt and azimuth in the sampled data.

        Parameters
        ----------
        demand : float
            Building annual demand in [kWh].
        epw_filepath : Union[Path, str]
            EnergyPlus weather file path used as input to :code:`PVWattsNone` model.
        use_sample_target : bool, default: False
            Whether to directly use the sizing in the sampled instance instead of sizing for `zero_net_energy_proportion`.
            Will still limit the size to the `roof_area`.
        zero_net_energy_proportion : Union[float, Tuple[float, float]], default: (0.7, 1.0)
            Proportion
        roof_area : float, optional
            Roof area where the PV is mounted in m^2. The default is to assume an infinite roof area.
        safety_factor : Union[float, Tuple[float, float]], default: 1.0
            The `nominal_power` is oversized by factor of `safety_factor`.
            It is only applied to the `zero_net_energy_proportion` estimate.
        sizing_data: pd.DataFrame, optional
            The sizing dataframe from which PV systems are sampled from. If initialized from
            py:class:`citylearn.citylearn.CityLearnEnv`, the data is parsed in when autosizing
            a building's PV. If the dataframe is not provided it is read in using
            :py:meth:`citylearn.data.DataSet.get_pv_sizing_data`.

        Returns
        -------
        nominal_power : float
            Autosized nominal power.
        inverter_ac_power_per_kw : np.ndarray
            SAM :code:`ac` output for :code:`PVWattsNone` model.

        Notes
        -----
        Data source: https://github.com/intelligent-environments-lab/CityLearn/tree/master/citylearn/data/misc/lbl-tracking_the_sun_res-pv.csv.
        """

        zero_net_energy_proportion = self._get_property_value(zero_net_energy_proportion, (0.7, 1.0))
        safety_factor = self._get_property_value(safety_factor, 1.0)
        roof_area = np.inf if roof_area is None else roof_area
        use_sample_target = False if use_sample_target is None else use_sample_target

        sizing_data = DataSet().get_pv_sizing_data() if sizing_data is None else sizing_data
        random_seed = self.random_seed
        tries = 3

        for i in range(tries):
            self._autosize_config = sizing_data.sample(1, random_state=random_seed + i).iloc[0].to_dict()
            if Pvwattsv8 is None:
                raise ModuleNotFoundError('PySAM is required for PV sizing but is not installed.')
            model = Pvwattsv8.default('PVWattsNone')
            pv_nominal_power = self.autosize_config['nameplate_capacity_module_1']/1000.0
            model.SystemDesign.system_capacity = pv_nominal_power
            model.SystemDesign.dc_ac_ratio = self.autosize_config['inverter_loading_ratio']
            model.SystemDesign.tilt = self.autosize_config['tilt_1']
            model.SystemDesign.azimuth = self.autosize_config['azimuth_1']
            model.SystemDesign.bifaciality = self.autosize_config['bifacial_module_1']*0.65
            model.SolarResource.solar_resource_file = epw_filepath
        
            try:
                model.execute()
                break

            except Exception as e:
                LOGGER.debug(f'Failed to simulate PVWatts using config: {self._autosize_config}')

                if i == tries - 1:
                    raise e
                
                else:
                    pass
        
        inverter_ac_power_per_kw = np.array(model.Outputs.ac, dtype='float32')/pv_nominal_power

        if use_sample_target:
            target_nominal_power = self.autosize_config['PV_system_size_DC']
        
        else:
            zne_nominal_power = demand/sum(inverter_ac_power_per_kw/1000.0)
            limited_zne_nominal_power = zne_nominal_power*zero_net_energy_proportion
            target_nominal_power = math.floor(limited_zne_nominal_power*safety_factor/pv_nominal_power)*pv_nominal_power

        module_area = self.autosize_config['module_area']
        pv_area = pv_nominal_power*5.263 if module_area is None or math.isnan(module_area) else module_area
        # Fix bug: roof_area OverflowError: cannot convert float infinity to integer
        if np.isinf(roof_area):
            roof_limit_nominal_power = np.inf
        else:
            roof_limit_nominal_power = math.floor(roof_area / pv_area) * pv_nominal_power

        nominal_power = min(max(target_nominal_power, pv_nominal_power), roof_limit_nominal_power)
        self._autosize_config = {
            **self.autosize_config,
            'demand': demand,
            'epw_filepath': epw_filepath,
            'use_sample_target': use_sample_target,
            'zero_net_energy_proportion': zero_net_energy_proportion,
            'roof_area': roof_area,
            'safety_factor': safety_factor,
            'pv_area': pv_area,
            'nameplate_capacity_module_1': model.SystemDesign.system_capacity,
            'bifacial_module_1': model.SystemDesign.bifaciality,
            'target_nominal_power': target_nominal_power,
            'roof_limit_nominal_power': roof_limit_nominal_power,
            'nominal_power': nominal_power
        }
        
        return nominal_power, inverter_ac_power_per_kw

class StorageDevice(Device):
    r"""Base storage device class.

    Parameters
    ----------
    capacity : float, default: 0.0
        Maximum amount of energy the storage device can store in [kWh]. Must be >= 0.
    efficiency : Union[float, Tuple[float, float]], default: (0.90, 0.98)
        Technical efficiency.
    loss_coefficient : Union[float, Tuple[float, float]], default: (0.001, 0.009)
        Standby hourly losses. Must be between 0 and 1 (this value is often 0 or really close to 0).
    initial_soc : Union[float, Tuple[float, float]], default: 0.0
        State of charge when `time_step` = 0. Must be >= 0 and < `capacity`.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, capacity: float = None, efficiency: Union[float, Tuple[float, float]] = None, loss_coefficient: Union[float, Tuple[float, float]] = None, initial_soc: Union[float, Tuple[float, float]] = None, time_step_ratio:float = None, **kwargs: Any):
        self.random_seed = kwargs.get('random_seed', None)
        self.capacity = capacity
        self.loss_coefficient = loss_coefficient
        self.initial_soc = initial_soc
        super().__init__(efficiency=efficiency, time_step_ratio=time_step_ratio, **kwargs)

    @property
    def capacity(self) -> float:
        r"""Maximum amount of energy the storage device can store in [kWh]."""

        return self.__capacity
    
    @property
    def time_step_ratio(self) -> float:
        r"""Maximum amount of energy the storage device can store in [kWh]."""

        return self.__time_step_ratio

    @property
    def loss_coefficient(self) -> float:
        r"""Effective step loss, compounded from the configured hourly fraction."""

        step_hours = max(float(self.seconds_per_time_step) / 3600.0, 0.0)
        return 1.0 - (1.0 - self.__loss_coefficient)**step_hours
    
    @property
    def initial_soc(self) -> float:
        r"""State of charge when `time_step` = 0 in [kWh]."""

        return self.__initial_soc

    @property
    def soc(self) -> np.ndarray:
        r"""State of charge time series between [0, 1] in [:math:`\frac{\textrm{capacity}_{\textrm{charged}}}{\textrm{capacity}}`]."""

        return self.__soc

    @property
    def energy_init(self) -> float:
        r"""Physical stored energy in [kWh], including states below the reserve."""
        initialized = getattr(self, '_StorageDevice__soc_initialized', None)
        if (
            initialized is not None
            and self.time_step > 0
            and self.time_step < len(initialized)
            and not bool(initialized[self.time_step])
        ):
            return max(0.0, float(self.__soc[self.time_step - 1])*as_float(self.capacity))
        return max(0.0, float(self.__soc[self.time_step])*as_float(self.capacity))

    @property
    def stored_energy_transfer(self) -> float:
        """Cumulative terminal-flow contribution to stored kWh in this step.

        Includes every charge/discharge call at its own efficiency. Excludes
        standby losses and exogenous SOC assignments such as vehicle arrivals.
        """
        if getattr(self, '_StorageDevice__transfer_time_step', None) != self.time_step:
            return 0.0
        return self.__stored_energy_transfer

    @property
    def gross_energy_charge(self):
        """Actual positive terminal movements, in control-step kWh."""
        return getattr(self, '_StorageDevice__gross_energy_charge', None)

    @property
    def gross_energy_discharge(self):
        return getattr(self, '_StorageDevice__gross_energy_discharge', None)

    @property
    def energy_provenance_events(self):
        """Actual operations in the current step, with AC/storage boundaries.

        This bounded journal is passive: it never feeds the physical model.
        """
        if getattr(self, '_energy_event_step', None) != self.time_step:
            return []
        return self._energy_events

    def _record_energy_event(self, kind, before, after, terminal=0.0):
        if getattr(self, '_energy_event_step', None) != self.time_step:
            self._energy_events = []
            self._energy_event_step = self.time_step
        self._energy_events.append(dict(kind=kind, before=float(before), after=float(after),
                                       terminal=float(terminal), bus=float(terminal)))
        if kind == 'transfer' and self.__gross_energy_charge is not None:
            self.__gross_energy_charge[self.time_step] = float(self.__gross_energy_charge[self.time_step]) + max(float(terminal), 0.0)
            self.__gross_energy_discharge[self.time_step] = float(self.__gross_energy_discharge[self.time_step]) + max(-float(terminal), 0.0)

    @property
    def energy_balance(self) -> np.ndarray:
        r"""Charged/discharged energy time series in [kWh]."""

        return self.__energy_balance
        
    @property
    def round_trip_efficiency(self) -> float:
        """Efficiency square root."""

        return self.efficiency**0.5

    @capacity.setter
    def capacity(self, capacity: float):
        capacity = 0.0 if capacity is None else capacity
        assert capacity >= 0, 'capacity must be >= 0.'
        self.__capacity = capacity

    @Device.efficiency.setter
    def efficiency(self, efficiency: float):
        efficiency = self._get_property_value(efficiency, (0.9, 0.98))
        assert efficiency <= 1.0, 'efficiency must be <= 1.0 for storage devices.'
        Device.efficiency.fset(self, efficiency)

    @loss_coefficient.setter
    def loss_coefficient(self, loss_coefficient: Union[float, Tuple[float, float]]):
        loss_coefficient = self._get_property_value(loss_coefficient, (0.001, 0.009))
        assert 0 <= loss_coefficient <= 1, 'loss_coefficient must be >= 0 and <= 1.'
        self.__loss_coefficient = loss_coefficient

    @initial_soc.setter
    def initial_soc(self, initial_soc: Union[float, Tuple[float, float]]):
        initial_soc = self._get_property_value(initial_soc, 0.0)
        assert 0.0 <= initial_soc <= 1.0, 'initial_soc must be >= 0.0 and <= 1.0.'
        self.__initial_soc = initial_soc

    @time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: float):
        time_step_ratio = self._get_property_value(time_step_ratio, 1.0)

        self.__time_step_ratio = time_step_ratio

    def next_time_step(self):
        try:
            previous_soc = float(self.__soc[self.time_step]) if self.time_step < len(self.__soc) else np.nan
        except AttributeError:
            previous_soc = np.nan

        super().next_time_step()

        if np.isfinite(previous_soc) and self.time_step < len(self.__soc):
            next_soc = clip_scalar(previous_soc * (1.0 - self.loss_coefficient), 0.0, 1.0)
            self.__soc[self.time_step] = next_soc
            self.__soc_initialized[self.time_step] = True
            self._record_energy_event('standby', previous_soc*as_float(self.capacity),
                                      float(self.__soc[self.time_step])*as_float(self.capacity))

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'capacity': self.capacity,
            'loss_coefficient': self.loss_coefficient,
            'initial_soc': self.initial_soc,
            'round_trip_efficiency': self.round_trip_efficiency
        }

    def charge(self, energy: float):
        self._charge(energy)

    def _charge(self, energy: float, energy_init: float = None):
        """Charges or discharges storage with respect to specified energy while considering `capacity` and `soc_init` limitations and, energy losses to the environment quantified by `round_trip_efficiency`.

        Parameters
        ----------
        energy : float
            Energy to charge if (+) or discharge if (-) in [kWh].

        Notes
        -----
        If charging, soc = min(`soc_init` + energy*`round_trip_efficiency`, `capacity`)
        If discharging, soc = max(0, `soc_init` + energy/`round_trip_efficiency`)
        """
        energy = float(energy) * self.time_step_ratio
        energy_init = self.energy_init if energy_init is None else float(energy_init)
        round_trip_efficiency = self.round_trip_efficiency
        # A reserve limits discharge; it must never raise the measured stored energy.
        energy_final = min(energy_init + energy*round_trip_efficiency, as_float(self.capacity)) if energy >= 0\
            else max(min(self._minimum_energy(), energy_init), energy_init + energy/round_trip_efficiency)

        self.__soc[self.time_step] = energy_final/max(as_float(self.capacity), ZERO_DIVISION_PLACEHOLDER)
        self.__soc_initialized[self.time_step] = True
        delta_energy = energy_final - energy_init
        self.__energy_balance[self.time_step] = (
            delta_energy / round_trip_efficiency if delta_energy >= 0 else delta_energy * round_trip_efficiency
        )
        terminal_energy = float(self.__energy_balance[self.time_step])
        stored_change = (terminal_energy * round_trip_efficiency if terminal_energy >= 0.0
                         else terminal_energy / round_trip_efficiency)
        self.__stored_energy_transfer = self.stored_energy_transfer + stored_change
        self.__transfer_time_step = self.time_step

        self._record_energy_event('transfer', energy_init, self.energy_init, terminal_energy)

    def force_set_soc(self, soc: float):
        before = self.energy_init
        self.__soc[self.time_step] = soc
        self.__soc_initialized[self.time_step] = True
        self._record_energy_event('external', before, self.energy_init)

    def initialize_at_activation(self):
        """Record the opening stock of a device entering the simulation mid-episode."""
        self.__soc[self.time_step] = self.initial_soc
        self.__soc_initialized[self.time_step] = True
        self._record_energy_event('external', 0.0, self.energy_init)

    def set_energy_balance(self, energy: float, energy_init:float) -> float:
        r"""Calculate energy balance.

        Parameters
        ----------
        energy: float
            Energy equivalent of state-of-charge in [kWh].
        energy_init: float
            Latest energy level after accounting for standby hourly lossses in [kWh]

        Returns
        -------
        energy: float
            Charged/discharged energy since last time step in [kWh]

        The energy balance is a derived quantity and is the product or quotient of the difference between consecutive SOCs and `round_trip_efficiency`
        for discharge or charge events respectively thus, thus accounts for energy losses to environment during charging and discharge. It is the
        actual energy charged/discharged irrespective of what is determined in the step function after taking into account storage design limits 
        e.g. maximum power input/output, capacity.
        """
        delta_energy = energy - energy_init
        if delta_energy >= 0:
            return delta_energy / self.round_trip_efficiency

        return delta_energy * self.round_trip_efficiency

    def _minimum_soc(self) -> float:
        return 0.0

    def _minimum_energy(self) -> float:
        return self._minimum_soc() * as_float(self.capacity)

    def autosize(self, demand: Iterable[float], safety_factor: Union[float, Tuple[float, float]] = None) -> float:
        r"""Autosize `capacity`.

        Set `capacity` to the minimum capacity needed to always meet `demand`.

        Parameters
        ----------
        demand : Union[float, Iterable[float]], optional
            Thermal energy in [kWh] at dataset resolution. Capacity covers the
            largest control-step demand, rather than a power in [kW].
        safety_factor : Union[float, Tuple[float, float]], default: (1.0, 2.0)
            The `capacity` is oversized by factor of `safety_factor`.

        Returns
        -------
        capacity : float
            Autosized capacity in [kWh].

        Notes
        -----
        `capacity` = max(control-step demand)*safety_factor
        """
        demand = np.asarray(demand) * float(self.time_step_ratio)
        safety_factor = self._get_property_value(safety_factor, (1.0, 2.0))
        capacity = as_float(np.nanmax(demand))*safety_factor

        return capacity

    def reset(self):
        r"""Reset `StorageDevice` to initial state."""

        super().reset()
        self.__soc = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__soc[0] = self.initial_soc
        self.__soc_initialized = np.zeros(self.episode_tracker.episode_time_steps, dtype=bool)
        self.__soc_initialized[0] = True
        self.__energy_balance = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__gross_energy_charge = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32') if isinstance(self, ElectricDevice) and self.capacity > 0 else None
        self.__gross_energy_discharge = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32') if self.__gross_energy_charge is not None else None
        self.__stored_energy_transfer = 0.0
        self.__transfer_time_step = self.time_step
        self._energy_events = []
        self._energy_event_step = self.time_step

class StorageTank(StorageDevice):
    r"""Base thermal energy storage class.

    Parameters
    ----------
    capacity : float, default: 0.0
        Maximum amount of energy the storage device can store in [kWh]. Must be >= 0.
    max_output_power : float, optional
        Maximum amount of power that the storage unit can output [kW].
    max_input_power : float, optional
        Maximum amount of power that the storage unit can use to charge [kW].
    
    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """
    
    def __init__(self, capacity: float = None, max_output_power: float = None, max_input_power: float = None, **kwargs: Any):
        super().__init__(capacity = capacity, **kwargs)
        self.max_output_power = max_output_power
        self.max_input_power = max_input_power

    @property
    def max_output_power(self) -> float:
        r"""Maximum amount of power that the storage unit can output [kW]."""

        return self.__max_output_power

    @property
    def max_input_power(self) -> float:
        r"""Maximum amount of power that the storage unit can use to charge [kW]."""

        return self.__max_input_power

    @max_output_power.setter
    def max_output_power(self, max_output_power: float):
        assert max_output_power is None or max_output_power >= 0, '`max_output_power` must be >= 0.'
        self.__max_output_power = max_output_power

    @max_input_power.setter
    def max_input_power(self, max_input_power: float):
        assert max_input_power is None or max_input_power >= 0, '`max_input_power` must be >= 0.'
        self.__max_input_power = max_input_power

    def charge(self, energy: float):
        """Charges or discharges storage with respect to specified energy while considering `capacity` and `soc_init` limitations and, energy losses to the environment quantified by `efficiency`.

        Parameters
        ----------
        energy : float
            Energy to charge if (+) or discharge if (-) in [kWh].

        Notes
        -----
        If charging, soc = min(`soc_init` + energy*`efficiency`, `max_input_power`, `capacity`)
        If discharging, soc = max(0, `soc_init` + energy/`efficiency`, `max_output_power`)
        """
        if energy >= 0:
            if self.max_input_power is not None:
                max_input_energy = power_kw_to_energy_kwh(self.max_input_power, self.seconds_per_time_step)
                energy = np.nanmin([energy, to_dataset_resolution_energy(max_input_energy, self.time_step_ratio)])
        else:
            if self.max_output_power is not None:
                max_output_energy = power_kw_to_energy_kwh(self.max_output_power, self.seconds_per_time_step)
                energy = np.nanmax([-to_dataset_resolution_energy(max_output_energy, self.time_step_ratio), energy])

        super().charge(energy)

class Battery(StorageDevice, ElectricDevice):
    r"""Base electricity storage class.

    Parameters
    ----------
    capacity : float, default: 0.0
        Maximum amount of energy the storage device can store in [kWh]. Must be >= 0.
    nominal_power: float
        Maximum amount of electric power that the battery can use to charge or discharge.
    capacity_loss_coefficient : Union[float, Tuple[float, float]], default: (1e-5, 1e-4)
        Battery degradation; storage capacity lost in each charge and discharge cycle (as a fraction of the total capacity).
    power_efficiency_curve: list, default: [[0, 0.83],[0.3, 0.83],[0.7, 0.9],[0.8, 0.9],[1, 0.85]]
        Charging/Discharging efficiency as a function of nominal power.
    capacity_power_curve: list, default: [[0.0, 1],[0.8, 1],[1.0, 0.2]]   
        Maximum power of the battery as a function of its current state of charge.
    depth_of_discharge: Union[float, Tuple[float, float]], default: 1.0
        Maximum fraction of the battery that can be discharged relative to the total battery capacity.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super classes.
    """
    
    def __init__(self, capacity: float = None, nominal_power: float = None, capacity_loss_coefficient: Union[float, Tuple[float, float]] = None, power_efficiency_curve: List[List[float]] = None, capacity_power_curve: List[List[float]] = None, depth_of_discharge: Union[float, Tuple[float, float]] = None, time_step_ratio: float = None, **kwargs: Any):
        self._efficiency_history = array('d')
        self._capacity_history = array('d')
        self.random_seed = kwargs.get('random_seed', None)
        self.depth_of_discharge = depth_of_discharge
        super().__init__(capacity=capacity, nominal_power=nominal_power, time_step_ratio = time_step_ratio, **kwargs)
        self._capacity_history = array('d', [self.capacity])
        self.capacity_loss_coefficient = capacity_loss_coefficient
        self.power_efficiency_curve = power_efficiency_curve
        self.capacity_power_curve = capacity_power_curve
        self.time_step_ratio=time_step_ratio

    @StorageDevice.efficiency.getter
    def efficiency(self) -> float:
        """Current time step technical efficiency."""

        return self.efficiency_history[-1]
    
    @property
    def degraded_capacity(self) -> float:
        r"""Maximum amount of energy the storage device can store after degradation in [kWh]."""

        return self.capacity_history[-1]

    @property
    def capacity_loss_coefficient(self) -> float:
        """Battery degradation; storage capacity lost in each charge and discharge cycle (as a fraction of the total capacity)."""

        return self.__capacity_loss_coefficient

    @property
    def power_efficiency_curve(self) -> np.ndarray:
        """Charging/Discharging efficiency as a function of the nomianl power."""

        return self.__power_efficiency_curve

    @property
    def capacity_power_curve(self) -> np.ndarray:
        """Maximum power of the battery as a function of its current state of charge."""

        return self.__capacity_power_curve
    
    @property
    def time_step_ratio(self) -> float:
        """Maximum power of the battery as a function of its current state of charge."""

        return self.__time_step_ratio
    
    @property
    def depth_of_discharge(self) -> float:
        """Maximum fraction of the battery that can be discharged relative to the total battery capacity."""

        return self.__depth_of_discharge

    @property
    def efficiency_history(self) -> Sequence[float]:
        """Time series of technical efficiency."""

        return self._efficiency_history

    @property
    def capacity_history(self) -> Sequence[float]:
        """Time series of maximum amount of energy the storage device can store in [kWh]."""

        return self._capacity_history
    
    @StorageDevice.capacity.setter
    def capacity(self, capacity: Union[float, Tuple[float, float]]):
        StorageDevice.capacity.fset(self, capacity)
        self._capacity_history = array('d', [super().capacity])

    @efficiency.setter
    def efficiency(self, efficiency: Union[float, Tuple[float, float]]):
        StorageDevice.efficiency.fset(self, efficiency)
        self._efficiency_history.append(super().efficiency)

    def set_rated_efficiency(self, efficiency: Union[float, Tuple[float, float]]):
        r"""Replace the rated efficiency outside a simulation, e.g. with a datasheet value after autosizing.

        During simulation `efficiency` is read from `power_efficiency_curve` at every charge or discharge,
        and :py:meth:`reset` restores the first recorded value. Assigning `efficiency` directly therefore
        neither changes the simulated efficiency nor survives a reset. This method makes `efficiency`
        the reset value and rescales a generated `power_efficiency_curve` so that its rated point equals
        it. A user-supplied curve is left unchanged.

        Parameters
        ----------
        efficiency : Union[float, Tuple[float, float]]
            Rated efficiency. `None` or NaN draws the default, as the `efficiency` setter does.
        """

        StorageDevice.efficiency.fset(self, efficiency)
        rated = float(super().efficiency)
        self._efficiency_history = array('d', [rated])
        reference = getattr(self, '_curve_reference_efficiency', None)

        if reference is not None and reference > 0.0 and rated != reference:
            curve = np.array(self.__power_efficiency_curve, dtype=float)
            curve[1] = curve[1]*(rated/reference)
            self.__power_efficiency_curve = curve
            self._curve_reference_efficiency = rated

    @capacity_loss_coefficient.setter
    def capacity_loss_coefficient(self, capacity_loss_coefficient: Union[float, Tuple[float, float]]):
        capacity_loss_coefficient = self._get_property_value(capacity_loss_coefficient, (1e-5, 1e-4))
        assert 0.0 <= capacity_loss_coefficient <= 1.0, 'capacity_loss_coefficient must be >= 0.0 and <= 1.0.'
        self.__capacity_loss_coefficient = capacity_loss_coefficient

    @power_efficiency_curve.setter
    def power_efficiency_curve(self, power_efficiency_curve: List[List[float]]):
        # A generated curve is expressed relative to the rated efficiency it was drawn from,
        # so `set_rated_efficiency` can rescale it; a user-supplied curve is kept as given.
        self._curve_reference_efficiency = float(self.efficiency) if power_efficiency_curve is None else None

        if power_efficiency_curve is None:
            power_efficiency_curve = [
                [0, self.numpy_random_state.uniform(self.efficiency*0.85, self.efficiency*0.90)],
                [self.numpy_random_state.uniform(0.25, 0.35), self.numpy_random_state.uniform(self.efficiency*0.90, self.efficiency*0.95)],
                [self.numpy_random_state.uniform(0.65, 0.75), self.numpy_random_state.uniform(self.efficiency*0.98, self.efficiency*1.0)],
                [self.numpy_random_state.uniform(0.75, 0.85), self.efficiency],
                [1, self.numpy_random_state.uniform(self.efficiency*0.95, self.efficiency*0.98)]
            ]
        else:
            pass

        self.__power_efficiency_curve = np.array(power_efficiency_curve).T

    @capacity_power_curve.setter
    def capacity_power_curve(self, capacity_power_curve: List[List[float]]):
        if capacity_power_curve is None:
            capacity_power_curve = [
                [0.0, self.numpy_random_state.uniform(0.95, 1.0)],
                [self.numpy_random_state.uniform(0.75, 0.85), self.numpy_random_state.uniform(0.90, 0.95)],
                [1.0, self.numpy_random_state.uniform(0.20, 0.30)]
            ]
        else:
            pass

        self.__capacity_power_curve = np.array(capacity_power_curve).T

    @StorageDevice.initial_soc.setter
    def initial_soc(self, initial_soc: float):
        initial_soc = 1.0 - self.depth_of_discharge if initial_soc is None else initial_soc
        StorageDevice.initial_soc.fset(self, initial_soc)

    @depth_of_discharge.setter
    def depth_of_discharge(self, depth_of_discharge: float):
        depth_of_discharge = self._get_property_value(depth_of_discharge, 1.0)
        assert 0.0 <= depth_of_discharge <= 1.0, 'depth_of_discharge must be >= 0.0 and <= 1.0.'
        self.__depth_of_discharge = depth_of_discharge

    @time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: float):
        self.__time_step_ratio = self._get_property_value(time_step_ratio, 1.0)     

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'depth_of_discharge': self.depth_of_discharge,
            'capacity_loss_coefficient': self.capacity_loss_coefficient,
            'power_efficiency_curve': self.power_efficiency_curve,
            'capacity_power_curve': self.capacity_power_curve,
        }

    def charge(self, energy: float):
        """Charges or discharges storage with respect to specified energy while considering `capacity` degradation and `soc_init` 
        limitations, losses to the environment quantified by `efficiency`, `power_efficiency_curve` and `capacity_power_curve`.

        Parameters
        ----------
        energy : float
            Energy to charge if (+) or discharge if (-) in [kWh].
        """
        if np.isnan(self.capacity_before_step[self.time_step]):
            self.capacity_before_step[self.time_step] = self.degraded_capacity
        # Public control paths pass dataset-resolution kWh; physical limits are per control step.
        ratio = self.time_step_ratio if self.time_step_ratio not in (None, 0) else 1.0
        requested_energy = float(energy) * ratio
        step_hours = max(float(self.seconds_per_time_step) / 3600.0, 1.0e-12)
        energy_init = self.energy_init
        degraded_capacity = self.degraded_capacity

        if requested_energy >= 0:
            max_input_power = max(float(self.get_max_input_power(energy_init=energy_init)), 0.0)
            max_input_energy = power_kw_to_energy_kwh(max_input_power, self.seconds_per_time_step)
            limited_energy = min(requested_energy, max_input_energy)

            for _ in range(2):
                self.efficiency = self.get_current_efficiency(abs(limited_energy) / step_hours)
                energy_wrt_degrade = max(degraded_capacity - energy_init, 0.0)
                capacity_limited_energy = energy_wrt_degrade / max(self.round_trip_efficiency, ZERO_DIVISION_PLACEHOLDER)
                limited_energy = min(requested_energy, max_input_energy, capacity_limited_energy)

            energy = limited_energy / ratio

        else:
            max_output_power = max(float(self.get_max_output_power(energy_init=energy_init)), 0.0)
            max_output_energy = power_kw_to_energy_kwh(max_output_power, self.seconds_per_time_step)
            requested_output = abs(requested_energy)
            limited_output = min(requested_output, max_output_energy)

            for _ in range(2):
                self.efficiency = self.get_current_efficiency(limited_output / step_hours)
                soc_limit_wrt_dod = 1.0 - self.depth_of_discharge
                minimum_energy = soc_limit_wrt_dod * self.capacity
                dod_limited_output = max(energy_init - minimum_energy, 0.0) * self.round_trip_efficiency
                limited_output = min(requested_output, max_output_energy, dod_limited_output)

            energy = -limited_output / ratio

        super()._charge(energy, energy_init=energy_init)
        self._capacity_history.append(max(degraded_capacity - self.degrade(), 0.0))
        ratio = self.time_step_ratio if self.time_step_ratio not in (None, 0) else 1.0
        dataset_resolution_balance = self.energy_balance[self.time_step]/ratio
        self.update_electricity_consumption(dataset_resolution_balance, enforce_polarity=False)

    def _minimum_soc(self) -> float:
        return clip_scalar(1.0 - self.depth_of_discharge, 0.0, 1.0)

    def next_time_step(self):
        super().next_time_step()
        if self.time_step < len(self.capacity_before_step):
            self.capacity_before_step[self.time_step] = self.degraded_capacity

    def get_max_output_power(self, energy_init: float = None) -> float:
        r"""Get maximum output power while considering `capacity_power_curve` limitations if defined otherwise, returns `nominal_power`.

        Returns
        -------
        max_output_power : float
            Maximum amount of power that the storage unit can output [kW].
        """

        return self.get_max_input_power(energy_init=energy_init)

    def get_max_input_power(self, energy_init: float = None) -> float:
        r"""Get maximum input power while considering `capacity_power_curve` limitations.

        Returns
        -------
        max_input_power : float
            Maximum amount of power that the storage unit can use to charge [kW].
        """

        #The initial SOC is the previous SOC minus the energy losses
        energy_init = self.energy_init if energy_init is None else energy_init
        soc = energy_init/max(self.capacity, ZERO_DIVISION_PLACEHOLDER)
        curve_x = self.capacity_power_curve[0]
        curve_y = self.capacity_power_curve[1]
        if not np.isfinite(soc):
            return np.nan

        # Calculating the maximum power rate at which the battery can be charged or discharged
        idx = min(len(curve_x) - 2, max(0, int(np.searchsorted(curve_x, soc, side='left')) - 1))
        max_output_power = self.nominal_power*(
            curve_y[idx]
            + (curve_y[idx+1] - curve_y[idx])*(soc - curve_x[idx])
            /(curve_x[idx+1] - curve_x[idx])
        )
        
        return max_output_power

    def get_current_efficiency(self, power: float) -> float:
        r"""Get technical efficiency while considering `power_efficiency_curve` limitations.

        Returns
        -------
        efficiency : float
            Technical efficiency.
        """

        # Efficiency curves are defined on normalized average power, not kWh per step.
        power_normalized = min(max(abs(float(power))/max(self.nominal_power, ZERO_DIVISION_PLACEHOLDER), 0.0), 1.0)
        curve_x = self.power_efficiency_curve[0]
        curve_y = self.power_efficiency_curve[1]
        if not np.isfinite(power_normalized):
            return np.nan
        idx = min(len(curve_x) - 2, max(0, int(np.searchsorted(curve_x, power_normalized, side='left')) - 1))
        efficiency = curve_y[idx]\
            + (power_normalized - curve_x[idx]
            )*(curve_y[idx + 1] - curve_y[idx]
            )/(curve_x[idx + 1] - curve_x[idx])

        return efficiency

    def force_set_soc(self, soc: float):
        """
        Forcefully set the battery's state-of-charge (SOC) for the current time step,
        bypassing restrictions such as efficiency losses, power limits, and degradation.

        This is used for reconnections of the EV to the platform.

        Parameters
        ----------
        soc : float
            Desired state-of-charge as a fraction (between 0 and 1). Values outside this range are not accepted.
        """
        # Ensure soc is between 0 and 1
        if soc < 0 or soc > 1:
            raise AttributeError("Soc must be between 0 and 1. Check your dataset")
        # Directly update the internal SOC array.
        # Note: __soc is defined in the StorageDevice class, so we access it via name mangling.
        super().force_set_soc(soc)

    def degrade(self) -> float:
        r"""Get amount of capacity degradation.

        Returns
        -------
        capacity : float
            Maximum amount of energy the storage device can store in [kWh].
        """

        # Calculating the degradation of the battery: new max. capacity of the battery after charge/discharge
        capacity_degrade = self.capacity_loss_coefficient*self.capacity*abs(float(self.energy_balance[self.time_step]))/(2*max(self.degraded_capacity, ZERO_DIVISION_PLACEHOLDER))
        return capacity_degrade
    
    def autosize(
        self, demand: float, duration: Union[float, Tuple[float, float]] = None, parallel: bool = None, safety_factor: Union[float, Tuple[float, float]] = None,
        sizing_data: pd.DataFrame = None
    ) -> Tuple[float, float, float, float, float, float]:
        r"""Randomly selects a battery from the internally defined real world manufacturer model and autosizes its parameters.

        The total capacity and nominal power are autosized using average demand power for a specified duration. It is assumed that
        there is no limit on the number of batteries that can be connected in series or parallel for any of the battery models.

        Parameters
        ----------
        demand : float
            Building energy demand in [kWh] at dataset resolution. Converted
            to average control-step power in [kW] before applying duration.
        duration : Union[float, Tuple[float, float]], default : (1.5, 3.5)
            Number of hours the sized battery should be able to meet demand.
        parallel : bool, default : False
            Whether to assume multiple batteries are connected in parallel so
            that the maximum nominal power is the product of the unit count and
            the nominal_power of one battery i.e., increasing number of battery
            units also increases nominal power.
        safety_factor : Union[float, Tuple[float, float]], default: 1.0
            The `target capacity is oversized by factor of `safety_factor`.

        Returns
        -------
        capacity : float
            Selected battery's autosized capacity to meet demand for duration.
        nominal_power : float
            Selected battery's autosized nominal power to meet demand for duration.
        depth_of_discharge : float
            Selected battery depth-of-discharge.
        efficiency : float
            Selected battery efficiency.
        loss_coefficient : float
            Selected battery loss coefficient.
        capacity_loss_coefficient : float
            Selected battery capacity loss coefficient.
        sizing_data: pd.DataFrame, optional
            The sizing dataframe from which batteries systems are sampled from. If initialized from
            py:class:`citylearn.citylearn.CityLearnEnv`, the data is parsed in when autosizing
            a building's battery. If the dataframe is not provided it is read in using
            :py:meth:`citylearn.data.DataSet.get_battery_sizing_data`.

        Notes
        -----
        Data source: https://github.com/intelligent-environments-lab/CityLearn/tree/master/citylearn/data/misc/battery_choices.yaml.
        """

        demand = float(demand) * self.time_step_ratio / seconds_to_hours(self.seconds_per_time_step)
        duration = self._get_property_value(duration, (1.5, 3.5))
        safety_factor = self._get_property_value(safety_factor, 1.0)
        parallel = False if parallel is None else parallel

        sizing_data = DataSet().get_battery_sizing_data() if sizing_data is None else sizing_data
        choices = sizing_data[sizing_data['nominal_power']<=demand].copy()

        if choices.shape[0] == 0:
            choices = sizing_data.sort_values('nominal_power').iloc[0:1].copy()
        
        else:
            pass
        
        choices = choices.to_dict('index')
        choice = self.numpy_random_state.choice(list(choices.keys()))
        target_capacity = demand*duration*safety_factor
        unit_count = max(1, math.floor(target_capacity/choices[choice]['capacity']))
        
        capacity = choices[choice]['capacity']*unit_count
        nominal_power = choices[choice]['nominal_power']*max(1.0, unit_count*int(parallel))
        depth_of_discharge = choices[choice]['depth_of_discharge']
        efficiency = choices[choice]['efficiency']
        loss_coefficient = choices[choice]['loss_coefficient']
        capacity_loss_coefficient = choices[choice]['capacity_loss_coefficient']
        
        self._autosize_config = {
            'model': choice,
            'demand': demand,
            'duration': duration,
            'safety_factor': safety_factor,
            'unit_count': unit_count,
            **choices[choice],
        }

        return capacity, nominal_power, depth_of_discharge, efficiency, loss_coefficient, capacity_loss_coefficient

    def as_dict(self) -> dict:
        """
        Return a dictionary representation of the current state for use in rendering or logging.
        """
        return {
            'Battery Soc-%': self.soc[self.time_step],
            'Battery (Dis)Charge-kWh': self.energy_balance[self.time_step]
        }

    def reset(self):
        r"""Reset `Battery` to initial state."""

        super().reset()
        self._efficiency_history = self._efficiency_history[0:1]
        self._capacity_history = self._capacity_history[0:1]
        self.capacity_before_step = np.full(self.episode_tracker.episode_time_steps, np.nan)
        self.capacity_before_step[0] = self.degraded_capacity

class DeferrableAppliance(ElectricDevice):
    """Generic deferrable appliance with sparse cycle requests and fixed kWh/step profiles."""

    SENTINEL_TIME_STEP = -1.0
    _cycle_index = None  # Older serialized appliances rebuild this lazily.

    def __init__(
        self,
        deferrable_appliance_simulation: DeferrableApplianceSimulation,
        name: str = None,
        trigger_threshold: float = 0.5,
        **kwargs,
    ):
        self.deferrable_appliance_simulation = deferrable_appliance_simulation
        self.name = name
        default_trigger_threshold = 0.5
        if trigger_threshold is None:
            threshold = default_trigger_threshold
        else:
            try:
                threshold = float(trigger_threshold)
            except (TypeError, ValueError):
                threshold = default_trigger_threshold
        if not np.isfinite(threshold):
            threshold = default_trigger_threshold
        self.trigger_threshold = float(np.clip(threshold, 0.0, 1.0))
        self.__past_action_values = None
        self.__cycle_state: Dict[str, str] = {}
        self.__cycle_start_time_steps: Dict[str, int] = {}
        self.__cycle_completion_time_steps: Dict[str, int] = {}
        self.__cycle_missed_time_steps: Dict[str, int] = {}
        self.__cycle_cancelled_time_steps: Dict[str, int] = {}
        super().__init__(**kwargs)

    @property
    def deferrable_appliance_simulation(self) -> DeferrableApplianceSimulation:
        return self.__deferrable_appliance_simulation

    @deferrable_appliance_simulation.setter
    def deferrable_appliance_simulation(self, value: DeferrableApplianceSimulation):
        self.__deferrable_appliance_simulation = value
        self._cycle_index = None

    @property
    def name(self) -> str:
        return self.__name

    @name.setter
    def name(self, value: str):
        self.__name = value

    @property
    def past_action_values(self) -> np.ndarray:
        return self.__past_action_values

    @property
    def cycle_state(self) -> Mapping[str, str]:
        return dict(self.__cycle_state)

    def reset(self):
        super().reset()
        self._cycle_index = None
        self._validate_cycle_profiles_against_nominal_power()
        self.__past_action_values = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__cycle_state = {}
        self.__cycle_start_time_steps = {}
        self.__cycle_completion_time_steps = {}
        self.__cycle_missed_time_steps = {}
        self.__cycle_cancelled_time_steps = {}
        from citylearn.internal.deferrable_service_audit import ServiceLedger
        episode_start = int(self.episode_tracker.episode_start_time_step or 0)
        self._service_ledger = ServiceLedger(
            episode_start, episode_start + int(self.episode_tracker.episode_time_steps) - 1,
        )
        self.action_feedback_last_start_requested = np.zeros(self.episode_tracker.episode_time_steps, dtype=bool)
        self.action_feedback_last_start_applied = np.zeros(self.episode_tracker.episode_time_steps, dtype=bool)
        self.action_feedback_start_blocked = np.zeros(self.episode_tracker.episode_time_steps, dtype=bool)
        for reason in (
            'availability',
            'power_limit',
            'soc_limit',
            'building_headroom',
            'phase_headroom',
            'export_headroom',
            'outage',
            'deferrable_window',
        ):
            setattr(
                self,
                f'action_feedback_clip_reason_{reason}',
                np.zeros(self.episode_tracker.episode_time_steps, dtype=bool),
            )

        episode_start = int(getattr(self.episode_tracker, 'episode_start_time_step', 0) or 0)
        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            cycle_id = cycle['cycle_id']
            if int(cycle['latest_start_time_step']) < episode_start:
                self._set_cycle_state(cycle_id, 'expired_before_episode')
            else:
                self._set_cycle_state(cycle_id, 'pending')

    def skip_cycles_before(self, global_time_step: int):
        """Exclude requests that expired before an asset/member became active.

        Dynamic topology may introduce a member or reinstall an appliance after
        the episode has started.  Requests whose admissible start window has
        already closed were never offered to the controller and must therefore
        not be reported as missed service, even when their completion deadline
        lies after activation.
        """

        activation = int(global_time_step)
        self._service_ledger.activation = activation
        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            cycle_id = cycle['cycle_id']
            if (
                self.__cycle_state.get(cycle_id) == 'pending'
                and int(cycle['latest_start_time_step']) < activation
            ):
                self._set_cycle_state(cycle_id, 'expired_before_activation')

    def next_time_step(self):
        super().next_time_step()
        self._update_cycle_states()

    def start_cycle(self, action_value: float):
        """Start next pending cycle when the ON command is active and the request is feasible."""

        if self.__past_action_values is None:
            self.__past_action_values = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')

        try:
            action_scalar = float(action_value)
        except (TypeError, ValueError):
            action_scalar = 0.0
        if not np.isfinite(action_scalar):
            action_scalar = 0.0
        self.__past_action_values[self.time_step] = action_scalar
        self._update_cycle_states()

        if not self._is_start_command(action_scalar):
            return

        cycle = self._next_pending_cycle()
        if cycle is None:
            return

        current_global = self._current_global_time_step()
        if not self._can_start_cycle(cycle, current_global):
            if current_global > int(cycle['latest_start_time_step']):
                self._mark_missed(cycle, current_global)
            return
        if not self._cycle_respects_nominal_power(cycle):
            return

        cycle_id = cycle['cycle_id']
        self._set_cycle_state(cycle_id, 'running')
        self.__cycle_start_time_steps[cycle_id] = current_global
        self._service_ledger.start(cycle, current_global)

        for offset, energy_kwh in enumerate(cycle['load_profile']):
            step = self.time_step + offset
            if 0 <= step < self.episode_tracker.episode_time_steps:
                ratio = self.time_step_ratio if self.time_step_ratio not in (None, 0) else 1.0
                self._ElectricDevice__electricity_consumption[step] = (
                    float(self._ElectricDevice__electricity_consumption[step]) + float(energy_kwh) / ratio
                )

    def preview_start_energy_kwh(self, action_value: float) -> float:
        """Return current-step energy that would be added if ``action_value`` starts a cycle."""

        profile = self.preview_start_profile_kwh(action_value)
        return float(profile[0]) if profile.size > 0 else 0.0

    def preview_start_profile_kwh(self, action_value: float) -> np.ndarray:
        """Return the full profile that would be added if ``action_value`` starts a cycle."""

        self._update_cycle_states()
        if not self._is_start_command(action_value):
            return np.zeros(0, dtype='float32')

        cycle = self._next_pending_cycle()
        if cycle is None:
            return np.zeros(0, dtype='float32')

        if not self._can_start_cycle(cycle, self._current_global_time_step()):
            return np.zeros(0, dtype='float32')
        if not self._cycle_respects_nominal_power(cycle):
            return np.zeros(0, dtype='float32')

        return np.array(cycle['load_profile'], dtype='float32')

    def cancel_pending_and_running(self, global_time_step: Optional[int] = None, reason: str = 'asset_removed'):
        """Cancel future service after a dynamic topology removal."""

        current_global = self._current_global_time_step() if global_time_step is None else int(global_time_step)
        self._service_ledger.cancel(current_global, reason)
        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            cycle_id = cycle['cycle_id']
            if (self.__cycle_state.get(cycle_id) in {'pending', 'running'}
                    or (cycle_id in self._service_ledger.starts and cycle_id not in self._service_ledger.finished)):
                self._set_cycle_state(cycle_id, 'cancelled')
                self.__cycle_cancelled_time_steps[cycle_id] = current_global

        local_step = int(self.time_step)
        if self._ElectricDevice__electricity_consumption is not None and local_step < len(self._ElectricDevice__electricity_consumption):
            self._ElectricDevice__electricity_consumption[local_step:] = 0.0

    def observations(self) -> Mapping[str, float]:
        self._update_cycle_states()
        cycle = self._current_or_next_cycle()
        current_global = self._current_global_time_step()
        step_hours = max(float(self.seconds_per_time_step) / 3600.0, 1.0e-6)

        if cycle is None:
            return {
                'pending': 0.0,
                'running': 0.0,
                'can_start': 0.0,
                'deadline_missed': 0.0,
                'earliest_start_time_step': self.SENTINEL_TIME_STEP,
                'latest_start_time_step': self.SENTINEL_TIME_STEP,
                'deadline_time_step': self.SENTINEL_TIME_STEP,
                'hours_until_latest_start': -1.0,
                'hours_until_deadline': -1.0,
                'slack_steps': -1.0,
                'slack_ratio': -1.0,
                'urgency_ratio': -1.0,
                'cycle_duration_steps': 0.0,
                'cycle_energy_kwh': 0.0,
                'remaining_energy_kwh': 0.0,
                'current_step_energy_kwh': 0.0,
                'priority': 0.0,
                'must_run': 0.0,
                'cycle_average_power_kw': 0.0,
                'cycle_peak_power_kw': 0.0,
                'cycle_load_factor_ratio': 0.0,
                'cycle_peak_step_offset_ratio': -1.0,
                'remaining_duration_steps': 0.0,
                'remaining_average_power_kw': 0.0,
                'current_step_power_kw': 0.0,
            }

        cycle_id = cycle['cycle_id']
        state = self.__cycle_state.get(cycle_id, 'pending')
        running = state == 'running'
        pending = state == 'pending'
        missed = state == 'missed'
        latest = int(cycle['latest_start_time_step'])
        earliest = int(cycle['earliest_start_time_step'])
        deadline = int(cycle['deadline_time_step'])
        slack_steps = max(float(latest - current_global), 0.0) if pending else 0.0
        window_steps = max(float(latest - earliest), 1.0)
        slack_ratio = np.clip(slack_steps / window_steps, 0.0, 1.0) if pending else 0.0
        current_energy = self._current_cycle_energy(cycle)
        remaining_energy = self._remaining_cycle_energy(cycle)
        profile = np.array(cycle['load_profile'], dtype='float64')
        duration_steps = max(int(cycle['duration_steps']), 0)
        cycle_duration_hours = max(float(duration_steps) * step_hours, 1.0e-6)
        cycle_average_power = float(cycle['total_energy_kwh']) / cycle_duration_hours if duration_steps > 0 else 0.0
        peak_energy = float(np.nanmax(profile)) if profile.size > 0 else 0.0
        cycle_peak_power = peak_energy / step_hours
        cycle_load_factor = cycle_average_power / cycle_peak_power if cycle_peak_power > 0.0 else 0.0
        peak_offset_ratio = (
            float(int(np.nanargmax(profile))) / max(float(duration_steps - 1), 1.0)
            if profile.size > 0 and duration_steps > 1
            else 0.0
        )
        remaining_duration_steps = self._remaining_cycle_duration_steps(cycle)
        remaining_duration_hours = max(float(remaining_duration_steps) * step_hours, 1.0e-6)
        remaining_average_power = remaining_energy / remaining_duration_hours if remaining_duration_steps > 0 else 0.0

        return {
            'pending': 1.0 if pending else 0.0,
            'running': 1.0 if running else 0.0,
            'can_start': 1.0 if self._can_start_cycle(cycle, current_global) else 0.0,
            'deadline_missed': 1.0 if missed else 0.0,
            'earliest_start_time_step': float(earliest),
            'latest_start_time_step': float(latest),
            'deadline_time_step': float(deadline),
            'hours_until_latest_start': max(float(latest - current_global), 0.0) * step_hours if pending else 0.0,
            'hours_until_deadline': max(float(deadline - current_global), 0.0) * step_hours if pending or running else 0.0,
            'slack_steps': slack_steps,
            'slack_ratio': float(slack_ratio),
            'urgency_ratio': float(1.0 - slack_ratio) if pending else 0.0,
            'cycle_duration_steps': float(cycle['duration_steps']),
            'cycle_energy_kwh': float(cycle['total_energy_kwh']),
            'remaining_energy_kwh': remaining_energy,
            'current_step_energy_kwh': current_energy,
            'priority': float(cycle['priority']),
            'must_run': 1.0 if bool(cycle.get('must_run', False)) else 0.0,
            'cycle_average_power_kw': cycle_average_power,
            'cycle_peak_power_kw': cycle_peak_power,
            'cycle_load_factor_ratio': float(np.clip(cycle_load_factor, 0.0, 1.0)),
            'cycle_peak_step_offset_ratio': float(np.clip(peak_offset_ratio, 0.0, 1.0)),
            'remaining_duration_steps': float(remaining_duration_steps),
            'remaining_average_power_kw': remaining_average_power,
            'current_step_power_kw': current_energy / step_hours,
        }

    def record_service_interval(self):
        """Record the executed interval, never the prebooked future profile."""
        energy = (float(self._ElectricDevice__electricity_consumption[self.time_step])
                  * self._electricity_consumption_ratio())
        self._service_ledger.record(self._current_global_time_step(), energy)

    def exclude_previously_offered_cycles(self, cycle_ids):
        """A reinstall must not offer the same logical request twice."""
        self._service_ledger.excluded.update(cycle_ids)
        for cycle_id in cycle_ids:
            if self.__cycle_state.get(cycle_id) == 'pending':
                self._set_cycle_state(cycle_id, 'already_accounted_previous_instance')

    def service_audit(self):
        """Pure snapshot of actual service with exclusive states and reasons."""
        from citylearn.internal.deferrable_service_audit import DEFINITION_VERSION
        return dict(definition_version=DEFINITION_VERSION,
                    records=self._service_ledger.records(self.deferrable_appliance_simulation.flexibility_schedule),
                    physical_energy_kwh=self._service_ledger.physical_energy)

    def service_summary(self) -> Mapping[str, float]:
        self._finalize_running_cycles_at_current_step()
        completed = 0
        missed = 0
        served = 0.0
        unserved = 0.0
        delays = []

        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            cycle_id = cycle['cycle_id']
            state = self.__cycle_state.get(cycle_id)
            if state == 'completed':
                completed += 1
                served += float(cycle['total_energy_kwh'])
                start = self.__cycle_start_time_steps.get(cycle_id)
                if start is not None:
                    delays.append(max(int(start) - int(cycle['earliest_start_time_step']), 0))
            elif state == 'missed':
                missed += 1
                unserved += float(cycle['total_energy_kwh'])

        requested = completed + missed
        step_hours = max(float(self.seconds_per_time_step) / 3600.0, 1.0e-6)
        return {
            'completed_cycles': float(completed),
            'missed_cycles': float(missed),
            'service_level_ratio': float(completed / requested) if requested > 0 else 1.0,
            'served_energy_kwh': float(served),
            'unserved_energy_kwh': float(unserved),
            'average_start_delay_hours': float(np.mean(delays) * step_hours) if delays else 0.0,
        }

    def as_dict(self) -> dict:
        return {
            'name': self.name,
            **self.observations(),
            **self.service_summary(),
        }

    def _current_global_time_step(self) -> int:
        episode_start_time_step = getattr(self.episode_tracker, 'episode_start_time_step', 0)
        if not isinstance(episode_start_time_step, (int, float, np.integer, np.floating)):
            episode_start_time_step = 0
        return int(episode_start_time_step) + int(self.time_step)

    def _cycle_peak_power_kw(self, cycle: Mapping[str, Any]) -> float:
        profile = np.array(cycle.get('load_profile', []), dtype='float64')
        if profile.size == 0:
            return 0.0
        step_hours = max(seconds_to_hours(self.seconds_per_time_step), 1.0e-12)
        return float(np.nanmax(profile) / step_hours)

    def _cycle_respects_nominal_power(self, cycle: Mapping[str, Any]) -> bool:
        nominal_power = float(getattr(self, 'nominal_power', 0.0) or 0.0)
        if nominal_power <= 0.0:
            return True
        return self._cycle_peak_power_kw(cycle) <= nominal_power + 1.0e-9

    def _validate_cycle_profiles_against_nominal_power(self):
        nominal_power = float(getattr(self, 'nominal_power', 0.0) or 0.0)
        if nominal_power <= 0.0:
            return

        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            peak_power = self._cycle_peak_power_kw(cycle)
            if peak_power > nominal_power + 1.0e-9:
                raise ValueError(
                    f"Deferrable appliance '{self.name}' cycle '{cycle['cycle_id']}' peak power "
                    f"{peak_power:.6g} kW exceeds nominal_power {nominal_power:.6g} kW."
                )

    def _get_cycle_index(self):
        schedule = self.deferrable_appliance_simulation.flexibility_schedule
        index = self._cycle_index
        if index is None or index.schedule is not schedule or index.size != len(schedule):
            index = self._cycle_index = CycleIndex(schedule, self.__cycle_state)
        return index

    def _set_cycle_state(self, cycle_id, state):
        self.__cycle_state[cycle_id] = state
        if self._cycle_index is not None:
            self._cycle_index.changed(cycle_id, state)

    def _next_pending_cycle(self) -> Optional[Mapping[str, Any]]:
        return self._get_cycle_index().first('pending')

    def _current_or_next_cycle(self) -> Optional[Mapping[str, Any]]:
        index = self._get_cycle_index()
        for state in ('running', 'pending', 'missed'):
            cycle = index.first(state)
            if cycle is not None:
                return cycle
        return None

    def _can_start_cycle(self, cycle: Mapping[str, Any], current_global: int) -> bool:
        if self.__cycle_state.get(cycle['cycle_id']) != 'pending':
            return False
        if not int(cycle['earliest_start_time_step']) <= current_global <= int(cycle['latest_start_time_step']):
            return False
        if current_global + int(cycle['duration_steps']) - 1 > int(cycle['deadline_time_step']):
            return False
        # The terminal environment index is not aggregated by Building.step, so a cycle must finish
        # before it to avoid writing energy that can never appear in building or district totals.
        if self.time_step + int(cycle['duration_steps']) >= int(self.episode_tracker.episode_time_steps):
            return False
        return True

    def _is_start_command(self, action_value: float) -> bool:
        try:
            action_scalar = float(action_value)
        except (TypeError, ValueError):
            return False
        if not np.isfinite(action_scalar):
            return False
        return action_scalar > self.trigger_threshold

    def _update_cycle_states(self):
        current_global = self._current_global_time_step()
        index = self._get_cycle_index()
        for cycle in index.running():
            cycle_id = cycle['cycle_id']
            start = self.__cycle_start_time_steps.get(cycle_id)
            if start is not None and current_global > start + int(cycle['duration_steps']) - 1:
                self._set_cycle_state(cycle_id, 'completed')
                self.__cycle_completion_time_steps[cycle_id] = current_global - 1
        if index.ordered_latest:
            # Validated non-overlapping calendars have increasing latest-start bounds.
            # Only requests whose boundary was crossed can change in this call.
            while True:
                cycle = index.first('pending')
                if cycle is None or current_global <= int(cycle['latest_start_time_step']):
                    break
                self._mark_missed(cycle, current_global)
        else:
            # Preserve permissive direct-constructor calendars outside the normal parser.
            for cycle in index.schedule:
                if current_global > int(cycle['latest_start_time_step']):
                    self._mark_missed(cycle, current_global)

    def _mark_missed(self, cycle: Mapping[str, Any], current_global: int):
        cycle_id = cycle['cycle_id']
        if self.__cycle_state.get(cycle_id) == 'pending':
            self._set_cycle_state(cycle_id, 'missed')
            self.__cycle_missed_time_steps[cycle_id] = int(current_global)

    def _finalize_running_cycles_at_current_step(self):
        """Close cycles whose last energy step has already been reached."""

        current_global = self._current_global_time_step()
        for cycle in self._get_cycle_index().running():
            cycle_id = cycle['cycle_id']
            start = self.__cycle_start_time_steps.get(cycle_id)
            if start is not None and current_global >= int(start) + int(cycle['duration_steps']) - 1:
                self._set_cycle_state(cycle_id, 'completed')
                self.__cycle_completion_time_steps[cycle_id] = int(start) + int(cycle['duration_steps']) - 1

    def _current_cycle_energy(self, cycle: Mapping[str, Any]) -> float:
        cycle_id = cycle['cycle_id']
        if self.__cycle_state.get(cycle_id) != 'running':
            return 0.0
        start = self.__cycle_start_time_steps.get(cycle_id)
        if start is None:
            return 0.0
        offset = self._current_global_time_step() - int(start)
        profile = cycle['load_profile']
        if 0 <= offset < len(profile):
            return float(profile[offset])
        return 0.0

    def _remaining_cycle_energy(self, cycle: Mapping[str, Any]) -> float:
        cycle_id = cycle['cycle_id']
        state = self.__cycle_state.get(cycle_id)
        profile = cycle['load_profile']
        if state == 'pending':
            return float(cycle['total_energy_kwh'])
        if state == 'running':
            start = self.__cycle_start_time_steps.get(cycle_id)
            if start is None:
                return 0.0
            offset = max(self._current_global_time_step() - int(start), 0)
            if offset < len(profile):
                return float(np.sum(profile[offset:]))
        return 0.0

    def _remaining_cycle_duration_steps(self, cycle: Mapping[str, Any]) -> int:
        cycle_id = cycle['cycle_id']
        state = self.__cycle_state.get(cycle_id)
        profile = cycle['load_profile']
        if state == 'pending':
            return int(cycle['duration_steps'])
        if state == 'running':
            start = self.__cycle_start_time_steps.get(cycle_id)
            if start is None:
                return 0
            offset = max(self._current_global_time_step() - int(start), 0)
            return max(len(profile) - int(offset), 0)
        return 0


class Escalator(ElectricDevice):
    """Aggregate escalator with three directly controllable operating states.

    Actions in ``[0, 1]`` map to standby, slow and normal operation.  Passenger
    values are not used to force a state: they only determine whether the chosen
    state meets the simple aggregate service requirement.  This deliberately
    avoids an unsupported queueing model while making the energy/service tradeoff
    explicit to an agent.
    """

    STATE_STANDBY = 0
    STATE_SLOW = 1
    STATE_NORMAL = 2
    STATE_NAMES = ('standby', 'slow', 'normal')

    def __init__(
        self,
        escalator_simulation: EscalatorSimulation,
        name: str = None,
        standby_power: float = 0.0,
        slow_power: float = 0.0,
        normal_power: float = 0.0,
        minimum_state_steps: int = 1,
        service_threshold_passengers: float = 0.5,
        **kwargs,
    ):
        self.escalator_simulation = escalator_simulation
        self.name = str(name) if name is not None else 'escalator'
        self.standby_power = self._as_non_negative_power(standby_power, 'standby_power')
        self.slow_power = self._as_non_negative_power(slow_power, 'slow_power')
        self.normal_power = self._as_non_negative_power(normal_power, 'normal_power')
        if not self.standby_power <= self.slow_power <= self.normal_power:
            raise ValueError('Escalator powers must satisfy standby_power <= slow_power <= normal_power.')
        try:
            minimum_state_steps = int(minimum_state_steps)
        except (TypeError, ValueError) as exc:
            raise ValueError('minimum_state_steps must be an integer >= 1.') from exc
        if minimum_state_steps < 1:
            raise ValueError('minimum_state_steps must be >= 1.')
        self.minimum_state_steps = minimum_state_steps
        self.service_threshold_passengers = self._as_non_negative_power(
            service_threshold_passengers, 'service_threshold_passengers'
        )
        self.__state = self.STATE_STANDBY
        self.__requested_state = self.STATE_STANDBY
        self.__state_start_time_step = -int(minimum_state_steps)
        super().__init__(nominal_power=self.normal_power, **kwargs)

    @staticmethod
    def _as_non_negative_power(value, name: str) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{name} must be a finite number >= 0.') from exc
        if not np.isfinite(value) or value < 0.0:
            raise ValueError(f'{name} must be a finite number >= 0.')
        return value

    @property
    def state(self) -> int:
        return int(self.__state)

    @property
    def requested_state(self) -> int:
        return int(self.__requested_state)

    @property
    def state_name(self) -> str:
        return self.STATE_NAMES[self.state]

    def reset(self):
        super().reset()
        steps = self.episode_tracker.episode_time_steps
        self.__state = self.STATE_STANDBY
        self.__requested_state = self.STATE_STANDBY
        # The initial standby state is not an operator command. Allow the first
        # agent action to select an operating state at timestep zero.
        self.__state_start_time_step = -self.minimum_state_steps
        self.state_history = np.zeros(steps, dtype='int8')
        self.requested_state_history = np.zeros(steps, dtype='int8')
        self.service_required = np.zeros(steps, dtype=bool)
        self.service_met = np.ones(steps, dtype=bool)
        self.unserved_passengers = np.zeros(steps, dtype='float32')
        self.state_changes = np.zeros(steps, dtype=bool)
        self.action_applied = np.zeros(steps, dtype=bool)

    def _value(self, name: str, default: float = 0.0) -> float:
        values = getattr(self.escalator_simulation, name, None)
        if values is None or self.time_step >= len(values):
            return float(default)
        try:
            value = float(values[self.time_step])
        except (TypeError, ValueError, IndexError):
            return float(default)
        return value if np.isfinite(value) else float(default)

    def _available(self) -> bool:
        return self._value('available', 1.0) >= 0.5

    @classmethod
    def action_to_state(cls, action_value: float) -> int:
        try:
            action = float(action_value)
        except (TypeError, ValueError):
            action = 0.0
        if not np.isfinite(action):
            action = 0.0
        action = float(np.clip(action, 0.0, 1.0))
        if action < 1.0 / 3.0:
            return cls.STATE_STANDBY
        if action < 2.0 / 3.0:
            return cls.STATE_SLOW
        return cls.STATE_NORMAL

    def _power_for_state(self, state: int) -> float:
        return (self.standby_power, self.slow_power, self.normal_power)[int(state)]

    def set_state(self, action_value: float):
        """Apply the normalized action and record current-step power/service."""

        requested = self.action_to_state(action_value)
        desired = requested if self._available() else self.STATE_STANDBY
        changed = False
        if desired != self.__state:
            elapsed = int(self.time_step) - int(self.__state_start_time_step)
            if elapsed >= self.minimum_state_steps or (not self._available() and desired == self.STATE_STANDBY):
                self.__state = desired
                self.__state_start_time_step = int(self.time_step)
                changed = True

        self.__requested_state = requested
        self.state_history[self.time_step] = self.__state
        self.requested_state_history[self.time_step] = requested
        self.state_changes[self.time_step] = changed
        self.action_applied[self.time_step] = True
        power_kw = self._power_for_state(self.__state)
        energy_kwh = power_kw * float(self.seconds_per_time_step) / 3600.0
        self.set_electricity_consumption(energy_kwh)

        passengers = max(self._value('passengers_expected_15min'), 0.0)
        required = passengers > self.service_threshold_passengers
        met = (not required) or (self.__state >= self.STATE_SLOW and self._available())
        self.service_required[self.time_step] = required
        self.service_met[self.time_step] = met
        self.unserved_passengers[self.time_step] = 0.0 if met else passengers

    def observations(self) -> Mapping[str, float]:
        """Return current aggregate operating and demand observations."""

        passengers = max(self._value('passengers_expected_15min'), 0.0)
        arriving = max(self._value('arriving_trains'), 0.0)
        departing = max(self._value('departing_trains'), 0.0)
        current = min(int(self.time_step), len(self.state_history) - 1)
        return {
            'passengers_from_trains_15min': max(self._value('passengers_from_trains_15min'), 0.0),
            'background_pedestrians_15min': max(self._value('background_pedestrians_15min'), 0.0),
            'passengers_expected_15min': passengers,
            'people_detected': float(self._value('people_detected') >= 0.5),
            # Existing source files carry both arrival and departure flags for a
            # passing train.  Avoid double counting in the control signal.
            'passing_trains': max(arriving, departing),
            'minutes_to_next_train': max(self._value('minutes_to_next_train'), 0.0),
            'available': float(self._available()),
            'state': float(self.state),
            'requested_state': float(self.requested_state),
            'power_kw': self._power_for_state(self.state),
            'service_required': float(self.service_required[current]),
            'service_met': float(self.service_met[current]),
            'unserved_passengers_15min': float(self.unserved_passengers[current]),
        }

    def service_summary(self, end_time_step: int = None) -> Mapping[str, float]:
        """Return cumulative service and energy indicators for reporting."""

        end = self.time_step if end_time_step is None else int(end_time_step)
        end = min(max(end, 0), len(self.state_history) - 1)
        applied = np.asarray(self.action_applied[:end + 1], dtype=bool)
        requested = np.asarray(self.escalator_simulation.passengers_expected_15min[:end + 1], dtype='float64')
        requested = np.clip(requested, 0.0, None) * applied
        unserved = np.asarray(self.unserved_passengers[:end + 1], dtype='float64') * applied
        total_requested = float(np.sum(requested))
        total_unserved = float(np.sum(unserved))
        total_served = max(total_requested - total_unserved, 0.0)
        return {
            'requested_passengers': total_requested,
            'served_passengers': total_served,
            'unserved_passengers': total_unserved,
            'service_level_ratio': 1.0 if total_requested <= 1.0e-9 else total_served / total_requested,
            'state_changes_count': float(np.sum(self.state_changes[:end + 1] * applied)),
            'standby_state_steps': float(np.sum((self.state_history[:end + 1] == self.STATE_STANDBY) * applied)),
            'slow_state_steps': float(np.sum((self.state_history[:end + 1] == self.STATE_SLOW) * applied)),
            'normal_state_steps': float(np.sum((self.state_history[:end + 1] == self.STATE_NORMAL) * applied)),
            'electricity_consumption_kwh': float(np.sum(self.electricity_consumption[:end + 1] * applied)),
        }

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            **super().get_metadata(),
            'name': self.name,
            'standby_power_kw': self.standby_power,
            'slow_power_kw': self.slow_power,
            'normal_power_kw': self.normal_power,
            'minimum_state_steps': self.minimum_state_steps,
            'service_threshold_passengers': self.service_threshold_passengers,
        }


class WashingMachine(ElectricDevice):
    """Represents a smart washing machine controlled via time-varying load profiles (kWh over time) instead of predefined fixed cycles."""

    def __init__(
        self,
        washing_machine_simulation: WashingMachineSimulation = None,
        name: str = None,
        **kwargs
    ):  
        """Initialize the washing machine with optional simulation data and a unique name."""
        self.washing_machine_simulation = washing_machine_simulation
        self.name = name
        self.__initiated = False
        super().__init__(**kwargs)

    @property
    def washing_machine_simulation(self) -> WashingMachineSimulation:
        """Returns the associated washing machine simulation containing time-based load profiles."""
        return self.__washing_machine_simulation

    @washing_machine_simulation.setter
    def washing_machine_simulation(self, washing_machine_simulation: WashingMachineSimulation):
        """Sets the simulation object for this washing machine."""
        self.__washing_machine_simulation = washing_machine_simulation    

    @property
    def name(self) -> str:
        """Returns the unique identifier or name of the washing machine."""
        return self.__name

    @name.setter
    def name(self, name: str):
        """Sets the unique name of the washing machine."""
        self.__name = name        

    @property
    def initiated(self) -> bool:
        """Indicates whether a washing cycle has been initiated in the current time step."""
        return self.__initiated

    @property
    def past_action_values(self) -> np.ndarray:
        """Returns the history of control actions issued to this washing machine."""
        return self.__past_action_values

    def next_time_step(self):
        """Advance the simulation by one time step and update internal state and buffers accordingly."""
        super().next_time_step()

        if self.__past_action_values is None:
            self.__past_action_values = np.zeros(
                self.episode_tracker.episode_time_steps, dtype='float32'
            )
        if self._ElectricDevice__electricity_consumption is None:
            self._ElectricDevice__electricity_consumption = np.zeros(
                self.episode_tracker.episode_time_steps, dtype='float32'
            )

        # Reset cycle initiation if the configured cycle boundaries change between steps
        if self.time_step > 0:
            prev_start = self.washing_machine_simulation.wm_start_time_step[self.time_step - 1]
            curr_start = self.washing_machine_simulation.wm_start_time_step[self.time_step]
            prev_end = self.washing_machine_simulation.wm_end_time_step[self.time_step - 1]
            curr_end = self.washing_machine_simulation.wm_end_time_step[self.time_step]
            if (prev_start != curr_start or prev_end != curr_end) and self.initiated:
                self.__initiated = False

    def start_cycle(self, action_value: float):
        """Trigger a washing cycle if conditions are met and apply the associated load profile to power consumption."""
        self.__past_action_values[self.time_step] = action_value

        start_time_step = self.washing_machine_simulation.wm_start_time_step[self.time_step]
        end__time_step = self.washing_machine_simulation.wm_end_time_step[self.time_step]
        episode_start_time_step = getattr(self.episode_tracker, 'episode_start_time_step', 0)
        if not isinstance(episode_start_time_step, (int, float, np.integer, np.floating)):
            episode_start_time_step = 0
        current_global_time_step = int(episode_start_time_step) + int(self.time_step)

        if not self.initiated and action_value > 0 and start_time_step != -1 and end__time_step != -1 and start_time_step <= current_global_time_step <= end__time_step:
            load_profile = self.washing_machine_simulation.load_profile[self.time_step]
            if len(load_profile) == 0:
                print("No load profile available at this step.")
                return

            self.__initiated = True

            # Apply load profile across future timesteps
            for offset, load in enumerate(load_profile):
                step = self.time_step + offset
                if step < self.episode_tracker.episode_time_steps:
                    self._ElectricDevice__electricity_consumption[step] += float(load)

    def observations(self) -> Mapping[str, float]:
        """Return the current observation dictionary including simulation inputs and machine state."""
        unwanted_keys = []  # Add any keys you want to exclude

        observations = {
            **{
                k.lstrip('_'): v[self.time_step]
                for k, v in vars(self.washing_machine_simulation).items()
                if isinstance(v, np.ndarray) and k.lstrip('_') not in unwanted_keys
            },
            'washing_machine_initiated': float(self.initiated),
            'washing_machine_action': self.past_action_values[self.time_step] if self.past_action_values is not None else 0.0
        }

        return observations    

    def reset(self):
        """Reset the internal state of the washing machine at the beginning of a new episode."""
        super().reset()
        self.__initiated = False
        self.__past_action_values = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32') 
        self._ElectricDevice__electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')

    def __str__(self) -> str:
        """Return a human-readable string representation of the washing machine's current state."""
        return str(self.as_dict())

    def as_dict(self) -> dict:
        """Return the current state of the washing machine as a dictionary."""
        return {
            'name': self.name,
            'initiated': self.initiated,
            **self.observations()
        }

    def render_simulation_end_data(self) -> dict:
        """Generate structured simulation output data for all time steps."""
        num_steps = self.episode_tracker.episode_time_steps
        simulation_attrs = {
            key: value
            for key, value in vars(self.washing_machine_simulation).items()
            if isinstance(value, np.ndarray)
        }

        time_steps = []
        for i in range(num_steps):
            step_data = {
                "time_step": i,
                "simulation": {},
                "status": {
                    "initiated": self.initiated if i == self.time_step else None,
                    "action_value": self.past_action_values[i] if self.past_action_values is not None else None
                }
            }

            for key, array in simulation_attrs.items():
                value = array[i]
                if isinstance(value, np.generic):
                    value = value.item()
                step_data["simulation"][key] = value

            time_steps.append(step_data)

        return {
            "simulation_name": self.name if self.name else "WashingMachineSimulation",
            "data": time_steps
        }
