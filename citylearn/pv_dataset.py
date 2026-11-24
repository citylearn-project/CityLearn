r"""Precompute PV generation and irradiance forecast columns for a CityLearn dataset.

The module writes ``solar_generation`` (W per kW of installed PV, the CityLearn ``per_kw``
convention) into the building CSV files and ``*_predicted_{1,2,3}`` irradiance columns into
``weather.csv``. Nothing here runs inside :py:class:`citylearn.citylearn.CityLearnEnv`.

Requires the optional extra ``pip install citylearn[pvlib]``. No function opens a network
connection unless it is named ``fetch_*`` or ``quartz_*``.

Command line::

    python -m citylearn.pv_dataset generate DATASET_DIR --latitude 30.27 --longitude -97.74 \
        --kwp 5 --tilt 25 --azimuth 180 --forecast statistical --out OUT_DIR
    python -m citylearn.pv_dataset validate DATASET_DIR --latitude 30.27 --longitude -97.74
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

try:
    import pvlib
except ImportError:  # pragma: no cover
    pvlib = None

HORIZONS = (1, 2, 3)
IRRADIANCE_COLUMNS = ('diffuse_solar_irradiance', 'direct_solar_irradiance')

# Statistical forecast error model: predicted_k[t] = x[t + k] * exp(e_k[t]), with e_k an AR(1)
# process over t, standard deviation ``sigma[k]`` and lag-1 autocorrelation ``rho``. ``method``
# records how the values were obtained; ``fit_forecast_error`` refits them from Quartz forecasts.
DEFAULT_FORECAST_ERROR = {
    'method': 'default-assumption',
    'sigma': {1: 0.15, 2: 0.20, 3: 0.25},
    'rho': 0.8,
}


@dataclass
class PVSpec:
    """PV system parameters for one building. Power in kW, angles in degrees."""

    kwp: float = 1.0
    tilt: float = 30.0
    azimuth: float = 180.0
    loss_percent: float = 14.0
    gamma_pdc: float = -0.004
    dc_ac_ratio: float = 1.2
    temperature_model: str = 'open_rack_glass_glass'
    albedo: float = 0.2


def _require_pvlib():
    if pvlib is None:
        raise ModuleNotFoundError('pvlib is required: pip install citylearn[pvlib]')


def infer_index(building: pd.DataFrame, year: int = 2017, seconds_per_time_step: int = 3600) -> pd.DatetimeIndex:
    """Timestamps (interval starts, local standard time) from the ``month`` and ``hour`` columns.

    Hour ``h`` of CityLearn hourly files covers ``[h-1, h)`` hours. A first row with hour 24 belongs
    to the last day of its month. The year is arbitrary (CityLearn files carry none); a non-leap
    year gives 8760 rows without 29 February.
    """

    if seconds_per_time_step != 3600:
        raise ValueError('infer_index supports hourly files only; pass --start for other resolutions.')

    month, hour = int(building['month'].iloc[0]), int(building['hour'].iloc[0])
    first = pd.Timestamp(year=year, month=month, day=1)

    if hour == 24:
        first = first + pd.offsets.MonthEnd(0)

    start = first + pd.Timedelta(hours=hour - 1)
    return pd.date_range(start, periods=len(building), freq='h')


def weather_to_pvlib(weather: pd.DataFrame, index: pd.DatetimeIndex, *, wind_speed: float = 1.0) -> pd.DataFrame:
    """Map CityLearn weather columns to pvlib names.

    CityLearn stores diffuse horizontal and direct normal irradiance, so ``ghi = dhi + dni cos(zenith)``
    is derived later in :py:func:`simulate_pv`. Only the first ``len(index)`` rows are used.
    """

    out = pd.DataFrame(index=index[:len(weather)])
    out['dhi'] = weather['diffuse_solar_irradiance'].to_numpy()[:len(out)]
    out['dni'] = weather['direct_solar_irradiance'].to_numpy()[:len(out)]
    out['temp_air'] = weather['outdoor_dry_bulb_temperature'].to_numpy()[:len(out)]
    out['wind_speed'] = wind_speed
    return out


def simulate_pv(
    weather: pd.DataFrame, latitude: float, longitude: float, spec: PVSpec, *,
    altitude: float = 0.0, utc_offset_hours: Optional[float] = None, step_seconds: int = 3600,
) -> np.ndarray:
    """Average AC power in W per kW of installed PV for every row of ``weather``.

    ``weather`` is indexed by interval start (tz-naive local standard time) with columns
    ``dni``, ``dhi``, ``temp_air`` and ``wind_speed``, plus optional ``ghi``. Solar position is
    evaluated at the interval midpoint. Uses a pvlib PVWatts ``ModelChain``; ``loss_percent`` scales
    the AC output.
    """

    _require_pvlib()
    from pvlib.location import Location
    from pvlib.modelchain import ModelChain
    from pvlib.pvsystem import Array, FixedMount, PVSystem
    from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS

    offset = longitude / 15.0 if utc_offset_hours is None else utc_offset_hours
    mid = weather.index + pd.Timedelta(seconds=step_seconds / 2) - pd.Timedelta(hours=offset)
    mid = mid.tz_localize('UTC')
    location = Location(latitude, longitude, tz='UTC', altitude=altitude)
    w = weather.copy()
    w.index = mid

    if 'ghi' not in w:
        zenith = location.get_solarposition(mid)['apparent_zenith']
        w['ghi'] = (w['dhi'] + w['dni'] * np.cos(np.radians(zenith.clip(upper=90.0)))).clip(lower=0.0)

    pdc0 = 1000.0
    array = Array(
        FixedMount(spec.tilt, spec.azimuth),
        module_parameters={'pdc0': pdc0, 'gamma_pdc': spec.gamma_pdc},
        temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS['sapm'][spec.temperature_model],
    )
    system = PVSystem(
        arrays=[array], inverter_parameters={'pdc0': pdc0 / spec.dc_ac_ratio},
        albedo=spec.albedo,
    )
    mc = ModelChain.with_pvwatts(system, location, aoi_model='physical', spectral_model='no_loss')
    mc.run_model(w[['ghi', 'dni', 'dhi', 'temp_air', 'wind_speed']])
    ac = mc.results.ac.fillna(0.0).clip(lower=0.0)
    return (ac.to_numpy() * (1.0 - spec.loss_percent / 100.0)).astype('float64')


def fetch_pvgis_tmy(latitude: float, longitude: float, **kwargs) -> pd.DataFrame:
    """Network call: PVGIS typical meteorological year through ``pvlib.iotools.get_pvgis_tmy``.

    Returns a frame with the CityLearn weather column names, hourly, 8760 rows.
    """

    _require_pvlib()
    data, *_ = pvlib.iotools.get_pvgis_tmy(latitude, longitude, map_variables=True, **kwargs)
    data = data.iloc[:8760]
    return pd.DataFrame({
        'outdoor_dry_bulb_temperature': data['temp_air'].to_numpy(),
        'outdoor_relative_humidity': data['relative_humidity'].to_numpy(),
        'diffuse_solar_irradiance': data['dhi'].to_numpy(),
        'direct_solar_irradiance': data['dni'].to_numpy(),
    })


def statistical_forecast(
    series: np.ndarray, sigma: Dict[int, float], rho: float, seed: int, horizons: Sequence[int] = HORIZONS,
) -> Dict[int, np.ndarray]:
    """``predicted_k[t] = series[t + k] * exp(e_k[t])`` with AR(1) log-errors; edge values are repeated."""

    rng = np.random.default_rng(seed)
    n = len(series)
    out = {}

    for k in horizons:
        shifted = np.concatenate([series[k:], np.repeat(series[-1], k)])
        s = float(sigma[k])
        noise = rng.standard_normal(n)
        e = np.empty(n)
        e[0] = noise[0] * s

        for t in range(1, n):
            e[t] = rho * e[t - 1] + np.sqrt(1.0 - rho ** 2) * s * noise[t]

        out[k] = np.clip(shifted * np.exp(e - 0.5 * s ** 2), 0.0, None)

    return out


def fit_forecast_error(
    truth: np.ndarray, forecasts: Dict[int, np.ndarray], *, floor: float = 50.0,
) -> dict:
    """Fit ``sigma`` and ``rho`` of the log-error model from a forecast and its truth (any matching unit).

    ``truth`` and ``forecasts[k]`` are aligned on the target time. Only rows where both exceed
    ``floor`` are used (night and twilight carry no information about the multiplicative error).
    """

    sigma, rhos = {}, []

    for k, f in forecasts.items():
        mask = (np.asarray(truth) > floor) & (np.asarray(f) > floor)
        e = np.log(np.asarray(f)[mask] / np.asarray(truth)[mask])
        sigma[int(k)] = float(e.std())

        if len(e) > 2:
            rhos.append(float(np.corrcoef(e[:-1], e[1:])[0, 1]))

    return {'method': 'fitted', 'sigma': sigma, 'rho': float(np.mean(rhos)) if rhos else 0.0}


def quartz_pv_forecast(
    latitude: float, longitude: float, kwp: float, tilt: float, azimuth: float, ts: pd.Timestamp, *, predictor: Optional[Callable] = None,
) -> pd.Series:
    """Network call: Quartz Solar Forecast (``model='gb'``, ICON) PV power in kW from ``ts`` for 48 h.

    Quartz fetches NWP from Open-Meteo and only returns a true forecast for ``ts`` within the last
    90 days; older timestamps silently receive reanalysis data. This function refuses them.
    ``predictor`` replaces the Quartz call (tests).
    """

    if (pd.Timestamp.now() - ts).days > 85:
        raise ValueError('Quartz provides forecasts for the last 90 days only; use the statistical model.')

    if predictor is None:
        from quartz_solar_forecast.forecast import run_forecast
        from quartz_solar_forecast.pydantic_models import PVSite
        site = PVSite(latitude=latitude, longitude=longitude, capacity_kwp=kwp, tilt=tilt, orientation=azimuth)
        predictor = lambda: run_forecast(site=site, ts=ts)  # noqa: E731

    return predictor()['power_kw']


def add_forecast_columns(weather: pd.DataFrame, params: dict, seed: int) -> pd.DataFrame:
    """Overwrite ``<irradiance>_predicted_{1,2,3}`` in ``weather`` with the statistical forecast."""

    weather = weather.copy()
    sigma = {int(k): v for k, v in params['sigma'].items()}

    for j, col in enumerate(IRRADIANCE_COLUMNS):
        forecasts = statistical_forecast(weather[col].to_numpy(float), sigma, params['rho'], seed + j)

        for k, values in forecasts.items():
            weather[f'{col}_predicted_{k}'] = np.round(values, 1)

    return weather


def generate(
    dataset_dir: Path, out_dir: Path, latitude: float, longitude: float, specs: Dict[str, PVSpec], *,
    year: int = 2017, start: Optional[str] = None, forecast: str = 'statistical',
    forecast_params: Optional[dict] = None, seed: int = 0, tmy: bool = False, altitude: float = 0.0,
    utc_offset_hours: Optional[float] = None,
) -> dict:
    """Copy ``dataset_dir`` to ``out_dir`` and rewrite ``solar_generation`` and the forecast columns.

    ``specs`` maps a building file stem (``Building_1``) to a :class:`PVSpec`; the key ``'*'``
    applies to buildings without an entry. Returns a provenance dict that is also written to
    ``out_dir/pv_provenance.json``.
    """

    dataset_dir, out_dir = Path(dataset_dir), Path(out_dir)

    if forecast not in ('statistical', 'none'):
        raise ValueError("forecast must be 'statistical' or 'none'; Quartz forecasts are supported by quartz_pv_forecast for the last 90 days only.")

    if out_dir.resolve() != dataset_dir.resolve():
        shutil.copytree(dataset_dir, out_dir, dirs_exist_ok=True)

    schema = json.loads((out_dir / 'schema.json').read_text())
    seconds = int(schema.get('seconds_per_time_step', 3600))
    weather = pd.read_csv(out_dir / 'weather.csv')
    buildings = sorted(p.stem for p in out_dir.glob('Building_*.csv'))
    first = pd.read_csv(out_dir / f'{buildings[0]}.csv')

    if tmy:
        tmy_weather = fetch_pvgis_tmy(latitude, longitude)
        weather = weather.copy()

        for col in tmy_weather.columns:
            weather[col] = tmy_weather[col].to_numpy()[:len(weather)]

    index = pd.date_range(start, periods=len(weather), freq=f'{seconds}s') if start else infer_index(first, year, seconds)
    w = weather_to_pvlib(weather, index)

    for name in buildings:
        spec = specs.get(name, specs.get('*'))

        if spec is None:
            continue

        path = out_dir / f'{name}.csv'
        df = pd.read_csv(path)
        df['solar_generation'] = np.round(simulate_pv(w, latitude, longitude, spec, altitude=altitude, utc_offset_hours=utc_offset_hours, step_seconds=seconds), 4)
        df.to_csv(path, index=False)

    params = None

    if forecast == 'statistical':
        params = forecast_params or DEFAULT_FORECAST_ERROR
        weather = add_forecast_columns(weather, params, seed)

    weather.to_csv(out_dir / 'weather.csv', index=False)
    provenance = {
        'pv_model': 'pvlib ModelChain.with_pvwatts', 'pvlib_version': getattr(pvlib, '__version__', None),
        'weather_source': 'pvgis_tmy' if tmy else 'dataset weather.csv', 'latitude': latitude, 'longitude': longitude,
        'unit': 'W per kW of installed PV (per_kw)', 'forecast': forecast if forecast == 'none' else 'statistical (NOT Quartz)',
        'forecast_error_model': params, 'seed': seed,
        'specs': {k: asdict(v) for k, v in specs.items()},
    }
    (out_dir / 'pv_provenance.json').write_text(json.dumps(provenance, indent=2, default=str))
    return provenance


def validate(dataset_dir: Path, latitude: float, longitude: float, spec: PVSpec, *, building: str = 'Building_1', year: int = 2017, **kwargs) -> dict:
    """Compare pvlib output with the dataset's own ``solar_generation`` (Pearson r, energy ratio, nMBE, nRMSE)."""

    dataset_dir = Path(dataset_dir)
    df = pd.read_csv(dataset_dir / f'{building}.csv')
    seconds = int(json.loads((dataset_dir / 'schema.json').read_text()).get('seconds_per_time_step', 3600))
    w = weather_to_pvlib(pd.read_csv(dataset_dir / 'weather.csv'), infer_index(df, year, seconds))
    sim = simulate_pv(w, latitude, longitude, spec, step_seconds=seconds, **kwargs)
    ref = df['solar_generation'].to_numpy(float)
    return {
        'pearson_r': float(np.corrcoef(sim, ref)[0, 1]),
        'energy_ratio_sim_over_dataset': float(sim.sum() / ref.sum()),
        'nmbe': float((sim - ref).mean() / ref.mean()),
        'nrmse': float(np.sqrt(((sim - ref) ** 2).mean()) / ref.mean()),
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m citylearn.pv_dataset', description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', required=True)

    for name in ('generate', 'validate'):
        s = sub.add_parser(name)
        s.add_argument('dataset_dir', type=Path)
        s.add_argument('--latitude', type=float, required=True)
        s.add_argument('--longitude', type=float, required=True)
        s.add_argument('--kwp', type=float, default=1.0, help='nominal power; solar_generation is per kW, so 1 keeps CityLearn per_kw scaling')
        s.add_argument('--tilt', type=float, default=30.0)
        s.add_argument('--azimuth', type=float, default=180.0, help='degrees from north, 180 = south')
        s.add_argument('--loss-percent', type=float, default=14.0)
        s.add_argument('--year', type=int, default=2017)
        s.add_argument('--utc-offset-hours', type=float, default=None, help='standard-time offset of the dataset (Austin: -6); default longitude/15, the mean solar time')
        s.add_argument('--building', default='Building_1', help='validate only')

    g = sub.choices['generate']
    g.add_argument('--out', type=Path, required=True)
    g.add_argument('--start', help='ISO timestamp of the first row; overrides month/hour inference')
    g.add_argument('--forecast', choices=('statistical', 'none'), default='statistical')
    g.add_argument('--forecast-params', type=Path, help='JSON from fit_forecast_error')
    g.add_argument('--seed', type=int, default=0)
    g.add_argument('--pvgis-tmy', action='store_true', help='network: replace weather irradiance and temperature by PVGIS TMY')
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    a = _parser().parse_args(argv)
    spec = PVSpec(kwp=a.kwp, tilt=a.tilt, azimuth=a.azimuth, loss_percent=a.loss_percent)

    if a.command == 'validate':
        print(json.dumps(validate(a.dataset_dir, a.latitude, a.longitude, spec, building=a.building, year=a.year, utc_offset_hours=a.utc_offset_hours), indent=2))
        return 0

    params = json.loads(a.forecast_params.read_text()) if a.forecast_params else None
    prov = generate(a.dataset_dir, a.out, a.latitude, a.longitude, {'*': spec}, year=a.year, start=a.start,
                    forecast=a.forecast, forecast_params=params, seed=a.seed, tmy=a.pvgis_tmy, utc_offset_hours=a.utc_offset_hours)
    print(json.dumps(prov, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
