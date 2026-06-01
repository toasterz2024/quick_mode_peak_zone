"""Project configuration: tunable defaults and data source mode.

All timestamps are normalized to Asia/Seoul. Naive timestamps in JSON logs and
metadata CSV are assumed to already be in Asia/Seoul (see spec section 5.5).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_TIMEZONE = "Asia/Seoul"
LOG_TIMEZONE_IF_NAIVE = "Asia/Seoul"
METADATA_TIMEZONE_IF_NAIVE = "Asia/Seoul"
DISPLAY_TIMEZONE = "Asia/Seoul"

PEAK_PLATEAU_DROP_THRESHOLD_MM: float = 3.0
PEAK_END_BELOW_THRESHOLD_MINUTES: int = 5

MANUAL_TRIGGER_TOLERANCE_MINUTES: int = 2
HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS: int = 90

NEAR_MAX_TOLERANCE_MM: float = 5.0
HEIGHT_CHANGE_10MIN_THRESHOLD_MM: float = 1.0
MAX_5MIN_VS_PREV_30_DELTA_MM: float = 1.0
SLOPE_RATIO_THRESHOLD: float = 0.3

T100_DETECTION_WINDOW_MINUTES: int = 10

DATA_SOURCE_MODE: str = os.environ.get("DATA_SOURCE_MODE", "local")

LOCAL_LOGS_DIR: Path = PROJECT_ROOT / "data" / "logs"
LOCAL_METADATA_PATH: Path = PROJECT_ROOT / "data" / "metadata" / "sessions_metadata.json"
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"

GITHUB_RAW_BASE_URL: str = os.environ.get(
    "GITHUB_RAW_BASE_URL",
    "https://raw.githubusercontent.com/<owner>/<repo>/<branch>",
)
GITHUB_LOGS_PATH: str = "data/logs"
GITHUB_METADATA_PATH: str = "data/metadata/sessions_metadata.json"

POSSIBLE_HEIGHT_COLUMNS = (
    "height_mm",
    "height",
    "current_height",
    "sensor_height",
    "measured_height",
)

POSSIBLE_TIMESTAMP_COLUMNS = (
    "timestamp",
    "time",
    "created_at",
    "measured_at",
    "datetime",
)

POSSIBLE_TEMPERATURE_COLUMNS = (
    "temperature_c",
    "temperature",
    "temp_c",
    "temp",
)

POSSIBLE_STAGE_COLUMNS = (
    "stage",
    "step",
    "state",
    "phase",
)
