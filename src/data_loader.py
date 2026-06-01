"""Data loading for metadata JSON and JSON session logs.

Supports two modes:
- ``local``: reads from the local ``data/`` directory.
- ``github_raw``: fetches files directly from raw GitHub URLs.

The normalized DataFrame always contains at least these columns:
``timestamp`` (timezone-aware, Asia/Seoul), ``elapsed_minutes``, ``height_mm``,
``session_id``. Optional columns: ``temperature_c``, ``stage``.

Metadata is now stored as a JSON array (``sessions_metadata.json``). The user
manually writes only ``manual_peakzone_entry_time`` (and optionally ``notes``);
``session_id``, ``device_id``, ``start_time`` and ``mode`` are auto-extracted
from the log file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from config import (
    DEFAULT_TIMEZONE,
    GITHUB_LOGS_PATH,
    GITHUB_METADATA_PATH,
    GITHUB_RAW_BASE_URL,
    LOCAL_LOGS_DIR,
    LOCAL_METADATA_PATH,
    LOG_TIMEZONE_IF_NAIVE,
    METADATA_TIMEZONE_IF_NAIVE,
    POSSIBLE_HEIGHT_COLUMNS,
    POSSIBLE_STAGE_COLUMNS,
    POSSIBLE_TEMPERATURE_COLUMNS,
    POSSIBLE_TIMESTAMP_COLUMNS,
)

logger = logging.getLogger(__name__)

METADATA_TIMESTAMP_FIELDS = (
    "manual_peakzone_entry_time",
    "real_peak_time_manual",
    "peak_start_time_manual",
    "peak_end_time_manual",
    "start_time",
)

DEVICE_ID_KEYS = ("device_id", "device", "device_name", "deviceId", "serial", "serial_number")
MODE_KEYS = ("mode", "program", "recipe", "cycle", "fermentation_mode")
NESTED_METADATA_KEYS = ("metadata", "meta", "info", "session", "device")


class DataLoadError(Exception):
    """Raised when a data source cannot be located or parsed."""


def _fetch_text(location: str | Path, *, source_mode: str) -> str:
    """Return the textual contents of a file from local disk or GitHub raw."""
    if source_mode == "github_raw":
        url = str(location)
        if not url.startswith(("http://", "https://")):
            url = f"{GITHUB_RAW_BASE_URL.rstrip('/')}/{url.lstrip('/')}"
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            raise DataLoadError(f"GitHub fetch failed ({response.status_code}): {url}")
        return response.text

    path = Path(location)
    if not path.exists():
        raise DataLoadError(f"Local file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_metadata(
    metadata_location: str | Path | None = None,
    *,
    source_mode: str = "local",
) -> pd.DataFrame:
    """Load the sessions metadata JSON and normalize timestamps to Asia/Seoul.

    The expected format is a JSON array of objects. Required keys per object:
    ``session_id``, ``log_file``, ``manual_peakzone_entry_time``. Optional keys:
    ``notes`` (or any of the historical fields like ``real_peak_time_manual``
    if the user wants to override auto-extracted values).
    """
    if metadata_location is None:
        metadata_location = (
            GITHUB_METADATA_PATH if source_mode == "github_raw" else LOCAL_METADATA_PATH
        )

    text = _fetch_text(metadata_location, source_mode=source_mode)
    try:
        payload = json.loads(text) if text.strip() else []
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"Invalid metadata JSON: {exc}") from exc

    if isinstance(payload, dict) and "sessions" in payload:
        payload = payload["sessions"]
    if not isinstance(payload, list):
        raise DataLoadError(
            "Metadata JSON must be an array of session objects "
            "(or {\"sessions\": [...]})."
        )

    if not payload:
        return pd.DataFrame(
            columns=[
                "session_id",
                "log_file",
                "manual_peakzone_entry_time",
                "notes",
            ]
        )

    df = pd.DataFrame(payload)

    for col in METADATA_TIMESTAMP_FIELDS:
        if col in df.columns:
            df[col] = _normalize_timestamp_series(
                df[col], assume_tz=METADATA_TIMEZONE_IF_NAIVE
            )

    for col in ("session_id", "log_file", "device_id", "mode", "notes"):
        if col in df.columns:
            df[col] = df[col].astype("string")

    return df


def extract_log_metadata(
    raw_json: Any,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Pull device_id, mode, start_time and end_time directly from a log.

    The function looks at the JSON root and any nested metadata-like dict
    (``metadata``, ``meta``, ``info``, ``session``, ``device``). Missing
    fields are returned as ``None``. ``start_time`` and ``end_time`` are
    taken from the parsed DataFrame when available.
    """
    info: dict[str, Any] = {
        "device_id": None,
        "mode": None,
        "start_time": None,
        "end_time": None,
    }

    candidates: list[dict[str, Any]] = []
    if isinstance(raw_json, dict):
        candidates.append(raw_json)
        for key in NESTED_METADATA_KEYS:
            value = raw_json.get(key)
            if isinstance(value, dict):
                candidates.append(value)

    for src in candidates:
        if info["device_id"] is None:
            for key in DEVICE_ID_KEYS:
                if key in src and src[key]:
                    info["device_id"] = str(src[key])
                    break
        if info["mode"] is None:
            for key in MODE_KEYS:
                if key in src and src[key]:
                    info["mode"] = str(src[key])
                    break

    if df is not None and not df.empty and "timestamp" in df.columns:
        info["start_time"] = df["timestamp"].iloc[0]
        info["end_time"] = df["timestamp"].iloc[-1]

    return info


def load_json_log(
    log_location: str | Path,
    *,
    source_mode: str = "local",
) -> dict[str, Any]:
    """Load a JSON log either from disk or from a raw GitHub URL."""
    if source_mode == "github_raw":
        location_str = str(log_location)
        if not location_str.startswith(("http://", "https://")):
            location_str = (
                f"{GITHUB_RAW_BASE_URL.rstrip('/')}/"
                f"{GITHUB_LOGS_PATH.strip('/')}/{location_str.lstrip('/')}"
            )
        text = _fetch_text(location_str, source_mode="github_raw")
    else:
        path = Path(log_location)
        if not path.is_absolute():
            path = LOCAL_LOGS_DIR / path
        text = _fetch_text(path, source_mode="local")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"Invalid JSON in log {log_location}: {exc}") from exc


def normalize_log_to_dataframe(
    raw_json: dict[str, Any] | list[Any],
    session_id: str,
) -> pd.DataFrame:
    """Convert an arbitrary JSON log structure into the standard DataFrame schema.

    The parser scans the JSON for the most plausible list of time-series records
    and renames columns to the canonical names. It is intentionally permissive.
    """
    records = _extract_records(raw_json)
    if not records:
        raise DataLoadError("No time-series records found in JSON log")

    df = pd.DataFrame(records)

    height_col = _find_column(df, POSSIBLE_HEIGHT_COLUMNS)
    timestamp_col = _find_column(df, POSSIBLE_TIMESTAMP_COLUMNS)
    if height_col is None or timestamp_col is None:
        raise DataLoadError(
            f"Log missing required columns. height_col={height_col!r}, "
            f"timestamp_col={timestamp_col!r}, available={list(df.columns)}"
        )

    out = pd.DataFrame()
    out["timestamp"] = _normalize_timestamp_series(
        df[timestamp_col], assume_tz=LOG_TIMEZONE_IF_NAIVE
    )
    out["height_mm"] = pd.to_numeric(df[height_col], errors="coerce")

    temp_col = _find_column(df, POSSIBLE_TEMPERATURE_COLUMNS)
    if temp_col is not None:
        out["temperature_c"] = pd.to_numeric(df[temp_col], errors="coerce")

    stage_col = _find_column(df, POSSIBLE_STAGE_COLUMNS)
    if stage_col is not None:
        out["stage"] = df[stage_col].astype("string")

    out["session_id"] = session_id
    return out


def load_all_sessions(
    metadata_location: str | Path | None = None,
    *,
    source_mode: str = "local",
) -> dict[str, dict[str, Any]]:
    """Load metadata and every referenced log into one structure.

    Returns ``{session_id: {"metadata_row": Series, "log_df": DataFrame | None,
    "load_error": str | None}}``. ``metadata_row`` already has
    ``device_id`` / ``mode`` / ``start_time`` merged from the log when not
    provided manually.
    """
    metadata_df = load_metadata(metadata_location, source_mode=source_mode)
    sessions: dict[str, dict[str, Any]] = {}

    for _, row in metadata_df.iterrows():
        session_id = str(row.get("session_id", "")).strip()
        if not session_id:
            continue

        log_file = row.get("log_file")
        entry: dict[str, Any] = {
            "metadata_row": row,
            "log_df": None,
            "load_error": None,
        }
        if not isinstance(log_file, str) or not log_file:
            entry["load_error"] = "missing_log_file"
            sessions[session_id] = entry
            continue

        try:
            raw = load_json_log(log_file, source_mode=source_mode)
            log_df = normalize_log_to_dataframe(raw, session_id=session_id)
            entry["log_df"] = log_df
            entry["metadata_row"] = _merge_with_log_metadata(row, raw, log_df)
        except DataLoadError as exc:
            logger.warning("Failed to load log for %s: %s", session_id, exc)
            entry["load_error"] = (
                "missing_log_file" if "not found" in str(exc).lower() else "invalid_log_format"
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected log-loading error for %s", session_id)
            entry["load_error"] = f"error: {exc}"

        sessions[session_id] = entry

    return sessions


def _merge_with_log_metadata(
    row: pd.Series,
    raw_json: Any,
    df: pd.DataFrame,
) -> pd.Series:
    """Fill ``device_id`` / ``mode`` / ``start_time`` from the log when absent."""
    auto = extract_log_metadata(raw_json, df)
    merged = row.copy()
    for key, value in auto.items():
        if value is None:
            continue
        existing = merged.get(key) if key in merged.index else None
        if existing is None or pd.isna(existing) or existing == "":
            merged[key] = value
    return merged


def _extract_records(raw: Any) -> list[dict[str, Any]]:
    """Find the deepest list of dicts that looks like time-series records."""
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw

    if isinstance(raw, dict):
        for key in ("records", "data", "log", "logs", "measurements", "history", "points"):
            value = raw.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
        for value in raw.values():
            extracted = _extract_records(value)
            if extracted:
                return extracted

    return []


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lower_cols = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate in lower_cols:
            return lower_cols[candidate]
    return None


def _normalize_timestamp_series(series: pd.Series, *, assume_tz: str) -> pd.Series:
    """Parse a timestamp series and convert it to ``DEFAULT_TIMEZONE``."""
    parsed = pd.to_datetime(series, errors="coerce", utc=False)
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(assume_tz, ambiguous="NaT", nonexistent="NaT")
    return parsed.dt.tz_convert(DEFAULT_TIMEZONE)
