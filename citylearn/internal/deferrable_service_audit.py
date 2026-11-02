"""Executed-interval accounting for deferrable requests, independent of reservations."""

DEFINITION_VERSION = 'deferrable-service-audit-v1'
STATES = ('pending', 'running', 'completed', 'missed', 'cancelled')
EXCLUSIONS = (
    'expired_before_episode', 'expired_before_activation', 'not_yet_available',
    'removed_before_available', 'outside_episode_service_horizon',
    'already_accounted_previous_instance',
)
REASONS = (
    'profile_delivered', 'profile_energy_shortfall', 'start_window_elapsed',
    'asset_removed', 'member_removed', 'window_open', 'profile_in_progress',
)


def metadata():
    return dict(
        definition_version=DEFINITION_VERSION,
        identity=['member_id', 'appliance_id', 'cycle_id'],
        population='requests with an admissible full-cycle start in an executed active interval',
        energy_balance='requested = served + final_unserved + outstanding',
        observed_completion_denominator='offered_count',
        resolved_completion_denominator='completed_count + missed_count + cancelled_count',
        zero_denominator=None,
        terminal_observation_is_executed=False,
    )


class ServiceLedger:
    """Keep actual service separately from future energy booked by start_cycle.

    Per-step work depends only on running cycles; calendar scans happen at audit
    time. A ledger belongs to one activation instance and is reset per episode.
    """

    def __init__(self, episode_start, terminal_step):
        self.episode_start = int(episode_start)
        self.terminal_step = int(terminal_step)
        self.activation = int(episode_start)
        self.last_step = None
        self.first_step = None
        self.exit_step = None
        self.exit_reason = None
        self.starts = {}
        self.active = {}
        self.served = {}
        self.finished = set()
        self.excluded = set()
        self.physical_energy = 0.0

    def start(self, cycle, step):
        cid = cycle['cycle_id']
        self.starts[cid] = int(step)
        self.active[cid] = cycle['load_profile']

    def record(self, step, energy):
        step = int(step)
        if self.last_step is not None and step <= self.last_step:
            return
        if self.exit_step is not None or step >= self.terminal_step:
            return
        if self.first_step is None:
            self.first_step = step
        self.last_step = step
        self.physical_energy += float(energy)
        weights = {}
        for cid, profile in self.active.items():
            offset = step - self.starts[cid]
            if 0 <= offset < len(profile):
                weights[cid] = float(profile[offset])
        total = sum(weights.values())
        if total > 0.0:
            for cid, weight in weights.items():
                self.served[cid] = self.served.get(cid, 0.0) + float(energy) * weight / total
        for cid, profile in list(self.active.items()):
            if step >= self.starts[cid] + len(profile) - 1:
                self.finished.add(cid)
                del self.active[cid]

    def cancel(self, step, reason):
        self.exit_step = int(step)
        self.exit_reason = reason
        self.active.clear()

    def records(self, schedule):
        result = []
        for cycle in schedule:
            cid = cycle['cycle_id']
            earliest = int(cycle['earliest_start_time_step'])
            latest = int(cycle['latest_start_time_step'])
            duration = int(cycle['duration_steps'])
            deadline = int(cycle['deadline_time_step'])
            requested = float(cycle['total_energy_kwh'])
            start = self.starts.get(cid)
            served = self.served.get(cid, 0.0)
            valid_first = max(earliest, self.activation)
            valid_last = min(latest, deadline - duration + 1, self.terminal_step - duration)
            reason = None
            if cid in self.excluded:
                reason = 'already_accounted_previous_instance'
            elif latest < self.episode_start:
                reason = 'expired_before_episode'
            elif latest < self.activation:
                reason = 'expired_before_activation'
            elif valid_first > valid_last:
                reason = 'outside_episode_service_horizon'
            elif self.first_step is None or max(valid_first, self.first_step) > min(valid_last, self.last_step):
                reason = 'removed_before_available' if self.exit_step is not None else 'not_yet_available'
            included = reason is None
            state = 'excluded'
            remainder = max(requested - served, 0.0)
            unserved = outstanding = 0.0
            if included:
                if cid in self.finished:
                    complete = abs(requested - served) <= 1.0e-6 * max(1.0, requested)
                    state, reason = ('completed', 'profile_delivered') if complete else ('missed', 'profile_energy_shortfall')
                elif start is None and self.last_step >= latest:
                    state, reason = 'missed', 'start_window_elapsed'
                elif self.exit_step is not None:
                    state, reason = 'cancelled', self.exit_reason
                elif start is not None:
                    state, reason = 'running', 'profile_in_progress'
                else:
                    state, reason = 'pending', 'window_open'
                if state in ('missed', 'cancelled'):
                    unserved = remainder
                elif state in ('pending', 'running'):
                    outstanding = remainder
            result.append(dict(
                cycle_id=cid, included=included, state=state, reason=reason,
                earliest_start_time_step=earliest, latest_start_time_step=latest,
                deadline_time_step=deadline, activation_time_step=self.activation,
                start_time_step=start, exit_time_step=self.exit_step,
                last_executed_time_step=self.last_step,
                requested_energy_kwh=requested, served_energy_kwh=served,
                final_unserved_energy_kwh=unserved, outstanding_energy_kwh=outstanding,
            ))
        return result


def summarize(records, physical_energy=0.0, duplicate_offered=0):
    offered = [r for r in records if r['included']]
    counts = {state + '_count': sum(r['state'] == state for r in offered) for state in STATES}
    resolved = sum(counts[state + '_count'] for state in ('completed', 'missed', 'cancelled'))
    result = dict(catalogue_count=len(records), offered_count=len(offered),
                  excluded_count=len(records) - len(offered), resolved_count=resolved,
                  duplicate_offered_count=duplicate_offered, **counts)
    for reason in EXCLUSIONS:
        result['excluded_' + reason + '_count'] = sum(not r['included'] and r['reason'] == reason for r in records)
    for reason in REASONS:
        result['reason_' + reason + '_count'] = sum(r['included'] and r['reason'] == reason for r in records)
    for key in ('requested', 'served', 'final_unserved', 'outstanding'):
        result[key + '_energy_kwh'] = sum(r[key + '_energy_kwh'] for r in offered)
    result['excluded_requested_energy_kwh'] = sum(r['requested_energy_kwh'] for r in records if not r['included'])
    result['physical_energy_kwh'] = float(physical_energy)
    result['physical_balance_residual_kwh'] = physical_energy - result['served_energy_kwh']
    result['service_balance_residual_kwh'] = (result['requested_energy_kwh'] - result['served_energy_kwh']
                                            - result['final_unserved_energy_kwh'] - result['outstanding_energy_kwh'])
    result['observed_completion_ratio'] = counts['completed_count'] / len(offered) if offered else None
    result['resolved_completion_ratio'] = counts['completed_count'] / resolved if resolved else None
    result['resolved_coverage_ratio'] = resolved / len(offered) if offered else None
    return result


def environment_audit(service):
    records, buildings = [], {}
    total_physical = 0.0
    total_duplicates = 0
    for building in service._get_kpi_buildings():
        logical = {}
        physical = 0.0
        duplicates = 0
        for appliance in service._deferrable_appliances_for_metrics(building):
            audit = appliance.service_audit()
            physical += audit['physical_energy_kwh']
            for row in audit['records']:
                row = dict(row, member_id=building.name, appliance_id=appliance.name)
                key = (appliance.name, row['cycle_id'])
                previous = logical.get(key)
                if previous is not None and previous['included'] and row['included']:
                    duplicates += 1
                if previous is None or not previous['included']:
                    logical[key] = row
        member_records = list(logical.values())
        buildings[building.name] = summarize(member_records, physical, duplicates)
        records.extend(member_records)
        total_physical += physical
        total_duplicates += duplicates
    return dict(**metadata(), records=records, buildings=buildings,
                district=summarize(records, total_physical, total_duplicates))
