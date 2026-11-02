"""Executed/requested service KPI aggregation for appliances and escalators."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService


def deferrable_records(kpi: "CityLearnKPIService", kpi_buildings):
    extended_building_rows, extended_district_rows = [], []
    service_audit = kpi.deferrable_service_audit()
    for name, summary in service_audit['buildings'].items():
        extended_building_rows.extend(kpi._metric(f'deferrable_appliance_audit_{key}', value, name, 'building')
                    for key, value in summary.items())
    extended_district_rows.extend(kpi._metric(f'deferrable_appliance_audit_{key}', value, 'District', 'district')
                for key, value in service_audit['district'].items())

    district_deferrable = {
        'completed_cycles': 0.0,
        'missed_cycles': 0.0,
        'served_energy_kwh': 0.0,
        'unserved_energy_kwh': 0.0,
    }
    delay_weighted_sum = 0.0
    delay_weight = 0.0
    for building in kpi_buildings:
        building_summary = {
            'completed_cycles': 0.0,
            'missed_cycles': 0.0,
            'served_energy_kwh': 0.0,
            'unserved_energy_kwh': 0.0,
        }
        building_delay_weighted_sum = 0.0
        building_delay_weight = 0.0
        for appliance in kpi._deferrable_appliances_for_metrics(building):
            summary = appliance.service_summary()
            completed = kpi._to_scalar(summary.get('completed_cycles'), 0.0)
            for key in building_summary:
                building_summary[key] += kpi._to_scalar(summary.get(key), 0.0)
            if completed > 0.0:
                delay = kpi._to_scalar(summary.get('average_start_delay_hours'), 0.0)
                building_delay_weighted_sum += delay * completed
                building_delay_weight += completed

        requested = building_summary['completed_cycles'] + building_summary['missed_cycles']
        service_level = None if requested <= 0.0 else building_summary['completed_cycles'] / requested
        avg_delay = 0.0 if building_delay_weight <= 0.0 else building_delay_weighted_sum / building_delay_weight
        extended_building_rows.extend([
            kpi._metric('deferrable_appliance_completed_cycles_count', building_summary['completed_cycles'], building.name, 'building'),
            kpi._metric('deferrable_appliance_missed_cycles_count', building_summary['missed_cycles'], building.name, 'building'),
            kpi._metric('deferrable_appliance_service_level_ratio', service_level, building.name, 'building'),
            kpi._metric('deferrable_appliance_served_energy_total_kwh', building_summary['served_energy_kwh'], building.name, 'building'),
            kpi._metric('deferrable_appliance_unserved_energy_total_kwh', building_summary['unserved_energy_kwh'], building.name, 'building'),
            kpi._metric('deferrable_appliance_average_start_delay_hours', avg_delay, building.name, 'building'),
        ])

        for key in district_deferrable:
            district_deferrable[key] += building_summary[key]
        delay_weighted_sum += building_delay_weighted_sum
        delay_weight += building_delay_weight

    district_requested = district_deferrable['completed_cycles'] + district_deferrable['missed_cycles']
    district_service_level = None if district_requested <= 0.0 else district_deferrable['completed_cycles'] / district_requested
    district_avg_delay = 0.0 if delay_weight <= 0.0 else delay_weighted_sum / delay_weight
    extended_district_rows.extend([
        kpi._metric('deferrable_appliance_completed_cycles_count', district_deferrable['completed_cycles'], 'District', 'district'),
        kpi._metric('deferrable_appliance_missed_cycles_count', district_deferrable['missed_cycles'], 'District', 'district'),
        kpi._metric('deferrable_appliance_service_level_ratio', district_service_level, 'District', 'district'),
        kpi._metric('deferrable_appliance_served_energy_total_kwh', district_deferrable['served_energy_kwh'], 'District', 'district'),
        kpi._metric('deferrable_appliance_unserved_energy_total_kwh', district_deferrable['unserved_energy_kwh'], 'District', 'district'),
        kpi._metric('deferrable_appliance_average_start_delay_hours', district_avg_delay, 'District', 'district'),
    ])
    return extended_building_rows, extended_district_rows


def escalator_records(kpi: "CityLearnKPIService", kpi_buildings):
    extended_building_rows, extended_district_rows = [], []
    # Escalators deliberately use aggregate passenger demand rather than a
    # queueing model. These KPIs expose the resulting energy/service tradeoff
    # alongside the existing electricity cost metrics.
    district_escalator = {
        'requested_passengers': 0.0,
        'served_passengers': 0.0,
        'unserved_passengers': 0.0,
        'electricity_consumption_kwh': 0.0,
        'state_changes_count': 0.0,
    }
    for building in kpi_buildings:
        building_escalator = dict.fromkeys(district_escalator, 0.0)
        for escalator in getattr(building, 'escalators', []) or []:
            summary = escalator.service_summary()
            for key in building_escalator:
                building_escalator[key] += kpi._to_scalar(summary.get(key), 0.0)

        requested = building_escalator['requested_passengers']
        service_level = None if requested <= 0.0 else building_escalator['served_passengers'] / requested
        extended_building_rows.extend([
            kpi._metric('escalator_requested_passengers_total_count', requested, building.name, 'building'),
            kpi._metric('escalator_served_passengers_total_count', building_escalator['served_passengers'], building.name, 'building'),
            kpi._metric('escalator_unserved_passengers_total_count', building_escalator['unserved_passengers'], building.name, 'building'),
            kpi._metric('escalator_service_level_ratio', service_level, building.name, 'building'),
            kpi._metric('escalator_electricity_consumption_total_kwh', building_escalator['electricity_consumption_kwh'], building.name, 'building'),
            kpi._metric('escalator_state_changes_count', building_escalator['state_changes_count'], building.name, 'building'),
        ])
        for key in district_escalator:
            district_escalator[key] += building_escalator[key]

    district_requested = district_escalator['requested_passengers']
    district_service_level = None if district_requested <= 0.0 else district_escalator['served_passengers'] / district_requested
    extended_district_rows.extend([
        kpi._metric('escalator_requested_passengers_total_count', district_requested, 'District', 'district'),
        kpi._metric('escalator_served_passengers_total_count', district_escalator['served_passengers'], 'District', 'district'),
        kpi._metric('escalator_unserved_passengers_total_count', district_escalator['unserved_passengers'], 'District', 'district'),
        kpi._metric('escalator_service_level_ratio', district_service_level, 'District', 'district'),
        kpi._metric('escalator_electricity_consumption_total_kwh', district_escalator['electricity_consumption_kwh'], 'District', 'district'),
        kpi._metric('escalator_state_changes_count', district_escalator['state_changes_count'], 'District', 'district'),
    ])
    return extended_building_rows, extended_district_rows
