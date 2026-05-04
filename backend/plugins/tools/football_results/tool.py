from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

PLUGIN_NAME = "football_results"
PLUGIN_DESCRIPTION = "Extract verified football results from strict trusted sources. Currently supports today's Premier League results."
PLUGIN_VERSION = "0.1.0"
PLUGIN_PERMISSIONS = "safe"

TRUSTED_SOURCES = [
    {
        "source_name": "The Guardian",
        "url": "https://www.theguardian.com/football/results",
        "title": "All results | Football | The Guardian",
    }
]

USER_AGENT = "JarvisLocalAssistant/0.1 (+trusted-source-extraction)"


def run(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("message") or "").strip()
    max_results = int(args.get("max_results") or 20)
    no_cache = bool(args.get("no_cache", False))

    if not _looks_like_supported_query(query):
        return _response(
            False,
            query=query,
            answer=(
                "football_results currently supports today's Premier League results only. "
                "Create or teach a new topic plugin for other football requests."
            ),
            confidence=0.2,
            results=[],
            unsupported_query=True,
        )

    return _premier_league_results(query=query, max_results=max_results, no_cache=no_cache)


def _looks_like_supported_query(query: str) -> bool:
    q = query.lower()
    competition = "premier league" in q or "epl" in q
    wants_results = any(word in q for word in ["result", "results", "score", "scores"])
    wants_fixtures = any(word in q for word in ["fixture", "fixtures", "calendar", "next match", "kick off", "kick-off"])
    return competition and wants_results and not wants_fixtures


def _premier_league_results(query: str, max_results: int, no_cache: bool) -> dict[str, Any]:
    source = TRUSTED_SOURCES[0]
    url = source["url"]
    try:
        html, final_url = _fetch(url)
        results = _extract_guardian_premier_league_results(html, final_url)
    except Exception as exc:
        return _response(
            False,
            query=query,
            answer="I could not verify completed Premier League results from trusted sources.",
            confidence=0.2,
            results=[],
            error=str(exc),
        )

    if not results:
        return _response(
            False,
            query=query,
            answer=(
                "I could not verify completed Premier League results for today from trusted sources. "
                "I may have found fixtures instead, but not final results."
            ),
            confidence=0.3,
            results=[],
            strict_extraction_failed=True,
        )

    results = results[:max_results]
    lines = ["Today's Premier League results:"]
    for item in results:
        lines.append(f"- {item['home_team']} {item['home_score']}-{item['away_score']} {item['away_team']}")
    lines.append("")
    lines.append("Source: The Guardian")

    return _response(
        True,
        query=query,
        answer="\n".join(lines),
        confidence=0.95,
        results=results,
        handler="premier_league_results",
        provider="the_guardian",
    )


def _fetch(url: str) -> tuple[str, str]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    return response.text, response.url or url


def _extract_guardian_premier_league_results(html: str, url: str) -> list[dict[str, Any]]:
    text = _html_to_text(html)
    section_match = re.search(
        r"(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday),\s+\d{1,2}\s+\w+\s+\d{4}\s+Premier League\s+(.*?)(?:\s+Bundesliga|\s+Serie A|\s+La Liga|\s+Ligue 1|\s+Women['’]?s Super League|\s+Scottish Premiership|\s+Championship|\s+League One|\s+League Two|\s+Friday,|\s+Saturday,|\s+Sunday,|\s+Monday,|\s+Tuesday,|\s+Wednesday,|\s+Thursday,|$)",
        text,
        flags=re.I | re.S,
    )
    if not section_match:
        return []

    section = _clean_text(section_match.group(2))
    results: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\bFT\s+([A-Z][A-Za-z .&'-]+?)\s+(\d{1,2})\s+(\d{1,2})\s+([A-Z][A-Za-z .&'-]+?)(?=\s+FT\s+[A-Z]|\s*$)",
        flags=re.I,
    )
    aliases = {"C Palace": "Crystal Palace"}
    for match in pattern.finditer(section):
        home = _clean_text(match.group(1)).strip(" -")
        home_score = int(match.group(2))
        away_score = int(match.group(3))
        away = _clean_text(match.group(4)).strip(" -")
        away = re.split(r"\b(?:Bundesliga|Serie A|La Liga|Ligue 1|Scottish Premiership|Women)\b", away)[0].strip()
        home = aliases.get(home, home)
        away = aliases.get(away, away)
        if not home or not away:
            continue
        results.append(
            {
                "home_team": home,
                "away_team": away,
                "home_score": home_score,
                "away_score": away_score,
                "competition": "Premier League",
                "status": "FT",
                "title": f"{home} {home_score}-{away_score} {away}",
                "url": url,
                "source": "The Guardian",
                "snippet": f"FT {home} {home_score}-{away_score} {away}",
                "relevance_score": 10,
            }
        )
    return results


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    return _clean_text(soup.get_text(" "))


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _response(ok: bool, **kwargs: Any) -> dict[str, Any]:
    confidence = float(kwargs.pop("confidence", 0.0))
    return {
        "ok": ok,
        "confidence": confidence,
        "confidence_label": "high" if confidence >= 0.8 else "medium" if confidence >= 0.5 else "low",
        "mode": "direct_extraction",
        "handler": kwargs.pop("handler", "football_results"),
        "provider": kwargs.pop("provider", "trusted_sources"),
        "sources": TRUSTED_SOURCES,
        **kwargs,
    }
