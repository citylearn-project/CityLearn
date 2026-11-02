import json
import numpy as np
import pytest
from citylearn.citylearn import CityLearnEnv
from test_robustness import _copy_schema,_event,_write_events,_clean_schema,_zero_actions


def schema_with_contract(tmp_path, *, selected=None, mode='hidden_faults', enabled=True):
    schema=_copy_schema(tmp_path,interface='entity',enabled=enabled)
    _write_events(schema,[_event(event_id='secret-fault-id',target_feature='non_shiftable_load',value=.2,mode='bias',start=0,end=2)])
    schema['robustness']['agent_observation_contract']={'mode':mode,
        'features':selected or {'building':['non_shiftable_load']}}
    return _clean_schema(schema)


def test_hidden_payload_contains_only_declared_measurements_and_no_labels(tmp_path):
    env=CityLearnEnv(schema_with_contract(tmp_path),episode_time_steps=4,random_seed=0,export_kpis_on_episode_end=False)
    try:
        obs,_=env.reset()
        specs=env.entity_specs['tables']
        b=specs['building']['features'];i=b.index('non_shiftable_load')
        assert obs['tables']['building'][0,i]==pytest.approx(env.buildings[0].energy_simulation.non_shiftable_load[0]+.2)
        assert 'robustness' not in obs['meta'] and 'runtime_status' not in obs['meta']
        assert 'secret-fault-id' not in json.dumps(obs['meta'])
        for table,values in obs['tables'].items():
            for col,feature in enumerate(specs[table]['features']):
                if (table,feature)!=('building','non_shiftable_load'):
                    assert np.all(values[:,col]==-9999)
            assert env.observation_space['tables'][table].contains(values)
        for _ in range(3):
            obs,_,_,_,info=env.step(_zero_actions(env))
            assert 'entity_action_execution' not in info
            assert 'secret-fault-id' not in json.dumps(obs['meta'])
        assert env.get_metadata()['robustness']['agent_observation_contract']['mode']=='hidden_faults'
    finally:env.close()


@pytest.mark.parametrize('selected',[
    {'building':['non_shiftable_load','load_power_kw']},
    {'building':['load_energy_kwh_step']},
    {'district':['robustness_active']},
    {'building':['nonexistent']},
])
def test_hidden_contract_rejects_clean_alternates_labels_and_unknown_fields(tmp_path,selected):
    with pytest.raises(ValueError):
        CityLearnEnv(schema_with_contract(tmp_path,selected=selected),episode_time_steps=4)


def test_hidden_contract_applies_without_events_enabled(tmp_path):
    env=CityLearnEnv(schema_with_contract(tmp_path,enabled=False),episode_time_steps=4,export_kpis_on_episode_end=False)
    try:
        obs,_=env.reset()
        assert 'runtime_status' not in obs['meta']
        assert np.all(obs['tables']['district']==-9999)
    finally:env.close()


def test_known_fault_mode_remains_explicit_and_physics_matches_hidden(tmp_path):
    known_path=tmp_path/'known';known_path.mkdir()
    hidden_path=tmp_path/'hidden';hidden_path.mkdir()
    known=CityLearnEnv(schema_with_contract(known_path,mode='known_faults'),episode_time_steps=4,random_seed=0,export_kpis_on_episode_end=False)
    hidden=CityLearnEnv(schema_with_contract(hidden_path),episode_time_steps=4,random_seed=0,export_kpis_on_episode_end=False)
    try:
        obs,_=known.reset();hidden.reset()
        assert obs['meta']['robustness']['active_event_ids']==['secret-fault-id']
        assert known.get_metadata()['robustness']['agent_observation_contract']['fault_labels_visible']
        while not known.terminated:
            known.step(_zero_actions(known));hidden.step(_zero_actions(hidden))
        np.testing.assert_allclose(known.net_electricity_consumption,hidden.net_electricity_consumption)
        assert known._provenance_service.summary()==hidden._provenance_service.summary()
    finally:known.close();hidden.close()


def test_hidden_contract_requires_entity_and_declared_features(tmp_path):
    schema=schema_with_contract(tmp_path)
    schema['interface']='flat'
    with pytest.raises(ValueError,match='entity'):
        CityLearnEnv(schema,episode_time_steps=4)
    schema['interface']='entity'
    schema['robustness']['agent_observation_contract']['features']={}
    with pytest.raises(ValueError,match='allowlist'):
        CityLearnEnv(schema,episode_time_steps=4)


def test_distinct_storage_and_vehicle_soc_are_independent_measurements(tmp_path):
    schema=schema_with_contract(tmp_path,selected={'storage':['soc'],'ev':['soc']})
    env=CityLearnEnv(schema,episode_time_steps=4,export_kpis_on_episode_end=False)
    try:
        obs,_=env.reset()
        for table in ('storage','ev'):
            col=env.entity_specs['tables'][table]['features'].index('soc')
            assert np.all(obs['tables'][table][:,col]!=-9999)
    finally:env.close()


def test_alias_check_uses_actual_episode_window(tmp_path):
    import pandas as pd
    from pathlib import Path
    schema=schema_with_contract(tmp_path)
    p=Path(schema['root_directory'])/schema['robustness']['events_file']
    frame=pd.read_csv(p)
    row=_event(event_id='outside-window',target_feature='load_power_kw',start=6,end=6)
    import csv
    with p.open('a',newline='') as stream:
        csv.DictWriter(stream,fieldnames=list(frame.columns)).writerow(row)
    env=CityLearnEnv(schema,episode_time_steps=4,export_kpis_on_episode_end=False)
    try:
        obs,_=env.reset()
        assert 'robustness' not in obs['meta']
    finally:env.close()


def test_wildcard_pv_fault_cannot_be_bypassed_through_building_alias(tmp_path):
    import pandas as pd
    from pathlib import Path
    schema=schema_with_contract(tmp_path,selected={'building':['pv_energy_kwh_step']})
    p=Path(schema['root_directory'])/schema['robustness']['events_file']
    pd.DataFrame([_event(target_type='pv',target_feature='*',mode='missing')]).to_csv(p,index=False)
    with pytest.raises(ValueError,match='uncorrupted alternate'):
        CityLearnEnv(schema,episode_time_steps=4)


def test_pv_capacity_factor_cannot_bypass_noisy_power_channel(tmp_path):
    import pandas as pd
    from pathlib import Path
    schema=schema_with_contract(tmp_path,selected={'pv':['generation_capacity_factor_ratio']})
    p=Path(schema['root_directory'])/schema['robustness']['events_file']
    pd.DataFrame([_event(target_type='pv',target_feature='generation_power_kw',mode='noise',std=.1)]).to_csv(p,index=False)
    with pytest.raises(ValueError,match='uncorrupted alternate'):
        CityLearnEnv(schema,episode_time_steps=4)
