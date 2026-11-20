"""Single authoritative metadata registry for ``evaluate_v2()`` KPIs.

This module intentionally uses only the Python standard library so that runtime
evaluation, multi-community aggregation, export manifests and documentation
builds can all read the same canonical ``(unit, description)`` definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from types import MappingProxyType
from typing import Dict, Mapping, Tuple

KPI_COLUMNS: Tuple[str, ...] = (
    'cost_function',
    'value',
    'name',
    'level',
    'unit',
    'description',
)

KPI_UNITS: Mapping[str, str] = MappingProxyType({
    'EUR': 'Monetary value in euros (or dataset currency when not EUR).',
    'EUR/day': 'Daily average monetary value per simulated day.',
    'kWh': 'Accumulated energy in kilowatt-hours.',
    'kWh/day': 'Daily average energy in kilowatt-hours per simulated day.',
    'kW': 'Electrical power in kilowatts.',
    'kgCO2': 'Accumulated carbon dioxide equivalent emissions in kilograms.',
    'kgCO2/day': 'Daily average carbon dioxide equivalent emissions per simulated day.',
    'ratio': 'Dimensionless ratio or fraction (1.0 denotes parity against a reference).',
    'percent': 'Percentage on a 0-100 scale (or signed relative percentage change).',
    'count': 'Count of events, cycles, passengers, members or intervals.',
    'hours': 'Duration or start delay in hours.',
    'C': 'Temperature difference in degrees Celsius.',
    'C*h': 'Thermal discomfort integral in degree-Celsius hours.',
    'dimensionless': 'Dimensionless indicator or lifecycle presence placeholder.',
})

KPI_UNIT_SUFFIXES: Tuple[Tuple[str, str, str], ...] = (
    ('eur', 'EUR (EUR/day for daily averages)', 'Monetary cost, revenue, penalty, savings or operator balance (dataset currency when not EUR).'),
    ('kwh', 'kWh (kWh/day for daily averages)', 'Accumulated or daily average electrical or thermal service energy.'),
    ('kgco2', 'kgCO2 (kgCO2/day for daily averages)', 'Accumulated or daily average carbon dioxide equivalent emissions.'),
    ('kw', 'kW', 'Peak or step-transition ramping electrical power.'),
    ('ratio', 'ratio', 'Dimensionless ratio, rate or share.'),
    ('percent', 'percent', 'Percentage on a 0-100 scale or signed relative benefit percentage.'),
    ('count', 'count', 'Event, cycle, passenger, member or interval count.'),
    ('hours', 'hours (C*h for degree-hours)', 'Duration or delay in hours, or degree-Celsius hours for thermal discomfort integrals.'),
    ('c', 'C', 'Temperature exceedance in degrees Celsius.'),
)


@dataclass(frozen=True)
class KPIDefinition:
    """Canonical metadata record for one ``evaluate_v2()`` KPI."""

    cost_function: str
    unit: str
    description: str
    level: str
    family: str


_SCOPE_NOUN: Mapping[str, str] = {
    'building': 'building',
    'district': 'district',
    'portfolio': 'multi-community portfolio',
}

_SCOPE_PHRASE: Mapping[str, str] = {
    'building': 'for the building',
    'district': 'across the district',
    'portfolio': 'across the multi-community portfolio',
}

_PHASE_PEAK_PATTERN = re.compile(
    r'^(building|district|portfolio)_electrical_service_phase_phase_peaks_(import|export)_peak_([a-z0-9_]+)_kw$'
)


def _portfolio_description_from_district(cost_function: str, district_desc: str) -> str:
    """Adapt a district KPI description to its ``MultiCommunityEnv`` portfolio row."""
    text = district_desc
    if text.startswith('District '):
        text = 'Portfolio ' + text[len('District '):]
    elif text.startswith('Netted district '):
        text = 'Portfolio sum of netted community ' + text[len('Netted district '):]
    text = text.replace('across the district', 'across the multi-community portfolio')
    text = text.replace('for the district', 'across the multi-community portfolio')
    text = text.replace('of the district', 'of the multi-community portfolio')
    text = text.replace('in the district', 'across the multi-community portfolio')
    text = text.replace('affecting the district', 'affecting the multi-community portfolio')
    if 'multi-community portfolio' not in text and not text.startswith('Portfolio '):
        text = f'{text[:-1]} across the multi-community portfolio.' if text.endswith('.') else f'{text} across the multi-community portfolio.'
    return text


def _build_static_registry() -> Dict[str, KPIDefinition]:
    registry: Dict[str, KPIDefinition] = {}

    def register(cost_function: str, unit: str, description: str, *, level: str, family: str) -> None:
        if unit not in KPI_UNITS:
            raise ValueError(f'Unknown canonical KPI unit {unit!r} for {cost_function!r}.')
        if not description or not description.endswith('.'):
            raise ValueError(f'KPI description for {cost_function!r} must be a non-empty sentence ending with ".".')
        registry[cost_function] = KPIDefinition(
            cost_function=cost_function,
            unit=unit,
            description=description,
            level=level,
            family=family,
        )

    def register_levels(
        levels: Tuple[str, ...],
        suffix: str,
        unit: str,
        family: str,
        describe,
    ) -> None:
        for level in levels:
            desc = describe(level) if callable(describe) else str(describe).format(
                scope=_SCOPE_NOUN[level],
                in_scope=_SCOPE_PHRASE[level],
                Scope=_SCOPE_NOUN[level].capitalize(),
            )
            register(f'{level}_{suffix}', unit, desc, level=level, family=family)

    bd = ('building', 'district')

    # 1. Cost family
    cost_variants = (
        ('total_control_eur', 'EUR', 'Total electricity cost under the evaluated controller {in_scope}.'),
        ('total_baseline_eur', 'EUR', 'Total electricity cost of the conventional without-storage baseline counterfactual {in_scope}.'),
        ('total_delta_eur', 'EUR', 'Control minus conventional-baseline total electricity cost {in_scope} (negative indicates savings).'),
        ('daily_average_control_eur', 'EUR/day', 'Daily average electricity cost under the evaluated controller {in_scope}.'),
        ('daily_average_baseline_eur', 'EUR/day', 'Daily average electricity cost of the conventional without-storage baseline counterfactual {in_scope}.'),
        ('daily_average_delta_eur', 'EUR/day', 'Control minus conventional-baseline daily average electricity cost {in_scope}.'),
        ('ratio_to_baseline_total_ratio', 'ratio', 'Signed lower-is-better ratio of control total electricity cost to the conventional baseline {in_scope}.'),
        ('total_business_as_usual_eur', 'EUR', 'Total electricity cost of the native business-as-usual reference rollout {in_scope}.'),
        ('total_delta_to_business_as_usual_eur', 'EUR', 'Control minus native business-as-usual total electricity cost {in_scope} (negative indicates savings).'),
        ('daily_average_business_as_usual_eur', 'EUR/day', 'Daily average electricity cost of the native business-as-usual reference rollout {in_scope}.'),
        ('daily_average_delta_to_business_as_usual_eur', 'EUR/day', 'Control minus native business-as-usual daily average electricity cost {in_scope}.'),
        ('ratio_to_business_as_usual_total_ratio', 'ratio', 'Signed lower-is-better ratio of control total electricity cost to the native business-as-usual reference {in_scope}.'),
        ('community_market_settled_total_eur', 'EUR', 'Total electricity cost after local community-market settlement {in_scope}.'),
        ('community_market_settled_daily_average_eur', 'EUR/day', 'Daily average electricity cost after local community-market settlement {in_scope}.'),
        ('community_market_counterfactual_total_eur', 'EUR', 'Total electricity cost without local community-market settlement {in_scope}.'),
        ('community_market_counterfactual_daily_average_eur', 'EUR/day', 'Daily average electricity cost without local community-market settlement {in_scope}.'),
        ('community_market_savings_total_eur', 'EUR', 'Total cost savings from local community-market settlement (counterfactual minus settled) {in_scope}.'),
        ('community_market_savings_daily_average_eur', 'EUR/day', 'Daily average cost savings from local community-market settlement {in_scope}.'),
    )
    for suffix, unit, template in cost_variants:
        register_levels(bd, f'cost_{suffix}', unit, 'cost', template)
    register(
        'district_cost_community_market_operator_balance_total_eur',
        'EUR',
        'Residual community-market operator financial balance from heterogeneous member tariffs across the district.',
        level='district',
        family='cost',
    )

    # 2. Energy grid family
    flow_labels = {
        'import': ('grid electricity import', 'netted district grid electricity import'),
        'export': ('grid electricity export', 'netted district grid electricity export'),
        'net_exchange': ('signed net grid electricity exchange (import minus export)', 'netted district signed electricity exchange (import minus export)'),
    }
    for metric, (b_flow, d_flow) in flow_labels.items():
        def _flow(level: str, b=b_flow, d=d_flow) -> str:
            return d if level == 'district' else f'{b} {_SCOPE_PHRASE[level]}'

        register_levels(bd, f'energy_grid_total_{metric}_control_kwh', 'kWh', 'energy_grid',
                        lambda lv, f=_flow: f'Total {f(lv)} under the evaluated controller.')
        register_levels(bd, f'energy_grid_total_{metric}_baseline_kwh', 'kWh', 'energy_grid',
                        lambda lv, f=_flow: f'Total {f(lv)} under the conventional without-storage baseline counterfactual.')
        register_levels(bd, f'energy_grid_total_{metric}_delta_kwh', 'kWh', 'energy_grid',
                        lambda lv, f=_flow: f'Control minus conventional-baseline total {f(lv)}.')
        register_levels(bd, f'energy_grid_daily_average_{metric}_control_kwh', 'kWh/day', 'energy_grid',
                        lambda lv, f=_flow: f'Daily average {f(lv)} under the evaluated controller.')
        register_levels(bd, f'energy_grid_daily_average_{metric}_baseline_kwh', 'kWh/day', 'energy_grid',
                        lambda lv, f=_flow: f'Daily average {f(lv)} under the conventional without-storage baseline counterfactual.')
        register_levels(bd, f'energy_grid_daily_average_{metric}_delta_kwh', 'kWh/day', 'energy_grid',
                        lambda lv, f=_flow: f'Control minus conventional-baseline daily average {f(lv)}.')
        register_levels(bd, f'energy_grid_total_{metric}_business_as_usual_kwh', 'kWh', 'energy_grid',
                        lambda lv, f=_flow: f'Total {f(lv)} of the native business-as-usual reference rollout.')
        register_levels(bd, f'energy_grid_total_{metric}_delta_to_business_as_usual_kwh', 'kWh', 'energy_grid',
                        lambda lv, f=_flow: f'Control minus native business-as-usual total {f(lv)}.')
        register_levels(bd, f'energy_grid_daily_average_{metric}_business_as_usual_kwh', 'kWh/day', 'energy_grid',
                        lambda lv, f=_flow: f'Daily average {f(lv)} of the native business-as-usual reference rollout.')
        register_levels(bd, f'energy_grid_daily_average_{metric}_delta_to_business_as_usual_kwh', 'kWh/day', 'energy_grid',
                        lambda lv, f=_flow: f'Control minus native business-as-usual daily average {f(lv)}.')
        signed_note = 'Signed lower-is-better ratio' if metric == 'net_exchange' else 'Ratio'
        register_levels(bd, f'energy_grid_ratio_to_baseline_{metric}_total_ratio', 'ratio', 'energy_grid',
                        lambda lv, f=_flow, sn=signed_note: f'{sn} of control total {f(lv)} to the conventional baseline.')
        register_levels(bd, f'energy_grid_ratio_to_business_as_usual_{metric}_total_ratio', 'ratio', 'energy_grid',
                        lambda lv, f=_flow, sn=signed_note: f'{sn} of control total {f(lv)} to the native business-as-usual reference.')

    register(
        'district_energy_grid_ratio_to_baseline_import_total_building_mean_ratio',
        'ratio',
        'Arithmetic mean of per-building control-to-baseline grid import ratios across the district (retained 3.6.0 definition).',
        level='district',
        family='energy_grid',
    )
    register(
        'district_energy_grid_ratio_to_baseline_net_exchange_total_building_mean_ratio',
        'ratio',
        'Arithmetic mean of per-building control-to-baseline signed net-exchange ratios across the district (retained 3.6.0 definition).',
        level='district',
        family='energy_grid',
    )

    # Community market energy grid rows
    market_grid_rows = (
        ('local_import_total_kwh', 'kWh', 'Total locally imported community-market electricity {in_scope}.'),
        ('local_export_total_kwh', 'kWh', 'Total locally exported community-market electricity {in_scope}.'),
        ('grid_import_after_local_total_kwh', 'kWh', 'Total external grid electricity import remaining after local community-market matching {in_scope}.'),
        ('grid_export_after_local_total_kwh', 'kWh', 'Total external grid electricity export remaining after local community-market matching {in_scope}.'),
        ('local_import_daily_average_kwh', 'kWh/day', 'Daily average locally imported community-market electricity {in_scope}.'),
        ('local_export_daily_average_kwh', 'kWh/day', 'Daily average locally exported community-market electricity {in_scope}.'),
        ('grid_import_after_local_daily_average_kwh', 'kWh/day', 'Daily average external grid import remaining after local community-market matching {in_scope}.'),
        ('grid_export_after_local_daily_average_kwh', 'kWh/day', 'Daily average external grid export remaining after local community-market matching {in_scope}.'),
    )
    for suffix, unit, template in market_grid_rows:
        register_levels(bd, f'energy_grid_community_market_{suffix}', unit, 'energy_grid', template)
    register(
        'district_energy_grid_community_market_local_traded_total_kwh',
        'kWh',
        'Total electricity traded locally within the community market across the district.',
        level='district',
        family='energy_grid',
    )
    register(
        'district_energy_grid_community_market_local_traded_daily_average_kwh',
        'kWh/day',
        'Daily average electricity traded locally within the community market across the district.',
        level='district',
        family='energy_grid',
    )

    # District shape quality rows
    shape_rows = (
        ('ramping_average_to_baseline_ratio', 'ratio', 'Ratio of mean upward step-to-step district net-power ramp to the conventional baseline.'),
        ('ramping_average_business_as_usual_kw', 'kW', 'Mean upward step-to-step district net-power ramp of the native business-as-usual rollout.'),
        ('ramping_average_delta_to_business_as_usual_kw', 'kW', 'Control minus native business-as-usual mean upward step-to-step district net-power ramp.'),
        ('ramping_average_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean upward step-to-step district net-power ramp to the native business-as-usual rollout.'),
        ('ramping_total_business_as_usual_kw', 'kW', 'Cumulative upward step-to-step district net-power ramp of the native business-as-usual rollout (retained 3.6.0 definition).'),
        ('ramping_total_delta_to_business_as_usual_kw', 'kW', 'Control minus native business-as-usual cumulative upward district net-power ramp (retained 3.6.0 definition).'),
        ('load_factor_penalty_daily_average_to_baseline_ratio', 'ratio', 'Ratio of mean daily (24 h) import-power load-factor penalty (1 - mean / peak) to the conventional baseline across the district.'),
        ('load_factor_penalty_monthly_average_to_baseline_ratio', 'ratio', 'Ratio of mean monthly (730 h) import-power load-factor penalty (1 - mean / peak) to the conventional baseline across the district.'),
        ('load_factor_penalty_daily_average_to_baseline_signed_net_ratio', 'ratio', 'Ratio of mean daily (24 h) signed-net load-factor penalty to the conventional baseline across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_monthly_average_to_baseline_signed_net_ratio', 'ratio', 'Ratio of mean monthly (730 h) signed-net load-factor penalty to the conventional baseline across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_daily_average_business_as_usual_ratio', 'ratio', 'Mean daily (24 h) import-power load-factor penalty (1 - mean / peak) of the native business-as-usual rollout across the district.'),
        ('load_factor_penalty_daily_average_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual mean daily (24 h) import-power load-factor penalty across the district.'),
        ('load_factor_penalty_daily_average_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean daily (24 h) import-power load-factor penalty to the native business-as-usual rollout across the district.'),
        ('load_factor_penalty_monthly_average_business_as_usual_ratio', 'ratio', 'Mean monthly (730 h) import-power load-factor penalty (1 - mean / peak) of the native business-as-usual rollout across the district.'),
        ('load_factor_penalty_monthly_average_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual mean monthly (730 h) import-power load-factor penalty across the district.'),
        ('load_factor_penalty_monthly_average_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean monthly (730 h) import-power load-factor penalty to the native business-as-usual rollout across the district.'),
        ('load_factor_penalty_daily_average_signed_net_business_as_usual_ratio', 'ratio', 'Mean daily (24 h) signed-net load-factor penalty of the native business-as-usual rollout across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_daily_average_signed_net_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual mean daily (24 h) signed-net load-factor penalty across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_daily_average_signed_net_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean daily (24 h) signed-net load-factor penalty to the native business-as-usual rollout across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_monthly_average_signed_net_business_as_usual_ratio', 'ratio', 'Mean monthly (730 h) signed-net load-factor penalty of the native business-as-usual rollout across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_monthly_average_signed_net_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual mean monthly (730 h) signed-net load-factor penalty across the district (retained 3.6.0 definition).'),
        ('load_factor_penalty_monthly_average_signed_net_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean monthly (730 h) signed-net load-factor penalty to the native business-as-usual rollout across the district (retained 3.6.0 definition).'),
        ('peak_daily_average_to_baseline_ratio', 'ratio', 'Ratio of mean daily (24 h) peak district net power to the conventional baseline.'),
        ('peak_daily_average_business_as_usual_kw', 'kW', 'Mean daily (24 h) peak district net power of the native business-as-usual rollout.'),
        ('peak_daily_average_delta_to_business_as_usual_kw', 'kW', 'Control minus native business-as-usual mean daily (24 h) peak district net power.'),
        ('peak_daily_average_to_business_as_usual_ratio', 'ratio', 'Ratio of control mean daily (24 h) peak district net power to the native business-as-usual rollout.'),
        ('peak_all_time_average_to_baseline_ratio', 'ratio', 'Ratio of episode peak district net power to the conventional baseline.'),
        ('peak_all_time_average_business_as_usual_kw', 'kW', 'Episode peak district net power of the native business-as-usual rollout.'),
        ('peak_all_time_average_delta_to_business_as_usual_kw', 'kW', 'Control minus native business-as-usual episode peak district net power.'),
        ('peak_all_time_average_to_business_as_usual_ratio', 'ratio', 'Ratio of control episode peak district net power to the native business-as-usual rollout.'),
    )
    for suffix, unit, desc in shape_rows:
        register(f'district_energy_grid_shape_quality_{suffix}', unit, desc, level='district', family='energy_grid')

    # 3. Emissions family
    def _emissions_basis(level: str) -> str:
        return 'netted district external grid import emissions' if level == 'district' else 'building grid import emissions'

    register_levels(bd, 'emissions_total_control_kgco2', 'kgCO2', 'emissions',
                    lambda lv: f'Total {_emissions_basis(lv)} under the evaluated controller.')
    register_levels(bd, 'emissions_total_baseline_kgco2', 'kgCO2', 'emissions',
                    lambda lv: f'Total {_emissions_basis(lv)} under the conventional without-storage baseline counterfactual.')
    register_levels(bd, 'emissions_total_delta_kgco2', 'kgCO2', 'emissions',
                    lambda lv: f'Control minus conventional-baseline total {_emissions_basis(lv)}.')
    register_levels(bd, 'emissions_daily_average_control_kgco2', 'kgCO2/day', 'emissions',
                    lambda lv: f'Daily average {_emissions_basis(lv)} under the evaluated controller.')
    register_levels(bd, 'emissions_daily_average_baseline_kgco2', 'kgCO2/day', 'emissions',
                    lambda lv: f'Daily average {_emissions_basis(lv)} under the conventional without-storage baseline counterfactual.')
    register_levels(bd, 'emissions_daily_average_delta_kgco2', 'kgCO2/day', 'emissions',
                    lambda lv: f'Control minus conventional-baseline daily average {_emissions_basis(lv)}.')
    register_levels(bd, 'emissions_ratio_to_baseline_total_ratio', 'ratio', 'emissions',
                    lambda lv: f'Ratio of control total {_emissions_basis(lv)} to the conventional baseline.')
    register_levels(bd, 'emissions_total_business_as_usual_kgco2', 'kgCO2', 'emissions',
                    lambda lv: f'Total {_emissions_basis(lv)} of the native business-as-usual reference rollout.')
    register_levels(bd, 'emissions_total_delta_to_business_as_usual_kgco2', 'kgCO2', 'emissions',
                    lambda lv: f'Control minus native business-as-usual total {_emissions_basis(lv)}.')
    register_levels(bd, 'emissions_daily_average_business_as_usual_kgco2', 'kgCO2/day', 'emissions',
                    lambda lv: f'Daily average {_emissions_basis(lv)} of the native business-as-usual reference rollout.')
    register_levels(bd, 'emissions_daily_average_delta_to_business_as_usual_kgco2', 'kgCO2/day', 'emissions',
                    lambda lv: f'Control minus native business-as-usual daily average {_emissions_basis(lv)}.')
    register_levels(bd, 'emissions_ratio_to_business_as_usual_total_ratio', 'ratio', 'emissions',
                    lambda lv: f'Ratio of control total {_emissions_basis(lv)} to the native business-as-usual reference.')
    register(
        'district_emissions_total_control_member_sum_kgco2',
        'kgCO2',
        'Sum of un-netted per-building grid import emissions under the evaluated controller across the district (retained 3.6.0 definition).',
        level='district',
        family='emissions',
    )
    register(
        'district_emissions_total_baseline_member_sum_kgco2',
        'kgCO2',
        'Sum of un-netted per-building grid import emissions under the conventional baseline across the district (retained 3.6.0 definition).',
        level='district',
        family='emissions',
    )
    register(
        'district_emissions_total_business_as_usual_member_sum_kgco2',
        'kgCO2',
        'Sum of un-netted per-building grid import emissions of the native business-as-usual rollout across the district (retained 3.6.0 definition).',
        level='district',
        family='emissions',
    )
    register(
        'district_emissions_ratio_to_baseline_total_building_mean_ratio',
        'ratio',
        'Arithmetic mean of per-building control-to-baseline emissions ratios across the district (retained 3.6.0 definition).',
        level='district',
        family='emissions',
    )

    # 4. Solar self-consumption family
    def _pv_export_phrase(level: str) -> str:
        return (
            'PV-backed net electricity exported outside the district after intra-community balancing'
            if level == 'district'
            else 'PV-backed net electricity exported by the building'
        )

    register_levels(bd, 'solar_self_consumption_total_generation_kwh', 'kWh', 'solar_self_consumption',
                    'Total available solar PV generation {in_scope}.')
    register_levels(bd, 'solar_self_consumption_total_generation_business_as_usual_kwh', 'kWh', 'solar_self_consumption',
                    'Total available solar PV generation of the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_total_generation_delta_to_business_as_usual_kwh', 'kWh', 'solar_self_consumption',
                    'Control minus native business-as-usual total solar PV generation {in_scope}.')
    register_levels(bd, 'solar_self_consumption_daily_average_generation_kwh', 'kWh/day', 'solar_self_consumption',
                    'Daily average solar PV generation {in_scope}.')
    register_levels(bd, 'solar_self_consumption_daily_average_generation_business_as_usual_kwh', 'kWh/day', 'solar_self_consumption',
                    'Daily average solar PV generation of the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_daily_average_generation_delta_to_business_as_usual_kwh', 'kWh/day', 'solar_self_consumption',
                    'Control minus native business-as-usual daily average solar PV generation {in_scope}.')
    register_levels(bd, 'solar_self_consumption_total_curtailment_kwh', 'kWh', 'solar_self_consumption',
                    'Total curtailed solar PV generation {in_scope}.')
    register_levels(bd, 'solar_self_consumption_total_export_kwh', 'kWh', 'solar_self_consumption',
                    lambda lv: f'Total {_pv_export_phrase(lv)} under the evaluated controller.')
    register_levels(bd, 'solar_self_consumption_total_export_business_as_usual_kwh', 'kWh', 'solar_self_consumption',
                    lambda lv: f'Total {_pv_export_phrase(lv)} of the native business-as-usual rollout.')
    register_levels(bd, 'solar_self_consumption_total_export_delta_to_business_as_usual_kwh', 'kWh', 'solar_self_consumption',
                    lambda lv: f'Control minus native business-as-usual total {_pv_export_phrase(lv)}.')
    register_levels(bd, 'solar_self_consumption_daily_average_export_kwh', 'kWh/day', 'solar_self_consumption',
                    lambda lv: f'Daily average {_pv_export_phrase(lv)} under the evaluated controller.')
    register_levels(bd, 'solar_self_consumption_daily_average_export_business_as_usual_kwh', 'kWh/day', 'solar_self_consumption',
                    lambda lv: f'Daily average {_pv_export_phrase(lv)} of the native business-as-usual rollout.')
    register_levels(bd, 'solar_self_consumption_daily_average_export_delta_to_business_as_usual_kwh', 'kWh/day', 'solar_self_consumption',
                    lambda lv: f'Control minus native business-as-usual daily average {_pv_export_phrase(lv)}.')
    register_levels(bd, 'solar_self_consumption_ratio_self_consumption_ratio', 'ratio', 'solar_self_consumption',
                    'Share of solar PV generation consumed locally rather than exported or curtailed {in_scope}.')
    register_levels(bd, 'solar_self_consumption_ratio_self_consumption_business_as_usual_ratio', 'ratio', 'solar_self_consumption',
                    'Solar PV self-consumption share of the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio', 'ratio', 'solar_self_consumption',
                    'Control minus native business-as-usual solar PV self-consumption share {in_scope}.')
    register_levels(bd, 'solar_self_consumption_ratio_to_business_as_usual_generation_total_ratio', 'ratio', 'solar_self_consumption',
                    'Ratio of control total solar PV generation to the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_ratio_to_business_as_usual_export_total_ratio', 'ratio', 'solar_self_consumption',
                    'Ratio of control total PV-backed export to the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio', 'ratio', 'solar_self_consumption',
                    'Ratio of control solar PV self-consumption share to the native business-as-usual rollout {in_scope}.')
    register_levels(bd, 'solar_self_consumption_community_market_local_share_of_demand_ratio', 'ratio', 'solar_self_consumption',
                    'Share of member electricity import demand covered by local community-market trading {in_scope}.')
    register_levels(bd, 'solar_self_consumption_community_market_local_share_of_export_ratio', 'ratio', 'solar_self_consumption',
                    'Share of member electricity export absorbed locally within the community market {in_scope}.')
    register_levels(bd, 'solar_self_consumption_community_market_import_share_ratio', 'ratio', 'solar_self_consumption',
                    'Share of total member import demand served through local community-market trading {in_scope}.')

    # 5. EV and EV departure audit family
    ev_rows = (
        ('events_departure_count', 'count', 'Observed EV departure events {in_scope}.'),
        ('events_departure_met_count', 'count', 'EV departures meeting the strict requested target SOC {in_scope}.'),
        ('events_departure_min_acceptable_count', 'count', 'EV departures meeting at least target SOC minus the service tolerance {in_scope}.'),
        ('events_departure_within_tolerance_count', 'count', 'EV departures finishing within the symmetric target SOC tolerance band {in_scope}.'),
        ('events_departure_target_feasible_count', 'count', 'EV departures whose strict target SOC was physically reachable under maximum charging and service limits {in_scope}.'),
        ('events_departure_target_infeasible_count', 'count', 'EV departures whose strict target SOC was physically unreachable under maximum charging and service limits {in_scope}.'),
        ('events_departure_min_acceptable_feasible_count', 'count', 'EV departures whose minimum acceptable SOC threshold was physically reachable {in_scope}.'),
        ('events_departure_min_acceptable_infeasible_count', 'count', 'EV departures whose minimum acceptable SOC threshold was physically unreachable {in_scope}.'),
        ('events_departure_within_tolerance_feasible_count', 'count', 'EV departures whose symmetric tolerance band lower bound was physically reachable {in_scope}.'),
        ('events_departure_within_tolerance_infeasible_count', 'count', 'EV departures whose symmetric tolerance band lower bound was physically unreachable {in_scope}.'),
        ('performance_departure_success_ratio', 'ratio', 'Fraction of EV departures meeting the strict requested target SOC {in_scope}.'),
        ('performance_departure_min_acceptable_ratio', 'ratio', 'Fraction of EV departures meeting at least target SOC minus the service tolerance {in_scope}.'),
        ('performance_departure_within_tolerance_ratio', 'ratio', 'Fraction of EV departures finishing within the symmetric target SOC tolerance band {in_scope}.'),
        ('performance_departure_success_feasible_ratio', 'ratio', 'Strict target SOC fulfillment rate over physically feasible EV departures {in_scope}.'),
        ('performance_departure_min_acceptable_feasible_ratio', 'ratio', 'Minimum acceptable SOC fulfillment rate over physically feasible EV departures {in_scope}.'),
        ('performance_departure_within_tolerance_feasible_ratio', 'ratio', 'Symmetric target SOC band fulfillment rate over physically feasible EV departures {in_scope}.'),
        ('performance_departure_soc_deficit_mean_ratio', 'ratio', 'Mean non-negative departure SOC deficit below the requested target SOC {in_scope}.'),
        ('performance_departure_shortfall_beyond_tolerance_mean_ratio', 'ratio', 'Mean departure SOC shortfall below the minimum acceptable threshold (target minus service tolerance) {in_scope}.'),
        ('performance_departure_soc_surplus_mean_ratio', 'ratio', 'Mean non-negative departure SOC surplus above the requested target SOC {in_scope}.'),
        ('performance_departure_soc_absolute_error_mean_ratio', 'ratio', 'Mean absolute departure SOC error relative to the requested target SOC {in_scope}.'),
        ('performance_departure_tolerance_ratio', 'ratio', 'Configured EV departure service SOC tolerance {in_scope}.'),
        ('total_charge_kwh', 'kWh', 'Total electricity charged into connected EVs under the evaluated controller {in_scope}.'),
        ('total_charge_business_as_usual_kwh', 'kWh', 'Total electricity charged into connected EVs in the native business-as-usual rollout {in_scope}.'),
        ('total_charge_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual EV charging energy {in_scope}.'),
        ('total_v2g_export_kwh', 'kWh', 'Total vehicle-to-grid (V2G) electricity discharged by connected EVs under the evaluated controller {in_scope}.'),
        ('total_v2g_export_business_as_usual_kwh', 'kWh', 'Total vehicle-to-grid (V2G) electricity discharged by connected EVs in the native business-as-usual rollout {in_scope}.'),
        ('total_v2g_export_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual V2G discharged energy {in_scope}.'),
        ('ratio_to_business_as_usual_charge_total_ratio', 'ratio', 'Ratio of control EV charging energy to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_v2g_export_total_ratio', 'ratio', 'Ratio of control EV V2G discharged energy to the native business-as-usual rollout {in_scope}.'),
        ('energy_accounting_connected_soc_gain_kwh', 'kWh', 'Net stored battery energy gained by EVs during connected charging sessions {in_scope}.'),
        ('energy_accounting_shortfall_kwh', 'kWh', 'Total unserved EV departure battery energy below requested departure targets {in_scope}.'),
        ('departure_audit_departures_count', 'count', 'Audited EV departures on active chargers within the evaluated window {in_scope}.'),
        ('departure_audit_service_observed_count', 'count', 'Audited EV departures with both a valid target SOC and an observed departure SOC {in_scope}.'),
        ('departure_audit_service_unknown_count', 'count', 'Audited EV departures missing a valid target SOC or observed departure SOC {in_scope}.'),
        ('departure_audit_service_coverage_ratio', 'ratio', 'Share of audited EV departures with observed departure service outcome {in_scope}.'),
    )
    for suffix, unit, template in ev_rows:
        register_levels(bd, f'ev_{suffix}', unit, 'ev', template)

    ev_thresholds = (
        ('target', 'strict target SOC'),
        ('min_acceptable', 'minimum acceptable departure SOC'),
        ('within_tolerance', 'symmetric target tolerance band'),
    )
    ev_unknown_reasons = (
        ('missing_target', 'missing or invalid target SOC'),
        ('missing_ev', 'no connected EV object on departure'),
        ('missing_battery', 'missing EV battery model'),
        ('invalid_capacity', 'non-positive or non-finite battery capacity'),
        ('invalid_charger_power', 'negative or non-finite charger max charging power'),
        ('invalid_charger_efficiency', 'charger efficiency outside [0, 1]'),
        ('invalid_time_step', 'non-positive or non-finite timestep duration'),
        ('missing_arrival_soc', 'unavailable session-start arrival SOC boundary'),
        ('unsupported_battery_model', 'custom battery class without physical replay support'),
        ('invalid_battery_parameters', 'invalid battery power, efficiency, loss or max-SOC parameters'),
        ('outage_supply_not_replayed', 'power outage during session preventing standalone feasibility disproof'),
    )
    for threshold, t_label in ev_thresholds:
        threshold_rows = (
            (f'{threshold}_feasible_count', 'count', f'Audited EV departures confirmed physically feasible for {t_label} {{in_scope}}.'),
            (f'{threshold}_infeasible_count', 'count', f'Audited EV departures confirmed physically infeasible for {t_label} {{in_scope}}.'),
            (f'{threshold}_unknown_count', 'count', f'Audited EV departures with unknown physical feasibility for {t_label} {{in_scope}}.'),
            (f'{threshold}_service_met_count', 'count', f'Audited EV departures with observed service meeting {t_label} {{in_scope}}.'),
            (f'{threshold}_feasible_service_observed_count', 'count', f'Confirmed-feasible audited EV departures with observed service for {t_label} {{in_scope}}.'),
            (f'{threshold}_feasible_service_met_count', 'count', f'Confirmed-feasible audited EV departures meeting {t_label} {{in_scope}}.'),
            (f'{threshold}_coverage_ratio', 'ratio', f'Share of audited EV departures with known feasibility (feasible or infeasible) for {t_label} {{in_scope}}.'),
            (f'{threshold}_service_observed_ratio', 'ratio', f'Fulfillment rate of {t_label} across audited departures with observed service {{in_scope}}.'),
            (f'{threshold}_service_feasible_ratio', 'ratio', f'Fulfillment rate of {t_label} across confirmed-feasible audited departures with observed service {{in_scope}}.'),
        )
        for suffix, unit, template in threshold_rows:
            register_levels(bd, f'ev_departure_audit_{suffix}', unit, 'ev', template)
        for reason, r_label in ev_unknown_reasons:
            register_levels(
                bd,
                f'ev_departure_audit_{threshold}_unknown_{reason}_count',
                'count',
                'ev',
                f'Audited EV departures with unknown {t_label} feasibility due to {r_label} {{in_scope}}.',
            )

    # 6. Stationary battery (BESS) family
    battery_rows = (
        ('total_charge_kwh', 'kWh', 'Total electricity charged into stationary batteries under the evaluated controller {in_scope}.'),
        ('total_charge_business_as_usual_kwh', 'kWh', 'Total electricity charged into stationary batteries in the native business-as-usual rollout {in_scope}.'),
        ('total_charge_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual stationary battery charging energy {in_scope}.'),
        ('total_discharge_kwh', 'kWh', 'Total electricity discharged from stationary batteries under the evaluated controller {in_scope}.'),
        ('total_discharge_business_as_usual_kwh', 'kWh', 'Total electricity discharged from stationary batteries in the native business-as-usual rollout {in_scope}.'),
        ('total_discharge_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual stationary battery discharging energy {in_scope}.'),
        ('total_throughput_kwh', 'kWh', 'Total stationary battery cycling throughput (gross charge plus gross discharge) under the evaluated controller {in_scope}.'),
        ('total_throughput_business_as_usual_kwh', 'kWh', 'Total stationary battery cycling throughput in the native business-as-usual rollout {in_scope}.'),
        ('total_throughput_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual stationary battery cycling throughput {in_scope}.'),
        ('health_equivalent_full_cycles_count', 'count', 'Equivalent full charge-discharge cycles of stationary batteries (throughput / (2 * capacity)) {in_scope}.'),
        ('health_equivalent_full_cycles_business_as_usual_count', 'count', 'Equivalent full charge-discharge cycles of stationary batteries in the native business-as-usual rollout {in_scope}.'),
        ('health_equivalent_full_cycles_delta_to_business_as_usual_count', 'count', 'Control minus native business-as-usual stationary battery equivalent full cycles {in_scope}.'),
        ('health_capacity_fade_ratio', 'ratio', 'Relative stationary battery capacity degradation fraction ((capacity - degraded_capacity) / capacity) {in_scope}.'),
        ('health_capacity_fade_business_as_usual_ratio', 'ratio', 'Relative stationary battery capacity degradation fraction in the native business-as-usual rollout {in_scope}.'),
        ('health_capacity_fade_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual stationary battery capacity degradation fraction {in_scope}.'),
        ('ratio_to_business_as_usual_charge_ratio', 'ratio', 'Ratio of control stationary battery charging energy to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_discharge_ratio', 'ratio', 'Ratio of control stationary battery discharging energy to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_throughput_ratio', 'ratio', 'Ratio of control stationary battery cycling throughput to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_equivalent_full_cycles_ratio', 'ratio', 'Ratio of control stationary battery equivalent full cycles to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_capacity_fade_ratio', 'ratio', 'Ratio of control stationary battery capacity degradation to the native business-as-usual rollout {in_scope}.'),
    )
    for suffix, unit, template in battery_rows:
        register_levels(bd, f'battery_{suffix}', unit, 'battery', template)

    # 7. Electrical service and phase family
    electrical_rows = (
        ('violations_energy_total_kwh', 'kWh', 'Residual energy exceeding declared total or per-phase electrical service limits after physical projection {in_scope}.'),
        ('violations_event_count', 'count', 'Executed intervals with residual exceedance of declared electrical service limits after physical projection {in_scope}.'),
        ('requested_pressure_energy_total_kwh', 'kWh', 'Unprojected controller request energy exceeding declared electrical service limits before projection {in_scope}.'),
        ('requested_pressure_event_count', 'count', 'Executed intervals where the unprojected controller request exceeded declared electrical service limits {in_scope}.'),
        ('imbalance_phase_average_ratio', 'ratio', 'Mean three-phase active-power imbalance ratio across evaluated intervals {in_scope}.'),
    )
    for suffix, unit, template in electrical_rows:
        register_levels(bd, f'electrical_service_phase_{suffix}', unit, 'electrical_service_phase', template)
    for phase in ('l1', 'l2', 'l3'):
        phase_upper = phase.upper()
        register_levels(
            bd,
            f'electrical_service_phase_phase_peaks_import_peak_{phase}_kw',
            'kW',
            'electrical_service_phase',
            f'Peak active import power on phase {phase_upper} {{in_scope}}.',
        )
        register_levels(
            bd,
            f'electrical_service_phase_phase_peaks_export_peak_{phase}_kw',
            'kW',
            'electrical_service_phase',
            f'Peak active export power on phase {phase_upper} {{in_scope}}.',
        )

    # 8. Equity and equity audit family
    register(
        'building_equity_benefit_relative_percent',
        'percent',
        'Relative electricity cost reduction percentage of the building compared with the conventional baseline.',
        level='building',
        family='equity',
    )
    equity_district_rows = (
        ('equity_distribution_gini_benefit_ratio', 'ratio', 'Gini inequality coefficient of non-negative member relative cost benefits across the district.'),
        ('equity_distribution_top20_benefit_ratio', 'ratio', 'Share of total positive relative cost benefit captured by the top 20% of members across the district.'),
        ('equity_distribution_losers_percent', 'percent', 'Percentage of evaluated members experiencing higher electricity cost than the conventional baseline across the district.'),
        ('equity_distribution_bpr_asset_poor_over_rich_ratio', 'ratio', 'Benefit parity ratio of mean non-negative relative cost benefit between asset-poor and asset-rich member groups across the district.'),
        ('equity_audit_population_members_count', 'count', 'Total members in the audited district equity population.'),
        ('equity_audit_eligible_members_count', 'count', 'Members with finite costs and positive reference cost eligible for audited relative-benefit equity metrics across the district.'),
        ('equity_audit_excluded_nonpositive_reference_count', 'count', 'Members excluded from audited relative-benefit equity metrics due to zero or negative reference cost across the district.'),
        ('equity_audit_excluded_unknown_cost_count', 'count', 'Members excluded from audited equity metrics due to missing or non-finite cost totals across the district.'),
        ('equity_audit_coverage_ratio', 'ratio', 'Share of district members eligible for audited relative-benefit equity metrics.'),
        ('equity_audit_losers_percent', 'percent', 'Audited percentage of eligible members with negative relative cost benefit across the district.'),
        ('equity_audit_positive_benefit_gini_ratio', 'ratio', 'Audited Gini inequality coefficient of positive member relative cost benefits across the district.'),
        ('equity_audit_positive_benefit_top20_ratio', 'ratio', 'Audited share of total positive relative cost benefit captured by the top 20% of eligible members across the district.'),
    )
    for suffix, unit, desc in equity_district_rows:
        register(f'district_{suffix}', unit, desc, level='district', family='equity')

    # 9. Comfort, resilience and thermal service audit families
    comfort_rows = (
        ('discomfort_overall_ratio', 'ratio', 'Proportion of occupied intervals with indoor temperature outside the comfort band {in_scope}.'),
        ('discomfort_cold_ratio', 'ratio', 'Proportion of occupied intervals with indoor temperature below the heating comfort threshold {in_scope}.'),
        ('discomfort_hot_ratio', 'ratio', 'Proportion of occupied intervals with indoor temperature above the cooling comfort threshold {in_scope}.'),
        ('discomfort_cold_delta_min_c', 'C', 'Minimum cold temperature exceedance below the comfort band during uncomfortable intervals {in_scope}.'),
        ('discomfort_cold_delta_max_c', 'C', 'Maximum cold temperature exceedance below the comfort band during uncomfortable intervals {in_scope}.'),
        ('discomfort_cold_delta_average_c', 'C', 'Mean cold temperature exceedance below the comfort band during uncomfortable intervals {in_scope}.'),
        ('discomfort_hot_delta_min_c', 'C', 'Minimum hot temperature exceedance above the comfort band during uncomfortable intervals {in_scope}.'),
        ('discomfort_hot_delta_max_c', 'C', 'Maximum hot temperature exceedance above the comfort band during uncomfortable intervals {in_scope}.'),
        ('discomfort_hot_delta_average_c', 'C', 'Mean hot temperature exceedance above the comfort band during uncomfortable intervals {in_scope}.'),
        ('resilience_one_minus_thermal_ratio', 'ratio', 'Proportion of occupied power-outage intervals experiencing thermal discomfort (1 minus thermal resilience) {in_scope}.'),
        ('resilience_unserved_energy_outage_normalized_ratio', 'ratio', 'Unserved thermal and base electrical demand normalized by expected demand during power-outage intervals {in_scope}.'),
        ('resilience_unserved_energy_annual_normalized_ratio', 'ratio', 'Unserved thermal and base electrical demand normalized by total expected demand over the evaluated window {in_scope}.'),
    )
    for suffix, unit, template in comfort_rows:
        register_levels(bd, f'comfort_resilience_{suffix}', unit, 'comfort_resilience', template)

    thermal_audit_rows = (
        ('executed_intervals_count', 'count', 'Executed active intervals included in the thermal and service-energy audit {in_scope}.'),
        ('known_occupancy_intervals_count', 'count', 'Executed intervals with finite non-negative occupancy telemetry {in_scope}.'),
        ('occupied_intervals_count', 'count', 'Executed intervals with positive occupant count {in_scope}.'),
        ('evaluated_occupied_intervals_count', 'count', 'Occupied intervals with valid indoor temperature, setpoints and comfort band {in_scope}.'),
        ('excluded_occupied_intervals_count', 'count', 'Occupied intervals excluded from thermal evaluation due to missing or invalid temperature/setpoint telemetry {in_scope}.'),
        ('discomfort_intervals_count', 'count', 'Evaluated occupied intervals with cold or hot comfort-band exceedance {in_scope}.'),
        ('cold_intervals_count', 'count', 'Evaluated occupied intervals with indoor temperature below heating setpoint minus comfort band {in_scope}.'),
        ('hot_intervals_count', 'count', 'Evaluated occupied intervals with indoor temperature above cooling setpoint plus comfort band {in_scope}.'),
        ('occupied_hours', 'hours', 'Total occupied duration in hours across executed intervals {in_scope}.'),
        ('evaluated_occupied_hours', 'hours', 'Total occupied duration in hours with valid thermal comfort telemetry {in_scope}.'),
        ('discomfort_hours', 'hours', 'Total occupied duration in hours spent outside the thermal comfort band {in_scope}.'),
        ('cold_degree_hours', 'C*h', 'Integrated cold discomfort below the heating setpoint in degree-Celsius hours {in_scope}.'),
        ('hot_degree_hours', 'C*h', 'Integrated hot discomfort above the cooling setpoint in degree-Celsius hours {in_scope}.'),
        ('outage_intervals_count', 'count', 'Executed intervals with an active grid power outage {in_scope}.'),
        ('unknown_outage_intervals_count', 'count', 'Executed intervals with missing or invalid power-outage signal telemetry {in_scope}.'),
        ('outage_occupied_intervals_count', 'count', 'Occupied intervals coinciding with an active grid power outage {in_scope}.'),
        ('evaluated_outage_occupied_intervals_count', 'count', 'Occupied power-outage intervals with valid thermal comfort telemetry {in_scope}.'),
        ('outage_discomfort_intervals_count', 'count', 'Evaluated occupied power-outage intervals outside the thermal comfort band {in_scope}.'),
        ('energy_evaluated_intervals_count', 'count', 'Executed intervals with valid expected and served service-energy components {in_scope}.'),
        ('expected_service_energy_kwh', 'kWh', 'Total expected thermal and base electrical service energy over audited intervals {in_scope}.'),
        ('served_service_energy_kwh', 'kWh', 'Total served thermal and base electrical service energy over audited intervals {in_scope}.'),
        ('unserved_service_energy_kwh', 'kWh', 'Total unserved thermal and base electrical service energy shortfall over audited intervals {in_scope}.'),
        ('outage_expected_service_energy_kwh', 'kWh', 'Expected thermal and base electrical service energy during power-outage intervals {in_scope}.'),
        ('outage_unserved_service_energy_kwh', 'kWh', 'Unserved thermal and base electrical service energy shortfall during power-outage intervals {in_scope}.'),
        ('discomfort_ratio', 'ratio', 'Audited share of evaluated occupied intervals spent in thermal discomfort {in_scope}.'),
        ('thermal_coverage_ratio', 'ratio', 'Share of occupied intervals with valid thermal telemetry {in_scope}.'),
        ('occupancy_coverage_ratio', 'ratio', 'Share of executed intervals with known occupancy telemetry {in_scope}.'),
        ('outage_discomfort_ratio', 'ratio', 'Audited share of evaluated occupied power-outage intervals spent in thermal discomfort {in_scope}.'),
        ('outage_thermal_coverage_ratio', 'ratio', 'Share of occupied power-outage intervals with valid thermal telemetry {in_scope}.'),
        ('energy_coverage_ratio', 'ratio', 'Share of executed intervals with valid service-energy accounting {in_scope}.'),
        ('unserved_service_ratio', 'ratio', 'Audited ratio of unserved to expected thermal and base electrical service energy {in_scope}.'),
        ('outage_unserved_service_ratio', 'ratio', 'Audited ratio of unserved to expected service energy during power-outage intervals {in_scope}.'),
    )
    for suffix, unit, template in thermal_audit_rows:
        register_levels(bd, f'thermal_service_audit_{suffix}', unit, 'thermal_service_audit', template)

    # 10. Deferrable appliance service and audit family
    deferrable_rows = (
        ('service_completed_cycles_count', 'count', 'Deferrable appliance cycles completed within their deadline under the evaluated controller {in_scope}.'),
        ('service_completed_cycles_business_as_usual_count', 'count', 'Deferrable appliance cycles completed in the native business-as-usual rollout {in_scope}.'),
        ('service_completed_cycles_delta_to_business_as_usual_count', 'count', 'Control minus native business-as-usual completed deferrable appliance cycles {in_scope}.'),
        ('service_missed_cycles_count', 'count', 'Deferrable appliance cycles that missed their start window or energy target under the evaluated controller {in_scope}.'),
        ('service_missed_cycles_business_as_usual_count', 'count', 'Deferrable appliance cycles missed in the native business-as-usual rollout {in_scope}.'),
        ('service_missed_cycles_delta_to_business_as_usual_count', 'count', 'Control minus native business-as-usual missed deferrable appliance cycles {in_scope}.'),
        ('service_service_level_ratio', 'ratio', 'Deferrable appliance cycle completion ratio (completed / (completed + missed)) {in_scope}.'),
        ('service_service_level_business_as_usual_ratio', 'ratio', 'Deferrable appliance cycle completion ratio of the native business-as-usual rollout {in_scope}.'),
        ('service_service_level_delta_to_business_as_usual_ratio', 'ratio', 'Control minus native business-as-usual deferrable appliance cycle completion ratio {in_scope}.'),
        ('service_served_energy_total_kwh', 'kWh', 'Total electricity delivered to completed deferrable appliance cycles under the evaluated controller {in_scope}.'),
        ('service_served_energy_total_business_as_usual_kwh', 'kWh', 'Total electricity delivered to completed deferrable appliance cycles in the native business-as-usual rollout {in_scope}.'),
        ('service_served_energy_total_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual served deferrable appliance energy {in_scope}.'),
        ('service_unserved_energy_total_kwh', 'kWh', 'Total unserved energy of missed deferrable appliance cycles under the evaluated controller {in_scope}.'),
        ('service_unserved_energy_total_business_as_usual_kwh', 'kWh', 'Total unserved energy of missed deferrable appliance cycles in the native business-as-usual rollout {in_scope}.'),
        ('service_unserved_energy_total_delta_to_business_as_usual_kwh', 'kWh', 'Control minus native business-as-usual unserved deferrable appliance energy {in_scope}.'),
        ('service_average_start_delay_hours', 'hours', 'Mean start delay from earliest admissible start across completed deferrable appliance cycles {in_scope}.'),
        ('service_average_start_delay_business_as_usual_hours', 'hours', 'Mean deferrable appliance start delay of the native business-as-usual rollout {in_scope}.'),
        ('service_average_start_delay_delta_to_business_as_usual_hours', 'hours', 'Control minus native business-as-usual mean deferrable appliance start delay {in_scope}.'),
        ('ratio_to_business_as_usual_completed_cycles_ratio', 'ratio', 'Ratio of control completed deferrable appliance cycles to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_missed_cycles_ratio', 'ratio', 'Ratio of control missed deferrable appliance cycles to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_service_level_ratio', 'ratio', 'Ratio of control deferrable appliance completion service level to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_served_energy_total_ratio', 'ratio', 'Ratio of control served deferrable appliance energy to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_unserved_energy_total_ratio', 'ratio', 'Ratio of control unserved deferrable appliance energy to the native business-as-usual rollout {in_scope}.'),
        ('ratio_to_business_as_usual_average_start_delay_ratio', 'ratio', 'Ratio of control mean deferrable appliance start delay to the native business-as-usual rollout {in_scope}.'),
        ('audit_catalogue_count', 'count', 'Total scheduled deferrable appliance requests in the dataset catalogue {in_scope}.'),
        ('audit_offered_count', 'count', 'Deferrable appliance requests with an admissible full-cycle start within executed active intervals {in_scope}.'),
        ('audit_excluded_count', 'count', 'Scheduled deferrable appliance requests excluded as outside the active episode service horizon {in_scope}.'),
        ('audit_resolved_count', 'count', 'Offered deferrable appliance requests resolved as completed, missed or cancelled by evaluation time {in_scope}.'),
        ('audit_duplicate_offered_count', 'count', 'Duplicate offered deferrable appliance request records across reinstalled asset instances {in_scope}.'),
        ('audit_pending_count', 'count', 'Offered deferrable appliance requests still unstarted with an open start window at evaluation time {in_scope}.'),
        ('audit_running_count', 'count', 'Offered deferrable appliance requests currently mid-cycle at evaluation time {in_scope}.'),
        ('audit_completed_count', 'count', 'Audited offered deferrable appliance requests that delivered their full load profile {in_scope}.'),
        ('audit_missed_count', 'count', 'Audited offered deferrable appliance requests that missed their start window or profile energy {in_scope}.'),
        ('audit_cancelled_count', 'count', 'Audited offered deferrable appliance requests cancelled due to asset or member removal {in_scope}.'),
        ('audit_excluded_expired_before_episode_count', 'count', 'Scheduled deferrable requests excluded because latest start elapsed before episode start {in_scope}.'),
        ('audit_excluded_expired_before_activation_count', 'count', 'Scheduled deferrable requests excluded because latest start elapsed before dynamic activation {in_scope}.'),
        ('audit_excluded_not_yet_available_count', 'count', 'Scheduled deferrable requests excluded because their admissible start window had not yet opened {in_scope}.'),
        ('audit_excluded_removed_before_available_count', 'count', 'Scheduled deferrable requests excluded because the asset or member exited before the window opened {in_scope}.'),
        ('audit_excluded_outside_episode_service_horizon_count', 'count', 'Scheduled deferrable requests excluded because a full cycle could not fit before episode or deadline end {in_scope}.'),
        ('audit_excluded_already_accounted_previous_instance_count', 'count', 'Scheduled deferrable requests excluded because an earlier dynamic instance already accounted for the cycle {in_scope}.'),
        ('audit_reason_profile_delivered_count', 'count', 'Offered deferrable requests resolved with full profile energy delivered {in_scope}.'),
        ('audit_reason_profile_energy_shortfall_count', 'count', 'Offered deferrable requests marked missed due to delivered energy shortfall after cycle completion {in_scope}.'),
        ('audit_reason_start_window_elapsed_count', 'count', 'Offered deferrable requests marked missed because the latest start timestep elapsed without starting {in_scope}.'),
        ('audit_reason_asset_removed_count', 'count', 'Offered deferrable requests cancelled because the appliance asset was dynamically removed {in_scope}.'),
        ('audit_reason_member_removed_count', 'count', 'Offered deferrable requests cancelled because the building member departed the community {in_scope}.'),
        ('audit_reason_window_open_count', 'count', 'Offered deferrable requests still pending with an open start window {in_scope}.'),
        ('audit_reason_profile_in_progress_count', 'count', 'Offered deferrable requests still executing their load profile at evaluation time {in_scope}.'),
        ('audit_requested_energy_kwh', 'kWh', 'Total requested energy across offered deferrable appliance cycles {in_scope}.'),
        ('audit_served_energy_kwh', 'kWh', 'Total physically served energy attributed to offered deferrable appliance cycles {in_scope}.'),
        ('audit_final_unserved_energy_kwh', 'kWh', 'Final unserved energy across missed and cancelled offered deferrable appliance cycles {in_scope}.'),
        ('audit_outstanding_energy_kwh', 'kWh', 'Remaining energy of pending and in-progress offered deferrable appliance cycles {in_scope}.'),
        ('audit_excluded_requested_energy_kwh', 'kWh', 'Total requested energy of excluded out-of-horizon deferrable appliance cycles {in_scope}.'),
        ('audit_physical_energy_kwh', 'kWh', 'Total physical electricity consumed by deferrable appliances during executed intervals {in_scope}.'),
        ('audit_physical_balance_residual_kwh', 'kWh', 'Residual between physical appliance electricity consumption and cycle-attributed served energy {in_scope}.'),
        ('audit_service_balance_residual_kwh', 'kWh', 'Accounting residual of requested minus served, final-unserved and outstanding deferrable energy {in_scope}.'),
        ('audit_observed_completion_ratio', 'ratio', 'Completed offered deferrable requests divided by all offered requests {in_scope}.'),
        ('audit_resolved_completion_ratio', 'ratio', 'Completed offered deferrable requests divided by resolved (completed, missed or cancelled) requests {in_scope}.'),
        ('audit_resolved_coverage_ratio', 'ratio', 'Share of offered deferrable requests resolved by evaluation time {in_scope}.'),
    )
    for suffix, unit, template in deferrable_rows:
        register_levels(bd, f'deferrable_appliance_{suffix}', unit, 'deferrable_appliance', template)

    # 11. Escalator family
    escalator_rows = (
        ('service_requested_passengers_total_count', 'count', 'Total passenger demand arriving at escalators {in_scope}.'),
        ('service_served_passengers_total_count', 'count', 'Total escalator passengers served {in_scope}.'),
        ('service_unserved_passengers_total_count', 'count', 'Total escalator passengers unserved {in_scope}.'),
        ('service_service_level_ratio', 'ratio', 'Fraction of requested escalator passenger demand served {in_scope}.'),
        ('energy_electricity_consumption_total_kwh', 'kWh', 'Total electricity consumed by escalators {in_scope}.'),
        ('operation_state_changes_count', 'count', 'Total escalator operating-mode transitions {in_scope}.'),
    )
    for suffix, unit, template in escalator_rows:
        register_levels(bd, f'escalator_{suffix}', unit, 'escalator', template)

    # 12. Demand response and audit family
    dr_rows = (
        ('events_count', 'count', 'Unique demand-response events with active settlement intervals {in_scope}.'),
        ('active_time_step_count', 'count', 'Active demand-response settlement timesteps {in_scope}.'),
        ('requested_total_kwh', 'kWh', 'Total requested demand-response flexibility energy over active timesteps {in_scope}.'),
        ('delivered_total_kwh', 'kWh', 'Signed demand-response energy delivered in the requested direction {in_scope}.'),
        ('shortfall_total_kwh', 'kWh', 'Non-delivered requested demand-response energy beyond tolerance {in_scope}.'),
        ('compliance_ratio', 'ratio', 'Credited demand-response delivery divided by valid requested energy {in_scope}.'),
        ('revenue_total_eur', 'EUR', 'Gross settlement revenue earned from credited demand-response delivery {in_scope}.'),
        ('penalty_total_eur', 'EUR', 'Total financial penalty incurred from demand-response shortfall {in_scope}.'),
        ('net_revenue_total_eur', 'EUR', 'Net demand-response settlement revenue (revenue minus penalty) {in_scope}.'),
        ('invalid_baseline_time_step_count', 'count', 'Active demand-response timesteps excluded from financial settlement due to an invalid pre-event baseline {in_scope}.'),
    )
    for suffix, unit, template in dr_rows:
        register_levels(bd, f'demand_response_{suffix}', unit, 'demand_response', template)
    register(
        'building_demand_response_uncapped_contribution_total_kwh',
        'kWh',
        'Diagnostic uncapped positive demand-response energy contribution of the building before district tolerance and cap.',
        level='building',
        family='demand_response',
    )

    dr_purposes = (
        ('all', 'all demand-response requests'),
        ('service', 'service-purpose demand-response requests'),
        ('stress', 'stress-test demand-response requests'),
        ('unspecified', 'unspecified-purpose demand-response requests'),
    )
    dr_audit_metrics = (
        ('events_count', 'count', 'Unique events across {purpose} in the district.'),
        ('active_intervals_count', 'count', 'Active settlement intervals across {purpose} in the district.'),
        ('valid_intervals_count', 'count', 'Active intervals with a valid pre-event baseline across {purpose} in the district.'),
        ('requested_kwh', 'kWh', 'Total requested flexibility energy across {purpose} in the district.'),
        ('valid_requested_kwh', 'kWh', 'Requested flexibility energy over valid-baseline intervals across {purpose} in the district.'),
        ('delivered_kwh', 'kWh', 'Signed flexibility energy delivered across {purpose} in the district.'),
        ('credited_kwh', 'kWh', 'Credited flexibility energy (non-negative and capped at target) across {purpose} in the district.'),
        ('shortfall_kwh', 'kWh', 'Shortfall energy after tolerance across {purpose} in the district.'),
        ('revenue_eur', 'EUR', 'Settlement revenue from credited delivery across {purpose} in the district.'),
        ('penalty_eur', 'EUR', 'Shortfall penalty across {purpose} in the district.'),
        ('net_revenue_eur', 'EUR', 'Net settlement revenue (revenue minus penalty) across {purpose} in the district.'),
        ('baseline_coverage_ratio', 'ratio', 'Share of active intervals with a valid pre-event baseline across {purpose} in the district.'),
        ('requested_energy_coverage_ratio', 'ratio', 'Share of requested energy covered by valid-baseline intervals across {purpose} in the district.'),
        ('compliance_ratio', 'ratio', 'Credited delivery divided by valid requested energy across {purpose} in the district.'),
        ('excluded_insufficient_history_intervals_count', 'count', 'Active intervals excluded due to insufficient pre-event history across {purpose} in the district.'),
        ('excluded_nonfinite_history_intervals_count', 'count', 'Active intervals excluded due to non-finite pre-event history across {purpose} in the district.'),
        ('excluded_no_members_intervals_count', 'count', 'Active intervals excluded because no active community members were present across {purpose} in the district.'),
        ('excluded_topology_changed_intervals_count', 'count', 'Active intervals excluded because active member topology changed in the baseline window across {purpose} in the district.'),
    )
    for p_key, p_label in dr_purposes:
        for m_key, unit, template in dr_audit_metrics:
            register(
                f'district_demand_response_audit_{p_key}_{m_key}',
                unit,
                template.format(purpose=p_label),
                level='district',
                family='demand_response',
            )

    # 13. Robustness family
    robustness_rows = (
        ('events_count', 'count', 'Unique robustness perturbation events affecting the {scope}.'),
        ('active_time_step_count', 'count', 'Executed timesteps with at least one applied robustness perturbation {in_scope}.'),
        ('observation_corruption_count', 'count', 'Agent-facing observation corruptions applied by robustness events {in_scope}.'),
        ('forecast_corruption_count', 'count', 'Agent-facing forecast corruptions applied by robustness events {in_scope}.'),
        ('action_corruption_count', 'count', 'Controller action-channel corruptions applied before physical execution {in_scope}.'),
        ('asset_unavailable_time_step_count', 'count', 'Asset unavailability applications from robustness events {in_scope}.'),
        ('missing_observation_count', 'count', 'Observation or telemetry values replaced by the missing-data sentinel {in_scope}.'),
        ('action_dropout_count', 'count', 'Controller actions forced to zero by action dropout or asset-control outage {in_scope}.'),
    )
    for suffix, unit, template in robustness_rows:
        register_levels(bd, f'robustness_{suffix}', unit, 'robustness', template)

    # 14. Energy provenance ledger family (including BAU and delta variants)
    def register_provenance(levels: Tuple[str, ...], stem: str, unit: str, base_desc: str) -> None:
        for level in levels:
            scope_text = _SCOPE_PHRASE[level]
            full_base = base_desc.format(in_scope=scope_text, scope=_SCOPE_NOUN[level])
            stem_no_dot = full_base[:-1] if full_base.endswith('.') else full_base
            register(
                f'{level}_energy_provenance_{stem}_{unit.lower()}',
                unit,
                f'{stem_no_dot}.',
                level=level,
                family='energy_provenance',
            )
            register(
                f'{level}_energy_provenance_{stem}_business_as_usual_{unit.lower()}',
                unit,
                f'{stem_no_dot} in the native business-as-usual reference rollout.',
                level=level,
                family='energy_provenance',
            )
            register(
                f'{level}_energy_provenance_{stem}_delta_to_business_as_usual_{unit.lower()}',
                unit,
                f'Control minus native business-as-usual {stem_no_dot[0].lower() + stem_no_dot[1:]}.',
                level=level,
                family='energy_provenance',
            )

    provenance_common = (
        ('pv_generated', 'kWh', 'Total solar PV electricity generated since episode reset {in_scope}'),
        ('pv_load_direct', 'kWh', 'Solar PV electricity serving building load directly in the same interval without storage {in_scope}'),
        ('pv_load_after_storage', 'kWh', 'Solar PV electricity serving building load after storage discharge {in_scope}'),
        ('unknown_input', 'kWh', 'Initial or externally reset storage energy of unknown origin entering the provenance ledger {in_scope}'),
        ('external_purchase_unknown_carbon', 'kWh', 'External grid electricity imported at timesteps with unknown carbon intensity {in_scope}'),
        ('external_import', 'kWh', 'External grid electricity imported after local community sharing {in_scope}'),
        ('external_purchase_emissions', 'kgCO2', 'Carbon emissions from external grid electricity purchases after local community sharing {in_scope}'),
    )
    for stem, unit, template in provenance_common:
        register_provenance(bd, stem, unit, template)

    for direction, dir_label in (
        ('local_import', 'received via intra-community local import'),
        ('local_export', 'sent via intra-community local export'),
    ):
        register_provenance(bd, direction, 'kWh', f'Total electricity {dir_label} {{in_scope}}')
        register_provenance(bd, f'pv_{direction}', 'kWh', f'Solar PV-attributed electricity {dir_label} {{in_scope}}')
        register_provenance(bd, f'grid_{direction}', 'kWh', f'External grid-attributed electricity {dir_label} {{in_scope}}')

    destinations = (
        ('load', 'delivered to final building electrical load'),
        ('mobility', 'departing in connected EV batteries as mobility energy delivery'),
        ('grid_export', 'exported to the external utility grid'),
        ('loss', 'dissipated in storage charging, discharging and standby losses'),
        ('asset_exit', 'leaving the boundary in removed stationary or non-mobility storage assets'),
        ('external_reset', 'displaced from storage stocks by an imposed external SOC reset'),
        ('curtailment', 'curtailed from available solar PV generation'),
        ('stored', 'remaining in active stationary and connected EV storage at evaluation time'),
    )
    for dest, dest_label in destinations:
        register_provenance(bd, f'pv_{dest}', 'kWh', f'Solar PV-origin electricity {dest_label} {{in_scope}}')
        register_provenance(bd, f'grid_{dest}', 'kWh', f'External grid-origin electricity {dest_label} {{in_scope}}')
        register_provenance(bd, f'unknown_{dest}', 'kWh', f'Unknown-initial-origin electricity {dest_label} {{in_scope}}')
        register_provenance(bd, f'carbon_{dest}', 'kgCO2', f'Attributed grid carbon emissions of energy {dest_label} {{in_scope}}')
        register_provenance(bd, f'carbon_unknown_{dest}', 'kWh', f'Electricity with unknown carbon factor {dest_label} {{in_scope}}')

    provenance_district_only = (
        ('unknown_balance_residual', 'kWh', 'District provenance conservation residual for unknown-origin energy {in_scope}'),
        ('grid_balance_residual', 'kWh', 'District provenance conservation residual for external grid-origin energy {in_scope}'),
        ('pv_balance_residual', 'kWh', 'District provenance conservation residual for solar PV-origin energy {in_scope}'),
        ('carbon_balance_residual', 'kgCO2', 'District provenance conservation residual for attributed grid carbon emissions {in_scope}'),
        ('pv_useful_building', 'ratio', 'Fraction of district solar PV generation delivered to final building loads'),
        ('pv_useful_with_mobility', 'ratio', 'Fraction of district solar PV generation delivered to final building loads or departing EV mobility'),
        ('storage_max_residual', 'kWh', 'Maximum single-interval storage energy provenance conservation residual {in_scope}'),
        ('bus_max_residual', 'kWh', 'Maximum single-interval member AC-bus power balance residual {in_scope}'),
    )
    for stem, unit, template in provenance_district_only:
        register_provenance(('district',), stem, unit, template)

    # 15. Dynamic topology lifecycle placeholder
    register(
        'topology_lifecycle_presence',
        'dimensionless',
        'Lifecycle placeholder row (NaN value) recording a dynamic-topology member with no active intervals in the evaluated window.',
        level='building',
        family='topology',
    )

    # 16. Multi-community portfolio counterparts for every district KPI
    for key, definition in list(registry.items()):
        if definition.level == 'district' and key.startswith('district_'):
            portfolio_key = 'portfolio_' + key[len('district_'):]
            register(
                portfolio_key,
                definition.unit,
                _portfolio_description_from_district(portfolio_key, definition.description),
                level='portfolio',
                family=definition.family,
            )

    return registry


KPI_REGISTRY: Mapping[str, KPIDefinition] = MappingProxyType(_build_static_registry())


@lru_cache(maxsize=None)
def get_kpi_definition(cost_function: str) -> KPIDefinition:
    """Resolve ``cost_function`` to its canonical :class:`KPIDefinition`.

    Raises
    ------
    KeyError
        If ``cost_function`` is neither statically registered nor matched by a
        parameterized KPI family pattern.
    """
    key = str(cost_function)
    direct = KPI_REGISTRY.get(key)
    if direct is not None:
        return direct

    phase_match = _PHASE_PEAK_PATTERN.fullmatch(key)
    if phase_match is not None:
        level, direction, phase = phase_match.groups()
        phase_label = phase.upper()
        scope_phrase = _SCOPE_PHRASE[level]
        return KPIDefinition(
            cost_function=key,
            unit='kW',
            description=f'Peak active {direction} power on phase {phase_label} {scope_phrase}.',
            level=level,
            family='electrical_service_phase',
        )

    if key.startswith('portfolio_'):
        district_key = 'district_' + key[len('portfolio_'):]
        district_def = get_kpi_definition(district_key)
        return KPIDefinition(
            cost_function=key,
            unit=district_def.unit,
            description=_portfolio_description_from_district(key, district_def.description),
            level='portfolio',
            family=district_def.family,
        )

    raise KeyError(f'Unregistered KPI cost_function: {cost_function!r}.')


def resolve_kpi_metadata(cost_function: str) -> Tuple[str, str]:
    """Return ``(unit, description)`` for ``cost_function`` from the KPI registry."""
    definition = get_kpi_definition(cost_function)
    return definition.unit, definition.description
