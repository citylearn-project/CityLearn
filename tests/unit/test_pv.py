import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from citylearn.energy_model import PV
import citylearn.energy_model as energy_model

pytestmark = pytest.mark.skipif(
    getattr(energy_model, "Pvwattsv8", None) is None,
    reason="PySAM/Pvwattsv8 is not installed in this environment.",
)


class DummyElectricDevice:
    def __init__(self, nominal_power=0.0, **kwargs):
        self.nominal_power = nominal_power
        self.random_seed = 0


@pytest.fixture
def monkeypatch_base_class(monkeypatch):
    monkeypatch.setattr("citylearn.energy_model.ElectricDevice", DummyElectricDevice)


def test_get_generation_scalar():
    pv = PV(nominal_power=10.0)
    result = pv.get_generation(800)
    assert result == 8.0  # 10 * 800 / 1000


def test_get_generation_array():
    pv = PV(nominal_power=5.0)
    power_input = np.array([1000, 900, 800])
    result = pv.get_generation(power_input)
    np.testing.assert_array_almost_equal(result, np.array([5.0, 4.5, 4.0]))


def make_mock_model(ac_output, nameplate_capacity, config=None):
    """Helper function to create a mock PVWatts model."""
    model = MagicMock()
    model.Outputs.ac = ac_output
    model.SystemDesign.system_capacity = nameplate_capacity
    model.SystemDesign.dc_ac_ratio = config.get("inverter_loading_ratio", 1.1)
    model.SystemDesign.tilt = config.get("tilt_1", 20)
    model.SystemDesign.azimuth = config.get("azimuth_1", 180)
    model.SystemDesign.bifaciality = config.get("bifacial_module_1", 0.0) * 0.65
    return model


@patch("citylearn.energy_model.DataSet.get_pv_sizing_data")
@patch("citylearn.energy_model.Pvwattsv8.default")
def test_autosize_basic(mock_pvwatts, mock_sizing_data):
    # Setup
    test_config = {
        "nameplate_capacity_module_1": 3000,  # W
        "inverter_loading_ratio": 1.1,
        "tilt_1": 20,
        "azimuth_1": 180,
        "bifacial_module_1": 0.5,
        "PV_system_size_DC": 6000,
        "module_area": 10.0,
    }
    ac_output = np.ones(8760) * 2000  # 2 kW every hour
    sizing_df = pd.DataFrame([test_config])

    mock_sizing_data.return_value = sizing_df
    mock_model = make_mock_model(ac_output, 3.0, test_config)
    mock_pvwatts.return_value = mock_model

    pv = PV()
    demand = 5000  # kWh
    epw_path = "test.epw"

    nominal_power, inverter_ac_power_per_kw = pv.autosize(
        demand=demand, epw_filepath=epw_path
    )

    # Check inverter outputs
    assert isinstance(nominal_power, float)
    assert nominal_power > 0
    assert isinstance(inverter_ac_power_per_kw, np.ndarray)
    assert np.allclose(inverter_ac_power_per_kw, 2000 / 3.0)


@patch("citylearn.energy_model.DataSet.get_pv_sizing_data")
@patch("citylearn.energy_model.Pvwattsv8.default")
def test_autosize_with_roof_limit(mock_pvwatts, mock_sizing_data):
    config = {
        "nameplate_capacity_module_1": 5000,
        "inverter_loading_ratio": 1.2,
        "tilt_1": 20,
        "azimuth_1": 180,
        "bifacial_module_1": 0.6,
        "PV_system_size_DC": 10000,
        "module_area": 15.0,
    }
    sizing_df = pd.DataFrame([config])
    mock_sizing_data.return_value = sizing_df
    mock_model = make_mock_model(np.ones(8760) * 5000, 5.0, config)
    mock_pvwatts.return_value = mock_model

    pv = PV()
    nominal_power, _ = pv.autosize(
        demand=10000,
        epw_filepath="dummy.epw",
        roof_area=50  # very limited roof area
    )

    expected_max = (50 // 15) * 5.0
    assert nominal_power <= expected_max


@patch("citylearn.energy_model.DataSet.get_pv_sizing_data")
@patch("citylearn.energy_model.Pvwattsv8.default")
def test_autosize_use_sample_target(mock_pvwatts, mock_sizing_data):
    config = {
        "nameplate_capacity_module_1": 4000,
        "inverter_loading_ratio": 1.1,
        "tilt_1": 30,
        "azimuth_1": 180,
        "bifacial_module_1": 0.4,
        "PV_system_size_DC": 8000,
        "module_area": 12.0,
    }
    sizing_df = pd.DataFrame([config])
    mock_sizing_data.return_value = sizing_df
    mock_model = make_mock_model(np.ones(8760) * 3000, 4.0, config)
    mock_pvwatts.return_value = mock_model

    pv = PV()
    nominal_power, _ = pv.autosize(
        demand=5000,
        epw_filepath="dummy.epw",
        use_sample_target=True
    )

    assert np.isclose(nominal_power, 8000)

