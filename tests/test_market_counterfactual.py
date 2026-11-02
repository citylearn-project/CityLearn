"""Market savings compare identical external tariffs with and without sharing."""
import json

import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from test_market_phase_invariants import _write_residual_market_schema, _rollout_zero_actions


@pytest.mark.parametrize('import_price', [0.20, -0.10])
@pytest.mark.parametrize('export_price', [0.0, 0.05])
@pytest.mark.parametrize('local_trading', [False, True])
def test_market_savings_exclude_external_export_revenue(
    tmp_path, import_price, export_price, local_trading,
):
    path = _write_residual_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    schema['root_directory'] = str(path.parent)
    schema['community_market'].update(
        settlement_version=2,
        grid_export_price=export_price,
        local_trading_enabled=local_trading,
    )
    prices = pd.read_csv(path.parent / 'pricing.csv')
    prices.iloc[:, :] = import_price
    prices.to_csv(path.parent / 'pricing.csv', index=False)
    env = CityLearnEnv(schema, central_agent=True, random_seed=0)
    try:
        _rollout_zero_actions(env)
        expected_counterfactual = 0.0
        expected_savings = 0.0
        for rows, demand, surplus in zip(
            env._community_market_settlement_history, [2.0, 1.0, 0.5], [1.0, 3.0, 0.5],
        ):
            shared = min(demand, surplus) if local_trading else 0.0
            counterfactual = demand * import_price - surplus * export_price
            settled = (demand - shared) * import_price - (surplus - shared) * export_price
            saving = shared * (import_price - export_price)
            assert sum(row['counterfactual_cost_eur'] for row in rows) == pytest.approx(counterfactual, abs=1e-7)
            assert sum(row['settled_cost_eur'] for row in rows) == pytest.approx(settled, abs=1e-7)
            assert sum(row['market_savings_eur'] for row in rows) == pytest.approx(saving, abs=1e-7)
            for row in rows:
                assert row['local_buy_price'] == pytest.approx(0.8 * import_price)
                assert row['local_sell_price'] == pytest.approx(0.8 * import_price)
                if not local_trading:
                    assert row['market_savings_eur'] == pytest.approx(0.0, abs=1e-7)
            expected_counterfactual += counterfactual
            expected_savings += saving

        frame = env.evaluate_v2(include_business_as_usual=False)
        district = frame[frame['name'] == 'District'].set_index('cost_function')['value']
        assert district['district_cost_community_market_counterfactual_total_eur'] == pytest.approx(expected_counterfactual, abs=1e-7)
        assert district['district_cost_community_market_savings_total_eur'] == pytest.approx(expected_savings, abs=1e-7)
    finally:
        env.close()
