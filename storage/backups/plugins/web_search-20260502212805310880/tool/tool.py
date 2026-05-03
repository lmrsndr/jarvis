"""
Jarvis plugin: web_search

A simple local-first web search helper using DuckDuckGo's public Instant Answer API.
This avoids paid token/API usage by default.
"""

from __future__ import annotations

from typing import Any, Dict, List
import requests

PLUGIN_NAME = "web_search"
PLUGIN_DESCRIPTION = 'Search the web for real-time information using DuckDuckGo Instant Answer.'
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "safe"


def _add_result(results: List[Dict[str, str]], title: str | None, url: str | None, snippet: str | None) -> None:
    """Add a result if it has useful content and is not a duplicate."""
    title = (title or "").strip()
    url = (url or "").strip()
    snippet = (snippet or "").strip()

    if not title and not snippet:
        return

    candidate = {"title": title or url or "Untitled result", "url": url, "snippet": snippet}

    for existing in results:
        if existing.get("url") == candidate["url"] and candidate["url"]:
            return
        if existing.get("title") == candidate["title"] and existing.get("snippet") == candidate["snippet"]:
            return

    results.append(candidate)


def run(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a web search.

    Expected args:
        {
            "query": "search text",
            "max_results": 5
        }
    """
    query = str(args.get("query", "")).strip()
    max_results = int(args.get("max_results", 5) or 5)
    max_results = max(1, min(max_results, 10))

    if not query:
        return {
            "ok": False,
            "error": "Missing required argument: query",
            "results": [],
        }

    try:
        response = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
            timeout=12,
            headers={"User-Agent": "Jarvis-local-assistant/0.1"},
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"Web search request failed: {exc}",
            "query": query,
            "results": [],
        }
    except ValueError as exc:
        return {
            "ok": False,
            "error": f"Search provider returned invalid JSON: {exc}",
            "query": query,
            "results": [],
        }

    results: List[Dict[str, str]] = []

    _add_result(
        results,
        data.get("Heading"),
        data.get("AbstractURL"),
        data.get("AbstractText"),
    )

    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break

        if isinstance(topic, dict) and "Topics" in topic:
            for subtopic in topic.get("Topics", []):
                if len(results) >= max_results:
                    break
                if isinstance(subtopic, dict):
                    _add_result(
                        results,
                        subtopic.get("Text"),
                        subtopic.get("FirstURL"),
                        subtopic.get("Text"),
                    )
        elif isinstance(topic, dict):
            _add_result(
                results,
                topic.get("Text"),
                topic.get("FirstURL"),
                topic.get("Text"),
            )

    return {
        "ok": True,
        "query": query,
        "provider": "duckduckgo_instant_answer",
        "results": results[:max_results],
        "note": "DuckDuckGo Instant Answer may return limited results for some queries.",
    }
