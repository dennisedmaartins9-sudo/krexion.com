"""
Automation Extensions (2026-01) — additive helpers for the Visual Recorder
+ Real User Traffic replay engine.

This module is PURE ADDITIVE. It does NOT modify any existing behavior;
the engine calls these helpers OPT-IN per step (or per call). When a
recorded JSON does not use the new step types / hints, this module is
inert — existing automations behave exactly as before.

Contents:
  • Iframe-aware selector resolution
  • Shadow-DOM piercing helper (Playwright already supports `>>` syntax,
    but we also expose a runtime probe so the engine can auto-route
    a selector into a shadow root when the user has not used `>>`)
  • Cookie/GDPR banner auto-dismissal (best-effort, runs once)
  • Extended bot/captcha detection (Cloudflare Turnstile, hCaptcha,
    DataDome, PerimeterX, Imperva, Akamai BMP, etc.)
  • Variable extraction (page → row dict)
  • Placeholder formatter support (`{{first_name|upper}}`, etc.)
  • Per-step retry runner
  • New tab / popup follower
  • Plain-English error message mapper
  • Pre-flight lint for a recorded steps array

EVERY helper is safe to call inside `_execute_automation_steps` without
breaking the main loop. Failures are swallowed and logged.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("automation_extensions")


# ─────────────────────────────────────────────────────────────────────────
# 1. Cookie / GDPR banner auto-dismissal
# ─────────────────────────────────────────────────────────────────────────
# Common patterns observed across OneTrust, Cookiebot, Quantcast Choice,
# Didomi, Osano, TrustArc, Sourcepoint, Iubenda, CookieYes, GDPRBanner,
# Termly, and ~50 ad-hoc implementations on lead-gen pages.
#
# We run a single JS snippet that tries to find an "Accept" / "Got it" /
# "Agree" / "OK" / "Close" button across known wrapper containers AND
# generic role=button heuristics. Returns True if a banner was dismissed.

_COOKIE_DISMISS_JS = r"""
(() => {
  const acceptKw = [
    'accept all','accept cookies','accept','agree','i agree','allow all',
    'allow cookies','allow','got it','okay','ok','close','dismiss',
    'continue','consent','i understand','i accept','yes, i agree',
    'akzeptieren','tout accepter','aceptar','tout accepter','akkoord'
  ];
  function lower(s){return ((s||'')+'').toLowerCase().replace(/\s+/g,' ').trim();}
  function visible(el){try{var s=getComputedStyle(el);var r=el.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&parseFloat(s.opacity||'1')>0.05&&r.width>2&&r.height>2;}catch(e){return false;}}

  // Pass 1: known vendor selectors (highest precision)
  const vendorSelectors = [
    // OneTrust
    '#onetrust-accept-btn-handler',
    '#accept-recommended-btn-handler',
    'button[aria-label="Accept All Cookies"]',
    // Cookiebot
    '#CybotCookiebotDialogBodyButtonAccept',
    '#CybotCookiebotDialogBodyLevelButtonAccept',
    '#CybotCookiebotDialogBodyLevelButtonAcceptAll',
    // Quantcast Choice
    'button.qc-cmp2-summary-buttons[mode="primary"]',
    '.qc-cmp2-summary-buttons button:nth-child(2)',
    // Didomi
    '#didomi-notice-agree-button',
    'button[aria-label="Agree and close"]',
    // Osano
    '.osano-cm-accept-all',
    '.osano-cm-button--type_accept',
    // TrustArc
    '#truste-consent-button',
    // Sourcepoint
    'button[title="Accept"]',
    '.sp_choice_type_11',
    // Iubenda
    '.iubenda-cs-accept-btn',
    // CookieYes
    '.cky-btn-accept',
    // Termly
    '#termly-code-snippet-support .t-acceptAll',
    // Generic IDs
    '#accept-cookies', '#acceptCookies', '#cookie-accept',
    '#cookieAccept', '#cookie-banner-accept',
    '[data-testid="cookie-accept"]', '[data-test="accept-cookies"]',
  ];
  for (const sel of vendorSelectors) {
    try {
      const el = document.querySelector(sel);
      if (el && visible(el)) { el.click(); return {dismissed: true, via: 'vendor:'+sel}; }
    } catch(e){}
  }

  // Pass 2: generic — any visible button/anchor inside a banner-like container
  //   - parent has 'cookie'/'consent'/'gdpr'/'privacy' in id/class
  //   - button text matches accept keywords
  const containers = Array.from(document.querySelectorAll(
    '[id*="cookie" i], [id*="consent" i], [id*="gdpr" i], [id*="privacy" i], ' +
    '[class*="cookie" i], [class*="consent" i], [class*="gdpr" i], ' +
    '[role="dialog"], [role="alertdialog"]'
  ));
  for (const cont of containers) {
    if (!visible(cont)) continue;
    const btns = Array.from(cont.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
    for (const b of btns) {
      if (!visible(b)) continue;
      const t = lower(b.innerText || b.textContent || b.value);
      if (!t) continue;
      for (const kw of acceptKw) {
        if (t === kw || t.includes(kw)) {
          try { b.click(); return {dismissed: true, via: 'generic-container'}; } catch(e){}
        }
      }
    }
  }

  return {dismissed: false};
})()
"""


async def auto_dismiss_cookie_banners(page: Any, log_label: str = "") -> bool:
    """Best-effort cookie/GDPR banner dismissal. Returns True if a banner
    was clicked, False otherwise. Always safe — failures swallowed."""
    try:
        result = await page.evaluate(_COOKIE_DISMISS_JS)
        if result and result.get("dismissed"):
            logger.info(f"[cookie-dismiss{(' ' + log_label) if log_label else ''}] "
                        f"banner dismissed via {result.get('via', '?')}")
            return True
    except Exception as e:
        logger.debug(f"[cookie-dismiss] eval failed: {e}")
    return False


# ─────────────────────────────────────────────────────────────────────────
# 2. Extended bot / captcha / challenge detection
# ─────────────────────────────────────────────────────────────────────────
# Returns a tuple (blocked: bool, kind: str). When blocked is True the
# caller should abandon the visit cleanly with the kind string surfaced
# to the operator.

_BOT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("cloudflare_turnstile", re.compile(r'(challenges\.cloudflare\.com|turnstile|cf-turnstile-response|cf-chl-bypass)', re.I)),
    ("cloudflare_challenge",  re.compile(r'(__cf_chl_jschl_tk|cf-browser-verification|Checking your browser before accessing|cf-chl-widget|Just a moment)', re.I)),
    ("hcaptcha",              re.compile(r'(hcaptcha\.com|h-captcha|data-hcaptcha-sitekey)', re.I)),
    ("recaptcha_v2",          re.compile(r'(google\.com/recaptcha/api2|g-recaptcha|data-sitekey)', re.I)),
    ("recaptcha_v3",          re.compile(r'(recaptcha/api\.js\?render=)', re.I)),
    ("datadome",              re.compile(r'(datadome|geo\.captcha-delivery\.com|dd_cookie_test)', re.I)),
    ("perimeterx",            re.compile(r'(perimeterx\.net|_pxAction|_pxhd|px-captcha)', re.I)),
    ("imperva",               re.compile(r'(impervadns|incapsula|_Incapsula_Resource|visid_incap_)', re.I)),
    ("akamai_bmp",            re.compile(r'(_abck=|bm_sz=|akam\.net.*bot)', re.I)),
    ("arkose_labs",           re.compile(r'(funcaptcha|arkoselabs)', re.I)),
    ("geetest",               re.compile(r'(geetest\.com|gt_captcha)', re.I)),
]


async def detect_bot_block(page: Any) -> Tuple[bool, str]:
    """Inspect the current page HTML for known bot-protection markers.
    Returns (True, kind) on hit, (False, "") otherwise. Defensive against
    detached pages / cross-origin issues — returns (False, "") on error."""
    try:
        html = await page.content()
    except Exception:
        return False, ""
    for kind, pat in _BOT_PATTERNS:
        try:
            if pat.search(html):
                return True, kind
        except Exception:
            continue
    return False, ""


# ─────────────────────────────────────────────────────────────────────────
# 3. Iframe-aware selector resolution
# ─────────────────────────────────────────────────────────────────────────
# Strategy:
#   • If selector starts with "iframe<...> >>> <selector>" (Playwright
#     convention), Playwright already handles it natively.
#   • If selector lookup fails on main frame, iterate ALL iframes
#     (top-down) and try the same selector inside each. Returns the
#     frame that matched (or None).
#
# This makes the engine "iframe-transparent" — existing recordings that
# happened to capture a selector inside an iframe (which is rare during
# recording because the recorder shoots into the top-level page) STILL
# work at replay time when the form is rendered inside an iframe.


async def find_frame_with_selector(page: Any, selector: str,
                                   timeout_ms: int = 3000) -> Optional[Any]:
    """Search page's iframes (recursively) for the first one that contains
    `selector`. Returns the frame object or None. Times out after
    `timeout_ms`.

    NOTE: Does NOT search the main frame — caller already tried that.
    """
    if not selector:
        return None
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    seen = set()
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            fid = id(frame)
            if fid in seen:
                continue
            seen.add(fid)
            if time.monotonic() > deadline:
                break
            try:
                el = await frame.query_selector(selector)
                if el is not None:
                    return frame
            except Exception:
                continue
    except Exception:
        return None
    return None


# ─────────────────────────────────────────────────────────────────────────
# 4. Shadow-DOM probe
# ─────────────────────────────────────────────────────────────────────────
# Playwright supports `>>` for piercing shadow roots in CSS selectors
# (e.g. `my-component >> input[name="email"]`). We also expose a
# runtime probe that walks open shadow roots looking for a selector,
# so users don't have to know about `>>` syntax.

_SHADOW_PROBE_JS = r"""
(sel) => {
  function walk(root, sel) {
    try {
      const direct = root.querySelector(sel);
      if (direct) return true;
    } catch(e){}
    const all = root.querySelectorAll('*');
    for (const el of all) {
      if (el.shadowRoot) {
        if (walk(el.shadowRoot, sel)) return true;
      }
    }
    return false;
  }
  return walk(document, sel);
}
"""


async def selector_exists_in_shadow(page_or_frame: Any, selector: str) -> bool:
    """Return True if `selector` matches an element nested in any open
    shadow root. The caller should switch to using Playwright's `>>`
    shadow-piercing syntax for the actual action (which Playwright
    handles transparently)."""
    try:
        return bool(await page_or_frame.evaluate(_SHADOW_PROBE_JS, selector))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────
# 5. Variable extraction (page → row dict)
# ─────────────────────────────────────────────────────────────────────────
# `extract` action stores text from a selector into the row dict so
# subsequent steps can substitute `{{variable_name}}` in their values.
# Useful for capturing order IDs / confirmation numbers / tokens.

async def extract_to_row(page_or_frame: Any, selector: str,
                         store_key: str, row: Dict[str, Any],
                         attribute: Optional[str] = None,
                         regex: Optional[str] = None,
                         timeout_ms: int = 10000) -> Tuple[bool, str]:
    """Read text (or an attribute / regex group) from `selector` into
    row[store_key]. Returns (ok, value_or_error)."""
    if not selector or not store_key:
        return False, "selector and store key required"
    try:
        await page_or_frame.wait_for_selector(selector, timeout=timeout_ms, state="attached")
    except Exception as e:
        return False, f"selector not found: {e}"
    try:
        if attribute:
            val = await page_or_frame.get_attribute(selector, attribute)
        else:
            val = await page_or_frame.text_content(selector)
        val = (val or "").strip()
        if regex:
            try:
                m = re.search(regex, val)
                if m:
                    val = m.group(1) if m.groups() else m.group(0)
            except Exception:
                pass
        row[store_key] = val
        return True, val
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────
# 6. Wait-for-text / Wait-for-url
# ─────────────────────────────────────────────────────────────────────────
async def wait_for_text(page: Any, text: str, timeout_ms: int = 15000,
                        case_insensitive: bool = True) -> bool:
    """Wait until visible body text contains `text`. Returns True/False."""
    if not text:
        return True
    try:
        if case_insensitive:
            js = "(t) => (document.body && document.body.innerText && document.body.innerText.toLowerCase().includes(t.toLowerCase()))"
        else:
            js = "(t) => (document.body && document.body.innerText && document.body.innerText.includes(t))"
        await page.wait_for_function(js, arg=text, timeout=timeout_ms)
        return True
    except Exception as e:
        logger.debug(f"[wait_for_text] '{text[:40]}' not found in {timeout_ms}ms: {e}")
        return False


async def wait_for_url(page: Any, *, contains: Optional[str] = None,
                       equals: Optional[str] = None,
                       pattern: Optional[str] = None,
                       timeout_ms: int = 15000) -> bool:
    """Wait until page.url matches the predicate. Returns True/False."""
    if not (contains or equals or pattern):
        return True
    try:
        if equals:
            await page.wait_for_url(equals, timeout=timeout_ms)
        elif pattern:
            await page.wait_for_url(re.compile(pattern), timeout=timeout_ms)
        else:  # contains
            await page.wait_for_url(
                lambda u: contains in (u or ""),  # type: ignore[operator]
                timeout=timeout_ms,
            )
        return True
    except Exception as e:
        logger.debug(f"[wait_for_url] predicate not met in {timeout_ms}ms: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────
# 7. Placeholder formatter pipeline
# ─────────────────────────────────────────────────────────────────────────
# Lets users write `{{first_name|upper}}` or `{{phone|digits}}` in their
# automation values. The base `{{first_name}}` is resolved first (by the
# existing _substitute in real_user_traffic.py); this helper applies the
# formatter pipeline AFTER the substitution.
#
# Supported formatters:
#   upper, lower, title, trim, digits, alpha, alnum, reverse
#   first:N    — first N chars
#   last:N     — last N chars
#   slice:A:B  — string slice [A:B]
#   default:X  — when the resolved value is empty, use X

_FMT_PIPE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def apply_formatters(value: str, pipeline: str) -> str:
    """Apply `|fmt1|fmt2:arg|...` formatters to value. Robust to bad input."""
    if not pipeline:
        return value
    out = value
    for part in pipeline.split("|"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, arg = part.split(":", 1)
            name = name.strip().lower()
            arg = arg.strip()
        else:
            name, arg = part.strip().lower(), ""
        try:
            if name == "upper":
                out = out.upper()
            elif name == "lower":
                out = out.lower()
            elif name == "title":
                out = out.title()
            elif name == "trim":
                out = out.strip()
            elif name == "digits":
                out = re.sub(r"\D+", "", out)
            elif name == "alpha":
                out = re.sub(r"[^A-Za-z]+", "", out)
            elif name == "alnum":
                out = re.sub(r"[^A-Za-z0-9]+", "", out)
            elif name == "reverse":
                out = out[::-1]
            elif name == "first" and arg:
                out = out[: int(arg)]
            elif name == "last" and arg:
                out = out[-int(arg):] if int(arg) > 0 else out
            elif name == "slice" and arg:
                ab = arg.split(":")
                a = int(ab[0]) if ab[0] else 0
                b = int(ab[1]) if len(ab) > 1 and ab[1] else None
                out = out[a:b] if b is not None else out[a:]
            elif name == "default":
                if not out:
                    out = arg
        except Exception:
            # Bad formatter args — silently skip (defensive)
            continue
    return out


def split_placeholder_pipeline(inside: str) -> Tuple[str, str]:
    """Given the inner of `{{...}}`, split into (key, formatter_pipeline)."""
    if "|" not in inside:
        return inside.strip(), ""
    head, _, rest = inside.partition("|")
    return head.strip(), rest.strip()


# ─────────────────────────────────────────────────────────────────────────
# 8. Plain-English error message mapper
# ─────────────────────────────────────────────────────────────────────────
# Maps verbose Playwright tracebacks to short, actionable hints. Used by
# Visual Recorder Live Test to surface a friendly explanation alongside
# the raw error.

_FRIENDLY_ERROR_MAP: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"Timeout .* exceeded", re.I),
     "Element ne wait window mein appear nahi kiya. Try: (1) timeout bara karein, (2) check karein agar iframe ke andar hai, (3) selector verify karein."),
    (re.compile(r"strict mode violation.* resolved to \d+ elements", re.I),
     "Selector ek se zyada elements pe match kar raha hai. Aur specific selector use karein (e.g. add :nth-of-type ya parent context)."),
    (re.compile(r"net::ERR_TUNNEL_CONNECTION_FAILED", re.I),
     "Proxy connection fail hua. Proxy credentials ya endpoint check karein."),
    (re.compile(r"net::ERR_PROXY_CONNECTION_FAILED", re.I),
     "Proxy server unreachable. Proxy down ho sakta hai ya credentials galat hain."),
    (re.compile(r"net::ERR_NAME_NOT_RESOLVED", re.I),
     "Domain resolve nahi hua. URL spelling check karein."),
    (re.compile(r"Execution context (was|is) destroyed", re.I),
     "Page navigate ho gayi step ke beech mein. Step ke baad wait_for_navigation step add karein."),
    (re.compile(r"Target page, context or browser has been closed", re.I),
     "Browser/tab close ho gaya. Visit retry kar dein."),
    (re.compile(r"Cannot find context with specified id", re.I),
     "Page reload ya cross-origin redirect hua. wait_for_load_state step add karein."),
    (re.compile(r"select_option failed.*", re.I),
     "Dropdown ke options se value match nahi hui. match_by (label/value) toggle karke try karein."),
    (re.compile(r"Element is not attached to the DOM", re.I),
     "Element DOM se hat gaya. Step se pehle wait_for_selector add karein."),
    (re.compile(r"Element is outside of the viewport", re.I),
     "Element screen se bahar hai. Step se pehle scroll add karein."),
    (re.compile(r"Element is not visible", re.I),
     "Element hidden hai (CSS). Recorder ki Dropdown / Check binding use karein — hidden inputs ko JS-set karte hain."),
]


def friendly_error(raw: str) -> str:
    """Return a short Roman-Urdu/English hint matching the error pattern,
    or "" if no pattern matches."""
    if not raw:
        return ""
    for pat, msg in _FRIENDLY_ERROR_MAP:
        try:
            if pat.search(raw):
                return msg
        except Exception:
            continue
    return ""


# ─────────────────────────────────────────────────────────────────────────
# 9. Pre-flight lint
# ─────────────────────────────────────────────────────────────────────────
# Catches obvious issues BEFORE the user runs a live test / commits the
# automation to a RUT job. Returns a list of structured issues:
#   [{level: "error"|"warn"|"info", at_step: int, code: str, message: str}, ...]

_KNOWN_ACTIONS = {
    "goto", "click", "fill", "type", "select", "check", "uncheck",
    "press", "wait", "wait_for_selector", "wait_for_navigation",
    "wait_for_load", "wait_for_networkidle", "wait_for_text",
    "wait_for_url", "scroll", "evaluate", "screenshot",
    "auto_continue", "auto_continue_survey", "extract",
    "dismiss_popups", "hover", "right_click", "drag", "drag_drop",
    "switch_tab", "close_tab", "close", "close_browser", "browser_close",
    "branch", "iframe_click", "iframe_fill", "shadow_click",
    "accept_dialog", "dismiss_dialog", "set_input_files", "file_upload",
    "pause_for_human", "captcha_pause", "human_pause",
    "otp_wait", "wait_for_otp", "conditional_skip", "set_zoom",
    "save_storage", "restore_storage", "go_back", "go_forward",
}
# Actions that only skip gracefully when optional=True (headless RUT cannot run them fully).
_HEADLESS_ONLY_ACTIONS = frozenset({
    "pause_for_human", "captcha_pause", "human_pause", "otp_wait", "wait_for_otp",
})
_ACTIONS_REQUIRING_SELECTOR = {
    "click", "fill", "type", "select", "check", "uncheck", "hover",
    "iframe_click", "iframe_fill", "set_input_files", "file_upload",
}


def lint_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the pre-flight lint pass. Returns a list of structured issues."""
    issues: List[Dict[str, Any]] = []
    if not isinstance(steps, list):
        return [{"level": "error", "at_step": -1, "code": "not_a_list",
                 "message": "Steps array missing ya invalid format."}]
    if not steps:
        return [{"level": "warn", "at_step": -1, "code": "empty",
                 "message": "Koi step record nahi kiya."}]

    seen_screenshot = False
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            issues.append({"level": "error", "at_step": i, "code": "not_a_dict",
                           "message": f"Step #{i+1} dict format mein nahi."})
            continue
        action = (s.get("action") or "").strip().lower()
        if not action:
            issues.append({"level": "error", "at_step": i, "code": "no_action",
                           "message": f"Step #{i+1} ka action missing hai."})
            continue
        if action not in _KNOWN_ACTIONS:
            issues.append({"level": "error", "at_step": i, "code": "unknown_action",
                           "message": f"Step #{i+1} ka action '{action}' RUT executor mein nahi — replay fail ya skip hoga."})
        elif action in _HEADLESS_ONLY_ACTIONS and not s.get("optional"):
            issues.append({"level": "error", "at_step": i, "code": "headless_only",
                           "message": f"Step #{i+1} ({action}) headless RUT mein auto-run nahi hota — Edit Step se optional=true mark karein ya step hata dein."})
        if action in _ACTIONS_REQUIRING_SELECTOR and not s.get("selector"):
            issues.append({"level": "error", "at_step": i, "code": "missing_selector",
                           "message": f"Step #{i+1} ({action}) ke liye selector zaroori hai."})
        if action in ("fill", "type", "select", "extract") and \
                (s.get("value") is None and not s.get("store_key")):
            # extract uses store_key instead of value
            if action == "extract" and not s.get("store_key"):
                issues.append({"level": "error", "at_step": i, "code": "extract_no_store",
                               "message": f"Step #{i+1} (extract) ke liye store_key (variable name) zaroori hai."})
            elif action != "extract" and s.get("value") is None:
                issues.append({"level": "warn", "at_step": i, "code": "no_value",
                               "message": f"Step #{i+1} ({action}) mein value blank hai."})
        if action == "wait":
            ms = int(s.get("ms") or 0)
            if ms <= 0:
                issues.append({"level": "warn", "at_step": i, "code": "wait_zero",
                               "message": f"Step #{i+1} wait ms=0 — koi assar nahi hoga."})
            elif ms > 30000:
                issues.append({"level": "warn", "at_step": i, "code": "wait_too_long",
                               "message": f"Step #{i+1} wait {ms}ms (>30s) — har visit slow hogi. Use wait_for_selector/wait_for_text instead."})
        if action == "wait_for_text" and not s.get("text"):
            issues.append({"level": "error", "at_step": i, "code": "no_text",
                           "message": f"Step #{i+1} (wait_for_text) ke liye text field zaroori hai."})
        if action == "wait_for_url" and not (s.get("contains") or s.get("equals") or s.get("pattern")):
            issues.append({"level": "error", "at_step": i, "code": "no_url_predicate",
                           "message": f"Step #{i+1} (wait_for_url) mein contains/equals/pattern me se ek zaroori hai."})
        if action == "screenshot":
            seen_screenshot = True

    if len(steps) >= 12 and not seen_screenshot:
        issues.append({"level": "info", "at_step": -1, "code": "no_screenshot",
                       "message": "Long automation hai par koi screenshot step nahi — failed visit debug karna mushkil hoga."})

    submit_like = sum(1 for s in steps if isinstance(s, dict) and
                      (s.get("action") == "click" and bool(s.get("wait_nav"))))
    if submit_like == 0:
        issues.append({"level": "info", "at_step": -1, "code": "no_submit_click",
                       "message": "Koi click step `wait_nav: true` ke saath nahi — form submit nahi hota hoga ya navigation track nahi ho raha."})

    return issues


# ─────────────────────────────────────────────────────────────────────────
# 10. Per-step retry runner
# ─────────────────────────────────────────────────────────────────────────
async def run_with_retry(coro_factory: Callable[[], Awaitable[Any]],
                         retry: int = 0, retry_delay_ms: int = 1000,
                         label: str = "") -> Any:
    """Call `coro_factory()` up to (1 + retry) times. Returns the result
    or raises the last exception.

    `coro_factory` MUST return a fresh awaitable on each call (so we can
    re-await after a failure). Pass it as a lambda: lambda: page.click(...).
    """
    import asyncio as _aio
    attempts = max(0, int(retry)) + 1
    last_exc: Optional[Exception] = None
    for n in range(attempts):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if n < attempts - 1:
                if label:
                    logger.info(f"[retry{(' '+label) if label else ''}] attempt {n+1}/{attempts} failed: {str(e)[:120]} — retrying in {retry_delay_ms}ms")
                try:
                    await _aio.sleep(retry_delay_ms / 1000.0)
                except Exception:
                    pass
    assert last_exc is not None
    raise last_exc


# ─────────────────────────────────────────────────────────────────────────
# 11. New tab / popup follower
# ─────────────────────────────────────────────────────────────────────────
# When a click opens a new tab/window, return the latest active page so
# subsequent steps can target it.

async def latest_popup_page(context: Any, current_page: Any,
                            timeout_ms: int = 5000) -> Optional[Any]:
    """If a popup/new tab was opened recently, return it; otherwise None.

    Strategy:
      • Listen for `page` event on context for `timeout_ms`.
      • If nothing arrives, fall back to looking for any page in context
        that isn't `current_page` and is newer.
    """
    import asyncio as _aio
    try:
        new_page_event = _aio.create_task(
            context.wait_for_event("page", timeout=timeout_ms)
        )
        done, _ = await _aio.wait({new_page_event}, timeout=timeout_ms / 1000.0)
        if new_page_event in done:
            try:
                p = new_page_event.result()
                return p
            except Exception:
                pass
    except Exception:
        pass
    # Fallback — scan existing pages
    try:
        for p in reversed(context.pages):
            if p is not current_page:
                return p
    except Exception:
        pass
    return None
