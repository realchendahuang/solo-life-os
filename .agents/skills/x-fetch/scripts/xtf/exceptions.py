"""Typed exception hierarchy.

Replaces the old ``dict | str | None`` tri-state returns. Every exception
carries a stable machine-readable ``code`` that also appears in CLI JSON
output as ``error.code``, so agent callers can branch on it.
"""
from __future__ import annotations


class XtfError(Exception):
    """Base class for all x-tweet-fetcher errors."""

    code = "error"

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message or self.code}


class InvalidInput(XtfError):
    """URL / ID / argument could not be parsed."""

    code = "invalid_input"


class NotFound(XtfError):
    """Tweet / user / list / article does not exist (HTTP 404 or API-level)."""

    code = "not_found"


class RateLimited(XtfError):
    """Upstream returned 429/403 — retry later or switch instance."""

    code = "rate_limited"


class UpstreamDown(XtfError):
    """Upstream (FxTwitter / Nitter instance) unreachable or returned 5xx."""

    code = "upstream_down"


class BackendUnavailable(XtfError):
    """Required local dependency missing (Camofox not running, Playwright not installed, no Nitter instance configured)."""

    code = "backend_unavailable"


class NotSupported(XtfError):
    """This backend does not implement the requested capability.

    Raised by backends so the router can fall through to the next one.
    """

    code = "not_supported"


class AllBackendsFailed(XtfError):
    """Every candidate backend raised; carries the per-backend errors."""

    code = "all_backends_failed"

    def __init__(self, message: str = "", causes: dict | None = None):
        super().__init__(message)
        self.causes = causes or {}

    def to_dict(self) -> dict:
        d = super().to_dict()
        if self.causes:
            d["causes"] = {k: str(v) for k, v in self.causes.items()}
        return d
