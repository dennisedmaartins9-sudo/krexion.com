"""
Krexion — Browser Profiles Module (2026-06-11)
================================================

AdsPower / GoLogin-style manual browsing profiles. Each profile stores:
  • Identity config (name, country, language, UA, viewport, device)
  • Anti-detect config (same flags as RUT jobs — auto-tuned by master toggle)
  • Referrer config (Pro Mode platform/email weights for outbound clicks)
  • Proxy assignment (manual or ProxyJet auto-allocated unique IP)
  • Persistent storage_state (cookies + localStorage across launches)

Customers use these profiles to MANUALLY browse the web with the same
professional-grade anti-detect stack used by RUT jobs. Typical use:
verify offer pages, login to ad accounts on alt identities, manual
research on competitor sites without burning your main IP.

Architecture:
  • Cloud mode (krexion.com)         → CRUD only. Launch returns a
                                       bridge_job that the customer's
                                       local desktop client picks up
                                       and opens HEADED Chromium with
                                       all anti-detect injected.
  • Desktop mode (Electron/native)   → CRUD + actual local launch.
                                       The Electron host process opens
                                       a Playwright headed context with
                                       full anti-detect script + the
                                       stored storage_state.

Storage:
  • Mongo collection: `browser_profiles`   (per-user records)
  • Mongo collection: `browser_profile_templates`  (saved create-form presets)
  • Bridge jobs of kind="browser_profile_launch" relay to desktop.

Endpoints (all under /api/browser-profiles/*):
  GET    /                   List user's profiles
  POST   /                   Create profile (auto-gen UA + viewport optional)
  GET    /{id}               Get one profile (incl. storage_state stats)
  PUT    /{id}               Update profile config
  DELETE /{id}               Delete profile + its sessions
  POST   /{id}/clone         Duplicate (new id, name " (copy)")
  POST   /{id}/launch        Start a manual browse session
  POST   /{id}/stop          Stop a running session
  GET    /{id}/status        Is the session running?
  POST   /import-bulk        Bulk-create N profiles (range / list)
  GET    /export             Download all profiles as JSON
  POST   /generate-quick     One-click: create a profile with auto UA + proxy
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("browser_profile_module")

# ─── Globals bound by server.py via _bind() ──────────────────────────
_DB: Any = None
_BRIDGE_QUEUE: Any = None
_GET_USER: Any = None
_UA_GEN: Any = None
_PROXYJET_GEN: Any = None

router = APIRouter(prefix="/api/browser-profiles", tags=["browser-profiles"])


def _bind(*, db, get_current_user, bridge_enqueue=None, ua_generate_func=None,
          proxyjet_generate_func=None):
    """Called once by server.py at import time.

    `proxyjet_generate_func` (2026-01) is the bound coroutine that
    backs the `/api/proxyjet/generate-batch` endpoint. We use it for
    the new advanced-create flow: when a user enables ProxyJet mode
    we call it to allocate N unique exit-IPs so every profile gets a
    truly-distinct outbound proxy.
    """
    global _DB, _BRIDGE_QUEUE, _GET_USER, _UA_GEN, _PROXYJET_GEN
    _DB = db
    _GET_USER = get_current_user
    _BRIDGE_QUEUE = bridge_enqueue
    _UA_GEN = ua_generate_func
    _PROXYJET_GEN = proxyjet_generate_func


# Wrapper used as FastAPI Depends — resolves to the bound real dep at
# request time (so router decorators can reference it even though it's
# set after import).
async def _auth(request: Any = None):
    if _GET_USER is None:
        raise HTTPException(status_code=503, detail="Browser Profiles: auth not bound")
    # FastAPI will resolve the bound dep on the actual handler via
    # Depends below; this stub is only used when no fancy dep injection
    # is wanted. We return a marker — actual user is extracted via
    # the wrapper pattern below in each endpoint.
    return None


# ──────────────────────────────────────────────────────────────────────
# Default UA + viewport pools for auto-gen
# ──────────────────────────────────────────────────────────────────────
_VIEWPORTS_DESKTOP = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
    {"width": 2560, "height": 1440},
]
_VIEWPORTS_MOBILE = [
    {"width": 390, "height": 844},   # iPhone 15
    {"width": 393, "height": 852},   # iPhone 14 Pro
    {"width": 414, "height": 896},   # iPhone XR
    {"width": 360, "height": 780},   # Galaxy S22
    {"width": 412, "height": 915},   # Pixel 7
]

# v2.7.12 — Device catalog for mix create + smart naming.
# Each entry drives viewport/DPR + human-readable auto-name slug.
_DEVICE_CATALOG: List[Dict[str, Any]] = [
    # iOS
    {"id": "iphone16promax", "slug": "iPhone16ProMax", "platform": "ios", "brand": "iphone",
     "label": "iPhone 16 Pro Max", "viewport": {"width": 440, "height": 956}, "dpr": 3.0},
    {"id": "iphone16pro", "slug": "iPhone16Pro", "platform": "ios", "brand": "iphone",
     "label": "iPhone 16 Pro", "viewport": {"width": 402, "height": 874}, "dpr": 3.0},
    {"id": "iphone15promax", "slug": "iPhone15ProMax", "platform": "ios", "brand": "iphone",
     "label": "iPhone 15 Pro Max", "viewport": {"width": 430, "height": 932}, "dpr": 3.0},
    {"id": "iphone15pro", "slug": "iPhone15Pro", "platform": "ios", "brand": "iphone",
     "label": "iPhone 15 Pro", "viewport": {"width": 393, "height": 852}, "dpr": 3.0},
    {"id": "iphone15plus", "slug": "iPhone15Plus", "platform": "ios", "brand": "iphone",
     "label": "iPhone 15 Plus", "viewport": {"width": 430, "height": 932}, "dpr": 3.0},
    {"id": "iphone15", "slug": "iPhone15", "platform": "ios", "brand": "iphone",
     "label": "iPhone 15", "viewport": {"width": 390, "height": 844}, "dpr": 3.0},
    {"id": "iphone14pro", "slug": "iPhone14Pro", "platform": "ios", "brand": "iphone",
     "label": "iPhone 14 Pro", "viewport": {"width": 393, "height": 852}, "dpr": 3.0},
    {"id": "iphone13", "slug": "iPhone13", "platform": "ios", "brand": "iphone",
     "label": "iPhone 13", "viewport": {"width": 390, "height": 844}, "dpr": 3.0},
    {"id": "iphonese", "slug": "iPhoneSE", "platform": "ios", "brand": "iphone",
     "label": "iPhone SE", "viewport": {"width": 375, "height": 667}, "dpr": 2.0},
    {"id": "ipadpro11", "slug": "iPadPro11", "platform": "ios", "brand": "ipad",
     "label": "iPad Pro 11", "viewport": {"width": 834, "height": 1194}, "dpr": 2.0},
    # Android
    {"id": "pixel9", "slug": "Pixel9", "platform": "android", "brand": "google",
     "label": "Pixel 9", "viewport": {"width": 412, "height": 915}, "dpr": 2.625},
    {"id": "pixel8", "slug": "Pixel8", "platform": "android", "brand": "google",
     "label": "Pixel 8", "viewport": {"width": 412, "height": 915}, "dpr": 2.625},
    {"id": "pixel7", "slug": "Pixel7", "platform": "android", "brand": "google",
     "label": "Pixel 7", "viewport": {"width": 412, "height": 915}, "dpr": 2.625},
    {"id": "galaxys24ultra", "slug": "GalaxyS24Ultra", "platform": "android", "brand": "samsung",
     "label": "Galaxy S24 Ultra", "viewport": {"width": 384, "height": 824}, "dpr": 3.0},
    {"id": "galaxys24", "slug": "GalaxyS24", "platform": "android", "brand": "samsung",
     "label": "Galaxy S24", "viewport": {"width": 360, "height": 780}, "dpr": 3.0},
    {"id": "galaxys23", "slug": "GalaxyS23", "platform": "android", "brand": "samsung",
     "label": "Galaxy S23", "viewport": {"width": 360, "height": 780}, "dpr": 3.0},
    {"id": "galaxya55", "slug": "GalaxyA55", "platform": "android", "brand": "samsung",
     "label": "Galaxy A55", "viewport": {"width": 412, "height": 915}, "dpr": 2.625},
    {"id": "oneplus12", "slug": "OnePlus12", "platform": "android", "brand": "oneplus",
     "label": "OnePlus 12", "viewport": {"width": 412, "height": 919}, "dpr": 3.5},
    {"id": "xiaomi14", "slug": "Xiaomi14", "platform": "android", "brand": "xiaomi",
     "label": "Xiaomi 14", "viewport": {"width": 393, "height": 873}, "dpr": 2.75},
    # Desktop
    {"id": "win11chrome", "slug": "Win11-Chrome", "platform": "desktop", "brand": "windows",
     "label": "Windows 11 Chrome", "viewport": {"width": 1920, "height": 1080}, "dpr": 1.0},
    {"id": "win11fhd", "slug": "Win11-1536", "platform": "desktop", "brand": "windows",
     "label": "Windows 11 1536", "viewport": {"width": 1536, "height": 864}, "dpr": 1.25},
    {"id": "win11hd", "slug": "Win11-1366", "platform": "desktop", "brand": "windows",
     "label": "Windows 11 1366", "viewport": {"width": 1366, "height": 768}, "dpr": 1.0},
    {"id": "macchrome", "slug": "Mac-Chrome", "platform": "desktop", "brand": "mac",
     "label": "macOS Chrome", "viewport": {"width": 1440, "height": 900}, "dpr": 2.0},
    {"id": "macretina", "slug": "Mac-Retina", "platform": "desktop", "brand": "mac",
     "label": "macOS Retina", "viewport": {"width": 1680, "height": 1050}, "dpr": 2.0},
]


def _devices_for_platform(platform: str) -> List[Dict[str, Any]]:
    plat = (platform or "").lower().strip()
    return [d for d in _DEVICE_CATALOG if d["platform"] == plat]


def _find_device(device_id: str) -> Optional[Dict[str, Any]]:
    key = (device_id or "").strip().lower()
    if not key:
        return None
    for d in _DEVICE_CATALOG:
        if d["id"] == key or d["slug"].lower() == key:
            return d
    return None


def _split_mix_counts(
    total: int,
    ios_pct: float,
    android_pct: float,
    desktop_pct: float,
) -> Optional[List[Tuple[str, int]]]:
    """Return [(platform, n), ...] or None when mix disabled (all zero)."""
    total = max(1, int(total))
    ios_pct = max(0.0, float(ios_pct or 0))
    android_pct = max(0.0, float(android_pct or 0))
    desktop_pct = max(0.0, float(desktop_pct or 0))
    s = ios_pct + android_pct + desktop_pct
    if s <= 0:
        return None
    ios_pct, android_pct, desktop_pct = (
        ios_pct / s * 100.0,
        android_pct / s * 100.0,
        desktop_pct / s * 100.0,
    )
    n_ios = int(round(total * ios_pct / 100.0))
    n_android = int(round(total * android_pct / 100.0))
    if desktop_pct <= 0:
        n_desktop = 0
    elif ios_pct <= 0 and android_pct <= 0:
        n_desktop = total
        n_ios = 0
        n_android = 0
    else:
        n_desktop = total - n_ios - n_android
    # When desktop is 0%, rounding remainder must go to iOS/Android only.
    if desktop_pct <= 0:
        while n_ios + n_android < total:
            if ios_pct >= android_pct:
                n_ios += 1
            else:
                n_android += 1
        while n_ios + n_android > total:
            if n_ios >= n_android and n_ios > 0:
                n_ios -= 1
            elif n_android > 0:
                n_android -= 1
            else:
                break
    # Fix rare overshoot from rounding when desktop allowed.
    while n_desktop < 0 and (n_ios > 0 or n_android > 0):
        if n_ios >= n_android and n_ios > 0:
            n_ios -= 1
        elif n_android > 0:
            n_android -= 1
        n_desktop = total - n_ios - n_android
    while n_ios + n_android + n_desktop > total:
        if n_desktop > 0:
            n_desktop -= 1
        elif n_android > 0:
            n_android -= 1
        elif n_ios > 0:
            n_ios -= 1
        else:
            break
    while n_ios + n_android + n_desktop < total:
        if desktop_pct > 0:
            n_desktop += 1
        elif ios_pct >= android_pct:
            n_ios += 1
        else:
            n_android += 1
    out: List[Tuple[str, int]] = []
    if n_ios:
        out.append(("ios", n_ios))
    if n_android:
        out.append(("android", n_android))
    if n_desktop:
        out.append(("desktop", n_desktop))
    return out or [("desktop", total)]


def _auto_name_device(country: str, device_slug: str) -> str:
    """Smart unique name: Krexion-iPhone15-US-0825-A7K3."""
    cc = (country or "us").upper()[:3]
    slug = re.sub(r"[^A-Za-z0-9_-]+", "", (device_slug or "Device"))[:28] or "Device"
    ts = datetime.now().strftime("%m%d")
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"Krexion-{slug}-{cc}-{ts}-{suffix}"


def _pick_device(
    platform: str,
    *,
    device_mode: str = "random",
    device_id: str = "",
    used_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Pick a catalog device for this platform; prefer unused ids in-batch."""
    used_ids = used_ids if used_ids is not None else set()
    specific = _find_device(device_id) if (device_mode or "").lower() == "specific" else None
    if specific and specific["platform"] == platform:
        used_ids.add(specific["id"])
        return specific
    pool = _devices_for_platform(platform)
    if not pool:
        # Synthetic fallback
        if platform == "ios":
            return {
                "id": "iphone15", "slug": "iPhone15", "platform": "ios", "brand": "iphone",
                "label": "iPhone 15", "viewport": {"width": 390, "height": 844}, "dpr": 3.0,
            }
        if platform == "android":
            return {
                "id": "pixel8", "slug": "Pixel8", "platform": "android", "brand": "google",
                "label": "Pixel 8", "viewport": {"width": 412, "height": 915}, "dpr": 2.625,
            }
        return {
            "id": "win11chrome", "slug": "Win11-Chrome", "platform": "desktop", "brand": "windows",
            "label": "Windows 11 Chrome", "viewport": {"width": 1920, "height": 1080}, "dpr": 1.0,
        }
    unused = [d for d in pool if d["id"] not in used_ids]
    choice = random.choice(unused or pool)
    used_ids.add(choice["id"])
    return choice


def _viewport_for_device(
    device: Dict[str, Any],
    *,
    resolution_mode: str = "match_device",
    width: int = 0,
    height: int = 0,
) -> Dict[str, int]:
    mode = (resolution_mode or "match_device").lower().strip()
    if mode == "exact" and width > 0 and height > 0:
        return {"width": int(width), "height": int(height)}
    if mode == "random":
        plat = device.get("platform") or "desktop"
        return _gen_random_viewport(is_mobile=(plat in ("ios", "android")))
    vp = device.get("viewport") or {}
    w = int(vp.get("width") or 0)
    h = int(vp.get("height") or 0)
    if w > 0 and h > 0:
        return {"width": w, "height": h}
    return _gen_random_viewport(is_mobile=(device.get("platform") in ("ios", "android")))

_FALLBACK_UAS_DESKTOP = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
]
_FALLBACK_UAS_MOBILE = [
    # v2.7.8 — Chromium profiles: Android Chrome/136 only (no pure Safari).
    # Mix Chrome *app* (no wv) ~50% + WebView (wv) ~50% for in-app realism.
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.125 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; SM-S931B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.113 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.92 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro Build/AP3A.240905.015; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.7103.125 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.7103.113 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-A556B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.7103.92 Mobile Safari/537.36",
]


def _gen_random_ua(is_mobile: bool = False) -> str:
    return random.choice(_FALLBACK_UAS_MOBILE if is_mobile else _FALLBACK_UAS_DESKTOP)


def _gen_random_viewport(is_mobile: bool = False) -> Dict[str, int]:
    return random.choice(_VIEWPORTS_MOBILE if is_mobile else _VIEWPORTS_DESKTOP).copy()


def _infer_os_from_ua(ua: str, *, is_mobile: bool = False, fallback: str = "windows") -> str:
    """Infer profile `os` from UA so Android mobile profiles don't get `ios`."""
    try:
        from visual_recorder import _detect_mobile_from_ua
        _, os_kind = _detect_mobile_from_ua(ua or "")
        if os_kind in ("ios", "ipados"):
            return "ios"
        if os_kind == "android":
            return "android"
        if os_kind == "macos":
            return "macos"
        if os_kind == "linux":
            return "linux"
        if os_kind == "windows":
            return "windows"
    except Exception:
        pass
    if is_mobile:
        u = (ua or "").lower()
        if "android" in u:
            return "android"
        if "iphone" in u or "ipad" in u or "ios" in u:
            return "ios"
        return "android"
    return fallback


def _allow_ios_safari_ua() -> bool:
    return (os.environ.get("KREXION_ALLOW_IOS_SAFARI_UA") or "").strip().lower() in (
        "1", "true", "yes",
    )


def _normalize_profile_ua_honesty(ua: str) -> Tuple[str, Dict[str, Any]]:
    """Profile create/update UA honesty (v2.7.9 dual-engine).

    Prefer storing iOS UAs as the user requested — launch path picks
    Playwright WebKit or Android Chrome fallback. Non-iOS UAs go through
    ``_normalize_mobile_ua_for_visit`` (Chromium path).
    """
    try:
        from real_user_traffic import (
            _ua_prefers_webkit,
            _normalize_mobile_ua_for_visit,
            _os_from_mobile_ua,
        )
        raw = ua or ""
        if _ua_prefers_webkit(raw):
            # Store as requested; launch decides WebKit vs Chromium fallback.
            return raw.strip(), {
                "swapped_ios": False,
                "os": _os_from_mobile_ua(raw) or "ios",
                "is_mobile": True,
                "engine": "webkit",
                "note": "iOS UA stored as requested; launch picks WebKit or Chromium fallback",
            }
        return _normalize_mobile_ua_for_visit(raw)
    except Exception:
        try:
            from real_user_traffic import _normalize_mobile_ua_for_visit
            return _normalize_mobile_ua_for_visit(ua or "")
        except Exception:
            return ua or "", {
                "swapped_ios": False,
                "os": "",
                "is_mobile": False,
                "engine": "chromium",
                "note": "",
            }


def _coerce_profile_ua_for_chromium(ua: str) -> Tuple[str, Dict[str, Any]]:
    """Backward-compatible alias → ``_normalize_profile_ua_honesty``."""
    return _normalize_profile_ua_honesty(ua)


def _honest_ua_platform_for_profiles(platform: str, *, is_mobile: bool) -> str:
    """Default mobile platform is android; allow ios when WebKit available."""
    plat = (platform or "").strip().lower()
    if not plat or plat == "any":
        return "android" if is_mobile else "desktop"
    if is_mobile and plat == "ios":
        if _allow_ios_safari_ua():
            return "ios"
        try:
            from real_user_traffic import _webkit_runtime_available
            if _webkit_runtime_available():
                return "ios"
        except Exception:
            pass
        return "android"
    return plat or ("android" if is_mobile else "desktop")


def _parse_proxy_line(line: str, proxy_type: str = "http") -> Dict[str, str]:
    """Normalize a provider / manual proxy line → server + creds dict.

    Preserves socks5/socks4 when the line (or proxy_type) says so — do not
    force everything to http:// (breaks SOCKS providers).
    """
    line = (line or "").strip()
    server = ""
    username = ""
    password = ""
    if not line:
        return {"server": "", "username": "", "password": ""}
    ptype = (proxy_type or "http").strip().lower()
    if ptype.startswith("socks5"):
        default_scheme = "socks5"
    elif ptype.startswith("socks4"):
        default_scheme = "socks4"
    elif ptype in ("https", "http"):
        default_scheme = ptype
    else:
        default_scheme = "http"
    try:
        from urllib.parse import unquote, urlparse

        probe = line if "://" in line else f"{default_scheme}://{line}"
        if "://" in probe and "@" in probe.split("://", 1)[-1]:
            parsed = urlparse(probe)
            if parsed.hostname:
                scheme = parsed.scheme or default_scheme
                host = parsed.hostname
                port = parsed.port
                netloc = host if not port else f"{host}:{port}"
                return {
                    "server": f"{scheme}://{netloc}",
                    "username": unquote(parsed.username or ""),
                    "password": unquote(parsed.password or ""),
                }
    except Exception:
        pass
    try:
        if "://" in line:
            proto, rest = line.split("://", 1)
            if "@" in rest:
                creds, hostpart = rest.rsplit("@", 1)
                username, _, password = creds.partition(":")
                server = f"{proto}://{hostpart}"
            else:
                colon_parts = rest.split(":")
                if len(colon_parts) >= 4:
                    host, port, username = colon_parts[0], colon_parts[1], colon_parts[2]
                    password = ":".join(colon_parts[3:])
                    server = f"{proto}://{host}:{port}"
                elif len(colon_parts) == 2:
                    server = f"{proto}://{colon_parts[0]}:{colon_parts[1]}"
                else:
                    server = line
        elif "@" in line:
            creds, hostport = line.rsplit("@", 1)
            username, _, password = creds.partition(":")
            server = f"{default_scheme}://{hostport}"
        else:
            parts = line.split(":")
            if len(parts) >= 4:
                host, port, username = parts[0], parts[1], parts[2]
                password = ":".join(parts[3:])
                server = f"{default_scheme}://{host}:{port}"
            elif len(parts) >= 2:
                server = f"{default_scheme}://{parts[0]}:{parts[1]}"
            else:
                server = line
    except Exception as _pe:
        logger.warning(f"proxy line parse failed: {_pe}")
        server = line
    return {"server": server, "username": username, "password": password}


def _build_proxy_probe_url(proxy_string: str, proxy_type: str = "http") -> str:
    """Proxies-page parity — preserve scheme and `;` in DataImpulse usernames."""
    ps = (proxy_string or "").strip()
    if not ps:
        raise ValueError("empty proxy string")
    scheme_fallback = "socks5" if str(proxy_type).lower().startswith("socks") else "http"
    if "://" in ps:
        return ps
    if "@" in ps:
        return f"{scheme_fallback}://{ps}"
    parts = ps.split(":")
    if len(parts) == 4:
        host, port, username, password = parts
        return f"{scheme_fallback}://{username}:{password}@{host}:{port}"
    if len(parts) == 2:
        return f"{scheme_fallback}://{ps}"
    raise ValueError(f"Invalid proxy format: cannot parse {ps!r}")


def _proxy_dict_to_probe_url(proxy: Dict[str, Any], proxy_type: str = "http") -> str:
    """Build exit-IP probe URL from hydrated proxy fields (server.py parity)."""
    from urllib.parse import quote

    server = str(proxy.get("server") or "").strip()
    username = str(proxy.get("username") or "").strip()
    password = str(proxy.get("password") or "").strip()
    ptype = str(proxy.get("proxy_type") or proxy_type or "http").strip().lower()
    scheme_fallback = "socks5" if ptype.startswith("socks") else "http"

    if server:
        hostpart = server
        scheme = scheme_fallback
        if "://" in server:
            scheme, hostpart = server.split("://", 1)
        if "@" in hostpart:
            from urllib.parse import unquote, urlparse

            parsed = urlparse(server if "://" in server else f"{scheme_fallback}://{hostpart}")
            if parsed.hostname:
                scheme = parsed.scheme or scheme_fallback
                netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
                u = unquote(parsed.username or "") or username
                p = unquote(parsed.password or "") or password
                if u and p:
                    return (
                        f"{scheme}://{quote(u, safe='')}:{quote(p, safe='')}@{netloc}"
                    )
                if u:
                    return f"{scheme}://{quote(u, safe='')}@{netloc}"
                return f"{scheme}://{netloc}"
        if username and password:
            return (
                f"{scheme}://{quote(username, safe='')}:"
                f"{quote(password, safe='')}@{hostpart}"
            )
        return server if "://" in server else f"{scheme_fallback}://{hostpart}"

    raw = str(proxy.get("raw_line") or proxy.get("raw") or "").strip()
    if raw:
        return _build_proxy_probe_url(raw, ptype)
    raise ValueError("no_proxy_configured")


def proxy_is_active(proxy: Optional[Dict[str, Any]]) -> bool:
    """True only when proxy is explicitly enabled with a configured source."""
    p = dict(proxy or {})
    if p.get("enabled") is False:
        return False
    return bool(
        p.get("enabled")
        or str(p.get("provider_id") or "").strip()
        or p.get("use_proxyjet")
        or str(p.get("server") or "").strip()
    )


def hydrate_proxy_credentials(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing proxy username/password from raw_line or embedded server URL."""
    out = dict(cfg or {})
    server = str(out.get("server") or "").strip()
    username = str(out.get("username") or "").strip()
    password = str(out.get("password") or "").strip()
    ptype = str(out.get("proxy_type") or "http").strip() or "http"
    if not server and not str(out.get("raw_line") or out.get("raw") or "").strip():
        return out

    raw_line = str(out.get("raw_line") or out.get("raw") or "").strip()
    if raw_line:
        parsed = _parse_proxy_line(raw_line, proxy_type=ptype)
        if not server and parsed.get("server"):
            server = str(parsed["server"]).strip()
        if not username and parsed.get("username"):
            username = str(parsed["username"]).strip()
        if not password and parsed.get("password"):
            password = str(parsed["password"]).strip()

    if server and (not username or not password):
        probe = server if "://" in server else f"{ptype if ptype.startswith('socks') or ptype in ('http', 'https') else 'http'}://{server}"
        parsed = _parse_proxy_line(probe, proxy_type=ptype)
        if parsed.get("server"):
            server = str(parsed["server"]).strip()
        if not username and parsed.get("username"):
            username = str(parsed["username"]).strip()
        if not password and parsed.get("password"):
            password = str(parsed["password"]).strip()

    if server:
        out["server"] = server
    if username:
        out["username"] = username
    if password:
        out["password"] = password
    if ptype:
        out["proxy_type"] = ptype
    return out


def _canonical_proxy_raw_line(proxy: Dict[str, Any]) -> str:
    """Rebuild scheme://user:pass@host:port line for launch-time auth recovery."""
    out = hydrate_proxy_credentials(dict(proxy or {}))
    server = str(out.get("server") or "").strip()
    username = str(out.get("username") or "").strip()
    password = str(out.get("password") or "").strip()
    if not server or not username or not password:
        return str(out.get("raw_line") or out.get("raw") or "").strip()
    hostpart = server.split("://", 1)[-1]
    if "@" in hostpart:
        return str(out.get("raw_line") or out.get("raw") or server).strip()
    from urllib.parse import quote, urlparse

    try:
        scheme = urlparse(server if "://" in server else f"http://{server}").scheme or "http"
    except Exception:
        scheme = "http"
    if str(out.get("proxy_type") or "").lower().startswith("socks5"):
        scheme = "socks5"
    elif str(out.get("proxy_type") or "").lower().startswith("socks4"):
        scheme = "socks4"
    return f"{scheme}://{quote(username, safe='')}:{quote(password, safe='')}@{hostpart}"


def _proxy_host_from_server(server: str) -> str:
    srv = (server or "").strip()
    if not srv:
        return ""
    try:
        from urllib.parse import urlparse

        p = urlparse(srv if "://" in srv else f"http://{srv}")
        return (p.hostname or "").strip().lower()
    except Exception:
        return ""


def _sanitize_proxy_for_public(proxy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Redact secrets before API responses (list/get/ACL share)."""
    p = dict(proxy or {})
    has_password = bool(str(p.get("password") or "").strip())
    raw = str(p.get("raw_line") or p.get("raw") or "").strip()
    if raw and (":" in raw or "@" in raw):
        has_password = True
    p.pop("password", None)
    p.pop("raw_line", None)
    p.pop("raw", None)
    # Never leak user:pass embedded in server URL
    srv = str(p.get("server") or "").strip()
    if srv and "@" in srv.split("://", 1)[-1]:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(srv if "://" in srv else f"http://{srv}")
            if parsed.hostname:
                netloc = parsed.hostname
                if parsed.port:
                    netloc = f"{parsed.hostname}:{parsed.port}"
                p["server"] = f"{parsed.scheme or 'http'}://{netloc}"
                has_password = True
        except Exception:
            pass
    p["has_password"] = has_password
    # Empty password field for edit forms — client must send new value to change
    p["password"] = ""
    return p


async def resolve_launch_proxy_cfg(
    uid: str,
    user: Optional[dict],
    proxy_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Hydrate manual/provider proxy auth before Playwright — prevents Chromium sign-in popup."""
    out = await _finalize_proxy_cfg_for_launch(uid, user, dict(proxy_cfg or {}))
    out = hydrate_proxy_credentials(out)

    if not str(out.get("password") or "").strip():
        for key in ("raw_line", "raw"):
            raw = str(out.get(key) or "").strip()
            if raw:
                parsed = _parse_proxy_line(raw)
                if parsed.get("password"):
                    out["password"] = parsed["password"]
                if parsed.get("username") and not str(out.get("username") or "").strip():
                    out["username"] = parsed["username"]
                if parsed.get("server"):
                    out["server"] = parsed["server"]
                break

    if not str(out.get("password") or "").strip() and str(out.get("server") or "").strip():
        parsed = _parse_proxy_line(str(out.get("server") or ""))
        if parsed.get("password"):
            out["password"] = parsed["password"]
        if parsed.get("username") and not str(out.get("username") or "").strip():
            out["username"] = parsed["username"]
        if parsed.get("server"):
            out["server"] = parsed["server"]

    host = _proxy_host_from_server(str(out.get("server") or ""))
    if host and not str(out.get("password") or "").strip() and uid and _DB is not None:
        try:
            async for prov in _DB.proxy_providers.find({"user_id": uid, "enabled": True}):
                cfg = prov.get("config") or {}
                gw = str(cfg.get("gateway_host") or "").strip().lower()
                if gw and gw == host:
                    gw_pwd = str(cfg.get("password") or "").strip()
                    if gw_pwd:
                        out["password"] = gw_pwd
                        if not str(out.get("username") or "").strip() and cfg.get("username"):
                            out["username"] = str(cfg["username"]).strip()
                        break
        except Exception as exc:
            logger.debug(f"[browser-profile] gateway password lookup skipped: {exc}")

    raw = _canonical_proxy_raw_line(out)
    if raw:
        out["raw_line"] = raw
    return hydrate_proxy_credentials(out)


async def _finalize_proxy_cfg_for_launch(
    uid: str,
    user: Optional[dict],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve + merge provider gateway password before Playwright/Chromium launch."""
    out = await hydrate_proxy_credentials_for_launch(uid, user, dict(cfg or {}))
    if str(out.get("server") or "").strip():
        out["enabled"] = True
    if (
        str(out.get("server") or "").strip()
        and not str(out.get("password") or "").strip()
        and (
            out.get("enabled")
            or str(out.get("provider_id") or "").strip()
            or out.get("use_proxyjet")
        )
    ):
        logger.warning(
            "[browser-profile] proxy password missing after hydrate — "
            f"provider={str(out.get('provider_id') or '')[:8]} "
            f"server={str(out.get('server') or '')[:48]}"
        )
    return out


async def hydrate_proxy_credentials_for_launch(
    uid: str,
    user: Optional[dict],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Ensure rotating/manual profile proxies have auth before Playwright launch."""
    out = hydrate_proxy_credentials(cfg)
    provider_id = str(out.get("provider_id") or "").strip()
    if not provider_id or not uid:
        if str(out.get("password") or "").strip():
            return out
        return out

    # Rotating gateway: always prefer stored provider password (lines often
    # ship host-only or URL-encoded creds that advanced-create used to parse wrong).
    try:
        from proxy_provider_module import get_provider_gateway_credentials

        gw = await get_provider_gateway_credentials(uid, provider_id)
        gw_pwd = str(gw.get("password") or "").strip()
        if gw_pwd:
            if not str(out.get("username") or "").strip() and gw.get("username"):
                out["username"] = str(gw["username"]).strip()
            out["password"] = gw_pwd
            if not str(out.get("server") or "").strip():
                host = str(gw.get("gateway_host") or "").strip()
                port = str(gw.get("gateway_port") or "").strip()
                if host and port:
                    out["server"] = f"http://{host}:{port}"
            return hydrate_proxy_credentials(out)
    except Exception as exc:
        logger.debug(f"[browser-profile] provider gateway cred fallback skipped: {exc}")

    if str(out.get("password") or "").strip():
        return out

    try:
        from proxy_provider_module import get_proxy_from_provider

        pp_res = await get_proxy_from_provider(uid, provider_id)
        line = str(pp_res.get("proxy") or "").strip()
        if line:
            merged = _apply_resolved_line_to_proxy_cfg(out, line, provider_id=provider_id)
            merged = hydrate_proxy_credentials(merged)
            if str(merged.get("password") or "").strip():
                return merged
    except Exception as exc:
        logger.debug(f"[browser-profile] provider cred hydrate skipped: {exc}")

    return out


def _profile_provider_targeting(
    proxy_cfg: Dict[str, Any],
    profile_country: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """RUT parity — country/state hints for rotating_gateway username tokens."""
    targeting: Dict[str, Any] = {}
    cc = (
        str(
            proxy_cfg.get("proxyjet_country")
            or proxy_cfg.get("country")
            or profile_country
            or ""
        )
        .strip()
        .upper()
    )
    if cc and cc != "ANY":
        targeting["country"] = cc
    st = str(
        proxy_cfg.get("proxyjet_state") or proxy_cfg.get("state") or ""
    ).strip().upper()
    if st:
        targeting["state"] = st
    return targeting or None


def _apply_resolved_line_to_proxy_cfg(
    cfg: Dict[str, Any],
    line: str,
    *,
    provider_id: str = "",
) -> Dict[str, Any]:
    """Merge a provider/ProxyJet line into a profile proxy dict."""
    out = dict(cfg or {})
    parsed = _parse_proxy_line(str(line))
    out["enabled"] = True
    if provider_id:
        out["provider_id"] = provider_id
    out["server"] = parsed.get("server") or ""
    out["username"] = parsed.get("username") or ""
    out["password"] = parsed.get("password") or ""
    out["raw_line"] = str(line).strip()
    if not out["server"]:
        raw = str(line).strip()
        if "@" in raw:
            out["server"] = f"http://{raw.rsplit('@', 1)[-1]}"
        else:
            out["server"] = raw if "://" in raw else f"http://{raw}"
    out["use_proxyjet"] = False
    return hydrate_proxy_credentials(out)


async def _resolve_proxy_for_launch(
    uid: str,
    user: dict,
    proxy_cfg: Dict[str, Any],
    *,
    profile_country: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve provider / ProxyJet proxy to a concrete server URL before launch."""
    return await resolve_profile_proxy_for_launch(
        uid, user, proxy_cfg, team_dedupe=True, profile_country=profile_country,
    )


async def _fallback_provider_proxy_line(
    uid: str,
    user: Optional[dict],
    provider_id: str,
    *,
    targeting: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """VR/RUT-style single-line fallback when bulk unique fetch fails."""
    from proxy_provider_module import get_proxy_from_provider, get_proxy_lines_from_provider

    pp_res = await get_proxy_from_provider(uid, provider_id)
    if pp_res.get("use_proxyjet"):
        bulk = await get_proxy_lines_from_provider(
            uid,
            provider_id,
            1,
            strict_unique_ip=True,
            skip_datacenter_ip=True,
            targeting=targeting,
        )
        lines = bulk.get("lines") or []
        if lines:
            return str(lines[0])
        if bulk.get("error"):
            raise HTTPException(
                status_code=502,
                detail=f"Proxy provider failed: {bulk['error']}",
            )
        return None
    if pp_res.get("proxy"):
        return str(pp_res["proxy"])
    if pp_res.get("error"):
        raise HTTPException(
            status_code=502,
            detail=f"Proxy provider failed: {pp_res['error']}",
        )
    return None


async def resolve_profile_proxy_for_launch(
    uid: str,
    user: Optional[dict],
    proxy_cfg: Dict[str, Any],
    *,
    team_dedupe: bool = True,
    profile_country: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure profile proxy dict has a usable `server` when provider/proxyjet is set."""
    cfg = hydrate_proxy_credentials(dict(proxy_cfg or {}))
    if str(cfg.get("server") or "").strip():
        return await _finalize_proxy_cfg_for_launch(uid, user, cfg)

    provider_id = str(cfg.get("provider_id") or "").strip()
    targeting = _profile_provider_targeting(cfg, profile_country)

    if provider_id:
        used: Set[str] = set()
        if team_dedupe:
            used = await _load_team_profile_used_ips(uid)
        try:
            lines = await _allocate_provider_proxy_lines(
                uid, provider_id, 1, used, targeting=targeting,
            )
            resolved = _apply_resolved_line_to_proxy_cfg(
                cfg, lines[0], provider_id=provider_id,
            )
            logger.info(
                f"[browser-profile] provider {provider_id[:8]} resolved → "
                f"{str(resolved.get('server') or '')[:48]}"
            )
            return await _finalize_proxy_cfg_for_launch(uid, user, resolved)
        except HTTPException as bulk_err:
            try:
                fb_line = await _fallback_provider_proxy_line(
                    uid, user, provider_id, targeting=targeting,
                )
                if fb_line:
                    resolved = _apply_resolved_line_to_proxy_cfg(
                        cfg, fb_line, provider_id=provider_id,
                    )
                    logger.info(
                        f"[browser-profile] provider {provider_id[:8]} fallback → "
                        f"{str(resolved.get('server') or '')[:48]}"
                    )
                    return await _finalize_proxy_cfg_for_launch(uid, user, resolved)
            except HTTPException:
                raise
            raise bulk_err
        except Exception as exc:
            logger.warning(f"[browser-profile] provider resolve failed: {exc}")
            try:
                fb_line = await _fallback_provider_proxy_line(
                    uid, user, provider_id, targeting=targeting,
                )
                if fb_line:
                    resolved = _apply_resolved_line_to_proxy_cfg(
                        cfg, fb_line, provider_id=provider_id,
                    )
                    return await _finalize_proxy_cfg_for_launch(uid, user, resolved)
            except HTTPException:
                raise
            raise HTTPException(
                status_code=502,
                detail=f"Provider proxy resolve failed: {exc}",
            ) from exc

    if cfg.get("use_proxyjet") and not provider_id:
        if _PROXYJET_GEN is None:
            logger.warning("[browser-profile] ProxyJet enabled but generator not bound")
            return cfg
        try:
            from server import ProxyJetGenerateIn  # type: ignore
            pj_payload = ProxyJetGenerateIn(
                count=1,
                country=(cfg.get("proxyjet_country") or "US").strip().upper() or None,
                state=(cfg.get("proxyjet_state") or "").strip().upper() or None,
                sticky_minutes=0,
            )
            pj_resp = await _PROXYJET_GEN(pj_payload, user)
            lines = pj_resp.get("proxies") or []
            if lines:
                parsed = _parse_proxy_line(str(lines[0]))
                if parsed.get("server"):
                    cfg["enabled"] = True
                    cfg["server"] = parsed["server"]
                    if parsed.get("username"):
                        cfg["username"] = parsed["username"]
                    if parsed.get("password"):
                        cfg["password"] = parsed["password"]
        except Exception as e:
            logger.warning(f"[browser-profile] ProxyJet resolve at launch failed: {e}")
    return await _finalize_proxy_cfg_for_launch(uid, user, cfg)


async def validate_profile_perfect_session(db, session_id: str) -> Dict[str, Any]:
    """Active Browser Profile + Referrer Pro ON → manual link perfect mode.

    When valid, Krexion link clicks skip server-side wrapper hops; the profile
    Playwright route injects the platform Referer on the offer document (RUT
    pass_to_offer parity).
    """
    out: Dict[str, Any] = {"ok": False, "session_id": "", "profile_id": "", "platform": ""}
    sid = (session_id or "").strip()
    if not sid or len(sid) > 64 or db is None:
        return out
    try:
        sess = await db.browser_profile_sessions.find_one({
            "id": sid,
            "status": {"$in": ["running", "launching", "queued"]},
        })
        if not sess:
            return out
        pid = str(sess.get("profile_id") or "").strip()
        if not pid:
            return out
        prof = await db.browser_profiles.find_one({"id": pid})
        if not prof:
            return out
        ref = prof.get("referrer") or {}
        if not ref.get("enabled"):
            return out
        if ref.get("pass_to_offer") is False:
            return out
        out["ok"] = True
        out["session_id"] = sid
        out["profile_id"] = pid
        out["platform"] = str(ref.get("preset_platform") or "").strip().lower()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"validate_profile_perfect_session skipped: {exc}")
    return out


async def _mirror_profile_session(uid: str, profile_id: str, session_id: str, body: dict) -> None:
    """Shared local/cloud session-update mirror for profile cards."""
    sid = str(body.get("session_id") or session_id)
    status = str(body.get("status") or "")
    if not status:
        return
    await _DB.browser_profile_sessions.update_one(
        {"id": sid},
        {"$set": {
            "status": status,
            "fingerprint_hash": body.get("fingerprint_hash", ""),
            "error_message": str(body.get("error_message") or "")[:512],
            "updated_at": _now_iso(),
        }},
    )
    prof_update: Dict[str, Any] = {}
    if status == "running":
        prof_update = {"status": "running", "session_id": sid, "last_error": ""}
    elif status == "queued":
        # Distinct from "launching" so UI can show tray-wait vs Chromium starting.
        prof_update = {"status": "queued", "session_id": sid}
    elif status == "stopping":
        prof_update = {"status": "stopping", "session_id": sid}
    elif status in ("stopped", "closed", "error"):
        prof_update = {
            "status": "idle" if status in ("stopped", "closed") else "error",
            "session_id": "",
            "cdp_ws": "",
            "debugger_address": "",
        }
        if status == "error" and body.get("error_message"):
            prof_update["last_error"] = str(body.get("error_message"))[:512]
    elif status == "launching":
        prof_update = {"status": "launching", "session_id": sid}
    # v2.7.17 — persist CDP so Synchronizer / Local API can attach
    if body.get("cdp_ws"):
        prof_update["cdp_ws"] = str(body.get("cdp_ws"))[:512]
    if body.get("debugger_address"):
        prof_update["debugger_address"] = str(body.get("debugger_address"))[:128]
    if body.get("browser_kernel"):
        prof_update["browser_kernel"] = str(body.get("browser_kernel"))[:64]
    # v2.7.79 — JSON automation progress on profile card
    for _ak in (
        "automation_status",
        "automation_step",
        "automation_total_steps",
        "automation_action",
        "automation_error",
        "launch_warnings",
        "mobile_shell_active",
        "mobile_shell_embedded",
        "engine_used",
        "last_proxy_check",
        "exit_ip",
    ):
        if _ak in body:
            prof_update[_ak] = body[_ak]
    # One-shot migrate: persist Strict proxy when launch reported the patch
    _ad_patch = body.get("anti_detect_patch")
    if isinstance(_ad_patch, dict) and _ad_patch:
        try:
            doc0 = await _DB.browser_profiles.find_one({"id": profile_id}, {"_id": 0, "anti_detect": 1})
            cur_anti = dict((doc0 or {}).get("anti_detect") or {})
            cur_anti.update({k: v for k, v in _ad_patch.items() if k})
            prof_update["anti_detect"] = cur_anti
        except Exception:
            pass
    if status in ("stopped", "closed", "error"):
        prof_update.setdefault("launch_warnings", [])
        prof_update["mobile_shell_active"] = False
        prof_update["mobile_shell_embedded"] = False
    if prof_update:
        await _DB.browser_profiles.update_one(
            {"id": profile_id},
            {"$set": prof_update},
        )


# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────
class ProxyConfig(BaseModel):
    enabled: bool = False
    server: str = ""            # http://host:port or socks5://host:port
    username: str = ""
    password: str = ""
    # http | https | socks5 | socks4 — used when server has no scheme
    proxy_type: str = "http"
    # Legacy flag name kept for DB compat — means "auto line from selected
    # Proxy Provider" (any provider the user added in Settings), NOT
    # ProxyJet-only.
    use_proxyjet: bool = False
    proxyjet_country: str = "US"
    proxyjet_state: str = ""
    # Multi-provider: resolves a live line from Settings → Proxy Providers.
    # Empty ⇒ manual server/username/password fields apply.
    provider_id: str = ""
    # Provider smart mode: no pre-bound line at create; fresh session each launch
    smart_session: bool = False


class AntiDetectConfig(BaseModel):
    """Single master switch + same flags as RUT (auto-tuned)."""
    master: bool = True             # ⭐ master toggle (default ON for new profiles)
    tls_prewarm: bool = True
    behavioral_bio: bool = True
    ip_warmup: bool = False         # Heavy — opt in
    browser_variant: str = "rotate" # auto/rotate/chromium/brave/headless-shell
    identity_persist: bool = True   # Carry cookies+localStorage across launches
    paranoia_mode: bool = False     # Maximum anti-detect (slower)
    # v2.7.15 — WIN antidetect bundle (defaults = current strong stealth)
    canvas_mode: str = "noise"      # off | noise | real
    webgl_mode: str = "noise"       # off | noise | real
    audio_mode: str = "noise"       # off | noise | real
    font_mode: str = "noise"        # off | noise | real
    webrtc_mode: str = "proxy"      # disabled | proxy | real
    # Full Chromium user-data dir (AdsPower-class persistence). Default ON
    # for new profiles so logins/extensions survive better than storage_state alone.
    use_persistent_context: bool = True
    proxy_check_on_launch: bool = True
    # Strict proxy: never open the browser without a live proxy when proxy is
    # enabled (blocks DNS soft-launch / "open without proxy" real-IP leak).
    proxy_check_block_on_fail: bool = True
    # Abort launch if mobile device shell cannot frame the browser.
    # Default ON for new configs — mobile profiles must not soft-open as
    # plain Chromium/WebKit. Explicit False still allowed for power users.
    strict_mobile_shell: bool = True
    # Opt-in Local API CDP (--remote-debugging-port). Default OFF — was a
    # detection surface when always-on for native/local.
    local_api_cdp: bool = False
    # Prefer IPv4 (avoid dual-stack / WebRTC IPv6 leaks with proxies).
    disable_ipv6: bool = True
    # full | minimal | safari — safari auto for WebKit; minimal skips FP WIN layer
    stealth_profile: str = "full"
    # v2.7.16 — Octo-class: auto prefers CloakBrowser C++ Chromium
    browser_kernel: str = "auto"  # auto|cloak|patchright|playwright|firefox|chrome
    # v2.7.20 — CreepJS-class Fingerprint WIN pack (default ON)
    fingerprint_win: bool = True
    # When True + Stealth kernel: prefer real modes (less JS noise)
    fingerprint_win_prefer_real: bool = True
    # v2.7.77 — Optional Chromium extensions (unpacked dir)
    allow_extensions: bool = False
    extensions_dir: str = Field(default="", max_length=512)


class ReferrerProConfig(BaseModel):
    """Per-profile Referrer Pro config — RUT-grade referrer engine applied
    on every navigation in every tab while the profile session is open."""
    enabled: bool = False
    pro_mode: bool = True
    # Legacy / basic modes (same vocabulary as RUT referer override)
    mode: str = "auto"  # auto | platform_pool | custom | random_list | google_search | direct
    value: str = ""  # custom URL, URL list, or google keywords (mode-dependent)
    preset_platform: str = ""
    platform_weights: Dict[str, float] = Field(default_factory=dict)
    email_weights: Dict[str, float] = Field(default_factory=dict)
    social_wrapper: bool = True
    inapp_deep_path: bool = True
    strip_search_path: bool = True
    network_click_chain: bool = False
    search_engine: str = "google"
    search_keywords: str = ""
    brand: str = ""
    country: str = ""  # ISO override for geo-localized SERP referers
    wrapper_redirect: bool = False
    lang_match: bool = True
    device_mode: str = "auto"  # auto | match_platform | mobile_only | desktop_only
    tod_enabled: bool = False
    campaign_type: str = "auto"
    quality_tier: str = "standard"  # premium | standard | aggressive
    traffic_type: str = "auto"  # auto | paid | organic | mixed
    match_ua_to_platform: bool = True
    sticky_session: bool = True  # one resolved referer for whole launch session
    # RUT pass_to_offer parity — inject platform Referer on offer docs; skip wrapper hops.
    pass_to_offer: bool = True
    allow_risky_wrapper: bool = False
    custom_utm_enabled: bool = False
    custom_utm_source: str = ""
    custom_utm_medium: str = ""
    custom_utm_campaign: str = ""
    custom_utm_content: str = ""
    custom_utm_term: str = ""
    custom_click_id: str = Field(default="", max_length=256)


class ProfileBody(BaseModel):
    # 2026-01: `name` is now OPTIONAL. Empty/whitespace → a unique
    # short auto-name is generated server-side so the customer can
    # bulk-create profiles without thinking up names. Existing API
    # callers that send a name keep working unchanged.
    name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)
    country: str = Field(default="us", max_length=8)
    language: str = Field(default="en-US", max_length=24)
    timezone: str = Field(default="America/New_York", max_length=64)
    device_type: str = Field(default="desktop")  # desktop | mobile
    os: str = Field(default="windows")
    user_agent: str = Field(default="", max_length=600)
    viewport: Dict[str, int] = Field(default_factory=lambda: {"width": 1920, "height": 1080})
    is_mobile: bool = False
    has_touch: bool = False
    device_scale_factor: float = 1.0
    locale: str = "en-US"
    accept_language: str = "en-US,en;q=0.9"
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    anti_detect: AntiDetectConfig = Field(default_factory=AntiDetectConfig)
    referrer: ReferrerProConfig = Field(default_factory=ReferrerProConfig)
    tags: List[str] = Field(default_factory=list)
    start_url: str = Field(default="https://www.google.com/", max_length=512)
    # v2.7.13 — folders / geo / quick links (AdsPower-style agency UX)
    folder: str = Field(default="", max_length=80)
    geo_follow_proxy: bool = True
    quick_links: List[str] = Field(default_factory=list)


class BulkCreateBody(BaseModel):
    count: int = Field(..., ge=1, le=200)
    name_prefix: str = Field(default="Profile", max_length=64)
    base: ProfileBody
    randomize_ua: bool = True
    randomize_viewport: bool = True
    auto_unique_proxy: bool = True


# ── 2026-01: Advanced create — full UA + ProxyJet integration ─────────
# Powers the new "New Browser Profile" form which exposes the SAME
# controls as `/ua-generator` and the ProxyJet "Generate proxies on-
# demand" panel. Single endpoint handles both single-profile and
# bulk-create (count >= 1).
class AdvUACfg(BaseModel):
    """Subset of /api/user-agents/generate options surfaced in the
    Browser Profile form. Fully optional — unset → random."""
    app: str = "browser"                       # instagram, facebook, tiktok, ... browser
    platform: str = "any"                      # any, android, ios, desktop
    brand: Optional[str] = None
    device_id: Optional[str] = None
    app_version: Optional[str] = None
    os_version: Optional[str] = None
    region: Optional[str] = None
    resolution: Optional[str] = None
    # Mix-mode pools (UA generator picks one at random per profile)
    apps: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    device_ids: Optional[List[str]] = None
    app_versions: Optional[List[str]] = None
    os_versions: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    resolutions: Optional[List[str]] = None


class AdvProxyCfg(BaseModel):
    """How to attach proxies to the new profile(s).

    `mode`:
        "none"     → no proxy attached
        "manual"   → use the literal `server`/`username`/`password`
                     OR `lines` (one unique proxy per profile)
        "proxyjet" → call ProxyJet generator and assign each profile a
                     UNIQUE exit-IP from the result. Count = number of
                     profiles being created.
        "provider" → resolve the proxy from a user-configured provider
                     (see /api/proxy-providers). Falls through to legacy
                     if the provider fails / is disabled.
    """
    mode: str = "none"
    # Manual proxy
    server: str = ""
    username: str = ""
    password: str = ""
    # v2.7.13 — multiline paste: one proxy line per profile (unique IPs)
    lines: Optional[List[str]] = None
    # ProxyJet on-demand
    country: Optional[str] = None
    state: Optional[str] = None
    countries: Optional[List[str]] = None
    states: Optional[List[str]] = None
    # 0 / None = rotating (fresh per request); 1..120 = sticky N min
    sticky_minutes: Optional[int] = None
    # v2.4.0 — Multi-provider proxy (see settings › Proxy Providers)
    provider_id: Optional[str] = None
    # When mode=provider: bind provider_id only — fresh line + IP at each launch (no bulk pre-gen)
    smart_session: bool = True


class AdvancedCreateBody(BaseModel):
    """Single or bulk profile create with full UA + Proxy generator
    integration. Frontend's "New Browser Profile" form posts here."""
    count: int = Field(default=1, ge=1, le=200)
    name_prefix: str = Field(default="", max_length=64)
    # Basic identity (applied to every created profile)
    country: str = "us"
    device_type: str = "desktop"
    start_url: str = "https://www.google.com/"
    notes: str = ""
    viewport_width: int = 0   # 0 → device-default
    viewport_height: int = 0  # 0 → device-default
    anti_detect_on: bool = True
    # v2.7.15 — optional full anti_detect overrides (merged over anti_detect_on defaults)
    anti_detect: Optional[AntiDetectConfig] = None
    # v2.7.12 — Platform mix (%). Sum normalized; all-zero → legacy device_type.
    mix_ios_pct: float = Field(default=0, ge=0, le=100)
    mix_android_pct: float = Field(default=0, ge=0, le=100)
    mix_desktop_pct: float = Field(default=0, ge=0, le=100)
    # Device picker: random | specific
    device_mode: str = "random"
    device_id: str = ""
    # Resolution: match_device | random | exact
    resolution_mode: str = "match_device"
    # v2.7.13 — agency fields on create
    tags: List[str] = Field(default_factory=list)
    folder: str = Field(default="", max_length=80)
    timezone: str = Field(default="", max_length=64)
    locale: str = Field(default="", max_length=24)
    geo_follow_proxy: bool = True
    referrer: ReferrerProConfig = Field(default_factory=ReferrerProConfig)
    quick_links: List[str] = Field(default_factory=list)
    # Sub-configs
    ua: AdvUACfg = Field(default_factory=AdvUACfg)
    proxy: AdvProxyCfg = Field(default_factory=AdvProxyCfg)


class CookieImportBody(BaseModel):
    """Accept Playwright storage_state, cookie list, or Netscape text."""
    storage_state: Optional[Dict[str, Any]] = None
    cookies: Optional[List[Dict[str, Any]]] = None
    netscape: Optional[str] = None
    merge: bool = False  # False = replace cookies (origins kept unless clear_origins)


class CookieRobotBody(BaseModel):
    """Warm profile cookies via short stealth visits (local/native only)."""
    urls: Optional[List[str]] = None
    max_urls: int = Field(default=5, ge=1, le=10)


class ImportProfilesBody(BaseModel):
    profiles: List[Dict[str, Any]] = Field(default_factory=list)
    include_cookies: bool = False


class BulkMoveBody(BaseModel):
    profile_ids: List[str] = Field(default_factory=list)
    folder: str = Field(default="", max_length=80)


class ShareProfileBody(BaseModel):
    """Light team share: clone profile into another Krexion account by email."""
    target_email: str = Field(..., min_length=3, max_length=200)
    include_cookies: bool = False


class AclGrantBody(BaseModel):
    """Live team ACL (viewer | editor | admin) — does not clone the profile."""
    target_email: str = Field(..., min_length=3, max_length=200)
    role: str = Field(default="editor", max_length=16)  # viewer|editor|admin


class AclRevokeBody(BaseModel):
    target_email: str = Field(default="", max_length=200)
    user_id: str = Field(default="", max_length=80)


class SyncStartBody(BaseModel):
    master_id: str = Field(..., min_length=8, max_length=80)
    slave_ids: List[str] = Field(default_factory=list)
    modes: List[str] = Field(default_factory=lambda: ["navigate", "click", "type", "scroll"])
    jitter: bool = True


class CloudPhoneBindBody(BaseModel):
    provider: str = Field(default="partner", max_length=32)  # partner|cpi|none
    partner_url: str = Field(default="", max_length=512)
    external_id: str = Field(default="", max_length=120)
    device_id: str = Field(default="", max_length=80)  # CPI device mongo id
    label: str = Field(default="", max_length=120)


class OpenOnDeviceBody(BaseModel):
    device_id: str = Field(default="", max_length=80)  # empty = auto-pick online Android
    url: str = Field(default="", max_length=1024)
    auto_fallback: bool = True


class CloneOptsBody(BaseModel):
    include_cookies: bool = False
    fresh_proxy: bool = True
    fresh_ua: bool = False


class UpdateProfileTemplateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    settings: Optional[Dict[str, Any]] = None


class BulkIdsBody(BaseModel):
    profile_ids: List[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1, le=20)
    permanent: bool = False


class ProfileAutomationLaunch(BaseModel):
    """Optional JSON automation — only runs when enabled=True."""
    enabled: bool = False
    automation_upload_id: str = Field(default="", max_length=64)
    data_file_id: str = Field(default="", max_length=64)
    lead_row_index: int = Field(default=0, ge=-1, le=100000)
    skip_missing_steps: bool = True
    self_heal: bool = False
    after_mode: str = Field(default="manual", max_length=32)  # manual | close | next_lead
    consume_mode: str = Field(default="on_submit", max_length=32)  # on_submit | on_start
    claim_next: bool = False  # True = atomic next free row (bulk sets this ON)
    save_as_default: bool = False
    proxy_upload_id: str = Field(default="", max_length=64)  # Uploaded Things proxy batch (RUT parity)
    ua_upload_id: str = Field(default="", max_length=64)
    smart_funnel_enabled: bool = False
    smart_funnel_pattern: str = Field(default="auto", max_length=64)
    smart_funnel_min_deals: int = Field(default=2, ge=1, le=5)
    smart_funnel_wait_until_conversion: bool = True


class LaunchBody(BaseModel):
    start_url: Optional[str] = Field(default=None, max_length=512)
    automation: Optional[ProfileAutomationLaunch] = None
    recheck_proxy: bool = False


class BulkLaunchBody(BaseModel):
    profile_ids: List[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1, le=20)
    start_url: Optional[str] = Field(default=None, max_length=512)
    automation: Optional[ProfileAutomationLaunch] = None


class RunAutomationBody(BaseModel):
    automation_upload_id: str = Field(default="", max_length=64)
    data_file_id: str = Field(default="", max_length=64)
    lead_row_index: int = Field(default=0, ge=0, le=100000)
    skip_missing_steps: bool = True
    self_heal: bool = False
    after_mode: str = Field(default="manual", max_length=32)
    consume_mode: str = Field(default="on_submit", max_length=32)
    claim_next: bool = True
    proxy_upload_id: str = Field(default="", max_length=64)
    ua_upload_id: str = Field(default="", max_length=64)
    smart_funnel_enabled: bool = False
    smart_funnel_pattern: str = Field(default="auto", max_length=64)
    smart_funnel_min_deals: int = Field(default=2, ge=1, le=5)
    smart_funnel_wait_until_conversion: bool = True


class BulkRunJsonBody(BaseModel):
    profile_ids: List[str] = Field(default_factory=list)
    automation_upload_id: str = Field(default="", max_length=64)
    data_file_id: str = Field(default="", max_length=64)
    max_concurrent: int = Field(default=5, ge=1, le=20)
    skip_missing_steps: bool = True
    self_heal: bool = False
    after_mode: str = Field(default="manual", max_length=32)
    consume_mode: str = Field(default="on_submit", max_length=32)
    claim_next: bool = True
    proxy_upload_id: str = Field(default="", max_length=64)
    ua_upload_id: str = Field(default="", max_length=64)
    smart_funnel_enabled: bool = False
    smart_funnel_pattern: str = Field(default="auto", max_length=64)
    smart_funnel_min_deals: int = Field(default=2, ge=1, le=5)
    smart_funnel_wait_until_conversion: bool = True


class ValidateAutomationBody(BaseModel):
    automation_upload_id: str = Field(default="", max_length=64)
    data_file_id: str = Field(default="", max_length=64)


class SaveAutomationDefaultsBody(BaseModel):
    automation_upload_id: str = Field(default="", max_length=64)
    data_file_id: str = Field(default="", max_length=64)


class SaveProfileTemplateBody(BaseModel):
    """Save current create-form settings as a reusable profile template."""
    name: str = Field(..., min_length=1, max_length=80)
    settings: Dict[str, Any] = Field(default_factory=dict)


_ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


def _normalize_role(role: str) -> str:
    r = (role or "viewer").strip().lower()
    return r if r in ("viewer", "editor", "admin") else "viewer"


def _acl_entries(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = doc.get("acl") or []
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        out.append({
            "user_id": str(e.get("user_id") or ""),
            "email": str(e.get("email") or "").lower()[:200],
            "role": _normalize_role(str(e.get("role") or "viewer")),
            "added_at": str(e.get("added_at") or ""),
        })
    return out


def _role_for_user(doc: Dict[str, Any], uid: str) -> str:
    if str(doc.get("user_id") or "") == str(uid):
        return "owner"
    for e in _acl_entries(doc):
        if e.get("user_id") == str(uid):
            return e.get("role") or "viewer"
    return ""


def _has_min_role(doc: Dict[str, Any], uid: str, min_role: str) -> bool:
    got = _role_for_user(doc, uid)
    if not got:
        return False
    return _ROLE_RANK.get(got, 0) >= _ROLE_RANK.get(min_role, 99)


def _owned_or_shared_filter(uid: str) -> Dict[str, Any]:
    return {
        "$or": [
            {"user_id": uid},
            {"acl.user_id": uid},
        ]
    }


async def _get_profile_for_user(
    profile_id: str,
    uid: str,
    *,
    min_role: str = "viewer",
) -> Dict[str, Any]:
    doc = await _DB.browser_profiles.find_one({
        "id": profile_id,
        "$and": [
            {"$or": [{"user_id": uid}, {"acl.user_id": uid}]},
            _not_deleted_filter(),
        ],
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not _has_min_role(doc, uid, min_role):
        raise HTTPException(status_code=403, detail=f"Requires {min_role} access")
    return doc


def _adv_anti_detect_cfg(body: AdvancedCreateBody) -> AntiDetectConfig:
    """Build AntiDetectConfig for advanced_create — tls_prewarm True when on."""
    on = bool(body.anti_detect_on)
    if body.anti_detect is not None:
        raw = body.anti_detect.dict() if hasattr(body.anti_detect, "dict") else dict(body.anti_detect or {})
        raw["master"] = on
        fields = getattr(AntiDetectConfig, "model_fields", None) or getattr(AntiDetectConfig, "__fields__", {})
        return AntiDetectConfig(**{k: v for k, v in raw.items() if k in fields})
    return AntiDetectConfig(
        master=on,
        tls_prewarm=on,
        behavioral_bio=on,
        browser_variant="rotate" if on else "auto",
        identity_persist=on,
    )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 2026-01: Unique auto-name generator ────────────────────────────────
# Customers asked: "naam likhna zrori na ho — har profile unique name
# se khud ban jay". We mint a short readable + collision-resistant
# label using device-type + country + date + 4 random alnum chars.
# Examples:
#   Krexion-Desktop-US-0620-A7K3
#   Krexion-Mobile-PK-0620-X92R
def _auto_name(country: str = "us", device_type: str = "desktop") -> str:
    """Generate a unique, human-readable profile name. Cheap + lock-free."""
    cc = (country or "us").upper()[:3]
    dt = "Mobile" if (device_type or "").lower() == "mobile" else "Desktop"
    ts = datetime.now().strftime("%m%d")
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"Krexion-{dt}-{cc}-{ts}-{suffix}"


def _profile_doc(user_id: str, body: ProfileBody) -> Dict[str, Any]:
    """Convert ProfileBody → MongoDB document with metadata."""
    # Auto-fill UA + viewport if blank
    is_mobile = bool(body.is_mobile or body.device_type == "mobile")
    has_touch = bool(body.has_touch or is_mobile)
    ua = body.user_agent.strip() or _gen_random_ua(is_mobile)
    # v2.7.9 — Dual-engine honesty: keep iOS UAs as requested (launch picks
    # WebKit or Android fallback); Chromium path for non-iOS.
    ua, _meta = _normalize_profile_ua_honesty(ua)
    requested_os = (body.os or "").strip().lower()
    os_val = _infer_os_from_ua(
        ua,
        is_mobile=is_mobile,
        fallback=requested_os or ("android" if is_mobile else "windows"),
    )
    if _meta.get("os") in ("android", "ios"):
        os_val = _meta["os"]
    if os_val == "android" and requested_os == "ios":
        os_val = "android"
        is_mobile = True
        has_touch = True
    if os_val in ("android", "ios"):
        is_mobile = True
        has_touch = True
    viewport = body.viewport if body.viewport.get("width") else _gen_random_viewport(is_mobile)
    pid = str(uuid.uuid4())
    # 2026-01 — auto-generate unique name if blank
    name = (body.name or "").strip() or _auto_name(body.country, body.device_type)
    doc = {
        "id": pid,
        "user_id": user_id,
        "name": name,
        "notes": body.notes,
        "country": body.country.lower(),
        "language": body.language,
        "timezone": body.timezone,
        "device_type": body.device_type if not is_mobile else (body.device_type or "mobile"),
        "os": os_val,
        "user_agent": ua,
        "viewport": viewport,
        "is_mobile": is_mobile,
        "has_touch": has_touch,
        "device_scale_factor": float(body.device_scale_factor or (3.0 if is_mobile else 1.0)),
        "locale": body.locale,
        "accept_language": body.accept_language,
        "proxy": body.proxy.dict() if hasattr(body.proxy, "dict") else dict(body.proxy or {}),
        "anti_detect": body.anti_detect.dict() if hasattr(body.anti_detect, "dict") else dict(body.anti_detect or {}),
        "referrer": body.referrer.dict() if hasattr(body.referrer, "dict") else dict(body.referrer or {}),
        "tags": [str(t).strip()[:40] for t in (body.tags or []) if str(t).strip()][:20],
        "start_url": body.start_url,
        "folder": (body.folder or "").strip()[:80],
        "geo_follow_proxy": bool(body.geo_follow_proxy),
        "quick_links": [
            str(u).strip()[:512]
            for u in (body.quick_links or [])
            if str(u).strip()
        ][:12],
        "storage_state": {},   # cookies + localStorage persisted by desktop client
        "fingerprint_hash": "",  # set by desktop client on first launch
        "session_id": "",        # active session_id when launched
        "status": "idle",        # idle | launching | running | stopped | error
        "last_launched_at": "",
        "last_session_duration_sec": 0,
        "total_launches": 0,
        "storage_synced_at": "",
        "last_proxy_check": {},
        "exit_ip": "",
        "last_tls_prewarm_ok": None,
        "cdp_ws": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    # Mobile: Strict phone chrome ON unless user explicitly turned it off
    _anti = doc.get("anti_detect") if isinstance(doc.get("anti_detect"), dict) else {}
    if is_mobile and "strict_mobile_shell" not in _anti:
        _anti = dict(_anti)
        _anti["strict_mobile_shell"] = True
        doc["anti_detect"] = _anti
    return doc


def _not_deleted_filter() -> Dict[str, Any]:
    return {
        "$or": [
            {"deleted_at": {"$exists": False}},
            {"deleted_at": None},
            {"deleted_at": ""},
        ]
    }


def _public_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal-only fields for API responses."""
    d = dict(doc or {})
    d.pop("_id", None)
    # storage_state can be large — return only stats
    ss = d.get("storage_state") or {}
    d["storage_state_stats"] = {
        "has_cookies": bool(ss.get("cookies")),
        "cookie_count": len(ss.get("cookies") or []),
        "origin_count": len(ss.get("origins") or []),
        "synced_at": d.get("storage_synced_at") or "",
    }
    try:
        from browser_profile_health import compute_profile_health, format_last_used

        _hd = dict(d)
        _hd["storage_state"] = ss
        d["health"] = compute_profile_health(_hd)
        d["last_used_label"] = format_last_used(str(d.get("last_launched_at") or ""))
    except Exception:
        d["health"] = {"level": "unknown", "score": 0, "issues": []}
        d["last_used_label"] = ""
    d.pop("storage_state", None)
    # Never expose proxy passwords / raw lines to list/get/ACL clients
    if isinstance(d.get("proxy"), dict):
        d["proxy"] = _sanitize_proxy_for_public(d.get("proxy"))
    d["folder"] = (d.get("folder") or "").strip()
    d["geo_follow_proxy"] = bool(d.get("geo_follow_proxy", True))
    d["quick_links"] = d.get("quick_links") or []
    fh = str(d.get("fingerprint_hash") or "")
    d["fingerprint_short"] = fh[:12] if fh else ""
    d["last_proxy_check"] = d.get("last_proxy_check") or {}
    d["exit_ip"] = str(d.get("exit_ip") or (d.get("proxy") or {}).get("exit_ip") or "").strip()
    # Hint: strict when proxy enabled (default ON for unset / old profiles)
    d["strict_proxy"] = _strict_proxy_mode(doc if isinstance(doc, dict) else d)
    _anti = d.get("anti_detect") if isinstance(d.get("anti_detect"), dict) else {}
    d["strict_mobile_shell"] = bool((_anti or {}).get("strict_mobile_shell", True)) if bool(d.get("is_mobile")) else bool((_anti or {}).get("strict_mobile_shell"))
    # Effective: mobile + unset → strict ON
    if bool(d.get("is_mobile")) and "strict_mobile_shell" not in (_anti or {}):
        d["strict_mobile_shell"] = True
    d["mobile_shell_embedded"] = bool(d.get("mobile_shell_embedded"))
    # Proxy check age for UI badge
    _lpc = d.get("last_proxy_check") if isinstance(d.get("last_proxy_check"), dict) else {}
    _checked_at = str(
        _lpc.get("checked_at") or _lpc.get("at") or _lpc.get("ts") or _lpc.get("timestamp") or ""
    ).strip()
    d["proxy_check_age_hours"] = None
    d["proxy_check_stale"] = False
    if _checked_at:
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(_checked_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
            d["proxy_check_age_hours"] = round(age_h, 2)
            d["proxy_check_stale"] = age_h > 24.0
        except Exception:
            pass
    if "last_tls_prewarm_ok" not in d:
        d["last_tls_prewarm_ok"] = None
    # CDP endpoint only for local automation clients (still useful in UI copy)
    if not d.get("cdp_ws"):
        d.pop("cdp_ws", None)
    d["acl"] = _acl_entries(d)
    d["cloud_phone"] = d.get("cloud_phone") if isinstance(d.get("cloud_phone"), dict) else {}
    d["browser_kernel_label"] = str(d.get("browser_kernel") or "")
    d["default_automation_upload_id"] = str(d.get("default_automation_upload_id") or "")
    d["default_data_file_id"] = str(d.get("default_data_file_id") or "")
    d["automation_status"] = str(d.get("automation_status") or "")
    d["automation_step"] = int(d.get("automation_step") or 0)
    d["automation_total_steps"] = int(d.get("automation_total_steps") or 0)
    _lw = d.get("launch_warnings")
    d["launch_warnings"] = list(_lw) if isinstance(_lw, list) else []
    d["mobile_shell_active"] = bool(d.get("mobile_shell_active"))
    d["engine_used"] = str(d.get("engine_used") or "")
    return d


def _public_view_for(doc: Dict[str, Any], uid: str) -> Dict[str, Any]:
    d = _public_view(doc)
    d["my_role"] = _role_for_user(doc, uid) or "viewer"
    d["is_shared"] = str(doc.get("user_id") or "") != str(uid)
    return d


def _enforce_local_api_key(request: Request) -> None:
    """When KREXION_LOCAL_API_KEY is set, require matching header/Bearer (JWT still required)."""
    key = (os.environ.get("KREXION_LOCAL_API_KEY") or "").strip()
    if not key:
        return
    hdr = (request.headers.get("X-Krexion-Local-Key") or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if hdr != key and bearer != key:
        raise HTTPException(status_code=401, detail="Invalid or missing local API key")


def _parse_netscape_cookies(text: str) -> List[Dict[str, Any]]:
    """Parse Netscape / curl cookie file into Playwright cookie dicts."""
    out: List[Dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Netscape files mark HttpOnly cookies with a "#HttpOnly_" domain
        # prefix. Previously these lines were dropped as comments, losing
        # every HttpOnly (session/login) cookie. Preserve them.
        _http_only = False
        if line.startswith("#HttpOnly_"):
            _http_only = True
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            parts = line.split()
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expires, name, value = parts[:7]
        try:
            exp = int(float(expires))
        except Exception:
            exp = -1
        # Classic Netscape has no SameSite column — do NOT invent "Lax"
        # (forces logout on sites that issued Strict/None). Playwright
        # applies its own default when sameSite is omitted.
        ck: Dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain.lstrip("."),
            "path": path or "/",
            "secure": str(secure).upper() in ("TRUE", "1", "YES"),
            "httpOnly": _http_only,
        }
        if exp > 0:
            ck["expires"] = exp
        out.append(ck)
    return out


def _normalize_same_site(raw: Any) -> Optional[str]:
    """Preserve Strict / Lax / None; never invent a default."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    key = s.lower().replace("_", "")
    if key in ("strict",):
        return "Strict"
    if key in ("lax",):
        return "Lax"
    if key in ("none", "no_restriction", "norestriction"):
        return "None"
    # Already canonical?
    if s in ("Strict", "Lax", "None"):
        return s
    return None


def _normalize_cookie_list(cookies: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        item = {
            "name": name,
            "value": str(c.get("value") if c.get("value") is not None else ""),
            "domain": str(c.get("domain") or "").lstrip(".") or "localhost",
            "path": str(c.get("path") or "/"),
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly") or c.get("http_only") or False),
        }
        if c.get("expires") is not None:
            try:
                item["expires"] = float(c["expires"])
            except Exception:
                pass
        ss = _normalize_same_site(
            c.get("sameSite") if c.get("sameSite") is not None else c.get("same_site")
        )
        if ss:
            item["sameSite"] = ss
        out.append(item)
    return out


def _is_valid_exit_ip(ip: str) -> bool:
    """Accept IPv4/IPv6 exit IPs (legacy check rejected IPv6 because of ':')."""
    s = (ip or "").strip()
    if not s:
        return False
    try:
        import ipaddress

        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _format_profile_proxy_probe_failure(
    doc: Dict[str, Any],
    proxy: Dict[str, Any],
    probe: Optional[Dict[str, Any]] = None,
) -> str:
    name = str(doc.get("name") or doc.get("id") or "profile")[:64]
    err = str((probe or {}).get("error") or "").strip()
    if not str(proxy.get("password") or "").strip() and proxy.get("provider_id"):
        return (
            f"Profile '{name}': proxy configured but exit IP probe failed. "
            "Provider gateway password missing — open Proxies → edit provider → save password."
        )
    detail = f"Profile '{name}': proxy configured but exit IP probe failed"
    if err:
        detail += f" ({err[:160]})"
    return detail


def _is_rotating_gateway_proxy(proxy_cfg: Dict[str, Any]) -> bool:
    """True for manual pasted lines on DataImpulse / Smartproxy / etc."""
    cfg = hydrate_proxy_credentials(dict(proxy_cfg or {}))
    server = str(cfg.get("server") or "").strip()
    username = str(cfg.get("username") or "").strip()
    host = _proxy_host_from_server(server)
    if not host:
        for key in ("raw_line", "raw"):
            raw = str(cfg.get(key) or "").strip()
            if not raw:
                continue
            parsed = _parse_proxy_line(raw)
            host = _proxy_host_from_server(str(parsed.get("server") or ""))
            username = username or str(parsed.get("username") or "").strip()
            if host:
                break
    if not host:
        return False
    try:
        from real_user_traffic import _detect_rotating_gateway

        return bool(_detect_rotating_gateway(host, username))
    except Exception:
        host_l = host.lower()
        return any(
            dom in host_l
            for dom in ("dataimpulse.com", "smartproxy.com", "oxylabs.io", "brightdata.com")
        )


def _rotate_manual_proxy_session(proxy_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Inject a fresh gateway session so the next probe gets a new exit IP.

    v2.7.113 — Never force_replace geo DSL. DataImpulse usernames like
    `login__cr.us;state.alabama` must keep country/state; only sessid rotates.
    Older force_replace path stripped geo → `__sessid.N` and broke targeting.
    """
    out = hydrate_proxy_credentials(dict(proxy_cfg or {}))
    username = str(out.get("username") or "").strip()
    if not username:
        return out
    host = _proxy_host_from_server(str(out.get("server") or ""))
    try:
        import re as _re

        from proxy_provider_module import (
            _make_session_id,
            _rotate_session_in_username,
        )

        new_user = _rotate_session_in_username(username)
        if new_user == username and _is_rotating_gateway_proxy(out):
            sid = _make_session_id()
            # Drop prior sessid tokens only — keep __cr / state / city DSL intact.
            stripped = _re.sub(
                r"(?:;|__)(?:sessid|sessionid)\.[A-Za-z0-9_{}]+",
                "",
                username,
                flags=_re.I,
            )
            stripped = _re.sub(
                r"-(?:session(?:id)?|sessid|sess)-[A-Za-z0-9]+",
                "",
                stripped,
                flags=_re.I,
            ).rstrip(";-_")
            if (
                ";" in stripped
                or "__cr." in stripped.lower()
                or "__" in stripped
            ):
                new_user = f"{stripped};sessid.{sid}"
            elif "-session-" in username.lower() or "_session-" in username.lower():
                new_user = _rotate_session_in_username(f"{stripped}-session-{sid}")
            else:
                new_user = f"{stripped};sessid.{sid}"
        if new_user != username:
            out["username"] = new_user
            raw = _canonical_proxy_raw_line(out)
            if raw:
                out["raw_line"] = raw
            logger.info(
                "[browser-profile launch] rotated manual gateway session "
                f"host={host[:32]} user={username[:24]}→{new_user[:32]}"
            )
    except Exception as exc:
        logger.debug(f"[browser-profile] manual session rotate skipped: {exc}")
    return out


def _strict_proxy_mode(doc_or_anti: Optional[Dict[str, Any]]) -> bool:
    """True when profile must never soft-open without a working proxy.

    Reads anti_detect.proxy_check_block_on_fail (UI: Strict proxy) or
    anti_detect.strict_proxy alias.

    Default: ON when proxy is enabled and the flag was never saved
    (closes real-IP soft-launch leak on old profiles). Explicit False
    still allows soft-launch for power users who opt out.
    """
    if not isinstance(doc_or_anti, dict):
        return False
    anti = doc_or_anti.get("anti_detect") if "anti_detect" in doc_or_anti else doc_or_anti
    if not isinstance(anti, dict):
        anti = {}
    if anti.get("proxy_check_block_on_fail") is True:
        return True
    if anti.get("strict_proxy") is True:
        return True
    if anti.get("proxy_check_block_on_fail") is False:
        return False
    if anti.get("strict_proxy") is False:
        return False
    # Unset flag: treat as strict when proxy is configured on the profile
    proxy = {}
    if "proxy" in doc_or_anti and isinstance(doc_or_anti.get("proxy"), dict):
        proxy = doc_or_anti.get("proxy") or {}
    if (
        proxy.get("enabled")
        or str(proxy.get("server") or "").strip()
        or str(proxy.get("provider_id") or "").strip()
        or proxy.get("use_proxyjet")
    ):
        return True
    return False


def _proxy_ready_for_soft_launch(proxy_cfg: Dict[str, Any]) -> bool:
    """Launch may proceed without pre-bound exit IP when proxy line resolved.

    Note: this still keeps the proxy on the browser — it only skips the
    pre-bound unique exit-IP gate. It does NOT mean "open on real IP".
    """
    if not str(proxy_cfg.get("server") or "").strip():
        return False
    if str(proxy_cfg.get("password") or "").strip():
        return True
    if str(proxy_cfg.get("provider_id") or "").strip():
        return True
    if proxy_cfg.get("use_proxyjet"):
        return True
    if _is_rotating_gateway_proxy(proxy_cfg):
        return True
    return bool(str(proxy_cfg.get("username") or "").strip())


def _defer_launch_proxy_probe(proxy_cfg: Dict[str, Any]) -> bool:
    """Rotating/provider proxies — pre-probe must never block browser open."""
    if str(proxy_cfg.get("provider_id") or "").strip():
        return True
    if proxy_cfg.get("smart_session"):
        return True
    if proxy_cfg.get("use_proxyjet"):
        return True
    if _is_rotating_gateway_proxy(proxy_cfg):
        return True
    return False


def _set_soft_launch_proxy_state(
    doc: Dict[str, Any],
    proxy_cfg: Dict[str, Any],
    *,
    probe: Optional[Dict[str, Any]] = None,
) -> None:
    doc.pop("exit_ip", None)
    doc["proxy"] = dict(proxy_cfg)
    doc["proxy"].pop("exit_ip", None)
    err = str((probe or {}).get("error") or "").strip()
    msg = "Exit IP pre-check failed — browser will verify proxy after launch."
    if err:
        msg += f" ({err[:100]})"
    doc["_launch_proxy_probe_warning"] = msg


def _raise_if_strict_soft_launch(doc: Dict[str, Any], *, reason: str) -> None:
    """Strict proxy profiles must not soft-continue when exit-IP / probe failed."""
    if not _strict_proxy_mode(doc):
        return
    raise HTTPException(
        status_code=502,
        detail=(
            "Strict proxy: "
            f"{reason}. Fix Settings → Proxy Providers (or manual line), then relaunch. "
            "Browser was NOT opened."
        )[:480],
    )


async def _best_effort_bind_exit_ip_at_launch(
    cred_uid: str,
    user: dict,
    doc: Dict[str, Any],
    proxy_cfg: Dict[str, Any],
    *,
    provider_id: str,
    profile_id: str,
    used_ips: Set[str],
    targeting: Optional[Dict[str, Any]],
    max_retries: int = 0,
) -> Dict[str, Any]:
    """Rotating provider/manual: probe + dedupe when possible.

    Soft-continues with proxy still attached when Strict is OFF.
    Strict ON → abort if no verified unique exit IP.
    """
    rotating_manual = _is_rotating_gateway_proxy(proxy_cfg) and not provider_id
    attempts = max_retries or (8 if (provider_id or rotating_manual) else 3)
    last_probe: Dict[str, Any] = {}
    for attempt in range(attempts):
        doc["proxy"] = dict(proxy_cfg)
        probe_doc = {
            "proxy": proxy_cfg,
            "user_id": cred_uid,
            "id": profile_id,
            "name": doc.get("name"),
        }
        probe = await _probe_profile_proxy(probe_doc, user)
        last_probe = probe
        exit_ip = str(probe.get("exit_ip") or "").strip()
        if exit_ip:
            try:
                canonical = await _assert_unique_team_profile_ip(
                    cred_uid, exit_ip, used_ips, profile_id=profile_id,
                )
                doc["exit_ip"] = canonical
                doc["proxy"]["exit_ip"] = canonical
                doc["proxy"]["sticky_session"] = True
                doc.pop("_launch_proxy_probe_warning", None)
                logger.info(
                    f"[browser-profile launch] exit_ip={canonical} "
                    f"profile={profile_id[:8]} attempt={attempt + 1} "
                    f"provider={bool(provider_id)} manual_rotating={rotating_manual}"
                )
                return await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
            except HTTPException as exc:
                if exc.status_code != 409 or attempt >= attempts - 1:
                    break
                if provider_id:
                    logger.warning(
                        f"[browser-profile launch] duplicate provider IP attempt "
                        f"{attempt + 1} — rotating session"
                    )
                elif rotating_manual:
                    logger.warning(
                        f"[browser-profile launch] duplicate manual rotating IP "
                        f"attempt {attempt + 1} — fresh gateway session"
                    )
                    proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
                    proxy_cfg = await _finalize_proxy_cfg_for_launch(
                        cred_uid, user, proxy_cfg,
                    )
                    await asyncio.sleep(0.25)
                    continue
                else:
                    break
        elif (provider_id or rotating_manual) and attempt < attempts - 1:
            logger.warning(
                f"[browser-profile launch] rotating probe miss attempt "
                f"{attempt + 1} — new session"
            )
        else:
            break
        if provider_id:
            lines = await _allocate_provider_proxy_lines(
                cred_uid, provider_id, 1, used_ips, targeting=targeting,
            )
            proxy_cfg = _apply_resolved_line_to_proxy_cfg(
                proxy_cfg, lines[0], provider_id=provider_id,
            )
            proxy_cfg = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
        elif rotating_manual:
            proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
            proxy_cfg = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
            await asyncio.sleep(0.25)
        else:
            break

    err = str(last_probe.get("error") or "").strip() or "exit IP probe failed"
    _raise_if_strict_soft_launch(
        doc,
        reason=f"could not verify a unique exit IP before launch ({err[:160]})",
    )
    if rotating_manual or provider_id:
        doc["_launch_proxy_probe_warning"] = (
            "Could not reserve a team-unique exit IP before launch — browser will "
            "open and verify proxy after connect. For rotating gateways, each new "
            "session usually assigns a fresh IP."
        )
        if err and err != "exit IP probe failed":
            doc["_launch_proxy_probe_warning"] += f" ({err[:80]})"
        doc.pop("exit_ip", None)
        doc["proxy"] = dict(proxy_cfg)
        doc["proxy"].pop("exit_ip", None)
    else:
        _set_soft_launch_proxy_state(doc, proxy_cfg, probe=last_probe)
    logger.warning(
        f"[browser-profile launch] rotating soft launch profile={profile_id[:8]} "
        f"server={str(proxy_cfg.get('server') or '')[:48]}"
    )
    return await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)


def _friendly_proxy_probe_error(raw: str, gateway_host: str = "") -> str:
    """Turn Windows DNS / malformed-gateway failures into operator hints."""
    msg = (raw or "ipify_probe_failed").strip()
    host = (gateway_host or "").strip()
    low = msg.lower()
    if "getaddrinfo" in low or "11001" in msg or "nodename" in low or "name or service not known" in low:
        if host:
            return (
                f"DNS could not resolve proxy gateway '{host}'. "
                "Open Proxies → edit provider → Gateway host must be real "
                "(e.g. gw.dataimpulse.com or ca.rrp.bestgo.work) with the correct port."
            )
        return (
            "DNS could not resolve the proxy gateway host. "
            "Open Proxies → edit provider → check Gateway host + port."
        )
    if "407" in low or "authentication failed" in low or "proxy auth" in low:
        hint = f" via '{host}'" if host else ""
        return (
            f"Proxy authentication failed{hint}. "
            "Open Proxies → edit provider → re-save username/password "
            "(and country targeting if set), then retry Create."
        )
    if "geo endpoints returned no ip" in low or "ip endpoints returned no ip" in low:
        hint = f" via '{host}'" if host else ""
        bestgo = "bestgo" in host.lower() or "rrp." in host.lower()
        tip = (
            "BestGo gateways need a live balance + correct country/session username "
            "(dash DSL: user-country-us-session-…). If this provider is labeled "
            "DataImpulse but the gateway is *.bestgo.work, open Proxies → set Gateway "
            "to gw.dataimpulse.com OR keep BestGo host and use BestGo credentials — "
            "DataImpulse __cr DSL does not work on BestGo. "
            if bestgo
            else "Check provider balance / country targeting / password. "
        )
        return (
            f"Exit IP check failed{hint} — gateway reachable but IP endpoints "
            f"returned nothing. {tip}"
            "Then retry Create."
        )
    return msg[:240]


async def _quick_http_exit_ip_via_proxy(proxy: Dict[str, Any], ua: str = "") -> str:
    """Launcher-style plain HTTP exit-IP probe (create-gate fallback)."""
    try:
        from real_user_traffic import _proxy_url_for_http  # type: ignore
        import httpx
        import re
    except Exception:
        return ""
    server = _proxy_url_for_http(proxy)
    if not server:
        return ""
    probe_ua = (ua or "").strip() or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    urls = (
        "http://api.ipify.org/?format=text",
        "http://checkip.amazonaws.com/",
        "http://icanhazip.com",
        "http://ifconfig.me/ip",
        "http://ipinfo.io/ip",
        "http://ipecho.net/plain",
    )

    def _pull_ip(text: str) -> str:
        body = (text or "").strip()
        if not body:
            return ""
        first = body.split()[0].strip().strip('"').strip("'")
        if first and _is_valid_exit_ip(first):
            return first
        m = re.search(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b",
            body,
        )
        return m.group(0) if m else ""

    try:
        async with httpx.AsyncClient(
            proxy=server,
            timeout=httpx.Timeout(18.0, connect=10.0),
            headers={"User-Agent": probe_ua},
            verify=False,
            http2=False,
            trust_env=False,
        ) as cli:
            for url in urls:
                try:
                    r = await cli.get(url)
                    if r.status_code == 407:
                        continue
                    body = _pull_ip(r.text or "")
                    if body and _is_valid_exit_ip(body):
                        return body
                except Exception:
                    continue
    except Exception as exc:
        logger.debug(f"[browser-profile] quick HTTP exit-IP fallback failed: {exc}")
    return ""


async def _probe_profile_proxy(doc: Dict[str, Any], user: dict) -> Dict[str, Any]:
    """Exit-IP + optional fraud score for Proxy Check UI."""
    proxy = dict(doc.get("proxy") or {})
    uid = str(user.get("id") or doc.get("user_id") or "").strip()
    cred_uid = str(doc.get("user_id") or uid).strip() or uid
    if cred_uid:
        try:
            proxy = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy)
        except Exception as _hydr_probe:
            logger.debug(f"[browser-profile] proxy probe hydrate skipped: {_hydr_probe}")
    result: Dict[str, Any] = {
        "ok": False,
        "checked_at": _now_iso(),
        "proxy_enabled": proxy_is_active(proxy),
        "exit_ip": "",
        "country": "",
        "timezone": "",
        "fraud_score": None,
        "error": "",
    }
    server = (proxy.get("server") or "").strip()
    # Resolve provider_id → live line when possible
    if not server and proxy.get("provider_id"):
        try:
            from proxy_provider_module import resolve_provider_proxy_line  # type: ignore
            server = await resolve_provider_proxy_line(user, proxy.get("provider_id")) or ""
        except Exception:
            try:
                from proxy_provider_module import allocate_proxy_for_user  # type: ignore
                allocated = await allocate_proxy_for_user(user, provider_id=proxy.get("provider_id"))
                if isinstance(allocated, dict):
                    server = allocated.get("server") or allocated.get("proxy") or ""
                elif isinstance(allocated, str):
                    server = allocated
            except Exception as e:
                result["error"] = f"provider_resolve_failed: {e}"
                return result
    if not server:
        result["error"] = "no_proxy_configured"
        return result
    if not str(proxy.get("server") or "").strip():
        proxy["server"] = server

    try:
        from real_user_traffic import (  # noqa: WPS433
            _host_from_proxy_server,
            _probe_proxy_geo,
            _proxy_url_for_http,
        )
    except Exception as imp_exc:
        result["error"] = f"probe_engine_unavailable: {imp_exc}"
        return result

    probe_url = _proxy_url_for_http(proxy)
    if not probe_url:
        result["error"] = "no_proxy_configured"
        return result
    gateway_host = _host_from_proxy_server(probe_url)
    if not gateway_host or " " in gateway_host:
        result["error"] = (
            f"Invalid proxy gateway host '{gateway_host or '(empty)'}'. "
            "Open Proxies → edit provider → set Gateway host + port, then save password."
        )
        return result

    _default_probe_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    try:
        geo = await _probe_proxy_geo(
            dict(proxy), ua=_default_probe_ua, user_id=cred_uid or None,
        )
        exit_ip = str(geo.get("exit_ip") or "").strip()
        if geo.get("ok") and _is_valid_exit_ip(exit_ip):
            result["ok"] = True
            result["exit_ip"] = exit_ip
            result["country"] = str(geo.get("country") or geo.get("country_name") or "").strip()
            result["region"] = str(geo.get("region") or geo.get("region_name") or "").strip()
            result["city"] = str(geo.get("city") or "").strip()
            result["timezone"] = str(geo.get("timezone") or "").strip()
            result["is_vpn"] = bool(geo.get("is_vpn"))
            result["vpn_reason"] = str(geo.get("vpn_reason") or "").strip()
            try:
                from real_user_traffic import _assess_ip_quality  # type: ignore
                q = _assess_ip_quality(geo) or {}
                result["is_low_quality"] = bool(q.get("is_low_quality") or q.get("is_datacenter"))
                result["ip_quality_score"] = int(q.get("ip_quality_score") or 0)
                if result["is_low_quality"] and not result["is_vpn"]:
                    result["is_vpn"] = bool(q.get("is_datacenter"))
            except Exception:
                result["is_low_quality"] = bool(geo.get("is_low_quality"))
            try:
                from fraud_provider_module import check_ip_for_user  # type: ignore
                fr = await check_ip_for_user(user, exit_ip)
                if isinstance(fr, dict):
                    result["fraud_score"] = fr.get("fraud_score") or fr.get("score")
                    if not result["country"]:
                        result["country"] = fr.get("country") or fr.get("country_code") or ""
                    if fr.get("is_vpn") or fr.get("is_proxy"):
                        result["is_vpn"] = True
                        result["vpn_reason"] = result["vpn_reason"] or "flagged by fraud provider"
                    result["raw_fraud"] = {
                        k: fr.get(k)
                        for k in ("provider", "is_proxy", "is_vpn", "risk")
                        if k in fr
                    }
            except Exception:
                pass
        else:
            # v2.7.109/114 — HTTP ipify fallback, then enrich geo/VPN like RUT.
            fallback_ip = await _quick_http_exit_ip_via_proxy(proxy, _default_probe_ua)
            if _is_valid_exit_ip(fallback_ip):
                enrich = {
                    "exit_ip": fallback_ip,
                    "ok": False,
                    "is_vpn": False,
                    "country": "",
                    "region": "",
                    "city": "",
                    "timezone": "",
                }
                try:
                    from real_user_traffic import (  # type: ignore
                        _assess_ip_quality,
                        _enrich_geo_from_exit_ip,
                    )
                    await _enrich_geo_from_exit_ip(enrich)
                    q = _assess_ip_quality(enrich) or {}
                    enrich["is_low_quality"] = bool(q.get("is_low_quality") or q.get("is_datacenter"))
                    enrich["ip_quality_score"] = int(q.get("ip_quality_score") or 0)
                    if enrich["is_low_quality"]:
                        enrich["is_vpn"] = True
                        enrich["vpn_reason"] = "datacenter/hosting ISP"
                except Exception as _enr:
                    logger.debug(f"[browser-profile] exit-IP enrich skipped: {_enr}")
                result["ok"] = True
                result["exit_ip"] = fallback_ip
                result["probe_path"] = "quick_http_fallback"
                result["country"] = str(enrich.get("country") or "").strip()
                result["region"] = str(enrich.get("region") or enrich.get("region_name") or "").strip()
                result["city"] = str(enrich.get("city") or "").strip()
                result["timezone"] = str(enrich.get("timezone") or "").strip()
                result["is_vpn"] = bool(enrich.get("is_vpn"))
                result["vpn_reason"] = str(enrich.get("vpn_reason") or "").strip()
                result["is_low_quality"] = bool(enrich.get("is_low_quality"))
                logger.info(
                    f"[browser-profile] exit IP via quick HTTP fallback: {fallback_ip} "
                    f"host={gateway_host} vpn={result['is_vpn']}"
                )
            else:
                raw_err = str(geo.get("probe_error") or geo.get("error") or "").strip()
                result["error"] = _friendly_proxy_probe_error(raw_err, gateway_host)
    except Exception as e:
        fallback_ip = await _quick_http_exit_ip_via_proxy(proxy, _default_probe_ua)
        if _is_valid_exit_ip(fallback_ip):
            enrich = {"exit_ip": fallback_ip, "ok": False, "is_vpn": False}
            try:
                from real_user_traffic import _enrich_geo_from_exit_ip, _assess_ip_quality  # type: ignore
                await _enrich_geo_from_exit_ip(enrich)
                q = _assess_ip_quality(enrich) or {}
                if q.get("is_low_quality") or q.get("is_datacenter"):
                    enrich["is_vpn"] = True
            except Exception:
                pass
            result["ok"] = True
            result["exit_ip"] = fallback_ip
            result["probe_path"] = "quick_http_fallback"
            result["country"] = str(enrich.get("country") or "").strip()
            result["region"] = str(enrich.get("region") or "").strip()
            result["is_vpn"] = bool(enrich.get("is_vpn"))
            result["is_low_quality"] = bool(enrich.get("is_low_quality") or enrich.get("is_vpn"))
        else:
            result["error"] = _friendly_proxy_probe_error(str(e), gateway_host)
    return result


async def _load_team_profile_used_ips(uid: str) -> Set[str]:
    try:
        from cross_user_ip_isolation import list_team_profile_used_ips
        return await list_team_profile_used_ips(_DB, uid)
    except Exception as exc:
        logger.debug(f"team profile IP ledger fallback: {exc}")
        used: Set[str] = set()
        try:
            from cross_user_ip_isolation import canonicalize_ip
            async for doc in _DB.browser_profiles.find(
                {"user_id": uid, "exit_ip": {"$exists": True, "$ne": ""}},
                {"exit_ip": 1},
            ):
                c = canonicalize_ip(doc.get("exit_ip"))
                if c:
                    used.add(c)
        except Exception:
            pass
        return used


async def _bind_profile_exit_ip(
    uid: str,
    profile_id: str,
    exit_ip: str,
    *,
    source: str = "browser_profile",
) -> None:
    try:
        from cross_user_ip_isolation import canonicalize_ip, record_profile_exit_ip_for_user
        canonical = canonicalize_ip(exit_ip)
        if not canonical:
            return
        await record_profile_exit_ip_for_user(
            _DB, uid, profile_id, canonical, source=source,
        )
    except Exception as exc:
        logger.debug(f"profile exit IP ledger write skipped: {exc}")


async def _probe_proxy_cfg_exit_ip(user: dict, proxy_cfg: Dict[str, Any]) -> str:
    result = await _probe_profile_proxy({"proxy": proxy_cfg or {}}, user)
    return str(result.get("exit_ip") or "").strip()


async def _assert_unique_team_profile_ip(
    uid: str,
    exit_ip: str,
    used_ips: Set[str],
    *,
    profile_id: Optional[str] = None,
    batch_assigned: Optional[Set[str]] = None,
) -> str:
    """Fail if exit_ip already used by team; else reserve in-batch set."""
    try:
        from cross_user_ip_isolation import canonicalize_ip
        canonical = canonicalize_ip(exit_ip)
    except Exception:
        canonical = (exit_ip or "").strip()
    if not canonical:
        raise HTTPException(status_code=502, detail="Could not detect proxy exit IP")
    if batch_assigned is not None and canonical in batch_assigned:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Duplicate exit IP {canonical} — already assigned to another "
                f"profile in this batch"
            ),
        )
    if canonical in used_ips:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Duplicate exit IP {canonical} — already used by another profile "
                f"(team IP isolation). Retry launch for a fresh rotating IP, or "
                f"stop the other profile using this address."
            ),
        )
    used_ips.add(canonical)
    if batch_assigned is not None:
        batch_assigned.add(canonical)
    if profile_id:
        await _bind_profile_exit_ip(uid, profile_id, canonical)
    return canonical


async def _allocate_provider_proxy_lines(
    uid: str,
    provider_id: str,
    count: int,
    used_ips: Set[str],
    *,
    targeting: Optional[Dict[str, Any]] = None,
) -> List[str]:
    from proxy_provider_module import get_proxy_lines_from_provider
    pp_res = await get_proxy_lines_from_provider(
        uid,
        provider_id,
        count,
        unique_ip_seen=set(used_ips),
        strict_unique_ip=True,
        skip_datacenter_ip=True,
        targeting=targeting,
    )
    if pp_res.get("error") and not pp_res.get("lines"):
        raise HTTPException(
            status_code=502,
            detail=f"Provider proxy allocation failed: {pp_res.get('error')}",
        )
    lines = [str(x).strip() for x in (pp_res.get("lines") or []) if str(x).strip()]
    if len(lines) < count:
        warn = (pp_res.get("warnings") or [""])[0] if pp_res.get("warnings") else ""
        raise HTTPException(
            status_code=502,
            detail=(
                f"Provider returned only {len(lines)}/{count} unique clean IPs. "
                f"{warn or 'Try another country or smaller batch.'}"
            ),
        )
    return lines


async def _finalize_doc_proxy_and_ip(
    uid: str,
    user: dict,
    doc: Dict[str, Any],
    used_ips: Set[str],
) -> None:
    """Probe profile proxy, enforce team uniqueness, persist exit_ip on doc."""
    proxy = doc.get("proxy") or {}
    if not proxy_is_active(proxy):
        return
    proxy = await _finalize_proxy_cfg_for_launch(uid, user, dict(proxy))
    doc["proxy"] = proxy
    probe = await _probe_profile_proxy({"proxy": proxy, "user_id": uid}, user)
    exit_ip = str(probe.get("exit_ip") or "").strip()
    if not exit_ip:
        raise HTTPException(
            status_code=502,
            detail=_format_profile_proxy_probe_failure(doc, proxy, probe),
        )
    canonical = await _assert_unique_team_profile_ip(
        uid, exit_ip, used_ips, profile_id=str(doc.get("id") or ""),
    )
    doc["exit_ip"] = canonical
    doc["proxy"]["exit_ip"] = canonical
    doc["proxy"]["sticky_session"] = True


def _prepare_proxy_for_profile_create(doc: Dict[str, Any]) -> None:
    """Normalize proxy intent on a draft doc (credentials / raw_line).

    v2.7.106 — Exit IP bind is done by `_bind_unique_exit_ip_at_create`
    before insert. This helper only hydrates config shape.
    """
    proxy = dict(doc.get("proxy") or {})
    if not proxy_is_active(proxy):
        doc.pop("exit_ip", None)
        return
    provider_id = str(proxy.get("provider_id") or "").strip()
    if provider_id:
        proxy["enabled"] = True
        proxy["provider_id"] = provider_id
        proxy["smart_session"] = True
    if proxy.get("use_proxyjet"):
        proxy["enabled"] = True
    proxy = hydrate_proxy_credentials(proxy)
    raw = _canonical_proxy_raw_line(proxy)
    if raw:
        proxy["raw_line"] = raw
    # Binder sets exit_ip after probe — never keep a stale bind here
    proxy.pop("exit_ip", None)
    doc["proxy"] = proxy
    doc.pop("exit_ip", None)



def _normalize_create_target_state(raw: Any) -> str:
    """Normalize UI state to 2-letter US code when possible."""
    s = str(raw or "").strip().upper()
    if not s or s in ("ANY", "ALL", "*"):
        return ""
    if len(s) == 2 and s.isalpha():
        return s
    # Accept "ALABAMA" / "New York" / "state.alabama"
    s2 = s.replace("STATE.", "").replace("REGION.", "").replace("_", " ").replace("-", " ")
    try:
        from real_user_traffic import _normalize_state  # type: ignore
        return str(_normalize_state(s2) or _normalize_state(s) or "").strip().upper()[:2]
    except Exception:
        return s[:2] if len(s) >= 2 and s[:2].isalpha() else ""


def _apply_create_geo_targeting(
    proxy_cfg: Dict[str, Any],
    targeting: Optional[Dict[str, Any]],
    *,
    variant_index: int = 0,
) -> Dict[str, Any]:
    """Inject country/state + fresh sessid into rotating gateway username (RUT parity)."""
    cfg = dict(proxy_cfg or {})
    tgt = dict(targeting or {})
    country = str(tgt.get("country") or cfg.get("proxyjet_country") or "US").strip().upper()[:2] or "US"
    state = _normalize_create_target_state(tgt.get("state") or cfg.get("proxyjet_state") or "")
    if not state and not country:
        return cfg
    if not (
        _is_rotating_gateway_proxy(cfg)
        or str(cfg.get("provider_id") or "").strip()
        or cfg.get("use_proxyjet")
    ):
        # Static datacenter line — cannot rewrite geo DSL
        return cfg
    try:
        from real_user_traffic import _build_state_targeted_proxy  # type: ignore
        probe = dict(cfg)
        probe["is_rotating_gateway"] = True
        # RUT helper expects username/password keys
        if not probe.get("username") and probe.get("user"):
            probe["username"] = probe.get("user")
        out = _build_state_targeted_proxy(
            probe,
            state,
            country,
            state_variant_index=int(variant_index or 0),
        )
        if not out:
            return cfg
        cfg.update({k: out[k] for k in ("server", "username", "password", "raw") if k in out and out[k]})
        if out.get("raw") and not cfg.get("raw_line"):
            cfg["raw_line"] = out["raw"]
        if state:
            cfg["proxyjet_state"] = state
            cfg["state"] = state
        cfg["proxyjet_country"] = country
        cfg["country"] = country
        return cfg
    except Exception as exc:
        logger.debug(f"[browser-profile create] geo targeting inject skipped: {exc}")
        return cfg


def _create_probe_passes_rut_gates(
    probe: Dict[str, Any],
    targeting: Optional[Dict[str, Any]],
) -> tuple:
    """RUT-quality gates: IPv4 + non-VPN + country + selected state.

    Returns (ok, reason). Empty reason when ok.
    """
    exit_ip = str(probe.get("exit_ip") or "").strip()
    if not exit_ip or not _is_valid_exit_ip(exit_ip):
        return False, str(probe.get("error") or "exit IP probe failed")[:200]
    if ":" in exit_ip:
        return False, f"IPv6 exit {exit_ip} rejected — need IPv4"
    if probe.get("is_vpn") or probe.get("is_low_quality"):
        why = str(probe.get("vpn_reason") or "VPN/datacenter/hosting").strip()
        return False, f"exit IP {exit_ip} flagged {why} — rotating for clean residential"
    tgt = dict(targeting or {})
    want_cc = str(tgt.get("country") or "").strip().upper()[:2]
    want_st = _normalize_create_target_state(tgt.get("state") or "")
    geo = {
        "country": probe.get("country") or "",
        "region": probe.get("region") or "",
        "region_name": probe.get("region") or "",
        "city": probe.get("city") or "",
        "exit_ip": exit_ip,
        "is_vpn": bool(probe.get("is_vpn")),
    }
    try:
        from real_user_traffic import (  # type: ignore
            _geo_exit_state_code,
            _geo_matches_target_country,
            _heal_california_canada_collision,
        )
        _heal_california_canada_collision(geo)
        if want_cc and not _geo_matches_target_country(geo, want_cc):
            got = str(geo.get("country") or "?").upper()
            return False, f"exit country {got} != requested {want_cc} — rotating"
        if want_st:
            got_st = _geo_exit_state_code(geo)
            if not got_st or got_st != want_st:
                return False, (
                    f"exit state {got_st or '?'} != requested {want_st} — "
                    "rotating for correct geo"
                )
    except Exception as exc:
        logger.debug(f"[browser-profile create] geo gate skipped: {exc}")
    return True, ""


async def _bind_unique_exit_ip_at_create(
    uid: str,
    user: dict,
    doc: Dict[str, Any],
    *,
    used_ips: Set[str],
    batch_assigned: Set[str],
    targeting: Optional[Dict[str, Any]] = None,
    max_retries: int = 8,
) -> Dict[str, Any]:
    """RUT-grade bind before save: unique + non-VPN + selected country/state.

    v2.7.114 — Soft-defer removed. Profiles are NOT saved until a clean
    residential exit IP is verified (same quality bar as Real User Traffic).
    """
    _prepare_proxy_for_profile_create(doc)
    proxy_cfg = dict(doc.get("proxy") or {})
    if not proxy_is_active(proxy_cfg):
        doc.pop("exit_ip", None)
        return {"ok": True, "exit_ip": "", "skipped_proxy": True}

    provider_id = str(proxy_cfg.get("provider_id") or "").strip()
    rotating_manual = _is_rotating_gateway_proxy(proxy_cfg) and not provider_id
    profile_id = str(doc.get("id") or "").strip()
    tgt = dict(targeting or {})
    # Prefer proxyjet_* already on cfg when targeting empty
    if not tgt.get("country"):
        tgt["country"] = str(
            proxy_cfg.get("proxyjet_country") or doc.get("country") or "US"
        ).upper()[:2]
    if not tgt.get("state"):
        tgt["state"] = str(proxy_cfg.get("proxyjet_state") or "").upper()
    want_state = _normalize_create_target_state(tgt.get("state") or "")
    # Deeper retries when state geo must match (RUT ROW-FIRST style)
    base_attempts = max(1, int(max_retries or 8))
    attempts = max(base_attempts, 24 if want_state else base_attempts)
    last_err = "exit IP probe failed"

    for attempt in range(attempts):
        if provider_id:
            try:
                lines = await _allocate_provider_proxy_lines(
                    uid, provider_id, 1, used_ips | batch_assigned, targeting=tgt,
                )
                proxy_cfg = _apply_resolved_line_to_proxy_cfg(
                    proxy_cfg, lines[0], provider_id=provider_id,
                )
                proxy_cfg = _apply_create_geo_targeting(
                    proxy_cfg, tgt, variant_index=attempt,
                )
                proxy_cfg = await _finalize_proxy_cfg_for_launch(uid, user, proxy_cfg)
            except HTTPException as he:
                last_err = str(he.detail or he)[:200]
                if attempt >= attempts - 1:
                    break
                await asyncio.sleep(0.2)
                continue
            except Exception as exc:
                last_err = str(exc)[:200]
                break
        elif str(proxy_cfg.get("server") or "").strip() or str(proxy_cfg.get("raw_line") or "").strip():
            proxy_cfg = hydrate_proxy_credentials(proxy_cfg)
            if rotating_manual or _is_rotating_gateway_proxy(proxy_cfg):
                proxy_cfg = _apply_create_geo_targeting(
                    proxy_cfg, tgt, variant_index=attempt,
                )
                if attempt > 0:
                    try:
                        proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
                    except Exception:
                        pass
            proxy_cfg = await _finalize_proxy_cfg_for_launch(uid, user, proxy_cfg)
        else:
            last_err = "proxy enabled but no server/line to probe"
            break

        doc["proxy"] = dict(proxy_cfg)
        probe = await _probe_profile_proxy(
            {"proxy": proxy_cfg, "user_id": uid, "id": profile_id, "name": doc.get("name")},
            user,
        )
        gate_ok, gate_reason = _create_probe_passes_rut_gates(probe, tgt)
        if not gate_ok:
            last_err = gate_reason or "exit IP failed quality/geo gate"
            if (provider_id or rotating_manual) and attempt < attempts - 1:
                if rotating_manual or provider_id:
                    try:
                        proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
                        proxy_cfg = await _finalize_proxy_cfg_for_launch(uid, user, proxy_cfg)
                    except Exception:
                        pass
                    await asyncio.sleep(0.25)
                continue
            break

        exit_ip = str(probe.get("exit_ip") or "").strip()
        try:
            canonical = await _assert_unique_team_profile_ip(
                uid,
                exit_ip,
                used_ips,
                profile_id=profile_id,
                batch_assigned=batch_assigned,
            )
            doc["exit_ip"] = canonical
            doc["proxy"] = dict(proxy_cfg)
            doc["proxy"]["exit_ip"] = canonical
            doc["proxy"]["sticky_session"] = True
            doc["proxy"]["exit_ip_verified_at_create"] = True
            doc["proxy"]["exit_ip_country"] = str(probe.get("country") or "")[:8]
            doc["proxy"]["exit_ip_region"] = str(probe.get("region") or "")[:32]
            doc.pop("exit_ip_deferred", None)
            doc.get("proxy", {}).pop("exit_ip_deferred", None)
            raw = _canonical_proxy_raw_line(doc["proxy"])
            if raw:
                doc["proxy"]["raw_line"] = raw
            logger.info(
                f"[browser-profile create] RUT-quality exit_ip={canonical} "
                f"cc={probe.get('country')} st={probe.get('region')} "
                f"profile={profile_id[:8]} attempt={attempt + 1}"
            )
            return {
                "ok": True,
                "exit_ip": canonical,
                "country": str(probe.get("country") or ""),
                "region": str(probe.get("region") or ""),
            }
        except HTTPException as exc:
            last_err = str(exc.detail or exc)[:200]
            if exc.status_code != 409 or attempt >= attempts - 1:
                break
            if rotating_manual or provider_id:
                try:
                    proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
                    proxy_cfg = await _finalize_proxy_cfg_for_launch(uid, user, proxy_cfg)
                except Exception:
                    pass
                await asyncio.sleep(0.2)
            elif not provider_id:
                break

    # Hard fail — never soft-save without a verified clean unique IP.
    return {
        "ok": False,
        "reason": last_err or "could not reserve a unique clean exit IP",
        "name": str(doc.get("name") or ""),
    }


async def _pick_ua_line_from_upload(uid: str, upload_id: str) -> Optional[str]:
    """Pick next UA from Uploaded Things batch (one-time use at launch)."""
    up_id = str(upload_id or "").strip()
    if not up_id or _DB is None:
        return None
    doc = await _DB.uploaded_resources.find_one(
        {"id": up_id, "user_id": uid, "type": "user_agents"},
        {"_id": 0, "items": 1, "consumed_keys": 1},
    )
    if not doc:
        return None
    consumed = {str(k).strip() for k in (doc.get("consumed_keys") or []) if str(k).strip()}
    items = [str(x).strip() for x in (doc.get("items") or []) if str(x).strip()]
    for raw in items:
        if raw not in consumed:
            return raw
    return None


async def _consume_ua_line_from_upload(uid: str, upload_id: str, raw_line: str) -> bool:
    """Mark one UA line consumed in Uploaded Things (does not create auto batches)."""
    up_id = str(upload_id or "").strip()
    raw = str(raw_line or "").strip()
    if not up_id or not raw or _DB is None:
        return False
    try:
        key = raw[:256].lower()
        res = await _DB.uploaded_resources.update_one(
            {"id": up_id, "user_id": uid, "type": "user_agents"},
            {
                "$addToSet": {"consumed_keys": key},
                "$set": {"updated_at": _now_iso()},
                "$inc": {"consumed_count": 1},
            },
        )
        return bool(res.modified_count)
    except Exception as exc:
        logger.debug(f"[profile-launch] ua consume skipped: {exc}")
        return False


async def _apply_launch_ua_from_upload(uid: str, doc: Dict[str, Any], upload_id: str) -> None:
    """Override profile UA from an Uploaded Things UA batch for this launch."""
    raw = await _pick_ua_line_from_upload(uid, upload_id)
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="UA upload batch is empty or fully consumed — upload more user-agents.",
        )
    doc["user_agent"] = raw
    doc["_consume_ua_upload_id"] = str(upload_id or "").strip()
    doc["_consume_ua_raw"] = raw


async def _pick_proxy_line_from_upload(uid: str, upload_id: str) -> Optional[str]:
    """Pick next proxy line from Uploaded Things batch (RUT parity)."""
    up_id = str(upload_id or "").strip()
    if not up_id or _DB is None:
        return None
    doc = await _DB.uploaded_resources.find_one(
        {"id": up_id, "user_id": uid, "type": "proxies"},
        {"_id": 0},
    )
    if not doc:
        return None
    consumed = {str(k).strip() for k in (doc.get("consumed_keys") or []) if str(k).strip()}
    items = [str(x).strip() for x in (doc.get("items") or []) if str(x).strip()]
    for raw in items:
        if raw not in consumed:
            return raw
    return None


async def _consume_proxy_line_from_upload(uid: str, upload_id: str, raw_line: str) -> bool:
    """Remove a used proxy line from Uploaded Things (RUT parity)."""
    up_id = str(upload_id or "").strip()
    raw = str(raw_line or "").strip()
    if not up_id or not raw or _DB is None:
        return False
    try:
        res = await _DB.uploaded_resources.update_one(
            {"id": up_id, "user_id": uid, "type": "proxies"},
            {
                "$pull": {"items": raw},
                "$set": {"updated_at": _now_iso()},
                "$inc": {"consumed_count": 1, "item_count": -1},
            },
        )
        if not res.modified_count:
            return False
        doc = await _DB.uploaded_resources.find_one(
            {"id": up_id, "user_id": uid},
            {"_id": 0, "items": 1, "depleted": 1, "gsheet_url": 1},
        )
        gsheet_url = str((doc or {}).get("gsheet_url") or "").strip()
        if gsheet_url:
            try:
                import asyncio
                import gsheet_writer

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    gsheet_writer.delete_rows_by_first_column,
                    gsheet_url,
                    [raw],
                )
            except Exception as exc:
                logger.debug(f"[profile-automation] gsheet proxy delete skipped: {exc}")
        if doc and isinstance(doc.get("items"), list) and len(doc["items"]) == 0 and not doc.get("depleted"):
            await _DB.uploaded_resources.update_one(
                {"id": up_id, "user_id": uid},
                {"$set": {
                    "depleted": True,
                    "depleted_at": _now_iso(),
                    "item_count": 0,
                }},
            )
        return True
    except Exception as exc:
        logger.warning(f"[profile-automation] proxy consume failed: {exc}")
        return False


async def _apply_json_run_proxy_from_upload(
    uid: str,
    user: dict,
    doc: Dict[str, Any],
    auto_spec: Dict[str, Any],
) -> None:
    """Use Uploaded Things proxy batch for this JSON run instead of provider dial."""
    upload_id = str(auto_spec.get("proxy_upload_id") or "").strip()
    if not upload_id:
        return
    raw_line = await _pick_proxy_line_from_upload(uid, upload_id)
    if not raw_line:
        raise HTTPException(
            status_code=400,
            detail="Proxy upload batch is empty or fully consumed — upload more proxies.",
        )
    parsed = _parse_proxy_line(raw_line)
    if not parsed.get("server"):
        raise HTTPException(status_code=400, detail="Invalid proxy line in upload batch")
    proxy_cfg = dict(doc.get("proxy") or {})
    proxy_cfg["enabled"] = True
    proxy_cfg["server"] = parsed["server"]
    if parsed.get("username"):
        proxy_cfg["username"] = parsed["username"]
    if parsed.get("password"):
        proxy_cfg["password"] = parsed["password"]
    proxy_cfg.pop("provider_id", None)
    proxy_cfg.pop("use_proxyjet", None)
    proxy_cfg.pop("exit_ip", None)
    doc["proxy"] = proxy_cfg
    auto_spec["_consume_proxy_upload_id"] = upload_id
    auto_spec["_consume_proxy_raw"] = raw_line
    used_ips = await _load_team_profile_used_ips(uid)
    await _finalize_doc_proxy_and_ip(uid, user, doc, used_ips)
    await _consume_proxy_line_from_upload(uid, upload_id, raw_line)


async def _ensure_profile_launch_proxy(
    uid: str,
    user: dict,
    doc: Dict[str, Any],
    *,
    profile_country: Optional[str] = None,
    max_retries: int = 5,
) -> Dict[str, Any]:
    """Resolve proxy, probe exit IP, and guarantee a team-unique IP before launch."""
    proxy_cfg = dict(doc.get("proxy") or {})
    if not proxy_is_active(proxy_cfg):
        return proxy_cfg
    profile_id = str(doc.get("id") or "")
    cred_uid = str(doc.get("user_id") or uid).strip() or uid
    provider_id = str(proxy_cfg.get("provider_id") or "").strip()
    use_proxyjet = bool(proxy_cfg.get("use_proxyjet"))

    # v2.7.114 — Prefer create-verified sticky line (unique/non-VPN/geo already
    # checked). Do not wipe server/raw_line and re-roll a different IP on open.
    _create_verified = bool(
        proxy_cfg.get("exit_ip_verified_at_create")
        or (
            proxy_cfg.get("sticky_session")
            and str(doc.get("exit_ip") or proxy_cfg.get("exit_ip") or "").strip()
            and not proxy_cfg.get("exit_ip_deferred")
        )
    )
    if _create_verified and (
        str(proxy_cfg.get("server") or "").strip()
        or str(proxy_cfg.get("raw_line") or proxy_cfg.get("raw") or "").strip()
    ):
        proxy_cfg = hydrate_proxy_credentials(proxy_cfg)
        proxy_cfg = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
        if str(proxy_cfg.get("server") or "").strip():
            probe = await _probe_profile_proxy(
                {
                    "proxy": proxy_cfg,
                    "user_id": cred_uid,
                    "id": profile_id,
                    "name": doc.get("name"),
                },
                user,
            )
            tgt = {
                "country": str(
                    proxy_cfg.get("proxyjet_country")
                    or proxy_cfg.get("exit_ip_country")
                    or profile_country
                    or doc.get("country")
                    or "US"
                ).upper()[:2],
                "state": str(
                    proxy_cfg.get("proxyjet_state")
                    or proxy_cfg.get("exit_ip_region")
                    or ""
                ).upper(),
            }
            gate_ok, gate_reason = _create_probe_passes_rut_gates(probe, tgt)
            exit_ip = str(probe.get("exit_ip") or "").strip()
            stored = str(doc.get("exit_ip") or proxy_cfg.get("exit_ip") or "").strip()
            if gate_ok and exit_ip:
                # Keep sticky when still clean; allow same profile IP.
                try:
                    used = await _load_team_profile_used_ips(cred_uid)
                    used.discard(stored)
                    used.discard(exit_ip)
                    canonical = await _assert_unique_team_profile_ip(
                        cred_uid,
                        exit_ip,
                        used,
                        profile_id=profile_id,
                        batch_assigned=set(),
                    )
                    proxy_cfg["exit_ip"] = canonical
                    proxy_cfg["sticky_session"] = True
                    doc["exit_ip"] = canonical
                    logger.info(
                        f"[browser-profile launch] reused create-verified "
                        f"exit_ip={canonical} profile={profile_id[:8]}"
                    )
                    return proxy_cfg
                except Exception as _sticky_exc:
                    logger.warning(
                        f"[browser-profile launch] sticky reuse unique-check "
                        f"failed ({_sticky_exc}) — rotating"
                    )
            else:
                logger.warning(
                    f"[browser-profile launch] create-sticky failed re-check "
                    f"({gate_reason or 'probe failed'}) — rotating"
                )

    # v2.7.113 — Manual rotating gateways (DataImpulse paste, etc.) keep host:port
    # and only rotate sessid. v2.7.108 wiped server+raw_line for ALL rotating
    # hosts, then resolve_profile_proxy_for_launch could not rebuild without a
    # provider_id → "proxy enabled but no server URL could be resolved".
    _manual_rotating = (
        not provider_id
        and not use_proxyjet
        and _is_rotating_gateway_proxy(proxy_cfg)
    )
    # Provider / ProxyJet / smart_session (provider-backed): fresh allocated line.
    _fresh_rotating = bool(provider_id or use_proxyjet or proxy_cfg.get("smart_session"))
    if _manual_rotating:
        proxy_cfg.pop("exit_ip", None)
        proxy_cfg = hydrate_proxy_credentials(proxy_cfg)
        if not str(proxy_cfg.get("server") or "").strip():
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Profile '{doc.get('name') or profile_id[:8]}': proxy enabled but no server "
                    "URL could be resolved. Re-paste the manual proxy line "
                    "(user:pass@host:port) on the profile, then launch again."
                ),
            )
        proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
        proxy_cfg = await resolve_profile_proxy_for_launch(
            cred_uid, user, proxy_cfg, team_dedupe=True, profile_country=profile_country,
        )
    elif _fresh_rotating:
        proxy_cfg.pop("exit_ip", None)
        proxy_cfg.pop("raw_line", None)
        proxy_cfg.pop("raw", None)
        proxy_cfg["server"] = ""
        # Keep provider_id / password; username comes from newly allocated line
        if provider_id or use_proxyjet:
            proxy_cfg["username"] = ""
        proxy_cfg = await resolve_profile_proxy_for_launch(
            cred_uid, user, proxy_cfg, team_dedupe=True, profile_country=profile_country,
        )
    elif not str(proxy_cfg.get("server") or "").strip():
        proxy_cfg = await resolve_profile_proxy_for_launch(
            cred_uid, user, proxy_cfg, team_dedupe=True, profile_country=profile_country,
        )

    proxy_cfg = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)

    if not str(proxy_cfg.get("server") or "").strip():
        raise HTTPException(
            status_code=502,
            detail=(
                f"Profile '{doc.get('name') or profile_id[:8]}': proxy enabled but no server "
                "URL could be resolved. Open Proxies → edit provider → verify gateway "
                "host, port, and password, then launch again."
            ),
        )

    # Provider / smart_session / ProxyJet — pre-probe is best-effort only.
    if _defer_launch_proxy_probe(proxy_cfg):
        used_ips = await _load_team_profile_used_ips(cred_uid)
        try:
            from cross_user_ip_isolation import canonicalize_ip
            cur = canonicalize_ip(doc.get("exit_ip") or "")
            if cur:
                used_ips.discard(cur)
        except Exception:
            pass
        targeting = _profile_provider_targeting(proxy_cfg, profile_country)
        return await _best_effort_bind_exit_ip_at_launch(
            cred_uid,
            user,
            doc,
            proxy_cfg,
            provider_id=provider_id,
            profile_id=profile_id,
            used_ips=used_ips,
            targeting=targeting,
        )

    used_ips = await _load_team_profile_used_ips(cred_uid)
    try:
        from cross_user_ip_isolation import canonicalize_ip
        cur = canonicalize_ip(doc.get("exit_ip") or "")
        if cur:
            used_ips.discard(cur)
    except Exception:
        pass

    targeting = _profile_provider_targeting(proxy_cfg, profile_country)
    last_probe: Dict[str, Any] = {}
    last_err: Optional[HTTPException] = None

    for attempt in range(max_retries):
        doc["proxy"] = dict(proxy_cfg)
        probe_doc = {"proxy": proxy_cfg, "user_id": cred_uid, "id": profile_id, "name": doc.get("name")}
        try:
            probe = await _probe_profile_proxy(probe_doc, user)
            last_probe = probe
            exit_ip = str(probe.get("exit_ip") or "").strip()
            if not exit_ip:
                if provider_id and attempt < max_retries - 1:
                    logger.warning(
                        f"[browser-profile launch] exit IP probe failed on attempt "
                        f"{attempt + 1} — rotating provider session"
                    )
                    lines = await _allocate_provider_proxy_lines(
                        cred_uid, provider_id, 1, used_ips, targeting=targeting,
                    )
                    proxy_cfg = _apply_resolved_line_to_proxy_cfg(
                        proxy_cfg, lines[0], provider_id=provider_id,
                    )
                    proxy_cfg = await _finalize_proxy_cfg_for_launch(
                        cred_uid, user, proxy_cfg,
                    )
                    continue
                if _proxy_ready_for_soft_launch(proxy_cfg):
                    _raise_if_strict_soft_launch(
                        doc,
                        reason=(
                            "proxy exit-IP pre-check failed "
                            f"({str(probe.get('error') or 'no exit IP')[:120]})"
                        ),
                    )
                    _set_soft_launch_proxy_state(doc, proxy_cfg, probe=probe)
                    logger.warning(
                        f"[browser-profile launch] soft launch without exit_ip "
                        f"profile={profile_id[:8]} err={str(probe.get('error') or '')[:80]}"
                    )
                    return await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
                raise HTTPException(
                    status_code=502,
                    detail=_format_profile_proxy_probe_failure(doc, proxy_cfg, probe),
                )
            canonical = await _assert_unique_team_profile_ip(
                cred_uid, exit_ip, used_ips, profile_id=profile_id,
            )
            doc["exit_ip"] = canonical
            doc["proxy"]["exit_ip"] = canonical
            doc["proxy"]["sticky_session"] = True
            doc.pop("_launch_proxy_probe_warning", None)
            logger.info(
                f"[browser-profile launch] unique exit_ip={canonical} "
                f"profile={profile_id[:8]} attempt={attempt + 1}"
            )
            return await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
        except HTTPException as exc:
            last_err = exc
            if exc.status_code != 409 or attempt >= max_retries - 1:
                raise
            if provider_id:
                logger.warning(
                    f"[browser-profile launch] duplicate IP on attempt {attempt + 1} "
                    f"— rotating provider session"
                )
                lines = await _allocate_provider_proxy_lines(
                    cred_uid, provider_id, 1, used_ips, targeting=targeting,
                )
                proxy_cfg = _apply_resolved_line_to_proxy_cfg(
                    proxy_cfg, lines[0], provider_id=provider_id,
                )
                proxy_cfg = await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
            elif _is_rotating_gateway_proxy(proxy_cfg):
                logger.warning(
                    f"[browser-profile launch] duplicate manual rotating IP on "
                    f"attempt {attempt + 1} — fresh gateway session"
                )
                proxy_cfg = _rotate_manual_proxy_session(proxy_cfg)
                proxy_cfg = await _finalize_proxy_cfg_for_launch(
                    cred_uid, user, proxy_cfg,
                )
                await asyncio.sleep(0.25)
            else:
                raise

    if _proxy_ready_for_soft_launch(proxy_cfg):
        _raise_if_strict_soft_launch(
            doc,
            reason=(
                "could not allocate a unique verified exit IP "
                f"({str((last_probe or {}).get('error') or 'probe failed')[:120]})"
            ),
        )
        _set_soft_launch_proxy_state(doc, proxy_cfg, probe=last_probe)
        return await _finalize_proxy_cfg_for_launch(cred_uid, user, proxy_cfg)
    if last_err:
        raise last_err
    raise HTTPException(
        status_code=502,
        detail=_format_profile_proxy_probe_failure(doc, proxy_cfg, last_probe)
        or "Could not allocate a unique proxy exit IP for this profile",
    )


async def _resolve_user(request: Request) -> dict:
    """Module-internal helper — calls the bound get_current_user with the
    incoming request and returns the user dict (or raises 401)."""
    if _GET_USER is None:
        raise HTTPException(status_code=503, detail="Browser Profiles: auth not bound")
    user = await _GET_USER(request)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Unauthenticated")
    return user


def _resolve_user_or_401(user: dict) -> str:
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Unauthenticated")
    return user["id"]


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────
@router.get("/")
async def list_profiles(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    skip: int = Query(default=0, ge=0, le=10000),
    sort: str = Query(default="updated_at"),
    tag: Optional[str] = None,
    folder: Optional[str] = None,
    q: Optional[str] = None,
):
    """List owned + ACL-shared profiles for the current user."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    filt: Dict[str, Any] = {
        "$and": [
            {"$or": [{"user_id": uid}, {"acl.user_id": uid}]},
            _not_deleted_filter(),
        ],
    }
    if tag:
        filt["tags"] = tag
    if folder is not None and str(folder).strip() != "":
        if str(folder).strip().lower() in ("__", "none", "(none)", "unsorted"):
            filt["$and"].append({
                "$or": [
                    {"folder": {"$exists": False}},
                    {"folder": ""},
                    {"folder": None},
                ],
            })
        else:
            filt["folder"] = str(folder).strip()[:80]
    sort_key = (sort or "updated_at").strip().lower()
    sort_field = {
        "name": "name",
        "last_launched_at": "last_launched_at",
        "total_launches": "total_launches",
        "updated_at": "updated_at",
    }.get(sort_key, "updated_at")
    cur = (
        _DB.browser_profiles.find(filt)
        .sort(sort_field, -1)
        .skip(int(skip))
        .limit(limit)
    )
    docs = await cur.to_list(length=limit)
    needle = (q or "").strip().lower()
    if needle:
        docs = [
            d for d in docs
            if needle in str(d.get("name") or "").lower()
            or needle in str(d.get("notes") or "").lower()
            or needle in str(d.get("folder") or "").lower()
            or any(needle in str(t).lower() for t in (d.get("tags") or []))
            or needle in str(d.get("user_agent") or "").lower()
            or needle in str(d.get("start_url") or "").lower()
        ]
    return {
        "profiles": [_public_view_for(d, uid) for d in docs],
        "count": len(docs),
        "skip": skip,
        "limit": limit,
        "has_more": len(docs) >= limit,
        "sort": sort_field,
    }


@router.get("/trash")
async def list_trash_profiles(request: Request, limit: int = Query(default=200, ge=1, le=500)):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    filt = {
        "user_id": uid,
        "deleted_at": {"$exists": True, "$nin": [None, ""]},
    }
    cur = _DB.browser_profiles.find(filt).sort("deleted_at", -1).limit(limit)
    docs = await cur.to_list(length=limit)
    return {"profiles": [_public_view(d) for d in docs], "count": len(docs)}


@router.post("/")
async def create_profile(request: Request, body: ProfileBody):
    """Create a new browser profile — unique exit IP verified before save."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = _profile_doc(uid, body)
    if proxy_is_active(doc.get("proxy") or {}):
        used_ips = await _load_team_profile_used_ips(uid)
        batch_assigned: Set[str] = set()
        _tgt = {
            "country": str(
                (doc.get("proxy") or {}).get("proxyjet_country")
                or doc.get("country")
                or "US"
            ).upper()[:2],
            "state": str(
                (doc.get("proxy") or {}).get("proxyjet_state")
                or ""
            ).upper(),
        }
        bind = await _bind_unique_exit_ip_at_create(
            uid, user, doc,
            used_ips=used_ips,
            batch_assigned=batch_assigned,
            targeting=_tgt,
            max_retries=24,
        )
        if not bind.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Could not reserve a unique exit IP before create — "
                    f"{str(bind.get('reason') or 'probe failed')[:200]}. "
                    "Profile was NOT saved (no wasted profile)."
                ),
            )
        deferred = bool(bind.get("deferred"))
    else:
        _prepare_proxy_for_profile_create(doc)
        deferred = False
    await _DB.browser_profiles.insert_one(doc)
    out = {"profile": _public_view(doc), "id": doc["id"]}
    if deferred:
        out["exit_ip_deferred"] = True
        out["warning"] = str(bind.get("warning") or "")[:240]
    return out


@router.get("/device-catalog")
async def device_catalog(request: Request):
    """Device list for create-form dropdown — must be before /{profile_id}."""
    await _resolve_user(request)
    return {
        "devices": [
            {
                "id": d["id"],
                "slug": d["slug"],
                "label": d["label"],
                "platform": d["platform"],
                "brand": d.get("brand") or "",
                "viewport": d.get("viewport") or {},
                "dpr": d.get("dpr") or 1,
            }
            for d in _DEVICE_CATALOG
        ]
    }


@router.get("/folders")
async def list_folders(request: Request):
    """Distinct folder names for sidebar filter."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    folders: Dict[str, int] = {}
    unsorted = 0
    cur = _DB.browser_profiles.find({"user_id": uid}, {"folder": 1})
    async for doc in cur:
        f = (doc.get("folder") or "").strip()
        if not f:
            unsorted += 1
        else:
            folders[f] = folders.get(f, 0) + 1
    items = [{"name": k, "count": v} for k, v in sorted(folders.items(), key=lambda x: x[0].lower())]
    return {"folders": items, "unsorted": unsorted}


@router.post("/bulk-move")
async def bulk_move(request: Request, body: BulkMoveBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:200]
    folder = (body.folder or "").strip()[:80]
    if not ids:
        raise HTTPException(status_code=400, detail="profile_ids required")
    res = await _DB.browser_profiles.update_many(
        {"user_id": uid, "id": {"$in": ids}},
        {"$set": {"folder": folder, "updated_at": _now_iso()}},
    )
    return {"moved": int(res.modified_count or 0), "folder": folder}


@router.post("/import")
async def import_profiles(request: Request, body: ImportProfilesBody):
    """Re-import profiles from Export JSON (config; optional cookies)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    raw_list = body.profiles or []
    if not raw_list and isinstance(getattr(body, "__dict__", None), dict):
        pass
    created = []
    for raw in raw_list[:200]:
        if not isinstance(raw, dict):
            continue
        try:
            tags = raw.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            pb = ProfileBody(
                name=str(raw.get("name") or "").strip() or "",
                notes=str(raw.get("notes") or "")[:2000],
                country=str(raw.get("country") or "us").lower()[:8],
                language=str(raw.get("language") or "en-US"),
                timezone=str(raw.get("timezone") or "America/New_York"),
                device_type=str(raw.get("device_type") or "desktop"),
                os=str(raw.get("os") or "windows"),
                user_agent=str(raw.get("user_agent") or "")[:600],
                viewport=raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {"width": 1920, "height": 1080},
                is_mobile=bool(raw.get("is_mobile")),
                has_touch=bool(raw.get("has_touch") or raw.get("is_mobile")),
                device_scale_factor=float(raw.get("device_scale_factor") or 1.0),
                locale=str(raw.get("locale") or "en-US"),
                accept_language=str(raw.get("accept_language") or "en-US,en;q=0.9"),
                start_url=str(raw.get("start_url") or "https://www.google.com/")[:512],
                tags=[str(t) for t in tags][:20],
                folder=str(raw.get("folder") or "")[:80],
                geo_follow_proxy=bool(raw.get("geo_follow_proxy", True)),
                quick_links=[str(u) for u in (raw.get("quick_links") or [])][:12],
            )
            # Proxy / anti / referrer best-effort
            if isinstance(raw.get("proxy"), dict):
                try:
                    _fields = getattr(ProxyConfig, "model_fields", None) or getattr(ProxyConfig, "__fields__", {})
                    pb.proxy = ProxyConfig(**{k: v for k, v in raw["proxy"].items() if k in _fields})
                except Exception:
                    pass
            if isinstance(raw.get("anti_detect"), dict):
                try:
                    _fields = getattr(AntiDetectConfig, "model_fields", None) or getattr(AntiDetectConfig, "__fields__", {})
                    pb.anti_detect = AntiDetectConfig(**{k: v for k, v in raw["anti_detect"].items() if k in _fields})
                except Exception:
                    pass
            if isinstance(raw.get("referrer"), dict):
                try:
                    _fields = getattr(ReferrerProConfig, "model_fields", None) or getattr(ReferrerProConfig, "__fields__", {})
                    pb.referrer = ReferrerProConfig(**{k: v for k, v in raw["referrer"].items() if k in _fields})
                except Exception:
                    pass
            doc = _profile_doc(uid, pb)
            if body.include_cookies and isinstance(raw.get("storage_state"), dict):
                doc["storage_state"] = raw["storage_state"]
                doc["storage_synced_at"] = _now_iso()
            await _DB.browser_profiles.insert_one(doc)
            created.append(_public_view(doc))
        except Exception as e:
            logger.warning(f"import profile skipped: {e}")
    return {"created": len(created), "profiles": created}


@router.get("/local/info")
async def local_api_info(request: Request):
    """AdsPower-style Local API discovery for automation clients."""
    await _resolve_user(request)
    _enforce_local_api_key(request)
    mode = (os.environ.get("KREXION_MODE") or "").lower()
    local = mode in ("native", "local", "desktop")
    return {
        "ok": True,
        "local_mode": local,
        "base_path": "/api/browser-profiles/local",
        "endpoints": {
            "start": "POST /api/browser-profiles/local/start",
            "status": "GET /api/browser-profiles/local/status/{profile_id}",
            "stop": "POST /api/browser-profiles/local/stop",
            "list": "GET /api/browser-profiles/local/profiles",
            "cookies_get": "GET /api/browser-profiles/local/profiles/{id}/cookies",
            "cookies_put": "PUT /api/browser-profiles/local/profiles/{id}/cookies",
            "docs": "GET /api/browser-profiles/local/docs",
            "kernel": "GET /api/browser-profiles/local/kernel",
        },
        "notes": (
            "Start returns cdp_ws when enable_cdp=true and Chromium launches on this machine. "
            "Connect Playwright via chromium.connect_over_cdp(cdp_ws). "
            "Kernel auto = CloakBrowser C++ Chromium when installed (Octo-class), else Patchright, else Playwright. "
            "When KREXION_LOCAL_API_KEY is set, also send X-Krexion-Local-Key or Authorization Bearer."
        ),
    }


@router.get("/local/kernel")
async def local_kernel_status(request: Request):
    """Report CloakBrowser / Patchright / Playwright kernel availability."""
    await _resolve_user(request)
    _enforce_local_api_key(request)
    try:
        from krexion_browser_kernel import cloak_info, patchright_available, resolve_launch_plan
        plan = resolve_launch_plan({"browser_kernel": "auto"})
        return {
            "ok": True,
            "cloak": cloak_info(),
            "patchright": patchright_available(),
            "auto_plan": plan,
            "env_KREXION_BROWSER_KERNEL": (os.environ.get("KREXION_BROWSER_KERNEL") or "auto"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:240]}


@router.get("/local/docs")
async def local_api_docs(request: Request, format: str = Query(default="json")):
    """AdsPower / Octo → Krexion Local API migration map (markdown or json)."""
    await _resolve_user(request)
    _enforce_local_api_key(request)
    mapping = [
        {"vendor": "AdsPower start", "krexion": "POST /api/browser-profiles/local/start"},
        {"vendor": "AdsPower status", "krexion": "GET /api/browser-profiles/local/status/{id}"},
        {"vendor": "AdsPower stop", "krexion": "POST /api/browser-profiles/local/stop"},
        {"vendor": "AdsPower list", "krexion": "GET /api/browser-profiles/local/profiles"},
        {"vendor": "AdsPower cookies", "krexion": "GET/PUT /api/browser-profiles/local/profiles/{id}/cookies"},
        {"vendor": "Octo :58888 start + debug_port", "krexion": "POST /local/start {enable_cdp:true} → cdp_ws"},
        {"vendor": "Octo Octium kernel", "krexion": "anti_detect.browser_kernel=auto|cloak (CloakBrowser C++)"},
        {"vendor": "Octo noise toggles", "krexion": "canvas_mode / webgl_mode / audio_mode / font_mode"},
        {"vendor": "GoLogin / MoreLogin CDP", "krexion": "same Local start + connect_over_cdp"},
        {"vendor": "AdsPower Synchronizer", "krexion": "POST /api/browser-profiles/sync/start {master_id, slave_ids}"},
        {"vendor": "Team ACL / share", "krexion": "POST /{id}/acl + POST /{id}/share (clone)"},
        {"vendor": "MoreLogin Cloud Phone", "krexion": "POST /{id}/cloud-phone + /open-on-device (CPI)"},
        # back-compat keys
        {"adspower": "start", "krexion": "POST /api/browser-profiles/local/start"},
        {"adspower": "status", "krexion": "GET /api/browser-profiles/local/status/{id}"},
        {"adspower": "stop", "krexion": "POST /api/browser-profiles/local/stop"},
        {"adspower": "list", "krexion": "GET /api/browser-profiles/local/profiles"},
        {"adspower": "cookies", "krexion": "GET/PUT /api/browser-profiles/local/profiles/{id}/cookies"},
    ]
    if str(format or "json").lower() in ("md", "markdown", "text"):
        lines = [
            "# Krexion Local API — AdsPower / Octo / GoLogin migration map",
            "",
            "| Vendor | Krexion |",
            "|----------|---------|",
        ]
        for row in mapping:
            label = row.get("vendor") or row.get("adspower") or ""
            lines.append(f"| {label} | `{row['krexion']}` |")
        lines.extend([
            "",
            "Auth: JWT (Bearer) always. If `KREXION_LOCAL_API_KEY` is set, also send",
            "`X-Krexion-Local-Key` or `Authorization: Bearer <key>`.",
            "",
            "Kernel: `anti_detect.browser_kernel=auto` prefers CloakBrowser C++ Chromium",
            "(Octo Octium-class), then Patchright, then Playwright.",
            "",
        ])
        return {"ok": True, "format": "markdown", "markdown": "\n".join(lines), "map": mapping}
    return {"ok": True, "format": "json", "map": mapping}


@router.get("/local/profiles")
async def local_api_list_profiles(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
):
    await _resolve_user(request)
    _enforce_local_api_key(request)
    return await list_profiles(request, limit=limit)


@router.get("/local/profiles/{profile_id}/cookies")
async def local_api_export_cookies(request: Request, profile_id: str):
    await _resolve_user(request)
    _enforce_local_api_key(request)
    return await export_cookies(request, profile_id)


@router.put("/local/profiles/{profile_id}/cookies")
async def local_api_import_cookies(request: Request, profile_id: str, body: CookieImportBody):
    await _resolve_user(request)
    _enforce_local_api_key(request)
    return await import_cookies(request, profile_id, body)


@router.post("/local/start")
async def local_api_start(
    request: Request,
    body: Dict[str, Any] = Body(default_factory=dict),
):
    """Local automation: launch profile and optionally expose CDP websocket."""
    user = await _resolve_user(request)
    _enforce_local_api_key(request)
    uid = _resolve_user_or_401(user)
    profile_id = str((body or {}).get("profile_id") or "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    enable_cdp = bool((body or {}).get("enable_cdp", True))
    start_url = (body or {}).get("start_url")
    # Stash CDP preference on doc for launcher
    if enable_cdp:
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {"$set": {"local_api_cdp": True, "updated_at": _now_iso()}},
        )
    # Reuse launch_profile
    return await launch_profile(request, profile_id, start_url=start_url)


@router.get("/local/status/{profile_id}")
async def local_api_status(request: Request, profile_id: str):
    user = await _resolve_user(request)
    _enforce_local_api_key(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "ok": True,
        "profile_id": profile_id,
        "status": doc.get("status") or "idle",
        "session_id": doc.get("session_id") or "",
        "cdp_ws": doc.get("cdp_ws") or "",
        "debugger_address": doc.get("debugger_address") or "",
    }


@router.post("/local/stop")
async def local_api_stop(request: Request, body: Dict[str, Any] = Body(default_factory=dict)):
    await _resolve_user(request)
    _enforce_local_api_key(request)
    profile_id = str((body or {}).get("profile_id") or "").strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id required")
    return await stop_profile(request, profile_id)


# ── v2.7.17 — Multi-window Synchronizer ───────────────────────────────
@router.post("/sync/start")
async def sync_start(request: Request, body: SyncStartBody):
    """Start AdsPower-class multi-window sync (master → slaves via CDP)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    master = await _get_profile_for_user(body.master_id, uid, min_role="editor")
    if (master.get("status") or "") != "running":
        raise HTTPException(status_code=400, detail="Master profile must be running")
    from browser_profile_sync import resolve_cdp_for_profile, start_sync

    master_cdp = resolve_cdp_for_profile(body.master_id, master)
    if not master_cdp:
        raise HTTPException(
            status_code=400,
            detail="Master has no CDP endpoint — re-launch on local/native Krexion",
        )
    slave_cdps: Dict[str, str] = {}
    for sid in body.slave_ids or []:
        sdoc = await _get_profile_for_user(sid, uid, min_role="editor")
        if (sdoc.get("status") or "") != "running":
            raise HTTPException(status_code=400, detail=f"Slave {sid} must be running")
        cdp = resolve_cdp_for_profile(sid, sdoc)
        if not cdp:
            raise HTTPException(status_code=400, detail=f"Slave {sid} missing CDP — re-launch")
        slave_cdps[sid] = cdp
    try:
        result = await start_sync(
            user_id=uid,
            master_id=body.master_id,
            slave_ids=list(body.slave_ids or []),
            modes=list(body.modes or []),
            jitter=bool(body.jitter),
            master_cdp=master_cdp,
            slave_cdps=slave_cdps,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning(f"sync start failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync start failed: {e}")
    return result


@router.get("/sync/status")
async def sync_status_list(request: Request):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    from browser_profile_sync import list_syncs_for_user

    return {"syncs": list_syncs_for_user(uid)}


@router.get("/sync/{sync_id}")
async def sync_status_one(request: Request, sync_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    from browser_profile_sync import status_sync, _SYNC_GROUPS

    st = status_sync(sync_id)
    g = _SYNC_GROUPS.get(sync_id) or {}
    if not st.get("ok") or g.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="Sync not found")
    return st


@router.post("/sync/{sync_id}/stop")
async def sync_stop(request: Request, sync_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    from browser_profile_sync import stop_sync

    return await stop_sync(sync_id, user_id=uid)


@router.get("/cloud-phone/providers")
async def cloud_phone_providers(request: Request):
    """Partner + CPI BYO device options (ARM farm = partner URL)."""
    await _resolve_user(request)
    return {
        "providers": [
            {
                "id": "cpi",
                "name": "Krexion CPI device (BYO Android)",
                "kind": "byo_adb",
                "description": "Open profile URL on an online CPI worker Android via ADB am start",
            },
            {
                "id": "partner",
                "name": "Cloud Phone partner (Geelark / ARM farm)",
                "kind": "partner_url",
                "description": "Bind an external cloud-phone console URL / device id",
            },
            {
                "id": "none",
                "name": "None",
                "kind": "none",
                "description": "Clear cloud-phone binding",
            },
        ]
    }


@router.get("/templates")
async def list_profile_templates(request: Request):
    """List saved browser-profile create templates for the current user."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    items: List[Dict[str, Any]] = []
    cur = _DB.browser_profile_templates.find({"user_id": uid}).sort("updated_at", -1).limit(50)
    async for doc in cur:
        items.append({
            "id": doc.get("id"),
            "name": doc.get("name"),
            "settings": doc.get("settings") or {},
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "is_default": bool(doc.get("is_default")),
        })
    return {"templates": items}


@router.post("/templates")
async def save_profile_template(request: Request, body: SaveProfileTemplateBody):
    """Save create-form settings as a named template (one-click reuse)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    name = (body.name or "").strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="Template name required")
    settings = body.settings if isinstance(body.settings, dict) else {}
    tid = "bpt_" + secrets.token_hex(8)
    now = _now_iso()
    doc = {
        "id": tid,
        "user_id": uid,
        "name": name,
        "settings": settings,
        "created_at": now,
        "updated_at": now,
    }
    await _DB.browser_profile_templates.insert_one(doc)
    return {
        "ok": True,
        "template": {"id": tid, "name": name, "settings": settings, "created_at": now},
    }


@router.put("/templates/{template_id}")
async def update_profile_template(
    request: Request, template_id: str, body: UpdateProfileTemplateBody,
):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    if body.name and body.name.strip():
        patch["name"] = body.name.strip()[:80]
    if body.settings is not None and isinstance(body.settings, dict):
        patch["settings"] = body.settings
    res = await _DB.browser_profile_templates.update_one(
        {"id": template_id, "user_id": uid}, {"$set": patch},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    doc = await _DB.browser_profile_templates.find_one({"id": template_id, "user_id": uid})
    return {"ok": True, "template": {
        "id": doc.get("id"), "name": doc.get("name"), "settings": doc.get("settings") or {},
        "is_default": bool(doc.get("is_default")),
    }}


@router.post("/templates/{template_id}/default")
async def set_default_profile_template(request: Request, template_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profile_templates.find_one({"id": template_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    await _DB.browser_profile_templates.update_many(
        {"user_id": uid}, {"$set": {"is_default": False}},
    )
    await _DB.browser_profile_templates.update_one(
        {"id": template_id, "user_id": uid},
        {"$set": {"is_default": True, "updated_at": _now_iso()}},
    )
    return {"ok": True, "default_template_id": template_id}


@router.get("/templates/default")
async def get_default_profile_template(request: Request):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profile_templates.find_one({"user_id": uid, "is_default": True})
    if not doc:
        return {"template": None}
    return {"template": {
        "id": doc.get("id"), "name": doc.get("name"), "settings": doc.get("settings") or {},
    }}


@router.post("/import-vendors")
async def import_vendor_profiles(
    request: Request, body: Dict[str, Any] = Body(default_factory=dict),
):
    """Import profiles from AdsPower / GoLogin / Dolphin JSON exports."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    from browser_profile_import_vendors import parse_vendor_import_payload

    payload = body.get("data") or body.get("profiles") or body
    include_cookies = bool(body.get("include_cookies"))
    parsed = parse_vendor_import_payload(payload)
    if not parsed:
        raise HTTPException(status_code=400, detail="No recognizable vendor profiles in payload")
    created = 0
    for raw in parsed[:200]:
        try:
            pb = ProfileBody(
                name=str(raw.get("name") or "Imported")[:120],
                notes=str(raw.get("notes") or "")[:2000],
                country=str(raw.get("country") or "us")[:8],
                user_agent=str(raw.get("user_agent") or ""),
                viewport=raw.get("viewport") or {"width": 1920, "height": 1080},
                device_type=str(raw.get("device_type") or "desktop"),
                is_mobile=bool(raw.get("is_mobile")),
                has_touch=bool(raw.get("has_touch")),
                start_url=str(raw.get("start_url") or "https://www.google.com/")[:512],
                tags=list(raw.get("tags") or [])[:20],
                folder=str(raw.get("folder") or "")[:80],
            )
            doc = _profile_doc(uid, pb)
            if raw.get("proxy"):
                doc["proxy"] = {**(doc.get("proxy") or {}), **raw["proxy"]}
            if include_cookies and isinstance(raw.get("storage_state"), dict):
                doc["storage_state"] = raw["storage_state"]
            _prepare_proxy_for_profile_create(doc)
            await _DB.browser_profiles.insert_one(doc)
            created += 1
        except Exception as exc:
            logger.warning(f"vendor import row skipped: {exc}")
    return {"created": created, "parsed": len(parsed)}


@router.delete("/templates/{template_id}")
async def delete_profile_template(request: Request, template_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    res = await _DB.browser_profile_templates.delete_one({"id": template_id, "user_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True, "id": template_id}


@router.get("/{profile_id}")
async def get_profile(request: Request, profile_id: str):
    """Get one profile (owned or ACL-shared)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="viewer")
    return {"profile": _public_view_for(doc, uid)}


@router.get("/{profile_id}/acl")
async def get_profile_acl(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="viewer")
    return {
        "profile_id": profile_id,
        "owner_user_id": doc.get("user_id"),
        "acl": _acl_entries(doc),
        "my_role": _role_for_user(doc, uid),
    }


@router.post("/{profile_id}/acl")
async def grant_profile_acl(request: Request, profile_id: str, body: AclGrantBody):
    """Grant live team access (viewer|editor|admin) without cloning."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="admin")
    email = (body.target_email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid target_email required")
    target = await _DB.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if not target or not target.get("id"):
        raise HTTPException(status_code=404, detail="Target user not found")
    target_uid = target["id"]
    if target_uid == doc.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot ACL-grant the owner")
    role_in = (body.role or "").strip().lower()
    if role_in not in ("viewer", "editor", "admin"):
        raise HTTPException(
            status_code=400,
            detail="role must be one of: viewer, editor, admin",
        )
    role = _normalize_role(role_in)
    entries = [e for e in _acl_entries(doc) if e.get("user_id") != target_uid]
    entries.append({
        "user_id": target_uid,
        "email": email,
        "role": role,
        "added_at": _now_iso(),
    })
    await _DB.browser_profiles.update_one(
        {"id": profile_id},
        {"$set": {"acl": entries, "updated_at": _now_iso()}},
    )
    return {"ok": True, "acl": entries}


@router.delete("/{profile_id}/acl")
async def revoke_profile_acl(request: Request, profile_id: str, body: AclRevokeBody = Body(...)):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    await _get_profile_for_user(profile_id, uid, min_role="admin")
    email = (body.target_email or "").strip().lower()
    tid = (body.user_id or "").strip()
    doc = await _DB.browser_profiles.find_one({"id": profile_id})
    entries = _acl_entries(doc or {})
    kept = []
    for e in entries:
        if tid and e.get("user_id") == tid:
            continue
        if email and e.get("email") == email:
            continue
        kept.append(e)
    await _DB.browser_profiles.update_one(
        {"id": profile_id},
        {"$set": {"acl": kept, "updated_at": _now_iso()}},
    )
    return {"ok": True, "acl": kept}


@router.post("/{profile_id}/cloud-phone")
async def bind_cloud_phone(request: Request, profile_id: str, body: CloudPhoneBindBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    await _get_profile_for_user(profile_id, uid, min_role="editor")
    provider = (body.provider or "none").strip().lower()
    if provider not in ("partner", "cpi", "none"):
        raise HTTPException(status_code=400, detail="provider must be partner|cpi|none")
    binding: Dict[str, Any] = {}
    if provider != "none":
        binding = {
            "provider": provider,
            "partner_url": (body.partner_url or "").strip()[:512],
            "external_id": (body.external_id or "").strip()[:120],
            "device_id": (body.device_id or "").strip()[:80],
            "label": (body.label or "").strip()[:120],
            "bound_at": _now_iso(),
        }
    await _DB.browser_profiles.update_one(
        {"id": profile_id},
        {"$set": {"cloud_phone": binding, "updated_at": _now_iso()}},
    )
    return {
        "ok": True,
        "cloud_phone": binding,
        "capabilities": {
            "url_open": provider == "cpi",
            "binding_only": provider == "partner",
            "remote_control": False,
        },
        "note": (
            "Cloud Phone binds a device URL or CPI Android id for URL opens — "
            "not full remote control like AdsPower. Use Open on Device for queued navigation."
        ),
    }


@router.post("/{profile_id}/open-on-device")
async def open_profile_on_cpi_device(request: Request, profile_id: str, body: OpenOnDeviceBody):
    """Queue URL open on CPI Android (worker picks up needs_action).

    v2.7.21 — if device_id empty/offline, auto-pick first online android_* device.
    """
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    url = (body.url or doc.get("start_url") or "https://www.google.com/").strip()[:1024]
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="url must be http(s)")

    device = None
    wanted = (body.device_id or "").strip()
    if not wanted:
        # Prefer already-bound CPI device
        bound = (doc.get("cloud_phone") or {}).get("device_id") or ""
        if bound:
            wanted = str(bound).strip()

    if wanted:
        device = await _DB.cpi_devices.find_one({"id": wanted, "user_id": uid})
        if not device:
            device = await _DB.cpi_devices.find_one({"device_id": wanted, "user_id": uid})
        if device and device.get("status") == "offline" and body.auto_fallback:
            device = None  # fall through to online pick

    if not device:
        # Auto-pick best online Android
        cur = _DB.cpi_devices.find(
            {
                "user_id": uid,
                "device_type": {"$regex": "^android_"},
                "status": {"$in": ["online", "busy"]},
            },
            {"_id": 0},
        ).sort("last_heartbeat", -1).limit(1)
        async for d in cur:
            device = d
            break
    if not device:
        # Last resort: any android device for this user
        device = await _DB.cpi_devices.find_one(
            {"user_id": uid, "device_type": {"$regex": "^android_"}},
            {"_id": 0},
        )
    if not device:
        raise HTTPException(
            status_code=404,
            detail="No Krexion Android online — Enable Krexion Android on CPI Devices first",
        )

    action = {
        "type": "open_url",
        "url": url,
        "profile_id": profile_id,
        "queued_at": _now_iso(),
    }
    await _DB.cpi_devices.update_one(
        {"id": device["id"]},
        {"$set": {"needs_action": action, "updated_at": _now_iso()}},
    )
    await _DB.browser_profiles.update_one(
        {"id": profile_id},
        {"$set": {
            "cloud_phone": {
                "provider": "cpi",
                "device_id": device["id"],
                "label": device.get("label") or "",
                "last_open_url": url,
                "bound_at": _now_iso(),
            },
            "updated_at": _now_iso(),
        }},
    )
    return {
        "ok": True,
        "device_id": device["id"],
        "device_label": device.get("label") or "",
        "device_status": device.get("status") or "",
        "needs_action": action,
        "url": url,
        "auto_picked": not bool((body.device_id or "").strip()),
    }


@router.get("/{profile_id}/audit")
async def profile_audit_log(
    request: Request,
    profile_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Profile run history — lead rows consumed, sessions, automation events."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    await _get_profile_for_user(profile_id, uid, min_role="viewer")
    try:
        from browser_profile_audit import list_profile_audit

        rows = await list_profile_audit(_DB, uid, profile_id, limit=limit)
    except Exception as exc:
        logger.warning(f"[profile-audit] list failed: {exc}")
        rows = []
    return {"profile_id": profile_id, "events": rows, "count": len(rows)}


@router.get("/{profile_id}/cookies")
async def export_cookies(request: Request, profile_id: str):
    """Export Playwright storage_state cookies (+ origins). Owner-only."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="viewer")
    if str(doc.get("user_id") or "") != str(uid):
        raise HTTPException(status_code=403, detail="Cookie export is owner-only for shared profiles")
    ss = doc.get("storage_state") or {}
    return {
        "profile_id": profile_id,
        "storage_state": {
            "cookies": ss.get("cookies") or [],
            "origins": ss.get("origins") or [],
        },
        "cookie_count": len(ss.get("cookies") or []),
        "synced_at": doc.get("storage_synced_at") or "",
    }


@router.put("/{profile_id}/cookies")
async def import_cookies(request: Request, profile_id: str, body: CookieImportBody):
    """Import cookies (replace or merge). Owner-only — matches export ACL."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    # Use ACL helper so shared users get 403 (not misleading 404), then
    # require ownership — same policy as cookie export.
    doc = await _get_profile_for_user(profile_id, uid, min_role="viewer")
    if str(doc.get("user_id") or "") != str(uid):
        raise HTTPException(
            status_code=403,
            detail="Cookie import is owner-only for shared profiles",
        )
    existing = dict(doc.get("storage_state") or {})
    cookies: List[Dict[str, Any]] = []
    origins = list(existing.get("origins") or [])
    raw_input_count = 0
    if body.storage_state and isinstance(body.storage_state, dict):
        _raw = body.storage_state.get("cookies") or []
        raw_input_count = len(_raw) if isinstance(_raw, list) else 0
        cookies = _normalize_cookie_list(_raw)
        if "origins" in body.storage_state and isinstance(body.storage_state.get("origins"), list):
            origins = body.storage_state["origins"]
    elif body.cookies:
        raw_input_count = len(body.cookies)
        cookies = _normalize_cookie_list(body.cookies)
    elif body.netscape:
        _parsed = _parse_netscape_cookies(body.netscape)
        raw_input_count = len(_parsed)
        cookies = _normalize_cookie_list(_parsed)
        if body.netscape.strip() and not _parsed:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not parse any cookies from the pasted text. "
                    "Expecting Netscape/curl cookie format (7 tab- or "
                    "space-separated fields per line)."
                ),
            )
    else:
        raise HTTPException(status_code=400, detail="Provide storage_state, cookies, or netscape text")
    # Guard: a non-empty source that normalised to zero valid cookies must
    # NOT silently wipe existing cookies in replace mode (data-loss bug).
    if (
        raw_input_count > 0
        and not cookies
        and not body.merge
        and (existing.get("cookies") or [])
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "None of the provided cookies were valid — refusing to "
                "overwrite existing cookies. Check the format and try again."
            ),
        )
    if body.merge:
        by_key = {}
        for c in (existing.get("cookies") or []) + cookies:
            if not isinstance(c, dict):
                continue
            key = (c.get("domain"), c.get("path"), c.get("name"))
            by_key[key] = c
        cookies = list(by_key.values())
    new_ss = {"cookies": cookies, "origins": origins}
    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {
            "$set": {
                "storage_state": new_ss,
                "storage_synced_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        },
    )
    return {"ok": True, "cookie_count": len(cookies), "origin_count": len(origins)}


@router.get("/{profile_id}/fingerprint")
async def fingerprint_preview(request: Request, profile_id: str):
    """Coherence panel data from stored profile fields — no browser launch."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="viewer")
    pub = _public_view(doc)
    anti = doc.get("anti_detect") or {}
    if not isinstance(anti, dict):
        anti = {}
    ua = str(doc.get("user_agent") or "")
    webgl_preview: Dict[str, Any] = {}
    try:
        from anti_detect_v230 import align_webgl_to_ua_deterministic as _align_webgl
        webgl_preview = _align_webgl(ua, profile_id) or {}
    except Exception:
        webgl_preview = {
            "vendor": anti.get("webgl_vendor") or "",
            "renderer": anti.get("webgl_renderer") or "",
        }
    ss = doc.get("storage_state") or {}
    cookie_stats = {
        "has_cookies": bool(ss.get("cookies")),
        "cookie_count": len(ss.get("cookies") or []),
        "origin_count": len(ss.get("origins") or []),
        "synced_at": doc.get("storage_synced_at") or "",
    }
    running = str(doc.get("status") or "") in ("running", "launching")
    return {
        "ok": True,
        "profile_id": profile_id,
        "fingerprint_short": pub.get("fingerprint_short") or "",
        "fingerprint_hash": str(doc.get("fingerprint_hash") or "")[:128],
        "last_proxy_check": doc.get("last_proxy_check") or {},
        "last_tls_prewarm_ok": doc.get("last_tls_prewarm_ok"),
        "storage_synced_at": doc.get("storage_synced_at") or "",
        "cookie_stats": cookie_stats,
        "cdp_ws": (doc.get("cdp_ws") or "") if running else "",
        "status": doc.get("status") or "idle",
        "anti_detect": {
            "master": bool(anti.get("master", True)),
            "tls_prewarm": bool(anti.get("tls_prewarm", True)),
            "canvas_mode": str(anti.get("canvas_mode") or "noise"),
            "webgl_mode": str(anti.get("webgl_mode") or "noise"),
            "audio_mode": str(anti.get("audio_mode") or "noise"),
            "font_mode": str(anti.get("font_mode") or "noise"),
            "webrtc_mode": str(anti.get("webrtc_mode") or "proxy"),
            "use_persistent_context": bool(anti.get("use_persistent_context", True)),
            "proxy_check_on_launch": bool(anti.get("proxy_check_on_launch", True)),
            "proxy_check_block_on_fail": bool(anti.get("proxy_check_block_on_fail", True)),
            "browser_kernel": str(anti.get("browser_kernel") or "auto"),
            "fingerprint_win": bool(anti.get("fingerprint_win", True)),
            "fingerprint_win_prefer_real": bool(anti.get("fingerprint_win_prefer_real", True)),
        },
        "preview": {
            "user_agent": ua,
            "os": doc.get("os") or "",
            "timezone": doc.get("timezone") or "",
            "locale": doc.get("locale") or doc.get("language") or "",
            "geo_follow_proxy": bool(doc.get("geo_follow_proxy", True)),
            "viewport": doc.get("viewport") or {},
            "webgl_vendor": webgl_preview.get("vendor") or "",
            "webgl_renderer": webgl_preview.get("renderer") or "",
            "gpu_family": webgl_preview.get("gpu_family") or "",
            "fingerprint_salt": str(doc.get("fingerprint_salt") or "")[:32],
        },
    }


@router.post("/{profile_id}/fingerprint/refresh")
async def fingerprint_refresh(request: Request, profile_id: str):
    """Rotate fingerprint salt so next launch gets a new CreepJS-class identity.

    Keeps cookies/storage; clears stored fingerprint_hash so UI shows fresh
    short hash after relaunch. Desktop/native launch uses the new salt.
    """
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    new_salt = secrets.token_hex(8)
    await _DB.browser_profiles.update_one(
        {"id": profile_id},
        {
            "$set": {
                "fingerprint_salt": new_salt,
                "fingerprint_hash": "",
                "fingerprint_refreshed_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        },
    )
    return {
        "ok": True,
        "profile_id": profile_id,
        "fingerprint_salt": new_salt,
        "fingerprint_short": "",
        "message": "Fingerprint rotated — relaunch profile to apply",
    }


@router.post("/{profile_id}/cookie-robot")
async def cookie_robot(request: Request, profile_id: str, body: CookieRobotBody = Body(default_factory=CookieRobotBody)):
    """Warm cookies via short stealth visits — local/native/desktop only."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    mode = (os.environ.get("KREXION_MODE") or "").lower()
    if mode not in ("native", "local", "desktop"):
        raise HTTPException(
            status_code=501,
            detail="Cookie robot requires desktop/native mode — use Krexion Desktop",
        )
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        from browser_profile_launcher import warm_profile_cookies
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Launcher unavailable: {e}") from e
    profile_config = dict(doc)
    profile_config.pop("_id", None)
    result = await warm_profile_cookies(
        profile_config,
        urls=body.urls,
        max_urls=int(body.max_urls or 5),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=str(result.get("error") or "cookie robot failed")[:300])
    ss = result.get("storage_state") or {}
    if isinstance(ss, dict) and (ss.get("cookies") or ss.get("origins")):
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {
                "$set": {
                    "storage_state": ss,
                    "storage_synced_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            },
        )
    return {
        "ok": True,
        "profile_id": profile_id,
        "visited": result.get("visited") or [],
        "cookie_count": len((ss.get("cookies") or [])),
        "origin_count": len((ss.get("origins") or [])),
        "storage_synced_at": _now_iso(),
    }


@router.delete("/{profile_id}/cookies")
async def clear_cookies(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    res = await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {
            "$set": {
                "storage_state": {},
                "storage_synced_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        },
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True, "cleared": True}


@router.post("/{profile_id}/refresh-proxy")
async def refresh_profile_proxy(request: Request, profile_id: str):
    """Rotate provider/proxyjet line or re-probe manual proxy; clears launch error."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    if str(doc.get("user_id") or uid) != uid:
        raise HTTPException(status_code=403, detail="Only the profile owner can refresh proxy")
    cur_status = str(doc.get("status") or "idle").lower()
    if cur_status in ("running", "launching", "stopping", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Profile is {cur_status}. Stop it before rotating proxy.",
        )
    proxy = dict(doc.get("proxy") or {})
    if not proxy_is_active(proxy):
        raise HTTPException(status_code=400, detail="Profile has no proxy configured")
    patch_doc = dict(doc)
    proxy.pop("exit_ip", None)
    patch_doc["exit_ip"] = ""
    provider_id = str(proxy.get("provider_id") or "").strip()
    use_proxyjet = bool(proxy.get("use_proxyjet"))
    # v2.7.113 — Manual rotating: rotate sessid in-place (keep host:port).
    # Provider/ProxyJet: clear sticky create sessid and re-allocate.
    if provider_id or use_proxyjet:
        proxy.pop("raw_line", None)
        proxy.pop("raw", None)
        proxy["server"] = ""
        proxy["username"] = ""
        patch_doc["proxy"] = await resolve_profile_proxy_for_launch(
            uid, user, proxy, profile_country=patch_doc.get("country"),
        )
    elif _is_rotating_gateway_proxy(proxy):
        proxy = hydrate_proxy_credentials(proxy)
        proxy = _rotate_manual_proxy_session(proxy)
        patch_doc["proxy"] = await resolve_profile_proxy_for_launch(
            uid, user, proxy, profile_country=patch_doc.get("country"),
        )
    else:
        patch_doc["proxy"] = proxy
    used = await _load_team_profile_used_ips(uid)
    try:
        from cross_user_ip_isolation import canonicalize_ip
        cur = canonicalize_ip(doc.get("exit_ip") or "")
        if cur:
            used.discard(cur)
    except Exception:
        pass
    await _finalize_doc_proxy_and_ip(uid, user, patch_doc, used)
    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {
            "$set": {
                "proxy": patch_doc["proxy"],
                "exit_ip": patch_doc.get("exit_ip") or "",
                "status": "idle",
                "last_error": "",
                "updated_at": _now_iso(),
            }
        },
    )
    updated = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    return {
        "ok": True,
        "profile": _public_view(updated or {}),
        "exit_ip": patch_doc.get("exit_ip") or "",
    }


@router.post("/{profile_id}/check-proxy")
async def check_proxy(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    owner_uid = str(doc.get("user_id") or uid)
    result = await _probe_profile_proxy(doc, user)
    patch: Dict[str, Any] = {"last_proxy_check": result, "updated_at": _now_iso()}
    exit_ip = str(result.get("exit_ip") or "").strip()
    if exit_ip:
        used = await _load_team_profile_used_ips(owner_uid)
        try:
            from cross_user_ip_isolation import canonicalize_ip
            cur = canonicalize_ip(doc.get("exit_ip") or "")
            if cur:
                used.discard(cur)
        except Exception:
            pass
        try:
            canonical = await _assert_unique_team_profile_ip(
                owner_uid, exit_ip, used, profile_id=profile_id,
            )
            patch["exit_ip"] = canonical
            patch["proxy.exit_ip"] = canonical
            patch["proxy.sticky_session"] = True
        except HTTPException as exc:
            result["duplicate_ip"] = True
            result["error"] = str(exc.detail)
            patch["last_proxy_check"] = result
    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": owner_uid},
        {"$set": patch},
    )
    return result


@router.post("/{profile_id}/share")
async def share_profile(request: Request, profile_id: str, body: ShareProfileBody):
    """Light team share: clone profile into another user account by email."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    email = (body.target_email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid target_email required")
    target = await _DB.users.find_one({"email": email})
    if not target and hasattr(_DB, "customers"):
        target = await _DB.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if not target:
        # Try case-insensitive
        target = await _DB.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if not target or not target.get("id"):
        raise HTTPException(status_code=404, detail="Target user not found")
    target_uid = target["id"]
    if target_uid == uid:
        raise HTTPException(status_code=400, detail="Cannot share to yourself — use Clone")
    new_doc = dict(doc)
    new_doc.pop("_id", None)
    new_doc["id"] = str(uuid.uuid4())
    new_doc["user_id"] = target_uid
    new_doc["name"] = (doc.get("name") or "Profile") + f" (from {user.get('email') or 'team'})"
    if not body.include_cookies:
        new_doc["storage_state"] = {}
        new_doc["storage_synced_at"] = ""
    new_doc["fingerprint_hash"] = ""
    new_doc["total_launches"] = 0
    new_doc["last_launched_at"] = ""
    new_doc["status"] = "idle"
    new_doc["session_id"] = ""
    new_doc["cdp_ws"] = ""
    new_doc["shared_from_user_id"] = uid
    new_doc["created_at"] = _now_iso()
    new_doc["updated_at"] = _now_iso()
    await _DB.browser_profiles.insert_one(new_doc)
    return {"ok": True, "id": new_doc["id"], "target_email": email}


@router.put("/{profile_id}")
async def update_profile(request: Request, profile_id: str, body: ProfileBody):
    """Update an existing profile's config (does NOT touch storage_state)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    existing = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")
    new_doc = _profile_doc(uid, body)
    new_doc["id"] = existing["id"]
    new_doc["created_at"] = existing["created_at"]
    new_doc["storage_state"] = existing.get("storage_state") or {}
    new_doc["total_launches"] = existing.get("total_launches", 0)
    new_doc["last_launched_at"] = existing.get("last_launched_at", "")
    new_doc["fingerprint_hash"] = existing.get("fingerprint_hash", "")
    # v2.6.32 — Preserve live session fields so editing a running profile
    # doesn't orphan the headed browser or break Stop.
    new_doc["session_id"] = existing.get("session_id") or ""
    new_doc["status"] = existing.get("status") or "idle"
    new_doc["last_session_duration_sec"] = existing.get("last_session_duration_sec", 0)
    new_doc["last_error"] = existing.get("last_error", "")
    new_doc["storage_synced_at"] = existing.get("storage_synced_at", "")
    new_doc["last_proxy_check"] = existing.get("last_proxy_check") or {}
    new_doc["exit_ip"] = existing.get("exit_ip") or ""
    new_doc["cdp_ws"] = existing.get("cdp_ws") or ""
    new_doc["updated_at"] = _now_iso()
    # Password redact on GET means edit forms send password="". Keep prior
    # secret unless the operator typed a new one.
    _proxy = dict(new_doc.get("proxy") or {})
    _old_proxy = dict(existing.get("proxy") or {})
    if not str(_proxy.get("password") or "").strip() and str(_old_proxy.get("password") or "").strip():
        _proxy["password"] = _old_proxy["password"]
    if not str(_proxy.get("raw_line") or "").strip() and str(_old_proxy.get("raw_line") or "").strip():
        _proxy["raw_line"] = _old_proxy["raw_line"]
    new_doc["proxy"] = _proxy
    _wants_proxy = proxy_is_active(_proxy)
    if _wants_proxy and not str(_proxy.get("server") or "").strip():
        _used = await _load_team_profile_used_ips(uid)
        try:
            from cross_user_ip_isolation import canonicalize_ip
            cur = canonicalize_ip(existing.get("exit_ip") or "")
            if cur:
                _used.discard(cur)
        except Exception:
            pass
        new_doc["proxy"] = await resolve_profile_proxy_for_launch(
            uid, user, _proxy, profile_country=new_doc.get("country"),
        )
        await _finalize_doc_proxy_and_ip(uid, user, new_doc, _used)
    elif _wants_proxy and str(_proxy.get("server") or "").strip():
        _old_srv = str((existing.get("proxy") or {}).get("server") or "")
        _new_srv = str(_proxy.get("server") or "")
        if _old_srv != _new_srv or not new_doc.get("exit_ip"):
            _used = await _load_team_profile_used_ips(uid)
            try:
                from cross_user_ip_isolation import canonicalize_ip
                cur = canonicalize_ip(existing.get("exit_ip") or "")
                if cur:
                    _used.discard(cur)
            except Exception:
                pass
            try:
                await _finalize_doc_proxy_and_ip(uid, user, new_doc, _used)
            except HTTPException:
                raise
    await _DB.browser_profiles.replace_one({"id": profile_id, "user_id": uid}, new_doc)
    return {"profile": _public_view(new_doc)}


@router.delete("/{profile_id}")
async def delete_profile(request: Request, profile_id: str, permanent: bool = Query(default=False)):
    """Soft-delete a profile (recycle bin). Use permanent=true to hard-delete."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    if permanent:
        res = await _DB.browser_profiles.delete_one({"id": profile_id, "user_id": uid})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Profile not found")
        await _DB.browser_profile_sessions.delete_many({"profile_id": profile_id, "user_id": uid})
        return {"deleted": True, "permanent": True}
    res = await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid, **_not_deleted_filter()},
        {"$set": {"deleted_at": _now_iso(), "status": "idle", "session_id": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    await _DB.browser_profile_sessions.update_many(
        {"profile_id": profile_id, "user_id": uid},
        {"$set": {"status": "cancelled"}},
    )
    return {"deleted": True, "soft": True}


@router.post("/{profile_id}/restore")
async def restore_profile(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    res = await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {"deleted_at": "", "updated_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    return {"restored": True, "profile": _public_view(doc or {})}


@router.get("/{profile_id}/launch-preview")
async def launch_preview(request: Request, profile_id: str):
    """Pre-launch checklist data for UI."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    view = _public_view(doc)
    health = view.get("health") or {}
    proxy = doc.get("proxy") or {}
    return {
        "profile_id": profile_id,
        "name": doc.get("name"),
        "start_url": doc.get("start_url") or "https://www.google.com/",
        "health": health,
        "exit_ip": view.get("exit_ip") or "",
        "cookie_count": (view.get("storage_state_stats") or {}).get("cookie_count") or 0,
        "proxy_enabled": proxy_is_active(proxy),
        "strict_proxy": bool(view.get("strict_proxy")),
        "strict_mobile_shell": bool(view.get("strict_mobile_shell")),
        "proxy_check_age_hours": view.get("proxy_check_age_hours"),
        "proxy_check_stale": bool(view.get("proxy_check_stale")),
        "is_mobile": bool(doc.get("is_mobile")),
        "os": str(doc.get("os") or ""),
        "mobile_shell_active": bool(view.get("mobile_shell_active")),
        "mobile_shell_embedded": bool(view.get("mobile_shell_embedded")),
        "device": doc.get("device_model") or doc.get("device_type") or "",
        "last_proxy_check": view.get("last_proxy_check") or {},
        "ready": health.get("level") in ("good", "warn", "unknown"),
        "default_automation_upload_id": str(doc.get("default_automation_upload_id") or ""),
        "default_data_file_id": str(doc.get("default_data_file_id") or ""),
        "launch_warnings": list(view.get("launch_warnings") or []),
        "engine_used": str(view.get("engine_used") or ""),
    }

@router.post("/{profile_id}/clone")
async def clone_profile(
    request: Request,
    profile_id: str,
    body: CloneOptsBody = Body(default_factory=CloneOptsBody),
):
    """Duplicate a profile with a new id + ' (copy)' suffix."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    existing = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")
    new_doc = dict(existing)
    new_doc.pop("_id", None)
    new_doc["id"] = str(uuid.uuid4())
    new_doc["name"] = (existing.get("name") or "Profile") + " (copy)"
    if body and body.include_cookies:
        new_doc["storage_state"] = dict(existing.get("storage_state") or {})
        new_doc["storage_synced_at"] = existing.get("storage_synced_at") or ""
    else:
        new_doc["storage_state"] = {}
        new_doc["storage_synced_at"] = ""
    new_doc["fingerprint_hash"] = ""
    new_doc["total_launches"] = 0
    new_doc["last_launched_at"] = ""
    new_doc["status"] = "idle"
    new_doc["session_id"] = ""
    new_doc["cdp_ws"] = ""
    new_doc["exit_ip"] = ""
    if isinstance(new_doc.get("proxy"), dict):
        new_doc["proxy"].pop("exit_ip", None)
    new_doc["created_at"] = _now_iso()
    new_doc["updated_at"] = _now_iso()
    new_doc["deleted_at"] = ""
    proxy = new_doc.get("proxy") or {}
    if body and body.fresh_ua:
        try:
            is_mob = bool(new_doc.get("is_mobile"))
            plat = "android" if str(new_doc.get("os") or "").lower() == "android" else (
                "ios" if is_mob else "desktop"
            )
            uas = await _generate_uas_batch(
                user, count=1, platform=plat,
                app="browser", brand=None,
                region=str(new_doc.get("country") or "US").upper(),
                is_mobile=is_mob,
            )
            if uas:
                new_doc["user_agent"] = uas[0]
        except Exception as _ua_err:
            logger.debug(f"clone fresh_ua skipped: {_ua_err}")
    if body and body.fresh_proxy and (
        str(proxy.get("provider_id") or "").strip() or str(proxy.get("server") or "").strip()
    ):
        _prepare_proxy_for_profile_create(new_doc)
    await _DB.browser_profiles.insert_one(new_doc)
    return {"profile": _public_view(new_doc), "id": new_doc["id"]}


@router.post("/{profile_id}/launch")
async def launch_profile(
    request: Request,
    profile_id: str,
    body: LaunchBody = Body(default_factory=LaunchBody),
    *,
    _bulk_row_index: Optional[int] = None,
):
    """Queue a launch job for the customer's local desktop client."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    owner_uid = str(doc.get("user_id") or uid)

    cur_status = str(doc.get("status") or "idle").lower()
    if cur_status in ("running", "launching", "stopping", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Profile is already {cur_status}. Stop it first or wait for the current session to finish.",
        )

    start_url = (body.start_url if body else None) or doc.get("start_url") or "https://www.google.com/"

    auto_payload = None
    if body and body.automation:
        auto_payload = body.automation.model_dump()
    auto_spec: Dict[str, Any] = {"enabled": False}
    try:
        from browser_profile_automation import resolve_launch_automation

        auto_spec = await resolve_launch_automation(
            _DB,
            uid,
            auto_payload,
            doc,
            bulk_row_index=_bulk_row_index,
            claim_next=(
                True
                if _bulk_row_index is not None
                else bool((auto_payload or {}).get("claim_next"))
            ),
        )
    except ValueError as _auto_err:
        raise HTTPException(status_code=400, detail=str(_auto_err)) from _auto_err
    except Exception as _auto_exc:
        logger.warning(f"[browser-profile launch] automation resolve skipped: {_auto_exc}")

    if auto_payload and auto_payload.get("save_as_default"):
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {"$set": {
                "default_automation_upload_id": str(auto_spec.get("automation_upload_id") or ""),
                "default_data_file_id": str(auto_spec.get("data_file_id") or ""),
                "updated_at": _now_iso(),
            }},
        )

    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "profile_id": profile_id,
        "user_id": owner_uid,
        "started_at": _now_iso(),
        "status": "queued",
        "start_url": start_url,
        "automation_enabled": bool(auto_spec.get("enabled")),
        "automation_upload_id": str(auto_spec.get("automation_upload_id") or ""),
        "automation_total_steps": int(auto_spec.get("total_steps") or 0),
    }
    # v2.7.37 — Resolve proxy + probe team-unique exit IP before every launch.
    _proxy_cfg = doc.get("proxy") or {}
    _provider_id = str(_proxy_cfg.get("provider_id") or "").strip()
    try:
        if auto_spec.get("enabled") and str(auto_spec.get("proxy_upload_id") or "").strip():
            await _apply_json_run_proxy_from_upload(uid, user, doc, auto_spec)
            _proxy_cfg = doc.get("proxy") or {}
        else:
            _proxy_cfg = await _ensure_profile_launch_proxy(
                uid, user, doc, profile_country=doc.get("country"),
            )
            doc["proxy"] = _proxy_cfg
    except HTTPException:
        raise
    except Exception as _pp_err:
        logger.warning(f"[browser-profile launch] proxy ensure failed: {_pp_err}")
        raise HTTPException(
            status_code=502,
            detail=f"Proxy setup failed before launch: {_pp_err}",
        ) from _pp_err

    _ua_upload = str((auto_payload or {}).get("ua_upload_id") or "").strip()
    if _ua_upload:
        try:
            await _apply_launch_ua_from_upload(uid, doc, _ua_upload)
        except HTTPException:
            raise
        except Exception as _ua_exc:
            logger.warning(f"[browser-profile launch] ua upload apply skipped: {_ua_exc}")

    _proxy_patch: Dict[str, Any] = {
        "proxy": _proxy_cfg,
        "exit_ip": doc.get("exit_ip") or "",
        "updated_at": _now_iso(),
    }

    if str(_proxy_cfg.get("server") or "").strip():
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": owner_uid},
            {"$set": _proxy_patch},
        )
    elif (
        _proxy_cfg.get("enabled")
        or _provider_id
        or _proxy_cfg.get("use_proxyjet")
    ):
        raise HTTPException(
            status_code=502,
            detail=(
                "Proxy is enabled but no server URL could be resolved. "
                "Open Settings → Proxy Providers, verify credentials, then "
                "edit the profile and save again (or pick a different country/state)."
            ),
        )

    doc = dict(doc)
    doc["_launch_automation"] = auto_spec
    doc["user_id"] = owner_uid
    if auto_spec.get("enabled"):
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {"$set": {
                "automation_status": "queued",
                "automation_step": 0,
                "automation_total_steps": int(auto_spec.get("total_steps") or 0),
                "automation_error": "",
            }},
        )

    await _DB.browser_profile_sessions.insert_one(session)

    try:
        from browser_profile_audit import log_profile_event

        await log_profile_event(
            _DB,
            user_id=uid,
            profile_id=profile_id,
            session_id=session_id,
            event_type="session_start",
            detail={
                "start_url": start_url,
                "automation_enabled": bool(auto_spec.get("enabled")),
                "lead_row_index": auto_spec.get("lead_row_index"),
                "data_file_id": str(auto_spec.get("data_file_id") or ""),
                "bulk_row_index": _bulk_row_index,
            },
        )
    except Exception as _audit_err:
        logger.debug(f"[profile-audit] session_start skipped: {_audit_err}")

    if doc.get("_consume_ua_upload_id") and doc.get("_consume_ua_raw"):
        try:
            await _consume_ua_line_from_upload(
                uid,
                str(doc.get("_consume_ua_upload_id") or ""),
                str(doc.get("_consume_ua_raw") or ""),
            )
        except Exception as _uac_err:
            logger.debug(f"[profile-launch] ua consume skipped: {_uac_err}")

    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {"status": "launching", "session_id": session_id,
                  "last_launched_at": _now_iso()},
         "$inc": {"total_launches": 1}},
    )

    bridge_job_id: Optional[str] = None
    desktop_available = False
    launch_message = ""

    # Local desktop install (Electron + Inno Native + User-Package) must
    # launch in-process / via tray queue — NOT the cloud bridge. Prior
    # bug: only KREXION_MODE=native was treated as local, so `local`
    # installs enqueued orphan bridge jobs and cards stuck on "launching".
    _mode = (os.environ.get("KREXION_MODE") or "cloud").lower().strip()
    _is_local_desktop = _mode in ("native", "local")
    if _is_local_desktop:
        try:
            from browser_profile_launcher import launch_profile_session

            # v2.7.17 — enable CDP by default so Synchronizer / Local API can attach
            doc = dict(doc)
            doc["local_api_cdp"] = True
            doc["_launch_automation"] = auto_spec
            doc["user_id"] = owner_uid
            await _DB.browser_profiles.update_one(
                {"id": profile_id},
                {"$set": {"local_api_cdp": True}},
            )

            async def _on_update(body: dict):
                try:
                    await _mirror_profile_session(owner_uid, profile_id, session_id, body)
                    patch: Dict[str, Any] = {}
                    if body.get("storage_state") and isinstance(body["storage_state"], dict):
                        patch["storage_state"] = body["storage_state"]
                        patch["storage_synced_at"] = _now_iso()
                    if body.get("fingerprint_hash"):
                        patch["fingerprint_hash"] = str(body["fingerprint_hash"])[:128]
                    if body.get("duration_sec") is not None:
                        try:
                            patch["last_session_duration_sec"] = float(body["duration_sec"])
                        except Exception:
                            pass
                    if patch:
                        await _DB.browser_profiles.update_one(
                            {"id": profile_id},
                            {"$set": patch},
                        )
                except Exception as e:
                    logger.debug(f"local on_update failed: {e}")

            async def _run_local_launch():
                try:
                    await launch_profile_session(
                        doc,
                        session_id=session_id,
                        start_url=session["start_url"],
                        on_session_update=_on_update,
                    )
                except Exception as _launch_exc:  # noqa: BLE001
                    logger.warning(
                        f"local browser-profile session crashed: {_launch_exc}"
                    )
                    try:
                        await _on_update({
                            "profile_id": profile_id,
                            "session_id": session_id,
                            "status": "error",
                            "error_message": str(_launch_exc)[:512],
                        })
                    except Exception:
                        pass

            # Fire-and-forget the headed browser. The launcher blocks for
            # the lifetime of the user's manual browsing session, so we
            # MUST background it — otherwise the HTTP request would hang
            # until the user closes Chromium.
            asyncio.create_task(_run_local_launch())
            desktop_available = True
            bridge_job_id = f"local:{session_id}"
            launch_message = (
                "Opening Chromium on this PC — if nothing appears in ~1 minute, "
                "open the Krexion tray icon and click Launch again."
            )
        except Exception as e:
            logger.warning(f"local browser-profile launch failed: {e}")
            # Don't fall through to the bridge on the local desktop —
            # the bridge_enqueue would return None (no PC to relay to)
            # and the user would see the misleading "install" toast.
            desktop_available = False
            _local_err = (
                f"Could not start browser on this PC: {e}. "
                "Restart Krexion Local Engine / tray, then Launch again."
            )[:512]
            await _DB.browser_profiles.update_one(
                {"id": profile_id, "user_id": uid},
                {"$set": {
                    "status": "error",
                    "session_id": "",
                    "last_error": _local_err,
                }},
            )
            await _DB.browser_profile_sessions.update_one(
                {"id": session_id},
                {"$set": {
                    "status": "error",
                    "error_message": _local_err,
                    "ended_at": _now_iso(),
                }},
            )
            launch_message = _local_err

    elif _BRIDGE_QUEUE is not None:
        try:
            bridge_payload = {
                "kind": "browser_profile_launch",
                "user_id": uid,
                "profile_id": profile_id,
                "session_id": session_id,
                "profile_config": dict(doc) | {
                    "_launch_automation": auto_spec,
                    "user_id": owner_uid,
                    "local_api_cdp": True,
                },
                "start_url": session["start_url"],
                "queued_at": _now_iso(),
            }
            bridge_job_id = await _BRIDGE_QUEUE(uid, bridge_payload)
            desktop_available = bool(bridge_job_id)
            if desktop_available:
                launch_message = (
                    "Launch queued — your Krexion desktop app will open the browser shortly."
                )
        except Exception as e:
            logger.warning(f"bridge enqueue failed: {e}")

    # Cloud offline OR local start failed: don't leave card stuck on "launching".
    if not desktop_available and not launch_message:
        _offline_err = (
            "Krexion desktop app is offline. Start the desktop app on your PC, then click Launch again."
            if not _is_local_desktop else
            "Could not start the browser on this PC. Restart Krexion and try Launch again."
        )
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {"$set": {"status": "idle", "session_id": "", "last_error": _offline_err[:512]}},
        )
        await _DB.browser_profile_sessions.update_one(
            {"id": session_id},
            {"$set": {"status": "error", "error_message": _offline_err, "ended_at": _now_iso()}},
        )
        launch_message = _offline_err

    return {
        "session_id": session_id,
        "bridge_job_id": bridge_job_id,
        "desktop_available": desktop_available,
        "message": launch_message or (
            "Launch queued — your Krexion desktop app will open the browser shortly."
            if desktop_available else
            "Profile is configured but launching requires the Krexion desktop app. "
            "Install or start it, then click Launch again."
        ),
        "profile": _public_view(doc),
        "automation_enabled": bool(auto_spec.get("enabled")),
        "automation_total_steps": int(auto_spec.get("total_steps") or 0),
    }


@router.put("/{profile_id}/automation-defaults")
async def save_automation_defaults(
    request: Request,
    profile_id: str,
    body: SaveAutomationDefaultsBody,
):
    """Save default JSON + lead file for quick re-launch (Phase 4)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    await _get_profile_for_user(profile_id, uid, min_role="editor")
    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {
            "default_automation_upload_id": str(body.automation_upload_id or "").strip(),
            "default_data_file_id": str(body.data_file_id or "").strip(),
            "updated_at": _now_iso(),
        }},
    )
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    return {"ok": True, "profile": _public_view(doc or {})}


@router.post("/validate-automation")
async def validate_automation(request: Request, body: ValidateAutomationBody):
    """Dry-run: JSON template parses + placeholders match lead columns."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    from browser_profile_automation import validate_automation_against_data

    return await validate_automation_against_data(
        _DB,
        uid,
        automation_upload_id=str(body.automation_upload_id or "").strip(),
        data_file_id=str(body.data_file_id or "").strip(),
    )


@router.post("/{profile_id}/run-automation")
async def run_profile_automation_endpoint(
    request: Request,
    profile_id: str,
    body: RunAutomationBody = Body(default_factory=RunAutomationBody),
):
    """Re-run JSON automation on an already-open profile (no relaunch)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    st = str(doc.get("status") or "idle").lower()
    if st not in ("running", "launching", "queued"):
        raise HTTPException(
            status_code=409,
            detail="Profile must be running to re-run automation. Launch it first.",
        )
    upload_id = str(
        body.automation_upload_id or doc.get("default_automation_upload_id") or ""
    ).strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="automation_upload_id required")

    auto_payload = {
        "enabled": True,
        "automation_upload_id": upload_id,
        "data_file_id": str(
            body.data_file_id or doc.get("default_data_file_id") or ""
        ).strip(),
        "lead_row_index": int(body.lead_row_index or 0),
        "skip_missing_steps": body.skip_missing_steps,
        "self_heal": body.self_heal,
        "after_mode": str(body.after_mode or "manual"),
        "consume_mode": str(body.consume_mode or "on_submit"),
        "claim_next": body.claim_next is not False,
        "proxy_upload_id": str(body.proxy_upload_id or "").strip(),
        "ua_upload_id": str(body.ua_upload_id or "").strip(),
        "smart_funnel_enabled": bool(body.smart_funnel_enabled),
        "smart_funnel_pattern": str(body.smart_funnel_pattern or "auto"),
        "smart_funnel_min_deals": int(body.smart_funnel_min_deals or 2),
        "smart_funnel_wait_until_conversion": bool(body.smart_funnel_wait_until_conversion),
    }
    try:
        from browser_profile_automation import resolve_launch_automation

        auto_spec = await resolve_launch_automation(
            _DB,
            uid,
            auto_payload,
            doc,
            claim_next=bool(auto_payload.get("claim_next")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sid = str(doc.get("session_id") or "")
    queued = False
    _mode = (os.environ.get("KREXION_MODE") or "cloud").lower().strip()
    if _mode in ("native", "local"):
        try:
            from browser_profile_launcher import request_run_automation

            queued = request_run_automation(sid, auto_spec)
        except Exception as exc:
            logger.warning(f"[profile-automation] local queue failed: {exc}")

    if not queued and _BRIDGE_QUEUE is not None and sid:
        try:
            bridge_job_id = await _BRIDGE_QUEUE(uid, {
                "kind": "browser_profile_run_automation",
                "profile_id": profile_id,
                "session_id": sid,
                "automation": auto_spec,
                "feature_override": "browser-profile/run-automation",
                "queued_at": _now_iso(),
            })
            queued = bool(bridge_job_id)
        except Exception as exc:
            logger.warning(f"[profile-automation] bridge queue failed: {exc}")

    if not queued:
        raise HTTPException(
            status_code=503,
            detail="Could not queue automation — profile session not found on this desktop.",
        )

    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {
            "automation_status": "queued",
            "automation_step": 0,
            "automation_total_steps": int(auto_spec.get("total_steps") or 0),
            "automation_error": "",
        }},
    )
    return {
        "ok": True,
        "queued": True,
        "session_id": sid,
        "automation_total_steps": int(auto_spec.get("total_steps") or 0),
    }


@router.post("/{profile_id}/stop-automation")
async def stop_profile_automation(request: Request, profile_id: str):
    """Stop JSON automation only — profile browser stays open for manual use."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    sid = str(doc.get("session_id") or "")
    auto_st = str(doc.get("automation_status") or "").lower()
    if not sid:
        raise HTTPException(status_code=409, detail="Profile is not running")
    if auto_st not in ("queued", "running"):
        return {"ok": True, "stopped": False, "message": "No active automation"}

    stop_sent = False
    _mode = (os.environ.get("KREXION_MODE") or "cloud").lower().strip()
    _is_local_desktop = _mode in ("native", "local")
    if _is_local_desktop:
        try:
            from browser_profile_launcher import request_stop_automation

            stop_sent = bool(request_stop_automation(sid))
        except Exception as exc:
            logger.warning(f"[profile-automation] local stop failed: {exc}")
    elif _BRIDGE_QUEUE is not None and sid:
        try:
            bridge_job_id = await _BRIDGE_QUEUE(uid, {
                "kind": "browser_profile_stop_automation",
                "profile_id": profile_id,
                "session_id": sid,
                "feature_override": "browser-profile/stop-automation",
                "queued_at": _now_iso(),
            })
            stop_sent = bool(bridge_job_id)
        except Exception as exc:
            logger.warning(f"[profile-automation] bridge stop failed: {exc}")

    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {
            "automation_status": "stopped",
            "automation_action": "",
            "automation_error": "",
        }},
    )
    return {"ok": True, "stopped": stop_sent or True, "session_id": sid}


@router.post("/{profile_id}/stop")
async def stop_profile(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _get_profile_for_user(profile_id, uid, min_role="editor")
    sid = doc.get("session_id") or ""
    cur_status = str(doc.get("status") or "idle").lower()
    if not sid and cur_status not in ("running", "launching", "stopping", "queued"):
        return {"stopped": True, "message": "No active session"}

    stop_sent = False
    cancelled_queued = False

    # 2026-06-11 (v2.1.41): On the local desktop, stop the headed browser
    # directly via the in-process launcher. Bridge-based stop only makes
    # sense from cloud → customer's PC; trying to enqueue here would just
    # be a no-op.
    #
    # 2026-06-28 (Session-0 fix): on the NSSM-installed Windows build the
    # actual headed browser is owned by the tray app (Session 1), not
    # the backend service (Session 0). We can't kill it from here —
    # write a stop_requested flag into the `browser_launch_queue`
    # record instead so the tray app's polling loop closes the browser
    # in its own process.
    _mode = (os.environ.get("KREXION_MODE") or "cloud").lower().strip()
    _is_local_desktop = _mode in ("native", "local")
    _is_session0_service = bool(_is_local_desktop and (os.environ.get("KREXION_BUILD_TYPE") or "").strip().lower() == "binary")
    if _is_session0_service and sid:
        try:
            cancelled = await _DB.browser_launch_queue.find_one_and_update(
                {"id": sid, "status": "queued"},
                {"$set": {
                    "status": "cancelled",
                    "stop_requested": True,
                    "stop_requested_at": _now_iso(),
                }},
            )
            if cancelled:
                cancelled_queued = True
                stop_sent = True
            else:
                await _DB.browser_launch_queue.update_one(
                    {"id": sid},
                    {"$set": {"stop_requested": True, "stop_requested_at": _now_iso()}},
                )
                stop_sent = True
        except Exception as e:
            logger.warning(f"local browser-profile stop (queued) failed: {e}")
    elif _is_local_desktop and sid:
        try:
            from browser_profile_launcher import request_stop
            stop_sent = bool(request_stop(sid))
        except Exception as e:
            logger.warning(f"local browser-profile stop failed: {e}")
    elif _BRIDGE_QUEUE is not None and sid:
        try:
            bridge_job_id = await _BRIDGE_QUEUE(uid, {
                "kind": "browser_profile_stop",
                "user_id": uid,
                "profile_id": profile_id,
                "session_id": sid,
                "feature_override": "browser-profile/stop",
            })
            stop_sent = bool(bridge_job_id)
        except Exception as e:
            logger.warning(f"stop bridge enqueue failed: {e}")

    if cancelled_queued:
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
            {"$set": {"status": "idle", "session_id": ""}},
        )
        await _DB.browser_profile_sessions.update_many(
            {"profile_id": profile_id, "user_id": uid, "id": sid},
            {"$set": {"status": "stopped", "ended_at": _now_iso()}},
        )
        return {"stopped": True, "cancelled_before_launch": True}

    # Mark stopping but keep session_id until desktop confirms closed/stopped.
    await _DB.browser_profiles.update_one(
        {"id": profile_id, "user_id": uid},
        {"$set": {"status": "stopping"}},
    )
    await _DB.browser_profile_sessions.update_many(
        {"profile_id": profile_id, "user_id": uid, "status": {"$in": ["queued", "running", "launching"]}},
        {"$set": {"status": "stopping", "ended_at": ""}},
    )
    return {"stopped": stop_sent, "status": "stopping", "session_id": sid}


@router.get("/{profile_id}/status")
async def get_status(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one(
        {"id": profile_id, "user_id": uid},
        {"id": 1, "status": 1, "session_id": 1, "last_launched_at": 1, "total_launches": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    doc.pop("_id", None)
    return {"status": doc.get("status", "idle"),
            "session_id": doc.get("session_id", ""),
            "total_launches": doc.get("total_launches", 0),
            "last_launched_at": doc.get("last_launched_at", "")}


@router.post("/import-bulk")
async def import_bulk(request: Request, body: BulkCreateBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    docs: List[Dict[str, Any]] = []
    pad = max(2, len(str(body.count)))
    base_proxy = body.base.proxy if hasattr(body.base, "proxy") else ProxyConfig()
    provider_id = str(getattr(base_proxy, "provider_id", None) or "").strip()
    for i in range(1, body.count + 1):
        profile_body = body.base.copy(deep=True) if hasattr(body.base, "copy") else body.base
        profile_body.name = f"{body.name_prefix} {str(i).zfill(pad)}"
        if body.randomize_ua:
            profile_body.user_agent = _gen_random_ua(profile_body.is_mobile or profile_body.device_type == "mobile")
        if body.randomize_viewport:
            profile_body.viewport = _gen_random_viewport(profile_body.is_mobile or profile_body.device_type == "mobile")
        if body.auto_unique_proxy and provider_id:
            profile_body.proxy.enabled = True
            profile_body.proxy.provider_id = provider_id
            profile_body.proxy.smart_session = True
        doc = _profile_doc(uid, profile_body)
        _prepare_proxy_for_profile_create(doc)
        docs.append(doc)
    if docs:
        await _DB.browser_profiles.insert_many(docs)
    return {
        "created": len(docs),
        "profiles": [_public_view(d) for d in docs],
        "unique_ips_bound": 0,
        "proxy_bind_deferred": bool(body.auto_unique_proxy and provider_id),
    }


@router.get("/export/all")
async def export_all(request: Request):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    cur = _DB.browser_profiles.find({"user_id": uid})
    docs = await cur.to_list(length=2000)
    out: List[Dict[str, Any]] = []
    for d in docs:
        d.pop("_id", None)
        d.pop("storage_state", None)
        out.append(d)
    return {"profiles": out, "count": len(out), "exported_at": _now_iso()}


@router.post("/quick-generate")
async def quick_generate(request: Request, body: Dict[str, Any] = Body(default_factory=dict)):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    country = str(body.get("country") or "us").lower()
    device_type = str(body.get("device_type") or "desktop").lower()
    is_mobile = device_type == "mobile"
    # v2.7.104 — consistent smart unique naming (was "Profile <datetime>"
    # which used spaces/colons and clashed with the rest of the module).
    _name_slug = "Mobile" if is_mobile else "Desktop"
    name = str(body.get("name") or "").strip() or _auto_name_device(country, _name_slug)
    ua = _gen_random_ua(is_mobile)
    pb = ProfileBody(
        name=name,
        country=country,
        device_type=device_type,
        is_mobile=is_mobile,
        has_touch=is_mobile,
        device_scale_factor=3.0 if is_mobile else 1.0,
        user_agent=ua,
        viewport=_gen_random_viewport(is_mobile),
        os=_infer_os_from_ua(ua, is_mobile=is_mobile),
        anti_detect=AntiDetectConfig(master=True),
    )
    doc = _profile_doc(uid, pb)
    await _DB.browser_profiles.insert_one(doc)
    return {"profile": _public_view(doc), "id": doc["id"]}


# ── 2026-01 / v2.7.12: Advanced create — mix % + device catalog ──────
# Produces N profiles with optional iOS/Android/Desktop mix, smart
# device naming, and resolution modes. ProxyJet / provider / manual
# proxy paths unchanged.
async def _generate_uas_batch(
    user: dict,
    *,
    count: int,
    platform: str,
    app: str,
    brand: Optional[str],
    region: str,
    is_mobile: bool,
) -> List[str]:
    """Generate `count` UAs for one platform; fall back to local pools."""
    uas: List[str] = []
    if count <= 0:
        return uas
    if _UA_GEN is not None:
        try:
            from server import UAGenerateRequest  # type: ignore
            _ua_platform = _honest_ua_platform_for_profiles(
                platform or "",
                is_mobile=is_mobile,
            )
            ua_payload = UAGenerateRequest(
                app=app or "browser",
                platform=_ua_platform,
                brand=brand,
                region=region,
                count=count,
                format="json",
            )
            ua_resp = await _UA_GEN(ua_payload, user)
            raw = ua_resp.get("results") or ua_resp.get("user_agents") or []
            for item in raw:
                if isinstance(item, dict):
                    u = item.get("user_agent") or item.get("ua") or ""
                else:
                    u = str(item)
                if u:
                    uas.append(u)
        except Exception as e:
            logger.warning(f"advanced_create: UA generator call failed ({e}); using fallback pool")
    while len(uas) < count:
        uas.append(_gen_random_ua(is_mobile))
    coerced: List[str] = []
    for u in uas[:count]:
        cu, _ = _normalize_profile_ua_honesty(u)
        coerced.append(cu)
    return coerced


@router.post("/advanced-create")
async def advanced_create(request: Request, body: AdvancedCreateBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)

    count = max(1, min(int(body.count or 1), 200))
    country = (body.country or "us").lower()
    resolution_mode = (body.resolution_mode or "match_device").lower().strip()
    device_mode = (body.device_mode or "random").lower().strip()
    specific_id = (body.device_id or "").strip()

    # Specific device forces 100% of that platform.
    specific_dev = _find_device(specific_id) if device_mode == "specific" and specific_id else None
    if specific_dev:
        plat = specific_dev["platform"]
        mix_plan = [(plat, count)]
    else:
        mix_plan = _split_mix_counts(
            count,
            body.mix_ios_pct,
            body.mix_android_pct,
            body.mix_desktop_pct,
        )
        if mix_plan is None:
            # Legacy: single device_type / ua.platform
            legacy_plat = (body.ua.platform or "").lower().strip()
            if legacy_plat in ("ios", "android", "desktop"):
                mix_plan = [(legacy_plat, count)]
            else:
                dt = (body.device_type or "desktop").lower()
                mix_plan = [("android" if dt == "mobile" else "desktop", count)]

    # Expand to per-slot platform list
    platform_slots: List[str] = []
    for plat, n in mix_plan:
        platform_slots.extend([plat] * int(n))
    platform_slots = platform_slots[:count]
    while len(platform_slots) < count:
        platform_slots.append("desktop")

    # Generate UAs per platform group (keeps generator coherent).
    uas_by_plat: Dict[str, List[str]] = {}
    ua_cursors: Dict[str, int] = {}
    for plat, n in mix_plan:
        is_mob = plat in ("ios", "android")
        brand = body.ua.brand
        if specific_dev and specific_dev.get("brand"):
            brand = specific_dev["brand"]
        uas_by_plat[plat] = await _generate_uas_batch(
            user,
            count=n,
            platform=plat,
            app=body.ua.app or "browser",
            brand=brand,
            region=body.ua.region or country.upper(),
            is_mobile=is_mob,
        )
        ua_cursors[plat] = 0

    # ── Proxies — bind UNIQUE exit IP at create (v2.7.106) ──
    proxy_lines: List[str] = []
    provider_lines: List[str] = []
    proxy_mode = (body.proxy.mode or "none").lower()
    proxy_warnings: List[str] = []

    # Manual: warn when fewer lines than profiles (extras created proxy-less)
    if proxy_mode == "manual":
        _manual_lines = [str(x).strip() for x in (body.proxy.lines or []) if str(x).strip()]
        if _manual_lines and len(_manual_lines) < count:
            proxy_warnings.append(
                f"Only {len(_manual_lines)} proxy line(s) provided for {count} "
                f"profiles — {count - len(_manual_lines)} profile(s) created "
                "WITHOUT a proxy to avoid IP reuse. Paste one line per profile."
            )
        if (not _manual_lines) and body.proxy.server and count > 1:
            if not _is_rotating_gateway_proxy({
                "enabled": True,
                "server": body.proxy.server,
                "username": body.proxy.username or "",
                "password": body.proxy.password or "",
            }):
                proxy_warnings.append(
                    "Same static manual proxy for multiple profiles — only the first "
                    "unique exit IP is kept; duplicates are skipped (not saved)."
                )

    if proxy_mode == "provider" and body.proxy.provider_id:
        # Lines allocated per-slot inside unique-IP binder
        provider_lines = []
    elif proxy_mode == "proxyjet":
        if _PROXYJET_GEN is None:
            proxy_warnings.append(
                "ProxyJet not configured — profiles need ProxyJet creds before create."
            )
        else:
            try:
                from server import ProxyJetGenerateIn  # type: ignore
                pj_payload = ProxyJetGenerateIn(
                    count=count,
                    country=(body.proxy.country or "").strip().upper() or None,
                    state=(body.proxy.state or "").strip().upper() or None,
                    countries=body.proxy.countries,
                    states=body.proxy.states,
                    sticky_minutes=body.proxy.sticky_minutes,
                )
                pj_resp = await _PROXYJET_GEN(pj_payload, user)
                proxy_lines = [str(x).strip() for x in (pj_resp.get("proxies") or []) if str(x).strip()]
                if len(proxy_lines) < count:
                    proxy_warnings.append(
                        f"ProxyJet returned {len(proxy_lines)}/{count} lines — "
                        "slots without a unique IP will be skipped."
                    )
            except HTTPException as he:
                logger.warning(f"advanced_create: ProxyJet soft-fail: {he.detail}")
                proxy_warnings.append(str(he.detail)[:200])
            except Exception as e:
                logger.warning(f"advanced_create: ProxyJet soft-fail: {e}")
                proxy_warnings.append(f"ProxyJet generate failed: {str(e)[:120]}")

    def _parse_proxy_line_to_cfg(
        line: str,
        *,
        provider_id: str = "",
        use_proxyjet: bool = False,
        proxyjet_country: str = "US",
        proxyjet_state: str = "",
    ) -> ProxyConfig:
        parsed = _parse_proxy_line(str(line or "").strip())
        return ProxyConfig(
            enabled=True,
            server=parsed.get("server") or "",
            username=parsed.get("username") or "",
            password=parsed.get("password") or "",
            provider_id=str(provider_id or "").strip(),
            use_proxyjet=bool(use_proxyjet),
            proxyjet_country=(proxyjet_country or "US").upper(),
            proxyjet_state=(proxyjet_state or "").upper(),
        )

    pad = max(2, len(str(count)))
    docs: List[Dict[str, Any]] = []
    skipped_profiles: List[Dict[str, str]] = []
    used_device_ids: Set[str] = set()
    seen_ua: Set[str] = set()
    used_ips: Set[str] = await _load_team_profile_used_ips(uid)
    batch_assigned: Set[str] = set()
    unique_ips_bound = 0
    deferred_count = 0
    _targeting = {
        "country": (body.proxy.country or body.country or "US").upper()[:2],
        "state": (body.proxy.state or "").upper(),
    }

    for i, plat in enumerate(platform_slots):
        is_mobile = plat in ("ios", "android")
        device = _pick_device(
            plat,
            device_mode=device_mode,
            device_id=specific_id,
            used_ids=used_device_ids,
        )
        # UA for this slot
        idx = ua_cursors.get(plat, 0)
        pool = uas_by_plat.get(plat) or []
        ua = pool[idx] if idx < len(pool) else _gen_random_ua(is_mobile)
        ua_cursors[plat] = idx + 1
        # Soft uniqueness: reshuffle fallback if duplicate in-batch
        if ua in seen_ua:
            for _ in range(5):
                alt = _gen_random_ua(is_mobile)
                if alt not in seen_ua:
                    ua = alt
                    break
        seen_ua.add(ua)

        if (body.name_prefix or "").strip():
            name = f"{body.name_prefix.strip()} {str(i + 1).zfill(pad)}"
        else:
            name = _auto_name_device(country, str(device.get("slug") or plat))

        proxy_cfg = ProxyConfig()
        if proxy_mode == "provider" and body.proxy.provider_id:
            proxy_cfg = ProxyConfig(
                enabled=True,
                provider_id=str(body.proxy.provider_id or ""),
                smart_session=True,
                proxyjet_country=(body.proxy.country or body.country or "US").upper()[:2],
                proxyjet_state=(body.proxy.state or "").upper(),
            )
        elif proxy_mode == "manual":
            # One UNIQUE line per profile. Never reuse a line across
            # profiles (silent IP reuse defeats anti-detect) — extra
            # profiles are created proxy-less instead (warning emitted).
            lines = [str(x).strip() for x in (body.proxy.lines or []) if str(x).strip()]
            if lines:
                if i < len(lines):
                    proxy_cfg = _parse_proxy_line_to_cfg(lines[i])
                # else: leave proxy-less on purpose (no IP reuse)
            elif body.proxy.server:
                proxy_cfg = ProxyConfig(
                    enabled=True,
                    server=body.proxy.server.strip(),
                    username=body.proxy.username or "",
                    password=body.proxy.password or "",
                )
        elif proxy_mode == "proxyjet":
            if i < len(proxy_lines):
                proxy_cfg = _parse_proxy_line_to_cfg(
                    proxy_lines[i].strip(),
                    use_proxyjet=True,
                    proxyjet_country=(body.proxy.country or "US"),
                    proxyjet_state=(body.proxy.state or ""),
                )
            else:
                proxy_cfg = ProxyConfig(
                    enabled=True,
                    use_proxyjet=True,
                    proxyjet_country=(body.proxy.country or "US").upper(),
                    proxyjet_state=(body.proxy.state or "").upper(),
                )

        viewport = _viewport_for_device(
            device,
            resolution_mode=resolution_mode,
            width=body.viewport_width or 0,
            height=body.viewport_height or 0,
        )
        dpr = float(device.get("dpr") or (3.0 if is_mobile else 1.0))
        os_fallback = "ios" if plat == "ios" else ("android" if plat == "android" else "windows")
        if plat == "desktop" and (device.get("brand") or "") == "mac":
            os_fallback = "macos"

        _tags = [str(t).strip()[:40] for t in (body.tags or []) if str(t).strip()][:20]
        _tz = (body.timezone or "").strip() or "America/New_York"
        _locale = (body.locale or "").strip() or "en-US"
        try:
            _ref = body.referrer if isinstance(body.referrer, ReferrerProConfig) else ReferrerProConfig(**(body.referrer or {}))
        except Exception:
            _ref = ReferrerProConfig()

        pb = ProfileBody(
            name=name,
            country=country,
            device_type="mobile" if is_mobile else "desktop",
            is_mobile=is_mobile,
            has_touch=is_mobile,
            device_scale_factor=dpr,
            user_agent=ua,
            viewport=viewport,
            os=_infer_os_from_ua(ua, is_mobile=is_mobile, fallback=os_fallback),
            start_url=body.start_url or "https://www.google.com/",
            notes=body.notes or "",
            timezone=_tz,
            locale=_locale,
            language=_locale,
            accept_language=f"{_locale},{_locale.split('-')[0]};q=0.9" if "-" in _locale else f"{_locale},en;q=0.9",
            proxy=proxy_cfg,
            tags=_tags,
            folder=(body.folder or "").strip()[:80],
            geo_follow_proxy=bool(body.geo_follow_proxy),
            quick_links=[str(u).strip()[:512] for u in (body.quick_links or []) if str(u).strip()][:12],
            referrer=_ref,
            anti_detect=_adv_anti_detect_cfg(body),
        )
        doc = _profile_doc(uid, pb)
        doc["device_model"] = str(device.get("slug") or "")
        doc["device_label"] = str(device.get("label") or "")
        doc["device_catalog_id"] = str(device.get("id") or "")
        _pline = ""
        if proxy_mode == "provider" and body.proxy.provider_id:
            pass
        elif proxy_mode == "proxyjet" and i < len(proxy_lines):
            _pline = proxy_lines[i].strip()
        elif proxy_mode == "manual":
            _mlines = [str(x).strip() for x in (body.proxy.lines or []) if str(x).strip()]
            if _mlines and i < len(_mlines):
                _pline = _mlines[i]
        if _pline:
            doc.setdefault("proxy", {})["raw_line"] = _pline

        # v2.7.106/114 — RUT-quality unique exit IP before save (no soft-defer).
        if proxy_is_active(doc.get("proxy") or {}):
            # v2.7.114 — RUT-quality: unique + non-VPN + selected state before save
            bind = await _bind_unique_exit_ip_at_create(
                uid,
                user,
                doc,
                used_ips=used_ips,
                batch_assigned=batch_assigned,
                targeting=_targeting,
                max_retries=24,
            )
            if not bind.get("ok"):
                skipped_profiles.append({
                    "name": str(doc.get("name") or name),
                    "reason": str(bind.get("reason") or "unique exit IP unavailable")[:240],
                })
                proxy_warnings.append(
                    f"Skipped {doc.get('name') or name}: "
                    f"{str(bind.get('reason') or 'no unique IP')[:160]}"
                )
                continue
            if bind.get("exit_ip"):
                unique_ips_bound += 1
            if bind.get("deferred"):
                deferred_count += 1
                warn = str(bind.get("warning") or "").strip()
                if warn:
                    proxy_warnings.append(f"{doc.get('name') or name}: {warn[:180]}")
                else:
                    proxy_warnings.append(
                        f"{doc.get('name') or name}: exit IP deferred — "
                        "verified on first launch"
                    )
        else:
            _prepare_proxy_for_profile_create(doc)

        docs.append(doc)

    if docs:
        await _DB.browser_profiles.insert_many(docs)
    return {
        "created": len(docs),
        "profiles": [_public_view(d) for d in docs],
        "skipped": skipped_profiles,
        "ua_source": "live_generator" if _UA_GEN else "fallback_pool",
        "proxy_mode": proxy_mode,
        "proxies_allocated": unique_ips_bound if proxy_mode in ("proxyjet", "provider", "manual") else 0,
        "smart_session": bool(proxy_mode == "provider" and body.proxy.provider_id),
        "proxy_bind_deferred": deferred_count > 0,
        "deferred_exit_ip_count": deferred_count,
        "proxy_warnings": proxy_warnings,
        "unique_ips_bound": unique_ips_bound,
        "mix": {plat: n for plat, n in (mix_plan or [])},
    }


@router.post("/bulk-delete")
async def bulk_delete(request: Request, body: BulkIdsBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:200]
    if not ids:
        raise HTTPException(status_code=400, detail="profile_ids required")
    # Skip actively launching/running unless client sends only idle — we allow
    # delete of non-running; running ones are skipped with reason.
    deleted: List[str] = []
    skipped: List[Dict[str, str]] = []
    permanent = bool(getattr(body, "permanent", False))
    for pid in ids:
        doc = await _DB.browser_profiles.find_one({"id": pid, "user_id": uid}, {"status": 1, "deleted_at": 1})
        if not doc:
            skipped.append({"id": pid, "reason": "not_found"})
            continue
        st = str(doc.get("status") or "idle")
        if st in ("running", "launching", "queued", "stopping"):
            skipped.append({"id": pid, "reason": f"busy:{st}"})
            continue
        if permanent:
            if not str(doc.get("deleted_at") or "").strip():
                skipped.append({"id": pid, "reason": "not_in_trash"})
                continue
            res = await _DB.browser_profiles.delete_one({"id": pid, "user_id": uid})
            if res.deleted_count:
                await _DB.browser_profile_sessions.delete_many({"profile_id": pid, "user_id": uid})
                deleted.append(pid)
            else:
                skipped.append({"id": pid, "reason": "delete_failed"})
            continue
        await _DB.browser_profiles.update_one(
            {"id": pid, "user_id": uid},
            {"$set": {"deleted_at": _now_iso(), "status": "idle", "session_id": ""}},
        )
        deleted.append(pid)
    return {"deleted": deleted, "skipped": skipped, "deleted_count": len(deleted), "permanent": permanent}


@router.post("/bulk-stop")
async def bulk_stop(request: Request, body: BulkIdsBody):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:200]
    results = []
    for pid in ids:
        # Reuse stop endpoint logic via internal HTTP-less call pattern:
        try:
            fake_body = {}
            # Inline minimal stop: mark stop_requested / update status
            try:
                doc = await _get_profile_for_user(pid, uid, min_role="editor")
            except HTTPException as he:
                results.append({"id": pid, "ok": False, "reason": str(he.detail)[:120]})
                continue
            owner_uid = str(doc.get("user_id") or uid)
            st = str(doc.get("status") or "idle")
            if st not in ("running", "launching", "queued", "stopping"):
                results.append({"id": pid, "ok": False, "reason": f"not_active:{st}"})
                continue
            # Call existing stop handler by constructing a Request is hard;
            # duplicate the essential bits from stop_profile.
            from starlette.requests import Request as _Req  # noqa: F401
            # Prefer importing stop by invoking the route function with a shim —
            # simplest: set status stopping and queue stop flag.
            sid = str(doc.get("session_id") or "")
            await _DB.browser_profiles.update_one(
                {"id": pid, "user_id": owner_uid},
                {"$set": {"status": "stopping"}},
            )
            if sid:
                try:
                    await _DB.browser_launch_queue.update_one(
                        {"id": sid},
                        {"$set": {"stop_requested": True}},
                    )
                except Exception:
                    pass
                try:
                    from browser_profile_launcher import request_stop
                    await request_stop(sid)
                except Exception:
                    pass
            results.append({"id": pid, "ok": True, "status": "stopping"})
        except Exception as e:
            results.append({"id": pid, "ok": False, "reason": str(e)[:120]})
    return {"results": results, "stopped": sum(1 for r in results if r.get("ok"))}


@router.post("/bulk-launch")
async def bulk_launch(request: Request, body: BulkLaunchBody):
    """Launch up to max_concurrent idle profiles (rest skipped with reason)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:50]
    max_c = max(1, min(int(body.max_concurrent or 5), 20))
    if not ids:
        raise HTTPException(status_code=400, detail="profile_ids required")

    launched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for idx, pid in enumerate(ids):
        if len(launched) >= max_c:
            skipped.append({"id": pid, "reason": "concurrent_cap"})
            continue
        try:
            doc = await _get_profile_for_user(pid, uid, min_role="editor")
        except HTTPException as he:
            skipped.append({"id": pid, "reason": str(he.detail)[:160]})
            continue
        st = str(doc.get("status") or "idle")
        if st in ("running", "launching", "queued", "stopping"):
            skipped.append({"id": pid, "reason": f"busy:{st}"})
            continue
        launch_body = LaunchBody(
            start_url=body.start_url or doc.get("start_url"),
            automation=body.automation,
        )
        try:
            # Always pass a bulk marker so resolve uses atomic claim_next
            # (selection index is NOT used as lead row — avoids duplicate leads).
            result = await launch_profile(
                request,
                pid,
                launch_body,
                _bulk_row_index=idx if (body.automation and body.automation.enabled) else None,
            )
            launched.append({
                "id": pid,
                "ok": True,
                **{k: result.get(k) for k in (
                    "session_id", "desktop_available", "message",
                    "automation_enabled", "automation_total_steps",
                ) if isinstance(result, dict)},
            })
        except HTTPException as he:
            skipped.append({"id": pid, "reason": str(he.detail)[:160]})
        except Exception as e:
            skipped.append({"id": pid, "reason": str(e)[:160]})

    return {
        "launched": launched,
        "skipped": skipped,
        "launched_count": len(launched),
        "max_concurrent": max_c,
    }


@router.post("/bulk-run-json")
async def bulk_run_json(request: Request, body: BulkRunJsonBody):
    """Launch idle profiles with JSON, or queue JSON on already-running profiles."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    upload_id = str(body.automation_upload_id or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="automation_upload_id required")

    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:50]
    max_c = max(1, min(int(body.max_concurrent or 5), 20))
    if not ids:
        raise HTTPException(status_code=400, detail="profile_ids required")

    default_data_file = str(body.data_file_id or "").strip()
    default_proxy_upload = str(body.proxy_upload_id or "").strip()

    started: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    launched_count = 0

    for idx, pid in enumerate(ids):
        try:
            doc = await _get_profile_for_user(pid, uid, min_role="editor")
        except HTTPException as he:
            skipped.append({"id": pid, "reason": str(he.detail)[:160]})
            continue
        st = str(doc.get("status") or "idle").lower()
        row_data_file = default_data_file or str(doc.get("default_data_file_id") or "").strip()

        auto_base = ProfileAutomationLaunch(
            enabled=True,
            automation_upload_id=upload_id,
            data_file_id=row_data_file,
            skip_missing_steps=body.skip_missing_steps is not False,
            self_heal=bool(body.self_heal),
            after_mode=str(body.after_mode or "manual"),
            consume_mode=str(body.consume_mode or "on_submit"),
            claim_next=body.claim_next is not False,
            proxy_upload_id=default_proxy_upload,
            ua_upload_id=str(body.ua_upload_id or "").strip(),
            smart_funnel_enabled=bool(body.smart_funnel_enabled),
            smart_funnel_pattern=str(body.smart_funnel_pattern or "auto"),
            smart_funnel_min_deals=int(body.smart_funnel_min_deals or 2),
            smart_funnel_wait_until_conversion=bool(body.smart_funnel_wait_until_conversion),
        )

        if st in ("running", "launching", "queued"):
            if st == "launching":
                skipped.append({"id": pid, "reason": "still_launching"})
                continue
            try:
                run_body = RunAutomationBody(
                    automation_upload_id=upload_id,
                    data_file_id=row_data_file,
                    lead_row_index=0,
                    skip_missing_steps=body.skip_missing_steps,
                    self_heal=body.self_heal,
                    after_mode=str(body.after_mode or "manual"),
                    consume_mode=str(body.consume_mode or "on_submit"),
                    claim_next=body.claim_next is not False,
                    proxy_upload_id=default_proxy_upload,
                )
                result = await run_profile_automation_endpoint(request, pid, run_body)
                started.append({"id": pid, "mode": "queued_on_running", **result})
            except HTTPException as he:
                skipped.append({"id": pid, "reason": str(he.detail)[:160]})
            except Exception as e:
                skipped.append({"id": pid, "reason": str(e)[:160]})
            continue

        if st in ("stopping",):
            skipped.append({"id": pid, "reason": f"busy:{st}"})
            continue

        if launched_count >= max_c:
            skipped.append({"id": pid, "reason": "concurrent_cap"})
            continue

        launch_body = LaunchBody(
            start_url=doc.get("start_url"),
            automation=auto_base,
        )
        try:
            result = await launch_profile(
                request,
                pid,
                launch_body,
                _bulk_row_index=idx,
            )
            launched_count += 1
            started.append({
                "id": pid,
                "mode": "launch_with_json",
                "ok": True,
                **{k: result.get(k) for k in (
                    "session_id", "desktop_available", "message",
                    "automation_enabled", "automation_total_steps",
                ) if isinstance(result, dict)},
            })
        except HTTPException as he:
            skipped.append({"id": pid, "reason": str(he.detail)[:160]})
        except Exception as e:
            skipped.append({"id": pid, "reason": str(e)[:160]})

    return {
        "started": started,
        "skipped": skipped,
        "started_count": len(started),
        "max_concurrent": max_c,
        "automation_upload_id": upload_id,
    }


# LEGACY advanced_create body retained below was replaced above (v2.7.12).
# ── session-update bridge ────────────────────────────────────────────
@router.post("/_bridge/session-update")
async def bridge_session_update(request: Request, body: Dict[str, Any] = Body(...)):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    pid = str(body.get("profile_id") or "")
    sid = str(body.get("session_id") or "")
    status = str(body.get("status") or "running").lower()
    if not pid or not sid:
        raise HTTPException(status_code=400, detail="profile_id + session_id required")

    # v2.6.32 — Map tray-queue "queued" to UI-friendly "launching".
    display_status = status
    if status == "queued":
        display_status = "launching"

    update: Dict[str, Any] = {"status": display_status}
    if status in ("closed", "stopped", "error"):
        update["session_id"] = ""
        update["status"] = "idle" if status in ("closed", "stopped") else "error"
    elif status == "running":
        update["session_id"] = sid
    elif status == "stopping":
        update["session_id"] = sid
    if "storage_state" in body and isinstance(body["storage_state"], dict):
        update["storage_state"] = body["storage_state"]
        update["storage_synced_at"] = _now_iso()
    if "fingerprint_hash" in body:
        update["fingerprint_hash"] = str(body["fingerprint_hash"])[:128]
    if "last_tls_prewarm_ok" in body:
        update["last_tls_prewarm_ok"] = bool(body["last_tls_prewarm_ok"])
    if "last_proxy_check" in body and isinstance(body.get("last_proxy_check"), dict):
        update["last_proxy_check"] = body["last_proxy_check"]
    if body.get("cdp_ws"):
        update["cdp_ws"] = str(body.get("cdp_ws"))[:512]
    if body.get("debugger_address"):
        update["debugger_address"] = str(body.get("debugger_address"))[:128]
    if "duration_sec" in body:
        try:
            update["last_session_duration_sec"] = float(body["duration_sec"])
        except Exception:
            pass
    err_msg = body.get("error_message")
    if status == "error" and err_msg:
        update["last_error"] = str(err_msg)[:512]
    elif status == "running":
        update["last_error"] = ""
        update["session_id"] = sid
        if "storage_state" in body and isinstance(body["storage_state"], dict):
            update["storage_state"] = body["storage_state"]
    for _ak in (
        "automation_status",
        "automation_step",
        "automation_total_steps",
        "automation_action",
        "automation_error",
    ):
        if _ak in body:
            update[_ak] = body[_ak]

    await _DB.browser_profiles.update_one(
        {"id": pid, "user_id": uid}, {"$set": update}
    )
    sess_update: Dict[str, Any] = {
        "status": status,
        "ended_at": _now_iso() if status in ("closed", "stopped", "error") else "",
        "duration_sec": float(body.get("duration_sec") or 0),
    }
    if status == "error" and err_msg:
        sess_update["error_message"] = str(err_msg)[:512]
    await _DB.browser_profile_sessions.update_one(
        {"id": sid, "user_id": uid},
        {"$set": sess_update},
    )
    return {"ok": True}


__all__ = ["router", "_bind"]
