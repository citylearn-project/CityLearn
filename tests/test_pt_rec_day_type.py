"""The Portugal REC datasets use CityLearn's `day_type`: 1 Monday to 7 Sunday, 8 for a holiday.

Their member files used to code each member's rest days as 1 and Monday to Friday as 2 to 6, so the entity
feature `is_weekend` (day_type 6 or 7) marked Fridays as weekend days and Saturdays and Sundays as working days.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from citylearn.citylearn import CityLearnEnv

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
PT_REC = ('pt_rec_4', 'pt_rec_15', 'pt_rec_30', 'pt_rec_100')
# Portuguese public holidays from Monday to Friday, with 13 June (Lisbon). Weekend holidays keep 6 or 7.
WEEKDAY_HOLIDAYS = {
    '2023-04-07', '2023-04-25', '2023-05-01', '2023-06-08', '2023-06-13', '2023-08-15', '2023-10-05',
    '2023-11-01', '2023-12-01', '2023-12-08', '2023-12-25', '2024-01-01', '2024-03-29', '2024-04-25',
    '2024-05-01', '2024-05-30', '2024-06-10', '2024-06-13', '2024-08-15', '2024-11-01', '2024-12-25',
}
# Row t starts at 2023-01-01 00:00 UTC + 15 min * t; month, hour and minutes are Lisbon civil time.
LOCAL = pd.date_range('2023-01-01', periods=70_176, freq='15min', tz='UTC').tz_convert('Europe/Lisbon')


def _expected_day_type(local):
    holiday = np.isin(local.strftime('%Y-%m-%d'), sorted(WEEKDAY_HOLIDAYS))
    return np.where(holiday, 8, local.dayofweek + 1)


def _row(local_text):
    return int(np.flatnonzero(LOCAL == pd.Timestamp(local_text, tz='Europe/Lisbon'))[0])


def _zero_actions(env):
    tables = env.action_space['tables']
    return {'tables': {n: np.zeros(s.shape, dtype='float32') for n, s in tables.items()
                       if n in {'building', 'charger', 'deferrable_appliance'}}}


def _rollout(start, end):
    """Dates, day_type and is_weekend of the first building at every step of a pt_rec_4 window."""

    env = CityLearnEnv(
        str(DATASETS / 'pt_rec_4' / 'schema.json'), simulation_start_time_step=start, simulation_end_time_step=end,
        random_seed=0, export_kpis_on_episode_end=False,
    )
    try:
        features = env.entity_specs['tables']['building']['features']
        column = features.index('is_weekend')
        observations, _ = env.reset(seed=0)
        is_weekend = [observations['tables']['building'][0, column]]
        actions = _zero_actions(env)
        while not env.terminated:
            observations, *_ = env.step(actions)
            is_weekend.append(observations['tables']['building'][0, column])
        day_type = np.asarray(env.buildings[0].energy_simulation.day_type)
    finally:
        env.close()

    local = LOCAL[start:end + 1]
    return local, day_type, np.asarray(is_weekend[:len(local)])


@pytest.mark.parametrize('name', PT_REC)
def test_every_member_file_codes_the_lisbon_weekday_and_holidays(name):
    expected = _expected_day_type(LOCAL)
    files = sorted((DATASETS / name).rglob('Member_*.parquet'))
    assert files

    for path in files:
        table = pq.read_table(path, columns=['month', 'hour', 'minutes', 'day_type'])
        assert np.array_equal(table.column('month').to_numpy(), LOCAL.month), path
        assert np.array_equal(table.column('hour').to_numpy(), LOCAL.hour + 1), path
        assert np.array_equal(table.column('minutes').to_numpy(), LOCAL.minute), path
        assert np.array_equal(table.column('day_type').to_numpy(), expected), path


def test_first_two_weeks_of_2023_follow_the_weekday_and_is_weekend_only_on_saturday_and_sunday():
    local, day_type, is_weekend = _rollout(0, 14 * 96 - 1)

    assert local[0].isoformat() == '2023-01-01T00:00:00+00:00'  # a Sunday
    assert day_type[0] == 7 and day_type[96] == 1  # Monday 2 January
    assert np.array_equal(day_type, local.dayofweek + 1)
    assert len(is_weekend) == len(local)
    assert np.array_equal(is_weekend, (local.dayofweek >= 5).astype(float))


def test_a_tuesday_holiday_is_day_type_8_and_not_a_weekend_day():
    start = _row('2023-04-24 00:00')
    local, day_type, is_weekend = _rollout(start, start + 7 * 96 - 1)
    dates = np.asarray(local.strftime('%Y-%m-%d'))
    holiday = dates == '2023-04-25'

    assert holiday.sum() == 96
    assert (day_type[holiday] == 8).all()
    assert np.array_equal(day_type[~holiday], (local.dayofweek + 1)[~holiday])
    assert np.array_equal(is_weekend, (local.dayofweek >= 5).astype(float))


def test_annual_rec_generator_writes_the_citylearn_day_type():
    from scripts.generate_annual_rec_suite import citylearn_day_type

    local = pd.DatetimeIndex(pd.to_datetime([
        '2023-01-01 12:00', '2023-01-02 12:00', '2023-01-06 12:00', '2023-01-07 12:00',
        '2023-04-25 12:00', '2023-06-10 12:00', '2023-12-25 12:00',
    ])).tz_localize('Europe/Lisbon')

    assert citylearn_day_type(local).tolist() == [7, 1, 5, 6, 8, 6, 8]
