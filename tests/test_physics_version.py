"""The versioned physics setting and the corrections of physics version 2 that change no bundled result.

Each correction test reproduces its issue (tracking issue #226, theme 4). Physics version 1, the
behaviour of CityLearn 3.6.0, was removed in CityLearn 3.8.1 (#466).
"""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import Battery, ElectricHeater, HeatPump, StorageTank
from citylearn.internal.physics_version import (
    DEFAULT_PHYSICS_VERSION,
    LATEST_PHYSICS_VERSION,
    PHYSICS_VERSIONS,
    resolve_physics_version,
)
from citylearn.internal.runtime import CityLearnRuntimeService
from private_access import baseline_service

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'
MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'


def _minute_dataset(tmp_path: Path) -> tuple[Path, dict]:
    dataset = tmp_path / 'minute_ev_demo'
    shutil.copytree(MINUTE_DATASET, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    return dataset, schema


def _tracker(steps: int) -> EpisodeTracker:
    tracker = EpisodeTracker(0, steps - 1)
    tracker.next_episode(steps, False, False, 0)
    return tracker


# --- The setting ------------------------------------------------------------------------------------

def test_resolve_physics_version_accepts_only_version_2_and_defaults_to_it():
    assert PHYSICS_VERSIONS == (2,)
    assert DEFAULT_PHYSICS_VERSION == LATEST_PHYSICS_VERSION == 2
    assert resolve_physics_version(None) == 2
    assert resolve_physics_version(2) == 2
    assert resolve_physics_version(' 2 ') == 2
    assert resolve_physics_version(np.int64(2)) == 2


@pytest.mark.parametrize('value', [0, 3, True, False, 1.5, 2.0, 'latest', [1]])
def test_resolve_physics_version_rejects_unknown_values(value):
    with pytest.raises(ValueError, match='physics_version'):
        resolve_physics_version(value)


@pytest.mark.parametrize('value', [1, '1', np.int64(1)])
def test_physics_version_1_was_removed(value):
    with pytest.raises(ValueError, match=r'physics_version must be 2, got .*Version 1 was removed in CityLearn 3\.8\.1; '
                                         r'CityLearn 3\.7 reproduces CityLearn 3\.6\.0'):
        resolve_physics_version(value)


def test_environment_argument_overrides_schema_and_reaches_buildings_metadata_and_reference(tmp_path):
    _, schema = _minute_dataset(tmp_path)

    default_env = CityLearnEnv(dict(schema))
    assert default_env.physics_version == DEFAULT_PHYSICS_VERSION

    schema['physics_version'] = '2'
    env = CityLearnEnv(dict(schema))
    assert env.physics_version == 2
    assert [building.physics_version for building in env.buildings] == [2]
    # Exports stay comparable: the version is recorded.
    assert env.get_metadata()['physics_version'] == 2

    schema['physics_version'] = 7
    overridden = CityLearnEnv(dict(schema), physics_version=2)
    assert overridden.physics_version == 2
    assert [building.physics_version for building in overridden.buildings] == [2]

    # The native business-as-usual reference simulates the same physics as the evaluated env.
    sidecar = baseline_service(env)._new_sidecar_env()
    assert sidecar.physics_version == 2
    assert [building.physics_version for building in sidecar.buildings] == [2]


@pytest.mark.parametrize('where', ['argument', 'schema'])
@pytest.mark.parametrize('value', [1, 7])
def test_environment_rejects_physics_versions_other_than_2(tmp_path, where, value):
    _, schema = _minute_dataset(tmp_path)
    kwargs = {}

    if where == 'schema':
        schema['physics_version'] = value
    else:
        kwargs['physics_version'] = value

    with pytest.raises(ValueError, match='physics_version must be 2.*Version 1 was removed in CityLearn 3.8.1'):
        CityLearnEnv(dict(schema), **kwargs)


# --- #236: standby loss of an EV away from its charger ------------------------------------------------

def _away_ev_soc(tmp_path: Path, monkeypatch) -> tuple[np.ndarray, float]:
    dataset, schema = _minute_dataset(tmp_path)
    charger = pd.read_csv(dataset / 'charger_1_1.csv')
    # No EV at the charger at any step: the vehicle is away for the whole episode.
    for column in charger.columns:
        charger[column] = np.nan
    charger.to_csv(dataset / 'charger_1_1.csv', index=False)
    schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']['attributes']['loss_coefficient'] = 0.05
    # Remove the stochastic part of the away-from-charger drift, as in the issue's repro.
    monkeypatch.setattr(CityLearnRuntimeService, '_ev_unconnected_drift_std', staticmethod(lambda seconds: 0.0))
    env = CityLearnEnv(schema)
    env.reset()
    ev = env.electric_vehicles[0]
    assert all(c.connected_electric_vehicle is None for c in env.buildings[0].electric_vehicle_chargers)

    while not env.terminated:
        env.step([np.zeros(env.action_space[0].shape, dtype='float32').tolist()])

    # The terminal index is not simulated; compare the executed steps.
    return np.asarray(ev.battery.soc, dtype='float64')[:-1], ev.battery.loss_coefficient


def test_issue_236_away_ev_keeps_its_standby_loss(tmp_path, monkeypatch):
    soc, loss = _away_ev_soc(tmp_path, monkeypatch)
    expected = 0.4 * (1.0 - loss) ** np.arange(len(soc))

    assert loss > 0.0
    assert soc[-1] < soc[0]
    np.testing.assert_allclose(soc, expected, rtol=1.0e-6)


# --- #235: HVAC caps compare energy with energy ------------------------------------------------------

def test_issue_235_heat_pump_cap_converts_power_to_step_energy():
    device = HeatPump(nominal_power=10.0, efficiency=0.2, seconds_per_time_step=7200,
                      episode_tracker=_tracker(2), random_seed=0)
    device.reset()
    cop = device.get_cop(20.0, heating=False)
    requested_kwh = 1.0 * 10.0 * 2.0

    legacy = device.get_max_output_power(20.0, heating=False, max_electric_power=requested_kwh)
    corrected = device.get_max_output_power(20.0, heating=False, max_electric_power=requested_kwh, step_hours=2.0)

    assert legacy == pytest.approx(10.0 * cop)
    assert corrected == pytest.approx(20.0 * cop)
    # A half-power request is below the cap either way.
    assert device.get_max_output_power(20.0, heating=False, max_electric_power=10.0, step_hours=2.0) \
        == pytest.approx(device.get_max_output_power(20.0, heating=False, max_electric_power=10.0))


def test_issue_235_electric_heater_cap_converts_power_to_step_energy():
    device = ElectricHeater(nominal_power=10.0, efficiency=0.9, seconds_per_time_step=7200,
                            episode_tracker=_tracker(2), random_seed=0)
    device.reset()

    assert device.get_max_output_power(max_electric_power=20.0) == pytest.approx(9.0)
    assert device.get_max_output_power(max_electric_power=20.0, step_hours=2.0) == pytest.approx(18.0)


def _two_hour_cooling_demand(action: float) -> np.ndarray:
    """Cooling demand of the issue's repro: `citylearn_challenge_2023_phase_1` at 2-hour steps.

    The LSTM building applies HVAC actions only after its 12-step lookback, so steps without dynamics or
    outside the cooling mode are returned as NaN.
    """

    schema = json.loads((DATASETS / 'citylearn_challenge_2023_phase_1' / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASETS / 'citylearn_challenge_2023_phase_1')
    for index, building in enumerate(schema['buildings'].values()):
        building['include'] = index == 0
    schema['seconds_per_time_step'] = 7200
    schema['dataset_seconds_per_time_step'] = 7200
    steps = 24
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=steps, simulation_start_time_step=0,
                       simulation_end_time_step=steps - 1, random_seed=0)
    env.reset()
    building = env.buildings[0]
    names = env.action_names[0]
    actions = np.zeros(len(names), dtype='float32')
    actions[names.index('cooling_device')] = action
    demand = np.full(steps - 1, np.nan)

    while not env.terminated:
        t = building.time_step
        controlled = building.simulate_dynamics and building.energy_simulation.hvac_mode[t] in (1, 3)
        env.step([actions.tolist()])
        if controlled:
            demand[t] = float(building.energy_simulation.cooling_demand[t])

    return demand


def test_issue_235_two_hour_steps_are_not_capped_at_one_hour_of_output():
    half = _two_hour_cooling_demand(0.5)
    full = _two_hour_cooling_demand(1.0)
    controlled = ~np.isnan(half)

    assert controlled.any()
    # 3.6.0 capped a full action at the output of a half action: one hour of nominal power per two-hour step.
    np.testing.assert_allclose(full[controlled], 2.0 * half[controlled], rtol=1.0e-6)


# --- #233: autosizing at sub-hourly resolution ----------------------------------------------------------

@pytest.mark.parametrize('seconds', [3600, 900])
def test_issue_233_tank_capacity_holds_one_hour_of_peak_demand(seconds):
    tank = StorageTank(seconds_per_time_step=seconds, episode_tracker=_tracker(2), random_seed=0)
    hourly_peak_kw = 8.0
    demand = np.array([1.0, hourly_peak_kw * seconds / 3600.0, 2.0])

    assert tank.autosize(demand, safety_factor=1.5) == pytest.approx(hourly_peak_kw * 1.5)
    assert tank.autosize(demand, safety_factor=1.5, duration=2.0) == pytest.approx(hourly_peak_kw * 3.0)


def test_issue_233_tank_autosize_does_not_depend_on_resolution_in_a_building():
    capacities = {}

    for seconds in (3600, 900):
        schema = json.loads((DATASETS / 'citylearn_challenge_2021' / 'schema.json').read_text(encoding='utf-8'))
        schema['root_directory'] = str(DATASETS / 'citylearn_challenge_2021')
        for index, building in enumerate(schema['buildings'].values()):
            building['include'] = index == 0
            for storage in ('cooling_storage', 'dhw_storage'):
                if building.get(storage):
                    building[storage]['autosize'] = True
                    building[storage]['autosize_attributes'] = {'safety_factor': 1.0}
        # Hourly data at a 900 s control step, compressed as in 3.6.0, the case the issue reports.
        env = CityLearnEnv(schema, central_agent=True, seconds_per_time_step=seconds, random_seed=0,
                           time_step_ratio_mode='compress')
        building = env.buildings[0]
        capacities[seconds] = (building.cooling_storage.capacity, building.dhw_storage.capacity)

    # Hourly data at a 900 s control step: the same physical peak power, the same one-hour tank.
    np.testing.assert_allclose(capacities[900], capacities[3600], rtol=1.0e-6)


def test_issue_233_hourly_pv_profile_is_resampled_to_the_dataset_resolution(tmp_path, monkeypatch):
    _, schema = _minute_dataset(tmp_path)
    env = CityLearnEnv(schema)
    building = env.buildings[0]
    hourly = np.arange(48, dtype='float64')

    # 900 s data: each hourly average power is repeated, so the energy over an hour is unchanged.
    resampled = building._hourly_profile_to_dataset_resolution(hourly, 4 * 48)
    np.testing.assert_array_equal(resampled[:8], [0, 0, 0, 0, 1, 1, 1, 1])
    assert resampled.sum() * 0.25 == pytest.approx(hourly.sum())

    # A dataset shorter than the profile is truncated; a longer one repeats it.
    assert len(building._hourly_profile_to_dataset_resolution(hourly, 10)) == 10
    assert len(building._hourly_profile_to_dataset_resolution(hourly, 500)) == 500

    # Hourly data of the same length is returned unchanged, so hourly autosizing is unchanged.
    monkeypatch.setattr(type(building), '_dataset_step_hours', lambda self: 1.0)
    np.testing.assert_array_equal(building._hourly_profile_to_dataset_resolution(hourly, 48), hourly)

    # Two-hour data averages the hours of each step.
    monkeypatch.setattr(type(building), '_dataset_step_hours', lambda self: 2.0)
    np.testing.assert_array_equal(building._hourly_profile_to_dataset_resolution(hourly, 24)[:3], [0.5, 2.5, 4.5])


def test_pv_autosize_scales_the_window_demand_to_one_year(tmp_path, monkeypatch):
    _, schema = _minute_dataset(tmp_path)
    env = CityLearnEnv(schema)
    building = env.buildings[0]
    rows_per_year = int(round(365.0 * 24.0 / building._dataset_step_hours()))
    sized = []

    def fake_autosize(self, demand, epw_filepath, **kwargs):
        sized.append(demand)
        return 1.0, np.zeros(8760)

    monkeypatch.setattr(type(building.pv), 'autosize', fake_autosize)

    # PVWatts gives a full year of yield, so a one-week window must not give a smaller array.
    for rows in (rows_per_year // 52, rows_per_year, 2 * rows_per_year + rows_per_year // 2):
        monkeypatch.setattr(type(building), '_estimate_baseline_electricity_consumption',
                            lambda self, rows=rows: np.full(rows, 0.5))
        building.autosize_pv(epw_filepath='unused.epw')

    assert sized == pytest.approx([0.5 * rows_per_year] * 3)


# --- Efficiency naming and history -------------------------------------------------------------------

def _battery(**kwargs) -> Battery:
    battery = Battery(capacity=10.0, nominal_power=5.0, initial_soc=0.5, efficiency=0.81, loss_coefficient=0.0,
                      capacity_loss_coefficient=0.0, episode_tracker=_tracker(10), seconds_per_time_step=3600,
                      random_seed=0, power_efficiency_curve=[[0, 0.81], [1, 0.81]], **kwargs)
    battery.reset()
    return battery


def test_one_way_efficiency_without_the_removed_round_trip_alias():
    battery = _battery()

    assert battery.efficiency == pytest.approx(0.81)
    assert battery.one_way_efficiency == pytest.approx(0.9)
    # The misnamed `round_trip_efficiency` alias was removed in CityLearn 3.8.1 (#466).
    assert not hasattr(battery, 'round_trip_efficiency')
    metadata = battery.get_metadata()
    assert metadata['one_way_efficiency'] == pytest.approx(0.9)
    assert 'round_trip_efficiency' not in metadata


def test_efficiency_history_grows_by_one_entry_per_operation():
    battery = _battery()
    assert len(battery.efficiency_history) == 1

    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        for step in range(4):
            battery.charge(2.0 if step % 2 == 0 else -1.0)
            battery.next_time_step()

    assert len(battery.efficiency_history) == 5


def test_preview_charge_matches_charge_without_changing_the_battery():
    battery = _battery()
    battery.force_set_soc(0.95)
    soc_before = float(battery.soc[battery.time_step])
    history_before = list(battery.efficiency_history)

    preview = battery.preview_charge(5.0)

    assert float(battery.soc[battery.time_step]) == soc_before
    assert list(battery.efficiency_history) == history_before
    battery.charge(5.0)
    assert float(battery.energy_balance[battery.time_step]) == pytest.approx(preview, rel=1.0e-6)
