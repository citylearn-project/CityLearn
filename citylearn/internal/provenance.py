"""Passive electricity provenance, definition 1.0.

An interval has a perfectly mixed AC bus per member. Storage is proportionally
mixed and its operations remain ordered. An affine balance resolves same-step
storage cycles without inventing solar energy or iterating physical actions.
Only aggregate source/destination counters and active storage stocks are kept.
"""
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

DEFINITION_VERSION = '1.1'
KPI_DEFINITION_VERSION = '1.9.0'
EPS = 1e-10


def add(target, source, scale=1.0):
    for key, (energy, carbon) in source.items():
        old = target.get(key, (0.0, 0.0))
        target[key] = (old[0] + energy*scale, old[1] + carbon*scale)
    return target


def scaled(bag, factor):
    return {key: (e*factor, c*factor) for key, (e, c) in bag.items() if abs(e*factor) > EPS}


def energy(bag):
    return sum(v[0] for v in bag.values())


@dataclass
class Stock:
    battery: object
    owner: str
    kind: str
    bag: dict = field(default_factory=dict)
    step: int = -1
    cursor: int = 0
    connection: object = None


class CityLearnProvenanceService:
    """Electrical boundary: active member AC buses and connected EV batteries."""

    def __init__(self, env):
        self.env = env
        self.reset(empty=True)

    def reset(self, empty=False):
        self.stocks = {}
        self.sources = defaultdict(dict)
        self.sinks = defaultdict(dict)
        self.direct_load = defaultdict(float)
        self.external_emissions = defaultdict(float)
        self.external_import = defaultdict(float)
        self.internal_transfers = defaultdict(dict)
        self.steps = 0
        self.last_step = -1
        self.max_storage_residual = 0.0
        self.max_bus_residual = 0.0
        if not empty:
            self.synchronize()

    def assets(self):
        assets = {}
        for b in self.env.buildings:
            battery = getattr(b, 'electrical_storage', None)
            if battery is not None and battery.capacity > 0:
                assets[id(battery)] = (battery, b.name, 'stationary', None)
            for charger in getattr(b, 'electric_vehicle_chargers', []) or []:
                ev = getattr(charger, 'connected_electric_vehicle', None)
                if ev is not None:
                    assets[id(ev.battery)] = (ev.battery, b.name, 'ev', charger)
        return assets

    def source(self, owner, bag):
        add(self.sources[owner], bag)

    def sink(self, owner, destination, bag):
        add(self.sinks[(owner, destination)], bag)

    def synchronize(self):
        """Reconcile arrivals/departures/topology before an action or evaluation.

        Departure inventory leaves as mobility delivery, not inferred trip use.
        Imposed arrival SOC replaces the old cohort with unknown external energy.
        """
        assets = self.assets()
        active_chargers = {id(charger) for b in self.env.buildings
                           for charger in (getattr(b, 'electric_vehicle_chargers', []) or [])}
        for key in list(self.stocks):
            stock = self.stocks[key]
            if key not in assets or assets[key][1] != stock.owner:
                mobility = stock.kind == 'ev' and id(stock.connection) in active_chargers
                self.sink(stock.owner, 'mobility' if mobility else 'asset_exit', stock.bag)
                del self.stocks[key]
        for key, (battery, owner, kind, connection) in assets.items():
            if key not in self.stocks:
                bag = {('unknown', owner): (float(battery.energy_init), 0.0)}
                self.source(owner, bag)
                self.stocks[key] = Stock(battery, owner, kind, bag, int(battery.time_step),
                                         len(battery.energy_provenance_events), connection)
                continue
            stock = self.stocks[key]
            events = self._pending(stock)
            # Transfers are processed jointly with the member bus in settle().
            for event in events:
                if event['kind'] == 'transfer':
                    break
                if event['kind'] == 'external':
                    self.sink(owner, 'external_reset', stock.bag)
                    stock.bag = {('unknown', owner): (event['after'], 0.0)}
                    self.source(owner, stock.bag)
                else:
                    old = energy(stock.bag)
                    remaining = min(max(event['after']/old, 0.0), 1.0) if old > EPS else 0.0
                    self.sink(owner, 'loss', scaled(stock.bag, 1.0-remaining))
                    stock.bag = scaled(stock.bag, remaining)
                stock.cursor += 1

    @staticmethod
    def _pending(stock):
        if stock.step != stock.battery.time_step:
            stock.step, stock.cursor = int(stock.battery.time_step), 0
        return stock.battery.energy_provenance_events[stock.cursor:]

    def begin_step(self):
        self.synchronize()

    def _sharing(self, nets):
        env = self.env
        if getattr(env, 'community_market_enabled', False):
            rows = {r['building']: r for r in env._last_community_market_settlement}
            return {b.name: (rows[b.name]['local_import_kwh'], rows[b.name]['local_export_kwh'])
                    for b in env.buildings}
        # Explicit physical convention when financial settlement is disabled.
        imports = np.maximum(nets, 0.0)
        exports = np.maximum(-nets, 0.0)
        traded = min(float(imports.sum()), float(exports.sum()))
        weights = np.array([getattr(env, 'community_market_import_member_weights', {}).get(b.name, 1.0)
                            for b in env.buildings])
        local = env._runtime_service._allocate_weighted_share_import(imports, traded, weights)
        sold = exports*traded/exports.sum() if exports.sum() > EPS else np.zeros_like(exports)
        return {b.name: (float(i), float(e)) for b, i, e in zip(env.buildings, local, sold)}

    def settle(self):
        """Record one completed interval, idempotently, before topology advances."""
        t = int(self.env.time_step)
        if t <= self.last_step:
            return
        nets = np.array([float(b.net_electricity_consumption[t]) for b in self.env.buildings])
        sharing = self._sharing(nets)
        buses = {}
        pending_stocks = []
        for b, net in zip(self.env.buildings, nets):
            pv = max(-float(b.solar_generation[t]), 0.0)
            source = {('pv', b.name): (pv, 0.0)} if pv > EPS else {}
            self.source(b.name, source)
            curtailed = float(b.pv_curtailment[t]) if hasattr(b, 'pv_curtailment') else 0.0
            if curtailed > EPS:
                self.sink(b.name, 'curtailment', {('pv', b.name): (curtailed, 0.0)})
            pv = max(pv - curtailed, 0.0)
            source = {('pv', b.name): (pv, 0.0)} if pv > EPS else {}
            buses[b.name] = dict(known=dict(source), pv=pv, discharge=0.0, charge=0.0,
                                 recycle=0.0, net=net, building=b)
        for stock in self.stocks.values():
            bus = buses[stock.owner]
            known, coefficient = dict(stock.bag), 0.0
            losses, loss_coefficient = {}, 0.0
            external_sinks = []
            for event in self._pending(stock):
                if event['kind'] == 'external':
                    external_sinks.append((known, coefficient))
                    known = {('unknown', stock.owner): (event['after'], 0.0)}
                    self.source(stock.owner, known)
                    coefficient = 0.0
                    stock.cursor += 1
                    continue
                if event['kind'] == 'standby':
                    total = energy(known)+coefficient
                    fraction = min(max(1.0-event['after']/total, 0.0), 1.0) if total > EPS else 0.0
                    add(losses, known, fraction)
                    loss_coefficient += coefficient*fraction
                    known = scaled(known, 1.0-fraction)
                    coefficient *= 1.0-fraction
                    stock.cursor += 1
                    continue
                ac = event['bus']
                delta = event['after']-event['before']
                if ac >= 0:
                    stored = max(delta, 0.0)
                    coefficient += stored
                    loss_coefficient += max(ac-stored, 0.0)
                    bus['charge'] += ac
                else:
                    removed = max(-delta, 0.0)
                    total = energy(known)+coefficient
                    fraction = min(removed/total, 1.0) if total > EPS else 0.0
                    removed_known = scaled(known, fraction)
                    removed_coefficient = coefficient*fraction
                    eta = min(-ac/removed, 1.0) if removed > EPS else 0.0
                    add(bus['known'], removed_known, eta)
                    bus['recycle'] += removed_coefficient*eta
                    add(losses, removed_known, 1.0-eta)
                    loss_coefficient += removed_coefficient*(1.0-eta)
                    known = scaled(known, 1.0-fraction)
                    coefficient *= 1.0-fraction
                    bus['discharge'] += -ac
                stock.cursor += 1
            pending_stocks.append((stock, known, coefficient, losses, loss_coefficient, external_sinks))
        # Exporting members cannot also import in net community settlement, so
        # their source composition can be solved first without a dense matrix.
        pool, pool_direct, sold_total = {}, 0.0, 0.0
        for name, bus in buses.items():
            local_in, local_out = sharing[name]
            grid_in = max(bus['net'], 0.0)-local_in
            b = bus['building']
            ci = float(b.carbon_intensity.carbon_intensity[t])
            grid_key = ('grid' if np.isfinite(ci) else 'grid_unknown_carbon', name)
            grid = {grid_key: (grid_in, grid_in*ci if np.isfinite(ci) else 0.0)}
            self.source(name, grid)
            self.external_import[name] += grid_in
            self.external_emissions[name] += grid_in*ci if np.isfinite(ci) else 0.0
            add(bus['known'], grid)
            bus['supply'] = bus['pv']+bus['discharge']+max(bus['net'], 0.0)
            bus['load'] = max(bus['net']+bus['pv']+bus['discharge']-bus['charge'], 0.0)
            residual = bus['supply']-(bus['load']+bus['charge']+max(-bus['net'], 0.0))
            self.max_bus_residual = max(self.max_bus_residual, abs(residual))
            if local_in <= EPS:
                denominator = bus['supply']-bus['recycle']
                bus['mix'] = scaled(bus['known'], 1.0/denominator) if denominator > EPS else {}
                bus['direct'] = bus['pv']/bus['supply'] if bus['supply'] > EPS else 0.0
                add(pool, bus['mix'], local_out)
                pool_direct += local_out*bus['direct']
                sold_total += local_out
        for name, bus in buses.items():
            local_in, local_out = sharing[name]
            if local_in > EPS:
                add(bus['known'], pool, local_in/sold_total if sold_total > EPS else 0.0)
                denominator = bus['supply']-bus['recycle']
                bus['mix'] = scaled(bus['known'], 1.0/denominator) if denominator > EPS else {}
                direct_input = bus['pv']+pool_direct*local_in/sold_total if sold_total > EPS else bus['pv']
                bus['direct'] = direct_input/bus['supply'] if bus['supply'] > EPS else 0.0
            self.sink(name, 'load', scaled(bus['mix'], bus['load']))
            add(self.internal_transfers[(name, 'local_import')], pool,
                local_in/sold_total if sold_total > EPS else 0.0)
            add(self.internal_transfers[(name, 'local_export')], bus['mix'], local_out)
            self.direct_load[name] += bus['direct']*bus['load']
            self.sink(name, 'grid_export', scaled(bus['mix'], max(-bus['net'], 0.0)-local_out))
        for stock, known, coefficient, losses, loss_coefficient, external_sinks in pending_stocks:
            mix = buses[stock.owner]['mix']
            stock.bag = add(known, mix, coefficient)
            self.sink(stock.owner, 'loss', add(losses, mix, loss_coefficient))
            for external_known, external_coefficient in external_sinks:
                self.sink(stock.owner, 'external_reset', add(external_known, mix, external_coefficient))
            residual = abs(energy(stock.bag)-stock.battery.energy_init)
            self.max_storage_residual = max(self.max_storage_residual, residual)
        self.last_step, self.steps = t, self.steps+1

    def summary(self):
        """Destination attribution by recipient; producer identity stays in bags.

        The cohort identity is all PV generated since reset. Initial/external
        inventories are unknown, even if their historical origin was renewable.
        """
        names = set(self.sources) | {s.owner for s in self.stocks.values()}
        names |= {name for name, _ in self.sinks}
        result = {}
        for name in sorted(names):
            stocks = {}
            for stock in self.stocks.values():
                if stock.owner == name:
                    add(stocks, stock.bag)
            def quantity(bag, origin=None, carbon=False):
                return sum(v[1 if carbon else 0] for k, v in bag.items() if origin is None or k[0] == origin)
            row = dict(pv_generated_kwh=quantity(self.sources[name], 'pv'),
                       pv_load_direct_kwh=self.direct_load[name],
                       unknown_input_kwh=quantity(self.sources[name], 'unknown'),
                       external_purchase_unknown_carbon_kwh=quantity(self.sources[name], 'grid_unknown_carbon'),
                       external_import_kwh=self.external_import[name],
                       external_purchase_emissions_kgco2=self.external_emissions[name])
            for direction in ('local_import', 'local_export'):
                bag = self.internal_transfers[(name, direction)]
                row[f'{direction}_kwh'] = quantity(bag)
                row[f'pv_{direction}_kwh'] = quantity(bag, 'pv')
                row[f'grid_{direction}_kwh'] = quantity(bag, 'grid')+quantity(bag, 'grid_unknown_carbon')
            for destination in ('load', 'mobility', 'grid_export', 'loss', 'asset_exit', 'external_reset', 'curtailment', 'stored'):
                bag = stocks if destination == 'stored' else self.sinks[(name, destination)]
                row[f'pv_{destination}_kwh'] = quantity(bag, 'pv')
                row[f'grid_{destination}_kwh'] = quantity(bag, 'grid')+quantity(bag, 'grid_unknown_carbon')
                row[f'unknown_{destination}_kwh'] = quantity(bag, 'unknown')
                row[f'carbon_{destination}_kgco2'] = quantity(bag, carbon=True)
                row[f'carbon_unknown_{destination}_kwh'] = quantity(bag, 'unknown')+quantity(bag, 'grid_unknown_carbon')
            row['pv_load_after_storage_kwh'] = max(row['pv_load_kwh']-row['pv_load_direct_kwh'], 0.0)
            result[name] = row
        district = {key: sum(row[key] for row in result.values()) for key in next(iter(result.values()), {})}
        if district:
            district['unknown_balance_residual_kwh'] = district['unknown_input_kwh']-sum(
                district[f'unknown_{d}_kwh'] for d in ('load', 'mobility', 'grid_export', 'loss', 'asset_exit', 'external_reset', 'curtailment', 'stored'))
            district['grid_balance_residual_kwh'] = district['external_import_kwh']-sum(
                district[f'grid_{d}_kwh'] for d in ('load', 'mobility', 'grid_export', 'loss', 'asset_exit', 'external_reset', 'curtailment', 'stored'))
            district['pv_balance_residual_kwh'] = district['pv_generated_kwh']-sum(
                district[f'pv_{d}_kwh'] for d in ('load', 'mobility', 'grid_export', 'loss', 'asset_exit', 'external_reset', 'curtailment', 'stored'))
            district['carbon_balance_residual_kgco2'] = district['external_purchase_emissions_kgco2']-sum(
                district[f'carbon_{d}_kgco2'] for d in ('load', 'mobility', 'grid_export', 'loss', 'asset_exit', 'external_reset', 'curtailment', 'stored'))
            generation = district['pv_generated_kwh']
            district['pv_useful_building_ratio'] = district['pv_load_kwh']/generation if generation > EPS else None
            district['pv_useful_with_mobility_ratio'] = (district['pv_load_kwh']+district['pv_mobility_kwh'])/generation if generation > EPS else None
        district['storage_max_residual_kwh'] = self.max_storage_residual
        district['bus_max_residual_kwh'] = self.max_bus_residual
        return result, district

    def source_destinations(self):
        """Sparse producer/recipient evidence, without an episode-sized matrix."""
        rows = []
        bags = dict(self.sinks)
        for stock in self.stocks.values():
            key = (stock.owner, 'stored')
            # Copy before adding: exports must not mutate live counters.
            bags[key] = add(dict(bags.get(key, {})), stock.bag)
        for (recipient, destination), bag in sorted(bags.items()):
            for (origin, producer), (kwh, carbon) in sorted(bag.items()):
                if kwh > EPS:
                    rows.append(dict(origin=origin, producer=producer, recipient=recipient,
                                     destination=destination, energy_kwh=kwh, carbon_kgco2=carbon))
        return rows

    def get_metadata(self):
        return dict(definition_version=DEFINITION_VERSION, kpi_definition_version=KPI_DEFINITION_VERSION,
                    ev_feasibility='individual_conditioned_on_service_headroom_physical_replay_v2',
                    ev_departure_audit=dict(
                        definition_version='ev-departure-audit-v1',
                        legacy_feasibility='unchanged_permissive_missing_data',
                        population='active_charger_departures_in_evaluated_member_window',
                        scope='individual_replay_from_observed_session_boundary_not_joint_scheduling',
                        unknown_reasons='exclusive_first_applicable_reason_per_threshold',
                        coverage_denominator='all_detected_departures',
                        observed_service_denominator='departures_with_valid_target_and_observed_soc',
                        feasible_service_denominator='confirmed_feasible_departures_with_observed_service',
                        empty_denominator=None,
                        outage='zero_charge_sufficient_test_otherwise_unknown_local_supply'),
                    mixing='proportional_storage_and_interval_member_ac_bus',
                    boundary='active_member_ac_buses_and_connected_ev_storage',
                    sharing='market_allocation' if getattr(self.env, 'community_market_enabled', False)
                    else 'same_interval_netting_weighted_imports_proportional_exports',
                    initial_inventory='unknown_external', export_carbon_credit=False,
                    pv_generation='available_including_reported_curtailment',
                    reported_energy_intervals='executed_active_intervals_v1',
                    equipment_throughput='gross_terminal_movements_before_interval_netting',
                    completed_intervals=self.steps)
