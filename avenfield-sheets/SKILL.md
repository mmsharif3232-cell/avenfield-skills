---
name: avenfield-sheets
description: "Read and write Google Sheets directly via a service-account JSON. Use ANY TIME Momin wants to pull data from or push data to a Google Sheet — 'read this sheet', 'get the leads from <sheet URL>', 'write these results to the sheet', 'append rows', 'what tabs are in this sheet', 'add a tab', 'delete the scraped tab', 'make a new sheet', or whenever a lead list lives in Sheets and needs reading/updating. It does NOT verify, render, or push to Instantly — it's the Sheets read/write layer."
---

# Avenfield Sheets (service-account JSON)

Read/write any sheet **shared with the service account's email**. `sheets.py` in this skill dir. Dependency-free — signs the auth JWT with `openssl`, so no pip installs.

## Setup (per device)
- Copy the service-account JSON to the device.
- In `~/.avenfield/credentials.env`: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`
- Share each target sheet (Editor) with the SA email. Get it with:
  `python3 ~/.claude/skills/avenfield-sheets/sheets.py whoami`

If a call returns 403, the sheet isn't shared with the SA email yet.

## Run it

```bash
S=~/.claude/skills/avenfield-sheets/sheets.py

python3 $S whoami                                        # SA email to share sheets with
python3 $S tabs   --sheet "https://docs.google.com/spreadsheets/d/<ID>/edit"
python3 $S read   --sheet <ID> --range "leads!A1:H"
python3 $S write  --sheet <ID> --range "leads!A1" --values '[["url","email"],["x.com","a@x.com"]]'
python3 $S append --sheet <ID> --range "leads!A1" --values '[["y.com","b@y.com"]]'
python3 $S add-tab    --sheet <ID> --title results
python3 $S delete-tab --sheet <ID> --title scraped
python3 $S set-row-height --sheet <ID> --title "browser render"   # back to 21px default
python3 $S set-wrap       --sheet <ID> --title "browser render"   # CLIP: text stays in its cell, no overflow
python3 $S create --title "Campaign Log" [--folder <DRIVE_FOLDER_ID>]  # SA has no quota → creates in a shared folder
python3 $S share  --sheet <ID> --email faizan.advisory@gmail.com --role writer  # Drive permissions (needs Drive API)
python3 $S create --title "Leeds agencies — verified"    # SA owns it
```

## Working with leads
- Read a range, treat row 0 as headers, build dicts.
- To write results back, read headers first so columns line up, then `write`/`append`.
- Sheet ID is auto-extracted from a pasted URL, so either form works.

## Creating & sharing
- The service account has **no Drive storage quota**, so it can't create a file it
  would own. `create` falls back to the Drive API and makes the sheet inside a
  shared folder (`--folder`, or `SHEETS_PARENT_FOLDER_ID` from creds) so the
  folder's owner holds the quota. If even that 403s (folder is a personal My
  Drive, not a Shared Drive), create the file with the Google Drive connector (a
  real account) and just populate/format it here.
- `share` adds a Drive permission (reader/commenter/writer). Needs the Drive API
  enabled for the SA's project and the SA to own / be able to share the file.

## Notes
- Service account = non-interactive, identical on every device (just the JSON + the path).
- Sheets must be shared with the SA email (`whoami`) — that's the one gotcha.
- Needs `openssl` on PATH (standard on macOS/Linux).
