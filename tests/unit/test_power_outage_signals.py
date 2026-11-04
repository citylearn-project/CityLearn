import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.power_outage import ReliabilityMetricsPowerOutage


@pytest.mark.parametrize('time_steps', [1, 11, 24, 25, 49, 50, 721, 8760])
def test_signals_for_partial_days(time_steps):
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    signals = model.get_signals(time_steps, 3600.0)

    assert signals.shape == (time_steps,)
    assert set(np.unique(signals)) <= {0, 1}


def _signals_before_partial_day_fix(time_steps, seconds_per_time_step, saifi, caidi, random_seed):
    """Verbatim copy of the original algorithm, valid only for whole days."""

    nprs = np.random.RandomState(random_seed)
    time_steps_per_day = 86400.0/seconds_per_time_step
    time_steps_per_minute = 60.0/seconds_per_time_step
    day_count = time_steps/time_steps_per_day
    outage_days = nprs.binomial(n=1, p=saifi/365.0, size=int(day_count))
    outage_day_ixs = outage_days*np.arange(day_count)
    outage_day_ixs = outage_day_ixs[outage_day_ixs != 0]
    outage_day_count = outage_days[outage_days == 1].shape[0]
    starts = nprs.choice(list(range(int(time_steps_per_day))), size=outage_day_count)
    durations = nprs.exponential(scale=caidi, size=outage_day_count)*time_steps_per_minute
    signals = np.zeros(time_steps, dtype=int)

    for i, j, k in zip(outage_day_ixs, starts, durations):
        start_ix = i*time_steps_per_day + j
        signals[int(start_ix):int(start_ix + k)] = 1

    return signals


@pytest.mark.parametrize(('time_steps', 'seconds'), [(24*30, 3600.0), (96*7, 900.0), (24*365, 3600.0)])
def test_whole_day_signals_unchanged_by_partial_day_fix(time_steps, seconds):
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=120.0, random_seed=3)
    np.testing.assert_array_equal(
        model.get_signals(time_steps, seconds),
        _signals_before_partial_day_fix(time_steps, seconds, 200.0, 120.0, 3),
    )


def test_environment_with_stochastic_outages_and_partial_day_episode_resets():
    env = CityLearnEnv(
        'citylearn_challenge_2023_phase_2_local_evaluation', central_agent=True,
        simulation_start_time_step=0, simulation_end_time_step=48,
    )
    assert any(b.stochastic_power_outage for b in env.buildings)
    observations, _ = env.reset()
    assert len(observations) == 1
