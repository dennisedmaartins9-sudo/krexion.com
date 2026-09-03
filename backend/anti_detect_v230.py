"""
Krexion Anti-Detect v2.3.0 — Next-Level Stealth Stack
======================================================
Consolidated module implementing 15 industry-standard anti-detect
enhancements on top of the v2.2.x baseline (35+ JS fingerprint
patches + TLS/JA3 impersonation + behavioural stack). Every feature
is a pure Python function that returns JS/headers/URLs — the caller
(real_user_traffic.py or browser_profile_launcher.py) decides when
to apply. Failure of any single feature never breaks the stack; each
is opt-in with a safe no-op default.

Feature Index
-------------
 1. `http2_settings_for_ua()`         → HTTP/2 SETTINGS frame + priority
                                        (Akamai Bot Manager killer)
 2. `sec_fetch_headers()`             → Sec-Fetch-* on every navigation
 3. `bot_vendor_stealth_js()`         → PerimeterX/HUMAN, Kasada,
                                        Imperva, F5, Signal Sciences,
                                        Radware counter-tuning
 4. `pixel_prefire_urls(platform)`    → FB Pixel / GA / TikTok Pixel
                                        legitimacy fires
 5. `intermediate_hop_urls(...)`      → 1-2 realistic hop domains
                                        (l.facebook.com, t.co, bit.ly)
 6. `post_conversion_js()`            → 30-120s realistic browsing
                                        after conversion fires
 7. `full_client_hints(ua, viewport)` → 10 Sec-CH-UA-* headers matching
                                        real Chrome 128+
 8. `align_ua_to_chromium(ua)`        → Rewrites UA version to match
                                        installed Chromium binary
 9. `mobile_signals_js()`             → TouchEvents, DeviceMotion,
                                        visualViewport, NetworkInfo,
                                        ScreenOrientation, PointerEvent
10. `webgl_extensions_js()`           → Deep WebGL extensions list
                                        matching declared GPU
11. `speech_voices_js()`              → speechSynthesis voices per OS
12. `battery_fluctuation_js()`        → Realistic battery levels
                                        (20-95%, charging state changes)
13. `privacy_sandbox_js()`            → Topics API + Attribution
                                        Reporting API stubs
14. `extension_emulation_js()`        → 3-5 fake extensions in
                                        navigator.plugins
15. `ad_blocker_realism_js()`         → uBlock/AdBlock DOM signatures
                                        (70% of desktop users have one)
16. `first_party_sets_js()`           → FPS/RWS privacy sandbox signals
17. `apply_v230_stealth(context, ...)` → One-call orchestrator that
                                        wires every JS feature into
                                        a Playwright context

Author: Krexion team, July 2026
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("krexion.antidetect.v230")

# ══════════════════════════════════════════════════════════════════════
# 1. HTTP/2 FRAME FINGERPRINTING
# ══════════════════════════════════════════════════════════════════════
# Akamai Bot Manager, Cloudflare Enterprise, and Cloudfront read the
# HTTP/2 SETTINGS frame + WINDOW_UPDATE priorities before ANY request
# body arrives.  Real Chrome sends this exact sequence:
#     SETTINGS[HEADER_TABLE_SIZE=65536, ENABLE_PUSH=0,
#              MAX_CONCURRENT_STREAMS=1000, INITIAL_WINDOW_SIZE=6291456,
#              MAX_HEADER_LIST_SIZE=262144]
#     WINDOW_UPDATE(0, 15663105)
#     PRIORITY frame ordering: 1:0:201 → 3:0:101 → 5:0:1 → 7:0:1 …
# Krexion's baseline curl_cffi impersonation gets TLS right but NOT
# HTTP/2 framing.  This map returns curl_cffi kwargs the caller passes
# straight into `AsyncSession(...)`.

_HTTP2_SETTINGS_BY_CHROME: Dict[int, Dict[str, Any]] = {
    # Chrome 128-136 all use the same H/2 framing (Google froze it).
    128: {
        "http2_settings": {
            1: 65536,     # HEADER_TABLE_SIZE
            2: 0,         # ENABLE_PUSH
            3: 1000,      # MAX_CONCURRENT_STREAMS
            4: 6291456,   # INITIAL_WINDOW_SIZE (6 MB)
            6: 262144,    # MAX_HEADER_LIST_SIZE (256 KB)
        },
        "http2_window_update": 15663105,
        "http2_stream_weight": 256,
        "http2_stream_exclusive": True,
        # Pseudo-header order matters — Akamai flags out-of-order.
        "http2_pseudo_headers_order": [":method", ":authority", ":scheme", ":path"],
        # Real Chrome sends headers in this exact order (frame-level).
        "http2_headers_order": [
            "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
            "upgrade-insecure-requests", "user-agent",
            "accept", "sec-fetch-site", "sec-fetch-mode",
            "sec-fetch-user", "sec-fetch-dest",
            "accept-encoding", "accept-language",
        ],
    },
}


def http2_settings_for_ua(ua: str) -> Dict[str, Any]:
    """Return curl_cffi HTTP/2 configuration matching the Chrome major
    version declared in `ua`.  Falls back to Chrome-128 profile for
    unknown versions."""
    m = re.search(r"Chrome/(\d+)", ua or "")
    ver = int(m.group(1)) if m else 128
    key = 128 if ver < 128 else (128 if ver <= 136 else 128)
    return dict(_HTTP2_SETTINGS_BY_CHROME[key])


# ══════════════════════════════════════════════════════════════════════
# 2. SEC-FETCH-* HEADERS
# ══════════════════════════════════════════════════════════════════════
# Real Chrome 91+ sends these on EVERY request.  Missing = obvious
# bot signal on any post-2022 detection engine.
#
# Values depend on WHAT kind of navigation:
#   * top-level from ad click (cross-site)  → dest=document, mode=navigate,
#     site=cross-site, user=?1
#   * top-level same-site nav (link click)  → site=same-origin, user=?1
#   * XHR/fetch                              → dest=empty, mode=cors,
#     site=<computed>, user unset
#   * subresource (img/css/js)               → dest=<type>, mode=no-cors

def sec_fetch_headers(
    kind: str = "ad_click",
    referer_origin: str = "",
    target_origin: str = "",
) -> Dict[str, str]:
    """Return the correct Sec-Fetch-* header quartet for a given
    navigation kind.  Real Chrome sends these — missing = bot flag."""
    if kind == "ad_click":
        # A user clicking an ad from Facebook / TikTok / Google.
        return {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
        }
    if kind == "same_site_link":
        return {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
    if kind == "typed_url":
        return {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
    # Fallback (safe default = ad click)
    return {
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
    }


# ══════════════════════════════════════════════════════════════════════
# 3. BOT-VENDOR-SPECIFIC STEALTH COHORTS
# ══════════════════════════════════════════════════════════════════════
# One JS blob that inoculates the page against PerimeterX/HUMAN,
# Kasada, Imperva/Distil, F5 Bot Defense, Signal Sciences (Fastly),
# and Radware Bot Manager.  Each block runs at document_start so the
# vendor's inline detector sees a "clean" env before it can probe.

_BOT_VENDOR_STEALTH_JS = r"""
(function(){try{
  // ── PerimeterX / HUMAN Security ────────────────────────────────
  // Their `_px3` cookie is issued after their sensor JS reads:
  //   window.PX?, navigator.deviceMemory, screen.availWidth,
  //   window.chrome, and a canvas token.  We ensure these look
  //   consistent with a low-risk residential Chrome.
  try{
    Object.defineProperty(window, 'PX', {value: undefined, configurable: true});
    if(!navigator.deviceMemory){
      Object.defineProperty(navigator,'deviceMemory',{get:function(){return 8;}});
    }
  }catch(e){}

  // ── Kasada ─────────────────────────────────────────────────────
  // Kasada's script sets `x-kpsdk-ct` via a Worker.  It aborts if it
  // detects `Function.prototype.toString` was overridden (a common
  // Puppeteer tell).  We patch toString to return native code strings
  // for our overridden functions.
  try{
    const origToString = Function.prototype.toString;
    const overriddenFns = new WeakSet();
    Function.prototype.toString = function(){
      if(overriddenFns.has(this))return 'function '+(this.name||'')+'() { [native code] }';
      return origToString.call(this);
    };
    window.__kx_markNative = function(fn){overriddenFns.add(fn);return fn;};
  }catch(e){}

  // ── Imperva / Distil ───────────────────────────────────────────
  // Distil sets `incap_ses_*` cookies via a sensor that checks:
  //   - iframe contentWindow properties
  //   - console.debug behavior
  //   - error stack traces for "puppeteer" / "playwright" / "webdriver"
  // We scrub error stacks of these strings.
  try{
    const origErr = Error;
    const _kxScrubStack = function(s){
      return String(s||'').replace(/(playwright|puppeteer|selenium|webdriver|cdp)/gi,'chrome');
    };
    Object.defineProperty(Error.prototype,'stack',{
      get:function(){try{return _kxScrubStack(this._kxStack||origErr.captureStackTrace);}catch(e){return '';}},
      configurable:true
    });
  }catch(e){}

  // ── F5 Bot Defense ────────────────────────────────────────────
  // F5's `TS*` cookies (TSaaXXXX, TSbXXXX) are issued after their
  // sensor collects mouse/keyboard events with timing.  If NO events
  // are seen in the first 3s they escalate.  We ensure there's ambient
  // pointer activity so the sensor collects "real" data.
  try{
    if(document.body){
      document.body.addEventListener('mousemove',function(){},{passive:true,capture:false});
      document.body.addEventListener('touchstart',function(){},{passive:true,capture:false});
    }
  }catch(e){}

  // ── Signal Sciences (Fastly) ──────────────────────────────────
  // Their `sigsci-token` header requires a valid `Origin` on POSTs.
  // Playwright sometimes omits Origin on same-origin XHR; we patch
  // XMLHttpRequest to always include it.
  try{
    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(m,u){
      this._kxMethod=m;this._kxUrl=u;
      return origOpen.apply(this,arguments);
    };
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function(b){
      try{
        if((this._kxMethod||'').toUpperCase()==='POST' && !this._kxOriginSet){
          this.setRequestHeader('Origin', location.origin);
          this._kxOriginSet=true;
        }
      }catch(e){}
      return origSend.apply(this,arguments);
    };
  }catch(e){}

  // ── Radware Bot Manager ───────────────────────────────────────
  // Radware's `visid_incap_*` requires a valid `document.referrer`
  // that matches Sec-Fetch-Site.  We ensure they agree.
  try{
    // read-only property — nothing to patch here, just verify the
    // Referer header we set matches document.referrer (handled at
    // launch layer already).
  }catch(e){}
}catch(_kxE){}})();
"""


def bot_vendor_stealth_js() -> str:
    """Returns the single JS blob that runs before every page's own JS
    and neutralises the sensor scripts of the 6 bot vendors Krexion
    doesn't already have deep coverage for."""
    return _BOT_VENDOR_STEALTH_JS


# ══════════════════════════════════════════════════════════════════════
# 4. TRACKING PIXEL PRE-FIRE
# ══════════════════════════════════════════════════════════════════════
# Real ad clicks always fire a tracking pixel BEFORE the browser
# navigates to the offer.  Krexion's traffic skips this, so the
# advertiser's postback layer sees a click with no matching pixel event
# — an obvious bot pattern for MaxBounty / Perform[cb] / Cake premium.

def pixel_prefire_urls(platform: str, ttclid: str = "", fbclid: str = "", gclid: str = "") -> List[str]:
    """Return the list of pixel URLs to hit BEFORE the offer, matching
    the platform the visit is coming from.  Firing these makes the
    click look like a real ad-click journey to any postback-based
    fraud engine."""
    p = (platform or "").lower().strip()
    urls: List[str] = []

    if p in ("facebook", "messenger", "instagram"):
        # Facebook Pixel — real ads fire this on click and again on the
        # landing page.  We only fire the click-side ping here.
        pid = "".join(random.choices("0123456789", k=15))
        cid = fbclid or ("fb.1." + str(int(time.time() * 1000)) + "." + "".join(random.choices("0123456789", k=10)))
        urls.append(f"https://www.facebook.com/tr?id={pid}&ev=Lead&fbc={cid}&noscript=1")

    if p == "tiktok":
        # TikTok Pixel + Events API ping.
        pid = "C" + "".join(random.choices("0123456789ABCDEFGHIJKLMNOP", k=19))
        ct = ttclid or ("E.C." + "".join(random.choices("abcdef0123456789", k=32)))
        urls.append(f"https://analytics.tiktok.com/api/v1/pixel/act/?event_source=WEB&pixel_code={pid}&ttclid={ct}")

    if p in ("google", "youtube"):
        # Google Ads / Analytics conversion tracking.
        cid = gclid or ("EAIaIQobChMI" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=24)))
        urls.append(f"https://www.google-analytics.com/collect?v=1&t=event&tid=UA-{random.randint(100000,999999)}-1&cid={cid}&ec=Ad&ea=click")

    if p == "snapchat":
        pid = "".join(random.choices("abcdef0123456789", k=32))
        urls.append(f"https://tr.snapchat.com/p?pid={pid}&ev=CLICK")

    if p == "linkedin":
        pid = str(random.randint(1000000, 9999999))
        urls.append(f"https://px.ads.linkedin.com/collect/?pid={pid}&fmt=gif")

    if p in ("twitter",):
        pid = "o" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=5))
        urls.append(f"https://analytics.twitter.com/i/adsct?p_id={pid}&events=%5B%5B%22click%22%5D%5D")

    if p == "reddit":
        pid = "t2_" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
        urls.append(f"https://alb.reddit.com/rp.gif?id={pid}&type=click")

    if p == "pinterest":
        pid = str(random.randint(2600000000, 2700000000))
        urls.append(f"https://ct.pinterest.com/v3/?tid={pid}&event=Lead&ed=%7B%22source%22%3A%22web%22%7D")

    return urls


# ══════════════════════════════════════════════════════════════════════
# 5. REFERRER CHAIN SIMULATION
# ══════════════════════════════════════════════════════════════════════
# Real user journey: Platform → CDN redirect → Aggregator → Offer.
# Krexion default is 2 hops (Platform → Krexion tracker → Offer).
# Adding 1-2 intermediate hops through realistic short-link domains
# makes the HAR file look natural.

_INTERMEDIATE_HOP_DOMAINS: Dict[str, List[str]] = {
    "facebook":  ["l.facebook.com", "lm.facebook.com", "l.messenger.com"],
    "messenger": ["l.messenger.com", "l.facebook.com"],
    "instagram": ["l.instagram.com"],
    "tiktok":    ["www.tiktok.com/link/v2", "vm.tiktok.com"],
    "youtube":   ["www.youtube.com/redirect"],   # careful — has known leak fixed in v2.2.5
    "google":    ["www.google.com/url", "google.com/url"],
    "twitter":   ["t.co"],
    "linkedin":  ["www.linkedin.com/redir/redirect"],
    "snapchat":  ["snapchat.com/l"],
    "reddit":    ["out.reddit.com"],
    "pinterest": ["pinterest.com/offsite"],
    "generic":   ["bit.ly", "tinyurl.com", "ow.ly", "buff.ly", "linkbud.com"],
}


def intermediate_hop_urls(platform: str, offer_url: str, hops: int = 1) -> List[str]:
    """Return `hops` intermediate hop URLs to visit between the platform
    and the offer.  Each URL is a realistic short-link/redirect domain
    that carries the offer URL as a query parameter — mimics the
    natural multi-hop journey of a real ad click."""
    p = (platform or "").lower().strip()
    pool = _INTERMEDIATE_HOP_DOMAINS.get(p) or _INTERMEDIATE_HOP_DOMAINS["generic"]
    picks = random.sample(pool, min(hops, len(pool)))
    out: List[str] = []
    for dom in picks:
        # Build a plausible redirect URL for that domain
        if "l.facebook.com" in dom or "l.messenger.com" in dom or "l.instagram.com" in dom:
            token = "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_", k=200))
            out.append(f"https://{dom}/l.php?u={offer_url}&h={token}")
        elif "google.com/url" in dom:
            out.append(f"https://{dom}?sa=t&url={offer_url}&usg=" + "".join(random.choices("abcdef0123456789", k=32)))
        elif "linkedin.com/redir" in dom:
            out.append(f"https://{dom}?url={offer_url}&urlhash=" + "".join(random.choices("abcdef0123456789", k=8)))
        elif dom == "t.co":
            out.append(f"https://t.co/" + "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=10)))
        elif dom in ("bit.ly", "tinyurl.com", "ow.ly", "buff.ly", "linkbud.com"):
            slug = "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=7))
            out.append(f"https://{dom}/{slug}")
        else:
            # Generic pattern
            out.append(f"https://{dom}/?url={offer_url}")
    return out


async def fire_pixel_prefire(
    page: Any,
    *,
    platform: str = "",
    ttclid: str = "",
    fbclid: str = "",
    gclid: str = "",
    timeout_ms: int = 8000,
) -> List[str]:
    """Fire platform pixel URLs before the offer navigation.

    Uses Playwright's request API so pixels hit the network without
    leaving the current page. Never raises — returns the list of URLs
    that returned a sub-500 response."""
    urls = pixel_prefire_urls(platform, ttclid=ttclid, fbclid=fbclid, gclid=gclid)
    fired: List[str] = []
    for url in urls:
        try:
            resp = await page.request.get(url, timeout=timeout_ms)
            if resp and int(resp.status or 0) < 500:
                fired.append(url)
        except Exception as exc:
            logger.debug("pixel prefire failed %s: %s", url[:80], exc)
    return fired


async def navigate_intermediate_hops(
    page: Any,
    *,
    platform: str = "",
    offer_url: str = "",
    hops: int = 1,
    timeout_ms: int = 15000,
) -> List[str]:
    """Visit 1-N intermediate redirect hops before the final offer URL.

    Mimics the multi-hop journey of a real ad click (l.facebook.com,
    t.co, bit.ly, …). Never raises — returns URLs successfully visited."""
    urls = intermediate_hop_urls(platform, offer_url, hops=max(1, int(hops or 1)))
    visited: List[str] = []
    for url in urls:
        try:
            await page.goto(url, wait_until="commit", timeout=timeout_ms)
            visited.append(url)
            await asyncio.sleep(random.uniform(0.35, 1.15))
        except Exception as exc:
            logger.debug("intermediate hop failed %s: %s", url[:80], exc)
    return visited


# ══════════════════════════════════════════════════════════════════════
# 6. POST-CONVERSION BEHAVIOUR SIMULATION
# ══════════════════════════════════════════════════════════════════════
# Real users spend 30-120s on the thank-you page.  Immediate browser
# close = bot signal for MaxBounty Premium / Perform[cb] top-tier.

_POST_CONVERSION_JS = r"""
(function(){try{
  // Only run if we're on a page that looks like a thank-you / confirmation.
  const looksLikeThankYou = /thank|success|confirm|order|complete|welcome|done/i.test(
    (document.title || '') + ' ' + (location.pathname || '')
  );
  if(!looksLikeThankYou) return;
  window.__kx_postConversion = true;
  // Realistic browsing behaviour: gentle scroll + focus loss + return.
  const stayMs = 30000 + Math.floor(Math.random() * 90000);   // 30-120s
  const scrollTicks = 6 + Math.floor(Math.random() * 8);
  const scrollAtIdx = i => Math.floor((i / scrollTicks) * (document.body.scrollHeight || 800));
  for(let i = 0; i < scrollTicks; i++){
    setTimeout(function(){
      try{window.scrollTo({top: scrollAtIdx(i), behavior: 'smooth'});}catch(e){}
    }, Math.floor((i / scrollTicks) * stayMs));
  }
  // Simulate a tab-away and return at ~60% of stay
  setTimeout(function(){
    try{Object.defineProperty(document,'visibilityState',{get:function(){return 'hidden';},configurable:true});
        document.dispatchEvent(new Event('visibilitychange'));}catch(e){}
  }, Math.floor(stayMs * 0.6));
  setTimeout(function(){
    try{Object.defineProperty(document,'visibilityState',{get:function(){return 'visible';},configurable:true});
        document.dispatchEvent(new Event('visibilitychange'));}catch(e){}
  }, Math.floor(stayMs * 0.85));
}catch(e){}})();
"""


def post_conversion_js() -> str:
    """JS blob injected on every page — activates only when the URL/
    title look like a thank-you page and then simulates 30-120s of
    natural post-conversion browsing (scroll, tab-away, tab-return)."""
    return _POST_CONVERSION_JS


# ══════════════════════════════════════════════════════════════════════
# 7. FULL CLIENT HINTS HEADERS
# ══════════════════════════════════════════════════════════════════════
# Real Chrome 128+ sends 10+ Sec-CH-UA-* headers on secure requests.
# Krexion previously sent only 2-3.  Missing = old-Chrome or bot signal.

def full_client_hints(ua: str, viewport: Optional[Dict[str, int]] = None) -> Dict[str, str]:
    """Return all Sec-CH-UA-* / Sec-CH-* / Sec-CH-Prefers-* headers
    real Chrome 128+ sends, matching the UA + viewport passed in."""
    viewport = viewport or {"width": 1920, "height": 1080}
    # v2.6.30 — non-Chrome in-app UAs must not get branded Sec-CH-UA.
    # Mirrors real_user_traffic._build_client_hint_headers() so profile
    # launcher and v230 paths don't undo TikTok/FB-iOS suppression.
    try:
        from referrer_pro import is_non_chrome_inapp_ua as _is_nci
        if _is_nci(ua):
            ua_low = (ua or "").lower()
            headers: Dict[str, str] = {"Sec-CH-UA": ""}
            if "iphone" in ua_low or "ipad" in ua_low:
                headers["Sec-CH-UA-Platform"] = '"iOS"'
                headers["Sec-CH-UA-Mobile"] = "?1"
                _ios_m = re.search(r"iPhone OS (\d+)_(\d+)", ua or "")
                if _ios_m:
                    headers["Sec-CH-UA-Platform-Version"] = f'"{_ios_m.group(1)}.{_ios_m.group(2)}.0"'
            elif "android" in ua_low:
                headers["Sec-CH-UA-Platform"] = '"Android"'
                headers["Sec-CH-UA-Mobile"] = "?1"
            else:
                headers["Sec-CH-UA-Mobile"] = "?0"
            return headers
    except Exception:
        pass
    m = re.search(r"Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)", ua or "")
    full_ver = m.group(0).split("/")[1] if m else "128.0.6613.146"
    major_ver = m.group(1) if m else "128"
    ua_low = (ua or "").lower()

    # Platform detection
    if "windows" in ua_low:
        platform = '"Windows"'; platform_ver = '"15.0.0"'; arch = '"x86"'; bitness = '"64"'
        model = '""'; mobile = "?0"
    elif "iphone" in ua_low or "ipad" in ua_low:
        platform = '"iOS"'
        _ios_m = re.search(r"iPhone OS (\d+)_(\d+)", ua or "")
        platform_ver = f'"{_ios_m.group(1)}.{_ios_m.group(2)}.0"' if _ios_m else '"17.0.0"'
        arch = '"arm"'; bitness = '"64"'
        model = '"iPhone"' if "iphone" in ua_low else '"iPad"'; mobile = "?1"
    elif "android" in ua_low:
        platform = '"Android"'; platform_ver = '"14.0.0"'; arch = '"arm"'; bitness = '"64"'
        _model_m = re.search(r"Android[^;]*;\s*([^);]+)", ua or "")
        if _model_m:
            _model_raw = re.split(r"\s+Build/", _model_m.group(1).strip(), maxsplit=1)[0].strip()
            model = f'"{_model_raw}"' if _model_raw else '""'
        else:
            model = '""'
        mobile = "?1"
    elif "mac os" in ua_low or "macintosh" in ua_low:
        platform = '"macOS"'; platform_ver = '"15.1.0"'; arch = '"arm"'; bitness = '"64"'
        model = '""'; mobile = "?0"
    else:
        platform = '"Linux"'; platform_ver = '"6.5.0"'; arch = '"x86"'; bitness = '"64"'
        model = '""'; mobile = "?0"

    # Chrome brand list — real Chrome uses GREASE (a random brand +
    # the real brand + "Chromium").  The GREASE brand shuffles per
    # request but the shape is stable.
    grease_brand = random.choice(['"Not.A/Brand"', '"Not_A Brand"', '"Not?A_Brand"', '"Not-A.Brand"'])
    grease_ver = random.choice(['"8"', '"24"', '"99"'])
    ua_short = f'{grease_brand};v={grease_ver}, "Chromium";v="{major_ver}", "Google Chrome";v="{major_ver}"'
    ua_full  = f'{grease_brand};v={grease_ver}, "Chromium";v="{full_ver}", "Google Chrome";v="{full_ver}"'

    # DPR: prefer viewport device_scale_factor; else mobile→2/3, desktop→1.
    _dsf = viewport.get("device_scale_factor") if isinstance(viewport, dict) else None
    if _dsf is not None:
        try:
            dpr = str(float(_dsf)).rstrip("0").rstrip(".") if "." in str(float(_dsf)) else str(int(float(_dsf)))
            if dpr == "":
                dpr = "1"
        except Exception:
            dpr = "3" if mobile == "?1" else "1"
    elif mobile == "?1":
        dpr = "3"
    else:
        dpr = "1"

    return {
        "Sec-CH-UA": ua_short,
        "Sec-CH-UA-Mobile": mobile,
        "Sec-CH-UA-Platform": platform,
        "Sec-CH-UA-Full-Version-List": ua_full,
        "Sec-CH-UA-Platform-Version": platform_ver,
        "Sec-CH-UA-Model": model,
        "Sec-CH-UA-Arch": f'"{arch.strip(chr(34))}"',
        "Sec-CH-UA-Bitness": bitness,
        "Sec-CH-UA-WoW64": "?0",
        "Sec-CH-Prefers-Color-Scheme": '"light"',
        "Sec-CH-Prefers-Reduced-Motion": '"no-preference"',
        "Sec-CH-Viewport-Width": str(int(viewport.get("width", 1920))),
        "Sec-CH-DPR": dpr,
    }


# ══════════════════════════════════════════════════════════════════════
# 8. CHROMIUM BINARY VERSION ↔ UA STRING DRIFT CHECK
# ══════════════════════════════════════════════════════════════════════
def align_ua_to_chromium(ua: str, actual_chromium_ver: Optional[int] = None) -> str:
    """Rewrite the Chrome/CriOS major in `ua` to match `actual_chromium_ver`
    (or auto-detect if omitted). Always match binary major when drift > 0.
    If actual version can't be detected, returns UA unchanged (safe no-op)."""
    if not ua:
        return ua
    if actual_chromium_ver is None:
        actual_chromium_ver = detect_installed_chromium_major()
    if not actual_chromium_ver:
        return ua

    def _rewrite_token(token: str, text: str) -> str:
        m = re.search(rf"{token}/(\d+)", text)
        if not m:
            return text
        declared = int(m.group(1))
        if abs(declared - actual_chromium_ver) == 0:
            return text
        # Prefer full x.y.z.w rewrite; fall back to major-only token.
        rewritten = re.sub(
            rf"({token}/)\d+(\.\d+\.\d+\.\d+)",
            lambda m2: f"{m2.group(1)}{actual_chromium_ver}{m2.group(2)}",
            text,
            count=1,
        )
        if rewritten != text:
            return rewritten
        return re.sub(
            rf"({token}/)\d+",
            rf"\g<1>{actual_chromium_ver}",
            text,
            count=1,
        )

    out = _rewrite_token("Chrome", ua)
    out = _rewrite_token("CriOS", out)
    return out


def detect_installed_chromium_major() -> Optional[int]:
    """Best-effort major Chrome version from Playwright's full Chromium
    binary or a system Chrome install. Used to align UA strings with
    the actual TLS / Sec-CH-UA binary the visit runs."""
    try:
        import os
        import subprocess
        from pathlib import Path

        browsers_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
        try:
            import playwright as _pw
            bj = Path(_pw.__file__).parent / "driver" / "package" / "browsers.json"
            if bj.exists():
                with open(bj, "r", encoding="utf-8") as fh:
                    data = __import__("json").load(fh)
                rev = None
                for entry in data.get("browsers", []):
                    if entry.get("name") == "chromium":
                        rev = str(entry.get("revision") or "").strip() or None
                        break
                if rev:
                    plat = "win64" if os.name == "nt" else ("mac-arm64" if os.uname().machine == "arm64" else "linux64")
                    if os.name == "nt":
                        bin_name = "chrome.exe"
                    elif sys.platform == "darwin":
                        bin_name = "Chromium"
                        plat = "mac-arm64" if "arm" in (os.uname().machine or "").lower() else "mac-x64"
                    else:
                        bin_name = "chrome"
                    exe = Path(browsers_root) / f"chromium-{rev}" / plat / bin_name
                    if exe.exists():
                        r = subprocess.run(
                            [str(exe), "--version"],
                            capture_output=True, text=True, timeout=5,
                        )
                        m = re.search(r"(\d+)\.\d+\.\d+\.\d+", (r.stdout or r.stderr or ""))
                        if m:
                            return int(m.group(1))
        except Exception:
            pass
        for cmd in (["chromium", "--version"], ["chrome", "--version"], ["google-chrome", "--version"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                m = re.search(r"(\d+)\.\d+\.\d+\.\d+", r.stdout or r.stderr or "")
                if m:
                    return int(m.group(1))
            except Exception:
                continue
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════
# 8b. CDP / PLAYWRIGHT RUNTIME STEALTH
# ══════════════════════════════════════════════════════════════════════
# Playwright MUST keep CDP attached for automation — we cannot detach it
# without breaking the visit. These JS patches hide the *detectable*
# side-effects of an attached CDP session (debugger traps, binding
# objects, devtools dimension skew, missing chrome.runtime, etc.).

_CDP_STEALTH_JS = r"""
(function(){try{
  // ── Strip Playwright / Puppeteer binding leaks on window ──
  const HIDE_KEYS = [
    '__playwright','__pw_manual','__pwInitScripts','__pw_recorder',
    '__playwright__binding__','__pw','_playwright','playwright',
  ];
  HIDE_KEYS.forEach(function(k){
    try{ delete window[k]; }catch(e){}
    try{ Object.defineProperty(window,k,{get:function(){return undefined;},configurable:true}); }catch(e){}
  });

  // ── Filter cdc_ / webdriver artifacts from enumeration ──
  const BAD = /^(cdc_|__webdriver|__driver|__fxdriver|__selenium|\$cdc_|__playwright|__pw)/i;
  const origOwn = Object.getOwnPropertyNames;
  Object.getOwnPropertyNames = function(t){
    var keys = origOwn.apply(this, arguments);
    return t === window ? keys.filter(function(k){ return !BAD.test(String(k)); }) : keys;
  };
  const origKeys = Reflect.ownKeys;
  Reflect.ownKeys = function(t){
    var keys = origKeys.apply(this, arguments);
    return t === window ? keys.filter(function(k){ return !BAD.test(String(k)); }) : keys;
  };

  // ── Neutralize debugger; loops used to detect attached DevTools ──
  try{
    const origFunc = Function;
    const wrapped = function(){
      var args = Array.prototype.slice.call(arguments);
      if(args.length){
        var body = String(args[args.length - 1] || '');
        if(/debugger\s*;?/.test(body)){
          args[args.length - 1] = body.replace(/\bdebugger\s*;?/g, ';');
        }
      }
      return origFunc.apply(this, args);
    };
    wrapped.prototype = origFunc.prototype;
    Function = wrapped;
  }catch(e){}

  // ── chrome.runtime stub (extension-less real Chrome still has it) ──
  try{
    window.chrome = window.chrome || {};
    if(!window.chrome.runtime){
      window.chrome.runtime = {
        connect: function(){ return { onMessage: { addListener: function(){} }, postMessage: function(){} }; },
        sendMessage: function(){ return Promise.resolve(undefined); },
        id: undefined,
      };
    }
    if(!window.chrome.app){
      window.chrome.app = { isInstalled: false, getDetails: function(){ return null; } };
    }
  }catch(e){}

  // ── DevTools dock skew — detectors compare outer vs inner width ──
  try{
    var ow = window.outerWidth, oh = window.outerHeight;
    var iw = window.innerWidth, ih = window.innerHeight;
    if(ow - iw > 180 || oh - ih > 180){
      Object.defineProperty(window,'outerWidth',{get:function(){ return iw; }, configurable:true});
      Object.defineProperty(window,'outerHeight',{get:function(){ return ih + 85; }, configurable:true});
    }
  }catch(e){}

  // ── Block Error.prepareStackTrace CDP hooks when present ──
  try{
    if(Error.prepareStackTrace){
      Error.prepareStackTrace = undefined;
    }
  }catch(e){}
}catch(_kxE){}})();
"""


def cdp_stealth_js(*, safari_mode: bool = False) -> str:
    """JS patches that hide attached CDP / Playwright runtime side-effects."""
    if safari_mode:
        # Same scrub without inventing window.chrome (Safari must not have it).
        return r"""
(() => { try {
  try {
    const proto = Navigator.prototype;
    if (proto && 'webdriver' in proto) {
      Object.defineProperty(proto, 'webdriver', { get: () => undefined, configurable: true });
    }
  } catch (e) {}
  try {
    const names = Object.getOwnPropertyNames(window);
    for (const n of names) {
      if (/^cdc_|__playwright|__pw_|__webdriver/i.test(n)) {
        try { delete window[n]; } catch (e2) {}
      }
    }
  } catch (e) {}
  try {
    if (Error.prepareStackTrace) Error.prepareStackTrace = undefined;
  } catch (e) {}
} catch (_kxE) {} })();
"""
    return _CDP_STEALTH_JS


# ══════════════════════════════════════════════════════════════════════
# 9. MOBILE-SPECIFIC SIGNALS (Touch / DeviceMotion / visualViewport …)
# ══════════════════════════════════════════════════════════════════════
_MOBILE_SIGNALS_JS = r"""
(function(){try{
  const isMobile = /iPhone|iPad|Android/i.test(navigator.userAgent);
  if(!isMobile) return;

  // TouchEvent constructor + realistic touch points
  try{
    if(typeof TouchEvent === 'undefined'){
      window.TouchEvent = window.MouseEvent;
    }
    // navigator.maxTouchPoints must be ≥1 for a mobile UA
    if(!navigator.maxTouchPoints){
      Object.defineProperty(navigator,'maxTouchPoints',{get:function(){return 5;}});
    }
  }catch(e){}

  // DeviceMotionEvent + DeviceOrientationEvent stubs
  try{
    if(!window.DeviceMotionEvent){
      window.DeviceMotionEvent = function(){};
    }
    if(!window.DeviceOrientationEvent){
      window.DeviceOrientationEvent = function(){};
    }
  }catch(e){}

  // visualViewport (iOS Safari signature)
  try{
    if(!window.visualViewport){
      Object.defineProperty(window,'visualViewport',{get:function(){
        return {
          width: window.innerWidth, height: window.innerHeight,
          scale: 1, offsetLeft: 0, offsetTop: 0, pageLeft: 0, pageTop: 0,
          addEventListener: function(){}, removeEventListener: function(){},
        };
      }});
    }
  }catch(e){}

  // Network Information API — real mobile Chrome sends 4g/wifi
  try{
    if(!navigator.connection){
      Object.defineProperty(navigator,'connection',{get:function(){
        return {
          effectiveType: '4g', downlink: 10, rtt: 50, saveData: false,
          type: 'cellular',
          addEventListener: function(){}, removeEventListener: function(){},
        };
      }});
    }
  }catch(e){}

  // Screen Orientation API
  try{
    if(!screen.orientation){
      Object.defineProperty(screen,'orientation',{get:function(){
        return { type: 'portrait-primary', angle: 0,
                 addEventListener: function(){}, removeEventListener: function(){} };
      }});
    }
  }catch(e){}

  // PointerEvent — patch to include pointerType = 'touch' by default
  try{
    const OrigPE = window.PointerEvent;
    if(OrigPE){
      window.PointerEvent = function(type, init){
        init = init || {};
        if(!init.pointerType) init.pointerType = 'touch';
        return new OrigPE(type, init);
      };
      window.PointerEvent.prototype = OrigPE.prototype;
    }
  }catch(e){}

  // userAgentData mobile bit — real Android/iOS Chrome exposes this
  try{
    if(navigator.userAgentData && typeof navigator.userAgentData.getHighEntropyValues==='function'){
      const origGet = navigator.userAgentData.getHighEntropyValues.bind(navigator.userAgentData);
      navigator.userAgentData.getHighEntropyValues = function(hints){
        return origGet(hints).then(function(v){
          v = v || {};
          v.mobile = true;
          v.platform = /iphone|ipad|ipod/i.test(navigator.userAgent) ? 'iOS' : 'Android';
          return v;
        });
      };
    }else if(!navigator.userAgentData){
      Object.defineProperty(navigator,'userAgentData',{
        get:function(){
          return {
            mobile:true,
            platform:/iphone|ipad|ipod/i.test(navigator.userAgent)?'iOS':'Android',
            brands:[{brand:'Google Chrome',version:'131'},{brand:'Chromium',version:'131'}],
            getHighEntropyValues:function(){
              return Promise.resolve({ mobile:true, platform:this.platform, brands:this.brands });
            }
          };
        }
      });
    }
  }catch(e){}

  // Real mobile pages expose ontouchstart on the document element
  try{
    if(document && document.documentElement && !('ontouchstart' in document.documentElement)){
      document.documentElement.ontouchstart = null;
    }
  }catch(e){}
}catch(_kxE){}})();
"""


def mobile_signals_js() -> str:
    """JS that adds TouchEvents, DeviceMotion, visualViewport, Network
    Info, Screen Orientation, and PointerEvent hooks required for a
    mobile UA to look like a real mobile Chrome/Safari."""
    return _MOBILE_SIGNALS_JS


# ══════════════════════════════════════════════════════════════════════
# 10. WEBGL EXTENSIONS DEEP SPOOF
# ══════════════════════════════════════════════════════════════════════
_WEBGL_EXTENSIONS_JS = r"""
(function(){try{
  // Real Chrome + NVIDIA/Intel/AMD GPU returns ~28-32 extensions in
  // getSupportedExtensions().  Krexion's baseline only spoofs vendor/
  // renderer — missing extensions list is a give-away.
  const REAL_EXTS = [
    'ANGLE_instanced_arrays','EXT_blend_minmax','EXT_color_buffer_half_float',
    'EXT_disjoint_timer_query','EXT_float_blend','EXT_frag_depth',
    'EXT_shader_texture_lod','EXT_texture_compression_bptc',
    'EXT_texture_compression_rgtc','EXT_texture_filter_anisotropic',
    'EXT_sRGB','OES_element_index_uint','OES_fbo_render_mipmap',
    'OES_standard_derivatives','OES_texture_float','OES_texture_float_linear',
    'OES_texture_half_float','OES_texture_half_float_linear','OES_vertex_array_object',
    'WEBGL_color_buffer_float','WEBGL_compressed_texture_s3tc',
    'WEBGL_compressed_texture_s3tc_srgb','WEBGL_debug_renderer_info',
    'WEBGL_debug_shaders','WEBGL_depth_texture','WEBGL_draw_buffers',
    'WEBGL_lose_context','WEBGL_multi_draw','WEBGL_provoking_vertex',
    'KHR_parallel_shader_compile',
  ];
  const patch = function(proto){
    if(!proto) return;
    const orig = proto.getSupportedExtensions;
    if(!orig) return;
    proto.getSupportedExtensions = function(){
      return REAL_EXTS.slice();
    };
  };
  patch(WebGLRenderingContext && WebGLRenderingContext.prototype);
  if(typeof WebGL2RenderingContext !== 'undefined'){
    patch(WebGL2RenderingContext.prototype);
  }
}catch(e){}})();
"""


def webgl_extensions_js() -> str:
    return _WEBGL_EXTENSIONS_JS


# ══════════════════════════════════════════════════════════════════════
# 11. SPEECH SYNTHESIS VOICES SPOOF
# ══════════════════════════════════════════════════════════════════════
_SPEECH_VOICES_JS = r"""
(function(){try{
  const ua = navigator.userAgent.toLowerCase();
  let voices = [];
  if(ua.indexOf('windows') !== -1){
    voices = [
      {name:'Microsoft David - English (United States)', lang:'en-US', voiceURI:'Microsoft David', localService:true, default:true},
      {name:'Microsoft Mark - English (United States)', lang:'en-US', voiceURI:'Microsoft Mark', localService:true, default:false},
      {name:'Microsoft Zira - English (United States)', lang:'en-US', voiceURI:'Microsoft Zira', localService:true, default:false},
      {name:'Google US English', lang:'en-US', voiceURI:'Google US English', localService:false, default:false},
      {name:'Google UK English Female', lang:'en-GB', voiceURI:'Google UK English Female', localService:false, default:false},
      {name:'Google UK English Male', lang:'en-GB', voiceURI:'Google UK English Male', localService:false, default:false},
    ];
  }else if(ua.indexOf('mac os') !== -1 || ua.indexOf('iphone') !== -1 || ua.indexOf('ipad') !== -1){
    voices = [
      {name:'Alex', lang:'en-US', voiceURI:'com.apple.speech.synthesis.voice.Alex', localService:true, default:true},
      {name:'Samantha', lang:'en-US', voiceURI:'com.apple.voice.compact.en-US.Samantha', localService:true, default:false},
      {name:'Daniel', lang:'en-GB', voiceURI:'com.apple.voice.compact.en-GB.Daniel', localService:true, default:false},
      {name:'Karen', lang:'en-AU', voiceURI:'com.apple.voice.compact.en-AU.Karen', localService:true, default:false},
    ];
  }else{
    voices = [
      {name:'Google US English', lang:'en-US', voiceURI:'Google US English', localService:false, default:true},
      {name:'Google UK English Female', lang:'en-GB', voiceURI:'Google UK English Female', localService:false, default:false},
    ];
  }
  const buildVoiceList = () => voices.map(v => Object.assign(Object.create(SpeechSynthesisVoice.prototype||{}), v));
  try{
    Object.defineProperty(window.speechSynthesis,'getVoices',{value:buildVoiceList,configurable:true});
  }catch(e){}
}catch(_kxE){}})();
"""


def speech_voices_js() -> str:
    return _SPEECH_VOICES_JS


# ══════════════════════════════════════════════════════════════════════
# 12. BATTERY API FLUCTUATION
# ══════════════════════════════════════════════════════════════════════
_BATTERY_JS = r"""
(function(){try{
  const startLevel = 0.20 + Math.random() * 0.75;   // 20-95%
  const isCharging = Math.random() < 0.35;          // 35% users charging
  const state = {
    charging: isCharging, level: startLevel,
    chargingTime: isCharging ? Math.floor(Math.random() * 3600) : Infinity,
    dischargingTime: isCharging ? Infinity : Math.floor(60 * (Math.random() * 200 + 60)),
  };
  const listeners = { levelchange: [], chargingchange: [] };
  const battery = {
    get charging(){return state.charging;},
    get level(){return state.level;},
    get chargingTime(){return state.chargingTime;},
    get dischargingTime(){return state.dischargingTime;},
    addEventListener: function(t,cb){if(listeners[t]) listeners[t].push(cb);},
    removeEventListener: function(t,cb){if(listeners[t]) listeners[t] = listeners[t].filter(x => x!==cb);},
    dispatchEvent: function(){return true;},
  };
  // Fluctuate every 45-90s
  setInterval(function(){
    if(state.charging){
      state.level = Math.min(1, state.level + 0.005);
    }else{
      state.level = Math.max(0.05, state.level - 0.002);
    }
    listeners.levelchange.forEach(function(cb){try{cb({});}catch(e){}});
  }, 45000 + Math.random() * 45000);
  if(navigator.getBattery){
    const orig = navigator.getBattery;
    navigator.getBattery = function(){return Promise.resolve(battery);};
  }else{
    navigator.getBattery = function(){return Promise.resolve(battery);};
  }
}catch(_kxE){}})();
"""


def battery_fluctuation_js() -> str:
    return _BATTERY_JS


# ══════════════════════════════════════════════════════════════════════
# 13. PRIVACY SANDBOX API STUBS
# ══════════════════════════════════════════════════════════════════════
_PRIVACY_SANDBOX_JS = r"""
(function(){try{
  // Topics API — Chrome 128+ ships it enabled by default.
  if(!document.browsingTopics){
    Object.defineProperty(document,'browsingTopics',{value:function(){
      // Return 3 realistic topic IDs (Chrome only exposes recent
      // topics the user was profiled into).
      return Promise.resolve([
        { topic: 22, version: 'chrome.2:2:2', taxonomyVersion: '2', modelVersion: '4' },
        { topic: 57, version: 'chrome.2:2:2', taxonomyVersion: '2', modelVersion: '4' },
        { topic: 133, version: 'chrome.2:2:2', taxonomyVersion: '2', modelVersion: '4' },
      ]);
    },configurable:true});
  }
  // Attribution Reporting API stubs.
  if(!window.attributionReporting){
    Object.defineProperty(window,'attributionReporting',{value:{
      registerSource: function(){return Promise.resolve();},
      registerTrigger: function(){return Promise.resolve();},
    },configurable:true});
  }
  // Fenced Frames stub (needed for FLEDGE/Protected Audience).
  if(!window.HTMLFencedFrameElement){
    // Just needs to be defined so `typeof` checks return 'function'.
    window.HTMLFencedFrameElement = function(){};
  }
}catch(_kxE){}})();
"""


def privacy_sandbox_js() -> str:
    return _PRIVACY_SANDBOX_JS


# ══════════════════════════════════════════════════════════════════════
# 14. EXTENSION EMULATION (fake plugins in navigator.plugins)
# ══════════════════════════════════════════════════════════════════════
_EXTENSION_EMU_JS = r"""
(function(){try{
  // Real users usually have 3-8 extensions.  We fake 3-5 in the
  // plugins list.  Only runs on desktop (mobile Chrome has no
  // navigator.plugins entries).
  if(/iPhone|iPad|Android/i.test(navigator.userAgent)) return;
  const fakePlugins = [
    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
      description: 'Portable Document Format' },
    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
      description: '' },
    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
  ];
  // 30% of users have Grammarly, 20% LastPass, 25% uBlock.
  if(Math.random() < 0.30) fakePlugins.push({
    name: 'Grammarly', filename: 'grammarly.crx', description: 'Grammar checker'
  });
  if(Math.random() < 0.20) fakePlugins.push({
    name: 'LastPass', filename: 'lastpass.crx', description: 'Password manager'
  });
  try{
    Object.defineProperty(navigator,'plugins',{get:function(){
      const arr = fakePlugins.map(p => Object.assign({length:1, item:()=>null, namedItem:()=>null}, p));
      arr.length = fakePlugins.length;
      arr.item = function(i){return arr[i];};
      arr.namedItem = function(n){return arr.find(x=>x.name===n) || null;};
      arr.refresh = function(){};
      return arr;
    },configurable:true});
    Object.defineProperty(navigator,'mimeTypes',{get:function(){
      const mt = [{type:'application/pdf',suffixes:'pdf',description:'',enabledPlugin:fakePlugins[0]}];
      mt.length = mt.length;
      mt.item = function(i){return mt[i];};
      mt.namedItem = function(n){return mt.find(x=>x.type===n) || null;};
      return mt;
    },configurable:true});
  }catch(e){}
}catch(_kxE){}})();
"""


def extension_emulation_js() -> str:
    return _EXTENSION_EMU_JS


# ══════════════════════════════════════════════════════════════════════
# 15. AD BLOCKER REALISM
# ══════════════════════════════════════════════════════════════════════
_AD_BLOCKER_JS = r"""
(function(){try{
  // ~70% of US desktop users have an ad blocker.  If we present a
  // completely clean environment on every visit, that's a bot signal.
  // We flip a coin at page load and apply light ad-blocker DOM
  // signatures ~65% of the time on desktop.  Never on mobile.
  if(/iPhone|iPad|Android/i.test(navigator.userAgent)) return;
  if(Math.random() > 0.65) return;

  // uBlock Origin injects a <style> with `.dnt` and blocks known
  // ad hostnames from loading.  We simulate the DOM footprint
  // (a hidden div with a well-known adblock ID) — this is what
  // most ad-blocker-detection scripts probe for.
  const observer = function(){
    try{
      const bait = document.createElement('div');
      bait.id = 'adBanner';
      bait.className = 'adsbox pub_300x250 pub_300x250m';
      bait.style.cssText = 'width:1px;height:1px;position:absolute;left:-9999px;top:-9999px;';
      (document.body || document.documentElement).appendChild(bait);
      // Ad blockers hide this element within 100ms → checkers see
      // offsetHeight === 0.  We do the same.
      setTimeout(function(){
        try{bait.style.display = 'none';}catch(e){}
      }, 50 + Math.random() * 40);
    }catch(e){}
  };
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', observer);
  }else{
    observer();
  }
}catch(_kxE){}})();
"""


def ad_blocker_realism_js() -> str:
    return _AD_BLOCKER_JS


# ══════════════════════════════════════════════════════════════════════
# 16. FIRST-PARTY-SETS / RELATED WEBSITE SETS
# ══════════════════════════════════════════════════════════════════════
_FIRST_PARTY_SETS_JS = r"""
(function(){try{
  // Chrome 130+ ships Related Website Sets (formerly First-Party
  // Sets) at document.hasStorageAccessFor / Storage Access API level.
  // Missing = pre-2024 Chrome or bot signal.
  if(document.hasStorageAccessFor === undefined){
    Object.defineProperty(document,'hasStorageAccessFor',{value:function(u){
      return Promise.resolve(true);
    },configurable:true});
  }
  if(document.requestStorageAccessFor === undefined){
    Object.defineProperty(document,'requestStorageAccessFor',{value:function(u){
      return Promise.resolve();
    },configurable:true});
  }
  // Storage Access API baseline (Chrome 119+)
  if(document.hasStorageAccess === undefined){
    Object.defineProperty(document,'hasStorageAccess',{value:function(){
      return Promise.resolve(false);
    },configurable:true});
  }
  if(document.requestStorageAccess === undefined){
    Object.defineProperty(document,'requestStorageAccess',{value:function(){
      return Promise.resolve();
    },configurable:true});
  }
}catch(_kxE){}})();
"""


def first_party_sets_js() -> str:
    return _FIRST_PARTY_SETS_JS


# ══════════════════════════════════════════════════════════════════════
# 18. NATURAL CANVAS FINGERPRINT (Multilogin-style, not pure XOR)
# ══════════════════════════════════════════════════════════════════════
# Why this exists:
#   The baseline `_build_stealth_script` in real_user_traffic.py flips
#   the low bit of every RGBA pixel via XOR — cheap and effective for
#   simple fingerprinters, BUT modern anti-fraud (Cloudflare Turnstile,
#   DataDome, HUMAN Bot Defender) has started to detect pure-XOR noise
#   because it produces a *uniform* distribution of bit-flips that no
#   real GPU driver ever emits. Real GPU output has:
#     - Subpixel rounding quirks (nearest-neighbour vs bilinear)
#     - Anti-aliasing patterns (edges get ±1-2 on RGB, alpha untouched)
#     - Regional consistency (adjacent pixels have correlated jitter)
#     - Alpha channel almost never varies (real GPUs preserve it)
#
# This module emits a deterministic Perlin-lite noise field seeded by
# the profile ID (same profile → same fingerprint every session), that
# perturbs pixels only NEAR EDGES (Sobel-detected) with correlated
# neighbour offsets and never touches alpha. This looks like a real
# GPU driver, not a bot.
_NATURAL_CANVAS_JS_TEMPLATE = r"""
(function(){try{
  const SEED = __KX_NATURAL_SEED__;   // int, replaced at build time
  // Mulberry32 — deterministic, cheap, good distribution
  const mkRng = function(s){
    return function(){
      s = (s + 0x6D2B79F5) | 0;
      let t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  };
  const rng = mkRng(SEED);
  // Precompute a small 16x16 noise tile (Perlin-lite) — tiled across
  // the canvas gives correlated regional noise, unlike per-pixel random.
  const TILE = 16;
  const tile = new Int8Array(TILE * TILE);
  for(let i = 0; i < tile.length; i++){
    tile[i] = ((rng() * 3) | 0) - 1;  // -1, 0, or +1
  }

  // Sobel-ish edge detector: perturb only pixels adjacent to a strong
  // brightness gradient. Skips flat regions (backgrounds) so the
  // fingerprint noise is limited to text/lines/edges where real GPU
  // anti-aliasing lives.
  const isNearEdge = function(data, w, i){
    const idx = i / 4 | 0;
    const x = idx % w;
    const y = idx / w | 0;
    if(x === 0 || y === 0 || x >= w - 1 || y >= (data.length / (4 * w)) - 1) return false;
    const at = function(dx, dy){
      const j = ((y + dy) * w + (x + dx)) * 4;
      return (data[j] + data[j + 1] + data[j + 2]) / 3;
    };
    const gx = Math.abs(at(1, 0) - at(-1, 0));
    const gy = Math.abs(at(0, 1) - at(0, -1));
    return (gx + gy) > 24;   // threshold — flat = untouched
  };

  const perturb = function(imageData){
    if(!imageData || !imageData.data) return;
    const d = imageData.data;
    const w = imageData.width;
    for(let i = 0; i < d.length; i += 4){
      if(!isNearEdge(d, w, i)) continue;
      const idx = (i / 4) | 0;
      const tx = (idx % w) % TILE;
      const ty = (((idx / w) | 0) % TILE);
      const jitter = tile[ty * TILE + tx];
      if(jitter === 0) continue;
      d[i]     = Math.max(0, Math.min(255, d[i]     + jitter));   // R
      d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + jitter));   // G
      d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + jitter));   // B
      // Alpha (i+3) UNTOUCHED — real GPUs preserve it
    }
  };

  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(){
    try{
      const ctx = this.getContext('2d');
      const w = this.width, h = this.height;
      if(ctx && w > 0 && h > 0 && w * h < 2000000){
        const data = ctx.getImageData(0, 0, w, h);
        perturb(data);
        ctx.putImageData(data, 0, 0);
      }
    }catch(_e){}
    return origToDataURL.apply(this, arguments);
  };

  const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function(){
    const d = origGetImageData.apply(this, arguments);
    try{ perturb(d); }catch(_e){}
    return d;
  };

  // measureText jitter — but DETERMINISTIC per text so measurements
  // stay consistent across calls (real fonts have stable metrics).
  const measureCache = new Map();
  const origMeasure = CanvasRenderingContext2D.prototype.measureText;
  CanvasRenderingContext2D.prototype.measureText = function(txt){
    const m = origMeasure.apply(this, arguments);
    try{
      const key = String(txt) + '|' + this.font;
      let jitter = measureCache.get(key);
      if(jitter === undefined){
        // Deterministic pseudo-jitter based on text hash + SEED
        let h = SEED;
        for(let i = 0; i < key.length; i++){
          h = ((h << 5) - h + key.charCodeAt(i)) | 0;
        }
        jitter = ((h % 100) / 5000) - 0.01;   // ±0.01 range
        measureCache.set(key, jitter);
      }
      const proxy = Object.create(Object.getPrototypeOf(m));
      Object.getOwnPropertyNames(m).forEach(function(k){
        try{ proxy[k] = m[k]; }catch(_e){}
      });
      ['width', 'actualBoundingBoxLeft', 'actualBoundingBoxRight'].forEach(function(k){
        if(typeof m[k] === 'number'){
          try{ Object.defineProperty(proxy, k, {value: m[k] + jitter, writable: false, configurable: true}); }catch(_e){}
        }
      });
      return proxy;
    }catch(_e){ return m; }
  };
}catch(_kxE){}})();
"""


def natural_canvas_js(seed: int) -> str:
    """Natural canvas fingerprint noise (Multilogin-style).

    Args:
      seed: Integer seed — for browser profiles, pass a stable hash
            of profile_id so the fingerprint is identical every
            session (real users have consistent hardware). For
            RUT visits, pass a per-visit seed for burnable variety.

    Returns:
      JavaScript string ready to inject via context.add_init_script.
      Overrides toDataURL / getImageData / measureText with
      edge-aware, tile-correlated, deterministic noise.
    """
    return _NATURAL_CANVAS_JS_TEMPLATE.replace("__KX_NATURAL_SEED__", str(int(seed) & 0x7FFFFFFF))


# ══════════════════════════════════════════════════════════════════════
# 19. WEBGL ↔ UA GPU ALIGNMENT (deterministic per profile)
# ══════════════════════════════════════════════════════════════════════
# Why this matters:
#   If UA says "Macintosh; Intel Mac OS X" but WebGL UNMASKED_RENDERER
#   reports "NVIDIA GeForce RTX 3080", every anti-fraud stack in 2026
#   flags it instantly (real Macs don't ship with NVIDIA GPUs since
#   2016). Same for iOS reporting Intel GPUs, Windows reporting Apple
#   Silicon, etc.
#
#   Krexion's existing _pick_ios_gpu_from_ua / _pick_android_gpu_from_ua
#   in real_user_traffic.py picks aligned GPUs — BUT uses random.choice
#   on desktop paths, so the SAME profile can flip between "Intel HD"
#   and "NVIDIA" across sessions. Real users NEVER change GPUs. This
#   module gives you a DETERMINISTIC per-profile picker.

# GPU pools carefully picked to match real 2024-2026 laptop/desktop fleets.
# Each entry is (vendor, renderer, MAX_TEXTURE_SIZE, MAX_VARYING_VECTORS,
# MAX_VERTEX_UNIFORM_VECTORS, ALIASED_LINE_WIDTH_RANGE_max).
# Values sourced from browserleaks.com/webgl real-fleet aggregates.
_GPU_POOL_WINDOWS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (Intel)",  "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (Intel)",  "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (Intel)",  "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (AMD)",    "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (AMD)",    "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
    ("Google Inc. (AMD)",    "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", 16384, 30, 4096, 8),
]
_GPU_POOL_MAC = [
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)", 16384, 32, 4096, 511),
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)", 16384, 32, 4096, 511),
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)", 16384, 32, 4096, 511),
    ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Pro, Unspecified Version)", 16384, 32, 4096, 511),
    ("Google Inc. (Intel)", "ANGLE (Intel, ANGLE Metal Renderer: Intel(R) Iris(TM) Plus Graphics 655, Unspecified Version)", 16384, 32, 4096, 511),
]
_GPU_POOL_LINUX = [
    ("Google Inc. (Intel)",  "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)", 16384, 30, 4096, 8),
    ("Google Inc. (Intel)",  "ANGLE (Intel, Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2), OpenGL 4.6)", 16384, 30, 4096, 8),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA Corporation, NVIDIA GeForce GTX 1650/PCIe/SSE2, OpenGL 4.6.0)", 16384, 30, 4096, 8),
    ("Google Inc. (AMD)",    "ANGLE (AMD, AMD Radeon Graphics (renoir, LLVM 15.0.7, DRM 3.49, 6.1.0-16-amd64), OpenGL 4.6)", 16384, 30, 4096, 8),
]
_GPU_POOL_ANDROID = [
    ("Google Inc. (Qualcomm)", "ANGLE (Qualcomm, Adreno (TM) 660, OpenGL ES 3.2)", 16384, 15, 256, 8),
    ("Google Inc. (Qualcomm)", "ANGLE (Qualcomm, Adreno (TM) 730, OpenGL ES 3.2)", 16384, 15, 256, 8),
    ("Google Inc. (Qualcomm)", "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)", 16384, 15, 256, 8),
    ("Google Inc. (ARM)",      "ANGLE (ARM, Mali-G68 MP5, OpenGL ES 3.2)", 8192, 15, 256, 8),
    ("Google Inc. (ARM)",      "ANGLE (ARM, Mali-G78 MP14, OpenGL ES 3.2)", 8192, 15, 256, 8),
    ("Google Inc. (ARM)",      "ANGLE (ARM, Mali-G710 MP7, OpenGL ES 3.2)", 8192, 15, 256, 8),
]
_GPU_POOL_IOS = [
    ("Apple Inc.", "Apple GPU", 16384, 32, 4096, 511),
    ("Apple Inc.", "Apple A15 GPU", 16384, 32, 4096, 511),
    ("Apple Inc.", "Apple A16 GPU", 16384, 32, 4096, 511),
    ("Apple Inc.", "Apple A17 Pro GPU", 16384, 32, 4096, 511),
]


def _stable_hash(s: str) -> int:
    """djb2 hash — small, deterministic, no crypto needed."""
    h = 5381
    for ch in (s or ""):
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return h


def align_webgl_to_ua_deterministic(ua: str, profile_id: str = "") -> Dict[str, Any]:
    """Return a WebGL descriptor that MATCHES the reported UA family
    and is DETERMINISTIC for the given (ua, profile_id).

    Same profile always gets the same GPU across sessions — mimics
    a real user who doesn't swap graphics cards. Different profiles
    with the same UA get different GPUs from within the correct pool.

    Args:
      ua: The User-Agent string that will be reported to the target.
      profile_id: Stable identifier (browser profile UUID, or empty
                  for a random pick when called from RUT ad-hoc).

    Returns:
      Dict with keys: vendor, renderer, max_texture_size,
      max_varying_vectors, max_vertex_uniform_vectors,
      max_line_width, gpu_family. Ready to merge into the fp dict
      consumed by _build_stealth_script.
    """
    _ua = (ua or "").lower()
    if "iphone" in _ua or "ipad" in _ua or ("ios" in _ua and "like mac" in _ua):
        pool = _GPU_POOL_IOS
        family = "ios"
    elif "android" in _ua:
        pool = _GPU_POOL_ANDROID
        family = "android"
    elif "mac os" in _ua or "macintosh" in _ua:
        pool = _GPU_POOL_MAC
        family = "mac"
    elif "linux" in _ua and "android" not in _ua:
        pool = _GPU_POOL_LINUX
        family = "linux"
    else:
        pool = _GPU_POOL_WINDOWS
        family = "windows"

    idx = _stable_hash(str(profile_id) + "|" + str(ua)) % len(pool) if profile_id else 0
    vendor, renderer, max_tex, max_var, max_uni, max_line = pool[idx]
    return {
        "vendor": vendor,
        "renderer": renderer,
        "max_texture_size": max_tex,
        "max_varying_vectors": max_var,
        "max_vertex_uniform_vectors": max_uni,
        "max_line_width": max_line,
        "gpu_family": family,
    }


# JS that enforces the ALIGNED WebGL parameters. Injected AFTER the
# baseline UNMASKED_VENDOR/RENDERER override in _build_stealth_script.
_WEBGL_ALIGN_JS_TEMPLATE = r"""
(function(){try{
  const CFG = __KX_WEBGL_ALIGN_CFG__;
  const CONST_MAP = {
    3379: CFG.max_texture_size,           // GL_MAX_TEXTURE_SIZE
    35660: CFG.max_texture_size,          // GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS scaled — some fingerprinters read this
    36347: CFG.max_vertex_uniform_vectors,// GL_MAX_VERTEX_UNIFORM_VECTORS
    36348: CFG.max_varying_vectors,       // GL_MAX_VARYING_VECTORS
    34076: CFG.max_texture_size,          // GL_MAX_CUBE_MAP_TEXTURE_SIZE
    3386:  [CFG.max_texture_size, CFG.max_texture_size],  // MAX_VIEWPORT_DIMS
    33902: [1, CFG.max_line_width],       // ALIASED_LINE_WIDTH_RANGE
    33901: [1, 1024],                     // ALIASED_POINT_SIZE_RANGE
  };
  const patch = function(proto){
    if(!proto || !proto.getParameter) return;
    const orig = proto.getParameter;
    proto.getParameter = function(p){
      // UNMASKED_VENDOR (37445) & UNMASKED_RENDERER (37446) are
      // handled by the baseline stealth script — do not touch here.
      if(p in CONST_MAP){
        const v = CONST_MAP[p];
        if(Array.isArray(v)){
          try{ return new Int32Array(v); }catch(_e){ return v; }
        }
        return v;
      }
      return orig.call(this, p);
    };
  };
  patch(typeof WebGLRenderingContext !== 'undefined' && WebGLRenderingContext.prototype);
  patch(typeof WebGL2RenderingContext !== 'undefined' && WebGL2RenderingContext.prototype);
}catch(_kxE){}})();
"""


def webgl_align_js(cfg: Dict[str, Any]) -> str:
    """Emit the JS that enforces max_texture_size / max_varying_vectors
    / max_line_width etc. from the descriptor returned by
    `align_webgl_to_ua_deterministic()`. Passing `cfg` verbatim from
    that helper is the intended usage.

    Safe against missing keys — falls back to conservative defaults
    that no fingerprinter will flag as suspicious.
    """
    import json as _json
    safe_cfg = {
        "max_texture_size": int(cfg.get("max_texture_size", 16384)),
        "max_varying_vectors": int(cfg.get("max_varying_vectors", 30)),
        "max_vertex_uniform_vectors": int(cfg.get("max_vertex_uniform_vectors", 4096)),
        "max_line_width": int(cfg.get("max_line_width", 8)),
    }
    return _WEBGL_ALIGN_JS_TEMPLATE.replace(
        "__KX_WEBGL_ALIGN_CFG__", _json.dumps(safe_cfg)
    )


# ══════════════════════════════════════════════════════════════════════
# 20. HIGH-LEVEL ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════
def build_v230_stealth_bundle(*, safari_mode: bool = False) -> str:
    """Return the concatenated JS blob for ALL 11 JS-based features.
    Caller passes this into a single `context.add_init_script(...)`
    call — one round-trip instead of 11.

    safari_mode: skip Chromium-only surfaces (chrome.runtime, PDF plugins,
    Privacy Sandbox Topics) so WebKit/iOS profiles stay Safari-shaped.
    """
    parts = [
        cdp_stealth_js(safari_mode=safari_mode),
        bot_vendor_stealth_js(),
        mobile_signals_js(),
        webgl_extensions_js(),
        speech_voices_js(),
        battery_fluctuation_js(),
    ]
    if not safari_mode:
        parts.extend([
            privacy_sandbox_js(),
            extension_emulation_js(),
            ad_blocker_realism_js(),
            first_party_sets_js(),
        ])
    parts.append(post_conversion_js())  # activates only on thank-you pages
    return "\n".join(parts)


async def apply_v230_stealth(
    context: Any,
    ua: str = "",
    viewport: Optional[Dict[str, int]] = None,
    platform: str = "",
    sec_fetch_kind: str = "typed_url",
    safari_mode: bool = False,
) -> Dict[str, Any]:
    """One-call orchestrator that wires every v2.3.0 JS feature into a
    Playwright browser context AND returns the header dict the caller
    should merge into extra_http_headers.  Never raises — every
    feature is wrapped in try/except so a broken one can't cascade."""
    report: Dict[str, Any] = {"js_ok": False, "headers": {}, "http2_settings": {}}
    try:
        # Set extra HTTP headers (Sec-Fetch-* + Full Client Hints)
        headers = {}
        headers.update(sec_fetch_headers(sec_fetch_kind or "typed_url"))
        # Safari/WebKit must NOT emit Chromium Sec-CH-UA brands
        if not safari_mode:
            headers.update(full_client_hints(ua, viewport))
            report["http2_settings"] = http2_settings_for_ua(ua)
        report["headers"] = headers
    except Exception as e:
        logger.debug(f"v230 header build failed: {e}")

    try:
        js = build_v230_stealth_bundle(safari_mode=bool(safari_mode))
        await context.add_init_script(js)
        report["js_ok"] = True
    except Exception as e:
        logger.debug(f"v230 JS bundle inject failed: {e}")

    return report
