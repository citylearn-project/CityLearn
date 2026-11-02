"""Community settlement and equity KPI record assembly."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService


def market_records(kpi: "CityLearnKPIService", kpi_buildings, building_windows, simulated_days):
    extended_building_rows, extended_district_rows = [], []
    building_names = [building.name for building in kpi_buildings]
    kpi_building_by_name = {building.name: building for building in kpi_buildings}
    market_by_building, market_district = kpi._collect_market_totals(building_names)

    for building_name in building_names:
        t_start, t_end = building_windows.get(building_name, (0, -1))
        building_days = kpi._building_days(kpi_building_by_name[building_name], t_start, t_end)
        totals = market_by_building.get(building_name, {})
        local_import = kpi._to_scalar(totals.get('community_local_import_total_kwh'), 0.0)
        local_export = kpi._to_scalar(totals.get('community_local_export_total_kwh'), 0.0)
        grid_import = kpi._to_scalar(totals.get('community_grid_import_after_local_total_kwh'), 0.0)
        grid_export = kpi._to_scalar(totals.get('community_grid_export_after_local_total_kwh'), 0.0)
        import_share = None if (local_import + grid_import) <= 0.0 else local_import / (local_import + grid_import)
        export_share = None if (local_export + grid_export) <= 0.0 else local_export / (local_export + grid_export)

        extended_building_rows.extend([
            kpi._metric('community_local_import_total_kwh', local_import, building_name, 'building'),
            kpi._metric('community_local_export_total_kwh', local_export, building_name, 'building'),
            kpi._metric('community_grid_import_after_local_total_kwh', grid_import, building_name, 'building'),
            kpi._metric('community_grid_export_after_local_total_kwh', grid_export, building_name, 'building'),
            kpi._metric('community_local_import_daily_average_kwh', kpi._daily_average(local_import, building_days), building_name, 'building'),
            kpi._metric('community_local_export_daily_average_kwh', kpi._daily_average(local_export, building_days), building_name, 'building'),
            kpi._metric('community_grid_import_after_local_daily_average_kwh', kpi._daily_average(grid_import, building_days), building_name, 'building'),
            kpi._metric('community_grid_export_after_local_daily_average_kwh', kpi._daily_average(grid_export, building_days), building_name, 'building'),
            kpi._metric('community_settled_cost_total_eur', totals.get('community_settled_cost_total_eur', 0.0), building_name, 'building'),
            kpi._metric('community_counterfactual_cost_total_eur', totals.get('community_counterfactual_cost_total_eur', 0.0), building_name, 'building'),
            kpi._metric('community_market_savings_total_eur', totals.get('community_market_savings_total_eur', 0.0), building_name, 'building'),
            kpi._metric('community_settled_cost_daily_average_eur', kpi._daily_average(totals.get('community_settled_cost_total_eur', 0.0), building_days), building_name, 'building'),
            kpi._metric('community_counterfactual_cost_daily_average_eur', kpi._daily_average(totals.get('community_counterfactual_cost_total_eur', 0.0), building_days), building_name, 'building'),
            kpi._metric('community_market_savings_daily_average_eur', kpi._daily_average(totals.get('community_market_savings_total_eur', 0.0), building_days), building_name, 'building'),
            kpi._metric('community_local_share_of_demand', import_share, building_name, 'building'),
            kpi._metric('community_local_share_of_export', export_share, building_name, 'building'),
        ])

    district_local_import = market_district['community_local_import_total_kwh']
    district_local_export = market_district['community_local_export_total_kwh']
    district_grid_import = market_district['community_grid_import_after_local_total_kwh']
    district_grid_export = market_district['community_grid_export_after_local_total_kwh']

    extended_district_rows.extend([
        kpi._metric('community_local_import_total_kwh', district_local_import, 'District', 'district'),
        kpi._metric('community_local_export_total_kwh', district_local_export, 'District', 'district'),
        kpi._metric('community_grid_import_after_local_total_kwh', district_grid_import, 'District', 'district'),
        kpi._metric('community_grid_export_after_local_total_kwh', district_grid_export, 'District', 'district'),
        kpi._metric('community_local_import_daily_average_kwh', kpi._daily_average(district_local_import, simulated_days), 'District', 'district'),
        kpi._metric('community_local_export_daily_average_kwh', kpi._daily_average(district_local_export, simulated_days), 'District', 'district'),
        kpi._metric('community_grid_import_after_local_daily_average_kwh', kpi._daily_average(district_grid_import, simulated_days), 'District', 'district'),
        kpi._metric('community_grid_export_after_local_daily_average_kwh', kpi._daily_average(district_grid_export, simulated_days), 'District', 'district'),
        kpi._metric('community_settled_cost_total_eur', market_district['community_settled_cost_total_eur'], 'District', 'district'),
        kpi._metric('community_counterfactual_cost_total_eur', market_district['community_counterfactual_cost_total_eur'], 'District', 'district'),
        kpi._metric('community_market_savings_total_eur', market_district['community_market_savings_total_eur'], 'District', 'district'),
        kpi._metric('community_settled_cost_daily_average_eur', kpi._daily_average(market_district['community_settled_cost_total_eur'], simulated_days), 'District', 'district'),
        kpi._metric('community_counterfactual_cost_daily_average_eur', kpi._daily_average(market_district['community_counterfactual_cost_total_eur'], simulated_days), 'District', 'district'),
        kpi._metric('community_market_savings_daily_average_eur', kpi._daily_average(market_district['community_market_savings_total_eur'], simulated_days), 'District', 'district'),
        kpi._metric(
            'community_local_share_of_demand',
            None if (district_local_import + district_grid_import) <= 0.0 else district_local_import / (district_local_import + district_grid_import),
            'District',
            'district',
        ),
        kpi._metric(
            'community_local_share_of_export',
            None if (district_local_export + district_grid_export) <= 0.0 else district_local_export / (district_local_export + district_grid_export),
            'District',
            'district',
        ),
    ])
    return extended_building_rows, extended_district_rows


def equity_records(kpi: "CityLearnKPIService", building_names, equity_valid_benefits, equity_group_by_building):
    extended_district_rows = []
    equity_distribution = kpi._equity_distribution_metrics(np.array(list(equity_valid_benefits.values()), dtype='float64'))
    non_negative_benefits = {name: max(value, 0.0) for name, value in equity_valid_benefits.items()}
    has_complete_manual_groups = all(
        equity_group_by_building.get(name) in {'asset_rich', 'asset_poor'}
        for name in building_names
    )
    equity_bpr = kpi._equity_bpr(non_negative_benefits, equity_group_by_building) if has_complete_manual_groups else None

    extended_district_rows.extend([
        kpi._metric('equity_gini_benefit', equity_distribution['equity_gini_benefit'], 'District', 'district'),
        kpi._metric('equity_cr20_benefit', equity_distribution['equity_cr20_benefit'], 'District', 'district'),
        kpi._metric('equity_losers_percent', equity_distribution['equity_losers_percent'], 'District', 'district'),
        kpi._metric('equity_bpr_asset_poor_over_rich', equity_bpr, 'District', 'district'),
    ])
    return extended_district_rows
