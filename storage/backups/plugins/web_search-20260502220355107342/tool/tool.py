"""
Jarvis plugin: web_search v0.7.0

Strict trusted-source web lookup.
No general search-engine fallback. If Jarvis cannot verify from configured trusted
sources, it returns a teach request instead of inventing an answer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
import os
import re
import shutil
import socket
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import requests

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None

PLUGIN_NAME = "web_search"
PLUGIN_DESCRIPTION = "Strict trusted-source web lookup with real weather, BBC and Guardian football extraction, RSS news, teachable source categories, caching, summarised answers, and source-agreement confidence scoring."
PLUGIN_VERSION = "0.7.0"
PLUGIN_PERMISSIONS = "safe"

BASE_DIR = os.path.dirname(__file__)
SOURCES_FILE = os.path.join(BASE_DIR, "web_sources.json")
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
UA = "Jarvis-local-assistant/0.7 (+local) Mozilla/5.0"
TIMEOUT = 12


def _response(ok: bool, **kwargs: Any) -> Dict[str, Any]:
    confidence = float(kwargs.pop("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    base = {
        "ok": bool(ok),
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
    }
    base.update(kwargs)
    return base


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.55:
        return "medium"
    if value > 0:
        return "low"
    return "none"


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data.strip())


def _html_to_text(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript", "svg"]):
            bad.decompose()
        return _clean_text(soup.get_text(" "))
    parser = _TextExtractor()
    parser.feed(html)
    return _clean_text(" ".join(parser.parts))


def _load_sources() -> Dict[str, Any]:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Invalid web_sources.json")
        data.setdefault("strict_mode", True)
        data.setdefault("cache_ttl_seconds", 900)
        data.setdefault("categories", {})
        return data
    except Exception:
        return {"strict_mode": True, "cache_ttl_seconds": 900, "categories": {}}


def _save_sources(data: Dict[str, Any]) -> None:
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _normalise_category(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_ -]", "", name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", name)


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


def _cache_key(url: str, params: Optional[dict]) -> str:
    raw = url + "?" + urllib.parse.urlencode(params or {}, doseq=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get(url: str, params: Optional[dict] = None, ttl: Optional[int] = None, no_cache: bool = False) -> requests.Response:
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(url, params)
    cache_path = os.path.join(CACHE_DIR, key + ".json")
    if ttl and not no_cache and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if time.time() - cached.get("ts", 0) <= ttl:
                resp = requests.Response()
                resp.status_code = int(cached.get("status_code", 200))
                resp._content = cached.get("content", "").encode("utf-8")
                resp.url = cached.get("url", url)
                return resp
        except Exception:
            pass
    r = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": UA})
    if ttl and not no_cache and r.status_code < 500:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "status_code": r.status_code, "url": r.url, "content": r.text}, f)
        except Exception:
            pass
    return r


def _has_internet() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return True
    except Exception:
        return False


def _validate_url_list(values: Any) -> List[str]:
    out = []
    for v in values or []:
        u = str(v).strip()
        if u.startswith("http://") or u.startswith("https://"):
            out.append(u)
    return out


def _looks_like_weather(q: str) -> bool:
    q = q.lower()
    return any(w in q for w in ["weather", "forecast", "temperature", "rain", "wind"])


def _looks_like_football(q: str) -> bool:
    q = q.lower()
    return any(w in q for w in ["premier league", "football results", "football scores", "epl", "match results", "live scores", "fixtures"])


def _looks_like_trending(q: str) -> bool:
    q = q.lower()
    return any(x in q for x in ["trending", "popular topics", "most popular", "top 10", "top ten"])


def _builtin_news_topic(q: str) -> str:
    ql = q.lower()
    if any(x in ql for x in ["space news", "nasa news", "astronomy news", "latest space", "esa news"]):
        return "space_news"
    if any(x in ql for x in ["science news", "scientific news", "research news", "latest science"]):
        return "science_news"
    if any(x in ql for x in ["news", "headlines", "latest"]):
        return "general_news"
    return ""


def _detect_learned_category(query: str, categories: Dict[str, Any]) -> Optional[str]:
    q = query.lower()
    best_name = None
    best_score = 0
    for name, data in categories.items():
        score = 0
        if name.replace("_", " ") in q:
            score += 4
        for kw in data.get("keywords", []) or []:
            kw = str(kw).lower().strip()
            if kw and kw in q:
                score += 2 if " " in kw else 1
        if score > best_score:
            best_score = score
            best_name = name
    return best_name if best_score > 0 else None


def _extract_location(query: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.strip()
    q = query.strip()
    patterns = [
        r"(?:weather|forecast|temperature|rain|wind)\s+(?:in|for|at)\s+(.+?)(?:\s+tomorrow|\s+today|\s+on\s+\w+|\s+and\s+\w+|\?|$)",
        r"(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:in|for|at)\s+(.+?)(?:\?|$)",
        r"in\s+([A-Za-z ,.'-]+?)(?:\s+for|\s+tomorrow|\s+and|\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, q, re.I)
        if m:
            loc = m.group(1).strip(" .?")
            if loc and len(loc) <= 80:
                return loc
    return "Bristol, United Kingdom"


def _requested_day_indices(query: str, dates: List[str]) -> List[int]:
    q = query.lower()
    today = datetime.now().date()
    date_map = {d: i for i, d in enumerate(dates)}
    wanted: List[int] = []
    if "today" in q:
        wanted.append(0)
    if "tomorrow" in q:
        wanted.append(1)
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for idx, name in enumerate(weekdays):
        if name in q:
            for offset in range(0, min(10, len(dates))):
                dt = today + timedelta(days=offset)
                if dt.weekday() == idx:
                    wanted.append(date_map.get(str(dt), offset))
                    break
    if not wanted:
        wanted = list(range(min(3, len(dates))))
    clean = []
    for i in wanted:
        if 0 <= i < len(dates) and i not in clean:
            clean.append(i)
    return clean[:5]


def _weather_code(code: int) -> str:
    table = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
        56: "freezing drizzle", 57: "dense freezing drizzle", 61: "slight rain", 63: "moderate rain", 65: "heavy rain",
        66: "freezing rain", 67: "heavy freezing rain", 71: "slight snow", 73: "moderate snow", 75: "heavy snow",
        77: "snow grains", 80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
        85: "slight snow showers", 86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
    }
    return table.get(code, f"weather code {code}")


def _weather_handler(query: str, max_results: int, location: Optional[str], ttl: int, no_cache: bool) -> Dict[str, Any]:
    loc = _extract_location(query, location)
    try:
        geo = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": loc, "count": 1, "language": "en", "format": "json"}, ttl=86400, no_cache=no_cache)
        geo.raise_for_status()
        gdata = geo.json()
        if not gdata.get("results"):
            return _response(True, handler="weather", query=query, answer=f"I could not verify the location '{loc}' using Open-Meteo geocoding.", confidence=0.0, teach_request=True)
        place = gdata["results"][0]
        lat, lon = place["latitude"], place["longitude"]
        name = ", ".join(str(x) for x in [place.get("name"), place.get("admin1"), place.get("country")] if x)
        forecast = _get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                "timezone": "auto",
                "forecast_days": 10,
            },
            ttl=1800,
            no_cache=no_cache,
        )
        forecast.raise_for_status()
        daily = forecast.json().get("daily", {})
        dates = daily.get("time", [])
        indices = _requested_day_indices(query, dates)
        rows = []
        lines = []
        for i in indices:
            code = int(daily.get("weather_code", [0])[i])
            row = {
                "date": dates[i],
                "summary": _weather_code(code),
                "high_c": daily.get("temperature_2m_max", [None])[i],
                "low_c": daily.get("temperature_2m_min", [None])[i],
                "rain_probability_percent": daily.get("precipitation_probability_max", [None])[i],
                "wind_kmh": daily.get("wind_speed_10m_max", [None])[i],
            }
            rows.append(row)
            lines.append(f"{row['date']}: {row['summary']}, {row['low_c']}–{row['high_c']}°C, rain chance {row['rain_probability_percent']}%, max wind {row['wind_kmh']} km/h")
        return _response(True, handler="weather", provider="open-meteo", query=query, answer=f"Weather for {name}:\n" + "\n".join(lines), confidence=0.95, results=rows, sources=["https://open-meteo.com/"])
    except Exception as exc:
        return _response(False, handler="weather", query=query, error=f"Weather lookup failed: {exc}", answer="I could not verify the weather from Open-Meteo.", confidence=0.0)


def _parse_rss(url: str, limit: int, ttl: int, no_cache: bool) -> List[Dict[str, str]]:
    try:
        r = _get(url, ttl=ttl, no_cache=no_cache)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    items: List[Dict[str, str]] = []
    for item in root.findall(".//item")[:limit]:
        title = _clean_text(item.findtext("title") or "")
        link = _clean_text(item.findtext("link") or "")
        desc = _clean_text(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))
        pub = _clean_text(item.findtext("pubDate") or "")
        if title:
            items.append({"title": title, "url": link, "snippet": desc[:300], "published": pub, "source": _domain(link or url)})
    return items


def _agreement_score(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    sources = {r.get("source", "") for r in results if r.get("source")}
    words_per_result = []
    stop = {"the", "and", "for", "with", "from", "that", "this", "have", "has", "are", "was", "were", "will", "after", "latest", "news"}
    for r in results:
        text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        words = {w for w in re.findall(r"[a-zA-Z]{4,}", text) if w not in stop}
        words_per_result.append(words)
    overlap = 0
    comparisons = 0
    for i in range(len(words_per_result)):
        for j in range(i + 1, len(words_per_result)):
            comparisons += 1
            if words_per_result[i] & words_per_result[j]:
                overlap += 1
    overlap_ratio = overlap / comparisons if comparisons else 0.0
    source_bonus = min(0.35, 0.12 * len(sources))
    count_bonus = min(0.35, 0.07 * len(results))
    return min(0.95, 0.2 + source_bonus + count_bonus + 0.2 * overlap_ratio)


def _summarise_results(label: str, results: List[Dict[str, Any]], max_items: int = 5) -> str:
    if not results:
        return f"No verified {label} results were found."
    lines = []
    for r in results[:max_items]:
        title = r.get("title") or "Untitled"
        source = r.get("source") or _domain(r.get("url", ""))
        snippet = r.get("snippet") or ""
        if snippet:
            lines.append(f"- {title} ({source}): {snippet[:180]}")
        else:
            lines.append(f"- {title} ({source})")
    return f"Verified {label} from trusted sources:\n" + "\n".join(lines)


def _dedupe_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in results:
        key = (r.get("url") or "") + "|" + (r.get("title") or r.get("snippet") or "")[:90]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _category_search(category: str, query: str, categories: Dict[str, Any], max_results: int, ttl: int, no_cache: bool) -> Dict[str, Any]:
    cfg = categories.get(category, {})
    results: List[Dict[str, Any]] = []
    for feed in cfg.get("rss", []) or []:
        results.extend(_parse_rss(feed, max_results, ttl, no_cache))
    if not results:
        for url in cfg.get("sources", []) or []:
            try:
                r = _get(url, ttl=ttl, no_cache=no_cache)
                r.raise_for_status()
                title = _extract_title(r.text) or url
                text = _html_to_text(r.text)
                results.append({"title": title, "url": url, "snippet": text[:320], "source": _domain(url)})
            except Exception:
                continue
    results = _dedupe_results(results)[:max_results]
    conf = _agreement_score(results)
    if not results:
        return _teach_response(query, category, f"The configured trusted sources for '{category}' did not return usable data.")
    return _response(True, handler="trusted_category", provider="trusted_sources", category=category, query=query, answer=_summarise_results(category.replace("_", " "), results), confidence=conf, results=results, sources=(cfg.get("rss", []) or []) + (cfg.get("sources", []) or []))


def _news_handler(query: str, category: str, categories: Dict[str, Any], max_results: int, ttl: int, no_cache: bool) -> Dict[str, Any]:
    return _category_search(category, query, categories, max_results, ttl, no_cache)


def _extract_title(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return _clean_text(soup.title.string)
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return _clean_text(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""


def _football_handler(query: str, categories: Dict[str, Any], max_results: int, ttl: int, no_cache: bool) -> Dict[str, Any]:
    cfg = categories.get("sports", {})
    sources = cfg.get("sources", []) or []
    results: List[Dict[str, Any]] = []
    for url in sources:
        try:
            r = _get(url, ttl=300, no_cache=no_cache)
            if r.status_code >= 400:
                continue
            text = _html_to_text(r.text)
            source_name = "BBC Sport" if "bbc." in url else ("The Guardian" if "theguardian" in url else _domain(url))
            # Actual score patterns: Team A 1 Team B 2, Team A 1-2 Team B, with a context window.
            windows = []
            for m in re.finditer(r".{0,100}\b\d{1,2}\s*[-–]\s*\d{1,2}\b.{0,140}", text):
                windows.append(_clean_text(m.group(0)))
            # BBC often separates scores as text, so also catch windows containing Full time / Premier League.
            for m in re.finditer(r".{0,80}(?:Full time|FT|Premier League).{0,220}", text, re.I):
                w = _clean_text(m.group(0))
                if re.search(r"\b\d{1,2}\b", w):
                    windows.append(w)
            for w in windows:
                if len(w) < 20:
                    continue
                if "premier league" in query.lower() and not any(x in w.lower() for x in ["premier league", "full time", "ft"]):
                    # Keep this as a weaker possible score, but still include if score pattern is clean.
                    pass
                results.append({"title": "Football score item", "url": url, "snippet": w[:350], "source": source_name})
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    results = _dedupe_results(results)[:max_results]
    conf = min(0.85, _agreement_score(results)) if results else 0.0
    if not results:
        return _response(True, handler="football_scores", provider="trusted_sources", query=query, answer="I reached the trusted sports sources, but I could not confidently extract score lines. This usually means the page structure changed or there were no matching results. Use the source links below to verify manually, or add a better sports results source.", confidence=0.25, results=[], sources=sources, teach_request=True, suggested_action={"action": "add_source_category", "category": "sports", "sources": ["https://www.bbc.co.uk/sport/football/scores-fixtures"], "keywords": ["football", "scores", "results", "premier league"]})
    return _response(True, handler="football_scores", provider="bbc_guardian", query=query, answer=_summarise_results("football results", results), confidence=conf, results=results, sources=sources)


def _trending_handler(query: str, max_results: int, ttl: int, no_cache: bool) -> Dict[str, Any]:
    dt = datetime.now(timezone.utc) - timedelta(days=1)
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{dt:%Y/%m/%d}"
    try:
        r = _get(url, ttl=86400, no_cache=no_cache)
        r.raise_for_status()
        articles = r.json()["items"][0]["articles"]
        results = []
        skip_prefixes = ("Special:", "Wikipedia:", "File:", "Template:", "Category:")
        skip_titles = {"Main_Page", "Special:Search"}
        for a in articles:
            title = a.get("article", "")
            if not title or title in skip_titles or title.startswith(skip_prefixes):
                continue
            pretty = urllib.parse.unquote(title).replace("_", " ")
            page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title)
            results.append({"title": pretty, "url": page_url, "views": a.get("views"), "snippet": f"{a.get('views')} page views yesterday", "source": "Wikimedia"})
            if len(results) >= max_results:
                break
        answer = "Top popular topics from English Wikipedia pageviews:\n" + "\n".join(f"- {r['title']} ({r.get('views')} views)" for r in results)
        return _response(True, handler="trending_topics", provider="wikimedia_pageviews", query=query, answer=answer, confidence=0.85, results=results, sources=[url])
    except Exception as exc:
        return _response(False, handler="trending_topics", query=query, error=f"Trending lookup failed: {exc}", answer="I could not verify trending topics from Wikimedia.", confidence=0.0)


def _teach_response(query: str, category: Optional[str], reason: str) -> Dict[str, Any]:
    suggested_category = _normalise_category(category or re.sub(r"\W+", "_", query.lower())[:40].strip("_") or "new_topic")
    return _response(
        True,
        handler="strict_trusted_sources",
        query=query,
        answer=f"I cannot verify this from trusted sources. {reason} Please provide 2 to 5 trusted source URLs or RSS feeds so I can add a source category.",
        confidence=0.0,
        teach_request=True,
        suggested_action={
            "action": "add_source_category",
            "category": suggested_category,
            "description": f"Trusted sources for: {query}",
            "sources": [],
            "rss": [],
            "keywords": [w for w in re.findall(r"[a-zA-Z]{4,}", query.lower())[:6]],
        },
    )


def run(args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}
    action = str(args.get("action") or "search").strip()
    max_results = int(args.get("max_results", 5) or 5)
    max_results = max(1, min(max_results, 12))
    sources_data = _load_sources()
    ttl = int(sources_data.get("cache_ttl_seconds", 900) or 900)
    no_cache = bool(args.get("no_cache", False))
    categories: Dict[str, Any] = sources_data.setdefault("categories", {})

    if action == "clear_cache":
        try:
            if os.path.isdir(CACHE_DIR):
                shutil.rmtree(CACHE_DIR)
            os.makedirs(CACHE_DIR, exist_ok=True)
            return _response(True, action=action, answer="Web search cache cleared.", confidence=1.0)
        except Exception as exc:
            return _response(False, action=action, error=str(exc), answer="Could not clear cache.", confidence=0.0)

    if action == "add_source_category":
        name = _normalise_category(str(args.get("category", "")))
        if not name:
            return _response(False, error="Missing category name.", confidence=0.0)
        srcs = _validate_url_list(args.get("sources", []))
        rss = _validate_url_list(args.get("rss", []))
        keywords = [str(k).strip().lower() for k in args.get("keywords", []) if str(k).strip()]
        if not srcs and not rss:
            return _response(False, error="Provide at least one trusted source URL or RSS feed URL.", confidence=0.0)
        categories[name] = {
            "description": str(args.get("description", "")).strip(),
            "sources": srcs,
            "rss": rss,
            "keywords": keywords,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_sources(sources_data)
        return _response(True, action=action, category=name, answer=f"Added trusted source category '{name}' with {len(srcs)} page source(s), {len(rss)} RSS feed(s), and {len(keywords)} keyword(s).", confidence=1.0)

    if action == "list_source_categories":
        summary = {name: {"description": data.get("description", ""), "keywords": data.get("keywords", []), "sources": data.get("sources", []), "rss": data.get("rss", [])} for name, data in categories.items()}
        return _response(True, action=action, categories=summary, answer=f"Known trusted source categories: {', '.join(categories.keys()) or 'none'}", confidence=1.0)

    if action == "remove_source_category":
        name = _normalise_category(str(args.get("category", "")))
        existed = name in categories
        categories.pop(name, None)
        _save_sources(sources_data)
        return _response(True, action=action, category=name, answer=(f"Removed trusted source category '{name}'." if existed else f"Trusted source category '{name}' did not exist."), confidence=1.0)

    query = str(args.get("query", "")).strip()
    if not query:
        return _response(False, error="Missing required argument: query", confidence=0.0)

    if not _has_internet():
        return _response(False, query=query, error="No internet connection was detected from the Jarvis host.", answer="I cannot reach the internet from this machine right now. Check DNS, firewall, proxy, or outbound HTTPS access.", confidence=0.0)

    if _looks_like_weather(query):
        return _weather_handler(query, max_results, args.get("location"), ttl, no_cache)

    if _looks_like_football(query):
        return _football_handler(query, categories, max_results, ttl, no_cache)

    if _looks_like_trending(query):
        return _trending_handler(query, max_results, ttl, no_cache)

    news_cat = _builtin_news_topic(query)
    if news_cat and news_cat in categories:
        return _news_handler(query, news_cat, categories, max_results, ttl, no_cache)

    learned = _detect_learned_category(query, categories)
    if learned:
        return _category_search(learned, query, categories, max_results, ttl, no_cache)

    return _teach_response(query, None, "No trusted source category matched this question.")
