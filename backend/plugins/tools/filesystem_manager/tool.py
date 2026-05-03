from __future__ import annotations

import fnmatch
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

PLUGIN_NAME = "filesystem_manager"
PLUGIN_DESCRIPTION = "Safely list, read, search, create and manage files under ~/Projects. Destructive actions require host-verified admin confirmation and exact approval text."
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "medium"

ALLOWED_ROOT = Path.home() / "Projects"
MAX_READ_BYTES = 250_000
MAX_SEARCH_BYTES = 500_000
MAX_DEPTH_CAP = 8

EXCLUDED_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}

DANGEROUS_ACTIONS = {"overwrite_file", "rename", "delete"}
MEDIUM_ACTIONS = {"create_file", "create_folder", "append_file"}
SAFE_ACTIONS = {"list", "tree", "read", "search_names", "search_text", "info"}
ALL_ACTIONS = SAFE_ACTIONS | MEDIUM_ACTIONS | DANGEROUS_ACTIONS


def _allowed_root() -> Path:
    return ALLOWED_ROOT.expanduser().resolve()


def _resolve_safe(path_value: str | None) -> Path:
    if not path_value:
        raise ValueError("Missing path.")

    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = _allowed_root() / path

    resolved = path.resolve(strict=False)
    root = _allowed_root()

    if resolved != root and root not in resolved.parents:
        raise PermissionError(f"Path is outside allowed root: {root}")

    return resolved


def _reject_symlink_escape(path: Path) -> None:
    root = _allowed_root()
    current = path
    while current != current.parent:
        if current.exists() and current.is_symlink():
            target = current.resolve()
            if target != root and root not in target.parents:
                raise PermissionError(f"Symlink escapes allowed root: {current}")
        if current == root:
            break
        current = current.parent


def _approval_required(action: str, path: Path, args: dict[str, Any]) -> None:
    if action not in DANGEROUS_ACTIONS:
        return

    approval_text = str(args.get("approval_text") or "").strip()
    admin_confirmed = bool(args.get("admin_confirmed"))

    if not admin_confirmed:
        raise PermissionError("Dangerous action requires admin_confirmed=true. The host app should only pass this after admin password verification.")

    if action == "delete":
        expected = f"APPROVE DELETE: {path}"
    elif action == "overwrite_file":
        expected = f"APPROVE OVERWRITE: {path}"
    elif action == "rename":
        destination = _resolve_safe(str(args.get("destination", "")))
        expected = f"APPROVE RENAME: {path} -> {destination}"
    else:
        expected = ""

    if approval_text != expected:
        raise PermissionError(f"Approval phrase mismatch. Required exactly: {expected}")


def _backup_path(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = _allowed_root() / ".jarvis_backups" / timestamp
    relative = path.relative_to(_allowed_root())
    return backup_root / relative


def _backup_existing(path: Path) -> str | None:
    if not path.exists():
        return None
    backup = _backup_path(path)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, backup, symlinks=False)
    else:
        shutil.copy2(path, backup)
    return str(backup)


def _entry_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "type": "directory" if path.is_dir() else "file",
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def _list(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"Path does not exist: {path}"}
    if not path.is_dir():
        return {"error": f"Path is not a directory: {path}"}

    entries = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name in EXCLUDED_NAMES:
            continue
        entries.append(_entry_info(entry))
    return {"path": str(path), "entries": entries}


def _tree_lines(path: Path, max_depth: int, prefix: str = "", depth: int = 0) -> list[str]:
    if depth >= max_depth:
        return []
    try:
        entries = [entry for entry in path.iterdir() if entry.name not in EXCLUDED_NAMES]
        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return [f"{prefix}[permission denied]"]

    lines: list[str] = []
    for index, entry in enumerate(entries):
        connector = "└── " if index == len(entries) - 1 else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir() and not entry.is_symlink():
            extension = "    " if index == len(entries) - 1 else "│   "
            lines.extend(_tree_lines(entry, max_depth, prefix + extension, depth + 1))
    return lines


def _tree(path: Path, max_depth: int) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"Path does not exist: {path}"}
    if not path.is_dir():
        return {"error": f"Path is not a directory: {path}"}
    max_depth = max(1, min(int(max_depth), MAX_DEPTH_CAP))
    lines = [str(path)] + _tree_lines(path, max_depth=max_depth)
    return {"path": str(path), "max_depth": max_depth, "tree": "\n".join(lines)}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"Path does not exist: {path}"}
    if not path.is_file():
        return {"error": f"Path is not a file: {path}"}
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        return {"error": f"File is too large to read safely ({size} bytes). Limit is {MAX_READ_BYTES} bytes."}
    return {"path": str(path), "content": path.read_text(encoding="utf-8", errors="replace"), "size": size}


def _search_names(path: Path, pattern: str) -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        return {"error": f"Search path is not a directory: {path}"}
    matches = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_NAMES]
        for name in dirs + files:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                matches.append(str(Path(root) / name))
    return {"path": str(path), "pattern": pattern, "matches": matches[:200], "truncated": len(matches) > 200}


def _search_text(path: Path, query: str) -> dict[str, Any]:
    if not query:
        return {"error": "Missing query."}
    if not path.exists() or not path.is_dir():
        return {"error": f"Search path is not a directory: {path}"}

    results = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_NAMES]
        for filename in files:
            file_path = Path(root) / filename
            try:
                if file_path.stat().st_size > MAX_SEARCH_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if query.lower() in line.lower():
                    results.append({"path": str(file_path), "line": line_no, "text": line[:300]})
                    if len(results) >= 200:
                        return {"path": str(path), "query": query, "matches": results, "truncated": True}
    return {"path": str(path), "query": query, "matches": results, "truncated": False}


def _create_file(path: Path, content: str, overwrite: bool = False) -> dict[str, Any]:
    if path.exists() and not overwrite:
        return {"error": f"File already exists: {path}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"created": str(path), "bytes": len(content.encode("utf-8"))}


def _create_folder(path: Path) -> dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    return {"created": str(path)}


def _append_file(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)
    return {"appended": str(path), "bytes": len(content.encode("utf-8"))}


def _overwrite_file(path: Path, content: str) -> dict[str, Any]:
    backup = _backup_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"overwritten": str(path), "backup": backup, "bytes": len(content.encode("utf-8"))}


def _rename(path: Path, destination: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"Source does not exist: {path}"}
    if destination.exists():
        return {"error": f"Destination already exists: {destination}"}
    backup = _backup_existing(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    path.rename(destination)
    return {"renamed_from": str(path), "renamed_to": str(destination), "backup": backup}


def _delete(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": f"Path does not exist: {path}"}
    backup = _backup_existing(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {"deleted": str(path), "backup": backup}


def run(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "")).strip()
    if action not in ALL_ACTIONS:
        return {"error": f"Unknown or missing action: {action}", "allowed_actions": sorted(ALL_ACTIONS)}

    try:
        path = _resolve_safe(str(args.get("path", "")))
        _reject_symlink_escape(path)
        _approval_required(action, path, args)

        if action == "list":
            return _list(path)
        if action == "tree":
            return _tree(path, int(args.get("max_depth", 4)))
        if action == "read":
            return _read(path)
        if action == "info":
            if not path.exists():
                return {"error": f"Path does not exist: {path}"}
            return _entry_info(path)
        if action == "search_names":
            return _search_names(path, str(args.get("pattern", "*")))
        if action == "search_text":
            return _search_text(path, str(args.get("query", "")))
        if action == "create_file":
            return _create_file(path, str(args.get("content", "")), overwrite=False)
        if action == "create_folder":
            return _create_folder(path)
        if action == "append_file":
            return _append_file(path, str(args.get("content", "")))
        if action == "overwrite_file":
            return _overwrite_file(path, str(args.get("content", "")))
        if action == "rename":
            destination = _resolve_safe(str(args.get("destination", "")))
            _reject_symlink_escape(destination)
            return _rename(path, destination)
        if action == "delete":
            return _delete(path)
    except Exception as exc:  # Keep plugin failures as structured responses.
        return {"error": str(exc), "action": action}

    return {"error": "Unhandled action."}
