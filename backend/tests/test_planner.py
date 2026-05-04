from __future__ import annotations

import pytest

from core.planner import (
    PlannerError,
    build_planner_prompt,
    parse_planner_response,
    planner_result_to_route,
)


PLUGINS = [
    {
        "tool_name": "web_search",
        "description": "Collects trusted-source documents or direct weather data.",
        "intents": ["current_info", "news", "weather"],
        "execution_mode": "grounded_answer",
        "permissions": ["network"],
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {
        "tool_name": "filesystem_manager",
        "description": "Reads, lists, creates and modifies local files with permission controls.",
        "intents": ["filesystem", "code_tree"],
        "execution_mode": "direct_answer",
        "permissions": ["filesystem_read", "filesystem_write"],
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "path": {"type": "string"},
            },
        },
    },
]


def test_build_planner_prompt_contains_registry_and_user_request() -> None:
    prompt = build_planner_prompt("latest oil prices", PLUGINS)

    assert "You are Jarvis' plugin planner" in prompt
    assert "web_search" in prompt
    assert "filesystem_manager" in prompt
    assert "latest oil prices" in prompt
    assert "VALID JSON only" in prompt


def test_parse_use_plugin_plan_and_convert_to_route() -> None:
    raw = """
    {
      "decision": "use_plugin",
      "plugin_name": "web_search",
      "args": {"query": "latest oil prices"},
      "answer_type": null,
      "confidence": 0.92,
      "reason": "Needs current trusted-source information.",
      "suggested_plugin": null,
      "clarification_question": null
    }
    """

    plan = parse_planner_response(raw, PLUGINS)
    route = planner_result_to_route(plan)

    assert plan.decision == "use_plugin"
    assert plan.plugin_name == "web_search"
    assert plan.args == {"query": "latest oil prices"}
    assert plan.confidence == 0.92
    assert route is not None
    assert route["use_tool"] is True
    assert route["tool_name"] == "web_search"
    assert route["args"] == {"query": "latest oil prices"}
    assert route["planner_confidence"] == 0.92


def test_parse_direct_datetime_plan() -> None:
    raw = """
    {
      "decision": "answer_directly",
      "plugin_name": null,
      "args": {},
      "answer_type": "local_datetime",
      "confidence": 0.99,
      "reason": "The request asks for the current local year.",
      "suggested_plugin": null,
      "clarification_question": null
    }
    """

    plan = parse_planner_response(raw, PLUGINS)

    assert plan.decision == "answer_directly"
    assert plan.answer_type == "local_datetime"
    assert planner_result_to_route(plan) is None


def test_parse_needs_new_plugin_plan() -> None:
    raw = """
    {
      "decision": "needs_new_plugin",
      "plugin_name": null,
      "args": {},
      "answer_type": null,
      "confidence": 0.81,
      "reason": "No available plugin can control smart lights.",
      "suggested_plugin": "iot_light_controller",
      "clarification_question": null
    }
    """

    plan = parse_planner_response(raw, PLUGINS)

    assert plan.decision == "needs_new_plugin"
    assert plan.suggested_plugin == "iot_light_controller"


def test_parse_rejects_unknown_plugin() -> None:
    raw = """
    {
      "decision": "use_plugin",
      "plugin_name": "made_up_tool",
      "args": {},
      "confidence": 0.8,
      "reason": "bad plan"
    }
    """

    with pytest.raises(PlannerError):
        parse_planner_response(raw, PLUGINS)


def test_parse_rejects_non_object_args() -> None:
    raw = """
    {
      "decision": "use_plugin",
      "plugin_name": "web_search",
      "args": "latest oil prices",
      "confidence": 0.8,
      "reason": "bad args"
    }
    """

    with pytest.raises(PlannerError):
        parse_planner_response(raw, PLUGINS)


def test_parse_extracts_json_from_markdown_fence() -> None:
    raw = """```json
    {
      "decision": "normal_chat",
      "plugin_name": null,
      "args": {},
      "answer_type": null,
      "confidence": 0.7,
      "reason": "No tool needed.",
      "suggested_plugin": null,
      "clarification_question": null
    }
    ```"""

    plan = parse_planner_response(raw, PLUGINS)

    assert plan.decision == "normal_chat"
    assert plan.confidence == 0.7
