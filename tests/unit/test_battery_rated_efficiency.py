"""A battery's rated (datasheet) efficiency must reach the simulation and survive reset."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.base import EpisodeTracker
from citylearn.energy_model import Battery


def _battery(**kwargs):
    tracker = EpisodeTracker(0, 23)
    tracker.next_episode(24, False, False, 0)
    battery = Battery(
        capacity=10.0, nominal_power=5.0, efficiency=0.95, random_seed=7,
        episode_tracker=tracker, seconds_per_time_step=3600.0, **kwargs,
    )
    battery.reset()
    return battery


def test_rated_efficiency_rescales_generated_curve_and_survives_reset():
    battery = _battery()
    curve = battery.power_efficiency_curve.copy()
    assert curve[1, 3] == pytest.approx(0.95)  # the generated curve's rated point

    battery.set_rated_efficiency(0.90)
    battery.reset()

    assert battery.efficiency == 0.90
    np.testing.assert_allclose(battery.power_efficiency_curve[0], curve[0])
    np.testing.assert_allclose(battery.power_efficiency_curve[1], curve[1]*0.90/0.95)
    assert battery.get_current_efficiency(curve[0, 3]*battery.nominal_power) == pytest.approx(0.90)


def test_plain_efficiency_assignment_is_lost_at_reset():
    """Documents why autosizing uses `set_rated_efficiency`."""
    battery = _battery()
    battery.efficiency = 0.90
    battery.reset()

    assert battery.efficiency == pytest.approx(0.95)


def test_rated_efficiency_keeps_user_supplied_curve():
    curve = [[0.0, 0.83], [0.3, 0.83], [0.7, 0.9], [0.8, 0.9], [1.0, 0.85]]
    battery = _battery(power_efficiency_curve=curve)

    battery.set_rated_efficiency(0.80)
    battery.reset()

    assert battery.efficiency == 0.80
    np.testing.assert_array_equal(battery.power_efficiency_curve, np.array(curve).T)


def test_autosized_batteries_simulate_their_datasheet_efficiency():
    from citylearn.citylearn import CityLearnEnv

    path = Path(__file__).resolve().parents[2] / 'data' / 'datasets' / 'tx_travis_county_neighborhood' / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    names = [name for name, building in schema['buildings'].items()
             if (building.get('electrical_storage') or {}).get('autosize')][:5]
    assert names, 'dataset no longer autosizes batteries'
    env = CityLearnEnv(schema, buildings=names, solar_generation=False, episode_time_steps=24, random_seed=0)
    env.reset()
    checked = 0

    for building in env.buildings:
        storage = building.electrical_storage
        datasheet = (storage.autosize_config or {}).get('efficiency')
        if datasheet is None or not np.isfinite(datasheet):
            continue

        checked += 1
        assert storage.efficiency == pytest.approx(datasheet)
        # The generated curve peaks at the rated point.
        assert np.max(storage.power_efficiency_curve[1]) == pytest.approx(datasheet)

    assert checked > 0
