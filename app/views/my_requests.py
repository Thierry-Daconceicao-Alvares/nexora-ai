"""A requester's own requests and their status."""

from __future__ import annotations

import streamlit as st

import state
import ui
from client import ApiError


def render() -> None:
    me = state.persona()
    st.title("My requests")
    try:
        rows = state.call("GET", "/requests", params={"limit": 200})
    except ApiError as error:
        state.show_error(error)
        return
    waiting = [r for r in rows if r["status"] == "info_requested"]
    if waiting:
        st.warning(
            f"Procurement needs information on {len(waiting)} of your requests. "
            "Open them to complete them."
        )
    if not rows:
        st.info(f"{me.name.split()[0]}, you have no request yet. Create one from New request.")
        if st.button("Create a request", type="primary"):
            st.switch_page(state.PAGES["new"])
        return
    for r in rows:
        with st.container(border=True):
            left, right = st.columns([5, 2], vertical_alignment="center")
            left.markdown(
                f"**{r['external_ref']}**  {r['description']}<br>"
                f'<span class="nx-meta">{ui.money(r["amount"], r["currency"])}, submitted '
                f"{ui.when(r['created_at'])}</span>",
                unsafe_allow_html=True,
            )
            right.markdown(ui.status_chip(r["status"]), unsafe_allow_html=True)
            if right.button("Open", key=f"open-{r['id']}"):
                state.open_request(r["id"])
