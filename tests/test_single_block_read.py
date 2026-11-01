"""Tests for the combined 30100-30191 read and its fallback."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_coordinator import (
    coordinator_module, validation_module, valid_blocks, put_int,
)


def memory_map(blocks):
    """Lay the three PCS blocks out as one contiguous register space."""
    mem = [0] * 92
    mem[0:48] = blocks[30100]
    mem[56:86] = blocks[30156]
    mem[83:92] = blocks[30183]
    return mem


class SingleBlockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = coordinator_module.PylontechCoordinator(None, "test", 502)
        self.coordinator.use_single_block_read = True  # opt in; off by default
        self.blocks = valid_blocks()
        self.fail_big = False
        self.calls = []
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
        self.calls.append((address, count))
        if address == 30100 and count == 92:
            if self.fail_big:
                return SimpleNamespace(isError=lambda: True, registers=[])
            return SimpleNamespace(isError=lambda: False, registers=memory_map(self.blocks))
        return SimpleNamespace(isError=lambda: False, registers=self.blocks[address])

    async def poll(self):
        self.now += 5
        data = await self.coordinator._async_update_data()
        self.coordinator.data = data
        return data

    def test_combined_read_off_by_default(self):
        fresh = coordinator_module.PylontechCoordinator(None, "test", 502)
        self.assertFalse(fresh.use_single_block_read)

    async def test_one_request_replaces_three(self):
        await self.poll()
        pcs_reads = [c for c in self.calls if c[0] in (30100, 30156, 30183)]
        self.assertEqual(pcs_reads, [(30100, 92)])

    async def test_same_values_as_three_block_path(self):
        combined = await self.poll()
        legacy = coordinator_module.PylontechCoordinator(None, "test", 502)
        legacy.use_single_block_read = False
        legacy.client.read_holding_registers.side_effect = self.response
        legacy_data = await legacy._async_update_data()
        self.assertEqual(combined, legacy_data)

    async def test_corrupt_battery_power_still_rejected(self):
        put_int(self.blocks[30156], 6, 700_000_000)
        data = await self.poll()
        self.assertNotIn("battery_power", data)
        self.assertIn("pv_total_power", data)

    async def test_falls_back_when_big_read_fails(self):
        self.fail_big = True
        data = await self.poll()
        self.assertIn("battery_power", data)
        self.assertIn((30156, 30), self.calls)
        self.assertTrue(self.coordinator.use_single_block_read)

    async def test_disabled_after_repeated_failures(self):
        self.fail_big = True
        for _ in range(3):
            await self.poll()
        self.assertFalse(self.coordinator.use_single_block_read)
        self.calls.clear()
        await self.poll()
        self.assertNotIn((30100, 92), self.calls)

    async def test_unverified_grid_current_jump_drops_only_phase_values(self):
        self.blocks[30183][1] = 8
        await self.poll()
        self.blocks[30183][1] = 2000  # 200 A jump
        original = self.response
        state = {"n": 0}

        async def flaky(*, address, count, **kwargs):
            if address == 30100 and count == 92:
                state["n"] += 1
                if state["n"] > 1:  # re-read fails: jump cannot be verified
                    return SimpleNamespace(isError=lambda: True, registers=[])
            return await original(address=address, count=count, **kwargs)

        self.coordinator.client.read_holding_registers.side_effect = flaky
        data = await self.poll()
        self.assertNotIn("grid_current_s", data)
        self.assertIn("pv_total_power", data)
        self.assertIn("battery_soc", data)


if __name__ == "__main__":
    unittest.main()
