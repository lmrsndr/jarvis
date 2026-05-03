from pathlib import Path
import importlib.util


def load_tool():
    tool_path = Path(__file__).resolve().parents[1] / "tool.py"
    spec = importlib.util.spec_from_file_location("filesystem_manager_tool", tool_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rejects_outside_projects():
    tool = load_tool()
    result = tool.run({"action": "list", "path": "/etc"})
    assert "error" in result
    assert "outside allowed root" in result["error"]


def test_unknown_action_rejected():
    tool = load_tool()
    result = tool.run({"action": "format_disk", "path": "Jarvis"})
    assert "error" in result
    assert "allowed_actions" in result


def test_dangerous_action_requires_confirmation():
    tool = load_tool()
    result = tool.run({"action": "delete", "path": "Jarvis/something.txt"})
    assert "error" in result
    assert "admin_confirmed" in result["error"]
