"""Figures for the dashboard and the weekly digest, computed from the stored
requests, checks, analyses and decisions (nothing estimated, nothing assumed)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexora.db.models import AnalysisRow, CheckRow, DecisionRow, RequestRow

WAITING = ("awaiting_review", "awaiting_approver", "info_requested")
CLOSED = ("approved", "rejected")


def _aware(value: datetime, like: datetime) -> datetime:
    """SQLite returns naive datetimes; they are stored in UTC."""
    if value.tzinfo is None and like.tzinfo is not None:
        return value.replace(tzinfo=like.tzinfo)
    return value


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


def compute(session: Session, now: datetime, days: int = 30) -> dict[str, Any]:
    since = now - timedelta(days=days)
    requests = [
        r
        for r in session.scalars(select(RequestRow))
        if _aware(r.created_at, now) >= since or r.status in WAITING
    ]
    ids = {r.id for r in requests}
    current = {r.id: r.version for r in requests}

    checks = [
        c
        for c in session.scalars(select(CheckRow).where(CheckRow.outcome != "pass"))
        if c.request_id in ids and c.version == current[c.request_id] and c.stage != "validation"
    ]
    analyses = [a for a in session.scalars(select(AnalysisRow)) if a.request_id in ids]
    decisions = [d for d in session.scalars(select(DecisionRow)) if d.request_id in ids]

    by_status = Counter(r.status for r in requests)
    waiting = [r for r in requests if r.status in WAITING]
    oldest = max((now - _aware(r.updated_at, now) for r in waiting), default=None)

    closing = {}
    for d in decisions:
        if d.to_status in CLOSED:
            closing[d.request_id] = d.created_at
    cycle = [
        _hours(_aware(closing[r.id], now) - _aware(r.created_at, now))
        for r in requests
        if r.id in closing
    ]

    per_day = Counter(_aware(r.created_at, now).date().isoformat() for r in requests)
    first_day = (now - timedelta(days=days - 1)).date()
    daily = [
        {
            "date": (first_day + timedelta(days=i)).isoformat(),
            "requests": per_day.get((first_day + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(days)
    ]

    completed = [a for a in analyses if a.status == "completed"]
    latencies = [a.latency_ms for a in completed if a.provider != "scripted"]
    costs = [a.estimated_cost_usd for a in analyses if a.estimated_cost_usd is not None]
    issues = Counter(i["code"] for a in analyses for i in (a.issues or []))

    return {
        "period_days": days,
        "generated_at": now.isoformat(),
        "requests": {
            "total": len(requests),
            "by_status": dict(sorted(by_status.items())),
            "by_channel": dict(Counter(r.channel for r in requests)),
            "by_department": dict(Counter(r.department for r in requests)),
            "amount_eur": round(sum(float(r.amount_eur) for r in requests), 2),
            "daily": daily,
        },
        "queue": {
            "awaiting_review": by_status.get("awaiting_review", 0),
            "awaiting_approver": by_status.get("awaiting_approver", 0),
            "info_requested": by_status.get("info_requested", 0),
            "oldest_waiting_hours": _hours(oldest) if oldest else None,
        },
        "exceptions": {
            "requests_with_findings": len({c.request_id for c in checks}),
            "by_rule": dict(Counter(c.rule_id for c in checks).most_common()),
            "by_severity": dict(Counter(c.severity for c in checks)),
        },
        "decisions": {
            "total": len(decisions),
            "by_action": dict(Counter(d.action for d in decisions)),
            "approved_despite_high_findings": sum(
                1 for d in decisions if (d.evidence or {}).get("approved_despite")
            ),
            "closed": len(cycle),
            "cycle_time_hours_median": round(median(cycle), 1) if cycle else None,
            "cycle_time_hours_p90": _percentile(cycle, 0.9),
        },
        "ai": {
            "analyses": len(analyses),
            "by_provider": dict(Counter(a.provider for a in analyses)),
            "by_status": dict(Counter(a.status for a in analyses)),
            "by_verification": dict(Counter(a.verification or "none" for a in analyses)),
            "issues": dict(issues.most_common()),
            "latency_ms_median": round(median(latencies)) if latencies else None,
            "tokens": sum(a.input_tokens + a.output_tokens for a in analyses),
            "estimated_cost_usd": round(sum(costs), 6),
        },
    }
