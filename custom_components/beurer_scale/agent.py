"""BlueZ pairing agent that confirms numeric comparison for the scale only.

The BF500 asks for LE Secure Connections pairing with numeric comparison
(it shows a 6-digit number, confirmed with SET on the scale). Home Assistant
registers no BlueZ agent, so without this the pairing is rejected and the
connection drops during service discovery.

No ``from __future__ import annotations`` here: dbus-fast reads the D-Bus
signatures from the annotations.
"""
import asyncio
import logging

from dbus_fast import BusType, DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/org/homeassistant/beurer_scale/agent"
CAPABILITY = "DisplayYesNo"
REJECTED = "org.bluez.Error.Rejected"


def device_path_suffix(address: str) -> str:
    """BlueZ object path suffix for a device address."""
    return "dev_" + address.upper().replace(":", "_")


class _Agent(ServiceInterface):
    def __init__(self, owner: "PairingAgent") -> None:
        super().__init__("org.bluez.Agent1")
        self._owner = owner

    def _check(self, device: str) -> None:
        if not self._owner.is_allowed(device):
            _LOGGER.info("rejecting pairing request from %s (not a configured scale)", device)
            raise DBusError(REJECTED, "not a configured Beurer scale")

    @method()
    def Release(self):  # noqa: N802
        _LOGGER.debug("agent released by BlueZ")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
        self._check(device)
        _LOGGER.debug("pairing %s: confirming passkey %06d (the scale shows the same number, press SET)", device, passkey)
        self._owner.note_pairing(device, passkey)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802, F821
        self._check(device)
        _LOGGER.info("pairing %s: authorizing just-works pairing", device)
        self._owner.note_pairing(device, None)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
        self._check(device)

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
        raise DBusError(REJECTED, "PIN pairing not supported")

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821
        raise DBusError(REJECTED, "passkey entry not supported")

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
        _LOGGER.info("pairing %s: passkey %06d", device, passkey)

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
        _LOGGER.info("pairing %s: pin %s", device, pincode)

    @method()
    def Cancel(self):  # noqa: N802
        _LOGGER.info("pairing request cancelled by BlueZ")


class PairingAgent:
    """Registers one agent on the system bus for all configured scales."""

    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._addresses: set[str] = set()
        self.pairings: dict[str, int] = {}
        self._events: dict[str, asyncio.Event] = {}

    def is_allowed(self, device_path: str) -> bool:
        return any(device_path.endswith(device_path_suffix(a)) for a in self._addresses)

    def note_pairing(self, device_path: str, passkey: int | None) -> None:
        for address in self._addresses:
            if device_path.endswith(device_path_suffix(address)):
                self.pairings[address] = self.pairings.get(address, 0) + 1
                self.pairing_event(address).set()

    def pairing_event(self, address: str) -> asyncio.Event:
        """Event set whenever the scale at ``address`` asks for pairing."""
        return self._events.setdefault(address.upper(), asyncio.Event())

    async def async_add(self, address: str) -> None:
        self._addresses.add(address.upper())
        if self._bus is None:
            await self._async_register()

    async def async_remove(self, address: str) -> None:
        self._addresses.discard(address.upper())
        if not self._addresses and self._bus is not None:
            await self._async_unregister()

    async def _async_register(self) -> None:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(AGENT_PATH, _Agent(self))
        manager = await self._manager(bus)
        await manager.call_register_agent(AGENT_PATH, CAPABILITY)
        try:
            await manager.call_request_default_agent(AGENT_PATH)
        except DBusError as err:
            _LOGGER.warning("could not become default BlueZ agent: %s", err)
        self._bus = bus
        _LOGGER.debug("BlueZ pairing agent registered at %s", AGENT_PATH)

    async def _async_unregister(self) -> None:
        bus, self._bus = self._bus, None
        try:
            manager = await self._manager(bus)
            await manager.call_unregister_agent(AGENT_PATH)
        except DBusError as err:
            _LOGGER.debug("unregister agent failed: %s", err)
        bus.disconnect()

    async def async_remove_device(self, address: str) -> bool:
        """Remove the scale from BlueZ (forget the stale bond); True if removed."""
        if self._bus is None:
            return False
        suffix = device_path_suffix(address)
        introspection = await self._bus.introspect("org.bluez", "/")
        manager = self._bus.get_proxy_object("org.bluez", "/", introspection).get_interface(
            "org.freedesktop.DBus.ObjectManager"
        )
        for path, interfaces in (await manager.call_get_managed_objects()).items():
            if path.endswith(suffix) and "org.bluez.Device1" in interfaces:
                adapter_path = path.rsplit("/", 1)[0]
                adapter_introspection = await self._bus.introspect("org.bluez", adapter_path)
                adapter = self._bus.get_proxy_object("org.bluez", adapter_path, adapter_introspection).get_interface(
                    "org.bluez.Adapter1"
                )
                await adapter.call_remove_device(path)
                return True
        return False

    @staticmethod
    async def _manager(bus: MessageBus):
        introspection = await bus.introspect("org.bluez", "/org/bluez")
        return bus.get_proxy_object("org.bluez", "/org/bluez", introspection).get_interface(
            "org.bluez.AgentManager1"
        )
