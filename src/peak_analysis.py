"""Real peak detection and analytical peak plateau duration.

The plateau analytics are display-only: they MUST NOT participate in Layer 2
validation (see spec section 7).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    PEAK_END_BELOW_THRESHOLD_MINUTES,
    PEAK_PLATEAU_DROP_THRESHOLD_MM,
)


def get_real_peak(df: pd.DataFrame, metadata_row: pd.Series | None = None) -> dict[str, Any]:
    """Return ``real_peak_time`` and ``real_peak_height``.

    If the metadata contains a non-empty ``real_peak_time_manual``, that value
    is used. Otherwise the maximum of ``height_mm`` is taken and the *first*
    timestamp with that height is returned (deterministic on ties).
    """
    if df.empty:
        return {"real_peak_time": None, "real_peak_height": None}

    real_peak_height = float(df["height_mm"].max())

    real_peak_time: pd.Timestamp | None
    manual_value = None
    if metadata_row is not None and "real_peak_time_manual" in metadata_row.index:
        manual_value = metadata_row["real_peak_time_manual"]

    if manual_value is not None and not pd.isna(manual_value):
        real_peak_time = pd.Timestamp(manual_value)
    else:
        mask = df["height_mm"] >= real_peak_height
        real_peak_time = df.loc[mask, "timestamp"].iloc[0]

    return {
        "real_peak_time": real_peak_time,
        "real_peak_height": real_peak_height,
    }


def calculate_peak_plateau(
    df: pd.DataFrame,
    real_peak_time: pd.Timestamp | None,
    real_peak_height: float | None,
    *,
    drop_threshold_mm: float = PEAK_PLATEAU_DROP_THRESHOLD_MM,
    end_below_threshold_minutes: int = PEAK_END_BELOW_THRESHOLD_MINUTES,
) -> dict[str, Any]:
    """Compute ``peak_start_time``, ``peak_end_time`` and the duration in minutes.

    Rules (spec section 7):

    - ``peak_start_time`` is the first timestamp where
      ``height_mm >= real_peak_height - drop_threshold_mm``.
    - ``peak_end_time`` is searched **only after** ``real_peak_time``. The peak
      ends at the first timestamp ``t*`` such that the height stays *strictly*
      below the threshold for ``end_below_threshold_minutes`` consecutive
      minutes. A single noisy dip does not end the peak.
    - If no sustained drop is observed, ``peak_end_time`` is the last timestamp
      in the log.
    """
    if df.empty or real_peak_height is None or real_peak_time is None:
        return {
            "peak_start_time": None,
            "peak_end_time": None,
            "peak_duration_minutes": None,
        }

    threshold = real_peak_height - drop_threshold_mm

    start_mask = df["height_mm"] >= threshold
    if not start_mask.any():
        return {
            "peak_start_time": None,
            "peak_end_time": None,
            "peak_duration_minutes": None,
        }
    peak_start_time = df.loc[start_mask, "timestamp"].iloc[0]

    after = df[df["timestamp"] >= real_peak_time].reset_index(drop=True)
    peak_end_time = _find_sustained_drop_end(
        after,
        threshold=threshold,
        sustain_minutes=end_below_threshold_minutes,
    )
    if peak_end_time is None:
        peak_end_time = df["timestamp"].iloc[-1]

    peak_duration_minutes = (
        (peak_end_time - peak_start_time).total_seconds() / 60.0
    )

    return {
        "peak_start_time": peak_start_time,
        "peak_end_time": peak_end_time,
        "peak_duration_minutes": float(peak_duration_minutes),
    }


def _find_sustained_drop_end(
    after_peak_df: pd.DataFrame,
    *,
    threshold: float,
    sustain_minutes: int,
) -> pd.Timestamp | None:
    """Return the timestamp at which a sustained drop below ``threshold`` starts.

    The "sustained drop" is the first timestamp ``t*`` such that for the entire
    window ``[t*, t* + sustain_minutes]`` every recorded height is strictly
    below ``threshold``. If any point inside the window is at or above the
    threshold, the dip is treated as noise and the search resumes after it.
    """
    if after_peak_df.empty:
        return None

    sustain = pd.Timedelta(minutes=sustain_minutes)
    times = after_peak_df["timestamp"].to_numpy()
    heights = after_peak_df["height_mm"].to_numpy()
    n = len(times)

    for i in range(n):
        if heights[i] >= threshold:
            continue
        window_end_required = times[i] + sustain
        if times[-1] < window_end_required:
            return None

        j = i
        sustained = True
        while j < n and times[j] <= window_end_required:
            if heights[j] >= threshold:
                sustained = False
                break
            j += 1

        if sustained:
            return pd.Timestamp(times[i])

    return None
