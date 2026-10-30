"""Connects to the scale when it advertises and reads the stored measurements."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .agent import PairingAgent
from .const import DOMAIN, FRESH_ADV, CONNECT_TIMEOUT, MAX_ATTEMPTS, REDISCOVER_WAIT, PAIRING_SETTLE, PAIRING_WAIT, PAIRING_PROMPT, POLL_INTERVAL, RESPONSE_TIMEOUT, RETRY_DELAY
from .protocol import (
    BODY_UUID,
    CTS_UUID,
    UCP_SUCCESS,
    UCP_UUID,
    VENDOR_UUID,
    WEIGHT_SCALE_SERVICE_UUID,
    WEIGHT_UUID,
    Measurement,
    WeightRecord,
    encode_consent,
    encode_current_time,
    parse_body,
    parse_ucp_response,
    parse_weight,
)

_LOGGER = logging.getLogger(__name__)


BODY_KEYS = ("body_timestamp", "fat_pct", "muscle_pct", "water_pct", "bmr_kcal", "impedance")


class ConsentRejected(Exception):
    """The scale did not accept the PIN for this user slot."""


def signal(address: str, user: int) -> str:
    """Dispatcher signal name for new data."""
    return f"{DOMAIN}_{address}_{user}_update"


class BeurerScaleCoordinator:
    """Push-style coordinator: sync whenever the scale wakes up."""

    def __init__(
        self, hass: HomeAssistant, address: str, name: str, user: int, consent: int, agent: PairingAgent,
        lock: asyncio.Lock, on_auth_failed: Callable[[], None],
    ) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.user = user
        self._consent = consent
        self._agent = agent
        self._on_auth_failed = on_auth_failed
        self.last: dict[str, Any] | None = None
        self.last_sync_ok: bool | None = None
        # Shared by all user entries of this scale.
        self._lock = lock
        self._last_attempt = 0.0
        self._cancel: CALLBACK_TYPE | None = None
        self._cancel_poll: CALLBACK_TYPE | None = None
        self._attempts = 0
        self._pending = False
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{address.replace(':', '').lower()}_{user}")

    async def async_start(self) -> CALLBACK_TYPE:
        """Load the last measurement and start listening to advertisements."""
        stored = await self._store.async_load()
        if stored:
            self.last = stored.get("last")
        self._cancel = bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
        # HA only calls the callback above when the advertisement content
        # changes, so also re-check the last advertisement periodically.
        self._cancel_poll = async_track_time_interval(
            self.hass, self._async_poll, timedelta(seconds=POLL_INTERVAL)
        )
        return self._async_stop

    @callback
    def _async_poll(self, _now: Any) -> None:
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        # Ignore stale history: the scale is only reachable while it advertises.
        if info is not None and time.monotonic() - info.time < FRESH_ADV:
            self._async_on_advertisement(info, BluetoothChange.ADVERTISEMENT)

    @callback
    def _async_stop(self) -> None:
        if self._cancel:
            self._cancel()
            self._cancel = None
        if self._cancel_poll:
            self._cancel_poll()
            self._cancel_poll = None

    @callback
    def _async_on_advertisement(self, info: BluetoothServiceInfoBleak, change: BluetoothChange) -> None:
        # The scale lists the user slots with unsent measurements in its
        # Weight Scale service data, e.g. 01 02 03 04.
        pending = self.user in info.service_data.get(WEIGHT_SCALE_SERVICE_UUID, b"")
        if pending != self._pending:
            _LOGGER.debug("%s: user %d has %s data (rssi %s)", self.address, self.user, "new" if pending else "no new", info.rssi)
            self._pending = pending
            self._attempts = 0
        # Each attempt makes the scale show a pairing number until SET is
        # pressed, so only try a few times right after new data shows up.
        if (
            not pending
            or self._lock.locked()
            or self._attempts >= MAX_ATTEMPTS
            or time.monotonic() - self._last_attempt < RETRY_DELAY
        ):
            return
        self._start_sync(info)

    @callback
    def async_request_sync(self) -> None:
        """Manual sync (button); the scale must be awake."""
        if self._lock.locked():
            return
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        if info is None:
            _LOGGER.warning("%s: scale not in range; step on it to wake it up", self.address)
            return
        self._attempts = 0
        self._start_sync(info)

    @callback
    def _start_sync(self, info: BluetoothServiceInfoBleak) -> None:
        self._last_attempt = time.monotonic()
        self._attempts += 1
        _LOGGER.debug("%s: starting sync (attempt %d)", self.address, self._attempts)
        self.hass.async_create_background_task(self._async_sync(info), f"{DOMAIN} sync {self.address}")

    async def _async_sync(self, info: BluetoothServiceInfoBleak) -> None:
        async with self._lock:
            try:
                records = await self._async_read(info)
            except ConsentRejected as err:
                self.last_sync_ok = False
                # Retrying with the same PIN is pointless; ask the user for a new one.
                self._attempts = MAX_ATTEMPTS
                _LOGGER.error("%s: %s", self.address, err)
                self._on_auth_failed()
                return
            except Exception as err:  # noqa: BLE001
                self.last_sync_ok = False
                _LOGGER.warning(
                    "%s: sync failed (was SET pressed when the number showed?): %s: %s",
                    self.address, type(err).__name__, err,
                )
                _LOGGER.debug("sync failure details", exc_info=True)
                return
            finally:
                # Count the retry delay from the end of the attempt.
                self._last_attempt = time.monotonic()
            self.last_sync_ok = True
            await self._async_handle(records)

    async def _async_read(self, info: BluetoothServiceInfoBleak) -> list[Measurement]:
        # The scale forgets the Pi's bond after every connection. If BlueZ still
        # thinks it is paired, it skips pairing and the scale's own pairing
        # request then collides with service discovery. So forget the stale
        # bond and pair first (pair=True), then discover services.
        removed_at = time.monotonic()
        if await self._agent.async_remove_device(self.address):
            _LOGGER.debug("%s: removed stale BlueZ bond, waiting for advertisement", self.address)
            for _ in range(int(REDISCOVER_WAIT / 0.5)):
                last = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
                if last is not None and last.time > removed_at:
                    info = last
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError("scale not seen again after removing the stale bond")
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True) or info.device
        pairings_before = self._agent.pairings.get(self.address.upper(), 0)
        paired = self._agent.pairing_event(self.address)
        paired.clear()
        client = await establish_connection(
            BleakClientWithServiceCache, device, self.name, max_attempts=3, pair=True, timeout=CONNECT_TIMEOUT
        )
        _LOGGER.debug("%s: connected (pairing so far: %s)", self.address, paired.is_set())
        # The scale asks for a new pairing on every connection. Give it time to
        # finish (and the link to be encrypted) before touching any attribute.
        try:
            await asyncio.wait_for(paired.wait(), PAIRING_PROMPT)
            _LOGGER.debug("%s: pairing confirmed, settling", self.address)
            await asyncio.sleep(PAIRING_SETTLE)
        except TimeoutError:
            _LOGGER.debug("%s: no pairing request within %ss", self.address, PAIRING_PROMPT)
        records: list[Measurement] = []
        done = asyncio.Event()
        result: list[int] = []

        def on_weight(_: Any, data: bytearray) -> None:
            _LOGGER.debug("weight indication %s", bytes(data).hex())
            try:
                records.append(Measurement(weight=parse_weight(bytes(data))))
            except ValueError as err:
                _LOGGER.debug("ignoring weight record: %s", err)

        def on_body(_: Any, data: bytearray) -> None:
            _LOGGER.debug("body indication %s", bytes(data).hex())
            try:
                body = parse_body(bytes(data))
            except ValueError as err:
                _LOGGER.debug("ignoring body record: %s", err)
                return
            if records and records[-1].body is None:
                records[-1].body = body

        def on_ucp(_: Any, data: bytearray) -> None:
            _LOGGER.debug("ucp indication %s", bytes(data).hex())
            if (resp := parse_ucp_response(bytes(data))) is not None:
                result.append(resp[1])
                done.set()

        def on_vendor(_: Any, data: bytearray) -> None:
            _LOGGER.debug("vendor indication %s", bytes(data).hex())

        try:
            await self._async_first_write(client)
            _LOGGER.debug("%s: clock set", self.address)
            await client.start_notify(WEIGHT_UUID, on_weight)
            await client.start_notify(BODY_UUID, on_body)
            await client.start_notify(UCP_UUID, on_ucp)
            await client.start_notify(VENDOR_UUID, on_vendor)
            _LOGGER.debug("%s: indications on, sending consent for user %d", self.address, self.user)
            await client.write_gatt_char(UCP_UUID, encode_consent(self.user, self._consent), response=True)
            _LOGGER.debug("%s: consent sent, waiting for records", self.address)
            await asyncio.wait_for(done.wait(), RESPONSE_TIMEOUT)
            if result[0] != UCP_SUCCESS:
                raise ConsentRejected(f"scale rejected the PIN for user {self.user} (result {result[0]:#x})")
            await asyncio.sleep(0.5)
            await self._async_unsubscribe(client)
        finally:
            await client.disconnect()
        paired = self._agent.pairings.get(self.address.upper(), 0) > pairings_before
        _LOGGER.debug("%s: sync done, %s", self.address, "scale asked for pairing" if paired else "bond reused")
        return records

    async def _async_first_write(self, client: BleakClient) -> None:
        """Set the clock, waiting while the user confirms pairing with SET.

        The scale re-pairs on every connection and rejects GATT access with
        'Unlikely Error' until the pairing is confirmed on the scale.
        """
        deadline = time.monotonic() + PAIRING_WAIT
        while True:
            try:
                await client.write_gatt_char(CTS_UUID, encode_current_time(dt_util.now()), response=True)
                return
            except BleakError as err:
                if time.monotonic() > deadline or not client.is_connected:
                    raise
                _LOGGER.debug("%s: waiting for pairing confirmation (SET): %s", self.address, err)
                await asyncio.sleep(3)

    @staticmethod
    async def _async_unsubscribe(client: BleakClient) -> None:
        for uuid in (UCP_UUID, BODY_UUID, WEIGHT_UUID, VENDOR_UUID):
            try:
                await client.stop_notify(uuid)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("stop_notify %s failed", uuid, exc_info=True)

    async def _async_handle(self, records: list[Measurement]) -> None:
        """Keep only records newer than the last one we saw and publish the newest."""
        mine = [r for r in records if r.weight.user in (None, self.user)]
        _LOGGER.debug("%s: %d record(s) received", self.address, len(mine))
        last_ts = self.last.get("timestamp") if self.last else None
        fresh = [r for r in mine if (_iso(r.weight) or "") > (last_ts or "")]
        if not fresh:
            return
        newest = max(fresh, key=lambda r: _iso(r.weight) or "")
        # Keep the last real body analysis if the newest weighing had none.
        carried = {k: v for k, v in (self.last or {}).items() if k in BODY_KEYS}
        self.last = {**carried, **_to_dict(newest)}
        await self._store.async_save({"last": self.last})
        async_dispatcher_send(self.hass, signal(self.address, self.user))


def _iso(weight: WeightRecord) -> str | None:
    if weight.timestamp is None:
        return None
    return dt_util.as_utc(weight.timestamp.replace(tzinfo=dt_util.get_default_time_zone())).isoformat()


def _to_dict(m: Measurement) -> dict[str, Any]:
    w, b = m.weight, m.body
    data: dict[str, Any] = {
        "timestamp": _iso(w),
        "weight": w.weight_kg,
        "bmi": w.bmi,
        "height_m": w.height_m,
    }
    if b is not None and b.has_analysis:
        data.update(
            body_timestamp=data["timestamp"],
            fat_pct=b.fat_pct,
            muscle_pct=b.muscle_pct,
            water_pct=round(b.water_kg / w.weight_kg * 100, 1) if b.water_kg and w.weight_kg else None,
            bmr_kcal=round(b.bmr_kj / 4.184) if b.bmr_kj else None,
            impedance=b.impedance_ohm,
        )
    return data
