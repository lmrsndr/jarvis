# web_search v0.7.0

Strict trusted-source web lookup for Jarvis.

## Features

- Strict trusted sources only, no search-engine fallback
- Real weather via Open-Meteo
- BBC/Guardian football results extraction, best effort
- RSS-based news, science news, and space news
- Wikimedia top pageviews for popular topics
- Teachable source categories stored in `web_sources.json`
- Local caching in `.cache`
- Summarised answers, not raw HTML
- Confidence scoring based on number of usable results, source diversity, and source agreement

## Requirements

```bash
source ~/.venvs/main/bin/activate
pip install requests beautifulsoup4
```

`beautifulsoup4` is recommended. The plugin has a basic stdlib HTML fallback if it is missing.

## Teaching a new category

```json
{
  "action": "add_source_category",
  "category": "space_news",
  "description": "Trusted space news",
  "sources": ["https://www.nasa.gov/news/"],
  "rss": ["https://www.nasa.gov/news-release/feed/"],
  "keywords": ["space", "nasa", "astronomy"]
}
```

## Strict mode behaviour

If no category matches, or trusted sources cannot be read, the plugin returns `teach_request: true` instead of guessing.


## v0.7.1 note

If Jarvis replies with generic model text such as "I do not have direct access" and the API metadata does not show `tool_used` or `web_search`, the problem is not inside this plugin. The chat backend did not route the message to the plugin. Patch the backend tool-routing keywords to include: weather, forecast, temperature, rain, wind, football results, scores, fixtures, premier league, latest, news, current, today, tomorrow.

Direct plugin test from the Jarvis project root:

```bash
source ~/.venvs/main/bin/activate
python - <<'PY'
import json
from backend.plugins.tools.web_search.tool import run
print(json.dumps(run({"query":"weather in Bristol tomorrow"}), indent=2))
PY
```

Expected: JSON with `ok: true`, `handler: weather`, and a real Open-Meteo forecast.
