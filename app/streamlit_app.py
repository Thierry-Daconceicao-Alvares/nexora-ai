"""NEXORA AI interface (Streamlit). Run from the repository root:

    streamlit run app/streamlit_app.py

With NEXORA_API_URL set, it calls the API over HTTP; otherwise it runs the API
in the same process (demo mode)."""

from __future__ import annotations

import streamlit as st

import state
import ui
from views import activity, dashboard, import_csv, my_requests, new_request, queue, request

st.set_page_config(page_title="NEXORA AI", page_icon=":material/fact_check:", layout="wide")
ui.inject_css()

ROLE_LABEL = {
    "requester": "Requester",
    "reviewer": "Category buyer",
    "approver": "Head of Procurement",
    "admin": "Administrator",
}

with st.sidebar:
    st.markdown("### NEXORA AI")
    st.caption("Purchase request review for Nexora Industries, a fictional company.")
    people = state.all_personas()
    labels = {p.id: f"{p.name}, {ROLE_LABEL[p.role].lower()}" for p in people}
    st.selectbox(
        "Signed in as",
        options=list(labels),
        format_func=labels.get,
        key="persona_id",
        index=list(labels).index(st.session_state.get("persona_id", "u-karim")),
        help="Demo users. Each one has the permissions of its role, checked by the API.",
    )

me = state.persona()
pages = {
    "request": st.Page(
        request.render, title="Request", icon=":material/description:", url_path="request"
    ),
    "queue": st.Page(queue.render, title="My queue", icon=":material/inbox:", url_path="queue"),
    "all": st.Page(
        queue.render_all, title="All requests", icon=":material/list:", url_path="requests"
    ),
    "dashboard": st.Page(
        dashboard.render, title="Dashboard", icon=":material/monitoring:", url_path="dashboard"
    ),
    "mine": st.Page(
        my_requests.render, title="My requests", icon=":material/folder_open:", url_path="mine"
    ),
    "new": st.Page(
        new_request.render, title="New request", icon=":material/add_box:", url_path="new"
    ),
    "import": st.Page(
        import_csv.render, title="Import a file", icon=":material/upload_file:", url_path="import"
    ),
    "activity": st.Page(
        activity.render, title="Activity log", icon=":material/history:", url_path="activity"
    ),
}
state.PAGES.update(pages)

if me.role == "requester":
    visible = ["mine", "new", "import"]
elif me.role in ("reviewer", "approver"):
    visible = ["queue", "dashboard", "all"]
else:
    visible = ["dashboard", "all", "activity"]

navigation = st.navigation([pages[name] for name in [*visible, "request"]])

# A link from a notification (?request=<id>) opens that request.
linked = st.query_params.get("request")
if linked and navigation.url_path != "request":
    state.open_request(linked)

with st.sidebar:
    st.divider()
    mode = state.api().mode
    st.caption(
        "Connected to the NEXORA API."
        if mode == "http"
        else "Demo mode: the API runs inside this app, with demo requests dated 7 to 20 "
        "October 2026. Their AI analyses are recorded answers of a real model; a request "
        "you submit here is analysed by the scripted stand-in."
    )
    st.caption("Synthetic data only. Every figure comes from this environment.")

navigation.run()
