"""Reject corrupt Force H3X telemetry before publishing coordinator data.

These are deliberately broad sanity limits, not operating/protection settings.
See docs/telemetry-validation.md for their scope and sources.
"""
import logging
import math
import time

_LOGGER = logging.getLogger(__name__)

INVERTER_POWER_LIMIT = 30_000
PV_POWER_LIMIT = 40_000
# The CT measures the whole installation, not just the inverter output.
GRID_POWER_LIMIT = 1_000_000
# Match HA Recorder's reset boundary for TOTAL_INCREASING. Smaller dips
# must never be published as resets, even when the same bad read repeats.
COUNTER_RESET_RATIO = 0.9

VALUE_RANGES = {
    "ac_total_power": (-INVERTER_POWER_LIMIT, INVERTER_POWER_LIMIT),
    "battery_power": (-INVERTER_POWER_LIMIT, INVERTER_POWER_LIMIT),
    "eps_power": (-INVERTER_POWER_LIMIT, INVERTER_POWER_LIMIT),
    "grid_total_power": (-GRID_POWER_LIMIT, GRID_POWER_LIMIT),
    "pv_total_power": (0, PV_POWER_LIMIT),
    "battery_voltage": (0, 1000),
    "bms_voltage": (0, 1000),
    "battery_current": (-100, 100),
    "ac_frequency": (0, 70),
    "inverter_temperature": (-50, 150),
    "heatsink_temperature": (-50, 150),
    "bms_temperature": (-50, 100),
    "bms_cell_voltage_min": (0, 5),
    "bms_cell_voltage_max": (0, 5),
    "battery_soc": (0, 100),
    "bms_soc": (0, 100),
    "bms_soh": (0, 100),
    "bms_cycles": (0, 65534),
    "inverter_status": (0, 2),
    "charge_discharge_power": (-1000, 1000),
    "charge_limit_soc": (0, 100),
    "discharge_limit_soc": (0, 100),
    "meter_export_power_max": (-GRID_POWER_LIMIT, 0),
    "heat_pump": (0, 1),
    **{f"period_{n}": (0, 1) for n in range(1, 5)},
    **{f"pv{n}_voltage": (0, 1100) for n in range(1, 4)},
    **{f"pv{n}_current": (0, 50) for n in range(1, 4)},
    **{f"grid_voltage_{phase}": (0, 350) for phase in "rst"},
    **{f"ac_current_{phase}": (0, 100) for phase in "rst"},
    **{f"grid_current_{phase}": (-1000, 1000) for phase in "rst"},
    **{f"grid_power_{phase}": (-350_000, 350_000) for phase in "rst"},
}

# Maximum counter growth per second, using the same generous power limits.
COUNTER_RATES = {
    "pv_total_energy": PV_POWER_LIMIT / 3_600_000,
    "total_grid_import": GRID_POWER_LIMIT / 3_600_000,
    "total_grid_export": GRID_POWER_LIMIT / 3_600_000,
    "total_battery_charge": INVERTER_POWER_LIMIT / 3_600_000,
    "total_battery_discharge": INVERTER_POWER_LIMIT / 3_600_000,
    "bms_cycles": 100 / 86400,
}
VALUE_RANGES.update({key: (0, 10_000_000) for key in COUNTER_RATES if key != "bms_cycles"})


class TelemetryValidator:
    """Filter each poll without filling gaps with stale or fabricated numbers."""

    def __init__(self):
        self._counters = {}
        self._pending_counters = {}
        self._invalid_keys = set()

    @staticmethod
    def _counter_step_valid(key, previous, current, elapsed):
        # Float32 counters lose precision as lifetime totals grow. Allow two
        # float32 ULPs as well as the device's small, batched counter updates.
        tolerance = 1 if key == "bms_cycles" else max(
            0.1, 2 ** (math.frexp(max(previous, current))[1] - 23)
        )
        return 0 <= current - previous <= COUNTER_RATES[key] * max(0, elapsed) + tolerance

    def _counter_valid(self, key, value, now):
        previous = self._counters.get(key)
        if previous is not None:
            last_value, last_time = previous
            if self._counter_step_valid(key, last_value, value, now - last_time):
                self._counters[key] = (value, now)
                self._pending_counters.pop(key, None)
                return True
            # Reject impossible increases and small dips even when repeated.
            # Only a drop of more than 10% can be a reset candidate.
            if value >= COUNTER_RESET_RATIO * last_value:
                self._pending_counters.pop(key, None)
                return False

        # Confirm startup values and genuine meter resets with a second
        # consecutive, consistent sample before exposing a TOTAL_INCREASING.
        pending = self._pending_counters.get(key)
        if pending is not None and self._counter_step_valid(
            key, pending[0], value, now - pending[1]
        ):
            self._counters[key] = (value, now)
            self._pending_counters.pop(key, None)
            return True
        self._pending_counters[key] = (value, now)
        return False

    def validate(self, sample):
        """Return valid source values and derive power only from those values."""
        data = dict(sample)
        rejected = set()
        now = time.monotonic()

        def reject(key, reason):
            value = data.pop(key)
            rejected.add(key)
            if key not in self._invalid_keys:
                _LOGGER.warning("Ignoring Pylontech value %s=%r: %s", key, value, reason)

        for key, (minimum, maximum) in VALUE_RANGES.items():
            if key in data and (
                not isinstance(data[key], (int, float))
                or not math.isfinite(data[key])
                or not minimum <= data[key] <= maximum
            ):
                reject(key, f"outside sanity range [{minimum}, {maximum}]")

        for key in COUNTER_RATES:
            if key not in data:
                self._pending_counters.pop(key, None)
            elif not self._counter_valid(key, data[key], now):
                # A first sample is expected at startup; do not warn about it.
                if key in self._counters:
                    reject(key, "implausible counter change or unconfirmed reset")
                else:
                    data.pop(key)

        if ("bms_cell_voltage_min" in data and "bms_cell_voltage_max" in data
                and data["bms_cell_voltage_min"] > data["bms_cell_voltage_max"]):
            reject("bms_cell_voltage_min", "minimum exceeds maximum cell voltage")
            reject("bms_cell_voltage_max", "minimum exceeds maximum cell voltage")

        # Firmware status strings are retained; numerical telemetry is checked
        # above. Do not infer measurement validity from charging/idle status.
        self._invalid_keys = rejected

        if "ac_total_power" in data and "grid_total_power" in data:
            data["load_power"] = data["ac_total_power"] + data["grid_total_power"]
        for n in range(1, 4):
            voltage, current = f"pv{n}_voltage", f"pv{n}_current"
            if voltage in data and current in data:
                power = data[voltage] * data[current]
                if power <= PV_POWER_LIMIT:
                    data[f"pv{n}_power"] = power
        for phase in "rst":
            voltage, current = f"grid_voltage_{phase}", f"ac_current_{phase}"
            if voltage in data and current in data:
                power = data[voltage] * data[current]
                if power <= INVERTER_POWER_LIMIT:
                    data[f"ac_power_{phase}"] = power
                    grid_power = f"grid_power_{phase}"
                    if grid_power in data:
                        data[f"load_power_{phase}"] = power + data[grid_power]
        return data
