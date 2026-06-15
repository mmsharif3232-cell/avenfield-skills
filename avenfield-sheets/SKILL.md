---
name: avenfield-sheets
description: "Read and write Google Sheets directly, as Momin's own Google account (OAuth). Use ANY TIME Momin wants to pull data from or push data to a Google Sheet — 'read this sheet', 'get the leads from <sheet URL>', 'write these results to the sheet', 'append rows', 'what tabs are in this sheet', 'add a tab', 'delete the scraped tab', 'make a new sheet', or whenever a lead list lives in Sheets and needs reading/updating. Because it logs in AS the user, it can touch any sheet they can open — no sharing step. It does NOT verify, render, or push to Instantly — it's the Sheets read/write layer."
---

# Avenfield Sheets (Google Sheets via OAuth)

Read/write any spreadsheet Momin can open — no service-account sharing. `sheets.py` in this skill dir.

## One-time setup (tell Momin if not done)
1. In Google Cloud Console: enable the **Google Sheets API**, then create an **OAuth client ID → Desktop app**.
2. Put the id + secret in `~/.avenfield/credentials.env`:
   `GOOGLE_OAUTH_CLIENT_ID=…` and `GOOGLE_OAUTH_CLIENT_SECRET=…`
3. Per device, once: `python3 ~/.claude/skills/avenfield-sheets/sheets.py auth` (opens a browser to approve).

If a command returns "Not authorized on this device", run the `auth` step.

## Run it

```bash
S=~/.claude/skills/avenfield-sheets/sheets.py

# list tabs (accepts a full URL or the bare ID)
python3 $S tabs --sheet "https://docs.google.com/spreadsheets/d/<ID>/edit"

# read a range → JSON 2D array (first row is usually headers)
python3 $S read --sheet <ID> --range "leads!A1:H"

# overwrite a range
python3 $S write --sheet <ID> --range "leads!A1" --values '[["url","email"],["x.com","a@x.com"]]'

# append rows to the end
python3 $S append --sheet <ID> --range "leads!A1" --values '[["y.com","b@y.com"]]'

# manage tabs
python3 $S add-tab    --sheet <ID> --title results
python3 $S delete-tab --sheet <ID> --title scraped

# make a fresh spreadsheet (prints id + url)
python3 $S create --title "Leeds agencies — verified"
```

## Working with leads
- To get a list: `read` the data range, treat row 0 as headers, build dicts.
- To write results back: `read` headers first to know the column layout, then `write`/`append` so columns line up. For one-tab output, write everything onto the existing tab (it keeps columns you don't touch only if you write full rows — when in doubt, read first, merge, write back).
- Sheet ID is auto-extracted from a pasted URL, so either form works.

## Notes
- Acts as the user's Google account: full access to their own + shared sheets, edits attributed to them.
- Dependency-free (plain HTTPS + the stored refresh token). The token lives at `~/.avenfield/google-token.json` (perms 600), per device.
