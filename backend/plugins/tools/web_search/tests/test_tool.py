from __future__ import annotations

import json
from pathlib import Path

import requests

from plugins.tools.web_search import tool


def _response(text: str, url: str = "https://example.com/") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = text.encode("utf-8")
    response.url = url
    response.headers["content-type"] = "text/html"
    return response


def _json_response(data: dict, url: str = "https://example.com/") -> requests.Response:
    response = _response(json.dumps(data), url)
    response.headers["content-type"] = "application/json"
    return response


def test_bristol_weather_uses_direct_api(monkeypatch, tmp_path: Path) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)

    def fake_get(url: str, params=None, **kwargs):
        if "geocoding-api" in url:
            return _json_response({"results": [{"name": "Bristol", "admin1": "England", "country": "United Kingdom", "latitude": 51.45, "longitude": -2.59}]}, url)
        return _json_response(
            {
                "daily": {
                    "time": ["2026-05-03", "2026-05-04"],
                    "weather_code": [61, 3],
                    "temperature_2m_max": [14.2, 16.1],
                    "temperature_2m_min": [8.5, 9.2],
                    "precipitation_probability_max": [70, 20],
                    "wind_speed_10m_max": [18, 12],
                }
            },
            url,
        )

    monkeypatch.setattr(tool, "_get", fake_get)

    result = tool.run({"query": "weather in Bristol tomorrow"})

    assert result["ok"] is True
    assert result["mode"] == "direct_api"
    assert result["handler"] == "weather"
    assert "Weather for Bristol" in result["answer"]


def test_latest_oil_prices_collects_trusted_rag_documents(monkeypatch, tmp_path: Path) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)

    def fake_get(url: str, *args, **kwargs):
        if url.endswith("/rss.xml"):
            return _response(
                """
                <rss><channel>
                  <item>
                    <title>Oil prices rise as Brent crude trades near $82 a barrel</title>
                    <link>https://www.reuters.com/markets/commodities/oil-prices</link>
                    <description>Brent crude oil prices rose after OPEC signalled tighter supply.</description>
                  </item>
                  <item>
                    <title>Technology shares edge higher</title>
                    <link>https://www.reuters.com/markets/technology/stocks</link>
                    <description>Chipmakers gained in afternoon trading.</description>
                  </item>
                </channel></rss>
                """,
                url,
            )
        return _response(
            """
            <html><head><title>Oil prices rise</title></head><body>
              <nav>Markets menu</nav>
              <article>
                <h1>Oil prices rise as Brent crude trades near $82 a barrel</h1>
                <p>Brent crude oil prices rose after OPEC signalled tighter supply.</p>
                <p>Crude traders said barrels were supported by energy demand.</p>
                <p>Technology shares moved in a separate market update.</p>
              </article>
            </body></html>
            """,
            url,
        )

    monkeypatch.setattr(tool, "_get", fake_get)

    result = tool.run({"query": "latest oil prices"})

    assert result["ok"] is True
    assert result["mode"] == "trusted_rag"
    assert result["category"] == "finance_energy"
    assert result["documents"]
    assert "Brent crude oil prices rose" in result["documents"][0]["text"]
    assert result["documents"][0]["url"].startswith("https://www.reuters.com/")


def test_premier_league_collects_trusted_rag_documents_and_tables(monkeypatch, tmp_path: Path) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)
    monkeypatch.setattr(
        tool,
        "_get",
        lambda *args, **kwargs: _response(
            """
            <html><body>
              <main>
                <h1>Premier League fixtures</h1>
                <p>Chelsea face Arsenal in the Premier League on 05 May.</p>
                <table>
                  <tr><th>Date</th><th>Fixture</th><th>Competition</th></tr>
                  <tr><td>05 May</td><td>Chelsea v Arsenal</td><td>Premier League</td></tr>
                </table>
              </main>
            </body></html>
            """,
            "https://www.bbc.co.uk/sport/football/scores-fixtures",
        ),
    )

    result = tool.run({"query": "Premier League fixtures"})

    assert result["ok"] is True
    assert result["mode"] == "trusted_rag"
    assert result["category"] == "sports"
    assert result["documents"][0]["tables"]
    assert "Chelsea v Arsenal" in result["documents"][0]["tables"][0]


def test_latest_space_news_collects_relevant_documents(monkeypatch, tmp_path: Path) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)
    monkeypatch.setattr(
        tool,
        "_get",
        lambda *args, **kwargs: _response(
            """
            <html><head><title>NASA prepares Mars telescope launch</title></head><body>
              <article>
                <h1>NASA prepares Mars telescope launch</h1>
                <p>The space agency said the telescope will study Mars from orbit.</p>
                <p>Rocket engineers completed launch checks.</p>
              </article>
            </body></html>
            """,
            "https://www.nasa.gov/news/mars-telescope",
        ),
    )

    result = tool.run({"query": "latest space news"})

    assert result["ok"] is True
    assert result["mode"] == "trusted_rag"
    assert result["category"] == "space_news"
    assert "NASA prepares Mars telescope launch" in result["documents"][0]["text"]


def test_category_with_sources_but_no_relevant_content_reports_extraction_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)
    monkeypatch.setattr(
        tool,
        "_get",
        lambda *args, **kwargs: _response(
            """
            <rss><channel>
              <item>
                <title>City council approves new park</title>
                <link>https://space.example/local</link>
                <description>The project adds walking paths and benches.</description>
              </item>
            </channel></rss>
            """
        ),
    )

    result = tool.run({"query": "latest space news"})

    assert result["ok"] is True
    assert result["mode"] == "needs_sources"
    assert result["teach_request"] is True


def test_quantum_news_without_sources_requests_teaching(monkeypatch, tmp_path: Path) -> None:
    _patch_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(tool, "_has_internet", lambda: True)

    result = tool.run({"query": "latest quantum chip news"})

    assert result["ok"] is True
    assert result["mode"] == "needs_sources"
    assert result["teach_request"] is True
    assert "2-5 reliable sources" in result["answer"]


def _patch_sources(monkeypatch, tmp_path: Path) -> None:
    sources_path = tmp_path / "web_sources.json"
    sources_path.write_text(
        json.dumps(
            {
                "strict_mode": True,
                "cache_ttl_seconds": 900,
                "categories": {
                    "space_news": {
                        "description": "Space news",
                        "sources": ["https://www.nasa.gov/news/"],
                        "rss": ["https://www.nasa.gov/news-release/feed/"],
                        "keywords": ["space", "nasa", "astronomy", "mars", "telescope"],
                    },
                    "finance_energy": {
                        "description": "Energy markets",
                        "sources": ["https://www.reuters.com/markets/commodities/"],
                        "rss": ["https://www.reuters.com/rss.xml"],
                        "keywords": ["oil", "oil prices", "crude", "brent", "opec", "barrel"],
                    },
                    "sports": {
                        "description": "Sports",
                        "sources": ["https://www.bbc.co.uk/sport/football/scores-fixtures"],
                        "rss": [],
                        "keywords": ["football", "fixtures", "chelsea", "arsenal", "premier league"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tool, "SOURCES_FILE", str(sources_path))
