"""Switch platform for Pylontech Force H3X."""
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL

@dataclass
class PylontechSwitchEntityDescription(SwitchEntityDescription):
    """description of Pylontech Switch entity."""
    register_address: int = 0
    slave_id: int = 2


SWITCH_TYPES: tuple[PylontechSwitchEntityDescription, ...] = (
    PylontechSwitchEntityDescription(
        key="heat_pump",
        name="Heat Pump",
        icon="mdi:heat-pump",
        register_address=40848,
        slave_id=2,
    ),
    PylontechSwitchEntityDescription(
        key="period_1",
        name="Period 1",
        icon="mdi:calendar-clock",
        register_address=40908,
        slave_id=2,
    ),
    PylontechSwitchEntityDescription(
        key="period_2",
        name="Period 2",
        icon="mdi:calendar-clock",
        register_address=40914,
        slave_id=2,
    ),
    PylontechSwitchEntityDescription(
        key="period_3",
        name="Period 3",
        icon="mdi:calendar-clock",
        register_address=40920,
        slave_id=2,
    ),
    PylontechSwitchEntityDescription(
        key="period_4",
        name="Period 4",
        icon="mdi:calendar-clock",
        register_address=40926,
        slave_id=2,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pylontech switch based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        PylontechSwitch(coordinator, description, entry)
        for description in SWITCH_TYPES
    ]

    async_add_entities(entities)


class PylontechSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Pylontech switch."""

    _attr_has_entity_name = True
    entity_description: PylontechSwitchEntityDescription

    def __init__(
        self,
        coordinator,
        description: PylontechSwitchEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        
        self._attr_unique_id = f"{DOMAIN}_{entry.data['host']}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return value == 1

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the heat pump on (Write 1)."""
        success = await self.coordinator.async_write_register(
            address=self.entity_description.register_address,
            value=1,
            slave=self.entity_description.slave_id
        )
        if success:
            
            self.coordinator.data[self.entity_description.key] = 1
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the heat pump off (Write 0)."""
        success = await self.coordinator.async_write_register(
            address=self.entity_description.register_address,
            value=0,
            slave=self.entity_description.slave_id
        )
        if success:
            self.coordinator.data[self.entity_description.key] = 0
            self.async_write_ha_state()