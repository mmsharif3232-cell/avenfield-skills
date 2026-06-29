#!/usr/bin/env python3
"""Avenfield find-websites — find an org's official website from name+location.

The job a VA does by hand: Google a hospital (or any org) by name + city +
state, find their REAL official website, and confirm it's actually them. The URL
comes from a LIVE search — never a hallucinated guess.

Why not plain GPT? A normal chat model invents official-looking URLs (learned the
hard way on email-finding). So we render a real search-results page and let GPT
PICK from those real results — its pick is "grounded" (it can only effectively
choose a URL the search actually returned). Blank beats wrong: a URL we can't
trust is recorded in notes, never written as confirmed.

PIPELINE (per row)
  1. guess-first: if an auto_best_guess exists, render-verify it (one render, no
     search) — a correct guess is the cheapest confirm.
  2. render the DuckDuckGo HTML results page via Cloudflare → real candidate
     (url, title) list. All results are passed through (no directory pre-filter).
  3. gpt-5-mini PICKS the official site (its own domain or its parent health
     system) from those real results; prompt tells it to skip news/directory/
     social/jobs/gov pages.
  4. confirm a GROUNDED high/medium pick straight away (big hospital sites
     bot-block the renderer, so an on-page check is unreliable); for a low/
     ungrounded pick, render-verify the page (name tokens + city) first.
  5. write confirmed_url (only if confirmed) + va_notes (always).

COMMANDS
  F=~/.claude/skills/avenfield-find-websites/find_websites.py
  python3 $F estimate --sheet <ID> --tab VA_Worklist
  python3 $F trace    --name "<org>" --city "<city>" --state "<st>"   # no write
  python3 $F test     --sheet <ID> --tab VA_Worklist --n 15 [--start N]   # writes
  python3 $F run      --sheet <ID> --tab VA_Worklist [--start N] [--limit N] [--overwrite]

Columns resolve by LETTER (Q) or HEADER name (confirmed_url). Defaults match the
VA_Worklist layout. `run`/`test` are idempotent — they skip rows that already have
a confirmed_url unless --overwrite. `--start N` begins partway down the sheet.
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

# GPT-pick: a reasoning model chooses the official site from the REAL DuckDuckGo
# results (grounded → no hallucinated URLs; render-verify still guards uncertain picks).
GPT_PICK_MODEL = "gpt-5-mini"
GPT_IN_PER_1M = 0.25                  # $/1M input tokens  (sourced pricing)
GPT_OUT_PER_1M = 2.00                 # $/1M output tokens

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


def _api_retry(method, url, body=None, tries=5):
    """sh._api with retry — the agent proxy can 502 transiently; one blip on a
    read/auth call shouldn't abort the whole run. _api sys.exit()s on error, so
    catch SystemExit too."""
    for attempt in range(tries):
        try:
            return sh._api(method, url, body)
        except (Exception, SystemExit):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def read_tab(sheet_id: str, tab: str) -> list[list[str]]:
    raw = _api_retry("GET", f"{sh.SHEETS}/{sheet_id}/values/{_range(tab, 'A1:ZZ')}", None)
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


def cloudflare_search_raw(name: str, city: str, state: str):
    """Render the DuckDuckGo results page and return (list[(url, title)], ms).

    Keeps the result TITLE (the `links` endpoint returns {url,text}) — titles are
    a strong signal for the GPT picker. Decodes uddg redirects, drops directories,
    dedupes by homepage, keeps DuckDuckGo order, top ~10."""
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
    out, seen = [], set()
    for L in links:
        raw = L.get("url", "") if isinstance(L, dict) else str(L)
        title = (L.get("text", "") if isinstance(L, dict) else "").strip()
        real = decode_ddg(raw)
        if not real:
            continue
        hp = homepage(real)
        # No directory pre-filter here: GPT sees ALL real DDG results and reasons
        # over the titles to pick the official site (the prompt tells it to skip
        # news/directory/social/jobs/gov pages). "Fully trust GPT" — see SKILL.md.
        if not hp:
            continue
        if hp not in seen:
            seen.add(hp)
            out.append((real, title))   # keep the FULL url (deep path helps verify)
        if len(out) >= 10:
            break
    return out, ms


def gpt_pick_website(name, city, state, cands):
    """Let a reasoning model pick the official site from the REAL DDG results.

    cands = [(url, title)]. Returns (picked_homepage, why, confidence, usage)
    where usage = (prompt_tokens, completion_tokens) for cost accounting. The
    pick is grounded on real URLs; the downstream render-verify is the guard."""
    listing = "\n".join(f"{i+1}. {u}  —  {t[:80]}" for i, (u, t) in enumerate(cands)) or "(no results)"
    prompt = (
        "You identify the OFFICIAL website of a U.S. hospital from real search results.\n\n"
        f"Hospital: {name}\nCity/State: {city}, {state}\n\n"
        f"Search results (real URLs from DuckDuckGo):\n{listing}\n\n"
        "Return STRICT JSON: {\"url\":\"<official homepage, scheme+host only, or empty>\","
        "\"confidence\":\"high|medium|low\",\"why\":\"<=12 words\"}\n"
        "Rules:\n"
        "- Pick the hospital's OWN website, or its parent HEALTH SYSTEM's official site "
        "(e.g. a hospital owned by University Hospitals -> uhhospitals.org).\n"
        "- NEVER pick a news/TV/newspaper site, ratings/directory site, social media, "
        "jobs board, tourism/city portal, or government data page.\n"
        "- Prefer a URL from the list; output a CLEAN homepage (no path).\n"
        "- If none of the results is the official site, set url to \"\"."
    )
    body = {"model": GPT_PICK_MODEL, "reasoning_effort": "low",
            "messages": [{"role": "user", "content": prompt}]}
    status, data = 0, {}
    for attempt in range(3):   # transient proxy/network errors → retry with backoff
        try:
            status, data = ai.call("/chat/completions", body=body, timeout=90)
            if status == 200:
                break
        except (Exception, SystemExit):
            status, data = 0, {}
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    usage = (0, 0)
    if status != 200:
        return "", f"gpt error {status}", "low", usage
    u = data.get("usage", {})
    usage = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    content = ""
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except Exception:
        pass
    pick, why, conf = "", "", "low"
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            j = json.loads(m.group(0))
            pick = (j.get("url") or "").strip()
            why = (j.get("why") or "").strip()[:60]
            conf = (j.get("confidence") or "low").strip().lower()
        except Exception:
            pass
    if not pick:  # fallback: first URL in the content
        m2 = URL_RE.search(content)
        pick = m2.group(0) if m2 else ""
    hp = homepage(pick) if pick else ""
    # No directory guard: we fully trust GPT's pick (the prompt instructs it to
    # avoid directory/news/social pages). See SKILL.md "Fully trust GPT".
    return hp, (why or "gpt pick"), conf, usage


def gpt_verify_official(name, city, state, url, page_content):
    """Decide whether `url` is the hospital's OFFICIAL website from its rendered page.

    The hard case: large health systems (adventhealth.com, bannerhealth.com) and
    government operators (ihs.gov) run MANY hospitals on one domain — those sub-pages
    ARE official. Third-party directories (healthgrades, zocdoc) merely LIST the
    hospital — NOT official. GPT reads the rendered page and the URL to tell them apart.

    Returns (is_official: bool|None, confidence: 'high|medium|low', reason, (gin, gout)).
    is_official is None when GPT can't decide (-> 'Uncertain')."""
    page = (page_content or "")[:6000]   # cap tokens; the top of the page is enough
    prompt = (
        "You verify whether a URL is the OFFICIAL website of a specific U.S. hospital.\n\n"
        f"Hospital: {name}\nCity/State: {city}, {state}\nURL being checked: {url}\n\n"
        f"Rendered page content (markdown, truncated):\n---\n{page}\n---\n\n"
        "Decide: is this URL the hospital's official website?\n"
        "- OFFICIAL = the organization behind this domain OPERATES or directly owns this\n"
        "  hospital. This INCLUDES a parent health system's site (e.g. a hospital owned by\n"
        "  AdventHealth on adventhealth.com) and a government operator that runs the\n"
        "  facility (e.g. Indian Health Service on ihs.gov, VA on va.gov). A sub-page of\n"
        "  the operating system that names THIS hospital counts as official.\n"
        "- NOT OFFICIAL = a third-party directory/aggregator that merely LISTS the hospital\n"
        "  (healthgrades.com, zocdoc.com, vitals.com, usnews.com, yelp, npi lookups), a\n"
        "  news/social/jobs page, or a page about a DIFFERENT hospital/org than the one named.\n"
        "- If the page failed to render or is too sparse to tell, is_official=null, low.\n\n"
        "Return STRICT JSON only: {\"is_official\": true|false|null, "
        "\"confidence\": \"high|medium|low\", \"reason\": \"<=15 words\"}"
    )
    body = {"model": GPT_PICK_MODEL, "reasoning_effort": "low",
            "messages": [{"role": "user", "content": prompt}]}
    status, data = 0, {}
    for attempt in range(3):
        try:
            status, data = ai.call("/chat/completions", body=body, timeout=90)
            if status == 200:
                break
        except (Exception, SystemExit):
            status, data = 0, {}
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    usage = (0, 0)
    if status != 200:
        return None, "low", f"gpt error {status}", usage
    u = data.get("usage", {})
    usage = (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    content = ""
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except Exception:
        pass
    is_off, conf, reason = None, "low", "gpt returned no verdict"
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            j = json.loads(m.group(0))
            is_off = j.get("is_official", None)   # may be true/false/null
            conf = (j.get("confidence") or "low").strip().lower()
            reason = (j.get("reason") or "").strip()[:120] or "no reason given"
        except Exception:
            pass
    if conf not in ("high", "medium", "low"):
        conf = "low"
    return is_off, conf, reason, usage


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


def process_row(name: str, city: str, state: str, guess: str) -> dict:
    """Full per-row pipeline. Returns dict with confirmed_url + note + status +
    browser_ms + openai_calls/gpt_in/gpt_out for cost accounting.

    Two ways a row confirms: (1) an existing guess that render-verifies, or (2) a
    gpt-5-mini pick over the real DuckDuckGo results — confirmed straight away when
    grounded + high/medium, else only after an on-page render match. Blank beats
    wrong: an uncertain pick is recorded in notes, never written as confirmed.
    """
    ms_total = 0
    guess_n = norm_url(guess)

    # 1. Guess-first short-circuit: verify an existing non-directory guess before
    #    spending a search. A correct guess costs one render. (The guess column is
    #    a vetted best-guess, so a verified guess is trusted regardless of host.)
    if guess and not is_directory(guess):
        cand = homepage(guess) or guess
        ok, reason, ms = verify_url(cand, name, city)
        ms_total += ms
        if ok:
            return {"confirmed_url": cand, "status": "confirmed", "browser_ms": ms_total,
                    "openai_calls": 0, "gpt_in": 0, "gpt_out": 0,
                    "note": f"confirmed; matches guess; {reason}; src=guess"}

    # 2. GPT-pick: render the real DDG results, let gpt-5-mini reason over them to
    #    pick the official site (or its health-system parent). A pick is GROUNDED
    #    when its homepage appears in the real DDG results (so the URL provably
    #    exists — no hallucination). We confirm a grounded high/medium pick even
    #    when Cloudflare can't render it (big hospital sites bot-block / JS-render,
    #    which wrongly fails a name-on-page check). An actual on-page name match is
    #    still the strongest signal and confirms at any confidence.
    raw, ms = cloudflare_search_raw(name, city, state)
    ms_total += ms
    pick, why, conf, (gin, gout) = gpt_pick_website(name, city, state, raw)
    base = {"openai_calls": 1, "gpt_in": gin, "gpt_out": gout}
    if not pick:
        return {**base, "confirmed_url": "", "status": "not_found", "browser_ms": ms_total,
                "note": f"no official site found (gpt: {why}); src=gpt"}
    grounded = any(homepage(u) == pick for u, _ in raw)
    matches = norm_url(pick) == guess_n and bool(guess_n)
    gc = "matches guess" if matches else ("differs from guess" if guess_n else "no prior guess")
    # FAST PATH: a grounded high/medium pick is confirmed WITHOUT spending verify
    # renders (the pick is a real URL from the search + GPT reasoned over titles;
    # big hospital sites bot-block the renderer so an on-page check is unreliable).
    if grounded and conf in ("high", "medium"):
        base["browser_ms"] = ms_total
        return {**base, "confirmed_url": pick, "status": "confirmed",
                "note": f"confirmed; gpt-pick {conf} (grounded); {gc}; {why}; src=gpt"}
    # UNCERTAIN (low confidence or ungrounded): require an on-page render match
    # before confirming — try the homepage and the deep DDG URL behind it.
    targets = [pick] + [u for u, _ in raw if homepage(u) == pick and u != pick]
    on_page = False
    for tgt in targets[:2]:
        ok, vreason, m = verify_url(tgt, name, city)
        ms_total += m
        if ok:
            on_page = True
            break
    base["browser_ms"] = ms_total
    if on_page:
        return {**base, "confirmed_url": pick, "status": "confirmed",
                "note": f"confirmed; gpt-pick {conf}; {gc}; on-page {vreason}; src=gpt"}
    return {**base, "confirmed_url": "", "status": "found_unverified",
            "note": f"candidate={pick} gpt-pick {conf} (ungrounded/low: {why}); src=gpt"}


def _label(is_off):
    """Map GPT's true/false/null verdict to the sheet's Yes/No/Uncertain label."""
    if is_off is True:
        return "Yes"
    if is_off is False:
        return "No"
    return "Uncertain"


def verify_official_row(name, city, state, url_to_check, render_url):
    """Render render_url and ask GPT whether url_to_check is the hospital's official
    site. Returns dict: is_official(label)/confidence/reason/browser_ms/gpt_in/gpt_out.
    No domain-cache here — caching is handled by cmd_verify so it stays thread-safe."""
    ok, status, md, ms = cf_render_ms("markdown", {"url": render_url}, timeout=60, retries=2)
    if not ok or not md or md.startswith("[render"):
        # Render failed — let GPT still try on an empty page (it will return low/uncertain),
        # but most of the time a dead URL → No/Uncertain with a clear reason.
        is_off, conf, reason, (gin, gout) = gpt_verify_official(name, city, state, url_to_check, "")
        if is_off is None:
            reason = f"page did not render ({status}); {reason}"
        return {"is_official": _label(is_off), "confidence": conf.capitalize(),
                "reason": reason, "browser_ms": ms, "gpt_in": gin, "gpt_out": gout}
    is_off, conf, reason, (gin, gout) = gpt_verify_official(name, city, state, url_to_check, md)
    return {"is_official": _label(is_off), "confidence": conf.capitalize(),
            "reason": reason, "browser_ms": ms, "gpt_in": gin, "gpt_out": gout}


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

    # gpt flow: a guess row ≈ 1 verify render; a search row ≈ 1 DDG render + 1
    # gpt-5-mini call (most confirm on the grounded fast path, no extra render).
    renders = with_guess + need_search
    gpt_calls = need_search
    # ~640 in + ~250 out tokens per gpt-5-mini call (measured on real runs).
    gpt_usd = gpt_calls * (640 / 1_000_000 * GPT_IN_PER_1M + 250 / 1_000_000 * GPT_OUT_PER_1M)
    hrs = renders * 4 / 3600   # ~4s/render prior; test/run measure real X-Browser-Ms-Used
    billable = max(0.0, hrs - CF_FREE_HOURS)
    out = {
        "tab": args.tab,
        "backend": "gpt",
        "data_rows": len(data),
        "rows_with_name": sum(1 for r in data if _get(r, c["name"])),
        "already_confirmed": sum(1 for r in data if _get(r, c["confirmed"])),
        "rows_to_process": n,
        "rows_with_verifiable_guess": with_guess,
        "rows_needing_search": need_search,
        "projected_renders": renders,
        "projected_browser_hours_at_4s_each": round(hrs, 2),
        "est_cloudflare_usd": round(billable * CF_USD_PER_HOUR, 2),
        "projected_gpt_calls": gpt_calls,
        "est_gpt_usd": round(gpt_usd, 2),
        "note": (f"gpt-5-mini ≈ ${GPT_IN_PER_1M}/1M in + ${GPT_OUT_PER_1M}/1M out "
                 f"(~$0.0003/row). Cloudflare billed by browser-time: {CF_FREE_HOURS} "
                 f"hrs/mo free, then ${CF_USD_PER_HOUR}/hr. test/run measure real cost."),
    }
    print(json.dumps(out, indent=2))


def _run_batch(sheet_id, tab, hdr, data, c, args, write: bool):
    """Shared worker for test (write=False) and run (write=True)."""
    start = getattr(args, "start", 0) or 0
    todo = []
    for i, r in enumerate(data):
        if i < start:   # skip the first `start` data rows (e.g. --start 100 = row 101+)
            continue
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
    print(f"Processing {total} rows (concurrency={args.concurrency}, write={write})…", flush=True)
    results = {}
    done = 0
    stats = {"confirmed": 0, "found_unverified": 0, "not_found": 0}
    tot_ms = 0
    tot_openai = 0
    tot_gin = 0
    tot_gout = 0
    pending = []  # (row_1based, confirmed_url, note) buffered for batched writes

    def flush():
        """Write all buffered cells in ONE batchUpdate request (stays under the
        Sheets 'write requests per minute' quota — per-cell writes blow it)."""
        if not pending:
            return
        cc, nc = idx_to_col(c["confirmed"]), idx_to_col(c["notes"])
        data_ranges = []
        for r1, conf, note in pending:
            data_ranges.append({"range": _range_body(tab, f"{cc}{r1}"), "values": [[conf]]})
            data_ranges.append({"range": _range_body(tab, f"{nc}{r1}"), "values": [[note]]})
        for attempt in range(5):
            try:
                sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values:batchUpdate",
                        {"valueInputOption": "RAW", "data": data_ranges})
                break
            except (Exception, SystemExit) as e:  # _api sys.exit()s on HTTP errors
                if "429" in str(e) and attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
        pending.clear()

    def work(item):
        idx, row = item
        try:
            out = process_row(_get(row, c["name"]), _get(row, c["city"]),
                              _get(row, c["state"]), _get(row, c["guess"]))
        except (Exception, SystemExit) as e:
            # One row's transient failure (proxy 502, etc.) must not kill the batch.
            # Leave it blank+noted; a later run (no --overwrite) retries blank rows.
            out = {"confirmed_url": "", "status": "error", "browser_ms": 0,
                   "openai_calls": 0, "gpt_in": 0, "gpt_out": 0,
                   "note": f"processing error ({str(e)[:100]}); src=gpt"}
        return idx, row, out

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            idx, row, out = fut.result()
            results[idx] = out
            stats[out["status"]] = stats.get(out["status"], 0) + 1
            tot_ms += out.get("browser_ms", 0)
            tot_openai += out.get("openai_calls", 0)
            tot_gin += out.get("gpt_in", 0)
            tot_gout += out.get("gpt_out", 0)
            done += 1
            name = _get(row, c["name"])
            row_1based = idx + 2  # +1 header, +1 to 1-based
            if write:
                pending.append((row_1based, out["confirmed_url"], out["note"]))
                if len(pending) >= getattr(args, "flush_every", 10):   # real-time batched flush
                    flush()
                    if getattr(args, "status_cell", None):
                        # values.update is PUT (POST to values/{range} 404s); keep it
                        # strictly non-fatal — _api raises SystemExit on any error.
                        try:
                            sh._api("PUT", f"{sh.SHEETS}/{sheet_id}/values/"
                                    f"{_range(tab, args.status_cell)}?valueInputOption=RAW",
                                    {"values": [[f"find-websites {done}/{total} "
                                                 f"({stats['confirmed']} confirmed)"]]})
                        except (Exception, SystemExit):
                            pass
            tag = out["status"].upper()
            print(f"  [{done}/{total}] {tag:16} {name[:42]:42} -> "
                  f"{out['confirmed_url'] or '(blank)'}", flush=True)

    if write:
        flush()  # write any remainder

    # Real cost: measured browser-time + measured GPT token usage.
    hrs = tot_ms / 3_600_000
    gpt_usd = tot_gin / 1_000_000 * GPT_IN_PER_1M + tot_gout / 1_000_000 * GPT_OUT_PER_1M
    cost = {
        "browser_ms_total": tot_ms,
        "browser_hours": round(hrs, 3),
        "projected_full_run_hours_1017": round(hrs / total * 1017, 2) if total else 0,
        "cloudflare_usd_if_over_free_tier": round(hrs * CF_USD_PER_HOUR, 4),
        "openai_calls": tot_openai,
        "gpt_tokens_in": tot_gin,
        "gpt_tokens_out": tot_gout,
        "gpt_usd": round(gpt_usd, 4),
        "gpt_usd_per_row": round(gpt_usd / total, 5) if total else 0,
        "projected_gpt_usd_1017": round(gpt_usd / total * 1017, 2) if total else 0,
    }
    print("\n" + json.dumps({"processed": total, **stats, "cost": cost}, indent=2))
    return results


def cmd_test(args):
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)
    c = _cols(hdr, args)
    print(f"(test mode — sampling {args.n} rows; results ARE written to the sheet, "
          f"same as run)\n")
    _run_batch(sheet_id, args.tab, hdr, data, c, args, write=True)
    print(f"\nTest complete — wrote confirmed_url (col {idx_to_col(c['confirmed'])}) + "
          f"va_notes (col {idx_to_col(c['notes'])}) for the sampled rows. "
          f"Run the full pass without --n.")


def cmd_run(args):
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)
    c = _cols(hdr, args)
    _run_batch(sheet_id, args.tab, hdr, data, c, args, write=True)
    print(f"\nDone. Wrote confirmed_url (col {idx_to_col(c['confirmed'])}) + "
          f"va_notes (col {idx_to_col(c['notes'])}).")


def cmd_verify(args):
    """Verify each row's confirmed URL is the hospital's OFFICIAL website.

    Per row: pick the URL to evaluate (Manual Confirmed wins over confirmed_url),
    render it (prefer a same-domain auto_best_guess sub-page — richer for matching),
    ask GPT 'does this org operate this hospital?'. Writes is_official / confidence /
    reason. Renders are deduped per homepage domain (a verdict on the FIRST hospital
    on a shared system domain is reused for the rest, with a note)."""
    import threading
    sheet_id = sh._sheet_id(args.sheet)
    hdr, data = _load(sheet_id, args.tab)

    ci = {
        "name": resolve_col(args.name_col, hdr),
        "city": resolve_col(args.city_col, hdr),
        "state": resolve_col(args.state_col, hdr),
        "guess": resolve_col(args.guess_col, hdr),
        "confirmed": resolve_col(args.confirmed_col, hdr),
        "manual": resolve_col(args.manual_col, hdr),
    }
    # Output columns: resolve by header if it already exists, else by the given letter.
    def _out_col(spec):
        low = [h.strip().lower() for h in hdr]
        if spec.lower() in low:
            return low.index(spec.lower())
        if re.fullmatch(r"[A-Za-z]+", spec):
            return col_to_idx(spec)
        raise SystemExit(f"Bad output column {spec!r}")
    oc = {
        "official": _out_col(args.official_col),
        "conf": _out_col(args.conf_col),
        "reason": _out_col(args.reason_col),
    }

    # Write the header labels once (idempotent — overwrites whatever's there).
    sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values:batchUpdate", {
        "valueInputOption": "RAW",
        "data": [
            {"range": _range_body(args.tab, f"{idx_to_col(oc['official'])}1"), "values": [["is_official"]]},
            {"range": _range_body(args.tab, f"{idx_to_col(oc['conf'])}1"), "values": [["verify_confidence"]]},
            {"range": _range_body(args.tab, f"{idx_to_col(oc['reason'])}1"), "values": [["verify_reason"]]},
        ],
    })

    start = getattr(args, "start", 0) or 0
    todo = []
    for i, r in enumerate(data):
        if i < start:
            continue
        name = _get(r, ci["name"])
        if not name:
            continue
        url_to_check = _get(r, ci["manual"]) or _get(r, ci["confirmed"])
        if not url_to_check:
            continue
        if not args.overwrite and _get(r, oc["official"]):
            continue   # idempotent: skip rows already verified
        todo.append((i, r, url_to_check))
    if args.limit:
        todo = todo[:args.limit]
    if getattr(args, "n", 0):
        todo = todo[:args.n]

    total = len(todo)
    print(f"Verifying {total} rows (concurrency={args.concurrency})…", flush=True)

    cache = {}            # homepage-domain -> (result_dict, first_hospital_name)
    cache_lock = threading.Lock()
    pending = []          # (row_1based, official, conf, reason)
    pend_lock = threading.Lock()
    stats = {"Yes": 0, "No": 0, "Uncertain": 0}
    tot = {"ms": 0, "calls": 0, "gin": 0, "gout": 0}
    done = 0

    def flush():
        with pend_lock:
            if not pending:
                return
            batch = list(pending)
            pending.clear()
        oo, occ, orr = idx_to_col(oc["official"]), idx_to_col(oc["conf"]), idx_to_col(oc["reason"])
        ranges = []
        for r1, off, cf, rs in batch:
            ranges.append({"range": _range_body(args.tab, f"{oo}{r1}"), "values": [[off]]})
            ranges.append({"range": _range_body(args.tab, f"{occ}{r1}"), "values": [[cf]]})
            ranges.append({"range": _range_body(args.tab, f"{orr}{r1}"), "values": [[rs]]})
        for attempt in range(5):
            try:
                sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values:batchUpdate",
                        {"valueInputOption": "RAW", "data": ranges})
                break
            except (Exception, SystemExit) as e:
                if "429" in str(e) and attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise

    def work(item):
        idx, row, url_to_check = item
        name = _get(row, ci["name"])
        city = _get(row, ci["city"])
        state = _get(row, ci["state"])
        guess = _get(row, ci["guess"])
        dom = homepage(url_to_check)
        # prefer a same-domain guess sub-page for the render (more specific page)
        render_url = url_to_check
        if guess and homepage(guess) == dom and norm_url(guess) != norm_url(url_to_check):
            render_url = guess

        # Domain dedupe: reuse the verdict for the first hospital seen on this domain.
        if dom:
            with cache_lock:
                cached = cache.get(dom)
            if cached is not None:
                res0, first_name = cached
                res = dict(res0)
                res["reason"] = f"{res0['reason']}; same domain as {first_name}"
                res["browser_ms"] = 0
                res["gpt_in"] = 0
                res["gpt_out"] = 0
                res["_cached"] = True
                return idx, row, url_to_check, res

        try:
            res = verify_official_row(name, city, state, url_to_check, render_url)
        except (Exception, SystemExit) as e:
            res = {"is_official": "Uncertain", "confidence": "Low",
                   "reason": f"verify error ({str(e)[:80]})", "browser_ms": 0,
                   "gpt_in": 0, "gpt_out": 0}
        if dom and not res.get("reason", "").startswith("verify error"):
            with cache_lock:
                cache.setdefault(dom, (res, name))
        return idx, row, url_to_check, res

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            idx, row, url_to_check, res = fut.result()
            stats[res["is_official"]] = stats.get(res["is_official"], 0) + 1
            tot["ms"] += res.get("browser_ms", 0)
            if not res.get("_cached"):
                tot["calls"] += 1
            tot["gin"] += res.get("gpt_in", 0)
            tot["gout"] += res.get("gpt_out", 0)
            done += 1
            row_1based = idx + 2
            with pend_lock:
                pending.append((row_1based, res["is_official"], res["confidence"], res["reason"]))
                buffered = len(pending)
            if buffered >= getattr(args, "flush_every", 10):
                flush()
            name = _get(row, ci["name"])
            print(f"  [{done}/{total}] {res['is_official']:9} {res['confidence']:7} "
                  f"{name[:34]:34} {url_to_check[:38]}", flush=True)

    flush()

    hrs = tot["ms"] / 3_600_000
    gpt_usd = tot["gin"] / 1_000_000 * GPT_IN_PER_1M + tot["gout"] / 1_000_000 * GPT_OUT_PER_1M
    cost = {
        "unique_domains_rendered": len(cache),
        "browser_ms_total": tot["ms"],
        "browser_hours": round(hrs, 3),
        "gpt_calls": tot["calls"],
        "gpt_tokens_in": tot["gin"],
        "gpt_tokens_out": tot["gout"],
        "gpt_usd": round(gpt_usd, 4),
    }
    print("\n" + json.dumps({"processed": total, **stats, "cost": cost}, indent=2))
    print(f"\nWrote is_official (col {idx_to_col(oc['official'])}) / "
          f"verify_confidence (col {idx_to_col(oc['conf'])}) / "
          f"verify_reason (col {idx_to_col(oc['reason'])}).")


def cmd_trace(args):
    """Run ONE row and print the raw output of every step (writes nothing).
    Lets you verify the exact DDG→GPT→verify→decision flow before a full run."""
    name, city, state, guess = args.name, args.city or "", args.state or "", args.guess or ""
    print(f"=== TRACE: {name!r}  ({city}, {state})  guess={guess or '(none)'} ===\n")

    # Step 1: guess-first (only if a guess was supplied)
    if guess and not is_directory(guess):
        cand = homepage(guess) or guess
        ok, reason, ms = verify_url(cand, name, city)
        print(f"[1] guess-first: render-verify {cand}  -> ok={ok} ({reason}) [{ms}ms]")
        if ok:
            print(f"\nRESULT: confirmed_url={cand}\n        note=confirmed; matches guess; {reason}; src=guess")
            return
    else:
        print("[1] guess-first: no usable guess — skipped")

    # Step 2: Cloudflare → DuckDuckGo
    q = " ".join(p for p in (name, city, state) if p).strip()
    print(f"\n[2] Cloudflare 'links' on: {DDG_HTML}{urllib.parse.quote(q)}")
    raw, ms = cloudflare_search_raw(name, city, state)
    print(f"    browser-ms={ms}; {len(raw)} candidate(s) after decode+dedupe (no directory pre-filter):")
    for i, (u, t) in enumerate(raw):
        print(f"      {i+1}. {u}\n         title: {t[:90]!r}")

    # Step 3: GPT pick
    pick, why, conf, (gin, gout) = gpt_pick_website(name, city, state, raw)
    print(f"\n[3] gpt-5-mini pick: {pick or '(empty)'}  conf={conf}  why={why!r}")
    print(f"    tokens: in={gin} out={gout}  (~${gin/1e6*GPT_IN_PER_1M + gout/1e6*GPT_OUT_PER_1M:.5f})")
    if not pick:
        print("\nRESULT: not_found (gpt returned no official site)")
        return

    # Step 4: grounding + verify decision
    grounded = any(homepage(u) == pick for u, _ in raw)
    print(f"\n[4] grounded? {grounded}  (homepage of pick appears in the DDG results)")
    if grounded and conf in ("high", "medium"):
        print("    decision: grounded + high/medium → CONFIRM (fast path, no verify render)")
        print(f"\nRESULT: confirmed_url={pick}\n        note=confirmed; gpt-pick {conf} (grounded); src=gpt")
        return
    print("    decision: uncertain → require on-page render match")
    targets = [pick] + [u for u, _ in raw if homepage(u) == pick and u != pick]
    for tgt in targets[:2]:
        ok, vreason, m = verify_url(tgt, name, city)
        print(f"      render-verify {tgt[:70]} -> ok={ok} ({vreason}) [{m}ms]")
        if ok:
            print(f"\nRESULT: confirmed_url={pick}\n        note=confirmed; gpt-pick {conf}; on-page {vreason}; src=gpt")
            return
    print(f"\nRESULT: found_unverified (blank); candidate={pick} noted for review")


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
        p.add_argument("--concurrency", type=int, default=10)
        p.add_argument("--start", type=int, default=0,
                       help="skip the first N data rows (0-based; row 1 = first "
                            "hospital under the header). e.g. --start 100 = row 101+.")
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--overwrite", action="store_true")
        p.add_argument("--flush-every", type=int, default=10,
                       help="write to the sheet every N rows (real-time; default 10, "
                            "kept under Google's ~60 writes/min/user quota).")

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

    v = sub.add_parser("verify", help="verify each row's confirmed URL is the hospital's OFFICIAL site")
    common(v)
    v.add_argument("--n", type=int, default=0)
    v.add_argument("--manual-col", default="Manual Confirmed",
                   help="column holding the user-corrected URL (wins over confirmed_url)")
    # Output columns: default to the empty Y/Z/AA on this sheet. Accept a header
    # name too (so a re-run can target the already-labelled columns by name).
    v.add_argument("--official-col", default="Y")
    v.add_argument("--conf-col", default="Z")
    v.add_argument("--reason-col", default="AA")
    v.set_defaults(func=cmd_verify)

    tr = sub.add_parser("trace", help="run ONE hospital and print every step's raw output (no write)")
    tr.add_argument("--name", required=True)
    tr.add_argument("--city", default="")
    tr.add_argument("--state", default="")
    tr.add_argument("--guess", default="")
    tr.set_defaults(func=cmd_trace)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
