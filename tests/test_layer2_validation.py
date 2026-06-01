"""Tests for firmware-compatible Layer 2 validation (spec sections 8–11)."""

from __future__ import annotations

import pandas as pd

from src.layer2_validation import (
    INSUFFICIENT,
    INVALID,
    NO_LOG_ROW_WITHIN_TOLERANCE,
    T100_NOT_REACHED,
    VALID,
    validate_manual_layer2_trigger,
)


def _series(
    timestamps: list[str],
    heights: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps).tz_localize("Asia/Seoul"),
            "height_mm": heights,
        }
    )


def _stable_plateau_df() -> pd.DataFrame:
    """40 min of growth, then a long stable plateau (well past 10 minutes wide)."""
    times: list[str] = []
    heights: list[float] = []
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    for minute in range(0, 120):
        ts = base + pd.Timedelta(minutes=minute)
        times.append(ts.strftime("%Y-%m-%d %H:%M:%S"))
        if minute < 40:
            heights.append(10.0 + minute * 0.5)
        else:
            heights.append(10.0 + 40 * 0.5)
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(times).tz_localize("Asia/Seoul"),
            "height_mm": heights,
        }
    )
    return df


def test_condition_1_includes_current_point_firmware_compatible() -> None:
    """If current point is itself the 30-min max, condition_1 passes trivially."""
    df = _series(
        [f"2026-05-20 09:{m:02d}" for m in range(0, 60)],
        [10.0 + i * 0.5 for i in range(60)],
    )
    trigger = pd.Timestamp("2026-05-20 09:59", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:20", tz="Asia/Seoul"),
    )
    assert result["condition_1"] is True


def test_condition_2_signed_change_falling_height_passes() -> None:
    """Falling height (signed change negative) must pass condition_2."""
    rows: list[tuple[str, float]] = []
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    for minute in range(0, 60):
        rows.append((base + pd.Timedelta(minutes=minute), 30.0 + minute * 0.3))
    for minute in range(60, 80):
        rows.append((base + pd.Timedelta(minutes=minute), 48.0 - (minute - 60) * 0.5))
    df = pd.DataFrame(
        {
            "timestamp": [r[0] for r in rows],
            "height_mm": [r[1] for r in rows],
        }
    )

    trigger = pd.Timestamp("2026-05-20 10:15", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:30", tz="Asia/Seoul"),
    )
    change = result["manual_trigger_height_change_last_10min"]
    assert change is not None and change < 0
    assert result["condition_2"] is True


def test_condition_4_passes_when_no_positive_growth_reference() -> None:
    """If max_slope_last_60min <= 0, condition_4 passes (firmware behavior)."""
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    rows = [(base + pd.Timedelta(minutes=m), 50.0 - m * 0.1) for m in range(0, 80)]
    df = pd.DataFrame(
        {
            "timestamp": [r[0] for r in rows],
            "height_mm": [r[1] for r in rows],
        }
    )

    trigger = pd.Timestamp("2026-05-20 10:05", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul"),
    )
    assert result["manual_trigger_max_slope_last_60min"] is not None
    assert result["manual_trigger_max_slope_last_60min"] <= 0
    assert result["condition_4"] is True


def test_valid_manual_trigger_on_stable_plateau() -> None:
    df = _stable_plateau_df()
    trigger = pd.Timestamp("2026-05-20 10:25", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:25", tz="Asia/Seoul"),
    )
    assert result["validation_status"] == VALID
    assert result["manual_entry_layer2_valid"] is True


def test_invalid_manual_trigger_during_growth() -> None:
    """Trigger fired while height is still actively growing — should be invalid."""
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    rows = [(base + pd.Timedelta(minutes=m), 10.0 + m * 1.0) for m in range(0, 60)]
    df = pd.DataFrame(
        {
            "timestamp": [r[0] for r in rows],
            "height_mm": [r[1] for r in rows],
        }
    )
    trigger = pd.Timestamp("2026-05-20 09:40", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:10", tz="Asia/Seoul"),
    )
    assert result["validation_status"] == INVALID
    assert result["manual_entry_layer2_valid"] is False
    assert "condition_2" in result["failed_conditions_at_manual_entry"]


def test_no_log_row_within_tolerance() -> None:
    df = _stable_plateau_df()
    trigger = pd.Timestamp("2026-05-21 10:25", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:25", tz="Asia/Seoul"),
    )
    assert result["validation_status"] == NO_LOG_ROW_WITHIN_TOLERANCE


def test_t100_not_reached_returns_status() -> None:
    df = _stable_plateau_df()
    trigger = pd.Timestamp("2026-05-20 10:25", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=None,
    )
    assert result["validation_status"] == T100_NOT_REACHED
    assert result["manual_entry_layer2_valid"] is False


def test_insufficient_data_for_10min_lookup() -> None:
    """Trigger near start of log — no 10-min history available."""
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    rows = [(base + pd.Timedelta(minutes=m), 10.0 + m * 0.1) for m in range(0, 5)]
    df = pd.DataFrame(
        {
            "timestamp": [r[0] for r in rows],
            "height_mm": [r[1] for r in rows],
        }
    )
    trigger = pd.Timestamp("2026-05-20 09:02", tz="Asia/Seoul")
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul"),
    )
    assert result["condition_2"] == INSUFFICIENT


def test_height_10min_lookup_within_90_seconds_tolerance() -> None:
    """Lookup must succeed when the nearest point is within ±90 s of target."""
    base = pd.Timestamp("2026-05-20 09:00", tz="Asia/Seoul")
    timestamps = [base + pd.Timedelta(seconds=s) for s in range(0, 3600, 75)]
    heights = [10.0 + i * 0.3 for i in range(len(timestamps))]
    df = pd.DataFrame({"timestamp": timestamps, "height_mm": heights})

    trigger = timestamps[40]
    result = validate_manual_layer2_trigger(
        df,
        manual_peakzone_entry_time=trigger,
        t100_time=base + pd.Timedelta(minutes=2),
    )
    assert result["condition_2"] in (True, False)
