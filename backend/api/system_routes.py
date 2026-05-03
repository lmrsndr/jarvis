from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from core.audit_log import write_audit_event
from core.auth import clear_session, create_session, require_admin_password, session_is_valid
from core.config import Settings, get_settings
from core.providers import ProviderError, get_selected_provider, provider_status, set_selected_provider


router = APIRouter(prefix="/api/system", tags=["system"])


class ProviderSelectionRequest(BaseModel):
    provider: str


class LoginRequest(BaseModel):
    password: str


class ProviderKeyTestRequest(BaseModel):
    admin_password: str


@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {
        "status": "ok",
        "app": "jarvis",
        "default_provider": settings.default_provider,
        "selected_provider": get_selected_provider(),
        "local_only": settings.local_only,
        "allow_remote": settings.allow_remote,
    }


@router.post("/login")
def login(request: LoginRequest, response: Response, settings: Settings = Depends(get_settings)):
    try:
        require_admin_password(request.password, settings, audit_type="login")
    except HTTPException as exc:
        write_audit_event("login.failed", {"reason": "invalid_password"})
        raise exc
    create_session(response, settings)
    write_audit_event("login.success", {"remote_enabled": settings.allow_remote})
    return {"authenticated": True}


@router.post("/logout")
def logout(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    clear_session(request, response, settings)
    write_audit_event("logout", {})
    return {"authenticated": False}


@router.get("/session")
def session(request: Request, settings: Settings = Depends(get_settings)):
    return {"authenticated": session_is_valid(request, settings), "local_only": settings.local_only}


@router.get("/providers")
def providers(settings: Settings = Depends(get_settings)):
    return {"selected_provider": get_selected_provider(), "providers": provider_status(settings)}


@router.post("/provider")
def select_provider(request: ProviderSelectionRequest, settings: Settings = Depends(get_settings)):
    try:
        selected = set_selected_provider(request.provider, settings)
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"selected_provider": selected, "providers": provider_status(settings)}


@router.post("/providers/{provider}/test")
def test_provider_key(provider: str, request: ProviderKeyTestRequest, settings: Settings = Depends(get_settings)):
    require_admin_password(request.admin_password, settings, audit_type="provider_key_test")
    normalized = provider.lower()
    if normalized not in {"openai", "gemini"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only external provider keys can be tested.")
    configured = settings.provider_available(normalized)
    write_audit_event("provider_key_test", {"provider": normalized, "configured": configured})
    return {"provider": normalized, "configured": configured, "remote_call_performed": False}
