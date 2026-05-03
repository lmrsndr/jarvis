from __future__ import annotations

from typing import Any

from core.auth import verify_admin_password
from core.audit_log import write_audit_event
from core.config import Settings
from plugins.loader import PluginLoader, PluginNotFoundError, PluginValidationError
from plugins.universal import DESTRUCTIVE_ACTIONS, ExecutionLayer, PermissionEngine


class PluginPermissionError(PermissionError):
    pass


class PluginRunner:
    def __init__(self, loader: PluginLoader | None = None, settings: Settings | None = None) -> None:
        self.loader = loader or PluginLoader()
        self.settings = settings

    def run(
        self,
        name: str,
        args: dict[str, Any],
        *,
        confirmed: bool = False,
        admin_password: str | None = None,
    ) -> dict[str, Any]:
        record = self.loader.get_record(name)
        plugin = record.schema if record and record.status == "ready" else None
        if plugin is None or not plugin.enabled:
            raise PluginNotFoundError(name)
        plugin_data = plugin.model_dump()
        plugin_data["declared_permissions"] = record.permissions if record else {}

        try:
            self._verify_permissions(plugin_data, args, confirmed=confirmed, admin_password=admin_password)
            write_audit_event(
                "plugin.interaction.started",
                {
                    "tool_name": name,
                    "risk_level": plugin.risk_level or plugin.permissions,
                    "execution_mode": plugin.execution_mode,
                    "args_keys": sorted(args.keys()),
                    "confirmed": confirmed,
                },
            )
            result = self.loader.run_plugin(name, args)
            standardized = ExecutionLayer.standardize(plugin_data, result)
        except PermissionError as exc:
            write_audit_event(
                "plugin.interaction.denied",
                {"tool_name": name, "reason": str(exc), "args_keys": sorted(args.keys())},
            )
            raise PluginPermissionError(str(exc)) from exc
        except Exception as exc:
            write_audit_event(
                "plugin.interaction.error",
                {"tool_name": name, "error": str(exc), "args_keys": sorted(args.keys())},
            )
            raise

        write_audit_event(
            "plugin.interaction.completed",
            {
                "tool_name": name,
                "ok": standardized["ok"],
                "mode": standardized["mode"],
                "output_keys": sorted(result.keys()),
                "permissions_granted": confirmed or plugin.permissions == "safe",
            },
        )
        return {"tool_name": name, "result": result, "standardized": standardized, "executed": True}

    def _verify_permissions(
        self,
        plugin_data: dict[str, Any],
        args: dict[str, Any],
        *,
        confirmed: bool,
        admin_password: str | None,
    ) -> None:
        action = str(args.get("action") or "")
        plugin_name = str(plugin_data.get("tool_name") or plugin_data.get("name"))
        if action in DESTRUCTIVE_ACTIONS and plugin_name != "filesystem_manager":
            approval = str(args.get("approval_text") or "").strip()
            expected = PermissionEngine.approval_phrase(plugin_name, args)
            if approval != expected:
                raise PermissionError(f"Strong confirmation required. {expected}")
        PermissionEngine.assert_allowed(plugin_data, args, confirmed=confirmed)
        if str(plugin_data.get("risk_level") or plugin_data.get("permissions")) == "dangerous":
            if self.settings is None:
                raise PermissionError("Dangerous plugin requires settings for admin verification.")
            if not verify_admin_password(admin_password, self.settings, audit_type="dangerous_plugin"):
                raise PermissionError("Dangerous plugin requires admin password.")


def run_plugin(
    name: str,
    args: dict[str, Any],
    *,
    confirmed: bool = False,
    admin_password: str | None = None,
    settings: Settings | None = None,
    loader: PluginLoader | None = None,
) -> dict[str, Any]:
    return PluginRunner(loader=loader, settings=settings).run(
        name,
        args,
        confirmed=confirmed,
        admin_password=admin_password,
    )
