# M&A Advisory

## 1. Header

- **Status:** experimental (0 campaigns)
- **TAM estimate:** TBD — populate after first pull
- **Campaigns run:** 0
- **Last updated:** 2026-04-22
- **Cross-references:** (none yet)

---

## 2. Definition

**What counts:** Any firm providing M&A advisory services — buy-side or sell-side transaction advisory as a named service offering.

**Broad inclusion rule:** If a firm advises on M&A transactions, it qualifies. Full stop. Size, sector focus, independence, and sub-model are NOT disqualifiers. A 10-person LMM boutique and a 2,500-person global firm both qualify if M&A advisory is a service they offer.

**Sniff test (≤15 seconds):** Does the firm's website, marketing, or team-bio language reference advising clients on acquisitions, divestitures, sell-side, buy-side, or mergers as a core service?

**Span at launch:** Confirmed seeds cover ~30 employees to ~2,500 employees; pure-play boutiques to full-service banks; sector specialists (insurance, consumer goods, healthcare) to cross-sector generalists.

---

## 3. Seed Companies

### 3a. CONFIRMED — truth-set anchors (13)

| # | Firm | Rationale |
|---|---|---|
| 1 | Sica \| Fletcher | Insurance / financial services sector boutique, ~30 ppl, pure advisory |
| 2 | Murphy McCormack Capital Advisors | Independent LMM boutique, family-owned target |
| 3 | MidCap Advisors | LMM sell-side across industries |
| 4 | Protegrity Advisors | $10M–$100M revenue LMM advisory |
| 5 | TREP Advisors | Sell-side succession for business owners |
| 6 | Windsor Drake | Sell-side specialist for founders / shareholders |
| 7 | Financo | Consumer-goods sector boutique, 20–30 ppl |
| 8 | Corporate Finance Associates | 65+ yr independent LMM advisory. **VERIFY:** some sources suggest structural changes — confirm still independent before relying on first-run output |
| 9 | EBB Group | National multi-sector middle-market advisory |
| 10 | Leerink Partners | Healthcare-focused advisory + capital markets (M&A is M&A — qualifies) |
| 11 | Harris Williams | ~400 ppl, PNC-owned, middle-market M&A |
| 12 | Lincoln International | Global independent, M&A across sectors |
| 13 | Houlihan Lokey | ~2,500 ppl, top league-table M&A |

### 3b. FLAGGED — calibration anchors (bleed risks, NOT seeds)

Used to train the FLAGGED scorer. These firms appear in keyword pulls for M&A-adjacent vocabulary but do NOT provide M&A advisory.

| # | Firm | Why it bleeds |
|---|---|---|
| C1 | Bain & Company | Pure strategy consultancy. Does M&A due-diligence support, not deal advisory. Shares "transaction / advisory / strategic" vocabulary. |
| C2 | Edelman Financial Engines | Large RIA / wealth manager. "Advisory" in name, serves individuals, no corporate M&A. |
| C3 | Carr, Riggs & Ingram | Regional CPA firm with "business advisory services" branding but no M&A practice. Distinguishes audit / tax advisory from M&A advisory. |
| C4 | Datasite | Software vendor (VDR) sold TO M&A advisors. Appears in every M&A keyword pull because its marketing uses every M&A term. "Sells to the target, isn't the target." |

### 3c. AMBIGUOUS — grey-zone anchor (scorer calibration)

Used to train the AMBIGUOUS scorer so it doesn't over-flag genuine boundary cases.

| # | Firm | Why grey-zone |
|---|---|---|
| A1 | Transworld Business Advisors | Main Street business brokerage (franchise). Facilitates business sales at sub-$5M deal sizes. Some would call this M&A advisory, others wouldn't. Scorer should mark AMBIGUOUS rather than forcing a call. |

---

## 4. Filter Construction Notes (NOT paste-ready)

Prose starting points for the iteration loop. These inform where to seed and what language to try — they do **NOT** replace the seed → observe → derive → test cycle. Every campaign rebuilds filters from scratch using these notes as prior context.

### Industry tag starting points (AI Ark taxonomy)

- `Investment Banking` — primary tag for most seed firms
- `Financial Services` — common secondary tag; picks up firms not tagged as IB
- `Capital Markets` — appears for larger firms (Lincoln, Houlihan, Harris Williams)

Start broad; narrow only after seeing what the pull returns.

### P&S language patterns observed in seed descriptions

- **Explicit (high-signal):** "mergers and acquisitions," "M&A advisory," "sell-side advisory," "buy-side advisory"
- **Softer (higher AMBIGUOUS risk):** "transaction advisory," "transaction services," "strategic advisory," "corporate finance advisory"
- **Sector-qualified:** "[sector] M&A," "[sector] capital," "[sector] investment banking"

### Bleed categories observed via calibration anchors (candidate exclude patterns)

- **Strategy consulting** (Bain, McKinsey, BCG, and look-alikes) — often tagged adjacent to financial services
- **Wealth management / RIA** — "advisory" is a shared keyword with no M&A meaning
- **Pure CPA / audit** — "business advisory services" branding without transaction work
- **Deal-tech vendors** (VDRs, deal platforms, diligence software) — sell *to* M&A advisors; all the M&A keywords, none of the service

Still verified per run — do not preemptively exclude on first pass without observation.

### Title / seniority combos mapping to buyer persona

- Senior: Managing Director, Partner, Principal
- Mid (for larger firms): Director, Vice President
- True <20-person boutiques: Founder, Managing Partner

### Observed gotchas / starter notes

- AI Ark may tag smaller boutiques as `Financial Services` rather than `Investment Banking` — start broad.
- Sector-named firms (e.g., "Healthcare Capital," "Energy Advisors") are often legitimate sector-specialist M&A firms, not noise. See `~/avenfield/skills/ai-ark-expertise.md` on the sector-boutiques rule.
- Headcount spans ~10 to ~2,500+ across seeds. Do NOT apply a narrow employee-size filter unless the campaign explicitly targets a size band. This is a runtime parameter, not a vertical-level default.

---

## 5. Scorer Rules (prose)

Three tiers: CONFIRMED, FLAGGED, AMBIGUOUS. No LIKELY — under the broad-vertical rule, LIKELY collapses into CONFIRMED.

### CONFIRMED — include in list

- Firm's described services include "mergers and acquisitions," "M&A advisory," "buy-side," "sell-side," or explicit transaction-side work.
- Firm positions itself as an investment bank, M&A advisor, or boutique advisor on its own marketing.
- Sector-focused firms where a sector name is paired with "capital / partners / advisors / investment banking" AND description references transaction or advisory work.
- Firm size does NOT matter — a 2,500-person global bank qualifies just as a 15-person boutique does.

### FLAGGED — exclude from list

- Primary business is strategy consulting (management consulting, business strategy) with no M&A advisory practice.
- Primary business is wealth management, financial planning, or RIA serving individuals.
- Primary business is audit / tax / accounting with generic "business advisory" branding only.
- Primary business is real estate, IT services, staffing, legal, or any unrelated service that happens to use "acquisition" or "transaction" language.
- Firm is a software / platform vendor selling TO the M&A advisory market (VDR, deal management, data tools).

### AMBIGUOUS — drop from list (do not guess)

- Small business brokerage at Main Street deal sizes where "M&A advisory" framing is genuinely contested.
- Firm description uses "strategic advisory" or "transaction advisory" without clarifying whether this is M&A-side or consulting-side.
- Generic "corporate finance" or "financial advisory" framing with no transaction-specific language.

Additional rules accrete via Mode C approval as campaigns reveal stable patterns (3+ observation threshold).

---

## 6. Contamination Patterns (proven, observed 3+ campaigns)

*(Empty — no campaigns yet. Patterns promote here from section 7 after 3+ observations or explicit flagging.)*

---

## 7. Trending Observations (2x seen, not yet rule-worthy)

*(Empty — no campaigns yet. Patterns sit here after their 2nd observation; one more campaign and they become proposed rules at end-of-run report.)*

---

## 8. Campaign Log

*(Empty — no campaigns yet. Last ~5 runs live here: date, size, bounce rate, reply rate, notable filter changes.)*

---

## 9. Raw Observations Dump

*(Empty — auto-appends after each campaign. Append-only log of FLAGGED companies, their industries, descriptions. Messy by design; source material for trend detection.)*
