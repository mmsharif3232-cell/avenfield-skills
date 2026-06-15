#!/usr/bin/env bash
# Avenfield skills installer — run once per device after cloning the repo.
# Symlinks every avenfield-* skill into ~/.claude/skills so Claude finds them,
# and makes sure your local credentials file exists. Safe to re-run (e.g.
# after `git pull` adds new skills).
set -euo pipefail

REPO_SKILLS="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_SKILLS="$HOME/.claude/skills"
CRED="$HOME/.avenfield/credentials.env"

mkdir -p "$CLAUDE_SKILLS" "$HOME/.avenfield"

echo "Linking skills from $REPO_SKILLS → $CLAUDE_SKILLS"
linked=0
for dir in "$REPO_SKILLS"/avenfield-*/; do
  [ -d "$dir" ] || continue
  name="$(basename "$dir")"
  rm -rf "${CLAUDE_SKILLS:?}/$name"
  ln -s "$dir" "$CLAUDE_SKILLS/$name"
  echo "  ✓ $name"
  linked=$((linked+1))
done
echo "Linked $linked skill(s)."

if [ ! -f "$CRED" ]; then
  cp "$REPO_SKILLS/credentials.env.template" "$CRED"
  chmod 600 "$CRED"
  echo
  echo "⚠️  Created $CRED from the template."
  echo "    Open it and paste your keys, then you're done:"
  echo "      \$EDITOR $CRED"
else
  echo "Credentials already present at $CRED — leaving it alone."
fi
echo
echo "Done. Restart Claude Code (or start a new session) to pick up the skills."
