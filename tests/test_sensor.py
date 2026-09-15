"""Import the actual sensor platform with strict Home Assistant API stubs."""
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class SensorEntityStub:
    pass


class CoordinatorEntityStub:
    def __init__(self, coordinator):
        self.coordinator = coordinator


def load_sensor():
    """Keep power and apparent-power constants separate, as Home Assistant does.

    Reference: home-assistant/core, homeassistant/const.py (2026.9.0).
    Stubs deliberately do not invent constants via __getattr__.
    """
    modules = {name: ModuleType(name) for name in (
        "homeassistant", "homeassistant.components", "homeassistant.components.sensor",
        "homeassistant.config_entries", "homeassistant.const", "homeassistant.core",
        "homeassistant.helpers", "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator", "fh3x_sensor_test",
    )}
    sensor = modules["homeassistant.components.sensor"]
    sensor.SensorDeviceClass = SimpleNamespace(**{name: name.lower() for name in (
        "VOLTAGE", "CURRENT", "POWER", "APPARENT_POWER", "ENERGY", "FREQUENCY",
        "BATTERY", "TEMPERATURE",
    )})
    sensor.SensorStateClass = SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing")
    sensor.SensorEntity = SensorEntityStub
    sensor.SensorEntityDescription = SimpleNamespace
    constants = modules["homeassistant.const"]
    constants.PERCENTAGE = "%"
    for name, values in {
        "UnitOfPower": {"WATT": "W", "KILO_WATT": "kW"},
        "UnitOfApparentPower": {"VOLT_AMPERE": "VA"},
        "UnitOfElectricCurrent": {"AMPERE": "A"},
        "UnitOfElectricPotential": {"VOLT": "V"},
        "UnitOfEnergy": {"KILO_WATT_HOUR": "kWh"},
        "UnitOfFrequency": {"HERTZ": "Hz"},
        "UnitOfTemperature": {"CELSIUS": "°C"},
    }.items():
        setattr(constants, name, SimpleNamespace(**values))
    modules["homeassistant.config_entries"].ConfigEntry = object
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntityStub
    modules["fh3x_sensor_test"].__path__ = [str(
        Path(__file__).resolve().parents[1] / "custom_components" / "pylon_fh3x"
    )]
    with patch.dict(sys.modules, modules):
        return importlib.import_module("fh3x_sensor_test.sensor")


class SensorTests(unittest.TestCase):
    def test_platform_imports_and_uses_valid_power_units(self):
        platform = load_sensor()
        for description in platform.SENSOR_TYPES:
            with self.subTest(key=description.key):
                device_class = getattr(description, "device_class", None)
                if device_class == "apparent_power":
                    self.assertEqual(description.native_unit_of_measurement, "VA")
                elif device_class == "power":
                    self.assertEqual(description.native_unit_of_measurement, "W")

    def test_rejected_value_is_unknown_and_recovers_in_sensor(self):
        platform = load_sensor()
        description = next(item for item in platform.SENSOR_TYPES if item.key == "total_grid_import")
        coordinator = SimpleNamespace(data={"total_grid_import": 2025.52})
        entry = SimpleNamespace(data={"host": "test"}, entry_id="test", title="Test")
        sensor = platform.PylontechSensor(coordinator, description, entry)
        self.assertEqual(sensor.native_value, 2025.52)
        coordinator.data = {}
        self.assertIsNone(sensor.native_value)
        coordinator.data = {"total_grid_import": 2025.53}
        self.assertEqual(sensor.native_value, 2025.53)
