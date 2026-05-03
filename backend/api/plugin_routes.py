from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.audit_log import write_audit_event
from core.auth import require_admin_password, verify_admin_password
from core.config import Settings, get_settings
from plugins.installer import PluginInstallError, PluginInstaller
from plugins.loader import PluginLoader, PluginNotFoundError, PluginValidationError
from plugins.runner import PluginPermissionError, PluginRunner

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class ToolRunRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    admin_password: str | None = None


class PluginInstallRequest(BaseModel):
    filename: str
    package_base64: str
    admin_password: str | None = None
    approval_text: str = ""


@router.get("")
def list_plugins():
    return {"plugins": PluginLoader().list_plugins()}


@router.post("/install/preview")
def preview_install(request: PluginInstallRequest):
    try:
        preview = PluginInstaller().preview_base64_package(request.package_base64, request.filename)
    except (PluginInstallError, ValueError) as exc:
        write_audit_event("plugin_install.preview_failed", {"filename": request.filename, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return preview.as_dict()


@router.post("/install/apply")
def apply_install(request: PluginInstallRequest, settings: Settings = Depends(get_settings)):
    require_admin_password(request.admin_password, settings, audit_type="plugin_install")
    try:
        result = PluginInstaller().apply_base64_package(
            request.package_base64,
            request.filename,
            admin_password_valid=True,
            approval_text=request.approval_text,
        )
    except (PluginInstallError, ValueError) as exc:
        write_audit_event("plugin_install.apply_failed", {"filename": request.filename, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return result


@router.get("/{name}")
def get_plugin(name: str):
    loader = PluginLoader()
    plugin = loader.get_plugin(name)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin not found: {name}")
    return plugin.model_dump()


@router.post("/{name}/run")
def run_plugin(name: str, request: ToolRunRequest, settings: Settings = Depends(get_settings)):
    loader = PluginLoader()
    plugin = loader.get_plugin(name)
    if plugin is None:
        write_audit_event("plugin.run_denied", {"tool_name": name, "reason": "not_found"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin not found: {name}")
    _verify_run_permission(plugin.permissions, request, settings)

    try:
        write_audit_event(
            "plugin.run_started",
            {
                "tool_name": name,
                "permissions": plugin.permissions,
                "confirmed": request.confirmed,
                "args_keys": sorted(request.args.keys()),
            },
        )
        run_result = PluginRunner(loader=loader, settings=settings).run(
            name,
            request.args,
            confirmed=request.confirmed,
            admin_password=request.admin_password,
        )
        result = run_result["result"]
    except PluginNotFoundError as exc:
        write_audit_event("plugin.run_failed", {"tool_name": name, "reason": "not_found"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin not found: {name}") from exc
    except PluginPermissionError as exc:
        write_audit_event("plugin.run_denied", {"tool_name": name, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PluginValidationError as exc:
        write_audit_event("plugin.run_failed", {"tool_name": name, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_audit_event(
        "plugin.run",
        {
            "tool_name": name,
            "permissions": plugin.permissions,
            "confirmed": request.confirmed,
            "args_keys": sorted(request.args.keys()),
        },
    )
    return {"tool_name": name, "result": result}


def _verify_run_permission(permission: str, request: ToolRunRequest, settings: Settings) -> None:
    if permission == "safe":
        return
    if permission == "medium" and request.confirmed:
        return
    if permission == "dangerous" and verify_admin_password(request.admin_password, settings, audit_type="dangerous_plugin"):
        return
    if permission == "medium":
        write_audit_event("plugin.run_denied", {"permissions": permission, "reason": "confirmation_required"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Medium-risk plugin requires confirmation.")
    write_audit_event("plugin.run_denied", {"permissions": permission, "reason": "admin_password_required"})
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dangerous plugin requires admin password.")
