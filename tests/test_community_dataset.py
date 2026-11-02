import json
import numpy as np
import pandas as pd
import pytest
from citylearn.citylearn import CityLearnEnv
from test_electrical_service_and_market import _build_two_building_market_schema


def test_explicit_tariffs_and_operator_balance(tmp_path):
    path = _build_two_building_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    schema['community_market'].update(settlement_version=2, tariff_files={'Building_A':'a.csv','Building_B':'b.csv'})
    for file, buy, sell in [('a.csv', .3, .2), ('b.csv', .6, .25)]:
        pd.DataFrame({'grid_export_price':[.1,.1], 'community_buy_price':[buy,buy],
                      'community_sell_price':[sell,sell]}).to_csv(path.parent/file,index=False)
    path.write_text(json.dumps(schema))
    env=CityLearnEnv(str(path));env.reset()
    env.step([np.zeros(len(env.action_names[0]))])
    rows=env._community_market_settlement_history[-1]
    a,b=rows
    assert a['settled_cost_eur']==pytest.approx(.6)
    assert b['settled_cost_eur']==pytest.approx(-.5)
    assert a['counterfactual_cost_eur']==pytest.approx(1.)
    assert b['counterfactual_cost_eur']==pytest.approx(-.2)
    assert sum(r['market_savings_eur'] for r in rows)==pytest.approx(.7)
    assert sum(r['operator_balance_eur'] for r in rows)==pytest.approx(.1)
    # With internal trading disabled, grid exports are still remunerated.
    schema['community_market']['local_trading_enabled']=False
    path.write_text(json.dumps(schema));env=CityLearnEnv(str(path));env.reset()
    env.step([np.zeros(len(env.action_names[0]))])
    rows=env._community_market_settlement_history[-1]
    assert rows[0]['settled_cost_eur']==pytest.approx(1)
    assert rows[1]['settled_cost_eur']==pytest.approx(-.2)
    assert all(r['market_savings_eur']==pytest.approx(0.) for r in rows)


def test_inventory_battery_limits_and_directional_efficiency(tmp_path):
    path=_build_two_building_market_schema(tmp_path)
    schema=json.loads(path.read_text())
    schema['actions']['electrical_storage']['active']=True
    schema['buildings']['Building_B']['include']=False
    schema['buildings']['Building_A']['electrical_storage']={
        'type':'citylearn.community_dataset.InventoryBattery','autosize':False,
        'attributes':{'capacity':10,'initial_soc':.5,'max_charge_kw':2,'max_discharge_kw':1,
                      'min_soc':.2,'max_soc':.6,'charging_efficiency':.8,'discharging_efficiency':.9}}
    path.write_text(json.dumps(schema))
    env=CityLearnEnv(str(path));env.reset();battery=env.buildings[0].electrical_storage
    env.step([[1.]])
    assert max(battery.soc)<=.600001
    assert max(battery.electricity_consumption)<=1.25001
    env=CityLearnEnv(str(path));env.reset();env.step([[-1.]])
    battery=env.buildings[0].electrical_storage
    assert min(battery.electricity_consumption)==pytest.approx(-1., abs=1e-5)
    assert battery.soc[0]==pytest.approx(.5-1/.9/10, abs=1e-5)
