# AI Ark Expertise

> **Purpose**: Teach the List Agent how to build clean, launch-ready AI Ark lists at Avenfield. Consulted BEFORE any AI Ark action — filter construction, count check, pull intake, or post-run diagnosis.

---

## Core principle: same workflow as Apollo, different battleground filter

The **iteration loop is identical** to Apollo (see `apollo-expertise.md`):

```
Seed from known-good companies  →  Build filters  →  Count check  →  Diagnose bleed / TAM  →  Adjust filters  →  Repeat until confident
```

What changes is **where the iteration time goes**:

| Platform | Battleground filters | Frame filter |
|---|---|---|
| Apollo | Company keywords (include + exclude) | Industry |
| AI Ark | **Products & Services (include + exclude) + Company Keywords (include + exclude), used together** | Industry |

In AI Ark, P&S and company keywords are **contingent on each other** — they don't substitute, they reinforce. They catch different signals:
- **Products & Services (SMART mode)** = semantic / descriptive matching. Finds firms by what they *do*, paraphrased in plain English.
- **Company Keywords (WORD or SMART mode)** = matches the explicit tag/keyword array on the company record. Catches signal that's present as a literal tag but not obvious from the description.

**Use both.** A P&S phrase might miss a company whose description is vague but whose keywords array clearly says "M&A advisory." A keyword filter might miss a firm that doesn't tag itself cleanly but describes its service precisely. Running them together is how you hit precision AND recall.

Everything else — seeding, sampling discipline, TAM reality check, launch floor, decision-maker translation, write-back to `vertical-library.md` — carries over unchanged from Apollo.

---

## Filter hierarchy (where effort goes)

Rank by how much time the filter deserves in a typical AI Ark search:

1. **Products & Services — include AND exclude (SMART mode)** → battleground lever #1. Semantic matching: the phrases describe *what the firm does* in plain English.
2. **Company Keywords — include AND exclude (WORD or SMART mode)** → battleground lever #2. Matches the explicit tag/keyword array on company records. Catches literal signal the P&S phrase may miss.
3. **Industry (WORD mode)** → frame the search. Cast wide — 5–10 LinkedIn industry tags the target plausibly self-selects into. Exact match against LinkedIn's industry dropdown.
4. **Title / seniority (SMART mode)** → reason from org structure (see Campaign Inputs section below).
5. **Location, employee count, revenue, founded, company type** → coarse gates. Set once, adjust rarely.

**80%+ of iteration time lives in levers #1 + #2 combined.** Diagnose bleed by asking: is this a P&S issue (semantic phrase too loose), a keyword issue (missing exclude tag, or include tag too broad), or both? Often it's both — the two levers catch different contamination patterns.

If a search feels off, reach for P&S + company keywords first. Don't cut industry or size until battleground iteration is exhausted.

---

## The iteration loop (step by step)

### Step 0 — Seed from known-good companies

Same move as Apollo: pick **2–3 companies you know 100% fit the ICP**. But since AI Ark doesn't show per-company keyword tags the way Apollo does, the seeding observation targets are different:

- **Industry tag** → which LinkedIn industry bucket did this firm self-select into? Use that as a starting entry in your `industries` WORD list.
- **Company "About" / description text** → the language they use to describe themselves is your starting point for P&S SMART phrases. SMART mode matches semantically, so paraphrases of how the firm talks about itself work well.
- **Keywords array (if AI Ark exposes it)** → if the company record includes a `keywords` array, scan it for Apollo-style signal.
- **Employee size, founded year, location, company type** → sanity-check that your coarse filters would actually include this known-good company.

**When to re-run this step**: any time a search feels stuck — pick a fresh known-good company, inspect the above, check whether your filters would actually capture it.

### Step 1 — Build the starting filters

- Pick the **5–10 industries** that frame the vertical (WORD mode).
- Write **4–8 Products & Services include phrases** (SMART mode) describing what the firm does. Be specific — "practice management software for dental clinics" beats "healthcare software."
- Write **5–15 Products & Services exclude phrases** (SMART mode) for known contamination types the industry gate won't catch.
- Write **company keyword includes** (WORD or SMART) — literal tags the known-good companies from Step 0 had in their keyword arrays.
- Write **company keyword excludes** (WORD or SMART) — tags that clearly signal off-ICP firms in this vertical.
- Set titles / seniority for the buyer persona (see Campaign Inputs section).
- Apply location and other coarse gates per campaign inputs.

**Both battleground levers should have content from the start.** Don't lean entirely on P&S and leave keywords empty (or vice versa) — they catch different misses.

### Step 2 — Run the count check (size=1, FREE)

Run the Developer API count check with `size=1` to get `totalElements`. This is free. Never pull profiles through the Developer API — `size > 1` costs 0.5 credits per profile returned. That's a credit trap; always use the Web App API for actual pulls.

Compare count against a research-estimated universe for this ICP:

- **Count too high** (e.g., research says 5k companies but count returns 50k) → industry umbrella or P&S include is too broad, expect bleed.
- **Count too low** (<3,000 contacts, or <10% of estimated universe) → filters too tight, need to broaden.
- **Count in range** → proceed to pull and sample.

### Step 3 — Pull and sample for confidence (Momin's rule)

After pulling via the Web App API (free, concurrent), sample the result set at these positions (equivalent to Apollo's page sampling):

```
First 25  →  rows 250-275  →  rows 375-400  →  rows 750-775  →  rows 1,250-1,275  →  rows 2,500-2,525  →  last 25
```

(The Apollo equivalent was pages 1, 10, 15, 30, 50, 100, last at 25 rows per page — same pattern, just expressed in row ranges for a flat pulled list.)

If quality holds across the distribution, the list is clean. If bleed appears only in deeper samples, AI Ark's relevance ranking is putting looser matches at the back — your filters are letting them in.

### Step 4 — Diagnose bleed

For any sample:

1. **Scan company names** — look for ones that feel off-ICP.
2. **Open the company description** (summary / about text / industry tag).
3. **If the company is NOT our ICP** → inspect its industry tag + any keywords / P&S language in the record.
4. **Identify candidate contaminators** across BOTH battleground levers:
   - An overly-broad P&S include phrase that semantically matched this company?
   - A company keyword in your include list that's too broad, letting adjacent firms through?
   - A missing P&S exclude that would catch this pattern?
   - A missing keyword exclude (a tag that's clearly in this company's array that shouldn't be in the target set)?
   - An industry tag in your WORD list that's too shared with adjacent firms?

### Step 5 — Reverse-engineer the contaminator (test, don't guess)

Same principle as Apollo: when multiple filter elements look suspect, **don't pick one by gut — test each.**

- Tighten P&S include phrase A → re-run count → observe.
- Add P&S exclude phrase B → re-run count → observe.
- Add keyword exclude C → re-run count → observe.
- Keep the change that cleaned the list without collapsing TAM.

Because P&S and keywords are contingent, a single contamination pattern may need BOTH a P&S tweak AND a keyword tweak to fully resolve. Don't assume one lever is the whole answer. SMART mode is semantic and opaque — small changes to phrases can shift results in non-obvious ways. Empiricism wins.

### Step 6 — Repeat until confident

Confidence = sampling (Step 3) shows clean companies across the full distribution AND count is in a defensible range for the vertical.

### Step 7 — Hand off for export

Once confident, the filters become the final config. The agent runs the full pull, applies the company name cross-check (see Phase 5 below), shows the insight report, and awaits explicit approval before saving the list.

---

## Company name cross-check (Phase 5)

AI Ark pulls typically contain 10–30% off-ICP companies that passed both industry and P&S gates. A programmatic company-name scorer is **not optional** — run it on every record, not just spot checks. The scorer assigns each company to one of four tiers:

- **FLAGGED** — unambiguous noise (wrong business type). Drop.
- **CONFIRMED** — strong positive signal (name/industry/keyword leaves no doubt). Keep.
- **LIKELY** — weaker positive signal (probable match). Keep, expect slight noise.
- **AMBIGUOUS** — no signal either way. Drop — keeping these kills list quality.

**Derive scorer patterns fresh per vertical.** Do not copy from a prior vertical. Think about:
- What words unambiguously appear in the company name of a firm in this space?
- What industry tags are definitive vs. shared with adjacent noise?
- What name patterns are dead giveaways of the wrong business type?
- What combinations of signals together confirm a sector boutique (e.g., "Healthcare" + "Capital" → healthcare-focused M&A)?

**Sector boutiques rule**: firms like "Technology Partners," "Healthcare Capital," "Energy Advisors" are NOT noise — they're sector-specific boutiques. Only flag when the name clearly signals a non-target business. When in doubt on a pattern, make it LIKELY, not CONFIRMED.

---

## Insight report before export (Phase 5.5 — mandatory)

Before any export, the agent prints a full insight report to Momin and waits for explicit `export` approval:

1. **Score summary** — CONFIRMED / LIKELY / AMBIGUOUS / FLAGGED counts
2. **Top 20 companies by headcount** — name, size, industry, score tier
3. **Title distribution** — unique titles, descending count
4. **Geography breakdown** — top 10 states/cities
5. **Sample records** — 10 random clean contacts
6. **Noise audit** — 10 sample AMBIGUOUS + 10 sample FLAGGED companies with flag reasons

End with: *"Review the above. Reply `export` to save to AI Ark, or tell me what to adjust."*

**Never skip this.** This is Momin's visibility gate before any action is taken.

---

## TAM reality check

A count's raw number is meaningless alone. Judge it against **research-estimated universe for the vertical**.

Examples:
- Research says ~50k companies exist in the ICP → a count of 800 is a bad list.
- Research says ~4k companies exist in a niche vertical → a count of 800 might be correct.

Before launching a search, estimate the universe (web research, industry reports, association rosters). The agent records expected universe in `vertical-library.md` for each vertical so future pulls can be checked against it.

---

## Launch floor

**Minimum list size to launch: 3,000 contacts.** Below this, campaign setup overhead isn't worth it at Avenfield's current cadence. The agent should warn (not silently proceed) on sub-3k output.

---

## Campaign inputs Momin provides

These are NOT skill defaults — Momin provides them per campaign. The agent uses its own judgment to translate them into AI Ark filter values.

### Location
Momin specifies location per campaign. No default. If Momin forgets to specify, ask before proceeding.

### Job titles
Momin may give specific titles OR the shorthand **"decision makers only"**. When he says "decision makers only," translate as follows:

**Baseline decision-maker title set** (SMART mode phrases):
- Founder, Co-Founder, Owner
- CEO, President, Managing Director, Managing Partner
- C-suite in the buyer's function: CFO, CMO, CRO, COO, CTO, CIO, CISO, CPO — match the function to what's being sold.
- VP / SVP / EVP of [relevant function]
- Director / Head of [relevant function]

**Exclude when using "decision makers only"**:
- Manager, Senior Manager, Associate Manager
- All IC titles (Analyst, Specialist, Coordinator, Associate, Representative)
- Assistants / EAs / Interns / Students
- Advisors, Board Members (unless specifically wanted)

**Company-size-aware adjustment**:
- **SMB (<50 employees)** → tighten to Founder / Owner / CEO / President only.
- **Mid-market (50–500)** → full baseline set.
- **Enterprise (500+)** → typically VP and above only; Directors only in the specific function being sold to.

**Function-matching rule**: If Momin says "decision makers for a marketing tool," include marketing-function titles and exclude unrelated functions (Finance, Legal, Ops) even if they're technically decision-makers in their own function.

### Contractor-vertical adjustment (AI Ark-specific gotcha)
For contractor-heavy verticals (real estate agents, mortgage brokers, insurance producers, staffing recruiters), **drop the `employeeSize` filter entirely**. 1099 contractors don't appear in LinkedIn headcount, and the size filter will collapse the list to near-zero. This is unique to how AI Ark pulls from LinkedIn-sourced data.

---

## What gets written back to `vertical-library.md`

After every AI Ark run, the agent appends:

- **Vertical name** + short ICP description
- **Final filter config** (industries list, P&S include, P&S exclude, keyword include, keyword exclude, titles, coarse gates)
- **Count check result** (`totalElements`)
- **Pull size** (raw) vs. **clean size** (after Phase 5 scoring)
- **Score distribution** (CONFIRMED / LIKELY / AMBIGUOUS / FLAGGED counts)
- **Noise audit observations** — what contamination showed up
- **Scorer patterns that worked** for this vertical (reusable/adaptable next time)
- **TAM observed** vs. **universe estimate**
- **Campaign outcome if known** (reply rate, bounce rate, booked calls)

Over time, each vertical accumulates its own filter + scorer IP in `vertical-library.md`. Next time Momin wants "more of that vertical," the agent starts from proven config, not blank.

---

## Agent behavior rules (derived from this skill)

When the List Agent receives an `AI Ark: [ICP], [N] leads` command:

1. **Check `vertical-library.md` first** for prior runs in this vertical. If found, propose starting from the prior filter config + scorer, adjusted for any new context.
2. **Sanity-check the ICP for contractor-vertical signals** → pre-flag that `employeeSize` should be dropped.
3. **Work through Step 0 (seed) explicitly** — ask Momin for 2–3 known-good companies if he hasn't named any, or pull candidates from prior vertical-library entries.
4. **Run the count check first** (Developer API, size=1, FREE). Report count to Momin, compare against estimated universe, and iterate filters BEFORE any profile pull.
5. **Pull via Web App API only** (free). Never use Developer API for `size > 1`.
6. **Run the Phase 5 company name cross-check** on every record. Derive scorer patterns fresh for this vertical.
7. **Print the Phase 5.5 insight report and STOP.** Await explicit `export`.
8. **After export**, append to `vertical-library.md` and upload the CSV to Google Drive.
9. **If N requested < 3,000** (Avenfield launch floor), warn Momin before proceeding.
10. **Never pass `["CONTACT_REVEAL_EMAIL"]`** in save actions unless Momin explicitly asks for email enrichment (0.5 credits per contact).

---

## Open gaps (things to confirm with Momin)

- Employee size bands and revenue bands: typical ranges per vertical?
- "Always exclude" P&S phrases that bleed into basically every campaign (equivalent to Apollo's "agency/consulting" universal excludes)?
- Does Momin want the agent to execute AI Ark pulls itself (full pipeline including JWT capture), or hand off to a separate execution layer Momin runs?
- Should the Step 0 seed step ever be automated (agent picks candidate companies from a prior vertical-library entry) or always Momin-provided?
