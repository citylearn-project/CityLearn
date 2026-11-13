"""Regression tests for CityLearn 3.3 correctness audit fixes."""

from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.__main__ import Simulator
from citylearn.agents.base import Agent, BaselineAgent
from citylearn.agents.marlisa import MARLISA, MARLISARBC
from citylearn.agents.q_learning import TabularQLearning
from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController, BasicRBC, HourRBC
from citylearn.base import EpisodeTracker
from citylearn.building import Building
from citylearn.citylearn import CityLearnEnv
from citylearn.cost_function import CostFunction
from citylearn.data import (
    ChargerSimulation,
    EnergySimulation,
    EscalatorSimulation,
    Pricing,
    Weather,
)
from citylearn.electric_vehicle import ElectricVehicle
from citylearn.electric_vehicle_charger import Charger
from citylearn.energy_model import WashingMachine
from citylearn.exporter import EpisodeExporter
from citylearn.internal.comparison import load_kpis
from citylearn.internal.kpi_equipment import compute_phase_metrics
from citylearn.preprocessing import OnehotEncoding
from citylearn.reward_function import (
    ComfortReward,
    Electric_Vehicles_Reward_Function,
    MultiBuildingRewardFunction,
    SolarPenaltyReward,
)
from citylearn.utilities import FileHandler
from citylearn.utils.file_handler import FileHandler as SharedFileHandler
from citylearn.wrappers import (
    ClippedObservationWrapper,
    DiscreteObservationWrapper,
    RLlibMultiAgentActionWrapper,
    TabularQLearningWrapper,
)

ROOT = Path(__file__).resolve().parents[1]
CHALLENGE_2022 = ROOT / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'
MINUTE_EV_DEMO = ROOT / 'tests' / 'data' / 'minute_ev_demo'


def _schema_2022() -> dict:
    schema = json.loads((CHALLENGE_2022 / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(CHALLENGE_2022)
    return schema


def test_timeseries_slice_order_and_validation():
    n = 12
    es = EnergySimulation(
        month=[1] * n,
        hour=list(range(1, n + 1)),
        day_type=[1] * n,
        indoor_dry_bulb_temperature=[22.0] * n,
        non_shiftable_load=[1.0] * n,
        dhw_demand=[0.0] * n,
        cooling_demand=[1.0] * n,
        heating_demand=[0.0] * n,
        solar_generation=[10.0] * n,
        start_time_step=2,
        end_time_step=7,
    )
    assert len(es.non_shiftable_load) == 6
    noisy = es.solar_generation
    assert len(noisy) == 6

    es_noisy = EnergySimulation(
        month=[1] * n,
        hour=list(range(1, n + 1)),
        day_type=[1] * n,
        indoor_dry_bulb_temperature=[22.0] * n,
        non_shiftable_load=[1.0] * n,
        dhw_demand=[0.0] * n,
        cooling_demand=[1.0] * n,
        heating_demand=[0.0] * n,
        solar_generation=[0.01] * n,
        start_time_step=2,
        end_time_step=7,
        noise_std=5.0,
    )
    assert len(es_noisy.solar_generation) == 6
    assert np.all(es_noisy.solar_generation >= 0.0)

    with pytest.raises(AssertionError, match='Cooling and heating'):
        EnergySimulation(
            month=[1, 1],
            hour=[1, 2],
            day_type=[1, 1],
            indoor_dry_bulb_temperature=[22.0, 22.0],
            non_shiftable_load=[1.0, 1.0],
            dhw_demand=[0.0, 0.0],
            cooling_demand=[1.0, 0.0],
            heating_demand=[1.0, 0.0],
            solar_generation=[0.0, 0.0],
        )

    weather = Weather(
        outdoor_dry_bulb_temperature=list(range(n)),
        outdoor_relative_humidity=[50.0] * n,
        diffuse_solar_irradiance=[100.0] * n,
        direct_solar_irradiance=[200.0] * n,
        outdoor_dry_bulb_temperature_predicted_1=list(range(n)),
        outdoor_dry_bulb_temperature_predicted_2=list(range(n)),
        outdoor_dry_bulb_temperature_predicted_3=list(range(n)),
        outdoor_relative_humidity_predicted_1=[50.0] * n,
        outdoor_relative_humidity_predicted_2=[50.0] * n,
        outdoor_relative_humidity_predicted_3=[50.0] * n,
        diffuse_solar_irradiance_predicted_1=[100.0] * n,
        diffuse_solar_irradiance_predicted_2=[100.0] * n,
        diffuse_solar_irradiance_predicted_3=[100.0] * n,
        direct_solar_irradiance_predicted_1=[200.0] * n,
        direct_solar_irradiance_predicted_2=[200.0] * n,
        direct_solar_irradiance_predicted_3=[200.0] * n,
        start_time_step=3,
        end_time_step=6,
    )
    assert list(weather.outdoor_dry_bulb_temperature) == [3.0, 4.0, 5.0, 6.0]

    pricing = Pricing(
        electricity_pricing=list(range(n)),
        electricity_pricing_predicted_1=list(range(n)),
        electricity_pricing_predicted_2=list(range(n)),
        electricity_pricing_predicted_3=list(range(n)),
        start_time_step=4,
        end_time_step=7,
    )
    assert list(pricing.electricity_pricing) == [4.0, 5.0, 6.0, 7.0]


def test_charger_float_states_and_escalator_window_validation():
    sim = ChargerSimulation(
        electric_vehicle_charger_state=[1.0, '2.0', 'nan', 3.0],
        electric_vehicle_id=['ev1', 'ev1', '', 'ev1'],
        electric_vehicle_departure_time=[2, -1, -1, -1],
        electric_vehicle_required_soc_departure=[0.8, -1.0, -1.0, -1.0],
        electric_vehicle_estimated_arrival_time=[-1, 1, -1, -1],
        electric_vehicle_estimated_soc_arrival=[-1.0, 0.5, -1.0, -1.0],
    )
    assert list(sim.electric_vehicle_charger_state[:2]) == [1, 2]
    assert np.isnan(sim.electric_vehicle_charger_state[2])
    assert sim.electric_vehicle_charger_state[3] == 3

    df = pd.DataFrame({
        'time_step': [5, 6, 7],
        'passengers_from_trains_15min': [10, 12, 8],
        'background_pedestrians_15min': [5, 4, 6],
        'passengers_expected_15min': [15, 16, 14],
        'people_detected': [1, 1, 1],
        'arriving_trains': [1, 0, 1],
        'departing_trains': [0, 1, 0],
        'minutes_to_next_train': [5.0, 2.0, 7.0],
        'available': [1, 1, 1],
    })
    esc = EscalatorSimulation.from_dataframe(df)
    assert len(esc.passengers_expected_15min) == 3


def test_equipment_and_building_edge_cases():
    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, False, False, 0)
    ev = ElectricVehicle(episode_tracker=tracker, name='ev_default_battery', battery=None)
    assert ev.name == 'ev_default_battery'
    assert ev.battery.capacity == 0.0

    charger_sim = ChargerSimulation(
        electric_vehicle_charger_state=[3, 3, 3, 3],
        electric_vehicle_id=['', '', '', ''],
        electric_vehicle_departure_time=[-1, -1, -1, -1],
        electric_vehicle_required_soc_departure=[-1.0, -1.0, -1.0, -1.0],
        electric_vehicle_estimated_arrival_time=[-1, -1, -1, -1],
        electric_vehicle_estimated_soc_arrival=[-1.0, -1.0, -1.0, -1.0],
    )
    charger = Charger(
        episode_tracker=tracker,
        charger_simulation=charger_sim,
        charger_id='c1',
        nominal_power=7.2,
        seconds_per_time_step=None,
    )
    charger.reset()
    assert charger.seconds_per_time_step == 3600
    d = charger.as_dict()
    assert d['EV SOC-%'] == '-1.00'
    rendered = charger.render_simulation_end_data()
    assert rendered['name'] == 'c1'

    wm = WashingMachine(
        washing_machine_simulation=type('Sim', (), {
            'wm_start_time_step': np.array([0, -1], dtype=int),
            'wm_end_time_step': np.array([1, -1], dtype=int),
            'load_profile': [np.array([0.5, 0.5], dtype=float), np.array([], dtype=float)],
        })(),
        episode_tracker=tracker,
        name='wm1',
        seconds_per_time_step=1800,
        time_step_ratio=0.5,
    )
    wm.reset()
    wm.start_cycle(action_value=1.0)
    assert wm.past_action_values[0] == pytest.approx(1.0)
    assert wm.electricity_consumption[0] == pytest.approx(0.5)

    env = CityLearnEnv(_schema_2022(), central_agent=True, episode_time_steps=4, buildings=[0])
    obs_before, _ = env.reset()
    obs_before[0][0] = -999999.0
    assert env.observations[0][0] != -999999.0

    names_central = env.observation_names
    env.central_agent = False
    assert len(env.observation_names) == len(env.buildings)
    assert env.observation_names != names_central or len(env.buildings) == 1

    end_summary = env.buildings[0].render_simulation_end_data()
    assert end_summary['name'] == env.buildings[0].name
    assert len(end_summary['simulation_data']) == 4


def test_inventory_battery_nominal_power_fallback_and_bounded_initial_soc():
    env = CityLearnEnv(_schema_2022(), central_agent=True, episode_time_steps=4, buildings=[0])
    try:
        ev_schema = {
            'include': True,
            'battery': {
                'type': 'citylearn.community_dataset.InventoryBattery',
                'attributes': {
                    'capacity': 50.0,
                    'max_charge_kw': 11.0,
                    'max_discharge_kw': 7.5,
                    'min_soc': 0.25,
                    'max_soc': 0.85,
                },
            },
        }
        ev = env._loading_service.load_electric_vehicle(
            electric_vehicle_name='ev_test',
            schema={'random_seed': 42, 'seconds_per_time_step': 3600},
            electric_vehicle_schema=ev_schema,
            episode_tracker=env.episode_tracker,
            time_step_ratio=1.0,
        )
        assert ev.battery.nominal_power == pytest.approx(11.0)
        assert 0.25 <= ev.battery.initial_soc <= 0.85
    finally:
        env.close()


def test_bau_timeseries_export_has_no_duplicate_terminal_row(tmp_path: Path):
    env = CityLearnEnv(
        str(MINUTE_EV_DEMO / 'schema.json'),
        central_agent=True,
        episode_time_steps=4,
        random_seed=0,
        render_mode='end',
        render_session_name='bau_test',
        render_directory=tmp_path,
    )
    try:
        env.reset()
        while not (env.terminated or env.truncated):
            env.step([np.zeros(len(env.action_names[0]), dtype='float32')])
        result = env.run_business_as_usual_baseline()
        EpisodeExporter(env).export_business_as_usual_timeseries(env)
        csv_files = list(Path(env.new_folder_path).glob('exported_data_business_as_usual_*.csv'))
        assert len(csv_files) == 1
        df = pd.read_csv(csv_files[0])
        district_rows = df[(df['level'] == 'district') & (df['name'] == 'District')]
        assert list(district_rows['time_step']) == list(range(int(result.time_step)))
    finally:
        env.close()


def test_comparison_load_kpis_supports_multi_community_column(tmp_path: Path):
    kpi_csv = tmp_path / 'multi_comm_kpis.csv'
    pd.DataFrame([
        {'community_id': 'c1', 'name': 'District', 'cost_function': 'cost_total', 'value': 10.0},
        {'community_id': 'c2', 'name': 'District', 'cost_function': 'cost_total', 'value': 12.0},
    ]).to_csv(kpi_csv, index=False)
    loaded = load_kpis(kpi_csv)
    assert len(loaded) == 2


def test_sidecar_keeps_entity_interface_with_robustness():
    robust_schema = ROOT / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all_robustness' / 'schema.json'
    if robust_schema.exists():
        env = CityLearnEnv(str(robust_schema), interface='entity', episode_time_steps=4, buildings=[0])
        try:
            env.reset()
            sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
            try:
                assert sidecar.interface == 'entity'
            finally:
                sidecar.close()
        finally:
            env.close()


def test_onehot_encoding_and_wrappers():
    enc = OnehotEncoding([1, 2, 3])
    np.testing.assert_array_equal(enc * 2.0, np.array([0.0, 1.0, 0.0]))
    np.testing.assert_array_equal(enc * 99, np.array([0.0, 0.0, 0.0]))

    env = CityLearnEnv(_schema_2022(), central_agent=False, episode_time_steps=4, buildings=[0, 1])
    clipped_env = ClippedObservationWrapper(env)
    obs, _ = env.reset()
    original = copy.deepcopy(obs)
    raw = [list(row) for row in obs]
    raw[0][0] = 1e9
    out = clipped_env.observation(raw)
    assert raw[0][0] == 1e9  # input not mutated
    assert out[0][0] <= clipped_env.observation_space[0].high[0]
    assert obs == original

    disc_env = DiscreteObservationWrapper(env, default_bin_size=5)
    disc_out = disc_env.observation([[1e9] * len(s.low) for s in env.observation_space])
    for space, row in zip(disc_env.observation_space, disc_out):
        assert space.contains(np.array(row))

    # TabularQLearningWrapper on full 28-observation building must initialize in O(k) without MemoryError
    q_env = TabularQLearningWrapper(
        CityLearnEnv(_schema_2022(), central_agent=True, episode_time_steps=4, buildings=[0]),
        default_observation_bin_size=4,
        default_action_bin_size=3,
    )
    q_obs, _ = q_env.reset()
    assert 0 <= q_obs[0][0] < q_env.observation_space[0].n
    q_next, *_ = q_env.step([[0]])
    assert 0 <= q_next[0][0] < q_env.observation_space[0].n

    action_wrapper = RLlibMultiAgentActionWrapper(env)
    reversed_dict = {'agent_1': np.array([0.25]), 'agent_0': np.array([-0.5])}
    parsed = action_wrapper.action(reversed_dict)
    assert parsed == [[-0.5], [0.25]]


def test_q_learning_terminal_bootstrap_and_seed_reproducibility():
    schema = _schema_2022()
    for name in schema['observations']:
        schema['observations'][name]['active'] = name == 'hour'
    for name in schema['actions']:
        schema['actions'][name]['active'] = name == 'electrical_storage'

    def _make_agent():
        env = CityLearnEnv(copy.deepcopy(schema), central_agent=True, episode_time_steps=6, buildings=[0], random_seed=11)
        env = TabularQLearningWrapper(
            env, observation_bin_sizes=[{'hour': 24}], action_bin_sizes=[{'electrical_storage': 3}]
        )
        return TabularQLearning(env, learning_rate=1.0, discount_factor=0.9)

    agent = _make_agent()
    agent.q[0][:] = np.nan
    agent.q[0][4] = [10.0, 50.0, 5.0]
    agent.q[0][3, 1] = 0.0
    agent.update([[3]], [[1]], [-2.0], [[4]], terminated=True, truncated=False)
    assert agent.q[0][3, 1] == pytest.approx(-2.0)

    a1, a2 = _make_agent(), _make_agent()
    a1.learn(episodes=2)
    a2.learn(episodes=2)
    assert a1.actions == a2.actions


def test_marlisa_pca_compression_and_marlisa_rbc_uses_rbc():
    pytest.importorskip('torch')
    pytest.importorskip('sklearn')

    env = CityLearnEnv(_schema_2022(), central_agent=False, episode_time_steps=24, buildings=[0, 1], random_seed=0)
    agent = MARLISA(
        env,
        hidden_dimension=[8, 8],
        pca_compression=0.5,
        batch_size=8,
        start_regression_time_step=2,
        standardize_start_time_step=25,
        end_exploration_time_step=28,
    )
    agent.learn(episodes=2)
    assert all(agent.pca_flag)

    env_rbc = CityLearnEnv(_schema_2022(), central_agent=False, episode_time_steps=8, buildings=[0, 1], random_seed=3)
    rbc_ref = BasicRBC(CityLearnEnv(_schema_2022(), central_agent=False, episode_time_steps=8, buildings=[0, 1], random_seed=3))
    marlisa_rbc = MARLISARBC(env_rbc, rbc=BasicRBC, hidden_dimension=[8, 8])
    obs, _ = env_rbc.reset()
    expected = rbc_ref.predict(obs)
    actual = marlisa_rbc.predict(obs)
    np.testing.assert_allclose(actual, expected)
    assert marlisa_rbc.rbc.time_step == 1


def test_rbc_and_reward_and_cost_fixes():
    # Empty action_map when building has no active actions
    env_passive = CityLearnEnv(_schema_2022(), central_agent=True, episode_time_steps=4, buildings=[0])
    BaselineAgent(env_passive)
    hour_rbc = HourRBC(env_passive, action_map={})
    obs, _ = env_passive.reset()
    assert hour_rbc.predict(obs) == [[]]

    # BasicElectricVehicleRBC_ReferenceController supports cooling_storage
    schema_cs = _schema_2022()
    schema_cs['actions']['cooling_storage'] = {'active': True}
    env_cs = CityLearnEnv(schema_cs, central_agent=False, episode_time_steps=4, buildings=[0])
    ev_rbc = BasicElectricVehicleRBC_ReferenceController(env_cs)
    obs_cs, _ = env_cs.reset()
    pred_cs = ev_rbc.predict(obs_cs)
    assert len(pred_cs) == 1

    # MultiBuildingRewardFunction scopes per-building metadata
    meta = {
        'central_agent': True,
        'buildings': [
            {
                'name': 'B1',
                'cooling_storage': {'capacity': 0.0},
                'heating_storage': {'capacity': 0.0},
                'dhw_storage': {'capacity': 0.0},
                'electrical_storage': {'capacity': 0.0},
            },
            {
                'name': 'B2',
                'cooling_storage': {'capacity': 0.0},
                'heating_storage': {'capacity': 0.0},
                'dhw_storage': {'capacity': 0.0},
                'electrical_storage': {'capacity': 10.0},
            },
        ],
    }
    mbr = MultiBuildingRewardFunction(
        meta,
        {'B1': SolarPenaltyReward(meta), 'B2': SolarPenaltyReward(meta)},
    )
    res = mbr.calculate([
        {'net_electricity_consumption': 2.0, 'electrical_storage_soc': 0.5},
        {'net_electricity_consumption': 2.0, 'electrical_storage_soc': 0.5},
    ])
    # B1 has 0 storage capacity -> 0.0; B2 has 10.0 capacity -> -(1 + 0.5)*2 = -3.0
    assert res == [pytest.approx(-3.0)]

    # ComfortReward in hvac_mode == 2 with zero demand uses hvac_mode == 2 consistently
    comfort = ComfortReward({'central_agent': False}, band=2.0, lower_exponent=2.0, higher_exponent=3.0)
    # Heating mode (2), setpoint=20, indoor=19 (within band below setpoint -> 0.0 in heating mode), indoor=21 -> -1.0
    r_below = comfort.calculate([{
        'heating_demand': 0.0,
        'cooling_demand': 0.0,
        'hvac_mode': 2,
        'indoor_dry_bulb_temperature': 19.0,
        'indoor_dry_bulb_temperature_cooling_set_point': 24.0,
        'indoor_dry_bulb_temperature_heating_set_point': 20.0,
        'comfort_band': 2.0,
    }])
    r_above = comfort.calculate([{
        'heating_demand': 0.0,
        'cooling_demand': 0.0,
        'hvac_mode': 2,
        'indoor_dry_bulb_temperature': 23.0,
        'indoor_dry_bulb_temperature_cooling_set_point': 24.0,
        'indoor_dry_bulb_temperature_heating_set_point': 20.0,
        'comfort_band': 2.0,
    }])
    assert r_below == [pytest.approx(0.0)]
    assert r_above == [pytest.approx(-(3.0 ** 3.0))]

    # Electric_Vehicles_Reward_Function partial weights & negative soc_under <= -0.25 penalty
    ev_rf = Electric_Vehicles_Reward_Function({'central_agent': True}, weights={'soc_under': -4.0})
    assert ev_rf.weights['close_soc'] == pytest.approx(10.0)
    ev_pen = ev_rf.calculate_ev_penalty(
        {
            'net_electricity_consumption': 0.0,
            'electric_vehicles_chargers_dict': {
                'c1': {
                    'connected': True,
                    'previous_battery_soc': 0.5,
                    'battery_soc': 0.5,
                    'battery_capacity': 50.0,
                    'min_capacity': None,
                    'last_charged_kwh': 0.0,
                    'required_soc': 0.65,
                    'hours_until_departure': 0,
                    'max_charging_power': 7.0,
                    'max_discharging_power': 0.0,
                }
            },
        },
        current_reward=0.0,
    )
    assert ev_pen < 0.0

    # CostFunction empty series guards
    assert CostFunction.ramping([]) == []
    assert CostFunction.one_minus_load_factor([]) == []
    assert CostFunction.peak([]) == []
    assert CostFunction.electricity_consumption([]) == []
    assert CostFunction.zero_net_energy([]) == []
    assert CostFunction.carbon_emissions([]) == []
    assert CostFunction.cost([]) == []
    assert CostFunction.quadratic([]) == []


class _TrainableRecordingAgent(Agent):
    trained_flag = False
    evaluated_trained = False

    def __init__(self, env: CityLearnEnv, **kwargs):
        super().__init__(env, **kwargs)
        self.was_trained = False

    def learn(self, episodes: int = None, **kwargs):
        super().learn(episodes=episodes, **kwargs)
        self.was_trained = True

    def predict(self, observations, deterministic: bool = None):
        if deterministic:
            _TrainableRecordingAgent.evaluated_trained = self.was_trained
        return [[0.0] * len(a) for a in self.action_names]


def test_cli_simulator_train_evaluates_trained_agent_and_utf8_bom(tmp_path: Path):
    _TrainableRecordingAgent.evaluated_trained = False
    schema_path = CHALLENGE_2022 / 'schema.json'
    Simulator.train(
        episodes=1,
        evaluate=True,
        evaluation_episode_time_steps=[[0, 5]],
        schema=str(schema_path),
        agent_name=f'{__name__}._TrainableRecordingAgent',
        env_kwargs={'central_agent': True, 'episode_time_steps': 4, 'buildings': [0]},
        output_directory=tmp_path / 'sim_out',
        simulation_id='test_sim',
    )
    assert _TrainableRecordingAgent.evaluated_trained is True
    eval_json = FileHandler.read_json(tmp_path / 'sim_out' / 'test_sim-evaluation.json')
    assert eval_json['evaluation_episode_time_steps'] == [0, 5]

    # UTF-8 with BOM JSON/YAML round-trip
    bom_json = tmp_path / 'bom.json'
    bom_json.write_bytes(b'\xef\xbb\xbf{"hello": "\xc3\xa9"}')
    assert FileHandler.read_json(bom_json)['hello'] == 'é'
    assert SharedFileHandler.read_json(bom_json)['hello'] == 'é'
