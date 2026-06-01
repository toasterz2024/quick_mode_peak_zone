"""Tests for metadata JSON loading and log metadata auto-extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data_loader import (
    DataLoadError,
    _merge_with_log_metadata,
    extract_log_metadata,
    load_metadata,
    normalize_log_to_dataframe,
)


def _write_json(tmp_path: Path, name: str, payload) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_metadata_empty_array(tmp_path: Path) -> None:
    path = _write_json(tmp_path, "sessions_metadata.json", [])
    df = load_metadata(path, source_mode="local")
    assert df.empty
    assert "session_id" in df.columns


def test_load_metadata_with_entries(tmp_path: Path) -> None:
    payload = [
        {
            "session_id": "S001",
            "log_file": "session_001.json",
            "manual_peakzone_entry_time": "2026-05-20 16:42:00",
            "notes": "Good session",
        }
    ]
    path = _write_json(tmp_path, "sessions_metadata.json", payload)
    df = load_metadata(path, source_mode="local")
    assert len(df) == 1
    assert df.iloc[0]["session_id"] == "S001"
    assert str(df["manual_peakzone_entry_time"].dt.tz) == "Asia/Seoul"


def test_load_metadata_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(DataLoadError):
        load_metadata(path, source_mode="local")


def test_load_metadata_accepts_sessions_wrapper(tmp_path: Path) -> None:
    payload = {
        "sessions": [
            {
                "session_id": "S002",
                "log_file": "session_002.json",
                "manual_peakzone_entry_time": "2026-05-21 17:00:00",
            }
        ]
    }
    path = _write_json(tmp_path, "sessions_metadata.json", payload)
    df = load_metadata(path, source_mode="local")
    assert len(df) == 1


def test_extract_log_metadata_root_device_id() -> None:
    raw = {
        "device_id": "SourFriend-A494",
        "mode": "Quick",
        "records": [
            {"timestamp": "2026-05-20 09:00:00", "height_mm": 18.0},
            {"timestamp": "2026-05-20 09:05:00", "height_mm": 18.4},
        ],
    }
    df = normalize_log_to_dataframe(raw, session_id="S_TEST")
    info = extract_log_metadata(raw, df)
    assert info["device_id"] == "SourFriend-A494"
    assert info["mode"] == "Quick"
    assert info["start_time"] is not None
    assert info["end_time"] is not None


def test_extract_log_metadata_nested_section() -> None:
    raw = {
        "metadata": {"device_id": "SF-002", "program": "Auto"},
        "records": [
            {"timestamp": "2026-05-20 09:00:00", "height_mm": 18.0},
        ],
    }
    df = normalize_log_to_dataframe(raw, session_id="S_NESTED")
    info = extract_log_metadata(raw, df)
    assert info["device_id"] == "SF-002"
    assert info["mode"] == "Auto"


def test_extract_log_metadata_missing_fields() -> None:
    raw = {
        "records": [
            {"timestamp": "2026-05-20 09:00:00", "height_mm": 18.0},
        ],
    }
    df = normalize_log_to_dataframe(raw, session_id="S_BARE")
    info = extract_log_metadata(raw, df)
    assert info["device_id"] is None
    assert info["mode"] is None
    assert info["start_time"] is not None


def test_normalize_camelcase_real_device_log() -> None:
    """Real device logs use camelCase: measuredAt, containerTemp, doughHeight…"""
    raw = {
        "deviceId": "SourFriend-A494",
        "mode": "Auto",
        "records": [
            {
                "stepIndex": 0,
                "measuredAt": "2026-05-20T09:00:00Z",
                "elapsedSeconds": 0,
                "containerTemp": 26.0,
                "ambientTemp": 22.5,
                "humidity": 65,
                "height": 18.0,
                "lidOpen": False,
                "isOutlier": False,
            },
            {
                "stepIndex": 1,
                "measuredAt": "2026-05-20T09:05:00Z",
                "elapsedSeconds": 300,
                "containerTemp": 26.1,
                "ambientTemp": 22.6,
                "height": 18.4,
            },
        ],
    }
    df = normalize_log_to_dataframe(raw, session_id="S_REAL")
    assert "timestamp" in df.columns
    assert "height_mm" in df.columns
    assert "temperature_c" in df.columns
    assert df["height_mm"].iloc[0] == 18.0
    assert str(df["timestamp"].dt.tz) == "Asia/Seoul"

    info = extract_log_metadata(raw, df)
    assert info["device_id"] == "SourFriend-A494"
    assert info["mode"] == "Auto"


def test_merge_with_log_metadata_only_fills_missing() -> None:
    row = pd.Series(
        {
            "session_id": "S001",
            "log_file": "session_001.json",
            "manual_peakzone_entry_time": pd.Timestamp("2026-05-20 16:00", tz="Asia/Seoul"),
            "device_id": "MANUAL-OVERRIDE",
        }
    )
    raw = {
        "device_id": "FROM-LOG",
        "mode": "Quick",
        "records": [{"timestamp": "2026-05-20 09:00:00", "height_mm": 18.0}],
    }
    df = normalize_log_to_dataframe(raw, session_id="S001")

    merged = _merge_with_log_metadata(row, raw, df)
    assert merged["device_id"] == "MANUAL-OVERRIDE"
    assert merged["mode"] == "Quick"
    assert "start_time" in merged.index
