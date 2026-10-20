"""Errors the services raise; the API turns each into one HTTP status."""

from __future__ import annotations


class Conflict(Exception):
    """The action clashes with the current state (HTTP 409)."""


class NotFound(Exception):
    """No such object, or not visible to the actor (HTTP 404)."""


class Invalid(Exception):
    """The input is well formed but not acceptable (HTTP 422)."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field
