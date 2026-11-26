"""Device ids that two buildings share (#402)."""

from copy import deepcopy
import json

import pytest

from citylearn.citylearn import CityLearnEnv
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance, _zero_entity_payload


def _env(schema, tmp_path):
    return CityLearnEnv(schema, random_seed=0, offline=True, render_directory=tmp_path / 'exports',
                        export_kpis_on_episode_end=False)


def _two_member_schema(tmp_path, *, chargers=True):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    schema = json.loads(path.read_text())
    schema.update(interface='entity', simulation_start_time_step=0, simulation_end_time_step=7, episode_time_steps=8)
    member = deepcopy(schema['buildings']['Building_1'])
    if not chargers:
        member['chargers'] = {}
    schema['buildings']['Building_2'] = member
    return schema


@pytest.mark.parametrize('topology_mode', ['static', 'dynamic'])
def test_a_charger_id_declared_by_two_buildings_is_rejected_at_load(tmp_path, topology_mode):
    schema = _two_member_schema(tmp_path)
    schema['topology_mode'] = topology_mode
    with pytest.raises(ValueError, match=r"Charger id 'charger_1_1' is declared by both Building_1 and Building_2"):
        _env(schema, tmp_path)


def test_renamed_charger_loads(tmp_path):
    schema = _two_member_schema(tmp_path)
    member = schema['buildings']['Building_2']
    member['chargers'] = {'charger_2_1': member['chargers']['charger_1_1']}
    env = _env(schema, tmp_path)
    try:
        ids = [c.charger_id for b in env.buildings for c in b.electric_vehicle_chargers]
        assert ids == ['charger_1_1', 'charger_2_1']
    finally:
        env.close()


def test_a_shared_appliance_name_is_accepted_but_its_raw_action_id_is_ambiguous(tmp_path):
    # Appliance names are scoped to their building (Building/washer_1), as in the bundled dynamic-topology demo.
    schema = _two_member_schema(tmp_path, chargers=False)
    env = _env(schema, tmp_path)
    try:
        env.reset()
        payload = _zero_entity_payload(env)
        payload['map'] = {'Building_2/washer_1': {'start': 1.0}}
        env.step(payload)
        payload = _zero_entity_payload(env)
        payload['map'] = {'deferrable_appliance:washer_1': {'start': 1.0}}
        with pytest.raises(AssertionError, match="'washer_1' in the action map is ambiguous: it names Building_1/washer_1, Building_2/washer_1"):
            env.step(payload)
    finally:
        env.close()
