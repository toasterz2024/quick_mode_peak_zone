"""Plotly chart builders for the Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go


_EVENT_COLORS = {
    "real_peak_time": "#d62728",
    "manual_peakzone_entry_time": "#1f77b4",
    "t100_time": "#9467bd",
    "peak_start_time": "#2ca02c",
    "peak_end_time": "#ff7f0e",
}


def plot_height_with_events(
    df: pd.DataFrame,
    session_metrics: dict[str, Any],
) -> go.Figure:
    """Height-vs-time line chart with vertical event markers and plateau shading."""
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title="No data")
        return fig

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["height_mm"],
            mode="lines",
            name="height_mm",
            line={"color": "#444"},
        )
    )

    if "temperature_c" in df.columns and df["temperature_c"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["temperature_c"],
                mode="lines",
                name="temperature_c",
                yaxis="y2",
                line={"color": "#aaa", "dash": "dot"},
            )
        )
        fig.update_layout(
            yaxis2={
                "title": "temperature_c",
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
            }
        )

    plateau_start = session_metrics.get("peak_start_time")
    plateau_end = session_metrics.get("peak_end_time")
    if plateau_start is not None and plateau_end is not None:
        fig.add_shape(
            type="rect",
            x0=plateau_start,
            x1=plateau_end,
            y0=0,
            y1=1,
            yref="paper",
            fillcolor="#2ca02c",
            opacity=0.08,
            layer="below",
            line_width=0,
        )
        fig.add_annotation(
            x=plateau_start,
            y=1.02,
            yref="paper",
            text="peak plateau",
            showarrow=False,
            xanchor="left",
            font={"size": 11, "color": "#2ca02c"},
        )

    for key, color in _EVENT_COLORS.items():
        value = session_metrics.get(key)
        if value is None or pd.isna(value):
            continue
        fig.add_shape(
            type="line",
            x0=value,
            x1=value,
            y0=0,
            y1=1,
            yref="paper",
            line={"color": color, "dash": "dash"},
        )
        fig.add_annotation(
            x=value,
            y=1.0,
            yref="paper",
            text=key,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font={"size": 10, "color": color},
        )

    fig.update_layout(
        xaxis_title="timestamp",
        yaxis_title="height_mm",
        legend={"orientation": "h"},
        margin={"t": 40, "b": 40, "l": 40, "r": 40},
    )
    return fig


def plot_peak_duration_by_session(results_df: pd.DataFrame) -> go.Figure:
    """Bar chart of ``peak_duration_minutes`` per session."""
    fig = go.Figure()
    if results_df.empty or "peak_duration_minutes" not in results_df.columns:
        fig.update_layout(title="No data")
        return fig
    fig.add_trace(
        go.Bar(
            x=results_df["session_id"],
            y=results_df["peak_duration_minutes"],
            marker_color="#2ca02c",
        )
    )
    fig.update_layout(
        xaxis_title="session_id",
        yaxis_title="peak_duration_minutes",
        margin={"t": 40, "b": 40, "l": 40, "r": 40},
    )
    return fig


def plot_manual_trigger_diff_by_session(results_df: pd.DataFrame) -> go.Figure:
    """Bar chart of ``manual_to_real_peak_diff_minutes`` per session."""
    fig = go.Figure()
    if results_df.empty or "manual_to_real_peak_diff_minutes" not in results_df.columns:
        fig.update_layout(title="No data")
        return fig

    colors = [
        "#1f77b4" if (v is not None and not pd.isna(v) and v >= 0) else "#d62728"
        for v in results_df["manual_to_real_peak_diff_minutes"]
    ]
    fig.add_trace(
        go.Bar(
            x=results_df["session_id"],
            y=results_df["manual_to_real_peak_diff_minutes"],
            marker_color=colors,
        )
    )
    fig.add_shape(
        type="line",
        x0=0,
        x1=1,
        y0=0,
        y1=0,
        xref="paper",
        line={"color": "#444", "dash": "dash"},
    )
    fig.update_layout(
        xaxis_title="session_id",
        yaxis_title="manual_to_real_peak_diff_minutes",
        margin={"t": 40, "b": 40, "l": 40, "r": 40},
    )
    return fig


def plot_validation_status(results_df: pd.DataFrame) -> go.Figure:
    """Bar chart of ``validation_status`` counts."""
    fig = go.Figure()
    if results_df.empty or "validation_status" not in results_df.columns:
        fig.update_layout(title="No data")
        return fig
    counts = results_df["validation_status"].fillna("unknown").value_counts()
    fig.add_trace(
        go.Bar(
            x=counts.index.astype(str),
            y=counts.values,
            marker_color="#1f77b4",
        )
    )
    fig.update_layout(
        xaxis_title="validation_status",
        yaxis_title="sessions",
        margin={"t": 40, "b": 40, "l": 40, "r": 40},
    )
    return fig
