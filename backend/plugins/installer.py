from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.audit_log import write_audit_event
from core.config import ROOT_DIR
from plugins.schema import PluginSchema


PROTECTED_CORE_PATHS = (
    Path("backend/core"),
    Path("backend/api"),
    Path("backend/memory"),
    Path("frontend/src"),
    Path("backend/main.py"),
)
TOOLS_PATH = Path("backend/plugins/tools")
REGISTRY_PATH = Path("backend/plugins/registry.json")
MARKER_START = "JARVIS_PLUGIN_EDIT_START"
MARKER_END = "JARVIS_PLUGIN_EDIT_END"


class PluginInstallError(RuntimeError):
    pass


@dataclass
class InstallPreview:
    tool_name: str
    files_to_add: list[str]
    files_to_modify: list[str]
    permissions_requested: str
    risk_level: str
    tests_to_run: list[str]
    password_approval_needed: bool
    approval_phrases_required: list[str]
    forbidden: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "files_to_add": self.files_to_add,
            "files_to_modify": self.files_to_modify,
            "permissions_requested": self.permissions_requested,
            "risk_level": self.risk_level,
            "tests_to_run": self.tests_to_run,
            "password_approval_needed": self.password_approval_needed,
            "approval_phrases_required": self.approval_phrases_required,
            "forbidden": self.forbidden,
        }


class PluginInstaller:
    def __init__(self, root_dir: Path = ROOT_DIR) -> None:
        self.root_dir = root_dir
        self.tools_dir = self.root_dir / TOOLS_PATH
        self.registry_path = self.root_dir / REGISTRY_PATH
        self.backup_dir = self.root_dir / "storage" / "backups" / "plugins"

    def preview_base64_package(self, package_base64: str, filename: str) -> InstallPreview:
        return self.preview_package(base64.b64decode(package_base64), filename)

    def apply_base64_package(
        self,
        package_base64: str,
        filename: str,
        admin_password_valid: bool = False,
        approval_text: str = "",
    ) -> dict[str, Any]:
        return self.apply_package(base64.b64decode(package_base64), filename, admin_password_valid, approval_text)

    def preview_package(self, package_bytes: bytes, filename: str) -> InstallPreview:
        write_audit_event("plugin_install.preview_started", {"filename": filename})
        extracted = self._read_zip(package_bytes, filename)
        schema = extracted["schema"]
        file_map = extracted["file_map"]
        files_to_add: list[str] = []
        files_to_modify: list[str] = []
        forbidden: list[str] = []
        approval_phrases: list[str] = []

        for relative_path in sorted(file_map):
            target = self._target_path(relative_path)
            display = target.as_posix()
            if self._is_delete_marker(relative_path):
                forbidden.append(f"Deletion is not supported in this version: {display}")
                approval_phrases.append(f"APPROVE DELETE: {display}")
                continue
            if self._is_protected_path(target):
                approval_phrases.append(f"APPROVE CORE CHANGE: {target.name}")
                if not self._has_marker_blocks(file_map[relative_path]):
                    forbidden.append(f"Protected file missing marker blocks: {display}")
            if (self.root_dir / target).exists():
                files_to_modify.append(display)
                approval_phrases.append(f"APPROVE OVERWRITE: {display}")
            else:
                files_to_add.append(display)

        password_needed = bool(files_to_modify or any(self._is_protected_path(self._target_path(path)) for path in file_map))
        preview = InstallPreview(
            tool_name=schema.tool_name,
            files_to_add=files_to_add,
            files_to_modify=files_to_modify,
            permissions_requested=schema.permissions,
            risk_level=self._risk_level(schema, files_to_modify, forbidden),
            tests_to_run=schema.tests,
            password_approval_needed=password_needed,
            approval_phrases_required=sorted(set(approval_phrases)),
            forbidden=forbidden,
        )
        write_audit_event("plugin_install.preview_completed", preview.as_dict())
        return preview

    def apply_package(
        self,
        package_bytes: bytes,
        filename: str,
        admin_password_valid: bool = False,
        approval_text: str = "",
    ) -> dict[str, Any]:
        write_audit_event("plugin_install.apply_started", {"filename": filename})
        extracted = self._read_zip(package_bytes, filename)
        schema: PluginSchema = extracted["schema"]
        file_map: dict[Path, bytes] = extracted["file_map"]
        preview = self.preview_package(package_bytes, filename)

        if preview.forbidden:
            write_audit_event("plugin_install.refused", {"tool_name": schema.tool_name, "reasons": preview.forbidden})
            raise PluginInstallError("; ".join(preview.forbidden))

        if preview.password_approval_needed:
            if not admin_password_valid:
                raise PluginInstallError("Admin password is required for overwrite or protected core changes.")
            missing = [phrase for phrase in preview.approval_phrases_required if phrase not in approval_text]
            if missing:
                raise PluginInstallError(f"Missing approval phrase: {missing[0]}")

        backup_path = self._create_backup(schema.tool_name)
        write_audit_event("plugin_install.backup_created", {"tool_name": schema.tool_name, "backup": str(backup_path)})

        applied_targets: list[Path] = []
        try:
            for relative_path, content in file_map.items():
                target = self.root_dir / self._target_path(relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and not admin_password_valid:
                    raise PluginInstallError(f"Refusing overwrite without admin approval: {target}")
                target.write_bytes(content)
                applied_targets.append(target)

            test_result = self._run_tests(schema)
            if test_result != 0:
                raise PluginInstallError(f"Plugin tests failed with exit code {test_result}.")

            self._enable_plugin(schema.tool_name)
            write_audit_event("plugin_install.enabled", {"tool_name": schema.tool_name})
            return {"installed": True, "tool_name": schema.tool_name, "backup": str(backup_path)}
        except Exception as exc:
            self._rollback(schema.tool_name, backup_path)
            write_audit_event("plugin_install.rolled_back", {"tool_name": schema.tool_name, "reason": str(exc)})
            if isinstance(exc, PluginInstallError):
                raise
            raise PluginInstallError(str(exc)) from exc

    def _read_zip(self, package_bytes: bytes, filename: str) -> dict[str, Any]:
        if not filename.endswith(".zip"):
            raise PluginInstallError("Plugin package must be a .zip file.")
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / filename
            package_path.write_bytes(package_bytes)
            try:
                with zipfile.ZipFile(package_path) as archive:
                    names = [name for name in archive.namelist() if not name.endswith("/")]
                    _validate_archive_names(names)
                    schema_name = _find_schema_name(names)
                    schema = PluginSchema(**json.loads(archive.read(schema_name).decode("utf-8")))
                    file_map = self._build_file_map(archive, names, schema, schema_name)
            except zipfile.BadZipFile as exc:
                raise PluginInstallError("Plugin package is not a valid zip file.") from exc
        return {"schema": schema, "file_map": file_map}

    def _build_file_map(
        self,
        archive: zipfile.ZipFile,
        names: list[str],
        schema: PluginSchema,
        schema_name: str,
    ) -> dict[Path, bytes]:
        base_prefix = _base_prefix(schema_name)
        file_map: dict[Path, bytes] = {}
        for name in names:
            relative = Path(name)
            if base_prefix and relative.parts[: len(base_prefix.parts)] == base_prefix.parts:
                relative = Path(*relative.parts[len(base_prefix.parts) :])
            if relative == Path("."):
                continue

            if _is_repo_relative(relative):
                target = relative
            else:
                target = TOOLS_PATH / schema.tool_name / relative

            if target.parts[:3] == TOOLS_PATH.parts and target.parts[3] != schema.tool_name:
                raise PluginInstallError("Plugin package may only write inside its own plugin tool folder.")
            file_map[target] = archive.read(name)
        if TOOLS_PATH / schema.tool_name / "tool.schema.json" not in file_map:
            raise PluginInstallError("Plugin package must include tool.schema.json.")
        return file_map

    def _target_path(self, relative_path: Path) -> Path:
        return Path(relative_path.as_posix())

    def _is_protected_path(self, target: Path) -> bool:
        return any(target == protected or protected in target.parents for protected in PROTECTED_CORE_PATHS)

    def _is_delete_marker(self, relative_path: Path) -> bool:
        return relative_path.name.endswith(".delete")

    def _has_marker_blocks(self, content: bytes) -> bool:
        text = content.decode("utf-8", errors="ignore")
        return MARKER_START in text and MARKER_END in text

    def _risk_level(self, schema: PluginSchema, files_to_modify: list[str], forbidden: list[str]) -> str:
        if forbidden or schema.permissions == "dangerous":
            return "dangerous"
        if files_to_modify or schema.permissions == "medium":
            return "medium"
        return "safe"

    def _create_backup(self, tool_name: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        backup_path = self.backup_dir / f"{tool_name}-{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=False)
        target_plugin_dir = self.tools_dir / tool_name
        if target_plugin_dir.exists():
            shutil.copytree(target_plugin_dir, backup_path / "tool", dirs_exist_ok=True)
        if self.registry_path.exists():
            shutil.copy2(self.registry_path, backup_path / "registry.json")
        return backup_path

    def _run_tests(self, schema: PluginSchema) -> int:
        plugin_dir = self.tools_dir / schema.tool_name
        test_paths = [plugin_dir / test_path for test_path in schema.tests]
        for test_path in test_paths:
            if plugin_dir.resolve() not in test_path.resolve().parents:
                raise PluginInstallError("Plugin tests must stay inside the plugin directory.")
            if not test_path.exists():
                raise PluginInstallError(f"Plugin test file not found: {test_path}")
        write_audit_event("plugin_install.tests_started", {"tool_name": schema.tool_name, "tests": schema.tests})
        try:
            for test_path in test_paths:
                _run_test_file(test_path)
        except Exception as exc:
            write_audit_event(
                "plugin_install.tests_completed",
                {"tool_name": schema.tool_name, "exit_code": 1, "reason": str(exc)},
            )
            return 1
        write_audit_event("plugin_install.tests_completed", {"tool_name": schema.tool_name, "exit_code": 0})
        return 0

    def _enable_plugin(self, tool_name: str) -> None:
        data = {"plugins": []}
        if self.registry_path.exists():
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        plugins = {item["tool_name"]: item for item in data.get("plugins", [])}
        plugins[tool_name] = {"tool_name": tool_name, "enabled": True}
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps({"plugins": sorted(plugins.values(), key=lambda item: item["tool_name"])}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _rollback(self, tool_name: str, backup_path: Path) -> None:
        target_plugin_dir = self.tools_dir / tool_name
        failed_path = backup_path / "failed_install"
        if target_plugin_dir.exists():
            shutil.move(str(target_plugin_dir), str(failed_path))
        backup_tool = backup_path / "tool"
        if backup_tool.exists():
            shutil.copytree(backup_tool, target_plugin_dir, dirs_exist_ok=True)
        backup_registry = backup_path / "registry.json"
        if backup_registry.exists():
            shutil.copy2(backup_registry, self.registry_path)
        elif self.registry_path.exists():
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            data["plugins"] = [item for item in data.get("plugins", []) if item.get("tool_name") != tool_name]
            self.registry_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _validate_archive_names(names: list[str]) -> None:
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise PluginInstallError(f"Unsafe archive path: {name}")


def _find_schema_name(names: list[str]) -> str:
    matches = [name for name in names if Path(name).name == "tool.schema.json"]
    if len(matches) != 1:
        raise PluginInstallError("Plugin package must contain exactly one tool.schema.json file.")
    return matches[0]


def _base_prefix(schema_name: str) -> Path | None:
    parent = Path(schema_name).parent
    if parent == Path("."):
        return None
    return parent


def _is_repo_relative(path: Path) -> bool:
    if not path.parts:
        return False
    return path.parts[0] in {"backend", "frontend", "storage"}


def _run_test_file(test_path: Path) -> None:
    module_name = f"jarvis_plugin_test_{test_path.stem}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, test_path)
    if spec is None or spec.loader is None:
        raise PluginInstallError(f"Unable to load plugin test: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests = [getattr(module, name) for name in dir(module) if name.startswith("test_") and callable(getattr(module, name))]
    if not tests:
        raise PluginInstallError(f"No test functions found in {test_path}")
    for test in tests:
        test()
