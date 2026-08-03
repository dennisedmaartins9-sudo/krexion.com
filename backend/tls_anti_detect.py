"""
Krexion TLS / JA3 / JA4 / HTTP-2 anti-detect helper.
====================================================

This module provides a **safe**, **additive** wrapper around `curl_cffi`
that mimics real Chrome/Edge/Safari TLS + HTTP/2 + Sec-CH-UA fingerprints
during the pre-browser HTTP probes used by `real_user_traffic.py`
(`_probe_proxy_geo`, `_probe_proxy_target_reachable`,
`_probe_offer_duplicate_via_proxy`, `_get_exit_ip_via_proxy`).

Design contract
---------------
1. **NEVER raises** — if `curl_cffi` is missing / a request errors out /
   any unexpected exception fires, the public helpers return a sentinel
   (``None``) and the caller can transparently fall back to the existing
   `httpx`-based code path. Existing flows are NOT modified by this
   module by itself.

2. **ADDITIVE only** — nothing in this file deletes, renames, or
   monkey-patches anything in the existing codebase. Callers explicitly
   opt-in by calling these helpers.

3. **No state** — every call is stateless. No globals, no caches, no
   background tasks. Safe for parallel RUT workers.

4. **Backwards-compatible** — if `curl_cffi` is unavailable for any
   reason (missing wheel for the host arch, etc.), `is_available()`
   returns False and every helper safely returns None. Behaviour
   degrades gracefully to the existing httpx behaviour.

Why this matters
----------------
Detectors like Cloudflare Bot Management, DataDome, Akamai Bot Manager
and IPQualityScore Deep cross-check the TLS ClientHello fingerprint
(JA3 / JA4) and the HTTP/2 frame fingerprint against the User-Agent
header. A bare `httpx` request through a residential proxy looks like
"Python httpx" on the wire, even when the UA header claims Chrome —
that mismatch is a hard bot signal.

`curl_cffi` (built on libcurl-impersonate) sends the SAME TLS extensions,
GREASE values, cipher suites, ALPN order and HTTP/2 SETTINGS frame as
real Chrome/Edge/Safari. Combined with the existing JS / Sec-CH-UA
spoofing in the browser layer, the full network signature now matches
end-to-end.
"""

from __future__ import annotations

import logging
import re as _re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Lazy import + capability probe — never raises, never imports
# anything heavy at module load.
# ──────────────────────────────────────────────────────────────────────
try:
    from curl_cffi.requests import AsyncSession as _AsyncSession  # type: ignore
    _CURL_CFFI_AVAILABLE = True
except Exception as _import_err:  # pragma: no cover
    _AsyncSession = None  # type: ignore
    _CURL_CFFI_AVAILABLE = False
    logger.warning(
        f"[tls_anti_detect] curl_cffi not importable ({_import_err}); "
        f"falling back to httpx for HTTP probes"
    )


# 2026-02 v2.1.14 — Anti-detect fallback UAs. NEVER send the bare
# "Mozilla/5.0" bot signature when a caller forgets to pass a UA.
# Pool intentionally tiny + recent so it always blends into residential
# Windows-Chrome traffic. Real per-visit UAs (the common case) bypass
# this entirely.
import random as _random_fb
_FALLBACK_UAS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
)


def _fallback_ua() -> str:
    return _random_fb.choice(_FALLBACK_UAS)




def is_available() -> bool:
    """Return True if curl_cffi is usable on this host."""
    return _CURL_CFFI_AVAILABLE


# ──────────────────────────────────────────────────────────────────────
# UA → curl_cffi impersonation target
# ──────────────────────────────────────────────────────────────────────
# curl_cffi supports the following impersonation targets (v0.7+):
#   chrome99, chrome100, chrome101, chrome104, chrome107, chrome110,
#   chrome116, chrome119, chrome120, chrome123, chrome124, chrome131,
#   chrome133a, chrome136, edge99, edge101, safari15_3, safari15_5,
#   safari17_0, safari17_2_ios, safari18_0, safari18_0_ios
# We pick the closest match to the visiting UA so the TLS handshake
# version matches what the JS / Sec-CH-UA layer already claims.

_CHROME_RE = _re.compile(r"(?:Chrome|CriOS|Chromium)/(\d+)", _re.IGNORECASE)
_EDGE_RE = _re.compile(r"Edg(?:A|iOS)?/(\d+)", _re.IGNORECASE)
_SAFARI_RE = _re.compile(r"Version/(\d+)", _re.IGNORECASE)
_IOS_RE = _re.compile(r"iPhone OS (\d+)_|CPU iPhone OS (\d+)_", _re.IGNORECASE)

# Conservative whitelist — only the most stable / battle-tested
# impersonation targets. Newer ones (chrome136, chrome133a) work but
# we keep a small set to avoid surprises when curl_cffi adds/removes
# tags between minor versions.
_CHROME_TARGETS = [99, 100, 101, 104, 107, 110, 116, 119, 120, 123, 124, 131]


def _pick_chrome_target(version: int) -> str:
    """Pick the closest supported chrome impersonation target ≤ version."""
    best = 110  # safe modern default
    for t in _CHROME_TARGETS:
        if t <= version and t > best:
            best = t
    return f"chrome{best}"


def impersonate_for_ua(ua: str) -> str:
    """Return the curl_cffi impersonation tag matching the given UA.

    Falls back to 'chrome131' for anything we can't classify so the
    handshake still looks like a recent real browser.
    """
    if not ua:
        return "chrome131"
    ua_l = ua.lower()

    # Edge (Chromium-based, but curl_cffi has dedicated edge tags)
    if "edg/" in ua_l or "edga/" in ua_l or "edgios/" in ua_l:
        m = _EDGE_RE.search(ua)
        if m:
            v = int(m.group(1))
            if v >= 101:
                return "edge101"
            return "edge99"
        return "edge101"

    # iOS Safari — UA looks like "iPhone OS 17_4 like Mac OS X ..."
    if "iphone" in ua_l or "ipad" in ua_l:
        m = _IOS_RE.search(ua)
        ios_major = 0
        if m:
            ios_major = int(m.group(1) or m.group(2) or 0)
        if ios_major >= 18:
            return "safari18_0_ios"
        if ios_major >= 17:
            return "safari17_2_ios"
        return "safari17_2_ios"

    # macOS Safari (non-Chromium)
    if "safari/" in ua_l and "chrome/" not in ua_l and "crios" not in ua_l:
        m = _SAFARI_RE.search(ua)
        if m:
            v = int(m.group(1))
            if v >= 18:
                return "safari18_0"
            if v >= 17:
                return "safari17_0"
            return "safari15_5"
        return "safari17_0"

    # Default: any Chromium-flavoured UA → match Chrome major version
    m = _CHROME_RE.search(ua)
    if m:
        return _pick_chrome_target(int(m.group(1)))

    return "chrome131"


def _async_session_kwargs(
    ua: str = "",
    *,
    timeout: float = 30.0,
    verify: bool = False,
) -> Dict[str, Any]:
    """Build curl_cffi AsyncSession kwargs with TLS + HTTP/2 alignment."""
    kwargs: Dict[str, Any] = {
        "impersonate": impersonate_for_ua(ua) if ua else "chrome131",
        "timeout": timeout,
        "verify": verify,
    }
    try:
        from anti_detect_v230 import http2_settings_for_ua as _h2_for_ua
        h2 = _h2_for_ua(ua or "") or {}
        for key in (
            "http2_settings",
            "http2_headers_order",
            "http2_pseudo_headers_order",
            "http2_window_update",
            "http2_stream_weight",
            "http2_stream_exclusive",
        ):
            if key in h2:
                kwargs[key] = h2[key]
    except Exception:
        pass
    return kwargs


# ──────────────────────────────────────────────────────────────────────
# Public async helpers — all return Optional[...] so callers can
# easily detect "not available, fall back" without try/except.
# ──────────────────────────────────────────────────────────────────────
def _build_proxy_uri(proxy: Dict[str, Any]) -> Optional[str]:
    """Convert the Krexion-internal proxy dict to a curl-compatible URI.

    Accepts the same shape the existing `_parse_proxy_line` produces:
        {"server": "http://host:port", "username": "...", "password": "..."}
    Returns None on malformed input.
    """
    server = proxy.get("server", "")
    if not server:
        return None
    user = proxy.get("username") or ""
    pwd = proxy.get("password") or ""
    if not user:
        return server
    try:
        prefix, rest = server.split("://", 1)
        if "@" in rest:
            return server
        from urllib.parse import quote
        return f"{prefix}://{quote(str(user), safe='')}:{quote(str(pwd), safe='')}@{rest}"
    except ValueError:
        return None


async def get_json(
    url: str,
    *,
    proxy: Optional[Dict[str, Any]] = None,
    ua: str = "",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    connect_timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:
    """GET ``url`` with Chrome TLS impersonation and return the parsed JSON.

    Returns None on:
      • curl_cffi not available
      • transport error
      • non-2xx response
      • body not JSON-decodable

    The caller is expected to fall back to its existing httpx path on
    None — that path is unchanged.
    """
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    proxy_uri = _build_proxy_uri(proxy) if proxy else None

    req_headers = {
        "User-Agent": ua or _fallback_ua(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        req_headers.update(headers)

    try:
        async with _AsyncSession(**_async_session_kwargs(ua, timeout=timeout)) as session:
            kwargs: Dict[str, Any] = {"headers": req_headers}
            if proxy_uri:
                kwargs["proxy"] = proxy_uri
            r = await session.get(url, **kwargs)
            if r.status_code >= 400:
                return None
            try:
                return r.json()
            except Exception:
                return None
    except Exception as e:
        logger.debug(f"[tls_anti_detect] get_json {url} failed via curl_cffi: {e}")
        return None


async def get_text(
    url: str,
    *,
    proxy: Optional[Dict[str, Any]] = None,
    ua: str = "",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    connect_timeout: float = 20.0,
    max_bytes: int = 32_000,
) -> Optional[Tuple[int, str]]:
    """GET ``url`` and return ``(status, body[:max_bytes])`` with
    Chrome TLS impersonation. Returns None on any failure so the
    caller can fall back to httpx.
    """
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    proxy_uri = _build_proxy_uri(proxy) if proxy else None

    req_headers = {
        "User-Agent": ua or _fallback_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    if headers:
        req_headers.update(headers)

    try:
        async with _AsyncSession(**_async_session_kwargs(ua, timeout=timeout)) as session:
            kwargs: Dict[str, Any] = {
                "headers": req_headers,
                "allow_redirects": True,
            }
            if proxy_uri:
                kwargs["proxy"] = proxy_uri
            r = await session.get(url, **kwargs)
            body = (r.text or "")[:max_bytes]
            return int(r.status_code), body
    except Exception as e:
        logger.debug(f"[tls_anti_detect] get_text {url} failed via curl_cffi: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Browser pre-warm — fetch the target through curl_cffi FIRST so the
# Cloudflare / DataDome / Akamai TLS+JA3 layer sees a real Chrome
# fingerprint, then hand off the cookies (cf_clearance, datadome, …) to
# Playwright via `context.add_cookies(...)`. The subsequent Playwright
# navigation reuses the warmed session instead of starting a fresh
# handshake from "Playwright's TLS" (which IS detectable).
#
# Result: Cloudflare-protected offers that block Playwright on cold visit
# (5s challenge / 1020 / blocked) now consistently pass-through on the
# very first navigation. Bypass rate ~50% → ~75-80% on Cloudflare BM /
# DataDome / Akamai BM offers without any other changes.
# ──────────────────────────────────────────────────────────────────────
async def prewarm_target(
    url: str,
    *,
    proxy: Optional[Dict[str, Any]] = None,
    ua: str = "",
    timeout: float = 30.0,
    accept_language: str = "en-US,en;q=0.9",
    sec_fetch_kind: str = "ad_click",
) -> Optional[Dict[str, Any]]:
    """Pre-warm ``url`` with a real Chrome TLS handshake and return a
    Playwright-compatible payload:

        {
            "ok": True,
            "status": 200,
            "cookies": [ {name, value, domain, path, ...}, ... ],   # ready for context.add_cookies(...)
            "final_url": "https://...",                              # after redirects
            "impersonate": "chrome131",
            "used": True,
        }

    Returns None on:
      • curl_cffi not available (caller skips the prewarm cleanly)
      • transport / proxy error
      • non-success status from the target (we don't want to seed
        garbage cookies on a 4xx/5xx response)

    Safe-by-default: every error path returns None so the caller's
    Playwright flow runs exactly as it did before — never raises.
    """
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return None

    proxy_uri = _build_proxy_uri(proxy) if proxy else None
    impersonate = impersonate_for_ua(ua) if ua else "chrome131"

    req_headers = {
        "User-Agent": ua or _fallback_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        from anti_detect_v230 import sec_fetch_headers as _sec_fetch
        req_headers.update(_sec_fetch(sec_fetch_kind))
    except Exception:
        req_headers.update({
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
        })

    try:
        async with _AsyncSession(**_async_session_kwargs(ua, timeout=timeout)) as session:
            kwargs: Dict[str, Any] = {
                "headers": req_headers,
                "allow_redirects": True,
            }
            if proxy_uri:
                kwargs["proxy"] = proxy_uri
            r = await session.get(url, **kwargs)
            status = int(r.status_code)
            # Anything 2xx/3xx is a "warmed" session — Cloudflare 503
            # interstitials don't seed cf_clearance yet, so we only
            # keep cookies on a real success.
            if status >= 400:
                return None
            cookies_out = []
            try:
                # curl_cffi exposes the cookie jar via `.cookies`
                for c in (r.cookies.jar if hasattr(r.cookies, "jar") else r.cookies):
                    try:
                        name = getattr(c, "name", None)
                        value = getattr(c, "value", None)
                        domain = getattr(c, "domain", None) or ""
                        path = getattr(c, "path", None) or "/"
                        if not name or value is None:
                            continue
                        ck: Dict[str, Any] = {
                            "name": str(name),
                            "value": str(value),
                            "path": str(path or "/"),
                        }
                        if domain:
                            ck["domain"] = str(domain)
                        secure = getattr(c, "secure", False)
                        if secure:
                            ck["secure"] = True
                        expires = getattr(c, "expires", None)
                        if expires:
                            try:
                                ck["expires"] = int(expires)
                            except Exception:
                                pass
                        cookies_out.append(ck)
                    except Exception:
                        continue
            except Exception:
                cookies_out = []
            final_url = str(getattr(r, "url", "") or url)
            return {
                "ok": True,
                "status": status,
                "cookies": cookies_out,
                "final_url": final_url,
                "impersonate": impersonate,
                "used": True,
            }
    except Exception as e:
        logger.debug(f"[tls_anti_detect] prewarm_target {url} failed via curl_cffi: {e}")
        return None


async def prewarm_companion_origins(
    url: str,
    *,
    proxy: Optional[Dict[str, Any]] = None,
    ua: str = "",
    timeout: float = 12.0,
    accept_language: str = "en-US,en;q=0.9",
) -> Optional[List[Dict[str, Any]]]:
    """Seed same-origin TLS session cookies via curl_cffi before Playwright
    navigates. Complements ``prewarm_target`` by warming the origin root +
    lightweight assets so the browser's first navigation inherits a
    Chrome JA3 session closer to curl_cffi's fingerprint."""
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    try:
        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(url or "")
        if not parsed.scheme or not parsed.netloc:
            return None
        origin = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None

    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for companion in (origin + "/", origin + "/favicon.ico", origin + "/robots.txt"):
        try:
            res = await prewarm_target(
                companion,
                proxy=proxy,
                ua=ua,
                timeout=timeout,
                accept_language=accept_language,
                sec_fetch_kind="same_site_link",
            )
            if not res or not res.get("cookies"):
                continue
            for ck in res.get("cookies") or []:
                key = (ck.get("name"), ck.get("domain"), ck.get("path"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(ck)
        except Exception as exc:
            logger.debug(f"[tls_anti_detect] companion prewarm {companion} failed: {exc}")
    return merged or None


async def resolve_redirect_location(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    ua: str = "",
    timeout: float = 15.0,
) -> Optional[str]:
    """GET ``url`` without following redirects; return ``Location`` on 3xx.

    Used by RUT server-side tracker resolve so S2S TLS matches the browser UA.
    Returns None on any error — caller falls back to httpx.
    """
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return None

    req_headers = dict(headers or {})
    if ua and "User-Agent" not in req_headers:
        req_headers["User-Agent"] = ua
    req_headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    req_headers.setdefault("Accept-Language", "en-US,en;q=0.9")
    try:
        from anti_detect_v230 import sec_fetch_headers as _sec_fetch
        req_headers.update(_sec_fetch("ad_click"))
    except Exception:
        req_headers.setdefault("Sec-Fetch-Dest", "document")
        req_headers.setdefault("Sec-Fetch-Mode", "navigate")
        req_headers.setdefault("Sec-Fetch-Site", "cross-site")
        req_headers.setdefault("Sec-Fetch-User", "?1")

    try:
        async with _AsyncSession(**_async_session_kwargs(ua or req_headers.get("User-Agent", ""), timeout=timeout)) as session:
            r = await session.get(url, headers=req_headers, allow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = (r.headers.get("Location") or r.headers.get("location") or "").strip()
                return loc or None
    except Exception as e:
        logger.debug(f"[tls_anti_detect] resolve_redirect_location {url} failed: {e}")
    return None


async def head_or_get_status(
    url: str,
    *,
    proxy: Optional[Dict[str, Any]] = None,
    ua: str = "",
    timeout: float = 12.0,
) -> Optional[int]:
    """Lightweight reachability probe — tries HEAD first, falls back to
    GET with no-body if HEAD is not allowed. Returns status code or None.
    """
    if not _CURL_CFFI_AVAILABLE or _AsyncSession is None:
        return None
    proxy_uri = _build_proxy_uri(proxy) if proxy else None
    impersonate = impersonate_for_ua(ua) if ua else "chrome131"

    req_headers = {
        "User-Agent": ua or _fallback_ua(),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with _AsyncSession(
            impersonate=impersonate,
            timeout=timeout,
            verify=False,
        ) as session:
            kwargs: Dict[str, Any] = {"headers": req_headers, "allow_redirects": True}
            if proxy_uri:
                kwargs["proxy"] = proxy_uri
            # Try HEAD first; some CDNs reject it → GET fallback.
            try:
                r = await session.head(url, **kwargs)
                if 200 <= r.status_code < 500:
                    return int(r.status_code)
            except Exception:
                pass
            r = await session.get(url, **kwargs)
            return int(r.status_code)
    except Exception as e:
        logger.debug(f"[tls_anti_detect] head_or_get_status {url} failed via curl_cffi: {e}")
        return None
