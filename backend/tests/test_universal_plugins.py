from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import ROOT_DIR
from plugins.loader import MASTER_SCHEMA_PATH, PluginLoader
from plugins.universal import PermissionEngine, UniversalIntentRouter


def test_loader_tracks_ready_and_invalid_plugins(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text('{"plugins": []}\n', encoding="utf-8")

    _write_plugin(tools_dir / "valid_tool", name="valid_tool", include_sidecars=True)
    _write_plugin(tools_dir / "invalid_tool", name="invalid_tool", include_sidecars=False)

    loader = PluginLoader(registry_path=registry_path, tools_dir=tools_dir, master_schema_path=MASTER_SCHEMA_PATH)
    records = loader.discover_records()

    assert records["valid_tool"].status == "ready"
    assert records["invalid_tool"].status == "invalid"
    assert "valid_tool" in loader.ready_plugins()
    assert "invalid_tool" in loader.invalid_plugins()


def test_universal_router_pauses_for_missing_required_input() -> None:
    route = UniversalIntentRouter(
        [
            {
                "tool_name": "code_debugger",
                "enabled": True,
                "status": "ready",
                "intents": ["audit a local code project"],
                "execution_mode": "actuate",
                "risk_level": "medium",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["audit"]},
                        "project_path": {"type": "string"},
                    },
                    "required": ["action", "project_path"],
                },
            }
        ]
    ).route("Audit a local code project")

    assert route.use_tool is False
    assert route.needs_clarification is True
    assert route.missing_fields == ["project_path"]
    assert "project_path" in route.clarification


def test_permission_engine_blocks_core_python_rewrite() -> None:
    plugin = {
        "tool_name": "code_debugger",
        "risk_level": "medium",
        "declared_permissions": {"filesystem_write": True},
    }

    with pytest.raises(PermissionError, match="core Python code"):
        PermissionEngine.assert_allowed(
            plugin,
            {
                "action": "apply_fix",
                "project_path": str(ROOT_DIR),
                "target_file": "backend/core/assistant.py",
                "approval_text": "APPROVE ACTION: code_debugger apply_fix",
            },
            confirmed=True,
        )


def _write_plugin(plugin_dir: Path, *, name: str, include_sidecars: bool) -> None:
    plugin_dir.mkdir(parents=True)
    schema = {
        "name": name,
        "tool_name": name,
        "version": "0.1.0",
        "description": "Test plugin.",
        "intents": ["test plugin"],
        "execution_mode": "direct_answer",
        "risk_level": "safe",
        "entry_file": "tool.py",
        "entry_function": "run",
        "permissions": "safe",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
    (plugin_dir / "tool.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (plugin_dir / "tool.py").write_text("def run(args):\n    return {'text': args.get('text', '')}\n", encoding="utf-8")
    if include_sidecars:
        (plugin_dir / "permissions.json").write_text('{"network": false}\n', encoding="utf-8")
        (plugin_dir / "examples.json").write_text('{"examples": [{"prompt": "test", "args": {"text": "test"}}]}\n', encoding="utf-8")
