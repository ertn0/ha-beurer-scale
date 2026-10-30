"""Config flow: pick the scale, then the user slot and its consent PIN."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import CONF_CONSENT, CONF_USER, DOMAIN

PIN = vol.All(vol.Coerce(int), vol.Range(min=0, max=9999))


class BeurerScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the BF500."""

    VERSION = 1

    def __init__(self) -> None:
        self._info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        """Scale found by the Bluetooth integration."""
        # One entry per user; once any user of this scale is set up, add more
        # users via "Add device" instead of showing a discovery every time.
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_ADDRESS) == discovery_info.address:
                return self.async_abort(reason="already_configured")
        self._info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user_slot()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual start: choose among discovered scales."""
        if user_input is not None:
            self._info = self._discovered[user_input[CONF_ADDRESS]]
            return await self.async_step_user_slot()
        self._discovered = {
            i.address: i for i in async_discovered_service_info(self.hass) if (i.name or "").startswith("BF500")
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In({a: f"{i.name} ({a})" for a, i in self._discovered.items()})}),
        )

    async def async_step_user_slot(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the scale's user slot (1-4) and the PIN set in the Beurer app."""
        assert self._info is not None
        if user_input is not None:
            unique_id = f"{self._info.address}_{user_input[CONF_USER]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{self._info.name} user {user_input[CONF_USER]}",
                data={CONF_ADDRESS: self._info.address, **user_input},
            )
        return self.async_show_form(
            step_id="user_slot",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
                    vol.Required(CONF_CONSENT): PIN,
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The scale rejected the PIN."""
        return await self.async_step_pin()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the PIN, e.g. after re-adding the scale in the Beurer app."""
        return await self.async_step_pin()

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new PIN for an existing user slot."""
        reauth = self.source == SOURCE_REAUTH
        entry = self._get_reauth_entry() if reauth else self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema({vol.Required(CONF_CONSENT): PIN}),
            description_placeholders={"user": str(entry.data[CONF_USER])},
        )
