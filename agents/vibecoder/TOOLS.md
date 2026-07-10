# TOOLS.md — Kai (vibecoder)
# Agent ID: vibecoder
# Last updated: 2026-04-23

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` -> `ddgs-search "your query" 5 duckduckgo`
- Wrong: calling `ddgs-search(...)` as a tool name

**Native `web_search` has no API provider. Do not use it.**
Use exec + ddgs-search. Always use `duckduckgo` or `bing` backend. Never `google` (TTY bug).

---

## Frontend Stack

| Component | Tool | Notes |
|-----------|------|-------|
| Framework | Next.js (React) | App Router, TypeScript |
| Styling | Tailwind CSS | Utility-first, responsive breakpoints |
| Component reference | shadcn/ui | For common UI patterns (buttons, cards, forms, modals) |
| Icons | Lucide React | Consistent icon set |
| Hosting | Netlify | Preview URLs on branches for design review |
| Source control | GitHub (Kane808-AI org) | Feature branches for design work |

## Design Tools

Kai does not use Figma or external design tools. Design work happens in code (React/Tailwind components) or as written specs handed to Leo.

When mocking up layouts:
- Build directly in JSX/Tailwind on a feature branch
- Use Netlify preview URLs for Chris approval
- Specify responsive behavior at all breakpoints: mobile (< 640px), tablet (640-1024px), desktop (> 1024px)

## Accessibility Testing

- Color contrast: use WebAIM contrast checker or browser dev tools
- Lighthouse accessibility audit: run via CLI or browser
- Screen reader: test with VoiceOver (macOS native)
- Touch targets: verify 44x44px minimum on mobile preview

## CRO and Analytics

- GA4 events to reference: `form_submit`, `cta_click`, `scroll_depth`, `chat_open`, `booking_start`
- Scroll depth and click patterns available in GA4 for data-informed design decisions
- A/B testing: no formal tool yet. Use branch-based previews for manual comparison.

## Image Generation

For design assets, mockup images, or placeholder visuals:
- Skill: `workspace/skills/gemini-image-gen`
- Script: `scripts/gen.py`
- Engine: imagen (Imagen 4 via Google AI Studio)
- Usage: `cd ~/.openclaw/workspace/skills/gemini-image-gen && ~/.openclaw/venv/google/bin/python3 scripts/gen.py --engine imagen --prompt 'your prompt'`

## Claude Code Delegation

For complex multi-file component builds (2+ terminal commands):
```
exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt 'task description'")
```

## Working Directories

- Growth engine sites: `Kane808-AI/<site-name>/` on GitHub
- Design components: within `src/components/` of each site repo
- Design system patterns: document in site repo `docs/design-system.md` (create if missing)
