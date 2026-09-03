"""
Form Filler / Survey Bot
-------------------------
Auto-fills a target form using data rows from Excel/CSV or a Google Sheet
(published-as-CSV URL). Uses Playwright headless Chromium — one submission
per row — takes a screenshot of the post-submit page.

Usage flow (invoked from server.py endpoints):
    1. POST /api/form-filler/jobs  -> create job, upload data, kick off bg task
    2. GET  /api/form-filler/jobs           -> list jobs
    3. GET  /api/form-filler/jobs/{id}      -> status + progress
    4. GET  /api/form-filler/jobs/{id}/download -> ZIP (screenshots + report.csv)
"""
from __future__ import annotations
import asyncio
import csv
import io
import os
import random
import re
import shutil
import time
import uuid
import zipfile
import logging

# Ensure Playwright finds the Chromium that was installed at the system path.
# The pip `playwright install chromium` command put browsers in /pw-browsers/;
# Playwright looks at the default ~/.cache/ms-playwright unless this env var
# is set. MUST be set BEFORE `from playwright.async_api import ...`.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and os.path.isdir("/pw-browsers"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/pw-browsers"

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

import httpx
import pandas as pd
from playwright.async_api import async_playwright, Page, BrowserContext

# 🛡️ Central anti-detect engine — IMPORTED LAZILY (inside the runner)
# to avoid circular imports. anti_detect_engine itself imports from
# real_user_traffic, which imports from form_filler — a top-level
# import here would deadlock. Lazy resolution sidesteps that.
def _get_stealth_launcher():
    try:
        from anti_detect_engine import launch_stealth_session  # type: ignore
        return launch_stealth_session
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            f"form_filler: anti_detect_engine unavailable ({e}); "
            f"falling back to vanilla launch"
        )
        return None

# Cross-module helpers — survey click + AI vision fallback
try:
    from rut_flash_helpers import survey_click_v2 as _rut_survey_click_v2
except Exception:  # noqa: BLE001
    _rut_survey_click_v2 = None
try:
    from ai_vision import (
        screenshot_for_ai as _ai_screenshot,
        ask_ai_for_next_action as _ai_ask,
        execute_action as _ai_execute,
    )
except Exception:  # noqa: BLE001
    _ai_screenshot = None
    _ai_ask = None
    _ai_execute = None

logger = logging.getLogger(__name__)

# ─────── Storage root ──────────────────────────────────────────────
# Docker uses /app/backend; native/local/CI must not crash on import.
def _resolve_results_root(dirname: str) -> Path:
    import tempfile

    candidates = []
    env_root = (os.environ.get("KREXION_RESULTS_ROOT") or "").strip()
    if env_root:
        candidates.append(Path(env_root) / dirname)
    candidates.append(Path("/app/backend") / dirname)
    candidates.append(Path(__file__).resolve().parent / dirname)
    candidates.append(Path.home() / ".local" / "share" / "Krexion" / dirname)
    candidates.append(Path(tempfile.gettempdir()) / "krexion" / dirname)
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            continue
    return candidates[-1]


RESULTS_ROOT = _resolve_results_root("form_filler_results")

# In-memory job registry (jobs also persisted in Mongo; this is the hot cache)
JOBS: Dict[str, Dict[str, Any]] = {}

# ─────── Captcha detection heuristics ──────────────────────────────
# We look for ACTUAL challenge widgets / iframes that block interaction —
# NOT any random script tag. Cloudflare's preview-pod / proxy edge often
# injects `<script>…/cdn-cgi/challenge-platform/scripts/jsd/main.js…</script>`
# (passive bot analytics, not a real challenge) into every response —
# matching that bare string was producing 100% false positives and made
# Real-User-Traffic mark every preview-pod tracker visit as
# `skipped_captcha`. The patterns below match only genuine, visible
# challenge surfaces:
#   • iframe srcs on the canonical challenge hosts (challenges.cloudflare.com
#     / google reCAPTCHA / hCaptcha)
#   • specific widget classes / IDs that imply a rendered challenge
#   • the literal Turnstile widget tag.
CAPTCHA_PATTERNS = [
    re.compile(r'src=["\'][^"\']*challenges\.cloudflare\.com', re.I),
    re.compile(r'src=["\'][^"\']*google\.com/recaptcha', re.I),
    re.compile(r'src=["\'][^"\']*recaptcha\.net', re.I),
    re.compile(r'src=["\'][^"\']*hcaptcha\.com', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*g-recaptcha\b', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*h-captcha\b', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*cf-turnstile\b', re.I),
    re.compile(r'<iframe[^>]+title=["\'][^"\']*recaptcha', re.I),
    re.compile(r'<iframe[^>]+title=["\'][^"\']*hcaptcha', re.I),
    # Real Cloudflare interstitial pages — the "Just a moment…" page —
    # have BOTH the `__cf_chl_` query-arg JS AND the cf-mitigated script;
    # the bare "/cdn-cgi/challenge-platform/scripts/jsd/main.js" injection
    # used by preview pods does NOT have these.
    re.compile(r'__cf_chl_jschl_tk__|__cf_chl_managed_tk__', re.I),
    re.compile(r'cf-mitigated|cf-error-details', re.I),
]


async def _page_has_captcha(page: Page) -> bool:
    """Return True only when a GENUINE captcha / interactive challenge
    widget is visible on the page. Returns False for Cloudflare's passive
    /cdn-cgi/challenge-platform/scripts/jsd/main.js bot analytics
    injection which preview-pod / proxy edges add to every response."""
    try:
        html = await page.content()
    except Exception:
        return False
    return any(p.search(html) for p in CAPTCHA_PATTERNS)


# ─────── Input data loading ────────────────────────────────────────
def load_rows_from_excel(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Load rows from an uploaded Excel/CSV file. Returns list of dicts keyed
    by column name (snake-cased + lower-cased for robust matching)."""
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))
    df.columns = [_norm_key(c) for c in df.columns]
    return df.to_dict(orient="records")


async def _load_rows_from_google_sheet_uncached(public_csv_url: str) -> List[Dict[str, Any]]:
    """Actual fetch implementation — wrapped by `load_rows_from_google_sheet`
    which adds an async TTL cache + per-URL single-flight (see gsheet_cache).

    Two paths, tried in order:

    1. **Authenticated path** (when GOOGLE_SHEETS_SA_PATH or _JSON env var is
       set). Uses the Sheets API to read the sheet directly. Works for any
       sheet shared with the service-account email OR shared "Anyone with
       link → Viewer/Editor". This is also the path that supports
       *deleting* consumed rows during a job.

    2. **Public CSV fallback** (legacy). Works only when the sheet is
       *Publish to web → CSV* OR shared as "Anyone with the link → Viewer".
       Used when no SA credentials are configured.
    """
    # Path 1: authenticated read
    try:
        import gsheet_writer  # local import to avoid hard dep at import time
        if gsheet_writer.is_write_enabled():
            loop = asyncio.get_running_loop()
            rows = await loop.run_in_executor(None, gsheet_writer.read_rows, public_csv_url)
            return rows or []
    except Exception as e:
        # Authenticated path failed (auth error, network, etc.) — fall
        # through to the public CSV path so user-uploaded sheets shared as
        # "Anyone with link" still work even if SA creds are misconfigured.
        import logging
        logging.getLogger(__name__).warning(f"authenticated gsheet read failed, falling back to CSV: {e}")

    # Path 2: legacy public CSV export
    target_gid: Optional[str] = None
    gid_match = re.search(r"[?&#]gid=(\d+)", public_csv_url)
    if gid_match:
        target_gid = gid_match.group(1)
    if "/edit" in public_csv_url and "export" not in public_csv_url:
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", public_csv_url)
        if m:
            public_csv_url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
            if target_gid is not None:
                public_csv_url += f"&gid={target_gid}"
    # Generous 5-minute timeout — Google's CSV export can be slow for
    # very large sheets (200k+ rows), and this fetch always runs in a
    # background task now (never blocks the user-facing endpoint), so
    # we can afford to wait. Failures here just mark the RUT job as
    # failed with a clear error message; the user retries.
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as cli:
        r = await cli.get(public_csv_url)
        if r.status_code != 200:
            raise ValueError(f"Could not fetch Google Sheet (HTTP {r.status_code}). Make sure it's 'Publish to web → CSV' or the shared view URL.")
        df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [_norm_key(c) for c in df.columns]
    return df.to_dict(orient="records")


async def load_rows_from_google_sheet(public_csv_url: str) -> List[Dict[str, Any]]:
    """Cached, single-flight wrapper around the actual sheet fetch.

    All callers in the codebase go through this function — that means
    one cache layer protects RUT bot, CPI worker, Form Filler, upload
    list refresh, proxy/UA pickers, etc. With 10 users hammering the
    same sheet concurrently this turns 10 round-trips into 1. Within
    the TTL window (default 20 s, env GSHEET_CACHE_TTL) all reads are
    in-memory."""
    import gsheet_cache  # local import keeps form_filler import-light
    return await gsheet_cache.get_or_fetch(
        public_csv_url,
        lambda: _load_rows_from_google_sheet_uncached(public_csv_url),
    )


def _norm_key(k: str) -> str:
    """Normalise a column header for robust matching (lower + non-alnum→'_')."""
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


# ─────── Column alias map ──────────────────────────────────────────
# Maps common spreadsheet column names → the form field name they likely match.
# Used as a second-pass fallback when the raw key doesn't match any field.
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "first":       ["first_name", "fname", "firstname", "given_name", "given"],
    "first_name":  ["first", "fname", "firstname", "given_name"],
    "last":        ["last_name", "lname", "lastname", "surname", "family_name"],
    "last_name":   ["last", "lname", "lastname", "surname", "family_name"],
    "fullname":    ["name", "full_name"],
    "name":        ["full_name", "fullname"],
    "email":       ["email_address", "emailaddress", "e_mail", "mail"],
    "cellphone":   ["phone", "phone_number", "phonenumber", "mobile", "mobilephone", "cell", "contact", "tel", "telephone"],
    "cell":        ["phone", "phone_number", "mobile", "cellphone"],
    "mobile":      ["phone", "phone_number", "cellphone"],
    "phone":       ["cellphone", "cell", "mobile", "phone_number", "tel", "contact", "telephone"],
    "address":     ["street_address", "streetaddress", "street", "addr", "address1", "address_1", "line1"],
    "street":      ["address", "street_address", "streetaddress", "addr"],
    "address1":    ["address", "street_address", "line1"],
    "zip":         ["zipcode", "zip_code", "postal", "postal_code", "postcode"],
    "zipcode":     ["zip", "zip_code", "postal", "postal_code"],
    "postal":      ["zip", "zipcode", "zip_code", "postal_code"],
    "dob":         ["date_of_birth", "birth", "birthdate", "birthday"],
    "day":         ["dob_day", "dobday", "birth_day", "birthday", "bday", "day_of_birth"],
    "month":       ["dob_month", "dobmonth", "birth_month", "bmonth", "month_of_birth"],
    "year":        ["dob_year", "dobyear", "birth_year", "byear", "year_of_birth"],
    "state":       ["region", "province"],
    "city":        ["town", "locality"],
}


def _value_for_key(row: Dict[str, Any], candidate_keys: List[str]) -> Optional[Any]:
    """Given a list of normalised keys (from a form field's name/id/placeholder
    /label), return a matching value from `row`. Uses exact match, then aliases,
    then fuzzy substring match."""
    for k in candidate_keys:
        if not k:
            continue
        # 1. Exact match
        if k in row and row[k] not in (None, ""):
            return row[k]
        # 2. Alias match — does any alias of a row column equal this key?
        for rk, rv in row.items():
            if rv in (None, ""):
                continue
            if k in _COLUMN_ALIASES.get(rk, []):
                return rv
        # 3. Does any alias of `k` exist in row?
        for alias in _COLUMN_ALIASES.get(k, []):
            if alias in row and row[alias] not in (None, ""):
                return row[alias]
    # 4. Fuzzy substring match as last resort
    for k in candidate_keys:
        if not k:
            continue
        for rk, rv in row.items():
            if rv in (None, ""):
                continue
            if (rk in k or k in rk) and len(rk) >= 3:
                return rv
    return None


def _reformat_value(cand_keys: List[str], attrs: dict, raw_value: Any) -> str:
    """Apply common format conversions — phone numbers, for example, often
    need `xxx-xxx-xxxx` when the source has plain digits."""
    s = str(raw_value).strip()
    joined_key = " ".join(cand_keys) + " " + (attrs.get("placeholder") or "")
    joined_key = joined_key.lower()
    is_phone = any(tok in joined_key for tok in ("phone", "cell", "mobile", "tel"))
    if is_phone:
        digits = re.sub(r"\D", "", s)
        if len(digits) == 10:
            # Prefer hyphenated format when the placeholder hints it
            if "-" in (attrs.get("placeholder") or "") or "000-000-0000" in joined_key:
                return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
            if "(" in (attrs.get("placeholder") or ""):
                return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
            # Default: return hyphenated (most common US format)
            return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
        if len(digits) == 11 and digits.startswith("1"):
            d = digits[1:]
            return f"{d[0:3]}-{d[3:6]}-{d[6:10]}"
    return s


# ─────── Human-like field interaction (anti-detect) ───────────────
# These helpers replace Playwright's instant .fill() with a realistic
# focus → mouse-move → click-with-offset → per-char typing pattern that
# bypasses behavior-tracking fraud detectors (Anura, IPQS deep mode,
# PerimeterX, HUMAN security, ArkoseLabs heuristics). Every helper is
# wrapped in try/except so a quirky page can never abort a visit — we
# always fall back to the original .fill() path on failure.

async def _human_mouse_move_to(page: Page, el) -> bool:
    """Move mouse from current position to a random point inside the
    bounding box of `el`, using 8-18 micro-steps (bezier-like). Returns
    True if movement landed inside the element so the caller knows it
    can safely .click() / .focus() / type. NEVER raises."""
    try:
        box = await el.bounding_box()
        if not box or box["width"] < 2 or box["height"] < 2:
            return False
        # Pick a random target point well inside the element (avoid edge
        # rounding artifacts on rounded buttons).
        pad_x = max(2, min(box["width"] * 0.15, 24))
        pad_y = max(2, min(box["height"] * 0.15, 16))
        tx = box["x"] + pad_x + random.random() * (box["width"] - 2 * pad_x)
        ty = box["y"] + pad_y + random.random() * (box["height"] - 2 * pad_y)
        # Mouse move with realistic step count — Playwright's `steps`
        # parameter interpolates linearly so 8-18 steps look like a
        # smooth human-speed motion.
        await page.mouse.move(tx, ty, steps=random.randint(8, 18))
        # Tiny dwell so the move event settles before the click —
        # detectors check that mousemove → click is NOT instant.
        await page.wait_for_timeout(random.randint(40, 140))
        return True
    except Exception:
        return False


async def _human_type_field(page: Page, el, value: str) -> bool:
    """Fill `el` like a real human:
       1. Mouse-move to a random offset inside the field
       2. Click (focus) — uses keyboard.press('Tab') with 30% chance if
          the field is the *next* logical sibling (currently always
          mouse-click for simplicity; TAB navigation is added at the
          loop level via `_human_tab_or_click`).
       3. Clear any existing value
       4. Type character-by-character with variable delay (50-180ms),
          occasional "thinking pause" (300-800ms) every 3-8 chars, and
          a small chance of typo+backspace (~6%).
       5. Special handling: @ and . in emails get a slight pre-pause
          (humans hesitate at punctuation in unfamiliar usernames).
    Returns True on success. NEVER raises.
    """
    s = str(value or "")
    if not s:
        return False
    try:
        # Move + click to focus the field (realistic offset, not center).
        moved = await _human_mouse_move_to(page, el)
        if moved:
            try:
                await el.click(timeout=3000)
            except Exception:
                # If click failed (covered by overlay), just focus —
                # focus still dispatches the focus event detectors look for.
                try:
                    await el.focus()
                except Exception:
                    pass
        else:
            try:
                await el.focus()
            except Exception:
                pass

        # Tiny pause after focus before typing — humans don't start
        # hammering keys instantly.
        await page.wait_for_timeout(random.randint(80, 260))

        # ── 2026-01 BUG FIX ────────────────────────────────────────────
        # Clear existing content (Ctrl+A → Delete). PREVIOUSLY this fired
        # unconditionally, but if the click/focus above silently failed
        # (e.g. the element is a hidden div, an overlay covers it, or
        # the selector matched something that isn't actually focusable)
        # the Ctrl+A would land on `document.body` and select the ENTIRE
        # PAGE'S TEXT — producing the "everything is blue" screenshots
        # users reported. Verify the active element really is our text
        # input before pressing the shortcut.
        try:
            is_focused = await page.evaluate(
                """(el) => {
                    const a = document.activeElement;
                    if (!a) return false;
                    if (el && a !== el) return false;
                    const tag = (a.tagName || '').toUpperCase();
                    if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
                    if (a.isContentEditable) return true;
                    return false;
                }""",
                el,
            )
        except Exception:
            is_focused = False
        if is_focused:
            try:
                await page.keyboard.press("Control+a")
                await page.wait_for_timeout(random.randint(20, 60))
                await page.keyboard.press("Delete")
                await page.wait_for_timeout(random.randint(30, 90))
            except Exception:
                pass

        # Type char-by-char with realistic variance
        chars = list(s)
        i = 0
        chars_since_pause = 0
        next_thinking_pause_at = random.randint(3, 8)
        # ~6% typo rate per word boundary, only on alphabetic chars
        typo_done = False
        while i < len(chars):
            ch = chars[i]

            # Occasional "thinking pause" every 3-8 chars (15% of the time)
            if chars_since_pause >= next_thinking_pause_at and random.random() < 0.15:
                await page.wait_for_timeout(random.randint(300, 800))
                chars_since_pause = 0
                next_thinking_pause_at = random.randint(3, 8)

            # Pre-pause at email/url punctuation (@ . - _)
            if ch in "@._-" and random.random() < 0.45:
                await page.wait_for_timeout(random.randint(120, 320))

            # Small chance of typo on alphabetic chars (one typo per field max)
            if (
                not typo_done
                and ch.isalpha()
                and i > 1
                and i < len(chars) - 2
                and random.random() < 0.06
            ):
                # Pick a neighbouring letter on QWERTY for realism
                neighbours = {
                    "a": "sq", "s": "ad", "d": "sf", "f": "dg", "g": "fh",
                    "h": "gj", "j": "hk", "k": "jl", "l": "k",
                    "q": "wa", "w": "qe", "e": "wr", "r": "et", "t": "ry",
                    "y": "tu", "u": "yi", "i": "uo", "o": "ip", "p": "o",
                    "z": "xa", "x": "zc", "c": "xv", "v": "cb", "b": "vn",
                    "n": "bm", "m": "n",
                }.get(ch.lower(), ch)
                wrong = random.choice(list(neighbours)) if neighbours else ch
                if ch.isupper():
                    wrong = wrong.upper()
                try:
                    await page.keyboard.type(wrong, delay=random.randint(50, 130))
                    await page.wait_for_timeout(random.randint(180, 380))
                    await page.keyboard.press("Backspace")
                    await page.wait_for_timeout(random.randint(80, 200))
                except Exception:
                    pass
                typo_done = True
                # Don't advance i — type the correct char next iteration

            # Variable per-char delay: most 50-150ms, some 150-280ms
            if random.random() < 0.18:
                delay = random.randint(150, 280)
            else:
                delay = random.randint(50, 150)
            try:
                await page.keyboard.type(ch, delay=delay)
            except Exception:
                return False
            i += 1
            chars_since_pause += 1

        # Small "review" pause after finishing — humans glance back at
        # what they typed before moving on.
        await page.wait_for_timeout(random.randint(120, 380))

        # Dispatch blur via Tab — but only here in the helper if caller
        # doesn't take over field navigation. Caller decides via
        # `_human_tab_or_click` so we DON'T press Tab inside this fn.
        return True
    except Exception as e:
        logger.debug(f"_human_type_field failed: {e}")
        return False


async def _human_tab_or_pause(page: Page) -> None:
    """Between fields: 30% chance press Tab (real users often tab),
    70% chance just wait 600-2000ms before the loop moves mouse to the
    next field. NEVER raises."""
    try:
        if random.random() < 0.30:
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(random.randint(120, 320))
        else:
            await page.wait_for_timeout(random.randint(600, 2000))
    except Exception:
        pass


# ─────── Landing-page CTA auto-click ───────────────────────────────
_LANDING_CTA_SELECTORS = [
    'button:has-text("UNLOCK")', 'a:has-text("UNLOCK")',
    'button:has-text("Claim")',  'a:has-text("Claim")',
    'button:has-text("Get Started")', 'a:has-text("Get Started")',
    'button:has-text("Start Now")', 'a:has-text("Start Now")',
    'button:has-text("Start")', 'a:has-text("Start")',
    'button:has-text("Continue")', 'a:has-text("Continue")',
    'button:has-text("Begin")', 'a:has-text("Begin")',
    'button:has-text("Sign up")', 'a:has-text("Sign up")',
    'button:has-text("Enter")', 'a:has-text("Enter")',
    'button:has-text("Next")', 'a:has-text("Next")',
    'a.btn', 'button.btn-primary', 'button.cta', '.cta-button',
]


async def _dismiss_popups(page: Page):
    """Best-effort: dismiss cookie banners / popups / age gates that block clicks."""
    for sel in [
        'button:has-text("Accept")', 'button:has-text("Accept All")',
        'button:has-text("I Agree")', 'button:has-text("Agree")',
        'button:has-text("OK")', 'button:has-text("Got it")',
        'button:has-text("Allow")', 'button:has-text("Yes")',
        '[aria-label="Close"]', 'button.close', '.cookie-accept',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(500)
        except Exception:
            continue


async def _ensure_form_visible(
    page: Page,
    max_tries: int = 2,
    skip_repeat_click: Optional[Any] = None,
) -> int:
    """If the current page has no fillable inputs, click a prominent CTA up to
    `max_tries` times. Returns the number of fillable inputs finally visible."""
    for attempt in range(max_tries + 1):
        await _dismiss_popups(page)
        inputs = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), "
            "textarea, select"
        )
        # Count real text-input fields (at least one visible)
        visible_count = 0
        for inp in inputs[:40]:
            try:
                if await inp.is_visible():
                    visible_count += 1
            except Exception:
                pass
        if visible_count >= 2:
            return visible_count
        if attempt >= max_tries:
            return visible_count
        # Click first visible CTA that is NOT the original offer/tracker URL.
        clicked = False
        for sel in _LANDING_CTA_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    if skip_repeat_click:
                        try:
                            href = await el.get_attribute("href")
                            page_url = page.url or ""
                            if href and skip_repeat_click(href, page_url):
                                continue
                        except Exception:
                            pass
                    await el.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            return visible_count
        # Wait for navigation / form to render. Some landing pages take >15s to
        # settle (heavy analytics / third-party JS) — we wait both for DOM
        # content and then networkidle, but silence timeouts.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
    return 0


async def _tick_consent_checkboxes(page: Page):
    """Tick any visible unchecked checkbox before submit (most forms have a
    single 'I agree / I consent' that blocks submit if unchecked).
    Uses click() + JS fallback because some sites bind custom handlers."""
    try:
        boxes = await page.query_selector_all("input[type=checkbox]")
        for cb in boxes:
            try:
                if not await cb.is_visible():
                    continue
                is_checked = await cb.is_checked()
                if not is_checked:
                    try:
                        await cb.check()
                    except Exception:
                        # JS fallback
                        await cb.evaluate("""e => {
                            e.checked = true;
                            e.dispatchEvent(new Event('change', {bubbles: true}));
                            e.dispatchEvent(new Event('click', {bubbles: true}));
                        }""")
            except Exception:
                continue
    except Exception:
        pass


# Selectors that typically DISMISS a "review / exit-intent / are you sure" modal
# and send the user back to the form for another submit attempt.
# NOTE: "Disregard" on some sites is actually the real submit (it closes the
# modal AND calls formSubmit()). We prefer buttons whose onclick attribute
# contains 'submit' or 'form', falling back to text heuristics.
_MODAL_SUBMIT_PREFERRED = [
    'button:has-text("Submit anyway")',
    'button:has-text("Yes, Submit")',
    'button:has-text("Yes, continue")',
    'button:has-text("Confirm")',
    'button:has-text("Disregard")',
    'a:has-text("Disregard")',
    'button:has-text("Continue")',
    'a:has-text("Continue")',
    'button:has-text("Yes")',
    'a:has-text("Yes")',
]


async def _dismiss_review_modal(page: Page) -> bool:
    """If a post-submit modal appeared, find the button that ACTUALLY submits
    (not the one that just returns to the form). Preferred picks:
        1. A button with onclick containing `submit` or `form`
        2. Text-based heuristics: Submit / Disregard / Continue / Yes / Confirm
    Returns True if a button was clicked."""
    # Strategy 1: inspect onclick attributes for submit intent
    try:
        candidates = await page.query_selector_all(
            ".modal button, .modal a, [role=dialog] button, [role=dialog] a, "
            ".popup button, .popup a, .overlay button, .overlay a, "
            "a.confirm, a.disregard, button.confirm, button.disregard"
        )
        for el in candidates:
            try:
                if not await el.is_visible():
                    continue
                info = await el.evaluate("""e => ({
                    onclick: (e.getAttribute('onclick') || '').toLowerCase(),
                    text: (e.innerText || '').trim().toLowerCase(),
                    cls: (e.className || '').toLowerCase()
                })""")
                if any(tok in info["onclick"] for tok in ("submit", "formsubmit", "form.submit")):
                    await el.click()
                    await page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 2: text-based heuristics
    for sel in _MODAL_SUBMIT_PREFERRED:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


# ─────── Form field auto-matching ───────────────────────────────────
async def _fill_form(page: Page, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    For every input/textarea/select on the page, try to find a matching
    column in `row` by comparing the normalised forms of:
        name, id, placeholder, aria-label, label text
    Returns {filled: [keys], skipped: [keys], matched: n}
    """
    filled: List[str] = []
    try:
        inputs = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), "
            "textarea, select"
        )
    except Exception as e:
        return {"filled": [], "skipped": list(row.keys()), "error": str(e)}

    for el in inputs:
        try:
            # 2026-05 — visibility check carve-out for <select>
            # Bootstrap-Select / Select2 / Chosen / React-Select all HIDE
            # the native <select> via display:none and surface a custom
            # button + dropdown UI. is_visible() returns False on the
            # native element, so the OLD `continue` here meant we
            # silently skipped EVERY plugin-styled dropdown — leaving
            # Birth Month / Birth Day / Birth Year empty on lead-gen
            # pages that use Bootstrap-Select (the screenshot the user
            # reported).
            #
            # For <select>, accept the element as long as it's IN the
            # DOM and not aria-hidden / display-none on an ancestor that
            # truly removes it from the form (the JS-driven select_option
            # in _select_option_smart below handles the rest).
            _tag_local = ""
            try:
                _tag_local = (await el.evaluate("e => e.tagName ? e.tagName.toLowerCase() : ''")) or ""
            except Exception:
                pass
            if _tag_local == "select":
                # Skip only if the element was detached or in a closed
                # <details> / hidden ancestor — anything else (including
                # bootstrap-select hidden native) we want to fill via JS.
                try:
                    _attached_ok = await el.evaluate(
                        "e => !!(e.isConnected && e.form)"
                    )
                except Exception:
                    _attached_ok = True
                if not _attached_ok:
                    continue
            else:
                # Original visible-check path for inputs / textareas.
                try:
                    if not await el.is_visible():
                        continue
                except Exception:
                    pass
        except Exception:
            pass
        try:
            attrs = await el.evaluate("""el => ({
                name: el.name || '',
                id: el.id || '',
                type: (el.type || '').toLowerCase(),
                placeholder: el.placeholder || '',
                aria: el.getAttribute('aria-label') || '',
                tag: el.tagName.toLowerCase()
            })""")
        except Exception:
            continue
        if attrs.get("type") in ("checkbox", "radio"):
            continue  # handled separately by _tick_consent_checkboxes

        # Gather candidate keys
        cand_keys = [
            _norm_key(attrs.get("name", "")),
            _norm_key(attrs.get("id", "")),
            _norm_key(attrs.get("placeholder", "")),
            _norm_key(attrs.get("aria", "")),
        ]
        cand_keys = [k for k in cand_keys if k]

        # Try label text too
        try:
            label_text = await el.evaluate("""el => {
                if (el.id) {
                    const l = document.querySelector('label[for="'+el.id+'"]');
                    if (l) return l.innerText || '';
                }
                const parentLabel = el.closest('label');
                return parentLabel ? parentLabel.innerText : '';
            }""")
            if label_text:
                cand_keys.append(_norm_key(label_text))
        except Exception:
            pass

        value = _value_for_key(row, cand_keys)
        if value is None:
            # Date dropdown heuristic: if this is a <select> and we can detect
            # whether it's day/month/year based on options count
            if attrs.get("tag") == "select":
                try:
                    opts_count = await el.evaluate("e => e.options.length")
                    if opts_count in (13, 14) and "month" in row:  # 12 months + placeholder
                        value = row.get("month")
                        cand_keys.append("month")
                    elif opts_count in (29, 30, 31, 32) and "day" in row:
                        value = row.get("day")
                        cand_keys.append("day")
                    elif opts_count > 30 and "year" in row:
                        # likely a year dropdown
                        value = row.get("year")
                        cand_keys.append("year")
                except Exception:
                    pass
        if value is None or value == "":
            continue

        final_value = _reformat_value(cand_keys, attrs, value)
        try:
            if attrs.get("tag") == "select":
                # 2026-05 — JS-driven select for plugin-hidden natives.
                # Playwright's el.select_option() waits for actionability
                # (element visible + stable), which fails when Bootstrap-
                # Select / Select2 / Chosen hide the native <select>. The
                # native still drives form submission, so setting .value
                # + dispatching change events is the correct fix.
                #
                # We try in this order:
                #   1. JS: find option whose label OR value matches
                #      `final_value` (trimmed, case-insensitive); set
                #      .value + dispatch input/change events + jQuery
                #      .selectpicker('refresh') / .chosen:updated so the
                #      visible plugin UI stays in sync.
                #   2. JS by numeric index if value looks like "1", "2"...
                #   3. Fall back to native el.select_option (label →
                #      value → index) for plain visible selects.
                _str_val = str(final_value)
                _js_ok = False
                _js_src = """(args) => {
                    const el = args.el;
                    const raw = String(args.raw);
                    const wantTrim = raw.trim().toLowerCase();
                    function setIt(opt) {
                        el.value = opt.value;
                        try { el.dispatchEvent(new Event('input',  {bubbles: true})); } catch(e){}
                        try { el.dispatchEvent(new Event('change', {bubbles: true})); } catch(e){}
                        try {
                            if (window.jQuery && window.jQuery(el).length) {
                                window.jQuery(el).val(opt.value).trigger('change');
                                try { window.jQuery(el).selectpicker('refresh'); } catch(e){}
                                try { window.jQuery(el).trigger('chosen:updated'); } catch(e){}
                            }
                        } catch(e){}
                        return true;
                    }
                    // 1) exact label / value (case-insensitive)
                    for (let i = 0; i < el.options.length; i++) {
                        const o = el.options[i];
                        const t = (o.text || '').trim().toLowerCase();
                        const l = (o.label || '').trim().toLowerCase();
                        if (t === wantTrim || l === wantTrim || String(o.value).toLowerCase() === wantTrim) {
                            return setIt(o);
                        }
                    }
                    // 2) substring (handles 'May' matching 'May (5)')
                    for (let i = 0; i < el.options.length; i++) {
                        const o = el.options[i];
                        const t = (o.text || '').trim().toLowerCase();
                        if (t && wantTrim && t.indexOf(wantTrim) === 0) {
                            return setIt(o);
                        }
                    }
                    // 3) numeric index (raw="5" → options[5])
                    if (/^\\d+$/.test(raw)) {
                        const idx = parseInt(raw, 10);
                        if (idx >= 0 && idx < el.options.length) {
                            return setIt(el.options[idx]);
                        }
                    }
                    return false;
                }"""
                try:
                    _js_ok = bool(await page.evaluate(
                        _js_src, {"el": el, "raw": _str_val}
                    ))
                except Exception:
                    _js_ok = False
                if _js_ok:
                    # JS path worked — for the few plugin UIs that ALSO
                    # need a click on the visible proxy (rare), the
                    # form's own change handler typically re-renders the
                    # visible label from el.value. We're done.
                    filled.append(cand_keys[0] if cand_keys else "")
                    continue
                # JS missed — fall through to Playwright's actionable
                # select_option (works for plain visible <select>).
                try:
                    await el.select_option(value=_str_val)
                except Exception:
                    try:
                        await el.select_option(label=_str_val)
                    except Exception:
                        # Last resort — try by numeric index (month as "1" → index 1)
                        try:
                            idx = int(_str_val)
                            await el.select_option(index=idx)
                        except Exception:
                            continue
            else:
                # ── 2026-01 Anti-detect: human-like typing first ─────
                # Replaces the instant .fill() with a focus → mouse-move
                # → click-with-offset → per-char typing flow. This
                # dispatches realistic keyboard events (keydown/keypress/
                # input/keyup) with variable per-char delay + occasional
                # typo+backspace + thinking pauses — bypasses behaviour-
                # tracking fraud detectors (Anura, IPQS deep, PerimeterX).
                #
                # We still keep the .fill() / JS-setter / keyboard.type
                # fallbacks below in case the human-typed value gets
                # blocked by a JS input mask (phone `000-000-0000`) or
                # a React/Vue-controlled component that fights keystrokes.
                human_ok = False
                try:
                    human_ok = await _human_type_field(page, el, str(final_value))
                except Exception as e:
                    logger.debug(f"human_type_field raised: {e}")

                # Verify the human-typed value actually landed. If the
                # field has a JS mask or React controlled-component
                # state, the keystrokes may have been intercepted.
                try:
                    cur_val_h = await el.input_value()
                except Exception:
                    cur_val_h = None
                _norm_target = re.sub(r"[\s\-()]", "", str(final_value))
                _norm_cur_h = re.sub(r"[\s\-()]", "", cur_val_h or "")
                if human_ok and _norm_cur_h == _norm_target:
                    filled.append(cand_keys[0] if cand_keys else "")
                    # Inter-field pause (TAB 30% / wait 70%) — prevents
                    # the loop from racing through all fields in <1s.
                    await _human_tab_or_pause(page)
                    continue

                # Fallback path — old behaviour preserved exactly so any
                # mask-protected / react-controlled field that broke
                # under human typing still gets filled the legacy way.
                # Primary attempt: fast fill (works for most inputs)
                try:
                    await el.fill(str(final_value))
                except Exception as e:
                    logger.debug(f"fill raised: {e}")

                # Verify the value actually landed. Some inputs have JS masks
                # (e.g. phone `000-000-0000`) that silently reject .fill() or
                # strip the value on the `input` event. If the stored value
                # differs, fall back to the React/Vue-compatible JS native
                # setter — this dispatches the input/change events the mask
                # expects while bypassing the value-sync that fights .fill().
                try:
                    cur_val = await el.input_value()
                except Exception:
                    cur_val = None

                if not cur_val or cur_val.replace("-", "").replace(" ", "").replace("(", "").replace(")", "") != re.sub(r"[\s\-()]", "", str(final_value)):
                    try:
                        await el.evaluate("""(e, v) => {
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            )?.set || Object.getOwnPropertyDescriptor(
                                window.HTMLTextAreaElement.prototype, 'value'
                            )?.set;
                            if (setter) setter.call(e, v); else e.value = v;
                            e.dispatchEvent(new Event('input', {bubbles: true}));
                            e.dispatchEvent(new Event('change', {bubbles: true}));
                            e.dispatchEvent(new Event('blur', {bubbles: true}));
                        }""", str(final_value))
                    except Exception as e:
                        logger.debug(f"JS setter fallback failed on {cand_keys}: {e}")

                    # Last resort — simulate real typing with keyboard events
                    try:
                        cur_val2 = await el.input_value()
                    except Exception:
                        cur_val2 = None
                    if not cur_val2:
                        try:
                            # Move mouse to field before clicking (real users
                            # don't teleport-click). Falls back to plain
                            # click if bounding box unavailable.
                            await _human_mouse_move_to(page, el)
                            await el.click()
                            await page.wait_for_timeout(random.randint(80, 200))
                            # ── 2026-01 BUG FIX (same rationale as the
                            # primary _human_type_field path) ──────────
                            # Verify focus landed on a real text input
                            # before Ctrl+A — otherwise the shortcut
                            # selects the ENTIRE page text.
                            try:
                                _is_focused = await page.evaluate(
                                    """(el) => {
                                        const a = document.activeElement;
                                        if (!a) return false;
                                        if (el && a !== el) return false;
                                        const tag = (a.tagName || '').toUpperCase();
                                        if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
                                        if (a.isContentEditable) return true;
                                        return false;
                                    }""",
                                    el,
                                )
                            except Exception:
                                _is_focused = False
                            if _is_focused:
                                await page.keyboard.press("Control+a")
                                await page.wait_for_timeout(random.randint(30, 90))
                                await page.keyboard.press("Delete")
                                await page.wait_for_timeout(random.randint(40, 110))
                            # Variable delay (was flat delay=30 — bot signature
                            # at ~200 WPM). Each char goes through individually
                            # so we can vary delay per char.
                            for _ch in str(final_value):
                                _d = random.randint(150, 280) if random.random() < 0.18 else random.randint(50, 150)
                                await page.keyboard.type(_ch, delay=_d)
                        except Exception as e:
                            logger.debug(f"keyboard.type fallback failed on {cand_keys}: {e}")
            filled.append(cand_keys[0] if cand_keys else "")
            # Inter-field pause for legacy fallback path too — prevents
            # the loop from racing through fields when the human-typed
            # path failed and we had to use .fill() / JS setter.
            try:
                await _human_tab_or_pause(page)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"fill failed on {cand_keys}: {e}")
            continue

    skipped = [k for k in row.keys() if k not in filled]
    return {"filled": filled, "skipped": skipped, "matched": len(filled)}


async def _click_submit(page: Page) -> bool:
    """Click the most likely submit button and return True on success."""
    candidates = [
        # Tag-based first
        "button[type=submit]",
        "input[type=submit]",
        # FlashRewards / RetailProductsUSA specific (they use div.choice-btn,
        # div.yes_btn, div.continue-btn etc. — NOT real <button> tags)
        "#continue-btn",
        "div.choice-btn:has-text('Continue')",
        "div.choice-btn:has-text('Submit')",
        "div.choice-btn[id*='continue']",
        "div.choice-btn[id*='submit']",
        "div.yes_btn",
        "div.yes-btn",
        "div.continue_btn",
        "div.continue-btn",
        "div.submit_btn",
        "div.submit-btn",
        "div.proceed-btn",
        "div.next-btn",
        "div.cta-btn",
        # Standard CTA buttons
        "button:has-text('Submit')",
        "button:has-text('Send')",
        "button:has-text('Continue')",
        "button:has-text('CONTINUE')",
        "button:has-text('Next')",
        "button:has-text('Finish')",
        "button:has-text('Complete')",
        "button:has-text('Claim')",
        "button:has-text('Unlock')",
        "button:has-text('Get')",
        "a:has-text('Continue')",
        "a:has-text('Submit')",
        # cursor:pointer divs/spans with continue text (broader fallback)
        "[role='button']:has-text('Continue')",
        "[role='button']:has-text('Submit')",
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                return True
        except Exception:
            continue
    # Final fallback: find the most-prominent CTA-style element on the page.
    # Heuristic: cursor:pointer div/span/button that isn't in nav/header/footer
    # AND has CTA-like text (not a policy/help link). Prefer larger buttons.
    try:
        clicked = await page.evaluate(
            """() => {
                const NAV_RE = /^(home|about|contact|menu|login|sign in|register|help|faq|terms|privacy|policy|disclosure|disclaimer|do not sell|notice of|member support|reward status|acceptable use|program requirements|unsubscribe|continue to claim|click here|learn more)$/i;
                const CTA_RE = /\\b(continue|submit|next|finish|complete|proceed|claim|unlock|get started|get my|yes,?|i agree|i accept|text me|sign up|subscribe|update|confirm|verify)\\b/i;
                const all = Array.from(document.querySelectorAll('div, span, a, button, [role="button"], input[type="button"]'));
                const candidates = [];
                for (const el of all) {
                    if (!el.offsetParent) continue;
                    if (el.closest('nav, header, footer, aside')) continue;
                    const t = (el.innerText || '').trim();
                    if (!t || t.length > 80) continue;
                    if (NAV_RE.test(t)) continue;
                    if (!CTA_RE.test(t)) continue;
                    const inner = el.querySelector('a, button, [role="button"]');
                    if (inner) continue;
                    const cur = window.getComputedStyle(el).cursor;
                    if (cur !== 'pointer' && el.tagName !== 'A' && el.tagName !== 'BUTTON') continue;
                    const r = el.getBoundingClientRect();
                    candidates.push({el, area: r.width * r.height, text: t});
                }
                // Largest first
                candidates.sort((a, b) => b.area - a.area);
                if (candidates.length === 0) return false;
                candidates[0].el.click();
                return true;
            }"""
        )
        if clicked:
            return True
    except Exception:
        pass
    try:
        await page.evaluate("const f = document.querySelector('form'); if (f) f.submit();")
        return True
    except Exception:
        return False


# ─────── Job runner ────────────────────────────────────────────────
async def run_form_filler_job(
    job_id: str,
    target_url: str,
    rows: List[Dict[str, Any]],
    count: int,
    duration_minutes: float,
    user_agents: Optional[List[str]] = None,
    proxies: Optional[List[str]] = None,
    skip_captcha: bool = True,
    db=None,
    gemini_api_key: Optional[str] = None,
    ai_provider: str = "gemini",
    target_screenshot_description: str = "Stage F deals/offers grid (multiple offer cards visible) — final reward conversion page.",
    # 2026-02 v2.1.31 — Anti-Detect Phase 1 wiring (additive — defaults
    # preserve previous behaviour exactly). See real_user_traffic.py for
    # the full design contract.
    pacing_per_hour: int = 0,
    identity_label: str = "",
    tls_prewarm: bool = False,
    # 2026-02 Step 5 — Phase 3+4 parity with RUT (Big-1)
    proxy_chain_enabled: bool = False,
    proxy_chain_use_tor: bool = True,
    browser_variant: str = "auto",
    behavioral_bio_enabled: bool = False,
    ip_warmup_enabled: bool = False,
):
    """
    Runs the batch sequentially. Progress is written to JOBS[job_id]
    and (if db provided) to Mongo every few iterations.
    """
    total = min(count, len(rows))
    if total <= 0:
        _finalise(job_id, status="failed", error="No rows to process")
        return

    delay = max(1.0, (duration_minutes * 60.0) / total) if duration_minutes > 0 else 2.0

    # ── 2026-02 v2.1.31 — PacingEngine (log-normal jitter) ───────────
    # When `pacing_per_hour` > 0, replace the flat `delay` with a per-
    # iteration log-normal sample so visits don't look perfectly
    # evenly-spaced. Defeats cohort detection. delay=0 (default) keeps
    # the legacy behaviour exactly.
    _ff_pacer = None
    try:
        if pacing_per_hour and int(pacing_per_hour) > 0:
            from advanced_anti_detect import PacingEngine as _PacingEngine  # type: ignore
            _ff_pacer = _PacingEngine(target_per_hour=int(pacing_per_hour))
            logger.info(
                "FormFiller pacing engine ON: target=%d/hr (log-normal jitter)",
                int(pacing_per_hour),
            )
    except Exception as _pace_err:  # noqa: BLE001
        logger.warning(f"FormFiller PacingEngine init failed ({_pace_err}); flat delay")
        _ff_pacer = None

    # ── 2026-02 v2.1.31 — TLS / JA3 prewarm helper (lazy import) ─────
    _ff_tls_ad = None
    if tls_prewarm:
        try:
            import tls_anti_detect as _ff_tls_ad  # type: ignore
            if not _ff_tls_ad.is_available():
                _ff_tls_ad = None
        except Exception:
            _ff_tls_ad = None

    job_dir = RESULTS_ROOT / job_id
    shots_dir = job_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    report: List[Dict[str, Any]] = []
    JOBS[job_id].update({
        "status": "running",
        "total": total,
        "processed": 0,
        "succeeded": 0,
        "skipped_captcha": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "delay_seconds": round(delay, 2),
    })
    if db is not None:
        await _persist(db, job_id)

    try:
        async with async_playwright() as p:
            for i in range(total):
                row = rows[i % len(rows)]
                ua = random.choice(user_agents) if user_agents else None
                proxy_cfg = _parse_proxy(random.choice(proxies)) if proxies else None

                status = "pending"
                error = ""
                shot_path = ""
                skip_reason = ""
                lead_proof = {}
                browser = None
                # ── 2026-02 Step 5 (Big-1): Proxy chain wrapping ──
                # Mirror RUT's per-row chain start/stop. Single-row visit
                # → single chain lifecycle.
                _ff_chain_handle = None
                _effective_proxy_cfg = proxy_cfg
                if proxy_chain_enabled and proxy_cfg:
                    try:
                        import proxy_chain as _ff_pc
                        _ff_chain = await _ff_pc.start_chain(
                            exit_proxy=proxy_cfg,
                            use_tor=bool(proxy_chain_use_tor),
                        )
                        if _ff_chain and _ff_chain.get("proxy"):
                            _effective_proxy_cfg = _ff_chain["proxy"]
                            _ff_chain_handle = _ff_chain.get("handle")
                            logger.info(
                                f"form_filler proxy chain ON row {i}: "
                                f"{len(_ff_chain.get('hops') or [])} hops"
                            )
                    except Exception as _ff_pc_err:  # noqa: BLE001
                        logger.debug(f"ff proxy_chain failed: {_ff_pc_err}")

                try:
                    # ── Stealth-armed launch (centralized engine) ────────
                    # Provides identical 35+ anti-detect patches as RUT:
                    # canvas/audio/WebGL/webdriver/WebRTC/Jornaya/etc.
                    _stealth_launch = _get_stealth_launcher()
                    if _stealth_launch:
                        try:
                            browser, context, page = await _stealth_launch(
                                p, ua=ua, proxy=_effective_proxy_cfg, headless=True,
                            )
                        except Exception as _ste_err:
                            import logging
                            logging.getLogger(__name__).warning(
                                f"stealth launch failed: {_ste_err} — using legacy"
                            )
                            browser = await p.chromium.launch(
                                headless=True,
                                proxy=_effective_proxy_cfg,
                                args=["--no-sandbox", "--disable-dev-shm-usage"],
                            )
                            context = await browser.new_context(user_agent=ua) if ua else await browser.new_context()
                            page = await context.new_page()
                    else:
                        browser = await p.chromium.launch(
                            headless=True,
                            proxy=_effective_proxy_cfg,
                            args=["--no-sandbox", "--disable-dev-shm-usage"],
                        )
                        context = await browser.new_context(user_agent=ua) if ua else await browser.new_context()
                        page = await context.new_page()

                    # ── 2026-02 Step 5 (Big-1): IP warm-up for FF ─
                    if ip_warmup_enabled:
                        try:
                            from advanced_anti_detect import warm_up_ip as _ff_warm
                            _wpg = await context.new_page()
                            try:
                                await _ff_warm(_wpg, visits=2, dwell_sec=3.0)
                            finally:
                                try: await _wpg.close()
                                except Exception: pass
                        except Exception as _wu_err:  # noqa: BLE001
                            logger.debug(f"ff ip_warmup failed: {_wu_err}")
                    # ── 2026-02 v2.1.31 — TLS / JA3 prewarm ──────────
                    # Pre-fetch target with real Chrome JA3 via curl_cffi
                    # and seed the resulting cookies onto the Playwright
                    # context BEFORE the first navigation. Bypass
                    # Cloudflare BM / DataDome / Akamai on cold visits.
                    if _ff_tls_ad is not None and tls_prewarm:
                        try:
                            _pw_res = await _ff_tls_ad.prewarm_target(
                                target_url,
                                proxy=proxy_cfg,
                                ua=ua or "",
                                timeout=20.0,
                            )
                            if _pw_res and _pw_res.get("ok") and _pw_res.get("cookies"):
                                try:
                                    await context.add_cookies(_pw_res["cookies"])
                                    logger.info(
                                        "form_filler TLS prewarm OK row %d: "
                                        "%d cookies seeded (status=%s)",
                                        i, len(_pw_res["cookies"]),
                                        _pw_res.get("status"),
                                    )
                                except Exception as _ck_err:  # noqa: BLE001
                                    logger.debug(f"prewarm add_cookies failed: {_ck_err}")
                        except Exception as _pw_err:  # noqa: BLE001
                            logger.debug(f"form_filler tls prewarm exception: {_pw_err}")

                    await page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(800)

                    if skip_captcha and await _page_has_captcha(page):
                        status = "skipped_captcha"
                        skip_reason = "Captcha detected — traffic skipped"
                    else:
                        # If the landing page has no form yet, auto-click a CTA
                        # (e.g. "UNLOCK NOW", "Claim", "Start", "Continue") until
                        # a real form becomes visible.
                        await _ensure_form_visible(page, max_tries=2)

                        if skip_captcha and await _page_has_captcha(page):
                            status = "skipped_captcha"
                            skip_reason = "Captcha detected after CTA click"
                        else:
                            # Multi-step survey + form loop. New behaviour
                            # (vs. legacy form-only): on every iteration we
                            # FIRST run the FlashRewards-style survey clicker
                            # (Yes/No, multi-choice, NO THANKS, agree-continue
                            # etc.) THEN attempt _fill_form. When neither
                            # progresses AND a Gemini key is configured, we
                            # ask the AI to choose the next action.
                            total_filled = 0
                            max_steps = 18  # raised — can take 8-12 stages on FlashRewards
                            survey_clicks = 0
                            ai_actions: List[str] = []  # short log of AI decisions
                            ai_used = 0
                            ai_max = 25  # cap AI calls per row to control cost
                            consecutive_no_progress = 0

                            for step in range(max_steps):
                                await page.wait_for_timeout(800 + random.randint(0, 700))
                                await _dismiss_popups(page)

                                # ── STEP A: survey-click (handles Yes/No,
                                #    NO THANKS, choice-btn, multi-select etc.)
                                pre_url = page.url
                                step_survey = 0
                                if _rut_survey_click_v2 is not None:
                                    try:
                                        sres = await _rut_survey_click_v2(
                                            page, max_iterations=8, picker=None,
                                        )
                                        if isinstance(sres, dict):
                                            step_survey = int(sres.get("clicks") or 0)
                                            survey_clicks += step_survey
                                    except Exception as e:  # noqa: BLE001
                                        logger.debug(f"survey click err: {e}")

                                # ── STEP B: form fill ──
                                fill_info = await _fill_form(page, row)
                                step_filled = len(fill_info.get("filled") or [])
                                total_filled += step_filled

                                # ── STEP C: submit if anything was filled OR
                                #    survey advanced us to a form (no fields
                                #    matched but URL didn't change → click
                                #    submit anyway to drive flow forward)
                                progress_made = step_survey > 0 or step_filled > 0
                                if progress_made or step == 0:
                                    if step_filled > 0:
                                        await _tick_consent_checkboxes(page)
                                        try:
                                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                                        except Exception:
                                            pass
                                        start_url = page.url
                                        await _click_submit(page)
                                        for _attempt in range(2):
                                            try:
                                                await page.wait_for_load_state(
                                                    "networkidle", timeout=8000
                                                )
                                            except Exception:
                                                pass
                                            await page.wait_for_timeout(1500)
                                            if page.url != start_url:
                                                break
                                            handled = await _dismiss_review_modal(page)
                                            if handled:
                                                await _tick_consent_checkboxes(page)
                                                await page.wait_for_timeout(400)
                                                await _click_submit(page)
                                                continue
                                            break

                                # ── STEP D: detect success / progression ──
                                cur_url = page.url
                                try:
                                    cur_html = (await page.content()).lower()
                                except Exception:
                                    cur_html = ""

                                # Stage F deals page detected?
                                deals_markers = (
                                    "complete 1 deal on this level",
                                    "complete deals to claim",
                                    "best match for you",
                                    "next step:\\s*complete",
                                )
                                if any(re.search(m, cur_html) for m in deals_markers):
                                    status = "ok"
                                    logger.info(f"row {i}: reached deals page — success")
                                    break

                                # Generic success page?
                                success_tokens = (
                                    "thank you", "thanks!", "congratulations",
                                    "successfully", "we received",
                                )
                                if any(t in cur_html for t in success_tokens):
                                    status = "ok"
                                    break

                                # Progress check
                                if cur_url != pre_url or step_survey > 0 or step_filled > 0:
                                    consecutive_no_progress = 0
                                else:
                                    consecutive_no_progress += 1

                                # ── STEP E: AI Vision FALLBACK ──
                                # When 2 consecutive iterations make no progress
                                # AND user has provided a Gemini API key, ask
                                # Gemini what to do next. Cheap (only fires
                                # when stuck) and helps for unknown campaigns.
                                if (
                                    consecutive_no_progress >= 2
                                    and gemini_api_key
                                    and _ai_ask is not None
                                    and ai_used < ai_max
                                ):
                                    try:
                                        b64 = await _ai_screenshot(page) if _ai_screenshot else None
                                        if b64:
                                            action = await _ai_ask(
                                                provider=ai_provider,
                                                api_key=gemini_api_key,
                                                page_screenshot_b64=b64,
                                                row=row,
                                                target_description=target_screenshot_description,
                                                recent_actions=ai_actions,
                                            )
                                            ai_used += 1
                                            if action:
                                                a_kind = (action.get("action") or "").lower()
                                                ai_actions.append(
                                                    f"{a_kind} '{action.get('target_text') or action.get('field_label') or ''}' "
                                                    f"({action.get('stage') or '?'})"
                                                )
                                                logger.info(
                                                    f"row {i} AI #{ai_used}: {ai_actions[-1]}"
                                                )
                                                if a_kind == "done":
                                                    status = "ok"
                                                    break
                                                if a_kind == "fail":
                                                    status = "ai_fail"
                                                    error = action.get("reason") or "AI gave up"
                                                    break
                                                if await _ai_execute(page, action):
                                                    consecutive_no_progress = 0
                                                    await page.wait_for_timeout(
                                                        1500 + random.randint(0, 1500)
                                                    )
                                    except Exception as e:
                                        logger.debug(f"AI fallback err: {e}")

                                # If neither rule-based nor AI made progress
                                # for 4 consecutive iterations, stop.
                                if consecutive_no_progress >= 4:
                                    if not status:
                                        status = "submitted_but_no_redirect"
                                    break

                            if status not in ("no_fields_matched", "skipped_captcha", "ai_fail"):
                                if not status or status == "pending":
                                    status = "ok"

                            # Capture lead-tracking proof (TrustedForm cert,
                            # LeadiD, universal_leadid) that many US lead-gen
                            # platforms inject into the final page after a
                            # successful submission.
                            try:
                                lead_proof = await page.evaluate("""() => {
                                    const grab = sel => {
                                        const el = document.querySelector(sel);
                                        return el ? (el.value || el.getAttribute('value') || '') : '';
                                    };
                                    return {
                                        trusted_form: grab('[name="xxTrustedFormCertUrl"]')
                                                   || grab('[name="xxTrustedFormToken"]'),
                                        lead_id: grab('#leadid_token')
                                              || grab('[name="universal_leadid"]')
                                              || grab('[name="LeadiD"]'),
                                    };
                                }""")
                            except Exception:
                                lead_proof = {}
                            try:
                                lead_proof["final_url"] = page.url
                            except Exception:
                                pass

                            # Wait an extra moment so dynamic offers / thank-you
                            # content renders before the screenshot
                            try:
                                await page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(1500)

                            # Screenshot the final page regardless of outcome
                            shot_path = str(shots_dir / f"row_{i+1:05d}.png")
                            try:
                                await page.screenshot(path=shot_path, full_page=True)
                            except Exception as e:
                                logger.warning(f"screenshot failed: {e}")
                    await context.close()
                except Exception as e:
                    status = "failed"
                    error = str(e)[:250]
                finally:
                    if browser is not None:
                        try: await browser.close()
                        except Exception: pass
                    # 2026-02 Step 5 (Big-1): stop the per-row proxy chain
                    if _ff_chain_handle is not None:
                        try: await _ff_chain_handle.stop()
                        except Exception: pass

                # Update counters
                j = JOBS[job_id]
                j["processed"] = i + 1
                if status == "ok":
                    j["succeeded"] += 1
                elif status == "skipped_captcha":
                    j["skipped_captcha"] += 1
                else:
                    j["failed"] += 1

                report.append({
                    "row_index": i + 1,
                    "status": status,
                    "error": error or skip_reason,
                    "screenshot": os.path.basename(shot_path) if shot_path else "",
                    "user_agent": ua or "",
                    "proxy": (proxy_cfg or {}).get("server", "") if proxy_cfg else "",
                    "trusted_form": (lead_proof or {}).get("trusted_form", ""),
                    "lead_id": (lead_proof or {}).get("lead_id", ""),
                    "final_url": (lead_proof or {}).get("final_url", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                if db is not None and (i + 1) % 3 == 0:
                    await _persist(db, job_id)

                # Pacing — log-normal jitter if PacingEngine is active,
                # otherwise the flat `delay` derived from duration_minutes.
                if i < total - 1:
                    if _ff_pacer is not None:
                        try:
                            _d = _ff_pacer.next_delay()
                            await asyncio.sleep(float(_d))
                        except Exception:
                            await asyncio.sleep(delay)
                    else:
                        await asyncio.sleep(delay)

        # Write report.csv
        with open(job_dir / "report.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["row_index", "status", "error", "screenshot", "user_agent", "proxy", "trusted_form", "lead_id", "final_url", "timestamp"],
            )
            writer.writeheader()
            writer.writerows(report)

        # Build ZIP for download
        zip_path = job_dir / "results.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in shots_dir.glob("*.png"):
                zf.write(p, arcname=f"screenshots/{p.name}")
            zf.write(job_dir / "report.csv", arcname="report.csv")

        JOBS[job_id].update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "report": report,
            "zip_path": str(zip_path),
        })
    except Exception as e:
        logger.exception(f"Job {job_id} crashed")
        _finalise(job_id, status="failed", error=str(e)[:300])
    finally:
        if db is not None:
            await _persist(db, job_id)


def _finalise(job_id: str, status: str, error: str = ""):
    j = JOBS.setdefault(job_id, {})
    j["status"] = status
    if error:
        j["error"] = error
    j["finished_at"] = datetime.now(timezone.utc).isoformat()


def _parse_proxy(proxy_str: str) -> Optional[Dict[str, str]]:
    """Parse `ip:port` or `ip:port:user:pass` or `http://user:pass@ip:port` into playwright proxy dict."""
    proxy_str = (proxy_str or "").strip()
    if not proxy_str:
        return None
    if proxy_str.startswith("http"):
        return {"server": proxy_str}
    parts = proxy_str.split(":")
    if len(parts) == 2:
        return {"server": f"http://{parts[0]}:{parts[1]}"}
    if len(parts) == 4:
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": parts[2],
            "password": parts[3],
        }
    return None


async def _persist(db, job_id: str):
    j = JOBS.get(job_id, {})
    try:
        await db.form_filler_jobs.update_one(
            {"job_id": job_id},
            {"$set": {**j, "job_id": job_id}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"Could not persist form-filler job {job_id}: {e}")


def create_job_record(
    job_id: str, user_id: str, target_url: str, total_rows: int,
    count: int, duration_minutes: float, data_source: str,
) -> Dict[str, Any]:
    JOBS[job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "target_url": target_url,
        "total_rows_loaded": total_rows,
        "count": count,
        "duration_minutes": duration_minutes,
        "data_source": data_source,
        "status": "queued",
        "total": min(count, total_rows),
        "processed": 0,
        "succeeded": 0,
        "skipped_captcha": 0,
        "failed": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return JOBS[job_id]


def cleanup_old_job(job_id: str):
    """Delete screenshots + ZIP for a job (called on /delete)."""
    d = RESULTS_ROOT / job_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    JOBS.pop(job_id, None)
