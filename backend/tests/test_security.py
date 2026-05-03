from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.config import Settings
from core.permissions import ensure_local_request


def test_local_request_allowed_by_default() -> None:
    ensure_local_request(_request("127.0.0.1"), Settings(local_only=True, allow_remote=False))


def test_remote_request_blocked_by_default() -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_local_request(_request("203.0.113.10"), Settings(local_only=True, allow_remote=False))
    assert exc.value.status_code == 403


def test_remote_request_requires_session_when_enabled() -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_local_request(_request("203.0.113.10"), Settings(local_only=False, allow_remote=True))
    assert exc.value.status_code == 401


def _request(host: str, path: str = "/api/chat") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": (host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
