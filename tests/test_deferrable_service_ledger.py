import pytest
from citylearn.internal.deferrable_service_audit import ServiceLedger, summarize


def cycle(cid='wash', earliest=0, latest=0, profile=(0.1, 0.2)):
    return dict(cycle_id=cid, earliest_start_time_step=earliest,
                latest_start_time_step=latest, deadline_time_step=latest+len(profile)-1,
                duration_steps=len(profile), load_profile=profile, total_energy_kwh=sum(profile))


def test_reserved_energy_is_not_served_and_query_is_pure():
    c = cycle(latest=3)
    ledger = ServiceLedger(0, 8)
    ledger.start(c, 0)
    assert ledger.records([c])[0]['state'] == 'excluded'
    ledger.record(0, .1)
    row = ledger.records([c])[0]
    assert row['state'] == 'running'
    assert row['served_energy_kwh'] == pytest.approx(.1)
    assert row['outstanding_energy_kwh'] == pytest.approx(.2)
    assert ledger.records([c]) == [row]
    ledger.record(0, .1)
    assert ledger.physical_energy == pytest.approx(.1)
    ledger.record(1, .2)
    assert ledger.records([c])[0]['state'] == 'completed'
    assert summarize(ledger.records([c]), ledger.physical_energy)['physical_balance_residual_kwh'] == pytest.approx(0)


@pytest.mark.parametrize('reason', ['member_removed', 'asset_removed'])
def test_partial_cancel_keeps_delivered_prefix(reason):
    c = cycle(earliest=10, latest=12)
    ledger = ServiceLedger(10, 20)
    ledger.start(c, 10)
    ledger.record(10, .1)
    ledger.cancel(11, reason)
    ledger.record(11, .2)
    row = ledger.records([c])[0]
    assert (row['state'], row['reason'], row['exit_time_step']) == ('cancelled', reason, 11)
    assert row['served_energy_kwh'] == pytest.approx(.1)
    assert row['final_unserved_energy_kwh'] == pytest.approx(.2)
    assert row['outstanding_energy_kwh'] == 0
    summary = summarize([row], ledger.physical_energy)
    assert summary['resolved_completion_ratio'] == 0
    assert summary['resolved_coverage_ratio'] == 1
    assert summary['service_balance_residual_kwh'] == pytest.approx(0)


def test_exclusive_population_and_denominators():
    schedule = [cycle('expired', -4, -3), cycle('missed', 0, 0),
                cycle('pending', 2, 4), cycle('future', 6, 6), cycle('horizon', 9, 9)]
    ledger = ServiceLedger(0, 10)
    for step in range(3):
        ledger.record(step, 0)
    rows = ledger.records(schedule)
    assert [r['state'] for r in rows] == ['excluded', 'missed', 'pending', 'excluded', 'excluded']
    assert [rows[i]['reason'] for i in (0, 3, 4)] == ['expired_before_episode', 'not_yet_available', 'outside_episode_service_horizon']
    s = summarize(rows)
    assert s['catalogue_count'] == 5
    assert s['offered_count'] == 2
    assert s['resolved_coverage_ratio'] == .5
    assert s['final_unserved_energy_kwh'] == pytest.approx(.3)
    assert s['outstanding_energy_kwh'] == pytest.approx(.3)
    assert s['service_balance_residual_kwh'] == pytest.approx(0)


def test_removal_before_available_and_late_activation():
    c = cycle(earliest=5, latest=6)
    old = ServiceLedger(0, 10)
    old.record(0, 0)
    old.cancel(1, 'asset_removed')
    assert old.records([c])[0]['reason'] == 'removed_before_available'
    new = ServiceLedger(0, 10)
    new.activation = 7
    new.record(7, 0)
    assert new.records([c])[0]['reason'] == 'expired_before_activation'


def test_finished_energy_shortfall_and_zero_energy_completion():
    c = cycle()
    ledger = ServiceLedger(0, 10)
    ledger.start(c, 0)
    ledger.record(0, .1)
    ledger.record(1, .05)
    row = ledger.records([c])[0]
    assert (row['state'], row['reason']) == ('missed', 'profile_energy_shortfall')
    assert row['final_unserved_energy_kwh'] == pytest.approx(.15)
    c = cycle(profile=(0, 0))
    ledger = ServiceLedger(0, 10)
    ledger.start(c, 0)
    ledger.record(0, 0)
    assert ledger.records([c])[0]['state'] == 'running'
    ledger.record(1, 0)
    assert ledger.records([c])[0]['state'] == 'completed'


def test_empty_population_has_undefined_ratios_and_unattributed_energy_visible():
    result = summarize([], .2)
    assert result['observed_completion_ratio'] is None
    assert result['resolved_completion_ratio'] is None
    assert result['resolved_coverage_ratio'] is None
    assert result['physical_balance_residual_kwh'] == .2


def test_deadline_precedes_later_removal():
    c = cycle(latest=0)
    ledger = ServiceLedger(0, 10)
    ledger.record(0, 0)
    ledger.cancel(1, 'member_removed')
    assert ledger.records([c])[0]['state'] == 'missed'
