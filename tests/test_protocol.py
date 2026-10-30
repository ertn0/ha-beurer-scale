"""Tests for the BF500 protocol helpers.

All packets are synthetic: built from made-up values in the layout the scale
uses (Bluetooth Weight Scale / Body Composition / User Data services).
"""
from datetime import datetime
import importlib.util
import pathlib
import struct
import sys

_spec = importlib.util.spec_from_file_location(
    "protocol", pathlib.Path(__file__).parent.parent / "custom_components/beurer_scale/protocol.py"
)
p = importlib.util.module_from_spec(_spec)
sys.modules["protocol"] = p
_spec.loader.exec_module(p)

WHEN = datetime(2025, 3, 1, 7, 30, 15)


def _ts(dt: datetime) -> bytes:
    return struct.pack("<HBBBBB", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def test_weight_with_timestamp_user_bmi_height():
    # flags 0x0e: timestamp, user id, BMI + height; SI units (0.005 kg, 0.1 BMI, 0.001 m)
    packet = bytes([0x0E]) + struct.pack("<H", 15000) + _ts(WHEN) + bytes([1]) + struct.pack("<HH", 231, 1800)
    r = p.parse_weight(packet)
    assert r.weight_kg == 75.0
    assert r.timestamp == WHEN
    assert r.user == 1 and r.bmi == 23.1 and r.height_m == 1.8


def test_weight_imperial_rejected():
    try:
        p.parse_weight(bytes([0x01]) + struct.pack("<H", 1000))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_body_composition_as_sent_by_bf500():
    # flags 0x0398: BMR, muscle %, soft lean mass, body water mass, impedance
    packet = struct.pack("<HHHHHHH", 0x0398, 185, 7000, 412, 11600, 8200, 5000)
    r = p.parse_body(packet)
    assert r.fat_pct == 18.5 and r.bmr_kj == 7000 and r.muscle_pct == 41.2
    assert r.soft_lean_kg == 58.0 and r.water_kg == 41.0 and r.impedance_ohm == 500.0
    assert r.has_analysis


def test_body_without_analysis():
    # weighed with shoes on: the scale sends zeros
    r = p.parse_body(struct.pack("<HHHHHHH", 0x0398, 0, 7000, 0, 0, 0, 0))
    assert not r.has_analysis


def test_ucp_response_and_consent():
    assert p.parse_ucp_response(bytes([0x20, 0x02, 0x01])) == (2, 1)
    assert p.parse_ucp_response(bytes([0x01, 0x02])) is None
    assert p.encode_consent(3, 1234) == bytes([0x02, 0x03]) + struct.pack("<H", 1234)


def test_current_time():
    assert p.encode_current_time(WHEN) == _ts(WHEN) + bytes([0, 0, 0])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
