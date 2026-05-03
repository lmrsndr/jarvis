from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from core.config import ROOT_DIR


RISK_ORDER = {"safe": 0, "medium": 1, "dangerous": 2}
WRITE_ACTIONS = {
    "create_file",
    "create_folder",
    "append_file",
    "overwrite_file",
    "rename",
    "delete",
    "apply_fix",
    "delete_file",
    "write",
}
DESTRUCTIVE_ACTIONS = {"delete", "delete_file", "overwrite_file", "rename", "apply_fix"}
PROTECTED_CORE_DIRS = (
    ROOT_DIR / "backend" / "core",
    ROOT_DIR / "backend" / "memory",
)
PROTECTED_CORE_FILES = (
    ROOT_DIR / "backend" / "core" / "providers.py",
    ROOT_DIR / "backend" / "core" / "assistant.py",
    ROOT_DIR / "backend" / "core" / "tool_router.py",
)


@dataclass(frozen=True)
class RouteDecision:
    use_tool: bool
    tool_name: str | None = None
    args: dict[str, Any] | None = None
    reason: str = ""
    requires_tool: bool = False
    missing_tool: str | None = None
    requires_confirmation: bool = False
    blocked: bool = False
    needs_clarification: bool = False
    clarification: str = ""
    missing_fields: list[str] | None = None
    approval_phrase: str | None = None
    execution_mode: str = "direct_answer"
    risk_level: str = "safe"
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "use_tool": self.use_tool,
            "tool_name": self.tool_name,
            "args": self.args or {},
            "reason": self.reason,
            "requires_tool": self.requires_tool,
            "missing_tool": self.missing_tool,
            "requires_confirmation": self.requires_confirmation,
            "blocked": self.blocked,
            "needs_clarification": self.needs_clarification,
            "clarification": self.clarification,
            "missing_fields": self.missing_fields or [],
            "approval_phrase": self.approval_phrase,
            "execution_mode": self.execution_mode,
            "risk_level": self.risk_level,
            "score": self.score,
        }


class UniversalIntentRouter:
    def __init__(
        self,
        plugins: list[dict[str, Any]],
        *,
        llm_fallback: Callable[[str, list[dict[str, Any]]], str | None] | None = None,
    ) -> None:
        self.plugins = [plugin for plugin in plugins if plugin.get("enabled", True) and plugin.get("status", "ready") != "invalid"]
        self.llm_fallback = llm_fallback

    def route(self, message: str) -> RouteDecision:
        scored = sorted(
            ((self._score_plugin(message, plugin), plugin) for plugin in self.plugins),
            key=lambda item: item[0],
            reverse=True,
        )
        scored = [(score, plugin) for score, plugin in scored if score > 0]
        if not scored:
            fallback_name = self.llm_fallback(message, self.plugins) if self.llm_fallback else None
            if fallback_name:
                plugin = next((item for item in self.plugins if _plugin_name(item) == fallback_name), None)
                if plugin:
                    return self._decision_for_plugin(message, plugin, 1.0, "LLM fallback selected a plugin.")
            return RouteDecision(use_tool=False, reason="General knowledge request.")

        best_score = scored[0][0]
        tied = [plugin for score, plugin in scored if score == best_score]
        if len(tied) > 1:
            names = ", ".join(_plugin_name(plugin) for plugin in tied)
            return RouteDecision(
                use_tool=False,
                needs_clarification=True,
                clarification=f"Which tool should I use: {names}?",
                reason="Multiple plugins matched equally.",
                score=best_score,
            )

        return self._decision_for_plugin(message, scored[0][1], best_score, "Plugin intent matched user request.")

    def _decision_for_plugin(self, message: str, plugin: dict[str, Any], score: float, reason: str) -> RouteDecision:
        args, missing = InputBuilder(plugin).build(message)
        name = _plugin_name(plugin)
        execution_mode = str(plugin.get("execution_mode") or "direct_answer")
        risk_level = str(plugin.get("risk_level") or plugin.get("permissions") or "safe")
        if missing:
            field_list = ", ".join(missing)
            return RouteDecision(
                use_tool=False,
                tool_name=name,
                args=args,
                reason=reason,
                needs_clarification=True,
                clarification=f"I need {field_list} before I can run {name}.",
                missing_fields=missing,
                execution_mode=execution_mode,
                risk_level=risk_level,
                score=score,
            )
        requires_confirmation = PermissionEngine.requires_confirmation(plugin, args)
        return RouteDecision(
            use_tool=True,
            tool_name=name,
            args=args,
            reason=reason,
            requires_confirmation=requires_confirmation,
            approval_phrase=PermissionEngine.approval_phrase(name, args) if requires_confirmation else None,
            execution_mode=execution_mode,
            risk_level=risk_level,
            score=score,
        )

    def _score_plugin(self, message: str, plugin: dict[str, Any]) -> float:
        normalized = _normalize(message)
        name = _plugin_name(plugin)
        keyword_score = self._keyword_score(normalized, plugin)
        intent_score = self._intent_score(normalized, plugin)
        example_score = self._example_score(normalized, plugin)
        if keyword_score:
            return 100 + keyword_score
        if intent_score:
            return 50 + intent_score
        if example_score:
            return example_score
        if name in normalized:
            return 100
        return 0

    def _keyword_score(self, normalized: str, plugin: dict[str, Any]) -> float:
        score = 0.0
        for term in [_plugin_name(plugin), *plugin.get("intents", [])]:
            words = _normalize(str(term))
            if words and words in normalized:
                score += 10
        return score

    def _intent_score(self, normalized: str, plugin: dict[str, Any]) -> float:
        score = 0.0
        schema = plugin.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        if not isinstance(properties, dict):
            return score
        for field, definition in properties.items():
            if str(field).replace("_", " ") in normalized:
                score += 4
            description = ""
            if isinstance(definition, dict):
                description = str(definition.get("description") or "")
                enum_values = definition.get("enum") or []
                for value in enum_values:
                    if _normalize(str(value)).replace("_", " ") in normalized:
                        score += 8
            for token in _tokens(description):
                if len(token) > 3 and token in normalized:
                    score += 1
        return score

    def _example_score(self, normalized: str, plugin: dict[str, Any]) -> float:
        examples = plugin.get("examples") or []
        best = 0.0
        for example in examples:
            prompt = _normalize(str(example.get("prompt") or ""))
            if not prompt:
                continue
            best = max(best, SequenceMatcher(None, normalized, prompt).ratio() * 25)
        return best if best >= 12 else 0.0


class InputBuilder:
    def __init__(self, plugin: dict[str, Any]) -> None:
        self.plugin = plugin
        schema = plugin.get("input_schema") or {}
        self.properties = schema.get("properties") if isinstance(schema, dict) else {}
        self.required = schema.get("required", []) if isinstance(schema, dict) else []

    def build(self, message: str) -> tuple[dict[str, Any], list[str]]:
        args: dict[str, Any] = {}
        normalized = _normalize(message)
        for field, definition in self.properties.items():
            if not isinstance(definition, dict):
                continue
            if "default" in definition:
                args[field] = definition["default"]
            value = self._extract_field(field, definition, message, normalized)
            if value is not None:
                args[field] = value

        required = list(self.required)
        any_required: list[list[str]] = []
        action = str(args.get("action") or "")
        action_requirements = self.plugin.get("action_requirements") or {}
        if action and isinstance(action_requirements, dict):
            requirement = action_requirements.get(action) or {}
            if isinstance(requirement, dict):
                required.extend(str(item) for item in requirement.get("required", []))
                any_required.extend(
                    [str(item) for item in group]
                    for group in requirement.get("any_required", [])
                    if isinstance(group, list)
                )

        missing = []
        for field in required:
            if field not in args or args[field] in {"", None}:
                missing.append(field)
        for group in any_required:
            if not any(field in args and args[field] not in {"", None, []} for field in group):
                missing.append(" or ".join(group))
        missing = _dedupe(missing)
        return args, missing

    def _extract_field(self, field: str, definition: dict[str, Any], message: str, normalized: str) -> Any:
        if field in {"query", "text"}:
            return message
        if field in {"path", "project_path", "target_file", "destination"}:
            return _extract_path_like(message)
        if field == "max_results":
            number = _extract_int(message)
            return number if number is not None else None
        if field == "max_depth":
            return _extract_int(message)
        if field == "action":
            enum_values = definition.get("enum") or []
            for value in enum_values:
                phrase = _normalize(str(value)).replace("_", " ")
                if phrase in normalized:
                    return value
            action = _infer_action(normalized, enum_values)
            if action:
                return action
        return None


class PermissionEngine:
    @staticmethod
    def requires_confirmation(plugin: dict[str, Any], args: dict[str, Any]) -> bool:
        action = str(args.get("action") or "")
        action_risk = plugin.get("action_risk") or {}
        if isinstance(action_risk, dict) and action in action_risk:
            return RISK_ORDER.get(str(action_risk[action]), 0) > RISK_ORDER["safe"]
        risk = str(plugin.get("risk_level") or plugin.get("permissions") or "safe")
        declared = plugin.get("declared_permissions") or {}
        return (
            RISK_ORDER.get(risk, 0) > RISK_ORDER["safe"]
            or bool(declared.get("destructive"))
            or bool(declared.get("filesystem_delete"))
            or action in DESTRUCTIVE_ACTIONS
        )

    @staticmethod
    def approval_phrase(plugin_name: str, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "run")
        summary = _action_summary(args)
        if action in DESTRUCTIVE_ACTIONS or action == "delete":
            return f"APPROVE ACTION: {plugin_name} {summary}"
        return f"APPROVE ACTION: {plugin_name} {summary}"

    @staticmethod
    def assert_allowed(plugin: dict[str, Any], args: dict[str, Any], *, confirmed: bool = False) -> None:
        if PermissionEngine.requires_confirmation(plugin, args) and not confirmed:
            name = _plugin_name(plugin)
            phrase = PermissionEngine.approval_phrase(name, args)
            raise PermissionError(f"Confirmation required. {phrase}")
        _reject_core_rewrite(args)


class ExecutionLayer:
    @staticmethod
    def standardize(plugin: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        mode = str(result.get("mode") or plugin.get("execution_mode") or "direct_answer")
        ok = bool(result.get("ok", True)) and "error" not in result
        return {
            "ok": ok,
            "mode": mode,
            "answer": str(result.get("answer") or result.get("text") or result.get("message") or ""),
            "data": result,
            "sources": result.get("sources") or [],
        }


def _plugin_name(plugin: dict[str, Any]) -> str:
    return str(plugin.get("tool_name") or plugin.get("name") or "")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _extract_int(message: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\b", message)
    return int(match.group(1)) if match else None


def _extract_path_like(message: str) -> str | None:
    match = re.search(r"(~/?[^\s,;:]+|/[^\s,;:]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,12})", message)
    return match.group(1) if match else None


def _infer_action(normalized: str, enum_values: list[Any]) -> str | None:
    candidates = {str(value) for value in enum_values}
    mappings = [
        (("delete", "remove"), "delete"),
        (("overwrite", "replace"), "overwrite_file"),
        (("rename",), "rename"),
        (("append",), "append_file"),
        (("create folder", "make folder", "new folder"), "create_folder"),
        (("create", "make file", "new file", "save file"), "create_file"),
        (("read", "open", "show file"), "read"),
        (("tree", "directory tree", "structure"), "tree"),
        (("list", "what files", "show files"), "list"),
        (("audit", "debug"), "audit"),
        (("preview",), "preview_fix"),
        (("apply", "fix"), "apply_fix"),
    ]
    for terms, action in mappings:
        if action in candidates and any(term in normalized for term in terms):
            return action
    return None


def _action_summary(args: dict[str, Any]) -> str:
    action = str(args.get("action") or "run")
    target_parts = [
        str(args.get(key) or "").strip()
        for key in ("path", "project_path", "target_file", "destination", "issue_id", "category")
        if str(args.get(key) or "").strip()
    ]
    return " ".join([action, *target_parts]).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _reject_core_rewrite(args: dict[str, Any]) -> None:
    action = str(args.get("action") or "")
    if action not in WRITE_ACTIONS:
        return
    project_path = args.get("project_path")
    for key in ("path", "destination", "target_file", "project_path"):
        value = args.get(key)
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if key == "target_file" and project_path and not path.is_absolute():
            path = Path(str(project_path)).expanduser() / path
        if not path.is_absolute():
            path = (Path.home() / "Projects" / path).resolve(strict=False)
        else:
            path = path.resolve(strict=False)
        if _is_protected_core_path(path):
            raise PermissionError("Plugins may not rewrite Jarvis core Python code through chat.")


def _is_protected_core_path(path: Path) -> bool:
    protected_dirs = [item.resolve(strict=False) for item in PROTECTED_CORE_DIRS]
    protected_files = [item.resolve(strict=False) for item in PROTECTED_CORE_FILES]
    return any(path == item for item in protected_files) or any(path == item or item in path.parents for item in protected_dirs)
