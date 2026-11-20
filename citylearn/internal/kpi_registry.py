"""Unit and one-line description of every KPI that ``evaluate_v2()`` returns.

This module is the single source for the ``unit`` and ``description`` columns of the
KPI table, of the exported KPI files and of the KPI catalogue in the experiment manifest.
KPI names are generated in several modules and follow
``level_family_subfamily_metric_variant_unit``. The registry maps the name without its
``level`` prefix (``building``, ``district`` or ``portfolio``) to a unit and a description:

* Each entry is a regular expression with optional named groups. Groups that name a
  reference (``v``, ``r``) or a part of the metric are expanded into the description.
* An explicit entry wins. The unit suffix of the name (``_kwh``, ``_eur`` ...) is only the
  fallback when an entry gives no unit, and the only source for a name without an entry.
  Such a name gets no description; ``tests/test_kpi_registry.py`` fails until it has an entry.

Units are the suffix tokens of the naming contract, listed in ``UNITS`` and in the Units
table of ``docs/kpis_reference.md``. A KPI named per day keeps the unit of its total.
"""

import re
from functools import lru_cache
from typing import Dict, List, Mapping, Optional, Tuple

import pandas as pd

#: Unit token to its meaning. Keep in sync with the Units table of ``docs/kpis_reference.md``.
UNITS: Dict[str, str] = {
    'eur': 'Monetary cost. If the dataset uses another currency, interpret as dataset currency.',
    'kwh': 'Accumulated energy.',
    'kgco2': 'Accumulated emissions.',
    'kw': 'Power.',
    'ratio': 'Dimensionless ratio.',
    'percent': 'Percentage.',
    'count': 'Event/cycle count.',
    'hours': 'Hours.',
    'degree_hours': 'Degree-hours: temperature deviation in Celsius times hours.',
    'c': 'Celsius.',
    'none': 'No unit: a placeholder row without a measured value.',
}

LEVELS = ('building', 'district', 'portfolio')

# A reference variant sits before the unit. No token means the control run.
_VARIANTS = {
    'control': 'control run',
    'baseline': 'baseline run',
    'business_as_usual': 'business-as-usual run',
    'delta': 'control minus baseline',
    'delta_to_business_as_usual': 'control minus business-as-usual',
}
_V = r'(?:_(?P<v>control|baseline|business_as_usual|delta_to_business_as_usual|delta))?'
_VR = r'_(?P<v>business_as_usual|delta_to_business_as_usual)'
_R = r'(?P<r>baseline|business_as_usual)'

_PARTS: Dict[str, Mapping[str, str]] = {
    'v': _VARIANTS,
    'r': {'baseline': 'control over baseline', 'business_as_usual': 'control over business-as-usual'},
    'w': {'daily': 'daily windows', 'monthly': 'monthly windows', 'all_time': 'the whole episode'},
    's': {'_signed_net': ', 3.6.0 definition on signed net power'},
    'stat': {'average': 'Average', 'max': 'Maximum', 'min': 'Minimum'},
    'side': {'cold': 'heating setpoint minus indoor temperature in cold-discomfort time steps',
             'hot': 'indoor temperature minus cooling setpoint in hot-discomfort time steps'},
    'o': {'pv_': 'PV ', 'grid_': 'grid-origin ', '': ''},
    'u': {'building': 'the building', 'with_mobility': 'the building and EV charging'},
    'phase': {'l1': 'L1', 'l2': 'L2', 'l3': 'L3'},
    'ev': {
        '': '', '_met': ' meeting the target SOC', '_min_acceptable': ' meeting the minimum acceptable SOC',
        '_within_tolerance': ' within the symmetric target tolerance',
        '_target_feasible': ' where the target SOC was reachable',
        '_target_infeasible': ' where the target SOC was not reachable',
        '_min_acceptable_feasible': ' where the minimum acceptable SOC was reachable',
        '_min_acceptable_infeasible': ' where the minimum acceptable SOC was not reachable',
        '_within_tolerance_feasible': ' where the lower tolerance bound was reachable',
        '_within_tolerance_infeasible': ' where the lower tolerance bound was not reachable',
    },
    'k': {'success': 'the target SOC', 'min_acceptable': 'the minimum acceptable SOC',
          'within_tolerance': 'the symmetric target tolerance'},
    't': {'target': 'the target SOC', 'min_acceptable': 'the minimum acceptable SOC',
          'within_tolerance': 'the symmetric target tolerance'},
    'e': {'soc_deficit': 'non-negative SOC deficit', 'shortfall_beyond_tolerance': 'SOC deficit below the minimum acceptable target',
          'soc_surplus': 'non-negative SOC surplus', 'soc_absolute_error': 'absolute SOC error to the requested target'},
    'per': {'total': 'over the episode', 'daily_average': 'per simulated day'},
    'dest': {
        'load': 'building load', 'mobility': 'EV charging', 'grid_export': 'grid export',
        'loss': 'conversion and storage losses', 'asset_exit': 'assets that left the community',
        'external_reset': 'external state resets', 'curtailment': 'curtailment',
        'stored': 'storage at the end of the episode',
    },
    'origin': {
        'pv': 'PV-generated energy', 'grid': 'Grid-imported energy with known carbon intensity',
        'unknown': 'Energy of unknown origin',
    },
    'purpose': {
        'all': 'all requests', 'service': 'service requests', 'stress': 'stress requests',
        'unspecified': 'requests without a declared purpose',
    },
}

# (pattern without level prefix, unit or None for the suffix fallback, description template).
_ENTRIES: List[Tuple[str, Optional[str], str]] = [
    # Cost
    (rf'cost_total{_V}_eur', None, 'Total electricity cost ({v}).'),
    (rf'cost_daily_average{_V}_eur', None, 'Electricity cost per simulated day ({v}).'),
    (rf'cost_ratio_to_{_R}_total_ratio', None, 'Total electricity cost, {r}.'),
    (r'cost_community_market_(?P<m>settled|counterfactual|savings)_(?P<per>total|daily_average)_eur', None,
     'Community-market cost {per}, {m}.'),
    (r'cost_community_market_operator_balance_total_eur', None,
     'Net amount the community-market operator pays and receives for local trades over the episode.'),
    # Grid exchange
    (r'energy_grid_(?P<per>total|daily_average)_(?P<m>import|export|net_exchange)' + _V + r'_kwh', None,
     'Grid {m} energy {per} ({v}).'),
    (rf'energy_grid_ratio_to_{_R}_(?P<m>import|export|net_exchange)_total_ratio', None,
     'Total grid {m} energy, {r}.'),
    (r'energy_grid_ratio_to_baseline_(?P<m>import|net_exchange)_total_building_mean_ratio', None,
     'Total grid {m} energy, mean of the building ratios of control over baseline (3.6.0 definition).'),
    (r'energy_grid_community_market_(?P<m>local_import|local_export|grid_import_after_local|grid_export_after_local)'
     r'_(?P<per>total|daily_average)_kwh', None, 'Community-market energy {per}, {m}.'),
    (r'energy_grid_community_market_local_traded_(?P<per>total|daily_average)_kwh', None,
     'Energy traded locally between members {per}.'),
    (rf'energy_grid_shape_quality_ramping_average{_VR}_kw', None,
     'Mean upward change of net grid power per step transition ({v}).'),
    (rf'energy_grid_shape_quality_ramping_total{_VR}_kw', None,
     'Sum of upward changes of net grid power, 3.6.0 definition ({v}).'),
    (rf'energy_grid_shape_quality_ramping_average_to_{_R}_ratio', None,
     'Mean upward change of net grid power per step transition, {r}.'),
    (rf'energy_grid_shape_quality_peak_(?P<w>daily|all_time)_average{_VR}_kw', None,
     'Peak import power, mean over {w} ({v}).'),
    (rf'energy_grid_shape_quality_peak_(?P<w>daily|all_time)_average_to_{_R}_ratio', None,
     'Peak import power, mean over {w}, {r}.'),
    (rf'energy_grid_shape_quality_load_factor_penalty_(?P<w>daily|monthly)_average(?P<s>_signed_net)?{_VR}_ratio',
     None, 'Load factor penalty, mean over {w} of one minus mean over peak import power{s} ({v}).'),
    (rf'energy_grid_shape_quality_load_factor_penalty_(?P<w>daily|monthly)_average(?P<s>_signed_net)?_to_{_R}_ratio',
     None, 'Load factor penalty, mean over {w} of one minus mean over peak import power{s}, {r}.'),
    (r'energy_grid_shape_quality_load_factor_penalty_(?P<w>daily|monthly)_average_to_baseline(?P<s>_signed_net)'
     r'_ratio', None,
     'Load factor penalty, mean over {w} of one minus mean over peak import power{s}, control over baseline.'),
    # Emissions
    (rf'emissions_total{_V}_kgco2', None, 'Total emissions of the grid import ({v}).'),
    (rf'emissions_total{_V}_member_sum_kgco2', None,
     'Total emissions, sum of the members\' own import emissions, 3.6.0 definition ({v}).'),
    (rf'emissions_daily_average{_V}_kgco2', None, 'Emissions of the grid import per simulated day ({v}).'),
    (rf'emissions_ratio_to_{_R}_total_ratio', None, 'Total emissions, {r}.'),
    (r'emissions_ratio_to_baseline_total_building_mean_ratio', None,
     'Total emissions, mean of the building ratios of control over baseline (3.6.0 definition).'),
    # Solar self-consumption
    (r'solar_self_consumption_(?P<per>total|daily_average)_(?P<m>generation|export)' + _V + r'_kwh', None,
     'Solar {m} energy {per} ({v}).'),
    (r'solar_self_consumption_total_curtailment_kwh', None, 'Solar generation curtailed over the episode.'),
    (rf'solar_self_consumption_ratio_self_consumption{_V}_ratio', None,
     'Share of solar generation consumed on site, not exported or curtailed ({v}).'),
    (r'solar_self_consumption_ratio_to_business_as_usual_(?P<m>generation|export)_total_ratio', None,
     'Total solar {m} energy, control over business-as-usual.'),
    (r'solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio', None,
     'Share of solar generation consumed on site, control over business-as-usual.'),
    (r'solar_self_consumption_community_market_import_share_ratio', None,
     'Share of member demand served by local community-market trades.'),
    (r'solar_self_consumption_community_market_local_share_of_demand_ratio', None,
     'Local community-market imports over member demand.'),
    (r'solar_self_consumption_community_market_local_share_of_export_ratio', None,
     'Local community-market exports over member exports.'),
    # Electric vehicles
    (r'ev_events_departure(?P<ev>|_met|_min_acceptable|_within_tolerance|_target_feasible|_target_infeasible|'
     r'_min_acceptable_feasible|_min_acceptable_infeasible|_within_tolerance_feasible|'
     r'_within_tolerance_infeasible)_count', None, 'Number of EV departures{ev}.'),
    (r'ev_performance_departure_(?P<k>success|min_acceptable|within_tolerance)_ratio', None,
     'EV departures meeting {k} over all departures.'),
    (r'ev_performance_departure_(?P<k>success|min_acceptable|within_tolerance)_feasible_ratio', None,
     'EV departures meeting {k} over the departures where it was feasible.'),
    (r'ev_performance_departure_(?P<e>soc_deficit|shortfall_beyond_tolerance|soc_surplus|soc_absolute_error)'
     r'_mean_ratio', None, 'Mean {e} over EV departures.'),
    (r'ev_performance_departure_tolerance_ratio', None,
     'Configured EV departure service tolerance, used for the minimum acceptable departure SOC.'),
    (rf'ev_total_charge{_V}_kwh', None, 'Energy charged into EVs ({v}).'),
    (rf'ev_total_v2g_export{_V}_kwh', None, 'Energy exported by EVs ({v}).'),
    (r'ev_ratio_to_business_as_usual_(?P<m>charge|v2g_export)_total_ratio', None,
     'Total energy {m} EVs, control over business-as-usual.'),
    (r'ev_energy_accounting_connected_soc_gain_kwh', None,
     'Energy added to EV batteries while connected, from the SOC change.'),
    (r'ev_energy_accounting_shortfall_kwh', None, 'EV energy shortfall at departure against the target SOC.'),
    (r'ev_departure_audit_departures_count', None, 'Number of EV departures in executed intervals.'),
    (r'ev_departure_audit_service_(?P<m>observed|unknown)_count', None,
     'Number of EV departures whose service outcome is {m}.'),
    (r'ev_departure_audit_service_coverage_ratio', None,
     'EV departures with an observed service outcome over all departures.'),
    (r'ev_departure_audit_(?P<t>target|min_acceptable|within_tolerance)_(?P<m>feasible|infeasible|unknown|'
     r'service_met|feasible_service_observed|feasible_service_met)_count', None,
     'Number of EV departures for {t}: {m}.'),
    (r'ev_departure_audit_(?P<t>target|min_acceptable|within_tolerance)_unknown_(?P<m>[a-z_]+)_count', None,
     'Number of EV departures for {t} with unknown feasibility because of {m}.'),
    (r'ev_departure_audit_(?P<t>target|min_acceptable|within_tolerance)_coverage_ratio', None,
     'EV departures with a known feasibility for {t} over all departures.'),
    (r'ev_departure_audit_(?P<t>target|min_acceptable|within_tolerance)_service_observed_ratio', None,
     'EV departures meeting {t} over the departures with an observed outcome.'),
    (r'ev_departure_audit_(?P<t>target|min_acceptable|within_tolerance)_service_feasible_ratio', None,
     'EV departures meeting {t} over the feasible departures with an observed outcome.'),
    # Battery
    (rf'battery_total_(?P<m>charge|discharge|throughput){_V}_kwh', None,
     'Battery {m} energy ({v}); throughput is charge plus discharge.'),
    (rf'battery_health_equivalent_full_cycles{_V}_count', None,
     'Equivalent full battery cycles, throughput relative to capacity ({v}).'),
    (rf'battery_health_capacity_fade{_V}_ratio', None, 'Relative battery capacity degradation ({v}).'),
    (r'battery_ratio_to_business_as_usual_(?P<m>capacity_fade|charge|discharge|equivalent_full_cycles|throughput)_ratio',
     None, 'Battery {m}, control over business-as-usual.'),
    # Electrical service and phases
    (r'electrical_service_phase_violations_energy_total_kwh', None,
     'Energy above the electrical service or phase limits that remains after projection.'),
    (r'electrical_service_phase_violations_event_count', None,
     'Time steps with a violation of the electrical service or phase limits.'),
    (r'electrical_service_phase_requested_pressure_energy_total_kwh', None,
     'Energy above the limits in the unprojected controller request.'),
    (r'electrical_service_phase_requested_pressure_event_count', None,
     'Time steps where the unprojected controller request exceeds the limits.'),
    (r'electrical_service_phase_imbalance_phase_average_ratio', None, 'Average phase imbalance.'),
    (r'electrical_service_phase_phase_peaks_(?P<m>import|export)_peak_(?P<phase>l1|l2|l3)_kw', None,
     'Peak {m} power on phase {phase}.'),
    # Comfort and resilience
    (r'comfort_resilience_discomfort_(?P<m>cold|hot|overall)_ratio', None,
     'Share of occupied time steps with {m} discomfort.'),
    (r'comfort_resilience_discomfort_(?P<side>cold|hot)_delta_(?P<stat>average|max|min)_c', None,
     '{stat} of {side}.'),
    (r'comfort_resilience_resilience_one_minus_thermal_ratio', None,
     'Share of occupied power-outage time steps with discomfort.'),
    (r'comfort_resilience_resilience_unserved_energy_outage_normalized_ratio', None,
     'Unserved energy over expected energy during power outages.'),
    (r'comfort_resilience_resilience_unserved_energy_annual_normalized_ratio', None,
     'Unserved energy over expected energy over the whole episode.'),
    (r'thermal_service_audit_(?P<m>executed|known_occupancy|occupied|evaluated_occupied|excluded_occupied|'
     r'discomfort|cold|hot|outage|unknown_outage|outage_occupied|evaluated_outage_occupied|outage_discomfort|'
     r'energy_evaluated)_intervals_count', None, 'Thermal audit: number of {m} intervals.'),
    (r'thermal_service_audit_(?P<m>occupied|evaluated_occupied|discomfort)_hours', None,
     'Thermal audit: {m} hours.'),
    (r'thermal_service_audit_(?P<m>cold|hot)_degree_hours', 'degree_hours',
     'Thermal audit: temperature deviation beyond the comfort band in {m} intervals, times hours.'),
    (r'thermal_service_audit_(?P<m>expected|served|unserved|outage_expected|outage_unserved)_service_energy_kwh', None,
     'Thermal audit: {m} service energy.'),
    (r'thermal_service_audit_(?P<m>discomfort|thermal_coverage|occupancy_coverage|outage_discomfort|'
     r'outage_thermal_coverage|energy_coverage|unserved_service|outage_unserved_service)_ratio', None,
     'Thermal audit: {m} ratio of pooled counts, undefined when its denominator is zero.'),
    # Equity
    (r'equity_benefit_relative_percent', None,
     'Relative cost benefit of the control over the baseline, 100 times baseline minus control over baseline.'),
    (r'equity_distribution_gini_benefit_ratio', None, 'Gini coefficient of the positive member benefits.'),
    (r'equity_distribution_top20_benefit_ratio', None, 'Share of the positive benefits held by the top 20% of members.'),
    (r'equity_distribution_losers_percent', None, 'Share of members with a negative benefit.'),
    (r'equity_distribution_bpr_asset_poor_over_rich_ratio', None,
     'Mean benefit of asset-poor members over that of asset-rich members.'),
    (r'equity_audit_(?P<m>population_members|eligible_members|excluded_nonpositive_reference|excluded_unknown_cost)_count',
     None, 'Equity audit: number of {m} members.'),
    (r'equity_audit_coverage_ratio', None, 'Members with a defined benefit over all members.'),
    (r'equity_audit_losers_percent', None, 'Share of members with a negative benefit among the eligible members.'),
    (r'equity_audit_positive_benefit_gini_ratio', None, 'Gini coefficient of the positive member benefits.'),
    (r'equity_audit_positive_benefit_top20_ratio', None,
     'Share of the positive benefits held by the top 20% of members.'),
    # Deferrable appliances
    (r'deferrable_appliance_service_(?P<m>completed|missed)_cycles' + _V + r'_count', None,
     'Number of {m} deferrable cycles ({v}).'),
    (r'deferrable_appliance_service_service_level' + _V + r'_ratio', None,
     'Completed cycles over completed plus missed cycles ({v}).'),
    (r'deferrable_appliance_service_(?P<m>served|unserved)_energy_total' + _V + r'_kwh', None,
     'Energy of {m} deferrable cycles ({v}).'),
    (r'deferrable_appliance_service_average_start_delay' + _V + r'_hours', None,
     'Mean delay between the earliest start and the start of completed cycles ({v}).'),
    (r'deferrable_appliance_ratio_to_business_as_usual_(?P<m>completed_cycles|missed_cycles|service_level|'
     r'average_start_delay)_ratio', None, 'Deferrable {m}, control over business-as-usual.'),
    (r'deferrable_appliance_ratio_to_business_as_usual_(?P<m>served|unserved)_energy_total_ratio', None,
     'Energy of {m} deferrable cycles, control over business-as-usual.'),
    (r'deferrable_appliance_audit_(?P<m>catalogue|offered|excluded|resolved|duplicate_offered|pending|running|'
     r'completed|missed|cancelled)_count', None, 'Deferrable cycle audit: number of {m} cycles.'),
    (r'deferrable_appliance_audit_excluded_(?P<m>[a-z_]+)_count', None,
     'Deferrable cycle audit: number of cycles excluded because {m}.'),
    (r'deferrable_appliance_audit_reason_(?P<m>[a-z_]+)_count', None, 'Deferrable cycle audit: number of offered cycles with the outcome reason {m}.'),
    (r'deferrable_appliance_audit_(?P<m>excluded_requested|requested|served|final_unserved|outstanding|physical)'
     r'_energy_kwh', None, 'Deferrable cycle audit: {m} energy.'),
    (r'deferrable_appliance_audit_(?P<m>physical_balance|service_balance)_residual_kwh', None,
     'Deferrable cycle audit: {m} residual; zero when the balance closes.'),
    (r'deferrable_appliance_audit_(?P<m>observed_completion|resolved_completion|resolved_coverage)_ratio', None,
     'Deferrable cycle audit: {m} ratio.'),
    # Escalators
    (r'escalator_service_(?P<m>requested|served|unserved)_passengers_total_count', None,
     'Escalator passengers {m} over the episode.'),
    (r'escalator_service_service_level_ratio', None, 'Passenger demand served by escalators.'),
    (r'escalator_energy_electricity_consumption_total_kwh', None, 'Electricity used by escalators.'),
    (r'escalator_operation_state_changes_count', None, 'Escalator operating-state changes.'),
    # Demand response
    (r'demand_response_events_count', None, 'Unique DR events with active settlement rows.'),
    (r'demand_response_active_time_step_count', None, 'Number of active DR timesteps.'),
    (r'demand_response_requested_total_kwh', None, 'Requested energy from `target_power_kw` over active steps.'),
    (r'demand_response_delivered_total_kwh', None,
     'Signed delivery, positive when the controller moves in the requested direction.'),
    (r'demand_response_shortfall_total_kwh', None, 'Non-delivered requested energy after tolerance.'),
    (r'demand_response_compliance_ratio', None, 'Credited delivery divided by valid requested energy.'),
    (r'demand_response_revenue_total_eur', None, 'Credited delivery revenue.'),
    (r'demand_response_penalty_total_eur', None, 'Shortfall penalty.'),
    (r'demand_response_net_revenue_total_eur', None, 'Revenue minus penalty.'),
    (r'demand_response_invalid_baseline_time_step_count', None,
     'Active steps excluded from economics because the pre-event baseline was invalid.'),
    (r'demand_response_uncapped_contribution_total_kwh', None,
     "Diagnostic: the member's own positive contribution, without the district tolerance and cap. "
     'Does not add up to the district.'),
    (r'demand_response_audit_(?P<purpose>all|service|stress|unspecified)_(?P<m>events|active_intervals|valid_intervals|'
     r'excluded_insufficient_history_intervals|excluded_nonfinite_history_intervals|excluded_no_members_intervals|'
     r'excluded_topology_changed_intervals)_count', None, 'DR audit for {purpose}: number of {m}.'),
    (r'demand_response_audit_(?P<purpose>all|service|stress|unspecified)_(?P<m>requested|valid_requested|delivered|'
     r'credited|shortfall)_kwh', None, 'DR audit for {purpose}: {m} energy.'),
    (r'demand_response_audit_(?P<purpose>all|service|stress|unspecified)_(?P<m>revenue|penalty|net_revenue)_eur', None,
     'DR audit for {purpose}: {m}.'),
    (r'demand_response_audit_(?P<purpose>all|service|stress|unspecified)_(?P<m>baseline_coverage|'
     r'requested_energy_coverage|compliance)_ratio', None, 'DR audit for {purpose}: {m} ratio.'),
    # Robustness
    (r'robustness_events_count', None, 'Unique robustness events that affected the target level.'),
    (r'robustness_active_time_step_count', None,
     'Timesteps with at least one applied robustness perturbation.'),
    (r'robustness_observation_corruption_count', None, 'Agent-facing observation corruptions.'),
    (r'robustness_forecast_corruption_count', None, 'Agent-facing forecast corruptions.'),
    (r'robustness_action_corruption_count', None, 'Action-channel corruptions before physical application.'),
    (r'robustness_asset_unavailable_time_step_count', None, 'Asset unavailable applications.'),
    (r'robustness_missing_observation_count', None,
     'Observation or telemetry values replaced by the missing sentinel.'),
    (r'robustness_action_dropout_count', None, 'Actions forced to zero by dropout or asset-control outage.'),
    # Energy provenance
    (rf'energy_provenance_(?P<origin>pv|grid|unknown)_(?P<dest>load|mobility|grid_export|loss|asset_exit|'
     rf'external_reset|curtailment|stored){_V}_kwh', None, '{origin} that ended in {dest} ({v}).'),
    (rf'energy_provenance_carbon_(?P<dest>load|mobility|grid_export|loss|asset_exit|external_reset|curtailment|'
     rf'stored){_V}_kgco2', None, 'Emissions of the grid-imported energy that ended in {dest} ({v}).'),
    (rf'energy_provenance_carbon_unknown_(?P<dest>load|mobility|grid_export|loss|asset_exit|external_reset|'
     rf'curtailment|stored){_V}_kwh', None,
     'Energy without a known carbon intensity that ended in {dest} ({v}).'),
    (rf'energy_provenance_pv_generated{_V}_kwh', None, 'PV energy generated since reset ({v}).'),
    (rf'energy_provenance_pv_load_direct{_V}_kwh', None, 'PV energy that reached the load without storage ({v}).'),
    (rf'energy_provenance_pv_load_after_storage{_V}_kwh', None,
     'PV energy that reached the load through storage ({v}).'),
    (rf'energy_provenance_unknown_input{_V}_kwh', None, 'Energy of unknown origin that entered the system ({v}).'),
    (rf'energy_provenance_external_import{_V}_kwh', None, 'Energy imported from the external grid ({v}).'),
    (rf'energy_provenance_external_purchase_emissions{_V}_kgco2', None,
     'Emissions of the energy purchased from the external grid ({v}).'),
    (rf'energy_provenance_external_purchase_unknown_carbon{_V}_kwh', None,
     'Energy purchased from the external grid without a known carbon intensity ({v}).'),
    (rf'energy_provenance_(?P<o>pv_|grid_|)local_(?P<m>import|export){_V}_kwh', None,
     'Local {o}{m} energy between members ({v}).'),
    (rf'energy_provenance_(?P<m>unknown|grid|pv)_balance_residual{_V}_kwh', None,
     'Residual of the {m} energy balance; zero when the balance closes ({v}).'),
    (rf'energy_provenance_carbon_balance_residual{_V}_kgco2', None,
     'Residual of the carbon balance; zero when the balance closes ({v}).'),
    (rf'energy_provenance_pv_useful_(?P<u>building|with_mobility){_V}_ratio', None,
     'PV generation used by {u} over PV generation ({v}).'),
    (rf'energy_provenance_(?P<m>storage|bus)_max_residual{_V}_kwh', None,
     'Largest {m} energy residual over the episode ({v}).'),
    # Members that left a dynamic community before the evaluation
    (r'topology_lifecycle_presence', 'none', 'Placeholder row of a member that left the community; its value is undefined.'),
]

# Descriptions use a few readable replacements for the raw metric tokens.
_READABLE = {'v2g': 'V2G', 'soc': 'SOC', 'pv': 'PV', 'dr': 'DR', 'ev': 'EV', 'min_acceptable': 'minimum acceptable'}

_COMPILED: List[Tuple[re.Pattern, Optional[str], str]] = [
    (re.compile(pattern), unit, template) for pattern, unit, template in _ENTRIES
]
_LEVEL_PREFIX = re.compile(rf'^(?:{"|".join(LEVELS)})_')
_UNIT_SUFFIX = re.compile(r'_(' + '|'.join(sorted(UNITS, key=len, reverse=True)) + r')$')


def _readable(token: str) -> str:
    text = token.replace('_', ' ')

    for phrase, replacement in _READABLE.items():
        text = re.sub(rf'\b{phrase.replace("_", " ")}\b', replacement, text)

    return text


def unit_from_suffix(name: str) -> Optional[str]:
    """Fallback unit: the unit token that ends the KPI name, if any."""

    match = _UNIT_SUFFIX.search(name)
    return None if match is None else match.group(1)


@lru_cache(maxsize=None)
def describe(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(unit, description)`` of a KPI name.

    The description is ``None`` when the name has no registry entry. The unit then falls back to
    the name suffix, and is ``None`` when the suffix is no unit token.
    """

    stripped = _LEVEL_PREFIX.sub('', name, count=1)

    for pattern, unit, template in _COMPILED:
        match = pattern.fullmatch(stripped)

        if match is None:
            continue

        fields = {}

        for group, value in match.groupdict().items():
            if value is None:
                fields[group] = ''
            elif group == 'v':
                fields[group] = _VARIANTS[value]
            else:
                fields[group] = _PARTS.get(group, {}).get(value, _readable(value.strip('_')))

        if 'v' in match.groupdict() and match.group('v') is None:
            fields['v'] = _VARIANTS['control']

        return unit or unit_from_suffix(name), template.format(**fields)

    return unit_from_suffix(name), None


def unit_of(name: str) -> Optional[str]:
    """Unit token of a KPI name."""

    return describe(name)[0]


def description_of(name: str) -> Optional[str]:
    """One-line description of a KPI name, or ``None`` when it is not registered."""

    return describe(name)[1]


def add_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Insert ``unit`` and ``description`` after the ``level`` column of a KPI table.

    The existing columns and their values are not changed.
    """

    names = frame['cost_function'].unique()
    described = {name: describe(name) for name in names}
    position = list(frame.columns).index('level') + 1
    frame.insert(position, 'unit', frame['cost_function'].map({name: unit for name, (unit, _) in described.items()}))
    frame.insert(position + 1, 'description',
                 frame['cost_function'].map({name: text for name, (_, text) in described.items()}))
    return frame


def catalogue(names) -> Dict[str, Dict[str, Optional[str]]]:
    """Unit and description of each KPI name, for the experiment manifest."""

    return {name: dict(zip(('unit', 'description'), describe(name))) for name in sorted(set(names))}
