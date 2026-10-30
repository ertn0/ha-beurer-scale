"""Beurer BF500 personal scale (Bluetooth LE)."""
from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .agent import PairingAgent
from .const import CONF_CONSENT, CONF_USER, DOMAIN
from .coordinator import BeurerScaleCoordinator
from .history_import import async_register as async_register_import

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type BeurerConfigEntry = ConfigEntry[BeurerScaleCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_register_import(hass)
    return True


def _agent(hass: HomeAssistant) -> PairingAgent:
    """One BlueZ agent shared by all entries."""
    return hass.data.setdefault(DOMAIN, {}).setdefault("agent", PairingAgent())


def _scale_lock(hass: HomeAssistant, address: str) -> asyncio.Lock:
    """One lock per scale: only one user entry may talk to it at a time."""
    locks = hass.data.setdefault(DOMAIN, {}).setdefault("locks", {})
    return locks.setdefault(address.upper(), asyncio.Lock())


async def async_setup_entry(hass: HomeAssistant, entry: BeurerConfigEntry) -> bool:
    """Set up one scale user."""
    agent = _agent(hass)
    await agent.async_add(entry.data[CONF_ADDRESS])
    coordinator = BeurerScaleCoordinator(
        hass,
        entry.data[CONF_ADDRESS],
        entry.title,
        entry.data[CONF_USER],
        entry.data[CONF_CONSENT],
        agent,
        _scale_lock(hass, entry.data[CONF_ADDRESS]),
        lambda: entry.async_start_reauth(hass),
    )
    entry.runtime_data = coordinator
    entry.async_on_unload(await coordinator.async_start())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BeurerConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        others = [
            e for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.data[CONF_ADDRESS] == entry.data[CONF_ADDRESS]
        ]
        if not others:
            await _agent(hass).async_remove(entry.data[CONF_ADDRESS])
    return unloaded
