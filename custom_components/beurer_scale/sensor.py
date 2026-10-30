"""Sensors for one user of the BF500."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_ADDRESS, PERCENTAGE, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BeurerConfigEntry
from .const import CONF_USER, DOMAIN
from .coordinator import BeurerScaleCoordinator, signal


@dataclass(frozen=True, kw_only=True)
class BeurerSensorDescription(SensorEntityDescription):
    """Sensor description with the key in the coordinator's record."""

    convert: Callable[[Any], Any] | None = None


SENSORS: tuple[BeurerSensorDescription, ...] = (
    BeurerSensorDescription(
        key="weight",
        translation_key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    BeurerSensorDescription(
        key="bmi", translation_key="bmi", state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1
    ),
    BeurerSensorDescription(
        key="fat_pct",
        translation_key="body_fat",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    BeurerSensorDescription(
        key="muscle_pct",
        translation_key="muscle",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    BeurerSensorDescription(
        key="water_pct",
        translation_key="body_water",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    BeurerSensorDescription(
        key="bmr_kcal",
        translation_key="bmr",
        native_unit_of_measurement="kcal/d",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BeurerSensorDescription(
        key="impedance",
        translation_key="impedance",
        native_unit_of_measurement="Ω",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    BeurerSensorDescription(
        key="timestamp",
        translation_key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        convert=dt_util.parse_datetime,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: BeurerConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(BeurerSensor(coordinator, entry, d) for d in SENSORS)


class BeurerSensor(SensorEntity):
    """One value of the latest measurement."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: BeurerSensorDescription

    def __init__(self, coordinator: BeurerScaleCoordinator, entry: BeurerConfigEntry, description: BeurerSensorDescription) -> None:
        self._coordinator = coordinator
        self.entity_description = description
        address, user = entry.data[CONF_ADDRESS], entry.data[CONF_USER]
        self._attr_unique_id = f"{address}_{user}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{address}_{user}")},
            name=entry.title,
            manufacturer="Beurer",
            model="BF 500",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal(self._coordinator.address, self._coordinator.user), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        value = (self._coordinator.last or {}).get(self.entity_description.key)
        if value is not None and self.entity_description.convert:
            return self.entity_description.convert(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key in ("fat_pct", "muscle_pct", "water_pct", "bmr_kcal", "impedance"):
            if ts := (self._coordinator.last or {}).get("body_timestamp"):
                return {"analysis_time": ts}
        return None
