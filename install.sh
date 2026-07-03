#!/usr/bin/env bash
# Avenfield skills installer — run once per device after cloning the repo.
# Links every skill into ~/.claude/skills, then walks you through the two
# secrets (your API keys + the Google service-account JSON) and finishes the
# Google Sheets setup. Safe to re-run.
set -euo pipefail

REPO_SKILLS="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_SKILLS="$HOME/.claude/skills"
AVF="$HOME/.avenfield"
CRED="$AVF/credentials.env"
SA_DEST="$AVF/google-sa.json"

mkdir -p "$CLAUDE_SKILLS" "$AVF"

# ── 1. Link the skills ───────────────────────────────────────────────
echo "Linking skills → $CLAUDE_SKILLS"
for dir in "$REPO_SKILLS"/avenfield-*/; do
  [ -d "$dir" ] || continue
  name="$(basename "$dir")"
  rm -rf "${CLAUDE_SKILLS:?}/$name"
  ln -s "$dir" "$CLAUDE_SKILLS/$name"
  echo "  ✓ $name"
done

# ── 1b. Enable the secret-blocking git hook (defense-in-depth) ───────
if [ -d "$REPO_SKILLS/.githooks" ]; then
  ( cd "$REPO_SKILLS" && git config core.hooksPath .githooks ) 2>/dev/null \
    && echo "  ✓ pre-commit secret guard enabled (.githooks)" \
    || echo "  ! could not set core.hooksPath (not a git repo?)"
fi

creds_ready() { [ -f "$CRED" ] && grep -q 'CLOUDFLARE_API_TOKEN=..*' "$CRED" 2>/dev/null; }

setup() {
  # ── 2. API keys blob ───────────────────────────────────────────────
  echo
  echo "──────────────────────────────────────────────────────────────"
  echo " STEP 1 / 2 · API keys"
  echo " Paste the keys blob (the lines from your 1Password note),"
  echo " then press Ctrl-D on a new line."
  echo "──────────────────────────────────────────────────────────────"
  tmp="$(mktemp)"
  cat > "$tmp" < /dev/tty
  # Drop any GOOGLE_APPLICATION_CREDENTIALS the paste might contain — we set it.
  grep -v '^GOOGLE_APPLICATION_CREDENTIALS=' "$tmp" > "$CRED" || true
  rm -f "$tmp"
  chmod 600 "$CRED"

  # ── 3. Google service-account JSON ────────────────────────────────
  echo
  echo "──────────────────────────────────────────────────────────────"
  echo " STEP 2 / 2 · Google service-account JSON"
  echo " Drag the .json file into this window (or type its path),"
  echo " then press Enter."
  echo "──────────────────────────────────────────────────────────────"
  printf "   JSON file path: "
  read -r SAPATH < /dev/tty
  # strip wrapping quotes/spaces a drag-and-drop can add
  SAPATH="${SAPATH%\"}"; SAPATH="${SAPATH#\"}"
  SAPATH="${SAPATH%\'}"; SAPATH="${SAPATH#\'}"
  SAPATH="$(printf '%s' "$SAPATH" | sed 's/\\ / /g; s/^ *//; s/ *$//')"
  SAPATH="${SAPATH/#\~/$HOME}"
  if [ ! -f "$SAPATH" ]; then
    echo "  ✗ No file at: $SAPATH — re-run install.sh once you have the JSON."
    return 1
  fi
  cp "$SAPATH" "$SA_DEST"
  chmod 600 "$SA_DEST"
  echo "GOOGLE_APPLICATION_CREDENTIALS=$SA_DEST" >> "$CRED"

  # ── 4. Finish Google Sheets: surface the SA email to share with ───
  email="$(/usr/bin/python3 -c "import json;print(json.load(open('$SA_DEST')).get('client_email',''))" 2>/dev/null || true)"
  echo
  echo "✓ Keys saved        → $CRED"
  echo "✓ Sheets JSON saved → $SA_DEST"
  if [ -n "$email" ]; then
    echo
    echo " Google Sheets is ready. To use a NEW sheet, share it (Editor) with:"
    echo "     $email"
    echo " (Sheets already shared with this address just work.)"
  else
    echo "  ⚠️  Couldn't read client_email — make sure you pointed at the real JSON."
  fi
}

echo
if ! [ -e /dev/tty ]; then
  echo "No terminal available — run install.sh directly in a terminal to set up keys."
elif creds_ready; then
  echo "Credentials already set at $CRED — skipping setup."
  echo "(To redo: rm $CRED && bash install.sh)"
else
  setup || true
fi

echo
echo "Done. Restart Claude Code (or start a new session) to load the skills."
