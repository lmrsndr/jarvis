from __future__ import annotations

from fastapi import HTTPException, Request, status

from core.config import Settings, get_settings
from core.auth import session_is_valid


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def ensure_local_request(request: Request, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    if request.url.path in {"/health", "/api/system/login"}:
        return
    client_host = request.client.host if request.client else ""
    if client_host in LOCAL_HOSTS:
        return
    if active_settings.local_only or not active_settings.allow_remote:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Remote requests are disabled. Set JARVIS_ALLOW_REMOTE=true to opt in.",
        )
    if not session_is_valid(request, active_settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required for remote access.")
