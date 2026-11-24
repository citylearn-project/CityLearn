"""Regression tests for public module re-exports preserved under ruff F401."""

import importlib

import pytest


@pytest.mark.parametrize(
    ('module_name', 'attr_name', 'canonical_module'),
    [
        ('citylearn.citylearn', 'Battery', 'citylearn.energy_model'),
        ('citylearn.citylearn', 'PV', 'citylearn.energy_model'),
        ('citylearn.citylearn', 'Pricing', 'citylearn.data'),
        ('citylearn.citylearn', 'CarbonIntensity', 'citylearn.data'),
        ('citylearn.citylearn', 'ChargerSimulation', 'citylearn.data'),
        ('citylearn.citylearn', 'LogisticRegressionOccupantParameters', 'citylearn.data'),
        ('citylearn.citylearn', 'Weather', 'citylearn.data'),
        ('citylearn.citylearn', 'CostFunction', 'citylearn.cost_function'),
        ('citylearn.citylearn', 'MultiBuildingRewardFunction', 'citylearn.reward_function'),
        ('citylearn.building', 'Normalize', 'citylearn.preprocessing'),
        ('citylearn.electric_vehicle', 'Normalize', 'citylearn.preprocessing'),
        ('citylearn.electric_vehicle', 'PeriodicNormalization', 'citylearn.preprocessing'),
        ('citylearn.energy_model', 'EpisodeTracker', 'citylearn.base'),
        ('citylearn.energy_model', 'EnergySimulation', 'citylearn.data'),
        ('citylearn.reward_function', 'Building', 'citylearn.building'),
    ],
)
def test_existing_module_import_paths_stay_available(module_name: str, attr_name: str, canonical_module: str):
    module = importlib.import_module(module_name)
    canonical = importlib.import_module(canonical_module)
    assert getattr(module, attr_name) is getattr(canonical, attr_name)
