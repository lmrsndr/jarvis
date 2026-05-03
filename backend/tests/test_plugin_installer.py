from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from plugins.installer import PluginInstallError, PluginInstaller


def test_valid_plugin_install(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip("valid_tool")

    preview = installer.preview_package(package, "valid_tool.zip")
    assert preview.tool_name == "valid_tool"
    assert preview.risk_level == "safe"
    assert preview.password_approval_needed is False

    result = installer.apply_package(package, "valid_tool.zip")
    assert result["installed"] is True
    assert (tmp_path / "backend/plugins/tools/valid_tool/tool.py").exists()
    registry = json.loads((tmp_path / "backend/plugins/registry.json").read_text(encoding="utf-8"))
    assert {"tool_name": "valid_tool", "enabled": True} in registry["plugins"]


def test_preview_does_not_apply_files_or_update_registry(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip("preview_only_tool")

    preview = installer.preview_package(package, "preview_only_tool.zip")

    assert preview.tool_name == "preview_only_tool"
    assert not (tmp_path / "backend/plugins/tools/preview_only_tool/tool.py").exists()
    registry = json.loads((tmp_path / "backend/plugins/registry.json").read_text(encoding="utf-8"))
    assert registry == {"plugins": []}


def test_invalid_schema_refusal(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip("invalid_tool", schema_overrides={"description": None})

    with pytest.raises(Exception):
        installer.preview_package(package, "invalid_tool.zip")


def test_overwrite_refusal(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip("same_tool")
    installer.apply_package(package, "same_tool.zip")

    with pytest.raises(PluginInstallError, match="Admin password"):
        installer.apply_package(package, "same_tool.zip")


def test_core_modification_refusal(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip(
        "core_tool",
        extra_files={"backend/core/config.py": b"# unsafe core replacement\n"},
    )

    preview = installer.preview_package(package, "core_tool.zip")
    assert preview.forbidden
    with pytest.raises(PluginInstallError, match="Protected file missing marker blocks"):
        installer.apply_package(package, "core_tool.zip", admin_password_valid=True, approval_text="APPROVE CORE CHANGE: config.py")


def test_delete_marker_is_refused(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip(
        "delete_tool",
        extra_files={"backend/plugins/tools/delete_tool/old_file.delete": b""},
    )

    preview = installer.preview_package(package, "delete_tool.zip")
    assert preview.risk_level == "dangerous"
    assert any("Deletion is not supported" in item for item in preview.forbidden)
    with pytest.raises(PluginInstallError, match="Deletion is not supported"):
        installer.apply_package(
            package,
            "delete_tool.zip",
            admin_password_valid=True,
            approval_text="APPROVE DELETE: backend/plugins/tools/delete_tool/old_file.delete",
        )


def test_failed_test_rollback(tmp_path: Path) -> None:
    installer = _installer(tmp_path)
    package = _plugin_zip("bad_test_tool", failing_test=True)

    with pytest.raises(PluginInstallError, match="Plugin tests failed"):
        installer.apply_package(package, "bad_test_tool.zip")

    assert not (tmp_path / "backend/plugins/tools/bad_test_tool/tool.py").exists()
    registry = json.loads((tmp_path / "backend/plugins/registry.json").read_text(encoding="utf-8"))
    assert all(item["tool_name"] != "bad_test_tool" for item in registry["plugins"])
    backups = list((tmp_path / "storage/backups/plugins").glob("bad_test_tool-*"))
    assert backups
    assert (backups[0] / "failed_install").exists()


def _installer(root: Path) -> PluginInstaller:
    (root / "backend/plugins/tools").mkdir(parents=True)
    (root / "backend/plugins").mkdir(parents=True, exist_ok=True)
    (root / "backend/plugins/registry.json").write_text('{"plugins": []}\n', encoding="utf-8")
    return PluginInstaller(root)


def _plugin_zip(
    tool_name: str,
    schema_overrides: dict | None = None,
    extra_files: dict[str, bytes] | None = None,
    failing_test: bool = False,
) -> bytes:
    schema = {
        "tool_name": tool_name,
        "version": "0.1.0",
        "description": "Test plugin.",
        "entry_file": "tool.py",
        "entry_function": "run",
        "permissions": "safe",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "allowed_changes": [],
        "forbidden_actions": [],
        "requires_password_for": [],
        "tests": ["tests/test_tool.py"],
        "enabled": True,
    }
    if schema_overrides:
        schema.update(schema_overrides)

    test_assertion = (
        "raise AssertionError('forced failure')"
        if failing_test
        else f"assert MODULE.run({{'text': 'ok'}}) == {{'text': 'ok'}}"
    )
    test_file = f"""
from __future__ import annotations
import importlib.util
from pathlib import Path
TOOL_PATH = Path(__file__).resolve().parents[1] / "tool.py"
SPEC = importlib.util.spec_from_file_location("{tool_name}", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
def test_tool():
    {test_assertion}
""".lstrip()
    tool_file = f'''
from __future__ import annotations
PLUGIN_NAME = "{tool_name}"
PLUGIN_DESCRIPTION = "Test plugin."
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "safe"
def run(args: dict) -> dict:
    return {{"text": str(args.get("text", ""))}}
'''.lstrip()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("tool.schema.json", json.dumps(schema))
        archive.writestr("tool.py", tool_file)
        archive.writestr("README.md", f"# {tool_name}\n")
        archive.writestr("tests/test_tool.py", test_file)
        for name, content in (extra_files or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()
