"""One request: what was asked, what the checks found, what the AI says and
on which passages, the decision panel, and the history."""

from __future__ import annotations

import html

import streamlit as st

import state
import ui
from client import ApiError
from views.new_request import request_form

PROVIDER_NOTE = {
    "recorded": "Recorded answer: this demo request was analysed once by the model named "
    "here; the public demo replays that answer and makes no model call. It went through "
    "the same checks in code as a live answer.",
    "scripted": "Scripted stand-in: no language model is configured, the text is assembled "
    "from the rule results.",
}


def _header(detail: dict, users: dict) -> None:
    left, right = st.columns([5, 2], vertical_alignment="top")
    left.title(detail["external_ref"])
    left.markdown(f"#### {html.escape(detail['description'])}")
    requester = users.get(detail["requester_id"], {}).get("name", detail["requester_id"])
    left.markdown(
        f'<p class="nx-meta"><b>{ui.money(detail["amount"], detail["currency"])}</b>'
        + (f" (EUR {detail['amount_eur']:,.2f})" if detail["currency"] != "EUR" else "")
        + f", requested by <b>{html.escape(requester)}</b> ({html.escape(detail['department'])})"
        f", supplier <b>{html.escape(detail['supplier_id'])}</b>, needed by "
        f"{detail['delivery_date']}. Version {detail['version']}, received by "
        f"{detail['channel']}.</p>",
        unsafe_allow_html=True,
    )
    left.markdown(
        ui.status_chip(detail["status"])
        + " "
        + ui.chip(
            "#8b98a5",
            "Head of Procurement" if detail["route"] == "approver" else "Category buyer",
        ),
        unsafe_allow_html=True,
    )
    closing = next(
        (d for d in reversed(detail["decisions"]) if d["to_status"] in ("approved", "rejected")),
        None,
    )
    if closing:
        name = users.get(closing["actor_id"], {}).get("name", closing["actor_id"])
        right.markdown(
            ui.stamp(closing["to_status"], name, closing["created_at"]), unsafe_allow_html=True
        )


def _details(detail: dict) -> None:
    """What the requester wrote, shown as text: the justification is where an
    instruction aimed at the AI would be, and the reviewer has to read it."""
    st.subheader("The request")
    category = detail["item_category"].replace("_", " ")
    item = f", item {html.escape(detail['item_code'])}" if detail.get("item_code") else ""
    attachments = ", ".join(
        f"{a['kind'].replace('_', ' ')} ({html.escape(a['file_name'])})"
        for a in detail["attachments"]
    )
    st.markdown(
        f'<p class="nx-meta">{float(detail["quantity"]):g} \u00d7 '
        f"{ui.money(detail['unit_price'], detail['currency'])}, {html.escape(category)}{item}"
        f"{', CapEx' if detail['is_capex'] else ''}. "
        f"Attachments: {attachments or 'none'}.</p>"
        f'<div class="nx-quote" style="margin-bottom:1.2rem">'
        f"{html.escape(detail['justification'])}</div>",
        unsafe_allow_html=True,
    )


def _checks(detail: dict) -> None:
    st.subheader("What the checks found")
    rules = [c for c in detail["checks"] if c["stage"] != "validation"]
    flagged = [c for c in rules if c["outcome"] != "pass"]
    flagged.sort(key=lambda c: -list(ui.SEVERITY).index(c["severity"]))
    if flagged:
        st.markdown("".join(ui.finding(c) for c in flagged), unsafe_allow_html=True)
    else:
        st.success("Every rule passed: no finding on this request.")
    passed = [c for c in rules if c["outcome"] == "pass"]
    with st.expander(ui.plural(len(passed), "check") + " passed"):
        for c in passed:
            st.markdown(f"- **{c['rule_id'].replace('_', ' ').capitalize()}**: {c['message']}")


def _analysis(detail: dict) -> None:
    analysis = detail.get("analysis")
    st.subheader("AI analysis")
    if not analysis:
        st.info("No analysis for this version.")
        return
    if analysis["status"] != "completed":
        st.warning(
            "The AI analysis is unavailable for this request "
            f"({analysis.get('error') or 'no answer'}). The checks above are complete; "
            "decide on them."
        )
        return
    output = analysis["output"]
    verification = ui.VERIFICATION.get(analysis["verification"])
    st.markdown(
        ui.verification_chip(analysis["verification"])
        + f' <span class="nx-meta">{html.escape(verification[2] if verification else "")}'
        f" Model: {html.escape(analysis['model'])}.</span>",
        unsafe_allow_html=True,
    )
    if analysis["provider"] in PROVIDER_NOTE:
        st.caption(PROVIDER_NOTE[analysis["provider"]])
    st.markdown(output["summary"])
    recommendation = output["recommendation"]
    st.markdown(
        f"**Suggested decision: {ui.ACTIONS[recommendation['action']]}.** "
        f"{recommendation['rationale']}"
    )
    st.caption("A suggestion for the reviewer. Only a person decides.")
    for finding in output["findings"]:
        refs = ", ".join(finding["citations"]) or "no policy passage"
        st.markdown(
            f"- **{finding['rule_id'].replace('_', ' ').capitalize()}**: "
            f"{finding['explanation']} _({refs})_"
        )
    if output["missing_information"]:
        st.markdown("**Missing information**")
        for item in output["missing_information"]:
            st.markdown(f"- {item}")
    if analysis["issues"]:
        with st.expander(
            ui.plural(len(analysis["issues"]), "issue") + " found when checking the analysis"
        ):
            for issue in analysis["issues"]:
                st.markdown(f"- `{issue['code']}`: {issue['detail']}")
    if analysis["citations"]:
        st.markdown("**Policy passages cited**")
        for citation in analysis["citations"]:
            document = citation["document"].split(" ", 1)[0]
            with st.expander(f"{document} {citation['section']}"):
                st.caption(citation["document"])
                st.markdown(
                    f'<div class="nx-quote">{html.escape(citation["text"] or "")}</div>',
                    unsafe_allow_html=True,
                )


def _decision_panel(detail: dict) -> None:
    actions = detail["allowed_actions"]
    if not actions:
        return
    with st.container(border=True):
        st.subheader("Your decision")
        action = st.radio(
            "Decision",
            actions,
            format_func=ui.ACTIONS.get,
            label_visibility="collapsed",
            key=f"action-{detail['id']}",
        )
        serious = [
            c
            for c in detail["checks"]
            if c["outcome"] != "pass" and c["severity"] in ("high", "critical")
        ]
        if action == "approve" and serious:
            st.warning(
                "You are approving despite "
                + ", ".join(c["rule_id"].replace("_", " ") for c in serious)
                + ". Your reason is recorded with the decision."
            )
        placeholder = {
            "approve": "Quote attached, price in line with the catalogue, within budget.",
            "reject": "Supplier blocked in the vendor master; use an approved supplier.",
            "request_info": "Please attach two more written quotes (NX-PUR-001 §5).",
            "escalate": "Above my approval authority: needs the Head of Procurement.",
        }[action]
        reason = st.text_area(
            "Reason (required)",
            placeholder=placeholder,
            key=f"reason-{detail['id']}",
            help="At least 10 characters. Visible to the requester and in the audit trail.",
        )
        if st.button(ui.ACTION_BUTTON[action], type="primary", key=f"go-{detail['id']}"):
            try:
                result = state.call(
                    "POST",
                    f"/requests/{detail['id']}/decisions",
                    json={"action": action, "reason": reason, "version": detail["version"]},
                )
            except ApiError as error:
                state.show_error(error)
                return
            st.toast(f"Decision recorded: {ui.STATUS[result['status']][1].lower()}")
            st.rerun()


def _completion(detail: dict) -> None:
    me = state.persona()
    if detail["status"] != "info_requested" or detail["requester_id"] != me.id:
        return
    question = next(
        (d for d in reversed(detail["decisions"]) if d["action"] == "request_info"), None
    )
    st.warning(
        "Procurement needs more information: "
        + (question["reason"] if question else "see the history.")
    )
    with st.expander("Complete the request", expanded=True):
        payload = request_form(f"complete-{detail['id']}", prefill=detail)
        if payload is not None:
            try:
                state.call("PUT", f"/requests/{detail['id']}", json=payload)
            except ApiError as error:
                state.show_error(error)
                return
            st.toast("Request completed and checked again")
            st.rerun()


def _history(detail: dict, users: dict) -> None:
    st.subheader("History")
    name = {uid: u["name"] for uid, u in users.items()}
    lines = []
    for d in detail["decisions"]:
        lines.append(
            f"<div><b>{html.escape(name.get(d['actor_id'], d['actor_id']))}</b>: "
            f"{ui.ACTIONS[d['action']].lower()} (version {d['version']})"
            f"<br>{html.escape(d['reason'])}<small>{ui.when(d['created_at'])}</small></div>"
        )
    created = f"<div>Submitted<small>{ui.when(detail['created_at'])}</small></div>"
    st.markdown(f'<div class="nx-timeline">{created}{"".join(lines)}</div>', unsafe_allow_html=True)
    if detail.get("audit"):
        with st.expander(f"Audit trail ({ui.plural(len(detail['audit']), 'event')})"):
            for e in detail["audit"]:
                who = name.get(e["actor_id"], "system") if e["actor_id"] else "system"
                st.markdown(f"- {ui.when(e['created_at'])}, {who}: `{e['type']}`")


def render() -> None:
    request_id = st.session_state.get("open_request") or st.query_params.get("request")
    if not request_id:
        st.title("Request")
        st.info("Open a request from a list to see it here.")
        return
    try:
        detail = state.call("GET", f"/requests/{request_id}")
    except ApiError as error:
        st.title("Request")
        if error.status == 404:
            st.error("This request does not exist or is not visible with your role.")
        else:
            state.show_error(error)
        return
    st.query_params["request"] = request_id  # the address can be shared
    users = state.reference(state.persona().token)["users"]
    _header(detail, users)
    _completion(detail)
    main, side = st.columns([3, 2], gap="large")
    with main:
        _details(detail)
        _checks(detail)
        _analysis(detail)
    with side:
        _decision_panel(detail)
        _history(detail, users)
