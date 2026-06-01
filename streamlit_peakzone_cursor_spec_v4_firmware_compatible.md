# Streamlit App Specification: Peak Zone Manual Trigger Validation Dashboard (v4, firmware-compatible)

## 0. Changelog v3 → v4

| # | Change | Reason |
|---|---|---|
| 1 | `peak_end_time` now defined as "after `real_peak_time`, height stays below `real_peak_height - 3 mm` for ≥ 5 consecutive minutes" | Removed ambiguity of "continuous" |
| 2 | `peak_plateau_drop_threshold` default: 2 mm → **3 mm** | Aligned with peak-end rule |
| 3 | Condition 1: explicit firmware-compatible note — current point **included** in 30-min max window | Matches `getMaxHeightLastNMin(30)` firmware behavior |
| 4 | Condition 2: **signed** change (`current - height_10min_ago`), not `abs()` | Matches firmware behavior; falling height passes |
| 5 | Condition 4: if `max_slope_last_60min <= 0` → condition **PASSES** (was: fails) | Matches firmware behavior |
| 6 | Condition 5: stored as `t100_reached: bool` instead of `time_since_t100 >= 0` | Cleaner semantics; diagnostics stored separately |
| 7 | `validation_status` is now an enum of 9 fixed values | Avoids ambiguity in implementation |
| 8 | All rolling windows are **time-based** (`rolling("10min", on="timestamp")`) | Handles non-uniform log intervals |
| 9 | `height_10min_ago` lookup uses nearest row within ±90 s | Handles missing/sparse points |
| 10 | All timestamps normalized to **Asia/Seoul**; naive timestamps assumed Asia/Seoul | Cross-timezone safety |
| 11 | Explicit `github_raw` / `local` data source modes | Clear persistent storage contract |
| 12 | `@st.cache_data` policy documented; cache is **not** history | Performance ≠ persistence |
| 13 | `tests/` directory and minimum test set defined | Allows regression checking |
| 14 | Multiple equal maxima: always **first** matching timestamp | Deterministic behavior |
| 15 | `peak_end_time` searched **only after** `real_peak_time` | Avoids false plateau before real peak |

---

## 1. Goal

Build a Streamlit application that validates manually recorded **Peak Zone / Layer 2 trigger time** using fermentation session logs.

**Important architecture rule:**

The app must **not** calculate its own Peak Zone entry time by searching for the first moment when Layer 2 conditions become true.

**Reason:**

Layer 2 conditions can become true too early in the raw logs. In the real system, Layer 2 is only meaningful after the system has already entered the correct monitoring context. Therefore this dashboard must only validate the manually recorded Layer 2 trigger time.

The app must answer these questions for every session:

1. When was the real peak according to logs?
2. How long did the peak / peak plateau last?
3. What time did the user manually record as Peak Zone entry / Layer 2 trigger?
4. At that manually recorded time, were all Layer 2 conditions actually satisfied (using **current firmware logic**)?
5. If not, which conditions failed?
6. How far was the manually recorded Peak Zone entry from the real peak?
7. How does this behave historically across many sessions?

---

## 2. What the App Must NOT Do

The app must **not** calculate:

```text
calculated_layer2_entry_time
first_layer2_true_time
valid_layer2_entry_time
```

Do not search through the whole log to find the first timestamp where all Layer 2 conditions are true.

This is intentionally excluded because it will produce false early detections.

The only Layer 2 time used by the app is:

```text
manual_peakzone_entry_time
```

This value is written manually in the metadata file.

The app should only check whether the Layer 2 conditions were true at this manually recorded time, using **firmware-compatible** Layer 2 logic.

---

## 3. Data Sources

The app uses two types of data:

1. JSON session logs
2. Manually edited metadata file

Both are stored in GitHub. **GitHub is the persistent history.** Streamlit cache is only a performance optimization, never a history store.

Recommended structure:

```text
peakzone-dashboard/
│
├── app.py
├── config.py
├── requirements.txt
├── README.md
│
├── data/
│   ├── logs/
│   │   ├── session_001.json
│   │   ├── session_002.json
│   │   └── ...
│   │
│   └── metadata/
│       └── sessions_metadata.csv
│
├── src/
│   ├── data_loader.py
│   ├── preprocessing.py
│   ├── peak_analysis.py
│   ├── layer2_validation.py
│   ├── metrics.py
│   └── plots.py
│
├── tests/
│   ├── test_peak_analysis.py
│   ├── test_layer2_validation.py
│   └── test_timezone_parsing.py
│
└── outputs/
    └── peakzone_validation_results.csv
```

### 3.1 Data source modes

```python
DATA_SOURCE_MODE = "github_raw"  # production
DATA_SOURCE_MODE = "local"       # development
```

| Mode | Behavior |
|---|---|
| `github_raw` | `data_loader` fetches logs and metadata from raw GitHub URLs using `requests` |
| `local` | `data_loader` reads files from local `data/` directory |

The mode is controlled by `config.py` and overridable from the Streamlit sidebar.

---

## 4. Metadata File

File:

```text
data/metadata/sessions_metadata.csv
```

Required columns:

```csv
session_id,log_file,device_id,start_time,manual_peakzone_entry_time,mode,notes
```

Optional columns:

```csv
real_peak_time_manual,peak_start_time_manual,peak_end_time_manual
```

Recommended full version:

```csv
session_id,log_file,device_id,start_time,manual_peakzone_entry_time,real_peak_time_manual,peak_start_time_manual,peak_end_time_manual,mode,notes
```

Example:

```csv
session_id,log_file,device_id,start_time,manual_peakzone_entry_time,real_peak_time_manual,peak_start_time_manual,peak_end_time_manual,mode,notes
S001,session_001.json,SourFriend-A494,2026-05-20 09:00:00,2026-05-20 16:42:00,,,,Quick,"Good session"
S002,session_002.json,SourFriend-A094,2026-05-21 09:15:00,2026-05-21 17:20:00,,,,Quick,"Height sensor noisy"
```

Meaning:

| Column | Meaning |
|---|---|
| `session_id` | Unique session ID |
| `log_file` | JSON log filename |
| `device_id` | Device name or ID |
| `start_time` | Session start timestamp |
| `manual_peakzone_entry_time` | Manually written time when Peak Zone / Layer 2 trigger happened |
| `real_peak_time_manual` | Optional manual real peak time. If missing, app calculates from max height |
| `peak_start_time_manual` | Optional manual peak plateau start |
| `peak_end_time_manual` | Optional manual peak plateau end |
| `mode` | Quick / Auto / Delayed / etc. |
| `notes` | Optional notes |

**Note on timezones:** the CSV does **not** contain a timezone column. All naive timestamps in metadata are assumed to be in `Asia/Seoul`. See section 5.5.

---

## 5. Expected JSON Log Format & Parsing

### 5.1 Normalized DataFrame

After loading, normalize each log into a pandas DataFrame with:

```text
timestamp           (timezone-aware, Asia/Seoul)
elapsed_minutes
height_mm
temperature_c       (optional)
stage               (optional)
session_id
```

Required columns: `timestamp`, `elapsed_minutes`, `height_mm`.

### 5.2 Flexible column names

Possible height column names:

```text
height
height_mm
current_height
sensor_height
measured_height
```

Possible timestamp column names:

```text
timestamp
time
created_at
measured_at
datetime
```

### 5.3 Parser requirements

1. Load JSON.
2. Extract time-series records (handle nested structures).
3. Convert timestamps to pandas datetime, **timezone-aware** (see 5.5).
4. Sort by timestamp.
5. Remove duplicate timestamps (keep first).
6. Remove invalid height rows if needed.
7. Calculate `elapsed_minutes` from first valid timestamp.
8. Normalize height column name to `height_mm`.

### 5.4 Non-uniform timestamps

The app must not assume regular intervals. All time-based operations use either:

```python
df.rolling("30min", on="timestamp")
```

or explicit boolean masking by timestamp range.

### 5.5 Timezone policy

```python
DEFAULT_TIMEZONE = "Asia/Seoul"
LOG_TIMEZONE_IF_NAIVE = "Asia/Seoul"
METADATA_TIMEZONE_IF_NAIVE = "Asia/Seoul"
DISPLAY_TIMEZONE = "Asia/Seoul"
```

Rules:

1. If a timestamp contains a timezone, preserve it and convert to `Asia/Seoul`.
2. If a timestamp is naive in a JSON log, treat it as `Asia/Seoul`.
3. If a timestamp is naive in metadata CSV, treat it as `Asia/Seoul`.
4. All internal comparisons use timezone-aware timestamps only.
5. Display all times in `Asia/Seoul`.

There is **no** per-row timezone column in the metadata. If different sessions are recorded in different timezones, normalize before committing to GitHub.

---

## 6. Real Peak Detection

### 6.1 Real peak height

```python
real_peak_height = df["height_mm"].max()
```

### 6.2 Real peak time

If `real_peak_time_manual` is present and non-empty in metadata, use it.

Otherwise:

```python
real_peak_time = first timestamp where height_mm == real_peak_height
```

When multiple timestamps share the same maximum, **always use the first**.

### 6.3 Manual trigger ↔ real peak difference

```python
manual_to_real_peak_diff_minutes = (
    manual_peakzone_entry_time - real_peak_time
).total_seconds() / 60
```

| Value | Meaning |
|---|---|
| Positive | Manual trigger happened **after** real peak (expected — firmware sees stable plateau) |
| Zero | Manual trigger matched real peak |
| Negative | Manual trigger happened **before** real peak (unexpected — likely a wrong manual time) |

---

## 7. Peak Duration / Plateau (analytics only)

> **Important:** peak plateau analysis is for dashboard analytics only. It does **not** participate in Layer 2 validation.

### 7.1 Defaults (configurable in sidebar)

```python
PEAK_PLATEAU_DROP_THRESHOLD_MM = 3.0
PEAK_END_BELOW_THRESHOLD_MINUTES = 5
```

### 7.2 Peak start

```python
peak_start_time = first timestamp where height_mm >= real_peak_height - PEAK_PLATEAU_DROP_THRESHOLD_MM
```

When multiple timestamps qualify, use the first.

### 7.3 Peak end

Searched **only after** `real_peak_time`.

```text
peak_end_time = first timestamp t* after real_peak_time such that
height_mm stays below (real_peak_height - PEAK_PLATEAU_DROP_THRESHOLD_MM)
for at least PEAK_END_BELOW_THRESHOLD_MINUTES consecutive minutes.

If no such period exists, peak_end_time = last timestamp in the log.
```

**Rationale:** a single noisy dip does not end the peak. The end is fixed only after a sustained drop.

### 7.4 Peak duration

```python
peak_duration_minutes = (peak_end_time - peak_start_time).total_seconds() / 60
```

---

## 8. Layer 2 Conditions to Validate at Manual Trigger Time

At the manually recorded `manual_peakzone_entry_time`, the app must check whether these 5 firmware-compatible conditions were true:

```text
1. current_height >= recent_max_30min_including_current - 5 mm
2. (current_height - height_10min_ago) <= 1 mm                 # signed
3. max_last_5min <= max_prev_30_ex_5min + 1 mm
4. slope_last_10min <= 0.3 × max_slope_last_60min              # passes if max_slope_last_60min <= 0
5. t100_reached == True
```

The app should calculate the required values around the manual trigger time and report True / False for each condition.

The app must calculate these conditions at the manual trigger time **only for validation**. It may calculate condition timelines for visualization, but it must not use the timeline to detect a new Peak Zone entry time.

---

## 9. Definitions of Layer 2 Conditions (firmware-compatible)

### 9.1 Condition 1 — near recent max

```text
current_height >= recent_max_30min_including_current - 5
```

Calculation:

```python
# Note: current point IS included in the window — matches firmware getMaxHeightLastNMin(30).
recent_max_30min = max(height_mm over previous 30 minutes including current point)
condition_1 = current_height >= recent_max_30min - 5
```

> Comment in code: `This intentionally matches current firmware behavior. Current point is included in recent max window.`

### 9.2 Condition 2 — flat growth (signed)

```text
condition_2 = (current_height - height_10min_ago) <= 1
```

Calculation:

```python
target_time = current_time - pd.Timedelta(minutes=10)
height_10min_ago = nearest row to target_time within ±HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS

height_change_last_10min = current_height - height_10min_ago   # SIGNED
condition_2 = height_change_last_10min <= 1
```

**This is a signed comparison, not absolute.** If the height is falling, the condition passes — this matches firmware behavior (growth has stopped).

If no row exists within tolerance:

```text
condition_2 = insufficient_data
```

### 9.3 Condition 3 — no new strong maximum

```text
max_last_5min <= max_prev_30_ex_5min + 1
```

Calculation:

```python
max_last_5min = max(height_mm in [current_time - 5min, current_time])
max_prev_30_ex_5min = max(height_mm in [current_time - 35min, current_time - 5min])

condition_3 = max_last_5min <= max_prev_30_ex_5min + 1
```

If not enough previous data:

```text
condition_3 = insufficient_data
```

### 9.4 Condition 4 — slowed slope

```text
slope_last_10min <= 0.3 × max_slope_last_60min
```

Calculation:

```python
slope_last_10min = (current_height - height_10min_ago) / 10        # mm/min, signed

max_slope_last_60min = max 10-minute slope observed during previous 60 minutes
```

Then:

```python
if max_slope_last_60min <= 0:
    condition_4 = True       # firmware-compatible: no meaningful growth reference → passes
else:
    condition_4 = slope_last_10min <= 0.3 * max_slope_last_60min
```

> Comment in code: `This intentionally matches current firmware behavior. When there is no positive growth reference, condition_4 passes.`

### 9.5 Condition 5 — t100 reached

```python
initial_height = minimum non-zero height during first 10 minutes
t100_height = initial_height * 2
t100_time = first timestamp where height_mm >= t100_height

condition_5_t100_reached = (t100_time is not None) and (current_time >= t100_time)
```

If t100 was never reached:

```python
condition_5_t100_reached = False
validation_status = "t100_not_reached"
```

Diagnostics also stored:

```text
initial_height
t100_height
t100_time
time_since_t100_min
```

---

## 10. Manual Trigger Validation

### 10.1 Find nearest log row

Default tolerance: `±2 minutes`.

```python
get_nearest_row(df, manual_peakzone_entry_time, tolerance_minutes=2)
```

If no row within tolerance:

```text
manual_trigger_validation_status = "no_log_row_within_tolerance"
```

### 10.2 Lookup tolerance for 10-min back values

```python
HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS = 90
```

If no nearby point exists, the affected condition is marked `insufficient_data`.

### 10.3 Validate

```python
manual_entry_layer2_valid = (
    condition_1
    and condition_2
    and condition_3
    and condition_4
    and condition_5_t100_reached
)
```

If invalid, list failed conditions:

```text
failed_conditions_at_manual_entry = condition_2, condition_4
```

Raw diagnostic values to surface:

```text
current_height
recent_max_30min
height_change_last_10min        (signed)
max_last_5min
max_prev_30_ex_5min
slope_last_10min                (signed, mm/min)
max_slope_last_60min            (mm/min)
t100_time
time_since_t100_min
```

---

## 11. `validation_status` Enum (fixed set)

```text
valid
invalid
missing_manual_trigger
no_log_row_within_tolerance
insufficient_data
missing_log_file
invalid_log_format
t100_not_reached
error
```

Assignment rules:

| Status | When |
|---|---|
| `valid` | manual trigger exists, nearest log row exists, all 5 conditions true |
| `invalid` | manual trigger exists, nearest log row exists, at least one condition false |
| `missing_manual_trigger` | metadata has no `manual_peakzone_entry_time` |
| `no_log_row_within_tolerance` | no log row within ±2 min of manual trigger |
| `insufficient_data` | required historical windows or 10-min lookup missing |
| `missing_log_file` | metadata references a log file that cannot be loaded |
| `invalid_log_format` | JSON cannot be normalized into required dataframe columns |
| `t100_not_reached` | t100 was never reached before/during manual trigger |
| `error` | unexpected exception; an `error_message` field is filled |

Priority (if multiple apply, pick the topmost):

```text
missing_log_file
invalid_log_format
missing_manual_trigger
no_log_row_within_tolerance
t100_not_reached
insufficient_data
invalid
valid
error  # only when an actual exception is caught
```

---

## 12. Required Metrics Per Session

```text
session_id
device_id
mode
real_peak_time
real_peak_height
peak_start_time
peak_end_time
peak_duration_minutes
manual_peakzone_entry_time
manual_to_real_peak_diff_minutes
manual_entry_layer2_valid
failed_conditions_at_manual_entry
validation_status
```

Diagnostic values:

```text
manual_trigger_current_height
manual_trigger_recent_max_30min
manual_trigger_height_change_last_10min        (signed)
manual_trigger_max_last_5min
manual_trigger_max_prev_30_ex_5min
manual_trigger_slope_last_10min                (signed)
manual_trigger_max_slope_last_60min
manual_trigger_t100_reached
manual_trigger_time_since_t100_min
```

---

## 13. Dashboard Sections

### 13.1 Sidebar filters & config

```text
data source mode (github_raw / local)
session selector
device selector
mode selector
date range
peak_plateau_drop_threshold_mm (default 3)
peak_end_below_threshold_minutes (default 5)
manual trigger tolerance minutes (default 2)
show only invalid manual triggers
show only sessions where manual trigger is after real peak
show only sessions where no log row exists near manual trigger
[ Clear cache ] button
```

### 13.2 Overview page

Summary cards:

```text
Total sessions
Sessions with manual Peak Zone entry
Average manual trigger difference from real peak
Median manual trigger difference from real peak
Average peak duration
Median peak duration
Percent of manual triggers valid by Layer 2 rules
Percent of manual triggers before real peak
Percent of manual triggers after real peak
Distribution of validation_status values
```

### 13.3 Session detail page

1. Height over time chart.
2. Temperature over time chart if available.
3. Vertical lines for:
   - t100 time
   - manual Peak Zone entry time
   - real peak time
   - peak plateau start
   - peak plateau end
4. Highlight peak plateau region.
5. Table with Layer 2 condition values at manual trigger time.
6. Table showing which Layer 2 conditions passed or failed.
7. Difference from manual trigger to real peak in minutes.
8. Peak duration in minutes.

### 13.4 Manual Trigger Validation page

```text
manual_peakzone_entry_time
nearest_log_timestamp
timestamp_difference_seconds
manual_entry_layer2_valid
validation_status
failed_conditions_at_manual_entry
```

Condition table:

| Condition | Formula | Value | Passed |
|---|---|---|---|
| condition_1 | current_height >= recent_max_30min − 5 | ... | True/False |
| condition_2 | (current − height_10min_ago) ≤ 1 (signed) | ... | True/False |
| condition_3 | max_last_5min ≤ max_prev_30_ex_5min + 1 | ... | True/False |
| condition_4 | slope_last_10min ≤ 0.3 × max_slope_last_60min (passes if max_slope ≤ 0) | ... | True/False |
| condition_5 | t100_reached | ... | True/False |

### 13.5 All Sessions page

Show table with the 13 metrics from section 12. Allow CSV download.

---

## 14. Required Charts

Use Plotly.

### 14.1 Height chart with events
- X: timestamp or elapsed_minutes
- Y: height_mm
- Vertical lines: real_peak_time, manual_peakzone_entry_time, t100_time
- Shaded region: peak plateau
- Hover: timestamp, height_mm, temperature_c if available

### 14.2 Peak duration chart
Bar chart: x = session_id, y = peak_duration_minutes.

### 14.3 Manual trigger difference chart
Bar chart: x = session_id, y = manual_to_real_peak_diff_minutes.

### 14.4 Validation status chart
Counts of each `validation_status` value.

---

## 15. Output File

```text
outputs/peakzone_validation_results.csv
```

Columns:

```text
session_id
device_id
mode
real_peak_time
real_peak_height
peak_start_time
peak_end_time
peak_duration_minutes
manual_peakzone_entry_time
nearest_log_timestamp_to_manual_trigger
manual_trigger_timestamp_diff_seconds
manual_to_real_peak_diff_minutes
manual_entry_layer2_valid
failed_conditions_at_manual_entry
validation_status
manual_trigger_current_height
manual_trigger_recent_max_30min
manual_trigger_height_change_last_10min
manual_trigger_max_last_5min
manual_trigger_max_prev_30_ex_5min
manual_trigger_slope_last_10min
manual_trigger_max_slope_last_60min
manual_trigger_t100_reached
manual_trigger_time_since_t100_min
```

---

## 16. Caching Policy

```python
@st.cache_data(show_spinner=False)
def cached_load_metadata(...): ...

@st.cache_data(show_spinner=False)
def cached_load_json_log(...): ...

@st.cache_data(show_spinner=False)
def cached_process_session(...): ...

@st.cache_data(show_spinner=False)
def cached_process_all_sessions(...): ...
```

Sidebar button:

```python
if st.button("Clear cache"):
    st.cache_data.clear()
```

> **GitHub = persistent history. Streamlit cache = temporary performance optimization.**

The cache MUST NOT be the source of truth for any session result.

---

## 17. Recommended Implementation Plan

### Step 1 — Project skeleton
```text
app.py
config.py
requirements.txt
src/data_loader.py
src/preprocessing.py
src/peak_analysis.py
src/layer2_validation.py
src/metrics.py
src/plots.py
tests/test_peak_analysis.py
tests/test_layer2_validation.py
tests/test_timezone_parsing.py
```

### Step 2 — `src/data_loader.py`
```python
load_metadata(metadata_path_or_url: str) -> pd.DataFrame
load_json_log(log_path_or_url: str) -> dict
normalize_log_to_dataframe(raw_json: dict, session_id: str) -> pd.DataFrame
load_all_sessions(source_mode: str, logs_location: str, metadata_location: str) -> dict
```

### Step 3 — `src/preprocessing.py`
```python
prepare_session_dataframe(df: pd.DataFrame) -> pd.DataFrame
calculate_initial_height(df: pd.DataFrame) -> float
calculate_t100_time(df: pd.DataFrame, initial_height: float) -> pd.Timestamp | None
```

### Step 4 — `src/peak_analysis.py`
```python
get_real_peak(df: pd.DataFrame, metadata_row: pd.Series) -> dict
calculate_peak_plateau(
    df: pd.DataFrame,
    real_peak_time: pd.Timestamp,
    real_peak_height: float,
    drop_threshold_mm: float = 3.0,
    end_below_threshold_minutes: int = 5,
) -> dict
```

### Step 5 — `src/layer2_validation.py`
```python
validate_manual_layer2_trigger(
    df: pd.DataFrame,
    manual_peakzone_entry_time: pd.Timestamp,
    tolerance_minutes: int = 2,
    height_10min_lookup_tolerance_seconds: int = 90,
) -> dict
```

This function must:
1. Find nearest log row within tolerance.
2. Calculate all Layer 2 required values at that timestamp (firmware-compatible).
3. Return condition pass/fail values.
4. Return failed condition list.
5. Return raw diagnostic values.
6. Return `validation_status` from the fixed enum.

**Must NOT** return any calculated Layer 2 entry time.

### Step 6 — `src/metrics.py`
```python
calculate_session_metrics(
    df: pd.DataFrame,
    metadata_row: pd.Series,
    peak_plateau_drop_threshold_mm: float = 3.0,
    peak_end_below_threshold_minutes: int = 5,
) -> dict
```

### Step 7 — `src/plots.py`
```python
plot_height_with_events(df: pd.DataFrame, session_metrics: dict)
plot_peak_duration_by_session(results_df: pd.DataFrame)
plot_manual_trigger_diff_by_session(results_df: pd.DataFrame)
plot_validation_status(results_df: pd.DataFrame)
```

### Step 8 — Streamlit UI in `app.py`
```python
st.sidebar
st.tabs([
    "Overview",
    "Session Detail",
    "Manual Trigger Validation",
    "All Sessions",
])

st.metric / st.dataframe / st.plotly_chart / st.download_button
```

---

## 18. Requirements

`requirements.txt`:

```text
streamlit
pandas
numpy
plotly
python-dateutil
requests
pytest
```

`requests` is required (for `github_raw` mode). `pytest` is used for unit tests.

---

## 19. Unit Tests

Minimum required tests in `tests/`:

```text
test_peak_analysis.py
    - peak_end_time with one noisy dip below threshold (must NOT end peak)
    - peak_end_time with sustained 5-min below-threshold period (must end peak)
    - peak_start_time with multiple equal maxima (must pick first)
    - peak_end search starts only after real_peak_time

test_layer2_validation.py
    - Condition 1 firmware-compatible: current point included
    - Condition 2 firmware-compatible: signed change (falling height → passes)
    - Condition 3: insufficient previous data
    - Condition 4: max_slope_last_60min <= 0 → condition passes
    - Condition 5: t100_reached True / False
    - validation_status: valid case
    - validation_status: invalid case
    - validation_status: no_log_row_within_tolerance
    - validation_status: t100_not_reached
    - validation_status: insufficient_data
    - height_10min_ago lookup within ±90 s

test_timezone_parsing.py
    - naive log timestamps assumed Asia/Seoul
    - naive metadata timestamps assumed Asia/Seoul
    - timezone-aware UTC timestamps converted to Asia/Seoul
    - non-uniform timestamps + time-based rolling window
```

---

## 20. Important Edge Cases

The app must handle:

1. Missing `manual_peakzone_entry_time`.
2. Missing or invalid JSON logs.
3. Missing real peak manual value.
4. Missing temperature data.
5. Missing stage data.
6. Sessions where t100 was never reached.
7. Sensor noise.
8. Temporary zero height values.
9. Non-uniform timestamp intervals.
10. Duplicate timestamps.
11. No log row within ±2 minutes of manual trigger.
12. Peak plateau not clearly detectable (no sustained drop → peak_end = last timestamp).
13. Multiple equal max-height timestamps (always first).
14. Naive timestamps without timezone (assume Asia/Seoul).
15. Single noisy dip below plateau threshold (does NOT end peak).

---

## 21. Success Criteria

The app is complete when:

1. User can add a JSON log to GitHub.
2. User can manually add `manual_peakzone_entry_time` to `sessions_metadata.csv`.
3. App loads all sessions in both `github_raw` and `local` modes.
4. App detects real peak from logs.
5. App estimates peak duration using sustained-drop rule.
6. App checks whether **firmware-compatible** Layer 2 conditions were true at the manually recorded trigger time.
7. App reports failed Layer 2 conditions if trigger was invalid.
8. App shows how far manual trigger was from real peak.
9. App shows charts for each session.
10. App preserves historical comparison across sessions (history = GitHub, not cache).
11. App allows downloading validation results as CSV.
12. Unit tests in `tests/` pass.

---

## 22. Notes for Cursor Agent

Main principle:

```text
This app validates manually recorded Layer 2 trigger time using current firmware logic.
It does not detect Peak Zone entry automatically.
```

Do not implement logic that searches for the first timestamp where all Layer 2 conditions are true.

Layer 2 condition timeline may be calculated for visualization only, but the result must not be called calculated Peak Zone entry.

The product question is:

```text
When we manually recorded that Layer 2 triggered, were the Layer 2 conditions truly satisfied
according to current firmware logic?
```

Secondary analysis questions:

```text
How far was this trigger from the real peak?
How long did the peak plateau last?
How often are manual triggers valid?
Which Layer 2 conditions fail most often?
```

Firmware-compatibility reminders for the agent:

```text
- Condition 1: current point IS included in the 30-min max window.
- Condition 2: signed change, NOT absolute. Falling height passes.
- Condition 4: if max_slope_last_60min <= 0, the condition PASSES.
- Condition 5: stored as boolean t100_reached.
- Peak plateau is analytics-only and never affects Layer 2 validation.
```
