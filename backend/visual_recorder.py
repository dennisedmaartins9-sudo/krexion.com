"""
Visual Recorder — interactive Playwright session manager that records the
user's clicks/typing as a Krexion automation JSON.

Workflow:
1. /api/visual-recorder/start — launches a headless Chromium with the
   user's chosen proxy + UA, opens the URL, returns a session_id.
2. The frontend polls /screenshot every ~700ms to render a live preview.
3. Each user interaction (click, type, wait, navigate) is forwarded to
   /click, /type, /wait, /navigate which:
     a. Performs the action inside Playwright.
     b. Captures a robust selector of the affected element.
     c. Appends a step to the in-memory `steps` array.
4. /mark-final captures the current screenshot as the conversion target.
5. /finalize stops the browser, returns the assembled JSON + the saved
   target screenshot (path).

Sessions auto-cleanup if idle >45 min. There is NO total-time cap
(per user requirement).
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import string
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("visual_recorder")

# ── Tunables ────────────────────────────────────────────────────────────
IDLE_TIMEOUT_S = 45 * 60        # 45 min idle → auto-stop session
REAPER_INTERVAL_S = 60          # check every minute
DEFAULT_VIEWPORT = (412, 914)   # Pixel-8 mobile (matches RUT mobile profile)
MAX_CONCURRENT_SESSIONS = 5     # prevent runaway memory
SCREENSHOT_QUALITY = 60         # JPEG quality for stream
SCREENSHOT_TYPE = "jpeg"
# Total time we allow for: playwright start + browser launch + new_context +
# initial goto. Bad/slow proxies otherwise hang the recorder forever.
STARTUP_TIMEOUT_S = 45          # Increased to 45s for slow proxies
LAUNCH_TIMEOUT_S = 15           # browser launch + context only
GOTO_TIMEOUT_MS = 35_000        # Increased to 35s for initial page.goto with slow proxies

# Persistent storage for finalized recordings.
#
# v2.1.19 — On Windows desktop installs, `__file__` points inside
# `C:\Program Files\Krexion Desktop\resources\backend\` which the
# installer sets to READ-ONLY for security. The original code did
# `Path(__file__).parent / "visual_recorder_sessions"` and then
# `.mkdir(...)` at module import time — that mkdir raised
# `PermissionError: [WinError 5] Access denied` which crashed the
# import. server.py then catches the failure and sets `vr = None`,
# leaving the customer with "Visual recorder module not available".
#
# Fix: prefer a per-user writable data root. Resolution order:
#   1. KREXION_DATA_DIR env var (set by main.js to %APPDATA%\Krexion-Desktop)
#   2. %APPDATA%\Krexion-Desktop on Windows
#   3. ~/.krexion on POSIX
#   4. fall back to Path(__file__).parent (cloud / dev installs where
#      the backend dir IS writable).
import os as _os_vr
def _resolve_sessions_root() -> Path:
    env_root = _os_vr.environ.get("KREXION_DATA_DIR")
    if env_root:
        return Path(env_root) / "visual_recorder_sessions"
    appdata = _os_vr.environ.get("APPDATA")  # Windows: %APPDATA%
    if appdata:
        return Path(appdata) / "Krexion-Desktop" / "visual_recorder_sessions"
    return Path.home() / ".krexion" / "visual_recorder_sessions"


try:
    SESSIONS_ROOT = _resolve_sessions_root()
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Last-resort: every Windows user has write access to %TEMP%, so
    # we can still run the recorder there even on a locked-down
    # install. Recordings will be lost on cleanup but the feature
    # itself stops being "unavailable".
    import tempfile as _tempfile_vr
    SESSIONS_ROOT = Path(_tempfile_vr.gettempdir()) / "krexion-visual-recorder"
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)


# ── Proxy parsing ───────────────────────────────────────────────────────
# Visual Recorder accepts the same flexible proxy string format used by
# the rest of Krexion (RUT, AdsPower, etc.):
#   host:port
#   host:port:user:pass
#   user:pass@host:port
#   http://user:pass@host:port
#   socks5://user:pass@host:port
# Returns Playwright's proxy dict ({server, username, password}) or None
# on invalid input. Without this, credentials were silently dropped and
# authenticated residential proxies returned ERR_TUNNEL_CONNECTION_FAILED
# (visible to the user as a blank live-preview).
def _parse_proxy_for_playwright(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    scheme = "http"
    for prefix, sch in (("http://", "http"), ("https://", "https"),
                        ("socks5://", "socks5"), ("socks4://", "socks4")):
        if s.lower().startswith(prefix):
            scheme = sch
            s = s[len(prefix):]
            break
    user, pwd = None, None
    if "@" in s:
        auth, s = s.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
        else:
            user = auth
    parts = s.split(":")
    if len(parts) == 2:
        host, port = parts
    elif len(parts) == 4:
        # host:port:user:pass
        host, port, user, pwd = parts
    else:
        return None
    try:
        int(port)
    except ValueError:
        return None
    out: Dict[str, Any] = {"server": f"{scheme}://{host}:{port}"}
    if user:
        out["username"] = user
    if pwd:
        out["password"] = pwd
    return out



# ── 2026-05: Rich element metadata capture for robust replay ────────────
# Every recorded step that targets a specific element (click form_fill,
# check, select, fill) now ALSO embeds a `fallbacks` dict describing the
# element by multiple complementary strategies:
#   • xpath_stable — xpath using stable attrs (id, name) where available,
#                    so a sibling reorder elsewhere on the page can't
#                    break it.
#   • xpath_abs    — full root-to-element xpath (fragile but precise
#                    when the page structure is identical to recording).
#   • text         — visible text content (trimmed, ≤80 chars).
#   • tag          — element tag (button, input, etc.) — used to scope
#                    text-based fallbacks so we don't accidentally
#                    match a stray <div> with the same words.
#   • attrs        — {id, name, type, placeholder, aria-label, role,
#                    data-testid, autocomplete, …} all surviving attrs.
#
# At REPLAY time, real_user_traffic.py's `_step_fallbacks(step)` reads
# this dict and FEEDS each strategy as an additional selector
# alternative into `_smart_wait_for_selector`. So the resolution
# pipeline becomes:
#   1. exact selector (recorded)
#   2. step.fallbacks.xpath_stable
#   3. step.fallbacks.xpath_abs
#   4. attribute-derived combos
#   5. text-based scoped to tag
#   6. user-aliased selectors (self-healing store)
#   7. token-derived & field-type fallbacks (legacy)
#
# Existing recordings WITHOUT a `fallbacks` dict keep working exactly
# as before — pure additive, zero-risk to old JSONs.
_RICH_ELEMENT_CAPTURE_JS = r"""
([x,y]) => {
  // v2.6.27 — iframe-aware capture. Real landing pages often open
  // popups / modals as iframes (survey funnels, exit-intent overlays,
  // sweepstakes forms). Previously `document.elementFromPoint(x,y)`
  // returned the <iframe> CONTAINER element and we recorded a
  // meaningless "click on iframe" step — the actual button inside the
  // popup was never targeted. We now drill into same-origin iframes
  // and record the ACTUAL element (inside the frame), attaching an
  // `iframe_path` array that lists each iframe's CSS selector so the
  // RUT/VR replay engine can navigate to the right frame via
  // Playwright's `page.frame_locator()`.
  //
  // Cross-origin iframes still fall back to the container-element
  // behaviour (browser sandbox forbids drilling in) — the operator
  // sees "no capture" for those and can hand-edit the step.

  function iframeSelector(iframeEl) {
    // Build a stable CSS selector for THIS iframe so the replay
    // engine can find it later. Prefer id > name > data-testid >
    // src (last-path-segment) > nth-of-type.
    if (iframeEl.id)          return 'iframe#' + iframeEl.id;
    if (iframeEl.getAttribute && iframeEl.getAttribute('name'))
      return 'iframe[name="' + iframeEl.getAttribute('name') + '"]';
    if (iframeEl.getAttribute && iframeEl.getAttribute('data-testid'))
      return 'iframe[data-testid="' + iframeEl.getAttribute('data-testid') + '"]';
    var src = (iframeEl.src || '').trim();
    if (src) {
      // Use only the LAST path segment (or filename) since query
      // params drift across page loads.
      var m = src.match(/([^\/?#]+)(?:[?#].*)?$/);
      if (m && m[1]) return 'iframe[src*="' + m[1].replace(/"/g, '\\"') + '"]';
    }
    // Nth-of-type fallback — count preceding sibling iframes in doc order.
    var idx = 1, sib = iframeEl.previousElementSibling;
    while (sib) {
      if (sib.tagName === 'IFRAME' || sib.tagName === 'FRAME') idx++;
      sib = sib.previousElementSibling;
    }
    return 'iframe:nth-of-type(' + idx + ')';
  }

  // v2.6.50 — Modal-aware hit testing. A single elementFromPoint(x,y)
  // often returns the full-screen backdrop or modal wrapper instead of
  // the BUTTON the user actually clicked (e.g. "START DEAL" inside a
  // popup). We stack-scan with elementsFromPoint when available and
  // prefer interactive targets inside the visible modal container.
  function isVisibleEl(el) {
    try {
      var cs = window.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (parseFloat(cs.opacity || '1') < 0.05) return false;
      if (cs.pointerEvents === 'none') return false;
      var r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return false;
      return true;
    } catch (e) { return false; }
  }

  function isInteractive(el) {
    if (!el || el.nodeType !== 1) return false;
    var tag = el.tagName;
    if (/^(A|BUTTON|INPUT|SELECT|TEXTAREA|LABEL)$/.test(tag)) return true;
    var role = ((el.getAttribute && el.getAttribute('role')) || '').toLowerCase();
    if (role === 'button' || role === 'link' || role === 'checkbox' || role === 'radio') return true;
    if (el.hasAttribute && el.hasAttribute('onclick')) return true;
    return false;
  }

  function isBackdropOrOverlay(el) {
    if (!el || el.nodeType !== 1) return false;
    var tag = el.tagName;
    if (tag !== 'DIV' && tag !== 'SPAN' && tag !== 'SECTION') return false;
    var cls = ((el.className || '') + '').toLowerCase();
    if (/backdrop|overlay|modal-backdrop|modal-overlay|scrim|mask|underlay/.test(cls)) return true;
    try {
      var cs = window.getComputedStyle(el);
      var pos = cs.position;
      if ((pos === 'fixed' || pos === 'absolute') && !isInteractive(el)) {
        var r = el.getBoundingClientRect();
        var vw = window.innerWidth || 1;
        var vh = window.innerHeight || 1;
        var area = r.width * r.height;
        var vwvh = vw * vh;
        if (area / vwvh > 0.85 && parseFloat(cs.opacity || '1') < 0.95) return true;
        var bg = cs.backgroundColor || '';
        if (/rgba?\(\s*0,\s*0,\s*0/.test(bg) && area / vwvh > 0.45) return true;
      }
    } catch (e) { /* skip */ }
    return false;
  }

  function findModalContainer(doc, px, py) {
    var popupSel = [
      '[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]',
      '.modal', '.popup', '.dialog', '.overlay', '.lightbox', '.drawer',
      '.MuiDialog-root', '.ant-modal', '.ReactModal__Content',
      '.chakra-modal__content', '.swal2-container', '.sweet-alert', '.fancybox-container'
    ].join(', ');
    var candidates = [];
    try {
      candidates = Array.from(doc.querySelectorAll(popupSel)).filter(function(el) {
        try {
          var cs = window.getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          if (parseFloat(cs.opacity || '1') < 0.05) return false;
          var r = el.getBoundingClientRect();
          if (r.width < 20 || r.height < 20) return false;
          return px >= r.left && px <= r.right && py >= r.top && py <= r.bottom;
        } catch (e) { return false; }
      });
    } catch (e) { candidates = []; }
    // Prefer innermost (leaf) modal when nested.
    for (var i = 0; i < candidates.length; i++) {
      for (var j = i + 1; j < candidates.length; j++) {
        if (candidates[i].contains(candidates[j])) {
          candidates.splice(i, 1);
          i--;
          break;
        } else if (candidates[j].contains(candidates[i])) {
          candidates.splice(j, 1);
          j--;
        }
      }
    }
    return candidates.length ? candidates[candidates.length - 1] : null;
  }

  function scoreElement(el, modalContainer) {
    if (!el || !isVisibleEl(el)) return -1000;
    var score = 0;
    if (isInteractive(el)) score += 100;
    if (modalContainer) {
      if (modalContainer.contains(el)) score += 50;
      else score -= 200;
    }
    if (isBackdropOrOverlay(el)) score -= 500;
    var tag = el.tagName;
    if (tag === 'IFRAME' || tag === 'FRAME') score += 10;
    try {
      var r = el.getBoundingClientRect();
      var area = r.width * r.height;
      if (area < 50000) score += 5;
      if (area > 200000 && !isInteractive(el)) score -= 20;
    } catch (e) { /* skip */ }
    return score;
  }

  function bestElementAtPoint(doc, px, py) {
    var modalContainer = findModalContainer(doc, px, py);
    var stack = [];
    if (doc.elementsFromPoint) {
      try { stack = doc.elementsFromPoint(px, py) || []; } catch (e) { stack = []; }
    }
    if (!stack.length) {
      var one = doc.elementFromPoint(px, py);
      if (one) stack = [one];
    }
    var best = null;
    var bestScore = -9999;
    for (var si = 0; si < stack.length; si++) {
      var cand = stack[si];
      if (!cand || cand.nodeType !== 1) continue;
      var sc = scoreElement(cand, modalContainer);
      if (sc > bestScore) {
        bestScore = sc;
        best = cand;
      }
    }
    return best;
  }

  function findInDoc(doc, px, py, framePath) {
    var el = bestElementAtPoint(doc, px, py);
    if (!el) return null;
    // If the point resolves to an iframe/frame, drill in when same-origin.
    if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
      var innerDoc = null;
      try {
        innerDoc = el.contentDocument || (el.contentWindow && el.contentWindow.document);
      } catch (e) {
        innerDoc = null;   // cross-origin — sandbox blocks us
      }
      if (innerDoc) {
        var r = el.getBoundingClientRect();
        var relX = px - r.left;
        var relY = py - r.top;
        var childPath = framePath.concat([iframeSelector(el)]);
        var inner = findInDoc(innerDoc, relX, relY, childPath);
        if (inner) return inner;
      }
      // Fall through — treat iframe itself as the target.
    }
    return { el: el, framePath: framePath, ownerDoc: doc };
  }

  var found = findInDoc(document, x, y, []);
  if (!found) return null;
  var el = found.el;
  var ownerDoc = found.ownerDoc || document;
  var iframePath = found.framePath || [];

  // Walk up to find a meaningful clickable ancestor (same heuristic
  // as the legacy capture so behavior is identical to before).
  var depth = 0;
  while (el && el.parentElement && el.parentElement.tagName !== 'BODY' && depth < 5) {
    var txt = ((el.innerText || el.textContent || el.value || '') + '').trim();
    var isInteractive = /^(A|BUTTON|INPUT|SELECT|TEXTAREA|LABEL)$/.test(el.tagName);
    if (isInteractive || (txt.length > 0 && txt.length < 400)) break;
    el = el.parentElement;
    depth++;
  }

  var r = el.getBoundingClientRect();
  var text = ((el.innerText || el.textContent || el.value || '') + '').replace(/\s+/g, ' ').trim().slice(0, 200);

  // Capture ALL attributes so the replay can try [data-testid=x],
  // [role=button], etc. without us hardcoding a whitelist that misses
  // tomorrow's custom-attr. Values capped at 120 chars.
  var attrs = {};
  if (el.attributes) {
    for (var i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i];
      if (a && a.name) {
        var v = (a.value || '') + '';
        if (v.length > 120) v = v.slice(0, 120);
        attrs[a.name] = v;
      }
    }
  }

  // Absolute xpath
  function absXPath(e) {
    if (e.nodeType !== 1) return '';
    var parts = [];
    while (e && e.nodeType === 1 && e.tagName !== 'HTML') {
      var idx = 1, sib = e.previousElementSibling;
      while (sib) {
        if (sib.tagName === e.tagName) idx++;
        sib = sib.previousElementSibling;
      }
      parts.unshift(e.tagName.toLowerCase() + '[' + idx + ']');
      e = e.parentElement;
    }
    return '/html/' + parts.join('/');
  }

  // Stable xpath — anchors on the FIRST stable attribute encountered
  // walking from the element toward <html>. Falls back to '' if none.
  function stableXPath(e) {
    if (e.nodeType !== 1) return '';
    var STABLE_ATTRS = ['id', 'data-testid', 'name', 'aria-label', 'placeholder'];
    var node = e;
    var suffix = '';
    while (node && node.nodeType === 1 && node.tagName !== 'HTML') {
      for (var k = 0; k < STABLE_ATTRS.length; k++) {
        var att = STABLE_ATTRS[k];
        var val = node.getAttribute && node.getAttribute(att);
        if (val) {
          val = val.replace(/'/g, "&apos;");
          var head = '//' + node.tagName.toLowerCase() + "[@" + att + "='" + val + "']";
          return head + suffix;
        }
      }
      var idx = 1, sib = node.previousElementSibling;
      while (sib) {
        if (sib.tagName === node.tagName) idx++;
        sib = sib.previousElementSibling;
      }
      suffix = '/' + node.tagName.toLowerCase() + '[' + idx + ']' + suffix;
      node = node.parentElement;
    }
    return '';
  }

  function siblingIndex(e) {
    var idx = 1, sib = e.previousElementSibling;
    while (sib) {
      if (sib.tagName === e.tagName) idx++;
      sib = sib.previousElementSibling;
    }
    return idx;
  }

  return {
    tag: el.tagName,
    text: text,
    placeholder: el.getAttribute && el.getAttribute('placeholder'),
    name: el.getAttribute && el.getAttribute('name'),
    id: el.id || '',
    type: el.type || '',
    aria: el.getAttribute && el.getAttribute('aria-label'),
    x: r.left + r.width / 2,
    y: r.top + r.height / 2,
    xpath_abs: absXPath(el),
    xpath_stable: stableXPath(el),
    attrs: attrs,
    nth_of_type: siblingIndex(el),
    tag_lower: el.tagName.toLowerCase(),
    // v2.6.27 — iframe drill path: empty array means top-level page.
    // Otherwise each entry is a CSS selector like `iframe#modal-popup`
    // that Playwright's `page.frame_locator(sel)` API can navigate to.
    iframe_path: iframePath,
  };
}
"""


def _build_fallbacks(info: Dict[str, Any]) -> Dict[str, Any]:
    """Distil rich element-capture `info` into a compact `fallbacks`
    dict that the replay engine reads via `_step_fallbacks()`.

    Keep it tight (≤ ~600 bytes typical) so JSON exports stay readable.
    Returns `{}` if `info` is missing or has no usable fields — the
    caller can attach it unconditionally (RUT engine treats empty dict
    same as absent).
    """
    if not isinstance(info, dict):
        return {}
    fb: Dict[str, Any] = {}

    xs = (info.get("xpath_stable") or "").strip()
    xa = (info.get("xpath_abs") or "").strip()
    if xs:
        fb["xpath"] = xs
    if xa and xa != xs:
        fb["xpath_abs"] = xa

    txt = (info.get("text") or "").strip()
    if txt and 3 <= len(txt) <= 80:
        fb["text"] = txt

    tag = (info.get("tag") or "").lower()
    if tag:
        fb["tag"] = tag

    nth = info.get("nth_of_type")
    if isinstance(nth, int) and nth > 0:
        fb["nth"] = nth

    attrs_in = info.get("attrs") or {}
    if isinstance(attrs_in, dict) and attrs_in:
        keep_keys = (
            "id", "name", "data-testid", "data-test", "data-cy",
            "data-qa", "data-id", "placeholder", "aria-label",
            "aria-describedby", "role", "type", "autocomplete",
            "for", "href", "title", "alt",
        )
        a: Dict[str, str] = {}
        for k in keep_keys:
            v = attrs_in.get(k)
            if isinstance(v, str) and v and len(v) <= 120:
                a[k] = v
        if a:
            fb["attrs"] = a

    # v2.6.27 — iframe drill path (see _RICH_ELEMENT_CAPTURE_JS). When
    # non-empty, the RUT/VR replay engine navigates to the frame via
    # Playwright's `page.frame_locator(sel).frame_locator(sel2)...`
    # chain BEFORE running the click/fill/type. Empty list (top-level
    # click) is omitted to keep exports terse.
    ip = info.get("iframe_path")
    if isinstance(ip, list) and ip:
        # Cap total path depth + each selector length so JSON stays lean.
        clean_path: List[str] = []
        for seg in ip[:5]:
            if isinstance(seg, str) and 0 < len(seg) <= 200:
                clean_path.append(seg)
        if clean_path:
            fb["iframe_path"] = clean_path

    return fb


def _attach_selector_and_xpath(step: Dict[str, Any], info: Optional[Dict[str, Any]]) -> None:
    """2026-06 — Ensure EVERY recorded step that targets a DOM element
    has BOTH a `selector` AND an `xpath` field at the top level.

    Customer ask: "step mein automatic os button yan field ka selector,
    xpath dono save hone chahye ta k kisi b waja se koi step stuck na ho."

    Why this exists separate from `fallbacks` :
        - The `fallbacks` dict is consumed by the RUT replay engine
          and was never user-visible.  Operators editing a step in
          the recorder UI couldn't SEE the xpath that was captured,
          which led to confusion ("did the recorder save the xpath?")
          and to manual fixes that overwrote the wrong field.
        - Surfacing `selector` + `xpath` as top-level editable fields
          makes both strategies visible to the operator AND visible
          to the RUT engine (which already reads top-level
          `step["xpath"]` as an additional alt — see
          `real_user_traffic._step_xpath_alt`).

    Behaviour:
        - NEVER overwrites an already-populated field (preserves any
          hand-curated value).
        - Picks `xpath_stable` first (survives renames) and falls back
          to `xpath_abs` (full root path).
        - Picks the most specific CSS available: data-testid → id →
          name → class.
        - Mutates `step` in place.  Safe to call with `info=None`
          (no-op).
    """
    if not isinstance(step, dict) or not isinstance(info, dict):
        return
    # XPath top-level
    if not step.get("xpath"):
        xs = (info.get("xpath_stable") or "").strip()
        xa = (info.get("xpath_abs") or "").strip()
        chosen = xs or xa
        if chosen:
            step["xpath"] = chosen
        # Keep the secondary xpath separately so the operator can
        # see BOTH in advanced view.
        if xs and xa and xs != xa and not step.get("xpath_abs"):
            step["xpath_abs"] = xa
    # CSS selector top-level — only fill if missing (most step
    # builders already set this, but check is cheap + idempotent).
    if not step.get("selector"):
        attrs = info.get("attrs") if isinstance(info.get("attrs"), dict) else {}
        best = ""
        for k in ("data-testid", "data-test", "data-cy", "data-qa", "data-id"):
            v = attrs.get(k) if attrs else None
            if isinstance(v, str) and v:
                v_esc = v.replace('"', '\\"')
                best = f'[{k}="{v_esc}"]'
                break
        if not best:
            _id = (info.get("id") or "").strip()
            if _id and not re.match(r"^[\d_-]", _id) and ":" not in _id and len(_id) < 60:
                best = f"#{_id}"
        if not best and attrs:
            nm = attrs.get("name")
            if isinstance(nm, str) and nm:
                tag_l = (info.get("tag") or "").lower()
                nm_esc = nm.replace('"', '\\"')
                best = f'{tag_l}[name="{nm_esc}"]' if tag_l else f'[name="{nm_esc}"]'
        if best:
            step["selector"] = best



def _build_text_click_evaluate(text: str, info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """JS that finds an element by visible text and clicks it.

    Robust against re-renders because it re-queries every replay.

    ── 2026-01 (selector-priority upgrade) ──
    If `info` (the rich element-capture dict from
    `_RICH_ELEMENT_CAPTURE_JS`) is provided, the emitted JS first
    tries — IN ORDER — to find the element by:
       1. CSS selector built from `id` / `data-testid` / `name`
       2. `xpath_stable` (anchored on the nearest stable ancestor attr)
       3. `xpath_abs` (DOM-position fallback)
       4. Visible-text matching (the legacy strategy, kept verbatim)

    This dramatically improves replay reliability for offer pages
    whose CTA wording changes between recording and replay (a/b
    rotators, dynamic banners) — selectors stay stable even when
    text shifts. Pure additive: if none of 1-3 match the JS falls
    through to the legacy text matcher with the exact same behaviour
    as before, so old recordings (and the random-pick callers that
    don't pass `info`) keep working unchanged.

    ── 2026-05 (revised) ──
    PRIORITISE ANCHORS. Many offer-page CTAs are anchors wrapped in
    DIV/SPAN containers (e.g. `<div class="text-center"><a href="...">
    Unlock Now</a></div>`). The naive "all elements" query matched the
    outer DIV first because its visible innerText was the SAME as the
    anchor's. Clicking the DIV did nothing useful (no href, no submit
    handler). We now search anchors first; if an `<a>` with matching
    text is found we navigate via `window.location.assign(el.href)`
    which is deterministic in headless Chromium + residential proxy
    (where the synthetic .click() event on anchors was being lost).

    For non-anchor matches we ALSO peek inside for a descendant `<a>`
    — common pattern in card-style CTAs. Falls back to a plain
    `.click()` for true buttons / input[type=submit] / React onClick
    spans.

    ── 2026-05 #2 (submit-button fix) ──
    For `input[type=submit]` and `button[type=submit]`, calling
    `el.click()` in JS does NOT always navigate (the browser's submit
    dispatcher may be skipped under headless + residential proxy).
    We now also call `form.submit()` 150ms after .click() as a safety
    net. Double-submits are de-duplicated server-side by the offer
    page's antispam token; the small delay lets any onclick analytics
    fire before the forced submit.
    """
    safe = text.replace("\\", "\\\\").replace("'", "\\'")

    # ── Selector-priority block ────────────────────────────────────
    # Built ONLY when `info` is provided. We inline literal CSS /
    # XPath strings into the emitted JS so the replay engine can
    # find the element WITHOUT re-running our capture pass.
    selector_block = ""
    if info and isinstance(info, dict):
        candidate_css: List[str] = []

        # Highest priority: explicit test-only attributes.
        attrs = info.get("attrs") or {}
        for k in ("data-testid", "data-test", "data-cy", "data-qa", "data-id"):
            v = attrs.get(k)
            if isinstance(v, str) and v:
                candidate_css.append(f'[{k}="{v}"]')

        # id (skip if it looks autogenerated — e.g. starts with digits
        # or contains a uuid-ish segment; those change on every render).
        _id = (info.get("id") or "").strip()
        if _id and not re.match(r"^[\d_-]", _id) and len(_id) < 60 and ":" not in _id:
            candidate_css.append(f"#{_id}")

        # name attribute
        _name = attrs.get("name") if isinstance(attrs.get("name"), str) else ""
        if _name:
            tag = (info.get("tag") or "").lower()
            if tag:
                candidate_css.append(f'{tag}[name="{_name}"]')
            else:
                candidate_css.append(f'[name="{_name}"]')

        # aria-label
        _aria = attrs.get("aria-label") if isinstance(attrs.get("aria-label"), str) else ""
        if _aria and len(_aria) <= 80:
            candidate_css.append(f'[aria-label="{_aria}"]')

        # Build an array literal of CSS selectors + the two XPaths
        # so the JS can iterate.
        def _js_str(s: str) -> str:
            return s.replace("\\", "\\\\").replace("'", "\\'")

        css_arr_js = "[" + ",".join(
            "'" + _js_str(c) + "'" for c in candidate_css
        ) + "]"
        xpath_stable = (info.get("xpath_stable") or "").strip()
        xpath_abs = (info.get("xpath_abs") or "").strip()
        xpath_stable_js = "'" + _js_str(xpath_stable) + "'" if xpath_stable else "''"
        xpath_abs_js = "'" + _js_str(xpath_abs) + "'" if xpath_abs and xpath_abs != xpath_stable else "''"

        # The emitted block tries each selector / xpath in turn. On
        # match it does the same anchor/inner/submit handling as the
        # text-based path so behaviour is uniform regardless of how
        # the element was located.
        selector_block = (
            "var _krxClick=function(el){"
            "if(!el)return false;"
            "var s=window.getComputedStyle(el);"
            "if(s.display==='none'||s.visibility==='hidden')return false;"
            "el.scrollIntoView({block:'center'});"
            # Anchor → location.assign for deterministic nav
            "if(el.tagName==='A'&&el.href&&!el.target){window.location.assign(el.href);return true;}"
            # LABEL[for] → click the real control
            "if(el.tagName==='LABEL'&&el.htmlFor){var ctl=document.getElementById(el.htmlFor);if(ctl){ctl.scrollIntoView({block:'center'});ctl.click();return true;}}"
            # Inner anchor (CTA-card pattern)
            "var inner=el.querySelector&&el.querySelector('a[href]');"
            "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return true;}"
            # Inner checkbox/radio
            "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
            "if(box&&!box.checked){box.click();return true;}"
            # Plain click
            "el.click();"
            "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
            "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
            "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
            "return true;};"
            # 1. CSS selectors
            "var _css=" + css_arr_js + ";"
            "for(var i=0;i<_css.length;i++){try{var _e=document.querySelector(_css[i]);if(_e&&_krxClick(_e))return;}catch(e){}}"
            # 2. xpath_stable
            "var _xs=" + xpath_stable_js + ";"
            "if(_xs){try{var _r=document.evaluate(_xs,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);if(_r&&_r.singleNodeValue&&_krxClick(_r.singleNodeValue))return;}catch(e){}}"
            # 3. xpath_abs
            "var _xa=" + xpath_abs_js + ";"
            "if(_xa){try{var _r2=document.evaluate(_xa,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);if(_r2&&_r2.singleNodeValue&&_krxClick(_r2.singleNodeValue))return;}catch(e){}}"
        )

    script = (
        "(function(){"
        + selector_block +
        "var t='" + safe + "'.replace(/\\s+/g,' ').trim().toLowerCase();"
        # If we entered the selector_block path and nothing matched
        # (e.g. all selectors stale), continue with text-based matching
        # below — no early return needed since selector_block returns
        # on success via `return;`.
        "var match=function(e){var s=window.getComputedStyle(e);"
        "if(s.display==='none'||s.visibility==='hidden')return false;"
        # 2026-01: Normalize whitespace + use CONTAINS match for long text.
        # Exact-match was too brittle — pages add trailing words like
        # "below." or wrap CTAs in extra <span> children that break === .
        # We use word-aware contains so we don't false-match short tokens.
        "var x=((e.innerText||e.textContent||e.value||'')+'').replace(/\\s+/g,' ').trim().toLowerCase();"
        "if(!x)return false;"
        "if(x===t)return true;"
        "if(t.length>=12&&x.indexOf(t)!==-1)return true;"
        "if(t.length>=12&&x.length>=8&&t.indexOf(x)!==-1)return true;"
        "return false;};"
        # 1. Prefer real anchors
        "var anchors=Array.from(document.querySelectorAll('a')).filter(match);"
        "if(anchors.length){var a=anchors[0];a.scrollIntoView({block:'center'});"
        "if(a.href&&!a.target){window.location.assign(a.href);}else{a.click();}return;}"
        # 2. Fall back to other clickable elements (added input + label-for handling)
        "var els=Array.from(document.querySelectorAll('button,div,span,label,input,[role=button],[role=checkbox]')).filter(match);"
        "if(els.length){var el=els[0];el.scrollIntoView({block:'center'});"
        # 2026-01: If matched element is a LABEL with `for=`, click the
        # actual control it points to (fixes checkbox text-click failures
        # where the visible text is in a <label> but the real input is
        # a separate <input type=checkbox>).
        "if(el.tagName==='LABEL'&&el.htmlFor){var ctl=document.getElementById(el.htmlFor);if(ctl){ctl.scrollIntoView({block:'center'});ctl.click();return;}}"
        # Peek inside for a wrapped anchor (CTA-card pattern)
        "var inner=el.querySelector&&el.querySelector('a[href]');"
        "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return;}"
        # 2026-01: If matched element contains a checkbox / radio, click that
        "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
        "if(box&&!box.checked){box.click();return;}"
        # Otherwise plain click
        "el.click();"
        # If this was a submit button, force the form submission as a safety net
        "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
        "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
        "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
        "}})();"
    )
    return {"action": "evaluate", "script": script}


def _locator_candidates_from_info(info: Dict[str, Any]) -> List[str]:
    """Build CSS selector candidates from rich element-capture metadata."""
    if not isinstance(info, dict):
        return []
    cands: List[str] = []
    attrs = info.get("attrs") or {}
    for k in ("data-testid", "data-test", "data-cy", "data-qa", "data-id"):
        v = attrs.get(k)
        if isinstance(v, str) and v:
            cands.append(f'[{k}="{v}"]')
    _id = (info.get("id") or "").strip()
    if _id and not re.match(r"^[\d_-]", _id) and len(_id) < 60 and ":" not in _id:
        cands.append(f"#{_id}")
    _name = attrs.get("name") if isinstance(attrs.get("name"), str) else ""
    if _name:
        tag = (info.get("tag") or "").lower()
        if tag:
            cands.append(f'{tag}[name="{_name}"]')
        else:
            cands.append(f'[name="{_name}"]')
    _aria = attrs.get("aria-label") if isinstance(attrs.get("aria-label"), str) else ""
    if _aria and len(_aria) <= 80:
        cands.append(f'[aria-label="{_aria}"]')
    return cands


async def _live_click_captured(page: Any, info: Dict[str, Any]) -> bool:
    """Perform a live click using captured element metadata (modal/iframe aware).

    Tries, in order: frame_locator chain + CSS locators, top-level locators,
    the same selector-priority JS as replay (_build_text_click_evaluate), then
    coordinate mouse.click as last resort.
    """
    if not info or not isinstance(info, dict):
        return False

    text = (info.get("text") or "").strip()
    iframe_path = info.get("iframe_path") or []
    if not isinstance(iframe_path, list):
        iframe_path = []
    locators = _locator_candidates_from_info(info)

    async def _try_locator_clicks(root: Any, *, force: bool = False) -> bool:
        for sel in locators:
            try:
                await root.locator(sel).first.click(timeout=3000, force=force)
                return True
            except Exception:
                continue
        if text:
            try:
                await root.get_by_text(text, exact=False).first.click(timeout=3000, force=force)
                return True
            except Exception:
                pass
        return False

    # 1. iframe_path chain (cross-origin safe via frame_locator)
    if iframe_path:
        try:
            fl: Any = page
            for seg in iframe_path:
                if not isinstance(seg, str) or not seg.strip():
                    continue
                fl = fl.frame_locator(seg.strip())
            if await _try_locator_clicks(fl):
                return True
            if await _try_locator_clicks(fl, force=True):
                return True
            # JS fallback scoped to the iframe document
            if locators or text:
                live_js = _build_text_click_evaluate(text or "", info)
                try:
                    await fl.locator("html").first.evaluate(live_js["script"])
                    return True
                except Exception:
                    pass
        except Exception:
            pass

    # 2. Top-level Playwright locators (normal then force — modal overlays)
    if await _try_locator_clicks(page):
        return True
    if await _try_locator_clicks(page, force=True):
        return True

    # 3. Top-level JS (selector-priority + text match — same as replay)
    if locators or text:
        try:
            live_js = _build_text_click_evaluate(text or "", info)
            await page.evaluate(live_js["script"])
            return True
        except Exception:
            pass

    # 4. Coordinate fallback
    try:
        x = float(info.get("x", 0))
        y = float(info.get("y", 0))
        if x > 0 and y > 0:
            await page.mouse.click(x, y)
            return True
    except Exception:
        pass

    return False


def _classify_gender_side(label: str) -> Optional[str]:
    """Return ``male`` / ``female`` for a captured button label, else None."""
    t = (label or "").strip().lower()
    if not t:
        return None
    if t in ("m", "male", "man") or t.startswith("male"):
        return "male"
    if t in ("f", "female", "woman") or t.startswith("female"):
        return "female"
    return None


def _split_gender_button_labels(labels: List[str]) -> Tuple[List[str], List[str]]:
    """Partition recorded button texts into male-side and female-side pools."""
    male: List[str] = []
    female: List[str] = []
    unknown: List[str] = []
    seen: set = set()
    for raw in labels or []:
        lb = (raw or "").strip()
        if not lb:
            continue
        key = lb.lower()
        if key in seen:
            continue
        seen.add(key)
        side = _classify_gender_side(lb)
        if side == "male":
            male.append(lb)
        elif side == "female":
            female.append(lb)
        else:
            unknown.append(lb)
    if not male and not female and len(unknown) >= 2:
        male = [unknown[0]]
        female = [unknown[1]]
    elif unknown:
        for lb in unknown:
            (male if len(male) <= len(female) else female).append(lb)
    return male, female


def _js_str_list(items: List[str]) -> str:
    safe = []
    for it in items:
        s = (it or "").replace("\\", "\\\\").replace("'", "\\'")
        if s:
            safe.append("'" + s + "'")
    return "[" + ",".join(safe) + "]"


def _build_gender_pick_evaluate(
    header_name: str,
    male_labels: List[str],
    female_labels: List[str],
) -> Dict[str, Any]:
    """Sheet-driven gender button click using recorded Male/Female labels."""
    hn = (header_name or "").strip()
    if not hn:
        raise ValueError("header_name required for gender_pick")
    safe_tpl = ("{{" + hn + "}}").replace("\\", "\\\\").replace("'", "\\'")
    male_js = _js_str_list(male_labels or ["Male", "M", "male", "m"])
    female_js = _js_str_list(female_labels or ["Female", "F", "female", "f"])
    script = (
        "(function(){"
        "var raw='" + safe_tpl + "'.replace(/\\s+/g,' ').trim().toLowerCase();"
        "var wantMale=raw==='m'||raw==='male'||raw==='man';"
        "var wantFemale=raw==='f'||raw==='female'||raw==='woman';"
        "var maleLabels=" + male_js + ";"
        "var femaleLabels=" + female_js + ";"
        "var targets=wantMale?maleLabels:(wantFemale?femaleLabels:[raw]);"
        "if(!targets||!targets.length)targets=[raw];"
        "var norm=function(s){return String(s||'').replace(/\\s+/g,' ').trim().toLowerCase();};"
        "var match=function(e){var s=window.getComputedStyle(e);"
        "if(s.display==='none'||s.visibility==='hidden')return false;"
        "var x=norm((e.innerText||e.textContent||e.value||''));"
        "if(!x)return false;"
        "for(var i=0;i<targets.length;i++){"
        "var t=norm(targets[i]);if(!t)continue;"
        "if(x===t)return true;"
        "if(t.length>=2&&x.indexOf(t)!==-1)return true;"
        "if(x.length>=2&&t.indexOf(x)!==-1)return true;"
        "if(t==='male'&&(x==='m'||x.indexOf('male')===0))return true;"
        "if(t==='female'&&(x==='f'||x.indexOf('female')===0))return true;"
        "}"
        "return false;};"
        "var anchors=Array.from(document.querySelectorAll('a')).filter(match);"
        "if(anchors.length){var a=anchors[0];a.scrollIntoView({block:'center'});"
        "if(a.href&&!a.target){window.location.assign(a.href);}else{a.click();}return;}"
        "var els=Array.from(document.querySelectorAll('button,div,span,label,input,[role=button],[role=radio]')).filter(match);"
        "if(els.length){var el=els[0];el.scrollIntoView({block:'center'});"
        "if(el.tagName==='LABEL'&&el.htmlFor){var ctl=document.getElementById(el.htmlFor);if(ctl){ctl.scrollIntoView({block:'center'});ctl.click();return;}}"
        "var inner=el.querySelector&&el.querySelector('a[href]');"
        "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return;}"
        "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
        "if(box&&!box.checked){box.click();return;}"
        "el.click();"
        "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
        "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
        "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
        "}})();"
    )
    return {
        "action": "evaluate",
        "script": script,
        "origin": "gender_pick",
        "header_name": hn,
        "gender_labels": {"male": male_labels, "female": female_labels},
    }


def _build_sheet_pick_evaluate(header_name: str) -> Dict[str, Any]:
    """Text-based button click driven by an Excel column at replay time.

    Unlike ``_build_text_click_evaluate(text, info)`` this deliberately
    omits CSS/XPath selector priority so we never lock to whichever
    button (e.g. Male) the user clicked during recording.  The emitted
    script uses ``var t='{{header}}'`` and normalises common gender
    shorthands (M/F → male/female) before text matching.
    """
    hn = (header_name or "").strip()
    if not hn:
        raise ValueError("header_name required for sheet_pick")
    safe_tpl = ("{{" + hn + "}}").replace("\\", "\\\\").replace("'", "\\'")
    script = (
        "(function(){"
        "var raw='" + safe_tpl + "'.replace(/\\s+/g,' ').trim().toLowerCase();"
        "var t=raw;"
        "if(raw==='m'||raw==='male'||raw==='man')t='male';"
        "else if(raw==='f'||raw==='female'||raw==='woman')t='female';"
        "var match=function(e){var s=window.getComputedStyle(e);"
        "if(s.display==='none'||s.visibility==='hidden')return false;"
        "var x=((e.innerText||e.textContent||e.value||'')+'').replace(/\\s+/g,' ').trim().toLowerCase();"
        "if(!x)return false;"
        "if(x===t)return true;"
        "if(t.length>=12&&x.indexOf(t)!==-1)return true;"
        "if(t.length>=12&&x.length>=8&&t.indexOf(x)!==-1)return true;"
        "if(t==='male'&&(x==='m'||x.indexOf('male')===0))return true;"
        "if(t==='female'&&(x==='f'||x.indexOf('female')===0))return true;"
        "return false;};"
        "var anchors=Array.from(document.querySelectorAll('a')).filter(match);"
        "if(anchors.length){var a=anchors[0];a.scrollIntoView({block:'center'});"
        "if(a.href&&!a.target){window.location.assign(a.href);}else{a.click();}return;}"
        "var els=Array.from(document.querySelectorAll('button,div,span,label,input,[role=button],[role=radio]')).filter(match);"
        "if(els.length){var el=els[0];el.scrollIntoView({block:'center'});"
        "if(el.tagName==='LABEL'&&el.htmlFor){var ctl=document.getElementById(el.htmlFor);if(ctl){ctl.scrollIntoView({block:'center'});ctl.click();return;}}"
        "var inner=el.querySelector&&el.querySelector('a[href]');"
        "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return;}"
        "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
        "if(box&&!box.checked){box.click();return;}"
        "el.click();"
        "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
        "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
        "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
        "}})();"
    )
    return {
        "action": "evaluate",
        "script": script,
        "origin": "sheet_pick",
        "header_name": hn,
    }


def _is_gender_header(header_name: Optional[str]) -> bool:
    key = (header_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return key in ("gender", "sex") or "gender" in key or key.endswith("_sex")


def _normalize_gender_click_label(value: str) -> str:
    """Map M/F shorthands to button-visible labels for live recording clicks."""
    g = (value or "").strip().lower()
    if g in ("m", "male", "man"):
        return "Male"
    if g in ("f", "female", "woman"):
        return "Female"
    return (value or "").strip()


def _build_random_pick_advanced(options: List[Dict[str, str]]) -> Dict[str, Any]:
    """2026-05 — Random-pick with PER-OPTION fallback strategies.

    Each option is a dict {text, selector, xpath} (any/all may be empty).
    The emitted JS picks one option at random then tries, in order:
      1. CSS selector (if provided + matches something)
      2. XPath (if provided + matches something)
      3. Text-contains fallback (same heuristic as the legacy builder)

    This addresses the user request: "edit mein random jo selection ki
    har selection k selector or xpath wagera add krne ka b option ho".
    Recorded as `action: random_pick_advanced` so old recordings keep
    using `evaluate` and the engine treats the new shape identically
    via this builder's emitted script.
    """
    safe_options = []
    for o in options:
        if not isinstance(o, dict):
            continue
        t = (o.get("text") or "").replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").strip()
        s = (o.get("selector") or "").replace("\\", "\\\\").replace("'", "\\'").strip()
        x = (o.get("xpath") or "").replace("\\", "\\\\").replace("'", "\\'").strip()
        if not (t or s or x):
            continue
        safe_options.append({"t": t, "s": s, "x": x})
    if not safe_options:
        return {"action": "evaluate", "script": "(function(){})();", "pick_options": []}

    opts_arr = "[" + ",".join(
        "{t:'" + o["t"] + "',s:'" + o["s"] + "',x:'" + o["x"] + "'}"
        for o in safe_options
    ) + "]"
    script = (
        "(function(){var opts=" + opts_arr + ";"
        "var pick=opts[Math.floor(Math.random()*opts.length)];"
        "var el=null;"
        # Strategy 1 — CSS selector
        "if(pick.s){try{el=document.querySelector(pick.s);}catch(e){}}"
        # Strategy 2 — XPath
        "if(!el&&pick.x){try{var r=document.evaluate(pick.x,document,null,9,null);el=r.singleNodeValue;}catch(e){}}"
        # Strategy 3 — Text contains (same as legacy)
        "if(!el&&pick.t){var tp=pick.t.replace(/\\s+/g,' ').trim().toLowerCase();"
        "var match=function(e){var st=window.getComputedStyle(e);"
        "if(st.display==='none'||st.visibility==='hidden')return false;"
        "var xt=((e.innerText||e.textContent||e.value||'')+'').replace(/\\s+/g,' ').trim().toLowerCase();"
        "if(!xt)return false;if(xt===tp)return true;"
        "if(tp.length>=12&&xt.indexOf(tp)!==-1)return true;"
        "if(tp.length>=12&&xt.length>=8&&tp.indexOf(xt)!==-1)return true;"
        "return false;};"
        "var a=Array.from(document.querySelectorAll('a')).filter(match);"
        "if(a.length)el=a[0];"
        "if(!el){var b=Array.from(document.querySelectorAll('button,div,span,label,input,[role=button],[role=checkbox]')).filter(match);if(b.length)el=b[0];}}"
        # Common click logic
        "if(!el)return;el.scrollIntoView({block:'center'});"
        "if(el.tagName==='A'&&el.href&&!el.target){window.location.assign(el.href);return;}"
        "if(el.tagName==='LABEL'&&el.htmlFor){var c=document.getElementById(el.htmlFor);if(c){c.scrollIntoView({block:'center'});c.click();return;}}"
        "var inner=el.querySelector&&el.querySelector('a[href]');"
        "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return;}"
        "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
        "if(box&&!box.checked){box.click();return;}"
        "el.click();"
        "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||(el.getAttribute&&el.getAttribute('type')==='submit'));"
        "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
        "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
        "})();"
    )
    return {
        "action": "evaluate",
        "script": script,
        # Persist the structured options so the Edit modal can re-render
        # them next time the user opens this step.
        "pick_options": safe_options,
    }


def _parse_legacy_random_pick(script: str) -> List[Dict[str, str]]:
    """Extract the `labels=[...]` array from an old random-pick evaluate
    script so the Edit modal can show the picks as editable rows even
    for recordings created BEFORE pick_options existed.
    """
    import re
    if not isinstance(script, str):
        return []
    m = re.search(r"var\s+labels\s*=\s*\[([^\]]*)\]", script)
    if not m:
        return []
    body = m.group(1)
    items = re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    out = []
    for it in items:
        # Reverse JS-escape: \\' → ' , \\\\ → \\
        t = it.replace("\\'", "'").replace("\\\\", "\\")
        if t.strip():
            out.append({"text": t.strip(), "selector": "", "xpath": ""})
    return out


def _build_random_pick_evaluate(texts: List[str]) -> Dict[str, Any]:
    """Pick one of N elements (by visible text) at random and click.

    Same anchor-first priority + submit-button force-submit safety net
    as _build_text_click_evaluate.
    """
    safe = [t.replace("\\", "\\\\").replace("'", "\\'") for t in texts]
    arr = "['" + "','".join(safe) + "']"
    script = (
        "(function(){var labels=" + arr + ";"
        "var pick=labels[Math.floor(Math.random()*labels.length)].replace(/\\s+/g,' ').trim().toLowerCase();"
        "var match=function(e){var s=window.getComputedStyle(e);"
        "if(s.display==='none'||s.visibility==='hidden')return false;"
        # 2026-01: same whitespace-normalised + contains match as
        # _build_text_click_evaluate so random survey picks aren't
        # broken by trailing "below." / extra <span> children.
        "var x=((e.innerText||e.textContent||e.value||'')+'').replace(/\\s+/g,' ').trim().toLowerCase();"
        "if(!x)return false;"
        "if(x===pick)return true;"
        "if(pick.length>=12&&x.indexOf(pick)!==-1)return true;"
        "if(pick.length>=12&&x.length>=8&&pick.indexOf(x)!==-1)return true;"
        "return false;};"
        "var anchors=Array.from(document.querySelectorAll('a')).filter(match);"
        "if(anchors.length){var a=anchors[0];a.scrollIntoView({block:'center'});"
        "if(a.href&&!a.target){window.location.assign(a.href);}else{a.click();}return;}"
        "var els=Array.from(document.querySelectorAll('button,div,span,label,input,[role=button],[role=checkbox]')).filter(match);"
        "if(els.length){var el=els[0];el.scrollIntoView({block:'center'});"
        "if(el.tagName==='LABEL'&&el.htmlFor){var ctl=document.getElementById(el.htmlFor);if(ctl){ctl.scrollIntoView({block:'center'});ctl.click();return;}}"
        "var inner=el.querySelector&&el.querySelector('a[href]');"
        "if(inner&&inner.href&&!inner.target){window.location.assign(inner.href);return;}"
        "var box=el.querySelector&&el.querySelector('input[type=checkbox],input[type=radio]');"
        "if(box&&!box.checked){box.click();return;}"
        "el.click();"
        "var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
        "if(isSubmit){var f=el.form||(el.closest&&el.closest('form'));"
        "if(f){setTimeout(function(){try{if(!f._krx_submitted){f._krx_submitted=true;f.submit();}}catch(e){}},150);}}"
        "}})();"
    )
    return {"action": "evaluate", "script": script}


def _build_fill_step(selector: str, value: str) -> Dict[str, Any]:
    return {"action": "fill", "selector": selector, "value": value, "timeout": 6000, "optional": True}


# ── 2026-01: Fallback sample data ──────────────────────────────────────
# When the user binds a form field to a column header (e.g. {{first}})
# but the recorder has NO sample_row (Excel not uploaded) OR the column
# is missing from the sample_row, the live browser input stays empty
# → form validation blocks CONTINUE → user can't record subsequent
# pages (survey / thank-you / etc.).
#
# This helper returns a sensible *temporary* value based on the column
# name so the live form passes validation. The recorded JSON step STILL
# uses the `{{header}}` placeholder — at RUT replay time the actual
# lead row substitutes via the engine's _substitute() function. Production
# behaviour is therefore unchanged; this only affects what's typed into
# the live browser during recording.
_FALLBACK_SAMPLES: Dict[str, str] = {
    # Names
    "first": "John", "firstname": "John", "first_name": "John", "fname": "John", "givenname": "John",
    "last": "Smith", "lastname": "Smith", "last_name": "Smith", "lname": "Smith", "surname": "Smith", "familyname": "Smith",
    "name": "John Smith", "fullname": "John Smith", "full_name": "John Smith",
    "middle": "A", "middlename": "A", "middle_name": "A", "mname": "A",
    # Contact
    "email": "john.smith@example.com", "emailaddress": "john.smith@example.com", "email_address": "john.smith@example.com", "mail": "john.smith@example.com",
    "phone": "5551234567", "phonenumber": "5551234567", "phone_number": "5551234567", "mobile": "5551234567", "tel": "5551234567", "telephone": "5551234567", "cell": "5551234567",
    # Address
    "address": "123 Main Street", "street": "123 Main Street", "streetaddress": "123 Main Street", "street_address": "123 Main Street", "address1": "123 Main Street", "addr": "123 Main Street",
    "address2": "Apt 4B", "apt": "4B", "unit": "4B", "suite": "4B",
    "city": "New York", "town": "New York",
    "state": "NY", "region": "NY", "province": "NY",
    "zip": "10001", "zipcode": "10001", "zip_code": "10001", "postal": "10001", "postalcode": "10001", "postal_code": "10001", "postcode": "10001",
    "country": "United States",
    # DOB
    "day": "15", "birth_day": "15", "birthday": "15", "dob_day": "15", "dday": "15", "bday": "15",
    "month": "6", "birth_month": "6", "birthmonth": "6", "dob_month": "6", "dmonth": "6", "bmonth": "6",
    "year": "1990", "birth_year": "1990", "birthyear": "1990", "dob_year": "1990", "dyear": "1990", "byear": "1990",
    "dob": "06/15/1990", "birthdate": "06/15/1990", "birth_date": "06/15/1990",
    "age": "34",
    # Misc
    "gender": "Male", "sex": "Male",
    "ssn": "123456789", "social": "123456789",
    "income": "50000", "salary": "50000",
    "password": "TempPass123!", "pwd": "TempPass123!", "passwd": "TempPass123!",
    "username": "johnsmith", "user": "johnsmith", "userid": "johnsmith",
    "company": "Acme Corp", "employer": "Acme Corp", "business": "Acme Corp",
}


def _get_fallback_sample_value(header_name: str) -> Optional[str]:
    """Return a temporary sample value for a header name so the live
    browser form fills with realistic data during recording.

    Match is case-insensitive AND tries substring matching as a last
    resort (e.g. "user_first_name" → "first" → "John").
    """
    if not header_name:
        return None
    key = str(header_name).strip().lower().replace("-", "_").replace(" ", "_")
    # Exact match
    if key in _FALLBACK_SAMPLES:
        return _FALLBACK_SAMPLES[key]
    # Try collapsed (no underscores)
    collapsed = key.replace("_", "")
    if collapsed in _FALLBACK_SAMPLES:
        return _FALLBACK_SAMPLES[collapsed]
    # Substring match — longest fallback key first
    for fk in sorted(_FALLBACK_SAMPLES.keys(), key=len, reverse=True):
        if fk in key or fk in collapsed:
            return _FALLBACK_SAMPLES[fk]
    return None


def _is_postal_header(header_name: str) -> bool:
    key = (header_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return any(p in key for p in ("zip", "postal", "postcode"))


# Case-insensitive sample_row column aliases (mirrors RUT _PLACEHOLDER_SYNONYMS).
_SAMPLE_ROW_SYNONYMS: Dict[str, List[str]] = {
    "zip": ["zip_code", "zipcode", "postal", "postal_code", "postalcode", "postcode"],
    "zip_code": ["zip", "zipcode", "postal", "postal_code", "postalcode", "postcode"],
    "gender": ["sex"],
    "sex": ["gender"],
}


def _format_sample_cell_value(header_name: str, raw: Any) -> str:
    """Normalise an Excel cell for live browser fill during recording."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return str(raw)
    key = (header_name or "").strip().lower()
    if _is_postal_header(key):
        if isinstance(raw, (int, float)):
            try:
                n = int(round(float(raw)))
                return str(n).zfill(5) if n < 100000 else str(n)
            except (ValueError, OverflowError):
                pass
        s = str(raw).strip()
        if s.replace(".", "", 1).isdigit() and "." in s:
            try:
                n = int(round(float(s)))
                return str(n).zfill(5) if n < 100000 else str(n)
            except ValueError:
                pass
        digits = "".join(c for c in s if c.isdigit())
        if len(digits) >= 5:
            return digits[:5]
        if digits:
            return digits.zfill(5)
    if isinstance(raw, float) and raw == int(raw):
        return str(int(raw))
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return str(raw).strip()


def _lookup_sample_row(sess: "RecorderSession", header_name: str) -> Optional[Any]:
    """Case-insensitive sample_row lookup with common column synonyms."""
    key = str(header_name or "").strip().lower()
    if not key or not sess.sample_row:
        return None
    if key in sess.sample_row:
        return sess.sample_row[key]
    for syn in _SAMPLE_ROW_SYNONYMS.get(key, []):
        if syn in sess.sample_row:
            return sess.sample_row[syn]
    collapsed = key.replace("_", "")
    for k, v in sess.sample_row.items():
        if str(k).replace("_", "") == collapsed:
            return v
    return None


def _resolve_live_value(sess: "RecorderSession", header_name: str) -> Optional[str]:
    """Resolve the value to fill into the live browser for a header.

    Priority:
      1. sess.sample_row[header_name]  (user-uploaded Excel data)
      2. _get_fallback_sample_value()  (sensible default based on column name)
    """
    if not header_name:
        return None
    raw = _lookup_sample_row(sess, header_name)
    if raw is not None and str(raw).strip() != "":
        return _format_sample_cell_value(header_name, raw)
    return _get_fallback_sample_value(header_name)


def _build_wait(ms: int) -> Dict[str, Any]:
    return {"action": "wait", "ms": int(max(100, min(ms, 120000)))}


def _build_wait_load(timeout_ms: int = 60000) -> Dict[str, Any]:
    return {"action": "wait_for_load", "timeout": int(timeout_ms)}


_SKIP_AUTO_WAIT_AFTER = frozenset({
    "wait",
    "wait_for_load",
    "wait_for_selector",
    "wait_for_text",
    "wait_for_url",
    "wait_for_network_idle",
    "screenshot",
    "close",
    "branch",
    "conditional_skip",
    "accept_dialog",
    "dismiss_dialog",
    "extract",
    "save_storage",
    "restore_storage",
})


def _auto_waits_after_action(action: str) -> List[Dict[str, Any]]:
    """Default auto-wait bundle appended after recorded actions when enabled."""
    a = (action or "").strip().lower()
    if a in _SKIP_AUTO_WAIT_AFTER:
        return []
    if a == "scroll":
        return [_build_wait(500)]
    if a in (
        "click",
        "fill",
        "type",
        "select",
        "check",
        "uncheck",
        "press",
        "hover",
        "evaluate",
        "right_click",
        "drag",
        "drag_drop",
        "switch_tab",
        "close_tab",
        "iframe_click",
        "iframe_fill",
        "shadow_click",
        "random_pick",
        "random_pick_advanced",
        "nav_click",
        "file_upload",
        "otp_wait",
        "captcha_pause",
        "human_pause",
    ):
        return [_build_wait(1500), _build_wait_load(60000), _build_wait(2000)]
    return [_build_wait(800)]


def _build_scroll(y: int) -> Dict[str, Any]:
    return {"action": "scroll", "y": int(y)}


# ── 2026-01: Device / Geo / Template helpers ──────────────────────────
# These give the Visual Recorder the SAME fingerprint coherence that
# RUT and the browser-profile launcher already enjoy. Previously the
# recorder hardcoded mobile+en-US+NY which leaked obvious
# UA/Platform/timezone mismatches → advertisers blacklisted.

# ── Country → (locale, timezone, accept_lang, lat, lon) ──
# Best-effort common mapping. Frontend may override any of these via
# explicit fields on /start. Defaults to en-US/NY when unknown.
_COUNTRY_GEO: Dict[str, Tuple[str, str, str, float, float]] = {
    "us": ("en-US",  "America/New_York",      "en-US,en;q=0.9",                 40.7128,  -74.0060),
    "ca": ("en-CA",  "America/Toronto",       "en-CA,en;q=0.9",                 43.6532,  -79.3832),
    "gb": ("en-GB",  "Europe/London",         "en-GB,en;q=0.9",                 51.5074,   -0.1278),
    "uk": ("en-GB",  "Europe/London",         "en-GB,en;q=0.9",                 51.5074,   -0.1278),
    "au": ("en-AU",  "Australia/Sydney",      "en-AU,en;q=0.9",                -33.8688,  151.2093),
    "de": ("de-DE",  "Europe/Berlin",         "de-DE,de;q=0.9,en;q=0.8",        52.5200,   13.4050),
    "fr": ("fr-FR",  "Europe/Paris",          "fr-FR,fr;q=0.9,en;q=0.8",        48.8566,    2.3522),
    "es": ("es-ES",  "Europe/Madrid",         "es-ES,es;q=0.9,en;q=0.8",        40.4168,   -3.7038),
    "it": ("it-IT",  "Europe/Rome",           "it-IT,it;q=0.9,en;q=0.8",        41.9028,   12.4964),
    "nl": ("nl-NL",  "Europe/Amsterdam",      "nl-NL,nl;q=0.9,en;q=0.8",        52.3676,    4.9041),
    "br": ("pt-BR",  "America/Sao_Paulo",     "pt-BR,pt;q=0.9,en;q=0.8",       -23.5505,  -46.6333),
    "mx": ("es-MX",  "America/Mexico_City",   "es-MX,es;q=0.9,en;q=0.8",        19.4326,  -99.1332),
    "ar": ("es-AR",  "America/Argentina/Buenos_Aires", "es-AR,es;q=0.9,en;q=0.8",-34.6037, -58.3816),
    "in": ("en-IN",  "Asia/Kolkata",          "en-IN,en;q=0.9,hi;q=0.8",        28.6139,   77.2090),
    "pk": ("en-PK",  "Asia/Karachi",          "en-PK,en;q=0.9,ur;q=0.8",        24.8607,   67.0011),
    "bd": ("bn-BD",  "Asia/Dhaka",            "bn-BD,bn;q=0.9,en;q=0.8",        23.8103,   90.4125),
    "id": ("id-ID",  "Asia/Jakarta",          "id-ID,id;q=0.9,en;q=0.8",        -6.2088,  106.8456),
    "ph": ("en-PH",  "Asia/Manila",           "en-PH,en;q=0.9,fil;q=0.8",       14.5995,  120.9842),
    "th": ("th-TH",  "Asia/Bangkok",          "th-TH,th;q=0.9,en;q=0.8",        13.7563,  100.5018),
    "vn": ("vi-VN",  "Asia/Ho_Chi_Minh",      "vi-VN,vi;q=0.9,en;q=0.8",        10.8231,  106.6297),
    "my": ("en-MY",  "Asia/Kuala_Lumpur",     "en-MY,en;q=0.9,ms;q=0.8",         3.1390,  101.6869),
    "sg": ("en-SG",  "Asia/Singapore",        "en-SG,en;q=0.9,zh;q=0.8",         1.3521,  103.8198),
    "jp": ("ja-JP",  "Asia/Tokyo",            "ja-JP,ja;q=0.9,en;q=0.8",        35.6762,  139.6503),
    "kr": ("ko-KR",  "Asia/Seoul",            "ko-KR,ko;q=0.9,en;q=0.8",        37.5665,  126.9780),
    "cn": ("zh-CN",  "Asia/Shanghai",         "zh-CN,zh;q=0.9,en;q=0.8",        31.2304,  121.4737),
    "tw": ("zh-TW",  "Asia/Taipei",           "zh-TW,zh;q=0.9,en;q=0.8",        25.0330,  121.5654),
    "hk": ("zh-HK",  "Asia/Hong_Kong",        "zh-HK,zh;q=0.9,en;q=0.8",        22.3193,  114.1694),
    "ae": ("en-AE",  "Asia/Dubai",            "en-AE,en;q=0.9,ar;q=0.8",        25.2048,   55.2708),
    "sa": ("ar-SA",  "Asia/Riyadh",           "ar-SA,ar;q=0.9,en;q=0.8",        24.7136,   46.6753),
    "tr": ("tr-TR",  "Europe/Istanbul",       "tr-TR,tr;q=0.9,en;q=0.8",        41.0082,   28.9784),
    "il": ("he-IL",  "Asia/Jerusalem",        "he-IL,he;q=0.9,en;q=0.8",        31.7683,   35.2137),
    "eg": ("ar-EG",  "Africa/Cairo",          "ar-EG,ar;q=0.9,en;q=0.8",        30.0444,   31.2357),
    "ng": ("en-NG",  "Africa/Lagos",          "en-NG,en;q=0.9",                  6.5244,    3.3792),
    "za": ("en-ZA",  "Africa/Johannesburg",   "en-ZA,en;q=0.9",                -26.2041,   28.0473),
    "ke": ("en-KE",  "Africa/Nairobi",        "en-KE,en;q=0.9,sw;q=0.8",        -1.2921,   36.8219),
    "ru": ("ru-RU",  "Europe/Moscow",         "ru-RU,ru;q=0.9,en;q=0.8",        55.7558,   37.6173),
    "ua": ("uk-UA",  "Europe/Kyiv",           "uk-UA,uk;q=0.9,en;q=0.8",        50.4501,   30.5234),
    "pl": ("pl-PL",  "Europe/Warsaw",         "pl-PL,pl;q=0.9,en;q=0.8",        52.2297,   21.0122),
    "se": ("sv-SE",  "Europe/Stockholm",      "sv-SE,sv;q=0.9,en;q=0.8",        59.3293,   18.0686),
    "no": ("no-NO",  "Europe/Oslo",           "no-NO,no;q=0.9,en;q=0.8",        59.9139,   10.7522),
    "fi": ("fi-FI",  "Europe/Helsinki",       "fi-FI,fi;q=0.9,en;q=0.8",        60.1699,   24.9384),
    "dk": ("da-DK",  "Europe/Copenhagen",     "da-DK,da;q=0.9,en;q=0.8",        55.6761,   12.5683),
    "be": ("nl-BE",  "Europe/Brussels",       "nl-BE,nl;q=0.9,fr;q=0.8,en;q=0.7",50.8503, 4.3517),
    "ch": ("de-CH",  "Europe/Zurich",         "de-CH,de;q=0.9,en;q=0.8",        47.3769,    8.5417),
    "at": ("de-AT",  "Europe/Vienna",         "de-AT,de;q=0.9,en;q=0.8",        48.2082,   16.3738),
    "ie": ("en-IE",  "Europe/Dublin",         "en-IE,en;q=0.9",                 53.3498,   -6.2603),
    "pt": ("pt-PT",  "Europe/Lisbon",         "pt-PT,pt;q=0.9,en;q=0.8",        38.7223,   -9.1393),
    "nz": ("en-NZ",  "Pacific/Auckland",      "en-NZ,en;q=0.9",                -36.8485,  174.7633),
}


def _resolve_country_geo(country: str) -> Tuple[str, str, str, float, float]:
    """Return (locale, timezone_id, accept_lang, lat, lon) for a 2-letter
    country code. Falls back to US defaults for unknown codes so the
    recorder still works for niche markets — caller can override any
    field explicitly on /start.
    """
    cc = (country or "").strip().lower()[:2]
    return _COUNTRY_GEO.get(cc, _COUNTRY_GEO["us"])


def _detect_mobile_from_ua(ua: str) -> Tuple[bool, str]:
    """Sniff the UA string to figure out if we should run the recorder
    in mobile mode. Returns (is_mobile, os_kind).

    `os_kind` ∈ {android, ios, ipados, windows, macos, linux}.
    """
    u = (ua or "").lower()
    if "iphone" in u or "ios " in u or " ios)" in u:
        return True, "ios"
    if "ipad" in u:
        # iPadOS 13+ UA looks like macOS — but Playwright treats it as
        # tablet either way. Mark as mobile to enable touch.
        return True, "ipados"
    if "android" in u:
        return True, "android"
    if "mobile" in u and "windows" not in u:
        return True, "android"  # generic mobile fallback
    if "windows" in u:
        return False, "windows"
    if "mac os" in u or "macintosh" in u:
        return False, "macos"
    if "linux" in u:
        return False, "linux"
    return False, "windows"


def _resolve_device_viewport(
    explicit_viewport: Optional[Tuple[int, int]],
    is_mobile: bool,
    os_kind: str,
) -> Tuple[Tuple[int, int], float]:
    """Pick a realistic (viewport, device_scale_factor) for the device.

    If the caller passed a non-default viewport we keep it (customer
    may want a specific dimension). Otherwise we map os_kind →
    common device size.
    """
    if explicit_viewport and explicit_viewport != DEFAULT_VIEWPORT:
        # Customer pinned a specific size — respect it but pick a
        # sensible DSF.
        if is_mobile:
            return explicit_viewport, 3.0
        return explicit_viewport, 1.0

    if is_mobile:
        if os_kind == "ios":
            # iPhone 14/15 Pro logical size
            return (393, 852), 3.0
        if os_kind == "ipados":
            # iPad Pro 11" landscape — treat as tablet
            return (1024, 1366), 2.0
        # Android default → Pixel 8 / Galaxy S24 mid-size
        return (412, 915), 2.625
    # Desktop default — Full HD; will work for most monitors
    return (1920, 1080), 1.0


def _resolve_template_value(
    sess: "RecorderSession",
    template: str,
) -> str:
    """Resolve a `{{name}}` template using:
       1. Built-in dynamic generators (random_email, today, uuid, etc.)
       2. sess.sample_row (Excel column lookup, case-insensitive)
       3. Fallback: return the literal template unchanged

    Designed so multiple templates can appear in one string, e.g.
    `"user_{{counter}}_{{random_alnum:6}}@example.com"`.

    Supported built-ins:
      {{random_email}}             → uniq lowercase email at example.com
      {{random_email:gmail.com}}   → at a custom domain
      {{random_alnum:N}}           → N-char lowercase alnum
      {{random_digits:N}}          → N digits (good for OTP-style)
      {{random_phone}}             → 10-digit US-style "5552223333"
      {{random_phone:UK}}          → country-aware (UK/US/IN/PK/DE)
      {{uuid}}                     → full uuid4
      {{uuid_short}}               → first 8 hex chars
      {{counter}}                  → per-session incrementing int (1,2,…)
      {{today}}                    → YYYY-MM-DD
      {{today:DD/MM/YYYY}}         → custom strftime fmt
      {{now}}                      → ISO timestamp
      {{epoch}}                    → unix seconds
      {{first_name}}, {{last_name}}, {{full_name}} → from name pool
    """
    raw = (template or "").strip()
    if not raw:
        return ""
    # Strip wrapping braces if caller passed e.g. "{{random_email}}"
    if raw.startswith("{{") and raw.endswith("}}"):
        raw = raw[2:-2].strip()
    name, _, arg = raw.partition(":")
    name = name.strip().lower()
    arg = arg.strip()

    if name in ("random_email", "rand_email", "email_random"):
        domain = arg or "example.com"
        local = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        return f"u{local}@{domain}"
    if name in ("random_alnum", "rand_alnum"):
        n = max(1, min(int(arg or "8"), 64))
        return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))
    if name in ("random_digits", "rand_digits"):
        n = max(1, min(int(arg or "6"), 32))
        return "".join(secrets.choice(string.digits) for _ in range(n))
    if name in ("random_phone", "rand_phone", "phone"):
        cc = (arg or "us").lower()
        def d(n: int) -> str:
            return "".join(secrets.choice(string.digits) for _ in range(n))
        if cc == "uk":
            return "07" + d(9)
        if cc == "in":
            return "9" + d(9)
        if cc == "pk":
            return "03" + d(9)
        if cc == "de":
            return "01" + d(9)
        # US default: never start area-code with 0/1, never 555-01xx (reserved)
        area = secrets.choice([str(x) for x in range(200, 999)])
        exch = secrets.choice([str(x) for x in range(200, 999)])
        sub = d(4)
        return f"{area}{exch}{sub}"
    if name in ("uuid",):
        return str(uuid.uuid4())
    if name in ("uuid_short", "shortid"):
        return uuid.uuid4().hex[:8]
    if name in ("counter", "n"):
        sess.template_counter = (sess.template_counter or 0) + 1
        return str(sess.template_counter)
    if name in ("today", "date"):
        fmt = arg or "%Y-%m-%d"
        # Common human shorthand → strftime conversion
        fmt = (fmt.replace("YYYY", "%Y").replace("YY", "%y")
                  .replace("MM", "%m").replace("DD", "%d")
                  .replace("HH", "%H").replace("mm", "%M").replace("SS", "%S"))
        return datetime.now().strftime(fmt)
    if name in ("now", "iso"):
        return datetime.now(timezone.utc).isoformat()
    if name in ("epoch", "ts"):
        return str(int(time.time()))
    if name in ("first_name", "firstname"):
        return secrets.choice(_FIRST_NAMES)
    if name in ("last_name", "lastname"):
        return secrets.choice(_LAST_NAMES)
    if name in ("full_name", "fullname", "name"):
        return f"{secrets.choice(_FIRST_NAMES)} {secrets.choice(_LAST_NAMES)}"

    # Not a built-in → try sample_row (Excel column) lookup
    if sess.sample_row:
        v = sess.sample_row.get(name)
        if v is not None and str(v).strip():
            return str(v)
    # Last resort: return the original wrapped form so the recorded
    # JSON keeps `{{name}}` for runtime RUT substitution (it knows
    # how to resolve from the real lead row).
    return "{{" + name + "}}"


_FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Elizabeth", "David", "Barbara", "Richard",
    "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
    "Daniel", "Emily", "Matthew", "Anna", "Christopher", "Olivia",
    "Andrew", "Sophia", "Joshua", "Mia",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson",
]


def resolve_templates_in_text(sess: "RecorderSession", text: str) -> str:
    """Replace ALL `{{...}}` occurrences in `text` with resolved
    values. Multi-template strings work — e.g.
    `"user_{{counter}}_{{random_alnum:6}}@x.com"`.
    """
    if not text or "{{" not in text:
        return text
    import re as _re
    return _re.sub(
        r"\{\{\s*([^{}]+?)\s*\}\}",
        lambda m: _resolve_template_value(sess, m.group(1)),
        text,
    )


# ── Session state ───────────────────────────────────────────────────────
@dataclass
class RecorderSession:
    session_id: str
    user_id: str
    url: str
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    headers: List[str] = field(default_factory=list)  # Excel column names for form-fill binding
    proxy_provider_id: str = ""
    country: str = ""
    device_type: str = "auto"
    # ── 2026-05 ──
    # Sample data row used DURING recording so the form fills with
    # realistic values (lets the user proceed past form validation
    # and record steps on the page that comes AFTER submit). At
    # replay time the RUT engine substitutes the actual lead row.
    sample_row: Dict[str, Any] = field(default_factory=dict)
    viewport: Tuple[int, int] = DEFAULT_VIEWPORT
    # ── 2026-01 (mobile fingerprint coherence) ───────────────────────
    # Device emulation knobs — were previously HARDCODED at
    # `is_mobile=True, has_touch=True, dsf=2, locale=en-US,
    # timezone=America/New_York`. Now driven by what the frontend
    # passes on /start so the recorder browser presents to the
    # advertiser the SAME fingerprint the eventual RUT job will
    # present. Without this, advertisers detect the mismatch
    # (e.g. UA says Windows but maxTouchPoints=5) and either fail
    # the offer or redirect to "Not available in your region".
    is_mobile: bool = True
    has_touch: bool = True
    device_scale_factor: float = 2.0
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    accept_language: str = "en-US,en;q=0.9"
    os_kind: str = "android"     # android | ios | windows | macos | linux
    geo_lat: float = 40.7128
    geo_lon: float = -74.0060
    # Counter that {{counter}} dynamic template increments per use.
    template_counter: int = 0
    steps: List[Dict[str, Any]] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    target_screenshot_path: Optional[str] = None
    final_url: Optional[str] = None
    final_text_snippet: Optional[str] = None
    # Connection lifecycle: starting | ready | error | stopped
    state: str = "starting"
    error_message: str = ""
    ready_at: Optional[float] = None
    # Playwright handles (set once state == "ready")
    playwright: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    # ── 2026-01 (multi-tab support) ─────────────────────────────────
    # Track ALL pages opened in this browser context (initial page +
    # any popup / target="_blank" / window.open tabs the offer page
    # spawns). `pages` is the live list of open Playwright Page
    # objects in the order they were created. `active_page_index`
    # points to the one currently rendered by /screenshot and acted
    # on by /click, /type, etc. — i.e. `sess.page` is always
    # `sess.pages[active_page_index]` (when non-empty).
    #
    # Without this the recorder could only see the FIRST page; clicking
    # a button that opened a new tab (e.g. CPA offer → reward redirect)
    # caused the new page to be invisible to the user and its steps
    # un-recordable. See `_attach_page_listeners` + `switch_tab`.
    pages: List[Any] = field(default_factory=list)
    active_page_index: int = 0
    # ── 2026-06 (v2.1.74) — JS dialog capture ──
    # When the live page fires alert() / confirm() / prompt() Playwright's
    # default is to auto-DISMISS so they never appear to the user (and the
    # user can't choose to accept/dismiss/type a response). We override
    # via page.on("dialog") to PARK the dialog handle in pending_dialog
    # until the user (or a recorded `accept_dialog` / `dismiss_dialog`
    # step) explicitly resolves it. Operator UI polls
    # GET /api/visual-recorder/{sid}/dialog and shows an in-app banner
    # with [Accept] [Dismiss] (+ prompt-text field if type == "prompt")
    # and POSTs the answer to /dialog/answer which also records the
    # decision as a step so replay reproduces the same choice.
    pending_dialog: Optional[Dict[str, Any]] = None
    # Lock to serialize actions on the same browser
    lock: Optional[asyncio.Lock] = None
    # Background startup task (so we can cancel it on stop)
    startup_task: Any = None
    # 2026-01 (additive): live progress feed for live_test. Polled by the
    # frontend at ~400ms intervals to show real-time step execution
    # ("step #5 click button.submit — running…", "step #5 ok in 230ms").
    # Reset at the start of every live_test invocation.
    live_progress: List[Dict[str, Any]] = field(default_factory=list)
    live_progress_running: bool = False
    live_progress_started_at: Optional[float] = None
    live_progress_finished_at: Optional[float] = None
    # ── 2026-05: Auto-fix history for Undo support ──
    # Each entry: {kind, at_step, summary, applied_at, snapshot_before}
    # where snapshot_before is a deep-copy of `steps` BEFORE that fix
    # was applied. Capped at 20 entries (LRU) so memory stays bounded
    # even for sessions where the user spams Auto-fix-all repeatedly.
    fix_history: List[Dict[str, Any]] = field(default_factory=list)
    # When True, append short settle waits after each recorded action step.
    auto_insert_waits: bool = False

    def touch(self):
        self.last_activity = time.time()

    def append_step(self, step: Optional[Dict[str, Any]], *, allow_auto_waits: bool = True) -> None:
        """Append a recorded step and optionally auto-insert settle waits."""
        if not step:
            return
        self.steps.append(step)
        if not allow_auto_waits or not self.auto_insert_waits:
            return
        if step.get("source") == "auto_wait":
            return
        for wait_step in _auto_waits_after_action(str(step.get("action") or "")):
            auto = dict(wait_step)
            auto["source"] = "auto_wait"
            auto.setdefault("optional", True)
            self.steps.append(auto)


# Global registry
_SESSIONS: Dict[str, RecorderSession] = {}
_REAPER_TASK: Optional[asyncio.Task] = None


# ── Lifecycle ───────────────────────────────────────────────────────────
async def start_session(
    user_id: str,
    url: str,
    proxy: Optional[str] = None,
    user_agent: Optional[str] = None,
    headers: Optional[List[str]] = None,
    sample_row: Optional[Dict[str, Any]] = None,
    # ── 2026-01 (mobile fingerprint coherence) ──
    # Optional device hints from frontend. If not provided we sniff
    # the UA. This is what fixes the "advertiser sees mismatched
    # mobile/desktop fingerprint" problem — the recorder browser
    # now presents EXACTLY the device a real customer would.
    device_type: str = "auto",     # auto | desktop | mobile | tablet
    country: str = "",             # 2-letter lowercase → drives locale + tz + geo
    locale: str = "",              # explicit override
    timezone_id: str = "",         # explicit override
    accept_language: str = "",     # explicit override
    viewport_w: int = 0,
    viewport_h: int = 0,
    device_scale_factor: float = 0.0,
    auto_insert_waits: bool = False,
    proxy_provider_id: str = "",
) -> RecorderSession:
    """Create a session and kick off browser launch in the background.

    Returns IMMEDIATELY with state="starting". The caller (frontend) should
    poll `/state` until `state` becomes "ready" or "error". This avoids
    tying up a request thread for 30+ seconds while a slow residential
    proxy negotiates a TCP tunnel.

    `sample_row` (optional): one dict of Excel column → value used to
    populate form inputs DURING recording so the user can proceed past
    form validation and record steps on the post-submit page. At RUT
    replay time the actual lead row substitutes via `{{column}}`.
    """
    if len(_SESSIONS) >= MAX_CONCURRENT_SESSIONS:
        # Reap before refusing
        await _reap_idle()
        if len(_SESSIONS) >= MAX_CONCURRENT_SESSIONS:
            raise RuntimeError(
                f"Max {MAX_CONCURRENT_SESSIONS} concurrent recorder sessions running. "
                "Wait for one to free or stop yours first."
            )

    sid = str(uuid.uuid4())
    # Normalise sample_row keys to lowercase for case-insensitive lookups
    norm_sample: Dict[str, Any] = {}
    if sample_row:
        for k, v in sample_row.items():
            if k is None:
                continue
            norm_sample[str(k).strip().lower()] = v

    # ── 2026-01: Resolve device + geo BEFORE creating the session ──
    final_ua = user_agent or (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    # Device choice — explicit overrides UA sniffing
    dt = (device_type or "auto").strip().lower()
    if dt in ("mobile", "phone"):
        is_mobile = True
        _, sniffed_os = _detect_mobile_from_ua(final_ua)
        os_kind = sniffed_os if sniffed_os in ("ios", "ipados", "android") else "android"
    elif dt in ("desktop", "pc"):
        is_mobile = False
        _, sniffed_os = _detect_mobile_from_ua(final_ua)
        os_kind = sniffed_os if sniffed_os in ("windows", "macos", "linux") else "windows"
    elif dt == "tablet":
        is_mobile = True
        os_kind = "ipados"
    else:
        # Auto: sniff UA
        is_mobile, os_kind = _detect_mobile_from_ua(final_ua)

    # Geo: explicit fields override country-derived defaults
    (geo_locale, geo_tz, geo_accept, geo_lat, geo_lon) = _resolve_country_geo(country)
    final_locale = locale or geo_locale
    final_tz = timezone_id or geo_tz
    final_accept = accept_language or geo_accept

    # Viewport + DSF
    explicit_vp: Optional[Tuple[int, int]] = None
    if viewport_w > 0 and viewport_h > 0:
        explicit_vp = (int(viewport_w), int(viewport_h))
    (final_vp, default_dsf) = _resolve_device_viewport(explicit_vp, is_mobile, os_kind)
    final_dsf = device_scale_factor if device_scale_factor > 0 else default_dsf

    sess = RecorderSession(
        session_id=sid,
        user_id=user_id,
        url=url,
        proxy=proxy,
        user_agent=final_ua,
        headers=headers or [],
        sample_row=norm_sample,
        viewport=final_vp,
        is_mobile=is_mobile,
        has_touch=is_mobile,
        device_scale_factor=final_dsf,
        locale=final_locale,
        timezone_id=final_tz,
        accept_language=final_accept,
        os_kind=os_kind,
        geo_lat=geo_lat,
        geo_lon=geo_lon,
        auto_insert_waits=bool(auto_insert_waits),
        proxy_provider_id=(proxy_provider_id or "").strip(),
        country=(country or "").strip().lower()[:2],
        device_type=(device_type or "auto").strip().lower(),
    )
    sess.lock = asyncio.Lock()
    sess.state = "starting"

    _SESSIONS[sid] = sess
    _ensure_reaper()

    # Fire-and-forget background init. Wrapped with overall timeout so a
    # dead proxy can never hang us forever.
    sess.startup_task = asyncio.create_task(_init_browser_bg(sess))
    logger.info(
        f"Visual recorder session created (starting): {sid} "
        f"(url={url[:60]}, mobile={is_mobile}, os={os_kind}, "
        f"vp={final_vp}, locale={final_locale}, tz={final_tz})"
    )
    return sess


async def _init_browser_bg(sess: RecorderSession) -> None:
    """Background task: launch Playwright + open URL with strict timeout.

    On success: state="ready". On any failure / timeout: state="error" with
    error_message set, and Playwright handles cleaned up.
    """
    sid = sess.session_id
    try:
        await asyncio.wait_for(_init_browser_inner(sess), timeout=STARTUP_TIMEOUT_S)
        sess.state = "ready"
        sess.ready_at = time.time()
        sess.touch()
        logger.info(f"Visual recorder session ready: {sid}")
    except asyncio.TimeoutError:
        sess.state = "error"
        sess.error_message = (
            f"Connection timed out after {STARTUP_TIMEOUT_S}s. "
            "The proxy or target URL is too slow / unreachable. "
            "Try a different proxy or remove the proxy field."
        )
        logger.warning(f"Visual recorder startup timeout: {sid}")
        await _cleanup_handles(sess)
    except Exception as e:
        sess.state = "error"
        sess.error_message = f"Startup failed: {type(e).__name__}: {str(e)[:240]}"
        logger.warning(f"Visual recorder startup failed {sid}: {e}")
        await _cleanup_handles(sess)

# ── Multi-tab helpers (2026-01) ─────────────────────────────────────────
# These give the Visual Recorder real "browser with tabs" semantics so
# offer pages that open new tabs (target="_blank", window.open, etc.) are
# captured + recordable instead of disappearing into the background.

_PAGE_INIT_SCRIPT = """
Object.defineProperty(document.fonts, 'ready', {
    get: () => Promise.resolve(),
    configurable: true
});
"""


def _attach_dialog_listener(sess: "RecorderSession", target_page: Any) -> None:
    """v2.1.74 — Capture native JS dialogs (alert/confirm/prompt/beforeunload)
    that the offer page fires. Playwright's default is to auto-dismiss
    them so the operator never even sees the popup. We park the dialog
    in `sess.pending_dialog` and wait for the operator to call
    `POST /api/visual-recorder/{sid}/dialog/answer` (which then resolves
    the Playwright Dialog handle with accept/dismiss + optional prompt
    text). The decision is also recorded as a step so RUT replay
    reproduces the same answer.

    Idempotent — uses a per-page flag so repeat invocations on the same
    page don't stack listeners.
    """
    if target_page is None:
        return
    if getattr(target_page, "_kx_dialog_attached", False):
        return
    try:
        setattr(target_page, "_kx_dialog_attached", True)
    except Exception:
        pass

    def _on_dialog(dialog: Any) -> None:
        # Sync handler — Playwright supports both sync + async, sync is
        # safer here because we don't want to await inside the event
        # dispatch (would race with other concurrent dialogs).
        try:
            sess.pending_dialog = {
                "type": getattr(dialog, "type", "alert"),
                "message": (getattr(dialog, "message", "") or "")[:2000],
                "default_value": (getattr(dialog, "default_value", "") or "")[:500],
                "page_url": (target_page.url or "")[:300],
                "_handle": dialog,  # python ref; serialized away by /dialog GET
                "captured_at": time.time(),
            }
            logger.info(
                f"[vr {sess.session_id}] dialog captured: "
                f"type={sess.pending_dialog['type']!r} "
                f"msg={sess.pending_dialog['message'][:80]!r}"
            )
        except Exception as _e:
            logger.debug(f"[vr {sess.session_id}] dialog capture err: {_e}")
            # Fall back to dismissing so the page doesn't hang
            try:
                asyncio.create_task(dialog.dismiss())
            except Exception:
                pass

    try:
        target_page.on("dialog", _on_dialog)
    except Exception as _e:
        logger.debug(f"[vr {sess.session_id}] dialog listener attach err: {_e}")


def _attach_page_listeners(sess: "RecorderSession") -> None:
    """Wire up the context-level "page" event so any popup / new tab
    that the live page spawns is tracked AND auto-promoted to the
    active tab. Idempotent — safe to call multiple times on the same
    session (Playwright's event emitter dedups listeners by identity
    but we use a flag for clarity).
    """
    if getattr(sess, "_page_listener_attached", False):
        return
    if sess.context is None:
        return

    async def _on_new_page(new_page: Any) -> None:
        try:
            # Best-effort: block fonts on new page same as initial
            try:
                await new_page.route(
                    "**/*.{woff,woff2,ttf,otf,eot}",
                    lambda route: route.abort(),
                )
            except Exception:
                pass
            try:
                await new_page.add_init_script(_PAGE_INIT_SCRIPT)
            except Exception:
                pass

            # v2.1.74 — wire up JS dialog capture for popups
            try:
                _attach_dialog_listener(sess, new_page)
            except Exception as _de:
                logger.debug(f"[vr {sess.session_id}] dialog wire on new page failed: {_de}")

            # Wait briefly for the page to load content. Don't block
            # too long — some popups never fire `load` (ad iframes,
            # tracking pixels) but DO render visible content quickly.
            try:
                await new_page.wait_for_load_state(
                    "domcontentloaded", timeout=8000
                )
            except Exception:
                pass

            # Register + auto-switch ONLY if not already known (the
            # context may emit duplicate events under proxy retries).
            if new_page not in sess.pages:
                sess.pages.append(new_page)
                sess.active_page_index = len(sess.pages) - 1
                sess.page = new_page
                logger.info(
                    f"[vr {sess.session_id}] new tab #{sess.active_page_index} "
                    f"opened — auto-switched (url={(new_page.url or '')[:80]})"
                )

            # Also clean up on close so we don't keep stale handles
            async def _on_close(_p: Any = new_page) -> None:
                try:
                    if _p in sess.pages:
                        idx = sess.pages.index(_p)
                        sess.pages.pop(idx)
                        # If we just closed the active page, fall back
                        # to the last remaining tab (or to None).
                        if not sess.pages:
                            sess.page = None
                            sess.active_page_index = 0
                        else:
                            sess.active_page_index = min(
                                sess.active_page_index, len(sess.pages) - 1
                            )
                            sess.page = sess.pages[sess.active_page_index]
                        logger.info(
                            f"[vr {sess.session_id}] tab closed — "
                            f"now {len(sess.pages)} tab(s), active={sess.active_page_index}"
                        )
                except Exception:
                    pass

            try:
                new_page.on("close", lambda _p: asyncio.create_task(_on_close()))
            except Exception:
                pass
        except Exception as e:
            logger.warning(
                f"[vr {sess.session_id}] new-page listener failed: {e}"
            )

    try:
        sess.context.on(
            "page", lambda new_page: asyncio.create_task(_on_new_page(new_page))
        )
        sess._page_listener_attached = True  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning(f"[vr {sess.session_id}] could not attach page listener: {e}")


async def list_tabs(sess: "RecorderSession") -> List[Dict[str, Any]]:
    """Return one entry per open page in the recorder's browser context.
    UI uses this to render the tabs strip above the live preview.
    """
    sess.touch()
    out: List[Dict[str, Any]] = []
    if not sess.pages:
        return out
    for idx, p in enumerate(sess.pages):
        url = ""
        title = ""
        try:
            url = p.url or ""
        except Exception:
            url = ""
        try:
            # `page.title()` is async — keep this loop's outer call
            # async so titles populate too. Wrapped in try to skip
            # the (rare) closed-page case mid-iteration.
            title = await asyncio.wait_for(p.title(), timeout=1.0)
        except Exception:
            title = ""
        out.append({
            "index": idx,
            "url": url,
            "title": title or url,
            "is_active": idx == sess.active_page_index,
        })
    return out


async def switch_tab(sess: "RecorderSession", index: int) -> Dict[str, Any]:
    """Make `sess.pages[index]` the active tab — all subsequent
    /screenshot, /click, /type, etc. calls operate on it.

    2026-06 — When called during active recording (state=="ready" and
    `record_step=True`), this ALSO appends a `switch_tab` step to the
    recipe so the RUT replay can faithfully reproduce the operator's
    "go back to the previous tab to start the next deal" navigation.
    Without this, the auto-recorded recipe would auto-follow new tabs
    on each click (RUT's new-tab detection) but never return to a
    prior tab, breaking multi-deal workflows on the same landing page.

    Pure additive — the API endpoint passes `record_step=True` by
    default. Set False (e.g. in tests) to switch without recording.
    """
    sess.touch()
    if not sess.pages:
        return {"ok": False, "error": "no_tabs"}
    if index < 0 or index >= len(sess.pages):
        return {"ok": False, "error": "index_out_of_range", "total": len(sess.pages)}
    prev_index = int(getattr(sess, "active_page_index", 0) or 0)
    async with sess.lock:
        sess.active_page_index = index
        sess.page = sess.pages[index]
        # Bring to front so any subsequent DevTools / screenshot call
        # gets the freshest paint (Playwright headless still benefits).
        try:
            await sess.page.bring_to_front()
        except Exception:
            pass
    url = ""
    try:
        url = sess.page.url or ""
    except Exception:
        pass

    # 2026-06 — Record the manual tab switch as a step so RUT can
    # faithfully replay "back to previous tab". Only record when:
    #   • The session is in "ready" state (i.e. live recording is on)
    #   • The target index is different from the previous one (no-op
    #     switches don't need a step)
    #   • The last step isn't already a switch_tab to the same index
    #     (defensive de-dup; the UI polls /tabs every 1.5s and clicks
    #     can briefly stack)
    try:
        is_recording = (getattr(sess, "state", "") == "ready")
        if is_recording and index != prev_index:
            last = sess.steps[-1] if sess.steps else None
            if not (isinstance(last, dict)
                    and last.get("action") == "switch_tab"
                    and int(last.get("index") or -1) == int(index)):
                sess.append_step({
                    "action": "switch_tab",
                    "index": int(index),
                    # URL kept for human-readable diagnostics + a safer
                    # fallback during replay (see real_user_traffic
                    # handler).
                    "url": url[:200] if url else "",
                    "source": "manual",
                })
    except Exception as _rec_e:
        # NEVER let recording-side bookkeeping break the actual tab
        # switch — the switch already succeeded above; this is purely
        # informational.
        logger.warning(
            f"[vr {sess.session_id}] switch_tab step append failed: {_rec_e}"
        )

    logger.info(
        f"[vr {sess.session_id}] switched to tab #{index} (url={url[:80]})"
    )
    return {"ok": True, "active_index": index, "url": url, "total": len(sess.pages)}


async def close_tab(sess: "RecorderSession", index: int) -> Dict[str, Any]:
    """Close the page at `index` and fall back to the previous tab as
    active (if any).
    """
    sess.touch()
    if not sess.pages:
        return {"ok": False, "error": "no_tabs"}
    if index < 0 or index >= len(sess.pages):
        return {"ok": False, "error": "index_out_of_range", "total": len(sess.pages)}
    if len(sess.pages) == 1:
        # Refuse to close the last tab — would leave the recorder
        # blind. Frontend should hide the close button when total=1.
        return {"ok": False, "error": "cannot_close_last_tab"}
    page = sess.pages[index]
    try:
        await page.close()
    except Exception:
        pass
    # The page's own `close` event handler updates sess.pages /
    # active_page_index. Wait a beat so the listener fires first.
    await asyncio.sleep(0.05)
    return {
        "ok": True,
        "active_index": sess.active_page_index,
        "total": len(sess.pages),
    }




async def _init_browser_inner(sess: RecorderSession) -> None:
    """The actual launch sequence. Wrapped by `_init_browser_bg` for timeout."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    sess.playwright = pw

    launch_opts: Dict[str, Any] = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-renderer-backgrounding",
        ],
        "timeout": LAUNCH_TIMEOUT_S * 1000,  # Playwright launch budget
    }
    if sess.proxy:
        # 2026-05: Use full proxy parser so user:pass@host:port style
        # residential proxies (proxy-jet, brightdata, etc.) actually
        # authenticate. Previously credentials were silently dropped and
        # the recorder showed a blank preview because the proxy refused
        # the tunnel.
        parsed_proxy = _parse_proxy_for_playwright(sess.proxy)
        if parsed_proxy:
            launch_opts["proxy"] = parsed_proxy
        else:
            logger.warning(
                f"Visual recorder: could not parse proxy '{sess.proxy[:60]}'. "
                "Falling back to no-proxy mode."
            )

    sess.browser = await pw.chromium.launch(**launch_opts)
    # ── 2026-01: Dynamic device + geo + stealth ──
    # Was previously hardcoded to mobile+en-US+NY which leaked
    # obvious UA/Platform/timezone mismatches → advertisers detected
    # the recorder. Now driven by what frontend passed on /start so
    # the recorder browser presents EXACTLY the fingerprint the
    # eventual RUT job will use.
    sess.context = await sess.browser.new_context(
        viewport={"width": sess.viewport[0], "height": sess.viewport[1]},
        user_agent=sess.user_agent,
        device_scale_factor=sess.device_scale_factor,
        is_mobile=sess.is_mobile,
        has_touch=sess.has_touch,
        locale=sess.locale,
        timezone_id=sess.timezone_id,
        extra_http_headers={
            "Accept-Language": sess.accept_language,
            # Client Hints — most modern offers check these. Without
            # them a "mobile" UA browser leaks `Sec-CH-UA-Mobile: ?0`
            # which is an instant tell.
            "Sec-CH-UA-Mobile": "?1" if sess.is_mobile else "?0",
            "Sec-CH-UA-Platform": (
                '"iOS"' if sess.os_kind == "ios" else
                '"Android"' if sess.os_kind == "android" else
                '"Windows"' if sess.os_kind == "windows" else
                '"macOS"' if sess.os_kind == "macos" else
                '"Linux"'
            ),
        },
    )

    # ── Inject full stealth/anti-detect script (~35 patches) ──
    # Pulls in the SAME `_build_stealth_script` that RUT and the
    # browser-profile launcher use, so every layer aligns:
    #   • navigator.userAgentData with correct mobile + platform
    #   • navigator.maxTouchPoints (5 mobile, 0 desktop)
    #   • navigator.platform leak fixed (iPhone / Linux armv8l)
    #   • screen.orientation portrait-primary on mobile
    #   • window.orientation = 0 on mobile
    #   • Canvas / WebGL / Audio fingerprint noise
    #   • webdriver flag hidden
    #   • chrome.runtime exposed (real Chrome)
    #   • plugins[] / mimeTypes[] realistic
    # Without this the recorder Chromium leaked all the obvious
    # automation tells even though the UA looked perfect.
    try:
        from real_user_traffic import _build_stealth_script, _fingerprint_from_ua
        # Build the full fingerprint dict from the UA (handles platform,
        # webgl_vendor, webgl_renderer, hardware_concurrency, etc.)
        fp = _fingerprint_from_ua(sess.user_agent)
        # Override viewport / DSF / mobile flags with session values
        # (frontend may have overridden defaults).
        fp["viewport"] = {"width": sess.viewport[0], "height": sess.viewport[1]}
        fp["device_scale_factor"] = sess.device_scale_factor
        fp["is_mobile"] = sess.is_mobile
        fp["has_touch"] = sess.has_touch
        fp["os"] = sess.os_kind if sess.os_kind in ("android", "ios", "windows", "macos", "linux") else fp.get("os", "windows")
        geo = {
            "locale": sess.locale,
            "timezone": sess.timezone_id,
            "accept_language": sess.accept_language,
            "lat": sess.geo_lat,
            "lon": sess.geo_lon,
        }
        stealth_js = _build_stealth_script(fp, geo)
        await sess.context.add_init_script(stealth_js)
        # Best-effort: also spoof geolocation if the offer requests it.
        try:
            await sess.context.set_geolocation(
                {"latitude": sess.geo_lat, "longitude": sess.geo_lon, "accuracy": 50}
            )
            await sess.context.grant_permissions(["geolocation"])
        except Exception:
            pass
    except Exception as e:
        logger.warning(
            f"[vr {sess.session_id}] stealth-script injection failed ({e}) "
            "— falling back to minimal webdriver hide"
        )
        await sess.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

    sess.page = await sess.context.new_page()
    sess.pages = [sess.page]
    sess.active_page_index = 0

    # 2026-01 (multi-tab) — Listen for popups / new tabs that the offer
    # page opens (target="_blank", window.open, anchor with no target
    # attr but `rel="noopener"`, etc). Whenever a new Page appears in
    # this context we:
    #   1) Wait briefly for it to reach `domcontentloaded` so the user
    #      sees content (not a blank canvas) when they switch to it.
    #   2) Append it to `sess.pages` and AUTO-SWITCH `sess.page` to it.
    #      Auto-switching matches the typical user mental model — they
    #      just clicked a CTA, the "new tab" IS the next thing to
    #      interact with. They can manually switch back via the tabs
    #      bar if they need the original.
    #   3) Re-attach the font-blocking init script so screenshot calls
    #      on this new page also don't hang waiting for webfonts.
    _attach_page_listeners(sess)
    # v2.1.74 — also wire dialog capture on the initial page
    try:
        _attach_dialog_listener(sess, sess.page)
    except Exception as _de:
        logger.debug(f"[vr {sess.session_id}] dialog wire on initial page failed: {_de}")

    # Block font files to prevent font loading delays
    # This prevents Playwright screenshot from hanging on fonts.ready
    await sess.page.route("**/*.{woff,woff2,ttf,otf,eot}", lambda route: route.abort())

    # Override document.fonts.ready to prevent screenshot hanging
    # This must be done via page.add_init_script so it runs on every page load
    await sess.page.add_init_script("""
        Object.defineProperty(document.fonts, 'ready', {
            get: () => Promise.resolve(),
            configurable: true
        });
    """)

    # 2026-01 — initial auto wait_for_load(60000) + wait(2000) removed
    # per user request. The runtime engine's own page.goto(target_url,
    # wait_until="domcontentloaded") already ensures the page is loaded
    # before playback begins; pre-pending these two steps to the recorded
    # JSON only burned watchdog seconds without adding reliability.
    # Users who want an explicit settle delay can insert a wait step
    # from the recorder UI right after starting.

    # Navigate — proxy-friendly strategy:
    # 1. First try `domcontentloaded` with a SHORT timeout so the user
    #    gets a visible page within a few seconds even on slow
    #    residential proxies (was previously blocking on networkidle
    #    for the full 35s — looked like "page never loaded" to the
    #    customer).
    # 2. Then optionally chase `load` in the background (best-effort)
    #    so analytics scripts finish without blocking interaction.
    # ── 2026-05 (proxy fix) ──
    try:
        await sess.page.goto(sess.url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    except Exception as e:
        logger.warning(f"Initial goto (domcontentloaded) failed for {sess.session_id}: {e}")
        # Last-resort: a bare `commit` so at least the URL changes and
        # the next /screenshot poll returns SOMETHING the user can see.
        try:
            await sess.page.goto(sess.url, wait_until="commit", timeout=GOTO_TIMEOUT_MS)
        except Exception as e2:
            logger.warning(f"Fallback goto also failed for {sess.session_id}: {e2}")

    # Best-effort: wait for `load` for up to 6s more so the page is
    # interactive. This runs AFTER domcontentloaded so a stuck
    # advertiser tracker can't block the initial preview.
    try:
        await sess.page.wait_for_load_state("load", timeout=6000)
    except Exception:
        pass


async def _cleanup_handles(sess: RecorderSession) -> None:
    """Close any partially-opened Playwright handles. Safe to call twice."""
    try:
        if sess.browser:
            await sess.browser.close()
    except Exception:
        pass
    try:
        if sess.playwright:
            await sess.playwright.stop()
    except Exception:
        pass
    sess.browser = None
    sess.context = None
    sess.page = None
    sess.pages = []
    sess.active_page_index = 0
    sess.playwright = None


async def stop_session(session_id: str) -> bool:
    sess = _SESSIONS.pop(session_id, None)
    if not sess:
        return False
    # Cancel pending startup if it's still running
    try:
        if sess.startup_task and not sess.startup_task.done():
            sess.startup_task.cancel()
    except Exception:
        pass
    await _cleanup_handles(sess)
    sess.state = "stopped"
    logger.info(f"Visual recorder session stopped: {session_id}")
    return True


def get_session(session_id: str, user_id: str) -> RecorderSession:
    sess = _SESSIONS.get(session_id)
    if not sess or sess.user_id != user_id:
        raise KeyError("Session not found")
    return sess


def list_user_sessions(user_id: str) -> List[Dict[str, Any]]:
    """Return metadata for all active sessions belonging to this user.
    Used by the UI to render the "Active Sessions" panel so the user can
    see which recorders are running, switch between them, or stop the
    ones they no longer need (frees up slots toward the
    MAX_CONCURRENT_SESSIONS=5 cap).
    """
    now = time.time()
    out: List[Dict[str, Any]] = []
    for sid, s in _SESSIONS.items():
        if s.user_id != user_id:
            continue
        # Try to read current page url (cheap, no awaits). Falls back to
        # the initial session URL if the live page isn't available yet.
        page_url = ""
        page_title = ""
        try:
            if s.page is not None:
                page_url = s.page.url or ""
        except Exception:
            page_url = ""
        out.append({
            "session_id": sid,
            "url": s.url,
            "current_url": page_url or s.url,
            "title": page_title,
            "state": s.state,
            "error_message": s.error_message or "",
            "step_count": len(s.steps),
            "elapsed_seconds": int(now - s.created_at),
            "idle_seconds": int(now - s.last_activity),
            "viewport": {"width": s.viewport[0], "height": s.viewport[1]},
        })
    # Newest first so the most recent session is on top.
    out.sort(key=lambda x: x["elapsed_seconds"])
    return out


def get_global_session_stats() -> Dict[str, int]:
    """Lightweight global counters so the UI can show "X/5 in use"."""
    return {
        "total_running": len(_SESSIONS),
        "max_concurrent": MAX_CONCURRENT_SESSIONS,
    }


# ── Idle reaper ─────────────────────────────────────────────────────────
def _ensure_reaper():
    global _REAPER_TASK
    if _REAPER_TASK is None or _REAPER_TASK.done():
        try:
            _REAPER_TASK = asyncio.create_task(_reaper_loop())
        except RuntimeError:
            pass


async def _reaper_loop():
    while True:
        try:
            await asyncio.sleep(REAPER_INTERVAL_S)
            await _reap_idle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Visual recorder reaper error: {e}")


async def _reap_idle():
    now = time.time()
    to_kill = [sid for sid, s in _SESSIONS.items() if now - s.last_activity > IDLE_TIMEOUT_S]
    for sid in to_kill:
        logger.info(f"Reaping idle visual recorder session {sid}")
        await stop_session(sid)


# ── Actions ─────────────────────────────────────────────────────────────
async def take_screenshot(sess: RecorderSession) -> bytes:
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return b""
    async with sess.lock:
        try:
            # Override fonts.ready immediately before screenshot
            # This is more reliable than add_init_script for already-loaded pages
            try:
                await sess.page.evaluate("""
                    Object.defineProperty(document.fonts, 'ready', {
                        get: () => Promise.resolve(),
                        configurable: true,
                        writable: true
                    });
                """)
            except Exception:
                pass  # Ignore if already overridden or page not ready
            
            # Screenshot with reasonable timeout - fonts are now handled properly
            data = await sess.page.screenshot(
                type=SCREENSHOT_TYPE, 
                quality=SCREENSHOT_QUALITY, 
                full_page=False,
                timeout=30000,  # 30s timeout - fonts no longer block
                animations="disabled"
            )
        except Exception as e:
            logger.warning(f"screenshot failed for {sess.session_id}: {e}")
            return b""
    return data


async def get_page_meta(sess: RecorderSession) -> Dict[str, Any]:
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return {"url": "", "title": "", "viewport": {"width": sess.viewport[0], "height": sess.viewport[1]}, "page_status": "not_ready"}
    async with sess.lock:
        try:
            url = sess.page.url
            title = await sess.page.title()
            vp = sess.page.viewport_size or {"width": sess.viewport[0], "height": sess.viewport[1]}
        except Exception:
            url, title, vp = "", "", {"width": sess.viewport[0], "height": sess.viewport[1]}

    # ── 2026-05: Page-load error classification ─────────────────────
    # User report: "Visual Recorder mein chrome-error://chromewebdata/
    # dikh raha hai aur blank white page — solve kar do". This happens
    # when Chromium can't fetch the target URL (dead proxy, DNS fail,
    # SSL handshake fail, connection refused). We now return a
    # structured `page_status` + `page_status_reason` so the frontend
    # can render a clear error banner with a "Reload" button instead
    # of showing a useless blank preview.
    page_status = "ok"
    page_status_reason = ""
    try:
        lu = (url or "").lower()
        if lu.startswith("chrome-error://") or lu.startswith("chrome-error:"):
            page_status = "load_error"
            # Chromium puts the actual error code in the URL hash or
            # in the document title — try to extract a meaningful hint.
            t = (title or "").lower()
            if "no internet" in t or "err_internet" in t:
                page_status_reason = "no_internet"
            elif "name_not_resolved" in t or "dns" in t:
                page_status_reason = "dns_failure"
            elif "proxy" in t or "tunnel" in t:
                page_status_reason = "proxy_error"
            elif "ssl" in t or "cert" in t or "https" in t:
                page_status_reason = "ssl_error"
            elif "refused" in t or "connection" in t:
                page_status_reason = "connection_refused"
            elif "timed_out" in t or "timeout" in t:
                page_status_reason = "timeout"
            else:
                page_status_reason = "unknown_load_error"
        elif lu.startswith("about:blank") or not lu:
            page_status = "blank"
            page_status_reason = "page_not_loaded_yet"
    except Exception:
        pass

    return {
        "url": url,
        "title": title,
        "viewport": vp,
        "page_status": page_status,
        "page_status_reason": page_status_reason,
    }


async def reload_page(sess: RecorderSession) -> Dict[str, Any]:
    """2026-05 — Re-navigate the recorder's page to its original URL.

    Used by the new "Reload" button surfaced when `page_status !=
    "ok"`. Useful when a transient proxy failure / DNS hiccup made
    Chromium land on `chrome-error://chromewebdata/`. The session
    keeps its recorded steps and proxy config — only the live page
    navigates again.

    Returns `{ok, url, page_status, page_status_reason}`.
    """
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return {"ok": False, "error": "session_not_ready"}
    async with sess.lock:
        try:
            # Best-effort: 30s timeout, wait for DOMContentLoaded —
            # enough for slow offer pages but not so long we hang the
            # whole UI poll cycle.
            await sess.page.goto(sess.url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            return {
                "ok": False,
                "error": f"navigation_failed: {str(e)[:200]}",
                "url": sess.url,
            }
    meta = await get_page_meta(sess)
    return {
        "ok": meta.get("page_status") == "ok",
        "url": meta.get("url"),
        "page_status": meta.get("page_status"),
        "page_status_reason": meta.get("page_status_reason"),
    }


async def click_at(sess: RecorderSession, x: int, y: int, mode: str = "default", header_name: Optional[str] = None, group_id: Optional[str] = None) -> Dict[str, Any]:
    """Forward a click at (x, y) onto the page. Captures the element and
    appends a step. Modes:
      - default:    normal text-based click
      - form_fill:  click + remember field for next /type call (Excel header binding)
      - sheet_pick: click a button (Male/Female etc.) + bind to Excel column via
                    /sheet-pick-bind (text match at replay — no fixed Male selector)
      - random:     add this element to a "random pick" group (group_id required)
      - dropdown:   click a <select> element, return its <option> list so the
                    caller can bind an option (literal value/label) OR an
                    Excel column. No step is recorded until /dropdown-bind
                    is called (mirrors the form_fill → /type two-step flow).
      - final:      mark current page as conversion target
    """
    sess.touch()
    async with sess.lock:
        # 2026-05 — Use the shared `_RICH_ELEMENT_CAPTURE_JS` so click,
        # form_fill, dropdown and check all get the same xpath_stable /
        # xpath_abs / attrs / nth_of_type / tag metadata. The
        # `_build_fallbacks(info)` helper turns this into the
        # backward-compatible `fallbacks` dict that the RUT replay
        # engine reads (older recordings without `fallbacks` keep
        # working — `_step_fallbacks` returns [] for them).
        info = await sess.page.evaluate(
            _RICH_ELEMENT_CAPTURE_JS,
            [int(x), int(y)],
        )
        if not info:
            # fall back to plain click at coords
            await sess.page.mouse.click(x, y)
            return {"recorded": False, "warning": "No element at that point — clicked anyway, no step recorded"}

        # Perform the click
        # ── 2026-01 fix ──
        # Skip the live click for `random` mode: in random mode the user
        # is just collecting candidate texts (or, in the new checklist
        # flow, even this path is bypassed by /detect-clickables). If we
        # click here the page navigates away before the user can add more
        # options to the random pool. Pure capture only — no side-effect.
        # 2026-05: `check` mode handles its OWN click via the resolution
        # JS below (label→checkbox walk) so the live page reflects the
        # actual toggled state — a blind mouse.click() at coords could
        # land on a hidden input and do nothing.
        if mode not in ("random", "random_click", "check", "gender_pick"):
            try:
                await _live_click_captured(sess.page, info)
            except Exception:
                pass

        # For dropdown mode we also need to pull the option list out of
        # the element (or its nearest <select> ancestor) BEFORE leaving
        # the page lock so the DOM is in the state the user just saw.
        #
        # 2026-05 — Also DETECT whether the <select> is hidden behind a
        # custom dropdown UI (Bootstrap-Select, Select2, Chosen, React-
        # Select, etc). When detected we add `state: "attached"` and
        # `prefer_js_set: true` hints to the recorded `select` step so
        # the RUT replay engine skips the (futile) visibility wait and
        # goes straight to the JS-driven select path. This eliminates
        # the 5s+ pre-wait per dropdown for every visit of every job
        # using this automation.
        dropdown_options: List[Dict[str, str]] = []
        dropdown_selector: str = ""
        dropdown_wrapper_kind: str = ""   # "bootstrap-select"|"select2"|"chosen"|"react-select"|""
        dropdown_is_hidden: bool = False
        if mode == "dropdown":
            try:
                opts = await sess.page.evaluate(
                    """([x,y])=>{
                        var el = document.elementFromPoint(x, y);
                        if(!el) return null;
                        // Walk up to find the nearest <select> — works
                        // whether the user clicked the select directly or
                        // a styled wrapper around it.
                        var sel = el;
                        while(sel && sel.tagName !== 'SELECT'){
                            sel = sel.parentElement;
                        }
                        if(!sel || sel.tagName !== 'SELECT') return null;

                        // ── Detect hidden / custom-UI wrapping ──
                        var cs = window.getComputedStyle(sel);
                        var rect = sel.getBoundingClientRect();
                        var isHidden = (
                            cs.display === 'none' ||
                            cs.visibility === 'hidden' ||
                            parseFloat(cs.opacity || '1') < 0.05 ||
                            rect.width < 4 || rect.height < 4 ||
                            rect.left < -2000 || rect.top < -2000
                        );
                        // Climb ancestors looking for known wrapper class names
                        var wrapperKind = '';
                        var p = sel.parentElement;
                        var depth = 0;
                        while(p && depth < 6 && !wrapperKind){
                            var c = (p.className || '') + '';
                            var cl = c.toLowerCase();
                            if(/(^|\\s)bootstrap-select(\\s|$|--)/.test(cl)) wrapperKind = 'bootstrap-select';
                            else if(/select2(-container|-selection|-hidden|-dropdown)/.test(cl)) wrapperKind = 'select2';
                            else if(/(^|\\s)chosen-container/.test(cl)) wrapperKind = 'chosen';
                            else if(/react-select__(control|container|value-container)/.test(cl)) wrapperKind = 'react-select';
                            else if(/(^|\\s)nice-select(\\s|$)/.test(cl)) wrapperKind = 'nice-select';
                            else if(/(^|\\s)selectric/.test(cl)) wrapperKind = 'selectric';
                            else if(/(^|\\s)multiselect(\\s|$|-)/.test(cl)) wrapperKind = 'multiselect';
                            p = p.parentElement; depth++;
                        }
                        // If <select> is hidden but no known wrapper class, still
                        // treat as custom UI — the user clearly clicked SOMETHING
                        // visible above the hidden select.
                        if(isHidden && !wrapperKind) wrapperKind = 'generic-custom';

                        var options = [];
                        for(var i=0; i<sel.options.length; i++){
                            var o = sel.options[i];
                            options.push({
                                value: String(o.value == null ? '' : o.value),
                                label: String(o.text || o.label || '').trim(),
                                index: i,
                                selected: !!o.selected,
                            });
                        }
                        return {
                            name: sel.getAttribute('name') || '',
                            id: sel.id || '',
                            options: options,
                            isHidden: isHidden,
                            wrapperKind: wrapperKind,
                        };
                    }""",
                    [int(x), int(y)],
                )
                if opts and opts.get("options"):
                    dropdown_options = opts["options"]
                    dropdown_is_hidden = bool(opts.get("isHidden"))
                    dropdown_wrapper_kind = (opts.get("wrapperKind") or "") if dropdown_is_hidden else (opts.get("wrapperKind") or "")
                    # Build the same selector style as form_fill so the
                    # downstream `select` action can find the element.
                    dropdown_selector = _make_selector_for_input({
                        "tag": "SELECT",
                        "name": opts.get("name") or "",
                        "id": opts.get("id") or "",
                    })
            except Exception:
                pass

        # ── 2026-05: `check` mode — resolve actual checkbox + toggle it live ──
        # The user clicks the VISIBLE checkbox UI (which may be the
        # underlying <input type=checkbox>, OR a wrapping <label>, OR
        # a CSS-styled sibling <span>/<div>). We resolve to the real
        # <input type=checkbox> via three strategies:
        #   1. Clicked element IS the checkbox.
        #   2. Clicked element is a <label for="X"> — find element by id.
        #   3. Clicked element is INSIDE a <label> that wraps a checkbox.
        # Then we toggle it via the wrapping label.click() (proper user
        # flow) so the live preview shows the checked state.
        check_info: Dict[str, Any] = {}
        if mode == "check":
            try:
                cbinfo = await sess.page.evaluate(
                    """([x,y])=>{
                        var el = document.elementFromPoint(x, y);
                        if(!el) return null;
                        var cb = null;
                        // Strategy 1: direct hit
                        if(el.tagName==='INPUT' && el.type==='checkbox') cb = el;
                        // Strategy 2: <label for="X">
                        if(!cb && el.tagName==='LABEL' && el.htmlFor) {
                            cb = document.getElementById(el.htmlFor);
                            if(cb && cb.type !== 'checkbox') cb = null;
                        }
                        // Strategy 3: walk up to nearest <label>, find inner checkbox
                        if(!cb) {
                            var lbl = el.closest && el.closest('label');
                            if(lbl) {
                                cb = lbl.querySelector('input[type=checkbox]');
                                if(!cb && lbl.htmlFor) {
                                    var found = document.getElementById(lbl.htmlFor);
                                    if(found && found.type === 'checkbox') cb = found;
                                }
                            }
                        }
                        // Strategy 4: walk up looking for any checkbox child
                        if(!cb) {
                            var p = el;
                            for(var i=0; i<4 && p; i++) {
                                var found = p.querySelector && p.querySelector('input[type=checkbox]');
                                if(found) { cb = found; break; }
                                p = p.parentElement;
                            }
                        }
                        if(!cb) return null;
                        // Toggle via the proper user-flow: click wrapping label
                        var lbl = cb.closest('label');
                        var beforeChecked = cb.checked;
                        try {
                            if(lbl) lbl.click();
                            if(cb.checked === beforeChecked) cb.click();
                        } catch(e) {}
                        return {
                            id: cb.id || '',
                            name: cb.getAttribute('name') || '',
                            class: cb.className || '',
                            checked: cb.checked,
                            tag: 'INPUT',
                            type: 'checkbox',
                            text: (lbl ? (lbl.innerText || '').trim().slice(0, 80) : ''),
                        };
                    }""",
                    [int(x), int(y)],
                )
                if cbinfo:
                    check_info = cbinfo
                    # Override `info` so build-step gets the resolved
                    # checkbox attributes (not the wrapping label/span).
                    info["id"] = cbinfo.get("id") or info.get("id") or ""
                    info["name"] = cbinfo.get("name") or info.get("name") or ""
                    info["tag"] = "INPUT"
                    info["type"] = "checkbox"
                    if cbinfo.get("text"):
                        info["text"] = cbinfo["text"]
            except Exception:
                pass

    # Build & append step (outside lock to keep it short)
    step: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = {"element": info}

    text = info.get("text") or ""
    if mode == "default":
        if text:
            # 2026-01: pass the rich element info so the emitted JS can
            # try CSS/XPath selectors BEFORE falling back to text match.
            # Old recordings still work (no info, behaves as before).
            step = _build_text_click_evaluate(text, info)
        else:
            # No text — can't build a robust click. Fall back to coord-based
            # click. Anchor-first priority (and inner-anchor peek) to handle
            # the common pattern of a DIV/SPAN wrapping the real <a href>.
            # Also force-submit if the clicked element is type=submit.
            step = {"action": "evaluate", "script": (
                f"(function(){{"
                f"var el=document.elementFromPoint({int(x)},{int(y)});"
                f"if(!el)return;"
                f"el.scrollIntoView({{block:'center'}});"
                f"if(el.tagName==='A'&&el.href&&!el.target){{window.location.assign(el.href);return;}}"
                f"var inner=el.querySelector&&el.querySelector('a[href]');"
                f"if(inner&&inner.href&&!inner.target){{window.location.assign(inner.href);return;}}"
                f"var up=el.closest&&el.closest('a[href]');"
                f"if(up&&up.href&&!up.target){{window.location.assign(up.href);return;}}"
                f"el.click();"
                f"var isSubmit=(el.tagName==='INPUT'||el.tagName==='BUTTON')&&(el.type==='submit'||el.getAttribute&&el.getAttribute('type')==='submit');"
                f"if(isSubmit){{var f=el.form||(el.closest&&el.closest('form'));"
                f"if(f){{setTimeout(function(){{try{{if(!f._krx_submitted){{f._krx_submitted=true;f.submit();}}}}catch(e){{}}}},150);}}}}"
                f"}})();"
            )}
        # 2026-01: attach rich fallbacks dict to default click steps too.
        # Previously only form_fill / dropdown / check got this — meaning
        # text-based click steps had NO selector/xpath rescue path at
        # replay time. This was the root cause of the "selector/xpath
        # not traced properly" issue: if the page's CTA text changed
        # between recording and replay, the click silently failed and
        # the rest of the automation continued past it. Now the
        # `fallbacks` dict (xpath_stable, xpath_abs, key attrs, text)
        # is available to the RUT replay engine — see
        # `real_user_traffic._step_fallbacks` for how it's consumed by
        # the native_click / wait_for_selector chain.
        if step is not None:
            _fb_click = _build_fallbacks(info)
            if _fb_click:
                step["fallbacks"] = _fb_click
            # ── 2026-06 — surface selector + xpath as TOP-LEVEL editable
            # fields on the recorded step so the Edit Step panel shows
            # them (was empty for evaluate-action click steps, which
            # confused users into thinking nothing was captured and
            # risked steps being skipped during job replay).
            #
            # Purely cosmetic for the existing replay path: the embedded
            # JS in `step["script"]` already tries CSS → xpath_stable →
            # xpath_abs → text-match in order. Surfacing these as named
            # fields lets the user (1) SEE what was captured and (2)
            # EDIT them to override the brittle text-match fallback
            # without having to hand-craft the eval JS.
            try:
                _attrs = (info.get("attrs") or {}) if isinstance(info, dict) else {}
                _id = (info.get("id") or "").strip() if isinstance(info, dict) else ""
                _best_css = ""
                # Priority order mirrors _build_text_click_evaluate's
                # selector block so what's shown == what replay uses.
                for k in ("data-testid", "data-test", "data-cy", "data-qa", "data-id"):
                    v = _attrs.get(k) if isinstance(_attrs, dict) else None
                    if isinstance(v, str) and v:
                        _best_css = f'[{k}="{v}"]'
                        break
                if not _best_css and _id and not re.match(r"^[\d_-]", _id) and len(_id) < 60 and ":" not in _id:
                    _best_css = f"#{_id}"
                if not _best_css and isinstance(_attrs, dict):
                    _nm = _attrs.get("name")
                    if isinstance(_nm, str) and _nm:
                        _tg = (info.get("tag") or "").lower() if isinstance(info, dict) else ""
                        _best_css = f'{_tg}[name="{_nm}"]' if _tg else f'[name="{_nm}"]'
                if _best_css and not step.get("selector"):
                    step["selector"] = _best_css
                _xp = (info.get("xpath_stable") or info.get("xpath_abs") or "").strip() if isinstance(info, dict) else ""
                if _xp and not step.get("xpath"):
                    step["xpath"] = _xp
            except Exception:
                # Never let a cosmetic-only enhancement break recording.
                pass
    elif mode == "form_fill":
        # Build a selector for the input
        sel = _make_selector_for_input(info)
        extra["selector"] = sel
        extra["header_name"] = header_name

        # ── 2026-05 ──
        # If a header is mapped AND the recorder has a sample_row,
        # AUTO-FILL the live browser input with the sample value so
        # the user can move past form validation and record steps on
        # the NEXT page. The recorded step still uses the {{header}}
        # template — at RUT replay time the real lead row substitutes.
        # ── 2026-01 update ──
        # If sample_row is missing OR the column is not in it, fall
        # back to a sensible default (e.g. first→John, zip→10001)
        # so the live form still fills and CONTINUE works. The recorded
        # JSON step is unchanged; only the live browser uses the fallback.
        sample_val: Optional[str] = _resolve_live_value(sess, header_name) if header_name else None
        # Always emit a real `fill` step in the JSON so the runner
        # populates the input with the lead's value. The placeholder
        # `{{header_name}}` is substituted by the RUT engine's
        # _substitute() function. If no header is mapped yet, we still
        # add a wait_for_selector so the user can /type later.
        if header_name:
            step = {
                "action": "fill",
                "selector": sel,
                "value": "{{" + header_name + "}}",
                "optional": True,
            }
            # 2026-05 — attach rich fallbacks so RUT replay can rescue
            # this fill if `sel` stops matching (renamed id/name, etc.)
            _fb = _build_fallbacks(info)
            if _fb:
                step["fallbacks"] = _fb
            # 2026-05 — also stash the fallbacks under this selector so
            # the subsequent /type call (which doesn't re-capture rich
            # metadata) can attach the SAME fallbacks to its fill step.
            try:
                if not hasattr(sess, "_form_fill_fallbacks"):
                    sess._form_fill_fallbacks = {}  # type: ignore[attr-defined]
                if _fb:
                    sess._form_fill_fallbacks[sel] = _fb  # type: ignore[attr-defined]
            except Exception:
                pass
            # During recording, also fill the live browser with the
            # sample value so the page sees a populated field.
            if sample_val is not None:
                try:
                    fill_ok, fill_extra = await _fill_live_input(sess.page, sel, sample_val)
                    extra.update(fill_extra)
                    if not fill_ok:
                        extra["fill_warning"] = fill_extra.get(
                            "fill_warning",
                            "Live fill failed — use Fix Type (T) on the email field, then Continue.",
                        )
                except Exception as e:  # noqa: BLE001
                    extra["fill_warning"] = (
                        f"Selector did not match in the live page ({type(e).__name__}). "
                        "Step recorded anyway; verify the column name matches the field."
                    )
            else:
                extra["sample_hint"] = (
                    "No sample data for this column. Pass `sample_row` when "
                    "starting the recorder (or upload an Excel data file) so "
                    "forms fill automatically during recording."
                )
        else:
            step = {"action": "wait_for_selector", "selector": sel, "timeout": 8000, "optional": True}
    elif mode == "sheet_pick":
        # Two-step flow (like dropdown): click captures the element, bind
        # records the per-row text-click evaluate step.
        step = None
        extra["pending_sheet_pick"] = True
        extra["clicked_text"] = text
        tag_u = (info.get("tag") or "").upper()
        if tag_u in ("INPUT", "TEXTAREA", "SELECT"):
            extra["warning"] = (
                "That looks like a form input — use Form Fill for text fields "
                "or Dropdown for <select> elements."
            )
        elif not text:
            extra["warning"] = (
                "No visible text on this element — Sheet Pick works best on "
                "labelled buttons (Male / Female / Yes / No)."
            )
    elif mode == "gender_pick":
        # Collect Male + Female button labels (no step yet) — bind via
        # /gender-pick-bind once both sides are captured.
        step = None
        extra["gender_pick_text"] = text
        if not text:
            extra["warning"] = (
                "No visible text — click the Male or Female button label."
            )
    elif mode in ("random", "random_click"):
        # Don't add a step — caller will batch via /group-random
        extra["pending_random_text"] = text
        extra["group_id"] = group_id
    elif mode == "dropdown":
        # We don't record the `select` step yet — the caller has to bind
        # it (literal option or Excel header) via /dropdown-bind first.
        # Surface the option list so the UI can render a picker.
        # 2026-05: Also surface custom-UI detection hints so the picker
        # shows a badge ("Bootstrap-Select detected") and so bind_dropdown
        # can stamp the right state/JS hints onto the recorded step.
        step = None
        extra["selector"] = dropdown_selector or _make_selector_for_input(info)
        extra["options"] = dropdown_options
        if dropdown_wrapper_kind:
            extra["wrapper_kind"] = dropdown_wrapper_kind
        # 2026-05 — stash fallbacks for the upcoming /dropdown-bind call
        # so the recorded `select` step gets attribute/xpath/text rescue
        # paths same as click & check do.
        try:
            _fb_dd = _build_fallbacks(info)
            if _fb_dd:
                if not hasattr(sess, "_pending_dropdown_fallbacks"):
                    sess._pending_dropdown_fallbacks = {}  # type: ignore[attr-defined]
                sess._pending_dropdown_fallbacks[extra["selector"]] = _fb_dd  # type: ignore[attr-defined]
        except Exception:
            pass
        if dropdown_is_hidden:
            extra["is_hidden_select"] = True
            # Stash on the session so /dropdown-bind picks it up
            sess._pending_dropdown_meta = {  # type: ignore[attr-defined]
                "selector": dropdown_selector,
                "wrapper_kind": dropdown_wrapper_kind,
                "is_hidden_select": True,
            }
        else:
            # Clear any stale meta from a previous dropdown click
            try:
                if hasattr(sess, "_pending_dropdown_meta"):
                    delattr(sess, "_pending_dropdown_meta")
            except Exception:
                pass
        if not dropdown_options:
            extra["warning"] = (
                "No <select> element found at that point — pick the dropdown "
                "control itself (the one that opens the option list)."
            )
    elif mode == "check":
        # 2026-05: dedicated checkbox recording. The user clicked the
        # visible UI (label / styled span / the input itself); we
        # already resolved to the real <input type=checkbox> above and
        # toggled it via wrapping-label click in the live page.
        # Build a robust selector preferring #id → [name="X"] →
        # input[type=checkbox][name="X"]. The RUT engine routes this
        # through _smart_check_with_fallback at replay time, which
        # additionally handles CSS-styled hidden checkboxes (display:none
        # with sibling-span proxy) — so even if the page changes its
        # ID after recording, the visit will still succeed.
        sel: str = ""
        if info.get("id"):
            sel = f"#{info['id']}"
        elif info.get("name"):
            sel = f"input[name='{info['name']}']"
        else:
            sel = "input[type='checkbox']"  # last-resort
        extra["selector"] = sel
        extra["checked_after"] = bool(check_info.get("checked")) if check_info else None
        if not check_info:
            extra["warning"] = (
                "No checkbox found at that point — click directly on the "
                "checkbox (or the label / red box around it)."
            )
            step = None
        else:
            step = {
                "action": "check",
                "selector": sel,
                "timeout": 8000,
                "optional": True,
            }
            # 2026-05 — attach rich fallbacks so check step survives
            # selector drift between recording and replay.
            _fb_chk = _build_fallbacks(info)
            if _fb_chk:
                step["fallbacks"] = _fb_chk
    elif mode == "final":
        # Captured separately by /mark-final endpoint
        step = None
    else:
        step = _build_text_click_evaluate(text) if text else None

    if step is not None:
        # 2026-06 — Ensure every recorded step has BOTH selector + xpath
        # at the TOP LEVEL (so RUT replay always has a backup selector
        # path, and the operator can SEE both in the Edit Step UI).
        # No-op when the step already has both (rare, but happens for
        # default click which sets them earlier).
        try:
            _attach_selector_and_xpath(step, info)
        except Exception:
            # Never let selector enrichment break recording.
            pass
        sess.append_step(step)
        # 2026-01 — auto waits removed per user request. Earlier this added
        # wait(1500) + wait_for_load(60000) + wait(2000) after every click,
        # which combined with the stuck-watchdog (60s URL-change threshold)
        # caused legitimate visits to be aborted while waiting for the
        # page-load event that never fires between clicks on the same form.
        # If a click triggers a real navigation, the next action in the
        # recorded sequence will naturally wait via its own selector
        # resolution / fill timeout. For deliberate post-click pauses the
        # user can manually add a wait step from the recorder UI
        # (Insert → Wait / Wait for page load).

    return {"recorded": step is not None, "step": step, "element": info, "mode": mode,
            **{k: v for k, v in extra.items() if k != "element"},
            **({"cross_origin_iframe": True,
                "warning": "Cross-origin iframe click — RUT replay uses frame_locator. "
                "Use ⋯ More → iframe click for reliable replay."}
               if isinstance(info, dict) and (info.get("tag") or "").upper() in ("IFRAME", "FRAME")
               and not (info.get("iframe_path") or [])
               else {})}


async def add_screenshot_marker(sess: RecorderSession, name: Optional[str] = None) -> Dict[str, Any]:
    """Insert a 'screenshot' action step at the current position. During
    the actual RUT job, the runner will take a real screenshot at this
    point and push it to the Live Activity panel so the customer can
    visually verify how far the visit progressed.

    Does NOT take a screenshot now — the live preview the customer is
    already polling from /screenshot covers the recording-time view.
    """
    sess.touch()
    safe_name = (name or f"Step {len(sess.steps) + 1}")[:60].strip() or f"Step {len(sess.steps) + 1}"
    step = {
        "action": "screenshot",
        "name": safe_name,
        # optional=True so a transient screenshot failure during job
        # execution (e.g. a closed page) doesn't fail the whole visit.
        "optional": True,
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ── 2026-05: User-requested explicit "close browser" recording step ──
# Why this exists:
#   The user noticed visits in the Live Visual Grid keep their browser
#   tile populated for a few seconds after the final recorded step,
#   while the per-visit Playwright context is still being torn down by
#   the outer finally-block. On medium-RAM VPSes this stacks (each
#   visit holds ~150-300 MB until its finally fires), so concurrent
#   workers were sometimes starved of RAM and the next worker booted
#   slowly. With this `close` step the operator can mark "browser
#   work is done here, free it NOW" at any point in the recording —
#   typically right after the conversion-confirmation screenshot.
#   The RUT runner already handles this action (see real_user_traffic.
#   py / `elif action in ("close", "close_browser", ...)`).
#
# Notes:
#   • optional=False on purpose — close is a final step; if it can't
#     run (e.g. page already gone), we WANT to know about it in the
#     diagnostics so the recording isn't silently incomplete.
#   • No selector / no timeout — it's a pure browser-lifecycle action.
async def add_close_browser_step(sess: RecorderSession) -> Dict[str, Any]:
    """Insert a 'close' action step at the current position. The RUT
    runner will close the per-visit page+context as soon as it reaches
    this step, releasing RAM/proxy slot for the next worker."""
    sess.touch()
    step = {
        "action": "close",
        # No timeout/selector — pure lifecycle step. Not marked optional
        # because if the runner can't reach it, the operator should see
        # it in the diagnostics report (silently skipping a close would
        # leak the very resource this step exists to free).
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def live_test(
    sess: RecorderSession,
    sample_row: Optional[Dict[str, Any]] = None,
    fresh_page: bool = False,
    start_index: int = 0,
    rut_parity: bool = False,
    self_heal: Optional[bool] = None,
    skip_captcha: Optional[bool] = None,
) -> Dict[str, Any]:
    """Run the current recorded steps end-to-end against the live page,
    returning per-step timing + ok/error + a static-analysis diagnostic
    summary. This is the "Run Live Test" button in the recorder.

    `start_index` (2026-01) — skip the first N steps and pick up replay
    from step `start_index` onwards. Powers the "Replay from here"
    button on the Live Test results panel: when step #15 fails, the
    user fixes it and re-runs from #15 — the browser is already on the
    correct page state (because the previous test got us there), so we
    DO NOT open a fresh page and we DO NOT execute steps 0..14 again.
    This makes the debug loop ~5-10× faster vs. re-running the whole
    automation each time.

    Strategy:
      • Open a fresh page (default) so we mirror what a RUT visit would
        actually see — fresh cookies, fresh DOM, fresh JS state. If the
        user wants to replay on the CURRENT page (e.g. to debug only
        the last few steps), they can pass fresh_page=False.
      • Substitute {{header}} placeholders with values from `sample_row`
        (defaults to the session's sample_row).
      • Reuse `_execute_automation_steps` with collect_timings=True so
        every step gets {idx, action, selector, ok, error, ms}.
      • Layer a static-analysis pass on the steps array for
        anti-patterns / wrapper-kind summary / top-3 slowest hints.

    Returns:
      {
        ok: bool,
        total_ms: int,
        executed_steps: int,
        error: str|None,
        step_results: [{idx, action, selector, ok, error, ms, optional, self_healed?}, ...],
        diagnostics: {
          slowest: [{idx, action, ms}, ...3],
          anti_patterns: [str, ...],
          wrapper_summary: {bootstrap-select: 3, ...} | {},
          recommendations: [str, ...],
        },
        final_url: str,
      }
    """
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return {"ok": False, "error": "Recorder session not ready"}
    if not sess.steps:
        return {"ok": False, "error": "No steps recorded yet — record at least one step before running Live Test."}

    # Lazy import to avoid the visual_recorder ↔ real_user_traffic
    # circular import at module-load time. real_user_traffic also
    # depends on small helpers in this module via runtime calls.
    try:
        from real_user_traffic import _execute_automation_steps
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": f"Engine import failed: {e}"}

    row = dict(sample_row or sess.sample_row or {})

    # 2026-01: "Replay from here" — slice steps when start_index > 0.
    # The browser stays on its current state (no fresh_page) so the
    # remaining steps pick up exactly where the previous run failed.
    # We re-index the per-step results back to the ORIGINAL indices
    # before returning so the UI panel highlights the right rows.
    full_steps = list(sess.steps)
    if start_index < 0:
        start_index = 0
    if start_index >= len(full_steps):
        return {"ok": False, "error": f"start_index {start_index} ≥ total steps {len(full_steps)}"}
    steps_to_run = full_steps[start_index:]
    if start_index > 0:
        # Forcing fresh_page=False — the WHOLE POINT of replay-from-here
        # is to preserve the post-failure browser state. Override any
        # accidental fresh_page=True from the caller.
        fresh_page = False

    # 2026-01 (additive): reset live-progress feed at the start of every
    # live_test invocation. The callback below appends one event per
    # step transition (running → ok / failed) so the UI can show a
    # live "step #N — running…" / "step #N ok in 230ms" feed.
    sess.live_progress = []
    sess.live_progress_running = True
    sess.live_progress_started_at = time.time()
    sess.live_progress_finished_at = None

    async def _progress_cb(event: Dict[str, Any]) -> None:
        try:
            # Re-map sliced idx back to ORIGINAL recording idx so the UI
            # highlights the right row when start_index > 0.
            if start_index > 0 and "idx" in event:
                try:
                    event = dict(event)
                    event["idx"] = int(event["idx"]) + start_index
                except (TypeError, ValueError):
                    pass
            sess.live_progress.append(event)
            # 2026-01: memory optimization — drop heavy screenshot_b64
            # payload from all but the most recent 8 events. UI only
            # ever shows the LATEST frame in the live view, so older
            # screenshots are dead weight. Keeps memory bounded
            # regardless of automation length.
            if len(sess.live_progress) > 8:
                for old in sess.live_progress[:-8]:
                    if old.get("screenshot_b64"):
                        old["screenshot_b64"] = ""  # strip image bytes
            # Cap event count — keep last 500 events.
            if len(sess.live_progress) > 500:
                sess.live_progress = sess.live_progress[-500:]
        except Exception:
            pass

    async with sess.lock:
        # Optionally open a fresh page for an honest end-to-end test.
        # We DO NOT close the recorder's existing page — the user is
        # mid-recording and switching back to it should still work.
        page = sess.page
        fresh_ctx = None
        fresh_page_obj = None
        if fresh_page and sess.context is not None:
            try:
                fresh_page_obj = await sess.context.new_page()
                if sess.url:
                    await fresh_page_obj.goto(sess.url, timeout=45000, wait_until="domcontentloaded")
                page = fresh_page_obj
            except Exception as e:
                # Fresh-page setup failed — fall back to current page so
                # the live-test still returns useful timing data.
                if fresh_page_obj is not None:
                    try:
                        await fresh_page_obj.close()
                    except Exception:
                        pass
                fresh_page_obj = None
                page = sess.page
                logger.warning(f"[live-test] fresh-page setup failed, using recorder page: {e}")

        try:
            _use_self_heal = bool(self_heal) if self_heal is not None else bool(rut_parity)
            _use_skip_captcha = bool(skip_captcha) if skip_captcha is not None else (not rut_parity)
            res = await _execute_automation_steps(
                page=page,
                row=row,
                steps=steps_to_run,
                skip_captcha=_use_skip_captcha,
                self_heal=_use_self_heal,
                collect_timings=True,
                user_id=sess.user_id,   # enable self-healing aliases (2026-01)
                on_step_progress=_progress_cb,  # 2026-01: real-time step feed
                skip_missing_steps=not rut_parity,
            )
        except Exception as e:
            res = {"status": "failed", "error": f"Live test crashed: {e}", "executed_steps": 0, "step_results": []}
        finally:
            # Best-effort close of the fresh page (if any)
            if fresh_page_obj is not None:
                try:
                    await fresh_page_obj.close()
                except Exception:
                    pass
            # 2026-01: mark live progress feed as finished
            sess.live_progress_running = False
            sess.live_progress_finished_at = time.time()

        final_url = ""
        try:
            final_url = sess.page.url or ""
        except Exception:
            pass

    # ── Layer the static-analysis diagnostic pass on top of timings ──
    step_results = res.get("step_results") or []

    # 2026-01: when start_index > 0 ("Replay from here"), the runtime
    # indices in step_results are 0..N relative to the sliced steps —
    # re-map them to the ORIGINAL recording's indices so the UI shows
    # the right rows highlighted in red/green.
    if start_index > 0:
        for sr_item in step_results:
            if isinstance(sr_item, dict) and "idx" in sr_item:
                try:
                    sr_item["idx"] = int(sr_item["idx"]) + start_index
                except (TypeError, ValueError):
                    pass

    diagnostics = analyse_steps(sess.steps, step_results)

    # Same re-map for failed_at_idx
    failed_at = res.get("failed_at_idx")
    if failed_at is not None and start_index > 0:
        try:
            failed_at = int(failed_at) + start_index
        except (TypeError, ValueError):
            pass

    return {
        "ok": res.get("status") == "ok",
        "status": res.get("status"),
        "error": res.get("error"),
        "executed_steps": res.get("executed_steps", 0),
        "total_ms": res.get("total_ms"),
        "step_results": step_results,
        "diagnostics": diagnostics,
        "final_url": final_url,
        "failed_at_idx": failed_at,
        "total_steps": len(sess.steps),
        "fresh_page": bool(fresh_page),
        "start_index": start_index,
        "rut_parity": bool(rut_parity),
        "self_heal": bool(_use_self_heal),
        "skip_captcha": bool(_use_skip_captcha),
    }


def analyse_steps(
    steps: List[Dict[str, Any]],
    step_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Smart Replay Diagnostics — static analysis on the steps array,
    optionally combined with runtime per-step timings.

    Detects:
      • Top-3 slowest steps (if runtime timings provided)
      • Anti-patterns:
          - click → fill/select on different selector with no wait
          - wait_for_selector state="visible" without wrapper hint
            (dropdown landmines from older recordings)
          - long sequence with no screenshot for debug visibility
          - hard wait of >5000ms (flag for replacement with
            wait_for_load_state or wait_for_selector)
          - select step on dropdown without match_by clarification
      • Wrapper-kind summary (count of bootstrap-select / select2 etc)
      • Recommendations (actionable, one-liner each)
    """
    steps = list(steps or [])
    sr = list(step_results or [])

    # ── Wrapper-kind summary ─────────────────────────────────────────
    wrapper_summary: Dict[str, int] = {}
    for s in steps:
        wk = (s.get("wrapper_kind") or "").strip()
        if wk:
            wrapper_summary[wk] = wrapper_summary.get(wk, 0) + 1
    native_selects = sum(1 for s in steps if (s.get("action") == "select") and not s.get("wrapper_kind"))
    if native_selects > 0:
        wrapper_summary.setdefault("native", 0)
        wrapper_summary["native"] += native_selects

    # ── Top-3 slowest steps (needs runtime data) ─────────────────────
    slowest: List[Dict[str, Any]] = []
    if sr:
        ranked = sorted(
            [{"idx": r.get("idx"), "action": r.get("action"), "selector": r.get("selector"), "ms": int(r.get("ms") or 0)} for r in sr if r.get("ms") is not None],
            key=lambda r: r["ms"], reverse=True,
        )
        slowest = ranked[:3]

    # ── Anti-pattern detection ───────────────────────────────────────
    # Two-tier output:
    #   `anti` / `recs` — legacy string lists for the existing UI panels
    #   `findings`      — structured records the new Auto-fix endpoint
    #                     can act on. Each finding has:
    #                       kind:          stable id (e.g. "hard_wait_too_long")
    #                       at_step:       0-indexed step the fix targets
    #                       message:       human-readable description
    #                       fix_summary:   what the auto-fix WILL do
    #                       auto_fixable:  bool (false means user must re-record)
    #                       extra:         per-kind data the apply step needs
    anti: List[str] = []
    recs: List[str] = []
    findings: List[Dict[str, Any]] = []

    # 1. wait_for_selector state="visible" on a dropdown-like selector
    #    without wrapper_kind hint (legacy recording pattern → may 25s
    #    timeout on hidden-behind-custom-UI selects).
    for i, s in enumerate(steps):
        if s.get("action") == "wait_for_selector" and (s.get("state") or "visible") == "visible":
            sel = (s.get("selector") or "").lower()
            if any(k in sel for k in ("select", "month", "year", "day", "country", "state", "gender", "dob")):
                # Look at next non-wait step for a select action
                for j in range(i + 1, min(i + 3, len(steps))):
                    if steps[j].get("action") == "select":
                        msg = (
                            f"Step #{i+1} `wait_for_selector` with state=\"visible\" before a `select` — "
                            f"if the underlying <select> is hidden behind a custom dropdown, this could "
                            f"25s-timeout on replay."
                        )
                        rec = f"Switch step #{i+1}'s state from 'visible' to 'attached'."
                        anti.append(msg + " (Newer iteration-4 helper now auto-falls back, but re-recording stamps the hint cleanly.)")
                        recs.append(
                            f"Re-record step #{i+1}'s dropdown — the recorder now auto-detects custom UIs "
                            f"and stamps state=\"attached\" + wrapper_kind for instant matching."
                        )
                        findings.append({
                            "kind": "wait_for_visible_before_select",
                            "at_step": i,
                            "message": msg,
                            "fix_summary": rec,
                            "auto_fixable": True,
                            "extra": {},
                        })
                        break

    # 2. Click immediately followed by fill/select on a DIFFERENT selector,
    #    with no wait_for_selector / wait between them.
    for i, s in enumerate(steps[:-1]):
        if s.get("action") == "click":
            nxt = steps[i + 1]
            if nxt.get("action") in ("fill", "select", "type") and nxt.get("selector") and s.get("selector") != nxt.get("selector"):
                msg = (
                    f"Step #{i+1} click → step #{i+2} {nxt.get('action')} on a different selector with no "
                    f"wait between them. If the click triggers DOM changes (e.g. step-2 of a multi-page form), "
                    f"the next step may race the DOM update."
                )
                rec = f"Insert a wait_for_selector('{nxt.get('selector')}') between steps #{i+1} and #{i+2}."
                anti.append(msg)
                recs.append(f"Insert a 'Wait for navigation' or 'Wait for selector' between steps #{i+1} and #{i+2}.")
                findings.append({
                    "kind": "click_then_action_no_wait",
                    "at_step": i,
                    "message": msg,
                    "fix_summary": rec,
                    "auto_fixable": True,
                    "extra": {"next_selector": nxt.get("selector"), "next_action": nxt.get("action")},
                })

    # 3. Hard wait > 5s — usually a sign the recording is over-cautious
    for i, s in enumerate(steps):
        if s.get("action") == "wait":
            ms = int(s.get("ms") or 0)
            if ms > 5000:
                # Find the NEXT actionable step (fill/click/select/type/check)
                # so we can replace the hard wait with wait_for_selector on it.
                next_sel = None
                next_action_idx = None
                for j in range(i + 1, min(i + 6, len(steps))):
                    sj = steps[j]
                    if sj.get("action") in ("fill", "click", "select", "type", "check", "uncheck") and sj.get("selector"):
                        next_sel = sj.get("selector")
                        next_action_idx = j
                        break
                msg = f"Step #{i+1} hard wait of {ms}ms (>5s). Hard waits inflate every visit's runtime."
                if next_sel:
                    rec = f"Replace step #{i+1}'s hard {ms}ms wait with wait_for_selector('{next_sel}', timeout={max(8000, ms)}ms) — saves ~{(ms - 1500) / 1000:.1f}s per visit."
                    fixable = True
                else:
                    rec = f"Replace step #{i+1}'s hard wait with wait_for_selector — but no actionable step follows it within 5 steps. Manual review needed."
                    fixable = False
                anti.append(msg)
                recs.append(
                    f"Replace step #{i+1}'s hard wait with `wait_for_selector` on whatever element you're "
                    f"actually waiting for. Saves ~{(ms - 1500) / 1000:.1f}s per visit."
                )
                findings.append({
                    "kind": "hard_wait_too_long",
                    "at_step": i,
                    "message": msg,
                    "fix_summary": rec,
                    "auto_fixable": fixable,
                    "extra": {"ms": ms, "next_selector": next_sel, "next_action_idx": next_action_idx},
                })

    # 4. select step with no match_by — may match the wrong option on
    #    forms with duplicate labels (e.g. "Other" appearing twice).
    for i, s in enumerate(steps):
        if s.get("action") == "select" and not s.get("match_by"):
            msg = (
                f"Step #{i+1} select without match_by — defaults to 'label' which may match the wrong "
                f"option on forms with duplicate visible text."
            )
            rec = f"Set step #{i+1}'s match_by to 'label' explicitly."
            anti.append(msg)
            recs.append(f"Re-bind step #{i+1} via the dropdown picker so match_by is explicitly set.")
            findings.append({
                "kind": "select_missing_match_by",
                "at_step": i,
                "message": msg,
                "fix_summary": rec,
                "auto_fixable": True,
                "extra": {},
            })

    # 5. Long automation with no screenshots — hard to debug a failed visit
    if len(steps) >= 12 and not any(s.get("action") == "screenshot" for s in steps):
        # Find the LAST click (likely the submit) to insert screenshot just before it.
        last_click_idx = None
        for i in range(len(steps) - 1, -1, -1):
            if steps[i].get("action") == "click":
                last_click_idx = i
                break
        anti.append(
            "No screenshot steps in a long automation — when a visit fails in production "
            "you'll have nothing to look at."
        )
        recs.append(
            "Add a Screenshot step right before the submit click (Insert → Screenshot) so "
            "failed visits surface the form state."
        )
        if last_click_idx is not None:
            findings.append({
                "kind": "long_automation_no_screenshot",
                "at_step": last_click_idx,
                "message": "Long automation with no screenshot — failed visits won't have a debug image.",
                "fix_summary": f"Insert a screenshot step right before step #{last_click_idx+1} (the last click).",
                "auto_fixable": True,
                "extra": {"insert_before_idx": last_click_idx},
            })

    return {
        "slowest": slowest,
        "anti_patterns": anti,
        "wrapper_summary": wrapper_summary,
        "recommendations": recs,
        "findings": findings,
        "auto_fixable_count": sum(1 for f in findings if f.get("auto_fixable")),
        "total_steps": len(steps),
        "has_runtime_data": bool(sr),
    }


def apply_auto_fix(
    steps: List[Dict[str, Any]],
    kind: str,
    at_step: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Apply a single auto-fix to a steps array. Returns the NEW steps
    array + a human-readable description of what was changed.

    Pure function — does not mutate the input array. Caller is
    responsible for persisting the result (e.g. `sess.steps = new_steps`).

    Supported kinds (must match analyse_steps `findings[*].kind`):
      • `wait_for_visible_before_select` — flip state="visible" → "attached"
      • `hard_wait_too_long` — replace hard wait with wait_for_selector
        on the next actionable step's selector
      • `select_missing_match_by` — set match_by="label" on the select step
      • `click_then_action_no_wait` — insert wait_for_selector for the
        following step's selector AFTER the click
      • `long_automation_no_screenshot` — insert a screenshot step
        immediately before the last click (the "submit")

    Returns (new_steps, change_summary). If kind is unknown or at_step
    is out of range, raises ValueError so the caller can surface a
    clear error to the user.
    """
    if not isinstance(steps, list) or at_step < 0 or at_step >= len(steps):
        raise ValueError(f"Invalid step index {at_step} for {len(steps)} steps")

    new_steps = [dict(s) for s in steps]  # deep-ish copy of each step dict
    extra = extra or {}

    if kind == "wait_for_visible_before_select":
        s = new_steps[at_step]
        if s.get("action") != "wait_for_selector":
            raise ValueError(f"Step #{at_step+1} is not a wait_for_selector — cannot apply fix")
        s["state"] = "attached"
        return new_steps, f"Step #{at_step+1}: changed state from 'visible' → 'attached' (handles dropdowns hidden behind custom UIs)."

    if kind == "hard_wait_too_long":
        s = new_steps[at_step]
        if s.get("action") != "wait":
            raise ValueError(f"Step #{at_step+1} is not a wait — cannot apply fix")
        next_sel = extra.get("next_selector")
        if not next_sel:
            # Re-derive from following steps in case extra is missing.
            for j in range(at_step + 1, min(at_step + 6, len(new_steps))):
                sj = new_steps[j]
                if sj.get("action") in ("fill", "click", "select", "type", "check", "uncheck") and sj.get("selector"):
                    next_sel = sj.get("selector")
                    break
        if not next_sel:
            raise ValueError(f"No actionable step follows step #{at_step+1} within 5 steps — fix not applicable.")
        original_ms = int(s.get("ms") or 0)
        # Replace in place with a wait_for_selector. Timeout: use the
        # original wait ms (capped at 25s) so a slow page that needed
        # 8s still gets up to 8s before failing — but the wait ends as
        # soon as the element appears, saving the rest.
        new_steps[at_step] = {
            "action": "wait_for_selector",
            "selector": next_sel,
            "state": "attached",
            "timeout": min(max(8000, original_ms), 25000),
            "optional": True,
            "_auto_fix": "hard_wait_too_long",
        }
        saved = max(0, (original_ms - 1500) / 1000)
        return new_steps, f"Step #{at_step+1}: replaced {original_ms}ms hard wait with wait_for_selector('{next_sel}', state='attached'). Saves up to ~{saved:.1f}s/visit."

    if kind == "select_missing_match_by":
        s = new_steps[at_step]
        if s.get("action") != "select":
            raise ValueError(f"Step #{at_step+1} is not a select — cannot apply fix")
        s["match_by"] = "label"
        return new_steps, f"Step #{at_step+1}: set match_by='label' explicitly (default behavior, but now defensive against future engine changes)."

    if kind == "click_then_action_no_wait":
        s = new_steps[at_step]
        if s.get("action") != "click":
            raise ValueError(f"Step #{at_step+1} is not a click — cannot apply fix")
        next_sel = extra.get("next_selector")
        if not next_sel:
            if at_step + 1 < len(new_steps):
                next_sel = new_steps[at_step + 1].get("selector")
        if not next_sel:
            raise ValueError(f"Next step has no selector — fix not applicable.")
        # Insert a wait_for_selector RIGHT AFTER the click.
        wait_step = {
            "action": "wait_for_selector",
            "selector": next_sel,
            "state": "attached",
            "timeout": 15000,
            "optional": True,
            "_auto_fix": "click_then_action_no_wait",
        }
        new_steps.insert(at_step + 1, wait_step)
        return new_steps, f"Inserted wait_for_selector('{next_sel}') right after step #{at_step+1}'s click. Eliminates the race condition."

    if kind == "long_automation_no_screenshot":
        # Insert a screenshot step BEFORE the at_step (which is the last click)
        screenshot_step = {
            "action": "screenshot",
            "name": f"before-step-{at_step+1}",
            "_auto_fix": "long_automation_no_screenshot",
        }
        new_steps.insert(at_step, screenshot_step)
        return new_steps, f"Inserted screenshot step right before step #{at_step+1} (your submit click). Failed visits will now have a debug image."

    raise ValueError(f"Unknown auto-fix kind: {kind!r}")


async def bind_dropdown(
    sess: RecorderSession,
    selector: str,
    value: Optional[str] = None,
    header_name: Optional[str] = None,
    match_by: str = "label",
) -> Dict[str, Any]:
    """Finalise a dropdown binding started by a `mode='dropdown'` click.

    The caller passes EITHER:
      - `value`        — a literal option (e.g. "Male") to always select, OR
      - `header_name`  — an Excel column name; the row's value is used.

    `match_by` is either 'label' (visible text — default, most forgiving)
    or 'value' (the option's value attribute).

    ── 2026-05 ──
    During recording we ALSO call `page.select_option()` on the live
    browser so the dropdown VISIBLY changes and the form's onchange
    handlers fire. This is essential because many offer-page forms
    enable/show subsequent fields only after a dropdown is set, and
    server-side validation blocks submit if any required select is
    untouched. The placeholder `{{header}}` remains in the recorded
    step → RUT engine substitutes per-lead at replay time.
    """
    sess.touch()
    if not selector:
        return {"recorded": False, "error": "selector required"}
    if not value and not header_name:
        return {"recorded": False, "error": "either value or header_name required"}
    chosen = f"{{{{{header_name}}}}}" if header_name else str(value)
    match_by_norm = match_by if match_by in ("label", "value") else "label"
    step = {
        "action": "select",
        "selector": selector,
        "value": chosen,
        "match_by": match_by_norm,
    }
    # 2026-05 — attach fallbacks stashed by the dropdown click.
    try:
        _fb_map = getattr(sess, "_pending_dropdown_fallbacks", None)
        if isinstance(_fb_map, dict):
            _fb_sel = _fb_map.get(selector)
            if _fb_sel:
                step["fallbacks"] = _fb_sel
                # 2026-06 — also surface xpath as a top-level editable
                # field so the operator can SEE both selector AND xpath
                # in the Edit Step UI, and RUT replay has both rescue
                # paths at the top level.
                _xs = (_fb_sel.get("xpath") or _fb_sel.get("xpath_abs") or "").strip()
                if _xs and not step.get("xpath"):
                    step["xpath"] = _xs
            # one-shot — drop entry so the next dropdown starts clean
            _fb_map.pop(selector, None)
    except Exception:
        pass
    # ── 2026-05: Carry custom-UI hints from the dropdown click ──
    # If the <select> is hidden behind Bootstrap-Select / Select2 / etc,
    # the recording-time click stashed metadata on the session. We copy
    # it onto the step so the RUT replay engine can skip the (useless)
    # visibility pre-wait and go straight to the JS-driven select path
    # — saves ~5s of phase-1 wait time per dropdown per visit.
    meta = getattr(sess, "_pending_dropdown_meta", None)
    if meta and meta.get("selector") == selector:
        if meta.get("is_hidden_select"):
            # Engine reads this and routes wait_for_selector to
            # state="attached" (vs default "visible") for THIS step,
            # AND skips the visibility pre-wait entirely.
            step["state"] = "attached"
            step["prefer_js_set"] = True
        if meta.get("wrapper_kind"):
            step["wrapper_kind"] = meta["wrapper_kind"]
        # one-shot — clear after use so the next dropdown click starts clean
        try:
            delattr(sess, "_pending_dropdown_meta")
        except Exception:
            pass
    sess.append_step(step)
    # 2026-01 — auto wait(500) removed per user request.
    # Brief settle wait so subsequent steps see the post-change DOM
    # is no longer auto-appended. User can insert a wait manually if needed.

    # Live-browser select using literal value OR sample-row lookup
    # OR fallback faker (2026-01) so the dropdown always gets a value
    # during recording even when sample_row is empty or missing this col.
    live_val: Optional[str] = None
    if value:
        live_val = str(value)
    elif header_name:
        live_val = _resolve_live_value(sess, header_name)
    extra: Dict[str, Any] = {}
    if live_val is not None:
        async with sess.lock:
            ok, used = await _smart_select_option(sess.page, selector, live_val, match_by_norm)
            if ok:
                extra["selected_sample"] = (used or live_val)[:30]
            else:
                extra["select_warning"] = (
                    f"Live <select> did not accept '{live_val}' (tried multiple variants). "
                    "Step recorded anyway; verify the option matches one of the dropdown values."
                )
    else:
        extra["sample_hint"] = (
            "No sample data — provide a literal `value` or supply "
            "`sample_row` at session start so this dropdown gets a "
            "value during recording (so you can submit the form and "
            "continue recording on the NEXT page)."
        )
    return {"recorded": True, "step": step, **extra}


async def bind_sheet_pick(
    sess: RecorderSession,
    header_name: str,
    clicked_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Finalise a sheet-pick binding started by a ``mode='sheet_pick'`` click."""
    sess.touch()
    hn = (header_name or "").strip()
    if not hn:
        return {"recorded": False, "error": "header_name required"}
    try:
        step = _build_sheet_pick_evaluate(hn)
    except ValueError as e:
        return {"recorded": False, "error": str(e)}
    sess.append_step(step)

    extra: Dict[str, Any] = {}
    live_val = _resolve_live_value(sess, hn)
    if live_val:
        click_label = (
            _normalize_gender_click_label(live_val)
            if _is_gender_header(hn)
            else str(live_val).strip()
        )
        clicked_norm = (clicked_text or "").strip().lower()
        target_norm = click_label.strip().lower()
        if not clicked_norm or clicked_norm != target_norm:
            try:
                live_js = _build_text_click_evaluate(click_label)
                async with sess.lock:
                    await sess.page.evaluate(live_js["script"])
                extra["clicked_sample"] = click_label[:40]
            except Exception as e:  # noqa: BLE001
                extra["click_warning"] = (
                    f"Live page could not click '{click_label}' ({type(e).__name__}). "
                    "Step recorded anyway — verify the column value matches a button label."
                )
        else:
            extra["clicked_sample"] = click_label[:40]
    else:
        extra["sample_hint"] = (
            f"No sample data for column '{hn}'. Upload Excel before recording "
            "so the live page selects the correct button during recording."
        )
    return {"recorded": True, "step": step, "header_name": hn, **extra}


async def bind_gender_pick(
    sess: RecorderSession,
    header_name: str,
    button_labels: List[str],
) -> Dict[str, Any]:
    """Record a gender step after the user clicked Male + Female buttons."""
    sess.touch()
    hn = (header_name or "").strip()
    if not hn:
        return {"recorded": False, "error": "header_name required"}
    labels = [(lb or "").strip() for lb in (button_labels or []) if (lb or "").strip()]
    if len(labels) < 2:
        return {
            "recorded": False,
            "error": "Add at least 2 gender buttons (Male and Female) before binding",
        }
    male_labels, female_labels = _split_gender_button_labels(labels)
    if not male_labels or not female_labels:
        return {
            "recorded": False,
            "error": (
                "Could not tell which button is Male vs Female — use labels like "
                "Male/Female or M/F"
            ),
        }
    try:
        step = _build_gender_pick_evaluate(hn, male_labels, female_labels)
    except ValueError as e:
        return {"recorded": False, "error": str(e)}
    sess.append_step(step)

    extra: Dict[str, Any] = {
        "male_labels": male_labels,
        "female_labels": female_labels,
    }
    live_val = _resolve_live_value(sess, hn)
    if live_val:
        side = _classify_gender_side(str(live_val)) or _classify_gender_side(
            _normalize_gender_click_label(str(live_val))
        )
        pick_pool = male_labels if side == "male" else female_labels if side == "female" else []
        click_label = pick_pool[0] if pick_pool else _normalize_gender_click_label(str(live_val))
        try:
            live_js = _build_text_click_evaluate(click_label)
            async with sess.lock:
                await sess.page.evaluate(live_js["script"])
            extra["clicked_sample"] = click_label[:40]
        except Exception as e:  # noqa: BLE001
            extra["click_warning"] = (
                f"Live page could not click '{click_label}' ({type(e).__name__}). "
                "Step recorded anyway."
            )
    else:
        extra["sample_hint"] = (
            f"No sample data for column '{hn}'. Upload Excel before recording "
            "so the live page selects the correct gender during recording."
        )
    return {"recorded": True, "step": step, "header_name": hn, **extra}


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


async def _smart_select_option(page: Any, selector: str, live_val: str, match_by: str) -> Tuple[bool, Optional[str]]:
    """Try selecting an <option> using a comprehensive variant list so
    common date / state / number dropdowns work even when the recorded
    value's format differs from the option attribute.

    Variants tried (in order, from `value_normalizer.expand_value_variants`):
      - the live_val as-is + case variants
      - zero-padded / un-padded numeric ("6" ↔ "06")
      - month-name variants ("6" ↔ "June" ↔ "Jun")
      - US state code ↔ full name ("TX" ↔ "Texas")
      - Canadian province code ↔ full name ("ON" ↔ "Ontario")
      - boolean variants ("y" ↔ "yes" ↔ "true" ↔ "1")
      - date parsed → all formats (split fields too: year, month, day)

    PHASE 1 (instant, ~10ms): JS-driven set via page.evaluate. Sets the
    underlying <select>.value AND dispatches native `input`+`change`
    events plus jQuery .trigger('change') + selectpicker.refresh +
    chosen:updated — so any custom UI wrapper (Bootstrap-Select / Select2
    / Chosen / React-Select / nice-select / generic-custom) re-renders
    its visible widget and any form validators see the change. THIS is
    the fix for the "dropdown shows empty / Next button does nothing"
    bug on custom-UI offer forms.

    PHASE 2 (fallback, slower): Playwright's `page.select_option()`
    against each variant × (label, value) — only reached if PHASE 1
    didn't succeed (e.g. cross-origin iframe).

    Returns (success, variant_used).
    """
    val = str(live_val).strip()
    if not val:
        return False, None

    try:
        from value_normalizer import expand_value_variants
        candidates: List[str] = expand_value_variants(live_val)
    except Exception:
        # Defensive: if module fails to import for any reason, fall back
        # to the raw value only — the loop below will still attempt it.
        candidates = [val]
    if not candidates:
        candidates = [val]

    # ── PHASE 1: JS-driven set (works for hidden / custom-UI selects) ──
    _js_set_select = """
    (function(args) {
        var selector  = args.selector;
        var rawList   = args.rawList && args.rawList.length ? args.rawList : [args.raw];
        var byLabel   = args.byLabel;
        function findOpt(el, raw, byLabel) {
            var want = String(raw);
            var wantTrim = want.trim().toLowerCase();
            for (var i = 0; i < el.options.length; i++) {
                var o = el.options[i];
                if (byLabel) {
                    var t = (o.text || '').trim().toLowerCase();
                    var l = (o.label || '').trim().toLowerCase();
                    if (t === wantTrim || l === wantTrim) return o;
                } else {
                    if (String(o.value) === want) return o;
                }
            }
            // Try the OTHER strategy if the primary didn't match
            for (var i = 0; i < el.options.length; i++) {
                var o = el.options[i];
                if (byLabel) {
                    if (String(o.value) === want) return o;
                } else {
                    var t = (o.text || '').trim().toLowerCase();
                    if (t === wantTrim) return o;
                }
            }
            return null;
        }
        var el = null;
        try { el = document.querySelector(selector); } catch (e) { return {ok: false}; }
        if (!el || el.tagName !== 'SELECT') return {ok: false};
        var opt = null;
        for (var r = 0; r < rawList.length && !opt; r++) {
            opt = findOpt(el, rawList[r], byLabel);
        }
        if (!opt) return {ok: false};
        el.value = opt.value;
        try { el.dispatchEvent(new Event('input',  {bubbles: true})); } catch (e) {}
        try { el.dispatchEvent(new Event('change', {bubbles: true})); } catch (e) {}
        try {
            if (window.jQuery && window.jQuery(el).length) {
                window.jQuery(el).val(opt.value).trigger('change');
                try { window.jQuery(el).selectpicker('refresh'); } catch (e) {}
                try { window.jQuery(el).trigger('chosen:updated'); } catch (e) {}
            }
        } catch (e) {}
        // Blur after change — some forms validate on blur, not change.
        try { el.dispatchEvent(new Event('blur', {bubbles: true})); } catch (e) {}
        return {ok: true, value: opt.value, label: opt.text};
    })
    """
    try:
        js_result = await asyncio.wait_for(
            page.evaluate(
                _js_set_select,
                {
                    "selector": selector,
                    "raw": val,
                    "rawList": candidates,
                    "byLabel": (match_by != "value"),
                },
            ),
            timeout=4.0,
        )
        if isinstance(js_result, dict) and js_result.get("ok"):
            return True, js_result.get("label") or js_result.get("value") or val
    except Exception:
        pass

    # ── PHASE 2: Playwright select_option fallback ──
    primary_modes = ("label", "value") if match_by != "value" else ("value", "label")
    for candidate in candidates:
        for mode in primary_modes:
            try:
                if mode == "label":
                    await page.select_option(selector, label=candidate, timeout=2000)
                else:
                    await page.select_option(selector, value=candidate, timeout=2000)
                return True, candidate
            except Exception:
                continue
    return False, None


def _make_selector_for_input(info: Dict[str, Any]) -> str:
    """Build a CSS selector for an input given its DOM info."""
    name = info.get("name") or ""
    placeholder = info.get("placeholder") or ""
    id_ = info.get("id") or ""
    aria = info.get("aria") or ""
    type_ = info.get("type") or ""
    if id_:
        return f"#{id_}"
    if name:
        return f"input[name='{name}']"
    if placeholder:
        return f"input[placeholder='{placeholder}']"
    if aria:
        return f"input[aria-label='{aria}']"
    if type_:
        return f"input[type='{type_}']"
    return "input"


async def type_text(sess: RecorderSession, selector: str, value: str, header_name: Optional[str] = None) -> Dict[str, Any]:
    """Type into the element matched by `selector`. If header_name is set,
    the recorded step uses `{{header_name}}` placeholder so the RUT engine
    substitutes from the Excel row at runtime.

    ── 2026-05 ──
    If `value` is empty AND a `header_name` is set, automatically fill
    the live browser with the value from `sample_row[header_name]` so
    the user can navigate to the next page without manually typing.
    This makes one-click "bind to column" recording workflow feasible.
    """
    sess.touch()
    # ── 2026-05 (defense-in-depth) ──
    # Some older clients send `value="{{first}}"` (the literal
    # placeholder) when binding to a header — that string was then
    # typed into the live form, the field failed validation, and the
    # user couldn't submit. We detect a `{{...}}` placeholder in
    # `value` and treat it as a binding marker — the live browser is
    # filled with the resolved sample value, not the literal text.
    import re
    placeholder_match = re.fullmatch(r"\s*\{\{\s*([^}]+?)\s*\}\}\s*", value or "")
    if placeholder_match and not header_name:
        header_name = placeholder_match.group(1).strip()
    if placeholder_match:
        value = ""  # treat as empty so the sample-row branch fires
    # Resolve the value to ACTUALLY type into the live browser. The
    # recorded JSON step still uses the `{{header}}` placeholder so
    # RUT replays with the real lead's data.
    # 2026-01: fall back to faker default when sample_row missing the col
    # so the live form fills even without Excel data uploaded.
    live_val = value
    if (not live_val) and header_name:
        live_val = _resolve_live_value(sess, header_name)
    extra: Dict[str, Any] = {}
    async with sess.lock:
        if live_val:
            fill_ok, fill_extra = await _fill_live_input(sess.page, selector, live_val)
            extra.update(fill_extra)
            if not fill_ok:
                logger.warning(
                    f"type fill failed selector={selector}: {extra.get('fill_warning', '')}"
                )
        elif header_name:
            extra["sample_hint"] = (
                f"No sample value for column '{header_name}'. Upload an "
                "Excel file BEFORE starting the recorder so the live form "
                "fills automatically (you'll be able to submit and "
                "continue recording on the next page)."
            )

    template = f"{{{{{header_name}}}}}" if header_name else value
    step = _build_fill_step(selector, template)
    # 2026-05 — attach fallbacks captured by the earlier form_fill click
    # for THIS selector (if any). Without this, the second /type call
    # would lose the rich rescue paths and skip on a renamed input.
    try:
        _fb_map = getattr(sess, "_form_fill_fallbacks", None)
        if isinstance(_fb_map, dict):
            _fb_sel = _fb_map.get(selector)
            if _fb_sel:
                step["fallbacks"] = _fb_sel
    except Exception:
        pass
    sess.append_step(step)
    # 2026-01 — auto wait removed per user request (was wait(800) here).
    return {"recorded": True, "step": step, "header_name": header_name, **extra}


async def add_wait_step(sess: RecorderSession, ms: int) -> Dict[str, Any]:
    sess.touch()
    step = _build_wait(ms)
    sess.append_step(step, allow_auto_waits=False)
    return {"recorded": True, "step": step}


async def add_wait_load_step(sess: RecorderSession, timeout_ms: int = 60000) -> Dict[str, Any]:
    sess.touch()
    step = _build_wait_load(timeout_ms)
    sess.append_step(step, allow_auto_waits=False)
    return {"recorded": True, "step": step}


async def add_scroll_step(sess: RecorderSession, y: int) -> Dict[str, Any]:
    sess.touch()
    async with sess.lock:
        try:
            await sess.page.mouse.wheel(0, int(y))
        except Exception:
            pass
    step = _build_scroll(y)
    sess.append_step(step)
    # 2026-01 — auto wait(500) after scroll removed per user request.
    return {"recorded": True, "step": step}


async def navigate_to(sess: RecorderSession, url: str) -> Dict[str, Any]:
    """Navigate the page to a new URL. Records a `goto` step ONLY — auto
    wait_for_load / wait steps are no longer appended (2026-01 — per user
    request). The runtime engine's own goto already waits for
    domcontentloaded; add an explicit wait step from the recorder UI if a
    specific page needs a longer settle delay."""
    sess.touch()
    async with sess.lock:
        try:
            await sess.page.goto(url, wait_until="load", timeout=45000)
        except Exception as e:
            logger.warning(f"navigate failed: {e}")
    # NOTE: previously auto-appended _build_wait_load(60000) + _build_wait(2000)
    # here — removed per user request to prevent over-padded playback that
    # blew past the stuck-watchdog window.
    return {"recorded": True, "url": url}


async def mark_final(sess: RecorderSession) -> Dict[str, Any]:
    """Capture the current screenshot as the conversion target."""
    sess.touch()
    folder = SESSIONS_ROOT / sess.session_id
    folder.mkdir(parents=True, exist_ok=True)
    target_path = folder / "target_screenshot.png"
    async with sess.lock:
        try:
            await sess.page.screenshot(path=str(target_path), type="png", full_page=False)
            sess.target_screenshot_path = str(target_path)
            sess.final_url = sess.page.url
            try:
                txt = await sess.page.evaluate("() => (document.body.innerText || '').slice(0, 280)")
                sess.final_text_snippet = (txt or "").strip()
            except Exception:
                sess.final_text_snippet = None
        except Exception as e:
            logger.warning(f"mark_final failed: {e}")
            return {"recorded": False, "error": str(e)}
    return {
        "recorded": True,
        "target_screenshot_path": sess.target_screenshot_path,
        "final_url": sess.final_url,
        "final_text_snippet": sess.final_text_snippet,
    }


async def group_last_as_random(
    sess: RecorderSession,
    count: int,
    texts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build & append one random-pick step.

    Two input modes:
      1. Legacy (click-to-pool): caller has clicked N candidate buttons
         in mode=random and they're sitting in ``sess._pending_random``.
         Pass ``texts=None`` and we'll use the last ``count`` of them.
      2. NEW (checklist flow, 2026-01): caller passes ``texts`` directly
         (selected from /detect-clickables) — we skip the pending list
         entirely. This avoids the user having to click each button
         on the live page (which would navigate it forward and break
         the recording).

    Either way, the resulting JSON step is identical and the playback
    behaviour (``_build_random_pick_evaluate``) is unchanged.
    """
    sess.touch()
    # ── 2026-01 checklist path ─────────────────────────────────────
    if texts:
        take = [str(t).strip() for t in texts if str(t).strip()]
        if not take:
            return {"recorded": False, "error": "No non-empty texts supplied"}
    else:
        pending = getattr(sess, "_pending_random", None) or []
        if not pending:
            return {"recorded": False, "error": "No pending random elements — use mode=random click first OR pass texts directly"}
        take = pending[-int(count):]
    step = _build_random_pick_evaluate(take)
    sess.append_step(step)
    # 2026-01 — auto wait(2000) + wait_for_load(60000) + wait(2500) after
    # random-pick removed per user request. The random-pick JS itself
    # navigates the page when it clicks an <a> with href; subsequent
    # steps' selector timeouts will naturally wait for the new DOM.
    sess._pending_random = []
    return {"recorded": True, "step": step, "items": take}


async def navigate_only_click(sess: RecorderSession, x: int, y: int) -> Dict[str, Any]:
    """Perform a real click at (x, y) on the live page WITHOUT
    appending any step to the recording.

    Use case (2026-01): the Random Pick step contains its own random-
    button-click JavaScript; at recording time the user still needs
    to advance the live browser to the next page so they can record
    subsequent steps. Clicking with the normal "Click" tool would
    add an extra (unwanted) step. This endpoint performs the click
    purely for navigation purposes.
    """
    sess.touch()
    async with sess.lock:
        try:
            await sess.page.mouse.click(int(x), int(y))
        except Exception as e:  # noqa: BLE001
            return {"clicked": False, "error": f"{type(e).__name__}: {e}"}
    return {"clicked": True, "recorded": False}


async def _fill_live_input(page: Any, selector: str, live_val: str) -> Tuple[bool, Dict[str, Any]]:
    """Fill a live input during recording (no step appended).

    Shared by ``type_text`` (recorded fill steps) and ``manual_type_at``
    (Fix Type tool — correction only, zero JSON steps).
    """
    extra: Dict[str, Any] = {}
    fill_ok = False
    fill_err: Optional[str] = None
    if not live_val:
        return False, extra
    try:
        await page.fill(selector, live_val, timeout=6000)
        _got = await page.evaluate(
            "(s) => { var e = document.querySelector(s); return e ? (e.value != null ? e.value : (e.innerText || '')) : ''; }",
            selector,
        )
        if isinstance(_got, str) and _got.strip() == live_val.strip():
            fill_ok = True
            extra["filled_sample"] = live_val[:30]
    except Exception as e:
        fill_err = f"fill: {type(e).__name__}: {str(e)[:80]}"
    if not fill_ok:
        try:
            await page.click(selector, timeout=4000)
            try:
                await page.click(selector, click_count=3, timeout=1500)
                await page.keyboard.press("Backspace")
            except Exception:
                pass
            await page.keyboard.type(live_val, delay=25)
            _got2 = await page.evaluate(
                "(s) => { var e = document.querySelector(s); return e ? (e.value != null ? e.value : (e.innerText || '')) : ''; }",
                selector,
            )
            if isinstance(_got2, str) and live_val.strip() in _got2:
                fill_ok = True
                extra["filled_sample"] = live_val[:30]
                extra["fill_strategy"] = "keyboard"
        except Exception as e:
            fill_err = (fill_err or "") + f" | keyboard: {type(e).__name__}: {str(e)[:80]}"
    if not fill_ok:
        try:
            await page.evaluate(
                """([s, v]) => {
                    var e = document.querySelector(s);
                    if (!e) return;
                    try {
                        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                        if (setter && setter.set) { setter.set.call(e, v); }
                        else { e.value = v; }
                    } catch(_) { try { e.value = v; } catch(__){} }
                    try { e.dispatchEvent(new Event('input', {bubbles:true})); } catch(_){}
                    try { e.dispatchEvent(new Event('change', {bubbles:true})); } catch(_){}
                }""",
                [selector, live_val],
            )
            fill_ok = True
            extra["filled_sample"] = live_val[:30]
            extra["fill_strategy"] = "js_set"
        except Exception as e:
            fill_err = (fill_err or "") + f" | js: {type(e).__name__}: {str(e)[:80]}"
    if not fill_ok:
        extra["fill_warning"] = (fill_err or "all strategies failed")[:200]
    elif fill_ok and selector:
        # Blur so React / TrustedForm / Jornaya validators see a
        # "finished typing" event before the next Continue click.
        try:
            await page.evaluate(
                """(s) => {
                    var e = document.querySelector(s);
                    if (!e) return;
                    try { e.dispatchEvent(new Event('blur', {bubbles:true})); } catch(_){}
                }""",
                selector,
            )
        except Exception:
            pass
    return fill_ok, extra


async def manual_type_at(sess: RecorderSession, x: int, y: int, value: str) -> Dict[str, Any]:
    """Type into an input at (x, y) WITHOUT recording a step.

    Use case (2026-07): Form Fill may auto-type a wrong sample value
    during recording (e.g. zip typo). The operator fixes the live field
    with this tool — same idea as Move / nav_only for clicks.
    """
    sess.touch()
    live_val = str(value or "").strip()
    if not live_val:
        return {"typed": False, "recorded": False, "error": "value required"}
    async with sess.lock:
        info = await sess.page.evaluate(_RICH_ELEMENT_CAPTURE_JS, [int(x), int(y)])
        if not info:
            return {"typed": False, "recorded": False, "error": "No element at that point"}
        tag = (info.get("tag") or "").upper()
        attrs = info.get("attrs") or {}
        type_attr = (attrs.get("type") or info.get("type") or "").lower()
        is_editable = (
            tag in ("INPUT", "TEXTAREA")
            or bool(info.get("contenteditable"))
            or type_attr in ("text", "email", "tel", "number", "search", "password", "")
        )
        if not is_editable:
            return {
                "typed": False,
                "recorded": False,
                "error": "That is not a text field — click an input/textarea to fix its value.",
            }
        selector = _make_selector_for_input(info)
        try:
            await sess.page.mouse.click(info.get("x") or int(x), info.get("y") or int(y))
        except Exception:
            pass
        fill_ok, extra = await _fill_live_input(sess.page, selector, live_val)
    if not fill_ok:
        return {
            "typed": False,
            "recorded": False,
            "selector": selector,
            **extra,
        }
    return {
        "typed": True,
        "recorded": False,
        "selector": selector,
        **extra,
    }


async def detect_clickables(sess: RecorderSession) -> Dict[str, Any]:
    """Detect every visible clickable element on the current page and
    return their visible text + bounding box. Used by the new "Random
    Pick" checklist UI so the user doesn't have to click each candidate
    button on the live page (which would navigate it away).

    Selectors covered: <a>, <button>, <input type=submit/button/reset>,
    elements with role=button / role=link / role=checkbox / role=radio,
    <label> elements, and any element with onclick / cursor:pointer.

    De-duped by trimmed text + tag (so the same "Continue" button isn't
    listed twice). Hidden (display:none / visibility:hidden / zero-size)
    elements are skipped.

    ── 2026-06 (LABEL/SPAN dedup) ──
    Customer feedback: the random pool was showing each answer button
    twice — once as `LABEL` and once as `SPAN` — because lead-gen offer
    pages typically wrap each option in `<label><span>Less than $5k
    </span></label>`. Both the outer LABEL (caught by selector match)
    AND the inner SPAN (caught by cursor:pointer + no-children) made it
    into the candidate list with identical text, confusing the operator.
    We now skip an element if any of its ancestors is ALSO in the
    candidate set with the SAME trimmed text — i.e. we keep only the
    OUTERMOST clickable for each distinct text. Behaviour for non-nested
    duplicates (e.g. two separate "Continue" buttons in different
    sections) is unchanged: both still appear.
    """
    sess.touch()
    async with sess.lock:
        try:
            items = await sess.page.evaluate(
                r"""
                () => {
                    const SEL = 'a, button, input[type=submit], input[type=button], input[type=reset], [role=button], [role=link], [role=checkbox], [role=radio], label, [onclick]';
                    const candidates = Array.from(document.querySelectorAll(SEL));
                    // Add elements with cursor:pointer that haven't already
                    // been picked up by the selector above.
                    const all = Array.from(document.body ? document.body.querySelectorAll('*') : []);
                    for (const el of all) {
                        if (candidates.indexOf(el) !== -1) continue;
                        try {
                            const cs = window.getComputedStyle(el);
                            if (cs && cs.cursor === 'pointer' && el.children.length === 0) {
                                candidates.push(el);
                            }
                        } catch (e) {}
                    }

                    // 2026-06 LABEL/SPAN dedup pre-pass — build a set of
                    // candidate elements first so we can check "is any
                    // ancestor also a candidate with the same text?"
                    // before deciding whether to emit this one.
                    const candSet = new Set(candidates);
                    const normText = (el) => ((el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim());

                    const seen = new Set();
                    const out = [];
                    for (const el of candidates) {
                        try {
                            const cs = window.getComputedStyle(el);
                            if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') < 0.05) continue;
                            const r = el.getBoundingClientRect();
                            if (r.width < 4 || r.height < 4) continue;
                            const rawText = normText(el);
                            if (!rawText) continue;
                            const text = rawText.slice(0, 200);
                            const tag = el.tagName;

                            // 2026-06 — Skip this element if ANY ancestor
                            // (up to <body>) is also in the candidate set
                            // AND has the same trimmed text. The ancestor
                            // will be emitted instead, so the user sees
                            // ONE row per option (e.g. only LABEL, not
                            // LABEL + nested SPAN). We compare against
                            // the ancestor's RAW text — slicing matches
                            // happens after this check.
                            let suppressed = false;
                            let p = el.parentElement;
                            let depthGuard = 0;
                            while (p && depthGuard < 12) {
                                if (candSet.has(p)) {
                                    const ptxt = normText(p);
                                    if (ptxt && ptxt === rawText) {
                                        suppressed = true;
                                        break;
                                    }
                                }
                                p = p.parentElement;
                                depthGuard++;
                            }
                            if (suppressed) continue;

                            const key = tag + '||' + text.toLowerCase();
                            if (seen.has(key)) continue;
                            seen.add(key);
                            out.push({
                                text: text,
                                tag: tag,
                                role: el.getAttribute('role') || '',
                                type: el.type || '',
                                href: (el.getAttribute && el.getAttribute('href')) || '',
                                x: Math.round(r.left + r.width / 2),
                                y: Math.round(r.top + r.height / 2),
                                width: Math.round(r.width),
                                height: Math.round(r.height),
                                top: Math.round(r.top),
                            });
                        } catch (e) {}
                    }
                    // Sort by visual order (top → bottom, left → right)
                    out.sort((a, b) => (a.top - b.top) || (a.x - b.x));
                    return out;
                }
                """
            )
        except Exception as e:  # noqa: BLE001
            return {"items": [], "error": f"detect failed: {type(e).__name__}: {e}"}
    return {"items": items or [], "count": len(items or [])}


def remove_step(sess: RecorderSession, index: int) -> Dict[str, Any]:
    sess.touch()
    if 0 <= index < len(sess.steps):
        removed = sess.steps.pop(index)
        return {"removed": removed, "remaining": len(sess.steps)}
    return {"removed": None, "remaining": len(sess.steps)}


def move_step(sess: RecorderSession, index: int, direction: str) -> Dict[str, Any]:
    """Move a step up or down in the recorded list. `direction` ∈ {'up','down'}.
    Returns the swap result + new index, or no-op if out of bounds."""
    sess.touch()
    n = len(sess.steps)
    if not (0 <= index < n):
        return {"moved": False, "reason": "index out of range"}
    target = index - 1 if direction == "up" else index + 1
    if not (0 <= target < n):
        return {"moved": False, "reason": "edge"}
    sess.steps[index], sess.steps[target] = sess.steps[target], sess.steps[index]
    return {"moved": True, "from": index, "to": target}


def move_step_to(sess: RecorderSession, from_index: int, to_index: int) -> Dict[str, Any]:
    """2026-01 (additive): drag-and-drop reorder. Removes the step at
    `from_index` and re-inserts it at `to_index`. Both indices are
    clamped to the current array length. Returns updated total + new
    position, or no-op if from == to."""
    sess.touch()
    n = len(sess.steps)
    if not (0 <= from_index < n):
        return {"moved": False, "reason": f"from_index {from_index} out of range (have {n} steps)"}
    # Clamp to_index (drag-drop UI may overshoot by 1 when dropping at end)
    to_idx = max(0, min(int(to_index), n - 1))
    if from_index == to_idx:
        return {"moved": False, "reason": "from == to"}
    step = sess.steps.pop(from_index)
    sess.steps.insert(to_idx, step)
    return {"moved": True, "from": from_index, "to": to_idx, "total": len(sess.steps)}


def duplicate_step(sess: RecorderSession, index: int) -> Dict[str, Any]:
    """Insert a deep copy of the step at `index` right after it."""
    sess.touch()
    if not (0 <= index < len(sess.steps)):
        return {"duplicated": False, "reason": "index out of range"}
    import copy as _copy
    clone = _copy.deepcopy(sess.steps[index])
    sess.steps.insert(index + 1, clone)
    return {"duplicated": True, "step": clone, "new_index": index + 1}


def rename_step(sess: RecorderSession, index: int, name: str) -> Dict[str, Any]:
    """Set / update the `name` field of an existing step (purely a label,
    surfaced by the UI + Live Activity panel during the job run)."""
    sess.touch()
    if not (0 <= index < len(sess.steps)):
        return {"renamed": False, "reason": "index out of range"}
    sess.steps[index]["name"] = (name or "").strip() or None
    return {"renamed": True, "name": sess.steps[index].get("name")}


# Fields that the UI is allowed to patch on an existing recorded step.
# We deliberately do NOT allow changing `action` (that would break replay
# semantics — user should delete + record a new step instead). The
# `humanize` flag (new 2026-01) lets the user opt OUT of slow per-char
# human typing for individual fill/type steps when speed matters more
# than stealth (e.g. live-test debugging, internal forms).
_EDITABLE_STEP_FIELDS = {
    "selector", "value", "timeout", "key", "ms",
    "state", "delay", "match_by", "humanize", "name",
    # 2026-01 additive — new step type fields
    "text", "contains", "equals", "pattern",
    "store_key", "var", "attribute", "regex",
    "retry", "retry_delay", "if_exists", "if_exists_timeout",
    "case_insensitive", "wait_nav", "optional",
    "max_iterations", "iteration_wait_ms", "stop_on_host",
    # 2026-05 — manual fallback editor. Lets the user paste xpath / text
    # / attrs onto an existing step so RUT replay has rescue paths even
    # when the original recording captured only a brittle CSS selector.
    # See visual_recorder._build_fallbacks for the schema.
    "fallbacks",
    # 2026-06 — surfaced xpath field on evaluate-action click steps so
    # the Edit Step panel can show/override it (paired with the
    # `step["xpath"]` set inside click_at). Replay engine reads this
    # via `_step_fallbacks` so the value participates in the rescue
    # chain even though the primary mechanism remains the embedded JS.
    "xpath",
    # 2026-05 — random-pick advanced editor. Lets the operator edit
    # an existing evaluate step to add per-option selector/xpath
    # fallbacks. See _build_random_pick_advanced.
    "pick_options",
    # 2026-02 — branch step (conditional if/else-if/else). Nested step
    # arrays are passed through verbatim by the dict-validator below.
    "branches", "default_steps", "timeout_ms",
}


def update_step(sess: RecorderSession, index: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update one or more whitelisted fields on an existing step.
    Used by the new "Edit step" UI modal in the Visual Recorder when a
    live-test reveals a wrong selector / too-low timeout / etc. Does NOT
    re-execute the step against the live browser — the new values take
    effect on the NEXT Live Test or RUT run.

    Whitelisted fields: see `_EDITABLE_STEP_FIELDS`.
    `action` is intentionally read-only (changing it would break replay).

    Returns include `alias_saved` flag (True iff a selector rename was
    persisted to the global Selector Aliases store for self-healing
    future replays).
    """
    sess.touch()
    if not (0 <= index < len(sess.steps)):
        return {"updated": False, "reason": "index out of range"}
    if not isinstance(patch, dict):
        return {"updated": False, "reason": "patch must be a dict"}

    step = sess.steps[index]
    old_selector = step.get("selector") or ""
    applied: Dict[str, Any] = {}
    for k, v in patch.items():
        if k not in _EDITABLE_STEP_FIELDS:
            continue
        # Normalise empty strings to None for optional text fields so the
        # downstream replay doesn't see "" and try to act on it.
        # 2026-05 — pick_options / fallbacks must NOT be caught by the
        # generic string branch (a malformed string input would slip
        # into `step[k]` untouched and break the replay engine). They
        # have dedicated dict/list validators below.
        if isinstance(v, str) and k not in ("pick_options", "fallbacks"):
            v_clean = v.strip()
            if k in ("value", "name", "match_by", "state"):
                step[k] = v_clean or None
            elif k in ("selector", "key"):
                # Selector / key are required-ish — keep as empty string
                # if user explicitly cleared (caller's responsibility to
                # validate before saving in the UI).
                step[k] = v_clean
            else:
                step[k] = v_clean
            applied[k] = step[k]
        elif k in ("timeout", "ms", "delay") and v is not None:
            try:
                step[k] = max(0, int(v))
                applied[k] = step[k]
            except (TypeError, ValueError):
                continue
        elif k == "humanize":
            step[k] = bool(v)
            applied[k] = step[k]
        elif k == "fallbacks":
            # 2026-05 — manual fallback editor support.
            # Accept ONLY a dict; sanitise to the schema produced by
            # `_build_fallbacks` (recorder side) + extra string/list
            # safety so the user can't inject 100KB blobs through the
            # UI. If user sends None or {} we DELETE the key so the
            # step doesn't carry an empty fallbacks dict.
            if v is None or (isinstance(v, dict) and not v):
                if "fallbacks" in step:
                    del step["fallbacks"]
                applied[k] = None
                continue
            if not isinstance(v, dict):
                continue
            clean: Dict[str, Any] = {}
            for fk in ("xpath", "xpath_abs", "text", "tag"):
                fv = v.get(fk)
                if isinstance(fv, str):
                    fv = fv.strip()
                    if fv and len(fv) <= 500:
                        clean[fk] = fv
            nth_in = v.get("nth")
            if isinstance(nth_in, int) and 1 <= nth_in <= 9999:
                clean["nth"] = nth_in
            attrs_in = v.get("attrs")
            if isinstance(attrs_in, dict):
                a_clean: Dict[str, str] = {}
                for ak, av in attrs_in.items():
                    if not isinstance(ak, str) or len(ak) > 64:
                        continue
                    if isinstance(av, str) and av and len(av) <= 200:
                        a_clean[ak] = av
                if a_clean:
                    clean["attrs"] = a_clean
            if clean:
                step["fallbacks"] = clean
                applied[k] = clean
            else:
                # All fields stripped out — treat as a clear.
                if "fallbacks" in step:
                    del step["fallbacks"]
                applied[k] = None
        elif k == "pick_options":
            # 2026-05 — Random-pick advanced editor. Replaces script
            # with freshly-built evaluate JS that tries CSS → xpath →
            # text-contains per option.
            if not isinstance(v, list):
                continue
            clean_opts = []
            for o in v:
                if not isinstance(o, dict):
                    continue
                t = (o.get("text") or "").strip()[:200]
                s = (o.get("selector") or "").strip()[:500]
                x = (o.get("xpath") or "").strip()[:500]
                if t or s or x:
                    clean_opts.append({"text": t, "selector": s, "xpath": x})
            if clean_opts:
                rebuilt = _build_random_pick_advanced(clean_opts)
                step["action"] = "evaluate"
                step["script"] = rebuilt["script"]
                step["pick_options"] = clean_opts
                applied[k] = clean_opts
            else:
                if "pick_options" in step:
                    del step["pick_options"]
                applied[k] = []
        else:
            step[k] = v
            applied[k] = v
    return {"updated": True, "applied": applied, "step": step, "_old_selector": old_selector}


async def update_step_with_alias(sess: RecorderSession, index: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Async wrapper around `update_step` that ALSO persists a selector
    alias when the user changed the selector — the cornerstone of
    self-healing replay. Saves under (sess.user_id, sess.url domain,
    old_selector → new_selector). Best-effort: if the aliases store is
    unreachable, the edit still succeeds and we just skip the save."""
    result = update_step(sess, index, patch)
    if not result.get("updated"):
        return result

    old_sel = result.pop("_old_selector", "") or ""
    new_sel = (result.get("applied") or {}).get("selector")
    alias_saved = False
    if new_sel and old_sel and new_sel.strip() != old_sel.strip():
        try:
            import selector_aliases as _sa
            domain = _sa.extract_domain(sess.url or "")
            if domain and sess.user_id:
                alias_saved = await _sa.save_alias(sess.user_id, domain, old_sel, new_sel)
        except Exception:
            alias_saved = False
    result["alias_saved"] = alias_saved
    return result


# Whitelisted action types for "manual add step" — these can be added
# without browser interaction (just appended to sess.steps). Replay
# happens during Live Test / RUT run. We don't allow `goto` from
# manual-add since that's better done by starting a new recording at
# the new URL.
_MANUAL_STEP_ACTIONS = {
    "wait_for_selector", "click", "fill", "type", "select", "press",
    "wait", "wait_for_load", "wait_for_navigation", "wait_for_networkidle",
    "hover", "check", "uncheck", "screenshot",
    # 2026-01 additive — new step types from automation_extensions
    "wait_for_text", "wait_for_url", "extract", "dismiss_popups",
    "auto_continue", "auto_continue_survey",
    # 2026-02 additive — conditional branching (if/else-if/else)
    "branch",
    # 2026-06 additive — multi-tab control. `switch_tab` lets RUT
    # return to a prior tab (e.g. after finishing one deal on a new
    # tab, switch back to the listing tab to start the next deal).
    # `close_tab` is the safe-close counterpart so a recipe can clean
    # up the per-deal popup before moving on.
    "switch_tab", "close_tab",
}


def add_manual_step(sess: RecorderSession, step: Dict[str, Any], position: Optional[int] = None) -> Dict[str, Any]:
    """Append (or insert at `position`) a manually-authored step into the
    recorder session. Used by the new "Add Manual Step" UI button when
    the user needs to inject a step that the auto-recorder didn't pick
    up (e.g., hidden field needing an XPath selector). Validates the
    action type against the whitelist; selector / value pass-through
    unchanged so the user can supply BOTH CSS (`#x`, `[name=x]`) and
    XPath (`//input[@name="x"]`, `xpath=//div`) — Playwright auto-
    detects xpath at replay time. Returns the inserted step + new
    index."""
    sess.touch()
    if not isinstance(step, dict):
        return {"added": False, "reason": "step must be a dict"}
    action = (step.get("action") or "").strip().lower()
    if action not in _MANUAL_STEP_ACTIONS:
        return {
            "added": False,
            "reason": f"action '{action}' not allowed for manual add. "
                      f"Allowed: {sorted(_MANUAL_STEP_ACTIONS)}",
        }

    # Build a clean step dict — only keep known fields, normalise types.
    clean: Dict[str, Any] = {"action": action}
    for k in ("selector", "value", "key", "state", "match_by", "name",
              # 2026-01 additive — new step type fields
              "text", "contains", "equals", "pattern",
              "store_key", "var", "attribute", "regex",
              # 2026-06 additive — switch_tab/close_tab diagnostic URL
              "url"):
        v = step.get(k)
        if v is not None and str(v).strip() != "":
            clean[k] = str(v).strip()
    for k in ("timeout", "ms", "delay",
              # 2026-01 additive — retry config + per-iteration tunables
              "retry", "retry_delay", "if_exists_timeout",
              "max_iterations", "iteration_wait_ms",
              # 2026-06 additive — switch_tab/close_tab tab index
              "index"):
        v = step.get(k)
        if v is not None:
            try:
                clean[k] = max(0, int(v))
            except (TypeError, ValueError):
                pass
    if "humanize" in step:
        clean["humanize"] = bool(step["humanize"])
    if "if_exists" in step:
        clean["if_exists"] = bool(step["if_exists"])
    if "case_insensitive" in step:
        clean["case_insensitive"] = bool(step["case_insensitive"])
    if "wait_nav" in step:
        clean["wait_nav"] = bool(step["wait_nav"])
    if "optional" in step:
        clean["optional"] = bool(step["optional"])
    # 2026-02 — `branch` action carries nested step lists & per-branch
    # conditions. Preserve them verbatim so raw-JSON authors can paste
    # arbitrary branch trees without losing data on round-trip.
    if action == "branch":
        if isinstance(step.get("branches"), list):
            clean["branches"] = step["branches"]
        if isinstance(step.get("default_steps"), list):
            clean["default_steps"] = step["default_steps"]
        if "timeout_ms" in step:
            try:
                clean["timeout_ms"] = max(0, int(step["timeout_ms"]))
            except (TypeError, ValueError):
                pass
    # Tag this step so the UI can show a small "manual" badge — purely
    # cosmetic, doesn't affect replay.
    clean["source"] = "manual"

    # Default timeouts so users don't have to set them every time.
    if action in ("wait_for_selector", "click", "fill", "type", "select", "hover", "check", "uncheck") and "timeout" not in clean:
        clean["timeout"] = 8000
    if action == "wait" and "ms" not in clean:
        clean["ms"] = 1000
    if action in ("wait_for_text", "wait_for_url", "extract") and "timeout" not in clean:
        clean["timeout"] = 15000

    # Insert at position (clamped to valid range) or append.
    n = len(sess.steps)
    if position is None or not isinstance(position, int):
        idx = n
    else:
        idx = max(0, min(int(position), n))
    sess.steps.insert(idx, clean)
    return {"added": True, "step": clean, "index": idx, "total": len(sess.steps)}


def import_steps(sess: RecorderSession, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bulk-replace the session's steps with the provided list (used
    when the user clicks "Live Visual Test" on the finalized Recording
    Complete screen: a fresh recorder session is spawned with the same
    url/proxy/UA, then the saved JSON is imported here, then a live
    test is fired so the user can visually verify the full automation
    step by step). Validates each step is a dict with a known action
    type; otherwise rejects the import to prevent runtime crashes."""
    sess.touch()
    if not isinstance(steps, list):
        return {"imported": False, "reason": "steps must be a list"}
    # Light validation — accept any dict with `action` string, since the
    # replay engine handles unknown actions defensively.
    cleaned: List[Dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        action = (s.get("action") or "").strip().lower()
        if not action:
            continue
        # Copy the step so we don't mutate the caller's data
        cleaned.append(dict(s))
    sess.steps = cleaned
    return {"imported": True, "total": len(cleaned)}


def update_session_data(sess: RecorderSession, *, sample_row: Optional[Dict[str, Any]] = None,
                         headers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Update the sample row / headers on an active session — used when
    the "Live Visual Test" reuses a finalized bundle and needs to push
    the same sample data into the new session before replay."""
    sess.touch()
    if sample_row is not None and isinstance(sample_row, dict):
        sess.sample_row = sample_row
    if headers is not None and isinstance(headers, list):
        sess.headers = [str(h) for h in headers if h]
    return {"ok": True, "headers": sess.headers, "sample_row": getattr(sess, "sample_row", None)}


async def suggest_selectors(sess: RecorderSession, failed_selector: str, limit: int = 8) -> Dict[str, Any]:
    """Smart Selector Suggester (2026-01) — when a step fails because
    the recorded selector no longer matches the page, query the LIVE
    DOM for nearby candidates that look similar and rank them.

    Used by the Edit-step modal's "🔍 Find similar selectors" button.
    Returns a list of candidate selectors with metadata so the user can
    one-click swap the failed selector for the right one.

    Strategy:
      1. Extract identifier tokens from the failed selector
         (e.g., `#birth_month` → ["birth", "month"];
          `[name="dob_year"]` → ["dob", "year"];
          `//input[@id='first']` → ["first"]).
      2. In a single page.evaluate() call, scan all form-relevant
         elements (input/select/textarea/button) and score each by
         how many tokens appear in its id/name/class/aria-label/
         placeholder/label text.
      3. Return top `limit` candidates sorted by score, each with a
         ready-to-paste CSS selector + tag + visible label preview.
    """
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"suggestions": [], "error": f"Session not ready ({sess.state})"}

    sel = (failed_selector or "").strip()
    if not sel:
        return {"suggestions": [], "error": "empty selector"}

    # ── Token extraction (handles CSS id/name attr + xpath patterns) ─
    import re as _re
    tokens: List[str] = []

    # #id
    for m in _re.finditer(r"#([\w\-]+)", sel):
        tokens.append(m.group(1))
    # [name="x"], [id="x"], [name=x], [id=x]
    for m in _re.finditer(r"\[(?:name|id)\s*=\s*[\"']?([\w\-]+)[\"']?\]", sel):
        tokens.append(m.group(1))
    # xpath @id='x' / @name='x'
    for m in _re.finditer(r"@(?:name|id)\s*=\s*[\"']([\w\-]+)[\"']", sel):
        tokens.append(m.group(1))
    # If the selector itself is a bare word (no special chars), use it
    if not tokens and _re.match(r"^[\w\-]+$", sel):
        tokens.append(sel)

    # Sub-tokens (split on _ - space camelCase)
    sub: List[str] = []
    for t in tokens:
        for piece in _re.split(r"[_\-\s]+", t):
            if piece and len(piece) >= 2:
                sub.append(piece.lower())
        # camelCase → snake-ish
        for piece in _re.findall(r"[A-Z]?[a-z]+", t):
            if piece and len(piece) >= 2:
                sub.append(piece.lower())
    # Dedup preserving order
    seen: set = set()
    search_tokens: List[str] = []
    for t in sub:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            search_tokens.append(tl)
    if not search_tokens:
        return {"suggestions": [], "error": "could not extract tokens from selector", "tokens": []}

    # ── Run DOM scan in browser ──────────────────────────────────────
    js = """
    (params) => {
      const tokens = params.tokens.map(t => t.toLowerCase());
      const candidates = [];
      const els = document.querySelectorAll('input, select, textarea, button, [contenteditable=true]');
      function visibleLabel(el) {
        // Linked <label for=id>
        const id = el.getAttribute('id');
        if (id) {
          const lab = document.querySelector('label[for="' + CSS.escape(id) + '"]');
          if (lab && lab.innerText) return lab.innerText.trim().slice(0, 60);
        }
        // Ancestor <label> wrapping the field
        const parentLab = el.closest('label');
        if (parentLab && parentLab.innerText) return parentLab.innerText.trim().slice(0, 60);
        // aria-label
        const aria = el.getAttribute('aria-label');
        if (aria) return aria.trim().slice(0, 60);
        // placeholder fallback
        const ph = el.getAttribute('placeholder');
        if (ph) return ph.trim().slice(0, 60);
        return '';
      }
      function isVisible(el) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return false;
        const cs = window.getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
        return true;
      }
      els.forEach(el => {
        const id = (el.getAttribute('id') || '').toLowerCase();
        const name = (el.getAttribute('name') || '').toLowerCase();
        const cls = (el.getAttribute('class') || '').toLowerCase();
        const aria = (el.getAttribute('aria-label') || '').toLowerCase();
        const ph = (el.getAttribute('placeholder') || '').toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        const label = visibleLabel(el).toLowerCase();
        const haystack = [id, name, cls, aria, ph, label].join(' | ');
        let score = 0;
        let matched = [];
        tokens.forEach(t => {
          if (!t) return;
          if (id === t) { score += 10; matched.push(t); return; }
          if (name === t) { score += 8; matched.push(t); return; }
          if (id.includes(t) || name.includes(t)) { score += 5; matched.push(t); return; }
          if (aria.includes(t) || ph.includes(t) || label.includes(t)) { score += 3; matched.push(t); return; }
          if (cls.includes(t)) { score += 1; matched.push(t); return; }
        });
        if (score <= 0) return;
        // Build a stable selector — prefer #id, then [name=], then nth-of-type tag
        let suggested = '';
        if (id) {
          suggested = '#' + id;
        } else if (name) {
          suggested = el.tagName.toLowerCase() + '[name="' + name + '"]';
        } else if (aria) {
          suggested = el.tagName.toLowerCase() + '[aria-label="' + el.getAttribute('aria-label') + '"]';
        } else {
          // fallback: nth-of-type within parent
          const parent = el.parentElement;
          if (parent) {
            const sibs = Array.from(parent.children).filter(c => c.tagName === el.tagName);
            const idx = sibs.indexOf(el);
            suggested = el.tagName.toLowerCase() + ':nth-of-type(' + (idx + 1) + ')';
          } else {
            suggested = el.tagName.toLowerCase();
          }
        }
        candidates.push({
          selector: suggested,
          tag: el.tagName.toLowerCase(),
          input_type: type || null,
          id: id || null,
          name: name || null,
          label: visibleLabel(el) || null,
          placeholder: el.getAttribute('placeholder') || null,
          visible: isVisible(el),
          matched_tokens: matched,
          score: score,
        });
      });
      // Sort by score DESC, then visible first
      candidates.sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        return (b.visible ? 1 : 0) - (a.visible ? 1 : 0);
      });
      return candidates.slice(0, params.limit);
    }
    """

    try:
        async with sess.lock:
            results = await sess.page.evaluate(js, {"tokens": search_tokens, "limit": int(limit)})
    except Exception as e:
        return {"suggestions": [], "error": f"DOM scan failed: {e}", "tokens": search_tokens}

    return {
        "suggestions": results or [],
        "tokens": search_tokens,
        "failed_selector": sel,
    }


async def selector_bbox(sess: RecorderSession, selector: str) -> Dict[str, Any]:
    """Return the bounding box of the first element matching `selector`
    on the LIVE page, in CSS pixel coordinates relative to the
    viewport. Used by the Edit modal's "hover-to-preview" feature
    to draw a blue outline overlay on the screenshot.

    Returns:
      { found: bool, x, y, width, height,
        viewport: {width, height}, error?: str }
    """
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"found": False, "error": f"Session not ready ({sess.state})"}
    sel = (selector or "").strip()
    if not sel:
        return {"found": False, "error": "empty selector"}

    # Playwright auto-detects XPath when selector starts with `//`, `..`,
    # or `xpath=` — no special handling needed here. We just call
    # query_selector and bounding_box; both work for CSS + XPath.
    try:
        async with sess.lock:
            el = await sess.page.query_selector(sel)
            if el is None:
                # Get viewport size for debugging
                vp = sess.page.viewport_size or {"width": 0, "height": 0}
                return {"found": False, "error": "Element not found", "viewport": vp}
            bbox = await el.bounding_box()
            vp = sess.page.viewport_size or {"width": 0, "height": 0}
            if bbox is None:
                return {"found": False, "error": "Element has no bounding box (likely hidden)", "viewport": vp}
            return {
                "found": True,
                "x": float(bbox.get("x", 0)),
                "y": float(bbox.get("y", 0)),
                "width": float(bbox.get("width", 0)),
                "height": float(bbox.get("height", 0)),
                "viewport": vp,
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


async def press_key(sess: RecorderSession, key: str) -> Dict[str, Any]:
    """Send a single keyboard key press to the page (Enter, Tab, Escape,
    Backspace, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, PageDown, etc.).
    Step is recorded so it replays during the RUT run."""
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"recorded": False, "error": f"Session not ready ({sess.state})"}
    safe_key = (key or "").strip()
    if not safe_key:
        return {"recorded": False, "error": "key required"}
    try:
        await sess.page.keyboard.press(safe_key)
    except Exception as e:
        return {"recorded": False, "error": f"Key press failed: {e}"}
    step = {"action": "press", "key": safe_key}
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def hover_at(sess: RecorderSession, x: int, y: int) -> Dict[str, Any]:
    """Hover the mouse over an (x,y) page coordinate. Useful for menus
    that only reveal on hover. Step is recorded so it replays."""
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"recorded": False, "error": f"Session not ready ({sess.state})"}
    try:
        await sess.page.mouse.move(int(x), int(y))
    except Exception as e:
        return {"recorded": False, "error": f"Hover failed: {e}"}
    step = {
        "action": "evaluate",
        "script": (
            "(function(){var el=document.elementFromPoint("
            + str(int(x)) + "," + str(int(y)) +
            ");if(el){el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));"
            "el.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));}})();"
        ),
        "name": f"Hover @ ({int(x)},{int(y)})",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def wait_for_selector(
    sess: RecorderSession, selector: str, timeout_ms: int = 15000
) -> Dict[str, Any]:
    """Wait until a CSS selector becomes visible on the page (max
    `timeout_ms`). Useful when an offer takes a variable time to load
    a CTA. Step is recorded — RUT will wait the same way at replay."""
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"recorded": False, "error": f"Session not ready ({sess.state})"}
    sel = (selector or "").strip()
    if not sel:
        return {"recorded": False, "error": "selector required"}
    timeout_ms = max(500, min(int(timeout_ms or 15000), 120000))
    try:
        await sess.page.wait_for_selector(sel, state="visible", timeout=timeout_ms)
    except Exception as e:
        return {"recorded": False, "error": f"Selector did not appear within {timeout_ms}ms: {e}"}
    step = {"action": "wait_for_selector", "selector": sel, "timeout": timeout_ms}
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ─────────────────────────────────────────────────────────────────────
# 2026-01 v2.4.2 — Three additive helpers requested by customer:
#   • wait_for_xpath           — sibling to wait_for_selector, uses xpath
#   • scan_element_at          — inspect an element's text/selector/xpath
#                                without recording a step or clicking it
#   • detect_popup_buttons     — like detect_clickables but scoped to
#                                any currently-visible popup/modal/dialog
# All three follow the same session/lock/return pattern as the existing
# helpers above. Zero changes to any existing function/step schema.
# ─────────────────────────────────────────────────────────────────────

async def wait_for_xpath(
    sess: RecorderSession, xpath: str, timeout_ms: int = 15000
) -> Dict[str, Any]:
    """Wait until an XPath expression matches a visible element on the
    page (max `timeout_ms`). Records an equivalent `wait_for_selector`
    step with the `xpath=` Playwright prefix — RUT replay hits the
    same engine as the CSS-selector wait, no runtime branching needed.
    Customer ask: "wait for selector button k sath wait for xpath b
    hona chahye agr wait for selector ko selector na mile to wait for
    xpath use kr liya jay yan customer jo chahe use kr sake"."""
    sess.touch()
    if sess.state != "ready" or not sess.page:
        return {"recorded": False, "error": f"Session not ready ({sess.state})"}
    xp = (xpath or "").strip()
    if not xp:
        return {"recorded": False, "error": "xpath required"}
    # Playwright's `xpath=` prefix is the canonical way to pass raw
    # xpath to page.wait_for_selector. It also accepts a bare xpath
    # starting with "/" or "//" so we normalise defensively.
    engine_sel = xp if xp.startswith("xpath=") else f"xpath={xp}"
    timeout_ms = max(500, min(int(timeout_ms or 15000), 120000))
    try:
        await sess.page.wait_for_selector(engine_sel, state="visible", timeout=timeout_ms)
    except Exception as e:
        return {"recorded": False, "error": f"XPath did not appear within {timeout_ms}ms: {e}"}
    # Store BOTH the engine-prefixed selector (for the RUT wait engine
    # that already understands `xpath=…`) AND a bare `xpath` field
    # (for the step-editor UI + selector-fallback logic that expects
    # `step.xpath` — same convention used by _attach_selector_and_xpath).
    step = {
        "action": "wait_for_selector",
        "selector": engine_sel,
        "xpath": xp,
        "timeout": timeout_ms,
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def scan_element_at(sess: RecorderSession, x: int, y: int) -> Dict[str, Any]:
    """Return the text / css-selector / xpath / attributes of whatever
    element sits under (x, y) — WITHOUT clicking it and WITHOUT
    recording a step. Powers the "Scan" tool: customer clicks a
    button on the live preview and gets a copy-able set of locators
    they can reuse anywhere (RPA Studio, wait_for_selector, manual
    click steps, etc). Customer ask: "scan button use kr k page pr
    kisi b button pr click krein to oska text, selector, xpath show
    ho jay jo customer use kr k kahin b use kr sake"."""
    sess.touch()
    async with sess.lock:
        if sess.state != "ready" or not sess.page:
            return {"ok": False, "error": f"Session not ready ({sess.state})"}
        try:
            info = await sess.page.evaluate(
                _RICH_ELEMENT_CAPTURE_JS,
                [int(x), int(y)],
            )
        except Exception as e:
            return {"ok": False, "error": f"Could not scan element: {e}"}
        if not info:
            return {"ok": False, "error": "No element at that point"}
        # 2026-07 v2.5.4 — Build a solid CSS selector using the same
        # priority ladder (data-testid → id → name → aria-label → tag+text)
        # that the recorded steps use, so the "Copy selector" button
        # in the UI returns something that ACTUALLY resolves at replay
        # time. Before this fix, `info["selector"]` was empty (the JS
        # captured attrs but never composed a selector) so the UI
        # showed a blank selector string for many scanned elements.
        _selector_synth = ""
        _tmp_step: Dict[str, Any] = {}
        try:
            _attach_selector_and_xpath(_tmp_step, info)
            _selector_synth = _tmp_step.get("selector", "") or ""
        except Exception:
            _selector_synth = ""
        # Extra fallbacks if the primary ladder didn't produce anything.
        if not _selector_synth:
            attrs = info.get("attrs") or {}
            tag_l = (info.get("tag") or "").lower()
            aria = attrs.get("aria-label") if isinstance(attrs, dict) else None
            if isinstance(aria, str) and aria:
                aria_esc = aria.replace('"', '\\"')[:60]
                _selector_synth = f'{tag_l}[aria-label="{aria_esc}"]' if tag_l else f'[aria-label="{aria_esc}"]'
            elif tag_l:
                cls = attrs.get("class") if isinstance(attrs, dict) else ""
                if isinstance(cls, str) and cls.strip():
                    # Pick the first stable-looking class token
                    tokens = [c for c in cls.split() if c and not any(x in c.lower() for x in ("hover", "active", "focus", "js-"))]
                    if tokens:
                        _selector_synth = f"{tag_l}.{tokens[0]}"
                    else:
                        _selector_synth = tag_l
                else:
                    _selector_synth = tag_l

        # Existing info["selector"] wins if it happened to be present
        # (some future JS revision might populate it).
        selector_final = (info.get("selector") or "").strip() or _selector_synth

        out: Dict[str, Any] = {
            "ok": True,
            "text": (info.get("text") or "").strip(),
            "selector": selector_final,
            "xpath": (info.get("xpath_stable") or info.get("xpath_abs") or "").strip(),
            "xpath_stable": (info.get("xpath_stable") or "").strip(),
            "xpath_abs": (info.get("xpath_abs") or "").strip(),
            "tag": (info.get("tag") or "").upper(),
            "attrs": info.get("attrs") or {},
            "bbox": {
                "x": info.get("x"),
                "y": info.get("y"),
                "w": info.get("w"),
                "h": info.get("h"),
            },
        }
        return out


# 2026-07 v2.5.4 — Wait-for-button: click any button in the live preview
# and record a `wait_for_selector` step targeting that exact button —
# NO click is fired on the page, only a wait-until-visible step is
# appended. Useful when the target page loads content lazily: the
# customer picks the button they know will eventually appear, and
# during replay RUT pauses until it materialises before proceeding.
# Customer ask: "wait for button ka aik feature ho jay osko use kr k
# jis b button ye link pr click krein to wo os k ane tak wait kre
# jab wo show ho tab process start ho jay".
async def add_wait_for_button_at(
    sess: RecorderSession, x: int, y: int, timeout_ms: int = 30000,
) -> Dict[str, Any]:
    sess.touch()
    cap = await _capture_element_locators(sess, x, y)
    if not cap.get("ok"):
        return {"recorded": False, "error": cap.get("error", "Could not read element")}
    selector = cap.get("selector") or ""
    xpath = cap.get("xpath") or ""
    text = cap.get("text") or ""

    if not selector and not xpath:
        return {"recorded": False, "error": "Could not derive a selector/xpath for this element — try clicking a different part of the button."}

    timeout_ms = max(500, min(int(timeout_ms or 30000), 300000))
    step: Dict[str, Any] = {
        "action": "wait_for_selector",
        "timeout": timeout_ms,
        "origin": "wait_for_button",
    }
    if selector:
        step["selector"] = selector
    if xpath:
        step["xpath"] = xpath
    if text:
        step["hint_text"] = text
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def _capture_element_locators(
    sess: RecorderSession, x: int, y: int,
) -> Dict[str, Any]:
    """Read element under (x,y) and derive text / CSS selector / xpath."""
    async with sess.lock:
        if sess.state != "ready" or not sess.page:
            return {"ok": False, "error": f"Session not ready ({sess.state})"}
        try:
            info = await sess.page.evaluate(
                _RICH_ELEMENT_CAPTURE_JS,
                [int(x), int(y)],
            )
        except Exception as e:
            return {"ok": False, "error": f"Could not read element: {e}"}
        if not info:
            return {"ok": False, "error": "No element at that point"}

    _tmp_step: Dict[str, Any] = {}
    try:
        _attach_selector_and_xpath(_tmp_step, info)
    except Exception:
        pass
    selector = (_tmp_step.get("selector") or "").strip()
    xpath = (
        (_tmp_step.get("xpath") or "")
        or (info.get("xpath_stable") or info.get("xpath_abs") or "")
    ).strip()
    text = ((info.get("text") or "").strip())[:120]
    attrs = info.get("attrs") or {}
    if not text and isinstance(attrs, dict):
        for key in ("aria-label", "placeholder", "title", "value", "alt"):
            val = attrs.get(key)
            if isinstance(val, str) and val.strip():
                text = val.strip()[:120]
                break
    if not selector and not xpath and text:
        esc = text.replace('"', '\\"')[:80]
        selector = f'text="{esc}"'
    return {"ok": True, "selector": selector, "xpath": xpath, "text": text, "info": info}


async def add_wait_for_text_at(
    sess: RecorderSession, x: int, y: int, timeout_ms: int = 15000,
) -> Dict[str, Any]:
    """Point-and-click wait_for_text — auto-detect visible text at (x,y)."""
    sess.touch()
    cap = await _capture_element_locators(sess, x, y)
    if not cap.get("ok"):
        return {"recorded": False, "error": cap.get("error", "Could not read element")}
    text = (cap.get("text") or "").strip()
    if len(text) < 2:
        return {
            "recorded": False,
            "error": "No readable text on this element — click the visible label or button text.",
        }
    timeout_ms = max(500, min(int(timeout_ms or 15000), 300000))
    step: Dict[str, Any] = {
        "action": "wait_for_text",
        "text": text,
        "timeout": timeout_ms,
        "case_insensitive": True,
        "origin": "wait_for_text_pick",
    }
    if cap.get("selector"):
        step["hint_selector"] = cap["selector"]
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def add_wait_for_xpath_at(
    sess: RecorderSession, x: int, y: int, timeout_ms: int = 15000,
) -> Dict[str, Any]:
    """Point-and-click xpath wait — records step without live wait."""
    sess.touch()
    cap = await _capture_element_locators(sess, x, y)
    if not cap.get("ok"):
        return {"recorded": False, "error": cap.get("error", "Could not read element")}
    xpath = (cap.get("xpath") or "").strip()
    if not xpath:
        return {"recorded": False, "error": "Could not derive xpath — try Wait for selector or Scan."}
    timeout_ms = max(500, min(int(timeout_ms or 15000), 300000))
    engine_sel = xpath if xpath.startswith("xpath=") else f"xpath={xpath}"
    step: Dict[str, Any] = {
        "action": "wait_for_selector",
        "selector": engine_sel,
        "xpath": xpath,
        "timeout": timeout_ms,
        "origin": "wait_for_xpath_pick",
    }
    if cap.get("text"):
        step["hint_text"] = cap["text"]
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def add_wait_for_selector_at(
    sess: RecorderSession, x: int, y: int, timeout_ms: int = 15000,
) -> Dict[str, Any]:
    """Point-and-click CSS selector wait — same as wait-for-button."""
    result = await add_wait_for_button_at(sess, x, y, timeout_ms)
    if result.get("recorded") and isinstance(result.get("step"), dict):
        result["step"]["origin"] = "wait_for_selector_pick"
    return result


# JS run by detect_popup_buttons — finds visible popup / dialog / modal
# containers on the page using multiple heuristics (role attribute, aria-
# modal, common CSS class names, fixed-positioned high-z overlays), then
# for each container extracts every clickable inside (buttons, links,
# inputs, [role=button], onclick, cursor:pointer). Same shape as
# detect_clickables().items so the front-end can reuse the checklist UI.
#
# 2026-01 v2.6.28 — Bug fixes to Popup Work:
#   1. VISIBILITY FILTER — previously the class-based selector (`.modal`,
#      `.popup`, etc.) matched hidden containers too. Landing pages
#      often have 3-5 template popups sitting in the DOM with
#      display:none; the user only sees 1. We now apply the same
#      display/visibility/opacity/size gate to ALL candidates (not
#      just the ad-hoc overlay scan) so `popup_count` matches what the
#      user actually sees.
#   2. RICHER ITEM METADATA — each detected clickable now carries
#      `element_kind` = "text_input" | "textarea" | "select" |
#      "checkbox" | "radio" | "button" | "link" | "generic". The
#      front-end uses this to auto-pick the right recorder tool
#      (Form Fill for text_input, Dropdown for select, Check Box for
#      checkbox/radio, Click for the rest) so the operator can
#      Form-Fill / Dropdown / Check-Box INSIDE popups too, not just
#      Click them. Customer ask: "agr click form fill wale button b
#      use krein to wo b sab es pr use hun".
#   3. INPUT-TYPE LABELS — inputs / textareas now get their
#      placeholder / name / aria-label as the label (instead of the
#      useless "Button #N" fallback) so the popup checklist row shows
#      "Email address" not "Button #3".
_DETECT_POPUP_BUTTONS_JS = r"""
() => {
  const out = [];

  // ── Helper: is the element visibly on screen right now? ───────────
  const isVisible = (el) => {
    try {
      const cs = window.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (parseFloat(cs.opacity || '1') < 0.05) return false;
      const r = el.getBoundingClientRect();
      if (r.width < 20 || r.height < 20) return false;
      // Off-screen (below-fold DOM template popups often live at y=99999)
      if (r.bottom < 0 || r.top > (window.innerHeight || 10000) + 200) return false;
      if (r.right < 0 || r.left > (window.innerWidth || 10000) + 200) return false;
      return true;
    } catch (e) { return false; }
  };

  // ── Step 1: find popup / modal / dialog containers ────────────────
  // v2.6.30 — same-origin iframe scan (survey funnels often render
  // modals inside iframes; top-document-only scan missed them).
  function iframeSelector(iframeEl) {
    if (iframeEl.id) return 'iframe#' + iframeEl.id;
    if (iframeEl.getAttribute && iframeEl.getAttribute('name'))
      return 'iframe[name="' + iframeEl.getAttribute('name') + '"]';
    if (iframeEl.getAttribute && iframeEl.getAttribute('data-testid'))
      return 'iframe[data-testid="' + iframeEl.getAttribute('data-testid') + '"]';
    var src = (iframeEl.src || '').trim();
    if (src) {
      var m = src.match(/([^/?#]+)(?:[?#].*)?$/);
      if (m && m[1]) return 'iframe[src*="' + m[1].replace(/"/g, '\\"') + '"]';
    }
    var idx = 1, sib = iframeEl.previousElementSibling;
    while (sib) {
      if (sib.tagName === 'IFRAME' || sib.tagName === 'FRAME') idx++;
      sib = sib.previousElementSibling;
    }
    return 'iframe:nth-of-type(' + idx + ')';
  }

  const isVisibleInDoc = (el) => {
    try {
      const cs = window.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (parseFloat(cs.opacity || '1') < 0.05) return false;
      const r = el.getBoundingClientRect();
      if (r.width < 20 || r.height < 20) return false;
      return true;
    } catch (e) { return false; }
  };

  const popupSel = [
    '[role="dialog"]',
    '[role="alertdialog"]',
    '[aria-modal="true"]',
    '.modal',
    '.popup',
    '.dialog',
    '.overlay',
    '.lightbox',
    '.drawer',
    '.MuiDialog-root',
    '.ant-modal',
    '.ReactModal__Content',
    '.chakra-modal__content',
    '.swal2-container',
    '.sweet-alert',
    '.fancybox-container',
    '[class*="alert" i]',
    '[class*="modal-content" i]',
    '[class*="modal-dialog" i]',
    '[class*="popup-content" i]',
  ].join(', ');

  const popupEntries = [];

  function collectPopupsInDoc(doc, ox, oy, iframePath) {
    const win = doc.defaultView || window;
    const candidates = Array.from(doc.querySelectorAll(popupSel)).filter(isVisibleInDoc);

    const vw = win.innerWidth || doc.documentElement.clientWidth || 1;
    const vh = win.innerHeight || doc.documentElement.clientHeight || 1;
    const vwvh = vw * vh;
    const scanRoot = doc.body ? doc.body.querySelectorAll('*') : [];
    for (const el of scanRoot) {
      if (candidates.indexOf(el) !== -1) continue;
      try {
        const cs = win.getComputedStyle(el);
        const pos = cs.position;
        if (pos !== 'fixed' && pos !== 'absolute') continue;
        const zi = parseFloat(cs.zIndex || '0');
        if (!(zi >= 100)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 100 || r.height < 100) continue;
        const area = r.width * r.height;
        if (area / vwvh < 0.10) continue;
        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') < 0.15) continue;
        candidates.push(el);
      } catch (e) { /* skip */ }
    }

    for (const el of candidates) {
      popupEntries.push({ el: el, ox: ox, oy: oy, iframePath: iframePath.slice() });
    }

    doc.querySelectorAll('iframe, frame').forEach((ifr) => {
      try {
        const idoc = ifr.contentDocument;
        if (!idoc) return;
        const ir = ifr.getBoundingClientRect();
        collectPopupsInDoc(
          idoc,
          ox + ir.left,
          oy + ir.top,
          iframePath.concat([iframeSelector(ifr)])
        );
      } catch (e) { /* cross-origin */ }
    });
  }

  collectPopupsInDoc(document, 0, 0, []);

  // De-dupe: if a container is nested inside another container we keep
  // ONLY the inner one (buttons live at the leaf of the popup tree).
  const kept = popupEntries.filter((entry) =>
    !popupEntries.some((other) =>
      other.el !== entry.el && other.el.contains && other.el.contains(entry.el)
    )
  );

  // v2.6.55 — TOP POPUP ONLY: enumerate buttons inside the modal the
  // user actually sees at the viewport center — NOT every high-z layer,
  // backdrop, or hidden template still sitting in the DOM.
  function effectiveZ(el) {
    var z = 0;
    var n = el;
    var win = (el.ownerDocument && el.ownerDocument.defaultView) || window;
    while (n && n.nodeType === 1 && n !== (el.ownerDocument && el.ownerDocument.documentElement)) {
      try {
        var cs = win.getComputedStyle(n);
        if (cs.position && cs.position !== 'static') {
          var zi = parseInt(cs.zIndex, 10);
          if (!isNaN(zi)) z = Math.max(z, zi);
        }
      } catch (e) { /* skip */ }
      n = n.parentElement;
    }
    return z;
  }

  function coversCenter(el) {
    var r = el.getBoundingClientRect();
    var cx = (window.innerWidth || 0) / 2;
    var cy = (window.innerHeight || 0) / 2;
    return cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom;
  }

  function isTopHit(el, doc) {
    try {
      var r = el.getBoundingClientRect();
      var cx = r.left + r.width / 2;
      var cy = r.top + r.height / 2;
      var d = doc || document;
      var stack = [];
      if (d.elementsFromPoint) {
        try { stack = d.elementsFromPoint(cx, cy) || []; } catch (e) { stack = []; }
      }
      if (!stack.length) {
        var one = d.elementFromPoint(cx, cy);
        if (one) stack = [one];
      }
      for (var i = 0; i < stack.length; i++) {
        var h = stack[i];
        if (h === el || (el.contains && el.contains(h))) return true;
      }
    } catch (e) { /* skip */ }
    return false;
  }

  function isPopupLikeNode(node) {
    if (!node || node.nodeType !== 1) return false;
    try {
      if (node.matches) {
        var parts = popupSel.split(',');
        for (var pi = 0; pi < parts.length; pi++) {
          var sel = parts[pi].trim();
          if (sel && node.matches(sel) && isVisibleInDoc(node)) return true;
        }
      }
      var cs = window.getComputedStyle(node);
      var pos = cs.position;
      if (pos === 'fixed' || pos === 'absolute') {
        var zi = parseFloat(cs.zIndex || '0');
        var r = node.getBoundingClientRect();
        if (zi >= 50 && r.width >= 80 && r.height >= 80 && isVisibleInDoc(node)) return true;
      }
    } catch (e) { /* skip */ }
    return false;
  }

  function findPopupAtViewportCenter() {
    var cx = (window.innerWidth || 0) / 2;
    var cy = (window.innerHeight || 0) / 2;
    return findPopupAtPoint(document, cx, cy, 0, 0, []);
  }

  function findPopupAtPoint(doc, px, py, ox, oy, iframePath) {
    var stack = [];
    try {
      stack = doc.elementsFromPoint ? doc.elementsFromPoint(px, py) : [];
    } catch (e) { stack = []; }
    if (!stack.length) {
      var one = doc.elementFromPoint(px, py);
      if (one) stack = [one];
    }
    for (var si = 0; si < stack.length; si++) {
      var node = stack[si];
      if (!node || node.nodeType !== 1) continue;
      if (node.tagName === 'IFRAME' || node.tagName === 'FRAME') {
        try {
          var idoc = node.contentDocument;
          if (idoc) {
            var ir = node.getBoundingClientRect();
            var innerHit = findPopupAtPoint(
              idoc, px - ir.left, py - ir.top,
              ox + ir.left, oy + ir.top,
              iframePath.concat([iframeSelector(node)])
            );
            if (innerHit) return innerHit;
          }
        } catch (e) { /* cross-origin */ }
      }
      var walk = node;
      while (walk && walk !== doc.body) {
        if (isPopupLikeNode(walk)) {
          var best = null;
          for (var ki = 0; ki < kept.length; ki++) {
            var ent = kept[ki];
            if (ent.el === walk || (ent.el.contains && ent.el.contains(walk))) {
              if (!best || effectiveZ(ent.el) >= effectiveZ(best.el)) best = ent;
            }
          }
          if (best) return best;
          return { el: walk, ox: ox, oy: oy, iframePath: iframePath.slice() };
        }
        walk = walk.parentElement;
      }
    }
    return null;
  }

  var centerPopup = findPopupAtViewportCenter();
  var scanPopups = [];
  if (centerPopup) {
    scanPopups = [centerPopup];
  } else if (kept.length) {
    var pool = kept.filter(function(e) { return coversCenter(e.el); });
    if (!pool.length) pool = kept.slice();
    pool.sort(function(a, b) { return effectiveZ(b.el) - effectiveZ(a.el); });
    scanPopups = [pool[0]];
  }

  // ── Step 2: enumerate clickables inside the TOP popup only ────────
  // v2.6.28 — Widened selector so form fields (text inputs, textareas,
  //           <select>) are also detected. The front-end will route
  //           them to Form Fill / Dropdown / Check Box tools instead
  //           of the default Click.
  const BTN_SEL = 'a, button, input, textarea, select, [role=button], [role=link], [role=checkbox], [role=radio], [aria-label*="close" i], [aria-label*="dismiss" i], [aria-label*="cancel" i], label, [onclick], [class*="close" i], [class*="dismiss" i], [data-dismiss], [data-close]';
  const normText = (el) => (
    (el.innerText || el.textContent || el.value ||
     el.getAttribute('aria-label') || el.getAttribute('title') || '')
      .replace(/\s+/g, ' ').trim()
  );

  // v2.6.28 — Classify each element so the UI can auto-pick the right
  // recorder tool (Form Fill / Dropdown / Check Box / Click).
  const classifyKind = (el) => {
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'SELECT') return 'select';
    if (tag === 'TEXTAREA') return 'textarea';
    if (tag === 'INPUT') {
      const t = ((el.getAttribute('type') || 'text') + '').toLowerCase();
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio')    return 'radio';
      if (t === 'submit' || t === 'button' || t === 'reset' || t === 'image')
        return 'button';
      if (t === 'file') return 'file';
      // text / email / password / number / search / tel / url / date / …
      return 'text_input';
    }
    if (tag === 'A') return 'link';
    if (tag === 'BUTTON') return 'button';
    // role= fallbacks (custom widgets)
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role === 'checkbox') return 'checkbox';
    if (role === 'radio')    return 'radio';
    if (role === 'link')     return 'link';
    if (role === 'button')   return 'button';
    return 'generic';
  };

  // 2026-07 v2.5.4 — Extract a label even when the button has no text.
  // Handles the common close-X patterns:
  //   • <button><svg>…</svg></button>                → "✕ (icon button)"
  //   • <button class="close" aria-label="Close">    → aria-label wins
  //   • <span class="modal__close" role="button">    → class hint "close"
  //   • <i class="fa fa-times"></i>                  → icon class name
  //   • plain <div style="cursor:pointer">✕</div>    → the ✕ char
  const iconLabelFor = (el) => {
    const cls = (el.className && typeof el.className === 'string')
      ? el.className : '';
    // 1. cross / times / close / xmark FontAwesome & Material icons
    if (/(?:^|\s)(fa-(?:times|xmark|close)|icon-close|icon-x|material-icons.*close)/i.test(cls))
      return '✕ (close)';
    // 2. class name hint (any word containing close/dismiss/cancel/x-btn)
    if (/close|dismiss|cancel|xbtn|x-btn|btn-x/i.test(cls))
      return '✕ (close)';
    // 3. child SVG with an aria/title
    const svg = el.querySelector && el.querySelector('svg');
    if (svg) {
      const tt = svg.querySelector('title');
      if (tt && tt.textContent) return tt.textContent.trim().slice(0, 60);
      const al = svg.getAttribute('aria-label');
      if (al) return al.trim().slice(0, 60);
      return '(icon button)';
    }
    // 4. Look at innerHTML for ✕ / × unicode
    const html = (el.innerHTML || '').trim();
    if (/^[×✕✖✗✘⨯]$/.test((el.innerText || html).replace(/\s+/g, '')))
      return '✕ (close)';
    // 5. Font Awesome / Material Icons wrapper without cross keyword
    if (/(?:^|\s)(fa[- ]|material-icons|icon-)/i.test(cls))
      return '(icon button)';
    return '';
  };

  // v2.6.28 — For form fields (input / textarea / select) prefer
  // placeholder / name / aria-label / linked <label> over the "Button
  // #N" fallback since text-input's innerText is always empty.
  const formFieldLabelFor = (el) => {
    const ph = el.getAttribute && (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('title'));
    if (ph && ph.trim()) return ph.trim();
    const nm = el.getAttribute && (el.getAttribute('name') || el.getAttribute('id'));
    // Try linked <label for=id>
    if (el.id) {
      try {
        const lbl = document.querySelector('label[for="' + el.id.replace(/"/g, '\\"') + '"]');
        if (lbl) {
          const t = (lbl.innerText || lbl.textContent || '').replace(/\s+/g, ' ').trim();
          if (t) return t;
        }
      } catch (e) {}
    }
    // Wrapping <label> (implicit for)
    let p = el.parentElement, depth = 0;
    while (p && depth < 3) {
      if (p.tagName === 'LABEL') {
        const t = (p.innerText || p.textContent || '').replace(/\s+/g, ' ').trim();
        if (t) return t;
        break;
      }
      p = p.parentElement; depth++;
    }
    if (nm && nm.trim()) return nm.trim();
    return '';
  };

  scanPopups.forEach((entry, popupIdx) => {
    const popup = entry.el;
    const ox = entry.ox || 0;
    const oy = entry.oy || 0;
    const iframePath = entry.iframePath || [];
    const ownerDoc = popup.ownerDocument || document;
    const rectP = popup.getBoundingClientRect();
    if (rectP.width < 20 || rectP.height < 20) return;
    const inside = Array.from(popup.querySelectorAll(BTN_SEL));
    // Cursor:pointer sweep for hand-rolled close-Xs and ad-hoc buttons.
    const insideAll = Array.from(popup.querySelectorAll('*'));
    for (const el of insideAll) {
      if (inside.indexOf(el) !== -1) continue;
      try {
        const cs = window.getComputedStyle(el);
        if (cs && cs.cursor === 'pointer' && el.children.length <= 3) {
          inside.push(el);
        }
      } catch (e) {}
    }
    const seen = new Set();
    let btnCounter = 0;
    for (const el of inside) {
      try {
        const cs = window.getComputedStyle(el);
        if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') < 0.05) continue;
        if (cs.pointerEvents === 'none') continue;
        if (el.disabled || (el.getAttribute && el.getAttribute('aria-disabled') === 'true')) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        // Skip buttons hidden behind the modal backdrop / another layer.
        if (!isTopHit(el, ownerDoc)) continue;
        // v2.6.28 — Skip hidden form inputs like <input type="hidden">
        // and off-screen fields (Firebase reCAPTCHA hidden inputs, etc)
        const tagUp = (el.tagName || '').toUpperCase();
        if (tagUp === 'INPUT' && ((el.getAttribute('type') || '').toLowerCase() === 'hidden')) continue;
        // v2.6.28 polish — Skip a wrapping <label> if it already contains
        //   an input/textarea/select that will be enumerated on its own
        //   row. Otherwise the same visible target shows up twice in the
        //   checklist (once as the label, once as the input), and ticks
        //   would record two steps against the same field. Keep bare
        //   labels (no inner control) since they're used as standalone
        //   clickable hints in some designs.
        if (tagUp === 'LABEL' && el.querySelector && el.querySelector('input,textarea,select')) continue;

        const kind = classifyKind(el);
        const rawText = normText(el);
        // Popup close-Xs often have empty text — synthesise a label
        // from aria-label / title / icon class / SVG so the UI still
        // shows a meaningful checkbox row.
        let label = rawText;
        if (!label) {
          const al = el.getAttribute('aria-label') || el.getAttribute('title') || '';
          if (al) label = al.trim();
        }
        // v2.6.28 — For form fields prefer placeholder/name/label
        //           BEFORE the icon/close heuristics.
        if (!label && (kind === 'text_input' || kind === 'textarea' || kind === 'select' || kind === 'checkbox' || kind === 'radio')) {
          label = formFieldLabelFor(el);
        }
        if (!label) {
          label = iconLabelFor(el);
        }
        // v2.5.4 — LAST-RESORT synthetic label so no clickable is dropped.
        // Small square inline elements at the top-right corner of the
        // popup are 99% close-Xs even without any hint.
        if (!label) {
          const relX = r.left - rectP.left;
          const relY = r.top - rectP.top;
          const isSmallSquare = Math.abs(r.width - r.height) < 8 && r.width < 60 && r.width > 8;
          const nearTopRight = relY < 60 && (rectP.width - (relX + r.width)) < 60;
          if (isSmallSquare && nearTopRight) {
            label = '✕ (close corner)';
          } else {
            btnCounter += 1;
            label = `Button #${btnCounter}`;
          }
        }
        label = label.slice(0, 200);
        const tag = el.tagName;
        const dedupKey = `${popupIdx}::${tag}::${label}::${Math.round(r.left)}::${Math.round(r.top)}`;
        if (seen.has(dedupKey)) continue;
        seen.add(dedupKey);
        out.push({
          popup_index: popupIdx,
          text: label,
          tag: tag,
          element_kind: kind,
          input_type: (tagUp === 'INPUT' ? (el.getAttribute('type') || 'text').toLowerCase() : ''),
          x: Math.round(r.left + r.width / 2 + ox),
          y: Math.round(r.top + r.height / 2 + oy),
          w: Math.round(r.width),
          h: Math.round(r.height),
          iframe_path: iframePath.length ? iframePath : undefined,
        });
      } catch (e) {}
    }
  });

  return {
    popup_count: scanPopups.length,
    total_popups_found: kept.length,
    top_popup_only: true,
    items: out,
  };
}
"""


async def detect_popup_buttons(sess: RecorderSession) -> Dict[str, Any]:
    """Find every visible popup / modal / dialog on the page and list
    the clickable buttons inside each — cross (✕), OK, Cancel, Yes/No,
    custom close-Xs, etc. Powers the "Popup Work" tool so users can
    add popup-interaction steps mid-flow (e.g. a survey shows a
    "continue?" popup they must dismiss). Same return shape as
    detect_clickables so the same checklist UI works with a small
    tweak (grouped by popup_index).  Customer ask: "click button k
    sath aik popup work ka button hona chahye … os pr jo button hun
    like cross yan koi b to wo show ho jayn"."""
    sess.touch()
    async with sess.lock:
        if sess.state != "ready" or not sess.page:
            return {"popup_count": 0, "items": [], "error": f"Session not ready ({sess.state})"}
        try:
            result = await sess.page.evaluate(_DETECT_POPUP_BUTTONS_JS)
        except Exception as e:
            return {"popup_count": 0, "items": [], "error": f"Popup scan failed: {e}"}
        if not isinstance(result, dict):
            return {"popup_count": 0, "items": []}
        # Normalise + hard-cap so a busy page can't overwhelm the UI.
        items = result.get("items") or []
        if len(items) > 300:
            items = items[:300]
        return {
            "popup_count": int(result.get("popup_count") or 0),
            "total_popups_found": int(result.get("total_popups_found") or 0),
            "top_popup_only": bool(result.get("top_popup_only")),
            "items": items,
        }


def get_steps(sess: RecorderSession) -> List[Dict[str, Any]]:
    return sess.steps


# ─────────────────────────────────────────────────────────────────────
# 2026-01: Pre-flight lint + quick step builders
# ─────────────────────────────────────────────────────────────────────
def lint_session(sess: RecorderSession) -> Dict[str, Any]:
    """Pre-flight lint on the current session's steps. Returns:
        {
          ok: bool,                      # True iff no `error` issues
          issues: [
            {level, at_step, code, message}, ...
          ],
          summary: {errors: N, warnings: N, infos: N}
        }
    """
    sess.touch()
    try:
        from automation_extensions import lint_steps
        issues = lint_steps(sess.steps)
    except Exception as e:  # pragma: no cover
        return {"ok": False, "issues": [{"level": "error", "at_step": -1,
                "code": "lint_unavailable", "message": str(e)}],
                "summary": {"errors": 1, "warnings": 0, "infos": 0}}
    errors = sum(1 for i in issues if i.get("level") == "error")
    warnings = sum(1 for i in issues if i.get("level") == "warn")
    infos = sum(1 for i in issues if i.get("level") == "info")
    return {
        "ok": errors == 0,
        "issues": issues,
        "summary": {"errors": errors, "warnings": warnings, "infos": infos},
    }


def add_wait_for_text_step(sess: RecorderSession, text: str,
                           timeout: int = 15000,
                           case_insensitive: bool = True,
                           optional: bool = False) -> Dict[str, Any]:
    """Append a `wait_for_text` step (e.g. wait for "Thank you")."""
    sess.touch()
    if not text:
        return {"recorded": False, "error": "text required"}
    step = {
        "action": "wait_for_text",
        "text": str(text),
        "timeout": max(1000, int(timeout)),
        "case_insensitive": bool(case_insensitive),
    }
    if optional:
        step["optional"] = True
    sess.append_step(step)
    return {"recorded": True, "step": step}


def add_wait_for_url_step(sess: RecorderSession,
                          contains: Optional[str] = None,
                          equals: Optional[str] = None,
                          pattern: Optional[str] = None,
                          timeout: int = 15000,
                          optional: bool = False) -> Dict[str, Any]:
    """Append a `wait_for_url` step (e.g. wait until URL contains '/success')."""
    sess.touch()
    if not (contains or equals or pattern):
        return {"recorded": False, "error": "contains/equals/pattern required"}
    step = {
        "action": "wait_for_url",
        "timeout": max(1000, int(timeout)),
    }
    if contains: step["contains"] = str(contains)
    if equals:   step["equals"]   = str(equals)
    if pattern:  step["pattern"]  = str(pattern)
    if optional: step["optional"] = True
    sess.append_step(step)
    return {"recorded": True, "step": step}


def add_extract_step(sess: RecorderSession,
                     selector: str, store_key: str,
                     attribute: Optional[str] = None,
                     regex: Optional[str] = None,
                     timeout: int = 10000,
                     optional: bool = False) -> Dict[str, Any]:
    """Append an `extract` step — captures text/attribute from a selector
    into a variable usable in subsequent steps via `{{store_key}}`."""
    sess.touch()
    if not selector or not store_key:
        return {"recorded": False, "error": "selector + store_key required"}
    step = {
        "action": "extract",
        "selector": str(selector),
        "store_key": str(store_key),
        "timeout": max(1000, int(timeout)),
    }
    if attribute: step["attribute"] = str(attribute)
    if regex:     step["regex"]     = str(regex)
    if optional:  step["optional"]  = True
    sess.append_step(step)
    return {"recorded": True, "step": step}


def add_dismiss_popups_step(sess: RecorderSession) -> Dict[str, Any]:
    """Append a `dismiss_popups` step (auto-clicks cookie/GDPR banners)."""
    sess.touch()
    step = {"action": "dismiss_popups", "optional": True}
    sess.append_step(step)
    return {"recorded": True, "step": step}


def get_live_progress(sess: RecorderSession, since_idx: int = 0) -> Dict[str, Any]:
    """Return the current live-progress feed for an in-flight or recently
    completed live_test. Frontend polls this every ~400ms.

    Args:
        since_idx: only return events with array index >= since_idx
            (lets the frontend do incremental fetches).

    Returns:
        {
          running: bool,        # True while live_test is executing
          started_at: float,    # epoch seconds
          finished_at: float | None,
          total_events: int,
          events: [{idx, action, selector, status, ms?, error?, friendly_hint?, timestamp_ms}, ...],
        }
    """
    sess.touch()
    all_events = sess.live_progress or []
    since = max(0, int(since_idx or 0))
    return {
        "running": bool(sess.live_progress_running),
        "started_at": sess.live_progress_started_at,
        "finished_at": sess.live_progress_finished_at,
        "total_events": len(all_events),
        "events": all_events[since:],
    }


def set_session_settings(
    sess: RecorderSession,
    *,
    auto_insert_waits: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update live recorder preferences (e.g. auto wait insertion)."""
    sess.touch()
    if auto_insert_waits is not None:
        sess.auto_insert_waits = bool(auto_insert_waits)
    return {"auto_insert_waits": sess.auto_insert_waits}


async def finalize(sess: RecorderSession) -> Dict[str, Any]:
    """Stop the session and return the recording bundle."""
    sess.touch()
    out = {
        "session_id": sess.session_id,
        "url": sess.url,
        "proxy": sess.proxy,
        "proxy_provider_id": getattr(sess, "proxy_provider_id", "") or "",
        "country": getattr(sess, "country", "") or "",
        "device_preset": getattr(sess, "device_type", "auto") or "auto",
        "user_agent": sess.user_agent,
        "headers": sess.headers,
        "automation_json": sess.steps,
        "target_screenshot_path": sess.target_screenshot_path,
        "final_url": sess.final_url,
        "final_text_snippet": sess.final_text_snippet,
        "step_count": len(sess.steps),
        "auto_insert_waits": bool(getattr(sess, "auto_insert_waits", False)),
    }
    # Persist to disk before stopping
    try:
        folder = SESSIONS_ROOT / sess.session_id
        folder.mkdir(parents=True, exist_ok=True)
        import json as _json
        with open(folder / "automation.json", "w") as f:
            _json.dump(sess.steps, f, indent=2)
        with open(folder / "meta.json", "w") as f:
            _json.dump({k: v for k, v in out.items() if k != "automation_json"}, f, indent=2)
    except Exception as e:
        logger.warning(f"finalize persist failed: {e}")
    await stop_session(sess.session_id)
    return out


# ══════════════════════════════════════════════════════════════════════
# ── 2026-01 (Phase 1 features for "any-offer" coverage) ──────────────
# ══════════════════════════════════════════════════════════════════════
# These functions add steps that the runtime engine already understands
# (wait_for_load, wait_for_selector, fill, etc.) but with smarter
# variants that handle the most common offer-page edge cases that
# previously required manual JSON editing.

# ── A. Network-idle wait ─────────────────────────────────────────────
async def add_wait_network_idle(sess: RecorderSession, timeout_ms: int = 30000) -> Dict[str, Any]:
    """Append a 'wait for network idle' step. Critical for SPAs (React,
    Vue, Next.js, Nuxt offer pages) where the visible CTA renders only
    AFTER an XHR/fetch finishes — `wait_for_selector` alone often races
    the JS engine and timeouts. The runtime maps this to Playwright's
    `wait_for_load_state("networkidle")`.
    """
    sess.touch()
    try:
        await sess.page.wait_for_load_state("networkidle", timeout=int(timeout_ms))
    except Exception:
        pass  # Recording continues even if live wait timed out
    step = {
        "action": "wait_for_load",
        "state": "networkidle",
        "timeout": int(timeout_ms),
        "name": f"Wait for network idle ({timeout_ms}ms)",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ── B. Iframe-aware click / fill helpers ─────────────────────────────
def _build_iframe_click_step(
    text: str,
    info: Dict[str, Any],
    frame_selector: str,
) -> Dict[str, Any]:
    """Step that targets an element INSIDE an iframe. Replay engine
    needs `frame_selector` (CSS for the iframe element) + an inner
    `selector` or `text` to click.

    Same selector-priority fallback chain as `_build_text_click_evaluate`
    is encoded in the JS — but scoped to the iframe's contentWindow.
    """
    safe_text = (text or "").replace("\\", "\\\\").replace("'", "\\'")
    safe_fs = frame_selector.replace("\\", "\\\\").replace("'", "\\'")
    fb = _build_fallbacks(info)
    # Build CSS selector candidates the same way as _build_text_click
    cands: List[str] = []
    attrs = (info or {}).get("attrs") or {}
    for k in ("data-testid", "data-test", "data-cy", "data-qa", "data-id"):
        v = attrs.get(k)
        if isinstance(v, str) and v:
            cands.append(f'[{k}="{v}"]')
    _id = ((info or {}).get("id") or "").strip()
    if _id and ":" not in _id:
        cands.append(f"#{_id}")
    css_arr = "[" + ",".join("'" + c.replace("'", "\\'") + "'" for c in cands) + "]"
    xpath_stable = ((info or {}).get("xpath_stable") or "").strip()
    xs_js = "'" + xpath_stable.replace("'", "\\'") + "'" if xpath_stable else "''"
    script = (
        "(function(){"
        + f"var fr=document.querySelector('{safe_fs}');"
        "if(!fr||!fr.contentDocument){console.warn('[krx] iframe missing');return;}"
        "var doc=fr.contentDocument;"
        "var _doClick=function(el){if(!el)return false;el.scrollIntoView({block:'center'});"
        "if(el.tagName==='A'&&el.href&&!el.target){el.click();return true;}el.click();return true;};"
        f"var _css={css_arr};"
        "for(var i=0;i<_css.length;i++){try{var _e=doc.querySelector(_css[i]);if(_e&&_doClick(_e))return;}catch(e){}}"
        f"var _xs={xs_js};"
        "if(_xs){try{var _r=doc.evaluate(_xs,doc,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);if(_r&&_r.singleNodeValue&&_doClick(_r.singleNodeValue))return;}catch(e){}}"
        f"var t='{safe_text}'.replace(/\\s+/g,' ').trim().toLowerCase();"
        "if(!t)return;"
        "var els=Array.from(doc.querySelectorAll('a,button,div,span,label,input,[role=button]')).filter(function(e){"
        "var x=((e.innerText||e.textContent||e.value||'')+'').replace(/\\s+/g,' ').trim().toLowerCase();"
        "return x===t||(t.length>=8&&x.indexOf(t)!==-1);});"
        "if(els.length)_doClick(els[0]);"
        "})();"
    )
    step = {
        "action": "evaluate",
        "script": script,
        "frame_selector": frame_selector,
        "name": f"iframe click: {(text or 'element')[:40]}",
    }
    if fb:
        step["fallbacks"] = fb
    return step


# ── C. File upload step ──────────────────────────────────────────────
async def add_file_upload(
    sess: RecorderSession,
    selector: str,
    template_path: str,
    label: str = "",
) -> Dict[str, Any]:
    """Append a 'set_input_files' step. `template_path` can be a local
    file path that the customer's Electron app will resolve (e.g.
    `~/Pictures/sample_id.jpg`), or a `{{column_name}}` template that
    resolves per-row at RUT replay time.

    Common use cases:
      • KYC / ID verification offers
      • Profile picture during signup
      • Crypto exchange document upload
    """
    sess.touch()
    if not selector or not selector.strip():
        return {"recorded": False, "error": "selector_required"}
    if not template_path or not template_path.strip():
        return {"recorded": False, "error": "file_path_required"}
    step = {
        "action": "set_input_files",
        "selector": selector.strip(),
        "files": template_path.strip(),
        "timeout": 15000,
        "name": label or f"Upload file → {selector[:40]}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ── D. OTP / verification-code wait + extract ────────────────────────
async def add_otp_wait(
    sess: RecorderSession,
    *,
    source: str = "url",  # url | clipboard | page_text | selector
    selector: str = "",
    url_regex: str = "",
    text_regex: str = "",
    target_selector: str = "",
    timeout_ms: int = 120000,
    digits: int = 6,
    label: str = "",
) -> Dict[str, Any]:
    """Append a step that waits for an N-digit code to appear, extracts
    it, and fills it into the target input.

    For email-verify offers the typical flow is:
      1. Submit form → API sends code to a temp inbox
      2. Customer's email-pulling worker (or webhook) updates the
         lead row with the code
      3. The job poll-reads the code → fills the verify input

    For URL-based code delivery (some sweepstakes) the code arrives
    via the redirect URL — we extract it with `url_regex`.

    The recorded step type `wait_for_otp` is interpreted at replay
    time by RUT — for now the recorder just emits the step config.
    """
    sess.touch()
    n = max(3, min(int(digits or 6), 10))
    step = {
        "action": "wait_for_otp",
        "source": source,
        "selector": selector or None,
        "url_regex": url_regex or fr"\b(\d{{{n}}})\b",
        "text_regex": text_regex or fr"\b(\d{{{n}}})\b",
        "target_selector": target_selector,
        "timeout": int(timeout_ms),
        "digits": n,
        "name": label or f"Wait & fill OTP ({n} digits)",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ── E. CAPTCHA detection probe ───────────────────────────────────────
async def detect_captcha(sess: RecorderSession) -> Dict[str, Any]:
    """Scan the live page for known CAPTCHA widgets so the recorder
    can WARN the user (and optionally insert a `pause_for_human` step
    that the customer's Electron client surfaces as a popup during
    job replay so a human solves it).
    """
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return {"detected": False, "reason": "not_ready"}
    js = """
    (function(){
      var hits = [];
      // reCAPTCHA v2/v3
      if (document.querySelector('iframe[src*="recaptcha"], .g-recaptcha, [data-sitekey][class*="recaptcha"]')) {
        hits.push({type:'recaptcha', version: document.querySelector('iframe[src*="recaptcha"][src*="invisible"]') ? 'v3' : 'v2'});
      }
      // hCaptcha
      if (document.querySelector('iframe[src*="hcaptcha"], .h-captcha, [data-sitekey][class*="hcaptcha"]')) {
        hits.push({type:'hcaptcha'});
      }
      // Cloudflare Turnstile
      if (document.querySelector('iframe[src*="challenges.cloudflare"], .cf-turnstile, [data-sitekey][class*="cf-"]')) {
        hits.push({type:'turnstile'});
      }
      // Cloudflare JS challenge page
      if (document.title.toLowerCase().indexOf('just a moment') !== -1 ||
          document.body.innerText.toLowerCase().indexOf('checking your browser') !== -1) {
        hits.push({type:'cloudflare_jschallenge'});
      }
      // FunCaptcha / Arkose
      if (document.querySelector('iframe[src*="arkoselabs"], .funcaptcha, #funcaptcha')) {
        hits.push({type:'funcaptcha'});
      }
      // GeeTest
      if (document.querySelector('iframe[src*="geetest"], .geetest_panel, .geetest_btn')) {
        hits.push({type:'geetest'});
      }
      return hits;
    })();
    """
    try:
        async with sess.lock:
            hits = await sess.page.evaluate(js)
    except Exception as e:
        return {"detected": False, "error": str(e)}
    return {
        "detected": bool(hits),
        "providers": hits or [],
        "recommendation": (
            "Insert a 'pause_for_human' step here so during job replay "
            "the customer's Electron client opens a popup window for "
            "manual CAPTCHA solving, then resumes automation."
        ) if hits else None,
    }


async def add_captcha_pause(sess: RecorderSession, label: str = "") -> Dict[str, Any]:
    """Insert a pause step that the runtime treats as 'wait for human
    confirmation' — pops up a modal in the customer's Electron app
    during job replay. The customer solves CAPTCHA manually, clicks
    Continue, and automation resumes.
    """
    sess.touch()
    step = {
        "action": "pause_for_human",
        "reason": "captcha",
        "timeout": 300000,  # 5 min — generous for human solve
        "optional": True,
        "name": label or "⏸ Pause for human (CAPTCHA)",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


# ── F. Resolve dynamic templates at recording time ───────────────────
# This is what makes {{random_email}}, {{today}}, {{counter}}, etc.
# work DURING recording — the recorder fills the form with the actual
# resolved value so the customer can see the offer respond correctly,
# while the recorded step keeps the {{template}} text for runtime
# resolution per lead row.
def resolve_template(sess: RecorderSession, value: str) -> str:
    """Public alias for `resolve_templates_in_text` (Phase 1 PRD)."""
    return resolve_templates_in_text(sess, value)


# ── G. Generic pause-for-human step ──────────────────────────────────
async def add_human_pause(
    sess: RecorderSession,
    reason: str = "manual_step",
    timeout_ms: int = 300000,
    label: str = "",
) -> Dict[str, Any]:
    """General-purpose pause that lets the recorder customer surface
    ANY popup during job replay — not just CAPTCHA. Examples:
      • 'Connect wallet now' for crypto offers
      • 'Approve from your phone' for 2FA push notifications
      • 'Wait for SMS code'
    """
    sess.touch()
    step = {
        "action": "pause_for_human",
        "reason": reason or "manual_step",
        "timeout": int(timeout_ms),
        "optional": True,
        "name": label or f"⏸ Pause for human ({reason})",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}



# ══════════════════════════════════════════════════════════════════════
# ── 2026-01 (Phase 2 features — full "any-offer" coverage) ───────────
# ══════════════════════════════════════════════════════════════════════

async def iframe_click(
    sess: RecorderSession,
    frame_selector: str,
    inner_selector: str = "",
    inner_text: str = "",
    timeout_ms: int = 10000,
) -> Dict[str, Any]:
    """Click an element inside a (possibly cross-origin) iframe.
    Uses Playwright frame_locator which traverses cross-origin frames."""
    sess.touch()
    if not frame_selector:
        return {"recorded": False, "error": "frame_selector_required"}
    if not inner_selector and not inner_text:
        return {"recorded": False, "error": "inner_selector_or_text_required"}
    async with sess.lock:
        try:
            fl = sess.page.frame_locator(frame_selector)
            if inner_selector:
                await fl.locator(inner_selector).first.click(timeout=int(timeout_ms))
            else:
                await fl.get_by_text(inner_text).first.click(timeout=int(timeout_ms))
        except Exception as e:
            return {"recorded": False, "error": f"iframe_click_failed: {e}"}
    step = {
        "action": "iframe_click",
        "frame_selector": frame_selector,
        "selector": inner_selector or None,
        "text": inner_text or None,
        "timeout": int(timeout_ms),
        "name": f"iframe click → {(inner_selector or inner_text or '')[:40]}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def iframe_fill(
    sess: RecorderSession,
    frame_selector: str,
    inner_selector: str,
    value: str,
    timeout_ms: int = 10000,
) -> Dict[str, Any]:
    """Fill an input inside an iframe. Templates resolved at recording."""
    sess.touch()
    if not frame_selector or not inner_selector:
        return {"recorded": False, "error": "selectors_required"}
    live_value = resolve_templates_in_text(sess, value or "")
    async with sess.lock:
        try:
            fl = sess.page.frame_locator(frame_selector)
            await fl.locator(inner_selector).first.fill(live_value, timeout=int(timeout_ms))
        except Exception as e:
            return {"recorded": False, "error": f"iframe_fill_failed: {e}"}
    step = {
        "action": "iframe_fill",
        "frame_selector": frame_selector,
        "selector": inner_selector,
        "value": value,
        "timeout": int(timeout_ms),
        "name": f"iframe fill → {inner_selector[:40]}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def shadow_click(
    sess: RecorderSession,
    chain: List[str],
) -> Dict[str, Any]:
    """Click an element nested behind shadow roots.
    chain = ['my-card', 'checkout-button', 'button.primary']
    Pierces each shadow root in order. Works for Stripe Elements,
    Shopify modern checkout, Salesforce Lightning, etc.
    """
    sess.touch()
    if not chain or not isinstance(chain, list):
        return {"recorded": False, "error": "chain_required"}
    js_chain = "[" + ",".join("'" + str(c).replace("'", "\\'") + "'" for c in chain) + "]"
    script = (
        "(function(){"
        f"var chain={js_chain};"
        "var root=document;"
        "for(var i=0;i<chain.length-1;i++){"
        "var el=root.querySelector(chain[i]);"
        "if(!el)return;"
        "if(el.shadowRoot)root=el.shadowRoot;else root=el;"
        "}"
        "var target=root.querySelector(chain[chain.length-1]);"
        "if(!target)return;"
        "target.scrollIntoView({block:'center'});target.click();"
        "})();"
    )
    async with sess.lock:
        try:
            await sess.page.evaluate(script)
        except Exception as e:
            return {"recorded": False, "error": f"shadow_click_failed: {e}"}
    step = {
        "action": "evaluate",
        "script": script,
        "name": f"shadow-DOM click → {' >> '.join(chain[-2:])}",
        "shadow_chain": chain,
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def drag_drop(
    sess: RecorderSession,
    *,
    source_selector: str = "",
    source_x: int = 0, source_y: int = 0,
    target_selector: str = "",
    target_x: int = 0, target_y: int = 0,
    delta_x: int = 0, delta_y: int = 0,
    steps: int = 25,
) -> Dict[str, Any]:
    """Drag-and-drop with smooth interpolated movement.
    Modes:
       1. source_selector + target_selector  (CSS)
       2. source x/y + target x/y            (coords)
       3. source_selector + delta x/y        (slider — relative drag)
    Critical for slider/puzzle CAPTCHAs (AWS WAF, GeeTest)."""
    sess.touch()
    async with sess.lock:
        try:
            if source_selector and (target_selector or delta_x or delta_y):
                src = await sess.page.query_selector(source_selector)
                if not src:
                    return {"recorded": False, "error": "source_not_found"}
                box = await src.bounding_box()
                if not box:
                    return {"recorded": False, "error": "source_no_bbox"}
                sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                if target_selector:
                    tgt = await sess.page.query_selector(target_selector)
                    if not tgt:
                        return {"recorded": False, "error": "target_not_found"}
                    tbox = await tgt.bounding_box()
                    tx, ty = tbox["x"] + tbox["width"] / 2, tbox["y"] + tbox["height"] / 2
                else:
                    tx, ty = sx + int(delta_x), sy + int(delta_y)
            else:
                sx, sy = int(source_x), int(source_y)
                tx, ty = int(target_x), int(target_y)
            await sess.page.mouse.move(sx, sy)
            await sess.page.mouse.down()
            await sess.page.mouse.move(tx, ty, steps=int(steps))
            await sess.page.mouse.up()
        except Exception as e:
            return {"recorded": False, "error": f"drag_failed: {e}"}
    step = {
        "action": "drag_drop",
        "source_selector": source_selector or None,
        "source_x": int(source_x) if not source_selector else None,
        "source_y": int(source_y) if not source_selector else None,
        "target_selector": target_selector or None,
        "target_x": int(target_x) or None,
        "target_y": int(target_y) or None,
        "delta_x": int(delta_x) or None,
        "delta_y": int(delta_y) or None,
        "steps": int(steps),
        "name": f"drag {source_selector or '(x,y)'} → {target_selector or 'destination'}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def browser_back(sess: RecorderSession) -> Dict[str, Any]:
    sess.touch()
    async with sess.lock:
        try:
            await sess.page.go_back(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
    step = {"action": "go_back", "name": "← Browser back"}
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def browser_forward(sess: RecorderSession) -> Dict[str, Any]:
    sess.touch()
    async with sess.lock:
        try:
            await sess.page.go_forward(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
    step = {"action": "go_forward", "name": "→ Browser forward"}
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def right_click(
    sess: RecorderSession,
    x: int = 0, y: int = 0,
    selector: str = "",
) -> Dict[str, Any]:
    sess.touch()
    async with sess.lock:
        try:
            if selector:
                el = await sess.page.query_selector(selector)
                if el:
                    await el.click(button="right")
            else:
                await sess.page.mouse.click(int(x), int(y), button="right")
        except Exception as e:
            return {"recorded": False, "error": f"right_click_failed: {e}"}
    step = {
        "action": "right_click",
        "selector": selector or None,
        "x": int(x) if not selector else None,
        "y": int(y) if not selector else None,
        "name": f"Right-click → {selector or f'({x},{y})'}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def clipboard_write(
    sess: RecorderSession,
    text: str,
) -> Dict[str, Any]:
    """Write text to clipboard. Templates resolved at recording time;
    the recorded step keeps {{literal}} for per-row substitution."""
    sess.touch()
    live = resolve_templates_in_text(sess, text or "")
    async with sess.lock:
        try:
            await sess.page.evaluate(
                "(t) => navigator.clipboard && navigator.clipboard.writeText(t)",
                live,
            )
        except Exception:
            pass
    step = {
        "action": "clipboard_write",
        "text": text,
        "name": f"Clipboard ← {live[:30]}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def clipboard_read_into_var(
    sess: RecorderSession,
    var_name: str = "clipboard",
) -> Dict[str, Any]:
    sess.touch()
    if not var_name or not var_name.strip():
        return {"recorded": False, "error": "var_name_required"}
    var = var_name.strip()
    step = {
        "action": "clipboard_read",
        "var": var,
        "name": f"Read clipboard → {{{{{var}}}}}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def add_conditional_skip(
    sess: RecorderSession,
    *,
    if_type: str,
    selector: str = "",
    text: str = "",
    skip_count: int = 1,
    label: str = "",
) -> Dict[str, Any]:
    """Insert a step that at replay time SKIPS the next N steps if
    condition matches. Perfect for offers that SOMETIMES show CAPTCHA
    or popups — e.g. if .captcha-frame is visible, skip the next 2
    steps that would otherwise fail."""
    sess.touch()
    typ = (if_type or "visible").lower()
    if typ not in ("visible", "not_visible", "text"):
        return {"recorded": False, "error": "invalid_if_type"}
    if typ in ("visible", "not_visible") and not selector:
        return {"recorded": False, "error": "selector_required_for_visible"}
    if typ == "text" and not text:
        return {"recorded": False, "error": "text_required_for_text"}
    step = {
        "action": "conditional_skip",
        "if_type": typ,
        "selector": selector or None,
        "text": text or None,
        "skip_count": max(1, int(skip_count)),
        "optional": True,
        "name": label or f"⏭ If {typ}: {selector or text[:30]} — skip next {skip_count}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def export_storage_state(sess: RecorderSession) -> Dict[str, Any]:
    """Pull all cookies + localStorage from the current context.
    Returned dict can be re-applied later to resume a logged-in state."""
    sess.touch()
    if sess.state != "ready" or sess.context is None:
        return {"ok": False, "error": "not_ready"}
    async with sess.lock:
        try:
            state = await sess.context.storage_state()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "state": state}


async def add_save_storage_step(
    sess: RecorderSession,
    var_name: str = "session_state",
) -> Dict[str, Any]:
    sess.touch()
    v = (var_name or "session_state").strip() or "session_state"
    step = {
        "action": "save_storage",
        "var": v,
        "name": f"💾 Save cookies+storage → {{{{{v}}}}}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def add_restore_storage_step(
    sess: RecorderSession,
    var_name: str = "session_state",
) -> Dict[str, Any]:
    sess.touch()
    v = (var_name or "session_state").strip() or "session_state"
    step = {
        "action": "restore_storage",
        "var": v,
        "name": f"📂 Restore cookies+storage from {{{{{v}}}}}",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def set_zoom(
    sess: RecorderSession,
    level: float = 1.0,
) -> Dict[str, Any]:
    """Set browser zoom (1.0 = 100%, 1.25 = 125%, etc.)."""
    sess.touch()
    lvl = max(0.25, min(float(level or 1.0), 3.0))
    async with sess.lock:
        try:
            await sess.page.evaluate(f"() => document.body.style.zoom = '{lvl}'")
        except Exception:
            pass
    step = {
        "action": "set_zoom",
        "level": lvl,
        "name": f"🔍 Zoom = {int(lvl * 100)}%",
    }
    sess.append_step(step)
    return {"recorded": True, "step": step}


async def headless_probe(sess: RecorderSession) -> Dict[str, Any]:
    """Run the same detection probes big anti-bot vendors run
    (Akamai, DataDome, F5 Shape, PerimeterX). Returns a 0-100 score
    plus list of failed checks so the customer knows WHY their
    recorder browser might be flagged."""
    sess.touch()
    if sess.state != "ready" or sess.page is None:
        return {"score": 0, "error": "not_ready"}
    probes_js = """
    (function(){
      var r = {};
      r.webdriver = !!navigator.webdriver;
      var ua = navigator.userAgent.toLowerCase();
      var uaMobile = /mobile|android|iphone|ipad/.test(ua);
      r.uaDataMismatch = navigator.userAgentData ? (navigator.userAgentData.mobile !== uaMobile) : null;
      r.touchMismatch = uaMobile && navigator.maxTouchPoints === 0;
      r.langsEmpty = !navigator.languages || navigator.languages.length === 0;
      r.chromeRuntimeMissing = (typeof chrome === 'undefined' || !chrome.runtime);
      r.pluginsEmpty = !navigator.plugins || navigator.plugins.length === 0;
      r.hairlineHack = (function(){
        var d = document.createElement('div');
        d.style.width = '0.5px'; document.body.appendChild(d);
        var w = d.getBoundingClientRect().width;
        document.body.removeChild(d);
        return w === 0;
      })();
      try {
        var canvas = document.createElement('canvas');
        var gl = canvas.getContext('webgl');
        var debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
        var renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
        r.webglRenderer = renderer;
        if (uaMobile && /nvidia|amd|intel\\(r\\)/i.test(renderer)) r.webglDesktopOnMobile = true;
      } catch(e) {}
      r.tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      r.notificationDenied = (typeof Notification !== 'undefined' && Notification.permission === 'denied');
      r.screenW = screen.width;
      r.screenH = screen.height;
      r.maxTouchPoints = navigator.maxTouchPoints;
      r.languages = navigator.languages;
      return r;
    })();
    """
    try:
        async with sess.lock:
            r = await sess.page.evaluate(probes_js)
    except Exception as e:
        return {"score": 0, "error": str(e)}
    score = 100
    fails: List[str] = []
    if r.get("webdriver"):              score -= 25; fails.append("navigator.webdriver leaks true")
    if r.get("uaDataMismatch"):         score -= 15; fails.append("navigator.userAgentData.mobile mismatch with UA")
    if r.get("touchMismatch"):          score -= 15; fails.append("maxTouchPoints=0 on mobile UA")
    if r.get("langsEmpty"):              score -= 8; fails.append("navigator.languages empty")
    if r.get("chromeRuntimeMissing"):    score -= 5; fails.append("chrome.runtime missing")
    if r.get("pluginsEmpty"):            score -= 5; fails.append("navigator.plugins empty")
    if r.get("hairlineHack"):           score -= 10; fails.append("Hairline-width CDP marker (0.5px → 0)")
    if r.get("webglDesktopOnMobile"):   score -= 10; fails.append("WebGL renderer is desktop GPU but UA is mobile")
    if r.get("notificationDenied"):      score -= 2; fails.append("Notification.permission=denied (headless default)")
    return {
        "score": max(0, score),
        "raw": r,
        "fails": fails,
        "verdict": (
            "EXCELLENT — looks like a real browser" if score >= 85 else
            "GOOD — minor leaks, still mostly real" if score >= 70 else
            "RISKY — multiple anti-bot vendors will flag this" if score >= 50 else
            "HIGH RISK — basic detection will fire"
        ),
    }

