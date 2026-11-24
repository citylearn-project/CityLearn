import json

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('pvlib')

from citylearn import pv_dataset as pvd  # noqa: E402


@pytest.fixture
def dataset(tmp_path):
    n = 24 * 10
    hours = np.arange(n) % 24 + 1
    month = np.full(n, 6)
    pd.DataFrame({'month': month, 'hour': hours, 'solar_generation': 0.0}).to_csv(tmp_path / 'Building_1.csv', index=False)
    elevation = np.clip(np.sin((hours - 6.0) / 12.0 * np.pi), 0.0, None)
    w = pd.DataFrame({
        'outdoor_dry_bulb_temperature': 25.0,
        'diffuse_solar_irradiance': 100.0 * elevation,
        'direct_solar_irradiance': 800.0 * elevation,
    })
    w.to_csv(tmp_path / 'weather.csv', index=False)
    (tmp_path / 'schema.json').write_text(json.dumps({'seconds_per_time_step': 3600}))
    return tmp_path


def test_infer_index_hour_24_belongs_to_previous_day():
    df = pd.DataFrame({'month': [7, 8, 8], 'hour': [24, 1, 2]})
    idx = pvd.infer_index(df, year=2017)
    assert idx[0] == pd.Timestamp('2017-07-31 23:00')
    assert idx[1] == pd.Timestamp('2017-08-01 00:00')


def test_simulate_pv_units_and_night(dataset):
    df = pd.read_csv(dataset / 'Building_1.csv')
    w = pvd.weather_to_pvlib(pd.read_csv(dataset / 'weather.csv'), pvd.infer_index(df))
    out = pvd.simulate_pv(w, 30.0, -90.0, pvd.PVSpec(tilt=20), utc_offset_hours=-6)
    assert out.shape == (len(df),)
    assert (out >= 0).all()
    assert 300 < out.max() < 1000  # W per kW installed
    assert out[:4].sum() == 0.0  # local midnight to 4 am


def test_kwp_does_not_scale_output(dataset):
    df = pd.read_csv(dataset / 'Building_1.csv')
    w = pvd.weather_to_pvlib(pd.read_csv(dataset / 'weather.csv'), pvd.infer_index(df))
    a = pvd.simulate_pv(w, 30.0, -90.0, pvd.PVSpec(kwp=1.0), utc_offset_hours=-6)
    b = pvd.simulate_pv(w, 30.0, -90.0, pvd.PVSpec(kwp=9.0), utc_offset_hours=-6)
    np.testing.assert_allclose(a, b)


def test_generate_writes_columns_and_provenance(dataset, tmp_path_factory):
    out = tmp_path_factory.mktemp('out')
    prov = pvd.generate(dataset, out, 30.0, -90.0, {'*': pvd.PVSpec()}, utc_offset_hours=-6, seed=1)
    assert 'NOT Quartz' in prov['forecast']
    b = pd.read_csv(out / 'Building_1.csv')
    w = pd.read_csv(out / 'weather.csv')
    assert b['solar_generation'].max() > 300
    assert all(f'direct_solar_irradiance_predicted_{k}' in w for k in (1, 2, 3))
    assert (w.filter(like='_predicted_') >= 0).all().all()
    assert (out / 'pv_provenance.json').exists()
    assert (pd.read_csv(dataset / 'Building_1.csv')['solar_generation'] == 0).all()  # source untouched


def test_forecast_is_deterministic_and_zero_at_night():
    x = np.tile(np.r_[np.zeros(8), np.full(8, 500.0), np.zeros(8)], 5)
    a = pvd.statistical_forecast(x, {1: .1, 2: .1, 3: .1}, .5, seed=3)
    b = pvd.statistical_forecast(x, {1: .1, 2: .1, 3: .1}, .5, seed=3)
    np.testing.assert_array_equal(a[1], b[1])
    assert a[1][:7].max() == 0.0


def test_fit_recovers_sigma():
    rng = np.random.default_rng(0)
    truth = np.full(20000, 400.0)
    fc = {1: truth * np.exp(rng.normal(0, 0.2, truth.size))}
    assert pvd.fit_forecast_error(truth, fc)['sigma'][1] == pytest.approx(0.2, abs=0.01)


def test_quartz_refuses_old_timestamps():
    with pytest.raises(ValueError, match='90 days'):
        pvd.quartz_pv_forecast(51.0, 0.0, 4.0, 30, 180, pd.Timestamp('2020-01-01'))


def test_quartz_predictor_injection():
    ts = pd.Timestamp.now()
    s = pvd.quartz_pv_forecast(51.0, 0.0, 4.0, 30, 180, ts, predictor=lambda: pd.DataFrame({'power_kw': [1.0]}))
    assert s.iloc[0] == 1.0


def test_cli_generate(dataset, tmp_path, capsys):
    out = tmp_path / 'cli'
    assert pvd.main(['generate', str(dataset), '--latitude', '30', '--longitude', '-90', '--out', str(out), '--forecast', 'none']) == 0
    assert 'solar_generation' in pd.read_csv(out / 'Building_1.csv')
