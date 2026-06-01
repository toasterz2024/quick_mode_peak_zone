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
    _merge_with_log_metadata,
    extract_log_metadata,
    load_json_log,
    load_metadata,
    normalize_log_to_dataframe,
)
from src.metrics import calculate_session_metrics
from src.peak_analysis import calculate_peak_plateau, get_real_peak
from src.plots import (
    plot_height_with_events,
    plot_manual_trigger_diff_by_session,
    plot_peak_duration_by_session,
    plot_validation_status,
)
from src.preprocessing import (
    calculate_initial_height,
    calculate_t100_time,
    prepare_session_dataframe,
)

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

        try:
            raw = cached_load_json_log(log_file, source_mode)
            df = normalize_log_to_dataframe(raw, session_id=session_id)
            merged_row = _merge_with_log_metadata(row, raw, df)
            load_error: str | None = None
        except DataLoadError as exc:
            df = None
            merged_row = row
            load_error = (
                "missing_log_file"
                if "not found" in str(exc).lower()
                else "invalid_log_format"
            )

        rows.append(
            calculate_session_metrics(
                df,
                merged_row,
                peak_plateau_drop_threshold_mm=peak_plateau_drop_threshold_mm,
                peak_end_below_threshold_minutes=peak_end_below_threshold_minutes,
                manual_trigger_tolerance_minutes=manual_trigger_tolerance_minutes,
                load_error=load_error,
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
        "manual_entry_layer2_valid",
        str(record.get("manual_entry_layer2_valid")),
    )
    c3.metric(
        "peak_duration (min)", _fmt(record.get("peak_duration_minutes"))
    )
    failed_conds = record.get("failed_conditions_at_manual_entry")
    c4.metric(
        "failed conditions",
        str(failed_conds) if failed_conds else "—",
    )

    st.markdown("### Timing comparison")
    t1, t2, t3 = st.columns(3)
    t1.metric(
        "manual Peak Zone entry",
        _fmt_time(record.get("manual_peakzone_entry_time")),
    )
    t2.metric(
        "real peak time (computed)",
        _fmt_time(record.get("real_peak_time")),
    )
    diff_val = record.get("manual_to_real_peak_diff_minutes")
    t3.metric(
        "diff: manual − real peak (min)",
        _fmt(diff_val),
        help=(
            "Negative = manual trigger BEFORE real peak (device decided early).\n"
            "Positive = manual trigger AFTER real peak (device decided late)."
        ),
    )
    if diff_val is not None and not pd.isna(diff_val):
        if diff_val < -0.5:
            st.info(
                f"Manual trigger fired **{abs(diff_val):.1f} min before** the real peak."
            )
        elif diff_val > 0.5:
            st.warning(
                f"Manual trigger fired **{diff_val:.1f} min after** the real peak."
            )
        else:
            st.success("Manual trigger matched the real peak (within 30 s).")

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


def _add_session_tab(
    metadata_df: pd.DataFrame,
    sidebar: dict[str, Any],
) -> None:
    st.subheader("Add new session")
    st.caption(
        "Pick a log that is not yet registered in metadata. The app extracts "
        "device, start/end time and real peak from the log, and gives you a "
        "ready-to-paste JSON entry. You only need to set the Peak Zone trigger time."
    )

    if sidebar["source_mode"] != "local":
        st.info(
            "This helper currently works in `local` mode only. "
            "Switch the data source in the sidebar."
        )
        return

    logs_dir = config.LOCAL_LOGS_DIR
    if not logs_dir.exists():
        st.error(f"Logs directory not found: `{logs_dir}`")
        return

    all_logs = sorted(p.name for p in logs_dir.glob("*.json"))
    if not all_logs:
        st.info(f"No JSON logs found in `{logs_dir}`. Add a file and refresh.")
        return

    registered: set[str] = set()
    if not metadata_df.empty and "log_file" in metadata_df.columns:
        registered = {f for f in metadata_df["log_file"].dropna().tolist() if f}

    unregistered = [f for f in all_logs if f not in registered]
    if not unregistered:
        st.success(
            "All logs in `data/logs/` are already registered. "
            "Push a new log file to GitHub to see it here."
        )
        return

    log_file = st.selectbox(
        f"Unregistered logs ({len(unregistered)})", options=unregistered
    )
    if log_file is None:
        return

    try:
        raw = cached_load_json_log(log_file, "local")
        df = prepare_session_dataframe(
            normalize_log_to_dataframe(raw, session_id=Path(log_file).stem)
        )
    except DataLoadError as exc:
        st.error(f"Failed to load log: {exc}")
        return
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"Unexpected error parsing log: {exc}")
        return

    if df.empty:
        st.error("Log contains no usable records.")
        return

    log_meta = extract_log_metadata(raw, df)
    device_initial = log_meta.get("device_reported_initial_height")
    if device_initial is not None and device_initial > 0:
        initial_height = float(device_initial)
    else:
        initial_height = calculate_initial_height(df)
    t100_time = calculate_t100_time(df, initial_height)
    peak = get_real_peak(df, metadata_row=None)
    plateau = calculate_peak_plateau(
        df,
        peak.get("real_peak_time"),
        peak.get("real_peak_height"),
        drop_threshold_mm=sidebar["drop_threshold"],
        end_below_threshold_minutes=sidebar["end_below_minutes"],
    )

    session_date = df["timestamp"].iloc[0].strftime("%Y-%m-%d")
    st.markdown(f"### Auto-extracted info  ·  _{session_date}_")
    c1, c2, c3 = st.columns(3)
    c1.metric("device_id", log_meta.get("device_id") or "—")
    c2.metric("mode", log_meta.get("mode") or "—")
    c3.metric(
        "duration (h)",
        f"{(df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds() / 3600:.1f}",
    )

    c4, c5, c6 = st.columns(3)
    c4.metric("start_time", _fmt_time(log_meta.get("start_time")))
    c5.metric("end_time", _fmt_time(log_meta.get("end_time")))
    c6.metric("t100_time", _fmt_time(t100_time) if t100_time is not None else "not reached")

    c7, c8, c9 = st.columns(3)
    c7.metric("real_peak_time (computed)", _fmt_time(peak.get("real_peak_time")))
    c8.metric(
        "real_peak_height (computed)",
        f"{peak.get('real_peak_height'):.2f} mm" if peak.get("real_peak_height") else "—",
    )
    c9.metric(
        "peak_duration (min)", _fmt(plateau.get("peak_duration_minutes"))
    )

    device_peak_time = log_meta.get("device_reported_peak_time")
    device_peak_height = log_meta.get("device_reported_peak_height")
    if device_peak_time is not None or device_peak_height is not None:
        st.caption("Device-reported values (from the log's `heightAnalysis` section):")
        d1, d2, d3 = st.columns(3)
        d1.metric("device peak_time", _fmt_time(device_peak_time))
        d2.metric(
            "device peak_height",
            f"{device_peak_height:.2f} mm" if device_peak_height is not None else "—",
        )
        d3.metric(
            "device initial_height",
            f"{log_meta.get('device_reported_initial_height'):.2f} mm"
            if log_meta.get("device_reported_initial_height") is not None
            else "—",
        )

    chart_events = {
        "real_peak_time": peak.get("real_peak_time"),
        "t100_time": t100_time,
        "peak_start_time": plateau.get("peak_start_time"),
        "peak_end_time": plateau.get("peak_end_time"),
    }
    st.plotly_chart(plot_height_with_events(df, chart_events), use_container_width=True)

    st.divider()
    st.markdown("### Set manual Peak Zone trigger time")
    st.caption(
        "Use the chart above to locate when the device/app reported Peak Zone entry. "
        "By default we pre-fill the value with the calculated real peak time — adjust it."
    )

    default_dt = (
        log_meta.get("device_reported_peak_time")
        or peak.get("real_peak_time")
        or df["timestamp"].iloc[-1]
    )
    if hasattr(default_dt, "tz_convert"):
        default_dt = default_dt.tz_convert(config.DEFAULT_TIMEZONE)
    elif hasattr(default_dt, "tz_localize") and default_dt.tz is None:
        default_dt = default_dt.tz_localize(config.DEFAULT_TIMEZONE)

    c_date, c_time = st.columns(2)
    picked_date = c_date.date_input("Date", value=default_dt.date())
    picked_time = c_time.time_input("Time", value=default_dt.time())

    manual_trigger = pd.Timestamp.combine(
        picked_date, picked_time
    ).tz_localize(config.DEFAULT_TIMEZONE)

    notes_value = st.text_input("notes (optional)", value="")

    suggested_session_id = Path(log_file).stem
    custom_session_id = st.text_input(
        "session_id (default = filename without .json)",
        value=suggested_session_id,
    )

    entry: dict[str, Any] = {
        "session_id": custom_session_id.strip() or suggested_session_id,
        "log_file": log_file,
        "manual_peakzone_entry_time": manual_trigger.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if notes_value.strip():
        entry["notes"] = notes_value.strip()

    st.divider()
    st.markdown(
        "### Copy this entry into `data/metadata/sessions_metadata.json`"
    )
    st.code(json.dumps(entry, indent=2, ensure_ascii=False), language="json")

    st.markdown(
        "**Steps to publish:**\n\n"
        "1. Open `data/metadata/sessions_metadata.json` in your editor.\n"
        "2. Add this object to the JSON array `[...]` (don't forget the comma between entries).\n"
        "3. Commit and push:\n"
        "   ```bash\n"
        f"   git add data/metadata/sessions_metadata.json data/logs/{log_file}\n"
        f"   git commit -m \"data: add session {entry['session_id']}\"\n"
        "   git push\n"
        "   ```\n"
        "4. Streamlit Cloud redeploys automatically in 1–2 minutes."
    )


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


def _fmt_time(value: Any) -> str:
    """Format a Timestamp / datetime as ``HH:MM:SS`` (no date)."""
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
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

    overview, detail, all_sessions, add_session = st.tabs(
        [
            "Overview",
            "Session Detail",
            "All Sessions",
            "Add Session",
        ]
    )
    with overview:
        _overview_tab(filtered)
    with detail:
        _session_detail_tab(filtered, sidebar)
    with all_sessions:
        _all_sessions_tab(filtered)
    with add_session:
        _add_session_tab(metadata_df, sidebar)


if __name__ == "__main__":
    main()
