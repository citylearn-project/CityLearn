"""A battery removed or replaced by a topology event keeps its past in the building's series.

`remove_asset` and `add_asset` for `electrical_storage` replace the building's `Battery` instance. The
building's battery series read the current instance, so the replaced battery's consumption used to vanish
from them for every step it was installed. The baselines without storage subtract that series from the
net consumption, so they then contained the controller's battery dispatch for those steps.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json"
EVENT_TIME_STEP = 6
REMOVE = {
    "id": "remove_storage", "time_step": EVENT_TIME_STEP, "operation": "remove_asset",
    "target_member_id": "Building_12", "target_asset_type": "electrical_storage",
    "target_asset_id": "electrical_storage",
}
REPLACE = {
    "id": "replace_storage", "time_step": EVENT_TIME_STEP, "operation": "add_asset",
    "target_member_id": "Building_12", "target_asset_type": "electrical_storage",
    "target_asset_id": "electrical_storage", "source_member_id": "Building_1",
    "source_asset_id": "electrical_storage",
}


def _schema(events):
    schema = json.loads(SCHEMA_PATH.read_text())
    schema["root_directory"] = str(SCHEMA_PATH.parent)
    schema["interface"] = "entity"
    schema["topology_mode"] = "dynamic"
    schema["topology_events"] = events
    return schema


def _actions(env, value):
    payload = {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in env.action_space["tables"].items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }
    building = next(b for b in env.buildings if b.name == "Building_12")
    if "electrical_storage" in building.active_actions:
        payload["map"] = {"building:Building_12": {"electrical_storage": value}}
    return payload


def _run(events, storage_actions, baseline_version=2):
    env = CityLearnEnv(_schema(events), interface="entity", topology_mode="dynamic", episode_time_steps=12,
                       random_seed=0, baseline_version=baseline_version)
    env.reset(seed=0)
    building = next(b for b in env.buildings if b.name == "Building_12")
    replaced = building.electrical_storage

    while not env.terminated:
        env.step(_actions(env, storage_actions[env.time_step]))

    n = env.time_step
    series = {
        name: np.asarray(getattr(building, name)[:n], dtype=float)
        for name in (
            "net_electricity_consumption", "electrical_storage_electricity_consumption",
            "net_electricity_consumption_without_storage", "energy_to_electrical_storage",
            "energy_from_electrical_storage",
        )
    }
    series["district_net_electricity_consumption_without_storage"] = np.asarray(
        env.net_electricity_consumption_without_storage[:n], dtype=float
    )
    series["replaced"] = np.asarray(replaced.electricity_consumption[:n], dtype=float)
    series["replaced_energy_balance"] = np.asarray(replaced.energy_balance[:n], dtype=float)
    series["current"] = np.asarray(building.electrical_storage.electricity_consumption[:n], dtype=float)
    env.close()
    return series


@pytest.mark.parametrize("event", [REMOVE, REPLACE], ids=["remove", "replace"])
def test_replaced_battery_history_stays_in_building_series(event):
    charge_then_discharge = [0.8, 0.8, 0.8, -0.6, -0.6, 0.4] + [0.5]*6
    series = _run([event], charge_then_discharge)
    cut = EVENT_TIME_STEP

    replaced = series["replaced"]
    assert np.abs(replaced[:cut]).sum() > 1.0, "the battery must move energy before the event"

    building = series["electrical_storage_electricity_consumption"]
    np.testing.assert_array_equal(building[:cut], replaced[:cut])
    np.testing.assert_array_equal(building[cut:], series["current"][cut:])
    np.testing.assert_array_equal(series["energy_to_electrical_storage"][:cut],
                                  series["replaced_energy_balance"][:cut].clip(min=0.0))
    np.testing.assert_array_equal(series["energy_from_electrical_storage"][:cut],
                                  series["replaced_energy_balance"][:cut].clip(max=0.0)*-1)

    if event is REMOVE:
        assert np.all(building[cut:] == 0.0)


@pytest.mark.parametrize("event", [REMOVE, REPLACE], ids=["remove", "replace"])
def test_baseline_without_storage_does_not_depend_on_the_replaced_battery_dispatch(event):
    # Only the Building_12 battery actions differ between the two runs, so the baselines without
    # storage, for the building and the district, must be the same.
    first = _run([event], [0.8, 0.8, 0.8, -0.6, -0.6, 0.4] + [0.5]*6)
    second = _run([event], [-0.3, 0.2, 0.6, 0.6, -0.9, -0.2] + [-0.5]*6)
    assert not np.array_equal(first["net_electricity_consumption"], second["net_electricity_consumption"])

    for name in ("net_electricity_consumption_without_storage", "district_net_electricity_consumption_without_storage"):
        np.testing.assert_allclose(first[name], second[name], rtol=0.0, atol=1.0e-5, err_msg=name)


@pytest.mark.parametrize("event", [REMOVE, REPLACE], ids=["remove", "replace"])
def test_baseline_version_1_keeps_the_3_6_0_storage_series(event):
    # baseline_version 1 reproduces CityLearn 3.6.0: the building's battery series reads only the current
    # instance, so the replaced battery's history is lost and the baseline keeps its dispatch.
    actions = [0.8, 0.8, 0.8, -0.6, -0.6, 0.4] + [0.5]*6
    v1 = _run([event], actions, baseline_version=1)
    v2 = _run([event], actions, baseline_version=2)
    cut = EVENT_TIME_STEP

    assert np.abs(v1["replaced"][:cut]).sum() > 1.0
    np.testing.assert_array_equal(v1["electrical_storage_electricity_consumption"], v1["current"])
    np.testing.assert_array_equal(v2["electrical_storage_electricity_consumption"][:cut], v2["replaced"][:cut])

    # The controlled run is the same under both versions; only the series that keep the history differ.
    np.testing.assert_array_equal(v1["net_electricity_consumption"], v2["net_electricity_consumption"])
    np.testing.assert_array_equal(v1["replaced"], v2["replaced"])

    # As in 3.6.0, the v1 baseline then depends on the replaced battery's dispatch.
    other = _run([event], [-0.3, 0.2, 0.6, 0.6, -0.9, -0.2] + [-0.5]*6, baseline_version=1)
    assert not np.allclose(v1["net_electricity_consumption_without_storage"][:cut],
                           other["net_electricity_consumption_without_storage"][:cut], rtol=0.0, atol=1.0e-5)
