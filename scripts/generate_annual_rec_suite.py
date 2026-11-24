#!/usr/bin/env python3
"""Generate the canonical 2023 quarter-hour REC dataset suite.

The generated datasets are deterministic hybrid scenarios: member demand, PV,
weather, carbon, EV sessions and flexible-load requests are reproducible
synthetic profiles, while electricity prices are the official 2023 Portuguese
day-ahead prices published by OMIE.  The script keeps the four experimental
families self-contained and emits separate schemas for scenario variants that
share exactly the same physical time-series files.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd
import requests


YEAR = 2023
SECONDS_PER_TIME_STEP = 900
STEPS_PER_HOUR = 4
STEPS_PER_DAY = 96
N_STEPS = 35_040
N_HOURS = 8_760
TIMEZONE = "Europe/Lisbon"
GENERATOR_VERSION = "1.9.0"
DATASET_CONTRACT_VERSION = "2023-q15-v1.9"
SEED = 2023
OMIE_URL_TEMPLATE = (
    "https://www.omie.es/en/file-download?parents=marginalpdbcpt&"
    "filename=marginalpdbcpt_{date}.1"
)
OMIE_ARCHIVE_URL = (
    "https://www.omie.es/en/file-access-list?dir=+Day-ahead+market+hourly+price+in+Portugal&"
    "parents%5B0%5D=%2F&parents%5B1%5D=Day-ahead+Market&parents%5B2%5D=1.+Prices&"
    "realdir=marginalpdbcpt"
)
OMIE_MTU15_NOTICE_URL = (
    "https://www.omie.es/sites/default/files/2025-10/2501001_go_live_mtu15_md_en_vf.pdf"
)
ERSE_CONTRACTED_POWER_URL = (
    "https://www.erse.pt/media/02ibhrwu/manualutilizador_pt.pdf"
)
EREDES_CONNECTION_MANUAL_URL = (
    "https://www.e-redes.pt/sites/eredes/files/2025-04/"
    "Ficha%20eletrotecnica%20-%20como%20preencher_vf.pdf"
)
ERSE_EV_CHARGING_URL = (
    "https://www.erse.pt/consumidores-de-energia/mobilidade-electrica/como-funciona/"
)
DGEG_CONSUMPTION_URL = (
    "https://www.dgeg.gov.pt/pt/estatistica/energia/eletricidade/"
    "consumo-por-municipio-e-tipo-de-consumidor/"
)
PORDATA_CONSUMPTION_URL = (
    "https://www.pordata.pt/portugal/consumo+de+energia+eletrica+por+consumidor+"
    "total+e+por+tipo+de+consumo-1231"
)


def community_market_config(member_ids: Iterable[str]) -> Dict[str, object]:
    """The `community_market` section of a generated schema; CityLearn validates it at load (#366)."""
    return {
        "enabled": True,
        "local_price_ratio_to_grid_import": 0.8,
        "intra_community_sell_ratio": 0.8,
        "grid_export_price": 0.0,
        "import_member_weights": {member_id: 1.0 for member_id in member_ids},
        "counterfactual": "grid_only",
        "kpis": {
            "community_local_traded_enabled": True,
            "community_self_consumption_enabled": True,
        },
    }


@dataclass(frozen=True)
class FamilyConfig:
    key: str
    directory: str
    label: str
    member_categories: Tuple[str, ...]
    pv_members: Tuple[int, ...]
    battery_members: Tuple[int, ...]
    charger_counts: Mapping[int, int]
    deferrable_members: Tuple[int, ...]
    variants: Tuple[str, ...]
    default_variant: str


def _core_categories(member_count: int) -> Tuple[str, ...]:
    if member_count == 15:
        return tuple("residential" for _ in range(15))
    if member_count == 30:
        return tuple(
            ["residential"] * 24
            + ["small_service"] * 4
            + ["high_consumption"] * 2
        )
    raise ValueError(member_count)


FAMILIES: Mapping[str, FamilyConfig] = {
    "micro": FamilyConfig(
        key="micro",
        directory="rec_2023_micro_4_q",
        label="MICRO-4-Q",
        member_categories=("residential",) * 4,
        pv_members=(1, 2),
        battery_members=(1,),
        charger_counts={1: 1, 3: 1},
        deferrable_members=(1,),
        variants=("MICRO-4-Q",),
        default_variant="MICRO-4-Q",
    ),
    "core15": FamilyConfig(
        key="core15",
        directory="rec_2023_core_15_stripped",
        label="CORE-15-STRIPPED",
        member_categories=_core_categories(15),
        pv_members=(1, 3, 5, 8, 10, 12, 14),
        battery_members=(1, 3, 12),
        charger_counts={1: 1, 2: 1, 4: 1, 5: 1, 6: 2, 10: 1},
        deferrable_members=(2, 6, 9, 14),
        variants=("CORE-15-STRIPPED",),
        default_variant="CORE-15-STRIPPED",
    ),
    "core30": FamilyConfig(
        key="core30",
        directory="rec_2023_core_30",
        label="CORE-30",
        member_categories=_core_categories(30),
        pv_members=(1, 3, 5, 8, 10, 12, 14, 16, 18, 20, 22, 24, 25, 27, 29),
        battery_members=(1, 3, 12, 18, 25, 29),
        charger_counts={
            1: 1, 2: 1, 4: 1, 5: 1, 6: 2, 10: 1,
            16: 1, 17: 1, 19: 1, 20: 2, 21: 2, 23: 1,
        },
        deferrable_members=(2, 6, 9, 14, 17, 22, 26, 30),
        variants=(
            "CORE-30-NOMINAL",
            "CORE-30-SAFETY",
            "CORE-30-HEALTH",
            "CORE-30-DYNAMIC",
            "CORE-30-COMBINED",
        ),
        default_variant="CORE-30-NOMINAL",
    ),
    "premium": FamilyConfig(
        key="premium",
        directory="rec_2023_premium_100",
        label="PREMIUM-100",
        member_categories=tuple(
            ["residential"] * 70
            + ["small_service"] * 20
            + ["high_consumption"] * 10
        ),
        pv_members=(
            1, 2, 5, 8, 9, 12, 13, 16, 17, 20, 21, 24, 25, 28, 29,
            32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60,
            62, 64, 66, 68, 70,
            71, 72, 73, 75, 76, 78, 79, 81, 82, 84, 85, 87, 88, 90,
            91, 92, 94, 95, 97, 99,
        ),
        battery_members=(
            1, 8, 12, 17, 25, 32, 38, 44, 50, 52, 58, 62, 66, 70,
            71, 75, 79, 82, 87, 90,
            92, 97,
        ),
        charger_counts={
            **{
                i: 1
                for i in (
                    1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23,
                    27, 29, 31, 34, 37, 40, 43, 46, 49, 52, 55, 58,
                )
            },
            **{i: 2 for i in (6, 25, 45, 61, 66, 70)},
            **{i: 2 for i in (71, 73, 75, 77, 79, 82, 84, 86, 88, 90)},
            91: 4, 93: 4, 95: 4, 97: 6, 99: 6,
        },
        deferrable_members=(
            2, 6, 10, 14, 18, 22, 26, 30, 34, 39, 45, 51, 57, 63, 69,
            72, 73, 76, 78, 80, 82, 84, 86, 88, 90,
            91, 93, 95, 97, 99,
        ),
        variants=("PREMIUM-100-CLEAN", "PREMIUM-100-ALLIN"),
        default_variant="PREMIUM-100-CLEAN",
    ),
}


OBSERVATIONS = {
    name: {"active": active, "shared_in_central_agent": shared}
    for name, active, shared in (
        ("month", True, True),
        ("day_type", True, True),
        ("hour", True, True),
        ("minutes", True, True),
        ("daylight_savings_status", True, True),
        ("outdoor_dry_bulb_temperature", True, True),
        ("outdoor_dry_bulb_temperature_predicted_1", True, True),
        ("outdoor_dry_bulb_temperature_predicted_2", True, True),
        ("outdoor_dry_bulb_temperature_predicted_3", True, True),
        ("outdoor_relative_humidity", True, True),
        ("diffuse_solar_irradiance", True, True),
        ("direct_solar_irradiance", True, True),
        ("carbon_intensity", True, True),
        ("non_shiftable_load", True, False),
        ("solar_generation", True, False),
        ("electrical_storage_soc", True, False),
        ("net_electricity_consumption", True, False),
        ("electricity_pricing", True, True),
        ("electricity_pricing_predicted_1", True, True),
        ("electricity_pricing_predicted_2", True, True),
        ("electricity_pricing_predicted_3", True, True),
        ("power_outage", True, False),
        ("electric_vehicle_charger_connected_state", True, False),
        ("connected_electric_vehicle_at_charger_battery_capacity", True, False),
        ("connected_electric_vehicle_at_charger_departure_time", True, False),
        ("connected_electric_vehicle_at_charger_required_soc_departure", True, False),
        ("connected_electric_vehicle_at_charger_soc", True, False),
        ("electric_vehicle_charger_incoming_state", True, False),
        ("incoming_electric_vehicle_at_charger_estimated_arrival_time", True, False),
        ("deferrable_appliance_pending", True, False),
        ("deferrable_appliance_running", True, False),
        ("deferrable_appliance_can_start", True, False),
        ("deferrable_appliance_deadline_missed", True, False),
        ("deferrable_appliance_earliest_start_time_step", True, False),
        ("deferrable_appliance_latest_start_time_step", True, False),
        ("deferrable_appliance_deadline_time_step", True, False),
        ("deferrable_appliance_hours_until_latest_start", True, False),
        ("deferrable_appliance_hours_until_deadline", True, False),
        ("deferrable_appliance_slack_steps", True, False),
        ("deferrable_appliance_slack_ratio", True, False),
        ("deferrable_appliance_urgency_ratio", True, False),
        ("deferrable_appliance_cycle_duration_steps", True, False),
        ("deferrable_appliance_cycle_energy_kwh", True, False),
        ("deferrable_appliance_remaining_energy_kwh", True, False),
        ("deferrable_appliance_current_step_energy_kwh", True, False),
        ("deferrable_appliance_priority", True, False),
    )
}


def _member_id(index: int) -> str:
    return f"Member_{index:03d}"


def _charger_id(member_index: int, charger_index: int) -> str:
    return f"CHG-M{member_index:03d}-{charger_index:02d}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_file_checksums(root: Path) -> None:
    checksum_path = root / "file_checksums.sha256"
    excluded = {"file_checksums.sha256", "validation_report.json"}
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        rows.append(f"{digest.hexdigest()}  {relative}")
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _shift_forecast(values: np.ndarray, steps: int) -> np.ndarray:
    result = np.empty_like(values)
    result[:-steps] = values[steps:]
    result[-steps:] = values[-1]
    return result


def _parse_omie_payload(day: date, filename: str, payload: bytes) -> Tuple[List[Mapping], Mapping]:
    text = payload.decode("latin-1")
    rows: List[Mapping] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("MARGINAL") or line == "*":
            continue
        fields = line.split(";")
        if len(fields) < 6:
            raise ValueError(f"Malformed OMIE row for {day.isoformat()}: {line!r}")
        row_day = date(int(fields[0]), int(fields[1]), int(fields[2]))
        if row_day != day:
            raise ValueError(f"OMIE file for {day.isoformat()} contains {row_day.isoformat()}.")
        rows.append(
            {
                "market_date": day.isoformat(),
                "market_period": int(fields[3]),
                "price_spain_eur_per_mwh": float(fields[4]),
                "price_portugal_eur_per_mwh": float(fields[5]),
            }
        )
    if len(rows) not in {23, 24, 25}:
        raise ValueError(f"Expected 23, 24 or 25 OMIE periods on {day}, got {len(rows)}.")
    if [r["market_period"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"Non-contiguous OMIE periods on {day}.")
    source = {
        "market_date": day.isoformat(),
        "filename": filename,
        "url": (
            "https://www.omie.es/en/file-download?parents=marginalpdbcpt&"
            f"filename={filename}"
        ),
        "periods": len(rows),
        "raw_sha256": _sha256_bytes(payload),
    }
    return rows, source


def _download_omie_day(day: date, filename: str, timeout: float = 30.0) -> Tuple[date, str, bytes]:
    url = (
        "https://www.omie.es/en/file-download?parents=marginalpdbcpt&"
        f"filename={filename}"
    )
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.content
    if b"MARGINALPDBCPT" not in payload:
        raise ValueError(f"Unexpected response for {url}.")
    return day, filename, payload


def _omie_2023_filenames() -> Mapping[date, str]:
    response = requests.get(OMIE_ARCHIVE_URL, timeout=60.0)
    response.raise_for_status()
    matches = re.findall(r"marginalpdbcpt_(2023\d{4})\.(\d+)", response.text)
    revisions: Dict[date, Tuple[int, str]] = {}
    for compact_date, revision_text in matches:
        day = pd.Timestamp(compact_date).date()
        revision = int(revision_text)
        filename = f"marginalpdbcpt_{compact_date}.{revision}"
        if day not in revisions or revision > revisions[day][0]:
            revisions[day] = (revision, filename)
    if len(revisions) != 365:
        raise ValueError(
            f"OMIE archive index exposed {len(revisions)} days for 2023, expected 365."
        )
    return {day: value[1] for day, value in revisions.items()}


def get_omie_hourly(source_root: Path, refresh: bool = False) -> pd.DataFrame:
    """Return the 8,760 official Portuguese prices and persist provenance."""

    hourly_path = source_root / "omie_2023_hourly.parquet"
    provenance_path = source_root / "omie_2023_daily_provenance.csv"
    if hourly_path.is_file() and provenance_path.is_file() and not refresh:
        frame = pd.read_parquet(hourly_path)
        if len(frame) != N_HOURS:
            raise ValueError(f"Cached OMIE hourly file has {len(frame)} rows, expected {N_HOURS}.")
        return frame

    source_root.mkdir(parents=True, exist_ok=True)
    days = [date(YEAR, 1, 1) + timedelta(days=i) for i in range(365)]
    filenames = _omie_2023_filenames()
    payloads: Dict[date, Tuple[str, bytes]] = {}
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(_download_omie_day, day, filenames[day]): day
            for day in days
        }
        for future in as_completed(futures):
            day, filename, payload = future.result()
            payloads[day] = (filename, payload)

    records: List[Mapping] = []
    sources: List[Mapping] = []
    for day in days:
        filename, payload = payloads[day]
        daily_rows, daily_source = _parse_omie_payload(day, filename, payload)
        records.extend(daily_rows)
        sources.append(daily_source)
    if len(records) != N_HOURS:
        raise ValueError(f"OMIE 2023 contains {len(records)} physical hours, expected {N_HOURS}.")

    frame = pd.DataFrame(records)
    frame.insert(0, "timestamp_utc", pd.date_range(
        f"{YEAR}-01-01", periods=N_HOURS, freq="1h", tz="UTC"
    ))
    frame.to_parquet(hourly_path, index=False, compression="zstd")
    pd.DataFrame(sources).to_csv(provenance_path, index=False)
    return frame


def build_calendar() -> pd.DataFrame:
    utc = pd.date_range(f"{YEAR}-01-01", periods=N_STEPS, freq="15min", tz="UTC")
    local = utc.tz_convert(TIMEZONE)
    offsets = np.array([int(ts.utcoffset().total_seconds() // 60) for ts in local], dtype="int16")
    return pd.DataFrame(
        {
            "time_step": np.arange(N_STEPS, dtype="int32"),
            "timestamp_utc": utc,
            "timestamp_local": local.astype(str),
            "timezone": TIMEZONE,
            "utc_offset_minutes": offsets,
            "month_local": local.month.astype("int8"),
            "day_local": local.day.astype("int8"),
            "day_of_week_local": (local.dayofweek + 1).astype("int8"),
            "hour_local": local.hour.astype("int8"),
            "minute_local": local.minute.astype("int8"),
            "daylight_savings_status": (offsets != 0).astype("int8"),
        }
    )


def build_shared_series(calendar_frame: pd.DataFrame, omie_hourly: pd.DataFrame):
    local_hour = calendar_frame["hour_local"].to_numpy(dtype="float64") + calendar_frame["minute_local"].to_numpy(dtype="float64") / 60.0
    day_of_year = pd.to_datetime(calendar_frame["timestamp_utc"], utc=True).dt.dayofyear.to_numpy(dtype="float64")
    solar_declination = 2.0 * np.pi * (day_of_year - 81.0) / 365.0
    daylight = np.clip(np.sin(np.pi * (local_hour - 7.0) / 11.0), 0.0, None)
    seasonal_solar = np.clip(0.68 + 0.32 * np.sin(solar_declination), 0.20, 1.0)
    cloud = np.clip(
        0.76 + 0.14 * np.sin(2.0 * np.pi * day_of_year / 9.0)
        + 0.08 * np.sin(2.0 * np.pi * day_of_year / 31.0),
        0.35,
        1.0,
    )
    pv_factor = np.clip(daylight * seasonal_solar * cloud, 0.0, 1.0)
    direct = 780.0 * pv_factor
    diffuse = np.where(daylight > 0.0, 55.0 + 120.0 * daylight * (1.0 - cloud), 0.0)
    outdoor_temperature = (
        16.0
        + 7.0 * np.sin(2.0 * np.pi * (day_of_year - 172.0) / 365.0)
        + 3.2 * np.sin(2.0 * np.pi * (local_hour - 14.0) / 24.0)
    )
    humidity = np.clip(70.0 - 0.8 * (outdoor_temperature - 16.0) + 8.0 * np.sin(2.0 * np.pi * local_hour / 24.0), 30.0, 96.0)

    weather = pd.DataFrame(
        {
            "outdoor_dry_bulb_temperature": outdoor_temperature.astype("float32"),
            "outdoor_relative_humidity": humidity.astype("float32"),
            "diffuse_solar_irradiance": diffuse.astype("float32"),
            "direct_solar_irradiance": direct.astype("float32"),
        }
    )
    forecast_rng = np.random.default_rng(SEED * 17)
    weather_error_scale = {
        "outdoor_dry_bulb_temperature": (0.35, 0.80, 1.50),
        "outdoor_relative_humidity": (1.50, 3.00, 5.00),
        "diffuse_solar_irradiance": (0.10, 0.18, 0.28),
        "direct_solar_irradiance": (0.08, 0.16, 0.26),
    }
    for name in tuple(weather.columns):
        values = weather[name].to_numpy()
        for number, (horizon, scale) in enumerate(
            zip((4, 24, 96), weather_error_scale[name]), start=1
        ):
            truth = _shift_forecast(values, horizon).astype("float64")
            innovations = forecast_rng.normal(0.0, 1.0, len(values) + 16)
            correlated_error = np.convolve(
                innovations, np.ones(16, dtype="float64") / 16.0, mode="valid"
            )[: len(values)]
            correlated_error /= max(float(correlated_error.std()), 1.0e-9)
            if "solar_irradiance" in name:
                prediction = np.clip(truth * (1.0 + scale * correlated_error), 0.0, None)
            else:
                prediction = truth + scale * correlated_error
                if name == "outdoor_relative_humidity":
                    prediction = np.clip(prediction, 0.0, 100.0)
            weather[f"{name}_predicted_{number}"] = prediction.astype("float32")

    price_hourly = omie_hourly["price_portugal_eur_per_mwh"].to_numpy(dtype="float64")
    price = np.repeat(price_hourly / 1000.0, STEPS_PER_HOUR)
    if len(price) != N_STEPS:
        raise ValueError("Quarter-hour OMIE price expansion failed.")
    pricing = pd.DataFrame({"electricity_pricing": price.astype("float32")})
    local_index = pd.DatetimeIndex(calendar_frame["timestamp_utc"]).tz_convert(TIMEZONE)
    current_indices = np.arange(N_STEPS, dtype="int64")
    for number, horizon in enumerate((4, 24, 96), start=1):
        target_indices = np.minimum(current_indices + horizon, N_STEPS - 1)
        target = price[target_indices]
        target_delivery_dates = local_index[target_indices].normalize()
        publication_instants = target_delivery_dates - pd.Timedelta(days=1) + pd.Timedelta(hours=13)
        published = local_index >= publication_instants

        # Realised market prices are exact only after the declared day-ahead
        # publication cut-off.  Before publication, daily persistence supplies
        # a causal fallback for the requested delivery interval.
        persistence_indices = np.maximum(target_indices - STEPS_PER_DAY, 0)
        persistence_indices = np.minimum(persistence_indices, current_indices)
        prediction = np.where(published, target, price[persistence_indices])
        pricing[f"electricity_pricing_predicted_{number}"] = prediction.astype("float32")

    # A deterministic representative Portuguese grid-intensity profile.  It is
    # intentionally labelled hybrid; only the OMIE prices are represented as
    # historical measurements from 2023.
    carbon = np.clip(
        0.205
        + 0.045 * np.sin(2.0 * np.pi * (local_hour - 18.0) / 24.0)
        + 0.030 * np.sin(2.0 * np.pi * (day_of_year - 20.0) / 365.0)
        - 0.040 * pv_factor,
        0.055,
        0.370,
    )
    carbon_intensity = pd.DataFrame({"carbon_intensity": carbon.astype("float32")})
    return weather, pricing, carbon_intensity, pv_factor


def _profile_seed(member_index: int) -> int:
    # Core-15 is a literal first-15 subset of Core-30 because this seed is
    # independent of the family name.
    return SEED * 10_000 + member_index


ROUTINE_ARCHETYPES: Mapping[str, Tuple[str, ...]] = {
    "residential": (
        "early_commuter",
        "standard_commuter",
        "late_commuter",
        "home_worker",
        "home_day",
    ),
    "small_service": (
        "office_hours",
        "retail_six_day",
        "clinic_split_day",
        "hospitality_extended",
        "workshop_early",
    ),
    "high_consumption": (
        "day_process",
        "extended_process",
        "continuous_process",
        "morning_intensive",
        "evening_intensive",
    ),
}


def _routine_archetype(member_index: int, category: str) -> str:
    """Return a stratified scenario archetype that is stable across families."""

    archetypes = ROUTINE_ARCHETYPES[category]
    return archetypes[(member_index - 1) % len(archetypes)]


def _periodic_gaussian(
    hour: np.ndarray,
    centre: float | np.ndarray,
    width: float,
) -> np.ndarray:
    delta = np.abs(hour - centre)
    delta = np.minimum(delta, 24.0 - delta)
    return np.exp(-0.5 * (delta / width) ** 2)


def _bounded_lognormal(
    rng: np.random.Generator,
    median: float,
    sigma: float,
    lower: float,
    upper: float,
) -> float:
    """Sample without producing artificial point masses at clipping limits."""

    for _ in range(1_000):
        value = float(rng.lognormal(mean=np.log(median), sigma=sigma))
        if lower < value < upper:
            return value
    raise RuntimeError("Unable to sample the bounded annual-demand distribution.")


def build_member_timeseries(
    member_index: int,
    category: str,
    has_pv: bool,
    calendar_frame: pd.DataFrame,
    pv_factor: np.ndarray,
) -> Tuple[pd.DataFrame, Mapping]:
    rng = np.random.default_rng(_profile_seed(member_index))
    local_index = pd.DatetimeIndex(calendar_frame["timestamp_utc"]).tz_convert(TIMEZONE)
    hour = local_index.hour.to_numpy(dtype="float64") + local_index.minute.to_numpy(dtype="float64") / 60.0
    day_of_week = local_index.dayofweek.to_numpy(dtype="int8")
    weekday = day_of_week < 5
    saturday = day_of_week == 5
    day_of_year = local_index.dayofyear.to_numpy(dtype="float64")
    day_codes, unique_days = pd.factorize(local_index.normalize())
    n_local_days = len(unique_days)
    daily_shift = np.clip(rng.normal(0.0, 0.42, n_local_days), -1.25, 1.25)[day_codes]
    holiday = np.isin(
        local_index.strftime("%m-%d"),
        (
            "01-01", "04-07", "04-09", "04-25", "05-01", "06-08",
            "06-10", "08-15", "10-05", "11-01", "12-01", "12-08", "12-25",
        ),
    )
    off_day = ~weekday | holiday
    routine_archetype = _routine_archetype(member_index, category)

    if category == "residential":
        occupants = int(rng.integers(1, 6))
        base_kw = rng.uniform(0.16, 0.39)
        routine_parameters = {
            "early_commuter": (6.35, 17.75, 0.08, 0.18),
            "standard_commuter": (7.45, 19.35, 0.10, 0.20),
            "late_commuter": (9.00, 21.65, 0.12, 0.23),
            "home_worker": (8.10, 19.55, 0.46, 0.42),
            "home_day": (8.55, 18.80, 0.62, 0.52),
        }
        morning_centre, evening_centre, daytime_level, lunch_scale = routine_parameters[routine_archetype]
        morning = rng.uniform(0.50, 1.35) * _periodic_gaussian(
            hour, morning_centre + daily_shift, rng.uniform(0.75, 1.35)
        )
        evening = rng.uniform(0.95, 2.25) * _periodic_gaussian(
            hour, evening_centre + 0.45 * daily_shift, rng.uniform(1.35, 2.25)
        )
        daytime = daytime_level * ((hour >= 9.0) & (hour < 17.0))
        lunch = lunch_scale * _periodic_gaussian(
            hour, 13.0 + 0.35 * daily_shift, rng.uniform(0.65, 1.15)
        )
        weekday_activity = base_kw + morning + evening + daytime + lunch
        weekend_activity = (
            base_kw * 1.10
            + rng.uniform(0.55, 1.15) * _periodic_gaussian(hour, 9.4 + daily_shift, 1.45)
            + rng.uniform(0.35, 0.90) * _periodic_gaussian(hour, 13.4, 1.35)
            + rng.uniform(1.00, 2.00) * _periodic_gaussian(hour, 20.3, 2.15)
            + rng.uniform(0.14, 0.38) * ((hour >= 10.0) & (hour < 18.0))
        )
        activity = np.where(off_day, weekend_activity, weekday_activity)
        away_probability = {
            "early_commuter": 0.055,
            "standard_commuter": 0.050,
            "late_commuter": 0.045,
            "home_worker": 0.030,
            "home_day": 0.025,
        }[routine_archetype]
        reduced_days = rng.random(n_local_days) < away_probability
        reduced_factor = np.where(reduced_days[day_codes], rng.uniform(0.38, 0.58), 1.0)
        activity = base_kw + (activity - base_kw) * reduced_factor
        annual_target_kwh = _bounded_lognormal(rng, 2_490.0, 0.40, 1_100.0, 6_500.0)
        if routine_archetype in {"early_commuter", "standard_commuter", "late_commuter"}:
            occupied = off_day | (hour < morning_centre + 1.0) | (hour >= evening_centre - 1.0)
            occupancy_ratio = np.where(occupied, 1.0, 0.08)
        elif routine_archetype == "home_worker":
            occupancy_ratio = np.where(off_day, 1.0, 0.82)
        else:
            occupancy_ratio = np.where(off_day, 1.0, 0.92)
        equity_group = "residential"
    elif category == "small_service":
        occupants = int(rng.integers(4, 20))
        base_kw = rng.uniform(0.55, 1.55)
        operating_power = rng.uniform(3.8, 10.5)
        if routine_archetype == "office_hours":
            opening = weekday & ~holiday & (hour >= 7.6 + daily_shift) & (hour < 18.4 + daily_shift)
            shape = 0.45 * _periodic_gaussian(hour, 10.2, 2.2) + 0.35 * _periodic_gaussian(hour, 15.3, 2.0)
            closure_probability = 0.070
        elif routine_archetype == "retail_six_day":
            opening = (weekday | saturday) & ~holiday & (hour >= 9.0 + daily_shift) & (hour < 20.7 + daily_shift)
            shape = 0.35 * _periodic_gaussian(hour, 12.1, 2.0) + 0.55 * _periodic_gaussian(hour, 18.0, 2.1)
            closure_probability = 0.035
        elif routine_archetype == "clinic_split_day":
            opening = weekday & ~holiday & (
                ((hour >= 7.3 + daily_shift) & (hour < 13.0))
                | ((hour >= 14.0) & (hour < 19.2 + daily_shift))
            )
            shape = 0.55 * _periodic_gaussian(hour, 10.1, 1.6) + 0.48 * _periodic_gaussian(hour, 16.5, 1.6)
            closure_probability = 0.060
        elif routine_archetype == "hospitality_extended":
            opening = (hour >= 6.0 + 0.4 * daily_shift) & (hour < 23.2 + 0.2 * daily_shift)
            shape = (
                0.60 * _periodic_gaussian(hour, 8.0, 1.5)
                + 0.50 * _periodic_gaussian(hour, 13.1, 1.6)
                + 0.85 * _periodic_gaussian(hour, 20.0, 1.8)
            )
            closure_probability = 0.018
        else:
            opening = (
                (weekday & ~holiday & (hour >= 6.1 + daily_shift) & (hour < 16.8 + daily_shift))
                | (saturday & (hour >= 7.0) & (hour < 13.0))
            )
            shape = 0.65 * _periodic_gaussian(hour, 9.0, 1.8) + 0.30 * _periodic_gaussian(hour, 14.2, 1.5)
            closure_probability = 0.050
        reduced_days = rng.random(n_local_days) < closure_probability
        operation_factor = np.where(reduced_days[day_codes], rng.uniform(0.04, 0.20), 1.0)
        opening_level = opening.astype("float64") * operation_factor
        activity = base_kw + operating_power * opening_level * (1.0 + shape)
        annual_target_kwh = _bounded_lognormal(rng, 16_580.0, 0.45, 7_000.0, 45_000.0)
        occupancy_ratio = np.where(opening, 0.72 + 0.22 * np.clip(shape, 0.0, 1.0), 0.03)
        equity_group = "service"
    else:
        occupants = int(rng.integers(20, 90))
        base_kw = rng.uniform(3.5, 9.5)
        operating_power = rng.uniform(16.0, 46.0)
        if routine_archetype == "day_process":
            opening = weekday & ~holiday & (hour >= 6.0 + daily_shift) & (hour < 18.3 + daily_shift)
            shift_shape = 0.45 * _periodic_gaussian(hour, 10.5, 2.4) + 0.30 * _periodic_gaussian(hour, 15.2, 2.2)
            reduced_weekend = 0.05
        elif routine_archetype == "extended_process":
            opening = ((weekday & ~holiday) | saturday) & (hour >= 5.0 + daily_shift) & (hour < 23.0 + 0.4 * daily_shift)
            shift_shape = 0.35 * _periodic_gaussian(hour, 8.5, 2.3) + 0.40 * _periodic_gaussian(hour, 17.0, 3.0)
            reduced_weekend = 0.18
        elif routine_archetype == "continuous_process":
            opening = np.ones(N_STEPS, dtype=bool)
            shift_shape = (
                0.16 * _periodic_gaussian(hour, 6.0, 1.8)
                + 0.20 * _periodic_gaussian(hour, 14.0, 2.0)
                + 0.14 * _periodic_gaussian(hour, 22.0, 1.8)
            )
            reduced_weekend = 0.82
        elif routine_archetype == "morning_intensive":
            opening = (day_of_week < 6) & (hour >= 3.8 + daily_shift) & (hour < 15.2 + daily_shift)
            shift_shape = 0.75 * _periodic_gaussian(hour, 7.2, 2.2)
            reduced_weekend = 0.25
        else:
            opening = (day_of_week < 6) & (hour >= 11.8 + daily_shift) & (hour < 23.8 + 0.3 * daily_shift)
            shift_shape = 0.72 * _periodic_gaussian(hour, 19.2, 2.5)
            reduced_weekend = 0.25
        reduced_days = rng.random(n_local_days) < 0.025
        maintenance_factor = np.where(reduced_days[day_codes], rng.uniform(0.22, 0.45), 1.0)
        weekend_factor = np.where(weekday, 1.0, reduced_weekend)
        opening_level = opening.astype("float64") * maintenance_factor * weekend_factor
        activity = base_kw + operating_power * opening_level * (1.0 + shift_shape)
        annual_target_kwh = _bounded_lognormal(rng, 175_900.0, 0.36, 75_000.0, 350_000.0)
        occupancy_ratio = np.where(opening, 0.68 + 0.25 * np.clip(shift_shape, 0.0, 1.0), 0.08)
        equity_group = "large_service"

    seasonal = 1.0 + 0.10 * np.cos(2.0 * np.pi * (day_of_year - 15.0) / 365.0)
    daily_multiplier = rng.lognormal(mean=-0.5 * 0.13**2, sigma=0.13, size=n_local_days)
    innovations = rng.normal(0.0, 1.0, N_STEPS + 7)
    correlated_noise = np.convolve(
        innovations,
        np.array([0.08, 0.12, 0.16, 0.28, 0.16, 0.12, 0.08]),
        mode="valid",
    )[:N_STEPS]
    correlated_noise /= max(float(correlated_noise.std()), 1.0e-9)
    within_day_noise = np.exp(0.065 * correlated_noise - 0.5 * 0.065**2)
    raw_load_kw = np.clip(
        activity
        * seasonal
        * daily_multiplier[day_codes]
        * within_day_noise,
        0.05,
        None,
    )
    load_kw = raw_load_kw * (annual_target_kwh / (raw_load_kw.sum() * 0.25))
    pv_capacity_kw = 0.0
    pv_orientation = "none"
    pv_derate = 0.0
    if has_pv:
        specific_yield_kwh_per_kwp = float(pv_factor.sum() * 0.25)
        if category == "residential":
            coverage_ratio = float(rng.uniform(0.58, 1.32))
            pv_capacity_kw = float(np.clip(
                annual_target_kwh * coverage_ratio / specific_yield_kwh_per_kwp,
                1.5,
                8.0,
            ))
        elif category == "small_service":
            coverage_ratio = float(rng.uniform(0.42, 1.02))
            pv_capacity_kw = float(np.clip(
                annual_target_kwh * coverage_ratio / specific_yield_kwh_per_kwp,
                8.0,
                40.0,
            ))
        else:
            coverage_ratio = float(rng.uniform(0.32, 0.82))
            pv_capacity_kw = float(np.clip(
                annual_target_kwh * coverage_ratio / specific_yield_kwh_per_kwp,
                30.0,
                150.0,
            ))
        pv_orientation = str(rng.choice(["east", "south", "west"], p=[0.25, 0.50, 0.25]))
        orientation_sign = {"east": -1.0, "south": 0.0, "west": 1.0}[pv_orientation]
        orientation_modifier = 1.0 + orientation_sign * 0.16 * np.tanh((hour - 13.0) / 2.8)
        pv_derate = float(rng.uniform(0.84, 0.98))
        day_shading = 1.0 - rng.uniform(0.0, 0.10) * (
            0.5 + 0.5 * np.sin(2.0 * np.pi * day_of_year / rng.uniform(17.0, 43.0))
        )
        member_pv_factor = np.clip(
            pv_factor * orientation_modifier * day_shading * pv_derate,
            0.0,
            1.05,
        )
    else:
        member_pv_factor = np.zeros(N_STEPS, dtype="float64")
    solar_kwh = pv_capacity_kw * member_pv_factor * 0.25

    outage = np.zeros(N_STEPS, dtype="int8")
    outage_start = 27_000 + (member_index % 20) * 8
    outage[outage_start:outage_start + 8] = 1

    frame = pd.DataFrame(
        {
            "month": calendar_frame["month_local"].to_numpy(dtype="int8"),
            "hour": calendar_frame["hour_local"].to_numpy(dtype="int8"),
            "minutes": calendar_frame["minute_local"].to_numpy(dtype="int8"),
            "day_type": calendar_frame["day_of_week_local"].to_numpy(dtype="int8"),
            "daylight_savings_status": calendar_frame["daylight_savings_status"].to_numpy(dtype="int8"),
            "indoor_dry_bulb_temperature": np.full(N_STEPS, 21.0, dtype="float32"),
            "average_unmet_cooling_setpoint_difference": np.zeros(N_STEPS, dtype="float32"),
            "indoor_relative_humidity": np.full(N_STEPS, 50.0, dtype="float32"),
            "occupant_count": np.clip(
                np.rint(occupants * occupancy_ratio), 0, occupants
            ).astype("int16"),
            "non_shiftable_load": (load_kw * 0.25).astype("float32"),
            "dhw_demand": np.zeros(N_STEPS, dtype="float32"),
            "cooling_demand": np.zeros(N_STEPS, dtype="float32"),
            "heating_demand": np.zeros(N_STEPS, dtype="float32"),
            "solar_generation": solar_kwh.astype("float32"),
            "power_outage": outage,
        }
    )
    metadata = {
        "member_id": _member_id(member_index),
        "member_index": member_index,
        "category": category,
        "routine_archetype": routine_archetype,
        "equity_group": equity_group,
        "occupants": occupants,
        "annual_reduced_activity_days": int(reduced_days.sum()),
        "pv_capacity_kw": round(pv_capacity_kw, 3),
        "pv_orientation_class": pv_orientation,
        "pv_derate_factor": round(pv_derate, 4),
        "annual_load_target_kwh": round(annual_target_kwh, 3),
        "annual_non_shiftable_load_kwh": round(float(frame["non_shiftable_load"].sum()), 3),
        "annual_pv_generation_kwh": round(float(frame["solar_generation"].sum()), 3),
        "peak_non_shiftable_power_kw": round(
            float(frame["non_shiftable_load"].max() * STEPS_PER_HOUR), 4
        ),
        "peak_pv_generation_power_kw": round(
            float(frame["solar_generation"].max() * STEPS_PER_HOUR), 4
        ),
        "peak_native_import_power_kw": round(
            float(
                np.maximum(
                    (frame["non_shiftable_load"] - frame["solar_generation"])
                    * STEPS_PER_HOUR,
                    0.0,
                ).max()
            ),
            4,
        ),
        "peak_native_export_power_kw": round(
            float(
                np.maximum(
                    (frame["solar_generation"] - frame["non_shiftable_load"])
                    * STEPS_PER_HOUR,
                    0.0,
                ).max()
            ),
            4,
        ),
        "annual_pv_to_load_ratio": round(
            float(frame["solar_generation"].sum() / frame["non_shiftable_load"].sum()), 4
        ),
    }
    return frame, metadata


def build_stationary_battery(
    member_index: int,
    category: str,
    pv_capacity_kw: float,
    annual_load_kwh: float,
) -> Mapping:
    """Size a reproducible product-like BESS around the host PV installation."""

    rng = np.random.default_rng(SEED * 20_000 + member_index)
    if category == "residential":
        capacities = np.array([5.0, 7.5, 9.6, 10.0, 13.5, 15.0])
        powers = np.array([2.5, 3.68, 4.6, 5.0, 6.0])
        autonomy_class = (0.65, 0.90, 1.20, 1.55, 1.90)[(member_index - 1) % 5]
        target_capacity = max(
            4.5,
            pv_capacity_kw * 1.10,
            annual_load_kwh / 365.0 * autonomy_class * rng.uniform(0.92, 1.08),
        )
    elif category == "small_service":
        capacities = np.array([20.0, 30.0, 40.0, 50.0, 60.0, 75.0])
        powers = np.array([10.0, 15.0, 20.0, 25.0, 30.0])
        autonomy_class = (0.55, 0.75, 0.95, 1.15, 1.35)[(member_index - 1) % 5]
        target_capacity = max(
            18.0,
            pv_capacity_kw * 1.10,
            annual_load_kwh / 365.0 * autonomy_class * rng.uniform(0.92, 1.08),
        )
    else:
        capacities = np.array([60.0, 80.0, 100.0, 120.0, 160.0, 200.0])
        powers = np.array([30.0, 40.0, 50.0, 60.0, 80.0])
        autonomy_class = (0.16, 0.38, 0.28, 0.46, 0.56)[(member_index - 1) % 5]
        target_capacity = max(
            55.0,
            pv_capacity_kw * 1.05,
            annual_load_kwh / 365.0 * autonomy_class * rng.uniform(0.92, 1.08),
        )
    capacity_scores = np.abs(np.log(capacities / target_capacity)) + rng.uniform(0.0, 0.045, len(capacities))
    capacity = float(capacities[int(np.argmin(capacity_scores))])
    target_power = min(capacity * rng.uniform(0.36, 0.55), max(pv_capacity_kw, capacity * 0.30))
    valid_powers = powers[powers <= capacity * 0.65 + 1.0e-9]
    power = float(valid_powers[int(np.argmin(np.abs(valid_powers - target_power)))])
    return {
        "battery_capacity_kwh": capacity,
        "battery_nominal_power_kw": power,
        "battery_efficiency": round(float(rng.uniform(0.92, 0.965)), 3),
        "battery_initial_soc": round(float(rng.uniform(0.25, 0.60)), 3),
        "battery_depth_of_discharge": round(float(rng.choice([0.80, 0.85, 0.90, 0.95])), 2),
        "battery_loss_coefficient": round(float(rng.uniform(0.0005, 0.0015)), 5),
        "battery_capacity_loss_coefficient": round(float(rng.uniform(0.5e-5, 1.5e-5)), 7),
        "battery_sizing_method": "product_class_nearest_to_stratified_daily_load_autonomy_with_host_pv_floor",
    }


def _round_quarter_minutes(value: float) -> int:
    return int(np.clip(round(value / 15.0) * 15, 0, 24 * 60 - 15))


def _local_at(day: pd.Timestamp, minute_of_day: int, day_offset: int = 0) -> pd.Timestamp:
    """Construct a civil-time instant without elapsed-time DST drift.

    Adding a duration to a timezone-aware midnight shifts an intended wall
    clock routine by one hour after either Lisbon DST transition.  Build the
    naive local clock first and localize it instead.  The missing spring hour
    is moved forward by exactly one hour while the first occurrence of the
    repeated autumn hour is selected deterministically.
    """

    target_day = day.date() + timedelta(days=day_offset)
    local_clock = pd.Timestamp(target_day) + pd.Timedelta(
        minutes=int(minute_of_day)
    )
    return local_clock.tz_localize(
        TIMEZONE,
        ambiguous=True,
        nonexistent=pd.Timedelta(hours=1),
    )


def _session_windows(
    category: str,
    routine_archetype: str,
    rng: np.random.Generator,
) -> Iterable[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Yield reproducible but non-synchronised mobility windows.

    The distributions are scenario assumptions, not an empirical travel survey.
    Quarter-hour rounding preserves the dataset clock while member-, charger- and
    day-level draws avoid the former all-at-once arrivals.
    """

    days = pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31", freq="1D", tz=TIMEZONE)
    for day in days:
        windows: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
        if category == "residential":
            mobility = {
                "early_commuter": (17.25, 6.35, 0.88, 0.64, 52.0),
                "standard_commuter": (18.75, 7.50, 0.84, 0.66, 68.0),
                "late_commuter": (21.05, 9.35, 0.77, 0.61, 76.0),
                "home_worker": (16.45, 9.10, 0.58, 0.52, 88.0),
                "home_day": (15.25, 10.15, 0.50, 0.47, 96.0),
            }[routine_archetype]
            base_arrival, base_departure, weekday_probability, weekend_probability, spread = mobility
            is_weekend = day.dayofweek >= 5
            visit_probability = weekend_probability if is_weekend else weekday_probability
            if rng.random() <= visit_probability:
                arrival_minutes = _round_quarter_minutes(
                    np.clip(
                        rng.normal((base_arrival + (0.75 if is_weekend else 0.0)) * 60.0, spread),
                        12.0 * 60.0,
                        23.5 * 60.0,
                    )
                )
                departure_minutes = _round_quarter_minutes(
                    np.clip(
                        rng.normal((base_departure + (1.0 if is_weekend else 0.0)) * 60.0, spread),
                        4.5 * 60.0,
                        12.5 * 60.0,
                    )
                )
                arrival = _local_at(day, arrival_minutes)
                departure = _local_at(day, departure_minutes, day_offset=1)
                if departure.year == YEAR:
                    windows.append((arrival, departure))
        elif category == "small_service":
            service_patterns = {
                "office_hours": (5, ((8.0, 0.90, (4.0, 8.0)), (13.0, 0.52, (2.5, 5.0)))),
                "retail_six_day": (6, ((10.0, 0.82, (1.0, 3.0)), (14.0, 0.84, (1.0, 3.0)), (18.0, 0.66, (1.0, 2.5)))),
                "clinic_split_day": (5, ((7.75, 0.78, (2.0, 4.0)), (11.25, 0.68, (1.5, 3.0)), (15.25, 0.82, (2.0, 4.0)))),
                "hospitality_extended": (7, ((7.0, 0.68, (2.0, 4.0)), (12.0, 0.76, (1.5, 3.5)), (18.0, 0.86, (2.0, 4.5)))),
                "workshop_early": (6, ((6.5, 0.88, (4.0, 7.0)), (12.5, 0.58, (2.0, 4.0)))),
            }
            active_days, patterns = service_patterns[routine_archetype]
            if day.dayofweek >= active_days:
                patterns = ()
            for base_arrival, probability, duration_range in patterns:
                if rng.random() > probability:
                    continue
                arrival_minutes = _round_quarter_minutes(
                    np.clip(rng.normal(base_arrival * 60.0, 42.0), 5.0 * 60.0, 22.0 * 60.0)
                )
                duration_steps = int(
                    rng.integers(
                        round(duration_range[0] * 4),
                        round(duration_range[1] * 4) + 1,
                    )
                )
                arrival = _local_at(day, arrival_minutes)
                windows.append((arrival, arrival + pd.Timedelta(minutes=15 * duration_steps)))
        elif category == "high_consumption":
            high_patterns = {
                "day_process": (5, ((6.5, 0.90), (11.0, 0.82), (15.5, 0.76))),
                "extended_process": (6, ((5.5, 0.88), (10.5, 0.82), (15.5, 0.82), (20.0, 0.70))),
                "continuous_process": (7, ((2.0, 0.58), (8.0, 0.76), (14.0, 0.76), (20.0, 0.64))),
                "morning_intensive": (6, ((4.5, 0.88), (8.0, 0.86), (12.0, 0.76))),
                "evening_intensive": (6, ((12.0, 0.78), (16.0, 0.86), (20.0, 0.84))),
            }
            active_days, patterns = high_patterns[routine_archetype]
            if day.dayofweek >= active_days:
                patterns = ()
            for base_arrival, probability in patterns:
                if rng.random() > probability:
                    continue
                arrival_minutes = _round_quarter_minutes(
                    np.clip(rng.normal(base_arrival * 60.0, 38.0), 1.0 * 60.0, 23.0 * 60.0)
                )
                duration_steps = int(rng.integers(8, 25))
                arrival = _local_at(day, arrival_minutes)
                windows.append((arrival, arrival + pd.Timedelta(minutes=15 * duration_steps)))

        previous_departure = None
        for arrival, departure in sorted(windows, key=lambda value: value[0]):
            if previous_departure is not None and arrival < previous_departure + pd.Timedelta(minutes=15):
                duration = departure - arrival
                arrival = previous_departure + pd.Timedelta(minutes=15)
                departure = arrival + duration
            if departure <= arrival:
                continue
            previous_departure = departure
            yield arrival, departure


def build_charger_schedule(
    member_index: int,
    charger_number: int,
    category: str,
    routine_archetype: str,
    calendar_frame: pd.DataFrame,
    electrical_contract: Mapping,
) -> Tuple[pd.DataFrame, List[Mapping], List[Mapping], Mapping]:
    charger_id = _charger_id(member_index, charger_number)
    rng = np.random.default_rng(SEED * 100_000 + member_index * 100 + charger_number)
    states = np.full(N_STEPS, 3, dtype="int8")
    ev_ids = np.full(N_STEPS, "", dtype=object)
    session_ids = np.full(N_STEPS, "", dtype=object)
    departure = np.full(N_STEPS, np.nan, dtype="float32")
    required_soc = np.full(N_STEPS, np.nan, dtype="float32")
    estimated_arrival = np.full(N_STEPS, np.nan, dtype="float32")
    arrival_soc = np.full(N_STEPS, np.nan, dtype="float32")
    current_soc_reference = np.full(N_STEPS, np.nan, dtype="float32")
    utc_index = pd.DatetimeIndex(calendar_frame["timestamp_utc"])
    pool_size = 1 if category == "residential" else 4
    charger_spec = electrical_contract["charger_specs"][charger_number - 1]
    max_power = float(charger_spec["max_charging_power_kw"])
    max_discharging_power = float(charger_spec["max_discharging_power_kw"])
    phase_connection = str(charger_spec["phase_connection"])
    ev_catalog = []
    for pool_index in range(pool_size):
        ev_id = f"EV-{charger_id}-{pool_index + 1:02d}"
        capacity = float(rng.choice([40.0, 50.0, 58.0, 64.0, 75.0, 82.0]))
        ev_catalog.append(
            {
                "ev_id": ev_id,
                "home_charger_id": charger_id if category == "residential" else "",
                "vehicle_pool": category,
                "battery_capacity_kwh": capacity,
                "nominal_power_kw": min(50.0, capacity),
                "depth_of_discharge": 0.90,
                "initial_soc": round(float(rng.uniform(0.30, 0.60)), 3),
            }
        )

    sessions = []
    windows = list(_session_windows(category, routine_archetype, rng))
    previous_stop = 0
    for session_number, (arrival_local, departure_local) in enumerate(windows, start=1):
        arrival_utc = arrival_local.tz_convert("UTC")
        departure_utc = departure_local.tz_convert("UTC")
        start = int(utc_index.searchsorted(arrival_utc))
        stop = int(utc_index.searchsorted(departure_utc))
        if start < previous_stop:
            shift_steps = previous_stop - start
            start += shift_steps
            stop += shift_steps
        if start < 0 or stop > N_STEPS or stop <= start:
            continue
        arrival_utc = utc_index[start]
        departure_utc = utc_index[0] + pd.Timedelta(minutes=15 * stop)
        ev = ev_catalog[(session_number - 1) % pool_size]
        session_id = f"SES-{charger_id}-{session_number:04d}"
        duration_hours = (stop - start) * 0.25
        if category == "residential":
            mobility_energy_factor = {
                "early_commuter": 1.12,
                "standard_commuter": 1.00,
                "late_commuter": 0.92,
                "home_worker": 0.74,
                "home_day": 0.66,
            }[routine_archetype]
            sampled_energy = float(rng.lognormal(mean=np.log(6.0 * mobility_energy_factor), sigma=0.52))
        elif category == "small_service":
            sampled_energy = float(rng.lognormal(mean=np.log(9.0), sigma=0.48))
        else:
            sampled_energy = float(rng.lognormal(mean=np.log(15.0), sigma=0.48))
        maximum_deliverable = duration_hours * max_power * 0.95
        deliverable_fraction_cap = 0.85 if category == "residential" else 0.72
        required_energy = min(
            sampled_energy,
            maximum_deliverable * deliverable_fraction_cap,
            ev["battery_capacity_kwh"] * 0.72,
        )
        minimum_target = max(0.72, 0.10 + required_energy / ev["battery_capacity_kwh"])
        target = round(float(rng.uniform(minimum_target, 0.95)), 3)
        estimated_soc = round(
            float(target - required_energy / ev["battery_capacity_kwh"]), 3
        )
        required_energy = (target - estimated_soc) * ev["battery_capacity_kwh"]
        minimum_full_power_steps = int(math.ceil(
            required_energy / max(max_power * 0.95 * 0.25, 1.0e-9)
        ))
        temporal_slack_steps = (stop - start) - minimum_full_power_steps
        states[start:stop] = 1
        ev_ids[start:stop] = ev["ev_id"]
        session_ids[start:stop] = session_id
        departure[start:stop] = np.arange(stop - start, 0, -1, dtype="float32")
        required_soc[start:stop] = target
        # Boundary-initialization reference used only when an episode begins in
        # the middle of an already occupied charger window.  It is causal with
        # respect to the declared session contract and represents a neutral,
        # constant-rate service trajectory from arrival SOC to target SOC.  A
        # normal full-year rollout still initializes from the declared arrival
        # SOC and evolves according to the controller's actions.
        current_soc_reference[start:stop] = np.linspace(
            estimated_soc,
            target,
            stop - start,
            endpoint=False,
            dtype="float32",
        )
        # Incoming telemetry must never overwrite the occupied interval of the
        # preceding EV session on the same physical charger.
        incoming_start = max(previous_stop, start - 8, 0)
        states[incoming_start:start] = 2
        ev_ids[incoming_start:start] = ev["ev_id"]
        session_ids[incoming_start:start] = session_id
        estimated_arrival[incoming_start:start] = np.arange(start - incoming_start, 0, -1, dtype="float32")
        arrival_soc[incoming_start:start] = estimated_soc
        sessions.append(
            {
                "session_id": session_id,
                "member_id": _member_id(member_index),
                "charger_id": charger_id,
                "ev_id": ev["ev_id"],
                "routine_archetype": routine_archetype,
                "arrival_time_step": start,
                "departure_time_step": stop,
                "arrival_timestamp_utc": arrival_utc.isoformat(),
                "departure_timestamp_utc": departure_utc.isoformat(),
                "arrival_soc": estimated_soc,
                "required_departure_soc": target,
                "required_energy_kwh": round(float(required_energy), 4),
                "individual_charger_deliverable_energy_kwh": round(float(maximum_deliverable), 4),
                "individual_charger_slack_kwh": round(float(maximum_deliverable - required_energy), 4),
                "deliverable_fraction_cap": deliverable_fraction_cap,
                "minimum_full_power_steps": minimum_full_power_steps,
                "temporal_slack_steps": temporal_slack_steps,
                "connection_duration_hours": round(float(duration_hours), 3),
                "individual_charger_feasible": bool(required_energy <= maximum_deliverable + 1.0e-9),
                "deadline_time_step": stop,
                "must_serve": True,
            }
        )
        previous_stop = stop

    schedule = pd.DataFrame(
        {
            "electric_vehicle_charger_state": states,
            "electric_vehicle_id": ev_ids,
            "electric_vehicle_session_id": session_ids,
            "electric_vehicle_departure_time": departure,
            "electric_vehicle_required_soc_departure": required_soc,
            "electric_vehicle_estimated_arrival_time": estimated_arrival,
            "electric_vehicle_estimated_soc_arrival": arrival_soc,
            "electric_vehicle_current_soc": current_soc_reference,
        }
    )
    metadata = {
        "charger_id": charger_id,
        "member_id": _member_id(member_index),
        "physical_charger_number_at_member": charger_number,
        "charger_class": "residential" if category == "residential" else "shared_service",
        "routine_archetype": routine_archetype,
        "max_charging_power_kw": max_power,
        "max_discharging_power_kw": max_discharging_power,
        "phase_connection": phase_connection,
        "annual_session_count": len(sessions),
        "vehicle_pool_size": pool_size,
    }
    return schedule, sessions, ev_catalog, metadata


def build_deferrable(
    member_index: int,
    category: str,
    routine_archetype: str,
    calendar_frame: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, Mapping]:
    appliance_id = f"DEF-M{member_index:03d}-01"
    rng = np.random.default_rng(SEED * 1_000_000 + member_index)
    if category == "residential":
        residential_profiles = {
            "early_commuter": ("washing_machine", ([0.16, 0.31, 0.28, 0.16], [0.12, 0.22, 0.31, 0.28, 0.16, 0.10])),
            "standard_commuter": ("dishwasher", ([0.12, 0.24, 0.31, 0.22, 0.12], [0.10, 0.18, 0.26, 0.29, 0.20, 0.12])),
            "late_commuter": ("washer_dryer", ([0.18, 0.34, 0.31, 0.20, 0.14], [0.13, 0.23, 0.34, 0.31, 0.22, 0.14, 0.09])),
            "home_worker": ("domestic_hot_water_cycle", ([0.24, 0.31, 0.31, 0.24], [0.15, 0.24, 0.30, 0.30, 0.24, 0.15])),
            "home_day": ("dishwasher_or_laundry", ([0.14, 0.27, 0.32, 0.24, 0.13], [0.11, 0.20, 0.28, 0.30, 0.22, 0.13])),
        }
        appliance_type, profile_values = residential_profiles[routine_archetype]
    elif category == "small_service":
        service_profiles = {
            "office_hours": ("cleaning_or_preconditioning", ([0.45] * 8, [0.30, 0.45, 0.60, 0.60, 0.45, 0.30])),
            "retail_six_day": ("cold_storage_or_cleaning", ([0.65] * 8, [0.40, 0.65, 0.85, 0.85, 0.65, 0.40])),
            "clinic_split_day": ("sterilisation_or_laundry", ([0.55] * 6, [0.35, 0.55, 0.75, 0.75, 0.55, 0.35])),
            "hospitality_extended": ("dishwashing_or_hot_water", ([0.85] * 8, [0.50, 0.80, 1.05, 1.05, 0.80, 0.50])),
            "workshop_early": ("compressor_or_pumping", ([0.75] * 10, [0.45, 0.70, 0.95, 0.95, 0.70, 0.45])),
        }
        appliance_type, profile_values = service_profiles[routine_archetype]
    else:
        high_profiles = {
            "day_process": ("batch_process", ([2.2] * 12, [1.3, 1.8, 2.7, 2.7, 1.8, 1.3] * 2)),
            "extended_process": ("process_auxiliaries", ([2.5] * 12, [1.5, 2.1, 3.0, 3.0, 2.1, 1.5] * 2)),
            "continuous_process": ("maintenance_or_pumping", ([1.8] * 16, [1.2, 1.6, 2.2, 2.2, 1.6, 1.2] * 2)),
            "morning_intensive": ("thermal_preparation", ([2.8] * 10, [1.6, 2.3, 3.3, 3.3, 2.3, 1.6] * 2)),
            "evening_intensive": ("late_batch_process", ([2.4] * 14, [1.4, 2.0, 2.9, 2.9, 2.0, 1.4] * 2)),
        }
        appliance_type, profile_values = high_profiles[routine_archetype]
    profile_scale = float(rng.uniform(0.82, 1.22))
    profiles = []
    for number, values in enumerate(profile_values, start=1):
        values = [round(float(v) * profile_scale, 4) for v in values]
        profiles.append(
            {
                "profile_id": f"{appliance_id}-P{number:02d}",
                "duration_steps": len(values),
                "total_energy_kwh": round(float(sum(values)), 4),
                "load_profile": json.dumps(values, separators=(",", ":")),
            }
        )
    profile_frame = pd.DataFrame(profiles)

    utc = pd.DatetimeIndex(calendar_frame["timestamp_utc"])
    schedule = []
    previous_deadline = -1
    days = pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31", freq="1D", tz=TIMEZONE)
    for cycle_number, day in enumerate(days, start=1):
        if category == "residential":
            residential_windows = {
                "early_commuter": (0.56, (17.0, 20.5), (12, 29), 0.72),
                "standard_commuter": (0.64, (18.0, 21.5), (12, 33), 0.70),
                "late_commuter": (0.52, (20.0, 23.0), (8, 25), 0.66),
                "home_worker": (0.68, (9.0, 15.0), (16, 37), 0.74),
                "home_day": (0.70, (10.0, 17.0), (12, 33), 0.76),
            }
            occurrence_probability, earliest_range, window_range, must_run_probability = residential_windows[routine_archetype]
            if rng.random() > occurrence_probability:
                continue
            earliest_minute = _round_quarter_minutes(rng.uniform(*[v * 60.0 for v in earliest_range]))
            window_steps = int(rng.integers(window_range[0], window_range[1]))
        elif category == "small_service":
            service_windows = {
                "office_hours": (5, 0.84, (15.0, 19.0), (8, 25), 0.90),
                "retail_six_day": (6, 0.88, (18.5, 22.0), (8, 29), 0.88),
                "clinic_split_day": (5, 0.82, (12.0, 17.0), (8, 25), 0.92),
                "hospitality_extended": (7, 0.90, (9.0, 18.0), (8, 33), 0.90),
                "workshop_early": (6, 0.86, (6.0, 12.0), (8, 29), 0.94),
            }
            active_days, occurrence_probability, earliest_range, window_range, must_run_probability = service_windows[routine_archetype]
            if day.dayofweek >= active_days or rng.random() > occurrence_probability:
                continue
            earliest_minute = _round_quarter_minutes(rng.uniform(*[v * 60.0 for v in earliest_range]))
            window_steps = int(rng.integers(window_range[0], window_range[1]))
        else:
            high_windows = {
                "day_process": (5, 0.90, (5.0, 10.0), (8, 33), 0.95),
                "extended_process": (6, 0.92, (4.0, 12.0), (8, 37), 0.94),
                "continuous_process": (7, 0.94, (0.5, 18.0), (12, 41), 0.97),
                "morning_intensive": (6, 0.90, (3.0, 8.0), (8, 29), 0.95),
                "evening_intensive": (6, 0.90, (11.0, 18.0), (8, 33), 0.95),
            }
            active_days, occurrence_probability, earliest_range, window_range, must_run_probability = high_windows[routine_archetype]
            if day.dayofweek >= active_days or rng.random() > occurrence_probability:
                continue
            earliest_minute = _round_quarter_minutes(rng.uniform(*[v * 60.0 for v in earliest_range]))
            window_steps = int(rng.integers(window_range[0], window_range[1]))

        profile = profiles[(cycle_number - 1) % len(profiles)]
        duration_steps = int(profile["duration_steps"])
        earliest_local = _local_at(day, earliest_minute)
        latest_local = earliest_local + pd.Timedelta(minutes=15 * window_steps)
        completion_margin_steps = int(rng.integers(2, 17))
        deadline_local = latest_local + pd.Timedelta(
            minutes=15 * (duration_steps - 1 + completion_margin_steps)
        )
        if deadline_local.year != YEAR:
            continue
        earliest = int(utc.searchsorted(earliest_local.tz_convert("UTC")))
        latest = int(utc.searchsorted(latest_local.tz_convert("UTC")))
        deadline = min(int(utc.searchsorted(deadline_local.tz_convert("UTC"))), N_STEPS - 1)
        latest = min(latest, deadline - duration_steps + 1)
        if earliest > latest or earliest <= previous_deadline:
            continue
        schedule.append(
            {
                "cycle_id": f"{appliance_id}-C{cycle_number:04d}",
                "profile_id": profile["profile_id"],
                "earliest_start_time_step": earliest,
                "latest_start_time_step": latest,
                "deadline_time_step": deadline,
                "priority": round(float(rng.choice([0.5, 0.75, 1.0])), 2),
                "must_run": bool(rng.random() < must_run_probability),
            }
        )
        previous_deadline = deadline
    schedule_frame = pd.DataFrame(schedule)
    metadata = {
        "deferrable_id": appliance_id,
        "member_id": _member_id(member_index),
        "appliance_type": appliance_type,
        "routine_archetype": routine_archetype,
        "profile_scale": round(profile_scale, 4),
        "profile_count": len(profile_frame),
        "annual_cycle_count": len(schedule_frame),
        "minimum_profile_energy_kwh": float(profile_frame["total_energy_kwh"].min()),
        "maximum_profile_energy_kwh": float(profile_frame["total_energy_kwh"].max()),
        "kpis": ["completion", "delay", "unserved_energy_kwh"],
    }
    return profile_frame, schedule_frame, metadata


def _rotated_phase(member_index: int, offset: int = 0) -> str:
    return ("L1", "L2", "L3")[(member_index - 1 + offset) % 3]


def build_electrical_contract(
    member_index: int,
    category: str,
    charger_count: int,
    pv_capacity_kw: float,
    battery_nominal_power_kw: float,
    peak_native_import_kw: float,
    peak_native_export_kw: float,
    residential_charger_phase_offset: int = None,
) -> Mapping:
    """Return an active-power surrogate of a Portuguese connection contract.

    Contracted-power levels follow the normalized Portuguese BTN levels and
    representative BTE values.  CityLearn does not model reactive power, so
    kVA is mapped to an equal numerical kW ceiling under an explicit unity
    power-factor assumption.
    """

    charger_specs = []
    if category == "residential":
        if charger_count >= 2:
            connection_type = "three_phase"
            contracted_kva = 17.25 if member_index % 2 else 20.70
            default_split = "balanced"
            asset_phase_connection = "all_phases"
            for charger_number in range(1, charger_count + 1):
                charger_specs.append(
                    {
                        "phase_connection": _rotated_phase(
                            1 + int(residential_charger_phase_offset or 0),
                            charger_number - 1,
                        ),
                        "max_charging_power_kw": 7.4,
                        "max_discharging_power_kw": 0.0,
                    }
                )
        elif charger_count == 1 and member_index % 5 == 0:
            connection_type = "three_phase"
            contracted_kva = 13.80 if member_index % 2 else 17.25
            default_split = "balanced"
            asset_phase_connection = "all_phases"
            charger_specs.append(
                {
                    "phase_connection": "all_phases",
                    "max_charging_power_kw": 11.0,
                    "max_discharging_power_kw": 0.0,
                }
            )
        else:
            connection_type = "single_phase"
            contracted_kva = 6.90 if member_index % 2 else 10.35
            default_split = (
                _rotated_phase(1 + int(residential_charger_phase_offset))
                if charger_count and residential_charger_phase_offset is not None
                else _rotated_phase(member_index)
            )
            asset_phase_connection = default_split
            if charger_count:
                charger_specs.append(
                    {
                        "phase_connection": default_split,
                        "max_charging_power_kw": 3.7 if contracted_kva <= 6.90 else 7.4,
                        "max_discharging_power_kw": 0.0,
                    }
                )
            elif member_index % 7 == 0:
                connection_type = "three_phase"
                contracted_kva = 10.35 if member_index % 2 else 13.80
                default_split = "balanced"
                asset_phase_connection = "all_phases"
            else:
                contracted_kva = (3.45, 4.60, 5.75, 6.90)[(member_index - 1) % 4]
    elif category == "small_service":
        connection_type = "three_phase"
        contracted_kva = (20.70, 27.60, 34.50, 41.40)[(member_index - 1) % 4]
        if charger_count >= 2:
            contracted_kva = max(contracted_kva, 34.50)
        default_split = "balanced"
        asset_phase_connection = "all_phases"
        charger_specs = [
            {
                "phase_connection": "all_phases",
                "max_charging_power_kw": 11.0,
                "max_discharging_power_kw": 5.5,
            }
            for _ in range(charger_count)
        ]
    else:
        connection_type = "three_phase"
        contracted_kva = (69.0, 103.5, 138.0)[(member_index - 1) % 3]
        default_split = "balanced"
        asset_phase_connection = "all_phases"
        charger_specs = [
            {
                "phase_connection": "all_phases",
                "max_charging_power_kw": 22.0,
                "max_discharging_power_kw": 11.0,
            }
            for _ in range(charger_count)
        ]

    original_contracted_kva = float(contracted_kva)
    minimum_native_envelope_kw = 1.02 * max(
        float(peak_native_import_kw),
        float(peak_native_export_kw),
    )
    if category == "residential":
        candidate_levels = (3.45, 4.60, 5.75, 6.90, 10.35, 13.80, 17.25, 20.70)
    elif category == "small_service":
        candidate_levels = (20.70, 27.60, 34.50, 41.40, 69.0)
    else:
        candidate_levels = (69.0, 103.5, 138.0, 207.0)
    contracted_kva = next(
        (
            level
            for level in candidate_levels
            if level + 1.0e-9
            >= max(original_contracted_kva, minimum_native_envelope_kw)
        ),
        candidate_levels[-1],
    )

    total_import_kw = round(float(contracted_kva), 3)
    total_export_kw = round(
        min(
            total_import_kw,
            max(
                max(float(pv_capacity_kw), 0.0)
                + max(float(battery_nominal_power_kw), 0.0),
                1.02 * float(peak_native_export_kw),
            ),
        ),
        3,
    )
    if connection_type == "single_phase":
        per_phase_import = {
            phase: (total_import_kw if phase == default_split else 0.0)
            for phase in ("L1", "L2", "L3")
        }
        per_phase_export = {
            phase: (total_export_kw if phase == default_split else 0.0)
            for phase in ("L1", "L2", "L3")
        }
    else:
        per_phase_import = {
            phase: round(total_import_kw / 3.0, 3) for phase in ("L1", "L2", "L3")
        }
        per_phase_export = {
            phase: round(total_export_kw / 3.0, 3) for phase in ("L1", "L2", "L3")
        }

    return {
        "member_id": _member_id(member_index),
        "connection_type": connection_type,
        "simulator_mode": "three_phase",
        "default_split": default_split,
        "asset_phase_connection": asset_phase_connection,
        "contracted_power_kva": round(float(contracted_kva), 3),
        "original_sampled_contracted_power_kva": round(original_contracted_kva, 3),
        "native_peak_import_kw": round(float(peak_native_import_kw), 4),
        "native_peak_export_kw": round(float(peak_native_export_kw), 4),
        "native_feasibility_margin": 0.02,
        "contract_level_upgraded_for_native_feasibility": bool(
            contracted_kva > original_contracted_kva + 1.0e-9
        ),
        "active_power_factor_assumption": 1.0,
        "total_import_limit_kw": total_import_kw,
        "total_export_limit_kw": total_export_kw,
        "per_phase_import_limits_kw": per_phase_import,
        "per_phase_export_limits_kw": per_phase_export,
        "charger_specs": charger_specs,
        "source_class": "Portuguese BTN/BTE connection-level surrogate",
    }


def _electrical_service(contract: Mapping) -> Mapping:
    return {
        "mode": contract["simulator_mode"],
        "default_split": contract["default_split"],
        "connection_type": contract["connection_type"],
        "contracted_power_kva": contract["contracted_power_kva"],
        "original_sampled_contracted_power_kva": contract[
            "original_sampled_contracted_power_kva"
        ],
        "native_peak_import_kw": contract["native_peak_import_kw"],
        "native_peak_export_kw": contract["native_peak_export_kw"],
        "native_feasibility_margin": contract["native_feasibility_margin"],
        "contract_level_upgraded_for_native_feasibility": contract[
            "contract_level_upgraded_for_native_feasibility"
        ],
        "active_power_factor_assumption": contract["active_power_factor_assumption"],
        "limits": {
            "total": {
                "import_kw": contract["total_import_limit_kw"],
                "export_kw": contract["total_export_limit_kw"],
            },
            "per_phase": {
                phase: {
                    "import_kw": contract["per_phase_import_limits_kw"][phase],
                    "export_kw": contract["per_phase_export_limits_kw"][phase],
                }
                for phase in ("L1", "L2", "L3")
            },
        },
        "observations": {
            "headroom": True,
            "headroom_export": True,
            "violation": True,
            "phase_encoding": True,
        },
    }


def _core_topology_events() -> List[Mapping]:
    return [
        {"id": "core_add_member_016", "time_step": 3000, "operation": "add_member", "target_member_id": _member_id(16)},
        {"id": "core_remove_charger_m006_02", "time_step": 6000, "operation": "remove_asset", "target_member_id": _member_id(6), "target_asset_type": "charger", "target_asset_id": _charger_id(6, 2)},
        {"id": "core_reinstall_charger_m006_02", "time_step": 9000, "operation": "add_asset", "target_member_id": _member_id(6), "target_asset_type": "charger", "target_asset_id": _charger_id(6, 2), "source_member_id": _member_id(6), "source_asset_id": _charger_id(6, 2)},
        {"id": "core_remove_storage_m003", "time_step": 14000, "operation": "remove_asset", "target_member_id": _member_id(3), "target_asset_type": "electrical_storage", "target_asset_id": "electrical_storage"},
        {"id": "core_restore_storage_m003", "time_step": 15000, "operation": "add_asset", "target_member_id": _member_id(3), "target_asset_type": "electrical_storage", "target_asset_id": "electrical_storage", "source_member_id": _member_id(3), "source_asset_id": "electrical_storage"},
        {"id": "core_add_member_027", "time_step": 16000, "operation": "add_member", "target_member_id": _member_id(27)},
        {"id": "core_remove_deferrable_m017", "time_step": 22000, "operation": "remove_asset", "target_member_id": _member_id(17), "target_asset_type": "deferrable_appliance", "target_asset_id": "DEF-M017-01"},
        {"id": "core_restore_deferrable_m017", "time_step": 23000, "operation": "add_asset", "target_member_id": _member_id(17), "target_asset_type": "deferrable_appliance", "target_asset_id": "DEF-M017-01", "source_member_id": _member_id(17), "source_asset_id": "DEF-M017-01"},
        {"id": "core_add_member_029", "time_step": 24000, "operation": "add_member", "target_member_id": _member_id(29)},
        {"id": "core_remove_pv_m018", "time_step": 26000, "operation": "remove_asset", "target_member_id": _member_id(18), "target_asset_type": "pv", "target_asset_id": "pv"},
        {"id": "core_restore_pv_m018", "time_step": 27000, "operation": "add_asset", "target_member_id": _member_id(18), "target_asset_type": "pv", "target_asset_id": "pv", "source_member_id": _member_id(18), "source_asset_id": "pv"},
        {"id": "core_add_member_030", "time_step": 28000, "operation": "add_member", "target_member_id": _member_id(30)},
        {"id": "core_remove_member_019", "time_step": 30000, "operation": "remove_member", "target_member_id": _member_id(19)},
        {"id": "core_remove_member_008", "time_step": 33000, "operation": "remove_member", "target_member_id": _member_id(8)},
    ]


def _premium_topology_events() -> List[Mapping]:
    events: List[Mapping] = []
    for step, members in (
        (2880, range(61, 66)),
        (5760, range(81, 86)),
        (8640, range(91, 94)),
        (14400, range(66, 71)),
        (17280, range(86, 91)),
        (20160, range(94, 97)),
        (23040, range(97, 101)),
    ):
        for member in members:
            events.append({"id": f"premium_add_member_{member:03d}", "time_step": step, "operation": "add_member", "target_member_id": _member_id(member)})
    # Permanent late-year departures avoid conflating re-entry with a reset of
    # the participant's accumulated physical and service state.  The active
    # population first reaches all 100 members and then contracts to 94.
    for step, members in ((25920, (5, 6, 72)), (31680, (20, 21, 22))):
        for member in members:
            events.append({"id": f"premium_remove_member_{member:03d}_{step}", "time_step": step, "operation": "remove_member", "target_member_id": _member_id(member)})
    events.extend(
        [
            {"id": "premium_remove_charger_m025_02", "time_step": 10000, "operation": "remove_asset", "target_member_id": _member_id(25), "target_asset_type": "charger", "target_asset_id": _charger_id(25, 2)},
            {"id": "premium_reinstall_charger_m025_02", "time_step": 11000, "operation": "add_asset", "target_member_id": _member_id(25), "target_asset_type": "charger", "target_asset_id": _charger_id(25, 2), "source_member_id": _member_id(25), "source_asset_id": _charger_id(25, 2)},
            {"id": "premium_remove_charger_m071_02", "time_step": 21000, "operation": "remove_asset", "target_member_id": _member_id(71), "target_asset_type": "charger", "target_asset_id": _charger_id(71, 2)},
            {"id": "premium_reinstall_charger_m071_02", "time_step": 22000, "operation": "add_asset", "target_member_id": _member_id(71), "target_asset_type": "charger", "target_asset_id": _charger_id(71, 2), "source_member_id": _member_id(71), "source_asset_id": _charger_id(71, 2)},
            {"id": "premium_remove_pv_m012", "time_step": 18000, "operation": "remove_asset", "target_member_id": _member_id(12), "target_asset_type": "pv", "target_asset_id": "pv"},
            {"id": "premium_restore_pv_m012", "time_step": 19000, "operation": "add_asset", "target_member_id": _member_id(12), "target_asset_type": "pv", "target_asset_id": "pv", "source_member_id": _member_id(12), "source_asset_id": "pv"},
            {"id": "premium_remove_storage_m001", "time_step": 20000, "operation": "remove_asset", "target_member_id": _member_id(1), "target_asset_type": "electrical_storage", "target_asset_id": "electrical_storage"},
            {"id": "premium_restore_storage_m001", "time_step": 20500, "operation": "add_asset", "target_member_id": _member_id(1), "target_asset_type": "electrical_storage", "target_asset_id": "electrical_storage", "source_member_id": _member_id(1), "source_asset_id": "electrical_storage"},
            {"id": "premium_remove_deferrable_m073", "time_step": 24000, "operation": "remove_asset", "target_member_id": _member_id(73), "target_asset_type": "deferrable_appliance", "target_asset_id": "DEF-M073-01"},
            {"id": "premium_restore_deferrable_m073", "time_step": 25000, "operation": "add_asset", "target_member_id": _member_id(73), "target_asset_type": "deferrable_appliance", "target_asset_id": "DEF-M073-01", "source_member_id": _member_id(73), "source_asset_id": "DEF-M073-01"},
        ]
    )
    return sorted(events, key=lambda event: (event["time_step"], event["id"]))


def _robustness_events(family: str) -> pd.DataFrame:
    unavailable_member = 6 if family == "core30" else 25
    unavailable_charger = 2
    common = [
        {"event_id": "obs_missing_member_004", "module": "observation", "target_type": "building", "target_id": _member_id(4), "target_feature": "non_shiftable_load", "start_time_step": 7600, "end_time_step": 7631, "mode": "missing", "replacement_value": -9999.0},
        {"event_id": "forecast_price_bias", "module": "forecast", "target_type": "district", "target_id": "*", "target_feature": "electricity_pricing_predicted_1", "start_time_step": 15100, "end_time_step": 15195, "mode": "bias", "value": 0.025},
        {"event_id": "storage_action_delay", "module": "action", "target_type": "storage", "target_id": "*", "target_feature": "electrical_storage", "start_time_step": 20100, "end_time_step": 20147, "mode": "delay", "delay_steps": 4},
        {"event_id": "charger_unavailable", "module": "asset", "target_type": "charger", "target_id": f"{_member_id(unavailable_member)}/{_charger_id(unavailable_member, unavailable_charger)}", "target_feature": "both", "start_time_step": 27000, "end_time_step": 27047, "mode": "unavailable", "replacement_value": -9999.0},
    ]
    if family == "premium":
        common.extend(
            [
                {"event_id": "coincident_pv_telemetry_loss", "module": "observation", "target_type": "pv", "target_id": "*", "target_feature": "generation_energy_kwh_step", "start_time_step": 27016, "end_time_step": 27031, "mode": "missing", "replacement_value": -9999.0},
                {"event_id": "coincident_charger_dropout", "module": "action", "target_type": "charger", "target_id": "*", "target_feature": "electric_vehicle_storage", "start_time_step": 27016, "end_time_step": 27031, "mode": "dropout"},
                {"event_id": "service_charger_outage", "module": "asset", "target_type": "charger", "target_id": f"{_member_id(71)}/{_charger_id(71, 1)}", "target_feature": "both", "start_time_step": 27008, "end_time_step": 27047, "mode": "unavailable", "replacement_value": -9999.0},
                {"event_id": "stationary_storage_outage", "module": "asset", "target_type": "storage", "target_id": f"{_member_id(1)}/electrical_storage", "target_feature": "both", "start_time_step": 27016, "end_time_step": 27047, "mode": "unavailable", "replacement_value": -9999.0},
            ]
        )
    columns = [
        "event_id", "module", "target_type", "target_id", "target_feature",
        "start_time_step", "end_time_step", "mode", "value", "std",
        "min_value", "max_value", "replacement_value", "delay_steps",
    ]
    return pd.DataFrame(common).reindex(columns=columns)


def _dr_requests(family: str) -> pd.DataFrame:
    scale = 1.0 if family == "core30" else 3.0
    rows = [
        ("dr_winter_evening_down", "dso", "down", 2500, 2515, 18.0 * scale, 0.35, 1.20, 1.0),
        ("dr_spring_midday_up", "tso", "up", 12500, 12511, 12.0 * scale, 0.24, 0.80, 0.5),
        ("dr_summer_evening_down", "dso", "down", 22500, 22523, 24.0 * scale, 0.42, 1.50, 1.0),
        ("dr_winter_stress_down", "dso", "down", 27016, 27031, 30.0 * scale, 0.55, 1.80, 1.5),
    ]
    return pd.DataFrame(rows, columns=[
        "request_id", "issuer", "direction", "start_time_step", "end_time_step",
        "target_power_kw", "activation_price_eur_per_kwh",
        "shortfall_penalty_eur_per_kwh", "tolerance_power_kw",
    ])


def _variant_flags(variant: str) -> Mapping[str, bool]:
    return {
        "safety": variant in {"CORE-30-SAFETY", "CORE-30-COMBINED", "PREMIUM-100-CLEAN", "PREMIUM-100-ALLIN"},
        "health": variant in {"CORE-30-HEALTH", "CORE-30-COMBINED", "PREMIUM-100-ALLIN"},
        "dynamic": variant in {"CORE-30-DYNAMIC", "CORE-30-COMBINED", "PREMIUM-100-CLEAN", "PREMIUM-100-ALLIN"},
        "dr": variant in {"CORE-30-COMBINED", "PREMIUM-100-CLEAN", "PREMIUM-100-ALLIN"},
        "grid_outage": variant == "PREMIUM-100-ALLIN",
    }


def build_schema(
    config: FamilyConfig,
    variant: str,
    members: Sequence[Mapping],
    chargers: Sequence[Mapping],
    evs: Sequence[Mapping],
    deferrables: Sequence[Mapping],
    electrical_contracts: Mapping[str, Mapping],
) -> Mapping:
    flags = _variant_flags(variant)
    initial_inactive = set()
    if flags["dynamic"] and config.key == "core30":
        initial_inactive = {_member_id(i) for i in (16, 27, 29, 30)}
    elif flags["dynamic"] and config.key == "premium":
        initial_inactive = {
            *(_member_id(i) for i in range(61, 71)),
            *(_member_id(i) for i in range(81, 101)),
        }

    chargers_by_member: Dict[str, List[Mapping]] = {}
    for charger in chargers:
        chargers_by_member.setdefault(charger["member_id"], []).append(charger)
    deferrable_by_member = {item["member_id"]: item for item in deferrables}
    member_by_id = {item["member_id"]: item for item in members}

    buildings = {}
    for member in members:
        member_id = member["member_id"]
        member_index = int(member["member_index"])
        electrical_contract = electrical_contracts[member_id]
        building = {
            "include": member_id not in initial_inactive,
            "type": "citylearn.building.Building",
            "energy_simulation": f"timeseries/{member_id}.parquet",
            "weather": "shared/weather.parquet",
            "carbon_intensity": "shared/carbon_intensity.parquet",
            "pricing": "shared/pricing_omie_2023.parquet",
            "inactive_observations": [],
            "inactive_actions": [] if member["has_battery"] else ["electrical_storage"],
            "equity_group": member["equity_group"],
        }
        if member["has_pv"]:
            building["pv"] = {
                "type": "citylearn.energy_model.PV",
                "autosize": False,
                "attributes": {
                    "nominal_power": member["pv_capacity_kw"],
                    "generation_mode": "absolute",
                },
            }
        if member["has_battery"]:
            building["electrical_storage"] = {
                "type": "citylearn.energy_model.Battery",
                "autosize": False,
                "attributes": {
                    "capacity": member["battery_capacity_kwh"],
                    "nominal_power": member["battery_nominal_power_kw"],
                    "efficiency": member["battery_efficiency"],
                    "initial_soc": member["battery_initial_soc"],
                    "depth_of_discharge": member["battery_depth_of_discharge"],
                    "loss_coefficient": member["battery_loss_coefficient"],
                    "capacity_loss_coefficient": member["battery_capacity_loss_coefficient"],
                    "phase_connection": electrical_contract["asset_phase_connection"],
                },
            }
        member_chargers = chargers_by_member.get(member_id, [])
        if member_chargers:
            building["chargers"] = {}
            for item in member_chargers:
                building["chargers"][item["charger_id"]] = {
                    "type": "citylearn.electric_vehicle_charger.Charger",
                    "charger_simulation": f"chargers/{item['charger_id']}.parquet",
                    "autosize": False,
                    "noise_std": 0.0,
                    "attributes": {
                        "nominal_power": item["max_charging_power_kw"],
                        "efficiency": 0.95,
                        "charger_type": 1 if item["max_discharging_power_kw"] > 0 else 0,
                        "max_charging_power": item["max_charging_power_kw"],
                        "min_charging_power": 1.4,
                        "max_discharging_power": item["max_discharging_power_kw"],
                        "min_discharging_power": 0.0,
                        "phase_connection": item["phase_connection"],
                    },
                }
        if member_id in deferrable_by_member:
            item = deferrable_by_member[member_id]
            building["deferrable_appliances"] = {
                item["deferrable_id"]: {
                    "type": "citylearn.energy_model.DeferrableAppliance",
                    "autosize": False,
                    "cycle_profiles_file": f"deferrables/{item['deferrable_id']}_profiles.parquet",
                    "flexibility_schedule_file": f"deferrables/{item['deferrable_id']}_schedule.parquet",
                    "attributes": {"trigger_threshold": 0.5},
                }
            }
        if flags["safety"]:
            building["electrical_service"] = _electrical_service(electrical_contract)
        if flags["grid_outage"]:
            building["power_outage"] = {
                "simulate_power_outage": member_index in {4, 25, 71, 91},
                "stochastic_power_outage": False,
            }
        buildings[member_id] = building

    ev_definitions = {}
    for ev in evs:
        ev_definitions[ev["ev_id"]] = {
            "type": "citylearn.electric_vehicle.ElectricVehicle",
            "include": True,
            "battery": {
                "type": "citylearn.energy_model.Battery",
                "autosize": False,
                "attributes": {
                    "capacity": ev["battery_capacity_kwh"],
                    "nominal_power": ev["nominal_power_kw"],
                    "initial_soc": ev["initial_soc"],
                    "depth_of_discharge": ev["depth_of_discharge"],
                    "loss_coefficient": 0.0,
                },
            },
        }

    schema = {
        "dataset_id": variant,
        "dataset_family": config.label,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "random_seed": SEED,
        "root_directory": None,
        "central_agent": False,
        "interface": "entity",
        "simulation_start_time_step": 0,
        "simulation_end_time_step": N_STEPS - 1,
        "episode_time_steps": None,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": SECONDS_PER_TIME_STEP,
        "start_date": f"{YEAR}-01-01",
        "timezone": TIMEZONE,
        "observations": OBSERVATIONS,
        "actions": {
            "cooling_storage": {"active": False},
            "heating_storage": {"active": False},
            "dhw_storage": {"active": False},
            "electrical_storage": {"active": True},
            "electric_vehicle_storage": {"active": True},
            "deferrable_appliance": {"active": True},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "observation_bundles": {
            "entity_core_electrical": True,
            "entity_community_operational": True,
            "entity_forecasts_existing": True,
            "entity_forecasts_derived": True,
            "entity_demand_response": flags["dr"],
            "entity_robustness": flags["health"],
            "entity_action_feedback": True,
            "entity_temporal_derived": True,
        },
        "derived_forecasts": {
            "load_pv_method": "daily_persistence",
            "persistence_period_seconds": 86400,
            "cold_start": "current_step",
            "price_source": "publication_aware_day_ahead_market_input",
            "price_publication_time_local": "13:00",
            "price_unpublished_fallback": "daily_persistence",
            "price_horizon_steps": [4, 24, 96],
        },
        "community_market": community_market_config(member_by_id),
        "electric_vehicles_def": ev_definitions,
        "buildings": buildings,
        "render_file_format": "parquet",
        "export_kpis_on_episode_end": False,
        "physics_invariant_checks": True,
    }
    if flags["dynamic"]:
        schema["topology_mode"] = "dynamic"
        schema["topology_events"] = _core_topology_events() if config.key == "core30" else _premium_topology_events()
    else:
        schema["topology_mode"] = "static"
    if flags["health"]:
        schema["robustness"] = {
            "enabled": True,
            "events_file": "events/robustness_events.parquet",
            "random_seed": SEED,
            "missing_replacement_value": -9999.0,
            "modules": {
                "observations": {"enabled": True},
                "forecasts": {"enabled": True},
                "actions": {"enabled": True},
                "assets": {"enabled": True},
            },
        }
    if flags["dr"]:
        schema["demand_response"] = {
            "enabled": True,
            "requests_file": "events/demand_response_requests.parquet",
            "baseline_method": "rolling_pre_event_average",
            "baseline_window_seconds": 3600,
            "allow_overlapping_requests": False,
        }
    return schema


def _readme(config: FamilyConfig, members: Sequence[Mapping], chargers: Sequence[Mapping], deferrables: Sequence[Mapping]) -> str:
    variants = "\n".join(f"- `{variant}`" for variant in config.variants)
    return f"""# {config.label}

Canonical annual hybrid REC dataset generated by
`scripts/generate_annual_rec_suite.py`.

- Period: 2023-01-01 00:00 UTC to 2023-12-31 23:45 UTC.
- Resolution: 900 seconds; 35,040 steps.
- Local calendar: `{TIMEZONE}` with explicit UTC offset and DST attributes.
- Members: {len(members)}.
- PV assets: {sum(bool(m['has_pv']) for m in members)}.
- Stationary batteries: {sum(bool(m['has_battery']) for m in members)}.
- Charger-equipped members: {len(set(c['member_id'] for c in chargers))}.
- Physical chargers: {len(chargers)}.
- Deferrable appliances: {len(deferrables)}.
- Demand: reproducible category-shaped profiles scaled to annual target
  distributions anchored to 2023 Portuguese per-consumer consumption values;
  stratified routine archetypes alter operating hours, peaks, occupancy and
  reduced-activity days.
- PV and stationary storage: host-specific sizes and parameters; PV sizing is
  coupled to annual demand and BESS sizing uses stratified daily-load autonomy
  classes with a host-PV floor, rather than one common asset size.
- Electrical connections: Portuguese BTN contracted-power levels and
  representative BTE levels, with explicit single-/three-phase allocation.
- Electrical scope: active-power connection surrogate with a declared unity
  power-factor assumption; it is not a feeder power-flow or protection model.
- Prices: official 2023 OMIE Portugal day-ahead hourly prices, repeated over the
  four quarter-hours of each market hour and converted from EUR/MWh to EUR/kWh.
- Settlement: same-step local matching, local price at 80% of OMIE, equal
  importer weights, zero residual export remuneration and grid-only
  counterfactual.

## Variants

{variants}

`schema.json` is the default variant. Other variants are available as
`schemas/*.json`. Physical time series are shared, so scenario twins differ
only in the declared experimental dimension.

The files in `catalogs/` keep member, charger, EV and charging-session
identities separate. A physical charger may therefore host many sessions and
different EVs during the year.

Every ordinary EV session is individually feasible at the declared charger
power and efficiency. Community constraints may still create deliberate
competition between otherwise feasible services in Safety and AllIn variants.
Weather forecasts include reproducible horizon-dependent scenario error.
Derived load/PV forecasts use causal previous-day persistence with a
current-step cold start. Historical OMIE day-ahead forecasts respect the
declared publication boundary and use daily persistence before publication.

`catalogs/electrical_services.parquet` records every member's contracted power,
connection type, phase assignment and total/per-phase import/export limits.
`file_checksums.sha256` freezes every generated data, schema and event file.
"""


def generate_family(
    config: FamilyConfig,
    output_root: Path,
    calendar_frame: pd.DataFrame,
    omie_hourly: pd.DataFrame,
    omie_provenance: pd.DataFrame,
    weather: pd.DataFrame,
    pricing: pd.DataFrame,
    carbon_intensity: pd.DataFrame,
    pv_factor: np.ndarray,
) -> Path:
    output_root = output_root.resolve()
    family_root = (output_root / config.directory).resolve()
    if family_root.parent != output_root or config.directory not in {
        family.directory for family in FAMILIES.values()
    }:
        raise ValueError(f"Refusing to replace unexpected dataset target: {family_root}")
    # Every family is a generated artefact. Replacing the complete directory
    # prevents removed assets from surviving as stale files
    # after a contract or allocation change.
    if family_root.exists():
        shutil.rmtree(family_root)
    for directory in ("shared", "timeseries", "chargers", "deferrables", "catalogs", "events", "schemas", "sources"):
        (family_root / directory).mkdir(parents=True, exist_ok=True)

    calendar_frame.to_parquet(family_root / "shared/calendar.parquet", index=False, compression="zstd")
    weather.to_parquet(family_root / "shared/weather.parquet", index=False, compression="zstd")
    pricing.to_parquet(family_root / "shared/pricing_omie_2023.parquet", index=False, compression="zstd")
    carbon_intensity.to_parquet(family_root / "shared/carbon_intensity.parquet", index=False, compression="zstd")
    omie_hourly.to_parquet(family_root / "sources/omie_2023_hourly.parquet", index=False, compression="zstd")
    omie_provenance.to_csv(family_root / "sources/omie_2023_daily_provenance.csv", index=False)

    members = []
    for member_index, category in enumerate(config.member_categories, start=1):
        frame, metadata = build_member_timeseries(
            member_index,
            category,
            member_index in config.pv_members,
            calendar_frame,
            pv_factor,
        )
        metadata = {
            **metadata,
            "has_pv": member_index in config.pv_members,
            "has_battery": member_index in config.battery_members,
            "has_charging": member_index in config.charger_counts,
            "physical_charger_count": int(config.charger_counts.get(member_index, 0)),
            "has_deferrable": member_index in config.deferrable_members,
        }
        if metadata["has_battery"]:
            metadata = {
                **metadata,
                **build_stationary_battery(
                    member_index,
                    category,
                    float(metadata["pv_capacity_kw"]),
                    float(metadata["annual_non_shiftable_load_kwh"]),
                ),
            }
        else:
            metadata = {
                **metadata,
                "battery_capacity_kwh": 0.0,
                "battery_nominal_power_kw": 0.0,
                "battery_efficiency": 0.0,
                "battery_initial_soc": 0.0,
                "battery_depth_of_discharge": 0.0,
                "battery_loss_coefficient": 0.0,
                "battery_capacity_loss_coefficient": 0.0,
                "battery_sizing_method": "none",
            }
        members.append(metadata)
        frame.to_parquet(family_root / f"timeseries/{metadata['member_id']}.parquet", index=False, compression="zstd")

    residential_charger_phase_offsets: Dict[int, int] = {}
    residential_phase_cursor = 0
    for member_index, charger_count in config.charger_counts.items():
        category = config.member_categories[member_index - 1]
        if category != "residential":
            continue
        # A single 11 kW three-phase charger is already balanced over all
        # phases.  Every individually connected residential charger consumes
        # the next position in a family-level L1/L2/L3 rotation, preventing
        # asset-selection patterns from creating an accidental phase bias.
        if charger_count == 1 and member_index % 5 == 0:
            continue
        residential_charger_phase_offsets[member_index] = residential_phase_cursor
        residential_phase_cursor += int(charger_count)

    electrical_contracts: Dict[str, Mapping] = {}
    electrical_service_rows: List[Mapping] = []
    for member in members:
        member_index = int(member["member_index"])
        contract = build_electrical_contract(
            member_index,
            member["category"],
            int(member["physical_charger_count"]),
            float(member["pv_capacity_kw"]),
            float(member["battery_nominal_power_kw"]),
            float(member["peak_native_import_power_kw"]),
            float(member["peak_native_export_power_kw"]),
            residential_charger_phase_offsets.get(member_index),
        )
        electrical_contracts[member["member_id"]] = contract
        electrical_service_rows.append(
            {
                "member_id": member["member_id"],
                "connection_type": contract["connection_type"],
                "simulator_mode": contract["simulator_mode"],
                "default_split": contract["default_split"],
                "asset_phase_connection": contract["asset_phase_connection"],
                "contracted_power_kva": contract["contracted_power_kva"],
                "original_sampled_contracted_power_kva": contract[
                    "original_sampled_contracted_power_kva"
                ],
                "native_peak_import_kw": contract["native_peak_import_kw"],
                "native_peak_export_kw": contract["native_peak_export_kw"],
                "native_feasibility_margin": contract["native_feasibility_margin"],
                "contract_level_upgraded_for_native_feasibility": contract[
                    "contract_level_upgraded_for_native_feasibility"
                ],
                "active_power_factor_assumption": contract["active_power_factor_assumption"],
                "total_import_limit_kw": contract["total_import_limit_kw"],
                "total_export_limit_kw": contract["total_export_limit_kw"],
                **{
                    f"{phase.lower()}_import_limit_kw": contract["per_phase_import_limits_kw"][phase]
                    for phase in ("L1", "L2", "L3")
                },
                **{
                    f"{phase.lower()}_export_limit_kw": contract["per_phase_export_limits_kw"][phase]
                    for phase in ("L1", "L2", "L3")
                },
                "source_class": contract["source_class"],
            }
        )

    chargers: List[Mapping] = []
    sessions: List[Mapping] = []
    evs: List[Mapping] = []
    for member_index, charger_count in config.charger_counts.items():
        category = config.member_categories[member_index - 1]
        for charger_number in range(1, charger_count + 1):
            schedule, new_sessions, new_evs, metadata = build_charger_schedule(
                member_index,
                charger_number,
                category,
                _routine_archetype(member_index, category),
                calendar_frame,
                electrical_contracts[_member_id(member_index)],
            )
            chargers.append(metadata)
            sessions.extend(new_sessions)
            evs.extend(new_evs)
            schedule.to_parquet(family_root / f"chargers/{metadata['charger_id']}.parquet", index=False, compression="zstd")

    deferrables: List[Mapping] = []
    for member_index in config.deferrable_members:
        category = config.member_categories[member_index - 1]
        profiles, schedule, metadata = build_deferrable(
            member_index,
            category,
            _routine_archetype(member_index, category),
            calendar_frame,
        )
        deferrables.append(metadata)
        profiles.to_parquet(family_root / f"deferrables/{metadata['deferrable_id']}_profiles.parquet", index=False, compression="zstd")
        schedule.to_parquet(family_root / f"deferrables/{metadata['deferrable_id']}_schedule.parquet", index=False, compression="zstd")

    pd.DataFrame(members).to_parquet(family_root / "catalogs/members.parquet", index=False, compression="zstd")
    pd.DataFrame(chargers).to_parquet(family_root / "catalogs/chargers.parquet", index=False, compression="zstd")
    pd.DataFrame(evs).drop_duplicates("ev_id").to_parquet(family_root / "catalogs/electric_vehicles.parquet", index=False, compression="zstd")
    pd.DataFrame(sessions).to_parquet(family_root / "catalogs/charging_sessions.parquet", index=False, compression="zstd")
    pd.DataFrame(deferrables).to_parquet(family_root / "catalogs/deferrables.parquet", index=False, compression="zstd")
    pd.DataFrame(electrical_service_rows).to_parquet(
        family_root / "catalogs/electrical_services.parquet",
        index=False,
        compression="zstd",
    )

    if config.key in {"core30", "premium"}:
        _robustness_events(config.key).to_parquet(family_root / "events/robustness_events.parquet", index=False, compression="zstd")
        _dr_requests(config.key).to_parquet(family_root / "events/demand_response_requests.parquet", index=False, compression="zstd")

    schemas = {}
    for variant in config.variants:
        schema = build_schema(
            config,
            variant,
            members,
            chargers,
            evs,
            deferrables,
            electrical_contracts,
        )
        filename = variant.lower().replace("-", "_") + ".json"
        variant_schema = {**schema, "root_directory": ".."}
        _write_json(family_root / "schemas" / filename, variant_schema)
        schemas[variant] = f"schemas/{filename}"
        if variant == config.default_variant:
            _write_json(family_root / "schema.json", schema)

    settlement = {
        "settlement_id": "same_step_equal_weight_v1",
        "grid_import_price_source": "OMIE Portugal day-ahead 2023",
        "local_price_ratio_to_grid_import": 0.8,
        "matching": "same_time_step_minimum_of_community_surplus_and_demand",
        "import_member_weights": "equal",
        "grid_export_price_eur_per_kwh": 0.0,
        "counterfactual": "grid_only_without_local_matching",
        "outputs": ["participant", "community"],
    }
    _write_json(family_root / "settlement_contract.json", settlement)

    manifest = {
        "dataset_family": config.label,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "generator_version": GENERATOR_VERSION,
        "random_seed": SEED,
        "calendar": {
            "year": YEAR,
            "time_steps": N_STEPS,
            "seconds_per_time_step": SECONDS_PER_TIME_STEP,
            "timeline": "UTC",
            "local_timezone": TIMEZONE,
        },
        "composition": {
            "members": len(members),
            "member_categories": pd.Series([m["category"] for m in members]).value_counts().sort_index().to_dict(),
            "pv_assets": sum(bool(m["has_pv"]) for m in members),
            "stationary_batteries": sum(bool(m["has_battery"]) for m in members),
            "charger_equipped_members": len(set(c["member_id"] for c in chargers)),
            "physical_chargers": len(chargers),
            "electric_vehicles_in_catalog": len({ev["ev_id"] for ev in evs}),
            "annual_charging_sessions": len(sessions),
            "deferrable_appliances": len(deferrables),
        },
        "variants": schemas,
        "default_variant": config.default_variant,
        "price_source": {
            "provider": "OMIE",
            "market": "Portugal day-ahead",
            "archive_url": OMIE_ARCHIVE_URL,
            "mtu15_notice_url": OMIE_MTU15_NOTICE_URL,
            "source_resolution": "hourly physical market periods",
            "quarter_hour_method": "repeat_each_physical_hour_four_times_without_interpolation",
            "conversion": "EUR/MWh divided by 1000 to EUR/kWh",
        },
        "calibration_and_scope": {
            "calendar": {
                "routine_time_basis": "Europe/Lisbon civil wall clock localized before UTC conversion",
                "nonexistent_spring_time_policy": "shift forward by one hour",
                "ambiguous_autumn_time_policy": "first occurrence",
            },
            "demand": {
                "method": "stratified routine-archetype profiles scaled to bounded annual target distributions",
                "anchor_year": 2023,
                "anchor_values_kwh_per_consumer": {
                    "residential": 2489.9,
                    "small_service_non_domestic": 16583.3,
                    "high_consumption_industry": 175891.0,
                },
                "sources": [DGEG_CONSUMPTION_URL, PORDATA_CONSUMPTION_URL],
                "claim_boundary": "national category anchor, not a fitted sample of REC members",
            },
            "asset_heterogeneity": {
                "pv": "annual-demand-coupled capacity, orientation, derate and shading scenario draws",
                "stationary_battery": "product-class capacity and power sized by stratified daily-load autonomy with a host-PV floor, plus member-specific efficiency, SOC and degradation parameters",
                "routine_archetypes": {
                    category: list(archetypes)
                    for category, archetypes in ROUTINE_ARCHETYPES.items()
                },
                "claim_boundary": "controlled stratified heterogeneity, not population-frequency inference",
            },
            "electrical_connections": {
                "method": "normalized Portuguese BTN levels and representative BTE connection levels",
                "sources": [ERSE_CONTRACTED_POWER_URL, EREDES_CONNECTION_MANUAL_URL],
                "active_power_factor_assumption": 1.0,
                "claim_boundary": "connection and phase-headroom surrogate; no feeder voltage, reactive power or protection model",
            },
            "ev_charging": {
                "power_source": ERSE_EV_CHARGING_URL,
                "session_model": "reproducible category-conditional scenario distributions",
                "individual_feasibility_rule": "residential required energy <= 85% and shared-service required energy <= 72% of charger deliverable energy at 95% efficiency; all sessions <= 72% of EV capacity",
                "claim_boundary": "mobility scenario, not a fitted national travel survey",
            },
            "forecasts": {
                "weather": "future truth plus reproducible temporally correlated, horizon-dependent scenario error",
                "load_pv": "causal previous-day persistence with current-step cold start",
                "price": "historical day-ahead market input repeated to quarter-hours",
            },
        },
        "hybrid_series": {
            "historical": ["OMIE Portugal day-ahead price 2023"],
            "deterministic_representative": ["member demand", "PV", "weather", "carbon intensity", "EV sessions", "deferrables"],
        },
        "identity_contract": ["member_id", "charger_id", "ev_id", "session_id"],
        "settlement_contract": "settlement_contract.json",
        "file_integrity": "file_checksums.sha256",
    }
    _write_json(family_root / "dataset_manifest.json", manifest)
    (family_root / "README.md").write_text(
        _readme(config, members, chargers, deferrables), encoding="utf-8"
    )
    _write_file_checksums(family_root)
    return family_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--output-root", type=Path, default=root / "data/datasets")
    parser.add_argument("--source-root", type=Path, default=root / "data/datasets/rec_2023_source_data")
    parser.add_argument(
        "--families",
        nargs="+",
        choices=[*FAMILIES, "all"],
        default=["all"],
        help="Families to generate.",
    )
    parser.add_argument("--refresh-omie", action="store_true", help="Redownload all 365 official daily files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = list(FAMILIES) if "all" in args.families else list(dict.fromkeys(args.families))
    omie_hourly = get_omie_hourly(args.source_root, refresh=args.refresh_omie)
    omie_provenance = pd.read_csv(args.source_root / "omie_2023_daily_provenance.csv")
    calendar_frame = build_calendar()
    weather, pricing, carbon_intensity, pv_factor = build_shared_series(calendar_frame, omie_hourly)
    roots = []
    for key in selected:
        roots.append(
            generate_family(
                FAMILIES[key],
                args.output_root,
                calendar_frame,
                omie_hourly,
                omie_provenance,
                weather,
                pricing,
                carbon_intensity,
                pv_factor,
            )
        )
    for root in roots:
        print(root)


if __name__ == "__main__":
    main()
