"""Total ratios whose reference is negligible are undefined (#403)."""

import pytest

from citylearn.internal.kpi import CityLearnKPIService

THROUGHPUT = 'battery_ratio_to_business_as_usual_throughput_ratio'
NET = 'energy_grid_ratio_to_baseline_net_exchange_total_ratio'
IMPORT = 'energy_grid_ratio_to_business_as_usual_import_total_ratio'


def _records(ratio, rows):
    """`rows` maps a building name or 'District' to (control, reference, ratio value)."""

    records = {}
    for name, (control, reference, value) in rows.items():
        level = 'district' if name == 'District' else 'building'
        metric = f'{level}_{ratio}'
        control_name, reference_name, _ = CityLearnKPIService.total_ratio_components(level)[metric]
        for key, v in ((control_name, control), (reference_name, reference), (metric, value)):
            records[(level, name, key)] = dict(level=level, name=name, cost_function=key, value=v)
    return records


def _apply(records):
    CityLearnKPIService._undefine_zero_over_zero_ratios(object.__new__(CityLearnKPIService), records)
    return {(level, name): r['value'] for (level, name, metric), r in records.items() if metric.endswith('_ratio')}


def test_a_reference_below_one_percent_of_the_member_scale_undefines_the_building_ratio():
    # Building_15 on plus_evs: its BAU barely cycles the battery, so the ratio was about 2,400.
    values = _apply(_records(THROUGHPUT, {
        'Building_1': (120.0, 100.0, 1.2),
        'Building_2': (90.0, 100.0, 0.9),
        'Building_15': (1208.5, 0.5, 2417.0),
        'District': (1418.5, 200.5, 1418.5 / 200.5),
    }))
    assert values['building', 'Building_15'] is None
    assert values['building', 'Building_1'] == 1.2
    assert values['building', 'Building_2'] == 0.9
    # District rows are unaffected: 200.5 kWh is far above 1% of the 66.8 kWh member scale.
    assert values['district', 'District'] == pytest.approx(1418.5 / 200.5)


def test_signed_totals_use_the_absolute_member_scale_and_a_cancelling_district_also_hits_the_rule():
    # Building_1 on plus_evs (Zero, full year): a baseline net exchange close to zero gave -720.
    rows = {
        'Building_1': (-150.0, 0.2, -720.0),
        'Building_2': (-40.0, -50.0, 1.2),
        'Building_3': (70.0, 60.0, 70.0 / 60.0),
        'District': (-120.0, 10.2, -120.0 / 10.2),
    }
    values = _apply(_records(NET, rows))
    assert values['building', 'Building_1'] is None
    assert values['building', 'Building_2'] == 1.2
    assert values['district', 'District'] == pytest.approx(-120.0 / 10.2)
    rows['District'] = (-120.0, 0.1, -1200.0)
    assert _apply(_records(NET, rows))['district', 'District'] is None


def test_zero_over_zero_keeps_its_value_and_a_single_member_keeps_its_ratio():
    values = _apply(_records(IMPORT, {
        'Building_1': (0.0, 0.0, 1.0),
        'Building_2': (100.0, 100.0, 1.0),
        'District': (100.0, 100.0, 1.0),
    }))
    assert values['building', 'Building_1'] == 1.0
    values = _apply(_records(IMPORT, {'Building_1': (5.0, 0.01, 500.0), 'District': (5.0, 0.01, 500.0)}))
    assert values['building', 'Building_1'] == 500.0
