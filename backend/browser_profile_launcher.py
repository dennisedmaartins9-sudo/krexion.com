"""
Krexion — Browser Profile Launcher (LOCAL DESKTOP execution)
==============================================================

Runs ONLY on the customer's local desktop / Electron host process where
Playwright is installed with a real Chromium binary. NOT used on the
cloud VPS (cloud edge just enqueues the bridge job — this file actually
opens the headed browser the customer interacts with).

Execution flow:
  1. sync_client.py pulls a bridge_jobs row with feature="browser-profile/launch"
  2. sync_client.py calls launch_profile_session(...) from THIS module
  3. We start a HEADED Playwright Chromium with the profile's config:
       • user_agent + viewport + device_scale_factor + locale + timezone
       • proxy (manual or ProxyJet-allocated)
       • storage_state (cookies + localStorage from previous sessions)
       • anti-detect script injected via add_init_script (same one RUT uses)
  4. Browser opens to start_url. Customer manually browses.
  5. When the customer closes the LAST page or the browser, we:
       • Export updated storage_state
       • POST to /api/browser-profiles/_bridge/session-update so the
         cloud profile record is updated with new cookies + duration.
  6. Function returns — sync_client marks the bridge job as completed.

This is a fully self-contained module — no FastAPI route. The local
backend invokes it directly via a thin endpoint or via sync_client.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("browser_profile_launcher")

# Track running sessions so the UI / stop endpoint can find them
_RUNNING_SESSIONS: Dict[str, Dict[str, Any]] = {}

# ── 2026-06-28 — Windows Service Session-0 isolation workaround ─────
# On the NSSM-installed customer build (`KREXION_BUILD_TYPE=binary`)
# the backend runs as a Windows Service in Session 0. Services in
# Session 0 CANNOT show GUI windows on the user's desktop — Chromium
# spawns as a headless ghost process the customer never sees, even
# though Playwright reports `launch()` succeeded. This is the root
# cause of the "Browser Profile launch krte hein pr Chromium open ni
# hota" customer report. The Electron build doesn't have this bug
# because its backend is a child of the Electron main process (which
# is itself a user-session GUI app), so child processes inherit the
# user's session and Chromium displays correctly.
#
# Fix: when running as a Windows Service, the backend defers headed
# launches to a small in-process helper INSIDE the existing tray app
# (`desktop/krexion_dashboard.py`), which already runs in the user's
# interactive session via the HKCU Run autostart entry. Coordination
# is via a tiny `browser_launch_queue` collection in the shared local
# MongoDB — no new HTTP endpoint, no IPC complexity.
#
# Detection signal: `KREXION_BUILD_TYPE=binary` is set ONLY by the
# Inno-Setup NSSM installer (see `installer/krexion-setup.iss`).
# Electron + cloud-edge deployments don't set it, so they continue to
# spawn Chromium directly via `asyncio.create_task` exactly as before.
_LAUNCH_QUEUE_COLLECTION = "browser_launch_queue"
# If the tray helper never claims a queued launch, un-stick the profile card.
_USER_SESSION_PICKUP_TIMEOUT_SEC = 60.0

# Headed Profiles — same anti-detect Chromium flags as RUT
# (`real_user_traffic._BROWSER_LAUNCH_ARGS_BASE`), minus headless-only
# switches. Profiles stay HEADED; viewport stays profile-owned.
_PROFILE_HEADED_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-features=AutomationControlled,UseDnsHttpsSvcb",
    "--disable-blink-features=AutomationControlled",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--disable-translate",
    "--disable-default-apps",
    "--disable-component-update",
    "--no-first-run",
    "--no-default-browser-check",
    "--metrics-recording-only",
    "--enable-quic",
    "--quic-version=h3",
    # v2.7.7 — no force-all-origins QUIC flag; prefer IPv4-proxy-consistent
    # (avoid dual-stack Chrome feature vs IPv6-exit-reject clash).
    "--enable-features=AddressSpaceTraversal",
    "--disable-infobars",
]


def _should_defer_to_user_session() -> bool:
    """True when the current process runs as the NSSM-installed Windows
    Service. Defers headed browser launches to the tray-app helper
    instead of spawning them inline (which would land in Session 0)."""
    if not sys.platform.startswith("win"):
        return False
    build_type = (os.environ.get("KREXION_BUILD_TYPE") or "").strip().lower()
    return build_type == "binary"


async def _enqueue_for_user_session(
    profile_config: Dict[str, Any],
    session_id: str,
    start_url: str,
    on_session_update: Optional[Any] = None,
) -> Dict[str, Any]:
    """Write a pending launch record so the tray-app helper can pick it
    up and run the headed browser in the user's interactive session.

    The tray app polls the same local MongoDB every ~2s (see
    `process_pending_user_session_launches`) and runs the actual
    Playwright launch with full Session 1+ desktop access.

    We also call the on_session_update callback with status="queued"
    so the frontend UI flips from "launching" to a clearer state
    quickly, instead of staring at "launching..." for 2 seconds while
    the tray app picks up the queue.
    """
    profile_id = str(profile_config.get("id") or "")
    queued_at = _now_iso()
    record = {
        "id": session_id,
        "profile_id": profile_id,
        "profile_config": profile_config,
        "start_url": start_url,
        "status": "queued",
        "queued_at": queued_at,
        "claimed_at": "",
        "completed_at": "",
        "error_message": "",
    }
    try:
        # Lazy import to avoid circulars at module load — server.py is
        # the module that owns the motor client.
        from server import db as _db  # type: ignore
        await _db[_LAUNCH_QUEUE_COLLECTION].insert_one(record)
        logger.info(
            f"[profile-launch] queued for user-session helper "
            f"session_id={session_id[:8]} profile={profile_id[:8]}"
        )
    except Exception as exc:  # noqa: BLE001
        # If we can't even queue the launch, fall back to inline launch
        # so the customer at least sees the error rather than silently
        # losing the click.
        logger.warning(
            f"[profile-launch] queue insert failed ({exc}); falling back "
            f"to inline launch (may not display on NSSM service)"
        )
        return await _launch_inline_for_fallback(
            profile_config,
            session_id=session_id,
            start_url=start_url,
            on_session_update=on_session_update,
        )

    # Tell the frontend the launch is queued. The tray helper will then
    # send "running"/"closed"/"error" updates via the same callback when
    # it processes the queue entry.
    if on_session_update is not None:
        try:
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "queued",
                "message": "Waiting for Krexion tray (user session) to open Chromium…",
            })
        except Exception as _cb_err:  # noqa: BLE001
            logger.debug(f"queued-callback failed: {_cb_err}")

    # Watchdog: if tray never claims within N seconds, fail closed with a
    # clear error so the card does not stay on "launching/queued" forever.
    try:
        asyncio.create_task(
            _watch_user_session_pickup(
                session_id=session_id,
                profile_id=profile_id,
                user_id=str(profile_config.get("user_id") or ""),
                on_session_update=on_session_update,
            )
        )
    except Exception as _wd_err:  # noqa: BLE001
        logger.debug(f"[profile-launch] pickup watchdog schedule failed: {_wd_err}")

    return {"ok": True, "session_id": session_id, "queued": True}


async def _watch_user_session_pickup(
    *,
    session_id: str,
    profile_id: str,
    user_id: str = "",
    on_session_update: Optional[Any] = None,
    timeout_sec: float = _USER_SESSION_PICKUP_TIMEOUT_SEC,
) -> None:
    """Fail the launch if tray never claims the queue row in time."""
    try:
        await asyncio.sleep(max(5.0, float(timeout_sec or 60.0)))
    except Exception:
        return
    try:
        from server import db as _db  # type: ignore
    except Exception:
        return
    try:
        row = await _db[_LAUNCH_QUEUE_COLLECTION].find_one(
            {"id": session_id},
            {"status": 1, "_id": 0},
        )
        if not row or str(row.get("status") or "") != "queued":
            return  # claimed / cancelled / finished
        err = (
            "Browser launch timed out — Krexion tray helper did not pick up the job. "
            "Open the Krexion icon in the Windows system tray (or restart Krexion), "
            "then click Launch again."
        )
        await _db[_LAUNCH_QUEUE_COLLECTION].update_one(
            {"id": session_id, "status": "queued"},
            {"$set": {
                "status": "error",
                "error_message": err,
                "completed_at": _now_iso(),
            }},
        )
        await _db.browser_profile_sessions.update_one(
            {"id": session_id},
            {"$set": {
                "status": "error",
                "error_message": err[:512],
                "ended_at": _now_iso(),
            }},
        )
        _prof_q: Dict[str, Any] = {
            "status": "error",
            "session_id": "",
            "last_error": err[:512],
        }
        if user_id:
            await _db.browser_profiles.update_one(
                {"id": profile_id, "user_id": user_id},
                {"$set": _prof_q},
            )
        else:
            await _db.browser_profiles.update_one(
                {"id": profile_id},
                {"$set": _prof_q},
            )
        if on_session_update is not None:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": "error",
                    "error_message": err,
                })
            except Exception:
                pass
        logger.warning(
            f"[profile-launch] tray pickup timeout session_id={session_id[:8]} "
            f"profile={profile_id[:8]}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[profile-launch] pickup watchdog failed: {exc}")


async def expire_stale_user_session_launches(
    motor_db: Any,
    *,
    older_than_sec: float = _USER_SESSION_PICKUP_TIMEOUT_SEC,
) -> int:
    """Mark long-queued launches as error (tray drain safety net)."""
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(15.0, float(older_than_sec or 60.0)))
    cutoff_iso = cutoff.isoformat()
    err = (
        "Browser launch timed out — Krexion tray helper did not pick up the job. "
        "Open the Krexion system-tray app, then click Launch again."
    )
    expired = 0
    try:
        async for doc in motor_db[_LAUNCH_QUEUE_COLLECTION].find({
            "status": "queued",
            "queued_at": {"$lt": cutoff_iso},
        }):
            sid = str(doc.get("id") or "")
            pid = str(
                (doc.get("profile_config") or {}).get("id")
                or doc.get("profile_id")
                or ""
            )
            uid = str((doc.get("profile_config") or {}).get("user_id") or "")
            try:
                await motor_db[_LAUNCH_QUEUE_COLLECTION].update_one(
                    {"id": sid, "status": "queued"},
                    {"$set": {
                        "status": "error",
                        "error_message": err,
                        "completed_at": _now_iso(),
                    }},
                )
                if sid:
                    await motor_db.browser_profile_sessions.update_one(
                        {"id": sid},
                        {"$set": {
                            "status": "error",
                            "error_message": err[:512],
                            "ended_at": _now_iso(),
                        }},
                    )
                if pid:
                    q = {"id": pid}
                    if uid:
                        q["user_id"] = uid
                    await motor_db.browser_profiles.update_one(
                        q,
                        {"$set": {
                            "status": "error",
                            "session_id": "",
                            "last_error": err[:512],
                        }},
                    )
                expired += 1
            except Exception:
                continue
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[user-session] expire stale failed: {exc}")
    return expired


async def _launch_inline_for_fallback(*args, **kwargs) -> Dict[str, Any]:
    """Internal: fallback path when queue insert fails. Calls the real
    launcher inline. Imported lazily to avoid recursion on import."""
    # Manually re-invoke the inner inline launch flow. We rebuild the
    # same arguments the wrapped function expects.
    profile_config = args[0] if args else kwargs.get("profile_config")
    session_id = kwargs.get("session_id")
    start_url = kwargs.get("start_url")
    on_session_update = kwargs.get("on_session_update")
    return await _launch_session_inline(
        profile_config,
        session_id=session_id,
        start_url=start_url,
        on_session_update=on_session_update,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_os_from_ua(ua: str, *, fallback: str = "windows") -> str:
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
    except Exception:
        pass
    return fallback


def _resolve_geo_for_profile(profile_config: Dict[str, Any]) -> Dict[str, Any]:
    country = str(profile_config.get("country") or "us").lower()
    try:
        from visual_recorder import _resolve_country_geo
        loc, tz, al, lat, lon = _resolve_country_geo(country)
    except Exception:
        loc, tz, al, lat, lon = "en-US", "America/New_York", "en-US,en;q=0.9", 40.7128, -74.0060
    return {
        "locale": profile_config.get("locale") or loc,
        "timezone": profile_config.get("timezone") or tz,
        "accept_language": profile_config.get("accept_language") or al,
        "lat": lat,
        "lon": lon,
    }


def _pick_stable(seed: int, choices: List[Any]) -> Any:
    if not choices:
        return None
    return choices[int(seed) % len(choices)]


def _profile_screen_metrics(os_key: str, vw: int, vh: int, seed: int) -> Dict[str, Any]:
    """Screen/outer deltas derived from the PROFILE viewport (not RUT random)."""
    if os_key in ("android", "ios"):
        return {
            "screen_width": vw,
            "screen_height": vh,
            "avail_width": vw,
            "avail_height": vh,
            "outer_width_delta": 0,
            "outer_height_delta": 0,
            "color_depth": 24,
            "max_touch_points": 5 if os_key == "ios" else int(_pick_stable(seed, [5, 10])),
        }
    if os_key == "macos":
        tb = int(_pick_stable(seed, [22, 25, 28]))
        oh = int(_pick_stable(seed >> 3, [74, 87, 105, 130]))
        return {
            "screen_width": max(1280, vw),
            "screen_height": max(800, vh + tb),
            "avail_width": max(1280, vw),
            "avail_height": max(800, vh),
            "outer_width_delta": 0,
            "outer_height_delta": oh,
            "color_depth": 30,
            "max_touch_points": 0,
        }
    if os_key == "linux":
        tb = int(_pick_stable(seed, [24, 40, 60]))
        oh = int(_pick_stable(seed >> 3, [74, 100, 130]))
        return {
            "screen_width": max(1024, vw),
            "screen_height": max(768, vh + tb),
            "avail_width": max(1024, vw),
            "avail_height": max(768, vh),
            "outer_width_delta": 0,
            "outer_height_delta": oh,
            "color_depth": 24,
            "max_touch_points": 0,
        }
    # windows / default
    tb = int(_pick_stable(seed, [40, 48, 60, 80]))
    oh = int(_pick_stable(seed >> 3, [74, 87, 117, 138]))
    return {
        "screen_width": max(1024, vw),
        "screen_height": max(768, vh + tb),
        "avail_width": max(1024, vw),
        "avail_height": max(768, vh),
        "outer_width_delta": 0,
        "outer_height_delta": oh,
        "color_depth": 24,
        "max_touch_points": 0,
    }


def _build_profile_stealth_fp(
    ua: str,
    *,
    profile_id: str,
    viewport: Dict[str, Any],
    dsf: float,
    is_mobile: bool,
    has_touch: bool,
    profile_os: str = "",
) -> Dict[str, Any]:
    """Full RUT fingerprint for Profiles — keep profile viewport/mobile flags.

    Uses `_sync_fingerprint_to_ua` so platform/vendor/HC/WebGL/fonts match
    the UA, then overlays profile-owned viewport + deterministic seeds so
    the same profile always looks like the same device across launches.
    """
    from anti_detect_v230 import _stable_hash as _stable_hash_fn
    from real_user_traffic import _sync_fingerprint_to_ua

    identity = str(profile_id or "profile")
    fp = _sync_fingerprint_to_ua(ua or "", identity_label=identity)

    vw = max(320, int((viewport or {}).get("width") or 1920))
    vh = max(480, int((viewport or {}).get("height") or 1080))
    fp["viewport"] = {"width": vw, "height": vh}
    fp["device_scale_factor"] = float(dsf)
    fp["is_mobile"] = bool(is_mobile)
    fp["has_touch"] = bool(has_touch)
    if profile_os:
        fp["os"] = str(profile_os).lower().strip() or fp.get("os") or "windows"

    os_key = str(fp.get("os") or "windows").lower()
    screen = _profile_screen_metrics(os_key, vw, vh, _stable_hash_fn(f"{identity}:screen"))
    fp.update(screen)
    if has_touch and int(fp.get("max_touch_points") or 0) <= 0:
        fp["max_touch_points"] = 5

    # Stable per-profile noise seeds (RUT uses per-visit random).
    fp["canvas_seed"] = (_stable_hash_fn(f"{identity}:canvas") % (2**30)) or 1
    fp["audio_seed"] = (_stable_hash_fn(f"{identity}:audio") % (2**30)) or 1
    fp["font_seed"] = (_stable_hash_fn(f"{identity}:font") % (2**30)) or 1
    fp["history_length"] = 2 + (int(fp["canvas_seed"]) % 4)

    # Desktop HC/DM: stabilize (mobile keeps UA-device-coupled values from RUT).
    if os_key not in ("android", "ios"):
        fp["hardware_concurrency"] = int(
            _pick_stable(_stable_hash_fn(f"{identity}:hc"), [4, 8, 12, 16])
        )
        fp["device_memory"] = int(
            _pick_stable(_stable_hash_fn(f"{identity}:dm"), [4, 8, 16, 32])
        )

    # Battery / network — deterministic snapshot per profile.
    if os_key in ("android", "ios"):
        bl = 0.18 + ((_stable_hash_fn(f"{identity}:bat") % 7400) / 10000.0)
        fp["battery_level"] = round(min(0.92, max(0.18, bl)), 2)
        fp["battery_charging"] = bool(_stable_hash_fn(f"{identity}:batc") % 100 < 35)
        fp["effective_type"] = _pick_stable(
            _stable_hash_fn(f"{identity}:net"), ["4g", "4g", "4g", "3g"]
        )
        fp["downlink"] = round(
            2.5 + ((_stable_hash_fn(f"{identity}:dl") % 750) / 100.0), 1
        )
        fp["rtt"] = int(
            _pick_stable(_stable_hash_fn(f"{identity}:rtt"), [50, 100, 150, 200, 300])
        )
        fp["connection_type"] = "cellular"
    else:
        bl = 0.45 + ((_stable_hash_fn(f"{identity}:bat") % 5300) / 10000.0)
        fp["battery_level"] = round(min(0.98, max(0.45, bl)), 2)
        fp["battery_charging"] = bool(_stable_hash_fn(f"{identity}:batc") % 100 < 70)
        fp["effective_type"] = "4g"
        fp["downlink"] = round(
            5.0 + ((_stable_hash_fn(f"{identity}:dl") % 1500) / 100.0), 1
        )
        fp["rtt"] = int(
            _pick_stable(_stable_hash_fn(f"{identity}:rtt"), [25, 50, 75, 100])
        )
        fp["connection_type"] = "wifi"

    # Required keys for `_build_stealth_script` — never leave sparse.
    for key, default in (
        ("platform", "Win32"),
        ("vendor", "Google Inc."),
        ("hardware_concurrency", 8),
        ("device_memory", 8),
        ("webgl_vendor", "Google Inc."),
        ("webgl_renderer", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"),
        ("canvas_seed", 1),
    ):
        if key not in fp or fp.get(key) in (None, ""):
            fp[key] = default

    return fp


async def _align_profile_geo_from_proxy(
    geo: Dict[str, Any],
    proxy_arg: Optional[Dict[str, Any]],
    ua: str,
    profile_config: Dict[str, Any],
) -> Dict[str, Any]:
    """When a proxy is set, align locale/tz/lat/lon to the exit IP (RUT parity).

    Probe always wins for timezone/locale/accept_language/lat/lon so the
    browser fingerprint matches the exit IP (profile overrides are logged
    when they conflict).
    """
    if not proxy_arg or not proxy_arg.get("server"):
        return geo
    try:
        from real_user_traffic import _probe_proxy_geo
        uid = str(profile_config.get("user_id") or "") or None
        probed = await _probe_proxy_geo(proxy_arg, ua or "", user_id=uid)
        if not probed.get("ok"):
            return geo
        out = dict(geo)
        out["lat"] = float(probed.get("lat") if probed.get("lat") is not None else out["lat"])
        out["lon"] = float(probed.get("lon") if probed.get("lon") is not None else out["lon"])
        if probed.get("timezone"):
            out["timezone"] = probed["timezone"]
        if probed.get("locale"):
            out["locale"] = probed["locale"]
        if probed.get("accept_language"):
            out["accept_language"] = probed["accept_language"]
        # Warn if profile had conflicting explicit geo (probe still wins).
        _prof_tz = str(profile_config.get("timezone") or "").strip()
        _prof_loc = str(profile_config.get("locale") or "").strip()
        if _prof_tz and out.get("timezone") and _prof_tz != out.get("timezone"):
            logger.warning(
                f"[profile-launch] profile timezone '{_prof_tz}' conflicts with "
                f"proxy exit tz '{out.get('timezone')}' — using probe"
            )
        if _prof_loc and out.get("locale") and _prof_loc != out.get("locale"):
            logger.warning(
                f"[profile-launch] profile locale '{_prof_loc}' conflicts with "
                f"proxy exit locale '{out.get('locale')}' — using probe"
            )
        logger.info(
            f"[profile-launch] geo aligned to proxy exit "
            f"ip={probed.get('exit_ip')} tz={out.get('timezone')} "
            f"city={probed.get('city')}"
        )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[profile-launch] proxy geo align skipped: {exc}")
        return geo


def _coerce_profile_ua(ua: str, profile_config: Dict[str, Any]) -> str:
    referrer = profile_config.get("referrer") or {}
    platform = ""
    if referrer.get("enabled"):
        pw = referrer.get("platform_weights") or {}
        if isinstance(pw, dict) and pw:
            try:
                platform = max(pw, key=lambda k: float(pw.get(k) or 0))
            except Exception:
                platform = next(iter(pw.keys()), "")
        if not platform and referrer.get("brand"):
            platform = str(referrer.get("brand")).lower()
    if not platform:
        try:
            from real_user_traffic import _get_referer_from_ua, _platform_from_referer_url
            ref = _get_referer_from_ua(ua)
            platform = _platform_from_referer_url(ref) or ""
        except Exception:
            platform = ""
    if platform:
        try:
            from referrer_pro import coerce_ua_for_platform
            return coerce_ua_for_platform(ua, platform)
        except Exception:
            pass
    return ua


def _compute_fingerprint_hash(
    ua: str,
    viewport: Dict[str, Any],
    profile_id: str,
    webgl_cfg: Optional[Dict[str, Any]],
) -> str:
    import hashlib
    payload = "|".join([
        ua or "",
        str(viewport.get("width", "")),
        str(viewport.get("height", "")),
        profile_id or "",
        str((webgl_cfg or {}).get("vendor", "")),
        str((webgl_cfg or {}).get("renderer", "")),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


async def _resolve_referer_for_goto(
    ua: str,
    profile_config: Dict[str, Any],
    target_url: str,
) -> tuple:
    """Return (referer_url, extra_headers) for the first navigation."""
    referrer = profile_config.get("referrer") or {}
    if not referrer.get("enabled"):
        return "", {}
    try:
        from real_user_traffic import _resolve_visit_referer
        pw = referrer.get("platform_weights") or {}
        ew = referrer.get("email_weights") or {}
        cfg = {
            "enabled": True,
            "pro_mode": bool(referrer.get("pro_mode", True)),
            "platform_weights": json.dumps(pw) if isinstance(pw, dict) else str(pw or ""),
            "email_weights": json.dumps(ew) if isinstance(ew, dict) else str(ew or ""),
            "brand": str(referrer.get("brand") or ""),
            "target_url": target_url,
            "country": profile_config.get("country"),
            "search_engine": str(referrer.get("search_engine") or "google"),
            "search_keywords": str(referrer.get("search_keywords") or ""),
            "social_wrapper": bool(referrer.get("social_wrapper", True)),
            "inapp_deep_path": bool(referrer.get("inapp_deep_path", True)),
            "strip_search_path": bool(referrer.get("strip_search_path", True)),
            "network_click_chain": bool(referrer.get("network_click_chain", False)),
        }
        ref_url, _plat, _esp, extras = _resolve_visit_referer(ua, cfg)
        extra_headers: Dict[str, str] = {}
        sf = (extras or {}).get("sec_fetch") or {}
        if isinstance(sf, dict):
            extra_headers.update({str(k): str(v) for k, v in sf.items()})
        return ref_url or "", extra_headers
    except Exception as _ref_err:
        logger.debug(f"profile referer resolve skipped: {_ref_err}")
        return "", {}


async def launch_profile_session(
    profile_config: Dict[str, Any],
    *,
    session_id: str,
    start_url: str,
    on_session_update: Optional[Any] = None,
) -> Dict[str, Any]:
    """Open a HEADED Chromium for manual browsing with all anti-detect
    layers applied. Blocks until the customer closes the browser.

    2026-06-28: on the NSSM-installed Windows native build the call
    is silently rerouted to `_enqueue_for_user_session()` because
    Windows Services in Session 0 cannot display GUI windows. The
    tray app (running in the user's interactive session via the HKCU
    Run autostart) polls the queue and runs the launch instead — see
    `process_pending_user_session_launches` below. All other deployment
    modes (Electron, cloud-edge bridge, dev runs) still spawn inline.

    Args:
        profile_config: Full profile document from MongoDB
        session_id: Unique session id (also used to track stop signals)
        start_url: First URL to navigate to
        on_session_update: Optional async callback to report progress
                           (status, storage_state, duration_sec)

    Returns:
        {"ok": bool, "session_id": ..., "duration_sec": ..., "error": ...}
    """
    # ── 2026-06-28 — Session-0 detection + handoff to tray app ──────
    if _should_defer_to_user_session():
        return await _enqueue_for_user_session(
            profile_config,
            session_id=session_id,
            start_url=start_url,
            on_session_update=on_session_update,
        )
    # Otherwise: in-process inline launch (Electron, cloud-edge bridge, dev)
    return await _launch_session_inline(
        profile_config,
        session_id=session_id,
        start_url=start_url,
        on_session_update=on_session_update,
    )


async def _launch_session_inline(
    profile_config: Dict[str, Any],
    *,
    session_id: str,
    start_url: str,
    on_session_update: Optional[Any] = None,
) -> Dict[str, Any]:
    """Real inline launch flow — the original `launch_profile_session`
    body before the 2026-06-28 Session-0 split. Spawns Chromium directly
    in the current process. Works correctly when the process is in the
    user's interactive session (Electron child, dev run, tray helper).
    """
    # ── 2026-07 (v2.1.59) crash-visibility wrapper ──────────────────────
    # Customer report: Browser Profile "Launch" pressed → card chip
    # stuck on "launching" forever, Chromium never opens. Root cause:
    # every failure path BEFORE the in-body `on_session_update("running")`
    # call (Playwright import error, browser launch crash, context
    # creation OOM, proxy probe explosion, etc.) just `return`ed or
    # raised — and since sync_client fires this function as a
    # `asyncio.create_task(...)`, the exception was silently swallowed
    # by the event loop. The cloud's `_bridge/session-update` endpoint
    # was therefore NEVER notified, so the profile status was wedged
    # at "launching" with no actionable error for the operator.
    #
    # Fix: outer try/except that ALWAYS notifies the cloud with the
    # actual error, plus guaranteed cleanup of `_RUNNING_SESSIONS`.
    profile_id = str(profile_config.get("id") or "")

    async def _notify_error(msg: str) -> None:
        """Best-effort cloud notification so the UI un-sticks from
        'launching' and shows the real reason. Failure here is logged
        but never re-raised — we already have an error to report."""
        logger.warning(f"[profile-launch] session={session_id[:8]} ERROR: {msg}")
        if on_session_update is None:
            return
        try:
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "error",
                "error_message": msg,
            })
        except Exception as _nerr:  # noqa: BLE001
            logger.warning(f"[profile-launch] error notify itself failed: {_nerr}")

    try:
        try:
            from playwright.async_api import async_playwright
        except ImportError as _ie:
            await _notify_error(
                "Playwright is not installed on this host. The Krexion "
                "desktop install should auto-bundle it; please reinstall "
                "or run `python -m playwright install chromium` manually."
            )
            return {"ok": False, "error": f"Playwright not installed: {_ie}"}

        # ── v2.1.59 Pre-flight: Chromium binary readiness check ─────────
        # On a fresh Krexion install the PowerShell installer tries to
        # download the pre-bundled Chromium ZIP from GitHub Releases —
        # when that step is skipped/fails it logs:
        #   "Krexion backend will auto-download Chromium on first launch"
        # The actual download is then kicked off in the backend's
        # startup hook (_ensure_playwright_chromium) and runs for ~60s.
        # If the customer clicks Launch on a Browser Profile DURING that
        # window, Playwright's `chromium.launch()` raises a cryptic
        # "Executable doesn't exist at ..." error. We pre-check the
        # binary HERE and surface a friendly status that the UI can
        # render — auto-triggering the install if it hasn't started yet,
        # so the customer's next click "just works" after ~60-90s.
        try:
            from real_user_traffic import get_engine_status, _ensure_chromium_available  # type: ignore
            engine = get_engine_status()
            estatus = (engine or {}).get("status") or "error"
            if estatus == "ready":
                pass  # All good — proceed to launch
            elif estatus == "installing":
                await _notify_error(
                    "Chromium browser engine is still downloading "
                    "(~150 MB). Please wait ~60 seconds and click "
                    "Launch again."
                )
                return {"ok": False, "session_id": session_id,
                        "error": "chromium_installing"}
            elif estatus == "missing":
                # Kick off the install in the background and tell the
                # operator to retry. We deliberately don't await here —
                # the download takes too long for a synchronous UI click.
                try:
                    asyncio.create_task(_ensure_chromium_available())
                except Exception:  # noqa: BLE001
                    pass
                await _notify_error(
                    "Chromium browser engine is missing — downloading "
                    "it now (~150 MB, takes ~60-90 seconds). Click "
                    "Launch again once this banner clears."
                )
                return {"ok": False, "session_id": session_id,
                        "error": "chromium_missing_install_started"}
            else:
                # 'error' or unknown — fall through to the actual launch
                # so Playwright surfaces its native error (better than
                # blocking on a metadata read glitch).
                logger.warning(
                    f"[profile-launch] chromium engine status='{estatus}' "
                    f"(msg={(engine or {}).get('message','')}); continuing anyway"
                )
        except ImportError:
            # real_user_traffic helper isn't available in this build —
            # not fatal, just skip the pre-check and let Playwright handle it.
            logger.debug("[profile-launch] engine status helper not importable; skipping pre-check")
        except Exception as _ge:  # noqa: BLE001
            logger.debug(f"[profile-launch] chromium pre-check skipped: {_ge}")

        started_at = time.time()
        _RUNNING_SESSIONS[session_id] = {
            "profile_id": profile_id,
            "started_at": started_at,
            "stop_requested": False,
        }

        try:
            return await _launch_profile_session_inner(
                profile_config,
                session_id=session_id,
                start_url=start_url,
                on_session_update=on_session_update,
                async_playwright=async_playwright,
                started_at=started_at,
                profile_id=profile_id,
            )
        except Exception as _inner_err:  # noqa: BLE001
            # Surface launch crash to the cloud + frontend UI
            import traceback as _tb
            tb_short = _tb.format_exc()[:600]
            logger.warning(
                f"[profile-launch] launch crashed: {type(_inner_err).__name__}: "
                f"{_inner_err}\n{tb_short}"
            )
            await _notify_error(
                f"{type(_inner_err).__name__}: {str(_inner_err)[:240]}"
            )
            return {"ok": False, "session_id": session_id, "error": str(_inner_err)}
    finally:
        # ALWAYS reclaim the session slot so a hard-crashing launch
        # doesn't leak _RUNNING_SESSIONS entries forever (used by the
        # /stop endpoint to find the right session).
        _RUNNING_SESSIONS.pop(session_id, None)


async def _launch_profile_session_inner(
    profile_config: Dict[str, Any],
    *,
    session_id: str,
    start_url: str,
    on_session_update: Optional[Any],
    async_playwright: Any,
    started_at: float,
    profile_id: str,
) -> Dict[str, Any]:
    """Real launch flow — kept separate so the outer wrapper can centralise
    crash-notification + cleanup. All previous behaviour preserved."""

    ua = profile_config.get("user_agent") or ""
    viewport = profile_config.get("viewport") or {"width": 1920, "height": 1080}
    is_mobile = bool(profile_config.get("is_mobile"))
    has_touch = bool(profile_config.get("has_touch") or is_mobile)
    dsf = float(profile_config.get("device_scale_factor") or (3.0 if is_mobile else 1.0))
    anti = profile_config.get("anti_detect") or {}
    master = bool(anti.get("master", True))
    identity_persist = bool(anti.get("identity_persist", True))
    tls_prewarm = bool(anti.get("tls_prewarm", False)) and master
    behavioral_bio = bool(anti.get("behavioral_bio", True)) and master
    ip_warmup = bool(anti.get("ip_warmup", False)) and master
    paranoia_mode = bool(anti.get("paranoia_mode", False))

    ua = _coerce_profile_ua(ua, profile_config)
    try:
        from real_user_traffic import _normalize_mobile_ua_for_visit as _norm_ua
        ua, _ua_meta = _norm_ua(ua)
    except Exception:
        _ua_meta = {}
        try:
            from real_user_traffic import _coerce_ua_off_webkit_on_chromium as _coerce_ios
            ua = _coerce_ios(ua)
        except Exception:
            pass
    _profile_engine = str((_ua_meta or {}).get("engine") or "chromium").lower()
    if _profile_engine != "webkit":
        try:
            from anti_detect_v230 import align_ua_to_chromium as _align_chrome
            _aligned = _align_chrome(ua)
            if _aligned:
                ua = _aligned
        except Exception:
            pass
    # v2.7.9 — Re-infer OS from final UA. WebKit path keeps ios; Chromium
    # honesty may have swapped to Android when WebKit was missing.
    inferred_os = _infer_os_from_ua(ua, fallback="")
    if _ua_meta.get("os"):
        profile_os = str(_ua_meta["os"])
    elif inferred_os:
        profile_os = inferred_os
    else:
        profile_os = profile_config.get("os") or (
            "android" if is_mobile else "windows"
        )
    if profile_os in ("android", "ios") or _ua_meta.get("is_mobile"):
        is_mobile = True
        has_touch = True
        if not profile_config.get("device_scale_factor"):
            dsf = 3.0
    geo = _resolve_geo_for_profile(profile_config)
    locale = geo["locale"]
    timezone_id = geo["timezone"]
    accept_lang = geo["accept_language"]

    storage_state = profile_config.get("storage_state") or None
    if not identity_persist:
        storage_state = None

    proxy_cfg = profile_config.get("proxy") or {}
    proxy_arg = None
    proxy_diag: Dict[str, Any] = {"requested": False, "server": "", "ok": None, "error": ""}
    _proxy_enabled = bool(proxy_cfg.get("enabled")) or bool(proxy_cfg.get("use_proxyjet"))
    if _proxy_enabled and proxy_cfg.get("server"):
        # ── 2026-06 — Normalize the proxy server URL ──────────────
        # Customer report: launching a profile errored with
        # ERR_TIMED_OUT on google.com. Root cause: ProxyJet returned
        # lines parsed correctly but the stored `server` value can
        # arrive WITHOUT an `http://` scheme (e.g. just "host:port")
        # which Chromium silently ignores when handed via the
        # `proxy` launch option. Then the browser falls through to
        # the OS direct connection — which on a locked-down Windows
        # host has no route to google.com and times out.
        # We now normalize to a Chromium-acceptable URL form.
        raw_server = str(proxy_cfg["server"]).strip()
        username = str(proxy_cfg.get("username") or "")
        password = str(proxy_cfg.get("password") or "")

        # 2026-06 (follow-up) — Defensive normalization for LEGACY
        # profiles created before the parser fix in
        # browser_profile_module.py.  Some stored proxies still have
        # the format `http://user:pass@host` (port stripped, creds
        # baked into URL) which Chromium silently defaults to port 80
        # for — causing the customer's "Proxy could not be reached"
        # within 10s on EVERY profile launch.  We rebuild the proxy
        # tuple from whatever shape was saved so old and new
        # profiles BOTH work.
        try:
            from urllib.parse import urlparse, urlunparse
            # 1. Ensure a scheme so urlparse can work.
            if "://" not in raw_server:
                # If creds are embedded without scheme (rare): user:pass@host[:port]
                raw_server = f"http://{raw_server}"
            # 1.5. 2026-07 v2.2.2 fix — Legacy profiles saved with the
            # `scheme://host:port:user:pass` format (BestGo / GeoNode
            # / rotating residentials) confused urlparse into treating
            # the fourth colon-separated field as a port, or into
            # exposing "http" as the hostname when everything after
            # the scheme was mis-tokenised. Result: Chromium's DNS
            # lookup came back with "ENOTFOUND http" within 10 s.
            # We strip the extra fields BEFORE urlparse sees them so
            # every legacy profile now launches cleanly.  Creds are
            # promoted to the separate username / password fields
            # that Chromium's proxy launch option expects.
            try:
                _proto_head, _proto_rest = raw_server.split("://", 1)
                if "@" not in _proto_rest:
                    _cp = _proto_rest.split(":")
                    if len(_cp) >= 4:
                        _h, _p, _u = _cp[0], _cp[1], _cp[2]
                        _pw = ":".join(_cp[3:])
                        raw_server = f"{_proto_head}://{_h}:{_p}"
                        if not username:
                            username = _u
                        if not password:
                            password = _pw
            except Exception:
                pass  # fall through to urlparse below
            parsed = urlparse(raw_server)
            host = parsed.hostname or ""
            port = parsed.port  # None when not specified
            # 2. Pull creds out of the URL if Chromium would otherwise
            #    see them inline (it ignores them when the separate
            #    `username`/`password` launch fields are also set, and
            #    sometimes mangles auth when both forms collide).
            if parsed.username and not username:
                username = parsed.username
            if parsed.password and not password:
                password = parsed.password
            # 3. Default port heuristics — the #1 root cause of the
            #    Proxy-could-not-be-reached error.  ProxyJet's gateways
            #    listen on port 1010; everything else gets the
            #    HTTP-proxy default of 8080 only when truly missing.
            if not port:
                lower_host = host.lower()
                if "proxy-jet.io" in lower_host:
                    port = 1010
                elif lower_host.endswith("smartproxy.com") or "smartproxy" in lower_host:
                    port = 7000
                elif "brightdata" in lower_host or "luminati" in lower_host:
                    port = 22225
                else:
                    # Leave port unset — Chromium uses 80 for http://
                    # and 443 for https://.  We can't guess better.
                    pass
            # 4. Rebuild the canonical scheme://host[:port] (no creds in URL).
            scheme = parsed.scheme or "http"
            if scheme not in ("http", "https", "socks5", "socks5h", "socks4"):
                scheme = "http"
            netloc = host if not port else f"{host}:{port}"
            raw_server = urlunparse((scheme, netloc, "", "", "", "")) if host else raw_server
        except Exception as _ne:
            logger.warning(f"[profile-launch] proxy URL normalize failed (using raw): {_ne}")
            if "://" not in raw_server:
                raw_server = f"http://{raw_server}"

        proxy_arg = {"server": raw_server}
        if username:
            proxy_arg["username"] = username
        if password:
            proxy_arg["password"] = password
        proxy_diag["requested"] = True
        proxy_diag["server"] = raw_server
    elif _proxy_enabled and not proxy_cfg.get("server"):
        proxy_diag["requested"] = True
        proxy_diag["ok"] = False
        proxy_diag["error"] = "Proxy enabled but no server URL could be resolved (check ProxyJet credentials)"

    # RUT parity: when proxy is live, align timezone/locale/geo to exit IP.
    geo = await _align_profile_geo_from_proxy(geo, proxy_arg, ua, profile_config)
    locale = geo["locale"]
    timezone_id = geo["timezone"]
    accept_lang = geo["accept_language"]

    async with async_playwright() as p:
        # Browser binary selection — prefer Chrome channel for realism,
        # fall back to bundled Chromium when not installed.
        # 2026-07 v2.2.6 — Krexion profile identity.
        # Customer ask: "chrome na show ho hamara apna krexion ka icon
        # he show ho or os ka sath number yan nam k pehla haraf show
        # ho jese chrome profile mein show hota hai" — the taskbar icon
        # is a bundled resource inside chrome.exe / chromium.exe so we
        # can NOT change it at runtime without shipping a custom binary
        # (that's a native-installer-level task tracked separately).
        # BUT we CAN light up Chromium's OWN native profile badge
        # (colored circle with the profile letter in the top-right
        # corner) by passing `--user-data-dir` pointing at a folder
        # named after this Krexion profile.  We also set the window
        # title prefix so the taskbar entry reads "Krexion".
        #
        # 2026-01 v2.4.1 — REVERTED per-tab favicon + per-tab title
        # override.  Customer feedback:
        #   "jitne tab kholte sab pr krexion ka logo a raha hai ye
        #    esa ni hona chahye balke jese orignal hota hai wese
        #    hona chahye"
        # We now leave EACH TAB's favicon + title exactly as the site
        # itself sets them (so myip.com shows the myip.com favicon,
        # not a Krexion K).  The Krexion identity now lives EXCLUSIVELY
        # on the Windows taskbar (via WM_SETICON + AppUserModelID) and
        # on Chromium's own profile-badge chip in the top-right of the
        # main window — both of which are correct places to brand the
        # browser instance without touching per-tab UI.
        _profile_label = (
            profile_config.get("name")
            or profile_config.get("id")
            or profile_config.get("label")
            or "Profile"
        )
        _profile_first_letter = (str(_profile_label)[:1] or "K").upper()
        # v2.4.1 — Register AppUserModelID BEFORE spawning Chromium so
        # Windows' shell groups the incoming child under a dedicated
        # "Krexion" taskbar entry from the very first frame paint,
        # instead of the generic "Google Chrome" entry (which is how
        # v2.2.7 was leaking the Chrome logo).
        try:
            if sys.platform.startswith("win"):
                import ctypes as _ctypes_pre
                _pre_appid = f"Krexion.BrowserProfile.{str(_profile_label)[:60] or 'Profile'}"
                _ctypes_pre.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_pre_appid)
        except Exception:
            pass
        try:
            import tempfile as _tf
            _kx_user_data_root = os.environ.get(
                "KREXION_PROFILE_DATA_ROOT",
                os.path.join(_tf.gettempdir(), "krexion_browser_profiles"),
            )
            _safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(_profile_label))[:60] or "Profile"
            _kx_user_data_dir = os.path.join(_kx_user_data_root, _safe_label)
            os.makedirs(_kx_user_data_dir, exist_ok=True)
        except Exception:
            _kx_user_data_dir = ""
        launch_kwargs: Dict[str, Any] = {
            "headless": False,
            "args": [
                *_PROFILE_HEADED_LAUNCH_ARGS,
                # Window title until first page paint; site title takes over after.
                f"--window-name=Krexion \u2014 {_profile_label} ({_profile_first_letter})",
            ],
        }
        if _kx_user_data_dir:
            launch_kwargs["args"].append(f"--user-data-dir={_kx_user_data_dir}")
        # Chromium: proxy on launch. WebKit: prefer proxy on context (below).
        if proxy_arg and _profile_engine != "webkit":
            launch_kwargs["proxy"] = proxy_arg

        if _profile_engine == "webkit":
            # Playwright WebKit — no channel=chrome, no Chromium CLI flags.
            wk_kwargs: Dict[str, Any] = {"headless": False}
            try:
                browser = await p.webkit.launch(**wk_kwargs)
            except Exception as _wk_err:
                logger.warning(
                    "WebKit launch failed (%s) — falling back to Chromium",
                    _wk_err,
                )
                _profile_engine = "chromium"
                try:
                    from real_user_traffic import (
                        _normalize_mobile_ua_for_chromium as _norm_chr,
                    )
                    ua, _fb_meta = _norm_chr(ua)
                    if _fb_meta.get("os"):
                        profile_os = str(_fb_meta["os"])
                    if _fb_meta.get("is_mobile"):
                        is_mobile = True
                        has_touch = True
                    try:
                        from anti_detect_v230 import align_ua_to_chromium as _align_chrome
                        _aligned = _align_chrome(ua)
                        if _aligned:
                            ua = _aligned
                    except Exception:
                        pass
                except Exception:
                    pass
                if proxy_arg:
                    launch_kwargs["proxy"] = proxy_arg
                channel = None
                variant = (anti.get("browser_variant") or "auto").lower()
                if variant in ("chrome", "rotate"):
                    channel = "chrome"
                try:
                    browser = (
                        await p.chromium.launch(channel=channel, **launch_kwargs)
                        if channel
                        else await p.chromium.launch(**launch_kwargs)
                    )
                except Exception:
                    browser = await p.chromium.launch(**launch_kwargs)
        else:
            # Pick channel (Chromium only)
            channel: Optional[str] = None
            variant = (anti.get("browser_variant") or "auto").lower()
            if variant in ("chrome", "rotate"):
                channel = "chrome"  # Falls back if not installed
            try:
                browser = await p.chromium.launch(channel=channel, **launch_kwargs) if channel else await p.chromium.launch(**launch_kwargs)
            except Exception:
                # Channel not present → fallback to bundled
                browser = await p.chromium.launch(**launch_kwargs)

        # 2026-07 v2.2.7 — Krexion taskbar icon override (Windows only).
        # 2026-01 v2.4.1 — Improved reliability: we now walk ALL Chromium
        # descendants of the Playwright driver PID via psutil (Chromium
        # spawns 5-10 helper processes; only the main "browser" process
        # owns the visible top-level window we need to WM_SETICON, and
        # Playwright's `_impl_obj._process.pid` often points to the
        # Node driver — NOT the Chromium browser process).
        # AppUserModelID was already set pre-launch (above); the loop
        # below just decorates every visible window it can find.
        try:
            _driver_pid = None
            try:
                _proc = getattr(getattr(browser, "_impl_obj", browser), "_process", None)
                if _proc is not None:
                    _driver_pid = getattr(_proc, "pid", None)
            except Exception:
                _driver_pid = None
            # Build the PID set: driver + all descendants (walk on-demand
            # inside the loop so newly-spawned Chromium helpers are
            # picked up as tabs open).
            _target_pids: List[int] = []
            if _driver_pid:
                _target_pids.append(int(_driver_pid))
                try:
                    import psutil as _psu
                    for _child in _psu.Process(int(_driver_pid)).children(recursive=True):
                        try:
                            _target_pids.append(int(_child.pid))
                        except Exception:
                            pass
                except Exception:
                    # psutil missing or process gone — driver PID alone
                    # is still useful for the first WM_SETICON pass.
                    pass
            if _target_pids:
                from krexion_window_icon import apply_krexion_icon_to_pids
                apply_krexion_icon_to_pids(
                    _target_pids,
                    profile_label=str(_profile_label)[:60] or "Profile",
                    parent_pid=int(_driver_pid) if _driver_pid else None,
                )
        except Exception as _icon_err:
            logger.debug(f"Krexion taskbar-icon override skipped: {_icon_err}")

        context_kwargs: Dict[str, Any] = {
            "user_agent": ua,
            "viewport": {"width": int(viewport.get("width", 1920)), "height": int(viewport.get("height", 1080))},
            "device_scale_factor": dsf,
            "is_mobile": is_mobile,
            "has_touch": has_touch,
            "locale": locale,
            "timezone_id": timezone_id,
            "geolocation": {
                "latitude": float(geo.get("lat") or 40.7128),
                "longitude": float(geo.get("lon") or -74.0060),
            },
            "permissions": ["geolocation"],
            "extra_http_headers": {"Accept-Language": accept_lang},
        }
        if _profile_engine == "webkit" and proxy_arg:
            context_kwargs["proxy"] = proxy_arg
        if storage_state and (storage_state.get("cookies") or storage_state.get("origins")):
            context_kwargs["storage_state"] = storage_state

        context = await browser.new_context(**context_kwargs)

        _webgl_cfg: Optional[Dict[str, Any]] = None
        _profile_ua = str(context_kwargs.get("user_agent") or ua)
        try:
            from anti_detect_v230 import align_webgl_to_ua_deterministic as _align_webgl
            _webgl_cfg = _align_webgl(_profile_ua, profile_id or session_id)
        except Exception:
            _webgl_cfg = None
        _fingerprint_hash = _compute_fingerprint_hash(_profile_ua, context_kwargs["viewport"], profile_id, _webgl_cfg)

        # v2.4.1 — Per-tab Krexion favicon + title-prefix injection has
        # been INTENTIONALLY REMOVED.  Prior versions (v2.2.6 → v2.4.0)
        # ran an init script on every page that:
        #     • deleted every <link rel="icon"> node
        #     • replaced it with a Krexion K-badge SVG data URL
        #     • prefixed document.title with "Krexion — <label>: "
        # Customer feedback (2026-01):
        #     "jitne tab kholte sab pr krexion ka logo a raha hai ye
        #      esa ni hona chahye balke jese orignal hota hai wese
        #      hona chahye"
        # Krexion branding now lives ONLY on:
        #     1. The Windows taskbar entry (WM_SETICON above swaps the
        #        Chrome logo for the Krexion K-badge on the taskbar +
        #        alt-tab + title-bar chip).
        #     2. Chromium's own profile badge (colored circle with the
        #        profile's first-letter in the top-right corner —
        #        rendered by Chromium when `--user-data-dir` points
        #        at a per-profile folder, done above).
        # Each tab now displays its site's REAL favicon and title,
        # matching how a stock Chrome install behaves — professional
        # and correct.

        # v2.6.30 — RUT-grade client hints before v2.3.0 merge (TikTok/FB-iOS
        # Sec-CH-UA suppression must not be overwritten by Chrome brands).
        _profile_ch_hints: Dict[str, str] = {}
        try:
            from real_user_traffic import _build_client_hint_headers as _bld_ch
            _os_hint = profile_os or ("android" if is_mobile else "windows")
            _profile_ch_hints = _bld_ch(
                {"os": _os_hint, "is_mobile": is_mobile},
                ua,
            )
            _pre = dict(context_kwargs.get("extra_http_headers") or {})
            _pre.update(_profile_ch_hints)
            context_kwargs["extra_http_headers"] = _pre
        except Exception as _ch_err:
            logger.debug(f"profile client-hint build skipped: {_ch_err}")

        try:
            from referrer_pro import make_sec_ch_ua_strip_route_handler
            await context.route("**/*", make_sec_ch_ua_strip_route_handler())
        except Exception as _route_err:
            logger.debug(f"profile sec-ch-ua route strip skipped: {_route_err}")

        _ctx_hdrs = dict(context_kwargs.get("extra_http_headers") or {})
        _ctx_hdrs["Accept-Language"] = accept_lang

        if master:
            try:
                # v2.7.5 — Full RUT stealth parity (complete fp + same inject
                # order as `_rut_apply_context_stealth`). Profile viewport /
                # headed Chrome stay profile-owned; seeds are stable per id.
                from anti_detect_v230 import _stable_hash as _stable_hash_fn
                from real_user_traffic import _rut_apply_context_stealth

                _stealth_fp = _build_profile_stealth_fp(
                    ua,
                    profile_id=profile_id or session_id,
                    viewport=context_kwargs["viewport"],
                    dsf=dsf,
                    is_mobile=is_mobile,
                    has_touch=has_touch,
                    profile_os=str(profile_os or ""),
                )
                if _stealth_fp.get("webgl_vendor") and _stealth_fp.get("webgl_renderer"):
                    _webgl_cfg = {
                        "vendor": _stealth_fp["webgl_vendor"],
                        "renderer": _stealth_fp["webgl_renderer"],
                        "gpu_family": _stealth_fp.get("gpu_family", ""),
                    }
                    _fingerprint_hash = _compute_fingerprint_hash(
                        _profile_ua,
                        context_kwargs["viewport"],
                        profile_id,
                        _webgl_cfg,
                    )

                geo_stealth = {
                    "locale": locale,
                    "timezone": timezone_id,
                    "accept_language": accept_lang,
                    "lat": geo["lat"],
                    "lon": geo["lon"],
                }
                await _rut_apply_context_stealth(
                    context,
                    fp=_stealth_fp,
                    geo=geo_stealth,
                    ua=ua,
                    platform=str(_stealth_fp.get("platform") or ""),
                    ctx_headers=_ctx_hdrs,
                    fp_hash_override=_stable_hash_fn(str(profile_id or session_id)),
                    identity_label=str(profile_id or session_id),
                )
                logger.info(
                    f"[profile-launch] RUT-parity stealth ON — "
                    f"os={_stealth_fp.get('os')} platform={_stealth_fp.get('platform')} "
                    f"webgl={str(_stealth_fp.get('webgl_renderer') or '')[:48]}"
                )

                if paranoia_mode:
                    await context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                        "window.chrome = window.chrome || { runtime: {} };"
                    )
            except Exception as e:
                logger.warning(f"anti-detect script injection failed: {e}")
                try:
                    context._krx_stealth_degraded = True
                except Exception:
                    pass
                # Minimal fallback — at least hide webdriver flag + try v230
                # (headed Profile soft-fails with warning; visit still opens)
                try:
                    from anti_detect_v230 import apply_v230_stealth
                    _v230_report = await apply_v230_stealth(
                        context, ua=ua, viewport=viewport, platform=""
                    )
                    _extra_hdrs = dict(_ctx_hdrs)
                    _extra_hdrs.update(_v230_report.get("headers") or {})
                    _extra_hdrs.update(_profile_ch_hints)
                    _extra_hdrs["Accept-Language"] = accept_lang
                    await context.set_extra_http_headers(_extra_hdrs)
                except Exception:
                    pass
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
        else:
            # Master anti-detect off — still apply v2.3.0 baseline when possible.
            try:
                from anti_detect_v230 import apply_v230_stealth
                _v230_report = await apply_v230_stealth(
                    context, ua=ua, viewport=viewport, platform=""
                )
                _extra_hdrs = dict(_ctx_hdrs)
                _extra_hdrs.update(_v230_report.get("headers") or {})
                _extra_hdrs.update(_profile_ch_hints)
                _extra_hdrs["Accept-Language"] = accept_lang
                await context.set_extra_http_headers(_extra_hdrs)
            except Exception as _v230_err:
                logger.debug(f"v2.3.0 anti-detect apply skipped: {_v230_err}")

        page = await context.new_page()

        # v2.6.32 — TLS prewarm seeds cookies before first navigation (RUT parity).
        if tls_prewarm:
            try:
                from tls_anti_detect import prewarm_target as _prewarm_target
                _pw_res = await _prewarm_target(
                    start_url or "https://www.google.com/",
                    proxy=proxy_arg,
                    ua=ua,
                    timeout=20.0,
                    accept_language=accept_lang,
                    sec_fetch_kind="ad_click",
                )
                if _pw_res and _pw_res.get("ok") and _pw_res.get("cookies"):
                    await context.add_cookies(_pw_res["cookies"])
            except Exception as _pw_err:
                logger.debug(f"[profile-launch] tls prewarm skipped: {_pw_err}")

        # v2.6.34 — IP warm-up before first navigation (RUT parity, opt-in).
        if ip_warmup:
            try:
                from advanced_anti_detect import warm_up_ip as _warm
                _warm_page = await context.new_page()
                try:
                    _sites = await _warm(_warm_page, visits=2, dwell_sec=4.0)
                    if _sites:
                        logger.info(
                            f"[profile-launch] ip_warmup OK via {len(_sites)} site(s) "
                            f"session={session_id[:8]}"
                        )
                finally:
                    try:
                        await _warm_page.close()
                    except Exception:
                        pass
            except Exception as _wu_err:
                logger.debug(f"[profile-launch] ip_warmup skipped: {_wu_err}")

        _referer_url, _referer_hdrs = await _resolve_referer_for_goto(
            ua, profile_config, start_url or "https://www.google.com/"
        )
        if _referer_hdrs:
            try:
                _cur = dict(context_kwargs.get("extra_http_headers") or {})
                _cur.update(_referer_hdrs)
                await context.set_extra_http_headers(_cur)
            except Exception:
                pass

        # ── 2026-06 — Proxy health pre-check + clear error diagnostic ──
        # Customer report: profile launch errored with "ERR_TIMED_OUT"
        # on google.com with no clue WHY. Most common root cause is
        # the proxy itself (ProxyJet credentials lapsed, IP allocated
        # to a region that's blocked, port unreachable from the
        # customer's local network, etc.). Rather than silently fail
        # the goto, we probe the proxy with a tiny timeout-bounded
        # HEAD-equivalent (`api.ipify.org`, served by Cloudflare) and
        # surface a meaningful diagnostic page if it fails. The user
        # then sees WHY the browser can't reach the target site and
        # can pick a different proxy / disable it / contact support.
        if proxy_arg is not None:
            try:
                import urllib.parse as _urlparse
                _parsed = _urlparse.urlparse(proxy_arg.get("server") or "")
                # 2026-07 v2.2.6 — Probe reliability fix.
                # Customer report:  profile launch failed with
                #   Error: APIRequestContext.get: Client network socket
                #   disconnected before secure TLS connection was
                #   established  Call log: GET https://api.ipify.org/...
                # even after the v2.2.2 URL-parser fix landed the proxy
                # cleanly as `http://us.rrp.bestgo.work:10000` with
                # separate username/password fields.  Root cause: the
                # probe was hitting an HTTPS URL through an HTTP proxy,
                # which requires the proxy to accept a CONNECT tunnel
                # and forward the TLS handshake untouched.  Some
                # residential-rotation proxies (BestGo, GeoNode, etc.)
                # occasionally drop the tunnel mid-handshake — usually
                # because their auth path takes >1 s and Playwright's
                # internal socket timer fires before the TLS layer even
                # starts negotiating.  Meanwhile the SAME proxy works
                # perfectly for the actual browser navigation because
                # Chromium's built-in proxy resolver has a longer grace
                # window and re-issues auth on drop.
                #
                # Fix: probe over PLAIN HTTP instead of HTTPS.  The
                # proxy simply forwards the request — no CONNECT tunnel,
                # no TLS handshake through the proxy — so the auth
                # timing issue is bypassed entirely.  If HTTP is
                # blocked (rare on residential proxies), we fall back
                # to the legacy HTTPS probe as a last-chance check.
                # Multiple probe hosts so a single dead endpoint can't
                # false-positive-flag a healthy proxy.
                _PROBE_URLS = (
                    "http://api.ipify.org/?format=text",       # HTTP first — most reliable
                    "http://checkip.amazonaws.com/",           # AWS metadata — plain-text IP
                    "http://ifconfig.me/ip",                   # DigitalOcean-hosted
                    "https://api.ipify.org/?format=text",      # HTTPS fallback (legacy)
                )
                _last_err = ""
                _exit_ip = ""
                for _pi, _probe_url in enumerate(_PROBE_URLS):
                    try:
                        _probe = await context.request.get(
                            _probe_url,
                            timeout=10000,
                            # 2026-07 — some proxies require a real
                            # browser UA to allow the request through,
                            # so we pass the same UA the browser uses.
                            headers=({"User-Agent": ua} if ua else {}),
                        )
                        _body = (await _probe.text()).strip()
                        if _body and 7 <= len(_body) <= 45:
                            _exit_ip = _body
                            logger.info(
                                f"[profile-launch] proxy probe OK via {_probe_url} "
                                f"(attempt {_pi + 1}/{len(_PROBE_URLS)}) — exit IP {_exit_ip}"
                            )
                            break
                        _last_err = f"non-IP body from {_probe_url}: {_body[:80]}"
                    except Exception as _pe_inner:
                        _last_err = f"{_probe_url}: {type(_pe_inner).__name__}: {str(_pe_inner)[:160]}"
                        logger.debug(f"[profile-launch] probe attempt {_pi + 1} failed: {_last_err}")
                        continue
                if _exit_ip:
                    proxy_diag["ok"] = True
                    proxy_diag["exit_ip"] = _exit_ip
                    # 2026-07 — Cross-check the exit IP against the
                    # user's premium fraud provider accounts (IPQS,
                    # IPHub, Scamalytics, ProxyCheck) so browser
                    # profiles use the SAME fraud filter as RUT
                    # visits. Safe: skipped when the profile has no
                    # user_id (legacy imports) OR when the user has
                    # not enabled their personal fraud filter (falls
                    # back to admin defaults, which is what happens
                    # today).
                    _profile_user_id = str(profile_config.get("user_id") or "")
                    if _profile_user_id:
                        try:
                            from fraud_provider_module import check_ip_for_user as _check_ip_for_user
                            _fraud_res = await _check_ip_for_user(_profile_user_id, _exit_ip)
                            _psource = str(_fraud_res.get("source", "") or "")
                            # Expose result even when clean — the UI's
                            # proxy-diag panel can show the score so
                            # the user knows the check actually ran
                            # with their premium key.
                            proxy_diag["fraud_source"] = _psource
                            proxy_diag["fraud_score"] = _fraud_res.get("vpn_score", 0)
                            proxy_diag["min_fraud_score"] = _fraud_res.get("min_fraud_score")
                            proxy_diag["is_vpn"] = bool(_fraud_res.get("is_vpn"))
                            proxy_diag["risk"] = str(_fraud_res.get("risk", "") or "")
                            if _fraud_res.get("is_vpn"):
                                _score = _fraud_res.get("vpn_score", 0)
                                proxy_diag["fraud_blocked"] = True
                                proxy_diag["ok"] = False
                                proxy_diag["error"] = (
                                    f"Exit IP flagged by fraud detection "
                                    f"({_psource}, score={_score})"
                                )
                                logger.warning(
                                    f"[profile-launch] exit IP {_exit_ip} flagged by "
                                    f"{_psource} (fraud_score={_score}) — session={session_id[:8]}"
                                )
                        except Exception as _fe:
                            logger.debug(f"[profile-launch] fraud provider check failed (non-blocking): {_fe}")
                else:
                    proxy_diag["ok"] = False
                    proxy_diag["error"] = _last_err or "all probe URLs failed"
                    logger.warning(f"[profile-launch] proxy health probe failed after all fallbacks: {_last_err}")
            except Exception as _pe:
                proxy_diag["ok"] = False
                proxy_diag["error"] = f"{type(_pe).__name__}: {str(_pe)[:200]}"
                logger.warning(
                    f"[profile-launch] proxy health probe outer failed: {proxy_diag['error']}"
                )

        # If proxy was REQUESTED but FAILED the probe, show a
        # diagnostic landing page INSTEAD of trying to load the real
        # start_url (which would just give ERR_TIMED_OUT). The
        # operator gets:
        #   • clear message about the proxy issue
        #   • the configured server + username (no password)
        #   • a "Continue without proxy" button via JS that just
        #     navigates to the start_url anyway (proxy-less)
        if proxy_diag.get("fraud_blocked"):
            try:
                _safe_err = str(proxy_diag.get("error") or "").replace("<", "&lt;").replace(">", "&gt;")
                _fraud_html = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>Krexion — Fraud detection blocked</title>"
                    "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
                    "background:#0b0b10;color:#e4e4e7;margin:0;padding:48px;"
                    "min-height:100vh;box-sizing:border-box}"
                    ".card{max-width:720px;margin:0 auto;background:#18181b;"
                    "border:1px solid #3f3f46;border-radius:12px;padding:32px}"
                    "h1{margin:0 0 8px;font-size:22px;color:#fb7185}"
                    ".muted{color:#71717a;font-size:13px;line-height:1.6}"
                    "code{background:#0a0a0f;border:1px solid #27272a;padding:2px 6px;"
                    "border-radius:4px;font-size:13px;color:#fbbf24;word-break:break-all}"
                    "</style></head><body><div class='card'>"
                    "<h1>⚠ Exit IP blocked by fraud detection</h1>"
                    "<p class='muted'>This browser profile's proxy exit IP failed your Settings → Fraud Detection rules. "
                    "Change proxy / country or adjust your fraud threshold before relaunching.</p>"
                    "<code>"+_safe_err+"</code>"
                    "</div></body></html>"
                )
                await page.set_content(_fraud_html, timeout=5000)
            except Exception as _fe:
                logger.warning(f"[profile-launch] fraud block page render failed: {_fe}")
        elif proxy_diag["requested"] and proxy_diag["ok"] is False:
            try:
                _safe_server = str(proxy_diag.get("server") or "").replace("<", "&lt;").replace(">", "&gt;")
                _safe_err = str(proxy_diag.get("error") or "").replace("<", "&lt;").replace(">", "&gt;")
                _safe_start = str(start_url or "https://www.google.com/").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                _diag_html = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>Krexion — Proxy unreachable</title>"
                    "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
                    "background:#0b0b10;color:#e4e4e7;margin:0;padding:48px;"
                    "min-height:100vh;box-sizing:border-box}"
                    ".card{max-width:720px;margin:0 auto;background:#18181b;"
                    "border:1px solid #3f3f46;border-radius:12px;padding:32px}"
                    "h1{margin:0 0 8px;font-size:22px;color:#fb7185}"
                    "h2{margin:24px 0 8px;font-size:14px;color:#a1a1aa;font-weight:600;"
                    "text-transform:uppercase;letter-spacing:0.05em}"
                    "code{background:#0a0a0f;border:1px solid #27272a;padding:2px 6px;"
                    "border-radius:4px;font-size:13px;color:#fbbf24;word-break:break-all}"
                    ".btn{display:inline-block;margin-top:24px;padding:10px 20px;"
                    "background:#7c3aed;color:white;border:none;border-radius:6px;"
                    "font-size:14px;cursor:pointer;text-decoration:none}"
                    ".btn:hover{background:#6d28d9}"
                    ".muted{color:#71717a;font-size:13px;line-height:1.6}"
                    "</style></head><body><div class='card'>"
                    "<h1>⚠ Proxy could not be reached</h1>"
                    "<p class='muted'>Krexion tried to route this browser profile through the configured proxy, "
                    "but the connection failed within 10 seconds. The site would otherwise show ERR_TIMED_OUT with no explanation.</p>"
                    "<h2>Proxy server</h2><code>"+_safe_server+"</code>"
                    "<h2>Reason</h2><code>"+_safe_err+"</code>"
                    "<h2>What to try</h2><ul class='muted'>"
                    "<li>Verify your ProxyJet credentials are still active (Settings → ProxyJet)</li>"
                    "<li>Try a different country / state in the profile's proxy section</li>"
                    "<li>Switch to <code>No Proxy</code> if you only need a clean UA / viewport</li>"
                    "<li>Check that the desktop machine's firewall allows outbound HTTPS</li>"
                    "</ul>"
                    "<a class='btn' href='"+_safe_start+"'>Continue without proxy →</a>"
                    "</div></body></html>"
                )
                await page.set_content(_diag_html, timeout=5000)
            except Exception as _de:
                logger.warning(f"[profile-launch] diagnostic page render failed: {_de}")
        else:
            # ── 2026-06 — Robust goto with retry + clear failure UI ──
            # Customer report: "profile launch kr te hein to error
            # ata hai profile proper os ip k hisab se chalti ni hai".
            # Two failure modes seen:
            #   1. The proxy probe passes (api.ipify is fast + Cloudflare
            #      always reachable) but the actual start_url goto times
            #      out — often because residential proxies blacklist
            #      Google's automation patterns OR the user's local DNS
            #      resolver can't see the target host.
            #   2. The probe is run too early; some ProxyJet sticky
            #      sessions take ~2-5s extra to fully provision a fresh
            #      exit IP, so the probe lands on a partially-warm
            #      tunnel that succeeds but the next request stalls.
            # We now do TWO goto attempts with progressively longer
            # timeouts, and if both fail we set a diagnostic page with
            # the actual error + the configured proxy so the operator
            # can SEE what went wrong instead of staring at the generic
            # Chrome "This site can't be reached" screen.
            _goto_err: Optional[str] = None
            _target_url = start_url or "https://www.google.com/"
            _goto_kwargs: Dict[str, Any] = {"timeout": 45000, "wait_until": "domcontentloaded"}
            if _referer_url:
                _goto_kwargs["referer"] = _referer_url
            for attempt in (1, 2):
                try:
                    _t_goto = 45000 if attempt == 1 else 75000
                    _goto_kwargs["timeout"] = _t_goto
                    await page.goto(_target_url, **_goto_kwargs)
                    _goto_err = None
                    # v2.6.34 — Behavioral bio warm-up after landing (RUT parity).
                    if behavioral_bio:
                        try:
                            from real_user_traffic import _human_warmup as _profile_warmup
                            _fp_warm = {
                                "viewport": context_kwargs.get("viewport") or viewport,
                                "is_mobile": is_mobile,
                            }
                            await _profile_warmup(
                                page, _fp_warm, paranoia=paranoia_mode,
                            )
                        except Exception as _bw_err:
                            logger.debug(f"[profile-launch] behavioral_bio skipped: {_bw_err}")
                    break
                except Exception as e:
                    _goto_err = f"attempt {attempt}/2 ({_t_goto/1000:.0f}s): {type(e).__name__}: {str(e)[:160]}"
                    logger.warning(f"start URL goto failed — {_goto_err}")
                    if attempt == 2:
                        break
                    # Brief sleep before retry — gives slow proxies a
                    # chance to settle their tunnel.
                    await asyncio.sleep(2.0)

            if _goto_err is not None:
                # Both attempts failed — show a clear diagnostic page
                # so the user understands what's happening.
                try:
                    _safe_url = str(_target_url).replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
                    _safe_err = str(_goto_err).replace("<", "&lt;").replace(">", "&gt;")
                    _safe_proxy = str((proxy_arg or {}).get("server") or "(none configured)").replace("<", "&lt;").replace(">", "&gt;")
                    _exit_ip_html = ""
                    if proxy_diag.get("exit_ip"):
                        _exit_ip_html = f"<h2>Last known proxy exit IP</h2><code>{proxy_diag['exit_ip']}</code>"
                    _diag_html = (
                        "<!doctype html><html><head><meta charset='utf-8'>"
                        "<title>Krexion — Page could not load</title>"
                        "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
                        "background:#0b0b10;color:#e4e4e7;margin:0;padding:48px;"
                        "min-height:100vh;box-sizing:border-box}"
                        ".card{max-width:760px;margin:0 auto;background:#18181b;"
                        "border:1px solid #3f3f46;border-radius:12px;padding:32px}"
                        "h1{margin:0 0 8px;font-size:22px;color:#fbbf24}"
                        "h2{margin:24px 0 8px;font-size:13px;color:#a1a1aa;font-weight:600;"
                        "text-transform:uppercase;letter-spacing:0.05em}"
                        "code{background:#0a0a0f;border:1px solid #27272a;padding:2px 6px;"
                        "border-radius:4px;font-size:13px;color:#fbbf24;word-break:break-all;display:inline-block}"
                        ".muted{color:#71717a;font-size:13px;line-height:1.6}"
                        ".pill{display:inline-block;padding:3px 8px;background:#7c3aed;color:white;"
                        "border-radius:9999px;font-size:11px;margin-left:6px}"
                        "</style></head><body><div class='card'>"
                        "<h1>⚠ Could not load the start page<span class='pill'>profile is live — you can still type a URL above</span></h1>"
                        "<p class='muted'>The browser launched successfully but the first navigation timed out. "
                        "This usually means the proxy tunnel is alive enough to pass our quick probe but the destination host "
                        "isn't reachable through it (geo-blocked, captcha wall, or proxy DNS issue).</p>"
                        "<h2>Target URL</h2><code>"+_safe_url+"</code>"
                        "<h2>Configured proxy</h2><code>"+_safe_proxy+"</code>"
                        +_exit_ip_html+
                        "<h2>Error</h2><code>"+_safe_err+"</code>"
                        "<h2>Next steps</h2><ul class='muted'>"
                        "<li>You can still TYPE a different URL in the address bar above — the proxy stays active</li>"
                        "<li>If even known-good sites (e.g. <code>example.com</code>) fail, the proxy is broken — pick a different country/state in the profile and relaunch</li>"
                        "<li>If only the target site fails, that host is blocking your proxy's exit IP — try a residential pool</li>"
                        "<li>To browse without the proxy, close this profile and relaunch with proxy disabled</li>"
                        "</ul></div></body></html>"
                    )
                    await page.set_content(_diag_html, timeout=5000)
                except Exception as _de:
                    logger.warning(f"[profile-launch] post-goto diagnostic page render failed: {_de}")

        # Tell cloud the session is now RUNNING
        if on_session_update:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": "running",
                    "fingerprint_hash": _fingerprint_hash,
                })
            except Exception:
                pass

        # ── Wait until the customer closes the browser ───────────────
        # We poll instead of using a single await so we can also respond
        # to a programmatic stop request from the cloud /stop endpoint.
        closed_event = asyncio.Event()
        _last_storage_flush = time.time()

        def _on_disconnected():
            closed_event.set()

        browser.on("disconnected", lambda *_: _on_disconnected())

        while not closed_event.is_set():
            try:
                await asyncio.wait_for(closed_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                sess = _RUNNING_SESSIONS.get(session_id) or {}
                if sess.get("stop_requested"):
                    try:
                        await context.close()
                    except Exception:
                        pass
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    break
                # Periodic storage_state flush (crash recovery when identity_persist ON)
                if identity_persist and (time.time() - _last_storage_flush) >= 120.0:
                    _last_storage_flush = time.time()
                    try:
                        _snap = await context.storage_state()
                        if on_session_update and _snap:
                            await on_session_update({
                                "profile_id": profile_id,
                                "session_id": session_id,
                                "status": "running",
                                "storage_state": _snap,
                                "fingerprint_hash": _fingerprint_hash,
                            })
                    except Exception as _sf_err:
                        logger.debug(f"[profile-launch] periodic storage flush skipped: {_sf_err}")

        # ── Save storage_state + push to cloud ────────────────────────
        new_storage: Dict[str, Any] = {}
        try:
            if not browser.is_connected():
                # Browser already closed — can't query storage. Skip.
                pass
            else:
                new_storage = await context.storage_state()
                await context.close()
                await browser.close()
        except Exception as e:
            logger.warning(f"storage_state export failed: {e}")

        duration = round(time.time() - started_at, 1)
        _final_status = "stopped" if (_RUNNING_SESSIONS.get(session_id) or {}).get("stop_requested") else "closed"
        if on_session_update:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": _final_status,
                    "storage_state": new_storage,
                    "duration_sec": duration,
                    "fingerprint_hash": _fingerprint_hash,
                })
            except Exception as e:
                logger.warning(f"final session update failed: {e}")

        _RUNNING_SESSIONS.pop(session_id, None)
        return {"ok": True, "session_id": session_id, "duration_sec": duration}


def request_stop(session_id: str) -> bool:
    """Mark a running session as stop-requested. Polled by the launch
    loop above; the browser is then closed and storage_state saved.
    """
    sess = _RUNNING_SESSIONS.get(session_id)
    if not sess:
        return False
    sess["stop_requested"] = True
    return True


def list_running() -> Dict[str, Dict[str, Any]]:
    """Return the dict of currently-running sessions (for debug / UI)."""
    return dict(_RUNNING_SESSIONS)


# ── 2026-06-28 — User-session helper (called BY the tray app) ───────
# Lives in the tray app's process (which runs in the user's
# interactive Windows session) and drains the `browser_launch_queue`
# collection that the NSSM-service backend writes into.

async def process_pending_user_session_launches(
    motor_db: Any,
    cloud_session_update_url: str = "",
    license_key: str = "",
) -> int:
    """Pick up to ONE queued launch and run it inline. Returns the
    number of launches started (0 or 1). The tray app calls this in a
    loop with ~2s pause between calls — we deliberately process one
    at a time so a single misconfigured profile can't block the queue.

    Also drains stop_requested flags on already-claimed entries so a
    customer's "Stop" click on the cloud / desktop UI propagates from
    the backend service (Session 0) to the running browser owned by
    THIS process (Session 1).

    All status updates are written DIRECTLY into the local Mongo
    `browser_profile_sessions` and the parent `browser_profiles`
    collections — same shape the backend's normal flow writes. The
    cloud is also notified via `cloud_session_update_url` when the
    profile was launched from the cloud UI (krexion.com), so the
    customer's cloud view stays in sync.
    """
    # 0. Expire launches the tray never claimed (stuck "queued" cards).
    try:
        n_expired = await expire_stale_user_session_launches(motor_db)
        if n_expired:
            logger.info(f"[user-session] expired {n_expired} stale queued launch(es)")
    except Exception as _exp_err:  # noqa: BLE001
        logger.debug(f"[user-session] expire stale skipped: {_exp_err}")

    # 1. Cancel queued launches that were stopped before the tray picked them up.
    try:
        async for _cancel_doc in motor_db[_LAUNCH_QUEUE_COLLECTION].find({
            "status": "queued",
            "stop_requested": True,
        }):
            try:
                _cancel_sid = str(_cancel_doc.get("id") or "")
                _cancel_pid = str((_cancel_doc.get("profile_config") or {}).get("id") or _cancel_doc.get("profile_id") or "")
                await motor_db[_LAUNCH_QUEUE_COLLECTION].update_one(
                    {"id": _cancel_doc.get("id")},
                    {"$set": {"status": "cancelled", "completed_at": _now_iso()}},
                )
                await motor_db.browser_profile_sessions.update_one(
                    {"id": _cancel_sid},
                    {"$set": {"status": "stopped", "ended_at": _now_iso()}},
                )
                await motor_db.browser_profiles.update_one(
                    {"id": _cancel_pid},
                    {"$set": {"status": "idle", "session_id": ""}},
                )
                logger.info(f"[user-session] cancelled queued launch session_id={_cancel_sid[:8]}")
            except Exception as _cancel_err:  # noqa: BLE001
                logger.debug(f"[user-session] queued cancel failed: {_cancel_err}")
    except Exception as _cancel_drain_err:  # noqa: BLE001
        logger.debug(f"[user-session] queued cancel drain failed: {_cancel_drain_err}")

    # 2. Honour stop requests on already-claimed launches first. The
    #    backend writes `stop_requested=true` into the queue record;
    #    we forward it to the in-process `request_stop()` so the
    #    polling loop inside `_launch_session_inline` closes Chromium.
    try:
        async for stop_doc in motor_db[_LAUNCH_QUEUE_COLLECTION].find({
            "stop_requested": True,
            "status": "claimed",
            "stop_acknowledged": {"$ne": True},
        }):
            try:
                request_stop(str(stop_doc.get("id") or ""))
                await motor_db[_LAUNCH_QUEUE_COLLECTION].update_one(
                    {"id": stop_doc.get("id")},
                    {"$set": {"stop_acknowledged": True,
                              "stop_acknowledged_at": _now_iso()}},
                )
                logger.info(
                    f"[user-session] stop forwarded session_id={str(stop_doc.get('id') or '')[:8]}"
                )
            except Exception as _stop_err:  # noqa: BLE001
                logger.debug(f"[user-session] stop forward failed: {_stop_err}")
    except Exception as _drain_err:  # noqa: BLE001
        logger.debug(f"[user-session] stop drain query failed: {_drain_err}")

    # 3. Atomically claim one queued launch (skip stop-requested rows)
    try:
        doc = await motor_db[_LAUNCH_QUEUE_COLLECTION].find_one_and_update(
            {"status": "queued", "stop_requested": {"$ne": True}},
            {"$set": {"status": "claimed", "claimed_at": _now_iso()}},
            sort=[("queued_at", 1)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[user-session] queue poll failed: {exc}")
        return 0
    if not doc:
        return 0

    session_id = str(doc.get("id") or "")
    profile_config = doc.get("profile_config") or {}
    profile_id = str(profile_config.get("id") or doc.get("profile_id") or "")
    start_url = str(doc.get("start_url") or "https://www.google.com/")
    logger.info(
        f"[user-session] claimed launch session_id={session_id[:8]} "
        f"profile={profile_id[:8]}"
    )

    async def _on_update(body: Dict[str, Any]) -> None:
        """Mirror status into the local Mongo collections that the
        normal flow writes, AND optionally push to the cloud."""
        try:
            sid = str(body.get("session_id") or session_id)
            status = str(body.get("status") or "")
            now = _now_iso()
            if status:
                await motor_db.browser_profile_sessions.update_one(
                    {"id": sid},
                    {"$set": {
                        "status": status,
                        "fingerprint_hash": body.get("fingerprint_hash", ""),
                        "error_message": body.get("error_message", "")[:500],
                        "updated_at": now,
                    }},
                )
                if status == "running":
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {"status": "running", "session_id": sid}},
                    )
                elif status == "queued":
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {"status": "launching", "session_id": sid}},
                    )
                elif status == "stopping":
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {"status": "stopping", "session_id": sid}},
                    )
                elif status in ("stopped", "closed", "error"):
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {
                            "status": "idle" if status in ("stopped", "closed") else "error",
                            "session_id": "",
                        }},
                    )
                if body.get("storage_state") and isinstance(body["storage_state"], dict):
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {"storage_state": body["storage_state"]}},
                    )
                if body.get("fingerprint_hash"):
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": {"fingerprint_hash": str(body["fingerprint_hash"])[:128]}},
                    )
        except Exception as _local_err:  # noqa: BLE001
            logger.debug(f"[user-session] local mirror failed: {_local_err}")

        # Optional: forward to cloud session-update endpoint
        if cloud_session_update_url:
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=15) as client:
                    headers = {"Content-Type": "application/json"}
                    if license_key:
                        headers["X-Krexion-License"] = license_key
                    await client.post(
                        cloud_session_update_url, json=body, headers=headers,
                    )
            except Exception as _cloud_err:  # noqa: BLE001
                logger.debug(f"[user-session] cloud push failed: {_cloud_err}")

    # Run the actual inline launch in THIS user-session process.
    # The launch blocks until the customer closes the browser, so we
    # fire it as a background task and return — the queue polling
    # loop can then start the next claim immediately if needed.
    async def _run_and_finalize() -> None:
        try:
            await _launch_session_inline(
                profile_config,
                session_id=session_id,
                start_url=start_url,
                on_session_update=_on_update,
            )
            await motor_db[_LAUNCH_QUEUE_COLLECTION].update_one(
                {"id": session_id},
                {"$set": {"status": "completed",
                          "completed_at": _now_iso()}},
            )
        except Exception as exc:  # noqa: BLE001
            err_msg = f"{type(exc).__name__}: {str(exc)[:240]}"
            logger.warning(
                f"[user-session] launch crashed session_id={session_id[:8]}: {err_msg}"
            )
            try:
                await motor_db[_LAUNCH_QUEUE_COLLECTION].update_one(
                    {"id": session_id},
                    {"$set": {"status": "error",
                              "error_message": err_msg,
                              "completed_at": _now_iso()}},
                )
            except Exception:  # noqa: BLE001
                pass
            await _on_update({
                "session_id": session_id,
                "profile_id": profile_id,
                "status": "error",
                "error_message": err_msg,
            })

    asyncio.create_task(_run_and_finalize())
    return 1


__all__ = [
    "launch_profile_session",
    "request_stop",
    "list_running",
    "process_pending_user_session_launches",
    "expire_stale_user_session_launches",
    "_build_profile_stealth_fp",
    "_PROFILE_HEADED_LAUNCH_ARGS",
]
