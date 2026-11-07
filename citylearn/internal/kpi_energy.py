"""Energy, carbon, cost, comfort and grid-shape KPI records.

The facade supplies window/unit helpers; these functions own their family
calculations and return records without changing simulator state.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from citylearn.cost_function import CostFunction

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService


def building_records(kpi: "CityLearnKPIService", building, t_start, t_end,
                     control_condition, baseline_condition, comfort_band,
                     evaluation_condition_cls, dynamics_building_cls):
    """Return legacy frame, extended rows and raw-cost relative benefit."""
    extended_building_rows = []
    building_days = kpi._building_days(building, t_start, t_end)

    if isinstance(building, dynamics_building_cls):
        building_control_condition = (
            evaluation_condition_cls.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV
            if control_condition is None else control_condition
        )
        building_baseline_condition = (
            evaluation_condition_cls.WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV
            if baseline_condition is None else baseline_condition
        )
    else:
        building_control_condition = (
            evaluation_condition_cls.WITH_STORAGE_AND_PV
            if control_condition is None else control_condition
        )
        building_baseline_condition = (
            evaluation_condition_cls.WITHOUT_STORAGE_BUT_WITH_PV
            if baseline_condition is None else baseline_condition
        )

    indoor = kpi._thermal_values(building, building.indoor_dry_bulb_temperature, t_start, t_end)
    cooling_setpoint = kpi._thermal_values(building, building.indoor_dry_bulb_temperature_cooling_set_point, t_start, t_end)
    heating_setpoint = kpi._thermal_values(building, building.indoor_dry_bulb_temperature_heating_set_point, t_start, t_end)
    occupants = kpi._thermal_values(building, building.occupant_count, t_start, t_end)
    discomfort_kwargs = {
        'indoor_dry_bulb_temperature': indoor,
        'dry_bulb_temperature_cooling_set_point': cooling_setpoint,
        'dry_bulb_temperature_heating_set_point': heating_setpoint,
        'band': kpi._thermal_values(building, building.comfort_band, t_start, t_end) if comfort_band is None else comfort_band,
        'occupant_count': occupants,
    }
    unmet, cold, hot, \
        cold_minimum_delta, cold_maximum_delta, cold_average_delta, \
        hot_minimum_delta, hot_maximum_delta, hot_average_delta = [v if v else [np.nan] for v in CostFunction.discomfort(**discomfort_kwargs)]

    expected_components, served_components = kpi._service_energy(building, t_start, t_end)
    expected_energy = expected_components.sum(axis=1)
    # Serving another demand cannot compensate a shortfall in this one.
    served_energy = np.minimum(expected_components, served_components).sum(axis=1)

    net_c_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption{building_control_condition.value}')),
        t_start,
        t_end,
    )
    net_b_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption{building_baseline_condition.value}')),
        t_start,
        t_end,
    )
    ec_c = kpi._positive_total(net_c_series)
    ec_b = kpi._positive_total(net_b_series)
    export_c = kpi._sum_finite(np.clip(-net_c_series, 0.0, None))
    export_b = kpi._sum_finite(np.clip(-net_b_series, 0.0, None))
    zne_c = kpi._net_total(net_c_series)
    zne_b = kpi._net_total(net_b_series)
    ce_c_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption_emission{building_control_condition.value}')),
        t_start,
        t_end,
    )
    ce_b_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption_emission{building_baseline_condition.value}')),
        t_start,
        t_end,
    )
    ce_c = kpi._positive_total(ce_c_series)
    ce_b = (
        kpi._positive_total(ce_b_series)
        if np.sum(kpi._slice_window(building.carbon_intensity.carbon_intensity, t_start, t_end)) != 0
        else 0.0
    )
    control_cost_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption_cost{building_control_condition.value}')),
        t_start,
        t_end,
    )
    baseline_cost_series = kpi._slice_window(
        kpi._energy_values(building, getattr(building, f'net_electricity_consumption_cost{building_baseline_condition.value}')),
        t_start,
        t_end,
    )
    cost_c_legacy = kpi._positive_total(control_cost_series)
    cost_b_legacy = kpi._positive_total(baseline_cost_series)
    cost_c_raw = kpi._sum_finite(control_cost_series)
    cost_b_raw = kpi._sum_finite(baseline_cost_series)
    equity_benefit = kpi._equity_relative_benefit_percent(cost_c_raw, cost_b_raw)


    legacy_building_frame = pd.DataFrame([{
        'cost_function': 'electricity_consumption_total',
        'value': kpi._safe_div(ec_c, ec_b),
    }, {
        'cost_function': 'zero_net_energy',
        'value': kpi._signed_ratio(zne_c, zne_b),
    }, {
        'cost_function': 'carbon_emissions_total',
        'value': kpi._safe_div(ce_c, ce_b),
    }, {
        'cost_function': 'cost_total',
        'value': kpi._safe_div(cost_c_legacy, cost_b_legacy),
    }, {
        'cost_function': 'discomfort_proportion',
        'value': unmet[-1],
    }, {
        'cost_function': 'discomfort_cold_proportion',
        'value': cold[-1],
    }, {
        'cost_function': 'discomfort_hot_proportion',
        'value': hot[-1],
    }, {
        'cost_function': 'discomfort_cold_delta_minimum',
        'value': cold_minimum_delta[-1],
    }, {
        'cost_function': 'discomfort_cold_delta_maximum',
        'value': cold_maximum_delta[-1],
    }, {
        'cost_function': 'discomfort_cold_delta_average',
        'value': cold_average_delta[-1],
    }, {
        'cost_function': 'discomfort_hot_delta_minimum',
        'value': hot_minimum_delta[-1],
    }, {
        'cost_function': 'discomfort_hot_delta_maximum',
        'value': hot_maximum_delta[-1],
    }, {
        'cost_function': 'discomfort_hot_delta_average',
        'value': hot_average_delta[-1],
    }, {
        'cost_function': 'one_minus_thermal_resilience_proportion',
        'value': kpi._cost_last(
            np.asarray(
                CostFunction.one_minus_thermal_resilience(
                    power_outage=kpi._thermal_values(building, building.power_outage_signal, t_start, t_end),
                    **discomfort_kwargs,
                ),
                dtype='float64',
            ),
            lambda x: x,
        ),
    }, {
        'cost_function': 'power_outage_normalized_unserved_energy_total',
        'value': kpi._cost_last(
            np.asarray(
                CostFunction.normalized_unserved_energy(
                    expected_energy,
                    served_energy,
                    power_outage=kpi._thermal_values(building, building.power_outage_signal, t_start, t_end),
                ),
                dtype='float64',
            ),
            lambda x: x,
        ),
    }, {
        'cost_function': 'annual_normalized_unserved_energy_total',
        'value': kpi._cost_last(
            np.asarray(CostFunction.normalized_unserved_energy(expected_energy, served_energy), dtype='float64'),
            lambda x: x,
        ),
    }])
    legacy_building_frame['name'] = building.name

    extended_building_rows.extend([
        kpi._metric('electricity_consumption_control_total_kwh', ec_c, building.name, 'building'),
        kpi._metric('electricity_consumption_baseline_total_kwh', ec_b, building.name, 'building'),
        kpi._metric('electricity_consumption_delta_total_kwh', ec_c - ec_b, building.name, 'building'),
        kpi._metric('electricity_consumption_control_daily_average_kwh', kpi._daily_average(ec_c, building_days), building.name, 'building'),
        kpi._metric('electricity_consumption_baseline_daily_average_kwh', kpi._daily_average(ec_b, building_days), building.name, 'building'),
        kpi._metric('electricity_consumption_delta_daily_average_kwh', kpi._daily_average(ec_c - ec_b, building_days), building.name, 'building'),
        kpi._metric('electricity_export_control_total_kwh', export_c, building.name, 'building'),
        kpi._metric('electricity_export_baseline_total_kwh', export_b, building.name, 'building'),
        kpi._metric('electricity_export_delta_total_kwh', export_c - export_b, building.name, 'building'),
        kpi._metric('electricity_export_control_daily_average_kwh', kpi._daily_average(export_c, building_days), building.name, 'building'),
        kpi._metric('electricity_export_baseline_daily_average_kwh', kpi._daily_average(export_b, building_days), building.name, 'building'),
        kpi._metric('electricity_export_delta_daily_average_kwh', kpi._daily_average(export_c - export_b, building_days), building.name, 'building'),
        kpi._metric('zero_net_energy_control_total_kwh', zne_c, building.name, 'building'),
        kpi._metric('zero_net_energy_baseline_total_kwh', zne_b, building.name, 'building'),
        kpi._metric('zero_net_energy_delta_total_kwh', zne_c - zne_b, building.name, 'building'),
        kpi._metric('zero_net_energy_control_daily_average_kwh', kpi._daily_average(zne_c, building_days), building.name, 'building'),
        kpi._metric('zero_net_energy_baseline_daily_average_kwh', kpi._daily_average(zne_b, building_days), building.name, 'building'),
        kpi._metric('zero_net_energy_delta_daily_average_kwh', kpi._daily_average(zne_c - zne_b, building_days), building.name, 'building'),
        kpi._metric('carbon_emissions_control_total_kgco2', ce_c, building.name, 'building'),
        kpi._metric('carbon_emissions_baseline_total_kgco2', ce_b, building.name, 'building'),
        kpi._metric('carbon_emissions_delta_total_kgco2', ce_c - ce_b, building.name, 'building'),
        kpi._metric('carbon_emissions_control_daily_average_kgco2', kpi._daily_average(ce_c, building_days), building.name, 'building'),
        kpi._metric('carbon_emissions_baseline_daily_average_kgco2', kpi._daily_average(ce_b, building_days), building.name, 'building'),
        kpi._metric('carbon_emissions_delta_daily_average_kgco2', kpi._daily_average(ce_c - ce_b, building_days), building.name, 'building'),
        kpi._metric('cost_control_total_eur', cost_c_raw, building.name, 'building'),
        kpi._metric('cost_baseline_total_eur', cost_b_raw, building.name, 'building'),
        kpi._metric('cost_delta_total_eur', cost_c_raw - cost_b_raw, building.name, 'building'),
        kpi._metric('cost_control_daily_average_eur', kpi._daily_average(cost_c_raw, building_days), building.name, 'building'),
        kpi._metric('cost_baseline_daily_average_eur', kpi._daily_average(cost_b_raw, building_days), building.name, 'building'),
        kpi._metric('cost_delta_daily_average_eur', kpi._daily_average(cost_c_raw - cost_b_raw, building_days), building.name, 'building'),
        kpi._metric('equity_relative_benefit_percent', equity_benefit, building.name, 'building'),
    ])
    return legacy_building_frame, extended_building_rows, equity_benefit


def district_records(kpi: "CityLearnKPIService", legacy_building, control_condition,
                     baseline_condition, evaluation_condition_cls, simulated_days):
    """Preserve district condition selection and legacy mean aggregation."""
    env = kpi.env
    get_net_electricity_consumption = lambda x, c: kpi._energy_values(x, getattr(x, f'net_electricity_consumption{c.value}'))
    get_net_electricity_consumption_cost = lambda x, c: kpi._energy_values(x, getattr(x, f'net_electricity_consumption_cost{c.value}'))
    get_net_electricity_consumption_emission = lambda x, c: kpi._energy_values(x, getattr(x, f'net_electricity_consumption_emission{c.value}'))
    daily_steps = kpi._window_steps(24.0 * 3600.0, env.seconds_per_time_step)
    monthly_steps = kpi._window_steps(730.0 * 3600.0, env.seconds_per_time_step)
    env_control_condition = (
        evaluation_condition_cls.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV
        if control_condition is None else control_condition
    )
    env_baseline_condition = (
        evaluation_condition_cls.WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV
        if baseline_condition is None else baseline_condition
    )

    net_c_env_series = np.array(get_net_electricity_consumption(env, env_control_condition), dtype='float64')
    net_b_env_series = np.array(get_net_electricity_consumption(env, env_baseline_condition), dtype='float64')
    ramp_c = kpi._ramping_final(net_c_env_series)
    ramp_b = kpi._ramping_final(net_b_env_series)
    dlf_daily_c = kpi._one_minus_load_factor_final(net_c_env_series, window=daily_steps)
    dlf_daily_b = kpi._one_minus_load_factor_final(net_b_env_series, window=daily_steps)
    dlf_monthly_c = kpi._one_minus_load_factor_final(net_c_env_series, window=monthly_steps)
    dlf_monthly_b = kpi._one_minus_load_factor_final(net_b_env_series, window=monthly_steps)
    peak_daily_c = kpi._peak_final(net_c_env_series, window=daily_steps)
    peak_daily_b = kpi._peak_final(net_b_env_series, window=daily_steps)
    peak_all_c = kpi._peak_final(net_c_env_series, window=env.time_steps)
    peak_all_b = kpi._peak_final(net_b_env_series, window=env.time_steps)

    legacy_district_base = pd.DataFrame([{
        'cost_function': 'ramping_average',
        'value': kpi._safe_div(ramp_c, ramp_b),
    }, {
        'cost_function': 'daily_one_minus_load_factor_average',
        'value': kpi._safe_div(dlf_daily_c, dlf_daily_b),
    }, {
        'cost_function': 'monthly_one_minus_load_factor_average',
        'value': kpi._safe_div(dlf_monthly_c, dlf_monthly_b),
    }, {
        'cost_function': 'daily_peak_average',
        'value': kpi._safe_div(peak_daily_c, peak_daily_b),
    }, {
        'cost_function': 'all_time_peak_average',
        'value': kpi._safe_div(peak_all_c, peak_all_b),
    }])

    legacy_district = pd.concat([legacy_district_base, legacy_building], ignore_index=True, sort=False)
    legacy_district = legacy_district.groupby(['cost_function'])[['value']].mean().reset_index()
    legacy_district['name'] = 'District'
    legacy_district['level'] = 'district'

    legacy_cost_functions = pd.concat([legacy_district, legacy_building], ignore_index=True, sort=False)

    # Extended KPI district-level
    ec_c_env = kpi._positive_total(net_c_env_series)
    ec_b_env = kpi._positive_total(net_b_env_series)
    export_c_env = kpi._sum_finite(np.clip(-net_c_env_series, 0.0, None))
    export_b_env = kpi._sum_finite(np.clip(-net_b_env_series, 0.0, None))
    zne_c_env = kpi._net_total(net_c_env_series)
    zne_b_env = kpi._net_total(net_b_env_series)
    ce_c_env = kpi._positive_total(get_net_electricity_consumption_emission(env, env_control_condition))
    ce_b_env = kpi._positive_total(get_net_electricity_consumption_emission(env, env_baseline_condition))
    env_control_cost_series = get_net_electricity_consumption_cost(env, env_control_condition)
    env_baseline_cost_series = get_net_electricity_consumption_cost(env, env_baseline_condition)
    cost_c_env_raw = kpi._sum_finite(env_control_cost_series)
    cost_b_env_raw = kpi._sum_finite(env_baseline_cost_series)

    extended_district_rows = [
        kpi._metric('electricity_consumption_control_total_kwh', ec_c_env, 'District', 'district'),
        kpi._metric('electricity_consumption_baseline_total_kwh', ec_b_env, 'District', 'district'),
        kpi._metric('electricity_consumption_delta_total_kwh', ec_c_env - ec_b_env, 'District', 'district'),
        kpi._metric('electricity_consumption_control_daily_average_kwh', kpi._daily_average(ec_c_env, simulated_days), 'District', 'district'),
        kpi._metric('electricity_consumption_baseline_daily_average_kwh', kpi._daily_average(ec_b_env, simulated_days), 'District', 'district'),
        kpi._metric('electricity_consumption_delta_daily_average_kwh', kpi._daily_average(ec_c_env - ec_b_env, simulated_days), 'District', 'district'),
        kpi._metric('electricity_export_control_total_kwh', export_c_env, 'District', 'district'),
        kpi._metric('electricity_export_baseline_total_kwh', export_b_env, 'District', 'district'),
        kpi._metric('electricity_export_delta_total_kwh', export_c_env - export_b_env, 'District', 'district'),
        kpi._metric('electricity_export_control_daily_average_kwh', kpi._daily_average(export_c_env, simulated_days), 'District', 'district'),
        kpi._metric('electricity_export_baseline_daily_average_kwh', kpi._daily_average(export_b_env, simulated_days), 'District', 'district'),
        kpi._metric('electricity_export_delta_daily_average_kwh', kpi._daily_average(export_c_env - export_b_env, simulated_days), 'District', 'district'),
        kpi._metric('zero_net_energy_control_total_kwh', zne_c_env, 'District', 'district'),
        kpi._metric('zero_net_energy_baseline_total_kwh', zne_b_env, 'District', 'district'),
        kpi._metric('zero_net_energy_delta_total_kwh', zne_c_env - zne_b_env, 'District', 'district'),
        kpi._metric('zero_net_energy_control_daily_average_kwh', kpi._daily_average(zne_c_env, simulated_days), 'District', 'district'),
        kpi._metric('zero_net_energy_baseline_daily_average_kwh', kpi._daily_average(zne_b_env, simulated_days), 'District', 'district'),
        kpi._metric('zero_net_energy_delta_daily_average_kwh', kpi._daily_average(zne_c_env - zne_b_env, simulated_days), 'District', 'district'),
        kpi._metric('carbon_emissions_control_total_kgco2', ce_c_env, 'District', 'district'),
        kpi._metric('carbon_emissions_baseline_total_kgco2', ce_b_env, 'District', 'district'),
        kpi._metric('carbon_emissions_delta_total_kgco2', ce_c_env - ce_b_env, 'District', 'district'),
        kpi._metric('carbon_emissions_control_daily_average_kgco2', kpi._daily_average(ce_c_env, simulated_days), 'District', 'district'),
        kpi._metric('carbon_emissions_baseline_daily_average_kgco2', kpi._daily_average(ce_b_env, simulated_days), 'District', 'district'),
        kpi._metric('carbon_emissions_delta_daily_average_kgco2', kpi._daily_average(ce_c_env - ce_b_env, simulated_days), 'District', 'district'),
        kpi._metric('cost_control_total_eur', cost_c_env_raw, 'District', 'district'),
        kpi._metric('cost_baseline_total_eur', cost_b_env_raw, 'District', 'district'),
        kpi._metric('cost_delta_total_eur', cost_c_env_raw - cost_b_env_raw, 'District', 'district'),
        kpi._metric('cost_control_daily_average_eur', kpi._daily_average(cost_c_env_raw, simulated_days), 'District', 'district'),
        kpi._metric('cost_baseline_daily_average_eur', kpi._daily_average(cost_b_env_raw, simulated_days), 'District', 'district'),
        kpi._metric('cost_delta_daily_average_eur', kpi._daily_average(cost_c_env_raw - cost_b_env_raw, simulated_days), 'District', 'district'),
    ]
    return legacy_cost_functions, extended_district_rows
