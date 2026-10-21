"""API security: admin key check, per-IP rate limiting, body limits, headers."""
from __future__ import annotations

import hmac
import time
from collections import OrderedDict
from typing import Dict, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from blockforge.api.errors import ApiError


# ------------------------------------------------------------------ admin key
def require_admin(request: Request) -> None:
    """Dependency for node-control endpoints (mining, peers, raw block submit)."""
    expected: str = request.app.state.settings.api_key
    if not expected:
        raise ApiError(403, "admin-disabled", "admin API is disabled: set BLOCKFORGE_API_KEY")
    supplied = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError(401, "unauthorized", "missing or invalid API key")


# --------------------------------------------------------------- rate limiting
class RateLimiter:
    """Token bucket per (client, bucket-name). Bounded memory (LRU of clients)."""

    def __init__(self, per_minute: int, max_clients: int = 10_000) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(per_minute)
        self._max = max_clients
        self._buckets: "OrderedDict[str, Tuple[float, float]]" = OrderedDict()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.pop(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        while len(self._buckets) > self._max:
            self._buckets.popitem(last=False)
        return allowed


def client_ip(request: Request) -> str:
    # X-Forwarded-For is NOT trusted: it is client-controlled unless a trusted proxy sets it.
    return request.client.host if request.client else "unknown"


def tx_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.tx_limiter
    if not limiter.allow(client_ip(request)):
        raise ApiError(429, "rate-limited", "too many transaction submissions")


class SecurityMiddleware(BaseHTTPMiddleware):
    """Global rate limit, request-size limit and hardening headers."""

    def __init__(self, app, limiter: RateLimiter, max_body_bytes: int) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._max_body = max_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._limiter.allow(client_ip(request)):
            return self._reject(429, "rate-limited", "too many requests")
        if request.method in ("POST", "PUT", "PATCH"):
            if "chunked" in request.headers.get("transfer-encoding", "").lower():
                return self._reject(411, "length-required", "chunked uploads are not accepted")
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return self._reject(411, "length-required", "Content-Length required")
            if int(length) > self._max_body:
                return self._reject(413, "too-large", "request body too large")
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _reject(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)