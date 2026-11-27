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


EQUIPMENT_SLOTS = ('cooling_device', 'heating_device', 'dhw_device', 'cooling_storage', 'heating_storage',
                   'dhw_storage', 'electrical_storage', 'pv')
CHARGER_ATTRIBUTES = ('efficiency', 'max_charging_power', 'min_charging_power', 'max_discharging_power',
                      'min_discharging_power', 'charge_efficiency_curve', 'discharge_efficiency_curve')
# Identity and window bookkeeping: they differ between envs that simulate the same devices.
_NOT_EQUIPMENT = frozenset({'uid', 'random_seed', 'simulation_time_steps'})


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


def equipment(env):
    """Sizes and parameters of every simulated device, keyed by building and device.

    :func:`inventory` records stored energy; this records what autosizing and random draws resolve
    (heat pump and heater power, storage capacity, PV, battery curves, chargers, appliances, EV
    batteries), so a reference can show that it simulates the same devices as the evaluated env.
    """
    def parameters(device):
        return _exact({'type': type(device).__name__, **{
            k: v for k, v in device.get_metadata().items() if k not in _NOT_EQUIPMENT}})

    devices = {}
    for building in env.buildings:
        for slot in EQUIPMENT_SLOTS:
            device = getattr(building, slot, None)
            if device is not None:
                devices[f'{building.name}/{slot}'] = parameters(device)
        for i, device in enumerate(building.deferrable_appliances or []):
            devices[f'{building.name}/deferrable_appliances[{i}]'] = parameters(device)
        for i, device in enumerate(building.escalators or []):
            devices[f'{building.name}/escalators[{i}]'] = parameters(device)
        for charger in building.electric_vehicle_chargers or []:
            devices[f'{building.name}/charger {charger.charger_id}'] = _exact(
                {k: getattr(charger, k, None) for k in CHARGER_ATTRIBUTES})
    for ev in getattr(env, '_all_electric_vehicles', None) or env.electric_vehicles:
        devices[f'{ev.name}/battery'] = parameters(ev.battery)
    return devices


def equipment_differences(left, right):
    """`device: parameter (left vs right)` for each parameter that differs, devices in order."""
    differences = []
    for device in sorted(set(left) | set(right)):
        a, b = left.get(device), right.get(device)
        if a is None or b is None:
            differences.append(f"{device}: {'absent' if a is None else 'present'} vs {'absent' if b is None else 'present'}")
            continue
        differences.extend(f'{device}: {k} ({a.get(k)!r} vs {b.get(k)!r})'
                           for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k))
    return differences


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
    from citylearn.internal.electrical_limits import serialize_district_electrical_service_config
    from citylearn.internal.evaluation_window import serialize_evaluation_window_config
    from citylearn.internal.observation_contract import configuration
    schema = deepcopy(env.schema)
    root = str(Path(schema.get('root_directory') or '.').resolve())
    ignored = {'root_directory', 'reward_function', 'central_agent', 'interface', 'shared_observations',
               'observations', 'actions', 'observation_bundles', 'community_market', 'random_seed', 'random_stream_version',
               'render', 'render_mode', 'render_directory', 'render_file_format', 'debug_timing',
               'metrics_log_interval', 'check_observation_limits', 'physics_invariant_checks',
               'export_kpis_on_episode_end', 'evaluation_window', 'district_electrical_service',
               'chargers_observations_helper', 'chargers_actions_helper',
               'chargers_shared_observations_helper', 'deferrable_appliance_observations_helper',
               'deferrable_appliance_actions_helper', 'escalator_observations_helper', 'escalator_actions_helper'}
    # The feeder setting only monitors (nothing simulated changes), so, like the evaluation window,
    # it is compared on its own in compare_manifests() and kept out of the physical hash.
    physical = {k: v for k, v in schema.items() if k not in ignored and not k.startswith('_')}
    effective_feeder = serialize_district_electrical_service_config(
        getattr(env, '_district_electrical_service_parsed', None)
    )
    if isinstance(physical.get('robustness'), dict):
        physical['robustness'].pop('agent_observation_contract', None)
    observation = {k: schema.get(k) for k in ('observations', 'observation_bundles', 'derived_forecasts')}
    observation.update(interface=env.interface, agent_contract=configuration(env))
    snapshot = getattr(env, '_input_snapshot', None) or {}
    files = {name: file_key(name, row['path'], root) for name, row in snapshot.items()}
    tracker = env.episode_tracker
    from citylearn.internal.temporal import axis_metadata, runtime_versions
    axis = axis_metadata(env)
    temporal = {key:axis[key] for key in ('definition_version','initialization_seed','clock_source','dataset_seconds_per_time_step','control_seconds_per_time_step','terminal_padding','data_noise_generator','episode_split_rng','random_stream_version')}
    return dict(temporal=temporal,definition_version=DEFINITION_VERSION,
                physics_version=getattr(env, 'physics_version', None),
                baseline_version=getattr(env, 'baseline_version', None),
                ev_soc_carryover=bool(getattr(env, 'ev_soc_carryover', False)),
                engine=dict(version=__version__, source_sha256=source_sha256(Path(__file__).resolve().parents[1]),
                            runtime_versions=runtime_versions()),
                physical_configuration_sha256=digest(canonical(physical, root, files)),
                data_files_sha256={canonical(k, root, files): v for k, v in data_files.items()},
                episode_start_time_step=tracker.episode_start_time_step,
                episode_end_time_step=tracker.episode_end_time_step,
                completed_intervals=env._provenance_service.steps,
                seconds_per_time_step=env.seconds_per_time_step, time_step_ratio=env.time_step_ratio,
                random_seed=env.random_seed, ev_drift_seed=getattr(env, '_ev_drift_seed', None),
                random_stream_namespace=getattr(env, 'random_stream_namespace', None),
                initial_inventory=getattr(env, '_comparison_initial_inventory', None),
                service_tolerances=dict(ev_within=env.ev_departure_within_tolerance,
                                        ev_service=env.ev_departure_service_tolerance),
                observation=canonical(observation, root, files),
                market=env.get_metadata()['community_market'],
                district_electrical_service=effective_feeder,
                evaluation_window=serialize_evaluation_window_config(getattr(env, '_evaluation_window_parsed', None)))


def native_reference(env):
    from citylearn import __version__
    from citylearn.agents.baseline import BusinessAsUsualAgent
    result = dict(implementation='citylearn.agents.baseline.BusinessAsUsualAgent',
                  simulator_version=__version__,
                  definition_version=BusinessAsUsualAgent.definition(
                      getattr(env, 'business_as_usual_ev_charge_target', 'full'), BusinessAsUsualAgent.hvac_mode_for(env))[1],
                  observation_access='entity_observations', evaluated=False, resolved_parameters=None)
    key = (env.episode_tracker.episode, int(env.time_step))
    cached = getattr(env, '_business_as_usual_baseline_cache', {}).get(key)
    if (cached is not None and cached.ev_charge_target == getattr(env, 'business_as_usual_ev_charge_target', 'full')
            and cached.hvac == BusinessAsUsualAgent.hvac_mode_for(env)):
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
    if 'community_id' in frame:
        # Multi-community exports repeat each name (e.g. District) once per community.
        frame = frame.assign(name=frame['community_id'].astype(str) + ':' + frame['name'].astype(str))
    if frame.duplicated(['name', 'cost_function']).any():
        raise ValueError('Duplicate KPI/name rows cannot be compared safely')
    return {(r['name'], r['cost_function']): (None if pd.isna(r['value']) or not math.isfinite(float(r['value'])) else float(r['value']))
            for r in frame.to_dict('records')}


def _is_evaluation_window_kpi(kpi_name):
    text = str(kpi_name or '')
    return '_energy_grid_window_average_power_' in text or '_ev_window_net_exchange_' in text


def _is_feeder_kpi(kpi_name):
    return '_energy_grid_feeder_limit_' in str(kpi_name or '')


def _monitor_status(left, right):
    """'disabled', 'paired', 'one_sided' or 'incompatible' for two post-processing settings."""
    left_enabled, right_enabled = bool(left.get('enabled')), bool(right.get('enabled'))
    if not left_enabled and not right_enabled:
        return 'disabled'
    if left_enabled and right_enabled:
        return 'paired' if left == right else 'incompatible'
    return 'one_sided'


# The manifest entries that compare_manifests() reads; a portfolio manifest keeps them for each community.
MANIFEST_EVIDENCE_KEYS = (
    'comparison_context', 'evaluation_window', 'district_electrical_service', 'controller_identity',
    'input_file_changes', 'unresolved_file_references', 'data_files_sha256', 'final_inventory',
    'business_as_usual_reference', 'energy_accounting', 'deferrable_service_audit', 'kpi_export',
)
MULTI_COMMUNITY_KIND = 'multi_community'


def manifest_evidence(manifest):
    """The part of an export manifest that :func:`compare_manifests` reads."""
    return {key: deepcopy(manifest.get(key)) for key in MANIFEST_EVIDENCE_KEYS if key in manifest}


def _compare_portfolio_manifests(left, right, mode):
    """Compare two `MultiCommunityEnv` export manifests community by community.

    The portfolios pair when they have the same communities, weights and portfolio rules and every community
    pairs with its namesake. A community's mismatches and missing evidence are listed as
    ``<community_id>:<item>``.
    """
    kinds = [manifest.get('kind') for manifest in (left, right)]
    mismatches, missing, declared, communities = [], [], [], {}
    if kinds[0] != kinds[1]:
        mismatches.append('export_kind')
    else:
        for key in ('community_ids', 'weights', 'portfolio_aggregation'):
            if left.get(key) is None or right.get(key) is None:
                missing.append(key)
            elif left[key] != right[key]:
                mismatches.append(key)
        a, b = (manifest.get('communities') or {} for manifest in (left, right))
        for community_id in sorted(set(a) & set(b)):
            report = compare_manifests((a[community_id] or {}).get('comparison_evidence') or {},
                                       (b[community_id] or {}).get('comparison_evidence') or {}, mode=mode)
            communities[community_id] = report
            mismatches.extend(f'{community_id}:{item}' for item in report['mismatches'])
            missing.extend(f'{community_id}:{item}' for item in report['missing_evidence'])
            declared.extend(f'{community_id}:{item}' for item in report['declared_differences'])
    status = 'incompatible' if mismatches else ('unknown' if missing else 'paired')
    first = next(iter(communities.values()), {})
    default = dict(status='disabled', comparable=False, left=None, right=None)
    return dict(definition_version=DEFINITION_VERSION, mode=mode, status=status, kind=MULTI_COMMUNITY_KIND,
                permitted_claim=('controller_difference' if mode == 'controller' else 'sharing_difference')
                if status == 'paired' else None,
                mismatches=sorted(set(mismatches)), missing_evidence=sorted(set(missing)),
                declared_differences=declared, communities=communities,
                evaluation_window=first.get('evaluation_window', default),
                district_electrical_service=first.get('district_electrical_service', default),
                left_controller=left.get('controller_identity'), right_controller=right.get('controller_identity'))


def compare_manifests(left, right, mode='controller'):
    if mode not in ('controller', 'sharing'):
        raise ValueError('Comparison mode must be controller or sharing')
    if MULTI_COMMUNITY_KIND in (left.get('kind'), right.get('kind')):
        return _compare_portfolio_manifests(left, right, mode)
    a, b = left.get('comparison_context'), right.get('comparison_context')
    missing, mismatches, declared = [], [], []
    default_window = {'enabled': False, 'start': None, 'end': None, 'timezone': None}
    win_a = (a or {}).get('evaluation_window') or left.get('evaluation_window') or default_window
    win_b = (b or {}).get('evaluation_window') or right.get('evaluation_window') or default_window
    window_status = _monitor_status(win_a, win_b)
    default_feeder = {'enabled': False, 'limits': {'import_kw': None, 'export_kw': None}}
    feeder_a = (a or {}).get('district_electrical_service') or left.get('district_electrical_service') or default_feeder
    feeder_b = (b or {}).get('district_electrical_service') or right.get('district_electrical_service') or default_feeder
    feeder_status = _monitor_status(feeder_a, feeder_b)
    if not a or not b or a.get('definition_version') != DEFINITION_VERSION or b.get('definition_version') != DEFINITION_VERSION:
        missing.append('versioned_comparison_context')
    else:
        if a.get('temporal') != b.get('temporal'):
            if 'temporal' not in a or 'temporal' not in b:missing.append('temporal')
            else:mismatches.append('temporal')
        required = ('physics_version', 'baseline_version', 'engine', 'physical_configuration_sha256', 'data_files_sha256', 'episode_start_time_step',
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
        # The feeder monitor changes no simulated quantity: a run with it and the same run without it
        # differ only in the feeder rows, as for a one-sided evaluation window.
        if feeder_status == 'incompatible':
            mismatches.append('district_electrical_service')
        elif feeder_status == 'one_sided':
            declared.append('district_electrical_service_one_sided')
        if window_status == 'incompatible':
            mismatches.append('evaluation_window')
        elif window_status == 'one_sided':
            declared.append('evaluation_window_one_sided')

        # Exports from before the setting existed ran without it.
        if bool(a.get('ev_soc_carryover', False)) != bool(b.get('ev_soc_carryover', False)):
            mismatches.append('ev_soc_carryover')
        # Two stream namespaces draw different random values from the same seed; exports from before
        # the option existed had none.
        if a.get('random_stream_namespace') != b.get('random_stream_namespace'):
            mismatches.append('random_stream_namespace')
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
    # Rounding changes the exported values; exports from before kpi_export was recorded are not checked.
    exports = [manifest.get('kpi_export') for manifest in (left, right)]
    if all(exports) and exports[0].get('kpi_round_decimals') != exports[1].get('kpi_round_decimals'):
        mismatches.append('kpi_round_decimals')
    status = 'incompatible' if mismatches else ('unknown' if missing else 'paired')
    return dict(definition_version=DEFINITION_VERSION, mode=mode, status=status,
                permitted_claim=('controller_difference' if mode == 'controller' else 'sharing_difference') if status == 'paired' else None,
                mismatches=sorted(set(mismatches)), missing_evidence=sorted(set(missing)), declared_differences=declared,
                evaluation_window=dict(status=window_status, comparable=(window_status == 'paired'), left=win_a, right=win_b),
                district_electrical_service=dict(status=feeder_status, comparable=(feeder_status == 'paired'),
                                                 left=feeder_a, right=feeder_b),
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
    window_status = (report.get('evaluation_window') or {}).get('status')
    feeder_status = (report.get('district_electrical_service') or {}).get('status')
    values = [load_kpis(p) for p in paths]
    rows = []
    unpaired_window_kpis = set()
    unpaired_feeder_kpis = set()
    for name, key in sorted(set(values[0]) | set(values[1])):
        a, b = (v.get((name, key)) for v in values)
        row = dict(name=name, kpi=key, left=a, right=b,
                   delta_right_minus_left=b-a if a is not None and b is not None else None)
        if _is_evaluation_window_kpi(key) and window_status in ('one_sided', 'incompatible'):
            row['window_status'] = window_status
            unpaired_window_kpis.add(key)
        if _is_feeder_kpi(key) and feeder_status in ('one_sided', 'incompatible'):
            row['feeder_status'] = feeder_status
            unpaired_feeder_kpis.add(key)
        rows.append(row)
    report['kpis'] = rows
    report['unpaired_window_kpis'] = sorted(unpaired_window_kpis)
    report['unpaired_feeder_kpis'] = sorted(unpaired_feeder_kpis)
    report['outcome_summary'] = [r for r in rows if r['name'].rsplit(':', 1)[-1] in ('District', 'Portfolio') and any(
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


def reference_configuration(env):
    """Building order and the per-building settings that the native BAU reference must reproduce.

    The reference is rebuilt from the schema and the constructor arguments. This records what they
    resolve to for each building, in the env's building order: the outage setting and the active
    actions, which setters can change after loading. :func:`equipment` records the devices.
    """
    return [dict(
        name=building.name,
        simulate_power_outage=bool(building.simulate_power_outage),
        # NoControlAgent disables every action of the evaluated env after loading; the reference keeps the loaded
        # actions, which the agent records (CityLearn #309).
        active_actions=sorted(building.active_actions)
        or list(getattr(building, '_no_control_loaded_active_actions', None) or []),
    ) for building in getattr(env, '_all_buildings', None) or env.buildings]


def configuration_differences(left, right):
    """`setting (left vs right)` for each :func:`reference_configuration` entry that differs."""
    names = [[row['name'] for row in rows] for rows in (left, right)]
    if names[0] != names[1]:
        return [f'building order ({names[0]!r} vs {names[1]!r})']
    return [f"{a['name']}: {key} ({a[key]!r} vs {b[key]!r})"
            for a, b in zip(left, right) for key in ('simulate_power_outage', 'active_actions') if a[key] != b[key]]
