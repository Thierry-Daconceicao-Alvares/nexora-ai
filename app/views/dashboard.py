"""The dashboard: the queue, the findings, the decisions and the cost of the AI,
all computed by the API from the requests stored in this environment."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import state
from client import ApiError

ALL_TIME = 3650
SERIES = "#3987e5"  # validated on the dark surface (dataviz validator, single slot)
SURFACE = "#1c2b36"
TEXT, MUTED, GRID = "#e7eef3", "#9aacba", "#2a3b48"


def _axis_config(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeWidth=0)
        .configure(background="transparent")
        .configure_axis(
            labelColor=MUTED,
            titleColor=MUTED,
            gridColor=GRID,
            domainColor=GRID,
            tickColor=GRID,
            labelFont="NexoraText",
            titleFont="NexoraText",
            labelFontSize=12,
            titleFontSize=12,
            titleFontWeight="normal",
        )
    )


def _daily(figures: dict) -> alt.Chart:
    frame = pd.DataFrame(figures["requests"]["daily"])
    frame = frame[frame["requests"].cumsum() > 0]  # start at the first request
    frame["date"] = pd.to_datetime(frame["date"])
    bars = (
        alt.Chart(frame)
        .mark_bar(color=SERIES, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.7})
        .encode(
            x=alt.X(
                "yearmonthdate(date):T",
                title=None,
                axis=alt.Axis(format="%d %b", grid=False, labelAngle=0, tickCount=6),
            ),
            y=alt.Y("requests:Q", title="Requests", axis=alt.Axis(tickMinStep=1)),
            tooltip=[
                alt.Tooltip("yearmonthdate(date):T", title="Day", format="%d %b %Y"),
                alt.Tooltip("requests:Q", title="Requests"),
            ],
        )
    )
    return _axis_config(bars.properties(height=220))


def _findings(figures: dict) -> alt.Chart | None:
    by_rule = figures["exceptions"]["by_rule"]
    if not by_rule:
        return None
    frame = pd.DataFrame(
        {
            "rule": [r.replace("_", " ").capitalize() for r in by_rule],
            "requests": list(by_rule.values()),
        }
    )
    base = alt.Chart(frame).encode(
        y=alt.Y("rule:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
        x=alt.X("requests:Q", title="Requests with this finding", axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip("rule:N", title="Rule"), alt.Tooltip("requests:Q", title="Requests")],
    )
    bars = base.mark_bar(
        color=SERIES, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, height={"band": 0.6}
    )
    labels = base.mark_text(align="left", dx=6, color=TEXT, fontSize=12).encode(text="requests:Q")
    return _axis_config((bars + labels).properties(height=max(120, 40 * len(frame))))


def render() -> None:
    st.title("Dashboard")
    days = (
        st.segmented_control(
            "Period",
            [7, 30, 90, ALL_TIME],
            # The demo data is dated October 2026: show all of it by default.
            default=ALL_TIME if state.api().mode == "embedded" else 30,
            format_func=lambda d: "All" if d == ALL_TIME else f"Last {d} days",
            label_visibility="collapsed",
        )
        or 30
    )
    try:
        figures = state.call("GET", "/metrics", params={"days": days})
    except ApiError as error:
        state.show_error(error)
        return
    queue, decisions, ai, req = (
        figures["queue"],
        figures["decisions"],
        figures["ai"],
        figures["requests"],
    )

    cols = st.columns(4)
    cols[0].metric("Waiting for review", queue["awaiting_review"], border=True)
    cols[1].metric("Waiting for approval", queue["awaiting_approver"], border=True)
    cols[2].metric("Waiting for the requester", queue["info_requested"], border=True)
    oldest = queue["oldest_waiting_hours"]
    if oldest is None:
        oldest_text = "none"
    elif oldest < 48:
        oldest_text = f"{oldest:.0f} h"
    else:
        oldest_text = f"{oldest / 24:.0f} days"
    cols[3].metric("Oldest wait", oldest_text, border=True)
    cols = st.columns(4)
    cols[0].metric(
        "Requests" if days == ALL_TIME else f"Requests, last {days} days",
        req["total"],
        border=True,
    )
    median = decisions["cycle_time_hours_median"]
    cols[1].metric(
        "Median time to a decision",
        "no decision yet" if median is None else f"{median:.1f} h",
        border=True,
    )
    cols[2].metric(
        "Serious findings approved",
        decisions["approved_despite_high_findings"],
        border=True,
    )
    cols[3].metric(
        "AI cost (estimated)",
        f"${ai['estimated_cost_usd']:.4f}",
        help=f"{ai['analyses']} analyses, {ai['tokens']:,} tokens, at list prices. "
        "The scripted stand-in costs nothing.",
        border=True,
    )

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Requests received")
        st.altair_chart(_daily(figures), width="stretch")
    with right:
        st.subheader("Findings by rule")
        chart = _findings(figures)
        if chart is None:
            st.info("No finding in this period.")
        else:
            st.altair_chart(chart, width="stretch")

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Decisions")
        by_action = decisions["by_action"]
        if by_action:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Decision": [a.replace("_", " ").capitalize() for a in by_action],
                        "Count": list(by_action.values()),
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No decision in this period.")
    with right:
        st.subheader("AI analyses")
        rows = [
            {"Verification": k.capitalize(), "Analyses": v}
            for k, v in ai["by_verification"].items()
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            latency = ai["latency_ms_median"]
            st.caption(
                "Provider: "
                + ", ".join(f"{k} ({v})" for k, v in ai["by_provider"].items())
                + (f". Median model latency {latency / 1000:.1f} s." if latency else ".")
            )
        else:
            st.info("No analysis in this period.")

    with st.expander("All figures as data"):
        st.json(figures, expanded=False)
    st.caption("Computed by the API from the requests stored in this environment (synthetic data).")
