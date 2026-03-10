"""Security middleware: rate limiting, CORS, security headers, request size limits."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from limits import parse as parse_limit
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from aml_monitoring.config import get_config

# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_rate_storage = MemoryStorage()
_rate_limiter = FixedWindowRateLimiter(_rate_storage)


def reset_rate_limits() -> None:
    """Clear all rate limit counters. For use in tests."""
    global _rate_storage, _rate_limiter
    _rate_storage = MemoryStorage()
    _rate_limiter = FixedWindowRateLimiter(_rate_storage)


def _get_read_limit() -> str:
    """Resolve read rate limit from config or env."""
    limit = os.environ.get("AML_RATE_LIMIT_READ")
    if limit:
        return limit
    sec = _safe_get_security_config()
    return sec.get("rate_limiting", {}).get("read_limit", "100/minute")


def _get_write_limit() -> str:
    """Resolve write rate limit from config or env."""
    limit = os.environ.get("AML_RATE_LIMIT_WRITE")
    if limit:
        return limit
    sec = _safe_get_security_config()
    return sec.get("rate_limiting", {}).get("write_limit", "20/minute")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting with separate read/write limits."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Determine client IP
        client_ip = request.client.host if request.client else "unknown"

        # Pick the right limit
        if request.method in _WRITE_METHODS:
            limit_str = _get_write_limit()
            namespace = "write"
        else:
            limit_str = _get_read_limit()
            namespace = "read"

        limit_item = parse_limit(limit_str)
        key = f"{namespace}:{client_ip}"

        if not _rate_limiter.hit(limit_item, key):  # noqa: uses module-level _rate_limiter
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry later."},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers into every response."""

    def __init__(self, app: Any, headers: dict[str, str] | None = None) -> None:
        super().__init__(app)
        self.security_headers = headers or self._default_headers()

    @staticmethod
    def _default_headers() -> dict[str, str]:
        sec = _safe_get_security_config().get("headers", {})
        return {
            "X-Content-Type-Options": sec.get("x_content_type_options", "nosniff"),
            "X-Frame-Options": sec.get("x_frame_options", "DENY"),
            "X-XSS-Protection": sec.get("x_xss_protection", "1; mode=block"),
            "Content-Security-Policy": sec.get(
                "content_security_policy", "default-src 'none'; frame-ancestors 'none'"
            ),
            "Referrer-Policy": sec.get("referrer_policy", "strict-origin-when-cross-origin"),
            "Cache-Control": sec.get("cache_control", "no-store"),
        }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        for k, v in self.security_headers.items():
            response.headers[k] = v
        return response


# ---------------------------------------------------------------------------
# Request Size Limit
# ---------------------------------------------------------------------------

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with Content-Length exceeding max_bytes."""

    def __init__(self, app: Any, max_bytes: int = 1_048_576) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------

def _safe_get_security_config() -> dict[str, Any]:
    """Load security config section, falling back to empty dict on config errors."""
    try:
        cfg = get_config()
        return cfg.get("security", {})
    except (ValueError, FileNotFoundError):
        return {}


def setup_security(app: FastAPI) -> None:
    """Wire all security middleware into the FastAPI app."""
    security_cfg = _safe_get_security_config()

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # CORS
    cors_cfg = security_cfg.get("cors", {})
    origins_env = os.environ.get("AML_CORS_ORIGINS")
    if origins_env:
        origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    else:
        origins = cors_cfg.get("allowed_origins", [
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
        ])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=cors_cfg.get("allow_credentials", False),
        allow_methods=cors_cfg.get("allow_methods", ["GET", "POST", "PATCH", "OPTIONS"]),
        allow_headers=cors_cfg.get("allow_headers", [
            "X-API-Key", "X-Correlation-ID", "Content-Type",
        ]),
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Request size limit
    req_cfg = security_cfg.get("request", {})
    max_body = req_cfg.get("max_body_size_bytes", 1_048_576)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_body)
