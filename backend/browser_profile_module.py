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
  • Mongo collection: `browser_profile_sessions`  (running launches)
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
    n_desktop = total - n_ios - n_android
    # Fix rare overshoot from rounding.
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
        n_desktop += 1
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


def _parse_proxy_line(line: str) -> Dict[str, str]:
    """Normalize a ProxyJet / provider proxy line → server + creds dict."""
    line = (line or "").strip()
    server = ""
    username = ""
    password = ""
    if not line:
        return {"server": "", "username": "", "password": ""}
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
            server = f"http://{hostport}"
        else:
            parts = line.split(":")
            if len(parts) >= 4:
                host, port, username = parts[0], parts[1], parts[2]
                password = ":".join(parts[3:])
                server = f"http://{host}:{port}"
            elif len(parts) >= 2:
                server = f"http://{parts[0]}:{parts[1]}"
            else:
                server = line
    except Exception as _pe:
        logger.warning(f"proxy line parse failed: {_pe}")
        server = line
    return {"server": server, "username": username, "password": password}


async def _resolve_proxy_for_launch(uid: str, user: dict, proxy_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ProxyJet / provider proxy to a concrete server URL before launch."""
    cfg = dict(proxy_cfg or {})
    if cfg.get("use_proxyjet") and not str(cfg.get("server") or "").strip():
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
    return cfg


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
        prof_update = {"status": "idle" if status in ("stopped", "closed") else "error", "session_id": ""}
        if status == "error" and body.get("error_message"):
            prof_update["last_error"] = str(body.get("error_message"))[:512]
    elif status == "launching":
        prof_update = {"status": "launching", "session_id": sid}
    if prof_update:
        await _DB.browser_profiles.update_one(
            {"id": profile_id, "user_id": uid},
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
    # ProxyJet auto-mode (uses customer's saved ProxyJet creds)
    use_proxyjet: bool = False
    proxyjet_country: str = "US"
    proxyjet_state: str = ""
    # v2.4.0 — Multi-provider proxy dropdown. When set, the launch flow
    # resolves this to a live proxy from the user's Proxy Providers.
    # Empty ⇒ existing enabled/server/proxyjet fields apply.
    provider_id: str = ""


class AntiDetectConfig(BaseModel):
    """Single master switch + same flags as RUT (auto-tuned)."""
    master: bool = True             # ⭐ master toggle (default ON for new profiles)
    tls_prewarm: bool = True
    behavioral_bio: bool = True
    ip_warmup: bool = False         # Heavy — opt in
    browser_variant: str = "rotate" # auto/rotate/chromium/brave/headless-shell
    identity_persist: bool = True   # Carry cookies+localStorage across launches
    paranoia_mode: bool = False     # Maximum anti-detect (slower)


class ReferrerProConfig(BaseModel):
    """Per-profile Referrer Pro config (used when this profile opens a
    new tab to a 3rd-party URL — engine injects matching Referer)."""
    enabled: bool = False
    pro_mode: bool = True
    platform_weights: Dict[str, float] = Field(default_factory=dict)
    email_weights: Dict[str, float] = Field(default_factory=dict)
    social_wrapper: bool = True
    inapp_deep_path: bool = True
    strip_search_path: bool = True
    network_click_chain: bool = False
    search_engine: str = "google"
    search_keywords: str = ""
    brand: str = ""


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
                     (same proxy applied to every profile)
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
    # ProxyJet on-demand
    country: Optional[str] = None
    state: Optional[str] = None
    countries: Optional[List[str]] = None
    states: Optional[List[str]] = None
    # 0 / None = rotating (fresh per request); 1..120 = sticky N min
    sticky_minutes: Optional[int] = None
    # v2.4.0 — Multi-provider proxy (see settings › Proxy Providers)
    provider_id: Optional[str] = None


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
    # v2.7.12 — Platform mix (%). Sum normalized; all-zero → legacy device_type.
    mix_ios_pct: float = Field(default=0, ge=0, le=100)
    mix_android_pct: float = Field(default=0, ge=0, le=100)
    mix_desktop_pct: float = Field(default=0, ge=0, le=100)
    # Device picker: random | specific
    device_mode: str = "random"
    device_id: str = ""
    # Resolution: match_device | random | exact
    resolution_mode: str = "match_device"
    # Sub-configs
    ua: AdvUACfg = Field(default_factory=AdvUACfg)
    proxy: AdvProxyCfg = Field(default_factory=AdvProxyCfg)


class BulkIdsBody(BaseModel):
    profile_ids: List[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=5, ge=1, le=20)


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
    return {
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
        "tags": body.tags or [],
        "start_url": body.start_url,
        "storage_state": {},   # cookies + localStorage persisted by desktop client
        "fingerprint_hash": "",  # set by desktop client on first launch
        "session_id": "",        # active session_id when launched
        "status": "idle",        # idle | launching | running | stopped | error
        "last_launched_at": "",
        "last_session_duration_sec": 0,
        "total_launches": 0,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
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
    }
    d.pop("storage_state", None)
    return d


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
    tag: Optional[str] = None,
):
    """List ALL profiles for the current user."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    q: Dict[str, Any] = {"user_id": uid}
    if tag:
        q["tags"] = tag
    cur = _DB.browser_profiles.find(q).sort("updated_at", -1).limit(limit)
    docs = await cur.to_list(length=limit)
    return {"profiles": [_public_view(d) for d in docs], "count": len(docs)}


@router.post("/")
async def create_profile(request: Request, body: ProfileBody):
    """Create a new browser profile."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = _profile_doc(uid, body)
    await _DB.browser_profiles.insert_one(doc)
    return {"profile": _public_view(doc), "id": doc["id"]}


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


@router.get("/{profile_id}")
async def get_profile(request: Request, profile_id: str):
    """Get one profile."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"profile": _public_view(doc)}


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
    new_doc["updated_at"] = _now_iso()
    await _DB.browser_profiles.replace_one({"id": profile_id, "user_id": uid}, new_doc)
    return {"profile": _public_view(new_doc)}


@router.delete("/{profile_id}")
async def delete_profile(request: Request, profile_id: str):
    """Delete a profile + any related sessions."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    res = await _DB.browser_profiles.delete_one({"id": profile_id, "user_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    await _DB.browser_profile_sessions.delete_many({"profile_id": profile_id, "user_id": uid})
    return {"deleted": True}


@router.post("/{profile_id}/clone")
async def clone_profile(request: Request, profile_id: str):
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
    new_doc["storage_state"] = {}
    new_doc["fingerprint_hash"] = ""
    new_doc["total_launches"] = 0
    new_doc["last_launched_at"] = ""
    new_doc["status"] = "idle"
    new_doc["created_at"] = _now_iso()
    new_doc["updated_at"] = _now_iso()
    await _DB.browser_profiles.insert_one(new_doc)
    return {"profile": _public_view(new_doc), "id": new_doc["id"]}


@router.post("/{profile_id}/launch")
async def launch_profile(request: Request, profile_id: str,
                          start_url: Optional[str] = Body(default=None, embed=True)):
    """Queue a launch job for the customer's local desktop client."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")

    cur_status = str(doc.get("status") or "idle").lower()
    if cur_status in ("running", "launching", "stopping", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Profile is already {cur_status}. Stop it first or wait for the current session to finish.",
        )

    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "profile_id": profile_id,
        "user_id": uid,
        "started_at": _now_iso(),
        "status": "queued",
        "start_url": start_url or doc.get("start_url") or "https://www.google.com/",
    }
    # v2.4.0 wire-up: resolve provider_id → live proxy just before launch
    # 2026-07 v2.5.3 — For rotating_gateway providers we now request a
    # single line with session rotation so back-to-back profile launches
    # don't reuse the same sticky IP.
    _proxy_cfg = doc.get("proxy") or {}
    _provider_id = str(_proxy_cfg.get("provider_id") or "").strip()
    if _provider_id:
        try:
            import importlib
            _pp_mod = importlib.import_module("proxy_provider_module")
            _pp_bulk = getattr(_pp_mod, "get_proxy_lines_from_provider", None)
            _pp_get = getattr(_pp_mod, "get_proxy_from_provider", None)
            _pp_res = None
            if _pp_bulk:
                _pp_res = await _pp_bulk(uid, _provider_id, 1)
                _lines = _pp_res.get("lines") or []
                _proxy_line = _lines[0] if _lines else None
                if _pp_res.get("use_proxyjet"):
                    _proxy_cfg["use_proxyjet"] = True
                    if _pp_res.get("country"):
                        _proxy_cfg["proxyjet_country"] = _pp_res["country"]
                    if _pp_res.get("state"):
                        _proxy_cfg["proxyjet_state"] = _pp_res["state"]
                    _proxy_cfg["enabled"] = True
                elif _proxy_line:
                    _proxy_cfg["enabled"] = True
                    _proxy_cfg["server"] = _proxy_line
            elif _pp_get:
                _pp_res = await _pp_get(uid, _provider_id)
                if _pp_res.get("use_proxyjet"):
                    _proxy_cfg["use_proxyjet"] = True
                    if _pp_res.get("country"):
                        _proxy_cfg["proxyjet_country"] = _pp_res["country"]
                    if _pp_res.get("state"):
                        _proxy_cfg["proxyjet_state"] = _pp_res["state"]
                    _proxy_cfg["enabled"] = True
                elif _pp_res.get("proxy"):
                    _proxy_cfg["enabled"] = True
                    _proxy_cfg["server"] = _pp_res["proxy"]
            # Persist the resolved snapshot back onto the doc so the
            # launcher (which reads .proxy) uses the just-picked value.
            doc["proxy"] = _proxy_cfg
        except Exception as _pp_err:
            logger.warning(f"[browser-profile launch] provider resolve failed: {_pp_err}")

    # v2.6.32 — ProxyJet-only profiles may have enabled=True but no server yet.
    _proxy_cfg = await _resolve_proxy_for_launch(uid, user, _proxy_cfg)
    doc["proxy"] = _proxy_cfg

    await _DB.browser_profile_sessions.insert_one(session)

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

            async def _on_update(body: dict):
                try:
                    await _mirror_profile_session(uid, profile_id, session_id, body)
                    if body.get("storage_state") and isinstance(body["storage_state"], dict):
                        await _DB.browser_profiles.update_one(
                            {"id": profile_id, "user_id": uid},
                            {"$set": {"storage_state": body["storage_state"]}},
                        )
                    if body.get("fingerprint_hash"):
                        await _DB.browser_profiles.update_one(
                            {"id": profile_id, "user_id": uid},
                            {"$set": {"fingerprint_hash": str(body["fingerprint_hash"])[:128]}},
                        )
                    if body.get("duration_sec") is not None:
                        try:
                            await _DB.browser_profiles.update_one(
                                {"id": profile_id, "user_id": uid},
                                {"$set": {"last_session_duration_sec": float(body["duration_sec"])}},
                            )
                        except Exception:
                            pass
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
                "profile_config": doc,
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
    }


@router.post("/{profile_id}/stop")
async def stop_profile(request: Request, profile_id: str):
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    doc = await _DB.browser_profiles.find_one({"id": profile_id, "user_id": uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
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
    for i in range(1, body.count + 1):
        profile_body = body.base.copy(deep=True) if hasattr(body.base, "copy") else body.base
        profile_body.name = f"{body.name_prefix} {str(i).zfill(pad)}"
        if body.randomize_ua:
            profile_body.user_agent = _gen_random_ua(profile_body.is_mobile or profile_body.device_type == "mobile")
        if body.randomize_viewport:
            profile_body.viewport = _gen_random_viewport(profile_body.is_mobile or profile_body.device_type == "mobile")
        doc = _profile_doc(uid, profile_body)
        docs.append(doc)
    if docs:
        await _DB.browser_profiles.insert_many(docs)
    return {"created": len(docs), "profiles": [_public_view(d) for d in docs]}


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
    name = str(body.get("name") or "").strip() or f"Profile {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    country = str(body.get("country") or "us").lower()
    device_type = str(body.get("device_type") or "desktop").lower()
    is_mobile = device_type == "mobile"
    pb = ProfileBody(
        name=name,
        country=country,
        device_type=device_type,
        is_mobile=is_mobile,
        has_touch=is_mobile,
        device_scale_factor=3.0 if is_mobile else 1.0,
        user_agent=_gen_random_ua(is_mobile),
        viewport=_gen_random_viewport(is_mobile),
        os=_infer_os_from_ua(_gen_random_ua(is_mobile), is_mobile=is_mobile),
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

    # ── Proxies (unchanged ProxyJet / provider / manual) ───────────
    proxy_lines: List[str] = []
    proxy_mode = (body.proxy.mode or "none").lower()
    if proxy_mode == "proxyjet":
        if _PROXYJET_GEN is None:
            raise HTTPException(
                status_code=503,
                detail="ProxyJet generator not bound — install ProxyJet credentials first",
            )
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
            proxy_lines = pj_resp.get("proxies") or []
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("advanced_create: ProxyJet generate failed")
            raise HTTPException(
                status_code=502,
                detail=f"Proxy generation failed: {str(e)[:200]}",
            )
        if len(proxy_lines) < count:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"ProxyJet returned only {len(proxy_lines)} of {count} "
                    f"proxies. Try a different country/state or smaller batch."
                ),
            )

    def _parse_proxy_line_to_cfg(line: str) -> ProxyConfig:
        server = ""
        username = ""
        password = ""
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
                        host, port, username = (
                            colon_parts[0], colon_parts[1], colon_parts[2]
                        )
                        password = ":".join(colon_parts[3:])
                        server = f"{proto}://{host}:{port}"
                    elif len(colon_parts) == 2:
                        server = f"{proto}://{colon_parts[0]}:{colon_parts[1]}"
                    elif len(colon_parts) == 1:
                        server = line
                    else:
                        server = f"{proto}://{colon_parts[0]}:{colon_parts[1]}"
            elif "@" in line:
                creds, hostport = line.rsplit("@", 1)
                username, _, password = creds.partition(":")
                server = f"http://{hostport}"
            else:
                parts = line.split(":")
                if len(parts) >= 4:
                    host, port, username = parts[0], parts[1], parts[2]
                    password = ":".join(parts[3:])
                    server = f"http://{host}:{port}"
                elif len(parts) >= 2:
                    server = f"http://{parts[0]}:{parts[1]}"
        except Exception as _pe:
            logger.warning(f"advanced_create: proxy line parse failed: {_pe}")
            server = line
        return ProxyConfig(
            enabled=True,
            server=server,
            username=username,
            password=password,
            use_proxyjet=True,
            proxyjet_country=(body.proxy.country or "").upper() or "US",
            proxyjet_state=(body.proxy.state or "").upper(),
        )

    pad = max(2, len(str(count)))
    docs: List[Dict[str, Any]] = []
    used_device_ids: Set[str] = set()
    seen_ua: Set[str] = set()

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
                provider_id=body.proxy.provider_id,
            )
        elif proxy_mode == "manual" and body.proxy.server:
            proxy_cfg = ProxyConfig(
                enabled=True,
                server=body.proxy.server.strip(),
                username=body.proxy.username or "",
                password=body.proxy.password or "",
            )
        elif proxy_mode == "proxyjet" and i < len(proxy_lines):
            proxy_cfg = _parse_proxy_line_to_cfg(proxy_lines[i].strip())

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
            proxy=proxy_cfg,
            anti_detect=AntiDetectConfig(
                master=bool(body.anti_detect_on),
                tls_prewarm=bool(body.anti_detect_on),
                behavioral_bio=bool(body.anti_detect_on),
                browser_variant="rotate" if body.anti_detect_on else "auto",
                identity_persist=bool(body.anti_detect_on),
            ),
        )
        doc = _profile_doc(uid, pb)
        doc["device_model"] = str(device.get("slug") or "")
        doc["device_label"] = str(device.get("label") or "")
        doc["device_catalog_id"] = str(device.get("id") or "")
        docs.append(doc)

    if docs:
        await _DB.browser_profiles.insert_many(docs)
    return {
        "created": len(docs),
        "profiles": [_public_view(d) for d in docs],
        "ua_source": "live_generator" if _UA_GEN else "fallback_pool",
        "proxy_mode": proxy_mode,
        "proxies_allocated": len(proxy_lines) if proxy_mode == "proxyjet" else 0,
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
    for pid in ids:
        doc = await _DB.browser_profiles.find_one({"id": pid, "user_id": uid}, {"status": 1})
        if not doc:
            skipped.append({"id": pid, "reason": "not_found"})
            continue
        st = str(doc.get("status") or "idle")
        if st in ("running", "launching", "queued", "stopping"):
            skipped.append({"id": pid, "reason": f"busy:{st}"})
            continue
        await _DB.browser_profiles.delete_one({"id": pid, "user_id": uid})
        await _DB.browser_profile_sessions.delete_many({"profile_id": pid, "user_id": uid})
        deleted.append(pid)
    return {"deleted": deleted, "skipped": skipped, "deleted_count": len(deleted)}


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
            doc = await _DB.browser_profiles.find_one({"id": pid, "user_id": uid})
            if not doc:
                results.append({"id": pid, "ok": False, "reason": "not_found"})
                continue
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
                {"id": pid, "user_id": uid},
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
async def bulk_launch(request: Request, body: BulkIdsBody):
    """Launch up to max_concurrent idle profiles (rest skipped with reason)."""
    user = await _resolve_user(request)
    uid = _resolve_user_or_401(user)
    ids = [str(x).strip() for x in (body.profile_ids or []) if str(x).strip()][:50]
    max_c = max(1, min(int(body.max_concurrent or 5), 20))
    if not ids:
        raise HTTPException(status_code=400, detail="profile_ids required")

    launched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for pid in ids:
        if len(launched) >= max_c:
            skipped.append({"id": pid, "reason": "concurrent_cap"})
            continue
        doc = await _DB.browser_profiles.find_one({"id": pid, "user_id": uid})
        if not doc:
            skipped.append({"id": pid, "reason": "not_found"})
            continue
        st = str(doc.get("status") or "idle")
        if st in ("running", "launching", "queued", "stopping"):
            skipped.append({"id": pid, "reason": f"busy:{st}"})
            continue
        # Delegate to existing launch endpoint implementation
        try:
            # Build a minimal internal call by reusing launch_profile
            result = await launch_profile(
                request,
                pid,
                start_url=doc.get("start_url") or None,
            )
            launched.append({"id": pid, "ok": True, **{k: result.get(k) for k in ("session_id", "desktop_available", "message") if isinstance(result, dict)}})
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
    if "fingerprint_hash" in body:
        update["fingerprint_hash"] = str(body["fingerprint_hash"])[:128]
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
