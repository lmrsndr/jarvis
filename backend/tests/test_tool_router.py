from __future__ import annotations

from core.tool_router import route_tool_request


ENABLED_PLUGINS = [
    {"tool_name": "filesystem_manager", "enabled": True},
    {"tool_name": "web_search", "enabled": True},
    {"tool_name": "echo_tool", "enabled": True},
]


def test_project_tree_routes_to_filesystem_manager() -> None:
    route = route_tool_request(
        "Can you give me a tree diagram of the Jarvis project in my Home/Projects folder?",
        ENABLED_PLUGINS,
    )

    assert route["use_tool"] is True
    assert route["tool_name"] == "filesystem_manager"
    assert route["args"]["action"] == "tree"
    assert route["args"]["path"] == "~/Projects/Jarvis"
    assert route["args"]["max_depth"] == 4
    assert "directory tree" in route["reason"]


def test_project_files_routes_to_filesystem_manager_list() -> None:
    route = route_tool_request("What files are in ~/Projects/Jarvis?", ENABLED_PLUGINS)

    assert route["use_tool"] is True
    assert route["tool_name"] == "filesystem_manager"
    assert route["args"]["action"] in {"list", "tree"}
    assert route["args"]["path"] == "~/Projects/Jarvis"


def test_read_project_readme_routes_to_filesystem_manager_read() -> None:
    route = route_tool_request("Read README.md from the Jarvis project", ENABLED_PLUGINS)

    assert route["use_tool"] is True
    assert route["tool_name"] == "filesystem_manager"
    assert route["args"]["action"] == "read"
    assert route["args"]["path"] == "~/Projects/Jarvis/README.md"


def test_general_knowledge_does_not_route_to_filesystem() -> None:
    route = route_tool_request("What is DNS?", ENABLED_PLUGINS)

    assert route["use_tool"] is False
    assert route["requires_tool"] is False
    assert route["tool_name"] is None


def test_today_routes_to_web_search_when_available() -> None:
    route = route_tool_request("What date is it today?", ENABLED_PLUGINS)

    assert route["use_tool"] is True
    assert route["tool_name"] == "web_search"
    assert route["args"]["query"] == "What date is it today?"


def test_today_requires_tool_when_web_search_unavailable() -> None:
    route = route_tool_request("What date is it today?", [{"tool_name": "web_search", "enabled": False}])

    assert route["use_tool"] is False
    assert route["requires_tool"] is True
    assert route["missing_tool"] == "web_search"


def test_invented_folder_structure_is_allowed_without_tool() -> None:
    route = route_tool_request("Invent a possible folder structure for a new app", ENABLED_PLUGINS)

    assert route["use_tool"] is False
    assert route["requires_tool"] is False
    assert route["tool_name"] is None


def test_create_txt_file_routes_to_projects_folder() -> None:
    route = route_tool_request("create a txt file named Jarvis in my Home/Project folder", ENABLED_PLUGINS)

    assert route["use_tool"] is True
    assert route["tool_name"] == "filesystem_manager"
    assert route["args"]["action"] == "create_file"
    assert route["args"]["path"] == "~/Projects/Jarvis.txt"
    assert route["requires_confirmation"] is False


def test_delete_file_requires_confirmation() -> None:
    route = route_tool_request("Can you delete Jarvis.txt for me?", ENABLED_PLUGINS)

    assert route["use_tool"] is True
    assert route["tool_name"] == "filesystem_manager"
    assert route["args"]["action"] == "delete"
    assert route["requires_confirmation"] is True
    assert route["approval_phrase"].startswith("APPROVE ACTION: filesystem_manager delete")


def test_path_escape_is_blocked() -> None:
    route = route_tool_request("Delete ../../.ssh/id_rsa", ENABLED_PLUGINS)

    assert route["use_tool"] is False
    assert route["requires_tool"] is True
    assert route["blocked"] is True
    assert route["tool_name"] == "filesystem_manager"
