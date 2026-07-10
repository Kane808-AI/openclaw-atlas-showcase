# TOOLS.md — Scout

## Web Search (Primary Tool)

Scout's main tool. Use exec + ddgs-search (never native web_search):
```
exec("ddgs-search 'query' 5 duckduckgo")
```
Use `duckduckgo` or `bing` backend only. Google backend has TTY bugs in non-interactive mode.

Multiple searches per research run. Include source URLs in every finding.

## HTTP Fetch (for specific URLs)

```
web_fetch("https://example.com")
```

Use for fetching specific known URLs: articles, product pages, trend reports.

## Ideas Backlog — DGC Products

Log qualifying products via Python script (NOT gog sheets — it doesn't work):
```bash
~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/add_to_tiktok_ideas_backlog.py '<json>'
```
JSON format: `[{"Product Name": "...", "Source": "...", "Description": "..."}]`

Status auto-set to "New". Never mark as anything else — Atlas handles status.

## Atlas Tasks Sheet

For non-DGC ideas (content angles, Brand75 opportunities, personal TikTok ideas):
- Sheet ID: `SHOWCASE_ATLAS_TASKS_SHEET_ID`
- Range: `Atlas Tasks!A:K`
- Append via:
```bash
~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_sheets_tool.py append \
  SHOWCASE_ATLAS_TASKS_SHEET_ID "Atlas Tasks!A:K" \
  --values-json '[["idea", "...", "inbox", "...", ...]]'
```

## Trend Research Sources

Primary sources to check for trend research:
- Exploding Topics: exploding-topics.com (use HTTP fetch or browser tool)
- Google Trends: trends.google.com (use browser tool)
- TikTok trending: indirect — search for hashtag volumes via ddgs-search
- Kalodata: kalodata.com (TikTok Shop affiliate data — browser tool)
- FastMoss: fastmoss.com (TikTok creator data — browser tool)

## Skills to Invoke (on-demand only)

Read the relevant skill before executing these workflow types:
- `~/.openclaw/workspace/skills/youtube-automation-ops/SKILL.md` — when researching YouTube channel ideas, title banks, content pillars, or repurposing opportunities
- `~/.openclaw/workspace/skills/affiliate-content-ops/SKILL.md` — when researching affiliate products, angles, compliance-safe hooks, or DGC-related content lanes
- `~/.openclaw/workspace/skills/pinterest-ops/SKILL.md` — when researching Pinterest traffic opportunities, pin formats, or keyword patterns

## Browser Tool (Last Resort)

Usage hierarchy: ddgs-search → HTTP fetch → browser control

Browser control only when JS rendering or auth required and earlier steps failed.

```
exec("node $HOME/.openclaw/scripts/browser_tool.js start --session atlas")
exec("node $HOME/.openclaw/scripts/browser_tool.js navigate --url 'https://example.com'")
exec("node $HOME/.openclaw/scripts/browser_tool.js read --selector 'div.main' --limit 5")
exec("node $HOME/.openclaw/scripts/browser_tool.js stop")
```

Always use `--session atlas`. Never per-site session names.

## DGC Product Brief Template

Every DGC product brief must include all 8 sections:
1. Product name + price range (search Amazon and TikTok Shop)
2. Why it's trending (Exploding Topics or Google Trends data point)
3. TikTok performance data (hashtag volumes, view counts — via ddgs-search)
4. What's selling (Kalodata or FastMoss affiliate data)
5. Top performing video formats (demo, unboxing, reaction, POV, list?)
6. Hook ideas (2-3 options in "funny dad" voice — first 3 seconds)
7. Trending audio suggestions (sounds used with similar content)
8. Recommended angle for Dad's Gadget Corner

Price research requirements:
- Retail price (Amazon or brand site)
- TikTok Shop price if listed
- Estimated affiliate commission (5-20% range — calculate both ends)
- Whether cheaper alternatives exist

Prioritize products in the $20-$80 range. Flag anything over $100 as high-barrier.

## Slack Reporting

Digests go to #scout-research. Format: top 3 findings, each with Platform, Trend/Tool, Why it fits, Which account, Source URL, Suggested angle.

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Never post content directly — Ideas Backlog only.
- Always include source URL with every logged idea.
- Never trigger TikTok Brain pipeline independently.
- Never spawn sub-agents.
- If nothing genuinely interesting found in a research run, log nothing and stay quiet.
