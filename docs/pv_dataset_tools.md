# PV generation and forecast columns for datasets

`citylearn.pv_dataset` writes `solar_generation` and the `*_predicted_{1,2,3}` irradiance columns of a dataset before a simulation. `CityLearnEnv` reads the columns as before, so the tool adds no runtime cost.

Install the optional dependency with `pip install citylearn[pvlib]`. No function opens a network connection except `fetch_pvgis_tmy` (`--pvgis-tmy`) and `quartz_pv_forecast`.

## Generate

```console
python -m citylearn.pv_dataset generate DATASET_DIR --out NEW_DIR \
    --latitude 30.27 --longitude -97.74 --tilt 25 --azimuth 180 --loss-percent 14 \
    --forecast statistical --seed 0
```

The dataset is copied to `NEW_DIR`. Every `Building_*.csv` gets a new `solar_generation` and `weather.csv` gets new predicted irradiance columns. `pv_provenance.json` records the model, the location, the PV parameters, the forecast method and the seed. From Python, `generate(..., specs={'Building_1': PVSpec(tilt=20), '*': PVSpec()})` sets parameters per building.

- **Unit.** `solar_generation` is the average AC power in W per kW of installed PV (CityLearn `per_kw` mode). The schema's `nominal_power` scales it, so `--kwp` does not change the file.
- **Model.** pvlib `ModelChain.with_pvwatts` with fixed-tilt mounting, physical AOI loss, SAPM open-rack cell temperature, `gamma_pdc = -0.004 /K`, DC/AC ratio 1.2 and a scalar loss (default 14 %) applied to the AC output. Solar position uses the interval midpoint.
- **Weather.** The dataset's `weather.csv` (`direct_solar_irradiance` is read as DNI, `diffuse_solar_irradiance` as DHI, `ghi = dhi + dni cos(zenith)`), or PVGIS TMY with `--pvgis-tmy`. CityLearn files carry no year or location: the timestamps come from `month` and `hour` (hourly files; `--start` for others) and the longitude gives the UTC offset.

## Forecast columns

The tool states in `pv_provenance.json` and on stdout which forecast ran.

- **Quartz.** Quartz Solar Forecast takes NWP data from Open-Meteo and returns a forecast only for the last 90 days; for older timestamps it silently uses reanalysis data. `quartz_pv_forecast` refuses such timestamps, so Quartz cannot produce forecast columns for the historical periods of the bundled datasets. Quartz's pinned dependencies (`xarray==2022.12.0`, NumPy 1) also conflict with current CityLearn environments: run it in a separate environment.
- **Statistical model (default).** `predicted_k[t] = x[t+k] exp(e_k[t])` for `x` direct and diffuse irradiance, with AR(1) log-errors of standard deviation `sigma[k]` and lag-1 correlation `rho`. Night values stay 0. `scripts/manual/fit_quartz_forecast_error.py` fits `sigma` and `rho` from recent Quartz forecasts against a pvlib simulation driven by Open-Meteo ERA5 irradiance (`--forecast-params` takes its JSON). The built-in default (`method: default-assumption`) is not fitted and is labelled as such in the provenance. A run for latitude 51.5, longitude -0.1, 14 days of November 2026 (156 daytime samples, floor 50 W/kW) gave `sigma = 0.59` for all horizons and `rho = 0.25`, a larger and less persistent error than the default assumption (0.15 to 0.25, `rho = 0.8`), so the default is not Quartz-fitted and one winter fortnight at one site does not justify replacing it. The fitted values compare Quartz with a reanalysis-driven simulation, not with measured PV.

## Validation

```console
python -m citylearn.pv_dataset validate DATASET_DIR --latitude 30.27 --longitude -97.74 --tilt 20
```

prints Pearson r, the energy ratio, nMBE and nRMSE of pvlib against the dataset's `solar_generation`. For `citylearn_challenge_2022_phase_all` `Building_1` (latitude and longitude of Austin, Texas assumed, tilt 20, UTC-6, hourly) r is 0.83 and the pvlib energy is 95 % of the dataset energy. The agreement is limited by the dataset: its `diffuse_solar_irradiance` reaches 1017 W/m2, which a diffuse component cannot, so its irradiance columns are not a clean pvlib input.
