"""The request form: a new request, or the completion of a request returned
for information."""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

import streamlit as st

import state
from client import ApiError

KIND_LABEL = {
    "quote": "Quote",
    "bid_comparison": "Bid comparison",
    "award_decision": "Award decision",
    "single_source_justification": "Single-source justification",
    "capex_approval": "Approved CapEx request",
    "specification": "Specification",
}


def request_form(key: str, prefill: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Draw the form; return the payload when the person submits it."""
    me = state.persona()
    ref = state.reference(me.token)
    prefill = prefill or {}
    suppliers = {s["id"]: s for s in ref["suppliers"]}
    items = {i["item_code"]: i for i in ref["items"]}

    with st.form(key, border=True):
        first, second = st.columns(2)
        external_ref = first.text_input(
            "Reference",
            value=prefill.get("external_ref")
            or f"PR-{date.today().year}-{random.randint(1, 99999):05d}",
            disabled=bool(prefill),
            help="Format PR-YYYY-NNNNN. A reference is used once.",
        )
        departments = ref["departments"]
        department = second.selectbox(
            "Department",
            departments,
            index=departments.index(prefill.get("department", me.department))
            if prefill.get("department", me.department) in departments
            else 0,
        )
        description = st.text_input(
            "What do you need?",
            value=prefill.get("description", ""),
            placeholder="Deep groove ball bearings 6205-2RS for conveyor line 3",
        )
        first, second = st.columns(2)
        supplier_ids = list(suppliers)
        supplier = first.selectbox(
            "Supplier",
            supplier_ids,
            index=supplier_ids.index(prefill["supplier_id"])
            if prefill.get("supplier_id") in suppliers
            else 0,
            format_func=lambda s: f"{suppliers[s]['name']} ({s})",
        )
        categories = ref["categories"]
        category = second.selectbox(
            "Category",
            categories,
            index=categories.index(prefill["item_category"])
            if prefill.get("item_category") in categories
            else categories.index("spare_parts")
            if "spare_parts" in categories
            else 0,
            format_func=lambda c: c.replace("_", " ").capitalize(),
        )
        codes = ["", *items]

        def item_label(code: str) -> str:
            if not code:
                return "Not in the catalogue"
            item = items[code]
            return f"{code}: {item['description']} ({item['unit_price']:.2f} {item['currency']})"

        item_code = st.selectbox(
            "Catalogue item (optional)",
            codes,
            index=codes.index(prefill["item_code"]) if prefill.get("item_code") in codes else 0,
            format_func=item_label,
            help="With a catalogue item, the price is compared with the reference price.",
        )
        first, second, third = st.columns(3)
        quantity = first.number_input(
            "Quantity", min_value=0.001, value=float(prefill.get("quantity", 1)), step=1.0
        )
        unit_price = second.number_input(
            "Unit price",
            min_value=0.01,
            value=float(prefill.get("unit_price", 100.0)),
            step=10.0,
            format="%.2f",
        )
        currencies = ref["currencies"]
        currency = third.selectbox(
            "Currency",
            currencies,
            index=currencies.index(prefill.get("currency", "EUR")),
        )
        justification = st.text_area(
            "Why is it needed?",
            value=prefill.get("justification", ""),
            placeholder="Preventive maintenance of conveyor line 3, planned in November.",
        )
        first, second = st.columns(2)
        delivery = first.date_input(
            "Needed by",
            value=date.fromisoformat(prefill["delivery_date"])
            if prefill.get("delivery_date")
            else date.today() + timedelta(days=21),
        )
        is_capex = second.toggle(
            "Capital expenditure (machinery, equipment)", value=prefill.get("is_capex", False)
        )
        st.markdown("**Documents attached**")
        counts = {k: 0 for k in KIND_LABEL}
        for a in prefill.get("attachments", []):
            counts[a["kind"]] = counts.get(a["kind"], 0) + 1
        columns = st.columns(3)
        chosen: dict[str, int] = {}
        for index, (kind, label) in enumerate(KIND_LABEL.items()):
            chosen[kind] = columns[index % 3].number_input(
                label,
                min_value=0,
                max_value=5,
                value=counts.get(kind, 0),
                step=1,
                key=f"{key}-{kind}",
            )
        submitted = st.form_submit_button(
            "Send the completed request" if prefill else "Submit the request", type="primary"
        )
    if not submitted:
        return None
    attachments = [
        {"kind": kind, "file_name": f"{kind}-{n + 1}.pdf"}
        for kind, count in chosen.items()
        for n in range(int(count))
    ]
    return {
        "external_ref": external_ref.strip(),
        "department": department,
        "supplier_id": supplier,
        "item_category": category,
        "item_code": item_code or None,
        "description": description,
        "quantity": f"{quantity:g}",
        "unit_price": f"{unit_price:.2f}",
        "currency": currency,
        "justification": justification,
        "delivery_date": delivery.isoformat(),
        "is_capex": is_capex,
        "attachments": attachments,
    }


def render() -> None:
    st.title("New request")
    st.caption(
        "The request is checked as soon as you submit it: you see at once what is missing "
        "and who will review it. Documents are recorded by type in this demo, not uploaded."
    )
    payload = request_form("new-request")
    if payload is None:
        return
    try:
        created = state.call("POST", "/requests", json=payload, headers={"Channel": "form"})
    except ApiError as error:
        state.show_error(error)
        return
    st.toast(f"{created['external_ref']} submitted")
    state.open_request(created["id"])
