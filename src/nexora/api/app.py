"""HTTP API. Thin: it authenticates the caller, then hands over to the services,
which hold every rule and every permission check."""

import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

import yaml
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexora.api import schemas as out
from nexora.config import Settings, get_settings
from nexora.db.models import AuditEventRow, RequestRow
from nexora.db.session import (
    make_engine,
    make_session_factory,
    migrate,
    seed_reference_data,
    transaction,
)
from nexora.domain.models import Role, User
from nexora.domain.rules_config import load_rules
from nexora.domain.workflow import DECIDERS
from nexora.llm import LLMProvider, build_provider
from nexora.services import csv_import, intake, metrics, notifications, review
from nexora.services.authorization import Forbidden, can_read
from nexora.services.csv_import import MAX_CSV_BYTES
from nexora.services.errors import Conflict, Invalid, NotFound
from nexora.services.retrieval import load_knowledge_base

bearer = HTTPBearer(auto_error=False)


def _load_users(settings: Settings) -> dict[str, User]:
    users = yaml.safe_load(settings.users_path.read_text(encoding="utf-8"))["users"]
    return {
        u["token"]: User(u["id"], u["name"], u["email"], Role(u["role"]), u["department"])
        for u in users
    }


class RateLimiter:
    """Sliding one-minute window per actor; enough to stop a runaway client."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.calls: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self.calls[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            raise HTTPException(429, detail={"code": "rate_limited", "message": "Too many calls."})
        window.append(now)


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    migrate(engine)
    factory = make_session_factory(engine)
    with transaction(factory) as session:
        seed_reference_data(session, settings.users_path, settings.synthetic_dir)
    rule_set = load_rules(settings.rules_path)
    users = _load_users(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    provider = provider or build_provider(settings)
    knowledge_base = load_knowledge_base(settings.knowledge_base_dir)

    app = FastAPI(
        title="NEXORA AI",
        version="0.2.0",
        description=(
            "AI-assisted review of purchase requests for Nexora Industries, a fictional "
            "company. Synthetic data; demonstration bearer tokens are listed in "
            "config/demo_users.yaml."
        ),
    )

    def session_dep() -> Iterator[Session]:
        with transaction(factory) as session:
            yield session

    def actor_dep(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> User:
        user = users.get(credentials.credentials) if credentials else None
        if user is None:
            raise HTTPException(
                401, detail={"code": "unauthenticated", "message": "A valid token is required."}
            )
        return user

    SessionDep = Annotated[Session, Depends(session_dep)]
    ActorDep = Annotated[User, Depends(actor_dep)]

    @app.exception_handler(Forbidden)
    async def forbidden_handler(_: Request, error: Forbidden) -> JSONResponse:
        return JSONResponse(
            status_code=403, content={"detail": {"code": "forbidden", "message": str(error)}}
        )

    @app.exception_handler(Conflict)
    async def conflict_handler(_: Request, error: Conflict) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"detail": {"code": "conflict", "message": str(error)}}
        )

    @app.exception_handler(NotFound)
    async def not_found_handler(_: Request, error: NotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": {"code": "not_found", "message": str(error)}}
        )

    @app.exception_handler(Invalid)
    async def invalid_handler(_: Request, error: Invalid) -> JSONResponse:
        body = {"code": "invalid", "message": str(error), "field": error.field}
        return JSONResponse(status_code=422, content={"detail": body})

    def detail_of(row: RequestRow, actor: User, session: Session) -> out.RequestDetail:
        detail = out.RequestDetail.of(row, knowledge_base)
        detail.allowed_actions = review.actions_for(actor, row)
        detail.audit = [
            out.AuditEvent.of(e)
            for e in session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.request_id == row.id)
                .order_by(AuditEventRow.id)
            )
        ]
        return detail

    @app.get("/health", response_model=out.Health, tags=["system"])
    def health(session: SessionDep) -> out.Health:
        session.execute(text("SELECT 1"))
        return out.Health(
            status="ok",
            database="ok",
            rule_set_version=rule_set.version,
            ai_provider=provider.name,
            ai_model=provider.model,
        )

    @app.post(
        "/requests",
        status_code=201,
        response_model=out.RequestDetail,
        responses={
            200: {"description": "Same request submitted again: the stored one is returned."},
            409: {"description": "Duplicate reference or reused idempotency key."},
            422: {"model": out.ValidationFailure, "description": "Invalid request."},
        },
        tags=["requests"],
    )
    def submit_request(
        payload: dict[str, Any],
        actor: ActorDep,
        session: SessionDep,
        idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
        channel: Annotated[
            str, Header(description="api, form, csv or email (set by the intake service).")
        ] = "api",
        on_behalf_of: Annotated[
            str | None,
            Header(
                max_length=200,
                description="Integration service only: email of the requester.",
            ),
        ] = None,
    ) -> Any:
        limiter.check(actor.id)
        result = intake.submit(
            session,
            actor,
            payload,
            rule_set,
            clock(),
            idempotency_key,
            provider=provider,
            knowledge_base=knowledge_base,
            channel=channel,
            on_behalf_of=on_behalf_of,
        )
        if not result.accepted:
            session.commit()  # keep the audit event of the rejection
            body = out.ValidationFailure(
                code="validation_failed",
                message="The request is not valid. Every problem is listed.",
                errors=[out.Check.of(c) for c in result.checks if c.outcome.value == "fail"],
            )
            return JSONResponse(status_code=422, content={"detail": body.model_dump(mode="json")})
        detail = detail_of(result.request, actor, session)
        detail.audit = []
        if result.replayed:
            return JSONResponse(status_code=200, content=detail.model_dump(mode="json"))
        return detail

    @app.get("/requests", response_model=list[out.RequestSummary], tags=["requests"])
    def list_requests(
        actor: ActorDep,
        session: SessionDep,
        status: str | None = None,
        department: str | None = None,
        actionable: Annotated[
            bool, Query(description="Only the requests waiting for a decision of the caller.")
        ] = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[out.RequestSummary]:
        query = select(RequestRow).order_by(RequestRow.created_at.desc()).limit(limit)
        if status:
            query = query.where(RequestRow.status == status)
        if department:
            query = query.where(RequestRow.department == department)
        if actionable:
            waiting = [s.value for s, (role, _) in DECIDERS.items() if role is actor.role]
            query = query.where(RequestRow.status.in_(waiting), RequestRow.requester_id != actor.id)
        if actor.role not in {Role.REVIEWER, Role.APPROVER, Role.ADMIN}:
            query = query.where(RequestRow.requester_id == actor.id)
        return [out.RequestSummary.of(r) for r in session.scalars(query)]

    @app.get("/requests/{request_id}", response_model=out.RequestDetail, tags=["requests"])
    def get_request(request_id: str, actor: ActorDep, session: SessionDep) -> out.RequestDetail:
        row = session.get(RequestRow, request_id)
        if row is None or not can_read(actor, row.requester_id):
            # Same answer for "absent" and "not yours": no information leak.
            raise HTTPException(404, detail={"code": "not_found", "message": "No such request."})
        return detail_of(row, actor, session)

    @app.put(
        "/requests/{request_id}",
        response_model=out.RequestDetail,
        responses={
            409: {"description": "The request is not waiting for information."},
            422: {"model": out.ValidationFailure, "description": "Invalid request."},
        },
        tags=["requests"],
    )
    def complete_request(
        request_id: str, payload: dict[str, Any], actor: ActorDep, session: SessionDep
    ) -> Any:
        """The requester completes a request returned for information: a new
        version is created and every check runs again."""
        limiter.check(actor.id)
        result = intake.resubmit(
            session,
            actor,
            request_id,
            payload,
            rule_set,
            clock(),
            provider=provider,
            knowledge_base=knowledge_base,
        )
        if not result.accepted:
            session.commit()  # keep the audit event of the rejection
            body = out.ValidationFailure(
                code="validation_failed",
                message="The request is not valid. Every problem is listed.",
                errors=[out.Check.of(c) for c in result.checks if c.outcome.value == "fail"],
            )
            return JSONResponse(status_code=422, content={"detail": body.model_dump(mode="json")})
        return detail_of(result.request, actor, session)

    @app.post(
        "/requests/{request_id}/decisions",
        status_code=201,
        response_model=out.DecisionResult,
        responses={
            403: {"description": "Wrong role, or the caller's own request."},
            409: {"description": "Wrong state, changed version or decision already taken."},
            422: {"description": "Missing reason or unknown action."},
        },
        tags=["review"],
    )
    def record_decision(
        request_id: str, body: out.DecisionIn, actor: ActorDep, session: SessionDep
    ) -> out.DecisionResult:
        """Approve, reject, request information or escalate. A reason is always required."""
        limiter.check(actor.id)
        decision = review.decide(
            session, actor, request_id, body.action, body.reason, body.version, clock()
        )
        return out.DecisionResult(decision=out.Decision.of(decision), status=decision.to_status)

    @app.get("/metrics", tags=["dashboard"])
    def get_metrics(
        actor: ActorDep, session: SessionDep, days: Annotated[int, Query(ge=1, le=365)] = 30
    ) -> dict[str, Any]:
        """Figures for the dashboard, computed from the stored data."""
        if actor.role not in {Role.REVIEWER, Role.APPROVER, Role.ADMIN, Role.INTAKE_SERVICE}:
            raise Forbidden("Only procurement and the integration service read the metrics.")
        return metrics.compute(session, clock(), days)

    def require_integration(actor: User) -> None:
        if actor.role not in {Role.INTAKE_SERVICE, Role.ADMIN}:
            raise Forbidden("Only the integration service reads this feed.")

    @app.get("/integration/outbox", tags=["integration"])
    def integration_outbox(
        actor: ActorDep,
        session: SessionDep,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        """Messages to send for the events after the cursor, with their recipients.
        n8n stores `next_cursor` and asks again from there."""
        require_integration(actor)
        return notifications.outbox(session, after, settings.ui_url, limit)

    @app.get("/integration/reminders", tags=["integration"])
    def integration_reminders(
        actor: ActorDep,
        session: SessionDep,
        older_than_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 48,
    ) -> list[dict[str, Any]]:
        """Requests waiting for a person for longer than the given number of hours."""
        require_integration(actor)
        return notifications.reminders(session, clock(), older_than_hours, settings.ui_url)

    @app.get("/integration/digest", tags=["integration"])
    def integration_digest(
        actor: ActorDep, session: SessionDep, days: Annotated[int, Query(ge=1, le=31)] = 7
    ) -> dict[str, Any]:
        """The weekly summary for the Head of Procurement."""
        require_integration(actor)
        return notifications.digest(session, clock(), days, settings.ui_url)

    @app.post("/requests/import", tags=["requests"])
    def import_requests(
        actor: ActorDep,
        session: SessionDep,
        file: Annotated[UploadFile, File(description="CSV file, one request per row.")],
    ) -> dict[str, Any]:
        """Submit every row of a CSV file. Each row is stored or refused on its
        own; the answer lists the result of every row."""
        limiter.check(actor.id)
        content = file.file.read(MAX_CSV_BYTES + 1)
        if len(content) > MAX_CSV_BYTES:
            raise Invalid("The file is larger than 1 MB.", field="file")
        rows = csv_import.parse(content)
        results = []
        for number, payload in rows:
            results.append(
                csv_import.submit_row(
                    session, actor, number, payload, rule_set, clock(), provider, knowledge_base
                )
            )
        return {
            "rows": len(results),
            "created": sum(r["status"] == "created" for r in results),
            "already_submitted": sum(r["status"] == "already_submitted" for r in results),
            "refused": sum(r["status"] == "refused" for r in results),
            "results": results,
        }

    @app.get("/events", response_model=list[out.AuditEvent], tags=["integration"])
    def events(
        actor: ActorDep,
        session: SessionDep,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[out.AuditEvent]:
        if actor.role not in {Role.INTAKE_SERVICE, Role.ADMIN}:
            raise Forbidden("Only the integration service can read the event feed.")
        rows = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.id > after)
            .order_by(AuditEventRow.id)
            .limit(limit)
        )
        return [out.AuditEvent.of(e) for e in rows]

    return app
