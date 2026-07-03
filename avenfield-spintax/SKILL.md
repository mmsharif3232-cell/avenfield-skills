---
name: avenfield-spintax
description: "Cold-email spintax specialist for Instantly. Use ANY TIME Momin pastes email copy and wants it spintaxed — 'spintax this', 'spin this copy', 'add spintax', 'make this unique per recipient', 'variation-ify this email'. Turns plain copy into Instantly {{RANDOM|a|b|c}} spintax following eight strict rules (spin every sentence's first word + every natural variation point, handle a/an inside blocks, short blocks, min 2 variants, custom variables untouchable, banned-word ban, no em dashes), then runs a deterministic audit (combination count, banned-word scan of every option via avenfield-spamguard, article-agreement + format checks, sample parsed combinations) and returns the spintaxed copy in the chat. Does NOT write new copy, fill variables, or import to Instantly — copy in, spintaxed copy out."
---

# Avenfield Spintax

Plain copy in → Instantly spintax out, in the chat. Claude does the spinning by
reasoning (the rules below); `spintax.py` makes the audit exact (count, banned
scan, article/format checks, sample combinations). No new copy, no variable
filling, no Instantly import.

## Instantly format
`{{RANDOM|option1|option2|option3}}` — `RANDOM` always caps, no spaces around the
pipes, wrapped in `{{ }}`. Only these blocks are spun; custom variables like
`{{firstName}}` are never touched.

## The eight rules
1. **Spin every sentence's first word.** Replace the first word of every sentence
   with a `{{RANDOM|...}}` block. If the sentence opens with a custom variable,
   leave it and spin the first meaningful word after it.
2. **Spin every natural variation point**, not just the first word — verbs, modals,
   adjectives, nouns, short phrases. No fixed run longer than 4–5 words unless
   they're proper nouns, custom variables, or have no natural synonym. Also: spin
   compound noun/verb phrases, and offer inverted order of paired items
   (`no upfront fees or retainers` ↔ `no retainers or upfront fees`).
3. **Handle a/an inside the block** when a fixed article precedes options with
   mixed vowel/consonant starts: `runs {{RANDOM|a hands-on|an active}} process`.
4. **Keep blocks short** — 1–3 words per option; never spin whole clauses.
5. **Min 2 variants**, no hard max; prefer fewer when options are equivalent.
6. **Custom variables are untouchable** — never wrap one, never make one an option.
7. **Banned-word ban on every introduced word** (all inflected forms). Reject and
   replace. Core list + clean swaps: get→reach/land/receive, chance→cut it,
   call→conversation/chat, million→large-scale, loans→accounts/book/portfolio,
   insurance→reframe (receivables/overhead), credit→capital/financing,
   cash→capital/liquidity, deal→situation/transaction/structure,
   access→use/leverage/tap into, billing→reframe (receivables/revenue timing),
   new/now/today→avoid, free→never. Extended caution: only, cost, life, finance,
   financial, bank, open, sales, medical, urgent, marketing, investment, invoice,
   mortgage, claims. (The audit also checks against `avenfield-spamguard`.)
8. **No em dashes** — use commas, hyphens, or restructure.

**Priority when rules conflict:** 1) grammatical correctness, 2) clarity, 3) variation count.

## Two-phase execution
- **Phase 1 — spin.** First read the whole copy and internalize POV, register,
  pronouns, rhythm, tone. Then apply all eight rules across every section.
- **Phase 2 — audit (use the script).** Parse every block, generate 50–100
  resolved combinations, read each as a complete email, and check grammar,
  article agreement, flow, and that no banned word surfaces. If any combination
  fails, fix the offending block's option and re-audit. Only deliver after a
  clean pass.

```bash
S=~/.claude/skills/avenfield-spintax/spintax.py
python3 $S count --file copy.txt                 # blocks + total combinations
python3 $S audit --file copy.txt --samples 80    # banned/article/format issues + samples
python3 $S combos --file copy.txt --n 5          # 5 resolved sample emails
```
`audit` returns `clean`, the combination `count`, `issues` (banned_options with the
exact block+option, article_risks, em_dashes, format, vars_in_block,
single_option_blocks), `failing_samples`, and `sample_combinations`. Fix any
`issues`, re-run, ship only when `clean: true`.

## What to report back every run
- Spintaxed version, clearly labelled beneath the original
- Total `{{RANDOM|...}}` blocks + total possible combinations
- Campaign list size and ratio (if provided)
- Audit result
- 3–5 sample parsed combinations

## Does NOT
Write new copy · fill custom variables · import to Instantly · change the original
copy. (For deliverability scanning of finished copy use `avenfield-spamguard`; to
push to a campaign use `avenfield-instantly` / `avenfield-instantly-upload`.)
