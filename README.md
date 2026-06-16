# Avenfield Skills

Claude-native capabilities for the cold-email pipeline. Each skill wraps one
underlying API (Cloudflare Browser Rendering, OpenAI, OmniVerifier, Instantly,
Google Sheets) and gives Claude raw, composable access — no web UI, no fixed
pipeline. You ask in plain English; Claude runs the skill.

## Skills

| Skill | Capability |
|-------|-----------|
| `avenfield-browser-render` | Render / scrape / screenshot / extract any site via Cloudflare Browser Rendering (markdown, HTML, screenshot, PDF, structured JSON, element scrape, links — single or batch) |
| `avenfield-verify` | Verify email deliverability via OmniVerifier (valid / catch-all / invalid / disposable / role) |
| `avenfield-instantly` | Drive Instantly v2 — list campaigns, add leads (single or bulk via `push-leads`), push sequences, or any endpoint (generic passthrough) |
| `avenfield-sheets` | Read/write any Google Sheet via the service-account JSON (share the sheet with the SA email) |
| `avenfield-openai` | Full OpenAI access — raw passthrough to any /v1 endpoint + `chat` and `extract` (single + batch) |
| `avenfield-personalize` | Generate cold-email merge variables ({{serviceLine}}…) from scraped website data — saved prompt presets, test-first, cost estimate before the full run, live progress, map back into the main sheet |
| `avenfield-instantly-upload` | Upload a Google Sheet of leads into an Instantly campaign — column→field/merge-var mapping, drops bad/dupe emails, fills blank tags, test-first then bulk (idempotent), never launches |
| `avenfield-spamguard` | Always-on deliverability/spam scan for copy — banned words/phrases, promotional/phishing wording, formatting bans; suggests rewrites, scans live Instantly sequences, rewrites risky company names |
| `avenfield-spintax` | Spintax cold-email copy for Instantly ({{RANDOM|a|b}}) per 8 strict rules, with a deterministic audit — combination count, banned-word scan, article/format checks, sample combinations |

Your existing copy/spintax/spamguard skills stay as-is — these complete the set.

## Install on a new device (one time)

You'll need two things from the admin (via 1Password / secure share):
1. the **API keys** blob, and 2. the **Google service-account JSON** file.

```bash
# 1. Clone the skills repo
git clone https://github.com/mmsharif3232-cell/avenfield-skills ~/avenfield-skills

# 2. Run the installer — it links the skills, then asks for the two secrets
bash ~/avenfield-skills/install.sh
#    STEP 1: paste the keys blob, press Ctrl-D
#    STEP 2: drag the .json file into the window, press Enter
#    → it saves both, wires up Google Sheets, prints the SA email to share sheets with

# 3. Restart Claude Code — all skills are live
```

That's it — no manual file editing. The installer writes
`~/.avenfield/credentials.env` and `~/.avenfield/google-sa.json` (perms 600)
and points `GOOGLE_APPLICATION_CREDENTIALS` at the JSON for you.

## How credentials work

- Secrets live **only** under `~/.avenfield/` on each device (perms 600).
- **Never** committed — only the `.template` is in git.
- Each skill reads keys in order: process env → `~/.avenfield/credentials.env`
  → the console `.env` (if present).
- Google Sheets: the installer drops the SA JSON in place. Share each target
  sheet (Editor) with the SA email it prints; sheets already shared just work.

## Updating

```bash
cd ~/avenfield-skills && git pull
bash install.sh        # re-links skills (picks up new ones); credentials untouched
```

Because `~/.claude/skills/avenfield-*` are symlinks into this repo, a `git pull`
updates the skill logic on that device immediately — no re-link needed for
existing skills.

## Security notes

- This puts your provider keys on every device that installs the skills. That's
  the trade-off for full local flexibility and no server dependency. Keep the
  devices trusted; rotate keys if a device is lost.
- If you'd rather keep keys in ONE place and hand out revocable per-person
  tokens instead, the skills can be pointed at a hosted proxy — ask and we'll
  switch the transport without changing how the skills feel.
