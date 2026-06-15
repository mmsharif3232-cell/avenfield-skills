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
| `avenfield-instantly` | Drive Instantly v2 — list campaigns, add leads, push sequences, or any endpoint (generic passthrough) |
| `avenfield-sheets` | Read/write any Google Sheet **as you** via OAuth — no service-account sharing |
| _(coming)_ `avenfield-extract` | Extract variables from rendered content via OpenAI |

Your existing copy/spintax/spamguard skills stay as-is — these complete the set.

## Install on a new device (one time)

```bash
# 1. Get the repo (skip if you already have the monorepo cloned)
git clone <REPO_URL> ~/avenfield        # or: git pull, if already cloned

# 2. Link the skills + create your local credentials file
bash ~/avenfield/skills/install.sh

# 3. Paste your keys (one time per device)
$EDITOR ~/.avenfield/credentials.env

# 4. Restart Claude Code — the skills are now available
```

## How credentials work

- Keys live **only** in `~/.avenfield/credentials.env` on each device (perms 600).
- That file is **never** committed — only the `.template` is in git.
- Every skill script reads keys from, in order: the process env →
  `~/.avenfield/credentials.env` → the console `.env` (if present).
- For `avenfield-sheets` you also need the Google service-account JSON copied
  to each device, at the path named in `GOOGLE_APPLICATION_CREDENTIALS`.

## Updating

```bash
cd ~/avenfield && git pull
bash skills/install.sh        # picks up any new skills; credentials untouched
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
