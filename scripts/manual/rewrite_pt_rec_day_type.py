#!/usr/bin/env python3
"""Rewrite the `day_type` column of the bundled Portugal REC datasets (pt_rec_4/15/30/100).

The member files were written with `day_type` 1 on each member's rest days (weekends, holidays and, for some
routines, school breaks or shift rest days) and the weekday plus 2 on the other days. This script replaces
that column with the CityLearn convention, the same for every member: 1 Monday to 7 Sunday, and 8 for a
Portuguese public holiday that falls from Monday to Friday. A holiday on a Saturday or Sunday keeps 6 or 7.

Row *t* is the interval that starts at 2023-01-01 00:00 UTC + 15 min * t; its Lisbon civil date gives the
day. The script checks that the file's `month`, `hour` (1-24) and `minutes` columns agree with that clock
before it changes anything. Nothing but `day_type` changes: the table keeps its columns, types, row order and
metadata, and is written with the same pyarrow settings, which reproduce the original bytes of an unchanged
table (checked for every file). Files that already hold the new values are left untouched.

Run one dataset at a time:

    python scripts/manual/rewrite_pt_rec_day_type.py data/datasets/pt_rec_4
"""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROWS = 70_176
START_UTC = "2023-01-01 00:00"
STEP = "15min"
TIMEZONE = "Europe/Lisbon"

# Public holidays from Monday to Friday: national holidays, plus 13 June (Santo Antonio, the Lisbon municipal
# holiday that the dataset calendar treats as a rest day). Weekend holidays (2023-01-01, 2023-04-09 Easter,
# 2023-06-10, 2024-03-31 Easter, 2024-10-05, 2024-12-01, 2024-12-08) keep their weekday code.
WEEKDAY_HOLIDAYS = (
    "2023-04-07",  # Good Friday
    "2023-04-25",  # Freedom Day
    "2023-05-01",  # Labour Day
    "2023-06-08",  # Corpus Christi
    "2023-06-13",  # Santo Antonio (Lisbon)
    "2023-08-15",  # Assumption
    "2023-10-05",  # Republic Day
    "2023-11-01",  # All Saints' Day
    "2023-12-01",  # Restoration of Independence
    "2023-12-08",  # Immaculate Conception
    "2023-12-25",  # Christmas Day
    "2024-01-01",  # New Year's Day
    "2024-03-29",  # Good Friday
    "2024-04-25",  # Freedom Day
    "2024-05-01",  # Labour Day
    "2024-05-30",  # Corpus Christi
    "2024-06-10",  # Portugal Day
    "2024-06-13",  # Santo Antonio (Lisbon)
    "2024-08-15",  # Assumption
    "2024-11-01",  # All Saints' Day
    "2024-12-25",  # Christmas Day
)


def local_clock() -> pd.DatetimeIndex:
    return pd.date_range(START_UTC, periods=ROWS, freq=STEP, tz="UTC").tz_convert(TIMEZONE)


def day_type(local: pd.DatetimeIndex) -> np.ndarray:
    day_of_week = local.dayofweek.to_numpy()
    holiday = np.isin(local.strftime("%Y-%m-%d"), WEEKDAY_HOLIDAYS)
    if not (day_of_week[holiday] < 5).all():
        raise ValueError("a listed holiday is not a Monday to Friday")
    return np.where(holiday, 8, day_of_week + 1)


def _write(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd")
    return buffer.getvalue()


def rewrite(path: Path, local: pd.DatetimeIndex, codes: np.ndarray) -> str:
    original = path.read_bytes()
    table = pq.read_table(io.BytesIO(original))
    if _write(table) != original:
        raise RuntimeError(f"{path}: pyarrow does not reproduce the original bytes; use pyarrow 18.1.0")
    if table.num_rows != ROWS:
        raise ValueError(f"{path}: {table.num_rows} rows, expected {ROWS}")
    for column, expected in (("month", local.month), ("hour", local.hour + 1), ("minutes", local.minute)):
        if not np.array_equal(table.column(column).to_numpy(), np.asarray(expected)):
            raise ValueError(f"{path}: column {column} does not follow the {TIMEZONE} clock from {START_UTC} UTC")

    index = table.schema.get_field_index("day_type")
    field = table.schema.field(index)
    current = table.column(index).to_numpy()
    if np.array_equal(current, codes):
        return "unchanged"
    # Check the old coding before replacing it: 1 on rest days, otherwise the weekday + 2.
    work = current != 1
    if not np.array_equal(current[work], local.dayofweek.to_numpy()[work] + 2):
        raise ValueError(f"{path}: day_type is neither the old coding nor the new one")

    new = table.set_column(index, field, pa.array(codes.astype(field.type.to_pandas_dtype()), type=field.type))
    data = _write(new)
    check = pq.read_table(io.BytesIO(data))
    if not check.schema.equals(table.schema, check_metadata=True):
        raise RuntimeError(f"{path}: schema changed")
    if not check.remove_column(index).equals(table.remove_column(index)):
        raise RuntimeError(f"{path}: a column other than day_type changed")
    if not np.array_equal(check.column(index).to_numpy(), codes):
        raise RuntimeError(f"{path}: day_type was not written as intended")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return "rewritten"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset", type=Path, help="dataset directory, e.g. data/datasets/pt_rec_4")
    args = parser.parse_args()

    local = local_clock()
    codes = day_type(local)
    counts = {"rewritten": 0, "unchanged": 0}
    size_before = size_after = 0
    for path in sorted(args.dataset.rglob("*.parquet")):
        if "day_type" not in pq.ParquetFile(path).schema_arrow.names:
            continue
        size_before += path.stat().st_size
        counts[rewrite(path, local, codes)] += 1
        size_after += path.stat().st_size
    print(f"{args.dataset}: {counts['rewritten']} rewritten, {counts['unchanged']} unchanged, "
          f"{size_before} -> {size_after} bytes ({size_after - size_before:+d})")


if __name__ == "__main__":
    main()
