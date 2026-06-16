---
name: avenfield-browser-render
description: "Render, scrape, screenshot, or extract from ANY website using Cloudflare Browser Rendering. Use ANY TIME Momin wants to pull content from a URL or list of URLs — 'render this site', 'scrape these domains', 'get the markdown for', 'screenshot this page', 'pull the homepage content', 'crawl this site', 'extract X from these websites', 'what does this company's site say', 'grab the about page', or any lead-research / personalization task that needs live website content. ALSO the go-to when Momin gives a Google Sheet of URLs and wants the rendered markdown (or extracted JSON) written into the next column — use render_sheet.py for that. This is the raw Cloudflare Browser Rendering capability with full option pass-through — single page or batch, markdown / HTML / screenshot / PDF / structured-JSON / element-scrape / links. It replaces the old console's fixed render flow: here you can render anything with any options. Does NOT verify emails, write copy, or push to Instantly — it only fetches/renders web content."
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

**Batch — many URLs at once, IN PARALLEL** (one per line on stdin → JSONL out, one object per URL). Default 6 concurrent renders; bump with `--concurrency`. Output order matches input order. Each line: `{"url","ok","status","result"}`, with retries on transient errors:
```bash
printf 'https://a.com\nhttps://b.com\nhttps://c.com\n' \
  | python3 .../cf_render.py markdown --batch --concurrency 8
```

## ⭐ Sheet → render → next column (the fast default for lead lists)

When Momin gives a **Google Sheet (link or ID) of URLs** and says "render these / give me the markdown in the next column", use **`render_sheet.py`** — it reads the URL column, renders every URL **concurrently**, and writes each result into the output column in a single Sheets write. No looping by hand.

```bash
R=~/.claude/skills/avenfield-browser-render/render_sheet.py

# URLs in column A, header in row 1, markdown lands in column B:
python3 $R --sheet "<sheet URL or ID>" --url-col A --start-row 2

# Choose tab, output column, endpoint, and parallelism:
python3 $R --sheet <ID> --tab Leads --url-col C --out-col D \
  --endpoint markdown --concurrency 10 --start-row 2 --out-header "Markdown"

# Structured extraction instead of raw markdown (CF runs the LLM server-side):
python3 $R --sheet <ID> --url-col A --start-row 2 --endpoint json \
  --body '{"prompt":"founder, city, one-line value prop","response_format":{...}}'

# Preview first — render but DON'T write, see the first 5 rows:
python3 $R --sheet <ID> --url-col A --start-row 2 --dry-run

# LIVE — watch the sheet fill row-by-row, with a running count/rate in H1:
python3 $R --sheet <ID> --url-col A --start-row 2 \
  --live --flush-every 25 --status-cell H1
```

**Live mode** (`--live`): instead of writing once at the end, results are flushed
to the output column every `--flush-every` completions (default 25) as renders
finish — so a big run visibly fills in real time. `--status-cell H1` writes a
`"850/1310 done · ok=817 · 105/min"` ticker to that cell so you can watch speed
and ETA. Use it for any run big enough that you'd want to see progress.

Behaviour worth knowing:
- `--out-col` defaults to the column right of `--url-col`. Point it at an EMPTY column so nothing is overwritten — writes are surgical (only the cells we computed).
- `--start-row 2` skips a header row (default is 1). Row alignment is preserved: row N's URL → row N's output cell, blank URL rows are skipped.
- Cells are truncated to `--max-chars` (default 45000; Google's hard cap is 50000) with a `…[truncated]` marker.
- Failures aren't silent — the cell gets a `[render failed <status>: …]` marker and the run summary lists `failed_rows`.
- The target sheet must be shared (Editor) with the SA email (`avenfield-sheets/sheets.py whoami`); a 403 means it isn't.

**Sanity pass before writing** (per CLAUDE.md): confirm it's the right sheet/tab, the URL column is the one you think, and the output column is empty. For a big run, do a `--dry-run` first.

For one-off research ("what does this company do?"), a single `markdown` call is enough — read it and answer. For a pasted/CSV list (not a sheet), pipe it through `--batch` and read the JSONL.

## Notes
- `markdown` is the default best choice for anything an LLM will read.
- Pass timeouts/wait conditions in `--body` for slow or JS-heavy sites (`gotoOptions.waitUntil: "networkidle0"`).
- The script prints Cloudflare's `result` directly; errors print the API's error payload so you can see status + reason.
- Cost is ~$0.005 per page — fine for hundreds, mention it before thousands.
