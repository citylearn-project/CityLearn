import json
import shutil
from pathlib import Path
import pytest
from citylearn.citylearn import CityLearnEnv
from citylearn.community_dataset import InventoryBattery


def test_loader_preserves_declared_ev_battery_and_zero_discharge(tmp_path):
    source=Path(__file__).parent/'data/minute_ev_demo'
    shutil.copytree(source,tmp_path/'dataset')
    path=tmp_path/'dataset/schema.json';schema=json.loads(path.read_text())
    schema['root_directory']=str(path.parent)
    for ev in schema['electric_vehicles_def'].values():
        ev['battery']['type']='citylearn.community_dataset.InventoryBattery'
        ev['battery']['attributes'].update(initial_soc=.4,max_charge_kw=5.,max_discharge_kw=0.,charging_efficiency=.9,discharging_efficiency=1.)
    path.write_text(json.dumps(schema))
    env=CityLearnEnv(str(path));env.reset(seed=0)
    for ev in env.electric_vehicles:
        battery=ev.battery
        assert isinstance(battery,InventoryBattery)
        assert battery.get_max_output_power()==0.
        assert battery.get_max_input_power()<=5.
        assert battery.charging_efficiency==.9
    env.close()
