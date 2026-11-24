"""Fit the statistical PV forecast error model of citylearn.pv_dataset to Quartz forecasts (network).

Runs Quartz Solar Forecast (gb, ICON) once per day at 00:00 UTC for the last ``--days`` days
(excluding the last 6, which the Open-Meteo archive does not yet cover), simulates the same site
with pvlib from Open-Meteo archive (ERA5) irradiance as the reference, and fits the log-error
sigma and autocorrelation. The reference is a reanalysis-driven simulation, not measured PV, and
Quartz is trained on UK sites: the fitted values describe forecast-versus-reanalysis disagreement.

Needs quartz-solar-forecast (its pins conflict with current numpy/pandas: use a separate venv) and pvlib.
    python scripts/manual/fit_quartz_forecast_error.py --latitude 51.5 --longitude -0.1 --out quartz_error.json
"""
import argparse
import json

import numpy as np
import pandas as pd
import requests

from citylearn.pv_dataset import PVSpec, fit_forecast_error, simulate_pv


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--latitude', type=float, required=True)
    p.add_argument('--longitude', type=float, required=True)
    p.add_argument('--days', type=int, default=14)
    p.add_argument('--tilt', type=float, default=35)
    p.add_argument('--azimuth', type=float, default=180)
    p.add_argument('--out', required=True)
    a = p.parse_args()

    from quartz_solar_forecast.forecast import run_forecast
    from quartz_solar_forecast.pydantic_models import PVSite

    end = pd.Timestamp.now().normalize() - pd.Timedelta(days=6)
    start = end - pd.Timedelta(days=a.days)
    r = requests.get('https://archive-api.open-meteo.com/v1/archive', params={
        'latitude': a.latitude, 'longitude': a.longitude, 'start_date': str(start.date()), 'end_date': str(end.date()),
        'hourly': 'temperature_2m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation', 'timezone': 'GMT'}, timeout=60)
    r.raise_for_status()
    h = pd.DataFrame(r.json()['hourly'])
    h.index = pd.to_datetime(h.pop('time'))
    # Open-Meteo radiation is the mean of the preceding hour; shift to interval start
    w = pd.DataFrame({'ghi': h.shortwave_radiation.shift(-1), 'dni': h.direct_normal_irradiance.shift(-1),
                      'dhi': h.diffuse_radiation.shift(-1), 'temp_air': h.temperature_2m, 'wind_speed': 1.0}).dropna()
    spec = PVSpec(tilt=a.tilt, azimuth=a.azimuth)
    truth = pd.Series(simulate_pv(w, a.latitude, a.longitude, spec, utc_offset_hours=0), index=w.index)

    site = PVSite(latitude=a.latitude, longitude=a.longitude, capacity_kwp=4.0, tilt=a.tilt, orientation=a.azimuth)
    forecasts = {k: [] for k in (1, 2, 3)}
    truths = {k: [] for k in (1, 2, 3)}

    for day in pd.date_range(start, end - pd.Timedelta(days=2), freq='D'):
        q = run_forecast(site=site, ts=day)['power_kw'].resample('1h').mean() / site.capacity_kwp * 1000.0
        # leads of 6-18 h cover daylight; the three pooled leads stand for horizons 1-3 of the dataset
        sub = q[(q.index >= day + pd.Timedelta(hours=6)) & (q.index < day + pd.Timedelta(hours=18))]

        for i, k in enumerate((1, 2, 3)):
            idx = sub.index[i::3].intersection(truth.index)
            forecasts[k].append(sub.loc[idx].to_numpy())
            truths[k].append(truth.loc[idx].to_numpy())

    t = np.concatenate([np.concatenate(truths[k]) for k in (1, 2, 3)])
    result = {'method': 'fitted-quartz-vs-era5-pvlib', 'sigma': {}, 'rho': 0.0}
    fit = fit_forecast_error(np.concatenate(truths[1]), {1: np.concatenate(forecasts[1])})
    sigma_all = fit_forecast_error(t, {1: np.concatenate([np.concatenate(forecasts[k]) for k in (1, 2, 3)])})
    result['sigma'] = {k: sigma_all['sigma'][1] for k in (1, 2, 3)}
    result['rho'] = fit['rho']
    result.update({'n_days': a.days, 'latitude': a.latitude, 'longitude': a.longitude, 'n_samples': int(t.size)})
    json.dump(result, open(a.out, 'w'), indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
