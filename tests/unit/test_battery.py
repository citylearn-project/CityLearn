import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
import math

from citylearn.energy_model import Battery

# Constants used in the Battery class
ZERO_DIVISION_PLACEHOLDER = 1e-10

# Mock the Environment class that Device inherits from
class Environment:
    def __init__(self, **kwargs):
        self.time_step = 0
        self.episode_tracker = MagicMock()
        self.episode_tracker.episode_time_steps = 100
        self.time_step_ratio = kwargs.get('time_step_ratio', 1.0)
        self.numpy_random_state = np.random.RandomState(kwargs.get('random_seed', 42))
    
    def get_metadata(self):
        return {}
    
    def reset(self):
        self.time_step = 0


# Mock other necessary components to isolate Battery for testing
class DataSet:
    def get_battery_sizing_data(self):
        data = {
            'model': ['model1', 'model2', 'model3'],
            'capacity': [10.0, 20.0, 50.0],
            'nominal_power': [5.0, 10.0, 25.0],
            'depth_of_discharge': [0.8, 0.9, 0.85],
            'efficiency': [0.92, 0.95, 0.90],
            'loss_coefficient': [0.002, 0.001, 0.003],
            'capacity_loss_coefficient': [1e-5, 2e-5, 5e-6]
        }
        df = pd.DataFrame(data)
        return df



class TestBattery(unittest.TestCase):
    """Unit tests for the Battery class"""
    
    def setUp(self):
        """Set up test fixtures before each test"""
        self.battery = Battery(
            capacity=100.0,
            nominal_power=10.0,
            capacity_loss_coefficient=1e-5,
            power_efficiency_curve=[[0, 0.83], [0.3, 0.83], [0.7, 0.9], [0.8, 0.9], [1, 0.85]],
            capacity_power_curve=[[0.0, 1], [0.8, 1], [1.0, 0.2]],
            depth_of_discharge=0.8,
            efficiency=0.9,
            loss_coefficient=0.001,
            random_seed=42
        )
        
        self.battery.episode_tracker = MagicMock()
        self.battery.episode_tracker.episode_time_steps = 100
        self.battery.reset()
        
        self.original_update_electricity = self.battery.update_electricity_consumption
        self.battery.update_electricity_consumption = MagicMock()

    def tearDown(self):
        """Clean up after each test"""
        if hasattr(self, 'original_update_electricity'):
            self.battery.update_electricity_consumption = self.original_update_electricity

    def test_initialization(self):
        """Test battery initialization with various parameters"""
        battery_default = Battery(random_seed=42)
        self.assertIsNotNone(battery_default.capacity)
        self.assertIsNotNone(battery_default.nominal_power)
        self.assertIsNotNone(battery_default.depth_of_discharge)
        self.assertIsNotNone(battery_default.capacity_loss_coefficient)
        
        battery = Battery(
            capacity=200.0,
            nominal_power=20.0,
            capacity_loss_coefficient=2e-5,
            depth_of_discharge=0.9,
            efficiency=0.95,
            random_seed=42
        )
        self.assertEqual(battery.capacity, 200.0)
        self.assertEqual(battery.nominal_power, 20.0)
        self.assertEqual(battery.capacity_loss_coefficient, 2e-5)
        self.assertEqual(battery.depth_of_discharge, 0.9)
        self.assertEqual(battery.efficiency, 0.95)
        
        self.assertEqual(len(battery.capacity_history), 1)
        self.assertEqual(battery.capacity_history[0], 200.0)
        
        self.assertTrue(hasattr(battery, '_efficiency_history'))

    def test_property_getters(self):
        """Test property getters return expected values"""
        self.assertEqual(self.battery.capacity, 100.0)
        self.assertEqual(self.battery.nominal_power, 10.0)
        self.assertEqual(self.battery.depth_of_discharge, 0.8)
        self.assertEqual(self.battery.capacity_loss_coefficient, 1e-5)
        
        self.assertEqual(len(self.battery.capacity_history), 1)
        self.assertEqual(self.battery.capacity_history[0], 100.0)
        self.assertEqual(self.battery.degraded_capacity, 100.0)  # Initial value should equal capacity

    def test_next_time_step_carries_soc_with_standby_loss_without_energy_balance(self):
        battery = Battery(
            capacity=10.0,
            nominal_power=5.0,
            initial_soc=0.5,
            efficiency=1.0,
            loss_coefficient=0.1,
            capacity_loss_coefficient=0.0,
            power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
            capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
            seconds_per_time_step=3600,
        )
        battery.episode_tracker = MagicMock()
        battery.episode_tracker.episode_time_steps = 3
        battery.reset()

        battery.next_time_step()

        self.assertAlmostEqual(float(battery.soc[1]), 0.45)
        self.assertAlmostEqual(float(battery.energy_balance[1]), 0.0)

    def test_zero_charge_does_not_apply_standby_loss_twice(self):
        battery = Battery(
            capacity=10.0,
            nominal_power=5.0,
            initial_soc=1.0,
            efficiency=1.0,
            loss_coefficient=0.1,
            capacity_loss_coefficient=0.0,
            power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
            capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
            seconds_per_time_step=3600,
        )
        battery.episode_tracker = MagicMock()
        battery.episode_tracker.episode_time_steps = 3
        battery.reset()
        battery.update_electricity_consumption = MagicMock()

        battery.charge(0.0)
        self.assertAlmostEqual(float(battery.soc[0]), 1.0)

        battery.next_time_step()
        self.assertAlmostEqual(float(battery.soc[1]), 0.9)

    def test_property_setters(self):
        """Test property setters update values correctly"""
        self.battery.capacity = 150.0
        self.assertEqual(self.battery.capacity, 150.0)
        self.assertEqual(self.battery.capacity_history[-1], 150.0)
        
        self.battery.capacity_loss_coefficient = 2e-5
        self.assertEqual(self.battery.capacity_loss_coefficient, 2e-5)
        
        self.battery.depth_of_discharge = 0.9
        self.assertEqual(self.battery.depth_of_discharge, 0.9)
        
        new_power_curve = [[0, 0.8], [0.5, 0.85], [1, 0.9]]
        self.battery.power_efficiency_curve = new_power_curve
        self.assertTrue(np.array_equal(self.battery.power_efficiency_curve[0], np.array([0, 0.5, 1])))
        self.assertTrue(np.array_equal(self.battery.power_efficiency_curve[1], np.array([0.8, 0.85, 0.9])))
        
        new_capacity_curve = [[0, 0.9], [0.5, 0.8], [1, 0.1]]
        self.battery.capacity_power_curve = new_capacity_curve
        self.assertTrue(np.array_equal(self.battery.capacity_power_curve[0], np.array([0, 0.5, 1])))
        self.assertTrue(np.array_equal(self.battery.capacity_power_curve[1], np.array([0.9, 0.8, 0.1])))

    def test_invalid_physical_battery_parameters_are_rejected(self):
        with self.assertRaises(AssertionError):
            Battery(depth_of_discharge=1.2, random_seed=42)
        with self.assertRaises(AssertionError):
            Battery(depth_of_discharge=-0.2, random_seed=42)
        with self.assertRaises(AssertionError):
            Battery(capacity_loss_coefficient=-0.001, random_seed=42)
        with self.assertRaises(AssertionError):
            Battery(efficiency=1.21, random_seed=42)

    def test_charge_positive_energy(self):
        """Test the charge method with positive energy (charging)"""
        self.battery.force_set_soc(0.5)  # Start at 50% SOC
        
        # Test charging with small amount
        self.battery.charge(5.0)  # Charge with 5 kWh
        
        # Check that SOC increased and energy_balance is positive
        self.assertGreater(self.battery.soc[self.battery.time_step], 0.5)
        self.assertGreater(self.battery.energy_balance[self.battery.time_step], 0)
        
        # Verify update_electricity_consumption was called
        self.battery.update_electricity_consumption.assert_called_once()

    def test_charge_negative_energy(self):
        """Test the charge method with negative energy (discharging)"""
        self.battery.force_set_soc(0.9)  # Start at 90% SOC
        
        # Test discharging
        self.battery.charge(-5.0)  # Discharge with 5 kWh
        
        # Check that SOC decreased and energy_balance is negative
        self.assertLess(self.battery.soc[self.battery.time_step], 0.9)
        self.assertLess(self.battery.energy_balance[self.battery.time_step], 0)
        
        # Verify update_electricity_consumption was called
        self.battery.update_electricity_consumption.assert_called_once()

    def test_depth_of_discharge_limit(self):
        """Test that the battery respects the depth of discharge limit when discharging"""
        # Set initial state to just above the DoD limit
        initial_soc = 1.0 - self.battery.depth_of_discharge + 0.05
        self.battery.force_set_soc(initial_soc)

        # Try to discharge more than allowed by DoD
        big_discharge = -self.battery.capacity  # Try to completely discharge
        self.battery.charge(big_discharge)
        
        # Check that SOC didn't go below DoD limit
        min_allowed_soc = 1.0 - self.battery.depth_of_discharge
        self.assertGreaterEqual(self.battery.soc[self.battery.time_step], min_allowed_soc - 1e-2)

    def test_standby_loss_cannot_push_battery_below_depth_of_discharge_limit(self):
        battery = Battery(
            capacity=100.0,
            nominal_power=100.0,
            initial_soc=1.0,
            depth_of_discharge=0.8,
            efficiency=1.0,
            loss_coefficient=0.1,
            capacity_loss_coefficient=0.0,
            power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
            capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
            seconds_per_time_step=3600,
        )
        battery.episode_tracker = MagicMock()
        battery.episode_tracker.episode_time_steps = 3
        battery.reset()
        battery.update_electricity_consumption = MagicMock()

        battery.charge(-100.0)

        self.assertGreaterEqual(float(battery.soc[0]), 0.2 - 1e-9)
        self.assertAlmostEqual(float(battery.soc[0]), 0.2, places=6)

    def test_capacity_limit(self):
        """Test that the battery respects the capacity limit when charging"""
        # Set initial state to high SOC
        self.battery.force_set_soc(0.9)
        
        # Try to charge more than capacity allows
        big_charge = self.battery.capacity  # Try to charge with full capacity worth of energy
        self.battery.charge(big_charge)
        
        # Check that SOC didn't exceed 100%
        self.assertLessEqual(self.battery.soc[self.battery.time_step], 1.0 + 1e-6)  # Allow for floating-point error

    def test_degrade(self):
        """Test the battery degradation calculation"""
        # Set a known state
        self.battery.force_set_soc(0.5)
        
        # Charge with a known amount of energy
        self.battery.charge(10.0)
        
        # Manually calculate expected degradation
        energy_balance = self.battery.energy_balance[self.battery.time_step]
        expected_degradation = self.battery.capacity_loss_coefficient * self.battery.capacity * abs(energy_balance) / (2 * self.battery.degraded_capacity)
        
        # Call the degrade method directly and compare
        actual_degradation = self.battery.degrade()
        self.assertAlmostEqual(actual_degradation, expected_degradation, places=6)
        
        # Verify capacity history has been updated after charging
        self.assertEqual(len(self.battery.capacity_history), 2)
        self.assertLess(self.battery.capacity_history[1], self.battery.capacity_history[0])

    def test_get_max_input_power(self):
        """Test the get_max_input_power method at different SOC levels"""
        # Test at different SOC levels
        for soc in [0.1, 0.5, 0.9]:
            self.battery.force_set_soc(soc)
            max_power = self.battery.get_max_input_power()
            
            # Power should be within reasonable bounds and related to nominal power
            self.assertGreaterEqual(max_power, 0.0)
            self.assertLessEqual(max_power, self.battery.nominal_power * 1.1)  # Allow for some tolerance
            
            # At high SOC, max power should be lower
            if soc > 0.8:
                self.assertLess(max_power, self.battery.nominal_power)

    def test_get_current_efficiency(self):
        """Test the efficiency calculation based on power level"""
        # Test get_current_efficiency at different power levels
        for power_level in [1.0, 5.0, 10.0]:
            efficiency = self.battery.get_current_efficiency(power_level)
            
            # Efficiency should be between 0 and 1
            self.assertGreaterEqual(efficiency, 0.0)
            self.assertLessEqual(efficiency, 1.0)

    def test_force_set_soc(self):
        """Test the force_set_soc method"""
        # Try setting SOC to specific values
        test_socs = [0.0, 0.3, 0.75, 1.0]
        
        for soc in test_socs:
            self.battery.force_set_soc(soc)
            self.assertAlmostEqual(self.battery.soc[self.battery.time_step], soc)
        
        # Test with invalid SOC values
        with self.assertRaises(AttributeError):
            self.battery.force_set_soc(-0.1)
        
        with self.assertRaises(AttributeError):
            self.battery.force_set_soc(1.1)

    def test_reset(self):
        """Test the reset method"""
        # Make some changes to the battery state
        self.battery.force_set_soc(0.7)
        self.battery.charge(5.0)
        self.battery.charge(-2.0)
        
        # Reset the battery
        self.battery.reset()
        
        # Check that state has been reset
        self.assertEqual(self.battery.time_step, 0)
        self.assertEqual(len(self.battery.efficiency_history), 1)
        self.assertEqual(len(self.battery.capacity_history), 1)
        self.assertEqual(self.battery.capacity_history[0], self.battery.capacity)

    def test_get_metadata(self):
        """Test the get_metadata method"""
        metadata = self.battery.get_metadata()
        
        # Check that required keys exist
        self.assertIn('depth_of_discharge', metadata)
        self.assertIn('capacity_loss_coefficient', metadata)
        self.assertIn('power_efficiency_curve', metadata)
        self.assertIn('capacity_power_curve', metadata)
        
        # Check that values match
        self.assertEqual(metadata['depth_of_discharge'], self.battery.depth_of_discharge)
        self.assertEqual(metadata['capacity_loss_coefficient'], self.battery.capacity_loss_coefficient)

    def test_as_dict(self):
        """Test the as_dict method for rendering"""
        # Set a known state
        self.battery.force_set_soc(0.6)
        self.battery.charge(5.0)
        
        # Get dict representation
        dict_repr = self.battery.as_dict()
        
        # Check that required keys exist
        self.assertIn('Battery Soc-%', dict_repr)
        self.assertIn('Battery (Dis)Charge-kWh', dict_repr)
        
        # Check values
        self.assertEqual(dict_repr['Battery Soc-%'], self.battery.soc[self.battery.time_step])
        self.assertEqual(dict_repr['Battery (Dis)Charge-kWh'], self.battery.energy_balance[self.battery.time_step])

    @patch('citylearn.data.DataSet')
    def test_autosize(self, mock_dataset):
        """Test the autosize method"""
        # Set up mock dataset
        mock_instance = mock_dataset.return_value
        mock_instance.get_battery_sizing_data.return_value = DataSet().get_battery_sizing_data()
        
        # Test autosizing
        capacity, nominal_power, dod, efficiency, loss_coef, capacity_loss_coef = self.battery.autosize(
            demand=10.0, 
            duration=2.0,
            safety_factor=1.2
        )
        
        # Verify returned values
        self.assertGreater(capacity, 0)
        self.assertGreater(nominal_power, 0)
        # A NaN datasheet value is returned as NaN; the setters then use the default or draw it.
        self.assertTrue(math.isnan(dod) or 0 <= dod <= 1)
        self.assertTrue(math.isnan(efficiency) or 0 < efficiency <= 1)
        
        # Check autosize_config was created
        self.assertIsNotNone(self.battery._autosize_config)


if __name__ == '__main__':
    unittest.main()
