"""Button to fetch measurements by hand (press SET on the scale afterwards)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BeurerConfigEntry
from .const import CONF_USER, DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: BeurerConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the fetch button."""
    async_add_entities([BeurerFetchButton(entry)])


class BeurerFetchButton(ButtonEntity):
    """Connect to the scale now and read this user's stored measurements."""

    _attr_has_entity_name = True
    _attr_translation_key = "fetch"

    def __init__(self, entry: BeurerConfigEntry) -> None:
        self._coordinator = entry.runtime_data
        address, user = entry.data[CONF_ADDRESS], entry.data[CONF_USER]
        self._attr_unique_id = f"{address}_{user}_fetch"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{address}_{user}")})

    async def async_press(self) -> None:
        self._coordinator.async_request_sync()
