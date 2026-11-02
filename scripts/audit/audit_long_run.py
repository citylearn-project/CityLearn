#!/usr/bin/env python3
"""Continuous native-dataset campaign with streaming meter reconciliation and resources.

This is a long-duration regression audit, not a second provenance engine or a
controller benchmark. Physics checks remain enabled on every executed interval.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from citylearn.citylearn import CityLearnEnv
from citylearn.agents.baseline import NormalPolicy
from citylearn.internal.experiment import experiment_manifest

DEFINITION_VERSION = 'long-run-audit-v1'
MIB = 1024**2


def rss_mib():
    """Current Linux RSS; peak RSS is reported separately."""
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/MIB


def retained_bytes(obj, seen=None):
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        size += sum(retained_bytes(k, seen)+retained_bytes(v, seen) for k,v in obj.items())
    elif isinstance(obj, (list, tuple)):
        size += sum(retained_bytes(x, seen) for x in obj)
    return size


class StreamingMeters:
    """Read executed device terminals and settlement; retain totals by member ID."""
    def __init__(self, absolute_tolerance=1e-5, relative_tolerance=1e-7):
        self.atol, self.rtol = absolute_tolerance, relative_tolerance
        self.members = defaultdict(lambda: defaultdict(float))
        self.checks = 0
        self.max_fraction = 0.0
        self.max_errors = defaultdict(float)
        self.active_min, self.active_max = None, 0
        self.steps = 0

    def check(self, label, actual, expected, *, atol=None):
        a, e = float(actual), float(expected)
        limit = (self.atol if atol is None else atol)+self.rtol*max(abs(a),abs(e))
        error = abs(a-e)
        self.checks += 1
        if not np.isfinite([a,e]).all() or error > limit:
            raise AssertionError(f'{label}: actual={a}, expected={e}, tolerance={limit}')
        self.max_errors[label] = max(self.max_errors[label], error)
        self.max_fraction = max(self.max_fraction, error/limit)

    def record(self, buildings, t, settlement):
        by_name = {r['building']:r for r in settlement}
        if len(by_name)!=len(settlement) or set(by_name)!={b.name for b in buildings}:
            raise AssertionError('Settlement and executed active member identities disagree')
        self.active_min = len(buildings) if self.active_min is None else min(self.active_min,len(buildings))
        self.active_max = max(self.active_max,len(buildings))
        internal_import = internal_export = internal_cash = 0.0
        for b in buildings:
            r=by_name[b.name];m=self.members[b.name]
            net=float(b.net_electricity_consumption[t])
            pv=-float(b.solar_generation[t])
            loads=sum(float(device.electricity_consumption[t]) for device in
                      [b.non_shiftable_load_device,b.cooling_device,b.heating_device,b.dhw_device])
            storage=float(b.electrical_storage.electricity_consumption[t])
            ev=sum(float(c.electricity_consumption[t]) for c in b.electric_vehicle_chargers or [])
            appliances=sum(float(a.electricity_consumption[t]) for a in b.deferrable_appliances or [])
            escalators=sum(float(a.electricity_consumption[t]) for a in getattr(b,'escalators',[]) or [])
            terms=loads+storage+ev+appliances+escalators-pv
            outage=bool(b.simulate_power_outage and b.power_outage_signal[t]>=1)
            curtailed=max(-terms,0.0) if outage else 0.0
            self.check('device_bus_kwh',net,terms+curtailed,atol=5e-4)
            self.check('meter_import_kwh',max(net,0),r['grid_import_kwh']+r['local_import_kwh'])
            self.check('meter_export_kwh',max(-net,0),r['grid_export_kwh']+r['local_export_kwh'])
            buy=float(r['grid_import_price']);sell=float(r['grid_export_price'])
            if not np.isfinite(buy) or buy < 0:
                raise AssertionError('Invalid native purchase price')
            self.check('export_price_eur_per_kwh',sell,0)
            self.check('internal_buy_price_eur_per_kwh',r['local_buy_price'],.8*buy)
            self.check('internal_sell_price_eur_per_kwh',r['local_sell_price'],.8*buy)
            cost=r['grid_import_kwh']*buy-r['grid_export_kwh']*sell+(r['local_import_kwh']-r['local_export_kwh'])*.8*buy
            self.check('member_cash_eur',r['settled_cost_eur'],cost)
            self.check('member_cost_history_eur',b.net_electricity_consumption_cost[t],cost)
            internal_import+=r['local_import_kwh'];internal_export+=r['local_export_kwh']
            internal_cash+=(r['local_import_kwh']-r['local_export_kwh'])*.8*buy
            for key,value in dict(net=net,import_kwh=max(net,0),export_kwh=max(-net,0),pv_generated_kwh=pv,
                                  external_import=r['grid_import_kwh'],external_export=r['grid_export_kwh'],
                                  local=r['local_import_kwh'],cost=cost,appliance_kwh=appliances,
                                  ev_net_kwh=ev,storage_net_kwh=storage,curtailed_kwh=curtailed,
                                  native_unserved_kwh=max(float(b.energy_simulation.non_shiftable_load[t])*b.time_step_ratio-float(b.non_shiftable_load_device.electricity_consumption[t]),0.0),
                                  active_intervals=1,outage_intervals=int(outage)).items():
                if not np.isfinite(value):raise AssertionError('Non-finite meter: '+key)
                m[key]+=value
        self.check('internal_energy_kwh',internal_import,internal_export)
        self.check('internal_cash_eur',internal_cash,0)
        self.steps+=1

    def totals(self):
        result=defaultdict(float)
        for m in self.members.values():
            for k,v in m.items():result[k]+=v
        return dict(result)

    def reconcile(self, env, frame):
        if frame.duplicated(['level','name','cost_function']).any():
            raise AssertionError('Duplicate KPI identities')
        values={(r.name,r.cost_function):r.value for r in frame.itertuples()}
        pairs={'cost':'cost_total_control_eur','import_kwh':'energy_grid_total_import_control_kwh',
               'export_kwh':'energy_grid_total_export_control_kwh','pv_generated_kwh':'solar_self_consumption_total_generation_kwh'}
        for name,row in self.members.items():
            for key,suffix in pairs.items():self.check('KPI_'+suffix,values[name,'building_'+suffix],row[key])
        totals=self.totals()
        for key,suffix in dict(local='energy_grid_community_market_local_traded_total_kwh',
                               external_import='energy_grid_community_market_grid_import_after_local_total_kwh',
                               external_export='energy_grid_community_market_grid_export_after_local_total_kwh',
                               cost='cost_community_market_settled_total_eur').items():
            self.check('district_KPI_'+suffix,values['District','district_'+suffix],totals[key])
        _,accounting=env._provenance_service.summary()
        for key in ['pv_balance_residual_kwh','grid_balance_residual_kwh','unknown_balance_residual_kwh',
                    'carbon_balance_residual_kgco2','storage_max_residual_kwh','bus_max_residual_kwh']:
            self.check('ledger_'+key,accounting[key],0,atol=1e-3)
        self.check('ledger_external_import_kwh',accounting['external_import_kwh'],totals['external_import'])
        self.check('ledger_PV_generated_kwh',accounting['pv_generated_kwh'],totals['pv_generated_kwh'])
        curtailment=sum(accounting.get(origin+'_curtailment_kwh',0) for origin in ['pv','grid','unknown'])
        self.check('ledger_curtailment_kwh',curtailment,totals['curtailed_kwh'],atol=1e-3)
        service=env.get_deferrable_service_audit()
        self.check('appliance_service_kwh',service['district']['served_energy_kwh'],totals['appliance_kwh'])
        return accounting,service


class ExecutedIntervalObserver:
    """Observe settled terminals before advancing time/topology to the next slot."""
    def __init__(self, env, meters, global_start):
        self.env, self.meters, self.global_start = env, meters, global_start
        self.runtime = env._runtime_service
        self.original = self.runtime.update_variables
        self.row = None

        def observed_update(*args, **kwargs):
            result = self.original(*args, **kwargs)
            buildings = list(env.buildings)
            t = int(env.time_step)
            meters.record(buildings, t, env._last_community_market_settlement)
            self.row = [global_start+t, len(buildings),
                        sum(float(b.net_electricity_consumption[t]) for b in buildings),
                        sum(float(b.net_electricity_consumption_cost[t]) for b in buildings),
                        sum(bool(b.simulate_power_outage and b.power_outage_signal[t]>=1) for b in buildings)]
            return result

        self.runtime.update_variables = observed_update

    def close(self):
        self.runtime.update_variables = self.original


def run(args):
    if args.transitions < 1 or args.start < 0 or args.block_steps < 1 or args.max_rss_mib <= 0 or args.max_seconds <= 0:
        raise ValueError('Positive durations, limits and nonnegative start required')
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Output directory must be empty to preserve previous evidence')
    args.output.mkdir(parents=True,exist_ok=True)
    report=dict(definition_version=DEFINITION_VERSION,status='running',schema=str(args.schema.resolve()),
                audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                schema_sha256=hashlib.sha256(args.schema.read_bytes()).hexdigest(),start=args.start,
                requested_transitions=args.transitions,seed=args.seed,physics_invariant_checks=True,
                limits=dict(max_rss_mib=args.max_rss_mib,max_seconds=args.max_seconds),blocks=[])
    def save():
        p=args.output/'summary.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');tmp.replace(p)
    env=None;observer=None;start_clock=time.monotonic();meters=StreamingMeters();phase='loading';current_interval=None
    try:
        schema=json.loads(args.schema.read_text())
        market=schema.get('community_market') or {}
        if not market.get('enabled') or market.get('local_price_ratio_to_grid_import')!=.8 or market.get('grid_export_price')!=0:
            raise ValueError('This native campaign requires declared 80% internal pricing and zero grid export price')
        root=Path(schema.get('root_directory') or '.')
        if not root.is_absolute():root=args.schema.resolve().parent/root
        if args.start+args.transitions>int(schema['simulation_end_time_step']):
            raise ValueError('Window must include its terminal observation within source data')
        schema.update(root_directory=str(root),simulation_start_time_step=args.start,
                      simulation_end_time_step=args.start+args.transitions,episode_time_steps=args.transitions+1,
                      rolling_episode_split=False,random_episode_split=False)
        env=CityLearnEnv(schema,random_seed=args.seed,offline=True,render_mode='none',
                         physics_invariant_checks=True,export_kpis_on_episode_end=False)
        obs,_=env.reset(seed=args.seed);policy=NormalPolicy(env)
        identity=policy.comparison_identity();env.set_experiment_identity(**identity)
        report.update(controller=identity,load_and_reset_seconds=time.monotonic()-start_clock,
                      rss_after_reset_mib=rss_mib(),members_initial=len(env.buildings))
        if report['rss_after_reset_mib']>args.max_rss_mib:
            raise RuntimeError('Measured RSS limit exceeded after loading/reset')
        batteries={}
        def collect_batteries():
            all_batteries=[b.electrical_storage for b in env.buildings]
            all_batteries += [e.battery for e in getattr(env,'_all_electric_vehicles',env.electric_vehicles)]
            for battery in all_batteries:
                if id(battery) not in batteries:batteries[id(battery)]=(battery,float(battery.degraded_capacity))
        collect_batteries()
        last_topology_version=env.topology_version
        block_clock=time.monotonic();block_step=0
        observer=ExecutedIntervalObserver(env,meters,args.start)
        trace=args.output/'intervals.csv'
        with trace.open('w',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['global_step','active_members','net_kwh','cost_eur','outage_members'])
            phase='dispatch'
            while not env.terminated:
                t=env.time_step;buildings=list(env.buildings)
                current_interval=args.start+t
                if env.topology_version!=last_topology_version:
                    collect_batteries();last_topology_version=env.topology_version
                before=meters.steps
                obs,reward,terminated,truncated,_=env.step(policy.predict(obs,deterministic=True))
                if not np.isfinite(reward).all():raise AssertionError('Non-finite reward')
                if meters.steps!=before+1:raise AssertionError('Exactly one executed meter sample required per transition')
                writer.writerow(observer.row)
                if truncated and not terminated:raise AssertionError('Unexpected truncated episode')
                if meters.steps % args.block_steps==0 or terminated:
                    now=time.monotonic();collect_batteries();ledger=env._provenance_service
                    aggregates=[ledger.sources,ledger.sinks,ledger.internal_transfers,[s.bag for s in ledger.stocks.values()]]
                    block=dict(completed_intervals=meters.steps,global_last_executed=args.start+t,
                               wall_seconds=now-start_clock,block_seconds=now-block_clock,
                               block_ms_per_interval=(now-block_clock)*1000/(meters.steps-block_step),
                               rss_mib=rss_mib(),peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                               active_members=len(env.buildings),ledger_aggregate_bytes=retained_bytes(aggregates),
                               settlement_history_steps=len(env._community_market_settlement_history))
                    report['blocks'].append(block);report['completed_intervals']=meters.steps;save();stream.flush()
                    print(json.dumps(block),flush=True);block_clock=now;block_step=meters.steps
                    if block['rss_mib']>args.max_rss_mib:raise RuntimeError('Measured RSS limit exceeded')
                    if now-start_clock>args.max_seconds:raise RuntimeError('Measured wall-time limit exceeded')
        observer.close();observer=None
        if meters.steps!=args.transitions:raise AssertionError('Executed interval count differs from requested window')
        phase='final_evaluation';evaluation_clock=time.monotonic();frame=env.evaluate_v2(include_business_as_usual=False)
        frame.to_csv(args.output/'kpis.csv',index=False)
        accounting,service=meters.reconcile(env,frame)
        (args.output/'service.json').write_text(json.dumps(service,indent=2,allow_nan=False)+'\n')
        manifest=experiment_manifest(env)
        if manifest['input_file_changes']:raise AssertionError('Input content changed after loading')
        (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        capacities=[]
        for battery,initial in batteries.values():
            final=float(battery.degraded_capacity)
            if not np.isfinite(final) or not 0<=final<=initial+1e-8:raise AssertionError('Invalid capacity degradation')
            capacities.append(dict(uid=battery.uid,initial_capacity_kwh=initial,final_capacity_kwh=final,
                                   capacity_loss_kwh=initial-final,history_entries=len(battery.capacity_history)))
        report.update(status='pass',checks=meters.checks,max_tolerance_fraction=meters.max_fraction,
                      max_absolute_errors=dict(meters.max_errors),meter_totals=meters.totals(),accounting=accounting,
                      active_members_min=meters.active_min,active_members_max=meters.active_max,
                      members_ever_observed=len(meters.members),member_totals={k:dict(v) for k,v in meters.members.items()},
                      topology_events=len(env.topology_event_log),capacity_degradation=capacities,
                      final_kpi_and_export_seconds=time.monotonic()-evaluation_clock,kpi_rows=len(frame),
                      ev_departure_audit={r.cost_function:float(r.value) if r.value is not None and np.isfinite(r.value) else None for r in frame.itertuples() if r.name=='District' and 'ev_departure_audit_' in r.cost_function},
                      peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                      audit_scope='Independent device/meter/cash streaming totals against KPIs; runtime physics every step; production provenance residuals. No second full producer/recipient-flow solve every interval.')
        if report['peak_rss_mib']>args.max_rss_mib or rss_mib()>args.max_rss_mib:
            raise RuntimeError('Measured RSS limit exceeded during final evaluation/export')
        if time.monotonic()-start_clock>args.max_seconds:
            raise RuntimeError('Measured wall-time limit exceeded during final evaluation/export')
    except Exception as error:
        report.update(status='fail',completed_intervals=meters.steps,error_type=type(error).__name__,error=str(error),
                      failure_phase=phase,failed_global_interval=current_interval if phase=='dispatch' else None,
                      traceback=traceback.format_exc(limit=10))
    finally:
        if observer is not None:observer.close()
        if env is not None:env.close()
        report['wall_seconds']=time.monotonic()-start_clock;save()
    print(json.dumps({k:report.get(k) for k in ['status','completed_intervals','wall_seconds','error']}),flush=True)
    return 0 if report['status']=='pass' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',type=Path,required=True)
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--transitions',type=int,required=True)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--block-steps',type=int,default=960)
    parser.add_argument('--max-rss-mib',type=float,default=8192)
    parser.add_argument('--max-seconds',type=float,default=14400)
    parser.add_argument('--output',type=Path,required=True)
    return run(parser.parse_args())


if __name__=='__main__':
    sys.exit(main())
