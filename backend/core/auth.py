from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response, status

from core.audit_log import write_audit_event
from core.config import Settings


SESSION_COOKIE = "jarvis_session"
SESSION_TTL_HOURS = 12
_sessions: dict[str, datetime] = {}


@dataclass(frozen=True)
class AuthResult:
    authenticated: bool
    local: bool


def verify_admin_password(password: str | None, settings: Settings, audit_type: str = "admin_password") -> bool:
    if not password or not settings.admin_password_hash:
        write_audit_event(f"{audit_type}.failed", {"reason": "missing_password_or_hash"})
        return False
    provided_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    valid = secrets.compare_digest(provided_hash, settings.admin_password_hash)
    if not valid:
        write_audit_event(f"{audit_type}.failed", {"reason": "invalid_password"})
    return valid


def require_admin_password(password: str | None, settings: Settings, audit_type: str = "admin_password") -> None:
    if not verify_admin_password(password, settings, audit_type=audit_type):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin password confirmation failed.")


def create_session(response: Response, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[_sign(token, settings)] = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=not settings.local_only,
        samesite="lax",
        max_age=SESSION_TTL_HOURS * 3600,
    )
    return token


def clear_session(request: Request, response: Response, settings: Settings) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(_sign(token, settings), None)
    response.delete_cookie(SESSION_COOKIE)


def session_is_valid(request: Request, settings: Settings) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    signed = _sign(token, settings)
    expires_at = _sessions.get(signed)
    if not expires_at:
        return False
    if expires_at <= datetime.now(timezone.utc):
        _sessions.pop(signed, None)
        return False
    return True


def _sign(token: str, settings: Settings) -> str:
    secret = settings.admin_password_hash or "jarvis-development-session-secret"
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
