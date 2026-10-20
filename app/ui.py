"""Look and small building blocks of the interface.

Palette: a petrol-night console. One accent (blue) for actions and charts;
the severity and outcome colours are the reserved status colours and are
always shown with a word, never alone. The decision stamp on closed requests
is the one decorative element.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

import streamlit as st

SEVERITY = {
    "info": ("#8b98a5", "Info"),
    "low": ("#a9b8c6", "Low"),
    "medium": ("#fab219", "Medium"),
    "high": ("#ec835a", "High"),
    "critical": ("#d03b3b", "Critical"),
}
STATUS = {
    "submitted": ("#8b98a5", "Submitted"),
    "validated": ("#8b98a5", "Validated"),
    "analysed": ("#8b98a5", "Analysed"),
    "awaiting_review": ("#3987e5", "Waiting for review"),
    "awaiting_approver": ("#3987e5", "Waiting for approval"),
    "info_requested": ("#fab219", "Information requested"),
    "approved": ("#0ca30c", "Approved"),
    "rejected": ("#d03b3b", "Rejected"),
}
ACTIONS = {
    "approve": "Approve",
    "reject": "Reject",
    "request_info": "Ask the requester for information",
    "escalate": "Send to the Head of Procurement",
}
ACTION_BUTTON = {
    "approve": "Approve the request",
    "reject": "Reject the request",
    "request_info": "Send the question",
    "escalate": "Send for approval",
}
VERIFICATION = {
    "verified": ("#0ca30c", "Verified", "Every citation, figure and finding was checked."),
    "corrected": (
        "#fab219",
        "Corrected",
        "Citations or explanations that did not hold were removed.",
    ),
    "unverified": (
        "#ec835a",
        "Unverified",
        "Some statements could not be checked. Read the issues before relying on it.",
    ),
}

CSS = """
<style>
:root {
  --nx-bg: #152029; --nx-surface: #1c2b36; --nx-raised: #233543; --nx-line: #314656;
  --nx-text: #e7eef3; --nx-muted: #9aacba; --nx-accent: #3987e5;
}
h1, h2, h3 { letter-spacing: 0.01em; }
.nx-chip {
  display: inline-flex; align-items: center; gap: .4rem; padding: .1rem .55rem;
  border: 1px solid var(--nx-line); border-radius: 999px; font-size: .82rem;
  color: var(--nx-text); background: var(--nx-surface); white-space: nowrap;
}
.nx-dot { width: .55rem; height: .55rem; border-radius: 2px; display: inline-block; }
.nx-meta { color: var(--nx-muted); font-size: .9rem; }
.nx-meta b { color: var(--nx-text); font-weight: 600; }
.nx-finding {
  border-left: 4px solid var(--sev); background: var(--nx-surface);
  padding: .6rem .8rem; margin: 0 0 .5rem 0; border-radius: 0 6px 6px 0;
}
.nx-finding p { margin: .2rem 0 0 0; }
.nx-finding .nx-ref { color: var(--nx-muted); font-size: .85rem; }
.nx-stamp {
  display: inline-block; transform: rotate(-4deg); border: 3px double var(--stamp);
  color: var(--stamp); padding: .35rem 1rem .45rem; border-radius: 6px; text-align: center;
  font-family: NexoraDisplay, sans-serif; line-height: 1.1;
}
.nx-stamp strong { font-size: 1.9rem; font-weight: 700; display: block; }
.nx-stamp span { font-size: .85rem; }
.nx-timeline { border-left: 2px solid var(--nx-line); margin-left: .3rem; padding-left: .9rem; }
.nx-timeline div { margin-bottom: .55rem; }
.nx-timeline small { color: var(--nx-muted); display: block; }
.nx-quote {
  border-left: 2px solid var(--nx-line); padding-left: .8rem; color: var(--nx-muted);
  font-size: .9rem; white-space: pre-wrap;
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def chip(color: str, label: str) -> str:
    return (
        f'<span class="nx-chip"><span class="nx-dot" style="background:{color}"></span>'
        f"{html.escape(label)}</span>"
    )


def severity_chip(severity: str) -> str:
    color, label = SEVERITY.get(severity, SEVERITY["info"])
    return chip(color, label)


def status_chip(status: str) -> str:
    color, label = STATUS.get(status, ("#8b98a5", status))
    return chip(color, label)


def money(amount: float, currency: str = "EUR") -> str:
    return f"{amount:,.2f} {currency}"


def when(value: str | None) -> str:
    if not value:
        return ""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.strftime("%d %b %Y, %H:%M")


def waiting(value: str, now: datetime | None = None) -> str:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    hours = ((now or datetime.now(UTC)) - moment).total_seconds() / 3600
    if hours < 1:
        return "less than an hour"
    if hours < 48:
        return f"{hours:.0f} h"
    return f"{hours / 24:.0f} days"


def stamp(action: str, name: str, moment: str) -> str:
    color = "#0ca30c" if action == "approved" else "#d03b3b"
    word = "Approved" if action == "approved" else "Rejected"
    return (
        f'<div class="nx-stamp" style="--stamp:{color}"><strong>{word}</strong>'
        f"<span>{html.escape(name)}<br>{when(moment)}</span></div>"
    )


def finding(check: dict) -> str:
    color, label = SEVERITY.get(check["severity"], SEVERITY["info"])
    ref = (
        f'<span class="nx-ref">Policy {html.escape(check["policy_ref"])}</span>'
        if check.get("policy_ref")
        else ""
    )
    rule = check["rule_id"].replace("_", " ").capitalize()
    return (
        f'<div class="nx-finding" style="--sev:{color}">'
        f"{chip(color, label)} <b>{html.escape(rule)}</b> {ref}"
        f"<p>{html.escape(check['message'])}</p></div>"
    )


def verification_chip(status: str | None) -> str:
    if status not in VERIFICATION:
        return chip("#8b98a5", "Not available")
    color, label, _ = VERIFICATION[status]
    return chip(color, label)
