#!/usr/bin/env python3
"""Avenfield find-websites — find an org's official website from name+location.

The job a VA does by hand: Google a hospital (or any org) by name + city +
state, find their REAL official website, and confirm it's actually them. This
automates that with OpenAI **web search** (so the URL comes from a live search,
not a hallucinated guess) followed by a Cloudflare **render-verify** guard — the
candidate page is fetched and only accepted if the org's name + city actually
appear on it. Blank beats wrong: a URL we can't verify is recorded in notes,
never written as confirmed.

Why not plain GPT? A normal chat model invents official-looking URLs. We learned
that the hard way on email-finding. So: web-search for candidates, then PROVE
each one by rendering it.

PIPELINE (per row)
  1. web search  "<name>, <city>, <state> official website"  (OpenAI)
  2. collect candidate URLs (from answer text + citations), drop directories/social
  3. render the best candidate (Cloudflare markdown)
  4. verify: enough name tokens + the city appear on the page?
  5. compare to the existing auto_best_guess (matches / differs)
  6. write confirmed_url (only if verified) + va_notes (always)

COMMANDS
  F=~/.claude/skills/avenfield-find-websites/find_websites.py
  python3 $F estimate --sheet <ID> --tab VA_Worklist
  python3 $F test     --sheet <ID> --tab VA_Worklist --n 15
  python3 $F run      --sheet <ID> --tab VA_Worklist [--limit N] [--overwrite]

Columns resolve by LETTER (Q) or HEADER name (confirmed_url). Defaults match the
VA_Worklist layout. `run` is idempotent — it skips rows that already have a
confirmed_url unless --overwrite.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _sibling(name: str) -> Path:
    p = _HERE.parent / name
    if (p).exists():
        return p
    return Path.home() / ".claude" / "skills" / name


sys.path.insert(0, str(_sibling("avenfield-openai")))
sys.path.insert(0, str(_sibling("avenfield-browser-render")))
sys.path.insert(0, str(_sibling("avenfield-sheets")))
import ai          # noqa: E402  OpenAI passthrough (call())
import cf_render   # noqa: E402  Cloudflare render (render_text())
import sheets as sh  # noqa: E402  Google Sheets (_api, SHEETS, _sheet_id)

# OpenAI web-search backend (fallback). Responses API web_search tool.
SEARCH_MODEL = "gpt-4o-mini"
SEARCH_TOOL = {"type": "web_search"}
COST_PER_OPENAI_SEARCH = 0.012        # $10/1k calls + ~$0.001-0.002 tokens (real)

# Cloudflare Browser Rendering is billed by DURATION, not per request:
# $0.09/browser-hour, 10 browser-hours/month free on Workers Paid.
# Source: developers.cloudflare.com/browser-rendering/platform/pricing/
CF_USD_PER_HOUR = 0.09
CF_FREE_HOURS = 10.0
DDG_HTML = "https://html.duckduckgo.com/html/?q="  # scrape-friendly results page

# Hosts that are never an org's own official site (social, search, and the many
# hospital-directory aggregators DuckDuckGo surfaces — these list the hospital's
# name+city, so they'd FALSELY pass the verify guard if not blocked).
DIRECTORY_HOSTS = {
    # social / search / general
    "facebook.com", "m.facebook.com", "linkedin.com", "wikipedia.org",
    "en.wikipedia.org", "yelp.com", "usnews.com", "health.usnews.com",
    "cms.gov", "medicare.gov", "data.cms.gov", "indeed.com", "x.com",
    "twitter.com", "instagram.com", "mapquest.com", "glassdoor.com",
    "google.com", "maps.google.com", "bing.com", "youtube.com", "tiktok.com",
    "yellowpages.com", "bbb.org", "ziprecruiter.com", "foursquare.com",
    "manta.com", "dnb.com", "superpages.com", "allnurses.com", "allbiz.com",
    # hospital/health directory aggregators
    "healthgrades.com", "vitals.com", "ratemds.com", "zocdoc.com", "webmd.com",
    "hospitalsandclinics.net", "hospitalcaredata.com", "healthcarecomps.com",
    "nationalhealthratings.com", "seniorhealthdatabase.com", "ourhealthnetwork.com",
    "healthcare4ppl.com", "myhospitalnow.com", "localoffices.org", "carelistings.com",
    "alaha.org", "hospital-data.com", "projects.propublica.org", "propublica.org",
    "ahd.com", "definitivehc.com", "beckershospitalreview.com", "ahdtools.com",
    "communitybenefitinsight.org", "medicalrecords.com", "caredash.com",
    "doximity.com", "sharecare.com", "wellness.com", "hospitalbycity.com",
    # social-service / 211 directories (share hospital names, not the org site)
    "pa211.org", "211.org", "auntbertha.com", "findhelp.org", "unitedway.org",
    "guidestar.org", "causeiq.com", "nonprofitlight.com",
    # NPI / provider-lookup directories
    "opennpi.com", "npidb.org", "npino.com", "hipaaspace.com", "npiprofile.com",
    "healthsoul.com", "nplocator.com", "docinfo.org", "npi.io", "hospital.io",
    "findadoctor.com", "medlineplus.gov", "clinicaltrials.gov",
}
# Tokens too generic to count as a name match.
STOP_TOKENS = {
    "hospital", "medical", "center", "centre", "regional", "memorial",
    "health", "healthcare", "system", "systems", "the", "of", "and",
    "inc", "llc", "county", "community", "general", "district", "care",
    "clinic", "services", "service", "st", "saint", "mt", "mount",
    "university", "dept", "department",
}

URL_RE = re.compile(r"https?://[^\s)\]\"'>]+")


def norm_url(u: str) -> str:
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def host_of(u: str) -> str:
    try:
        h = urllib.parse.urlparse(u if "://" in u else "http://" + u).netloc.lower()
        return re.sub(r"^www\.", "", h)
    except Exception:
        return ""


def homepage(u: str) -> str:
    """Reduce any URL to scheme://host (drop path/query)."""
    try:
        p = urllib.parse.urlparse(u if "://" in u else "https://" + u)
        if not p.netloc:
            return ""
        return f"https://{re.sub(r'^www.', '', p.netloc.lower())}"
    except Exception:
        return ""


def is_directory(u: str) -> bool:
    h = host_of(u)
    # .edu/.gov are colleges/agencies that share hospital names (e.g. Penn
    # Highlands Community College = pennhighlands.edu) — not the hospital's site.
    # This CMS list is community/critical-access hospitals, not universities.
    if h.endswith(".edu") or h.endswith(".gov"):
        return True
    return any(h == d or h.endswith("." + d) for d in DIRECTORY_HOSTS)


def name_tokens(name: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [t for t in toks if t not in STOP_TOKENS and len(t) > 2]


# ── column helpers ────────────────────────────────────────────────────────────
def col_to_idx(letter: str) -> int:
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def idx_to_col(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def resolve_col(spec: str, headers: list[str]) -> int:
    spec = (spec or "").strip()
    low = [h.strip().lower() for h in headers]
    if re.fullmatch(r"[A-Za-z]+", spec) and spec.lower() not in low:
        return col_to_idx(spec)
    if spec.lower() in low:
        return low.index(spec.lower())
    raise SystemExit(f"Column {spec!r} not found. Headers: {headers}")


def _range(tab: str, cells: str) -> str:
    return urllib.parse.quote(tab, safe="") + "!" + cells


def _range_body(tab: str, cells: str) -> str:
    if any(c in tab for c in (" ", "&", "'", "!")):
        tab = "'" + tab.replace("'", "''") + "'"
    return tab + "!" + cells


def read_tab(sheet_id: str, tab: str) -> list[list[str]]:
    raw = sh._api("GET", f"{sh.SHEETS}/{sheet_id}/values/{_range(tab, 'A1:ZZ')}", None)
    return raw.get("values", [])


def write_cell(sheet_id: str, tab: str, col_idx: int, row_1based: int, value: str):
    col = idx_to_col(col_idx)
    sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values:batchUpdate", {
        "valueInputOption": "RAW",
        "data": [{"range": _range_body(tab, f"{col}{row_1based}"), "values": [[value]]}],
    })


# ── Cloudflare render (captures X-Browser-Ms-Used for real cost) ──────────────
def cf_render_ms(endpoint: str, payload: dict, timeout: float = 60.0,
                 retries: int = 2) -> tuple[bool, int, str, int]:
    """Like cf_render.render_text but also returns browser-ms used.

    Returns (ok, status, result, browser_ms). browser_ms is summed across the run
    to compute the real Cloudflare cost (billed by duration, not per request).
    """
    acct, tok = cf_render._creds()
    url = f"{cf_render.API_BASE}/{acct}/browser-rendering/{endpoint}"
    data = json.dumps(payload).encode()
    last = (False, 0, "[render error: unknown]", 0)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body, status = r.read(), r.status
                ms = round(float(r.headers.get("X-Browser-Ms-Used", 0) or 0))
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
            ms = round(float(e.headers.get("X-Browser-Ms-Used", 0) or 0))
        except Exception as e:
            last = (False, 0, f"[render error: {e}]", 0)
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        text = body.decode("utf-8", "replace")
        if status == 200:
            try:
                res = json.loads(text).get("result")
            except (json.JSONDecodeError, AttributeError):
                res = text
            if not isinstance(res, str):
                res = json.dumps(res, ensure_ascii=False)
            return (True, status, res, ms)
        last = (False, status, f"[render failed {status}: {text[:160]}]", ms)
        if status in cf_render.TRANSIENT and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        return last
    return last


def decode_ddg(u: str) -> str:
    """DuckDuckGo HTML results wrap targets in /l/?uddg=<encoded>. Decode to the
    real URL; drop DuckDuckGo's own nav/feedback links."""
    if "duckduckgo.com/l/" in u:
        qs = urllib.parse.urlparse(u).query
        return urllib.parse.parse_qs(qs).get("uddg", [""])[0]
    if "duckduckgo.com" in host_of(u):
        return ""
    return u


def cloudflare_search_candidates(name: str, city: str, state: str) -> tuple[list[str], int]:
    """Render a DuckDuckGo results page via Cloudflare, extract + rank organic
    links. Returns (candidate_homepages_best_first, browser_ms)."""
    q = " ".join(p for p in (name, city, state) if p).strip()
    url = DDG_HTML + urllib.parse.quote(q)
    ok, status, result, ms = cf_render_ms("links", {"url": url}, timeout=60, retries=2)
    if not ok:
        return [], ms
    try:
        links = json.loads(result)
    except Exception:
        return [], ms
    if not isinstance(links, list):
        return [], ms

    toks, acr = name_tokens(name), acronym(name)
    # Keep the FULL result URL (its deep path often carries the specific hospital
    # name, so the verify render can confirm it even when the bare homepage can't —
    # e.g. phhealthcare.org/locations/huntingdon). Dedupe by homepage host.
    cands: list[tuple[str, int]] = []   # (full_url, ddg_position)
    seen = set()
    for idx, L in enumerate(links):
        raw = L.get("url", "") if isinstance(L, dict) else str(L)
        real = decode_ddg(raw)
        if not real:
            continue
        hp = homepage(real)
        if not hp or is_directory(hp):
            continue
        if hp not in seen:
            seen.add(hp)
            cands.append((real, idx))

    def score(item):
        full, pos = item
        label = re.sub(r"[^a-z0-9]", "", host_of(full).split(".")[0])
        s = pos  # DuckDuckGo's own ranking is a strong prior (top result = best)
        if len(acr) >= 3 and label.startswith(acr):
            s -= 5
        s -= sum(1 for t in toks if t in label)
        if homepage(full).endswith((".org", ".com")):
            s -= 1
        return s

    cands.sort(key=score)
    return [full for full, _ in cands], ms


# ── web search (OpenAI fallback) ──────────────────────────────────────────────
def web_search_candidates(name: str, city: str, state: str) -> list[str]:
    """Return candidate URLs (homepages) from an OpenAI web search, best-first.

    URLs are taken from BOTH the answer text and any citation annotations, so we
    don't depend on annotations being present. Directories/social are dropped.
    The render-verify step downstream is the real correctness guard.
    """
    prompt = (
        f"Find the OFFICIAL website of this hospital/organization — their own "
        f"domain, NOT google, maps, facebook, yelp, healthgrades, wikipedia or "
        f"any directory.\n\nName: {name}\nCity: {city}\nState: {state}\n\n"
        f"Reply with ONLY the homepage URL of their own website. If you cannot "
        f"find an official site, reply with exactly NONE."
    )
    body = {"model": SEARCH_MODEL, "tools": [SEARCH_TOOL], "input": prompt}
    status, data = ai.call("/responses", body=body, timeout=90)
    if status != 200:
        return []

    texts, ann_urls = [], []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("text"):
                    texts.append(c["text"])
                for a in c.get("annotations", []):
                    if a.get("url"):
                        ann_urls.append(a["url"])

    found = []
    # answer text URLs first (the model's chosen answer), then citations
    for blob in texts:
        found.extend(URL_RE.findall(blob))
    found.extend(ann_urls)

    seen, out = set(), []
    for u in found:
        hp = homepage(u)
        if not hp or is_directory(hp):
            continue
        if hp not in seen:
            seen.add(hp)
            out.append(hp)
    return out


def acronym(name: str) -> str:
    """Initials of the org name (skip filler like jr/of/the). 'D W McMillan
    Memorial Hospital' -> 'dwmmh'; 'South Arkansas Regional Hospital' -> 'sarh'."""
    skip = {"jr", "sr", "of", "the", "and", "llc", "inc", "co"}
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in skip]
    return "".join(w[0] for w in words)


def verify_url(url: str, name: str, city: str) -> tuple[bool, str, int]:
    """Render the URL and confirm the org is really there.
    Returns (ok, reason, browser_ms).

    Conservative on purpose — a false positive (wrong URL written as confirmed)
    is worse than a false negative (correct URL left in notes for a human). Two
    independent ways to confirm:
      A. HOST ACRONYM — the domain label starts with the org's initials
         (dwmmh.org, sarhcare.org, mlkch.org). Very specific; catches sites that
         brand under an abbreviation so the full name isn't on the page.
      B. PAGE TOKENS — significant name tokens appear on the rendered page:
         2+ tokens → a majority; a lone generic token (e.g. 'Mercy') → that
         token AND the city, since one common word can't stand alone.
    """
    ok, status, md, ms = cf_render_ms("markdown", {"url": url}, timeout=60, retries=2)
    if not ok or not md or md.startswith("[render"):
        return False, f"render failed ({status})", ms
    low = md.lower()
    toks = name_tokens(name)
    if not toks:
        return False, "no usable name tokens", ms
    hits = sum(1 for t in toks if t in low)
    city_ok = bool(city) and city.strip().lower() in low

    # A. host-acronym match
    host_label = re.sub(r"[^a-z0-9]", "", host_of(url).split(".")[0])
    acr = acronym(name)
    if len(acr) >= 3 and host_label.startswith(acr):
        return True, f"verified (host '{host_label}' matches acronym '{acr}')", ms

    # B. page-token match
    if len(toks) >= 2:
        accept = hits >= max(1, (len(toks) + 1) // 2) or (hits >= 1 and city_ok)
    else:
        accept = hits >= 1 and city_ok
    if accept:
        return True, f"verified ({hits}/{len(toks)} name tokens" + (", city" if city_ok else "") + ")", ms
    return False, f"name not found ({hits}/{len(toks)} tokens, city={'y' if city_ok else 'n'})", ms


def process_row(name: str, city: str, state: str, guess: str,
                backend: str = "cloudflare") -> dict:
    """Full per-row pipeline. Returns dict with confirmed_url + note + status +
    browser_ms (+ openai_calls for cost accounting)."""
    ms_total = 0
    openai_calls = 0
    guess_n = norm_url(guess)

    # 1. Guess-first short-circuit: if there's an existing non-directory guess,
    #    verify IT before spending a search. A correct guess costs one render.
    if guess and not is_directory(guess):
        cand = homepage(guess) or guess
        ok, reason, ms = verify_url(cand, name, city)
        ms_total += ms
        if ok:
            return {"confirmed_url": cand, "status": "confirmed", "browser_ms": ms_total,
                    "openai_calls": 0,
                    "note": f"confirmed; matches guess; {reason}; src=guess"}

    # 2. Search for candidates via the chosen backend.
    src = backend
    if backend == "openai":
        cands = web_search_candidates(name, city, state)
        openai_calls += 1
    else:  # cloudflare (default) or hybrid
        cands, ms = cloudflare_search_candidates(name, city, state)
        ms_total += ms
        src = "ddg"
        if not cands and backend == "hybrid":
            cands = web_search_candidates(name, city, state)
            openai_calls += 1
            src = "openai-fallback"

    if not cands:
        return {"confirmed_url": "", "status": "not_found", "browser_ms": ms_total,
                "openai_calls": openai_calls,
                "note": f"no official site found; src={src}"}

    # 3. Verify candidates, best-first; prefer one whose homepage matches the guess.
    #    We render the FULL result URL (its path may carry the hospital name) but
    #    write the clean homepage as the confirmed URL.
    ordered = sorted(cands, key=lambda u: (norm_url(homepage(u)) != guess_n))
    last_reason = ""
    for cand in ordered[:3]:   # cap verify renders per row
        ok, reason, ms = verify_url(cand, name, city)
        ms_total += ms
        last_reason = reason
        if ok:
            hp = homepage(cand) or cand
            matches = norm_url(hp) == guess_n and bool(guess_n)
            conf = "matches guess" if matches else ("differs from guess" if guess_n else "no prior guess")
            return {"confirmed_url": hp, "status": "confirmed", "browser_ms": ms_total,
                    "openai_calls": openai_calls,
                    "note": f"confirmed; {conf}; {reason}; src={src}"}

    return {"confirmed_url": "", "status": "found_unverified", "browser_ms": ms_total,
            "openai_calls": openai_calls,
            "note": f"candidate={homepage(ordered[0]) or ordered[0]} unverified ({last_reason}); src={src}"}


# ── sheet plumbing for commands ───────────────────────────────────────────────
def _load(sheet_id: str, tab: str):
    rows = read_tab(sheet_id, tab)
    if not rows:
        raise SystemExit(f"Tab {tab!r} is empty.")
    return rows[0], rows[1:]


def _cols(hdr, args):
    return {
        "name": resolve_col(args.name_col, hdr),
        "city": resolve_col(args.city_col, hdr),
        "state": resolve_col(args.state_col, hdr),
        "guess": resolve_col(args.guess_col, hdr),
        "confirmed": resolve_col(args.confirmed_col, hdr),
        "notes": resolve_col(args.notes_col, hdr),
    }


def _get(row, i):
    return (row[i] if i is not None and len(row) > i else "").strip()


def cmd_estimate(args):
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)
    c = _cols(hdr, args)
    todo = [r for r in data if _get(r, c["name"]) and (args.overwrite or not _get(r, c["confirmed"]))]
    n = len(todo)
    with_guess = sum(1 for r in todo if _get(r, c["guess"]) and not is_directory(_get(r, c["guess"])))
    need_search = n - with_guess
    backend = args.search_backend

    out = {
        "tab": args.tab,
        "backend": backend,
        "data_rows": len(data),
        "rows_with_name": sum(1 for r in data if _get(r, c["name"])),
        "already_confirmed": sum(1 for r in data if _get(r, c["confirmed"])),
        "rows_to_process": n,
        "rows_with_verifiable_guess": with_guess,
        "rows_needing_search": need_search,
    }
    if backend == "openai":
        out["projected_openai_searches"] = need_search
        out["projected_renders"] = n  # 1 verify render/row
        out["est_openai_usd"] = round(need_search * COST_PER_OPENAI_SEARCH, 2)
        out["note"] = ("Cloudflare renders billed by duration (≈ free within the "
                       "10 browser-hr/mo allowance); OpenAI search ≈ $0.012/call.")
    else:
        # cloudflare/hybrid: guess rows ≈ 1 render; search rows ≈ 1 search + ~1 verify
        renders = with_guess + need_search * 2
        out["projected_renders"] = renders
        out["projected_browser_hours_at_4s_each"] = round(renders * 4 / 3600, 2)
        hrs = renders * 4 / 3600
        billable = max(0.0, hrs - CF_FREE_HOURS)
        out["est_cloudflare_usd"] = round(billable * CF_USD_PER_HOUR, 2)
        out["note"] = (f"Cloudflare billed by browser-time: {CF_FREE_HOURS} hrs/mo free, "
                       f"then ${CF_USD_PER_HOUR}/hr. Estimate assumes ~4s/render; the "
                       "test batch measures real X-Browser-Ms-Used. No OpenAI spend.")
    print(json.dumps(out, indent=2))


def _run_batch(sheet_id, tab, hdr, data, c, args, write: bool):
    """Shared worker for test (write=False) and run (write=True)."""
    todo = []
    for i, r in enumerate(data):
        name = _get(r, c["name"])
        if not name:
            continue
        if not args.overwrite and _get(r, c["confirmed"]):
            continue
        todo.append((i, r))
    if args.limit:
        todo = todo[:args.limit]
    if hasattr(args, "n") and args.n:
        todo = todo[:args.n]

    total = len(todo)
    backend = args.search_backend
    print(f"Processing {total} rows (backend={backend}, concurrency={args.concurrency}, write={write})…", flush=True)
    results = {}
    done = 0
    stats = {"confirmed": 0, "found_unverified": 0, "not_found": 0}
    tot_ms = 0
    tot_openai = 0

    def work(item):
        idx, row = item
        out = process_row(_get(row, c["name"]), _get(row, c["city"]),
                          _get(row, c["state"]), _get(row, c["guess"]), backend=backend)
        return idx, row, out

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            idx, row, out = fut.result()
            results[idx] = out
            stats[out["status"]] = stats.get(out["status"], 0) + 1
            tot_ms += out.get("browser_ms", 0)
            tot_openai += out.get("openai_calls", 0)
            done += 1
            name = _get(row, c["name"])
            row_1based = idx + 2  # +1 header, +1 to 1-based
            if write:
                write_cell(sheet_id, tab, c["confirmed"], row_1based, out["confirmed_url"])
                write_cell(sheet_id, tab, c["notes"], row_1based, out["note"])
                if args.status_cell:
                    try:
                        sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values/"
                                f"{_range(tab, args.status_cell)}?valueInputOption=RAW",
                                {"values": [[f"find-websites {done}/{total} "
                                             f"({stats['confirmed']} confirmed)"]]})
                    except Exception:
                        pass
            tag = out["status"].upper()
            print(f"  [{done}/{total}] {tag:16} {name[:42]:42} -> "
                  f"{out['confirmed_url'] or '(blank)'}", flush=True)

    # Real cost from measured browser-time (+ any OpenAI fallback calls).
    hrs = tot_ms / 3_600_000
    cost = {
        "browser_ms_total": tot_ms,
        "browser_hours": round(hrs, 3),
        "browser_hours_per_row": round(hrs / total, 4) if total else 0,
        "projected_full_run_hours_1017": round(hrs / total * 1017, 2) if total else 0,
        "cloudflare_usd_if_over_free_tier": round(hrs * CF_USD_PER_HOUR, 4),
        "openai_calls": tot_openai,
        "openai_usd": round(tot_openai * COST_PER_OPENAI_SEARCH, 3),
    }
    print("\n" + json.dumps({"processed": total, **stats, "cost": cost}, indent=2))
    return results


def cmd_test(args):
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)
    c = _cols(hdr, args)
    print(f"(test mode — writing NOTHING to the sheet; sampling {args.n} rows)\n")
    _run_batch(sheet_id, args.tab, hdr, data, c, args, write=False)
    print("\nTest complete. Review above, then run the full pass without --n.")


def cmd_run(args):
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)
    c = _cols(hdr, args)
    _run_batch(sheet_id, args.tab, hdr, data, c, args, write=True)
    print(f"\nDone. Wrote confirmed_url (col {idx_to_col(c['confirmed'])}) + "
          f"va_notes (col {idx_to_col(c['notes'])}).")


def main():
    ap = argparse.ArgumentParser(description="Find & verify an org's official website (web search + render-verify).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--sheet", required=True)
        p.add_argument("--tab", default="VA_Worklist")
        p.add_argument("--name-col", default="hospital_name")
        p.add_argument("--city-col", default="city")
        p.add_argument("--state-col", default="state")
        p.add_argument("--guess-col", default="auto_best_guess")
        p.add_argument("--confirmed-col", default="confirmed_url")
        p.add_argument("--notes-col", default="va_notes")
        p.add_argument("--concurrency", type=int, default=8)
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--overwrite", action="store_true")
        p.add_argument("--search-backend", choices=["cloudflare", "openai", "hybrid"],
                       default="cloudflare",
                       help="cloudflare = DuckDuckGo render (near-free); "
                            "openai = web_search tool ($0.012/call); "
                            "hybrid = cloudflare then openai fallback.")

    e = sub.add_parser("estimate", help="row count + projected calls/cost (no API)")
    common(e)
    e.set_defaults(func=cmd_estimate)

    t = sub.add_parser("test", help="run pipeline on N rows, write nothing")
    common(t)
    t.add_argument("--n", type=int, default=15)
    t.set_defaults(func=cmd_test)

    r = sub.add_parser("run", help="full run, write confirmed_url + va_notes")
    common(r)
    r.add_argument("--n", type=int, default=0)
    r.add_argument("--status-cell", help="optional A1 cell for a live progress ticker")
    r.set_defaults(func=cmd_run)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
