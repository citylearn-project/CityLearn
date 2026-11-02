"""Explicit agent input contracts; audit metadata stays available to the researcher."""

DEFINITION_VERSION = 'agent-observation-contract-v1'
# Direct alternate representations of the same measurement. This is not a model
# of inference through independent sensors or the system's physical equations.
ALIASES = (
    {('building', f) for f in ('non_shiftable_load', 'load_power_kw', 'load_energy_kwh_step')},
    {('building', f) for f in ('solar_generation', 'pv_power_kw', 'pv_energy_kwh_step')}
    | {('pv', f) for f in ('generation_power_kw', 'generation_energy_kwh_step', 'generation_capacity_factor_ratio')},
    {('storage', f) for f in ('soc', 'soc_ratio', 'electrical_storage_soc_ratio', 'energy_to_full_kwh', 'energy_available_kwh', 'usable_soc_ratio', 'charge_headroom_ratio', 'discharge_available_ratio')}
    | {('building', f) for f in ('electrical_storage_soc', 'electrical_storage_soc_ratio')},
    {('ev', f) for f in ('soc', 'soc_ratio', 'energy_to_full_kwh', 'energy_available_kwh')}
    | {('charger', f) for f in ('connected_ev_soc', 'connected_ev_energy_to_full_kwh', 'connected_ev_energy_available_kwh', 'energy_to_required_soc_kwh', 'required_average_power_kw', 'avg_power_to_departure_kw', 'departure_energy_margin_kwh')},
) + tuple({(table, direction+'_power_kw'), (table, direction+'_energy_kwh_step')}
          for table in ('building', 'district') for direction in ('net', 'import', 'export'))



def configuration(env):
    config = (env.schema.get('robustness') or {}).get('agent_observation_contract') or {}
    mode = config.get('mode', 'known_faults')
    if mode not in ('known_faults', 'hidden_faults'):
        raise ValueError('agent_observation_contract.mode must be known_faults or hidden_faults')
    features = config.get('features', {})
    if mode == 'hidden_faults':
        if env.interface != 'entity':
            raise ValueError('hidden_faults currently requires the entity interface')
        if not isinstance(features, dict) or not features:
            raise ValueError('hidden_faults requires an explicit nonempty features allowlist')
        for names in features.values():
            if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
                raise ValueError('agent observation features must be lists of feature names')
            if any(n.startswith(('robustness_', 'fault_')) for n in names):
                raise ValueError('hidden_faults cannot expose diagnostic fault features')
        for group in ALIASES:
            selected = [(table, n) for table, names in features.items() for n in names if (table, n) in group]
            if len(selected) > 1:
                raise ValueError('hidden_faults contains equivalent measurement channels: '+str(selected))
    return dict(definition_version=DEFINITION_VERSION, mode=mode, features=features,
                masked_value=-9999.0, unlisted_features='masked' if mode == 'hidden_faults' else 'available',
                fault_labels_visible=mode == 'known_faults')


def validate(service):
    contract = configuration(service.env)
    if contract['mode'] != 'hidden_faults':
        return
    tables = service.env.entity_specs['tables']
    for table, names in contract['features'].items():
        declared = tables
        if (table not in tables or set(names)-set(tables[table]['features'])) and service.env.topology_mode == 'dynamic':
            declared = service._target_validator().env.entity_specs['tables']
        if table not in declared or set(names)-set(declared[table]['features']):
            raise ValueError(f'Unknown agent observation feature in table {table}')
    # An uncorrupted alternate channel cannot replace a targeted measurement.
    selected = [(t, f) for t, names in contract['features'].items() for f in names]
    tracker = service.env.episode_tracker
    for event in service._events:
        if event.end_time_step < tracker.episode_start_time_step or event.start_time_step > tracker.episode_end_time_step:
            continue
        telemetry = event.module == 'asset' and event.target_feature in service.TELEMETRY_FEATURES
        if (event.module not in ('observation', 'forecast') and not telemetry) or not service._module_enabled(event.module):
            continue
        for group in ALIASES:
            targets = {pair for pair in group if pair[0] == event.target_type
                       and (telemetry or service._observation_feature_allowed(event, pair[1]))}
            if targets:
                for pair in selected:
                    if pair in group and pair not in targets:
                        raise ValueError('hidden_faults selects an uncorrupted alternate to '+event.target_feature)



def apply(service, payload):
    contract = configuration(service.env)
    if contract['mode'] != 'hidden_faults':
        return payload
    validate(service)
    specs = service.env.entity_specs['tables']
    for table, values in payload['tables'].items():
        allowed = set(contract['features'].get(table, []))
        features = specs[table]['features']
        columns = [i for i, name in enumerate(features) if name not in allowed]
        if columns:
            values[:, columns] = contract['masked_value']
    # Build a safe metadata allowlist, rather than chasing future diagnostic keys.
    meta = payload.get('meta', {})
    payload['meta'] = {k: meta[k] for k in ('time_step', 'endogenous_time_step', 'seconds_per_time_step',
                                         'spec_version', 'temporal_semantics', 'topology_version') if k in meta}
    payload['meta']['agent_observation_contract'] = {'definition_version': DEFINITION_VERSION, 'mode': 'hidden_faults'}
    return payload
