# web_search v0.5.0

Free Jarvis web lookup plugin.

## Important install note

If Jarvis preview says:

```text
Missing approval phrase: APPROVE OVERWRITE: backend/plugins/tools/web_search/tool.py
```

paste this exact phrase into the approval phrase box and click Apply:

```text
APPROVE OVERWRITE: backend/plugins/tools/web_search/tool.py
```

That is not a plugin bug. Jarvis is correctly protecting an existing plugin file from being overwritten.

## Optional dependency

For best HTML parsing, install BeautifulSoup in Jarvis' Python environment:

```bash
source ~/.venvs/main/bin/activate
pip install beautifulsoup4
```

The plugin still works without it, but parsing is less accurate.

## Examples

```json
{"query":"weather forecast for Bristol tomorrow"}
```

```json
{"query":"What were today's football results in the Premier League?"}
```

```json
{"query":"latest space news"}
```

```json
{"query":"top 10 most popular topics today"}
```

```json
{
  "action":"add_source_category",
  "category":"space_news",
  "description":"Latest space and astronomy news",
  "sources":["https://www.nasa.gov/news/", "https://www.esa.int/Newsroom"],
  "rss":["https://www.nasa.gov/news-release/feed/"],
  "keywords":["space", "nasa", "astronomy", "rocket"]
}
```
