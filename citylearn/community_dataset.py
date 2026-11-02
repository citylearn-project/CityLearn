"""Explicit physical and economic contracts for inventory-derived datasets.

Legacy schemas are unchanged. Prices are EUR/kWh and timeseries are indexed by
absolute dataset time, including an episode's start offset.
"""
import math
from pathlib import Path
import numpy as np
import pandas as pd
from citylearn.energy_model import Battery
from citylearn.building import Building


class InventoryBuilding(Building):
    """Versioned loader for inventory scenarios; older runtimes fail explicitly."""


class InventoryEVBuilding(InventoryBuilding):
    """Requires the EV battery loader contract introduced in version 1.8.2."""


class RuntimeEVBuilding(InventoryEVBuilding):
    """Runtime EV datasets require arrival observations fixed in version 1.8.3."""


class InventoryBattery(Battery):
    """Battery with declared asymmetric powers, SOC range and efficiencies."""
    def __init__(self, max_charge_kw, max_discharge_kw, min_soc=0.0, max_soc=1.0,
                 charging_efficiency=1.0, discharging_efficiency=1.0, **kwargs):
        values = [max_charge_kw, max_discharge_kw, min_soc, max_soc,
                  charging_efficiency, discharging_efficiency]
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError('Battery parameters must be finite')
        if max_charge_kw <= 0 or max_discharge_kw < 0 or not 0 <= min_soc < max_soc <= 1:
            raise ValueError('Invalid battery power or SOC limits')
        if not 0 < charging_efficiency <= 1 or not 0 < discharging_efficiency <= 1:
            raise ValueError('Battery efficiencies must be in (0, 1]')
        self.max_charge_kw = float(max_charge_kw)
        self.max_discharge_kw = float(max_discharge_kw)
        self.max_soc = float(max_soc)
        self.charging_efficiency = float(charging_efficiency)
        self.discharging_efficiency = float(discharging_efficiency)
        self._charging = True
        kwargs.update(nominal_power=max(max_charge_kw, max_discharge_kw),
                      depth_of_discharge=1.0-min_soc, efficiency=charging_efficiency**2)
        kwargs.setdefault('capacity_power_curve', [[0.0, 1.0], [1.0, 1.0]])
        kwargs.setdefault('power_efficiency_curve', [[0.0, charging_efficiency**2], [1.0, charging_efficiency**2]])
        kwargs.setdefault('capacity_loss_coefficient', 0.0)
        kwargs.setdefault('loss_coefficient', 0.0)
        super().__init__(**kwargs)
        if not min_soc <= self.initial_soc <= max_soc:
            raise ValueError('Initial battery SOC is outside its declared limits')

    def get_max_input_power(self, energy_init=None):
        energy_init = self.energy_init if energy_init is None else energy_init
        headroom = max(0.0, self.capacity*self.max_soc-energy_init)
        return min(self.max_charge_kw, super().get_max_input_power(energy_init),
                   headroom/self.charging_efficiency*3600/self.seconds_per_time_step)

    def get_max_output_power(self, energy_init=None):
        # Call Battery input directly: its output method delegates back to input.
        return min(self.max_discharge_kw, Battery.get_max_input_power(self, energy_init))

    def get_current_efficiency(self, power):
        return (self.charging_efficiency if self._charging else self.discharging_efficiency)**2

    def charge(self, energy):
        self._charging = energy >= 0
        super().charge(energy)

    def get_metadata(self):
        return {**super().get_metadata(), 'max_charge_kw': self.max_charge_kw,
                'max_discharge_kw': self.max_discharge_kw, 'max_soc': self.max_soc,
                'charging_efficiency': self.charging_efficiency,
                'discharging_efficiency': self.discharging_efficiency}


def configure_tariffs(env, config):
    """Load portable per-building tariffs once; invalid explicit data fails closed."""
    env.community_tariffs = {}
    root = Path(env.schema.get('root_directory') or '.').resolve()
    for name, filename in (config.get('tariff_files') or {}).items():
        path = (root/filename).resolve()
        if root not in path.parents:
            raise ValueError('Community tariff files must be inside the dataset')
        frame = pd.read_csv(path)
        required = ['grid_export_price', 'community_buy_price', 'community_sell_price']
        if any(c not in frame for c in required):
            raise ValueError('Community tariff file lacks required columns')
        values = frame[required].to_numpy(dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError('Community tariffs must be finite and nonempty')
        env.community_tariffs[name] = values
    env.community_market_local_enabled = bool(config.get('local_trading_enabled', True))


def settlement_prices(env, name, time_step, grid_import_price):
    tariffs = getattr(env, 'community_tariffs', {}).get(name)
    if tariffs is None:
        local = env.community_market_sell_ratio*grid_import_price
        return float(getattr(env, 'community_market_grid_export_price', 0.0)), local, local
    offset = int(getattr(getattr(env, 'episode_tracker', None), 'episode_start_time_step', 0) or 0)
    index = offset + int(time_step)
    if not 0 <= index < len(tariffs):
        raise ValueError('Community tariff series does not cover this episode')
    return tuple(float(v) for v in tariffs[index])
