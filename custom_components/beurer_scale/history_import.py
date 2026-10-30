"""Action beurer_scale.import_history: import an app CSV export as statistics.

Home Assistant cannot backfill states, but it can import hourly long-term
statistics for a sensor. Each measurement becomes the mean/min/max of the hour
it was taken in. Only hours before the sensor was created are imported, so
nothing the recorder compiled itself is overwritten.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import async_import_statistics, get_metadata
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .const import CONF_USER, DOMAIN
from .history_csv import COLUMNS, parse_export

_LOGGER = logging.getLogger(__name__)

SERVICE = "import_history"
SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Required(CONF_USER): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    }
)


def async_register(hass: HomeAssistant) -> None:
    """Register the import action."""

    async def handle(call: ServiceCall) -> ServiceResponse:
        return await _async_import(hass, call.data["file"], call.data[CONF_USER])

    hass.services.async_register(DOMAIN, SERVICE, handle, SCHEMA, supports_response=SupportsResponse.OPTIONAL)


async def _async_import(hass: HomeAssistant, file: str, user: int) -> ServiceResponse:
    entry = next(
        (e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.data[CONF_USER] == user), None
    )
    if entry is None:
        raise ServiceValidationError(f"no Beurer scale entry for user {user}")

    config_dir = Path(hass.config.path()).resolve()
    path = (config_dir / file).resolve()
    if config_dir not in path.parents:
        raise ServiceValidationError("file must be inside the config directory")
    if not await hass.async_add_executor_job(path.is_file):
        raise ServiceValidationError(f"file not found: {file}")
    text = await hass.async_add_executor_job(path.read_text, "utf-8")
    try:
        rows = parse_export(text)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    registry = er.async_get(hass)
    entities: dict[str, er.RegistryEntry] = {}
    for key in COLUMNS.values():
        unique_id = f"{entry.data[CONF_ADDRESS]}_{user}_{key}"
        if entity_id := registry.async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id):
            entities[key] = registry.async_get(entity_id)

    metadata = await get_instance(hass).async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids={e.entity_id for e in entities.values()})
    )

    tz = dt_util.get_default_time_zone()
    result: dict[str, dict[str, int]] = {}
    for key, reg in entities.items():
        if reg.entity_id not in metadata:
            result[reg.entity_id] = {"imported_hours": 0, "skipped": len(rows), "reason": "no statistics yet"}
            continue
        cutoff = reg.created_at.replace(minute=0, second=0, microsecond=0)
        hours: dict[datetime, list[float]] = defaultdict(list)
        skipped = 0
        for local, values in rows:
            if key not in values:
                continue
            start = dt_util.as_utc(local.replace(tzinfo=tz)).replace(minute=0, second=0, microsecond=0)
            if start >= cutoff:
                skipped += 1
                continue
            hours[start].append(values[key])
        stats = [
            StatisticData(start=start, mean=sum(v) / len(v), min=min(v), max=max(v))
            for start, v in sorted(hours.items())
        ]
        if stats:
            async_import_statistics(hass, metadata[reg.entity_id][1], stats)
        result[reg.entity_id] = {"imported_hours": len(stats), "skipped_after_sensor_created": skipped}
        _LOGGER.info("imported %d hourly statistics into %s (%d skipped)", len(stats), reg.entity_id, skipped)
    return {"rows_in_file": len(rows), "sensors": result}
