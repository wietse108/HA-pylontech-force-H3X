"""DataUpdateCoordinator for Pylontech Force H3X."""
import asyncio
import logging
import struct
from datetime import timedelta

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .validation import TelemetryValidator

_LOGGER = logging.getLogger(__name__)

BATTERY_STATUS_MAP = {
    0: "Sleep",
    1: "Charging",
    2: "Discharging",
    3: "Idle",
    4: "Standby",
    5: "Run",
    6: "Fault",
    7: "Offline",
}

# =========================================================
# Modbus register decoding helpers
# =========================================================
def get_16bit_uint(regs, idx):
    return regs[idx]

def get_16bit_int(regs, idx):
    return struct.unpack('>h', struct.pack('>H', regs[idx]))[0]

def get_32bit_int(regs, idx):
    return struct.unpack('>i', struct.pack('>HH', regs[idx], regs[idx+1]))[0]

def get_32bit_float(regs, idx):
    return struct.unpack('>f', struct.pack('>HH', regs[idx], regs[idx+1]))[0]


async def _modbus_read(client, address, count, target_id):
    
    try:
        return await client.read_holding_registers(address=address, count=count, slave=target_id)
    except TypeError:
        pass
    try:
        return await client.read_holding_registers(address=address, count=count, unit=target_id)
    except TypeError:
        pass
    return await client.read_holding_registers(address=address, count=count, device_id=target_id)


class PylontechCoordinator(DataUpdateCoordinator):
    """Coordinate Modbus reads and writes for the inverter."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        self.client = AsyncModbusTcpClient(host=host, port=port, timeout=5)
        self.host = host
        self._validator = TelemetryValidator()
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def safe_read(self, address, count, slave):
        
        # Space requests to avoid overwhelming the inverter's Modbus interface.
        await asyncio.sleep(0.1) 
        res = await _modbus_read(self.client, address, count, slave)
        if res is None or res.isError():
            _LOGGER.warning("error while reading adress %s (Slave %s): %s", address, slave, res)
            return None
        registers = getattr(res, "registers", None)
        if (
            not isinstance(registers, (list, tuple))
            or len(registers) != count
            or any(type(word) is not int or not 0 <= word <= 0xFFFF for word in registers)
        ):
            _LOGGER.warning(
                "Ignoring malformed Modbus response at address %s (Slave %s): expected %s uint16 registers",
                address, slave, count,
            )
            return None
        return registers

    async def _async_update_data(self):
        """Fetch data from the inverter via Modbus."""
        try:
            if not self.client.connected:
                await self.client.connect()

            data = {}

            # Read frequently changing inverter data in two contiguous blocks.
            r_inverter_main = await self.safe_read(30100, 48, 2)
            if r_inverter_main:
                data["ac_total_power"] = get_32bit_int(r_inverter_main, 0)
                data["grid_total_power"] = get_32bit_int(r_inverter_main, 8)
                data["inverter_status"] = get_16bit_uint(r_inverter_main, 15)

                data["pv1_voltage"] = get_16bit_uint(r_inverter_main, 19) * 0.1
                data["pv1_current"] = get_16bit_uint(r_inverter_main, 20) * 0.1
                data["pv2_voltage"] = get_16bit_uint(r_inverter_main, 21) * 0.1
                data["pv2_current"] = get_16bit_uint(r_inverter_main, 22) * 0.1
                data["pv3_voltage"] = get_16bit_uint(r_inverter_main, 23) * 0.1
                data["pv3_current"] = get_16bit_uint(r_inverter_main, 24) * 0.1

                data["pv_total_power"] = get_32bit_int(r_inverter_main, 27)
                data["pv_total_energy"] = get_32bit_float(r_inverter_main, 29)
                data["grid_voltage_r"] = get_16bit_uint(r_inverter_main, 31) * 0.1
                data["ac_current_r"] = get_16bit_uint(r_inverter_main, 32) * 0.1
                data["grid_voltage_s"] = get_16bit_uint(r_inverter_main, 33) * 0.1
                data["ac_current_s"] = get_16bit_uint(r_inverter_main, 34) * 0.1
                data["grid_voltage_t"] = get_16bit_uint(r_inverter_main, 35) * 0.1
                data["ac_current_t"] = get_16bit_uint(r_inverter_main, 36) * 0.1
                data["ac_frequency"] = get_16bit_uint(r_inverter_main, 40) * 0.01
                data["inverter_temperature"] = get_16bit_int(r_inverter_main, 46) * 0.1
                data["heatsink_temperature"] = get_16bit_int(r_inverter_main, 47) * 0.1

            # Per-phase grid current/power (CT clamp measurements at the grid connection).
            r_grid_phases = await self.safe_read(30183, 9, 2)
            if r_grid_phases:
                data["grid_current_r"] = get_16bit_int(r_grid_phases, 0) * 0.1
                data["grid_current_s"] = get_16bit_int(r_grid_phases, 1) * 0.1
                data["grid_current_t"] = get_16bit_int(r_grid_phases, 2) * 0.1
                data["grid_power_r"] = get_32bit_int(r_grid_phases, 3)
                data["grid_power_s"] = get_32bit_int(r_grid_phases, 5)
                data["grid_power_t"] = get_32bit_int(r_grid_phases, 7)

            r_inverter_battery = await self.safe_read(30156, 30, 2)
            if r_inverter_battery:
                data["total_grid_import"] = get_32bit_float(r_inverter_battery, 0)
                data["total_grid_export"] = get_32bit_float(r_inverter_battery, 2)

                raw_status = get_16bit_uint(r_inverter_battery, 5)
                data["battery_status"] = BATTERY_STATUS_MAP.get(raw_status, f"Unknown ({raw_status})")
                data["battery_power"] = get_32bit_int(r_inverter_battery, 6)
                data["battery_voltage"] = get_16bit_uint(r_inverter_battery, 8) * 0.1
                data["battery_current"] = get_16bit_int(r_inverter_battery, 9) * 0.1
                data["eps_power"] = get_32bit_int(r_inverter_battery, 16)
                data["total_battery_charge"] = get_32bit_float(r_inverter_battery, 18)
                data["total_battery_discharge"] = get_32bit_float(r_inverter_battery, 20)
                data["battery_soc"] = get_16bit_uint(r_inverter_battery, 26)

            # Keep independent control ranges separate from telemetry blocks.
            r_active = await self.safe_read(40400, 3, 2)
            if r_active:
                data["active_power_control_mode"] = get_16bit_uint(r_active, 0)
                data["meter_export_power_max"] = get_32bit_int(r_active, 1)

            r_hp = await self.safe_read(40848, 1, 2)
            if r_hp:
                data["heat_pump"] = get_16bit_uint(r_hp, 0)

            r_ems = await self.safe_read(40901, 26, 2)
            if r_ems:
                data["charge_discharge_power"] = get_16bit_int(r_ems, 0)
                data["charge_limit_soc"] = get_16bit_uint(r_ems, 1)
                data["discharge_limit_soc"] = get_16bit_uint(r_ems, 2)
                data["ems_mode"] = str(get_16bit_uint(r_ems, 6))
                data["period_1"] = get_16bit_uint(r_ems, 7)
                data["period_2"] = get_16bit_uint(r_ems, 13)
                data["period_3"] = get_16bit_uint(r_ems, 19)
                data["period_4"] = get_16bit_uint(r_ems, 25)

            # Read all BMS values from one contiguous slave-1 block.
            r_bms = await self.safe_read(5123, 30, 1)
            if r_bms:
                data["bms_voltage"] = get_16bit_uint(r_bms, 0) * 0.1
                data["bms_temperature"] = get_16bit_int(r_bms, 3) * 0.1
                data["bms_soc"] = get_16bit_uint(r_bms, 4)
                data["bms_cycles"] = get_16bit_uint(r_bms, 5)
                data["bms_cell_voltage_max"] = get_16bit_uint(r_bms, 13) * 0.001
                data["bms_cell_voltage_min"] = get_16bit_uint(r_bms, 14) * 0.001
                data["bms_soh"] = get_16bit_uint(r_bms, 29)

            # Validate before exposing values or deriving any power sensors.
            data = self._validator.validate(data)
            if not data:
                raise UpdateFailed("No data received out of inverter.")

            return data

        except UpdateFailed:
            raise
        except ModbusException as err:
            raise UpdateFailed(f"error with modbus communication: {err}")
        except Exception as err:
            raise UpdateFailed(f"unexpected error: {err}")

    async def async_write_register(self, address: int, value: int, slave: int = 2) -> bool:
        """Write a signed or unsigned 16-bit value to a Modbus register."""
        try:
            if not self.client.connected:
                await self.client.connect()

            if value < 0:
                value = value & 0xFFFF

            # Support the slave-ID keyword used by multiple pymodbus versions.
            try:
                res = await self.client.write_register(address=address, value=value, slave=slave)
            except TypeError:
                try:
                    res = await self.client.write_register(address=address, value=value, unit=slave)
                except TypeError:
                    res = await self.client.write_register(address=address, value=value, device_id=slave)

            if res.isError():
                _LOGGER.error("error whil writing to register %s: %s", address, res)
                return False

            
            await self.async_request_refresh()
            return True

        except Exception as err:
            _LOGGER.error("Unexpected error whil writing to: %s", err)
            return False
        
    async def async_write_register_32bit(self, address: int, value: int, slave: int = 2) -> bool:
        """Write a 32-bit signed value (S32) as two consecutive 16-bit registers."""
        try:
            if not self.client.connected:
                await self.client.connect()

            # Split the signed value into two big-endian 16-bit registers.
            packed = struct.pack('>i', value)
            high, low = struct.unpack('>HH', packed)

            try:
                res = await self.client.write_registers(address=address, values=[high, low], slave=slave)
            except TypeError:
                try:
                    res = await self.client.write_registers(address=address, values=[high, low], unit=slave)
                except TypeError:
                    res = await self.client.write_registers(address=address, values=[high, low], device_id=slave)

            if res.isError():
                _LOGGER.error("Error writing 32-bit register %s: %s", address, res)
                return False

            await self.async_request_refresh()
            return True

        except Exception as err:
            _LOGGER.error("Unexpected error writing 32-bit register: %s", err)
            return False
