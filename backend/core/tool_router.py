from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from plugins.universal import UniversalIntentRouter


PROJECTS_PATH = "~/Projects"
JARVIS_PROJECT_PATH = "~/Projects/Jarvis"
DEFAULT_TREE_DEPTH = 4
DESTRUCTIVE_ACTIONS = {"delete", "overwrite_file", "rename"}

TREE_KEYWORDS = ("tree", "directory tree", "folder structure", "project structure", "file structure", "diagram")
LIST_KEYWORDS = ("list files", "show files", "what files", "what is inside", "what's inside")
READ_KEYWORDS = ("read file", "open file", "show file", "read ", "open ")
CREATE_FILE_KEYWORDS = (
    "create file",
    "create a file",
    "create txt file",
    "create a txt file",
    "create text file",
    "create a text file",
    "make file",
    "new file",
    "save file",
)
CREATE_FOLDER_KEYWORDS = ("create folder", "create a folder", "make folder", "new folder", "create directory")
APPEND_KEYWORDS = ("append", "add this to file")
RENAME_KEYWORDS = ("rename", "rename file")
OVERWRITE_KEYWORDS = ("overwrite", "replace file contents")
DELETE_KEYWORDS = ("delete", "remove", "delete file", "remove file")
WEB_KEYWORDS = (
    "weather",
    "forecast",
    "temperature",
    "rain",
    "wind",
    "news",
    "latest",
    "today",
    "current",
    "results",
    "scores",
    "fixtures",
    "match",
    "football",
    "premier league",
)
CREATIVE_BYPASS_KEYWORDS = ("invent", "imagine", "design", "suggest", "example", "possible")
ECHO_KEYWORDS = ("echo", "test echo", "test plugin", "echo_tool")
FILESYSTEM_CONTEXT_KEYWORDS = (
    "tree",
    "folder",
    "directory",
    "file structure",
    "project structure",
    "list files",
    "show files",
    "what files",
    "what is inside",
    "what's inside",
    "home/project",
    "home/projects",
    "~/project",
    "~/projects",
    "projects folder",
    "jarvis project",
)


def route_tool_request(
    message: str,
    enabled_plugins: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize(message)
    plugins = {
        str(plugin.get("tool_name", "")).strip()
        for plugin in enabled_plugins
        if plugin.get("enabled", True)
    }

    if _is_echo_request(normalized):
        if "echo_tool" not in plugins:
            return _missing_tool("echo_tool", "User asked to echo or test a plugin.")
        return _route(True, "echo_tool", {"text": message}, "User asked to echo or test a plugin.")

    if _is_creative_filesystem_request(normalized):
        return _route(False, reason="General knowledge request.")

    action = _filesystem_action(normalized)
    if action:
        if "filesystem_manager" not in plugins:
            return _missing_tool("filesystem_manager", "User asked for local filesystem access.")
        args, blocked_reason = _filesystem_args(message, normalized, action, context or {})
        if blocked_reason:
            return _route(
                False,
                "filesystem_manager",
                args,
                blocked_reason,
                requires_tool=True,
                blocked=True,
            )
        route = _route(
            True,
            "filesystem_manager",
            args,
            _filesystem_reason(action),
            requires_confirmation=action in DESTRUCTIVE_ACTIONS,
        )
        if action in DESTRUCTIVE_ACTIONS:
            route["approval_phrase"] = _approval_phrase(action, str(args["path"]))
        return route

    if _is_web_request(normalized):
        if "web_search" not in plugins:
            return _missing_tool("web_search", "User asked for current, live, recent, or web information.")
        return _route(
            True,
            "web_search",
            {"query": message, "max_results": 5},
            "User asked for current, live, recent, or web information.",
        )

    universal_route = UniversalIntentRouter(enabled_plugins).route(message).as_dict()
    if universal_route["use_tool"] or universal_route.get("needs_clarification"):
        return universal_route

    return _route(False, reason="General knowledge request.")


def _route(
    use_tool: bool,
    tool_name: str | None = None,
    args: dict[str, Any] | None = None,
    reason: str = "",
    requires_tool: bool = False,
    missing_tool: str | None = None,
    requires_confirmation: bool = False,
    blocked: bool = False,
) -> dict[str, Any]:
    return {
        "use_tool": use_tool,
        "tool_name": tool_name,
        "args": args or {},
        "reason": reason,
        "requires_tool": requires_tool,
        "missing_tool": missing_tool,
        "requires_confirmation": requires_confirmation,
        "blocked": blocked,
    }


def _missing_tool(tool_name: str, reason: str) -> dict[str, Any]:
    return _route(False, reason=reason, requires_tool=True, missing_tool=tool_name)


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", message.strip().lower())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_echo_request(normalized: str) -> bool:
    return _contains_any(normalized, ECHO_KEYWORDS)


def _is_web_request(normalized: str) -> bool:
    return _contains_any(normalized, WEB_KEYWORDS)


def _is_creative_filesystem_request(normalized: str) -> bool:
    return _contains_any(normalized, CREATIVE_BYPASS_KEYWORDS) and _contains_any(normalized, FILESYSTEM_CONTEXT_KEYWORDS)


def _filesystem_action(normalized: str) -> str | None:
    if _contains_any(normalized, DELETE_KEYWORDS):
        return "delete"
    if _contains_any(normalized, OVERWRITE_KEYWORDS):
        return "overwrite_file"
    if _contains_any(normalized, RENAME_KEYWORDS):
        return "rename"
    if _contains_any(normalized, APPEND_KEYWORDS):
        return "append_file"
    if _contains_any(normalized, CREATE_FOLDER_KEYWORDS):
        return "create_folder"
    if _contains_any(normalized, CREATE_FILE_KEYWORDS):
        return "create_file"
    if _contains_any(normalized, READ_KEYWORDS) and (_extract_filename(normalized) or "jarvis project" in normalized):
        return "read"
    if _contains_any(normalized, LIST_KEYWORDS):
        return "list"
    if _contains_any(normalized, TREE_KEYWORDS):
        return "tree"
    if _contains_any(normalized, FILESYSTEM_CONTEXT_KEYWORDS):
        return "list"
    return None


def _filesystem_args(
    message: str,
    normalized: str,
    action: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    path = _resolve_filesystem_path(message, normalized, action, context)
    if _path_escapes_projects(path):
        return {"action": action, "path": path}, "Refused filesystem request because the path is outside ~/Projects."

    args: dict[str, Any] = {"action": action, "path": path}
    if action == "tree":
        args["max_depth"] = DEFAULT_TREE_DEPTH
    if action in {"create_file", "append_file", "overwrite_file"}:
        args["content"] = _extract_content(message)
    return args, None


def _resolve_filesystem_path(message: str, normalized: str, action: str, context: dict[str, Any]) -> str:
    explicit_path = _extract_explicit_path(message)
    filename = _extract_named_file(message, normalized, action) or _extract_filename(message)

    if explicit_path:
        path = _normalize_project_path(explicit_path)
        if _is_projects_root(path) and ("jarvis project" in normalized or "jarvis project folder" in normalized):
            path = JARVIS_PROJECT_PATH
        if _is_projects_root(path) and filename:
            return str(PurePosixPath(path) / filename)
        return _ensure_txt_extension(path, normalized, action)

    if "jarvis project" in normalized or "jarvis project folder" in normalized:
        base = JARVIS_PROJECT_PATH
    elif filename and filename.lower() == "jarvis.txt" and _recent_context_is_jarvis(context):
        base = JARVIS_PROJECT_PATH
    elif action in {"read", "delete", "rename", "overwrite_file"} and filename:
        base = JARVIS_PROJECT_PATH if filename.lower() == "jarvis.txt" else PROJECTS_PATH
    else:
        base = PROJECTS_PATH

    if filename:
        return str(PurePosixPath(base) / filename)
    if action in {"tree", "list"}:
        return JARVIS_PROJECT_PATH if "jarvis" in normalized else PROJECTS_PATH
    return base


def _normalize_project_path(path: str) -> str:
    value = path.strip().rstrip(".?!")
    value = re.sub(r"^Home/Projects?\s+folder$", PROJECTS_PATH, value, flags=re.IGNORECASE)
    value = re.sub(r"^~/?Project(/|$)", "~/Projects/", value, flags=re.IGNORECASE)
    value = re.sub(r"^~/?Projects(/|$)", "~/Projects/", value, flags=re.IGNORECASE)
    value = re.sub(r"^Home/Project(/|$)", "~/Projects/", value, flags=re.IGNORECASE)
    value = re.sub(r"^Home/Projects(/|$)", "~/Projects/", value, flags=re.IGNORECASE)
    value = re.sub(r"^my Home/Projects? folder$", PROJECTS_PATH, value, flags=re.IGNORECASE)
    value = value.rstrip("/")
    return value or PROJECTS_PATH


def _extract_explicit_path(message: str) -> str | None:
    path_pattern = re.compile(
        r"(~/?Projects?(?:/[^\s,;:]+)?|(?:my\s+)?Home/Projects?(?:\s+folder)?(?:/[^\s,;:]+)?|/[^\s,;:]+|\.\./[^\s,;:]+)",
        flags=re.IGNORECASE,
    )
    match = path_pattern.search(message)
    if not match:
        if re.search(r"\bProjects?\s+folder\b", message, flags=re.IGNORECASE):
            return PROJECTS_PATH
        return None
    return re.sub(r"^my\s+", "", match.group(1).strip(), flags=re.IGNORECASE)


def _extract_named_file(message: str, normalized: str, action: str) -> str | None:
    patterns = (
        r"\bnamed\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
        r"\bcalled\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
        r"\b(?:delete|remove|read|open|append|overwrite)\s+['\"]?([A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,12})['\"]?",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return _ensure_txt_extension(match.group(1), normalized, action)
    return None


def _extract_filename(message: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,12})", message)
    if not match:
        return None
    return match.group(1)


def _ensure_txt_extension(path_or_name: str, normalized: str, action: str) -> str:
    if action not in {"create_file", "append_file", "overwrite_file"}:
        return path_or_name
    if ("txt file" not in normalized and "text file" not in normalized) or "." in PurePosixPath(path_or_name).name:
        return path_or_name
    return f"{path_or_name}.txt"


def _extract_content(message: str) -> str:
    quoted = re.search(r"['\"](.+?)['\"]", message)
    if quoted:
        return quoted.group(1)
    return ""


def _is_projects_root(path: str) -> bool:
    return path.rstrip("/").lower() in {"~/projects", "~/project"}


def _recent_context_is_jarvis(context: dict[str, Any]) -> bool:
    values = " ".join(str(value).lower() for value in context.values())
    return "jarvis" in values


def _path_escapes_projects(path: str) -> bool:
    if ".." in PurePosixPath(path).parts:
        return True
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        root = (Path.home() / "Projects").resolve(strict=False)
        resolved = expanded.resolve(strict=False)
        return resolved != root and root not in resolved.parents
    return not (path == PROJECTS_PATH or path == JARVIS_PROJECT_PATH or path.startswith("~/Projects/"))


def _approval_phrase(action: str, path: str) -> str:
    resolved = _absolute_projects_path(path)
    if action == "delete":
        return f"APPROVE DELETE: {resolved}"
    if action == "overwrite_file":
        return f"APPROVE OVERWRITE: {resolved}"
    return f"APPROVE RENAME: {resolved}"


def _absolute_projects_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _filesystem_reason(action: str) -> str:
    reasons = {
        "tree": "User asked for project directory tree.",
        "list": "User asked to list files or folders.",
        "read": "User asked to read a file.",
        "create_file": "User asked to create a file.",
        "create_folder": "User asked to create a folder.",
        "append_file": "User asked to append to a file.",
        "overwrite_file": "User asked to overwrite file contents.",
        "rename": "User asked to rename a file.",
        "delete": "User asked to delete a file.",
    }
    return reasons.get(action, "User asked for filesystem access.")
