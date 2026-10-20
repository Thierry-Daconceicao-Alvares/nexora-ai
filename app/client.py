"""How the interface talks to NEXORA: always through the HTTP API, so the
interface gets exactly the permissions and checks any other client gets.

- With NEXORA_API_URL set (Docker Compose), requests go over the network.
- Without it (a single-process demo), the same FastAPI application runs
  inside the interface process and is called in memory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
import yaml

from nexora.config import Settings


@dataclass
class ApiError(Exception):
    status: int
    message: str
    errors: list[dict[str, Any]]

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    department: str
    email: str
    token: str


def personas(settings: Settings | None = None) -> list[Persona]:
    settings = settings or Settings()
    users = yaml.safe_load(settings.users_path.read_text(encoding="utf-8"))["users"]
    return [
        Persona(u["id"], u["name"], u["role"], u["department"], u["email"], u["token"])
        for u in users
        if u["role"] in {"requester", "reviewer", "approver", "admin"}
    ]


class Api:
    def __init__(self, base_url: str | None = None, transport: Any = None) -> None:
        base_url = base_url if base_url is not None else os.environ.get("NEXORA_API_URL", "")
        if base_url:
            self.mode = "http"
            self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=90)
        else:
            from fastapi.testclient import TestClient

            self.mode = "embedded"
            self._http = transport or TestClient(embedded_app())

    def call(self, method: str, path: str, token: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise ApiError(0, f"The NEXORA service cannot be reached ({error}).", []) from error
        if response.status_code >= 400:
            raise _error(response)
        return response.json()

    def get(self, path: str, token: str, **kwargs: Any) -> Any:
        return self.call("GET", path, token, **kwargs)

    def post(self, path: str, token: str, **kwargs: Any) -> Any:
        return self.call("POST", path, token, **kwargs)

    def put(self, path: str, token: str, **kwargs: Any) -> Any:
        return self.call("PUT", path, token, **kwargs)


def embedded_app() -> Any:
    """The API inside the interface process (demo mode): the analyses of the
    demo requests are replayed from a real model's recorded answers, any other
    request is analysed by the configured provider (the scripted stand-in
    without a key). The demo data is added when the database is empty."""
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from nexora import demo
    from nexora.api.app import create_app
    from nexora.llm import build_provider
    from nexora.llm.replay import RECORDINGS, ReplayProvider

    settings = Settings()
    provider = ReplayProvider.from_file(RECORDINGS, fallback=build_provider(settings))
    clock: dict[str, datetime | None] = {"now": None}
    app = create_app(settings, clock=lambda: clock["now"] or datetime.now(UTC), provider=provider)
    demo.seed(TestClient(app), clock, log=lambda _: None)
    clock["now"] = None  # from now on, real time
    return app


def _error(response: httpx.Response) -> ApiError:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict):
        return ApiError(response.status_code, detail.get("message", ""), detail.get("errors", []))
    if isinstance(detail, list):  # FastAPI schema errors
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
            for e in detail
        ]
        return ApiError(response.status_code, "Some fields are not valid.", errors)
    return ApiError(response.status_code, f"The service answered HTTP {response.status_code}.", [])
