---
name: avenfield-browser-render
description: "Render, scrape, screenshot, or extract from ANY website using Cloudflare Browser Rendering. Use ANY TIME Momin wants to pull content from a URL or list of URLs — 'render this site', 'scrape these domains', 'get the markdown for', 'screenshot this page', 'pull the homepage content', 'crawl this site', 'extract X from these websites', 'what does this company's site say', 'grab the about page', or any lead-research / personalization task that needs live website content. This is the raw Cloudflare Browser Rendering capability with full option pass-through — single page or batch, markdown / HTML / screenshot / PDF / structured-JSON / element-scrape / links. It replaces the old console's fixed render flow: here you can render anything with any options. Does NOT verify emails, write copy, or push to Instantly — it only fetches/renders web content."
---

# Avenfield Browser Render

Raw access to **Cloudflare Browser Rendering** for lead research and content extraction. Run a real headless browser against any URL and get back markdown, HTML, a screenshot, a PDF, scraped elements, structured JSON, or links — single page or a whole list.

The capability is `cf_render.py` in this skill's directory. Credentials (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN) load automatically from `~/.avenfield/credentials.env` or the console `.env` — you don't manage keys.

## When to reach for which endpoint

| Goal | Endpoint |
|---|---|
| Read a page's content for extraction/personalization | `markdown` (cleanest for LLM reading) |
| Need the raw post-JS DOM | `content` |
| Pull specific fields by CSS selector | `scrape` |
| Let Cloudflare extract structured data with a prompt+schema | `json` |
| Visual proof / design reference | `screenshot` (→ `--out file.png`) |
| Save the page as PDF | `pdf` (→ `--out file.pdf`) |
| Map a site's links (find about/team/contact pages) | `links` |
| HTML + screenshot together | `snapshot` |

## How to run it

Always invoke with the system python so deps are present:

```bash
python3 ~/.claude/skills/avenfield-browser-render/cf_render.py <endpoint> --url <URL> [--body '<json>'] [--out file]
```

**Simple — one page to markdown:**
```bash
python3 .../cf_render.py markdown --url https://acme-agency.com
```

**Full control — any Cloudflare option via `--body`** (merged with `--url`):
```bash
python3 .../cf_render.py content --url https://acme.com \
  --body '{"gotoOptions":{"waitUntil":"networkidle0","timeout":45000},
           "waitForSelector":{"selector":"footer"},
           "rejectResourceTypes":["image","font","media"]}'
```

**Scrape specific elements:**
```bash
python3 .../cf_render.py scrape --url https://acme.com \
  --body '{"elements":[{"selector":"h1"},{"selector":"a[href*=mailto]"}]}'
```

**Structured extraction (Cloudflare runs the LLM server-side):**
```bash
python3 .../cf_render.py json --url https://acme.com \
  --body '{"prompt":"Extract founder name, city, and a one-line value prop",
           "response_format":{"type":"json_schema","json_schema":{"type":"object",
             "properties":{"founder":{"type":"string"},"city":{"type":"string"},
             "value_prop":{"type":"string"}}}}}'
```

**Screenshot / PDF (binary → file):**
```bash
python3 .../cf_render.py screenshot --url https://acme.com --out acme.png \
  --body '{"viewport":{"width":1440,"height":900},"screenshotOptions":{"fullPage":true}}'
```

**Batch — many URLs at once** (one per line on stdin → JSONL out, one object per URL):
```bash
printf 'https://a.com\nhttps://b.com\nhttps://c.com\n' \
  | python3 .../cf_render.py markdown --batch
```

## Working with lead lists

When Momin gives you a list of domains (CSV, sheet, pasted), the usual flow is:
1. Pull the URL column.
2. Run `--batch markdown` (or `--batch json` with a schema) over them.
3. Read each result and produce whatever he asked for — a personalization line, a summary, an extracted field — and write it back to wherever the leads live (sheet, CSV, or just the chat).

For one-off research ("what does this company do?"), a single `markdown` call is enough — read it and answer.

## Notes
- `markdown` is the default best choice for anything an LLM will read.
- Pass timeouts/wait conditions in `--body` for slow or JS-heavy sites (`gotoOptions.waitUntil: "networkidle0"`).
- The script prints Cloudflare's `result` directly; errors print the API's error payload so you can see status + reason.
- Cost is ~$0.005 per page — fine for hundreds, mention it before thousands.
