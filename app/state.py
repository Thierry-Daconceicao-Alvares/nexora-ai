"""Session state shared by the views: the API client, the signed-in persona,
and the navigation between pages."""

from __future__ import annotations

from typing import Any

import streamlit as st

from client import Api, ApiError, Persona, personas

PAGES: dict[str, Any] = {}


@st.cache_resource(show_spinner="Starting NEXORA...")
def api() -> Api:
    return Api()


@st.cache_data(show_spinner=False)
def all_personas() -> list[Persona]:
    return personas()


def persona() -> Persona:
    people = {p.id: p for p in all_personas()}
    return people[st.session_state.get("persona_id", "u-karim")]


def call(method: str, path: str, **kwargs: Any) -> Any:
    return api().call(method, path, persona().token, **kwargs)


@st.cache_data(ttl=300, show_spinner=False)
def reference(token: str) -> dict[str, Any]:
    return api().get("/reference", token)


def open_request(request_id: str) -> None:
    st.session_state.open_request = request_id
    st.switch_page(PAGES["request"])


def show_error(error: ApiError) -> None:
    st.error(error.message)
    for item in error.errors:
        field = item.get("field") or "request"
        st.markdown(f"- **{field}**: {item.get('message')}")
