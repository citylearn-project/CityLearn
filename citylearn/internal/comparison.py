"""Portable pairing evidence and explicit interpretation of experiment differences."""
from copy import deepcopy
import hashlib
import json
import math
import os
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


def relative_to_root(value, root, path=os.path):
    """Return ``value`` relative to ``root`` with ``/`` separators, or None if it is not under ``root``.

    ``path`` is the platform path module (``ntpath`` or ``posixpath``; tests pass both). On Windows
    ``/`` and ``\\`` are the same separator and the case of ``root`` is ignored, so the dataset root
    is removed however it is spelled; the rest keeps its text (``file_key`` gives input files their
    on-disk spelling). With ``posixpath`` this is exactly the string-prefix test of
    ``paired-experiment-v1``, so POSIX evidence does not change.
    """
    if path.altsep:
        value, root = value.replace(path.altsep, path.sep), root.replace(path.altsep, path.sep)
    prefix = root.rstrip(path.sep) + path.sep
    if path.normcase(value[:len(prefix)]) != path.normcase(prefix):
        return None
    return value[len(prefix):].replace(path.sep, '/')


def file_key(reference, resolved, root, path=os.path):
    """Manifest key of the input file that the schema string ``reference`` names.

    ``resolved`` is the file's resolved path, as ``snapshot_inputs`` records it, and ``root`` the
    resolved dataset root. If ``reference`` spells ``resolved`` apart from what the platform ignores
    (on Windows: ``/`` versus ``\\`` and letter case), the key is the file's path below ``root`` as
    the filesystem spells it: on Windows ``sub\\Weather.csv`` and ``sub/weather.csv`` both become
    ``sub/weather.csv``. Other spellings (``.`` or ``..`` components, repeated separators, links,
    8.3 short names) keep their text, with ``\\`` written as ``/`` on Windows, so two of them that
    name one file may fail to pair. With ``posixpath`` the key is exactly the
    ``paired-experiment-v1`` text.
    """
    if path.normcase(path.join(root, reference)) == path.normcase(resolved):
        relative = relative_to_root(resolved, root, path)
        if relative is not None:
            return relative
    relative = relative_to_root(reference, root, path)
    if relative is not None:
        return relative
    return reference.replace(path.sep, '/') if path.altsep else reference


def canonical(value, root, files=None):
    """``value`` without machine-specific paths: input-file references in ``files`` become their
    ``file_key`` and other paths under ``root`` become relative to it."""
    if isinstance(value, dict):
        return {k: canonical(v, root, files) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v, root, files) for v in value]
    if isinstance(value, str) and files and value in files:
        return files[value]
    if isinstance(value, str) and root:
        relative = relative_to_root(value, root)
        if relative is not None:
            return relative
    return value


def source_sha256(source_root):
    """Digest of the engine's Python source that does not depend on how it was checked out.

    Keys are POSIX paths relative to ``source_root``. Line endings are normalised the way Python
    reads source (CRLF and lone CR become LF; the compiled code is identical), so a Windows
    checkout with ``core.autocrlf`` hashes like the committed blobs and the wheel. Files without
    CR bytes, which includes every committed engine file, hash exactly as before.
    """
    source_root = Path(source_root)
    code = {p.relative_to(source_root).as_posix():
            hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')).hexdigest()
            for p in sorted(source_root.rglob('*.py'))}
    return digest(code)


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
    snapshot = getattr(env, '_input_snapshot', None) or {}
    files = {name: file_key(name, row['path'], root) for name, row in snapshot.items()}
    tracker = env.episode_tracker
    from citylearn.internal.temporal import axis_metadata, runtime_versions
    axis = axis_metadata(env)
    temporal = {key:axis[key] for key in ('definition_version','initialization_seed','clock_source','dataset_seconds_per_time_step','control_seconds_per_time_step','terminal_padding','data_noise_generator','episode_split_rng')}
    return dict(temporal=temporal,definition_version=DEFINITION_VERSION,
                engine=dict(version=__version__, source_sha256=source_sha256(Path(__file__).resolve().parents[1]),
                            runtime_versions=runtime_versions()),
                physical_configuration_sha256=digest(canonical(physical, root, files)),
                data_files_sha256={canonical(k, root, files): v for k, v in data_files.items()},
                episode_start_time_step=tracker.episode_start_time_step,
                episode_end_time_step=tracker.episode_end_time_step,
                completed_intervals=env._provenance_service.steps,
                seconds_per_time_step=env.seconds_per_time_step, time_step_ratio=env.time_step_ratio,
                random_seed=env.random_seed, ev_drift_seed=getattr(env, '_ev_drift_seed', None),
                initial_inventory=getattr(env, '_comparison_initial_inventory', None),
                service_tolerances=dict(ev_within=env.ev_departure_within_tolerance,
                                        ev_service=env.ev_departure_service_tolerance),
                observation=canonical(observation, root, files),
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


# Charger parameters that `Charger` setters can change after loading.
CHARGER_ATTRIBUTES = ('efficiency', 'max_charging_power', 'min_charging_power', 'max_discharging_power',
                      'min_discharging_power', 'charge_efficiency_curve', 'discharge_efficiency_curve')


def _exact(value):
    """Plain copy of `value` whose `==` is exact, NaN included."""
    if isinstance(value, dict):
        return {str(k): _exact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_exact(v) for v in value]
    if hasattr(value, 'tolist'):
        return _exact(value.tolist())
    if isinstance(value, float) and math.isnan(value):
        return 'nan'
    return value


def reference_configuration(env):
    """Building order and the per-building settings that the native BAU reference must reproduce.

    The reference is rebuilt from the schema and the constructor arguments. This records what they
    resolve to for each building, in the env's building order: the outage setting, the active actions
    and the chargers' power limits and efficiencies, all of which setters can change after loading.
    """
    return [dict(
        name=building.name,
        simulate_power_outage=bool(building.simulate_power_outage),
        active_actions=sorted(building.active_actions),
        chargers={str(charger.charger_id): _exact({k: getattr(charger, k, None) for k in CHARGER_ATTRIBUTES})
                  for charger in building.electric_vehicle_chargers or []},
    ) for building in getattr(env, '_all_buildings', None) or env.buildings]


def configuration_differences(left, right):
    """`setting (left vs right)` for each :func:`reference_configuration` entry that differs."""
    names = [[row['name'] for row in rows] for rows in (left, right)]
    if names[0] != names[1]:
        return [f'building order ({names[0]!r} vs {names[1]!r})']
    differences = []
    for a, b in zip(left, right):
        differences.extend(f"{a['name']}: {key} ({a[key]!r} vs {b[key]!r})"
                           for key in ('simulate_power_outage', 'active_actions') if a[key] != b[key])
        for charger in sorted(set(a['chargers']) | set(b['chargers'])):
            x, y = a['chargers'].get(charger), b['chargers'].get(charger)
            if x is None or y is None:
                differences.append(f"{a['name']}/charger {charger}: "
                                   f"{'absent' if x is None else 'present'} vs {'absent' if y is None else 'present'}")
                continue
            differences.extend(f"{a['name']}/charger {charger}: {k} ({x.get(k)!r} vs {y.get(k)!r})"
                               for k in CHARGER_ATTRIBUTES if x.get(k) != y.get(k))
    return differences
