"""Beurer BF500 BLE protocol: pure parsing helpers (no Home Assistant imports).

The scale speaks the standard Bluetooth Weight Scale (0x181D), Body Composition
(0x181B) and User Data (0x181C) services. Sequence reverse-engineered from an
iOS PacketLogger trace of the Beurer HealthManager Pro app:

1. write Current Time (0x2A2B)
2. enable indications on Weight (0x2A9D), Body Composition (0x2A9C),
   User Control Point (0x2A9F) and the vendor characteristic 0xFFF5
3. write UCP: 0x02 <user index> <consent code, uint16 LE>
4. the scale indicates all stored records of that user, then the UCP response
   ``20 02 01`` (op 0x20, request 0x02, result 0x01 = success)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import struct

WEIGHT_SCALE_SERVICE_UUID = "0000181d-0000-1000-8000-00805f9b34fb"
CTS_UUID = "00002a2b-0000-1000-8000-00805f9b34fb"
WEIGHT_UUID = "00002a9d-0000-1000-8000-00805f9b34fb"
BODY_UUID = "00002a9c-0000-1000-8000-00805f9b34fb"
UCP_UUID = "00002a9f-0000-1000-8000-00805f9b34fb"
VENDOR_UUID = "0000fff5-0000-1000-8000-00805f9b34fb"

UCP_OP_CONSENT = 0x02
UCP_OP_RESPONSE = 0x20
UCP_SUCCESS = 0x01

UNSUCCESSFUL = 0xFFFF


@dataclass(slots=True)
class WeightRecord:
    """One entry from the Weight Measurement characteristic (0x2A9D)."""

    weight_kg: float
    timestamp: datetime | None = None
    user: int | None = None
    bmi: float | None = None
    height_m: float | None = None


@dataclass(slots=True)
class BodyRecord:
    """One entry from the Body Composition Measurement characteristic (0x2A9C)."""

    fat_pct: float | None = None
    timestamp: datetime | None = None
    user: int | None = None
    bmr_kj: int | None = None
    muscle_pct: float | None = None
    muscle_kg: float | None = None
    ffm_kg: float | None = None
    soft_lean_kg: float | None = None
    water_kg: float | None = None
    impedance_ohm: float | None = None

    @property
    def has_analysis(self) -> bool:
        """The scale sends zeros when it could not measure impedance."""
        return bool(self.impedance_ohm) and self.fat_pct is not None


@dataclass(slots=True)
class Measurement:
    """A weight record plus the body composition record that followed it."""

    weight: WeightRecord
    body: BodyRecord | None = None


def encode_current_time(now: datetime) -> bytes:
    """Current Time characteristic: year, month, day, h, m, s, dow, frac, reason."""
    return struct.pack(
        "<HBBBBBBBB", now.year, now.month, now.day, now.hour, now.minute, now.second, 0, 0, 0
    )


def encode_consent(user: int, code: int) -> bytes:
    """UCP 'Consent' request for the given user index and PIN."""
    return struct.pack("<BBH", UCP_OP_CONSENT, user, code)


def _timestamp(data: bytes, offset: int) -> datetime | None:
    year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def parse_weight(data: bytes) -> WeightRecord:
    """Parse a 0x2A9D indication (SI units: 0.005 kg, 0.001 m)."""
    flags = data[0]
    if flags & 0x01:
        raise ValueError("imperial units are not supported")
    offset = 1
    weight = struct.unpack_from("<H", data, offset)[0] * 0.005
    offset += 2
    record = WeightRecord(weight_kg=round(weight, 3))
    if flags & 0x02:
        record.timestamp = _timestamp(data, offset)
        offset += 7
    if flags & 0x04:
        record.user = data[offset]
        offset += 1
    if flags & 0x08:
        bmi, height = struct.unpack_from("<HH", data, offset)
        record.bmi = round(bmi * 0.1, 1)
        record.height_m = round(height * 0.001, 3)
    return record


def parse_body(data: bytes) -> BodyRecord:
    """Parse a 0x2A9C indication (SI units)."""
    flags, fat = struct.unpack_from("<HH", data, 0)
    if flags & 0x01:
        raise ValueError("imperial units are not supported")
    offset = 4
    record = BodyRecord(fat_pct=None if fat == UNSUCCESSFUL else round(fat * 0.1, 1))

    def u16(scale: float, ndigits: int = 3) -> float:
        nonlocal offset
        value = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        return round(value * scale, ndigits)

    if flags & 0x0002:
        record.timestamp = _timestamp(data, offset)
        offset += 7
    if flags & 0x0004:
        record.user = data[offset]
        offset += 1
    if flags & 0x0008:
        record.bmr_kj = int(u16(1, 0))
    if flags & 0x0010:
        record.muscle_pct = u16(0.1, 1)
    if flags & 0x0020:
        record.muscle_kg = u16(0.005)
    if flags & 0x0040:
        record.ffm_kg = u16(0.005)
    if flags & 0x0080:
        record.soft_lean_kg = u16(0.005)
    if flags & 0x0100:
        record.water_kg = u16(0.005)
    if flags & 0x0200:
        record.impedance_ohm = u16(0.1, 1)
    return record


def parse_ucp_response(data: bytes) -> tuple[int, int] | None:
    """Return (request opcode, result code) for a UCP response, else None."""
    if len(data) >= 3 and data[0] == UCP_OP_RESPONSE:
        return data[1], data[2]
    return None
