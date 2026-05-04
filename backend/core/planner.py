from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from plugins.schema import PluginSchema


PlannerDecision = Literal["use_plugin", "answer_directly", "needs_new_plugin", "ask_clarification", "normal_chat"]


@dataclass(frozen=True)
class PlannerResult:
    decision: PlannerDecision
    plugin_name: str | None = None
    args: dict[str, Any] | None = None
    answer_type: str | None = None
    confidence: float = 0.0
    reason: str = ""
    suggested_plugin: str | None = None
    clarification_question: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "plugin_name": self.plugin_name,
            "args": dict(self.args or {}),
            "answer_type": self.answer_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "suggested_plugin": self.suggested_plugin,
            "clarification_question": self.clarification_question,
        }


class PlannerError(RuntimeError):
    pass


def build_planner_prompt(user_message: str, plugins: list[dict[str, Any] | PluginSchema]) -> str:
    registry = [_plugin_summary(plugin) for plugin in plugins]
    return (
        "You are Jarvis' plugin planner.\n"
        "Your job is to understand the user's request and decide how Jarvis should handle it.\n"
        "You must return VALID JSON only. Do not answer the user directly.\n\n"
        "Rules:\n"
        "1. You may only select plugins from the available_plugins list.\n"
        "2. Translate the user's request into the selected plugin's input arguments.\n"
        "3. If no existing plugin can perform the task, return decision needs_new_plugin.\n"
        "4. If the request is ordinary conversation and needs no plugin, return normal_chat.\n"
        "5. If the request is local date/time, return answer_directly with answer_type local_datetime.\n"
        "6. If required information is missing, return ask_clarification.\n"
        "7. Do not invent plugin names.\n\n"
        "Return one JSON object using this shape:\n"
        "{\n"
        "  \"decision\": \"use_plugin | answer_directly | needs_new_plugin | ask_clarification | normal_chat\",\n"
        "  \"plugin_name\": \"plugin name or null\",\n"
        "  \"args\": {},\n"
        "  \"answer_type\": \"local_datetime or null\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"reason\": \"short reason\",\n"
        "  \"suggested_plugin\": \"name for new plugin or null\",\n"
        "  \"clarification_question\": \"question or null\"\n"
        "}\n\n"
        f"available_plugins:\n{json.dumps(registry, indent=2)}\n\n"
        f"user_request:\n{user_message}\n"
    )


def parse_planner_response(raw_response: str, plugins: list[dict[str, Any] | PluginSchema]) -> PlannerResult:
    data = _extract_json_object(raw_response)
    decision = str(data.get("decision") or "").strip()
    valid_decisions = {"use_plugin", "answer_directly", "needs_new_plugin", "ask_clarification", "normal_chat"}
    if decision not in valid_decisions:
        raise PlannerError(f"Invalid planner decision: {decision}")

    plugin_name = _nullable_str(data.get("plugin_name"))
    known_plugins = {_plugin_name(plugin) for plugin in plugins}
    if decision == "use_plugin":
        if not plugin_name:
            raise PlannerError("Planner selected use_plugin without plugin_name.")
        if plugin_name not in known_plugins:
            raise PlannerError(f"Planner selected unknown plugin: {plugin_name}")
    elif plugin_name and plugin_name not in known_plugins:
        plugin_name = None

    args = data.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise PlannerError("Planner args must be a JSON object.")

    confidence = _confidence(data.get("confidence"))
    return PlannerResult(
        decision=decision,  # type: ignore[arg-type]
        plugin_name=plugin_name,
        args=args,
        answer_type=_nullable_str(data.get("answer_type")),
        confidence=confidence,
        reason=str(data.get("reason") or ""),
        suggested_plugin=_nullable_str(data.get("suggested_plugin")),
        clarification_question=_nullable_str(data.get("clarification_question")),
    )


def planner_result_to_route(plan: PlannerResult) -> dict[str, Any] | None:
    if plan.decision != "use_plugin" or not plan.plugin_name:
        return None
    return {
        "use_tool": True,
        "tool_name": plan.plugin_name,
        "args": dict(plan.args or {}),
        "reason": plan.reason or "LLM planner selected this plugin.",
        "requires_tool": True,
        "missing_tool": None,
        "requires_confirmation": False,
        "blocked": False,
        "planner_confidence": plan.confidence,
    }


def _plugin_summary(plugin: dict[str, Any] | PluginSchema) -> dict[str, Any]:
    if isinstance(plugin, PluginSchema):
        return {
            "tool_name": plugin.tool_name,
            "description": plugin.description,
            "intents": list(plugin.intents),
            "execution_mode": plugin.execution_mode,
            "permissions": plugin.permissions,
            "input_schema": plugin.input_schema,
        }
    return {
        "tool_name": plugin.get("tool_name") or plugin.get("name"),
        "description": plugin.get("description") or "",
        "intents": plugin.get("intents") or [],
        "execution_mode": plugin.get("execution_mode") or "direct_answer",
        "permissions": plugin.get("permissions") or plugin.get("risk_level") or "safe",
        "input_schema": plugin.get("input_schema") or {},
    }


def _plugin_name(plugin: dict[str, Any] | PluginSchema) -> str:
    if isinstance(plugin, PluginSchema):
        return plugin.tool_name
    return str(plugin.get("tool_name") or plugin.get("name") or "")


def _extract_json_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise PlannerError("Planner did not return a JSON object.")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise PlannerError("Planner response must be a JSON object.")
    return data


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text


def _confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))
