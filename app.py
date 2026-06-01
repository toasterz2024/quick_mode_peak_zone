"""Streamlit entry point for the Peak Zone Manual Trigger Validation Dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import config
from src.data_loader import (
    DataLoadError,
    load_all_sessions,
    load_json_log,
    load_metadata,
    normalize_log_to_dataframe,
)
from src.metrics import calculate_session_metrics
from src.plots import (
    plot_height_with_events,
    plot_manual_trigger_diff_by_session,
    plot_peak_duration_by_session,
    plot_validation_status,
)
from src.preprocessing import prepare_session_dataframe

st.set_page_config(
    page_title="Peak Zone Manual Trigger Validation",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def cached_load_metadata(
    metadata_location: str, source_mode: str
) -> pd.DataFrame:
    return load_metadata(metadata_location, source_mode=source_mode)


@st.cache_data(show_spinner=False)
def cached_load_json_log(log_location: str, source_mode: str) -> dict[str, Any]:
    return load_json_log(log_location, source_mode=source_mode)


@st.cache_data(show_spinner=False)
def cached_process_session(
    session_id: str,
    log_location: str,
    metadata_row_json: str,
    source_mode: str,
    peak_plateau_drop_threshold_mm: float,
    peak_end_below_threshold_minutes: int,
    manual_trigger_tolerance_minutes: int,
) -> dict[str, Any]:
    metadata_row = pd.read_json(metadata_row_json, typ="series")
    for col in (
        "start_time",
        "manual_peakzone_entry_time",
        "real_peak_time_manual",
        "peak_start_time_manual",
        "peak_end_time_manual",
    ):
        if col in metadata_row.index and metadata_row[col] is not None:
            try:
                metadata_row[col] = pd.Timestamp(metadata_row[col])
            except (ValueError, TypeError):
                metadata_row[col] = None

    try:
        raw = cached_load_json_log(log_location, source_mode)
        df = normalize_log_to_dataframe(raw, session_id=session_id)
        load_error: str | None = None
    except DataLoadError as exc:
        df = None
        load_error = (
            "missing_log_file" if "not found" in str(exc).lower() else "invalid_log_format"
        )

    return calculate_session_metrics(
        df,
        metadata_row,
        peak_plateau_drop_threshold_mm=peak_plateau_drop_threshold_mm,
        peak_end_below_threshold_minutes=peak_end_below_threshold_minutes,
        manual_trigger_tolerance_minutes=manual_trigger_tolerance_minutes,
        load_error=load_error,
    )


@st.cache_data(show_spinner=False)
def cached_process_all_sessions(
    metadata_location: str,
    source_mode: str,
    peak_plateau_drop_threshold_mm: float,
    peak_end_below_threshold_minutes: int,
    manual_trigger_tolerance_minutes: int,
) -> pd.DataFrame:
    metadata_df = cached_load_metadata(metadata_location, source_mode)
    rows = []
    for _, row in metadata_df.iterrows():
        session_id = str(row.get("session_id", "")).strip()
        if not session_id:
            continue
        log_file = row.get("log_file")
        if not isinstance(log_file, str) or not log_file:
            rows.append(
                calculate_session_metrics(
                    None,
                    row,
                    peak_plateau_drop_threshold_mm=peak_plateau_drop_threshold_mm,
                    peak_end_below_threshold_minutes=peak_end_below_threshold_minutes,
                    manual_trigger_tolerance_minutes=manual_trigger_tolerance_minutes,
                    load_error="missing_log_file",
                )
            )
            continue

        rows.append(
            cached_process_session(
                session_id=session_id,
                log_location=log_file,
                metadata_row_json=row.to_json(date_format="iso"),
                source_mode=source_mode,
                peak_plateau_drop_threshold_mm=peak_plateau_drop_threshold_mm,
                peak_end_below_threshold_minutes=peak_end_below_threshold_minutes,
                manual_trigger_tolerance_minutes=manual_trigger_tolerance_minutes,
            )
        )
    return pd.DataFrame(rows)


def _sidebar() -> dict[str, Any]:
    st.sidebar.header("Configuration")
    source_mode = st.sidebar.radio(
        "Data source",
        options=["local", "github_raw"],
        index=0 if config.DATA_SOURCE_MODE == "local" else 1,
        horizontal=True,
    )

    if source_mode == "local":
        metadata_location = str(config.LOCAL_METADATA_PATH)
        st.sidebar.caption(f"Local metadata: `{metadata_location}`")
    else:
        metadata_location = st.sidebar.text_input(
            "Metadata path (relative to GITHUB_RAW_BASE_URL)",
            value=config.GITHUB_METADATA_PATH,
        )

    drop_threshold = st.sidebar.number_input(
        "peak_plateau_drop_threshold_mm",
        min_value=0.5,
        max_value=20.0,
        value=float(config.PEAK_PLATEAU_DROP_THRESHOLD_MM),
        step=0.5,
    )
    end_below_minutes = st.sidebar.number_input(
        "peak_end_below_threshold_minutes",
        min_value=1,
        max_value=60,
        value=int(config.PEAK_END_BELOW_THRESHOLD_MINUTES),
        step=1,
    )
    manual_tolerance = st.sidebar.number_input(
        "manual trigger tolerance (minutes)",
        min_value=1,
        max_value=15,
        value=int(config.MANUAL_TRIGGER_TOLERANCE_MINUTES),
        step=1,
    )

    st.sidebar.divider()
    if st.sidebar.button("Clear cache"):
        st.cache_data.clear()
        st.sidebar.success("Cache cleared")

    return {
        "source_mode": source_mode,
        "metadata_location": metadata_location,
        "drop_threshold": float(drop_threshold),
        "end_below_minutes": int(end_below_minutes),
        "manual_tolerance": int(manual_tolerance),
    }


def _apply_filters(
    results_df: pd.DataFrame, metadata_df: pd.DataFrame
) -> pd.DataFrame:
    if results_df.empty:
        return results_df

    st.sidebar.header("Filters")
    device_options = sorted(
        [d for d in results_df["device_id"].dropna().unique().tolist() if d]
    )
    devices = st.sidebar.multiselect("Device", options=device_options)
    mode_options = sorted(
        [m for m in results_df["mode"].dropna().unique().tolist() if m]
    )
    modes = st.sidebar.multiselect("Mode", options=mode_options)
    only_invalid = st.sidebar.checkbox("Show only invalid manual triggers")
    only_after_peak = st.sidebar.checkbox(
        "Show only sessions where manual trigger is AFTER real peak"
    )
    only_no_row = st.sidebar.checkbox(
        "Show only sessions where no log row exists near manual trigger"
    )

    filtered = results_df.copy()
    if devices:
        filtered = filtered[filtered["device_id"].isin(devices)]
    if modes:
        filtered = filtered[filtered["mode"].isin(modes)]
    if only_invalid:
        filtered = filtered[filtered["validation_status"] == "invalid"]
    if only_after_peak:
        filtered = filtered[
            filtered["manual_to_real_peak_diff_minutes"].fillna(0) < 0
        ]
    if only_no_row:
        filtered = filtered[
            filtered["validation_status"] == "no_log_row_within_tolerance"
        ]
    return filtered


def _overview_tab(results_df: pd.DataFrame) -> None:
    st.subheader("Overview")
    if results_df.empty:
        st.info("No sessions to display.")
        return

    total = len(results_df)
    with_manual = results_df["manual_peakzone_entry_time"].notna().sum()
    valid_count = (results_df["validation_status"] == "valid").sum()
    invalid_count = (results_df["validation_status"] == "invalid").sum()
    before_peak = (
        results_df["manual_to_real_peak_diff_minutes"].fillna(0) > 0
    ).sum()
    after_peak = (
        results_df["manual_to_real_peak_diff_minutes"].fillna(0) < 0
    ).sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total sessions", total)
    c2.metric("With manual trigger", int(with_manual))
    c3.metric("Valid (Layer 2)", int(valid_count))
    c4.metric("Invalid (Layer 2)", int(invalid_count))

    c5, c6, c7, c8 = st.columns(4)
    avg_diff = results_df["manual_to_real_peak_diff_minutes"].mean()
    med_diff = results_df["manual_to_real_peak_diff_minutes"].median()
    avg_dur = results_df["peak_duration_minutes"].mean()
    med_dur = results_df["peak_duration_minutes"].median()
    c5.metric("Avg manual diff (min)", _fmt(avg_diff))
    c6.metric("Median manual diff (min)", _fmt(med_diff))
    c7.metric("Avg peak duration (min)", _fmt(avg_dur))
    c8.metric("Median peak duration (min)", _fmt(med_dur))

    c9, c10 = st.columns(2)
    c9.metric(
        "Manual trigger before peak",
        f"{(before_peak / max(total, 1)) * 100:.1f}%",
    )
    c10.metric(
        "Manual trigger after peak",
        f"{(after_peak / max(total, 1)) * 100:.1f}%",
    )

    st.divider()
    st.plotly_chart(plot_validation_status(results_df), use_container_width=True)
    st.plotly_chart(
        plot_manual_trigger_diff_by_session(results_df), use_container_width=True
    )
    st.plotly_chart(
        plot_peak_duration_by_session(results_df), use_container_width=True
    )


def _session_detail_tab(
    results_df: pd.DataFrame,
    sidebar: dict[str, Any],
) -> None:
    st.subheader("Session detail")
    if results_df.empty:
        st.info("No sessions to display.")
        return

    session_id = st.selectbox("Session", options=results_df["session_id"].tolist())
    if session_id is None:
        return

    record = results_df[results_df["session_id"] == session_id].iloc[0].to_dict()
    metadata_df = cached_load_metadata(
        sidebar["metadata_location"], sidebar["source_mode"]
    )
    metadata_row = metadata_df[metadata_df["session_id"] == session_id].iloc[0]
    log_file = metadata_row.get("log_file")

    df = None
    if isinstance(log_file, str) and log_file:
        try:
            raw = cached_load_json_log(log_file, sidebar["source_mode"])
            df = prepare_session_dataframe(
                normalize_log_to_dataframe(raw, session_id=session_id)
            )
        except DataLoadError as exc:
            st.error(f"Failed to load log: {exc}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("validation_status", str(record.get("validation_status")))
    c2.metric(
        "manual_to_real_peak_diff (min)",
        _fmt(record.get("manual_to_real_peak_diff_minutes")),
    )
    c3.metric(
        "peak_duration (min)", _fmt(record.get("peak_duration_minutes"))
    )
    c4.metric(
        "manual_entry_layer2_valid",
        str(record.get("manual_entry_layer2_valid")),
    )

    if df is not None and not df.empty:
        st.plotly_chart(
            plot_height_with_events(df, record), use_container_width=True
        )

    st.markdown("### Layer 2 condition values at manual trigger")
    condition_rows = [
        {
            "condition": "condition_1",
            "formula": "current_height >= recent_max_30min − 5",
            "value": _fmt(record.get("manual_trigger_recent_max_30min")),
            "passed": record.get("condition_1"),
        },
        {
            "condition": "condition_2",
            "formula": "(current − height_10min_ago) ≤ 1 (signed)",
            "value": _fmt(record.get("manual_trigger_height_change_last_10min")),
            "passed": record.get("condition_2"),
        },
        {
            "condition": "condition_3",
            "formula": "max_last_5min ≤ max_prev_30_ex_5min + 1",
            "value": (
                f"{_fmt(record.get('manual_trigger_max_last_5min'))} vs "
                f"{_fmt(record.get('manual_trigger_max_prev_30_ex_5min'))}"
            ),
            "passed": record.get("condition_3"),
        },
        {
            "condition": "condition_4",
            "formula": "slope_last_10min ≤ 0.3 × max_slope_last_60min",
            "value": (
                f"{_fmt(record.get('manual_trigger_slope_last_10min'))} vs "
                f"{_fmt(record.get('manual_trigger_max_slope_last_60min'))}"
            ),
            "passed": record.get("condition_4"),
        },
        {
            "condition": "condition_5",
            "formula": "t100_reached",
            "value": record.get("manual_trigger_t100_reached"),
            "passed": record.get("condition_5_t100_reached"),
        },
    ]
    st.dataframe(pd.DataFrame(condition_rows), use_container_width=True)


def _manual_validation_tab(results_df: pd.DataFrame) -> None:
    st.subheader("Manual Trigger Validation")
    if results_df.empty:
        st.info("No sessions to display.")
        return

    cols = [
        "session_id",
        "manual_peakzone_entry_time",
        "nearest_log_timestamp_to_manual_trigger",
        "manual_trigger_timestamp_diff_seconds",
        "manual_entry_layer2_valid",
        "validation_status",
        "failed_conditions_at_manual_entry",
    ]
    available = [c for c in cols if c in results_df.columns]
    st.dataframe(results_df[available], use_container_width=True)


def _all_sessions_tab(results_df: pd.DataFrame) -> None:
    st.subheader("All sessions")
    if results_df.empty:
        st.info("No sessions to display.")
        return

    st.dataframe(results_df, use_container_width=True)
    csv = results_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download peakzone_validation_results.csv",
        data=csv,
        file_name="peakzone_validation_results.csv",
        mime="text/csv",
    )


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


def main() -> None:
    st.title("Peak Zone Manual Trigger Validation Dashboard")
    st.caption(
        "Validates manually recorded Layer 2 trigger time using firmware-compatible logic. "
        "Does NOT auto-detect Peak Zone entry."
    )

    sidebar = _sidebar()

    try:
        metadata_df = cached_load_metadata(
            sidebar["metadata_location"], sidebar["source_mode"]
        )
    except DataLoadError as exc:
        st.error(f"Cannot load metadata: {exc}")
        st.stop()

    try:
        results_df = cached_process_all_sessions(
            metadata_location=sidebar["metadata_location"],
            source_mode=sidebar["source_mode"],
            peak_plateau_drop_threshold_mm=sidebar["drop_threshold"],
            peak_end_below_threshold_minutes=sidebar["end_below_minutes"],
            manual_trigger_tolerance_minutes=sidebar["manual_tolerance"],
        )
    except Exception as exc:  # pragma: no cover - defensive UI guard
        st.error(f"Failed to process sessions: {exc}")
        st.stop()

    filtered = _apply_filters(results_df, metadata_df)

    overview, detail, validation, all_sessions = st.tabs(
        ["Overview", "Session Detail", "Manual Trigger Validation", "All Sessions"]
    )
    with overview:
        _overview_tab(filtered)
    with detail:
        _session_detail_tab(filtered, sidebar)
    with validation:
        _manual_validation_tab(filtered)
    with all_sessions:
        _all_sessions_tab(filtered)


if __name__ == "__main__":
    main()
