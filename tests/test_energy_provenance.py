"""Analytical conservation cases independent of control policies."""
from types import SimpleNamespace as NS
from copy import deepcopy

import numpy as np
import pytest

from citylearn.base import EpisodeTracker
from citylearn.community_dataset import InventoryBattery
from citylearn.internal.provenance import CityLearnProvenanceService, energy
from citylearn.internal.runtime import CityLearnRuntimeService


def battery(initial=0., charge_eta=1., discharge_eta=1., loss=0., seconds=3600):
    tracker = EpisodeTracker(0, 99)
    tracker.next_episode(100, False, False, 0)
    b = InventoryBattery(capacity=10., max_charge_kw=10., max_discharge_kw=10.,
        initial_soc=initial, charging_efficiency=charge_eta, discharging_efficiency=discharge_eta,
        loss_coefficient=loss, seconds_per_time_step=seconds, episode_tracker=tracker, time_step_ratio=1.)
    b.reset()
    return b


class Case:
    def __init__(self, batteries):
        self.batteries = batteries
        self.buildings = [NS(name=f'M{i}', electrical_storage=b, electric_vehicle_chargers=[],
            solar_generation=np.zeros(100), net_electricity_consumption=np.zeros(100),
            carbon_intensity=NS(carbon_intensity=np.full(100, .2))) for i, b in enumerate(batteries)]
        self.env = NS(buildings=self.buildings, time_step=0, community_market_enabled=False,
                      _runtime_service=CityLearnRuntimeService)
        self.ledger = CityLearnProvenanceService(self.env)
        self.ledger.reset()

    def run(self, pv, load, commands):
        t = self.env.time_step
        if t:
            for b in self.batteries:
                b.next_time_step()
        self.ledger.begin_step()
        for i, b in enumerate(self.buildings):
            flows = []
            for command in commands[i]:
                self.batteries[i].charge(command)
                flows.append(self.batteries[i].energy_provenance_events[-1]['bus'])
            b.solar_generation[t] = -pv[i]
            b.net_electricity_consumption[t] = load[i]-pv[i]+sum(flows)
        self.ledger.settle()
        self.env.time_step += 1
        return self.summary()

    def summary(self):
        _, total = self.ledger.summary()
        assert total['pv_balance_residual_kwh'] == pytest.approx(0., abs=5e-6)
        assert total['carbon_balance_residual_kgco2'] == pytest.approx(0., abs=5e-6)
        assert total['storage_max_residual_kwh'] < 5e-6
        assert total['bus_max_residual_kwh'] < 5e-6
        return total


def test_pv_direct_and_delayed_export_are_different_destinations():
    c = Case([battery()])
    r = c.run([10.], [4.], [[4.]])
    assert r['pv_load_direct_kwh'] == pytest.approx(4.)
    assert r['pv_stored_kwh'] == pytest.approx(4.)
    r = c.run([0.], [0.], [[-4.]])
    assert r['pv_grid_export_kwh'] == pytest.approx(6.)
    assert r['pv_load_kwh'] == pytest.approx(4.)
    assert r['pv_useful_building_ratio'] == pytest.approx(.4)


def test_storage_use_losses_and_remaining_stock():
    c = Case([battery(charge_eta=.8, discharge_eta=.5)])
    c.run([5.], [0.], [[5.]])
    r = c.run([0.], [1.], [[-1.]])
    assert r['pv_loss_kwh'] == pytest.approx(2.)
    assert r['pv_load_after_storage_kwh'] == pytest.approx(1.)
    assert r['pv_stored_kwh'] == pytest.approx(2.)
    assert r['pv_load_direct_kwh'] == pytest.approx(0.)


def test_mixture_retains_acquisition_carbon_after_grid_intensity_changes():
    c = Case([battery()])
    c.run([2.], [0.], [[4.]])
    c.buildings[0].carbon_intensity.carbon_intensity[1] = .9
    r = c.run([0.], [2.], [[-2.]])
    assert r['pv_load_after_storage_kwh'] == pytest.approx(1.)
    assert r['grid_load_kwh'] == pytest.approx(1.)
    assert r['external_purchase_emissions_kgco2'] == pytest.approx(.4)
    assert r['carbon_load_kgco2'] == pytest.approx(.2)
    assert r['carbon_stored_kgco2'] == pytest.approx(.2)


def test_neighbor_grid_storage_is_not_relabelled_solar():
    c = Case([battery(), battery()])
    c.run([0., 0.], [0., 0.], [[4.], [0.]])
    r = c.run([0., 0.], [0., 4.], [[-4.], [0.]])
    assert r['pv_load_kwh'] == 0.
    assert r['grid_load_kwh'] == pytest.approx(4.)
    assert r['external_purchase_emissions_kgco2'] == pytest.approx(.8)
    assert r['carbon_load_kgco2'] == pytest.approx(.8)


def test_shared_pv_emissions_use_only_net_external_import():
    c = Case([battery(), battery()])
    r = c.run([2.5, 0.], [0., 3.5], [[0.], [0.]])
    assert r['external_purchase_emissions_kgco2'] == pytest.approx(.2)
    assert r['pv_load_direct_kwh'] == pytest.approx(2.5)


def test_multiple_opposing_transfers_resolve_with_proportional_mixing():
    c = Case([battery(initial=.2, charge_eta=.8, discharge_eta=.8)])
    r = c.run([4.], [2.2], [[3., -1.]])
    assert r['unknown_load_kwh'] > 0.
    assert r['pv_load_after_storage_kwh'] > 0.
    assert r['pv_loss_kwh'] > 0.
    assert energy(next(iter(c.ledger.stocks.values())).bag) == pytest.approx(c.batteries[0].energy_init)


def test_standby_unknown_inventory_and_asset_removal():
    c = Case([battery(initial=.2, loss=.1)])
    c.run([2.], [0.], [[2.]])
    r = c.run([0.], [0.], [[0.]])
    assert r['unknown_loss_kwh'] == pytest.approx(.2, abs=1e-6)
    assert r['pv_loss_kwh'] == pytest.approx(.2, abs=1e-6)
    c.env.buildings = []
    c.ledger.synchronize()
    r = c.summary()
    assert r['pv_asset_exit_kwh'] == pytest.approx(1.8, abs=1e-6)
    assert r['unknown_asset_exit_kwh'] == pytest.approx(1.8, abs=1e-6)
    assert r['pv_load_kwh'] == 0.


def test_ev_departure_and_return_soc_are_separate_cohorts():
    c = Case([battery()])
    b = c.batteries[0]
    ev = NS(battery=b)
    charger = NS(connected_electric_vehicle=ev)
    c.buildings[0].electrical_storage = None
    c.buildings[0].electric_vehicle_chargers = [charger]
    c.ledger.reset()
    c.run([4.], [0.], [[4.]])
    charger.connected_electric_vehicle = None
    c.ledger.synchronize()
    r = c.summary()
    assert r['pv_mobility_kwh'] == pytest.approx(4.)
    assert r['pv_useful_building_ratio'] == 0.
    assert r['pv_useful_with_mobility_ratio'] == pytest.approx(1.)
    b.force_set_soc(.3)
    charger.connected_electric_vehicle = ev
    c.ledger.synchronize()
    r = c.summary()
    assert r['unknown_stored_kwh'] == pytest.approx(3.)
    assert r['pv_stored_kwh'] == 0.


def test_external_assignment_invalidates_origin_even_with_same_soc():
    c = Case([battery()])
    c.run([4.], [0.], [[4.]])
    c.batteries[0].force_set_soc(.4)
    c.ledger.synchronize()
    r = c.summary()
    assert r['pv_external_reset_kwh'] == pytest.approx(4.)
    assert r['unknown_stored_kwh'] == pytest.approx(4.)


def test_evaluation_and_repeated_settlement_are_idempotent_and_reset_is_clean():
    c = Case([battery()])
    c.run([2.], [1.], [[1.]])
    before = deepcopy(c.summary())
    c.env.time_step -= 1
    c.ledger.settle()
    assert c.summary() == before
    assert c.summary() == before
    c.batteries[0].reset()
    c.ledger.reset()
    assert c.summary()['pv_generated_kwh'] == 0.


def test_actual_charger_keeps_every_transfer_and_conversion_loss():
    from citylearn.electric_vehicle import ElectricVehicle
    from citylearn.electric_vehicle_charger import Charger
    b = battery(initial=.2, charge_eta=.8, discharge_eta=.8)
    ev = ElectricVehicle(episode_tracker=b.episode_tracker, battery=b, name='EV', seconds_per_time_step=3600)
    charger = Charger(episode_tracker=b.episode_tracker, charger_simulation=NS(), charger_id='C',
        efficiency=.9, max_charging_power=5., max_discharging_power=5.,
        min_charging_power=0., min_discharging_power=0., seconds_per_time_step=3600, time_step_ratio=1.)
    ev.reset()
    charger.reset()
    charger.plug_car(ev)
    c = Case([b])
    c.buildings[0].electrical_storage = None
    c.buildings[0].electric_vehicle_chargers = [charger]
    c.ledger.reset()
    c.ledger.begin_step()
    for action in (.6, -.2, 0.):
        charger.update_connected_electric_vehicle_soc(action)
    assert charger.electricity_consumption[0] == pytest.approx(2., abs=1e-6)
    assert sum(e['bus'] for e in b.energy_provenance_events) == pytest.approx(2., abs=1e-6)
    c.buildings[0].solar_generation[0] = -4.
    c.buildings[0].net_electricity_consumption[0] = 0.
    c.ledger.settle()
    row = c.summary()
    assert row['pv_loss_kwh'] > 0.
    assert row['unknown_loss_kwh'] > 0.


def test_two_storages_on_same_bus_preserve_sources_during_transfer():
    a, b = battery(), battery(initial=.2)
    c = Case([a])
    charger = NS(connected_electric_vehicle=NS(battery=b))
    c.buildings[0].electric_vehicle_chargers = [charger]
    c.ledger.reset()
    c.ledger.begin_step()
    a.charge(4.)
    b.charge(-2.)
    c.buildings[0].solar_generation[0] = -2.
    c.buildings[0].net_electricity_consumption[0] = 0.
    c.ledger.settle()
    row = c.summary()
    assert row['pv_stored_kwh'] == pytest.approx(2.)
    assert row['unknown_stored_kwh'] == pytest.approx(2.)
    assert row['pv_load_kwh'] == 0.


def test_member_removal_with_connected_ev_is_asset_exit_not_mobility():
    b = battery()
    c = Case([b])
    c.buildings[0].electrical_storage = None
    c.buildings[0].electric_vehicle_chargers = [NS(connected_electric_vehicle=NS(battery=b))]
    c.ledger.reset()
    c.run([4.], [0.], [[4.]])
    c.env.buildings = []
    c.ledger.synchronize()
    r = c.summary()
    assert r['pv_asset_exit_kwh'] == pytest.approx(4.)
    assert r['pv_mobility_kwh'] == 0.
