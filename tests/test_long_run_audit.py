"""Counterexamples for the passive long-run meters, plus a real short CLI run."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('long_run_audit',ROOT/'scripts/audit/audit_long_run.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def fixture():
    def device(value):return NS(electricity_consumption=[value])
    def building(name,load,pv,net):
        return NS(name=name,net_electricity_consumption=[net],solar_generation=[-pv],
                  non_shiftable_load_device=device(load),cooling_device=device(0),heating_device=device(0),
                  dhw_device=device(0),electrical_storage=device(0),electric_vehicle_chargers=[],
                  deferrable_appliances=[],escalators=[],simulate_power_outage=False,power_outage_signal=[0],
                  energy_simulation=NS(non_shiftable_load=[load]),time_step_ratio=1,
                  net_electricity_consumption_cost=[-.05 if name=='A' else .1125])
    buildings=[building('A',.35,.6,-.25),building('B',.5,0,.5)]
    common=dict(grid_import_price=.25,grid_export_price=0,local_buy_price=.2,local_sell_price=.2)
    settlement=[dict(common,building='A',local_import_kwh=0,local_export_kwh=.25,grid_import_kwh=0,grid_export_kwh=0,settled_cost_eur=-.05),
                dict(common,building='B',local_import_kwh=.25,local_export_kwh=0,grid_import_kwh=.25,grid_export_kwh=0,settled_cost_eur=.1125)]
    return buildings,settlement


def test_independent_meter_example_and_recreated_member_identity():
    buildings,settlement=fixture();m=audit.StreamingMeters();m.record(buildings,0,settlement)
    m.record(copy.deepcopy(buildings),0,copy.deepcopy(settlement))
    totals=m.totals()
    assert totals['cost']==pytest.approx(.125)
    assert totals['external_import']==pytest.approx(.5)
    assert totals['pv_generated_kwh']==pytest.approx(1.2)
    assert m.members['A']['active_intervals']==2 and len(m.members)==2


@pytest.mark.parametrize('mutation',['device','cash','nonfinite_price','identity','local_energy'])
def test_meter_counterexamples_are_rejected(mutation):
    b,r=fixture()
    if mutation=='device':b[0].non_shiftable_load_device.electricity_consumption[0]+=.1
    elif mutation=='cash':r[0]['settled_cost_eur']+=.1
    elif mutation=='nonfinite_price':r[0]['grid_import_price']=float('nan')
    elif mutation=='identity':r[0]['building']='other'
    elif mutation=='local_energy':r[0]['local_export_kwh']+=.1
    with pytest.raises(AssertionError):audit.StreamingMeters().record(b,0,r)


def test_outage_rejection_is_curtailment_and_unbacked_load_fails():
    b,r=fixture();b=b[:1];b[0].simulate_power_outage=True;b[0].power_outage_signal=[1]
    b[0].net_electricity_consumption=[0];b[0].net_electricity_consumption_cost=[0]
    r=r[:1];r[0].update(local_export_kwh=0,settled_cost_eur=0)
    m=audit.StreamingMeters();m.record(b,0,r)
    assert m.totals()['curtailed_kwh']==pytest.approx(.25)
    b[0].non_shiftable_load_device.electricity_consumption=[.7]
    with pytest.raises(AssertionError):audit.StreamingMeters().record(b,0,r)


def test_observer_samples_before_equipment_is_replaced_at_next_boundary():
    buildings,settlement=fixture();m=audit.StreamingMeters()
    def update():return 'updated'
    env=NS(buildings=buildings,time_step=0,_last_community_market_settlement=settlement,
           _runtime_service=NS(update_variables=update))
    observer=audit.ExecutedIntervalObserver(env,m,100)
    try:
        assert env._runtime_service.update_variables()=='updated'
        # Replacing the next interval's hardware must not rewrite the executed sample.
        env.buildings[0].electrical_storage=NS(electricity_consumption=[99])
        assert m.steps==1 and m.totals()['storage_net_kwh']==0
        assert observer.row[:2]==[100,2]
        assert observer.row[2]==pytest.approx(.25)
    finally:observer.close()
    assert env._runtime_service.update_variables is update


@pytest.mark.parametrize('dynamic', [False, True])
def test_real_cli_exports_evidence_and_enforces_measured_resource_limit(tmp_path, dynamic):
    source=(ROOT/'tests/data/minute_ev_demo/schema.json').resolve()
    schema=json.loads(source.read_text());schema['root_directory']=str(source.parent)
    schema['community_market']=dict(enabled=True,local_price_ratio_to_grid_import=.8,grid_export_price=0)
    if dynamic:
        schema.update(interface='entity',topology_mode='dynamic',topology_events=[dict(id='replace_boundary',time_step=1,
                      operation='remove_asset',target_member_id='Building_1',target_asset_type='electrical_storage')])
    schema_path=tmp_path/'schema.json';schema_path.write_text(json.dumps(schema))
    output=tmp_path/'run'
    command=[sys.executable,str(ROOT/'scripts/audit/audit_long_run.py'),'--schema',str(schema_path),
             '--transitions','3','--block-steps','1','--output',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads((output/'summary.json').read_text())
    assert report['status']=='pass' and report['completed_intervals']==3
    assert len(report['blocks'])==3 and report['checks']>0
    assert report['physics_invariant_checks'] and report['controller']['implementation'].endswith('NormalPolicy')
    assert all((output/f).is_file() for f in ['manifest.json','service.json','intervals.csv','kpis.csv'])
    limited=tmp_path/'limited'
    result=subprocess.run(command+['--max-rss-mib','0.001','--output',str(limited)],capture_output=True,text=True)
    assert result.returncode==1
    report=json.loads((limited/'summary.json').read_text())
    assert report['status']=='fail' and report['completed_intervals']==0
    assert 'RSS limit' in report['error']
