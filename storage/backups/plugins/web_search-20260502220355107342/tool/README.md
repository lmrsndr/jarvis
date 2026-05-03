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
