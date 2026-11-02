import inspect
from typing import List, Dict, Tuple
import numpy as np
from citylearn.base import Environment, EpisodeTracker
from citylearn.electric_vehicle import ElectricVehicle
from citylearn.data import ChargerSimulation
from citylearn.data import ZERO_DIVISION_PLACEHOLDER
from citylearn.internal.units import (
    normalized_power_action_to_energy_kwh,
    to_dataset_resolution_energy,
)
np.seterr(divide='ignore', invalid='ignore')

class Charger(Environment):
    def __init__(
            self, episode_tracker: EpisodeTracker, charger_simulation: ChargerSimulation ,charger_id: str = None, efficiency: float = None, max_charging_power: float = None,
            min_charging_power: float = None, max_discharging_power: float = None,  min_discharging_power: float = None, charge_efficiency_curve: Dict[float, float] = None,
            discharge_efficiency_curve: Dict[float, float] = None, connected_electric_vehicle: ElectricVehicle = None, incoming_electric_vehicle: ElectricVehicle = None,
            phase_connection: str = None, time_step_ratio: int = None,
            **kwargs
    ):
        r"""Initializes the `Electric Vehicle Charger` class with the given attributes.

        Parameters
        ----------
        charger_id: str
            Id through which the charger is uniquely identified in the system
        max_charging_power : float, default 50
            Maximum charging power in kW.
        min_charging_power : float, default 0
            Minimum charging power in kW.
        max_discharging_power : float, default 50
            Maximum discharging power in kW.
        min_discharging_power : float, default 0
            Minimum discharging power in kW.
        charge_efficiency_curve : List, none [[0, 0.83],[0.3, 0.83],[0.7, 0.9],[0.8, 0.9],[1, 0.85]]
            Efficiency curve for charging containing power levels and corresponding efficiency values.
        discharge_efficiency_curve : List, none [[0, 0.83],[0.3, 0.83],[0.7, 0.9],[0.8, 0.9],[1, 0.85]]
            Efficiency curve for discharging containing power levels and corresponding efficiency values.

        Other Parameters
        ----------------
        **kwargs : dict
            Other keyword arguments used to initialize super classes.
        """

        self.efficiency = efficiency
        self.charger_id = charger_id
        self.max_charging_power = max_charging_power
        self.min_charging_power = min_charging_power
        self.max_discharging_power = max_discharging_power
        self.min_discharging_power = min_discharging_power
        self.charge_efficiency_curve = charge_efficiency_curve
        self.discharge_efficiency_curve = discharge_efficiency_curve
        self.connected_electric_vehicle = connected_electric_vehicle
        self.incoming_electric_vehicle = incoming_electric_vehicle
        self.phase_connection = phase_connection
        self.charger_simulation = charger_simulation

        arg_spec = inspect.getfullargspec(super().__init__)
        kwargs = {
            key: value for (key, value) in kwargs.items()
            if (key in arg_spec.args or (arg_spec.varkw is not None))
        }
        self.time_step_ratio = time_step_ratio
        seconds_per_time_step = kwargs.get('seconds_per_time_step', 3600)
        self.algorithm_action_based_time_step_hours_ratio = seconds_per_time_step / 3600
        super().__init__(episode_tracker=episode_tracker,time_step_ratio=time_step_ratio
                        ,**kwargs)

    @property
    def charger_simulation(self) -> ChargerSimulation:

        return self.__charger_simulation
    
    @property
    def charger_id(self) -> str:
        """ID of the charger."""

        return self.__charger_id

    @property
    def max_charging_power(self) -> float:
        """Maximum charging power in kW."""

        return self.__max_charging_power

    @property
    def min_charging_power(self) -> float:
        """Minimum charging power in kW."""

        return self.__min_charging_power

    @property
    def max_discharging_power(self) -> float:
        """Maximum discharging power in kW."""

        return self.__max_discharging_power

    @property
    def min_discharging_power(self) -> float:
        """Minimum discharging power in kW."""

        return self.__min_discharging_power

    @property
    def charge_efficiency_curve(self) -> dict:
        """Efficiency curve for charging containing power levels and corresponding efficiency values."""

        return self.__charge_efficiency_curve

    @property
    def discharge_efficiency_curve(self) -> dict:
        """Efficiency curve for discharging containing power levels and corresponding efficiency values."""

        return self.__discharge_efficiency_curve

    @property
    def connected_electric_vehicle(self) -> ElectricVehicle:
        """Electric_Vehicle currently connected to charger"""

        return self.__connected_ev

    @property
    def incoming_electric_vehicle(self) -> ElectricVehicle:
        """Electric_Vehicle incoming to charger"""

        return self.__incoming_ev

    @property
    def efficiency(self) -> float:
        """Technical efficiency."""

        return self.__efficiency

    @property
    def phase_connection(self) -> str:
        """Electrical phase connection assignment."""

        return self.__phase_connection


    @property
    def past_connected_evs(self) -> List[ElectricVehicle]:
        r"""Each timestep with the list of Past connected Evs or None in the case no electric_vehicle was connected """

        return self.__past_connected_evs

    @property
    def past_charging_action_values_kwh(self) -> List[float]:
        r"""Actions given to charge/discharge in [kWh]. Different from the electricity consumption as in this an action can be given but no electric_vehicle being connect it will not consume such energy"""

        return self.__past_charging_action_values_kwh

    @property
    def gross_energy_charge(self):
        """Actual AC import before netting opposing calls in an interval."""
        return self.__gross_energy_charge

    @property
    def gross_energy_discharge(self):
        return self.__gross_energy_discharge

    @property
    def electricity_consumption(self) -> List[float]:
        r"""Electricity consumption time series."""

        return self.__electricity_consumption
    
    @property
    def time_step_ratio(self) -> float:
        r"""Electricity consumption time series."""

        return self.__time_step_ratio

    @charger_simulation.setter
    def charger_simulation(self, charger_simulation: ChargerSimulation):
        self.__charger_simulation = charger_simulation

    @charger_id.setter
    def charger_id(self, charger_id: str):
        self.__charger_id = charger_id

    @max_charging_power.setter
    def max_charging_power(self, max_charging_power: float):
            if max_charging_power is None:
                self.__max_charging_power = 50.0
            else:
                self.__max_charging_power = max_charging_power

    @min_charging_power.setter
    def min_charging_power(self, min_charging_power: float):
            if min_charging_power is None:
                self.__min_charging_power = 0.0
            else:
                self.__min_charging_power = min_charging_power

    @max_discharging_power.setter
    def max_discharging_power(self, max_discharging_power: float):
            if max_discharging_power is None:
                self.__max_discharging_power = 50.0
            else:
                self.__max_discharging_power = max_discharging_power

    @min_discharging_power.setter
    def min_discharging_power(self, min_discharging_power: float):
            if min_discharging_power is None:
                self.__min_discharging_power = 0.0
            else:
                self.__min_discharging_power = min_discharging_power

    @charge_efficiency_curve.setter
    def charge_efficiency_curve(self, charge_efficiency_curve: List[List[float]]):
        if charge_efficiency_curve is not None:
            self.__charge_efficiency_curve = np.array(charge_efficiency_curve).T
        else:
            self.__charge_efficiency_curve = None

    @discharge_efficiency_curve.setter
    def discharge_efficiency_curve(self, discharge_efficiency_curve: List[List[float]]):
        if discharge_efficiency_curve is not None:
            self.__discharge_efficiency_curve = np.array(discharge_efficiency_curve).T
        else:
            self.__discharge_efficiency_curve = None

    @connected_electric_vehicle.setter
    def connected_electric_vehicle(self, electric_vehicle: ElectricVehicle):
        self.__connected_ev = electric_vehicle

    @incoming_electric_vehicle.setter
    def incoming_electric_vehicle(self, electric_vehicle: ElectricVehicle):
        self.__incoming_ev = electric_vehicle

    @phase_connection.setter
    def phase_connection(self, phase_connection: str):
        self.__phase_connection = None if phase_connection is None else str(phase_connection)

    @time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: float):
        self.__time_step_ratio = time_step_ratio    

    @efficiency.setter
    def efficiency(self, efficiency: float):
        if efficiency is None:
            self.__efficiency = 1.0
        else:
            assert 0 < efficiency <= 1, 'efficiency must be > 0.'
            self.__efficiency = efficiency

    def plug_car(self, electric_vehicle: ElectricVehicle):
        """
        Connects a electric_vehicle to the charger.

        Parameters
        ----------
        electric_vehicle : object
            electric_vehicle instance to be connected to the charger.
        """

        if self.connected_electric_vehicle is not None:
            raise ValueError("Charger is already in use.")
        self.connected_electric_vehicle = electric_vehicle
        self.__past_connected_evs[self.time_step] = self.connected_electric_vehicle

    def associate_incoming_car(self, electric_vehicle: ElectricVehicle):
        """
        Associates incoming electric_vehicle to the charger.

        Parameters
        ----------
        electric_vehicle : object
            electric_vehicle instance to be connected to the charger.
        """

        self.incoming_electric_vehicle = electric_vehicle

    def get_efficiency(self, power: float, charging: bool) -> float:
        """
        Returns the efficiency corresponding to a given power level.

        If no efficiency curve is set, returns self.efficiency.
        If a curve is set, interpolates efficiency from the appropriate curve.

        Parameters
        ----------
        power : float
            The charging or discharging power level (normalized between 0 and 1).
        charging : bool
            Whether the power level corresponds to charging (True) or discharging (False).

        Returns
        -------
        float
            The interpolated efficiency at the given power level.
        """
        # Select the correct efficiency curve
        efficiency_curve = self.__charge_efficiency_curve if charging else self.__discharge_efficiency_curve
        # If no curve is set, return default efficiency
        if efficiency_curve is None:
            return self.efficiency  # Default efficiency

        # Ensure efficiency_curve is properly shaped
        assert efficiency_curve.shape[0] == 2, "Efficiency curve must have shape (2, N)."

        power_levels, efficiencies = efficiency_curve  # Unpack rows
        return np.interp(power, power_levels, efficiencies)  # Interpolated efficiency

    @staticmethod
    def _deadband_power_kw(action_value: float, max_power_kw: float, min_power_kw: float) -> float:
        """Return requested power after enforcing charger minimum-power deadband."""

        max_power_kw = max(float(max_power_kw), 0.0)
        min_power_kw = max(min(float(min_power_kw), max_power_kw), 0.0)

        if max_power_kw <= 0.0:
            return 0.0

        requested_power_kw = abs(float(action_value)) * max_power_kw
        # Entity actions are float32. A command exactly at the minimum can
        # round a fraction below it; preserve that valid command without
        # admitting materially sub-minimum requests.
        tolerance_kw = np.finfo(np.float32).eps * max_power_kw
        if requested_power_kw + tolerance_kw < min_power_kw:
            return 0.0

        return min(max(requested_power_kw, min_power_kw), max_power_kw)

    def _signed_power_from_action(self, action_value: float) -> Tuple[float, bool]:
        try:
            action_value = float(np.clip(float(action_value), -1.0, 1.0))
        except (TypeError, ValueError):
            return 0.0, True

        if not np.isfinite(action_value):
            return 0.0, True

        if action_value > 0.0:
            return self._deadband_power_kw(
                action_value,
                self.max_charging_power,
                self.min_charging_power,
            ), True

        if action_value < 0.0:
            return -self._deadband_power_kw(
                action_value,
                self.max_discharging_power,
                self.min_discharging_power,
            ), False

        return 0.0, True

    def get_requested_power_kw(self, action_value: float) -> float:
        """Return the signed charger power request in kW after min-power deadband."""

        signed_power_kw, _ = self._signed_power_from_action(action_value)
        return signed_power_kw

    def update_connected_electric_vehicle_soc(self, action_value: float):
        """
        Updates the SOC of the connected electric vehicle based on the charging/discharging action.

        Parameters
        ----------
        action_value : float
            The normalized charging or discharging action (range [-1, 1]).
        """
        signed_power_kw, charging = self._signed_power_from_action(action_value)

        if signed_power_kw == 0.0:
            # Keep EV SOC state consistent at the current timestep even when no power is requested.
            # Without this, SOC at `time_step` can remain the zero-initialized default.
            if self.connected_electric_vehicle is not None:
                self.connected_electric_vehicle.battery.charge(0.0)
            self.__past_charging_action_values_kwh[self.time_step] = 0
            return

        if charging:
            applied_power_kw = abs(signed_power_kw)
            normalized_power = applied_power_kw / max(self.max_charging_power, ZERO_DIVISION_PLACEHOLDER)
            efficiency = self.get_efficiency(normalized_power, charging)
            commanded_energy_kwh = normalized_power_action_to_energy_kwh(
                normalized_power,
                self.max_charging_power,
                self.seconds_per_time_step,
            )
            battery_energy_kwh = commanded_energy_kwh * efficiency
        else:
            applied_power_kw = abs(signed_power_kw)
            normalized_power = applied_power_kw / max(self.max_discharging_power, ZERO_DIVISION_PLACEHOLDER)
            efficiency = self.get_efficiency(normalized_power, charging)
            commanded_energy_kwh = -normalized_power_action_to_energy_kwh(
                normalized_power,
                self.max_discharging_power,
                self.seconds_per_time_step,
            )
            battery_energy_kwh = commanded_energy_kwh / max(efficiency, ZERO_DIVISION_PLACEHOLDER)

        self.__past_charging_action_values_kwh[self.time_step] = commanded_energy_kwh

        if self.connected_electric_vehicle:
            electric_vehicle = self.connected_electric_vehicle

            # Battery model expects dataset-resolution energy. Convert from control-step kWh when needed.
            ratio = getattr(electric_vehicle.battery, 'time_step_ratio', None)
            battery_command = to_dataset_resolution_energy(battery_energy_kwh, ratio)
            electric_vehicle.battery.charge(battery_command)

            battery_energy_balance = electric_vehicle.battery.energy_balance[self.time_step]
            ac_energy = (
                battery_energy_balance / max(efficiency, ZERO_DIVISION_PLACEHOLDER)
                if battery_energy_balance >= 0 else battery_energy_balance * efficiency
            )
            self.__electricity_consumption[self.time_step] += ac_energy
            self.__gross_energy_charge[self.time_step] += max(float(ac_energy), 0.0)
            self.__gross_energy_discharge[self.time_step] += max(-float(ac_energy), 0.0)
            # Preserve charger losses at the AC boundary for passive provenance.
            events = electric_vehicle.battery.energy_provenance_events
            if events:
                events[-1]['bus'] = float(ac_energy)


    def next_time_step(self):
        r"""Advance to next `time_step`"""

        self.connected_electric_vehicle = None
        self.incoming_electric_vehicle = None
        super().next_time_step()

    def reset(self):
        """
        Resets the Charger to its initial state by disconnecting all electric_vehicles.
        """
        super().reset()
        self.connected_electric_vehicle = None
        self.incoming_electric_vehicle = None
        self.__electricity_consumption = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__gross_energy_charge = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__gross_energy_discharge = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__past_charging_action_values_kwh = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.__past_connected_evs = [None] * self.episode_tracker.episode_time_steps
        self.action_feedback_requested_action_normalized = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_limited_action_normalized = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_requested_power_kw = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
        self.action_feedback_limited_power_kw = np.zeros(self.episode_tracker.episode_time_steps, dtype='float32')
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

    def __str__(self):
        return str(self.as_dict())

    
    def as_dict(self) -> dict:
        """
        Return a dictionary representation of the charger and connected EV data.
        """
        net_consumption = self.electricity_consumption[self.time_step]  # dá sempre 0

        if net_consumption > 0:
            consumption = f"{net_consumption}"
            production = "-1.00"
        else:
            consumption = "-1.00"
            production = f"{abs(net_consumption)}"

        charger_data = {
            "Charger Consumption-kWh": consumption,
            "Charger Production-kWh": production,
            "Incoming EV Name": f"{self.incoming_electric_vehicle.name}" if self.incoming_electric_vehicle else "",
            "Charging Action-kWh": f"{self.past_charging_action_values_kwh[self.time_step]}"
        }

        # Check if EV is connected
        connected_ev = self.connected_electric_vehicle
        incoming_electric_vehicle = self.incoming_electric_vehicle
        if connected_ev:
            ev_data = {
                "EV SOC-%": f"{connected_ev.battery.soc[self.time_step]:.2f}",
                "EV Charger State": self.charger_simulation.electric_vehicle_charger_state[self.time_step],
                "EV Required SOC Departure-%": f"{self.charger_simulation.electric_vehicle_required_soc_departure[self.time_step]}",
                "EV Estimated SOC Arrival-%": f"{self.charger_simulation.electric_vehicle_estimated_soc_arrival[self.time_step]}",
                "EV Arrival Time": f"{self.charger_simulation.electric_vehicle_estimated_arrival_time[self.time_step]}",
                "EV Departure Time": f"{self.charger_simulation.electric_vehicle_departure_time[self.time_step]}",
                "Is EV Connected": True,
                "EV Name": connected_ev.name
            }
        elif incoming_electric_vehicle:
            ev_data = {
                "EV SOC-%": f"{incoming_electric_vehicle.battery.soc[self.time_step]:.2f}",
                "EV Charger State": self.charger_simulation.electric_vehicle_charger_state[self.time_step],
                "EV Required SOC Departure-%": f"{self.charger_simulation.electric_vehicle_required_soc_departure[self.time_step]}",
                "EV Estimated SOC Arrival-%": f"{self.charger_simulation.electric_vehicle_estimated_soc_arrival[self.time_step]}",
                "EV Arrival Time": f"{self.charger_simulation.electric_vehicle_estimated_arrival_time[self.time_step]}",
                "EV Departure Time": f"{self.charger_simulation.electric_vehicle_departure_time[self.time_step]}",
                "Is EV Connected": True,
                "EV Name": incoming_electric_vehicle.name
            }
        else:
            ev_data = {
                "EV SOC": "-1.00",
                "EV Charger State": "-1.00",
                "EV Required SOC Departure-%": "-1.00",
                "EV Estimated SOC Arrival-%": "-1.00",
                "EV Arrival Time": "-1.00",
                "EV Departure Time": "-1.00",
                "Is EV Connected": False,
                "EV Name": ""
            }

        # Merge charger and EV data
        charger_data.update(ev_data)
        return charger_data
    
    def render_simulation_end_data(self) -> dict:
        """
        Return a dictionary containing all simulation data across all time steps.
        The returned dictionary is structured with a general charger name and, for each time step,
        a dictionary with the charger data, EV data (if connected), and electricity consumption.

        Returns
        -------
        result : dict
            A JSON-like dictionary with the charger name and per-time-step data.
        """
        num_steps = self.episode_tracker.episode_time_steps - 1
        
        result = {
            'name': self.charger_id,
            'charger_data': []
        }
        
        for t in range(num_steps):
            time_step_data = {
                'time_step': t,
                'charger_id': self.charger_id,
                'electricity_consumption': self.electricity_consumption[t],
                "Charging Action-kWh": f"{self.past_charging_action_values_kwh[t]}",
                'connected_ev': None,
                'incoming_ev': None
            }
            
            # Include connected EV data if available
            if self.connected_electric_vehicle:
                ev = self.connected_electric_vehicle
                time_step_data['connected_ev'] = {
                    'name': ev.name,
                    'soc': ev.battery.soc[t],
                    'capacity': ev.battery.capacity,
                    'charger_state': ev.electric_vehicle_simulation.electric_vehicle_charger_state[t],
                    'required_soc_departure': ev.electric_vehicle_simulation.electric_vehicle_required_soc_departure[t],
                    'estimated_soc_arrival': ev.electric_vehicle_simulation.electric_vehicle_estimated_soc_arrival[t],
                    'arrival_time': ev.electric_vehicle_simulation.electric_vehicle_estimated_arrival_time[t],
                    'departure_time': ev.electric_vehicle_simulation.electric_vehicle_departure_time[t]
                }
            
            # Include incoming EV data if available
            if self.incoming_electric_vehicle:
                time_step_data['incoming_ev'] = {
                    'name': self.incoming_electric_vehicle.name
                }
            
            result['charger_data'].append(time_step_data)
        
        return result
