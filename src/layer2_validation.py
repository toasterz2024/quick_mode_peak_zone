"""Firmware-compatible Layer 2 condition validation at the manual trigger time.

Critical reminders (see spec sections 8–10):

- This module MUST NOT scan the log for the first timestamp where all
  conditions are true. It only validates the manually recorded trigger time.
- Condition 1: current point IS included in the 30-minute max window
  (matches firmware ``getMaxHeightLastNMin(30)``).
- Condition 2: signed change ``current - height_10min_ago``. Falling height
  passes the condition.
- Condition 4: when ``max_slope_last_60min <= 0`` the condition PASSES.
- Condition 5: stored as ``t100_reached`` (bool). Diagnostics keep
  ``time_since_t100_min`` separately.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS,
    HEIGHT_CHANGE_10MIN_THRESHOLD_MM,
    MANUAL_TRIGGER_TOLERANCE_MINUTES,
    MAX_5MIN_VS_PREV_30_DELTA_MM,
    NEAR_MAX_TOLERANCE_MM,
    SLOPE_RATIO_THRESHOLD,
)

INSUFFICIENT = "insufficient_data"

VALID = "valid"
INVALID = "invalid"
MISSING_MANUAL_TRIGGER = "missing_manual_trigger"
NO_LOG_ROW_WITHIN_TOLERANCE = "no_log_row_within_tolerance"
INSUFFICIENT_DATA = "insufficient_data"
MISSING_LOG_FILE = "missing_log_file"
INVALID_LOG_FORMAT = "invalid_log_format"
T100_NOT_REACHED = "t100_not_reached"
ERROR = "error"


def get_nearest_row(
    df: pd.DataFrame,
    target_time: pd.Timestamp,
    *,
    tolerance_seconds: int,
) -> pd.Series | None:
    """Return the row whose ``timestamp`` is closest to ``target_time``."""
    if df.empty or target_time is None or pd.isna(target_time):
        return None

    deltas = (df["timestamp"] - target_time).abs()
    idx = deltas.idxmin()
    if deltas.loc[idx].total_seconds() > tolerance_seconds:
        return None
    return df.loc[idx]


def validate_manual_layer2_trigger(
    df: pd.DataFrame,
    manual_peakzone_entry_time: pd.Timestamp | None,
    t100_time: pd.Timestamp | None,
    *,
    tolerance_minutes: int = MANUAL_TRIGGER_TOLERANCE_MINUTES,
    height_10min_lookup_tolerance_seconds: int = HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Validate firmware-compatible Layer 2 conditions at the manual trigger.

    Returns a dictionary with the condition pass/fail flags, raw diagnostic
    values and a fixed ``validation_status`` from the enum defined in spec
    section 11. The function never raises on missing data — instead it returns
    an appropriate ``validation_status``.
    """
    result: dict[str, Any] = {
        "validation_status": None,
        "manual_entry_layer2_valid": None,
        "failed_conditions_at_manual_entry": "",
        "nearest_log_timestamp": None,
        "timestamp_difference_seconds": None,
        "condition_1": None,
        "condition_2": None,
        "condition_3": None,
        "condition_4": None,
        "condition_5_t100_reached": None,
        "manual_trigger_current_height": None,
        "manual_trigger_recent_max_30min": None,
        "manual_trigger_height_change_last_10min": None,
        "manual_trigger_max_last_5min": None,
        "manual_trigger_max_prev_30_ex_5min": None,
        "manual_trigger_slope_last_10min": None,
        "manual_trigger_max_slope_last_60min": None,
        "manual_trigger_t100_reached": None,
        "manual_trigger_time_since_t100_min": None,
    }

    if manual_peakzone_entry_time is None or pd.isna(manual_peakzone_entry_time):
        result["validation_status"] = MISSING_MANUAL_TRIGGER
        return result

    if df.empty:
        result["validation_status"] = NO_LOG_ROW_WITHIN_TOLERANCE
        return result

    nearest = get_nearest_row(
        df,
        manual_peakzone_entry_time,
        tolerance_seconds=tolerance_minutes * 60,
    )
    if nearest is None:
        result["validation_status"] = NO_LOG_ROW_WITHIN_TOLERANCE
        return result

    current_time = nearest["timestamp"]
    current_height = float(nearest["height_mm"])
    result["nearest_log_timestamp"] = current_time
    result["timestamp_difference_seconds"] = float(
        (current_time - manual_peakzone_entry_time).total_seconds()
    )
    result["manual_trigger_current_height"] = current_height

    if t100_time is None:
        result["condition_5_t100_reached"] = False
        result["manual_trigger_t100_reached"] = False
        result["manual_trigger_time_since_t100_min"] = None
        result["validation_status"] = T100_NOT_REACHED
        result["manual_entry_layer2_valid"] = False
        return result

    t100_reached = current_time >= t100_time
    result["condition_5_t100_reached"] = bool(t100_reached)
    result["manual_trigger_t100_reached"] = bool(t100_reached)
    result["manual_trigger_time_since_t100_min"] = float(
        (current_time - t100_time).total_seconds() / 60.0
    )
    if not t100_reached:
        result["validation_status"] = T100_NOT_REACHED
        result["manual_entry_layer2_valid"] = False
        return result

    recent_max_30min = _max_in_window(
        df, current_time - pd.Timedelta(minutes=30), current_time
    )
    if recent_max_30min is None:
        result["condition_1"] = INSUFFICIENT
    else:
        result["manual_trigger_recent_max_30min"] = recent_max_30min
        result["condition_1"] = bool(
            current_height >= recent_max_30min - NEAR_MAX_TOLERANCE_MM
        )

    height_10min_ago = _nearest_height(
        df,
        current_time - pd.Timedelta(minutes=10),
        tolerance_seconds=height_10min_lookup_tolerance_seconds,
    )
    if height_10min_ago is None:
        result["condition_2"] = INSUFFICIENT
        slope_last_10min: float | None = None
    else:
        signed_change = current_height - height_10min_ago
        result["manual_trigger_height_change_last_10min"] = signed_change
        result["condition_2"] = bool(signed_change <= HEIGHT_CHANGE_10MIN_THRESHOLD_MM)
        slope_last_10min = signed_change / 10.0
        result["manual_trigger_slope_last_10min"] = slope_last_10min

    max_last_5min = _max_in_window(
        df, current_time - pd.Timedelta(minutes=5), current_time
    )
    max_prev_30_ex_5min = _max_in_window(
        df,
        current_time - pd.Timedelta(minutes=35),
        current_time - pd.Timedelta(minutes=5),
        right_inclusive=False,
    )
    if max_last_5min is None or max_prev_30_ex_5min is None:
        result["condition_3"] = INSUFFICIENT
    else:
        result["manual_trigger_max_last_5min"] = max_last_5min
        result["manual_trigger_max_prev_30_ex_5min"] = max_prev_30_ex_5min
        result["condition_3"] = bool(
            max_last_5min <= max_prev_30_ex_5min + MAX_5MIN_VS_PREV_30_DELTA_MM
        )

    max_slope_last_60min = _max_slope_in_window(
        df,
        current_time - pd.Timedelta(minutes=60),
        current_time,
        height_10min_lookup_tolerance_seconds=height_10min_lookup_tolerance_seconds,
    )
    if slope_last_10min is None or max_slope_last_60min is None:
        result["condition_4"] = INSUFFICIENT
    else:
        result["manual_trigger_max_slope_last_60min"] = max_slope_last_60min
        if max_slope_last_60min <= 0:
            result["condition_4"] = True
        else:
            result["condition_4"] = bool(
                slope_last_10min <= SLOPE_RATIO_THRESHOLD * max_slope_last_60min
            )

    condition_values = (
        result["condition_1"],
        result["condition_2"],
        result["condition_3"],
        result["condition_4"],
        result["condition_5_t100_reached"],
    )

    if any(v == INSUFFICIENT for v in condition_values):
        result["validation_status"] = INSUFFICIENT_DATA
        result["manual_entry_layer2_valid"] = False
        result["failed_conditions_at_manual_entry"] = ", ".join(
            _failed_condition_labels(result, include_insufficient=True)
        )
        return result

    bool_values = [bool(v) for v in condition_values]
    all_true = all(bool_values)
    result["manual_entry_layer2_valid"] = all_true

    if all_true:
        result["validation_status"] = VALID
        result["failed_conditions_at_manual_entry"] = ""
    else:
        result["validation_status"] = INVALID
        result["failed_conditions_at_manual_entry"] = ", ".join(
            _failed_condition_labels(result, include_insufficient=False)
        )

    return result


def _failed_condition_labels(
    result: dict[str, Any],
    *,
    include_insufficient: bool,
) -> list[str]:
    labels = [
        ("condition_1", result["condition_1"]),
        ("condition_2", result["condition_2"]),
        ("condition_3", result["condition_3"]),
        ("condition_4", result["condition_4"]),
        ("condition_5", result["condition_5_t100_reached"]),
    ]
    failed: list[str] = []
    for name, value in labels:
        if value is True:
            continue
        if value == INSUFFICIENT and include_insufficient:
            failed.append(f"{name}({INSUFFICIENT})")
        elif value is False:
            failed.append(name)
        elif value is None and include_insufficient:
            failed.append(f"{name}({INSUFFICIENT})")
    return failed


def _max_in_window(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    right_inclusive: bool = True,
) -> float | None:
    if right_inclusive:
        mask = (df["timestamp"] >= start) & (df["timestamp"] <= end)
    else:
        mask = (df["timestamp"] >= start) & (df["timestamp"] < end)
    window = df.loc[mask, "height_mm"]
    if window.empty:
        return None
    return float(window.max())


def _nearest_height(
    df: pd.DataFrame,
    target_time: pd.Timestamp,
    *,
    tolerance_seconds: int,
) -> float | None:
    row = get_nearest_row(df, target_time, tolerance_seconds=tolerance_seconds)
    if row is None:
        return None
    return float(row["height_mm"])


def _max_slope_in_window(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    height_10min_lookup_tolerance_seconds: int,
) -> float | None:
    """Maximum 10-minute slope (mm/min) over ``(start, end]``.

    For every point ``p`` inside the window we look up the height closest to
    ``p - 10 minutes`` and compute the slope. The maximum signed slope is
    returned. ``None`` when the window contains no points or when no points
    have a valid 10-min lookup.
    """
    mask = (df["timestamp"] > start) & (df["timestamp"] <= end)
    window = df.loc[mask]
    if window.empty:
        return None

    max_slope: float | None = None
    for _, row in window.iterrows():
        ten_min_back = row["timestamp"] - pd.Timedelta(minutes=10)
        past_height = _nearest_height(
            df, ten_min_back, tolerance_seconds=height_10min_lookup_tolerance_seconds
        )
        if past_height is None:
            continue
        slope = (float(row["height_mm"]) - past_height) / 10.0
        if max_slope is None or slope > max_slope:
            max_slope = slope
    return max_slope
