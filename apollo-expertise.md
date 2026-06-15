# Apollo Expertise

> **Purpose**: Teach the List Agent (and anyone working with Momin) how to build clean, launch-ready Apollo searches at Avenfield. This file is consulted BEFORE any Apollo-related action — URL validation, filter coaching, scrape intake, or post-run diagnosis.

---

## Core principle: the skill IS the workflow

There is **no secret keyword list** that wins. Anyone claiming a "perfect Apollo filter stack" is selling something. The expertise lives in an **iterative loop** with disciplined judgment calls at each step:

```
Seed from known-good companies  →  Build filters  →  Pull sample  →  Diagnose bleed / TAM  →  Adjust filters  →  Repeat until confident
```

The agent's job on the Apollo path is to honor this loop — either by executing it when given authority, or by coaching Momin through it when he's iterating himself.

---

## Filter hierarchy (where effort goes)

Rank by how much time the filter deserves in a typical search:

1. **Company keywords — include AND exclude** → THIS IS THE BATTLEGROUND. 80%+ of iteration time lives here. Every other filter is a coarse frame around this.
2. **Industry** → frame the search. One or two industries, not a grab-bag.
3. **Title / seniority / department** → standard ICP plumbing. Not where bleed usually comes from. *(TBD — confirm how Momin sets these)*
4. **Location, employee count, revenue** → coarse gates. Set once, adjust rarely. *(TBD — confirm defaults)*

If a search feels off, **reach for company keywords first**. Don't start cutting industry or size until keyword-level iteration is exhausted.

---

## The iteration loop (step by step)

### Step 0 — Seed from known-good companies

Before you write a single keyword from scratch, pick **2–3 companies you know 100% fit the ICP** and look at the keywords Apollo has already assigned them.

- These become your starting **include keywords**.
- You're reverse-engineering Apollo's own ontology instead of guessing what it might tag things as.
- Apollo's keyword tagging is opaque — a company you'd describe as a "vertical SaaS for dental practices" might be tagged `dental software`, `practice management`, `SaaS`, `healthcare IT`. Seeding tells you which of those Apollo actually uses.

**When to re-run this step**: Any time a search feels stuck — pick a fresh known-good company, inspect its tags, and check whether your current include list is missing an obvious Apollo-native keyword.

### Step 1 — Build the starting filters

- Pick 1–2 industries that frame the vertical.
- Add 3–8 **include** keywords describing the company's business/offering.
- Add 5–15 **exclude** keywords for known contamination types (agencies, consultants, resellers, etc., depending on vertical).
- Set titles / seniority for the buyer persona.

### Step 2 — Pull a sample and check the shape

Look at the total result count (TAM). Compare against a research-estimated universe for this ICP (see "TAM reality check" below).

- **TAM too high** vs. expected universe → filters too loose, expect bleed.
- **TAM too low** (<3,000 contacts, or <10% of estimated universe) → filters too tight, need to broaden.
- **TAM in range** → proceed to page sampling.

### Step 3 — Page sampling for confidence (Momin's rule)

Sample result pages at these positions:

```
Page 1  →  Page 10  →  Page 15  →  Page 30  →  Page 50  →  Page 100  →  Last page
```

If quality holds across the distribution, the list is clean. If bleed appears only on deeper pages, Apollo is putting the loosest matches at the back — your filters are letting them in. Never judge by page 1 alone.

### Step 4 — Diagnose bleed

For any result page:

1. **Scan company names** — look for ones that feel off-ICP.
2. **Open the company description** (Apollo shows this in the result row or profile).
3. **If the company is NOT our ICP** → inspect the keywords Apollo tagged the company with.
4. **Identify candidate contaminators** — any keyword in their tag list that overlaps with your include list, OR any off-ICP keyword that could become a new exclude.

### Step 5 — Reverse-engineer the contaminator (test, don't guess)

When multiple keywords look suspect: **don't pick one by gut — test both.**

- Remove or exclude keyword A → re-pull → observe.
- Remove or exclude keyword B → re-pull → observe.
- Keep the change that cleaned the list without collapsing TAM.

The anti-pattern is deducing which keyword "must be" the problem and changing it without verification. Apollo's tagging is opaque; empiricism wins.

### Step 6 — Repeat until confident

Confidence = page sampling (Step 3) shows clean companies across the full distribution AND TAM is in a defensible range for the vertical.

### Step 7 — Hand the final URL to the agent

Once confident, the Apollo search URL becomes the input to AmpleLeads.io scrape. The URL encodes every filter — the agent will scrape whatever that URL returns, so URL quality = list quality.

---

## TAM reality check

A pull's raw TAM is meaningless alone. Judge it against **research-estimated universe for the vertical**.

Examples:
- Research says ~50k companies exist in the ICP → a pull returning 800 is a bad list.
- Research says ~4k companies exist in a niche vertical → a pull returning 800 might be correct.

**Before launching a search**, estimate the universe (web research, industry reports, association rosters). The agent should record expected universe in `vertical-library.md` for each vertical so future pulls can be checked against it.

---

## Launch floor

**Minimum list size to launch: 3,000 contacts.** Below this, the campaign setup overhead isn't worth it at Avenfield's current cadence. The agent should warn (not silently proceed) on sub-3k output.

---

## What gets written back to `vertical-library.md`

After every Apollo run, the agent appends to `vertical-library.md`:

- **Vertical name** + short ICP description
- **Final Apollo URL** (or filter summary)
- **Include keywords** that worked
- **Exclude keywords** that worked
- **Contamination patterns observed** (e.g., "marketing agencies kept sneaking in via 'branding' keyword")
- **TAM observed** vs. **universe estimate**
- **OmniVerifier pass rate** (valid / total), once cleaned
- **Campaign outcome if known** (reply rate, bounce rate, booked calls)

Over time this turns into a compounding edge: every new campaign in a vertical starts 70% built from the last one's learnings.

---

## Campaign inputs Momin provides

These are NOT skill defaults — Momin provides them per campaign. The agent uses its own judgment to translate them into Apollo filter values.

### Location
Momin specifies location per campaign (e.g., "US + Canada", "UK", "DACH", "Australia"). No default. If Momin forgets to specify, ask before proceeding — location is non-optional for almost every Avenfield ICP.

### Job titles
Momin may give specific titles OR the shorthand **"decision makers only"**. When he says "decision makers only," the agent translates as follows:

**Baseline decision-maker title set** (default for most B2B verticals):
- Founder, Co-Founder, Owner
- CEO, President, Managing Director, Managing Partner
- C-suite in the buyer's function: CFO, CMO, CRO, COO, CTO, CIO, CISO, CPO, etc. — match the function to what's being sold.
- VP / SVP / EVP of [relevant function]
- Director / Head of [relevant function]

**Exclude when using "decision makers only"**:
- Manager, Senior Manager, Associate Manager
- All IC titles (Analyst, Specialist, Coordinator, Associate, Representative)
- Assistants / EAs / Interns / Students
- Advisors, Board Members (unless specifically wanted)

**Company-size-aware adjustment**:
- **SMB (<50 employees)**: Tighten to Founder / Owner / CEO / President only. VPs and Directors at this size are often overblown titles.
- **Mid-market (50–500)**: Full baseline set above.
- **Enterprise (500+)**: Typically VP and above only; Directors only in the specific function being sold to. Avoid C-suite unless explicitly wanted — deliverability suffers to executive inboxes.

**Function-matching rule**: If Momin says "decision makers for a marketing tool," include marketing-function C-suite/VP/Director titles and exclude unrelated functions (Finance, Legal, Ops) even if they're technically decision-makers at their own function.

If titles are ambiguous, ask Momin: "Confirm — 'decision makers' here means [specific title list]?"

---

## Open gaps (things to confirm with Momin)

These are holes in this file — questions I haven't pulled from Momin yet. Fill them in as they come up:

- Employee count bands: typical ranges per vertical?
- Technologies / Intent signals: does Momin use these Apollo filters at all?
- "Always exclude" keyword list: even if there's no universal recipe, are there 5–10 keywords that bleed into basically every campaign (e.g., "agency", "consulting")?
- Who iterates: does Momin build the URL himself in Apollo's UI, or should the agent eventually help drive iteration via sample scrapes?

---

## Agent behavior rules (derived from this skill)

When the List Agent receives an `Apollo: [URL], [N] leads` command:

1. **Parse the URL** for filter presence. If no excludes exist, warn Momin: "No exclude keywords set — this usually causes bleed in my experience. Proceed anyway?"
2. **Flag suspicious TAM** if inferable (e.g., URL implies a broad vertical but N is small, or vice versa).
3. **Proceed with scrape** once confirmed, then run the clean pipeline (see `list-hygiene.md`).
4. **After run**: append learnings to `vertical-library.md` per the template above.
5. **If OmniVerifier pass rate is unusually low** (<60%), flag this back to Momin — it often means the source filters let in junk companies with messy email infrastructure.
