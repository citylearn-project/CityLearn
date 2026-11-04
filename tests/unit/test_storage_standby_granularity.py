"""Standby loss is an hourly fraction, independent of data and control intervals."""

import pytest

from citylearn.base import EpisodeTracker
from citylearn.energy_model import Battery, StorageDevice, StorageTank


@pytest.mark.parametrize("storage_type", [StorageDevice, StorageTank, Battery])
@pytest.mark.parametrize("seconds", [15, 60, 900, 3600, 7200])
@pytest.mark.parametrize("hourly_loss", [0.0, 0.01, 1.0])
def test_same_elapsed_time_has_same_standby_loss(storage_type, seconds, hourly_loss):
    steps = 7200 // seconds
    tracker = EpisodeTracker(0, steps)
    tracker.next_episode(steps + 1, False, False, 0)
    storage = storage_type(
        capacity=100.0, initial_soc=1.0, efficiency=1.0,
        loss_coefficient=hourly_loss, time_step_ratio=1.0,
        seconds_per_time_step=seconds, episode_tracker=tracker,
        random_seed=0,
    )
    storage.reset()

    # SOC[0] is the initial instant. Each advance accounts for one interval;
    # repeated zero-energy commands at that instant must not add standby loss.
    for step in range(steps):
        before = float(storage.soc[step])
        storage.charge(0.0)
        storage.charge(0.0)
        assert storage.soc[step] == pytest.approx(before)
        assert storage.energy_balance[step] == pytest.approx(0.0)
        storage.next_time_step()

    assert storage.soc[steps] == pytest.approx((1.0 - hourly_loss)**2, abs=5e-6)
    assert 0.0 <= storage.soc[steps] <= 1.0


@pytest.mark.parametrize("seconds", [15, 900, 3600, 7200])
def test_standby_loss_ignores_dataset_to_control_ratio(seconds):
    losses = [StorageDevice(loss_coefficient=0.01, seconds_per_time_step=seconds,
                            time_step_ratio=ratio).loss_coefficient
              for ratio in [0.25, 1.0, 2.0]]
    assert losses == pytest.approx([1.0 - 0.99**(seconds/3600.0)] * 3)
