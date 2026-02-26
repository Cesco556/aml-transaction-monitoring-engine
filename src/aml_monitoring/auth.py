"""API key authentication and actor binding. Optional scopes: read_only vs read_write."""

from __future__ import annotations

import os
from contextvars import ContextVar

from starlette.requests import Request

# When AML_API_KEYS is empty or unset, we default to a single dev key (dev-only, not for production).
_DEFAULT_DEV_KEYS = {"dev": "dev_key"}
_DEFAULT_SCOPE = "read_write"

_current_scope: ContextVar[str] = ContextVar("api_key_scope", default=_DEFAULT_SCOPE)


def parse_api_keys_env() -> tuple[dict[str, str], dict[str, str]]:
    """Parse AML_API_KEYS env var into name->key and key->scope.
    Format: 'name1:key1,name2:key2:read_only' (optional :scope, default read_write).
    Returns (name_to_key, key_to_scope)."""
    raw = os.environ.get("AML_API_KEYS", "").strip()
    if not raw:
        keys = dict(_DEFAULT_DEV_KEYS)
        scopes = {v: _DEFAULT_SCOPE for v in keys.values()}
        return keys, scopes
    name_to_key: dict[str, str] = {}
    key_to_scope: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            parts = part.split(":")
            name = parts[0].strip()
            key = parts[1].strip() if len(parts) > 1 else ""
            scope = parts[2].strip() if len(parts) > 2 else _DEFAULT_SCOPE
            if name and key:
                name_to_key[name] = key
                key_to_scope[key] = (
                    scope if scope in ("read_only", "read_write") else _DEFAULT_SCOPE
                )
    if not name_to_key:
        keys = dict(_DEFAULT_DEV_KEYS)
        scopes = {v: _DEFAULT_SCOPE for v in keys.values()}
        return keys, scopes
    return name_to_key, key_to_scope


def require_api_key(request: Request) -> str:
    """Validate X-API-Key header; set audit actor and scope; return actor name.
    Raises 401 if header missing or key invalid."""
    from aml_monitoring.audit_context import set_actor

    name_to_key, key_to_scope = parse_api_keys_env()
    key_to_actor = {v: k for k, v in name_to_key.items()}
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    actor = key_to_actor.get(api_key)
    if not actor:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid API key")
    scope = key_to_scope.get(api_key, _DEFAULT_SCOPE)
    _current_scope.set(scope)
    set_actor(actor)
    return actor


def require_write_scope() -> None:
    """Raise 403 if current key scope is read_only. Call after require_api_key."""
    scope = _current_scope.get()
    if scope == "read_only":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Insufficient scope: write required")


def require_api_key_write(request: Request) -> str:
    """Require valid API key and write scope; return actor. Use for PATCH /alerts, POST /cases."""
    actor = require_api_key(request)
    require_write_scope()
    return actor
