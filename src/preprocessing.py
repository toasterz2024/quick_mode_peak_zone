"""Session-level preprocessing: cleaning, elapsed time, initial height, t100."""

from __future__ import annotations

import pandas as pd

from config import T100_DETECTION_WINDOW_MINUTES


def prepare_session_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, deduplicate, drop invalid rows and compute ``elapsed_minutes``.

    The input is expected to follow the normalized schema produced by
    :func:`src.data_loader.normalize_log_to_dataframe`.
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    out = out.dropna(subset=["timestamp", "height_mm"])
    out = out.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    out = out.drop_duplicates(subset=["timestamp"], keep="first").reset_index(drop=True)

    if out.empty:
        return out

    first_ts = out["timestamp"].iloc[0]
    out["elapsed_minutes"] = (
        (out["timestamp"] - first_ts).dt.total_seconds() / 60.0
    )
    return out


def calculate_initial_height(df: pd.DataFrame, *, window_minutes: int | None = None) -> float | None:
    """Minimum non-zero height during the first ``window_minutes`` of the session."""
    if df.empty:
        return None

    window = window_minutes if window_minutes is not None else T100_DETECTION_WINDOW_MINUTES
    first_ts = df["timestamp"].iloc[0]
    cutoff = first_ts + pd.Timedelta(minutes=window)

    early = df[(df["timestamp"] >= first_ts) & (df["timestamp"] <= cutoff)]
    nonzero = early[early["height_mm"] > 0]
    if nonzero.empty:
        return None
    return float(nonzero["height_mm"].min())


def calculate_t100_time(
    df: pd.DataFrame,
    initial_height: float | None,
) -> pd.Timestamp | None:
    """First timestamp where ``height_mm`` reaches ``2 * initial_height``."""
    if df.empty or initial_height is None or initial_height <= 0:
        return None

    threshold = initial_height * 2.0
    mask = df["height_mm"] >= threshold
    if not mask.any():
        return None
    return df.loc[mask, "timestamp"].iloc[0]
