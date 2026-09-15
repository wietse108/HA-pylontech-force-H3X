"""Exercise real Modbus decoding with a fake transport, without a running HA host.

Run with: python -m unittest discover -s tests -v
"""
import importlib
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


class CoordinatorStub:
    def __init__(self, *args, **kwargs):
        self.data = {}


class UpdateFailed(Exception):
    pass


def load_coordinator():
    """Stub framework imports only; run the integration's actual coordinator."""
    modules = {}
    for name in (
        "pymodbus", "pymodbus.client", "pymodbus.exceptions",
        "homeassistant", "homeassistant.core", "homeassistant.helpers",
        "homeassistant.helpers.update_coordinator", "fh3x_under_test",
    ):
        modules[name] = ModuleType(name)
    modules["pymodbus.client"].AsyncModbusTcpClient = lambda **kwargs: SimpleNamespace(
        connected=True, read_holding_registers=AsyncMock()
    )
    modules["pymodbus.exceptions"].ModbusException = type("ModbusException", (Exception,), {})
    modules["homeassistant.core"].HomeAssistant = object
    framework = modules["homeassistant.helpers.update_coordinator"]
    framework.DataUpdateCoordinator = CoordinatorStub
    framework.UpdateFailed = UpdateFailed
    modules["fh3x_under_test"].__path__ = [str(
        Path(__file__).resolve().parents[1] / "custom_components" / "pylon_fh3x"
    )]
    with patch.dict(sys.modules, modules):
        return (importlib.import_module("fh3x_under_test.coordinator"),
                importlib.import_module("fh3x_under_test.validation"))


coordinator_module, validation_module = load_coordinator()


def put_int(registers, offset, value):
    registers[offset:offset + 2] = struct.unpack(">HH", struct.pack(">i", value))


def put_float(registers, offset, value):
    registers[offset:offset + 2] = struct.unpack(">HH", struct.pack(">f", value))


def valid_blocks():
    """One normal sample, with unused register words left at zero."""
    blocks = {30100: [0] * 48, 30183: [0] * 9, 30156: [0] * 30,
              40400: [0] * 3, 40848: [0], 40901: [0] * 26, 5123: [0] * 30}
    main = blocks[30100]
    put_int(main, 0, 3000)
    put_int(main, 8, -1000)
    main[15] = 1
    main[19:25] = [4000, 30, 4000, 30, 0, 0]
    put_int(main, 27, 2400)
    put_float(main, 29, 1000)
    main[31:37] = [2300, 43, 2300, 43, 2300, 43]
    main[40], main[46], main[47] = 5000, 300, 350
    battery = blocks[30156]
    for offset in (0, 2, 18, 20):
        put_float(battery, offset, 1000)
    battery[5], battery[8], battery[9], battery[26] = 2, 4000, 25, 50
    put_int(battery, 6, 1000)
    blocks[5123][0:6] = [4000, 0, 0, 250, 50, 100]
    blocks[5123][13:15] = [3350, 3300]
    blocks[5123][29] = 100
    return blocks


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = coordinator_module.PylontechCoordinator(None, "test", 502)
        self.blocks = valid_blocks()
        self.now = 0
        self.coordinator.client.read_holding_registers.side_effect = self.response
        for patcher in (
            patch.object(coordinator_module.asyncio, "sleep", new=AsyncMock()),
            patch.object(validation_module, "time", SimpleNamespace(monotonic=lambda: self.now)),
            patch.object(validation_module._LOGGER, "warning"),
            patch.object(coordinator_module._LOGGER, "warning"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def response(self, *, address, count, **kwargs):
        return SimpleNamespace(isError=lambda: False, registers=self.blocks[address])

    async def poll(self):
        self.now += 5
        data = await self.coordinator._async_update_data()
        self.coordinator.data = data
        return data

    async def test_impossible_battery_power_never_reaches_ha_data(self):
        put_int(self.blocks[30156], 6, 700_000_000)
        data = await self.poll()
        self.assertIsNone(data.get("battery_power"))
        self.assertEqual(data["battery_soc"], 50)

    async def test_corrupt_sources_cannot_cancel_into_valid_load(self):
        put_int(self.blocks[30100], 0, 700_000_000)
        put_int(self.blocks[30100], 8, -699_999_000)
        data = await self.poll()
        self.assertIsNone(data.get("load_power"))

    async def test_short_response_is_rejected_before_decoding(self):
        self.blocks[30156] = [0] * 8
        self.assertIsNone(await self.coordinator.safe_read(30156, 30, 2))

    async def test_all_direct_power_registers_reject_both_signs_of_spikes(self):
        for address, offset, key in (
            (30100, 0, "ac_total_power"), (30100, 8, "grid_total_power"),
            (30100, 27, "pv_total_power"), (30156, 6, "battery_power"),
            (30156, 16, "eps_power"), (30183, 3, "grid_power_r"),
            (30183, 5, "grid_power_s"), (30183, 7, "grid_power_t"),
        ):
            for value in (700_000_000, -700_000_000, 2**31 - 1, -(2**31)):
                with self.subTest(key=key, value=value):
                    self.blocks = valid_blocks()
                    put_int(self.blocks[address], offset, value)
                    self.assertIsNone((await self.poll()).get(key))

    async def test_invalid_voltage_current_soc_soh_and_temperature(self):
        for address, offset, key, raw in (
            (30100, 19, "pv1_voltage", 65535),
            (30100, 20, "pv1_current", 65535),
            (30100, 31, "grid_voltage_r", 65535),
            (30100, 32, "ac_current_r", 65535),
            (30100, 40, "ac_frequency", 65535),
            (30100, 46, "inverter_temperature", 32767),
            (30100, 47, "heatsink_temperature", 32768),
            (30156, 8, "battery_voltage", 65535),
            (30156, 9, "battery_current", 32768),
            (30156, 26, "battery_soc", 101),
            (5123, 0, "bms_voltage", 65535),
            (5123, 3, "bms_temperature", 32767),
            (5123, 4, "bms_soc", 101),
            (5123, 5, "bms_cycles", 65535),
            (5123, 13, "bms_cell_voltage_max", 65535),
            (5123, 14, "bms_cell_voltage_min", 65535),
            (5123, 29, "bms_soh", 101),
            (30183, 0, "grid_current_r", 32767),
            (40901, 1, "charge_limit_soc", 101),
        ):
            with self.subTest(key=key):
                self.blocks = valid_blocks()
                self.blocks[address][offset] = raw
                self.assertIsNone((await self.poll()).get(key))

    async def test_invalid_sources_remove_only_their_derived_sensors(self):
        self.blocks[30100][19] = 65535
        self.blocks[30100][31] = 65535
        put_int(self.blocks[30183], 5, 700_000_000)
        data = await self.poll()
        for key in ("pv1_power", "ac_power_r", "load_power_r", "load_power_s"):
            self.assertIsNone(data.get(key), key)
        self.assertEqual(data["pv2_power"], 1200)
        self.assertEqual(data["load_power_t"], 989)

    async def test_valid_charging_export_negative_temperatures_and_abrupt_changes(self):
        await self.poll()
        put_int(self.blocks[30156], 6, -15000)
        self.blocks[30156][9] = (-500) & 0xFFFF
        self.blocks[5123][3] = (-200) & 0xFFFF
        put_int(self.blocks[30100], 0, -22500)
        put_int(self.blocks[30100], 8, -100000)
        put_int(self.blocks[30183], 3, -50000)
        self.blocks[30183][0] = (-2000) & 0xFFFF
        data = await self.poll()
        self.assertEqual(data["battery_power"], -15000)
        self.assertEqual(data["battery_current"], -50)
        self.assertEqual(data["bms_temperature"], -20)
        self.assertEqual(data["ac_total_power"], -22500)
        self.assertEqual(data["load_power"], -122500)
        self.assertEqual(data["grid_power_r"], -50000)
        self.assertEqual(data["grid_current_r"], -200)

    async def test_zero_readings_and_full_soc_are_valid(self):
        self.blocks = {address: [0] * len(words) for address, words in self.blocks.items()}
        self.blocks[30156][26] = 100
        data = await self.poll()
        for key in ("battery_power", "battery_voltage", "battery_current", "pv_total_power",
                    "ac_frequency", "load_power", "bms_cell_voltage_min"):
            self.assertEqual(data[key], 0, key)
        self.assertEqual(data["battery_soc"], 100)

    async def test_rejected_sample_is_not_clamped_or_replaced_with_previous_value(self):
        self.assertEqual((await self.poll())["battery_power"], 1000)
        put_int(self.blocks[30156], 6, 700_000_000)
        self.assertIsNone((await self.poll()).get("battery_power"))
        put_int(self.blocks[30156], 6, 2000)
        self.assertEqual((await self.poll())["battery_power"], 2000)

    async def test_malformed_blocks_leave_other_blocks_working(self):
        for words in (None, [], [0] * 29, [0] * 31, [-1] * 30,
                      [65536] * 30, [True] * 30, [1.0] * 30, "x" * 30):
            with self.subTest(words=repr(words)[:40]):
                self.blocks[30156] = words
                data = await self.poll()
                self.assertIsNone(data.get("battery_power"))
                self.assertEqual(data["ac_total_power"], 3000)

    async def test_empty_or_error_responses_are_not_decoded(self):
        for response in (None, SimpleNamespace(isError=lambda: True),
                         SimpleNamespace(isError=lambda: False)):
            self.coordinator.client.read_holding_registers.side_effect = None
            self.coordinator.client.read_holding_registers.return_value = response
            self.assertIsNone(await self.coordinator.safe_read(30100, 48, 2))

    async def test_no_usable_blocks_fails_the_update(self):
        self.blocks = {address: [] for address in self.blocks}
        with self.assertRaises(UpdateFailed):
            await self.poll()

    async def test_transport_error_fails_the_update(self):
        self.coordinator.client.read_holding_registers.side_effect = coordinator_module.ModbusException("offline")
        with self.assertRaises(UpdateFailed):
            await self.poll()

    async def test_reversed_cell_voltage_extrema_are_rejected(self):
        self.blocks[5123][13:15] = [3200, 3300]
        data = await self.poll()
        self.assertIsNone(data.get("bms_cell_voltage_min"))
        self.assertIsNone(data.get("bms_cell_voltage_max"))
        self.assertEqual(data["bms_soc"], 50)

    async def test_nonfinite_negative_and_huge_energy_values_are_rejected(self):
        for address, offset, key in (
            (30100, 29, "pv_total_energy"), (30156, 0, "total_grid_import"),
            (30156, 2, "total_grid_export"), (30156, 18, "total_battery_charge"),
            (30156, 20, "total_battery_discharge"),
        ):
            for value in (float("nan"), float("inf"), float("-inf"), -1, 1e30):
                with self.subTest(key=key, value=value):
                    self.blocks = valid_blocks()
                    put_float(self.blocks[address], offset, value)
                    self.assertIsNone((await self.poll()).get(key))

    async def test_counters_require_confirmation_at_startup(self):
        first = await self.poll()
        for key in validation_module.COUNTER_RATES:
            self.assertIsNone(first.get(key), key)
        second = await self.poll()
        self.assertEqual(second["total_battery_charge"], 1000)
        self.assertEqual(second["bms_cycles"], 100)

    async def test_single_startup_counter_spike_is_never_published(self):
        put_float(self.blocks[30156], 18, 900_000)
        self.assertIsNone((await self.poll()).get("total_battery_charge"))
        put_float(self.blocks[30156], 18, 1000)
        self.assertIsNone((await self.poll()).get("total_battery_charge"))
        self.assertEqual((await self.poll())["total_battery_charge"], 1000)

    async def test_counter_spike_never_poisons_baseline_even_when_repeated(self):
        await self.poll()
        await self.poll()
        put_float(self.blocks[30156], 18, 5000)
        for _ in range(3):
            self.assertIsNone((await self.poll()).get("total_battery_charge"))
        put_float(self.blocks[30156], 18, 1000.1)
        self.assertAlmostEqual((await self.poll())["total_battery_charge"], 1000.1, places=3)

    async def test_counter_dip_is_skipped_and_real_reset_is_confirmed(self):
        await self.poll()
        await self.poll()
        put_float(self.blocks[30156], 18, 0)
        self.assertIsNone((await self.poll()).get("total_battery_charge"))
        put_float(self.blocks[30156], 18, 1000)
        self.assertEqual((await self.poll())["total_battery_charge"], 1000)
        put_float(self.blocks[30156], 18, 0)
        self.assertIsNone((await self.poll()).get("total_battery_charge"))
        self.assertEqual((await self.poll())["total_battery_charge"], 0)

    async def test_counter_gap_uses_elapsed_time_since_last_valid_value(self):
        await self.poll()
        await self.poll()
        self.now += 3600
        put_float(self.blocks[30156], 18, 1020)
        self.assertEqual((await self.poll())["total_battery_charge"], 1020)

    async def test_missing_or_invalid_sample_breaks_counter_confirmation(self):
        await self.poll()
        put_float(self.blocks[30156], 18, float("nan"))
        await self.poll()
        put_float(self.blocks[30156], 18, 1000)
        self.assertIsNone((await self.poll()).get("total_battery_charge"))
        self.assertEqual((await self.poll())["total_battery_charge"], 1000)

    async def test_large_valid_float32_counter_keeps_working_at_its_precision(self):
        put_float(self.blocks[30156], 18, 2_000_000)
        await self.poll()
        await self.poll()
        put_float(self.blocks[30156], 18, 2_000_000.125)
        self.assertEqual((await self.poll())["total_battery_charge"], 2_000_000.125)

    async def test_repeated_bad_value_logs_once_until_recovery(self):
        put_int(self.blocks[30156], 6, 700_000_000)
        await self.poll()
        await self.poll()
        self.assertEqual(validation_module._LOGGER.warning.call_count, 1)
        put_int(self.blocks[30156], 6, 1000)
        await self.poll()
        put_int(self.blocks[30156], 6, 700_000_000)
        await self.poll()
        self.assertEqual(validation_module._LOGGER.warning.call_count, 2)

    async def test_exact_negative_energy_values_from_reported_logs(self):
        for address, offset, key, value in (
            (30156, 0, "total_grid_import", -1.46215599273087e37),
            (30100, 29, "pv_total_energy", -4.92869640932547e-31),
            (30156, 18, "total_battery_charge", -5.1825399857844e-17),
        ):
            with self.subTest(key=key):
                put_float(self.blocks[address], offset, value)
                self.assertIsNone((await self.poll()).get(key))

    async def test_reported_small_counter_decrease_is_never_treated_as_reset(self):
        put_float(self.blocks[30156], 0, 2025.52001953125)
        await self.poll()
        await self.poll()
        for value in (2025.50854492188, 2025.50854492188, 2025.515):
            put_float(self.blocks[30156], 0, value)
            self.assertIsNone((await self.poll()).get("total_grid_import"))
        put_float(self.blocks[30156], 0, 2025.53)
        self.assertAlmostEqual((await self.poll())["total_grid_import"], 2025.53, places=3)


if __name__ == "__main__":
    unittest.main()
