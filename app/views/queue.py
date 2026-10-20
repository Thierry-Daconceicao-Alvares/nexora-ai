"""The reviewer's and the approver's queue, and the list of all requests."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state
import ui
from client import ApiError

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _table(rows: list[dict], key: str, waiting_column: bool) -> None:
    frame = pd.DataFrame(
        [
            {
                "Reference": r["external_ref"],
                "Description": r["description"],
                "Department": r["department"],
                "Amount (EUR)": r["amount_eur"],
                "Highest finding": ui.SEVERITY[r["highest_severity"]][1],
                "Status": ui.STATUS.get(r["status"], ("", r["status"]))[1],
                "Waiting for": ui.waiting(r["updated_at"]) if waiting_column else None,
                "Submitted": ui.when(r["created_at"]),
            }
            for r in rows
        ]
    )
    if not waiting_column:
        frame = frame.drop(columns=["Waiting for"])
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        height=min(36 * (len(rows) + 1) + 4, 720),
        column_config={
            "Amount (EUR)": st.column_config.NumberColumn(format="%.2f"),
            "Description": st.column_config.TextColumn(width="large"),
        },
    )
    if event.selection.rows:
        state.open_request(rows[event.selection.rows[0]]["id"])


def render() -> None:
    me = state.persona()
    who = "category buyer" if me.role == "reviewer" else "Head of Procurement"
    st.title("My queue")
    try:
        rows = state.call("GET", "/requests", params={"actionable": "true", "limit": 200})
    except ApiError as error:
        state.show_error(error)
        return
    rows.sort(key=lambda r: (SEVERITY_ORDER[r["highest_severity"]], r["updated_at"]))
    if not rows:
        st.info(
            f"Nothing waits for the {who}. New requests appear here as soon as they are checked."
        )
        return
    st.markdown(
        f'<p class="nx-meta"><b>{len(rows)}</b> '
        + ("request waits" if len(rows) == 1 else "requests wait")
        + " for your decision, the most serious findings first. Select a row to open it.</p>",
        unsafe_allow_html=True,
    )
    _table(rows, "queue", waiting_column=True)


def render_all() -> None:
    st.title("All requests")
    reference = state.reference(state.persona().token)
    left, middle, _ = st.columns([2, 2, 3])
    status = left.selectbox(
        "Status",
        ["All", *ui.STATUS],
        format_func=lambda s: "All" if s == "All" else ui.STATUS[s][1],
    )
    department = middle.selectbox("Department", ["All", *reference["departments"]])
    params: dict = {"limit": 200}
    if status != "All":
        params["status"] = status
    if department != "All":
        params["department"] = department
    try:
        rows = state.call("GET", "/requests", params=params)
    except ApiError as error:
        state.show_error(error)
        return
    if not rows:
        st.info("No request matches these filters.")
        return
    _table(rows, "all", waiting_column=False)
