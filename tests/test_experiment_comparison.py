from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from citylearn.internal.comparison import compare_manifests, compare_exports
from citylearn.internal.experiment import experiment_manifest
from citylearn.citylearn import CityLearnEnv
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance, _zero_flat_actions


def export_run(path, output, *, seed=0, ratio=.8, identity='controller-a'):
    env=CityLearnEnv(str(path), episode_time_steps=4, random_seed=seed,
                     render_directory=output, export_kpis_on_episode_end=False,
                     ev_departure_service_tolerance=.07)
    env.schema['community_market']={'enabled':True,'local_price_ratio_to_grid_import':ratio,'grid_export_price':0.}
    env._configure_community_market()
    env.reset()
    env.set_experiment_identity(identity,'test-v1',{'action':0.})
    while not env.terminated:
        env.step(_zero_flat_actions(env))
    env.export_final_kpis(filepath='kpis.csv')
    p=Path(env.new_folder_path)/'kpis.csv'
    env.close()
    return p


def test_relocated_exports_pair_with_distinct_controller_identity(tmp_path):
    source=tmp_path/'source';source.mkdir()
    path=_schema_with_deferrable_appliance(source)
    a=export_run(path,tmp_path/'a')
    import shutil
    moved=tmp_path/'relocated'
    shutil.copytree(path.parent,moved)
    moved_schema=moved/'schema.json'
    data=json.loads(moved_schema.read_text());data['root_directory']=str(moved)
    moved_schema.write_text(json.dumps(data))
    b=export_run(moved_schema,tmp_path/'b',identity='controller-b')
    report=compare_exports(a,b)
    assert report['status']=='paired',report
    assert report['permitted_claim']=='controller_difference'
    assert report['baseline_reference']['evaluated']
    assert report['baseline_reference']['definition_version']=='immediate-full-charge-v1'
    assert report['baseline_reference']['resolved_parameters']['ev_target_soc']==1
    assert report['final_inventory']['left'] is not None
    assert all(r['delta_right_minus_left'] in (None,0.) for r in report['kpis'])
    manifest=json.loads(a.with_suffix('.manifest.json').read_text())
    other=deepcopy(manifest);other['comparison_context']['random_seed']=1
    assert 'random_seed' in compare_manifests(manifest,other)['mismatches']
    other=deepcopy(manifest);other['comparison_context']['initial_inventory'][0]['energy_kwh']+=1
    assert 'initial_inventory' in compare_manifests(manifest,other)['mismatches']
    other=deepcopy(manifest);other['business_as_usual_reference']['definition_version']='legacy-deadline'
    assert 'business_as_usual_reference' in compare_manifests(manifest,other)['mismatches']
    other=deepcopy(manifest);other['comparison_context']['data_files_sha256']['Building_1.csv']='different'
    assert 'data_files_sha256' in compare_manifests(manifest,other)['mismatches']
    other=deepcopy(manifest);other['comparison_context']['observation']['interface']='entity'
    assert 'observation' in compare_manifests(manifest,other)['mismatches']


def test_market_difference_requires_explicit_sharing_comparison(tmp_path):
    path=_schema_with_deferrable_appliance(tmp_path)
    p=export_run(path,tmp_path/'a')
    a=json.loads(p.with_suffix('.manifest.json').read_text());b=deepcopy(a)
    b['comparison_context']['market']['local_trading_enabled']=False
    assert compare_manifests(a,b)['status']=='incompatible'
    assert compare_manifests(a,b,mode='sharing')['status']=='paired'
    b['comparison_context']['market']['grid_export_price']=.1
    assert compare_manifests(a,b,mode='sharing')['status']=='incompatible'
    b=deepcopy(a);b['controller_identity']['implementation']='other'
    b['comparison_context']['market']['local_trading_enabled']=False
    assert 'controller_identity' in compare_manifests(a,b,mode='sharing')['mismatches']


def test_missing_evidence_is_unknown_not_identical(tmp_path):
    assert compare_manifests({}, {})['status']=='unknown'
    path=_schema_with_deferrable_appliance(tmp_path)
    p=export_run(path,tmp_path/'a');m=json.loads(p.with_suffix('.manifest.json').read_text())
    other=deepcopy(m);other['controller_identity']=None
    assert compare_manifests(m,other)['status']=='unknown'
    other=deepcopy(m);other['unresolved_file_references']=['missing.csv']
    assert compare_manifests(m,other)['status']=='unknown'


def test_native_reference_preserves_resolved_service_tolerance(tmp_path):
    path=_schema_with_deferrable_appliance(tmp_path)
    env=CityLearnEnv(str(path),episode_time_steps=4,random_seed=0,
                     ev_departure_within_tolerance=.03,ev_departure_service_tolerance=.12,
                     export_kpis_on_episode_end=False)
    try:
        env.reset()
        for _ in range(2):env.step(_zero_flat_actions(env))
        ref=env.run_business_as_usual_baseline().env
        assert ref.ev_departure_within_tolerance==.03
        assert ref.ev_departure_service_tolerance==.12
        manifest=experiment_manifest(env)
        assert manifest['business_as_usual_reference']['evaluated']
        assert manifest['comparison_context']['initial_inventory']!=manifest['final_inventory']
    finally:env.close()


def test_repeated_episodes_pair_away_vehicle_stochastic_trajectory(tmp_path):
    path=_schema_with_deferrable_appliance(tmp_path)
    # Isolate the away-vehicle stream: no controller can charge this fleet member.
    import pandas as pd
    schema=json.loads(path.read_text())
    chargers=schema['buildings']['Building_1']['chargers']
    file=next(iter(chargers.values()))['charger_simulation']
    frame=pd.read_csv(path.parent/file)
    frame['electric_vehicle_charger_state']=0
    frame['electric_vehicle_id']=''
    frame.to_csv(path.parent/file,index=False)
    env=CityLearnEnv(str(path),episode_time_steps=4,random_seed=5,export_kpis_on_episode_end=False)
    try:
        for _ in range(3):env.reset()
        initial=deepcopy(env._comparison_initial_inventory)
        while not env.terminated:env.step(_zero_flat_actions(env))
        ref=env.run_business_as_usual_baseline().env
        assert ref._ev_drift_seed==env._ev_drift_seed
        for a,b in zip(env.electric_vehicles,ref.electric_vehicles):
            np.testing.assert_allclose(a.battery.soc,b.battery.soc,atol=1e-7)
        final=experiment_manifest(env)['final_inventory']
        fleet=[r for r in final if r['kind']=='fleet_ev_including_away']
        assert fleet[0]['energy_kwh']>0
        assert fleet[0]['energy_kwh']==pytest.approx(float(env.electric_vehicles[0].battery.energy_init))
        assert env._comparison_initial_inventory==initial
    finally:env.close()


def test_native_controller_export_records_actual_identity(tmp_path):
    from citylearn.agents.baseline import BusinessAsUsualAgent
    path=_schema_with_deferrable_appliance(tmp_path)
    env=CityLearnEnv(str(path),episode_time_steps=4,render_directory=tmp_path/'exports',export_kpis_on_episode_end=False)
    try:
        env.reset();agent=BusinessAsUsualAgent(env,storage_min_soc=.25)
        while not env.terminated:env.step(agent.predict([]))
        env.export_final_kpis(model=agent,filepath='native.csv')
        manifest=json.loads((Path(env.new_folder_path)/'native.manifest.json').read_text())
        identity=manifest['controller_identity']
        assert identity['implementation']=='citylearn.agents.baseline.BusinessAsUsualAgent'
        assert identity['parameters']['storage_min_soc']==.25
        assert identity['observation_access']=='privileged_simulator_state'
    finally:env.close()


def test_cli_rejects_legacy_exports_without_pairing_evidence(tmp_path):
    import subprocess,sys
    import citylearn.internal.comparison as module
    for name in ('left','right'):
        (tmp_path/(name+'.csv')).write_text('KPI,District\ndistrict_cost_total_control_eur,1\n')
    script=Path(module.__file__).resolve().parents[2]/'scripts/audit/compare_experiments.py'
    result=subprocess.run([sys.executable,'-I',str(script),'--left',str(tmp_path/'left.csv'),
        '--right',str(tmp_path/'right.csv'),'--output',str(tmp_path/'comparison.json')],capture_output=True,text=True)
    assert result.returncode==2,result.stderr
    report=json.loads((tmp_path/'comparison.json').read_text())
    assert report['status']=='unknown' and report['permitted_claim'] is None
    assert report['kpis'][0]['delta_right_minus_left']==0


def test_equity_cli_accepts_v2_wide_and_does_not_claim_legacy_pairing(tmp_path):
    import subprocess,sys
    import citylearn.internal.comparison as module
    for name in ('left','right'):
        (tmp_path/(name+'.csv')).write_text('KPI,District\ndistrict_equity_distribution_gini_benefit_ratio,0.2\n')
    script=Path(module.__file__).resolve().parents[2]/'scripts/manual/compare_equity_runs.py'
    out=tmp_path/'equity.csv'
    result=subprocess.run([sys.executable,'-I',str(script),'--run-a',str(tmp_path/'left.csv'),
        '--run-b',str(tmp_path/'right.csv'),'--output',str(out)],capture_output=True,text=True)
    assert result.returncode==2,result.stderr
    assert 'improved' not in out.read_text()
    assert 'unknown' in out.read_text()
    assert json.loads(out.with_suffix('.comparison.json').read_text())['permitted_claim'] is None
