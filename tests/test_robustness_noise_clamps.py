"""Robustness noise (`noise_std`) keeps each perturbed series within its physical range.

`noise_std` adds zero-mean Gaussian noise in the unit of each series; it is not scaled by the series. One rule
bounds the result: solar generation and solar irradiance stay >= 0 and get no noise where the noise-free value is
zero (night), outdoor relative humidity stays within [0, 100] % and carbon intensity stays >= 0. The noise draws
themselves are unchanged, so values that the bounds do not touch are the same as without the rule. The bound tests
fail on CityLearn 3.5.0, which leaves the noise unbounded.
"""

from __future__ import annotations

import numpy as np
import pytest

from citylearn.data import CarbonIntensity, EnergySimulation, Weather
from citylearn.utilities import IndexedNoise

STEPS = 480
SEED = 11
HOUR = np.arange(STEPS) % 24
DAY = (HOUR >= 7) & (HOUR <= 18)


def _unbounded_noise(channel: int, std: float) -> np.ndarray:
    """The noise that the `channel`-th noisy series of an object draws from `IndexedNoise(SEED, 0)`."""

    stream = IndexedNoise(SEED, 0)
    for _ in range(channel):
        stream.normal(0.0, std, (STEPS,))
    return stream.normal(0.0, std, (STEPS,)).astype('float32')


def _energy_simulation(noise_std: float, solar: np.ndarray) -> EnergySimulation:
    zeros = np.zeros(STEPS)
    return EnergySimulation(
        month=np.ones(STEPS, dtype=int), hour=HOUR + 1, day_type=np.ones(STEPS, dtype=int),
        indoor_dry_bulb_temperature=np.full(STEPS, 21.0), non_shiftable_load=np.ones(STEPS),
        dhw_demand=zeros, cooling_demand=zeros, heating_demand=zeros, solar_generation=solar,
        seconds_per_time_step=3600, noise_std=noise_std, noise_seed=SEED,
    )


def _weather(noise_std: float) -> Weather:
    irradiance = np.where(DAY, 40.0, 0.0)
    # Humidity alternates between values near both bounds.
    humidity = np.where(np.arange(STEPS) % 2 == 0, 3.0, 97.0)
    series = {
        'outdoor_dry_bulb_temperature': np.full(STEPS, 5.0),
        'outdoor_relative_humidity': humidity,
        'diffuse_solar_irradiance': irradiance,
        'direct_solar_irradiance': irradiance,
    }
    kwargs = dict(series)
    for name, values in series.items():
        for i in (1, 2, 3):
            kwargs[f'{name}_predicted_{i}'] = values
    return Weather(**kwargs, noise_std=noise_std, noise_seed=SEED)


def test_solar_generation_noise_is_never_negative_and_zero_at_night():
    solar = np.where(DAY, 20.0, 0.0)
    noisy = _energy_simulation(50.0, solar).solar_generation
    assert noisy.min() >= 0.0
    np.testing.assert_array_equal(noisy[~DAY], 0.0)
    # Daytime values the bound does not touch keep the noise drawn for the series (channel 1, after indoor temperature).
    unbounded = np.float32(20.0) + _unbounded_noise(1, 50.0)
    kept = DAY & (unbounded >= 0.0)
    np.testing.assert_array_equal(noisy[kept], unbounded[kept])
    assert np.any(noisy[DAY] != 20.0)


def test_weather_noise_keeps_humidity_and_irradiance_in_range():
    weather = _weather(10.0)
    for suffix in ('', '_predicted_1', '_predicted_2', '_predicted_3'):
        humidity = getattr(weather, f'outdoor_relative_humidity{suffix}')
        assert humidity.min() >= 0.0 and humidity.max() <= 100.0
        assert np.any((humidity != 3.0) & (humidity != 97.0))
        for kind in ('diffuse', 'direct'):
            irradiance = getattr(weather, f'{kind}_solar_irradiance{suffix}')
            assert irradiance.min() >= 0.0
            np.testing.assert_array_equal(irradiance[~DAY], 0.0)
    # Temperature has no physical bound here and keeps its unbounded noise (first channel).
    np.testing.assert_array_equal(weather.outdoor_dry_bulb_temperature, np.float32(5.0) + _unbounded_noise(0, 10.0))


def test_carbon_intensity_noise_is_never_negative():
    base = np.full(STEPS, 0.05)
    noisy = CarbonIntensity(base, noise_std=0.2, noise_seed=SEED).carbon_intensity
    assert noisy.min() >= 0.0
    unbounded = base.astype('float32') + _unbounded_noise(0, 0.2)
    np.testing.assert_array_equal(noisy, np.maximum(unbounded, 0.0))


def test_values_already_outside_the_range_are_not_moved_into_it():
    # A dataset value below zero is not changed by the bound; only noise that leaves the range is clipped.
    base = np.full(STEPS, -0.1)
    noisy = CarbonIntensity(base, noise_std=0.2, noise_seed=SEED).carbon_intensity
    np.testing.assert_array_equal(noisy, base.astype('float32') + _unbounded_noise(0, 0.2))


@pytest.mark.parametrize('noise_std', [0.0, -1.0])
def test_without_noise_the_series_are_unchanged(noise_std):
    solar = np.where(DAY, 20.0, 0.0)
    np.testing.assert_array_equal(_energy_simulation(noise_std, solar).solar_generation, solar.astype('float32'))
    weather = _weather(noise_std)
    np.testing.assert_array_equal(weather.outdoor_relative_humidity,
                                  np.where(np.arange(STEPS) % 2 == 0, 3.0, 97.0).astype('float32'))
    base = np.full(STEPS, 0.05)
    np.testing.assert_array_equal(CarbonIntensity(base, noise_std=noise_std).carbon_intensity, base.astype('float32'))
