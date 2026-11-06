"""An EV is plugged into at most one charger, even when charger schedules overlap."""

import collections
import json
import warnings
from pathlib import Path

import numpy as np

from citylearn.citylearn import CityLearnEnv

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / 'data' / 'datasets' / 'citylearn_three_phase_dynamic_topology_demo' / 'schema.json'
)
CLONE_TIME_STEP = 1300  # `evt_add_charger_to_b2` clones charger_18_1 while Building_18 keeps it


def _zero_entity_action(env):
    return {'tables': {
        name: np.zeros(space.shape, dtype='float32') for name, space in env.action_space['tables'].spaces.items()
    }}


def _connections(env):
    plugged = collections.defaultdict(list)
    for building in env.buildings:
        for charger in building.electric_vehicle_chargers or []:
            if charger.connected_electric_vehicle is not None:
                plugged[charger.connected_electric_vehicle.name].append(charger.charger_id)
    return plugged


def test_cloned_charger_does_not_double_plug_its_sources_ev():
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    schema['root_directory'] = str(SCHEMA_PATH.parent)
    schema.update(simulation_start_time_step=CLONE_TIME_STEP - 5, simulation_end_time_step=CLONE_TIME_STEP + 10)
    env = CityLearnEnv(schema)
    env.reset()
    clone_steps = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')

        while not env.terminated:
            connections = _connections(env)
            assert all(len(chargers) == 1 for chargers in connections.values()), dict(connections)

            clone_present = any(
                charger.charger_id == 'charger_2_dyn_1'
                for building in env.buildings for charger in building.electric_vehicle_chargers or []
            )
            if clone_present and 'Electric_Vehicle_9' in connections:
                clone_steps.append(env.time_step)
                # The schema charger keeps the session that the clone's copied schedule repeats.
                assert connections['Electric_Vehicle_9'] == ['charger_18_1']

            action = _zero_entity_action(env)
            if action['tables']['charger'].size:
                action['tables']['charger'][:] = 1.0
            env.step(action)

    assert clone_steps, 'no step had both the cloned charger and an EV_9 session in the simulated window'
    messages = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert any("'charger_2_dyn_1'" in m and 'Electric_Vehicle_9' in m for m in messages)
    # One warning per charger pair, not one per step.
    assert sum("'charger_2_dyn_1'" in m for m in messages) == 1
