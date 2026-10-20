"""Domain vocabulary shared by the services, the API and the interface."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    REQUESTER = "requester"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    INTAKE_SERVICE = "intake_service"
    ADMIN = "admin"


class Status(StrEnum):
    SUBMITTED = "submitted"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"
    ANALYSED = "analysed"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_APPROVER = "awaiting_approver"
    INFO_REQUESTED = "info_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


class Outcome(StrEnum):
    PASS = "pass"
    FLAG = "flag"
    FAIL = "fail"


@dataclass(frozen=True)
class User:
    id: str
    name: str
    email: str
    role: Role
    department: str


@dataclass
class CheckResult:
    """One validation check or business rule, with what it saw."""

    stage: str  # "validation" or "rule"
    rule_id: str
    outcome: Outcome
    severity: Severity
    message: str
    field: str | None = None
    policy_ref: str | None = None
    evidence: dict[str, Any] = dc_field(default_factory=dict)
