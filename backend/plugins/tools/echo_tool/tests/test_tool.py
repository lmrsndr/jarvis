from __future__ import annotations

import importlib.util
from pathlib import Path


TOOL_PATH = Path(__file__).resolve().parents[1] / "tool.py"
SPEC = importlib.util.spec_from_file_location("echo_tool", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_echo_tool_returns_text() -> None:
    assert MODULE.run({"text": "hello"}) == {"text": "hello"}
