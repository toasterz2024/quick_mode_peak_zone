"""Tests for timezone normalization and non-uniform timestamps (spec 5.4–5.5)."""

from __future__ import annotations

import pandas as pd

from src.data_loader import _normalize_timestamp_series, normalize_log_to_dataframe


def test_naive_log_timestamp_assumed_seoul() -> None:
    series = pd.Series(["2026-05-20 09:00:00", "2026-05-20 09:10:00"])
    parsed = _normalize_timestamp_series(series, assume_tz="Asia/Seoul")
    assert str(parsed.dt.tz) == "Asia/Seoul"
    assert parsed.iloc[0] == pd.Timestamp("2026-05-20 09:00:00", tz="Asia/Seoul")


def test_naive_metadata_timestamp_assumed_seoul() -> None:
    series = pd.Series(["2026-05-20 09:00:00"])
    parsed = _normalize_timestamp_series(series, assume_tz="Asia/Seoul")
    assert str(parsed.dt.tz) == "Asia/Seoul"


def test_utc_timestamp_converted_to_seoul() -> None:
    series = pd.Series(["2026-05-20T00:00:00Z"])
    parsed = _normalize_timestamp_series(series, assume_tz="Asia/Seoul")
    assert parsed.iloc[0] == pd.Timestamp("2026-05-20 09:00:00", tz="Asia/Seoul")


def test_non_uniform_timestamps_preserved() -> None:
    raw = {
        "records": [
            {"timestamp": "2026-05-20 09:00:00", "height_mm": 10.0},
            {"timestamp": "2026-05-20 09:01:13", "height_mm": 10.5},
            {"timestamp": "2026-05-20 09:04:47", "height_mm": 11.2},
        ]
    }
    df = normalize_log_to_dataframe(raw, session_id="S_TZ")
    assert len(df) == 3
    assert str(df["timestamp"].dt.tz) == "Asia/Seoul"
    assert df["timestamp"].is_monotonic_increasing
