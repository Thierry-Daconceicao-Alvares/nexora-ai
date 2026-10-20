"""The audit trail, as an auditor reads it."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state
import ui
from client import ApiError


def render() -> None:
    st.title("Activity log")
    st.caption("Every step of every request, in order. Nothing in it can be edited.")
    try:
        events = state.call("GET", "/events", params={"limit": 500})
    except ApiError as error:
        state.show_error(error)
        return
    users = state.reference(state.persona().token)["users"]
    frame = pd.DataFrame(
        [
            {
                "#": e["id"],
                "Time": ui.when(e["created_at"]),
                "Event": e["type"],
                "By": users.get(e["actor_id"], {}).get("name", "system")
                if e["actor_id"]
                else "system",
                "Details": ", ".join(
                    f"{k}={v}" for k, v in e["payload"].items() if k not in {"evidence"}
                ),
            }
            for e in reversed(events)
        ]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
