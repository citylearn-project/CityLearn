import logging
import warnings
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union
from gymnasium import spaces
import numpy as np
import pandas as pd
try:
    import torch
except ImportError:  # pragma: no cover - optional dependency for LSTM dynamics only
    torch = None
from citylearn.base import Environment, EpisodeTracker
from citylearn.data import CarbonIntensity, EnergySimulation, Pricing, TOLERANCE, Weather, ZERO_DIVISION_PLACEHOLDER
from citylearn.dynamics import Dynamics, LSTMDynamics
from citylearn.electric_vehicle_charger import Charger
from citylearn.energy_model import Battery, DeferrableAppliance, ElectricDevice, ElectricHeater, Escalator, HeatPump, PV, StorageDevice, StorageTank, WashingMachine
from citylearn.internal.building_ops import BuildingOpsService
from citylearn.internal.units import (
    normalized_capacity_action_to_energy_kwh,
    normalized_power_action_to_energy_kwh,
    power_kw_to_energy_kwh,
    to_dataset_resolution_energy,
)
from citylearn.occupant import LogisticRegressionOccupant, Occupant
from citylearn.power_outage import PowerOutage
from citylearn.preprocessing import Normalize, PeriodicNormalization
from citylearn.utilities import parse_bool

LOGGER = logging.getLogger()
logging.basicConfig(level=logging.INFO)

class Building(Environment):
    r"""Base class for building.

    Parameters
    ----------
    energy_simulation : EnergySimulation
        Temporal features, cooling, heating, dhw and plug loads, solar generation and indoor environment time series.
    weather : Weather
        Outdoor weather conditions and forecasts time sereis.
    observation_metadata : dict
        Mapping of active and inactive observations.
    action_metadata : dict
        Mapping od active and inactive actions.
    episode_tracker: EpisodeTracker, optional
        :py:class:`citylearn.base.EpisodeTracker` object used to keep track of current episode time steps 
        for reading observations from data files.
    carbon_intensity : CarbonIntensity, optional
        Carbon dioxide emission rate time series.
    pricing : Pricing, optional
        Energy pricing and forecasts time series.
    dhw_storage : StorageTank, optional
        Hot water storage object for domestic hot water.
    cooling_storage : StorageTank, optional
        Cold water storage object for space cooling.
    heating_storage : StorageTank, optional
        Hot water storage object for space heating.
    electrical_storage : Battery, optional
        Electric storage object for meeting electric loads.
    dhw_device : Union[HeatPump, ElectricHeater], optional
        Electric device for meeting hot domestic hot water demand and charging `dhw_storage`.
    cooling_device : HeatPump, optional
        Electric device for meeting space cooling demand and charging `cooling_storage`.
    heating_device : Union[HeatPump, ElectricHeater], optional
        Electric device for meeting space heating demand and charging `heating_storage`.
    pv : PV, optional
        PV object for offsetting electricity demand from grid.
    name : str, optional
        Unique building name.
    observation_space_limit_delta: float, default: 0.0
        +/- buffer for observation space limits after they have been dynamically calculated.
    maximum_temperature_delta: float, default: 20.0
        Expected maximum absolute temperature delta above and below indoor dry-bulb temperature in [C].
    demand_observation_limit_factor: float, default: 1.15
        Multiplier for maximum cooling/heating/dhw demand observations when setting observation limits.
    simulate_power_outage: bool, default: False
        Whether to allow time steps when the grid is unavailable and loads must be met using only the 
        building's downward flexibility resources.
    stochastic_power_outage: bool, default: False
        Whether to use a stochastic function to determine outage time steps otherwise, 
        :py:class:`citylearn.building.Building.energy_simulation.power_outage` time series is used.
    stochastic_power_outage_model: PowerOutage, optional
        Power outage model class used to generate stochastic power outage signals.
    carbon_intensity : CarbonIntensity, optional
        Carbon dioxide emission rate time series.
    electric_vehicle_chargers : Charger, optional
        Electric Vehicle Chargers associated with the building.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize super class.
    """

    def __init__(
        self, energy_simulation: EnergySimulation, weather: Weather, observation_metadata: Mapping[str, bool],
        action_metadata: Mapping[str, bool], episode_tracker: EpisodeTracker,
        carbon_intensity: CarbonIntensity = None,
        pricing: Pricing = None, dhw_storage: StorageTank = None, cooling_storage: StorageTank = None,
        heating_storage: StorageTank = None, electrical_storage: Battery = None,
        dhw_device: Union[HeatPump, ElectricHeater] = None, cooling_device: HeatPump = None,
        heating_device: Union[HeatPump, ElectricHeater] = None, pv: PV = None, name: str = None,
        maximum_temperature_delta: float = None, observation_space_limit_delta: float = None,
        demand_observation_limit_factor: float = None, simulate_power_outage: bool = None,
        stochastic_power_outage: bool = None, stochastic_power_outage_model: PowerOutage = None,
        electric_vehicle_chargers: List[Charger] = None, time_step_ratio: int = None,
        deferrable_appliances: List[DeferrableAppliance] = None, washing_machines: List[WashingMachine] = None,
        escalators: List[Escalator] = None,
        **kwargs: Any
    ):
        charging_constraints = kwargs.pop('charging_constraints', None)
        electrical_service = kwargs.pop('electrical_service', None)
        electrical_storage_phase_connection = kwargs.pop('electrical_storage_phase_connection', None)
        self.equity_group = kwargs.pop('equity_group', None)
        self.name = name
        self.dhw_storage = dhw_storage
        self.cooling_storage = cooling_storage
        self.heating_storage = heating_storage
        self.electrical_storage = electrical_storage
        self.dhw_device = dhw_device
        self.cooling_device = cooling_device
        self.heating_device = heating_device
        self.__non_shiftable_load_device = ElectricDevice(nominal_power=0.0, **kwargs)
        self.pv = pv
        self.time_step_ratio=time_step_ratio
        super().__init__(
            seconds_per_time_step=kwargs.get('seconds_per_time_step'),
            random_seed=kwargs.get('random_seed'),
            episode_tracker=episode_tracker,
            time_step_ratio=self.time_step_ratio,
        )
        self.algorithm_action_based_time_step_hours_ratio = self.seconds_per_time_step / 3600
        self.stochastic_power_outage_model = stochastic_power_outage_model
        self.deferrable_appliances = deferrable_appliances if deferrable_appliances is not None else washing_machines
        self.escalators = escalators
        self.electric_vehicle_chargers = electric_vehicle_chargers
        self.energy_simulation = energy_simulation
        self.weather = weather
        self.carbon_intensity = carbon_intensity
        self.pricing = pricing
        self.observation_metadata = observation_metadata
        self.action_metadata = action_metadata
        self.observation_space_limit_delta = observation_space_limit_delta
        self.maximum_temperature_delta = maximum_temperature_delta
        self.demand_observation_limit_factor = demand_observation_limit_factor
        self.simulate_power_outage = simulate_power_outage
        self.stochastic_power_outage = stochastic_power_outage
        self.non_periodic_normalized_observation_space_limits = None
        self.periodic_normalized_observation_space_limits = None
        self._energy_simulation_observation_sources: List[Tuple[str, np.ndarray]] = []
        self._weather_observation_sources: List[Tuple[str, np.ndarray]] = []
        self._pricing_observation_sources: List[Tuple[str, np.ndarray]] = []
        self._carbon_observation_sources: List[Tuple[str, np.ndarray]] = []
        self._ops_service = BuildingOpsService(self)
        self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)
        self.action_space = self.estimate_action_space()
        self._initialize_charging_constraints(
            charging_constraints,
            electrical_service=electrical_service,
            electrical_storage_phase_connection=electrical_storage_phase_connection,
        )

    @property
    def energy_simulation(self) -> EnergySimulation:
        """Temporal features, cooling, heating, dhw and plug loads, solar generation and indoor environment time series."""

        return self.__energy_simulation

    @property
    def weather(self) -> Weather:
        """Outdoor weather conditions and forecasts time series."""

        return self.__weather

    @property
    def observation_metadata(self) -> Mapping[str, bool]:
        """Mapping of active and inactive observations."""

        return self.__observation_metadata

    @property
    def action_metadata(self) -> Mapping[str, bool]:
        """Mapping od active and inactive actions."""

        return self.__action_metadata

    @property
    def carbon_intensity(self) -> CarbonIntensity:
        """Carbon dioxide emission rate time series."""

        return self.__carbon_intensity

    @property
    def pricing(self) -> Pricing:
        """Energy pricing and forecasts time series."""

        return self.__pricing

    @property
    def dhw_storage(self) -> StorageTank:
        """Hot water storage object for domestic hot water."""

        return self.__dhw_storage

    @property
    def cooling_storage(self) -> StorageTank:
        """Cold water storage object for space cooling."""

        return self.__cooling_storage

    @property
    def heating_storage(self) -> StorageTank:
        """Hot water storage object for space heating."""

        return self.__heating_storage

    @property
    def electrical_storage(self) -> Battery:
        """Electric storage object for meeting electric loads."""

        return self.__electrical_storage

    @property
    def dhw_device(self) -> Union[HeatPump, ElectricHeater]:
        """Electric device for meeting hot domestic hot water demand and charging `dhw_storage`."""

        return self.__dhw_device

    @property
    def cooling_device(self) -> HeatPump:
        """Electric device for meeting space cooling demand and charging `cooling_storage`."""

        return self.__cooling_device

    @property
    def heating_device(self) -> Union[HeatPump, ElectricHeater]:
        """Electric device for meeting space heating demand and charging `heating_storage`."""

        return self.__heating_device

    @property
    def non_shiftable_load_device(self) -> ElectricDevice:
        """Generic electric device for meeting non_shiftable_load."""

        return self.__non_shiftable_load_device

    @property
    def pv(self) -> PV:
        """PV object for offsetting electricity demand from grid."""

        return self.__pv

    @property
    def electric_vehicle_chargers(self) -> List[Charger]:
        """Electric Vehicle Chargers associated with the building for charging connected eletric vehicles."""

        return self.__electric_vehicle_chargers

    @property
    def charger_phase_map(self) -> Mapping[str, str]:
        return getattr(self, '_charger_phase_map', {})

    @property
    def charging_building_limit_kw(self) -> float:
        return getattr(self, '_building_charger_limit_kw', None)

    @property
    def electrical_service_enabled(self) -> bool:
        return bool(getattr(self, '_electrical_service_enabled', False))

    @property
    def electrical_service_mode(self) -> str:
        return getattr(self, '_electrical_service_mode', 'single_phase')

    @property
    def electrical_storage_phase_connection(self) -> str:
        return getattr(self, '_electrical_storage_phase_connection', 'L1')
    
    @property
    def deferrable_appliances(self) -> List[DeferrableAppliance]:
        """Deferrable appliances associated with the building."""

        return self.__deferrable_appliances

    @property
    def washing_machines(self) -> List[DeferrableAppliance]:
        """Backward-compatible alias for deferrable appliances."""

        return self.deferrable_appliances

    @property
    def escalators(self) -> List[Escalator]:
        """Aggregate escalators associated with the building."""

        return self.__escalators

    @property
    def name(self) -> str:
        """Unique building name."""

        return self.__name

    @property
    def observation_space_limit_delta(self) -> float:
        """+/- buffer for observation space limits after they have been dynamically calculated."""

        return self.__observation_space_limit_delta

    @property
    def maximum_temperature_delta(self) -> float:
        """Expected maximum absolute temperature delta above and below indoor dry-bulb temperature in [C]."""

        return self.__maximum_temperature_delta

    @property
    def demand_observation_limit_factor(self) -> float:
        """Multiplier for maximum cooling/heating/dhw demand observations when setting observation limits."""

        return self.__demand_observation_limit_factor

    @property
    def simulate_power_outage(self) -> bool:
        """Whether to allow time steps when the grid is unavailable and loads must be met using only the 
        building's downward flexibility resources."""

        return self.__simulate_power_outage

    @property
    def stochastic_power_outage(self) -> bool:
        """Whether to use a stochastic function to determine outage time steps otherwise, 
        :py:class:`citylearn.building.Building.energy_simulation.power_outage` time series is used."""

        return self.__stochastic_power_outage

    @property
    def observation_space(self) -> spaces.Box:
        """Agent observation space."""

        return self.__observation_space

    @property
    def action_space(self) -> spaces.Box:
        """Agent action spaces."""

        return self.__action_space

    @property
    def active_observations(self) -> List[str]:
        """Observations in `observation_metadata` with True value i.e. obeservable."""

        return [k for k, v in self.observation_metadata.items() if v]

    @property
    def active_actions(self) -> List[str]:
        """Actions in `action_metadata` with True value i.e. 
        indicates which storage systems are to be controlled during simulation."""

        return [k for k, v in self.action_metadata.items() if v]

    @property
    def net_electricity_consumption_emission_without_storage_and_pv(self) -> np.ndarray:
        """Carbon dioxide emmission from `net_electricity_consumption_without_storage_pv` time series, in [kg_co2]."""

        return (self.carbon_intensity.carbon_intensity[0:self.time_step + 1] * self.net_electricity_consumption_without_storage_and_pv).clip(min=0)

    @property
    def net_electricity_consumption_cost_without_storage_and_pv(self) -> np.ndarray:
        """net_electricity_consumption_without_storage_and_pv` cost time series, in [$]."""

        return (
            self.pricing.electricity_pricing[0:self.time_step + 1]
            * np.clip(self.net_electricity_consumption_without_storage_and_pv, 0.0, None)
        )

    @property
    def net_electricity_consumption_without_storage_and_pv(self) -> np.ndarray:
        """Net electricity consumption in the absence of flexibility provided by storage devices, 
        and self generation time series, in [kWh]. 
        
        Notes
        -----
        net_electricity_consumption_without_storage_and_pv = 
        `net_electricity_consumption_without_storage` - `solar_generation`
        """

        return self.net_electricity_consumption_without_storage - self.solar_generation

    @property
    def net_electricity_consumption_emission_without_storage(self) -> np.ndarray:
        """Carbon dioxide emmission from `net_electricity_consumption_without_storage` time series, in [kg_co2]."""

        return (self.carbon_intensity.carbon_intensity[0:self.time_step + 1] * self.net_electricity_consumption_without_storage).clip(min=0)

    @property
    def net_electricity_consumption_cost_without_storage(self) -> np.ndarray:
        """`net_electricity_consumption_without_storage` cost time series, in [$]."""

        return (
            self.pricing.electricity_pricing[0:self.time_step + 1]
            * np.clip(self.net_electricity_consumption_without_storage, 0.0, None)
        )

    @property
    def net_electricity_consumption_without_storage(self) -> np.ndarray:
        """net electricity consumption in the absence of flexibility provided by storage devices time series, in [kWh]. 
        
        Notes
        -----
        net_electricity_consumption_without_storage = `net_electricity_consumption` - (`cooling_storage_electricity_consumption`
        + `heating_storage_electricity_consumption` + `dhw_storage_electricity_consumption` + `electrical_storage_electricity_consumption` + `charger_electricity_consumption`)

        Regarding electric vehicles there is:
        chargers_electricity_consumption -> Sum of the electricity consumption of all electric_vehicle_chargers in the building

        So, the first one is subtracted from the net_electricity_consumption, obtaining the energy consumption as if the cars were not used at all.
        However, if there are chargers and EVs, they need to charge per usual, so that consumption is added
        This is what allows to check if the control mechanism affects the grid balancing scheme for EVs for example.
        """
        return self.net_electricity_consumption - np.sum([
            self.cooling_storage_electricity_consumption,
            self.heating_storage_electricity_consumption,
            self.dhw_storage_electricity_consumption,
            self.electrical_storage_electricity_consumption,
            self.chargers_electricity_consumption,
        ], axis=0)

    @property
    def net_electricity_consumption_emission(self) -> np.ndarray:
        """Carbon dioxide emmission from `net_electricity_consumption` time series, in [kg_co2]."""

        return self.__net_electricity_consumption_emission[:self.time_step + 1]

    @property
    def net_electricity_consumption_cost(self) -> np.ndarray:
        """`net_electricity_consumption` cost time series, in [$]."""

        return self.__net_electricity_consumption_cost[:self.time_step + 1]

    @property
    def net_electricity_consumption(self) -> np.ndarray:
        """Net electricity consumption time series, in [kWh]."""

        return self.__net_electricity_consumption[:self.time_step + 1]

    @property
    def cooling_electricity_consumption(self) -> np.ndarray:
        """`cooling_device` net electricity consumption in meeting cooling demand and `cooling_storage` energy demand time series, in [kWh]. 
        """

        return self.cooling_device.electricity_consumption[:self.time_step + 1]

    @property
    def heating_electricity_consumption(self) -> np.ndarray:
        """`heating_device` net electricity consumption in meeting heating demand and `heating_storage` energy demand time series, in [kWh]. 
        """

        return self.heating_device.electricity_consumption[:self.time_step + 1]

    @property
    def dhw_electricity_consumption(self) -> np.ndarray:
        """`dhw_device` net electricity consumption in meeting domestic hot water and `dhw_storage` energy demand time series, in [kWh]. 
        """

        return self.dhw_device.electricity_consumption[:self.time_step + 1]

    @property
    def non_shiftable_load_electricity_consumption(self) -> np.ndarray:
        """`non_shiftable_load_device` net electricity consumption in meeting `non_shiftable_load` energy demand time series, in [kWh]. 
        """

        return self.non_shiftable_load_device.electricity_consumption[:self.time_step + 1]

    @property
    def cooling_storage_electricity_consumption(self) -> np.ndarray:
        """`cooling_storage` net electricity consumption time series, in [kWh]. 
        
        Positive values indicate `cooling_device` electricity consumption to charge `cooling_storage` while negative values indicate avoided `cooling_device` 
        electricity consumption by discharging `cooling_storage` to meet `cooling_demand`.
        """

        return self.cooling_device.get_input_power(self.cooling_storage.energy_balance[:self.time_step + 1],
            self.weather.outdoor_dry_bulb_temperature[:self.time_step + 1], False)

    @property
    def heating_storage_electricity_consumption(self) -> np.ndarray:
        """`heating_storage` net electricity consumption time series, in [kWh]. 
        
        Positive values indicate `heating_device` electricity consumption to charge `heating_storage` while negative values indicate avoided `heating_device` 
        electricity consumption by discharging `heating_storage` to meet `heating_demand`.
        """

        if isinstance(self.heating_device, HeatPump):
            consumption = self.heating_device.get_input_power(
                self.heating_storage.energy_balance[:self.time_step + 1],
                self.weather.outdoor_dry_bulb_temperature[:self.time_step + 1], True)
        else:
            consumption = self.heating_device.get_input_power(self.heating_storage.energy_balance[:self.time_step + 1])

        return consumption

    @property
    def dhw_storage_electricity_consumption(self) -> np.ndarray:
        """`dhw_storage` net electricity consumption time series, in [kWh]. 
        
        Positive values indicate `dhw_device` electricity consumption to charge `dhw_storage` while negative values indicate avoided `dhw_device` 
        electricity consumption by discharging `dhw_storage` to meet `dhw_demand`.
        """

        if isinstance(self.dhw_device, HeatPump):
            consumption = self.dhw_device.get_input_power(
                self.dhw_storage.energy_balance[:self.time_step + 1],
                self.weather.outdoor_dry_bulb_temperature[
                :self.time_step + 1], True)
        else:
            consumption = self.dhw_device.get_input_power(self.dhw_storage.energy_balance[:self.time_step + 1])

        return consumption

    @property
    def electrical_storage_electricity_consumption(self) -> np.ndarray:
        """Energy supply from grid and/or `PV` to `electrical_storage` time series, in [kWh]."""

        values = self.electrical_storage.electricity_consumption[:self.time_step + 1]
        prefix = getattr(self, '_archived_storage_electricity', None)
        if prefix is not None:
            values = values.copy()
            size = min(len(prefix), len(values))
            values[:size] = prefix[:size]
        return values
    
    @property
    def pv_curtailment(self) -> np.ndarray:
        """Available PV not admitted to the islanded AC bus, in kWh/interval."""
        return self.__pv_curtailment[:self.time_step + 1]

    @property
    def chargers_electricity_consumption(self) -> np.ndarray:
        """Electricity consumption of chargers time series, in [kWh]."""

        return self.__chargers_electricity_consumption[:self.time_step + 1]
    
    @property
    def deferrable_appliances_electricity_consumption(self) -> np.ndarray:
        """Electricity consumption of deferrable appliances time series, in [kWh]."""

        return self.__deferrable_appliances_electricity_consumption[:self.time_step + 1]

    @property
    def washing_machines_electricity_consumption(self) -> np.ndarray:
        """Backward-compatible alias for deferrable appliance electricity consumption."""

        return self.deferrable_appliances_electricity_consumption

    @property
    def escalators_electricity_consumption(self) -> np.ndarray:
        """Electricity consumption of escalators in [kWh]."""

        return self.__escalators_electricity_consumption[:self.time_step + 1]

    @property
    def energy_from_cooling_device_to_cooling_storage(self) -> np.ndarray:
        """Energy supply from `cooling_device` to `cooling_storage` time series, in [kWh]."""

        return self.cooling_storage.energy_balance[:self.time_step + 1].clip(min=0)

    @property
    def energy_from_heating_device_to_heating_storage(self) -> np.ndarray:
        """Energy supply from `heating_device` to `heating_storage` time series, in [kWh]."""

        return self.heating_storage.energy_balance[:self.time_step + 1].clip(min=0)

    @property
    def energy_from_dhw_device_to_dhw_storage(self) -> np.ndarray:
        """Energy supply from `dhw_device` to `dhw_storage` time series, in [kWh]."""

        return self.dhw_storage.energy_balance[:self.time_step + 1].clip(min=0)

    @property
    def energy_to_electrical_storage(self) -> np.ndarray:
        """Energy supply from `electrical_device` to building time series, in [kWh]."""

        return self.electrical_storage.energy_balance[:self.time_step + 1].clip(min=0)

    @property
    def energy_from_cooling_device(self) -> np.ndarray:
        """Energy supply from `cooling_device` to building time series, in [kWh]."""

        return self.__energy_from_cooling_device[:self.time_step + 1]

    @property
    def energy_from_heating_device(self) -> np.ndarray:
        """Energy supply from `heating_device` to building time series, in [kWh]."""

        return self.__energy_from_heating_device[:self.time_step + 1]

    @property
    def energy_from_dhw_device(self) -> np.ndarray:
        """Energy supply from `dhw_device` to building time series, in [kWh]."""

        return self.__energy_from_dhw_device[:self.time_step + 1]

    @property
    def energy_to_non_shiftable_load(self) -> np.ndarray:
        """Energy supply from grid, PV and battery to non shiftable loads, in [kWh]."""

        return self.__energy_to_non_shiftable_load[:self.time_step + 1]

    @property
    def energy_from_cooling_storage(self) -> np.ndarray:
        """Energy supply from `cooling_storage` to building time series, in [kWh]."""

        return self.cooling_storage.energy_balance[:self.time_step + 1].clip(max=0) * -1

    @property
    def energy_from_heating_storage(self) -> np.ndarray:
        """Energy supply from `heating_storage` to building time series, in [kWh]."""

        return self.heating_storage.energy_balance[:self.time_step + 1].clip(max=0) * -1

    @property
    def energy_from_dhw_storage(self) -> np.ndarray:
        """Energy supply from `dhw_storage` to building time series, in [kWh]."""

        return self.dhw_storage.energy_balance[:self.time_step + 1].clip(max=0) * -1

    @property
    def energy_from_electrical_storage(self) -> np.ndarray:
        """Energy supply from `electrical_storage` to building time series, in [kWh]."""

        return self.electrical_storage.energy_balance[:self.time_step + 1].clip(max=0) * -1

    @property
    def indoor_dry_bulb_temperature(self) -> np.ndarray:
        """dry bulb temperature time series, in [C].
        
        This is the temperature when cooling_device and heating_device are controlled.
        """

        return self.energy_simulation.indoor_dry_bulb_temperature[0:self.time_step + 1]

    @property
    def indoor_dry_bulb_temperature_cooling_set_point(self) -> np.ndarray:
        """Dry bulb temperature cooling set point time series, in [C]."""

        return self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[0:self.time_step + 1]

    @property
    def indoor_dry_bulb_temperature_heating_set_point(self) -> np.ndarray:
        """Dry bulb temperature heating set point time series, in [C]."""

        return self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[0:self.time_step + 1]

    @property
    def comfort_band(self) -> np.ndarray:
        """Occupant comfort band above the `indoor_dry_bulb_temperature_cooling_set_point` and below the `indoor_dry_bulb_temperature_heating_set_point`, in [C]."""

        return self.energy_simulation.comfort_band[0:self.time_step + 1]

    @property
    def occupant_count(self) -> np.ndarray:
        """Building occupant count time series, in [people]."""

        return self.energy_simulation.occupant_count[0:self.time_step + 1]

    @property
    def cooling_demand(self) -> np.ndarray:
        """Space cooling demand to be met by `cooling_device` and/or `cooling_storage` time series, in [kWh]."""

        return self.energy_simulation.cooling_demand[0:self.time_step + 1]

    @property
    def heating_demand(self) -> np.ndarray:
        """Space heating demand to be met by `heating_device` and/or `heating_storage` time series, in [kWh]."""

        return self.energy_simulation.heating_demand[0:self.time_step + 1]

    @property
    def dhw_demand(self) -> np.ndarray:
        """Domestic hot water demand to be met by `dhw_device` and/or `dhw_storage` time series, in [kWh]."""

        return self.energy_simulation.dhw_demand[0:self.time_step + 1]

    @property
    def non_shiftable_load(self) -> np.ndarray:
        """Electricity load that must be met by the grid, or `PV` and/or `electrical_storage` if available time series, in [kWh]."""

        return self.energy_simulation.non_shiftable_load[0:self.time_step + 1]

    @property
    def cooling_device_cop(self) -> np.ndarray:
        """Heat pump `cooling_device` coefficient of performance time series."""

        return self.cooling_device.get_cop(self.weather.outdoor_dry_bulb_temperature, heating=False)[0:self.time_step + 1]

    @property
    def heating_device_cop(self) -> np.ndarray:
        """Heat pump `heating_device` coefficient of performance or electric heater `heating_device` static technical efficiency time series."""

        return self.heating_device.get_cop(self.weather.outdoor_dry_bulb_temperature, heating=True)[0:self.time_step + 1] \
            if isinstance(self.heating_device, HeatPump) else np.zeros(self.time_step + 1, dtype='float32')

    @property
    def dhw_device_cop(self) -> np.ndarray:
        """Heat pump `dhw_device` coefficient of performance or electric heater `dhw_device` static technical efficiency time series."""

        return self.dhw_device.get_cop(self.weather.outdoor_dry_bulb_temperature, heating=True)[0:self.time_step + 1] \
            if isinstance(self.dhw_device, HeatPump) else np.zeros(self.time_step + 1, dtype='float32')

    @property
    def solar_generation(self) -> np.ndarray:
        """`PV` solar generation (negative value) time series, in [kWh]."""

        return self.__solar_generation[:self.time_step + 1]

    @property
    def power_outage_signal(self) -> np.ndarray:
        """Power outage signal time series, in [Yes/No]."""

        return self.__power_outage_signal[:self.time_step + 1]

    @property
    def downward_electrical_flexibility(self) -> float:
        """Available distributed energy resource capacity to satisfy electric loads while considering power outage at current time step.
        
        It is the sum of solar generation and any discharge from electrical storage, less electricity consumption by cooling, heating, 
        dhw and non-shiftable load devices, electrical storage and already served
        controllable devices. When there is no power outage, the returned value
        is `np.inf`.
        """

        if not self.power_outage:
            return np.inf

        capacity = abs(self.solar_generation[self.time_step]) - (
            self.cooling_device.electricity_consumption[self.time_step]
            + self.heating_device.electricity_consumption[self.time_step]
            + self.dhw_device.electricity_consumption[self.time_step]
            + self.non_shiftable_load_device.electricity_consumption[self.time_step]
            + self.electrical_storage.electricity_consumption[self.time_step]
        )

        # Read live device values: building-level aggregates are only refreshed
        # after all actions. Each subsequent load must see the remaining supply.
        for devices in (
            self.electric_vehicle_chargers,
            self.deferrable_appliances,
            self.escalators,
        ):
            capacity -= sum(device.electricity_consumption[self.time_step] for device in devices or [])

        return max(0.0, capacity)

    @property
    def power_outage(self) -> bool:
        """Whether there is power outage at current time step."""

        return self.simulate_power_outage and bool(self.__power_outage_signal[self.time_step])

    @property
    def stochastic_power_outage_model(self) -> PowerOutage:
        """Power outage model class used to generate stochastic power outage signals."""

        return self.__stochastic_power_outage_model

    @energy_simulation.setter
    def energy_simulation(self, energy_simulation: EnergySimulation):
        self.__energy_simulation = energy_simulation

    @weather.setter
    def weather(self, weather: Weather):
        self.__weather = weather

    @observation_metadata.setter
    def observation_metadata(self, observation_metadata: Mapping[str, bool]):
        self.__observation_metadata = dict(observation_metadata)

    @action_metadata.setter
    def action_metadata(self, action_metadata: Mapping[str, bool]):
        self.__action_metadata = dict(action_metadata)

    @carbon_intensity.setter
    def carbon_intensity(self, carbon_intensity: CarbonIntensity):
        if carbon_intensity is None:
            self.__carbon_intensity = CarbonIntensity(np.zeros(self.episode_tracker.simulation_time_steps, dtype='float32'))
        else:
            self.__carbon_intensity = carbon_intensity

    @pricing.setter
    def pricing(self, pricing: Pricing):
        if pricing is None:
            self.__pricing = Pricing(
                np.zeros(self.episode_tracker.simulation_time_steps, dtype='float32'),
                np.zeros(self.episode_tracker.simulation_time_steps, dtype='float32'),
                np.zeros(self.episode_tracker.simulation_time_steps, dtype='float32'),
                np.zeros(self.episode_tracker.simulation_time_steps, dtype='float32'),
            )
        else:
            self.__pricing = pricing

    @dhw_storage.setter
    def dhw_storage(self, dhw_storage: StorageTank):
        self.__dhw_storage = StorageTank(0.0) if dhw_storage is None else dhw_storage

    @cooling_storage.setter
    def cooling_storage(self, cooling_storage: StorageTank):
        self.__cooling_storage = StorageTank(0.0) if cooling_storage is None else cooling_storage

    @heating_storage.setter
    def heating_storage(self, heating_storage: StorageTank):
        self.__heating_storage = StorageTank(0.0) if heating_storage is None else heating_storage

    @electrical_storage.setter
    def electrical_storage(self, electrical_storage: Battery):
        self.__electrical_storage = Battery(0.0, 0.0) if electrical_storage is None else electrical_storage

    @dhw_device.setter
    def dhw_device(self, dhw_device: Union[HeatPump, ElectricHeater]):
        self.__dhw_device = ElectricHeater(0.0) if dhw_device is None else dhw_device

    @cooling_device.setter
    def cooling_device(self, cooling_device: HeatPump):
        self.__cooling_device = HeatPump(0.0) if cooling_device is None else cooling_device

    @heating_device.setter
    def heating_device(self, heating_device: Union[HeatPump, ElectricHeater]):
        self.__heating_device = HeatPump(0.0) if heating_device is None else heating_device

    @pv.setter
    def pv(self, pv: PV):
        self.__pv = PV(0.0) if pv is None else pv

    @electric_vehicle_chargers.setter
    def electric_vehicle_chargers(self, electric_vehicle_chargers: List[Charger]):
        self.__electric_vehicle_chargers = electric_vehicle_chargers if electric_vehicle_chargers is not None else []
        self._update_charger_lookup()

    @deferrable_appliances.setter
    def deferrable_appliances(self, deferrable_appliances: List[DeferrableAppliance]):
        self.__deferrable_appliances = deferrable_appliances if deferrable_appliances is not None else []

    @escalators.setter
    def escalators(self, escalators: List[Escalator]):
        self.__escalators = escalators if escalators is not None else []

    @washing_machines.setter
    def washing_machines(self, washing_machines: List[WashingMachine]):
        self.deferrable_appliances = washing_machines

    def _update_charger_lookup(self):
        chargers = self.__electric_vehicle_chargers if hasattr(self, '_Building__electric_vehicle_chargers') else []
        self._charger_lookup = {charger.charger_id: charger for charger in chargers} if chargers else {}
        if hasattr(self, '_include_phase_encoding'):
            self._update_phase_encoding_observations()

    @staticmethod
    def _parse_non_negative_limit(value: Any, path: str) -> Optional[float]:
        if value is None:
            return None

        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{path} must be a finite non-negative number or null.') from exc

        if np.isnan(parsed):
            raise ValueError(f'{path} cannot be NaN.')

        if np.isposinf(parsed):
            return None

        if np.isneginf(parsed) or parsed < 0.0:
            raise ValueError(f'{path} must be >= 0.0 when provided.')

        return parsed

    @staticmethod
    def _normalize_phase_label(value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        if text == '':
            return None

        lowered = text.lower()
        mapping = {
            'l1': 'L1',
            'l2': 'L2',
            'l3': 'L3',
            'phase_1': 'L1',
            'phase_2': 'L2',
            'phase_3': 'L3',
            'all_phases': 'all_phases',
            'all-phases': 'all_phases',
            'three_phase': 'all_phases',
            'three-phase': 'all_phases',
        }

        return mapping.get(lowered, text)

    def _resolve_phase_connection(self, phase_connection: Any, owner: str) -> str:
        mode = getattr(self, '_electrical_service_mode', 'single_phase')
        normalized = self._normalize_phase_label(phase_connection)

        if normalized is None:
            return 'L1' if mode == 'single_phase' else 'all_phases'

        if mode == 'single_phase':
            if normalized != 'L1':
                raise ValueError(f'{owner} phase_connection={normalized} is invalid for single_phase service. Use L1.')
            return normalized

        if normalized not in {'L1', 'L2', 'L3', 'all_phases'}:
            raise ValueError(f'{owner} phase_connection={normalized} is invalid. Use one of L1/L2/L3/all_phases.')

        return normalized

    def _initialize_charging_constraints(
        self,
        config: Mapping[str, Any],
        electrical_service: Mapping[str, Any] = None,
        electrical_storage_phase_connection: str = None,
    ):
        self._charging_constraints_config = config or {}
        self._electrical_service_config = electrical_service or {}
        self._electrical_service_enabled = bool(self._electrical_service_config)
        self._electrical_service_mode = 'single_phase'
        self._electrical_service_default_split = 'balanced'
        self._electrical_service_limits = {
            'total': {'import_kw': None, 'export_kw': None},
            'per_phase': {},
        }
        self._electrical_storage_phase_connection = 'L1'

        observations_config = {}
        expose_flag = None

        if self._electrical_service_enabled:
            observations_config = self._electrical_service_config.get('observations', {}) or {}
            expose_flag = self._electrical_service_config.get('expose_observations')
        else:
            observations_config = self._charging_constraints_config.get('observations', {}) or {}
            expose_flag = self._charging_constraints_config.get('expose_observations')

        self._charging_constraints_enabled = bool(self._charging_constraints_config) or self._electrical_service_enabled

        if 'headroom' in observations_config:
            self._expose_charging_constraints = parse_bool(
                observations_config.get('headroom', False),
                default=False,
                path='charging_constraints.observations.headroom',
            )
        elif expose_flag is not None:
            self._expose_charging_constraints = parse_bool(
                expose_flag,
                default=False,
                path='charging_constraints.expose_observations',
            )
        else:
            self._expose_charging_constraints = True

        self._expose_charging_export_headroom = parse_bool(
            observations_config.get('headroom_export', self._electrical_service_enabled),
            default=self._electrical_service_enabled,
            path='charging_constraints.observations.headroom_export',
        )
        self._expose_charging_violation = parse_bool(
            observations_config.get('violation', True),
            default=True,
            path='charging_constraints.observations.violation',
        )
        self._include_phase_encoding = parse_bool(
            observations_config.get('phase_encoding', False),
            default=False,
            path='charging_constraints.observations.phase_encoding',
        )
        self._building_charger_limit_kw = None
        self._phase_limits = []
        self._charger_phase_map: Mapping[str, str] = {}
        self._charging_constraints_state = None
        self._charging_constraint_penalty_kwh = 0.0
        self._charging_constraint_last_penalty_kwh = 0.0
        self._charging_constraint_violation_history = np.zeros(1, dtype='float32')
        self._charging_total_power_history_kw = np.zeros(1, dtype='float32')
        self._charging_phase_power_history_kw: Mapping[str, np.ndarray] = {}
        self._phase_encoding_observations: Mapping[str, float] = {}
        self._phase_encoding_phase_names: List[str] = []

        if not self._charging_constraints_enabled:
            self._charging_constraints_state = None
            return

        if self._electrical_service_enabled:
            mode = str(self._electrical_service_config.get('mode', 'single_phase')).strip().lower()
            if mode not in {'single_phase', 'three_phase'}:
                raise ValueError("electrical_service.mode must be one of {'single_phase', 'three_phase'}.")
            self._electrical_service_mode = mode

            split = str(self._electrical_service_config.get('default_split', 'balanced')).strip().lower()
            if split not in {'balanced', 'l1', 'l2', 'l3'}:
                raise ValueError("electrical_service.default_split must be one of {'balanced', 'L1', 'L2', 'L3'}.")
            if mode == 'single_phase' and split not in {'balanced', 'l1'}:
                raise ValueError("single_phase electrical service only accepts default_split as 'balanced' or 'L1'.")
            self._electrical_service_default_split = split

            limits = self._electrical_service_config.get('limits', {}) or {}
            total_limits = limits.get('total', {}) or {}
            self._electrical_service_limits['total']['import_kw'] = self._parse_non_negative_limit(
                total_limits.get('import_kw'), 'electrical_service.limits.total.import_kw'
            )
            self._electrical_service_limits['total']['export_kw'] = self._parse_non_negative_limit(
                total_limits.get('export_kw'), 'electrical_service.limits.total.export_kw'
            )

            per_phase_limits = limits.get('per_phase', {}) or {}
            phase_names = ['L1'] if mode == 'single_phase' else ['L1', 'L2', 'L3']

            normalized_phase_limits: Dict[str, Mapping[str, Any]] = {}
            for phase_name, values in per_phase_limits.items():
                normalized_name = self._normalize_phase_label(phase_name)
                normalized_phase_limits[normalized_name] = values

            if mode == 'single_phase':
                invalid = [name for name in normalized_phase_limits if name not in {None, 'L1'}]
                if invalid:
                    raise ValueError(f'single_phase electrical service cannot define per_phase limits for: {invalid}.')
            else:
                invalid = [name for name in normalized_phase_limits if name not in {'L1', 'L2', 'L3'}]
                if invalid:
                    raise ValueError(f'three_phase electrical service only accepts per_phase keys L1/L2/L3. Invalid keys: {invalid}.')

            for phase_name in phase_names:
                phase_limit_config = normalized_phase_limits.get(phase_name, {}) or {}
                import_limit = self._parse_non_negative_limit(
                    phase_limit_config.get('import_kw'),
                    f'electrical_service.limits.per_phase.{phase_name}.import_kw',
                )
                export_limit = self._parse_non_negative_limit(
                    phase_limit_config.get('export_kw'),
                    f'electrical_service.limits.per_phase.{phase_name}.export_kw',
                )
                self._electrical_service_limits['per_phase'][phase_name] = {
                    'import_kw': import_limit,
                    'export_kw': export_limit,
                }
                self._phase_limits.append(
                    {
                        'name': phase_name,
                        'limit_kw': import_limit,
                        'import_kw': import_limit,
                        'export_kw': export_limit,
                        'chargers': [],
                    }
                )

            self._building_charger_limit_kw = self._electrical_service_limits['total']['import_kw']

            for charger in self.electric_vehicle_chargers or []:
                charger_connection = self._resolve_phase_connection(
                    getattr(charger, 'phase_connection', None),
                    f'charger:{charger.charger_id}',
                )
                self._charger_phase_map[charger.charger_id] = charger_connection
                if charger_connection in {'L1', 'L2', 'L3'}:
                    for phase in self._phase_limits:
                        if phase['name'] == charger_connection:
                            phase['chargers'].append(charger.charger_id)
                            break

            self._electrical_storage_phase_connection = self._resolve_phase_connection(
                electrical_storage_phase_connection,
                'electrical_storage',
            )

        else:
            self._building_charger_limit_kw = self._parse_non_negative_limit(
                self._charging_constraints_config.get('building_limit_kw'),
                'charging_constraints.building_limit_kw',
            )
            phases = self._charging_constraints_config.get('phases', []) or []

            for idx, phase in enumerate(phases):
                name = phase.get('name')
                if not name:
                    name = f"phase_{len(self._phase_limits) + 1}"
                limit = self._parse_non_negative_limit(
                    phase.get('limit_kw'),
                    f'charging_constraints.phases[{idx}].limit_kw',
                )
                chargers = phase.get('chargers', []) or []
                self._phase_limits.append({'name': name, 'limit_kw': limit, 'import_kw': limit, 'export_kw': None, 'chargers': chargers})
                for charger_id in chargers:
                    self._charger_phase_map[charger_id] = name

        if self._include_phase_encoding and not self._phase_limits:
            self._include_phase_encoding = False

        self._update_phase_encoding_observations()

        if self._expose_charging_constraints:
            observation_keys = []
            if self._building_charger_limit_kw is not None:
                observation_keys.append('charging_building_headroom_kw')
            for phase in self._phase_limits:
                if phase.get('import_kw') is not None:
                    observation_keys.append(f"charging_phase_{phase['name']}_headroom_kw")

            if self._electrical_service_enabled and self._expose_charging_export_headroom:
                if self._electrical_service_limits['total'].get('export_kw') is not None:
                    observation_keys.append('charging_building_export_headroom_kw')
                for phase in self._phase_limits:
                    if phase.get('export_kw') is not None:
                        observation_keys.append(f"charging_phase_{phase['name']}_export_headroom_kw")

            for key in observation_keys:
                if key not in self.observation_metadata:
                    self.observation_metadata[key] = True

            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

        violation_key = 'charging_constraint_violation_kwh'
        if hasattr(self, 'observation_metadata'):
            self.observation_metadata[violation_key] = self._expose_charging_violation

        if self._include_phase_encoding:
            for key in self._phase_encoding_observations.keys():
                if key not in self.observation_metadata:
                    self.observation_metadata[key] = True

        self._set_default_charging_headroom()
        self._reset_charging_constraint_histories()

        if hasattr(self, 'observation_metadata'):
            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

    def _reset_charging_constraint_histories(self):
        steps = 1

        if getattr(self, 'episode_tracker', None) is not None:
            try:
                steps = int(self.episode_tracker.episode_time_steps)
            except Exception:
                steps = 1

        if steps <= 0:
            try:
                steps = int(len(self.energy_simulation.month))
            except Exception:
                steps = 1

        self._charging_constraint_violation_history = np.zeros(steps, dtype='float32')
        self._charging_total_power_history_kw = np.zeros(steps, dtype='float32')
        self._charging_phase_power_history_kw = {
            phase.get('name'): np.zeros(steps, dtype='float32')
            for phase in self._phase_limits
            if phase.get('name') is not None
        }

    def _record_charging_constraint_state(
        self,
        violation_kwh: float,
        total_power_kw: float,
        phase_power_kw: Optional[Mapping[str, float]] = None,
    ):
        t = int(self.time_step)
        if t < 0:
            return

        if t >= len(self._charging_constraint_violation_history):
            return

        self._charging_constraint_violation_history[t] = float(violation_kwh)
        self._charging_total_power_history_kw[t] = float(total_power_kw)
        phase_power_kw = phase_power_kw or {}

        for phase_name, history in self._charging_phase_power_history_kw.items():
            history[t] = float(phase_power_kw.get(phase_name, 0.0))

    def _update_phase_encoding_observations(self):
        previous_keys = list(getattr(self, '_phase_encoding_observation_keys', []))
        self._phase_encoding_observation_keys = []

        if not getattr(self, '_include_phase_encoding', False):
            self._phase_encoding_observations = {}
            self._phase_encoding_phase_names = []
            self._phase_encoding_observation_keys = previous_keys
            if hasattr(self, 'observation_metadata'):
                for key in previous_keys:
                    if key in self.observation_metadata:
                        self.observation_metadata[key] = False
            if hasattr(self, 'observation_metadata'):
                self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)
            return

        if not getattr(self, '_charger_lookup', None):
            self._phase_encoding_observations = {}
            return

        chargers = list(self._charger_lookup.keys())
        if not chargers:
            self._phase_encoding_observations = {}
            return

        phase_names = sorted(
            {
                phase.get('name')
                for phase in self._phase_limits
                if phase.get('name')
            }
            | {
                value
                for value in self._charger_phase_map.values()
                if value is not None
            }
        )
        has_unassigned = any(charger_id not in self._charger_phase_map for charger_id in chargers)
        if has_unassigned:
            phase_names = phase_names + ['unassigned']

        observations = {}
        for charger_id in chargers:
            assigned_phase = self._charger_phase_map.get(charger_id, 'unassigned' if has_unassigned else None)
            for phase_name in phase_names:
                key = f'charging_phase_one_hot_{charger_id}_{phase_name}'
                observations[key] = 1.0 if assigned_phase == phase_name else 0.0

        self._phase_encoding_observations = observations
        self._phase_encoding_phase_names = phase_names
        self._phase_encoding_observation_keys = list(observations.keys())

        if hasattr(self, 'observation_metadata'):
            for key in observations:
                self.observation_metadata[key] = True

        if hasattr(self, 'observation_metadata'):
            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

    def _set_default_charging_headroom(self):
        if not self._charging_constraints_enabled or not getattr(self, '_expose_charging_constraints', False):
            self._charging_constraints_state = None
            return

        base_total_kw = 0.0
        base_phase_kw = {phase['name']: 0.0 for phase in self._phase_limits}
        if getattr(self, '_electrical_service_enabled', False):
            try:
                base_total_kw, base_phase_kw = self._ops_service._estimate_base_power_at_step(self.time_step)
            except Exception:
                base_total_kw = 0.0
                base_phase_kw = {phase['name']: 0.0 for phase in self._phase_limits}

        building_headroom = None if self._building_charger_limit_kw is None else float(self._building_charger_limit_kw) - base_total_kw
        building_export_headroom = None
        if getattr(self, '_electrical_service_enabled', False):
            export_limit = self._electrical_service_limits.get('total', {}).get('export_kw')
            building_export_headroom = None if export_limit is None else float(export_limit) + base_total_kw

        phase_headroom = {
            phase['name']: None if phase.get('import_kw') is None else float(phase.get('import_kw')) - float(base_phase_kw.get(phase['name'], 0.0))
            for phase in self._phase_limits
        }
        phase_export_headroom = {
            phase['name']: None if phase.get('export_kw') is None else float(phase.get('export_kw')) + float(base_phase_kw.get(phase['name'], 0.0))
            for phase in self._phase_limits
        }
        self._charging_constraints_state = {
            'building_headroom_kw': building_headroom,
            'building_export_headroom_kw': building_export_headroom,
            'phase_headroom_kw': phase_headroom,
            'phase_export_headroom_kw': phase_export_headroom,
            'total_power_kw': base_total_kw,
            'phase_power_kw': base_phase_kw,
        }

    def _apply_charging_constraints_to_actions(
        self,
        actions: Optional[Mapping[str, float]],
        electrical_storage_action: Optional[float] = None,
    ) -> Tuple[Optional[Mapping[str, float]], Optional[float]]:
        """Compatibility wrapper for charging-constraints action limiter service."""

        return self._ops_service.apply_charging_constraints_to_actions(actions, electrical_storage_action)

    def consume_charging_constraint_penalty(self) -> float:
        penalty = self._charging_constraint_penalty_kwh
        self._charging_constraint_penalty_kwh = 0.0
        return penalty

    @observation_space.setter
    def observation_space(self, observation_space: spaces.Box):
        self.__observation_space = observation_space
        self.non_periodic_normalized_observation_space_limits = self.estimate_observation_space_limits(include_all=True, periodic_normalization=False)
        self.periodic_normalized_observation_space_limits = self.estimate_observation_space_limits(include_all=True, periodic_normalization=True)

    @action_space.setter
    def action_space(self, action_space: spaces.Box):
        self.__action_space = action_space

    @name.setter
    def name(self, name: str):
        self.__name = self.uid if name is None else name

    @observation_space_limit_delta.setter
    def observation_space_limit_delta(self, observation_space_limit_delta: float):
        self.__observation_space_limit_delta = 0.0 if observation_space_limit_delta is None else observation_space_limit_delta

        if hasattr(self, 'observation_space') and self.observation_space is not None:
            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

        else:
            pass

    @maximum_temperature_delta.setter
    def maximum_temperature_delta(self, maximum_temperature_delta: float):
        self.__maximum_temperature_delta = 20.0 if maximum_temperature_delta is None else maximum_temperature_delta

        if hasattr(self, 'observation_space') and self.observation_space is not None:
            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

        else:
            pass

    @demand_observation_limit_factor.setter
    def demand_observation_limit_factor(self, demand_observation_limit_factor: float):
        self.__demand_observation_limit_factor = 2.0 if demand_observation_limit_factor is None else demand_observation_limit_factor

        if hasattr(self, 'observation_space') and self.observation_space is not None:
            self.observation_space = self.estimate_observation_space(include_all=False, normalize=False)

        else:
            pass

    @stochastic_power_outage_model.setter
    def stochastic_power_outage_model(self, stochastic_power_outage_model: PowerOutage):
        self.__stochastic_power_outage_model = PowerOutage() if stochastic_power_outage_model is None else stochastic_power_outage_model

    @simulate_power_outage.setter
    def simulate_power_outage(self, simulate_power_outage: bool):
        self.__simulate_power_outage = False if simulate_power_outage is None else simulate_power_outage

    @stochastic_power_outage.setter
    def stochastic_power_outage(self, stochastic_power_outage: bool):
        self.__stochastic_power_outage = False if stochastic_power_outage is None else stochastic_power_outage

    @Environment.random_seed.setter
    def random_seed(self, seed: int):
        Environment.random_seed.fset(self, seed)
        self.cooling_device.random_seed = self.random_seed
        self.heating_device.random_seed = self.random_seed
        self.dhw_device.random_seed = self.random_seed
        self.cooling_storage.random_seed = self.random_seed
        self.heating_storage.random_seed = self.random_seed
        self.electrical_storage.random_seed = self.random_seed
        self.pv.random_seed = self.random_seed

    @Environment.episode_tracker.setter
    def episode_tracker(self, episode_tracker: EpisodeTracker):
        Environment.episode_tracker.fset(self, episode_tracker)
        self.cooling_device.episode_tracker = self.episode_tracker
        self.heating_device.episode_tracker = self.episode_tracker
        self.dhw_device.episode_tracker = self.episode_tracker
        self.cooling_storage.episode_tracker = self.episode_tracker
        self.heating_storage.episode_tracker = self.episode_tracker
        self.dhw_storage.episode_tracker = self.episode_tracker
        self.electrical_storage.episode_tracker = self.episode_tracker
        self.non_shiftable_load_device.episode_tracker = self.episode_tracker
        self.pv.episode_tracker = self.episode_tracker

    @Environment.time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: int):
        Environment.time_step_ratio.fset(self, time_step_ratio)
        self.cooling_device.time_step_ratio = self.time_step_ratio
        self.heating_device.time_step_ratio = self.time_step_ratio
        self.dhw_device.time_step_ratio = self.time_step_ratio
        self.cooling_storage.time_step_ratio = self.time_step_ratio
        self.heating_storage.time_step_ratio = self.time_step_ratio
        self.dhw_storage.time_step_ratio = self.time_step_ratio
        self.electrical_storage.time_step_ratio = self.time_step_ratio
        self.non_shiftable_load_device.time_step_ratio = self.time_step_ratio
        self.pv.time_step_ratio = self.time_step_ratio    

    def get_metadata(self) -> Mapping[str, Any]:
        n_years = max(1, (self.episode_tracker.episode_time_steps * self.seconds_per_time_step) / (8760 * 3600))
        return {
            **super().get_metadata(),
            'name': self.name,
            'observation_metadata': self.observation_metadata,
            'action_metadata': self.action_metadata,
            'maximum_temperature_delta': self.maximum_temperature_delta,
            'cooling_device': self.cooling_device.get_metadata(),
            'heating_device': self.heating_device.get_metadata(),
            'dhw_device': self.dhw_device.get_metadata(),
            'non_shiftable_load_device': self.non_shiftable_load_device.get_metadata(),
            'cooling_storage': self.cooling_storage.get_metadata(),
            'heating_storage': self.heating_storage.get_metadata(),
            'dhw_storage': self.dhw_storage.get_metadata(),
            'electrical_storage': self.electrical_storage.get_metadata(),
            'pv': self.pv.get_metadata(),
            'annual_cooling_demand_estimate': self.energy_simulation.cooling_demand.sum() / n_years,
            'annual_heating_demand_estimate': self.energy_simulation.heating_demand.sum() / n_years,
            'annual_dhw_demand_estimate': self.energy_simulation.dhw_demand.sum() / n_years,
            'annual_non_shiftable_load_estimate': self.energy_simulation.non_shiftable_load.sum() / n_years,
            'annual_solar_generation_estimate': self._pv_generation_to_control_step(
                self.energy_simulation.solar_generation
            ).sum() / n_years,
            'charging_constraints': self._charging_constraints_config,
            'electrical_service': self._electrical_service_config,
            'electrical_storage_phase_connection': self._electrical_storage_phase_connection,
            'charger_phase_map': self._charger_phase_map,
        }

    def observations(
        self,
        include_all: bool = None,
        normalize: bool = None,
        periodic_normalization: bool = None,
        check_limits: bool = None,
        observation_names: Iterable[str] = None,
    ) -> Mapping[str, float]:
        r"""Observations at current time step."""

        return self._ops_service.observations(
            include_all=include_all,
            normalize=normalize,
            periodic_normalization=periodic_normalization,
            check_limits=check_limits,
            observation_names=observation_names,
        )

    def update_ev_charger_observations(self, observations, valid_observations, ev_chargers, include_all: bool = False):
        """Compatibility wrapper for EV charger observation service."""

        return self._ops_service.update_ev_charger_observations(
            observations,
            valid_observations,
            ev_chargers,
            include_all=include_all,
        )

    def update_deferrable_appliance_observations(self, observations, valid_observations, deferrable_appliances):
        """Compatibility wrapper for deferrable-appliance observation service."""

        return self._ops_service.update_deferrable_appliance_observations(
            observations,
            valid_observations,
            deferrable_appliances,
        )

    def update_washing_machine_observations(self, observations, valid_observations, washing_machines):
        """Backward-compatible wrapper for old washing-machine integrations."""

        return self.update_deferrable_appliance_observations(observations, valid_observations, washing_machines)

    def update_escalator_observations(self, observations, valid_observations, escalators):
        """Compatibility wrapper for escalator observation service."""

        return self._ops_service.update_escalator_observations(
            observations,
            valid_observations,
            escalators,
        )

    def _get_observations_data(self, include_all: bool = False) -> Mapping[str, Union[float, int]]:
        """Compatibility wrapper for base observation data service."""

        return self._ops_service.get_observations_data(include_all=include_all)

    def _refresh_observation_source_cache(self):
        """Cache episode-sliced observation sources to avoid per-step dynamic lookups."""

        def _collect(source) -> List[Tuple[str, np.ndarray]]:
            collected: List[Tuple[str, np.ndarray]] = []
            for key, value in vars(source).items():
                if not isinstance(value, np.ndarray):
                    continue
                observation_name = key.lstrip('_')
                try:
                    series = source.__getattr__(observation_name)
                except AttributeError:
                    continue
                collected.append((observation_name, series))

            return collected

        self._energy_simulation_observation_sources = _collect(self.energy_simulation)
        self._weather_observation_sources = _collect(self.weather)
        self._pricing_observation_sources = _collect(self.pricing)
        self._carbon_observation_sources = _collect(self.carbon_intensity)
    
    @staticmethod
    def get_periodic_observation_metadata() -> Mapping[str, int]:
        r"""Get periodic observation names and their minimum and maximum values for periodic/cyclic normalization.

        Returns
        -------
        periodic_observation_metadata: Mapping[str, int]
            Observation low and high limits.
        """

        return {
            'hour': range(1, 25),
            'day_type': range(1, 8),
            'month': range(1, 13),
            'minutes': range(0, 60),
            'seconds': range(0, 60),
        }

    def apply_actions(self,
        cooling_or_heating_device_action: float = None,
        cooling_device_action: float = None, heating_device_action: float = None,
        cooling_storage_action: float = None, heating_storage_action: float = None,
        dhw_storage_action: float = None, electrical_storage_action: float = None,
        deferrable_appliance_actions: dict = None, washing_machine_actions: dict = None,
        escalator_actions: dict = None,
        electric_vehicle_storage_actions: dict = None,
    ):
        r"""Update cooling and heating demand for next timestep and charge/discharge storage devices."""

        return self._ops_service.apply_actions(
            cooling_or_heating_device_action=cooling_or_heating_device_action,
            cooling_device_action=cooling_device_action,
            heating_device_action=heating_device_action,
            cooling_storage_action=cooling_storage_action,
            heating_storage_action=heating_storage_action,
            dhw_storage_action=dhw_storage_action,
            electrical_storage_action=electrical_storage_action,
            deferrable_appliance_actions=deferrable_appliance_actions if deferrable_appliance_actions is not None else washing_machine_actions,
            escalator_actions=escalator_actions,
            electric_vehicle_storage_actions=electric_vehicle_storage_actions,
        )

    def clear_step_electric_loads_for_action(self):
        """Clear reset-populated electric loads before applying control at the current step."""

        for device in (
            self.cooling_device,
            self.heating_device,
            self.dhw_device,
            self.non_shiftable_load_device,
        ):
            device.set_electricity_consumption(0.0, time_step=self.time_step)

    def update_cooling_demand(self, action: float):
        """Update space cooling demand for current time step."""

        raise NotImplementedError

    def update_energy_from_cooling_device(self):
        r"""Update cooling device electricity consumption and energy tranfer for current time step's cooling demand."""

        demand = self.cooling_demand[self.time_step]
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]
        storage_output = self.energy_from_cooling_storage[self.time_step]
        max_electric_power = self.downward_electrical_flexibility
        max_device_output = self.cooling_device.get_max_output_power(temperature, heating=False, max_electric_power=max_electric_power)
        self.___demand_limit_check('cooling', demand, max_device_output)
        device_output = min(demand - storage_output, max_device_output)
        self.__energy_from_cooling_device[self.time_step] = device_output
        electricity_consumption = self.cooling_device.get_input_power(device_output, temperature, heating=False)
        # LOGGER.debug(
        #     'timestep:', self.time_step, 'bldg:', self.name, 'demand:', demand, 'temperature:', temperature, 
        #     'storage_capacity:', self.cooling_storage.capacity, 'prev_soc:', self.cooling_storage.soc[self.time_step - 1], 
        #     'curr_soc:', self.cooling_storage.soc[self.time_step], 'storage_output:', storage_output, 
        #     'max_electric_power:', max_electric_power, 'max_device_output:', max_device_output, 'device_output:', 
        #     device_output, 'consumption:', electricity_consumption
        # )
        self.___electricity_consumption_polarity_check('cooling', device_output, electricity_consumption)
        self.cooling_device.update_electricity_consumption(max(0.0, electricity_consumption))

    def update_cooling_storage(self, action: float):
        r"""Charge/discharge `cooling_storage` for current time step.

        Parameters
        ----------
        action: float
            Fraction of `cooling_storage` `capacity` to charge/discharge by.
        """

        energy = normalized_capacity_action_to_energy_kwh(
            action,
            self.cooling_storage.capacity,
            seconds_per_time_step=self.seconds_per_time_step,
            scale_with_time=True,
        )
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]

        if energy > 0.0:
            max_electric_power = self.downward_electrical_flexibility
            max_output = self.cooling_device.get_max_output_power(temperature, heating=False, max_electric_power=max_electric_power)
            energy = min(max_output, energy)

        else:
            demand = self.cooling_demand[self.time_step]
            energy = max(-demand, energy)

        self.cooling_storage.charge(self._convert_energy_for_storage(self.cooling_storage, energy))
        charged_energy = max(self.cooling_storage.energy_balance[self.time_step], 0.0)
        electricity_consumption = self.cooling_device.get_input_power(charged_energy, temperature, heating=False)
        self.cooling_device.update_electricity_consumption(electricity_consumption)

    def update_heating_demand(self, action: float):
        """Update space heating demand for current time step."""

        raise NotImplementedError

    def update_energy_from_heating_device(self):
        r"""Update heating device electricity consumption and energy tranfer for current time step's heating demand."""

        demand = self.heating_demand[self.time_step]
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]
        storage_output = self.energy_from_heating_storage[self.time_step]
        max_electric_power = self.downward_electrical_flexibility
        max_device_output = self.heating_device.get_max_output_power(temperature, heating=True, max_electric_power=max_electric_power) \
            if isinstance(self.heating_device, HeatPump) else self.heating_device.get_max_output_power(max_electric_power=max_electric_power)
        self.___demand_limit_check('heating', demand, max_device_output)
        device_output = min(demand - storage_output, max_device_output)
        self.__energy_from_heating_device[self.time_step] = device_output
        electricity_consumption = self.heating_device.get_input_power(device_output, temperature, heating=True) \
            if isinstance(self.heating_device, HeatPump) else self.heating_device.get_input_power(device_output)
        self.___electricity_consumption_polarity_check('heating', device_output, electricity_consumption)
        self.heating_device.update_electricity_consumption(max(0.0, electricity_consumption))

    def update_heating_storage(self, action: float):
        r"""Charge/discharge `heating_storage` for current time step.

        Parameters
        ----------
        action: float
            Fraction of `heating_storage` `capacity` to charge/discharge by.
        """

        energy = normalized_capacity_action_to_energy_kwh(
            action,
            self.heating_storage.capacity,
            seconds_per_time_step=self.seconds_per_time_step,
            scale_with_time=True,
        )
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]

        if energy > 0.0:
            max_electric_power = self.downward_electrical_flexibility
            max_output = self.heating_device.get_max_output_power(temperature, heating=True, max_electric_power=max_electric_power) \
                if isinstance(self.heating_device, HeatPump) else self.heating_device.get_max_output_power(max_electric_power=max_electric_power)
            energy = min(max_output, energy)

        else:
            demand = self.heating_demand[self.time_step]
            energy = max(-demand, energy)

        self.heating_storage.charge(self._convert_energy_for_storage(self.heating_storage, energy))
        charged_energy = max(self.heating_storage.energy_balance[self.time_step], 0.0)
        electricity_consumption = self.heating_device.get_input_power(charged_energy, temperature, heating=True) \
            if isinstance(self.heating_device, HeatPump) else self.heating_device.get_input_power(charged_energy)
        self.heating_device.update_electricity_consumption(electricity_consumption)

    def update_energy_from_dhw_device(self):
        r"""Update dhw device electricity consumption and energy tranfer for current time step's dhw demand."""

        demand = self.dhw_demand[self.time_step]
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]
        storage_output = self.energy_from_dhw_storage[self.time_step]
        max_electric_power = self.downward_electrical_flexibility
        max_device_output = self.dhw_device.get_max_output_power(temperature, heating=True, max_electric_power=max_electric_power) \
            if isinstance(self.dhw_device, HeatPump) else self.dhw_device.get_max_output_power(max_electric_power=max_electric_power)
        self.___demand_limit_check('dhw', demand, max_device_output)
        device_output = min(demand - storage_output, max_device_output)
        self.__energy_from_dhw_device[self.time_step] = device_output
        electricity_consumption = self.dhw_device.get_input_power(device_output, temperature, heating=True) \
            if isinstance(self.dhw_device, HeatPump) else self.dhw_device.get_input_power(device_output)
        self.___electricity_consumption_polarity_check('dhw', device_output, electricity_consumption)
        self.dhw_device.update_electricity_consumption(max(0.0, electricity_consumption))

    def update_dhw_storage(self, action: float):
        r"""Charge/discharge `dhw_storage` for current time step.

        Parameters
        ----------
        action: float
            Fraction of `dhw_storage` `capacity` to charge/discharge by.
        """

        energy = normalized_capacity_action_to_energy_kwh(
            action,
            self.dhw_storage.capacity,
            seconds_per_time_step=self.seconds_per_time_step,
            scale_with_time=True,
        )
        temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]

        if energy > 0.0:
            max_electric_power = self.downward_electrical_flexibility
            max_output = self.dhw_device.get_max_output_power(temperature, heating=True, max_electric_power=max_electric_power) \
                if isinstance(self.dhw_device, HeatPump) else self.dhw_device.get_max_output_power(max_electric_power=max_electric_power)
            energy = min(max_output, energy)

        else:
            demand = self.dhw_demand[self.time_step]
            energy = max(-demand, energy)

        self.dhw_storage.charge(self._convert_energy_for_storage(self.dhw_storage, energy))
        charged_energy = max(self.dhw_storage.energy_balance[self.time_step], 0.0)
        electricity_consumption = self.dhw_device.get_input_power(charged_energy, temperature, heating=True) \
            if isinstance(self.dhw_device, HeatPump) else self.dhw_device.get_input_power(charged_energy)
        self.dhw_device.update_electricity_consumption(electricity_consumption)

    def update_non_shiftable_load(self):
        r"""Update non shiftable loads electricity consumption for current time step non shiftable load."""

        demand = min(self.non_shiftable_load[self.time_step], self.downward_electrical_flexibility)
        self.__energy_to_non_shiftable_load[self.time_step] = demand
        self.non_shiftable_load_device.update_electricity_consumption(demand)

    def update_electrical_storage(self, action: float):
        """
        Charge/discharge the electrical storage (BESS) for the current time step.

        Parameters
        ----------
        action : float
            Normalized charging or discharging action (range [-1, 1]).
        """

        action = float(np.clip(action, -1.0, 1.0))
        energy = normalized_power_action_to_energy_kwh(
            action,
            self.electrical_storage.nominal_power,
            self.seconds_per_time_step,
        )

        # Optionally clamp to flexibility range if needed
        energy = min(energy, self.downward_electrical_flexibility)
        if self.power_outage and energy < 0.0:
            try:
                base_total_kw, _ = self._ops_service._estimate_base_power_at_step(self.time_step)
            except Exception:
                base_total_kw = 0.0
            local_load_kwh = power_kw_to_energy_kwh(max(float(base_total_kw), 0.0), self.seconds_per_time_step)
            energy = max(energy, -local_load_kwh)


        self.electrical_storage.charge(self._convert_energy_for_storage(self.electrical_storage, energy))

    @staticmethod
    def _convert_energy_for_storage(storage: StorageDevice, energy: float) -> float:
        """Convert energy for storage models that expect dataset-resolution values."""

        ratio = getattr(storage, 'time_step_ratio', None)
        return to_dataset_resolution_energy(energy, ratio)

    def _dataset_energy_to_control_step(self, energy: float) -> float:
        """Convert dataset-resolution kWh to the active control-step kWh."""

        ratio = 1.0 if self.time_step_ratio in (None, 0) else float(self.time_step_ratio)
        return float(energy) * ratio

    def _pv_generation_to_control_step(self, solar_generation: Union[float, Iterable[float]]) -> np.ndarray:
        """Convert PV inputs to control-step kWh."""

        generation = np.array(self.pv.get_generation(solar_generation), dtype='float32')

        if getattr(self.pv, 'generation_mode', 'per_kw') == 'absolute':
            ratio = 1.0 if self.time_step_ratio in (None, 0) else float(self.time_step_ratio)
            generation = generation * ratio

        return generation

    def _refresh_pv_generation_from(self, time_step: int) -> None:
        """Commit the current PV asset's production from ``time_step`` onward.

        Dynamic topology events replace the physical :class:`PV` instance at
        runtime.  ``__solar_generation`` is otherwise calculated only during
        reset, so changing ``self.pv`` without refreshing this series would
        alter the topology metadata while leaving the old PV production in the
        electrical balance.  Only the present and future are rewritten: past
        production remains an immutable record for KPI accounting.
        """

        start = int(max(time_step, 0))
        if start >= len(self.__solar_generation):
            return

        generation = (
            self._pv_generation_to_control_step(self.energy_simulation.solar_generation)
            * -1.0
        )
        upper = min(len(self.__solar_generation), len(generation))
        if start < upper:
            self.__solar_generation[start:upper] = generation[start:upper]

        if upper < len(self.__solar_generation):
            self.__solar_generation[max(start, upper):] = 0.0

    def _clip_outage_electric_loads_to_local_supply(self):
        """Clip initial electric loads to locally available islanded supply."""

        if not self.power_outage:
            return

        t = self.time_step
        available = abs(float(self.solar_generation[t])) + max(-float(self.electrical_storage.electricity_consumption[t]), 0.0)
        for device in (
            self.non_shiftable_load_device,
            self.dhw_device,
            self.heating_device,
            self.cooling_device,
        ):
            current = max(float(device.electricity_consumption[t]), 0.0)
            served = min(current, available)
            if served < current:
                device.set_electricity_consumption(served, time_step=t)
            available = max(available - served, 0.0)

    def ___demand_limit_check(self, end_use: str, demand: float, max_device_output: float):
        message = f'timestep: {self.time_step}, building: {self.name}, outage: {self.power_outage}, demand: {demand},' \
            f'output: {max_device_output}, difference: {demand - max_device_output}, check: {demand <= max_device_output},'
        assert self.power_outage or demand <= max_device_output or abs(demand - max_device_output) < TOLERANCE, \
            f'demand is greater than {end_use}_device max output | {message}'

    def ___electricity_consumption_polarity_check(self, end_use: str, device_output: float, electricity_consumption: float):
        message = f'timestep: {self.time_step}, building: {self.name}, device_output: {device_output}, electricity_consumption: {electricity_consumption}'
        assert electricity_consumption >= 0.0 or abs(electricity_consumption) < TOLERANCE, \
            f'negative electricity consumption for {end_use} demand | {message}'

    def estimate_observation_space(self, include_all: bool = None, normalize: bool = None) -> spaces.Box:
        r"""Get estimate of observation spaces.

        Parameters
        ----------
        include_all: bool, default: False,
            Whether to estimate for all observations as listed in `observation_metadata` or only those that are active.
        normalize : bool, default: False
            Whether to apply min-max normalization bounded between [0, 1].

        Returns
        -------
        observation_space : spaces.Box
            Observation low and high limits.
        """

        normalize = False if normalize is None else normalize
        normalized_observation_space_limits = self.estimate_observation_space_limits(include_all=include_all, periodic_normalization=True)
        unnormalized_observation_space_limits = self.estimate_observation_space_limits(include_all=include_all, periodic_normalization=False)

        if normalize:
            low_limit, high_limit = normalized_observation_space_limits
            low_limit = [0.0] * len(low_limit)
            high_limit = [1.0] * len(high_limit)
        else:
            low_limit, high_limit = unnormalized_observation_space_limits
            low_limit = list(low_limit.values())
            high_limit = list(high_limit.values())

        return spaces.Box(low=np.array(low_limit, dtype='float32'), high=np.array(high_limit, dtype='float32'), dtype='float32')

    def _ev_time_observation_high_limit(self, key: str) -> float:
        try:
            episode_steps = float(getattr(self.episode_tracker, 'episode_time_steps', 0) or 0)
        except Exception:
            episode_steps = 0.0
        high = max(24.0, episode_steps)
        if self.electric_vehicle_chargers is None:
            return high

        time_attributes = []
        if 'departure_time' in key:
            time_attributes.append('electric_vehicle_departure_time')
        if 'estimated_arrival_time' in key:
            time_attributes.append('electric_vehicle_estimated_arrival_time')

        for charger in self.electric_vehicle_chargers:
            simulation = getattr(charger, 'charger_simulation', None)
            if simulation is None:
                continue
            for attribute in time_attributes:
                raw_values = np.array(getattr(simulation, attribute, []), dtype='float64')
                if raw_values.size > 0:
                    high = max(high, float(raw_values.size))
                values = raw_values[np.isfinite(raw_values) & (raw_values >= 0.0)]
                if values.size > 0:
                    high = max(high, float(np.nanmax(values)))

        return high

    def _deferrable_time_observation_high_limit(self) -> float:
        try:
            high = float(max(getattr(self.episode_tracker, 'simulation_time_steps', 0) or 0, 1))
        except Exception:
            high = 1.0

        for appliance in self.deferrable_appliances or []:
            simulation = getattr(appliance, 'deferrable_appliance_simulation', None)
            for cycle in getattr(simulation, 'flexibility_schedule', []) or []:
                for key in ('earliest_start_time_step', 'latest_start_time_step', 'deadline_time_step'):
                    try:
                        value = float(cycle.get(key, -1.0))
                    except Exception:
                        value = -1.0
                    if np.isfinite(value) and value >= 0.0:
                        high = max(high, value)

        return high

    def _deferrable_step_observation_high_limit(self) -> float:
        high = self._deferrable_time_observation_high_limit()
        for appliance in self.deferrable_appliances or []:
            simulation = getattr(appliance, 'deferrable_appliance_simulation', None)
            for cycle in getattr(simulation, 'flexibility_schedule', []) or []:
                try:
                    high = max(high, float(cycle.get('duration_steps', 0.0)))
                except Exception:
                    pass

        return high

    def _deferrable_power_observation_high_limit(self) -> float:
        step_hours = max(float(self.seconds_per_time_step) / 3600.0, 1.0e-12)
        high = 1.0

        for appliance in self.deferrable_appliances or []:
            simulation = getattr(appliance, 'deferrable_appliance_simulation', None)
            for cycle in getattr(simulation, 'flexibility_schedule', []) or []:
                profile = np.array(cycle.get('load_profile', []), dtype='float64')
                if profile.size > 0:
                    high = max(high, float(np.nanmax(profile)) / step_hours)

        return high + 1.0e-6

    @staticmethod
    def _series_bound(values: Iterable[float], *, upper: bool, default: float = 0.0) -> float:
        arr = np.asarray(values)
        if arr.size == 0:
            return float(default)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                with np.errstate(all='ignore'):
                    value = np.nanmax(arr) if upper else np.nanmin(arr)
        except (TypeError, ValueError):
            try:
                numeric = arr.astype('float64')
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    with np.errstate(all='ignore'):
                        value = np.nanmax(numeric) if upper else np.nanmin(numeric)
            except (TypeError, ValueError):
                return float(default)

        try:
            value = float(value)
        except (TypeError, ValueError):
            return float(default)

        return value if np.isfinite(value) else float(default)

    def estimate_observation_space_limits(self, include_all: bool = None, periodic_normalization: bool = None) -> Tuple[
        Mapping[str, float], Mapping[str, float]]:
        r"""Get estimate of observation space limits.

        Find minimum and maximum possible values of all the observations, which can then be used by the RL agent to scale the observations 
        and train any function approximators more effectively.

        Parameters
        ----------
        include_all: bool, default: False,
            Whether to estimate for all observations as listed in `observation_metadata` or only those that are active.
        periodic_normalization: bool, default: False
            Whether to apply sine-cosine normalization to cyclic observations including hour, day_type and month.

        Returns
        -------
        observation_space_limits : Tuple[Mapping[str, float], Mapping[str, float]]
            Observation low and high limits.

        Notes
        -----
        Lower and upper bounds of net electricity consumption are rough estimates and may not be completely accurate hence,
        scaling this observation-variable using these bounds may result in normalized values above 1 or below 0. It is also
        assumed that devices and storage systems have been sized.
        """

        include_all = False if include_all is None else include_all
        internal_limit_observations = [
            'net_electricity_consumption_without_storage',
            'net_electricity_consumption_without_storage_and_partial_load',
            'net_electricity_consumption_without_storage_and_partial_load_and_pv'
        ]
        observation_names = list(self.observation_metadata.keys()) + internal_limit_observations if include_all else self.active_observations
        periodic_normalization = False if periodic_normalization is None else periodic_normalization
        periodic_observations = self.get_periodic_observation_metadata()
        low_limit, high_limit = {}, {}
        data = self._get_observation_space_limits_data()
        total_charger_power_kw = 0.0
        total_charger_power_kw += sum(getattr(charger, 'max_charging_power', 0.0) or 0.0 for charger in self.electric_vehicle_chargers)
        total_charger_power_kw += sum(getattr(charger, 'max_discharging_power', 0.0) or 0.0 for charger in self.electric_vehicle_chargers)
        total_storage_power_kw = float(getattr(self.electrical_storage, 'nominal_power', 0.0) or 0.0)
        max_violation_energy = power_kw_to_energy_kwh(total_charger_power_kw + total_storage_power_kw, self.seconds_per_time_step)
        cooling_device_energy_limit = power_kw_to_energy_kwh(self.cooling_device.nominal_power, self.seconds_per_time_step)
        heating_device_energy_limit = power_kw_to_energy_kwh(self.heating_device.nominal_power, self.seconds_per_time_step)
        dhw_device_energy_limit = power_kw_to_energy_kwh(self.dhw_device.nominal_power, self.seconds_per_time_step)
        electrical_storage_energy_limit = power_kw_to_energy_kwh(self.electrical_storage.nominal_power, self.seconds_per_time_step)
        escalators_energy_limit = sum(
            power_kw_to_energy_kwh(escalator.normal_power, self.seconds_per_time_step)
            for escalator in self.escalators or []
        )

        for key in observation_names:
            if key.startswith('charging_phase_one_hot_'):
                low_limit[key] = 0.0
                high_limit[key] = 1.0
                continue

            if key == 'charging_constraint_violation_kwh':
                low_limit[key] = 0.0
                high_limit[key] = max_violation_energy
                continue

            if key == 'net_electricity_consumption':
                # assumes devices and storages have been sized
                low_limits = data['non_shiftable_load'] - (
                    + electrical_storage_energy_limit
                    + data['solar_generation']
                )
                high_limits = data['non_shiftable_load'] \
                    + cooling_device_energy_limit \
                                + heating_device_energy_limit \
                                    + dhw_device_energy_limit \
                                        + electrical_storage_energy_limit \
                                            + escalators_energy_limit \
                                            - data['solar_generation']
                low_limit[key] = min(low_limits.min(), 0.0)
                high_limit[key] = high_limits.max()

            elif key == 'net_electricity_consumption_without_storage':
                low_limit[key] = min(low_limit['net_electricity_consumption'] + electrical_storage_energy_limit, 0.0)
                high_limit[key] = high_limit['net_electricity_consumption'] - electrical_storage_energy_limit

            elif key == 'net_electricity_consumption_without_storage_and_partial_load':
                low_limit[key] = low_limit['net_electricity_consumption_without_storage']
                high_limit[key] = high_limit['net_electricity_consumption_without_storage']

            elif key == 'net_electricity_consumption_without_storage_and_partial_load_and_pv':
                low_limit[key] = 0.0
                high_limits = data['non_shiftable_load'] \
                                + cooling_device_energy_limit \
                                    + heating_device_energy_limit \
                                        + dhw_device_energy_limit
                high_limit[key] = high_limits.max()

            elif key in ['cooling_storage_soc', 'heating_storage_soc', 'dhw_storage_soc',
                'electrical_storage_soc']:
                low_limit[key] = 0.0
                high_limit[key] = 1.0

            elif key in ['cooling_device_efficiency']:
                cop = self.cooling_device.get_cop(data['outdoor_dry_bulb_temperature'], heating=False)
                low_limit[key] = min(cop)
                high_limit[key] = max(cop)

            elif key in ['heating_device_efficiency']:
                if isinstance(self.heating_device, HeatPump):
                    cop = self.heating_device.get_cop(data['outdoor_dry_bulb_temperature'], heating=True)
                    low_limit[key] = min(cop)
                    high_limit[key] = max(cop)
                else:
                    low_limit[key] = self.heating_device.efficiency
                    high_limit[key] = self.heating_device.efficiency

            elif 'connected_state' in key or "_incoming_state" in key:
                low_limit[key] = 0
                high_limit[key] = 1

            elif "_departure_time" in key or "_estimated_arrival_time" in key:
                low_limit[key] = -1
                high_limit[key] = self._ev_time_observation_high_limit(key)

            elif "_soc" in key and "_electric_vehicle" in key:
                low_limit[key] = -0.1
                high_limit[key] = 1.0

            elif 'charger' in key:
                if self.electric_vehicle_chargers is not None:
                    for charger in self.electric_vehicle_chargers:
                        if key == f'charger_{charger.charger_id}_connected_state' or key == f'charger_{charger.charger_id}_incoming_state':
                            low_limit[key] = 0
                            high_limit[key] = 1
                        elif 'electric_vehicle_charger_state' in key:
                            low_limit[key] = 0
                            high_limit[key] = 1
                        elif any(value in key for value in
                                 ['electric_vehicle_departure_time', 'electric_vehicle_estimated_arrival_time']):
                            low_limit[key] = -1
                            high_limit[key] = self._ev_time_observation_high_limit(key)
                        elif any(value in key for value in
                                 ['electric_vehicle_required_soc_departure', 'electric_vehicle_estimated_soc_arrival',
                                  'electric_vehicle_soc']):
                            low_limit[key] = -0.1
                            high_limit[key] = 1.0
                        elif any(value in key for value in [f'connected_electric_vehicle_at_charger_{charger.charger_id}_battery_capacity']):
                            low_limit[key] = -1
                            high_limit[key] = 100

            elif key.startswith('escalator_'):
                low_limit[key] = 0.0
                if key.endswith(('_state', '_requested_state')):
                    high_limit[key] = 2.0
                elif key.endswith(('people_detected', 'available', 'service_required', 'service_met')):
                    high_limit[key] = 1.0
                elif key.endswith('_power_kw'):
                    high_limit[key] = max((e.normal_power for e in self.escalators or []), default=0.0)
                else:
                    source = 'minutes_to_next_train'
                    if 'passengers_from_trains' in key:
                        source = 'passengers_from_trains_15min'
                    elif 'background_pedestrians' in key:
                        source = 'background_pedestrians_15min'
                    elif 'passengers_expected' in key or 'unserved_passengers' in key:
                        source = 'passengers_expected_15min'
                    elif key.endswith('passing_trains'):
                        source = 'arriving_trains'
                    values = [
                        np.max(getattr(e.escalator_simulation, source))
                        for e in self.escalators or []
                        if getattr(e.escalator_simulation, source, None) is not None
                    ]
                    high_limit[key] = max([float(v) for v in values] or [1.0])

            elif 'deferrable_appliance' in key:
                low_limit[key] = -1.0
                if key.endswith('_ratio') or key.endswith(('pending', 'running', 'can_start', 'deadline_missed')):
                    high_limit[key] = 1.0
                elif key.endswith('_kwh'):
                    high_limit[key] = 1.0e6
                elif key.endswith('_kw'):
                    high_limit[key] = self._deferrable_power_observation_high_limit()
                elif key.endswith('_time_step'):
                    high_limit[key] = self._deferrable_time_observation_high_limit()
                elif key.endswith('_steps'):
                    high_limit[key] = self._deferrable_step_observation_high_limit()
                elif '_hours_' in key:
                    high_limit[key] = self._deferrable_time_observation_high_limit() * max(float(self.seconds_per_time_step) / 3600.0, 0.0)
                else:
                    high_limit[key] = max(self.episode_tracker.simulation_time_steps, 1)
            elif key in ['dhw_device_efficiency']:
                if isinstance(self.dhw_device, HeatPump):
                    cop = self.dhw_device.get_cop(data['outdoor_dry_bulb_temperature'], heating=True)
                    low_limit[key] = min(cop)
                    high_limit[key] = max(cop)
                else:
                    low_limit[key] = self.dhw_device.efficiency
                    high_limit[key] = self.dhw_device.efficiency

            elif key == 'indoor_dry_bulb_temperature':
                low_limit[key] = data['indoor_dry_bulb_temperature'].min() - self.maximum_temperature_delta
                high_limit[key] = data['indoor_dry_bulb_temperature'].max() + self.maximum_temperature_delta

            elif key in ['indoor_dry_bulb_temperature_cooling_delta', 'indoor_dry_bulb_temperature_heating_delta']:
                low_limit[key] = -self.maximum_temperature_delta
                high_limit[key] = self.maximum_temperature_delta

            elif key == 'comfort_band':
                low_limit[key] = 0
                high_limit[key] = self._series_bound(data[key], upper=True)

            elif key in ['cooling_demand', 'heating_demand', 'dhw_demand']:
                low_limit[key] = 0.0
                max_demand = data[key].max()
                high_limit[key] = max_demand * self.demand_observation_limit_factor

            elif key == 'cooling_electricity_consumption':
                low_limit[key] = 0.0
                high_limit[key] = cooling_device_energy_limit

            elif key == 'heating_electricity_consumption':
                low_limit[key] = 0.0
                high_limit[key] = heating_device_energy_limit

            elif key == 'dhw_electricity_consumption':
                low_limit[key] = 0.0
                high_limit[key] = dhw_device_energy_limit

            elif key == 'cooling_storage_electricity_consumption':
                demand = self.energy_simulation.__getattr__(
                    f'cooling_demand',
                    start_time_step=self.episode_tracker.simulation_start_time_step,
                    end_time_step=self.episode_tracker.simulation_end_time_step
                )
                electricity_consumption = self.cooling_device.get_input_power(demand, data['outdoor_dry_bulb_temperature'], False)
                low_limit[key] = -self._series_bound(electricity_consumption, upper=True)
                high_limit[key] = cooling_device_energy_limit

            elif key == 'heating_storage_electricity_consumption':
                demand = self.energy_simulation.__getattr__(
                    f'heating_demand',
                    start_time_step=self.episode_tracker.simulation_start_time_step,
                    end_time_step=self.episode_tracker.simulation_end_time_step
                )
                electricity_consumption = self.heating_device.get_input_power(demand, data['outdoor_dry_bulb_temperature'], True) \
                    if isinstance(self.heating_device, HeatPump) else self.heating_device.get_input_power(demand)
                low_limit[key] = -self._series_bound(electricity_consumption, upper=True)
                high_limit[key] = heating_device_energy_limit

            elif key == 'dhw_storage_electricity_consumption':
                demand = self.energy_simulation.__getattr__(
                    f'dhw_demand',
                    start_time_step=self.episode_tracker.simulation_start_time_step,
                    end_time_step=self.episode_tracker.simulation_end_time_step
                )
                electricity_consumption = self.dhw_device.get_input_power(demand, data['outdoor_dry_bulb_temperature'], True) \
                    if isinstance(self.dhw_device, HeatPump) else self.dhw_device.get_input_power(demand)
                low_limit[key] = -self._series_bound(electricity_consumption, upper=True)
                high_limit[key] = dhw_device_energy_limit

            elif key == 'electrical_storage_electricity_consumption':
                low_limit[key] = -electrical_storage_energy_limit
                high_limit[key] = electrical_storage_energy_limit

            elif key == 'power_outage':
                low_limit[key] = 0.0
                high_limit[key] = 1.0

            elif periodic_normalization and key in periodic_observations:
                values = list(periodic_observations[key])
                cycle_max = max(values) + (1 if min(values) == 0 else 0)
                pn = PeriodicNormalization(cycle_max)
                x_sin, x_cos = pn * np.array(values)
                low_limit[f'{key}_cos'], high_limit[f'{key}_cos'] = (
                    self._series_bound(x_cos, upper=False),
                    self._series_bound(x_cos, upper=True),
                )
                low_limit[f'{key}_sin'], high_limit[f'{key}_sin'] = (
                    self._series_bound(x_sin, upper=False),
                    self._series_bound(x_sin, upper=True),
                )

            elif key == 'occupant_interaction_indoor_dry_bulb_temperature_set_point_delta':
                # will get set in the overriding  LogisticRegressionOccupantInteractionBuilding._get_observation_space_limits_data
                pass

            else:
                low_limit[key] = self._series_bound(data[key], upper=False)
                high_limit[key] = self._series_bound(data[key], upper=True)

        low_limit = {k: v - self.observation_space_limit_delta for k, v in low_limit.items()}
        high_limit = {k: v + self.observation_space_limit_delta for k, v in high_limit.items()}

        return low_limit, high_limit
    
    def _get_observation_space_limits_data(self) -> Mapping[str, List[Union[float, int]]]:
        # Use entire dataset length for space limit estimation
        data = {
            **{k.lstrip('_'): self.energy_simulation.__getattr__(
                k.lstrip('_'), 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            ) for k in vars(self.energy_simulation)},
            'solar_generation':self._pv_generation_to_control_step(self.energy_simulation.__getattr__(
                'solar_generation', 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            )),
            **{k.lstrip('_'): self.weather.__getattr__(
                k.lstrip('_'), 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            ) for k in vars(self.weather)},
            **{k.lstrip('_'): self.carbon_intensity.__getattr__(
                k.lstrip('_'), 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            ) for k in vars(self.carbon_intensity)},
            **{k.lstrip('_'): self.pricing.__getattr__(
                k.lstrip('_'), 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            ) for k in vars(self.pricing)},
        }

        timesteps = self.episode_tracker.simulation_time_steps
        if getattr(self, '_charging_constraints_enabled', False):
            total_charger_power_kw = 0.0
            total_charger_power_kw += sum(getattr(charger, 'max_charging_power', 0.0) or 0.0 for charger in self.electric_vehicle_chargers)
            total_charger_power_kw += sum(getattr(charger, 'max_discharging_power', 0.0) or 0.0 for charger in self.electric_vehicle_chargers)
            total_storage_power_kw = float(getattr(self.electrical_storage, 'nominal_power', 0.0) or 0.0)
            control_margin_kw = total_charger_power_kw + total_storage_power_kw

            step_seconds = max(float(self.seconds_per_time_step), 1.0e-9)
            ratio = 1.0 if self.time_step_ratio in (None, 0) else float(self.time_step_ratio)

            def _energy_series_to_power_kw(values, *, already_control_step: bool = False):
                values = np.asarray(values, dtype='float64')
                if values.size == 0:
                    values = np.asarray([0.0], dtype='float64')
                if not already_control_step:
                    values = values * ratio
                return values * (3600.0 / step_seconds)

            non_shiftable_power_kw = _energy_series_to_power_kw(data.get('non_shiftable_load', np.zeros(timesteps)))
            solar_power_kw = -_energy_series_to_power_kw(
                data.get('solar_generation', np.zeros(timesteps)),
                already_control_step=True,
            )
            fixed_base_power_kw = non_shiftable_power_kw + solar_power_kw
            base_power_min_kw = self._series_bound(fixed_base_power_kw, upper=False)
            base_power_max_kw = self._series_bound(fixed_base_power_kw, upper=True)
            base_power_max_kw += float(getattr(self.cooling_device, 'nominal_power', 0.0) or 0.0)
            base_power_max_kw += float(getattr(self.heating_device, 'nominal_power', 0.0) or 0.0)
            base_power_max_kw += float(getattr(self.dhw_device, 'nominal_power', 0.0) or 0.0)
            try:
                base_power_max_kw += max(float(self._deferrable_power_observation_high_limit()), 0.0)
            except Exception:
                pass

            def _headroom_bounds(limit, *, export: bool = False):
                limit = float(limit)
                if getattr(self, '_electrical_service_enabled', False):
                    min_total_kw = base_power_min_kw - control_margin_kw
                    max_total_kw = base_power_max_kw + control_margin_kw
                    if export:
                        bounds = [limit + min_total_kw, limit + max_total_kw]
                    else:
                        bounds = [limit - max_total_kw, limit - min_total_kw]
                    return np.array([min(bounds), max(bounds)], dtype='float32')

                return np.array([0.0, limit], dtype='float32')

            if getattr(self, '_expose_charging_constraints', False):
                if self._building_charger_limit_kw is not None:
                    data['charging_building_headroom_kw'] = _headroom_bounds(self._building_charger_limit_kw)
                if getattr(self, '_electrical_service_enabled', False):
                    export_limit = self._electrical_service_limits.get('total', {}).get('export_kw')
                    if export_limit is not None:
                        data['charging_building_export_headroom_kw'] = _headroom_bounds(export_limit, export=True)
                for phase in self._phase_limits:
                    import_limit = phase.get('import_kw')
                    if import_limit is not None:
                        key = f"charging_phase_{phase['name']}_headroom_kw"
                        data[key] = _headroom_bounds(import_limit)
                    if getattr(self, '_electrical_service_enabled', False):
                        export_limit = phase.get('export_kw')
                        if export_limit is not None:
                            key = f"charging_phase_{phase['name']}_export_headroom_kw"
                            data[key] = _headroom_bounds(export_limit, export=True)

            max_violation_energy = power_kw_to_energy_kwh(total_charger_power_kw + total_storage_power_kw, self.seconds_per_time_step)
            data['charging_constraint_violation_kwh'] = np.array([0.0, max_violation_energy], dtype='float32')

            phase_one_hot_keys = getattr(self, '_phase_encoding_observation_keys', []) or []
            if phase_one_hot_keys:
                for key in phase_one_hot_keys:
                    data[key] = np.array([0.0, 1.0], dtype='float32')

        return data
    
    def estimate_action_space(self) -> spaces.Box:
        r"""Get estimate of action spaces.

        Find minimum and maximum possible values of all the actions, which can then be used by the RL agent to scale the selected actions.

        Returns
        -------
        action_space : spaces.Box
            Action low and high limits.

        Notes
        -----
        The lower and upper bounds for the `cooling_storage`, `heating_storage` and `dhw_storage` actions are set to (+/-) 1/maximum_demand for each respective end use, 
        as the energy storage device can't provide the building with more energy than it will ever need for a given time step. . 
        For example, if `cooling_storage` capacity is 20 kWh and the maximum `cooling_demand` is 5 kWh, its actions will be bounded between -5/20 and 5/20.
        These boundaries should speed up the learning process of the agents and make them more stable compared to setting them to -1 and 1. 
        """

        low_limit, high_limit = [], []

        for key in self.active_actions:
            if key == 'cooling_or_heating_device':
                if self.cooling_device.nominal_power > ZERO_DIVISION_PLACEHOLDER:
                    low_limit.append(-1.0)

                else:
                    low_limit.append(0.0)

                if self.heating_device.nominal_power > ZERO_DIVISION_PLACEHOLDER:
                    high_limit.append(1.0)

                else:
                    high_limit.append(0.0)

            elif key in ['cooling_device', 'heating_device']:
                low_limit.append(0.0)
                high_limit.append(1.0)

            elif 'electric_vehicle_storage' in key:
                if self.electric_vehicle_chargers is not None:
                    for c in self.electric_vehicle_chargers:
                        if key == f'electric_vehicle_storage_{c.charger_id}':
                            discharging_limit = 0 if c.max_discharging_power == 0 else -1
                            high_limit.append(1.0)  # For discharging limit
                            low_limit.append(discharging_limit)  # For charging limit
            
            elif key.startswith('deferrable_appliance_'):
                low_limit.append(0.0)
                high_limit.append(1.0)

            elif key.startswith('escalator_'):
                low_limit.append(0.0)
                high_limit.append(1.0)

            elif 'storage' in key:
                if key == 'electrical_storage':
                    limit = 1

                else:
                    if key == 'cooling_storage':
                        capacity = self.cooling_storage.capacity
                        power = self.cooling_device.nominal_power

                    elif key == 'heating_storage':
                        capacity = self.heating_storage.capacity
                        power = self.heating_device.nominal_power

                    elif key == 'dhw_storage':
                        capacity = self.dhw_storage.capacity
                        power = self.dhw_device.nominal_power

                    else:
                        raise Exception(f'Unknown action: {key}')

                    limit = power/max(capacity, ZERO_DIVISION_PLACEHOLDER)

                limit = min(limit, 1.0)
                low_limit.append(-limit)
                high_limit.append(limit)

            else:
                if key == 'cooling_storage':
                    capacity = self.cooling_storage.capacity
                    cooling_demand = self.energy_simulation.__getattr__(
                        'cooling_demand',
                        start_time_step=self.episode_tracker.simulation_start_time_step,
                        end_time_step=self.episode_tracker.simulation_end_time_step
                    )
                    maximum_demand = cooling_demand.max()

                elif key == 'heating_storage':
                    capacity = self.heating_storage.capacity
                    heating_demand = self.energy_simulation.__getattr__(
                        'heating_demand',
                        start_time_step=self.episode_tracker.simulation_start_time_step,
                        end_time_step=self.episode_tracker.simulation_end_time_step
                    )
                    maximum_demand = heating_demand.max()

                elif key == 'dhw_storage':
                    capacity = self.dhw_storage.capacity
                    dhw_demand = self.energy_simulation.__getattr__(
                        'dhw_demand',
                        start_time_step=self.episode_tracker.simulation_start_time_step,
                        end_time_step=self.episode_tracker.simulation_end_time_step
                    )
                    maximum_demand = dhw_demand.max()

                else:
                    raise Exception(f'Unknown action: {key}')

                maximum_demand_ratio = maximum_demand / max(capacity, ZERO_DIVISION_PLACEHOLDER)

                try:
                    low_limit.append(max(-maximum_demand_ratio, -1.0))
                    high_limit.append(min(maximum_demand_ratio, 1.0))

                except ZeroDivisionError:
                    low_limit.append(-1.0)
                    high_limit.append(1.0)

        return spaces.Box(low=np.array(low_limit, dtype='float32'), high=np.array(high_limit, dtype='float32'),
                          dtype='float32')

    def autosize_cooling_device(self, **kwargs):
        """Autosize `cooling_device` `nominal_power` to minimum power needed to always meet `cooling_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `cooling_device` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'cooling_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        temperature = self.weather.__getattr__(
            'outdoor_dry_bulb_temperature',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        self.cooling_device.nominal_power = self.cooling_device.autosize(temperature, cooling_demand=demand, **kwargs)

    def autosize_heating_device(self, **kwargs):
        """Autosize `heating_device` `nominal_power` to minimum power needed to always meet `heating_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `heating_device` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'heating_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        temperature = self.weather.__getattr__(
            'outdoor_dry_bulb_temperature',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )

        if isinstance(self.heating_device, HeatPump):
            self.heating_device.nominal_power = self.heating_device.autosize(temperature, heating_demand=demand, **kwargs)

        else:
            self.heating_device.nominal_power = self.heating_device.autosize(demand, **kwargs)

    def autosize_dhw_device(self, **kwargs):
        """Autosize `dhw_device` `nominal_power` to minimum power needed to always meet `dhw_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `dhw_device` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'dhw_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        temperature = self.weather.__getattr__(
            'outdoor_dry_bulb_temperature',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )

        if isinstance(self.dhw_device, HeatPump):
            self.dhw_device.nominal_power = self.dhw_device.autosize(temperature, heating_demand=demand, **kwargs)

        else:
            self.dhw_device.nominal_power = self.dhw_device.autosize(demand, **kwargs)

    def autosize_cooling_storage(self, **kwargs):
        """Autosize `cooling_storage` `capacity` to minimum capacity needed to always meet `cooling_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `cooling_storage` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'cooling_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        self.cooling_storage.capacity = self.cooling_storage.autosize(demand, **kwargs)

    def autosize_heating_storage(self, **kwargs):
        """Autosize `heating_storage` `capacity` to minimum capacity needed to always meet `heating_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `heating_storage` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'heating_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        self.heating_storage.capacity = self.heating_storage.autosize(demand, **kwargs)

    def autosize_dhw_storage(self, **kwargs):
        """Autosize `dhw_storage` `capacity` to minimum capacity needed to always meet `dhw_demand`.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `dhw_storage` `autosize` function.
        """

        demand = self.energy_simulation.__getattr__(
            'dhw_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        self.dhw_storage.capacity = self.dhw_storage.autosize(demand, **kwargs)

    def autosize_electrical_storage(self, **kwargs):
        """Autosize `electrical_storage` `capacity`, `nominal_power`, `depth_of_discharge`, `efficiency`, 
        `loss_coefficient`, and `capacity_loss_coefficient` to meet an estimated average peak demand.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `electrical_storage` `autosize` function.
        """

        demand = pd.DataFrame(self._estimate_baseline_electricity_consumption(), columns=['value'])
        demand['day'] = (demand.index / (self.seconds_per_time_step * 24 / self.seconds_per_time_step)).astype(int)
        demand = demand.groupby('day')['value'].max().mean()

        self.electrical_storage.capacity, \
            self.electrical_storage.nominal_power, \
                self.electrical_storage.depth_of_discharge, \
                    self.electrical_storage.efficiency, \
                        self.electrical_storage.loss_coefficient, \
                            self.electrical_storage.capacity_loss_coefficient = self.electrical_storage.autosize(demand, **kwargs)

    def autosize_pv(self, **kwargs):
        """Autosize `pv` `nominal_power` and set `energy_simulation.solar_generation` using sampled PV data from
        LBNL's Tracking The Sun dataset.
        
        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments parsed to `electrical_storage` `autosize` function.
        """

        demand = pd.DataFrame(self._estimate_baseline_electricity_consumption(), columns=['value'])
        demand['year'] = (demand.index / (self.seconds_per_time_step * 24 * 365 / self.seconds_per_time_step)).astype(int)
        demand = demand.groupby('year')['value'].sum().mean()
        epw_filepath = kwargs.pop('epw_filepath')
        self.pv.nominal_power, solar_generation = self.pv.autosize(demand, epw_filepath, **kwargs)
        self.pv.generation_mode = 'per_kw'
        self.energy_simulation.__setattr__('solar_generation', np.array(solar_generation, dtype='float32'))

    def _estimate_baseline_electricity_consumption(self) -> np.ndarray:
        """Returns estimated baseline electricity consumption time series for entire simulation period.
        
        The estimate is the sum of estimated cooling, heating, domestic hot water and non-shiftable 
        load consumption without storage and self-generation flexibility.

        Returns
        -------
        baseline_electricity_consumption: np.ndarray
            Estimate time series for simulation period which may be equal to or longer than the current
            episode's number of time steps.
        """

        cooling_demand = self.energy_simulation.__getattr__(
            'cooling_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        heating_demand = self.energy_simulation.__getattr__(
            'heating_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        dhw_demand = self.energy_simulation.__getattr__(
            'dhw_demand',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        non_shiftable_electricity_consumption = self.energy_simulation.__getattr__(
            'non_shiftable_load',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        outdoor_dry_bulb_temperature = self.weather.__getattr__(
            'outdoor_dry_bulb_temperature',
            start_time_step=self.episode_tracker.simulation_start_time_step,
            end_time_step=self.episode_tracker.simulation_end_time_step
        )
        cooling_electricity_consumption = self.cooling_device.get_input_power(cooling_demand, outdoor_dry_bulb_temperature, heating=False)

        if isinstance(self.heating_device, HeatPump):
            heating_electricity_consumption = self.heating_device.get_input_power(heating_demand, outdoor_dry_bulb_temperature, heating=True)

        else:
            heating_electricity_consumption = self.heating_device.get_input_power(heating_demand)

        if isinstance(self.dhw_device, HeatPump):
            dhw_electricity_consumption = self.dhw_device.get_input_power(dhw_demand, outdoor_dry_bulb_temperature, heating=True)

        else:
            dhw_electricity_consumption = self.dhw_device.get_input_power(dhw_demand)

        electricity_consumption = cooling_electricity_consumption \
            + heating_electricity_consumption \
                + dhw_electricity_consumption \
                    + non_shiftable_electricity_consumption

        return electricity_consumption

    def next_time_step(self):
        r"""Advance all energy storage and electric devices and, PV to next `time_step`."""

        self.cooling_device.next_time_step()
        self.heating_device.next_time_step()
        self.dhw_device.next_time_step()
        self.non_shiftable_load_device.next_time_step()
        self.cooling_storage.next_time_step()
        self.heating_storage.next_time_step()
        self.dhw_storage.next_time_step()
        self.electrical_storage.next_time_step()
        self.pv.next_time_step()


        if self.electric_vehicle_chargers is not None:
            for c in self.electric_vehicle_chargers:
                c.next_time_step()

        for appliance in self.deferrable_appliances or []:
            appliance.next_time_step()

        for escalator in self.escalators or []:
            escalator.next_time_step()

        super().next_time_step()

    def reset(self):
        r"""Reset `Building` to initial state."""

        # object reset
        super().reset()
        self._archived_storage_electricity = None
        self.cooling_storage.reset()
        self.heating_storage.reset()
        self.dhw_storage.reset()
        self.electrical_storage.reset()
        self.cooling_device.reset()
        self.heating_device.reset()
        self.dhw_device.reset()
        self.non_shiftable_load_device.reset()
        self.pv.reset()

        if self.electric_vehicle_chargers is not None:
            for c in self.electric_vehicle_chargers:
                c.reset()
        else:
            pass

        for appliance in self.deferrable_appliances or []:
            appliance.reset()

        for escalator in self.escalators or []:
            escalator.reset()

        # variable reset
        self.reset_dynamic_variables()
        self.reset_data_sets()
        self._refresh_observation_source_cache()
        self.__solar_generation = self._pv_generation_to_control_step(self.energy_simulation.solar_generation) * -1
        self.__energy_from_cooling_device = self.energy_simulation.cooling_demand.copy()
        self.__energy_from_heating_device = self.energy_simulation.heating_demand.copy()
        self.__energy_from_dhw_device = self.energy_simulation.dhw_demand.copy()
        self.__energy_to_non_shiftable_load = self.energy_simulation.non_shiftable_load.copy()
        self.__pv_curtailment = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__net_electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__net_electricity_consumption_emission = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__net_electricity_consumption_cost = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__power_outage_signal = self.reset_power_outage_signal()
        self.__chargers_electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__deferrable_appliances_electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__escalators_electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_electrical_storage_requested_action_normalized = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_electrical_storage_limited_action_normalized = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_electrical_storage_requested_power_kw = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_electrical_storage_limited_power_kw = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
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
                f'action_feedback_electrical_storage_clip_reason_{reason}',
                np.zeros(self.episode_tracker.episode_time_steps, dtype=bool),
            )
        self._set_default_charging_headroom()
        self._reset_charging_constraint_histories()

    def reset_power_outage_signal(self) -> np.ndarray:
        """Resets power outage signal time series.
        
        Resets to zeros if `simulate_power_outage` is `False` otherwise, resets to a stochastic time series 
        if `stochastic_power_outage` is `True` or the  time series defined in `energy_simulation.power_outage`.

        Returns
        -------
        power_outage_signal: np.ndarray
            Power outage signal time series.
        """

        power_outage_signal = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')

        if self.simulate_power_outage:
            if self.stochastic_power_outage:
                power_outage_signal = self.stochastic_power_outage_model.get_signals(
                    self.episode_tracker.episode_time_steps,
                    seconds_per_time_step=self.seconds_per_time_step,
                    weather=self.weather
                )

            else:
                power_outage_signal = self.energy_simulation.power_outage.copy()

        else:
            pass

        return power_outage_signal

    def reset_dynamic_variables(self):
        """Resets data file variables that change during control to their initial values."""

        pass

    def reset_data_sets(self):
        """Resets time series data `start_time_step` and `end_time_step` with respect to current episode's time step settings."""

        start_time_step = self.episode_tracker.episode_start_time_step
        end_time_step = self.episode_tracker.episode_end_time_step

        def set_data_window(data, default_start, default_end):
            offset = int(getattr(data, 'time_step_offset', 0) or 0)
            data.start_time_step = default_start - offset
            data.end_time_step = default_end - offset

        set_data_window(self.energy_simulation, start_time_step, end_time_step)
        set_data_window(self.weather, start_time_step, end_time_step)
        set_data_window(self.pricing, start_time_step, end_time_step)
        set_data_window(self.carbon_intensity, start_time_step, end_time_step)

        for charger in self.electric_vehicle_chargers or []:
            set_data_window(charger.charger_simulation, start_time_step, end_time_step)

        for escalator in self.escalators or []:
            set_data_window(escalator.escalator_simulation, start_time_step, end_time_step)

        # Deferrable appliance schedules use global time-step indices and are sparse,
        # so no dense data-window adjustment is needed here.

    def update_variables(self):
        """Update cooling, heating, dhw and net electricity consumption as well as net electricity consumption cost and carbon emissions."""

        if self.time_step == 0:
            temperature = self.weather.outdoor_dry_bulb_temperature[self.time_step]

            # cooling electricity consumption
            cooling_demand = self._dataset_energy_to_control_step(
                self.__energy_from_cooling_device[self.time_step]
            ) + self.cooling_storage.energy_balance[self.time_step]
            cooling_electricity_consumption = self.cooling_device.get_input_power(cooling_demand, temperature, heating=False)
            self.cooling_device.set_electricity_consumption(cooling_electricity_consumption)

            # heating electricity consumption
            heating_demand = self._dataset_energy_to_control_step(
                self.__energy_from_heating_device[self.time_step]
            ) + self.heating_storage.energy_balance[self.time_step]

            if isinstance(self.heating_device, HeatPump):
                heating_electricity_consumption = self.heating_device.get_input_power(heating_demand, temperature, heating=True)
            else:
                heating_electricity_consumption = self.heating_device.get_input_power(heating_demand)

            self.heating_device.set_electricity_consumption(heating_electricity_consumption)

            # dhw electricity consumption
            dhw_demand = self._dataset_energy_to_control_step(
                self.__energy_from_dhw_device[self.time_step]
            ) + self.dhw_storage.energy_balance[self.time_step]

            if isinstance(self.dhw_device, HeatPump):
                dhw_electricity_consumption = self.dhw_device.get_input_power(dhw_demand, temperature, heating=True)
            else:
                dhw_electricity_consumption = self.dhw_device.get_input_power(dhw_demand)

            self.dhw_device.set_electricity_consumption(dhw_electricity_consumption)

            # non shiftable load electricity consumption
            non_shiftable_load_electricity_consumption = self._dataset_energy_to_control_step(
                self.__energy_to_non_shiftable_load[self.time_step]
            )
            self.non_shiftable_load_device.set_electricity_consumption(non_shiftable_load_electricity_consumption)
            self._clip_outage_electric_loads_to_local_supply()

            # electrical storage
            # NOTE:
            # `Battery.charge(...)` already updates electrical storage electricity consumption
            # at the current control step. Re-applying it here causes double counting at t=0.
            # Keep this branch intentionally no-op for electrical storage to preserve a single
            # source of truth in the storage model update path.

        else:
            pass

        building_chargers_total_electricity_consumption = 0

        if self.electric_vehicle_chargers is not None:

            for c in self.electric_vehicle_chargers:
                # include charger electricity consumption for current timestep
                building_chargers_total_electricity_consumption = (
                    building_chargers_total_electricity_consumption + c.electricity_consumption[self.time_step]
                )
        else:
            pass

        self.__chargers_electricity_consumption[self.time_step] = building_chargers_total_electricity_consumption

        building_deferrable_appliances_total_electricity_consumption = 0.0
        for appliance in self.deferrable_appliances or []:
            building_deferrable_appliances_total_electricity_consumption += appliance.electricity_consumption[self.time_step]

        self.__deferrable_appliances_electricity_consumption[self.time_step] = building_deferrable_appliances_total_electricity_consumption

        building_escalators_total_electricity_consumption = 0.0
        for escalator in self.escalators or []:
            building_escalators_total_electricity_consumption += escalator.electricity_consumption[self.time_step]

        self.__escalators_electricity_consumption[self.time_step] = building_escalators_total_electricity_consumption

        # A disconnected surplus is curtailed, not useful consumption. Keep
        # available PV unchanged and report the rejected energy explicitly.
        served = (self.cooling_device.electricity_consumption[self.time_step]
                  + self.heating_device.electricity_consumption[self.time_step]
                  + self.dhw_device.electricity_consumption[self.time_step]
                  + self.non_shiftable_load_device.electricity_consumption[self.time_step]
                  + self.electrical_storage.electricity_consumption[self.time_step]
                  + self.__chargers_electricity_consumption[self.time_step]
                  + self.__deferrable_appliances_electricity_consumption[self.time_step]
                  + self.__escalators_electricity_consumption[self.time_step])
        self.__pv_curtailment[self.time_step] = max(-self.solar_generation[self.time_step] - served, 0.0) if self.power_outage else 0.0

        # net electricity consumption
        net_electricity_consumption = 0.0

        if not self.power_outage:
            net_electricity_consumption = self.cooling_device.electricity_consumption[self.time_step] \
                                          + self.heating_device.electricity_consumption[self.time_step] \
                                            + self.dhw_device.electricity_consumption[self.time_step] \
                                                + self.non_shiftable_load_device.electricity_consumption[self.time_step] \
                                                    + self.electrical_storage.electricity_consumption[self.time_step] \
                                                        + self.solar_generation[self.time_step] \
                                                                + self.__chargers_electricity_consumption[self.time_step] \
                                                                + self.__deferrable_appliances_electricity_consumption[self.time_step] \
                                                                + self.__escalators_electricity_consumption[self.time_step]
        else:
            pass

        self.__net_electricity_consumption[self.time_step] = net_electricity_consumption

        # net electriciy consumption cost
        self.__net_electricity_consumption_cost[self.time_step] = (
            max(net_electricity_consumption, 0.0)
            * self.pricing.electricity_pricing[self.time_step]
        )

        # net electriciy consumption emission
        self.__net_electricity_consumption_emission[self.time_step] = max(0.0, net_electricity_consumption*self.carbon_intensity.carbon_intensity[self.time_step])

    def set_net_electricity_consumption_cost(self, value: float, time_step: int = None):
        """Override net electricity consumption cost at a given time step."""

        idx = self.time_step if time_step is None else int(time_step)
        self.__net_electricity_consumption_cost[idx] = float(value)

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
            "Net Electricity Consumption-kWh": f"{self.net_electricity_consumption[self.time_step]}",
            "Non-shiftable Load-kWh": f"{self.non_shiftable_load[self.time_step]}",
            "Non-shiftable Load Electricity Consumption-kWh": f"{self.non_shiftable_load_electricity_consumption[self.time_step]}",
            "Energy Production from PV-kWh": f"{self.solar_generation[self.time_step]}",
        }

    def render_simulation_end_data(self) -> dict:
        """
        Return a dictionary containing all simulation data across all time steps.
        The returned dictionary is structured with the building name and, for each time step,
        a dictionary with the simulation data, including energy, weather, storage, and device information.

        Returns
        -------
        result : dict
            A JSON-like dictionary with the building name and per-time-step data.
        """
        if not hasattr(self, 'episode_tracker') or self.episode_tracker is None:
            raise AttributeError("Episode tracker is not initialized.")

        num_steps = self.episode_tracker.episode_time_steps  # Total number of time steps in the simulation

        result = {
            'name': self.name,
            'simulation_data': []
        }

        for t in range(num_steps):
            time_step_data = {
                'time_step': t,
                'name': self.name,
                'energy_simulation': {
                    'cooling_demand': self.energy_simulation.cooling_demand[t],
                    'heating_demand': self.energy_simulation.heating_demand[t],
                    'dhw_demand': self.energy_simulation.dhw_demand[t],
                    'solar_generation': self.energy_simulation.solar_generation[t],
                    'indoor_temperature': self.energy_simulation.indoor_dry_bulb_temperature[t],
                    'solar_generation': self.energy_simulation.solar_generation[t]
                },
                'weather': {
                    'outdoor_temperature': self.weather.outdoor_dry_bulb_temperature[t],
                    'direct_solar_irradiance': self.weather.direct_solar_irradiance[t]
                },
                'carbon_intensity': self.carbon_intensity.carbon_intensity[t] if self.carbon_intensity else None,
                'pricing': {
                    'electricity_price': self.pricing.electricity_pricing[t] if self.pricing else None,
                },
                'storage': {
                    'dhw_storage': {
                        'soc': self.dhw_storage.soc[t] if self.dhw_storage else None,
                        'capacity': self.dhw_storage.capacity if self.dhw_storage else None
                    },
                    'cooling_storage': {
                        'soc': self.cooling_storage.soc[t] if self.cooling_storage else None,
                        'capacity': self.cooling_storage.capacity if self.cooling_storage else None
                    },
                    'heating_storage': {
                        'soc': self.heating_storage.soc[t] if self.heating_storage else None,
                        'capacity': self.heating_storage.capacity if self.heating_storage else None
                    },
                    'electrical_storage': {
                        'soc': self.electrical_storage.soc[t] if self.electrical_storage else None,
                        'capacity': self.electrical_storage.capacity if self.electrical_storage else None
                    }
                },
                'devices': {
                    'dhw_device': {
                        'electricity_consumption': self.dhw_device.electricity_consumption[t] if self.dhw_device else None,
                        'nominal_power': self.dhw_device.nominal_power if self.dhw_device else None
                    },
                    'cooling_device': {
                        'electricity_consumption': self.cooling_device.electricity_consumption[t] if self.cooling_device else None,
                        'nominal_power': self.cooling_device.nominal_power if self.cooling_device else None
                    },
                    'heating_device': {
                        'electricity_consumption': self.heating_device.electricity_consumption[t] if self.heating_device else None,
                        'nominal_power': self.heating_device.nominal_power if self.heating_device else None
                    }
                },
                'pv': {
                    'power_generation': self.pv.electricity_consumption[t] if self.pv else None,
                    'nominal_power': self.pv.nominal_power if self.pv else None
                },
                'observations': self.observations(t) if hasattr(self, 'observations') else None
            }

            result['simulation_data'].append(time_step_data)

class DynamicsBuilding(Building):
    r"""Base class for temperature dynamic building.

    Parameters
    ----------
    *args: Any
        Positional arguments in :py:class:`citylearn.building.Building`.
    dynamics: Dynamics
        Indoor dry-bulb temperature dynamics model.
    ignore_dynamics: bool, default: False
        Wether to simulate temperature dynamics at any time step.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize :py:class:`citylearn.building.Building` super class.
    """

    def __init__(self, *args: Any, dynamics: Dynamics, ignore_dynamics: bool = None, **kwargs: Any):
        """Intialize `DynamicsBuilding`"""

        self.dynamics = dynamics
        self.ignore_dynamics = False if ignore_dynamics is None else ignore_dynamics
        super().__init__(*args, **kwargs)

    @property
    def simulate_dynamics(self) -> bool:
        """Whether to predict indoor dry-bulb temperature at current `time_step`."""

        return not self.ignore_dynamics

    @property
    def net_electricity_consumption_emission_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """Carbon dioxide emmission from `net_electricity_consumption_without_storage_and_partial_load_pv` time series, in [kg_co2]."""

        return (
            self.carbon_intensity.carbon_intensity[0:self.time_step + 1]*\
                self.net_electricity_consumption_without_storage_and_partial_load_and_pv).clip(min=0)

    @property
    def net_electricity_consumption_cost_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """net_electricity_consumption_without_storage_and_partial_load_and_pv` cost time series, in [$]."""

        return (
            self.pricing.electricity_pricing[0:self.time_step + 1]
            * np.clip(self.net_electricity_consumption_without_storage_and_partial_load_and_pv, 0.0, None)
        )

    @property
    def net_electricity_consumption_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """Net electricity consumption in the absence of flexibility provided by storage devices, 
        partial load cooling and heating devices and self generation time series, in [kWh]. 
        
        Notes
        -----
        net_electricity_consumption_without_storage_and_partial_load_and_pv = 
        `net_electricity_consumption_without_storage_and_partial_load` - `solar_generation`
        """

        return self.net_electricity_consumption_without_storage_and_partial_load - self.solar_generation

    @property
    def net_electricity_consumption_emission_without_storage_and_partial_load(self) -> np.ndarray:
        """Carbon dioxide emmission from `net_electricity_consumption_without_storage_and_partial_load` time series, in [kg_co2]."""

        return (
            self.carbon_intensity.carbon_intensity[0:self.time_step + 1]\
                *self.net_electricity_consumption_without_storage_and_partial_load).clip(min=0)

    @property
    def net_electricity_consumption_cost_without_storage_and_partial_load(self) -> np.ndarray:
        """`net_electricity_consumption_without_storage_and_partial_load` cost time series, in [$]."""

        return (
            self.pricing.electricity_pricing[0:self.time_step + 1]
            * np.clip(self.net_electricity_consumption_without_storage_and_partial_load, 0.0, None)
        )

    @property
    def net_electricity_consumption_without_storage_and_partial_load(self):
        """Net electricity consumption in the absence of flexibility provided by 
        storage devices and partial load cooling and heating devices time series, in [kWh]."""

        # cooling electricity consumption
        cooling_demand_difference = self.cooling_demand_without_partial_load - self.cooling_demand
        cooling_electricity_consumption_difference = self.cooling_device.get_input_power(
            cooling_demand_difference,
            self.weather.outdoor_dry_bulb_temperature[0:self.time_step + 1],
            heating=False
        )

        # heating electricity consumption
        heating_demand_difference = self.heating_demand_without_partial_load - self.heating_demand

        if isinstance(self.heating_device, HeatPump):
            heating_electricity_consumption_difference = self.heating_device.get_input_power(
                heating_demand_difference,
                self.weather.outdoor_dry_bulb_temperature[self.time_step],
                heating=True
            )
        else:
            heating_electricity_consumption_difference = self.dhw_device.get_input_power(heating_demand_difference)

        # net electricity consumption without storage and partial load
        return self.net_electricity_consumption_without_storage + np.sum([
            cooling_electricity_consumption_difference,
            heating_electricity_consumption_difference,
        ], axis=0)

    @property
    def heating_demand_without_partial_load(self) -> np.ndarray:
        """Total building space ideal heating demand time series in [kWh].
        
        This is the demand when heating_device is not controlled and always supplies ideal load.
        """

        return self.energy_simulation.heating_demand_without_control[0:self.time_step + 1]

    @property
    def cooling_demand_without_partial_load(self) -> np.ndarray:
        """Total building space ideal cooling demand time series in [kWh].
        
        This is the demand when cooling_device is not controlled and always supplies ideal load.
        """

        return self.energy_simulation.cooling_demand_without_control[0:self.time_step + 1]

    @property
    def indoor_dry_bulb_temperature_without_partial_load(self) -> np.ndarray:
        """Ideal load dry bulb temperature time series in [C].
        
        This is the temperature when cooling_device and heating_device
        are not controlled and always supply ideal load.
        """

        return self.energy_simulation.indoor_dry_bulb_temperature_without_control[0:self.time_step + 1]

    def apply_actions(self, **kwargs):
        super().apply_actions(**kwargs)
        self._update_dynamics_input()

        if self.simulate_dynamics:
            self.update_indoor_dry_bulb_temperature()
        else:
            pass

    def update_indoor_dry_bulb_temperature(self):
        raise NotImplementedError

    def get_dynamics_input(self):
        raise NotImplementedError

    def _update_dynamics_input(self):
        raise NotImplementedError

    def reset_dynamic_variables(self):
        """Resets data file variables that change during control to their initial values.
        
        Resets cooling demand, heating deamand and indoor temperature time series to their initial value 
        at the beginning of an episode.
        """

        start_ix = 0
        end_ix = self.episode_tracker.episode_time_steps
        self.energy_simulation.cooling_demand[
        start_ix:end_ix] = self.energy_simulation.cooling_demand_without_control.copy()[start_ix:end_ix]
        self.energy_simulation.heating_demand[
        start_ix:end_ix] = self.energy_simulation.heating_demand_without_control.copy()[start_ix:end_ix]
        self.energy_simulation.indoor_dry_bulb_temperature[
        start_ix:end_ix] = self.energy_simulation.indoor_dry_bulb_temperature_without_control.copy()[start_ix:end_ix]

    def reset(self):
        """Reset Building to initial state and resets `dynamics`."""

        super().reset()
        self.dynamics.reset()


class LSTMDynamicsBuilding(DynamicsBuilding):
    r"""Class for building with LSTM temperature dynamics model.

    Parameters
    ----------
    *args: Any
        Positional arguments in :py:class:`citylearn.building.Building`.
    dynamics: Dynamics
        Indoor dry-bulb temperature dynamics model.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize :py:class:`citylearn.building.Building` super class.
    """

    def __init__(self, *args, dynamics: LSTMDynamics, **kwargs):
        super().__init__(*args, dynamics=dynamics, **kwargs)
        self.dynamics: LSTMDynamics

    @DynamicsBuilding.simulate_dynamics.getter
    def simulate_dynamics(self) -> bool:
        return super().simulate_dynamics and self.dynamics._model_input[0][0] is not None

    def update_indoor_dry_bulb_temperature(self):
        """Predict and update indoor dry-bulb temperature for current `time_step`.

        This method will first apply min-max normalization to the model input data where the input data
        is made up of building and district level observations including the predicted 
        :py:attr:`citylearn.building.Building.energy_simulation.indoor_dry_bulb_temperature` 
        with all input variables having a length of :py:attr:`citylearn.dynamics.LSTMDynamics.lookback`.
        asides the `indoor_dry_bulb_temperature` whose input includes all values from
        `time_step` - (`lookback` + 1) to `time_step` - 1, other input variables have values from
        `time_step` - `lookback` to `time_step`. The `indoor_dry_bulb_temperature` for the current `time_step`
        is then predicted using the input data and current `hidden_state` and the predicted values replaces the
        current `time_step` value in :py:attr:`citylearn.building.Building.energy_simulation.indoor_dry_bulb_temperature`.

        Notes
        -----
        LSTM model only uses either cooling/heating demand not both as input variable. 
        Use :py:attr:`citylearn.building.Building.energy_simulation.hvac_mode` to specify whether to consider cooling 
        or heating demand at each `time_step`.
        """

        if torch is None:
            raise ImportError('torch is required to use LSTMDynamicsBuilding.')

        # predict
        model_input_tensor = torch.tensor(self.get_dynamics_input().T)
        model_input_tensor = model_input_tensor[np.newaxis, :, :]
        hidden_state = tuple([h.data for h in self.dynamics._hidden_state])
        indoor_dry_bulb_temperature_norm, self.dynamics._hidden_state = self.dynamics(model_input_tensor.float(), hidden_state)

        # update dry bulb temperature for current time step in model input
        ix = self.dynamics.input_observation_names.index('indoor_dry_bulb_temperature')
        self.dynamics._model_input[ix][-1] = indoor_dry_bulb_temperature_norm.item()

        # unnormalize temperature
        low_limit, high_limit = self.dynamics.input_normalization_minimum[ix], self.dynamics.input_normalization_maximum[ix]
        indoor_dry_bulb_temperature = indoor_dry_bulb_temperature_norm*(high_limit - low_limit) + low_limit
        
        # update temperature
        # this function is called after advancing to next timestep 
        # so the cooling demand update and this temperature update are set at the same time step
        self.energy_simulation.indoor_dry_bulb_temperature[self.time_step] = indoor_dry_bulb_temperature.item()

    def get_dynamics_input(self) -> np.ndarray:
        model_input = []

        for i, k in enumerate(self.dynamics.input_observation_names):
            if k == 'indoor_dry_bulb_temperature':
                # indoor temperature values are t = (t - lookback - 1) : t = (t - 1)
                #  i.e. use samples from previous time step to current time step
                model_input.append(self.dynamics._model_input[i][:-1])

            else:
                # other values are t = (t - lookback) : t = (t)
                #  i.e. use samples from previous time step to current time step
                model_input.append(self.dynamics._model_input[i][1:])

        model_input = np.array(model_input, dtype='float32')

        return model_input

    def _update_dynamics_input(self):
        """Updates and returns the input time series for the dynmaics prediction model.

        Updates the model input with the input variables for the current time step. 
        The variables in the input will have length of lookback + 1.
        """

        # get relevant observations for the current time step
        observations = self.observations(include_all=True, normalize=False, periodic_normalization=True)

        # append current time step observations to model input
        # leave out the oldest set of observations and keep only the previous n
        # where n is the lookback + 1 (to include current time step observations)
        self.dynamics._model_input = [
            l[-self.dynamics.lookback:] + [(observations[k] - min_) / (max_ - min_)]
            for l, k, min_, max_ in zip(
                self.dynamics._model_input,
                self.dynamics.input_observation_names,
                self.dynamics.input_normalization_minimum,
                self.dynamics.input_normalization_maximum
            )
        ]

    def update_cooling_demand(self, action: float):
        """Update space cooling demand for current time step.

        Sets the value of :py:attr:`citylearn.building.Building.energy_simulation.cooling_demand` for the current `time_step` to
        the ouput energy of the cooling device where the proportion of its nominal power made available is defined by `action`.
        If :py:attr:`citylearn.building.Building.energy_simulation.hvac_mode` at the next time step is = 0, i.e., off, or = 1, 
        i.e. cooling mode, the demand is set to 0.

        Parameters
        ----------
        action: float
            Proportion of cooling device nominal power that is made available.

        Notes
        -----
        Will only start controlling the heat pump when there are enough observations fo the LSTM lookback until then, maintains
        ideal load. This will imply that the agent does not learn anything in the initial timesteps that are less than the
        lookback. Taking this approach as a 'warm-up' because realistically, there will be no preceding observations to use in 
        lookback.
        """

        # only start controlling the heat pump when there are enough observations fo the LSTM lookback
        # until then, maintain ideal load. This will imply that the agent does not learn anything in the
        # initial timesteps that are less than the lookback. How does this affect learning longterm?
        # Taking this approach as a 'warm-up' because realistically, there will be no preceding observations
        # to use in lookback. Alternatively, one can use the rolled observation values at the end of the time series
        # but it complicates things and is not too realistic.

        if ('cooling_device' in self.active_actions or 'cooling_or_heating_device' in self.active_actions) and self.simulate_dynamics:
            if self.energy_simulation.hvac_mode[self.time_step] in [1, 3]:
                electric_power = action * self.cooling_device.nominal_power * self.algorithm_action_based_time_step_hours_ratio
                demand = self.cooling_device.get_max_output_power(
                    self.weather.outdoor_dry_bulb_temperature[self.time_step],
                    heating=False,
                    max_electric_power=electric_power
                )
            else:
                demand = 0.0

            self.energy_simulation.cooling_demand[self.time_step] = demand
        else:
            pass

    def update_heating_demand(self, action: float):
        """Update space heating demand for current time step.

        Sets the value of :py:attr:`citylearn.building.Building.energy_simulation.heating_demand` for the current `time_step` to
        the ouput energy of the heating device where the proportion of its nominal power made available is defined by `action`.
        If :py:attr:`citylearn.building.Building.energy_simulation.hvac_mode` at the next time step is = 0, i.e., off, or = 1, 
        i.e. cooling mode, the demand is set to 0.

        Parameters
        ----------
        action: float
            Proportion of heating device nominal power that is made available.

        Notes
        -----
        Will only start controlling the heat pump when there are enough observations fo the LSTM lookback until then, maintains
        ideal load. This will imply that the agent does not learn anything in the initial timesteps that are less than the
        lookback. Taking this approach as a 'warm-up' because realistically, there will be no preceding observations to use in 
        lookback.
        """
        
        if ('heating_device' in self.active_actions or 'cooling_or_heating_device' in self.active_actions) and self.simulate_dynamics:
            if self.energy_simulation.hvac_mode[self.time_step] in [2, 3]:
                electric_power = action * self.heating_device.nominal_power
                demand = self.heating_device.get_max_output_power(
                    self.weather.outdoor_dry_bulb_temperature[self.time_step],
                    heating=True,
                    max_electric_power=electric_power
                ) if isinstance(self.heating_device, HeatPump) else self.heating_device.get_max_output_power(max_electric_power=electric_power)
            else:
                demand = 0.0

            self.energy_simulation.heating_demand[self.time_step] = demand

        else:
            pass

class OccupantInteractionBuilding(DynamicsBuilding):
    r"""Base class for temperature dynamic and occupant interaction building.

    Parameters
    ----------
    *args: Any
        Positional arguments in :py:class:`citylearn.building.Building`.
    occupant: Occupant
        Occupant thermostat interaction model.
    ignore_occupant: bool, default: False
        Wether to ignore occupant interaction.

    Other Parameters
    ----------------
    **kwargs : Any
        Other keyword arguments used to initialize :py:class:`citylearn.building.Building` super class.
    """

    def __init__(self, *args: Any, occupant: Occupant = None, ignore_occupant: bool = None, **kwargs: Any):
        """Intialize `OccupantInteractionBuilding`"""

        self.occupant = occupant
        self.ignore_occupant = False if ignore_occupant is None else ignore_occupant
        super().__init__(*args, **kwargs)
    
    @DynamicsBuilding.episode_tracker.setter
    def episode_tracker(self, episode_tracker: EpisodeTracker):
        DynamicsBuilding.episode_tracker.fset(self, episode_tracker)
        self.occupant.episode_tracker = episode_tracker

    @DynamicsBuilding.random_seed.setter
    def random_seed(self, seed: int):
        DynamicsBuilding.random_seed.fset(self, seed)
        self.occupant.random_seed = self.random_seed
    
    def apply_actions(self, **kwargs):
        super().apply_actions(**kwargs)

        if self.simulate_dynamics:
            self.update_set_points()
        
        else:
            pass

    def update_set_points(self):
        """Update building indoor temperature dry-bulb temperature, humidity, etc setpoint using occupant interaction model."""

        raise NotImplementedError
    
    def reset_dynamic_variables(self):
        """Resets data file variables that change during control to their initial values.
        
        Resets cooling demand, heating deamand and indoor temperature time series to their initial value 
        at the beginning of an episode.
        """

        start_ix = 0
        end_ix = self.episode_tracker.episode_time_steps
        self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[start_ix:end_ix] = self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point_without_control.copy()[start_ix:end_ix]
        self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[start_ix:end_ix] = self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point_without_control.copy()[start_ix:end_ix]

    def next_time_step(self):
        super().next_time_step()
        self.occupant.next_time_step()
        
    def reset(self):
        """Reset Building to initial state and resets `dynamics` and `occupant`."""

        super().reset()
        self.occupant.reset()

class LogisticRegressionOccupantInteractionBuilding(OccupantInteractionBuilding, LSTMDynamicsBuilding):
    def __init__(self, *args, occupant: LogisticRegressionOccupant = None, set_point_hold_time_steps: int = None, **kwargs):
        super().__init__(*args, occupant=occupant, **kwargs)
        self.occupant: LogisticRegressionOccupant
        self.__set_point_hold_time_step_counter = None
        self.set_point_hold_time_steps = set_point_hold_time_steps
        self.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta_summary = []
        
    @property
    def set_point_hold_time_steps(self) -> int:
        return self.__set_point_hold_time_steps
    
    @set_point_hold_time_steps.setter
    def set_point_hold_time_steps(self, value: int):
        assert value is None or value >= 0, 'set_point_hold_time_steps must be >= 0'
        self.__set_point_hold_time_steps = np.inf if value is None else int(value)

    def update_set_points(self):
        current_cooling_set_point = self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[self.time_step]
        previous_cooling_set_point = self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[self.time_step - 1]
        current_heating_set_point = self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[self.time_step]
        previous_heating_set_point = self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[self.time_step - 1]
        hvac_mode = self.energy_simulation.hvac_mode[self.time_step]

        if hvac_mode == 1:
            current_set_point = current_cooling_set_point
            previous_set_point = previous_cooling_set_point

        elif hvac_mode == 2:
            current_set_point = current_heating_set_point
            previous_set_point = previous_heating_set_point

        elif hvac_mode == 3:
            raise NotImplementedError(
                'Setpoint update not implemented for auto hvac mode.' 
                ' Set hvac_mode in citylearn.Building.energy_simulation to 0 (off), 1 (cooling mode) or 2 (heating mode).'
            )
        
        else:
            pass

        current_temperature = self.energy_simulation.indoor_dry_bulb_temperature[self.time_step]
        previous_temperature = self.energy_simulation.indoor_dry_bulb_temperature[self.time_step - 1]
        interaction_input = current_temperature
        delta_input = [[current_set_point, previous_set_point, previous_temperature - previous_set_point]]
        model_input = (interaction_input, delta_input) 
        setpoint_delta = self.occupant.predict(x=model_input)
        self.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta[self.time_step] = setpoint_delta

        if abs(setpoint_delta) > 0.0 and not self.ignore_occupant:
            if hvac_mode == 1:
                self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[self.time_step:] = current_set_point + setpoint_delta

            elif hvac_mode == 2:
                self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[self.time_step:] = current_set_point + setpoint_delta
            
            else:
                pass

            self.__set_point_hold_time_step_counter = self.set_point_hold_time_steps

        elif self.__set_point_hold_time_step_counter is None:
            pass

        else:
            self.__set_point_hold_time_step_counter -= 1
        
        # revert back to default setpoint schedule if no occupant interaction in defined window
        if self.__set_point_hold_time_step_counter is not None and self.__set_point_hold_time_step_counter == 0:
            self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[self.time_step + 1:] \
                = self.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point_without_control[self.time_step + 1:]
            self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[self.time_step + 1:] \
                = self.energy_simulation.indoor_dry_bulb_temperature_heating_set_point_without_control[self.time_step + 1:]
            self.__set_point_hold_time_step_counter = None

        else:
            pass

    def _get_observations_data(self, include_all: bool = False) -> Mapping[str, Union[float, int]]:
        return {
            **super()._get_observations_data(include_all=include_all),
            **{
                k.lstrip('_'): self.occupant.parameters.__getattr__(k.lstrip('_'))[self.time_step] 
                for k, v in vars(self.occupant.parameters).items() if isinstance(v, np.ndarray)
            }
        }

    def _get_observation_space_limits_data(self) -> Mapping[str, List[Union[float, int]]]:
        data = {
            **super()._get_observation_space_limits_data(),
            **{k.lstrip('_'): self.occupant.parameters.__getattr__(
                k.lstrip('_'), 
                start_time_step=self.episode_tracker.simulation_start_time_step, 
                end_time_step=self.episode_tracker.simulation_end_time_step
            ) for k in vars(self.occupant.parameters)},
        }

        # hacky way to set the limits for the occupant setpoint change delta
        delta = max(list(self.occupant.delta_output_map.values()))
        data['occupant_interaction_indoor_dry_bulb_temperature_set_point_delta'][0] = delta
        data['occupant_interaction_indoor_dry_bulb_temperature_set_point_delta'][-1] = -delta

        return data

    def reset_data_sets(self):
        super().reset_data_sets()
        start_time_step = self.episode_tracker.episode_start_time_step
        end_time_step = self.episode_tracker.episode_end_time_step
        self.occupant.parameters.start_time_step = start_time_step
        self.occupant.parameters.end_time_step = end_time_step

    def reset_dynamic_variables(self):
        super().reset_dynamic_variables()
        start_ix = 0
        end_ix = self.episode_tracker.episode_time_steps
        delta_summary = np.unique(self.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta[start_ix:end_ix], return_counts=True)
        self.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta_summary.append([delta_summary[0].tolist(), delta_summary[1].tolist()])
        self.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta[start_ix:end_ix] =\
            self.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta_without_control.copy()[start_ix:end_ix]

    def reset(self):
        super().reset()
        self.__set_point_hold_time_step_counter = None
