"""
Krexion — Central Anti-Detect Engine
=====================================

THE single source of truth for stealth browser launching across the
entire Krexion platform. All features that drive a Playwright browser
(Real User Traffic, Form Filler, Visual Recorder live runs, RPA Studio,
Profile Builder smoke-tests, …) MUST go through this module so customers
get identical anti-detect protection no matter which feature they use.

What it gives you
-----------------
1. `build_fingerprint(ua=None)` — per-visit canvas/audio/WebGL/font seed
   + per-OS realistic platform/vendor/hardware values
2. `build_geo(country=None)` — proxy-aware geolocation spoof data
   (lat, lon, accuracy, timezone, locale)
3. `build_client_hint_headers(fp, ua)` — Sec-CH-UA-* HTTP headers that
   match the chosen UA + fingerprint
4. `build_stealth_script(fp, geo)` — the 800-line JS that gets injected
   into every browser context before any page JS runs. 35+ patches
   defeating webdriver, canvas/audio/font fingerprint, WebGL spoof,
   mobile sensors, CDP detection, TrustedForm/Jornaya counter-attack,
   geolocation, Worker inheritance, touch events, etc.
5. `launch_stealth_session()` — ONE-liner that returns a ready-to-use
   (browser, context, page) tuple with everything applied: --headless=new
   flag, proxy, UA, viewport, geolocation, locale, timezone, stealth
   init script, sec-ch-ua headers, WebRTC IP leak block, human warmup.

Where the implementation lives
------------------------------
All the heavy lifting (the 800-line stealth JS, fingerprint generation,
client hints) was originally written inside `real_user_traffic.py`. To
keep customer-facing behavior IDENTICAL, this module imports those
private helpers from RUT rather than duplicating them. That way:

  • RUT continues to work bit-identically (no regression)
  • Any future tweak to stealth JS automatically benefits ALL features
  • Form Filler, RPA Studio, Visual Recorder all share the same
    35+ anti-detect patches

Public API
----------
    launch_stealth_session(pw, *, ua=None, proxy=None, headless=True,
                            country=None, viewport=None, locale=None)
        -> (browser, context, page)

    apply_stealth_to_context(context, fp=None, geo=None, ua=None)
        -> None  (init scripts + extra headers attached)

    human_warmup(page, fp=None)
        -> None  (mouse jitter, scroll, dwell)

    build_fingerprint(ua=None) -> dict
    build_geo(country=None) -> dict
    build_client_hint_headers(fp, ua) -> dict
    build_stealth_script(fp, geo) -> str
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("anti_detect_engine")


# ─────────────────────────────────────────────────────────────────────
# We import the canonical implementations from real_user_traffic LAZILY
# (inside each function) to avoid circular-import deadlock:
#   anti_detect_engine -> real_user_traffic -> form_filler -> anti_detect_engine
# Module-level imports would break startup ordering.
# ─────────────────────────────────────────────────────────────────────
_rut_stealth_script = None
_rut_client_hints = None
_rut_fp_from_ua = None
_rut_launch = None
_rut_warmup = None
_RUT_BASE_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
_RUT_AVAILABLE = None  # tri-state: None=not-yet-tried, True/False=resolved


def _resolve_rut():
    """Lazy import — called on first use, caches result."""
    global _RUT_AVAILABLE, _rut_stealth_script, _rut_client_hints
    global _rut_fp_from_ua, _rut_launch, _rut_warmup, _RUT_BASE_ARGS
    if _RUT_AVAILABLE is not None:
        return _RUT_AVAILABLE
    try:
        from real_user_traffic import (
            _build_stealth_script as a,
            _build_client_hint_headers as b,
            _fingerprint_from_ua as c,
            _launch_anti_detect_browser as d,
            _human_warmup as e,
            _BROWSER_LAUNCH_ARGS_BASE as f,
        )
        _rut_stealth_script = a
        _rut_client_hints = b
        _rut_fp_from_ua = c
        _rut_launch = d
        _rut_warmup = e
        _RUT_BASE_ARGS = list(f)
        _RUT_AVAILABLE = True
        logger.info("anti_detect_engine: RUT helpers resolved — full stealth enabled")
    except Exception as ex:
        _RUT_AVAILABLE = False
        logger.warning(
            f"anti_detect_engine: RUT helpers unavailable ({ex}) — minimal stealth"
        )
    return _RUT_AVAILABLE


# ─────────────────────────────────────────────────────────────────────
# Pool of realistic up-to-date user agents (used when caller passes
# `ua=None`). Mix of desktop + mobile to keep traffic distribution
# natural across cohorts.
# ─────────────────────────────────────────────────────────────────────
_DEFAULT_UA_POOL = [
    # Desktop Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Desktop Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Mobile Chrome (Android)
    "Mozilla/5.0 (Linux; Android 14; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    # Mobile Safari (iOS)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


def _pick_default_ua() -> str:
    return random.choice(_DEFAULT_UA_POOL)


# ─────────────────────────────────────────────────────────────────────
# Public API — fingerprint + geo builders
# ─────────────────────────────────────────────────────────────────────
def build_fingerprint(ua: Optional[str] = None) -> Dict[str, Any]:
    """Build a fully-formed fingerprint dict for one visit.

    The dict feeds both stealth-JS and Sec-CH-UA-* HTTP headers, so all
    surfaces stay in sync (no UA-vs-platform mismatch which detectors
    love to flag). The returned dict ALWAYS contains a `ua` key so
    downstream code can reference the chosen user-agent string.
    """
    ua = ua or _pick_default_ua()
    if _resolve_rut() and _rut_fp_from_ua:
        try:
            fp = _rut_fp_from_ua(ua)
            # RUT's _fingerprint_from_ua doesn't carry the UA string —
            # add it so callers don't need to thread it separately.
            fp["ua"] = ua
            return fp
        except Exception as e:
            logger.warning(f"RUT fingerprint failed ({e}) — fallback")
    # Minimal fallback fingerprint
    return {
        "ua": ua,
        "platform": "Win32" if "Windows" in ua else ("MacIntel" if "Mac" in ua else "Linux x86_64"),
        "languages": ["en-US", "en"],
        "hardware_concurrency": random.choice([4, 8, 12, 16]),
        "device_memory": random.choice([4, 8, 16]),
        "max_touch_points": 0 if not ("Mobile" in ua or "iPhone" in ua or "iPad" in ua or "Android" in ua) else 5,
        "screen_width": 1920 if not ("Mobile" in ua or "iPhone" in ua or "Android" in ua) else 390,
        "screen_height": 1080 if not ("Mobile" in ua or "iPhone" in ua or "Android" in ua) else 844,
        "color_depth": 24,
        "vendor": "Google Inc.",
        "audio_seed": random.random() * 1e-7,
        "canvas_seed": random.random(),
        "is_mobile": "Mobile" in ua or "iPhone" in ua or "iPad" in ua or "Android" in ua,
        "viewport": {"width": 1366, "height": 768},
        "device_scale_factor": 1,
        "has_touch": "Mobile" in ua or "iPhone" in ua or "iPad" in ua or "Android" in ua,
    }


# Approximate centroids for common affiliate-target countries
_COUNTRY_GEO = {
    "US": {"lat": 38.0, "lon": -97.0, "timezone": "America/Chicago", "locale": "en-US"},
    "GB": {"lat": 54.0, "lon": -2.0, "timezone": "Europe/London", "locale": "en-GB"},
    "CA": {"lat": 56.0, "lon": -106.0, "timezone": "America/Toronto", "locale": "en-CA"},
    "AU": {"lat": -25.0, "lon": 133.0, "timezone": "Australia/Sydney", "locale": "en-AU"},
    "DE": {"lat": 51.0, "lon": 10.5, "timezone": "Europe/Berlin", "locale": "de-DE"},
    "FR": {"lat": 46.0, "lon": 2.0, "timezone": "Europe/Paris", "locale": "fr-FR"},
    "IN": {"lat": 22.0, "lon": 79.0, "timezone": "Asia/Kolkata", "locale": "en-IN"},
    "BR": {"lat": -14.0, "lon": -52.0, "timezone": "America/Sao_Paulo", "locale": "pt-BR"},
}


def build_geo(country: Optional[str] = None) -> Dict[str, Any]:
    """Build a geolocation spoof dict compatible with RUT's stealth script.

    Returns a dict with keys matching what `_build_stealth_script`
    expects:  exit_ip, country, country_name, city, region,
              lat, lon, timezone, accept_language, locale, is_vpn, ok
    """
    country = (country or "US").upper()
    base = _COUNTRY_GEO.get(country, _COUNTRY_GEO["US"])
    # Locale → accept_language string (e.g. "en-US" -> "en-US,en;q=0.9")
    lang_map = {
        "US": "en-US,en;q=0.9",
        "GB": "en-GB,en;q=0.9",
        "CA": "en-CA,en;q=0.9,fr-CA;q=0.8",
        "AU": "en-AU,en;q=0.9",
        "DE": "de-DE,de;q=0.9,en;q=0.8",
        "FR": "fr-FR,fr;q=0.9,en;q=0.8",
        "IN": "en-IN,en;q=0.9,hi;q=0.8",
        "BR": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    return {
        # RUT-compatible keys
        "exit_ip": None,
        "country": country,
        "country_name": country,
        "city": "",
        "region": "",
        "region_name": "",
        "lat": base["lat"] + random.uniform(-2.0, 2.0),
        "lon": base["lon"] + random.uniform(-2.0, 2.0),
        "timezone": base["timezone"],
        "accept_language": lang_map.get(country, "en-US,en;q=0.9"),
        "locale": base["locale"],
        "is_vpn": False,
        "ok": True,
        # Convenience aliases (used by some callers)
        "latitude": base["lat"] + random.uniform(-2.0, 2.0),
        "longitude": base["lon"] + random.uniform(-2.0, 2.0),
        "accuracy": random.uniform(20.0, 120.0),
    }


def build_client_hint_headers(fp: Dict[str, Any], ua: str) -> Dict[str, str]:
    """Sec-CH-UA-* headers that match the chosen UA + fingerprint."""
    if _resolve_rut() and _rut_client_hints:
        try:
            return _rut_client_hints(fp, ua)
        except Exception as e:
            logger.warning(f"RUT client hints failed ({e}) — fallback")
    # Minimal fallback
    return {
        "Accept-Language": ",".join(fp.get("languages", ["en-US"])),
    }


def build_stealth_script(fp: Dict[str, Any], geo: Dict[str, Any]) -> str:
    """The 800-line stealth JS that runs before any page JS.

    Falls back to a minimal `navigator.webdriver=false` stub if the RUT
    implementation isn't available.
    """
    if _resolve_rut() and _rut_stealth_script:
        try:
            return _rut_stealth_script(fp, geo)
        except Exception as e:
            logger.warning(f"RUT stealth script build failed ({e}) — fallback")
    # Minimal fallback (DOES NOT defeat modern detectors)
    return """
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
    window.chrome = { runtime: {} };
    """


# ─────────────────────────────────────────────────────────────────────
# Public API — high-level launch helper
# ─────────────────────────────────────────────────────────────────────
async def launch_stealth_session(
    pw,
    *,
    ua: Optional[str] = None,
    proxy: Optional[Dict[str, str]] = None,
    headless: bool = True,
    country: Optional[str] = None,
    viewport: Optional[Dict[str, int]] = None,
    locale: Optional[str] = None,
    extra_args: Optional[list] = None,
) -> Tuple[Any, Any, Any]:
    """ONE-call launcher that returns a stealth-armed (browser, context, page).

    `pw` is a started `playwright` instance:
        async with async_playwright() as pw:
            browser, context, page = await launch_stealth_session(pw, ...)

    The returned browser+context+page have these defenses ACTIVE:
      • --headless=new (if full chromium installed)
      • Realistic proxy + UA + viewport + geolocation + locale + timezone
      • 800-line stealth init script (webdriver, canvas/audio/WebGL/font,
        WebRTC IP leak, CDP detection, Worker/iframe inheritance, mobile
        sensors, TrustedForm/Jornaya counter, touch events, …)
      • Sec-CH-UA-* HTTP headers matched to UA
      • Permissions overrides (notifications, geolocation)

    Caller is responsible for closing the browser when done.
    """
    fp = build_fingerprint(ua=ua)
    actual_ua = fp.get("ua") or ua or _pick_default_ua()
    geo = build_geo(country=country)
    if locale:
        geo["locale"] = locale
    vp = viewport or ({"width": 390, "height": 844} if fp.get("is_mobile") else {"width": 1366, "height": 768})

    # 1. Launch browser — use the RUT-grade launcher if available
    #    (handles --headless=new + fallback to headless-shell).
    if _resolve_rut() and _rut_launch:
        try:
            browser = await _rut_launch(pw)
        except Exception as e:
            logger.warning(f"RUT launcher failed ({e}) — using minimal launch")
            browser = await pw.chromium.launch(
                headless=headless,
                args=list(_RUT_BASE_ARGS) + (extra_args or []),
            )
    else:
        browser = await pw.chromium.launch(
            headless=headless,
            args=list(_RUT_BASE_ARGS) + (extra_args or []),
        )

    # 2. Build context with realistic environment + proxy
    ctx_kwargs: Dict[str, Any] = {
        "user_agent": actual_ua,
        "viewport": vp,
        "locale": geo["locale"],
        "timezone_id": geo["timezone"],
        "geolocation": {
            "latitude": geo.get("lat") or geo.get("latitude"),
            "longitude": geo.get("lon") or geo.get("longitude"),
            "accuracy": geo.get("accuracy", 50.0),
        },
        "permissions": ["geolocation"],
        "is_mobile": bool(fp.get("is_mobile")),
        "has_touch": bool(fp.get("is_mobile")) or fp.get("max_touch_points", 0) > 0,
        "color_scheme": "light",
        "device_scale_factor": 3 if fp.get("is_mobile") else 1,
        "extra_http_headers": {"Accept-Language": geo.get("accept_language", "en-US,en;q=0.9")},
    }
    if proxy:
        ctx_kwargs["proxy"] = proxy

    try:
        context = await browser.new_context(**ctx_kwargs)
    except Exception as e:
        # Some Playwright versions don't accept all keys — retry minimal
        logger.warning(f"new_context with full args failed ({e}) — retrying minimal")
        minimal = {"user_agent": actual_ua, "viewport": vp}
        if proxy:
            minimal["proxy"] = proxy
        context = await browser.new_context(**minimal)

    # 3. Attach stealth + v2.3.0 extras + client hints (RUT hints win)
    try:
        await context.add_init_script(build_stealth_script(fp, geo))
    except Exception as e:
        logger.warning(f"add_init_script failed ({e})")

    _ch_hdrs = build_client_hint_headers(fp, actual_ua)
    _merged_hdrs: Dict[str, str] = {
        "Accept-Language": geo.get("accept_language", "en-US,en;q=0.9"),
    }
    _merged_hdrs.update(_ch_hdrs)
    try:
        from anti_detect_v230 import apply_v230_stealth as _v230_apply
        _v230_r = await _v230_apply(
            context, ua=actual_ua, viewport=vp, platform=fp.get("os") or "",
        )
        _v230_h = dict(_v230_r.get("headers") or {})
        _v230_h.update(_merged_hdrs)
        _merged_hdrs = _v230_h
    except Exception as _v230_err:
        logger.debug(f"v230 stealth on launch_stealth_session skipped: {_v230_err}")

    try:
        await context.set_extra_http_headers(_merged_hdrs)
    except Exception as e:
        logger.warning(f"set_extra_http_headers failed ({e})")

    try:
        from referrer_pro import make_sec_ch_ua_strip_route_handler
        await context.route("**/*", make_sec_ch_ua_strip_route_handler())
    except Exception as e:
        logger.debug(f"sec-ch-ua route strip skipped: {e}")

    # 4. Open the first page
    page = await context.new_page()
    return browser, context, page


async def apply_stealth_to_context(context, fp: Optional[Dict[str, Any]] = None,
                                    geo: Optional[Dict[str, Any]] = None,
                                    ua: Optional[str] = None) -> None:
    """Attach stealth init-script + sec-ch-ua headers to an EXISTING
    browser context. Useful for code paths that don't create the
    context themselves (e.g., Visual Recorder which uses Playwright's
    persistent profiles)."""
    fp = fp or build_fingerprint(ua=ua)
    geo = geo or build_geo()
    actual_ua = fp.get("ua") or ua or _pick_default_ua()
    try:
        await context.add_init_script(build_stealth_script(fp, geo))
        try:
            from anti_detect_v230 import natural_canvas_js as _natural_canvas, webgl_align_js as _webgl_align_js
            if fp.get("webgl_vendor") and fp.get("webgl_renderer"):
                _seed = int(fp.get("canvas_seed") or random.randint(1, 2**30))
                await context.add_init_script(_natural_canvas(_seed))
                await context.add_init_script(_webgl_align_js({
                    "vendor": fp["webgl_vendor"],
                    "renderer": fp["webgl_renderer"],
                }))
        except Exception:
            pass
        await context.set_extra_http_headers(build_client_hint_headers(fp, actual_ua))
    except Exception as e:
        logger.warning(f"apply_stealth_to_context failed: {e}")


async def human_warmup(page, fp: Optional[Dict[str, Any]] = None) -> None:
    """Realistic 1-3s mouse jitter + scroll dance.

    Defeats behavioral checks (Anura "zero mouse movement", FingerprintJS
    "no scroll deltas") that flag traffic with too-perfect interaction
    patterns.
    """
    if _resolve_rut() and _rut_warmup:
        try:
            await _rut_warmup(page, fp or build_fingerprint())
            return
        except Exception as e:
            logger.warning(f"RUT warmup failed ({e}) — minimal warmup")
    # Minimal fallback: 1-2s wait + a few mouse moves + small scroll
    try:
        await asyncio.sleep(random.uniform(0.8, 2.0))
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(random.randint(100, 1200), random.randint(100, 600),
                                   steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.3))
        try:
            await page.evaluate(f"window.scrollBy(0, {random.randint(120, 400)})")
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.4, 1.2))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# Pacing / cohort defense
# ─────────────────────────────────────────────────────────────────────
def compute_pacing_delay(conversions_per_hour: int = 10) -> float:
    """Returns seconds to wait before the next visit.

    Uses a Poisson-ish jitter so the inter-arrival times don't look
    perfectly regular (which detectors flag as machine traffic).
    """
    if conversions_per_hour <= 0:
        return 0.0
    base = 3600.0 / conversions_per_hour
    # Gamma-ish jitter: most values near base, occasional bursts + lulls
    jitter = random.lognormvariate(0, 0.3)
    return max(base * 0.3, base * jitter)


__all__ = [
    "build_fingerprint",
    "build_geo",
    "build_client_hint_headers",
    "build_stealth_script",
    "launch_stealth_session",
    "apply_stealth_to_context",
    "human_warmup",
    "compute_pacing_delay",
]
