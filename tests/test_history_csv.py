"""Tests for the HealthManager Pro CSV parser (synthetic data)."""
from datetime import datetime
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "history_csv", pathlib.Path(__file__).parent.parent / "custom_components/beurer_scale/history_csv.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

SAMPLE = """﻿User details


Gender  Male
Height  180 cm


Weight
Date;Time;kg;BMI;Body fat;Water;Muscles;Bone;Metabolic age;Pulse;Comment;Medication
01.02.2025;07:05;80.5;24.8;20.1;55.2;40.3;3.4;35;;;
02.02.2025;19:40;81;25;;;;;;;;

Blood pressure
Date;Time;Sys
"""


def test_parse_rows():
    rows = h.parse_export(SAMPLE)
    assert rows[0] == (
        datetime(2025, 2, 1, 7, 5),
        {"weight": 80.5, "bmi": 24.8, "fat_pct": 20.1, "water_pct": 55.2, "muscle_pct": 40.3},
    )
    assert rows[1] == (datetime(2025, 2, 2, 19, 40), {"weight": 81.0, "bmi": 25.0})
    assert len(rows) == 2


def test_no_table():
    try:
        h.parse_export("nothing here")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
