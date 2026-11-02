"""Portable input discovery and declared capability boundaries."""

def test_auditor_reads_bom_and_discovers_evaluation_entries(tmp_path):
    from scripts.audit.audit_datasets import discover_schema_paths, read_json
    folder = tmp_path/'dataset'
    folder.mkdir()
    (folder/'schema.json').write_text('{}')
    evaluation = folder/'evaluation'
    evaluation.mkdir()
    path = evaluation/'native.json'
    path.write_text('\ufeff{"root_directory": ".."}', encoding='utf-8')
    assert discover_schema_paths(tmp_path) == [path]
    assert read_json(path)['root_directory'] == '..'


def test_capability_report_does_not_hide_runtime_failures():
    from citylearn.internal.capabilities import unsupported_reason
    assert unsupported_reason({'demand_response': {'enabled': True}}, 'flat')
    assert unsupported_reason({'demand_response': {'enabled': True}}, 'entity') is None
    assert unsupported_reason({'buildings': {'a': {'escalators': {'e': {}}}}}, 'entity')
    assert unsupported_reason({'buildings': {'a': {'chargers': {'c': {}}}}}, 'entity') is None


def test_dynamic_auditor_uses_runtime_singleton_ids_and_appliance_keys():
    from scripts.audit.audit_datasets import validate_dynamic_events
    schema = {'topology_mode': 'dynamic', 'buildings': {'A': {
        'electrical_storage': {}, 'pv': {}, 'deferrable_appliances': {'washer': {}}}},
        'topology_events': [
            {'id': 'a', 'time_step': 1, 'operation': 'add_asset', 'target_member_id': 'A',
             'target_asset_type': 'electrical_storage', 'target_asset_id': 'BESS-NEW', 'source_asset_id': 'template'},
            {'id': 'b', 'time_step': 2, 'operation': 'remove_asset', 'target_member_id': 'A',
             'target_asset_type': 'deferrable_appliance', 'target_asset_id': 'washer'}]}
    assert validate_dynamic_events(schema)['status'] == 'pass'
    schema['topology_events'][1]['target_asset_id'] = 'missing'
    assert validate_dynamic_events(schema)['status'] == 'fail'
