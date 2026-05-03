"""
code_debugger Jarvis plugin

Purpose:
- Read/audit projects under /home/s-ndrlm-r/Projects
- Map frontend/backend/API relationships
- Propose safe fixes
- Apply limited fixes only when confirmation == "OK"
- Delete files only when confirmation == "OK"

Expected entrypoint:
    run(args: dict) -> dict
"""

from __future__ import annotations

import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ALLOWED_ROOT = Path("/home/s-ndrlm-r/Projects").resolve()
CONFIRMATION_PHRASE = "OK"
MAX_FILE_BYTES = 2_000_000
MAX_READ_FILE_BYTES = 300_000

TEXT_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".html", ".css", ".scss",
    ".json", ".md", ".py", ".yml", ".yaml", ".env", ".example",
    ".txt", ".mjs", ".cjs", ".sql", ".sh", ".xml", ".toml",
}

FRONTEND_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".vue", ".html"}
BACKEND_EXTENSIONS = {".js", ".ts", ".mjs", ".cjs", ".py"}

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", "coverage", "__pycache__",
    ".venv", "venv", "env", ".cache", ".pytest_cache", ".mypy_cache",
    "target", ".turbo", ".parcel-cache", "vendor",
}

IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
}

@dataclass
class Issue:
    id: str
    severity: str
    category: str
    title: str
    detail: str
    file: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    proposed_fix: Optional[Dict[str, Any]] = None


def _now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_project_path(project_path: str) -> Path:
    if not project_path:
        raise ValueError("Missing required argument: project_path")

    path = Path(project_path).expanduser().resolve()
    if not str(path).startswith(str(ALLOWED_ROOT) + os.sep) and path != ALLOWED_ROOT:
        raise ValueError(f"Refusing access outside allowed root: {ALLOWED_ROOT}")
    if not path.exists():
        raise ValueError(f"Project path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Project path is not a directory: {path}")
    return path


def _safe_target_path(project: Path, target_file: str) -> Path:
    if not target_file:
        raise ValueError("Missing target_file")
    target = (project / target_file).resolve()
    if not str(target).startswith(str(project) + os.sep) and target != project:
        raise ValueError("Refusing access outside selected project")
    if not str(target).startswith(str(ALLOWED_ROOT) + os.sep):
        raise ValueError("Refusing access outside allowed root")
    return target


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts) or path.name in IGNORE_FILES


def _is_probably_text(path: Path) -> bool:
    if path.name.startswith(".env"):
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


def _iter_project_files(project: Path, extensions: Optional[Set[str]] = None) -> Iterable[Path]:
    for path in project.rglob("*"):
        if _is_ignored(path):
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        if extensions and path.suffix.lower() not in extensions:
            continue
        if not extensions and not _is_probably_text(path):
            continue
        yield path


def _rel(project: Path, path: Path) -> str:
    return str(path.relative_to(project))


def _read_text(path: Path, max_bytes: int = MAX_FILE_BYTES) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _write_text_with_backup(path: Path, new_text: str) -> Dict[str, str]:
    backup = path.with_suffix(path.suffix + f".bak-{_now_stamp()}")
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8")
    return {"file": str(path), "backup": str(backup)}


def _make_diff(old: str, new: str, file_label: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{file_label}",
        tofile=f"b/{file_label}",
    ))


def _find_frontend_routes(text: str) -> Set[str]:
    patterns = [
        r'path\s*:\s*[\'\"`]([^\'\"`]+)[\'\"`]',
        r'<Route[^>]+path=[\'\"`]([^\'\"`]+)[\'\"`]',
        r'\bto=[\'\"`]([^\'\"`]+)[\'\"`]',
        r'\bhref=[\'\"`]([^\'\"`]+)[\'\"`]',
    ]
    out: Set[str] = set()
    for pattern in patterns:
        out.update(re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL))
    return {x for x in out if x and not x.startswith("#") and not x.startswith("mailto:")}


def _find_backend_routes(text: str) -> List[Dict[str, str]]:
    routes: List[Dict[str, str]] = []
    express_patterns = [
        r'\bapp\.(get|post|put|patch|delete)\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]',
        r'\brouter\.(get|post|put|patch|delete)\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]',
    ]
    for pattern in express_patterns:
        for method, route in re.findall(pattern, text, flags=re.IGNORECASE):
            routes.append({"method": method.upper(), "route": route})

    flask_fastapi_patterns = [
        r'@(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]',
        r'@(app|router)\.route\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`].*?methods\s*=\s*\[([^\]]+)\]',
    ]
    for pattern in flask_fastapi_patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            if len(match) == 2:
                method, route = match
                routes.append({"method": method.upper(), "route": route})
            elif len(match) == 3:
                _, route, methods_blob = match
                methods = re.findall(r'[\'\"]([A-Z]+)[\'\"]', methods_blob, flags=re.IGNORECASE)
                for method in methods or ["GET"]:
                    routes.append({"method": method.upper(), "route": route})
    return routes


def _find_api_calls(text: str) -> List[Dict[str, str]]:
    calls: List[Dict[str, str]] = []
    patterns = [
        ("FETCH", r'fetch\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]'),
        ("AXIOS", r'axios\.(get|post|put|patch|delete)\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]'),
        ("CLIENT", r'\bapi\.(get|post|put|patch|delete)\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]'),
    ]
    for kind, pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            if isinstance(match, tuple):
                method = match[0].upper() if match[0].lower() in {"get", "post", "put", "patch", "delete"} else "UNKNOWN"
                url = match[-1]
            else:
                method = "UNKNOWN"
                url = match
            calls.append({"method": method, "url": url, "kind": kind})
    return calls


def _find_buttons_and_forms(text: str) -> Tuple[List[str], List[str]]:
    buttons: Set[str] = set()
    forms: Set[str] = set()

    for pattern in [r'<button[^>]*>(.*?)</button>', r'<Button[^>]*>(.*?)</Button>']:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            label = re.sub(r'<[^>]+>', '', raw)
            label = re.sub(r'\s+', ' ', label).strip()
            if label:
                buttons.add(label[:120])

    for attr in ["aria-label", "title"]:
        for value in re.findall(attr + r'=[\'\"`]([^\'\"`]+)[\'\"`]', text, flags=re.IGNORECASE):
            if value.strip():
                buttons.add(value.strip()[:120])

    if re.search(r'<form\b', text, flags=re.IGNORECASE):
        forms.add("HTML form")
    for marker in ["onSubmit", "handleSubmit", "@submit", "type=\"submit\"", "type='submit'"]:
        if marker in text:
            forms.add(marker)
    return sorted(buttons), sorted(forms)


def _find_imports(text: str, suffix: str) -> Set[str]:
    imports: Set[str] = set()
    if suffix == ".py":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        except SyntaxError:
            pass
    else:
        patterns = [
            r'import\s+.*?from\s+[\'\"`]([^\'\"`]+)[\'\"`]',
            r'import\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]\s*\)',
            r'require\s*\(\s*[\'\"`]([^\'\"`]+)[\'\"`]\s*\)',
        ]
        for pattern in patterns:
            imports.update(re.findall(pattern, text, flags=re.DOTALL))
    return imports


def _normalise_endpoint(value: str) -> str:
    value = value.strip()
    value = re.sub(r'^https?://[^/]+', '', value)
    value = value.split("?")[0]
    value = value.rstrip("/") or "/"
    return value


def _endpoint_matches(api_url: str, backend_route: str) -> bool:
    api = _normalise_endpoint(api_url)
    route = _normalise_endpoint(backend_route)
    if api == route:
        return True
    if route in api or api in route:
        # Avoid silly match on root
        return len(route) > 3 and len(api) > 3
    # Express params /api/users/:id compared against /api/users/123
    route_regex = re.escape(route)
    route_regex = route_regex.replace(re.escape(":id"), r"[^/]+")
    route_regex = re.sub(r'\\:[A-Za-z_][A-Za-z0-9_]*', r'[^/]+', route_regex)
    return re.fullmatch(route_regex, api) is not None


def _audit(project: Path) -> Dict[str, Any]:
    frontend_files: List[str] = []
    backend_files: List[str] = []
    frontend_routes: List[Dict[str, str]] = []
    backend_routes: List[Dict[str, str]] = []
    api_calls: List[Dict[str, str]] = []
    buttons: List[Dict[str, str]] = []
    forms: List[Dict[str, str]] = []
    imports: List[Dict[str, str]] = []
    issues: List[Issue] = []

    all_files = list(_iter_project_files(project))

    for path in all_files:
        text = _read_text(path)
        rel = _rel(project, path)
        suffix = path.suffix.lower()

        if suffix in FRONTEND_EXTENSIONS:
            frontend_files.append(rel)
            for route in _find_frontend_routes(text):
                frontend_routes.append({"file": rel, "route": route})
            for call in _find_api_calls(text):
                api_calls.append({"file": rel, **call})
            file_buttons, file_forms = _find_buttons_and_forms(text)
            buttons.extend({"file": rel, "label": x} for x in file_buttons)
            forms.extend({"file": rel, "form": x} for x in file_forms)

        if suffix in BACKEND_EXTENSIONS:
            routes = _find_backend_routes(text)
            if routes:
                backend_files.append(rel)
            for route in routes:
                backend_routes.append({"file": rel, **route})

        for imp in _find_imports(text, suffix):
            imports.append({"file": rel, "import": imp})
            if imp.startswith(".") or imp.startswith("/"):
                # Basic broken relative import check.
                candidates = []
                base = path.parent
                raw = imp
                if raw.startswith("/"):
                    candidate_base = project / raw.lstrip("/")
                else:
                    candidate_base = (base / raw).resolve()
                for ext in ["", ".js", ".jsx", ".ts", ".tsx", ".vue", ".py", "/index.js", "/index.ts", "/index.tsx"]:
                    candidates.append(Path(str(candidate_base) + ext))
                if not any(c.exists() for c in candidates):
                    issues.append(Issue(
                        id="",
                        severity="medium",
                        category="broken_import",
                        title="Possible broken relative import",
                        detail=f"Import '{imp}' in {rel} does not resolve to an obvious file.",
                        file=rel,
                        evidence={"import": imp},
                    ))

    backend_route_values = {x["route"] for x in backend_routes}
    api_call_values = {x["url"] for x in api_calls}

    for route in sorted(backend_route_values):
        if route.startswith("/api"):
            if not any(_endpoint_matches(api, route) for api in api_call_values):
                issues.append(Issue(
                    id="",
                    severity="medium",
                    category="unreached_backend_route",
                    title="Backend API route has no obvious frontend API call",
                    detail=f"Backend route '{route}' was found, but no matching frontend fetch/axios/api call was detected.",
                    evidence={"backend_route": route},
                    proposed_fix={
                        "type": "manual",
                        "summary": "Add a frontend route/button/form/API client call for this backend route, or confirm it is intentionally internal/admin-only."
                    }
                ))

    for call in api_calls:
        url = call["url"]
        if url.startswith("/api") and not any(_endpoint_matches(url, route) for route in backend_route_values):
            issues.append(Issue(
                id="",
                severity="high",
                category="missing_backend_route",
                title="Frontend API call has no obvious backend route",
                detail=f"Frontend calls '{url}' in {call['file']}, but no matching backend route was detected.",
                file=call["file"],
                evidence={"api_call": url},
                proposed_fix={
                    "type": "manual",
                    "summary": "Either correct the frontend API URL or add the missing backend route."
                }
            ))

    for link in frontend_routes:
        route = link["route"]
        if route.startswith("/") and not route.startswith("/api") and "." not in route:
            # Basic warning only, because SPA routes may be valid without a physical file.
            matching_route = any(r["route"] == route for r in frontend_routes if r["file"] != link["file"])
            if not matching_route and route not in {"/", "*"}:
                issues.append(Issue(
                    id="",
                    severity="low",
                    category="possibly_unregistered_frontend_link",
                    title="Frontend link may not point to a registered page route",
                    detail=f"'{route}' is referenced in {link['file']}, but no matching route declaration was obvious.",
                    file=link["file"],
                    evidence={"route": route},
                ))

    # Number issues after collection.
    issue_dicts: List[Dict[str, Any]] = []
    for idx, issue in enumerate(issues, start=1):
        issue.id = f"ISSUE-{idx:03d}"
        issue_dicts.append(asdict(issue))

    summary = {
        "project": str(project),
        "files_scanned": len(all_files),
        "frontend_files_count": len(frontend_files),
        "backend_files_with_routes_count": len(set(backend_files)),
        "frontend_routes_count": len(frontend_routes),
        "backend_routes_count": len(backend_routes),
        "api_calls_count": len(api_calls),
        "buttons_count": len(buttons),
        "forms_count": len(forms),
        "issues_count": len(issue_dicts),
    }

    return {
        "ok": True,
        "mode": "audit",
        "summary": summary,
        "frontend_files": sorted(frontend_files),
        "backend_files_with_routes": sorted(set(backend_files)),
        "frontend_routes": frontend_routes,
        "backend_routes": backend_routes,
        "api_calls": api_calls,
        "buttons": buttons,
        "forms": forms,
        "imports_sample": imports[:500],
        "issues": issue_dicts,
        "notes": [
            "This is a static audit. It flags likely issues but does not prove runtime behaviour.",
            "Use preview_fix before apply_fix. apply_fix and delete_file require confirmation exactly equal to OK.",
        ],
    }


def _preview_fix(project: Path, issue_id: str) -> Dict[str, Any]:
    audit = _audit(project)
    issue = next((x for x in audit["issues"] if x["id"] == issue_id), None)
    if not issue:
        return {"ok": False, "error": f"Issue not found: {issue_id}", "available_issue_ids": [x["id"] for x in audit["issues"]]}

    # Most fixes are deliberately manual in v1. This avoids unsafe hallucinated edits.
    return {
        "ok": True,
        "mode": "preview_fix",
        "issue": issue,
        "can_auto_apply": False,
        "diff": "",
        "recommendation": issue.get("proposed_fix", {}).get("summary") or "Review the file and apply a targeted code change manually.",
        "safety_note": "V1 does not auto-generate broad code rewrites. It audits and proposes where to fix. Add specific fix templates later for repeated project patterns.",
    }


def _apply_fix(project: Path, issue_id: str, confirmation: str) -> Dict[str, Any]:
    if confirmation != CONFIRMATION_PHRASE:
        return {
            "ok": False,
            "error": "Write permission denied. confirmation must be exactly OK.",
        }
    preview = _preview_fix(project, issue_id)
    if not preview.get("ok"):
        return preview
    if not preview.get("can_auto_apply"):
        return {
            "ok": False,
            "mode": "apply_fix",
            "error": "This issue has no safe automatic fix in v1. Use the preview recommendation and edit manually, or add a specific fix template.",
            "issue": preview.get("issue"),
        }
    return {"ok": False, "error": "No automatic fix templates are enabled yet."}


def _delete_file(project: Path, target_file: str, confirmation: str) -> Dict[str, Any]:
    if confirmation != CONFIRMATION_PHRASE:
        return {"ok": False, "error": "Delete permission denied. confirmation must be exactly OK."}
    target = _safe_target_path(project, target_file)
    if not target.exists():
        return {"ok": False, "error": f"Target file does not exist: {target_file}"}
    if not target.is_file():
        return {"ok": False, "error": "Refusing to delete anything that is not a file."}

    trash_dir = project / ".jarvis_trash" / _now_stamp()
    trash_dir.mkdir(parents=True, exist_ok=True)
    moved_to = trash_dir / target.name
    shutil.move(str(target), str(moved_to))
    return {
        "ok": True,
        "mode": "delete_file",
        "deleted": target_file,
        "moved_to": str(moved_to),
        "note": "File was moved to .jarvis_trash rather than permanently deleted.",
    }


def _read_file(project: Path, target_file: str) -> Dict[str, Any]:
    target = _safe_target_path(project, target_file)
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": f"File not found: {target_file}"}
    if not _is_probably_text(target):
        return {"ok": False, "error": "Refusing to read non-text/binary file."}
    text = _read_text(target, max_bytes=MAX_READ_FILE_BYTES)
    return {
        "ok": True,
        "mode": "read_file",
        "file": target_file,
        "truncated": target.stat().st_size > MAX_READ_FILE_BYTES,
        "content": text,
    }


def _list_tree(project: Path, max_files: int = 500) -> Dict[str, Any]:
    files = []
    for path in _iter_project_files(project):
        files.append(_rel(project, path))
        if len(files) >= max_files:
            break
    return {
        "ok": True,
        "mode": "list_tree",
        "project": str(project),
        "files_returned": len(files),
        "max_files": max_files,
        "files": files,
    }


def run(args: Dict[str, Any]) -> Dict[str, Any]:
    action = args.get("action", "audit")
    project = _safe_project_path(args.get("project_path", ""))

    if action == "audit":
        return _audit(project)
    if action == "preview_fix":
        return _preview_fix(project, args.get("issue_id", ""))
    if action == "apply_fix":
        return _apply_fix(project, args.get("issue_id", ""), args.get("confirmation", ""))
    if action == "delete_file":
        return _delete_file(project, args.get("target_file", ""), args.get("confirmation", ""))
    if action == "read_file":
        return _read_file(project, args.get("target_file", ""))
    if action == "list_tree":
        return _list_tree(project, int(args.get("max_files", 500)))

    return {
        "ok": False,
        "error": f"Unknown action: {action}",
        "supported_actions": ["audit", "preview_fix", "apply_fix", "delete_file", "read_file", "list_tree"],
    }
