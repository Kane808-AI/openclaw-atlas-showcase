# TOOLS.md — Echo (scraper)
# Agent ID: scraper
# Last updated: 2026-04-23

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` -> `ddgs-search "your query" 5 duckduckgo`
- Wrong: calling `ddgs-search(...)` as a tool name

**Native `web_search` has no API provider. Do not use it.**
Use exec + ddgs-search. Always use `duckduckgo` or `bing` backend. Never `google` (TTY bug).

---

## Scraping Tool Hierarchy

Always follow this order. Do not skip steps.

### 1. Public APIs (best)
Check if the target has a public API before scraping HTML. Common ones:
- Google Places API (business listings)
- Yelp Fusion API (reviews, business data)
- Clutch/DesignRush (may have API or structured feeds)
- Social platforms (rate-limited but structured)

### 2. ddgs-search or HTTP fetch (fast)
For simple lookups, search result scraping, or fetching static pages:
```
exec("ddgs-search 'query here' 5 duckduckgo")
```
Or direct HTTP:
```python
import requests
r = requests.get(url, headers={'User-Agent': 'OpenClaw/1.0'})
```

### 3. requests + BeautifulSoup (structured extraction)
For parsing HTML DOM:
```python
from bs4 import BeautifulSoup
import requests
r = requests.get(url)
soup = BeautifulSoup(r.text, 'html.parser')
```

### 4. Browser control (last resort)
ONLY when JavaScript rendering or authentication is required, or methods 1-3 fail.

---

## Skills to Invoke (on-demand only)

Read the relevant skill before starting these workflow types:
- `~/.openclaw/workspace/skills/youtube-automation-ops/SKILL.md` — when collecting channel examples, title patterns, content pillars, or performance comps for YouTube workflows
- `~/.openclaw/workspace/skills/affiliate-content-ops/SKILL.md` — when gathering product angles, compliance context, or competitive affiliate examples
- `~/.openclaw/workspace/skills/pinterest-ops/SKILL.md` — when scraping Pinterest keyword, board, or pin-pattern data

## Data Output

### File Formats
- CSV: default for tabular data. Use `csv` module, not manual string building.
- JSON: for structured/nested data or API consumption.
- Markdown tables: for small datasets going into reports or Telegram.

### Output Location
Save scraped data to: `~/.openclaw/workspace/data/scrapes/`
Filename format: `YYYY-MM-DD-<source>-<description>.csv`

### Metadata
Every output file must include (as a header comment or companion `.meta.json`):
- Source URL(s)
- Extraction date
- Row count
- Any known gaps or limitations
- Rate limiting encountered (if any)

---

## Rate Limiting

- Minimum 1-2 second delay between requests to same domain
- If rate-limited (429), back off exponentially. Do not retry immediately.
- Cache results in `data/scrapes/` to avoid re-fetching
- Never run parallel requests against the same domain

## Ethics Checklist

Before any scrape:
1. Check `robots.txt` at the target domain
2. Verify no Terms of Service prohibition
3. Use public APIs if available
4. Rate-limit all requests
5. If scraping personal data, confirm with Chris first

---

## Claude Code Delegation

For complex multi-step scraping tasks (2+ terminal commands, pagination, multi-page crawls):
```
exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt 'task description'")
```

## Python Environment

Use the system Python or create a venv if packages are needed:
```
python3 -m pip install beautifulsoup4 requests --break-system-packages
```

Or for isolation:
```
python3 -m venv ~/.openclaw/venv/scraper
source ~/.openclaw/venv/scraper/bin/activate
pip install beautifulsoup4 requests
```
