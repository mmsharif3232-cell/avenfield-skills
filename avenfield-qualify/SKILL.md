---
name: avenfield-qualify
description: "Qualify a lead list against an Ideal Customer Profile (ICP) from scraped website content, then extract only the winning lead rows into a new sheet/tab. Use ANY TIME Momin wants to filter a list down to the right kind of company — 'are these actually M&A firms', 'qualify these leads', 'which of these are real <X> companies', 'separate the good leads from the junk', 'build a clean campaign list from the qualified ones'. Two steps: (1) classify — read each company's rendered markdown and label it (is_ma true/false, type, confidence, reason) via avenfield-personalize + an ICP preset; (2) extract — pull every raw lead row whose website qualified into a fresh tab, carrying the qualification columns across. Does NOT render (use avenfield-browser-render first), verify emails (avenfield-verify), or upload (avenfield-instantly-upload)."
---

# Avenfield Qualify

Turn a big scraped list into a clean, on-ICP campaign list. Classify each unique
company from its website markdown, then extract the lead rows for the winners.
Built on top of `avenfield-browser-render` (which produced the markdown) and
`avenfield-personalize` (which runs the GPT classification).

## Pipeline position
`render (browser-render) → qualify.classify → qualify.extract → verify → upload`

Render once per **unique website**; qualify operates on those unique rows; then
`extract` fans the verdict back out to the **per-contact lead rows** for upload.

## Step 1 — classify (what kind of company is this?)

Classification is GPT reading the scraped markdown against an ICP preset and
emitting structured labels. It delegates to `avenfield-personalize`, so you get
test-first, a cost estimate, concurrency, **auto-retry on rate-limit failures**,
and live status for free.

```bash
Q=~/.claude/skills/avenfield-qualify/qualify.py
# leads tab cols: A=url … F=scrape_markdown ; write verdict from col G
python3 $Q classify --sheet <ID> --tab leads --content-col F --key-col A \
      --icp ma_qualify --out-col G --test 15 --go     # 15-row test
python3 $Q classify --sheet <ID> --tab leads --content-col F --key-col A \
      --icp ma_qualify --out-col G --run --go         # full run
```
`--go` runs it; omit `--go` to just print the underlying personalize command.
Default concurrency 10–11 is safe on the current OpenAI key (it auto-retries the
handful that hit a rate limit — they recover, do not leave them failed).

### The ICP preset (`presets/ma_qualify.json`)
One preset = one ICP. The M&A one emits four columns:

| col | var | values |
|-----|-----|--------|
| G | `is_ma` | `true` / `false` |
| H | `ma_type` | `M&A advisory` · `business broker` · `investment bank` · `private equity` · `exit planning` · `wealth management` · `insurance` · `accounting` · `lending` · `recruiting` · `other` |
| I | `ma_confidence` | `high` · `medium` · `low` |
| J | `ma_reason` | one sentence (≤15 words) |

**What QUALIFIES (M&A ICP):** firms whose primary business is buying/selling
companies — M&A advisory (sell/buy-side), business brokers (lower-middle market),
investment banks with a deal practice, PE/family offices actively acquiring,
exit/succession advisory whose product is a business sale.
**What DOESN'T:** wealth management / financial planning, insurance, accounting/
tax, real estate, executive search, lending/mortgage (not deal-side), pure
consulting, portfolio/SaaS companies, and sites too thin to tell.

Confidence: **high** = site explicitly states it; **medium** = implied/mixed;
**low** = thin/blocked/undeterminable (preset forces `is_ma=false` + reason
"site content too thin to classify" when content is < 20 meaningful words).

To qualify a different ICP, copy the preset to `presets/<new_icp>.json`, rewrite
the prompt + vars + categories, and pass `--icp <new_icp>`.

## Step 2 — extract (keep only the winners' lead rows)

The classified tab is one row per unique website. The raw source tab is one row
per contact (many contacts share a website). `extract` matches them by
normalised URL and writes a new tab with only qualifying lead rows, carrying the
verdict columns across.

```bash
python3 $Q extract --sheet <ID> \
      --source-tab ma_advisers_us_instantly --source-url-col website \
      --qual-tab leads --qual-url-col url \
      --flag-col is_ma --flag-value true \
      --carry-cols ma_type,ma_confidence,ma_reason \
      --dest-tab qualified_leads \
      [--min-confidence high]          # optional: drop medium/low
      [--dry-run]                      # count + sample, write nothing
```
- URL matching is scheme/`www.`/trailing-slash/case-insensitive (`norm_url`).
- `--min-confidence high|medium|low` filters by the confidence column.
- Columns accept a **letter** (`E`) or a **header name** (`website`).
- Dest tab is created if missing, else cleared and rewritten (idempotent).
- After writing, automatically sets all rows to **21px height** and **CLIP wrap** so long markdown stays inside its cell and the sheet stays readable.
- Prints `{qualified_unique_sites, sites_with_lead_rows, qualified_lead_rows}`.

## Hard-won lessons (baked in)
- **Dedupe to unique URLs before classifying.** A leads tab built one-row-per-
  contact wastes API calls (and money) re-scoring the same site. Render +
  classify the **unique** sites, then `extract` fans the verdict back out.
- **Unrendered sites can't be classified.** Sites that never rendered (dead DNS,
  Cloudflare, JS-only) land as blank `is_ma`. Decide explicitly whether to
  include or drop them before upload — they are NOT auto-qualified.
- **Rate limits are transient.** At concurrency 10–11 a few rows 429; the
  personalize auto-retry recovers them. A nonzero `api_failures` with equal
  `recovered_on_retry` is fine.
- **Confidence gates quality, not just truth.** `is_ma=true, confidence=high` is
  your safe core; `medium` is reviewable; `low` is forced to false. For a premium
  list, gate the campaign on `--min-confidence high`.
- **Real M&A lists run ~60–65% qualified.** On the M&A-advisers-US sheet: 753
  unique sites → 476 qualified (195 M&A advisory, 145 IB, 64 brokers, 49 exit
  planning, 22 PE), 219 disqualified (mostly wealth mgmt / thin sites), 58
  unrendered. Expect a real chunk to fall out — that's the point.

## Does NOT
Render sites (use `avenfield-browser-render`) · verify emails
(`avenfield-verify`) · scan copy (`avenfield-spamguard`) · push to Instantly
(`avenfield-instantly-upload`). It classifies and extracts — nothing leaves the
sheet.
