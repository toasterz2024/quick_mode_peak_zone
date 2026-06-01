"""Generate two sample JSON logs for local Streamlit demo.

Run once:

    python scripts/generate_sample_logs.py
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "data" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _write_log(name: str, records: list[dict[str, object]]) -> None:
    path = LOGS_DIR / name
    path.write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(records)} rows)")


def _session_001() -> list[dict[str, object]]:
    """Long fermentation, stable plateau, manual trigger near peak."""
    start = datetime(2026, 5, 20, 9, 0, 0)
    records: list[dict[str, object]] = []
    initial = 20.0
    for minute in range(0, 540, 2):
        t = start + timedelta(minutes=minute)
        if minute < 60:
            h = initial + minute * 0.02
        elif minute < 420:
            growth = 25.0 * (1 - math.exp(-(minute - 60) / 90.0))
            h = initial + growth
        elif minute < 480:
            h = initial + 25.0 - (minute - 420) * 0.05
        else:
            h = initial + 22.0 - (minute - 480) * 0.4
        records.append(
            {
                "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
                "height_mm": round(h, 2),
                "temperature_c": 26.0,
            }
        )
    return records


def _session_002() -> list[dict[str, object]]:
    """Manual trigger while still actively growing."""
    start = datetime(2026, 5, 21, 9, 0, 0)
    records: list[dict[str, object]] = []
    initial = 18.0
    for minute in range(0, 540, 2):
        t = start + timedelta(minutes=minute)
        if minute < 60:
            h = initial + minute * 0.05
        elif minute < 360:
            h = initial + 3 + (minute - 60) * 0.08
        elif minute < 420:
            h = initial + 3 + 300 * 0.08 - (minute - 360) * 0.05
        else:
            h = initial + 3 + 300 * 0.08 - 60 * 0.05 - (minute - 420) * 0.2
        records.append(
            {
                "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
                "height_mm": round(max(h, 0), 2),
                "temperature_c": 25.5,
            }
        )
    return records


def main() -> None:
    _write_log("session_001.json", _session_001())
    _write_log("session_002.json", _session_002())


if __name__ == "__main__":
    main()
