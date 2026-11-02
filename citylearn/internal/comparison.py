"""Portable pairing evidence and explicit interpretation of experiment differences."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

DEFINITION_VERSION = 'paired-experiment-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def inventory(env):
    """Boundary snapshots, not a financial credit for unused stored energy."""
    rows = []
    for building in env.buildings:
        battery = building.electrical_storage
        if battery is not None and battery.capacity > 0:
            rows.append(dict(kind='active_stationary', id=building.name, capacity_kwh=float(battery.capacity),
                             energy_kwh=float(battery.energy_init)))
    for ev in getattr(env, '_all_electric_vehicles', None) or env.electric_vehicles:
        rows.append(dict(kind='fleet_ev_including_away', id=ev.name, capacity_kwh=float(ev.battery.capacity),
                         energy_kwh=float(ev.battery.energy_init)))
    return sorted(rows, key=lambda r: (r['kind'], r['id']))


def canonical(value, root):
    if isinstance(value, dict):
        return {k: canonical(v, root) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v, root) for v in value]
    if isinstance(value, str) and root and value.startswith(root.rstrip('/')+'/'):
        return value[len(root.rstrip('/'))+1:]
    return value


def context(env, data_files):
    from citylearn import __version__
    from citylearn.internal.observation_contract import configuration
    schema = deepcopy(env.schema)
    root = str(Path(schema.get('root_directory') or '.').resolve())
    ignored = {'root_directory', 'reward_function', 'central_agent', 'interface', 'shared_observations',
               'observations', 'actions', 'observation_bundles', 'community_market', 'random_seed',
               'render', 'render_mode', 'render_directory', 'render_file_format', 'debug_timing',
               'metrics_log_interval', 'check_observation_limits', 'physics_invariant_checks',
               'export_kpis_on_episode_end', 'chargers_observations_helper', 'chargers_actions_helper',
               'chargers_shared_observations_helper', 'deferrable_appliance_observations_helper',
               'deferrable_appliance_actions_helper', 'escalator_observations_helper', 'escalator_actions_helper'}
    physical = {k: v for k, v in schema.items() if k not in ignored and not k.startswith('_')}
    if isinstance(physical.get('robustness'), dict):
        physical['robustness'].pop('agent_observation_contract', None)
    observation = {k: schema.get(k) for k in ('observations', 'observation_bundles', 'derived_forecasts')}
    observation.update(interface=env.interface, agent_contract=configuration(env))
    source_root = Path(__file__).resolve().parents[1]
    code = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source_root.rglob('*.py'))}
    tracker = env.episode_tracker
    from citylearn.internal.temporal import axis_metadata, runtime_versions
    axis = axis_metadata(env)
    temporal = {key:axis[key] for key in ('definition_version','initialization_seed','clock_source','dataset_seconds_per_time_step','control_seconds_per_time_step','terminal_padding','data_noise_generator','episode_split_rng')}
    return dict(temporal=temporal,definition_version=DEFINITION_VERSION,
                engine=dict(version=__version__, source_sha256=digest(code), runtime_versions=runtime_versions()),
                physical_configuration_sha256=digest(canonical(physical, root)),
                data_files_sha256={canonical(k, root): v for k, v in data_files.items()},
                episode_start_time_step=tracker.episode_start_time_step,
                episode_end_time_step=tracker.episode_end_time_step,
                completed_intervals=env._provenance_service.steps,
                seconds_per_time_step=env.seconds_per_time_step, time_step_ratio=env.time_step_ratio,
                random_seed=env.random_seed, ev_drift_seed=getattr(env, '_ev_drift_seed', None),
                initial_inventory=getattr(env, '_comparison_initial_inventory', None),
                service_tolerances=dict(ev_within=env.ev_departure_within_tolerance,
                                        ev_service=env.ev_departure_service_tolerance),
                observation=canonical(observation, root),
                market=env.get_metadata()['community_market'])


def native_reference(env):
    from citylearn import __version__
    from citylearn.agents.baseline import BusinessAsUsualAgent
    result = dict(implementation='citylearn.agents.baseline.BusinessAsUsualAgent',
                  simulator_version=__version__, definition_version=BusinessAsUsualAgent.DEFINITION_VERSION,
                  observation_access='privileged_simulator_state', evaluated=False, resolved_parameters=None)
    key = (env.episode_tracker.episode, int(env.time_step))
    cached = getattr(env, '_business_as_usual_baseline_cache', {}).get(key)
    if cached is not None:
        result.update(getattr(cached.env, '_native_reference_metadata', {}))
        result['evaluated'] = True
    return result


def load_kpis(path):
    import pandas as pd
    frame = pd.read_parquet(path) if Path(path).suffix == '.parquet' else pd.read_csv(path)
    if 'KPI' in frame:
        frame = frame.melt(id_vars='KPI', var_name='name', value_name='value').rename(columns={'KPI': 'cost_function'})
    elif not {'cost_function', 'name', 'value'} <= set(frame):
        raise ValueError('Expected a V2 KPI export or long-form cost_function/name/value columns')
    if frame.duplicated(['name', 'cost_function']).any():
        raise ValueError('Duplicate KPI/name rows cannot be compared safely')
    return {(r['name'], r['cost_function']): (None if pd.isna(r['value']) or not math.isfinite(float(r['value'])) else float(r['value']))
            for r in frame.to_dict('records')}


def compare_manifests(left, right, mode='controller'):
    if mode not in ('controller', 'sharing'):
        raise ValueError('Comparison mode must be controller or sharing')
    a, b = left.get('comparison_context'), right.get('comparison_context')
    missing, mismatches, declared = [], [], []
    if not a or not b or a.get('definition_version') != DEFINITION_VERSION or b.get('definition_version') != DEFINITION_VERSION:
        missing.append('versioned_comparison_context')
    else:
        if a.get('temporal') != b.get('temporal'):
            if 'temporal' not in a or 'temporal' not in b:missing.append('temporal')
            else:mismatches.append('temporal')
        required = ('engine', 'physical_configuration_sha256', 'data_files_sha256', 'episode_start_time_step',
                    'episode_end_time_step', 'completed_intervals', 'seconds_per_time_step', 'time_step_ratio',
                    'random_seed', 'ev_drift_seed', 'initial_inventory', 'service_tolerances', 'observation', 'market')
        for key in required:
            if key not in a or key not in b or (key not in ('time_step_ratio',) and (a[key] is None or b[key] is None)):
                missing.append(key)
            elif key == 'market' and mode == 'sharing':
                toggles = {'enabled', 'local_trading_enabled'}
                aa, bb = ({k: v for k, v in x.items() if k not in toggles} for x in (a[key], b[key]))
                if aa != bb:
                    mismatches.append('market_prices_or_settlement')
                if a[key] == b[key]:
                    missing.append('sharing_toggle_difference')
                else:
                    declared.append('sharing_enabled_flags')
            elif a[key] != b[key]:
                mismatches.append(key)
    for manifest in (left, right):
        identity = manifest.get('controller_identity') or {}
        if not identity.get('implementation') or not identity.get('version') or identity.get('parameters') is None or not identity.get('observation_access'):
            if 'controller_identity' not in missing:
                missing.append('controller_identity')
        if manifest.get('input_file_changes') and 'input_changed_after_load' not in missing:
            missing.append('input_changed_after_load')
        if manifest.get('unresolved_file_references') or not manifest.get('data_files_sha256'):
            if 'data_file_evidence' not in missing:
                missing.append('data_file_evidence')
    if (left.get('controller_identity') and right.get('controller_identity')
            and left['controller_identity'].get('observation_access') != right['controller_identity'].get('observation_access')):
        mismatches.append('controller_observation_access')
    if mode == 'sharing' and left.get('controller_identity') and right.get('controller_identity') and left['controller_identity'] != right['controller_identity']:
        mismatches.append('controller_identity')
    if left.get('final_inventory') is None or right.get('final_inventory') is None:
        missing.append('final_inventory')
    for key in ('business_as_usual_reference', 'energy_accounting', 'deferrable_service_audit'):
        if not left.get(key) or not right.get(key):
            missing.append(key)
        elif left[key] != right[key]:
            mismatches.append(key)
    status = 'incompatible' if mismatches else ('unknown' if missing else 'paired')
    return dict(definition_version=DEFINITION_VERSION, mode=mode, status=status,
                permitted_claim=('controller_difference' if mode == 'controller' else 'sharing_difference') if status == 'paired' else None,
                mismatches=sorted(set(mismatches)), missing_evidence=sorted(set(missing)), declared_differences=declared,
                left_controller=left.get('controller_identity'), right_controller=right.get('controller_identity'),
                baseline_reference=left.get('business_as_usual_reference'),
                final_inventory=dict(left=left.get('final_inventory'), right=right.get('final_inventory')),
                inventory_differences=inventory_differences(left.get('final_inventory'), right.get('final_inventory')),
                interpretation=dict(legacy_solar='instantaneous_absorption_includes_charging',
                    useful_solar='provenance_to_final_building_load_or_mobility; stored_energy_reported_separately',
                    emissions='use_external_purchase_emissions_for_external_carbon; internal_allocation_is_separate',
                    service='read_EV_and_appliance_service_with_coverage_and_final_inventory',
                    cost='cost_delta_alone_does_not_prove_equal_service_or_equal_final_inventory'))


def compare_exports(left_path, right_path, mode='controller'):
    paths = [Path(left_path), Path(right_path)]
    manifests = []
    for p in paths:
        manifest_path = p.with_suffix('.manifest.json')
        manifests.append(json.loads(manifest_path.read_text()) if manifest_path.exists() else {})
    report = compare_manifests(*manifests, mode=mode)
    values = [load_kpis(p) for p in paths]
    rows = []
    for name, key in sorted(set(values[0]) | set(values[1])):
        a, b = (v.get((name, key)) for v in values)
        rows.append(dict(name=name, kpi=key, left=a, right=b,
                         delta_right_minus_left=b-a if a is not None and b is not None else None))
    report['kpis'] = rows
    report['outcome_summary'] = [r for r in rows if r['name']=='District' and any(
        text in r['kpi'] for text in ('cost_total_control', 'departure_audit_', 'deferrable_appliance_audit_',
                                     'provenance_pv_useful_', 'provenance_external_purchase_emissions'))]
    report['observed_differences'] = [r['kpi'] for r in report['outcome_summary']
                                      if r['delta_right_minus_left'] is not None and abs(r['delta_right_minus_left'])>1e-7]
    report['service_and_inventory_must_be_checked'] = True
    return report


def inventory_differences(left, right):
    maps = [{(r['kind'], r['id']): r['energy_kwh'] for r in (rows or [])} for rows in (left, right)]
    return [dict(kind=kind, id=name, left_kwh=maps[0].get((kind,name)), right_kwh=maps[1].get((kind,name)),
                 delta_right_minus_left_kwh=(maps[1][kind,name]-maps[0][kind,name])
                 if (kind,name) in maps[0] and (kind,name) in maps[1] else None)
            for kind,name in sorted(set(maps[0])|set(maps[1]))]
