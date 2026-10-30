"""Parse the CSV export of the Beurer HealthManager Pro app (no HA imports).

The export starts with a "User details" block, followed by a "Weight" table:

    Date;Time;kg;BMI;Body fat;Water;Muscles;Bone;Metabolic age;Pulse;Comment;Medication
    10.01.2025;08:56;94.1;29.7;27.2;52.6;36.8;3.6;47;;;

Body fat, water and muscles are percentages. Rows measured with shoes on only
have date, time and weight.
"""
from __future__ import annotations

from datetime import datetime

# CSV column -> coordinator record key (same keys as the sensors use).
COLUMNS = {
    "kg": "weight",
    "BMI": "bmi",
    "Body fat": "fat_pct",
    "Water": "water_pct",
    "Muscles": "muscle_pct",
}


def parse_export(text: str) -> list[tuple[datetime, dict[str, float]]]:
    """Return (local naive timestamp, {key: value}) for each weight row."""
    lines = text.lstrip("﻿").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("Date;Time;"))
    except StopIteration as err:
        raise ValueError("no weight table (Date;Time;...) found in export") from err
    header = lines[start].split(";")
    rows: list[tuple[datetime, dict[str, float]]] = []
    for line in lines[start + 1 :]:
        cells = line.split(";")
        if len(cells) < 3 or not cells[0].strip():
            if rows:
                break  # end of the weight table
            continue
        when = datetime.strptime(f"{cells[0]} {cells[1]}", "%d.%m.%Y %H:%M")
        values: dict[str, float] = {}
        for column, key in COLUMNS.items():
            if column in header and (cell := cells[header.index(column)].strip()):
                values[key] = float(cell.replace(",", "."))
        if "weight" in values:
            rows.append((when, values))
    return rows
