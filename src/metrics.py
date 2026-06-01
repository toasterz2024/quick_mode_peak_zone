"""Combine peak analysis and Layer 2 validation into one per-session record."""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS,
    MANUAL_TRIGGER_TOLERANCE_MINUTES,
    PEAK_END_BELOW_THRESHOLD_MINUTES,
    PEAK_PLATEAU_DROP_THRESHOLD_MM,
)
from src.layer2_validation import (
    ERROR,
    INVALID_LOG_FORMAT,
    MISSING_LOG_FILE,
    validate_manual_layer2_trigger,
)
from src.peak_analysis import calculate_peak_plateau, get_real_peak
from src.preprocessing import (
    calculate_initial_height,
    calculate_t100_time,
    prepare_session_dataframe,
)


def calculate_session_metrics(
    df: pd.DataFrame | None,
    metadata_row: pd.Series,
    *,
    peak_plateau_drop_threshold_mm: float = PEAK_PLATEAU_DROP_THRESHOLD_MM,
    peak_end_below_threshold_minutes: int = PEAK_END_BELOW_THRESHOLD_MINUTES,
    manual_trigger_tolerance_minutes: int = MANUAL_TRIGGER_TOLERANCE_MINUTES,
    height_10min_lookup_tolerance_seconds: int = HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS,
    load_error: str | None = None,
) -> dict[str, Any]:
    """Return all spec-defined metrics for a single session.

    ``df`` may be ``None`` when the log could not be loaded — in that case the
    ``load_error`` argument carries the failure mode (``missing_log_file`` or
    ``invalid_log_format``).
    """
    record: dict[str, Any] = {
        "session_id": _safe_str(metadata_row.get("session_id")),
        "device_id": _safe_str(metadata_row.get("device_id")),
        "mode": _safe_str(metadata_row.get("mode")),
        "start_time": metadata_row.get("start_time"),
        "end_time": metadata_row.get("end_time"),
        "notes": _safe_str(metadata_row.get("notes")),
        "device_reported_peak_time": metadata_row.get("device_reported_peak_time"),
        "device_reported_peak_height": metadata_row.get("device_reported_peak_height"),
        "device_reported_initial_height": metadata_row.get(
            "device_reported_initial_height"
        ),
        "real_peak_time": None,
        "real_peak_height": None,
        "peak_start_time": None,
        "peak_end_time": None,
        "peak_duration_minutes": None,
        "manual_peakzone_entry_time": metadata_row.get("manual_peakzone_entry_time"),
        "nearest_log_timestamp_to_manual_trigger": None,
        "manual_trigger_timestamp_diff_seconds": None,
        "manual_to_real_peak_diff_minutes": None,
        "manual_entry_layer2_valid": None,
        "failed_conditions_at_manual_entry": "",
        "validation_status": None,
        "manual_trigger_current_height": None,
        "manual_trigger_recent_max_30min": None,
        "manual_trigger_height_change_last_10min": None,
        "manual_trigger_max_last_5min": None,
        "manual_trigger_max_prev_30_ex_5min": None,
        "manual_trigger_slope_last_10min": None,
        "manual_trigger_max_slope_last_60min": None,
        "manual_trigger_t100_reached": None,
        "manual_trigger_time_since_t100_min": None,
        "t100_time": None,
        "initial_height": None,
    }

    if load_error == "missing_log_file":
        record["validation_status"] = MISSING_LOG_FILE
        return record
    if load_error == "invalid_log_format":
        record["validation_status"] = INVALID_LOG_FORMAT
        return record

    if df is None or df.empty:
        record["validation_status"] = MISSING_LOG_FILE
        return record

    try:
        prepared = prepare_session_dataframe(df)

        device_initial = metadata_row.get("device_reported_initial_height")
        if device_initial is not None and not pd.isna(device_initial) and device_initial > 0:
            initial_height = float(device_initial)
        else:
            initial_height = calculate_initial_height(prepared)
        t100_time = calculate_t100_time(prepared, initial_height)
        record["initial_height"] = initial_height
        record["t100_time"] = t100_time

        peak_info = get_real_peak(prepared, metadata_row)
        record["real_peak_time"] = peak_info["real_peak_time"]
        record["real_peak_height"] = peak_info["real_peak_height"]

        plateau = calculate_peak_plateau(
            prepared,
            peak_info["real_peak_time"],
            peak_info["real_peak_height"],
            drop_threshold_mm=peak_plateau_drop_threshold_mm,
            end_below_threshold_minutes=peak_end_below_threshold_minutes,
        )
        record.update(plateau)

        manual_time = record["manual_peakzone_entry_time"]
        if (
            manual_time is not None
            and not pd.isna(manual_time)
            and peak_info["real_peak_time"] is not None
        ):
            diff = (
                pd.Timestamp(manual_time) - peak_info["real_peak_time"]
            ).total_seconds() / 60.0
            record["manual_to_real_peak_diff_minutes"] = float(diff)

        validation = validate_manual_layer2_trigger(
            prepared,
            manual_peakzone_entry_time=(
                pd.Timestamp(manual_time)
                if manual_time is not None and not pd.isna(manual_time)
                else None
            ),
            t100_time=t100_time,
            tolerance_minutes=manual_trigger_tolerance_minutes,
            height_10min_lookup_tolerance_seconds=height_10min_lookup_tolerance_seconds,
        )

        record["validation_status"] = validation["validation_status"]
        record["manual_entry_layer2_valid"] = validation["manual_entry_layer2_valid"]
        record["failed_conditions_at_manual_entry"] = validation[
            "failed_conditions_at_manual_entry"
        ]
        record["nearest_log_timestamp_to_manual_trigger"] = validation[
            "nearest_log_timestamp"
        ]
        record["manual_trigger_timestamp_diff_seconds"] = validation[
            "timestamp_difference_seconds"
        ]
        for key in (
            "manual_trigger_current_height",
            "manual_trigger_recent_max_30min",
            "manual_trigger_height_change_last_10min",
            "manual_trigger_max_last_5min",
            "manual_trigger_max_prev_30_ex_5min",
            "manual_trigger_slope_last_10min",
            "manual_trigger_max_slope_last_60min",
            "manual_trigger_t100_reached",
            "manual_trigger_time_since_t100_min",
        ):
            record[key] = validation[key]

        record["condition_1"] = validation["condition_1"]
        record["condition_2"] = validation["condition_2"]
        record["condition_3"] = validation["condition_3"]
        record["condition_4"] = validation["condition_4"]
        record["condition_5_t100_reached"] = validation["condition_5_t100_reached"]

    except Exception as exc:  # pragma: no cover - defensive
        record["validation_status"] = ERROR
        record["error_message"] = repr(exc)

    return record


def _safe_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)
