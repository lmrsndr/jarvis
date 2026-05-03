from __future__ import annotations


PLUGIN_NAME = "echo_tool"
PLUGIN_DESCRIPTION = "Return supplied text unchanged."
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "safe"


def run(args: dict) -> dict:
    return {"text": str(args.get("text", ""))}
