"""
Jarvis plugin: web_search v0.5.0

Free web lookup plugin with:
- General DuckDuckGo HTML search
- BeautifulSoup HTML parsing, with stdlib fallback if bs4 is unavailable
- Real weather via Open-Meteo, no API key
- BBC football score extraction from BBC Sport pages, best effort
- RSS based news/science/space summaries
- Wikipedia top-read trending topics
- Teachable trusted source categories stored in web_sources.json
- Confidence scoring
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
import re
import socket
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import requests

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None

PLUGIN_NAME = "web_search"
PLUGIN_DESCRIPTION = "Free web search with topic handlers, teachable trusted sources, summaries and confidence scoring."
PLUGIN_VERSION = "0.5.0"
PLUGIN_PERMISSIONS = "safe"

BASE_DIR = os.path.dirname(__file__)
SOURCES_FILE = os.path.join(BASE_DIR, "web_sources.json")

UA = "Jarvis-local-assistant/0.5 (+https://127.0.0.1) Mozilla/5.0"
TIMEOUT = 12

BBC_PREMIER_LEAGUE_URLS = [
    "https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures",
    "https://www.bbc.com/sport/football/premier-league/scores-fixtures",
]

NEWS_RSS = {
    "news": [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://www.theguardian.com/uk/rss",
    ],
    "science_news": [
        "https://www.sciencedaily.com/rss/top/science.xml",
        "https://www.nature.com/nature.rss",
    ],
    "space_news": [
        "https://www.nasa.gov/news-release/feed/",
        "https://www.esa.int/rssfeed/Our_Activities",
    ],
}


def _response(ok: bool, **kwargs: Any) -> Dict[str, Any]:
    base = {"ok": ok, "confidence": float(kwargs.pop("confidence", 0.0))}
    base.update(kwargs)
    return base


def _get(url: str, params: Optional[dict] = None, timeout: int = TIMEOUT) -> requests.Response:
    return requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA})


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self.skip = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip = False

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
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
    if not os.path.exists(SOURCES_FILE):
        return {"categories": {}}
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "categories" not in data or not isinstance(data["categories"], dict):
            return {"categories": {}}
        return data
    except Exception:
        return {"categories": {}}


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


def _looks_like_weather(q: str) -> bool:
    q = q.lower()
    return any(w in q for w in ["weather", "forecast", "temperature", "rain tomorrow", "wind tomorrow"])


def _looks_like_football(q: str) -> bool:
    q = q.lower()
    return any(w in q for w in ["premier league", "football results", "football scores", "epl", "match results", "live scores"])


def _looks_like_trending(q: str) -> bool:
    q = q.lower()
    return any(x in q for x in ["trending", "popular topics", "most popular", "top 10 topics", "top ten topics"])


def _looks_like_news(q: str) -> str:
    ql = q.lower()
    if any(x in ql for x in ["space news", "nasa news", "astronomy news", "latest space"]):
        return "space_news"
    if any(x in ql for x in ["science news", "scientific news", "research news", "latest science"]):
        return "science_news"
    if any(x in ql for x in ["news", "headlines", "latest"]):
        return "news"
    return ""


def _detect_learned_category(query: str, categories: Dict[str, Any]) -> Optional[str]:
    q = query.lower()
    best_name = None
    best_score = 0
    for name, data in categories.items():
        score = 0
        if name.replace("_", " ") in q:
            score += 3
        for kw in data.get("keywords", []) or []:
            kw = str(kw).lower().strip()
            if kw and kw in q:
                score += 1
        if score > best_score:
            best_score = score
            best_name = name
    return best_name if best_score > 0 else None


def _extract_location(query: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.strip()
    q = query.strip()
    patterns = [
        r"(?:weather|forecast|temperature|rain|wind)\s+(?:in|for|at)\s+(.+?)(?:\s+tomorrow|\s+today|\s+this week|\?|$)",
        r"(?:tomorrow|today)\s+(?:in|for|at)\s+(.+?)(?:\?|$)",
        r"in\s+([A-Za-z ,.'-]+)(?:\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, q, re.I)
        if m:
            loc = m.group(1).strip(" .?")
            if loc and len(loc) <= 80:
                return loc
    return "Bristol, United Kingdom"


def _weather_handler(query: str, max_results: int, location: Optional[str]) -> Dict[str, Any]:
    loc = _extract_location(query, location)
    try:
        geo = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": loc, "count": 1, "language": "en", "format": "json"})
        geo.raise_for_status()
        gdata = geo.json()
        if not gdata.get("results"):
            return _response(False, handler="weather", query=query, error=f"Could not find location: {loc}", confidence=0.1)
        place = gdata["results"][0]
        lat, lon = place["latitude"], place["longitude"]
        name = ", ".join(str(x) for x in [place.get("name"), place.get("admin1"), place.get("country")] if x)

        want_tomorrow = "tomorrow" in query.lower()
        forecast = _get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                "timezone": "auto",
                "forecast_days": 7,
            },
        )
        forecast.raise_for_status()
        data = forecast.json().get("daily", {})
        idx = 1 if want_tomorrow and len(data.get("time", [])) > 1 else 0
        code = int(data.get("weather_code", [0])[idx])
        summary = _weather_code(code)
        day = data.get("time", [""])[idx]
        hi = data.get("temperature_2m_max", [None])[idx]
        lo = data.get("temperature_2m_min", [None])[idx]
        rain = data.get("precipitation_probability_max", [None])[idx]
        wind = data.get("wind_speed_10m_max", [None])[idx]
        answer = f"Weather for {name} on {day}: {summary}. High {hi}°C, low {lo}°C, rain chance {rain}%, max wind {wind} km/h."
        return _response(True, handler="weather", provider="open-meteo", query=query, answer=answer, confidence=0.95, results=[{"location": name, "date": day, "summary": summary, "high_c": hi, "low_c": lo, "rain_probability_percent": rain, "wind_kmh": wind}], sources=["https://open-meteo.com/"])
    except Exception as exc:
        return _response(False, handler="weather", query=query, error=f"Weather lookup failed: {exc}", confidence=0.1)


def _weather_code(code: int) -> str:
    table = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
        61: "slight rain", 63: "moderate rain", 65: "heavy rain", 71: "slight snow", 73: "moderate snow", 75: "heavy snow",
        80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers", 95: "thunderstorm",
    }
    return table.get(code, f"weather code {code}")


def _parse_rss(url: str, limit: int = 5) -> List[Dict[str, str]]:
    try:
        r = _get(url)
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
        items.append({"title": title, "url": link, "snippet": desc[:260], "published": pub, "source": _domain(link or url)})
    return items


def _news_handler(query: str, topic: str, max_results: int) -> Dict[str, Any]:
    feeds = NEWS_RSS.get(topic, NEWS_RSS["news"])
    results: List[Dict[str, str]] = []
    for feed in feeds:
        results.extend(_parse_rss(feed, limit=max_results))
    results = _dedupe_results(results)[:max_results]
    if not results:
        return _response(False, handler=topic, query=query, error="No RSS news results could be fetched.", confidence=0.15, teach_request=True, answer="I could not fetch reliable news results from the configured free sources. Please provide trusted source pages or RSS feeds for this topic.")
    bullets = "; ".join(r["title"] for r in results[: min(5, len(results))])
    label = topic.replace("_", " ")
    return _response(True, handler=topic, provider="rss", query=query, answer=f"Latest {label}: {bullets}", confidence=min(0.9, 0.45 + 0.1 * len(results)), results=results, sources=feeds)


def _trending_handler(query: str, max_results: int) -> Dict[str, Any]:
    # Wikimedia top-read pages: free, no key. Use yesterday because today's full data may not exist yet.
    dt = datetime.now(timezone.utc) - timedelta(days=1)
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{dt:%Y/%m/%d}"
    try:
        r = _get(url)
        r.raise_for_status()
        data = r.json()
        articles = data["items"][0]["articles"]
        results = []
        skip = {"Main_Page", "Special:Search", "Wikipedia:Featured_pictures"}
        for a in articles:
            title = a.get("article", "")
            if not title or title in skip or title.startswith(("Special:", "Wikipedia:", "File:")):
                continue
            pretty = urllib.parse.unquote(title).replace("_", " ")
            page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title)
            results.append({"title": pretty, "url": page_url, "views": a.get("views"), "source": "Wikipedia pageviews"})
            if len(results) >= max_results:
                break
        answer = "Top popular topics from English Wikipedia pageviews: " + "; ".join(x["title"] for x in results)
        return _response(True, handler="trending", provider="wikimedia_pageviews", query=query, answer=answer, confidence=0.85, results=results, sources=[url])
    except Exception as exc:
        return _response(False, handler="trending", query=query, error=f"Trending lookup failed: {exc}", confidence=0.1)


def _bbc_football_handler(query: str, max_results: int) -> Dict[str, Any]:
    pages = []
    for url in BBC_PREMIER_LEAGUE_URLS:
        try:
            r = _get(url)
            if r.status_code < 400:
                pages.append((url, r.text))
                break
        except Exception:
            continue
    if not pages:
        return _response(False, handler="football_scores", query=query, error="Could not fetch BBC Sport scores page.", confidence=0.15)
    url, html = pages[0]
    text = _html_to_text(html)

    # Best-effort extraction. BBC changes markup regularly, so use both soup and text patterns.
    results: List[Dict[str, str]] = []
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for block in soup.find_all(["article", "li", "div"], limit=500):
            t = _clean_text(block.get_text(" "))
            if not t:
                continue
            if re.search(r"\b\d+\s*-\s*\d+\b|\b\d+\s+\d+\b", t) and any(x in t.lower() for x in ["premier league", "full time", "half time", "ft", "kick off", "live"]):
                results.append({"title": "BBC Sport football score item", "snippet": t[:300], "url": url, "source": "BBC Sport"})
    if not results:
        # Try compact text windows around score-like patterns.
        for m in re.finditer(r".{0,80}\b\d{1,2}\s*[-–]\s*\d{1,2}\b.{0,120}", text):
            snippet = _clean_text(m.group(0))
            if len(snippet) > 25:
                results.append({"title": "Possible Premier League score", "snippet": snippet, "url": url, "source": "BBC Sport"})
                if len(results) >= max_results:
                    break
    results = _dedupe_results(results)[:max_results]
    if not results:
        return _response(True, handler="football_scores", provider="bbc_sport", query=query, answer="I reached BBC Sport, but I could not confidently extract Premier League scores from the page. Open the BBC source link for the live table, or add another sports source category if BBC markup has changed.", confidence=0.35, results=[], sources=[url])
    answer = "Premier League score items found on BBC Sport: " + "; ".join(r["snippet"][:120] for r in results[:5])
    return _response(True, handler="football_scores", provider="bbc_sport", query=query, answer=answer, confidence=0.65, results=results, sources=[url])


def _duckduckgo_html(query: str, max_results: int) -> Dict[str, Any]:
    try:
        r = _get("https://duckduckgo.com/html/", {"q": query})
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        return _response(False, handler="general_search", query=query, error=f"DuckDuckGo HTML search failed: {exc}", confidence=0.1, teach_request=True, answer="I could not fetch general web results. Please provide trusted sources for this topic.")

    results: List[Dict[str, str]] = []
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for res in soup.select(".result"):
            a = res.select_one("a.result__a")
            sn = res.select_one(".result__snippet")
            if not a:
                continue
            title = _clean_text(a.get_text(" "))
            href = a.get("href") or ""
            href = _clean_ddg_url(href)
            snippet = _clean_text(sn.get_text(" ") if sn else "")
            if title or snippet:
                results.append({"title": title, "url": href, "snippet": snippet, "source": _domain(href)})
            if len(results) >= max_results:
                break
    else:
        # fallback parser using regex, less accurate but avoids raw HTML output
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            href = _clean_ddg_url(unescape(m.group(1)))
            title = _clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
            results.append({"title": title, "url": href, "snippet": "", "source": _domain(href)})
            if len(results) >= max_results:
                break
    results = _dedupe_results(results)[:max_results]
    if not results:
        return _response(False, handler="general_search", query=query, error="No useful general search results found.", confidence=0.2, teach_request=True, answer="I do not have a reliable source for this topic yet. Please provide trusted source pages so I can learn a category for it.")
    answer = "Top web results: " + "; ".join(f"{r['title']} ({r.get('source','')})" for r in results[:5])
    return _response(True, handler="general_search", provider="duckduckgo_html", query=query, answer=answer, confidence=min(0.75, 0.35 + 0.08 * len(results)), results=results)


def _clean_ddg_url(href: str) -> str:
    if not href:
        return ""
    href = unescape(href)
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs:
        return qs["uddg"][0]
    return href


def _search_trusted_category(category: str, query: str, categories: Dict[str, Any], max_results: int) -> Dict[str, Any]:
    data = categories.get(category, {})
    results: List[Dict[str, str]] = []
    for feed in data.get("rss", []) or []:
        results.extend(_parse_rss(feed, limit=max_results))
    if not results:
        for url in data.get("sources", []) or []:
            try:
                r = _get(url)
                r.raise_for_status()
                text = _html_to_text(r.text)
                snippet = _clean_text(text[:500])
                title = _extract_title(r.text) or url
                results.append({"title": title, "url": url, "snippet": snippet, "source": _domain(url)})
            except Exception:
                continue
    results = _dedupe_results(results)[:max_results]
    if not results:
        return _response(False, handler="trusted_category", category=category, query=query, error=f"No configured sources for {category} returned usable data.", confidence=0.2, teach_request=True, answer=f"I have a category called {category}, but its sources did not return usable information. Please add or replace trusted sources for this category.")
    answer = f"Trusted results for {category.replace('_', ' ')}: " + "; ".join(r["title"] for r in results[:5])
    return _response(True, handler="trusted_category", provider="trusted_sources", category=category, query=query, answer=answer, confidence=min(0.85, 0.45 + 0.1 * len(results)), results=results, sources=(data.get("rss", []) or []) + (data.get("sources", []) or []))


def _extract_title(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return _clean_text(soup.title.string)
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return _clean_text(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""


def _dedupe_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in results:
        key = (r.get("url") or "") + "|" + (r.get("title") or r.get("snippet") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _validate_url_list(values: Any) -> List[str]:
    out = []
    for v in values or []:
        u = str(v).strip()
        if u.startswith("http://") or u.startswith("https://"):
            out.append(u)
    return out


def _has_internet() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return True
    except Exception:
        return False


def run(args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}
    action = str(args.get("action") or "search").strip()
    max_results = int(args.get("max_results", 5) or 5)
    max_results = max(1, min(max_results, 12))
    sources_data = _load_sources()
    categories: Dict[str, Any] = sources_data.setdefault("categories", {})

    if action == "add_source_category":
        name = _normalise_category(str(args.get("category", "")))
        if not name:
            return _response(False, error="Missing category name.", confidence=0.0)
        srcs = _validate_url_list(args.get("sources", []))
        rss = _validate_url_list(args.get("rss", []))
        keywords = [str(k).strip().lower() for k in args.get("keywords", []) if str(k).strip()]
        if not srcs and not rss:
            return _response(False, error="Provide at least one source URL or RSS feed URL.", confidence=0.0)
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
        return _response(True, action=action, categories=categories, answer=f"Known source categories: {', '.join(categories.keys()) or 'none' }", confidence=1.0)

    if action == "remove_source_category":
        name = _normalise_category(str(args.get("category", "")))
        existed = name in categories
        categories.pop(name, None)
        _save_sources(sources_data)
        return _response(True, action=action, category=name, answer=(f"Removed source category '{name}'." if existed else f"Source category '{name}' did not exist."), confidence=1.0)

    query = str(args.get("query", "")).strip()
    if not query:
        return _response(False, error="Missing required argument: query", confidence=0.0)

    if not _has_internet():
        return _response(False, query=query, error="No internet connection was detected from the Jarvis host.", answer="I cannot reach the internet from this machine right now. Check DNS, firewall, proxy, or outbound HTTPS access.", confidence=0.0)

    if _looks_like_weather(query):
        return _weather_handler(query, max_results, args.get("location"))

    if _looks_like_football(query):
        return _bbc_football_handler(query, max_results)

    if _looks_like_trending(query):
        return _trending_handler(query, max_results)

    news_topic = _looks_like_news(query)
    if news_topic:
        return _news_handler(query, news_topic, max_results)

    learned = _detect_learned_category(query, categories)
    if learned:
        return _search_trusted_category(learned, query, categories, max_results)

    return _duckduckgo_html(query, max_results)
