"""Tests for peak detection and plateau duration (spec section 7)."""

from __future__ import annotations

import pandas as pd

from src.peak_analysis import calculate_peak_plateau, get_real_peak


def _build_df(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([r[0] for r in rows]).tz_localize("Asia/Seoul"),
            "height_mm": [r[1] for r in rows],
        }
    )


def test_real_peak_uses_first_timestamp_on_ties() -> None:
    df = _build_df(
        [
            ("2026-05-20 10:00", 10.0),
            ("2026-05-20 10:01", 30.0),
            ("2026-05-20 10:02", 30.0),
            ("2026-05-20 10:03", 28.0),
        ]
    )
    info = get_real_peak(df, metadata_row=None)
    assert info["real_peak_height"] == 30.0
    assert info["real_peak_time"] == df["timestamp"].iloc[1]


def test_peak_end_ignores_single_noisy_dip() -> None:
    """A 1-min dip below the threshold must NOT end the plateau."""
    rows = [(f"2026-05-20 10:{m:02d}", 30.0) for m in range(0, 5)]
    rows += [("2026-05-20 10:05", 25.0)]
    rows += [(f"2026-05-20 10:{m:02d}", 30.0) for m in range(6, 20)]
    df = _build_df(rows)

    plateau = calculate_peak_plateau(
        df,
        real_peak_time=df["timestamp"].iloc[0],
        real_peak_height=30.0,
        drop_threshold_mm=3.0,
        end_below_threshold_minutes=5,
    )
    assert plateau["peak_end_time"] == df["timestamp"].iloc[-1]


def test_peak_end_triggers_on_sustained_drop() -> None:
    """A 5-minute continuous drop below the threshold must end the plateau."""
    rows = [(f"2026-05-20 10:{m:02d}", 30.0) for m in range(0, 5)]
    rows += [(f"2026-05-20 10:{m:02d}", 20.0) for m in range(5, 15)]
    df = _build_df(rows)

    plateau = calculate_peak_plateau(
        df,
        real_peak_time=df["timestamp"].iloc[0],
        real_peak_height=30.0,
        drop_threshold_mm=3.0,
        end_below_threshold_minutes=5,
    )
    assert plateau["peak_end_time"] == pd.Timestamp("2026-05-20 10:05", tz="Asia/Seoul")


def test_peak_end_search_only_after_real_peak_time() -> None:
    """An early dip before ``real_peak_time`` must not be treated as plateau end."""
    rows = [
        ("2026-05-20 09:00", 10.0),
        ("2026-05-20 09:10", 10.0),
        ("2026-05-20 09:20", 10.0),
        ("2026-05-20 09:30", 10.0),
        ("2026-05-20 09:40", 10.0),
        ("2026-05-20 10:00", 30.0),
        ("2026-05-20 10:01", 30.0),
        ("2026-05-20 10:02", 30.0),
    ]
    df = _build_df(rows)
    plateau = calculate_peak_plateau(
        df,
        real_peak_time=pd.Timestamp("2026-05-20 10:00", tz="Asia/Seoul"),
        real_peak_height=30.0,
        drop_threshold_mm=3.0,
        end_below_threshold_minutes=5,
    )
    assert plateau["peak_end_time"] == df["timestamp"].iloc[-1]
    assert plateau["peak_start_time"] == df["timestamp"].iloc[-3]
