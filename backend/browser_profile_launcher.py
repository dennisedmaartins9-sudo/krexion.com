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
import socket
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger("browser_profile_launcher")

# Track running sessions so the UI / stop endpoint can find them
_RUNNING_SESSIONS: Dict[str, Dict[str, Any]] = {}

# v2.7.78 — Ignore transient missing windows/shell during profile startup.
_PROFILE_UI_WATCH_GRACE_SEC = 45.0


def _proxy_dns_failure(server: str) -> Optional[str]:
    """Return a clear error if proxy hostname cannot be resolved (ENOTFOUND).

    BestGo / stale gateways often store hosts that no longer resolve on the
    customer's PC — Playwright then fails every request with getaddrinfo
    ENOTFOUND and iOS/Android profiles look 'broken'. Soft-disable instead.
    """
    raw = (server or "").strip()
    if not raw:
        return None
    try:
        from urllib.parse import urlparse

        host = urlparse(raw if "://" in raw else f"http://{raw}").hostname or ""
    except Exception:
        host = ""
    host = (host or "").strip().strip("[]")
    if not host:
        return "Proxy server URL has no hostname"
    # Literal IPs always "resolve".
    try:
        socket.inet_pton(socket.AF_INET, host)
        return None
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return None
    except OSError:
        pass
    try:
        socket.getaddrinfo(host, None)
        return None
    except socket.gaierror as exc:
        return f"getaddrinfo ENOTFOUND {host} ({exc})"
    except OSError as exc:
        return f"DNS lookup failed for {host} ({exc})"


def _is_dns_proxy_error(err: str) -> bool:
    low = (err or "").lower()
    return (
        "enotfound" in low
        or "getaddrinfo" in low
        or "name or service not known" in low
        or "nodename nor servname" in low
        or "11001" in low  # WSAHOST_NOT_FOUND
    )


def _profile_user_closed_ui(
    session_id: str,
    context: Any,
    browser: Any,
    tracked_pages: set,
) -> bool:
    """Detect user closed the profile browser (X). Minimize keeps session alive."""
    sess = _RUNNING_SESSIONS.get(session_id) or {}
    watch_started = float(sess.get("ui_watch_started_mono") or 0.0)
    in_grace = watch_started > 0 and (time.monotonic() - watch_started) < _PROFILE_UI_WATCH_GRACE_SEC

    try:
        if browser is not None and hasattr(browser, "is_connected"):
            if not browser.is_connected():
                return True
    except Exception:
        pass

    try:
        live_ctx = [
            p for p in (getattr(context, "pages", None) or []) if not p.is_closed()
        ]
        live_tracked = {p for p in tracked_pages if not p.is_closed()}
        if not live_ctx and not live_tracked:
            # During startup Playwright may briefly have zero pages while WebKit/shell attach.
            if in_grace:
                return False
            return True
    except Exception:
        pass

    if not sys.platform.startswith("win"):
        return False

    if in_grace:
        return False

    driver_pid = sess.get("driver_pid")
    try:
        from krexion_window_icon import is_process_alive, profile_engine_window_exists

        if driver_pid and not is_process_alive(int(driver_pid)):
            return True
    except Exception:
        pass

    if sess.get("mobile_shell"):
        try:
            from krexion_mobile_browser_shell import is_mobile_shell_alive

            if not is_mobile_shell_alive(session_id):
                # v2.7.125 — If shell is dead and engine was hidden from the
                # taskbar (TOOLWINDOW polish fallback), do NOT keep a ghost
                # "running" card. Operator already lost the window.
                if driver_pid:
                    try:
                        from krexion_window_icon import (
                            profile_engine_window_exists,
                            profile_engine_visible_on_taskbar,
                        )

                        if profile_engine_window_exists(
                            int(driver_pid), webkit=bool(sess.get("webkit"))
                        ):
                            # Visible taskbar button → keep; hidden TOOLWINDOW → closed
                            if profile_engine_visible_on_taskbar(
                                int(driver_pid), webkit=bool(sess.get("webkit"))
                            ):
                                sess["mobile_shell"] = False
                                _RUNNING_SESSIONS[session_id] = sess
                                return False
                            return True
                    except Exception:
                        pass
                if in_grace:
                    return False
                return True
        except Exception:
            pass
    else:
        try:
            from krexion_window_icon import profile_engine_window_exists

            if driver_pid and not profile_engine_window_exists(
                int(driver_pid), webkit=bool(sess.get("webkit"))
            ):
                return True
        except Exception:
            pass

    return False




def _start_title_keeper_for_session(session_id: str, hwnds: list) -> None:
    """Best-effort AdsPower-style durable window title."""
    try:
        sess = (_RUNNING_SESSIONS.get(session_id) or {})
        title = str(sess.get("window_title") or "")
        if not title or not hwnds:
            return
        from krexion_window_icon import keep_krexion_window_title
        keep_krexion_window_title(hwnds, title, session_key=f"title:{session_id}")
    except Exception:
        pass

async def _apply_shell_commands(
    session_id: str,
    context: Any,
    page: Any,
    home_url: str,
) -> None:
    """Drain mobile-shell IPC commands and drive Playwright pages."""
    try:
        from krexion_mobile_browser_shell import get_shell_cfg_path, adjust_shell_frame_scale, get_shell_frame_scale
        from krexion_mobile_shell_interactive import drain_shell_commands, write_shell_state
    except Exception:
        return
    cfg_path = get_shell_cfg_path(session_id)
    if not cfg_path:
        return
    cmds = drain_shell_commands(cfg_path)
    sess = _RUNNING_SESSIONS.get(session_id) or {}
    tabs_meta: List[Dict[str, str]] = list(sess.get("shell_tabs") or [])
    active_idx = int(sess.get("shell_active_tab") or 0)
    pages = [p for p in (getattr(context, "pages", None) or []) if not p.is_closed()]
    if not pages and page and not page.is_closed():
        pages = [page]

    async def _sync_state() -> None:
        live = [p for p in (getattr(context, "pages", None) or []) if not p.is_closed()]
        tab_list = []
        for i, pg in enumerate(live):
            title = tabs_meta[i]["title"] if i < len(tabs_meta) else f"Tab {i + 1}"
            url = tabs_meta[i]["url"] if i < len(tabs_meta) else ""
            try:
                url = pg.url or url
                title = (await pg.title()) or title
            except Exception:
                pass
            tab_list.append({"title": str(title)[:60], "url": str(url)[:200]})
        cur_url = ""
        if live and 0 <= active_idx < len(live):
            try:
                cur_url = live[active_idx].url or ""
            except Exception:
                pass
        write_shell_state(cfg_path, {
            "url": str(cur_url).replace("https://", "").replace("http://", "")[:56],
            "tabs": tab_list,
            "active_tab": active_idx,
            "tab_count": len(live),
            "zoom_pct": int(round(get_shell_frame_scale(session_id) * 100)),
        })
        sess["shell_tabs"] = tab_list
        sess["shell_active_tab"] = active_idx
        _RUNNING_SESSIONS[session_id] = sess

    for cmd in cmds:
        name = str(cmd.get("cmd") or "")
        try:
            if name == "go_back":
                tgt = pages[active_idx] if pages and active_idx < len(pages) else page
                if tgt:
                    await tgt.go_back()
            elif name == "go_forward":
                tgt = pages[active_idx] if pages and active_idx < len(pages) else page
                if tgt:
                    await tgt.go_forward()
            elif name == "reload":
                tgt = pages[active_idx] if pages and active_idx < len(pages) else page
                if tgt:
                    await tgt.reload()
            elif name == "go_home":
                url = str(cmd.get("url") or home_url or "https://www.google.com/")
                tgt = pages[active_idx] if pages and active_idx < len(pages) else page
                if tgt:
                    await tgt.goto(url, wait_until="domcontentloaded", timeout=60000)
            elif name == "new_tab":
                url = str(cmd.get("url") or home_url or "https://www.google.com/")
                await context.new_page()
                live = [p for p in context.pages if not p.is_closed()]
                active_idx = len(live) - 1
                if live:
                    await live[-1].goto(url, wait_until="domcontentloaded", timeout=60000)
            elif name == "switch_tab":
                idx = max(0, int(cmd.get("index") or 0))
                live = [p for p in context.pages if not p.is_closed()]
                if live and idx < len(live):
                    active_idx = idx
                    try:
                        await live[idx].bring_to_front()
                    except Exception:
                        pass
            elif name in ("fit_screen", "actual_size", "zoom_in", "zoom_out"):
                mode = {
                    "fit_screen": "fit",
                    "actual_size": "actual",
                    "zoom_in": "in",
                    "zoom_out": "out",
                }.get(name, name)
                adjust_shell_frame_scale(session_id, mode)
        except Exception as _sc_err:
            logger.debug(f"[mobile-shell] cmd {name} skipped: {_sc_err}")
        pages = [p for p in (getattr(context, "pages", None) or []) if not p.is_closed()]
    sess["shell_active_tab"] = active_idx
    _RUNNING_SESSIONS[session_id] = sess
    await _sync_state()

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
_USER_SESSION_PICKUP_TIMEOUT_SEC = 120.0

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


def _headed_launch_args(anti: Optional[Dict[str, Any]] = None) -> List[str]:
    """Build headed Chromium args; allow extensions when configured."""
    args = list(_PROFILE_HEADED_LAUNCH_ARGS)
    anti = anti or {}
    allow_ext = bool(anti.get("allow_extensions"))
    ext_path = str(anti.get("extensions_dir") or os.environ.get("KREXION_PROFILE_EXTENSIONS") or "").strip()
    if allow_ext or ext_path:
        args = [a for a in args if a != "--disable-extensions"]
        if ext_path and os.path.isdir(ext_path):
            args.append(f"--load-extension={ext_path}")
    # Prefer IPv4 when proxy is used — dual-stack leaks are a common fail
    if anti.get("disable_ipv6", True) is not False:
        if "--disable-ipv6" not in args:
            args.append("--disable-ipv6")
    return args


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
                "message": "Waiting for Krexion tray (user session) to open Krexion Browser…",
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
            "Open the Krexion icon in the Windows system tray (or restart Krexion Local "
            "PC Dashboard), wait for Backend Online, then click Launch again."
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
    # Wire profile.language → Accept-Language / navigator.languages when set
    lang = str(profile_config.get("language") or "").strip()
    accept = str(profile_config.get("accept_language") or "").strip()
    if lang and not accept:
        base = lang.split("-", 1)[0]
        accept = f"{lang},{base};q=0.9" if "-" in lang else f"{lang},en;q=0.8"
    elif lang and accept and lang.split(",")[0].strip() not in accept:
        # Prefer explicit language as primary tag
        accept = f"{lang},{accept}"
    locale = str(profile_config.get("locale") or "").strip() or loc
    if lang and not profile_config.get("locale"):
        locale = lang if "-" in lang else locale
    return {
        "locale": locale,
        "timezone": profile_config.get("timezone") or tz,
        "accept_language": accept or al,
        "lat": lat,
        "lon": lon,
        "language": lang,
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
    fingerprint_salt: str = "",
) -> Dict[str, Any]:
    """Full RUT fingerprint for Profiles — keep profile viewport/mobile flags.

    Uses `_sync_fingerprint_to_ua` so platform/vendor/HC/WebGL/fonts match
    the UA, then overlays profile-owned viewport + deterministic seeds so
    the same profile always looks like the same device across launches.
    Optional fingerprint_salt (from refresh API) rotates canvas/HC seeds
    without changing profile_id.
    """
    from anti_detect_v230 import _stable_hash as _stable_hash_fn
    from real_user_traffic import _sync_fingerprint_to_ua

    _salt = str(fingerprint_salt or "").strip()
    identity = f"{profile_id}:{_salt}" if _salt else str(profile_id or "profile")
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
    # v2.7.13 — allow locked profile timezone/locale when geo_follow_proxy=False
    if profile_config.get("geo_follow_proxy") is False:
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


def _coerce_profile_ua(
    ua: str,
    profile_config: Dict[str, Any],
    *,
    referrer_state: Optional[_ProfileReferrerState] = None,
    locale: str = "",
) -> str:
    """RUT-grade UA ↔ platform parity for browser profiles (Everflow browser field)."""
    referrer = profile_config.get("referrer") or {}
    if not referrer.get("enabled"):
        return ua
    if referrer.get("match_ua_to_platform") is False:
        return ua
    platform = ""
    if referrer_state and referrer_state.enabled:
        platform = (
            str(getattr(referrer_state, "ua_platform", "") or "").strip().lower()
            or str(referrer_state.platform or "").strip().lower()
        )
        if not platform and referrer_state.referer_url:
            try:
                from real_user_traffic import _platform_from_referer_url
                platform = (_platform_from_referer_url(referrer_state.referer_url) or "").strip().lower()
            except Exception:
                platform = ""
    if not platform:
        try:
            state = _resolve_profile_referrer_state(ua, profile_config, "")
            platform = state.platform or ""
        except Exception:
            platform = ""
    if not platform:
        try:
            from referrer_pro import dominant_platform_from_weights
            platform = dominant_platform_from_weights(referrer.get("platform_weights"))
        except Exception:
            platform = ""
    if not platform:
        return ua

    try:
        from referrer_pro import (
            APP_SUPPORT_MATRIX,
            _PLATFORM_TO_APP,
            _is_mobile_ua,
            coerce_ua_for_platform,
            ensure_inapp_platform_ua,
        )
        from real_user_traffic import _mobile_ua_for_inapp
    except Exception:
        return ua

    _MOBILE_ONLY_PLATFORMS = {
        "tiktok", "instagram", "snapchat", "facebook", "pinterest",
        "linkedin", "twitter", "reddit", "whatsapp", "telegram",
        "google", "gsearch", "youtube",
    }
    current = ua or ""
    if platform in _MOBILE_ONLY_PLATFORMS and not _is_mobile_ua(current):
        try:
            _new_mob = _mobile_ua_for_inapp()
            if _new_mob:
                current = _new_mob
                logger.info(
                    f"[profile-launch] desktop UA replaced with mobile for {platform}"
                )
        except Exception:
            pass

    _app_key = _PLATFORM_TO_APP.get(platform.lower())
    _family = _is_mobile_ua(current) or ""
    _needs_strict = bool(
        _app_key
        and _family in {"android", "ios"}
        and APP_SUPPORT_MATRIX.get(_app_key, {}).get(_family) == "supported"
    )
    if _needs_strict:
        coerced = ensure_inapp_platform_ua(
            current,
            platform,
            locale,
            mobile_ua_factory=_mobile_ua_for_inapp,
            attempts=4,
        )
    else:
        coerced = coerce_ua_for_platform(current, platform, locale)

    if coerced:
        logger.info(
            f"[profile-launch] UA coerced platform={platform} strict_inapp={_needs_strict}"
        )
        return coerced
    logger.warning(
        f"[profile-launch] UA coercion failed for platform={platform}; keeping base UA"
    )
    return current


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


@dataclass
class _ProfileReferrerState:
    """Sticky session referer resolved once from profile config."""
    enabled: bool = False
    referer_url: str = ""
    sec_fetch: Dict[str, str] = field(default_factory=dict)
    accept_language: str = ""
    wrapper_redirect: bool = False
    wrapper_template: str = ""
    platform: str = ""
    pro_extras: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    pass_to_offer: bool = True
    allow_risky_wrapper: bool = False
    brand: str = ""
    traffic_type: str = "auto"
    campaign_type: str = "auto"
    user_agent: str = ""
    click_id: str = ""
    ua_platform: str = ""


def _profile_referrer_effective(referrer: Dict[str, Any]) -> Dict[str, Any]:
    """Merge quality-tier defaults with explicit profile referrer fields."""
    out = dict(referrer or {})
    if not out.get("enabled"):
        return out
    try:
        from referrer_pro import quality_tier_defaults
        tier = str(out.get("quality_tier") or "standard").lower().strip()
        td = quality_tier_defaults(tier)
        _map = {
            "lang_match": "referrer_pro_lang_match",
            "social_wrapper": "referrer_pro_social_wrapper",
            "inapp_deep_path": "referrer_pro_inapp_deep_path",
            "strip_search_path": "referrer_pro_strip_search_path",
            "wrapper_redirect": "referrer_pro_wrapper_redirect",
            "tod_enabled": "referrer_pro_tod_enabled",
            "device_mode": "referrer_pro_device_mode",
        }
        for local_key, tier_key in _map.items():
            if local_key not in out or out.get(local_key) is None:
                if tier_key in td:
                    out[local_key] = td[tier_key]
    except Exception:
        pass
    return out


def _profile_referrer_resolve_cfg(
    referrer: Dict[str, Any],
    profile_config: Dict[str, Any],
    target_url: str,
    *,
    ua: str = "",
) -> Dict[str, Any]:
    """Build `_resolve_visit_referer` cfg dict from profile referrer block."""
    ref = _profile_referrer_effective(referrer)
    pw = ref.get("platform_weights") or {}
    ew = ref.get("email_weights") or {}
    mode = str(ref.get("mode") or "auto").strip().lower()
    if ref.get("pro_mode") and isinstance(pw, dict) and pw:
        mode = mode if mode not in ("", "auto", "platform_pool") else "auto"
    elif mode in ("", "auto") and isinstance(pw, dict) and pw:
        mode = "platform_pool"
    _vlow = (ua or "").lower()
    _visitor_mobile = "mobi" in _vlow or "iphone" in _vlow or "android" in _vlow
    country = (
        str(ref.get("country") or "").strip().lower()
        or str(profile_config.get("country") or "us").strip().lower()
    )
    cfg: Dict[str, Any] = {
        "enabled": True,
        "pro_mode": bool(ref.get("pro_mode", True)),
        "mode": mode,
        "value": str(ref.get("value") or ""),
        "preset_platform": str(ref.get("preset_platform") or ""),
        "platform_weights": json.dumps(pw) if isinstance(pw, dict) else str(pw or ""),
        "platform_pool": str(ref.get("platform_pool") or ""),
        "email_weights": json.dumps(ew) if isinstance(ew, dict) else str(ew or ""),
        "brand": str(ref.get("brand") or ""),
        "target_url": target_url or "",
        "country": country,
        "search_engine": str(ref.get("search_engine") or "google"),
        "search_keywords": str(ref.get("search_keywords") or ""),
        "social_wrapper": bool(ref.get("social_wrapper", True)),
        "inapp_deep_path": bool(ref.get("inapp_deep_path", True)),
        "strip_search_path": bool(ref.get("strip_search_path", True)),
        "network_click_chain": bool(ref.get("network_click_chain", False)),
        "traffic_type": str(ref.get("traffic_type") or "auto"),
        "campaign_type": str(ref.get("campaign_type") or "auto"),
        "lang_match": bool(ref.get("lang_match", True)),
        "device_mode": str(ref.get("device_mode") or "auto"),
        "tod_enabled": bool(ref.get("tod_enabled", False)),
        "visitor_is_mobile": _visitor_mobile,
        "require_non_empty_referer": True,
        # pass_to_offer uses direct platform Referer inject — not wrapper URL as referer.
        "wrapper_redirect": bool(ref.get("wrapper_redirect", False))
        and ref.get("pass_to_offer", True) is False,
    }
    if mode == "google_search" and not cfg["search_keywords"]:
        cfg["search_keywords"] = str(ref.get("value") or "")
    return cfg


def _resolve_profile_referrer_state(
    ua: str,
    profile_config: Dict[str, Any],
    target_url: str = "",
) -> _ProfileReferrerState:
    """Resolve sticky session referer from profile config (RUT-grade)."""
    referrer = profile_config.get("referrer") or {}
    if not referrer.get("enabled"):
        return _ProfileReferrerState(enabled=False)
    try:
        from real_user_traffic import _resolve_visit_referer
        cfg = _profile_referrer_resolve_cfg(referrer, profile_config, target_url, ua=ua)
        ref_url, plat, _esp, extras = _resolve_visit_referer(ua, cfg)
        accept_lang = ""
        try:
            if bool(referrer.get("lang_match", True)):
                from referrer_pro import accept_language_for_country
                accept_lang = accept_language_for_country(cfg.get("country"))
        except Exception:
            pass
        if not accept_lang:
            try:
                from referrer_pro import accept_language_for_country
                accept_lang = accept_language_for_country(cfg.get("country"))
            except Exception:
                pass
        ref_eff = _profile_referrer_effective(referrer)
        wrapper_redirect = bool(ref_eff.get("wrapper_redirect", False))
        wrapper_template = ref_url if wrapper_redirect and ref_url else ""
        sec_fetch: Dict[str, str] = {}
        sf = (extras or {}).get("sec_fetch") or {}
        if isinstance(sf, dict):
            sec_fetch = {str(k): str(v) for k, v in sf.items()}
        import uuid as _uuid_mod
        _click_id = str(_uuid_mod.uuid4()).replace("-", "")[:24]
        _extras = dict(extras or {})
        _extras.setdefault("click_id", _click_id)
        if str(referrer.get("custom_click_id") or "").strip():
            _extras["custom_click_id"] = str(referrer.get("custom_click_id") or "").strip()
        try:
            from referrer_pro import resolve_profile_custom_utms as _prof_utms
            _extras = _prof_utms(
                referrer,
                _extras,
                {
                    "click_id": _click_id,
                    "clickid": _click_id,
                    "platform": plat or "",
                    "source": plat or "",
                    "brand": str(referrer.get("brand") or ""),
                    "campaign": str(_extras.get("utm_campaign") or ""),
                },
            )
        except Exception:
            pass
        try:
            from referrer_pro import normalize_referer_url as _norm_ref_url
            ref_url = _norm_ref_url(ref_url or "")
            if not ref_url and str(referrer.get("value") or "").strip():
                ref_url = _norm_ref_url(str(referrer.get("value")))
        except Exception:
            pass
        if not ref_url and referrer.get("enabled"):
            try:
                from referrer_pro import (
                    build_inapp_deep_referer as _deep_ref,
                    dominant_platform_from_weights as _dom_pw,
                    detect_is_paid as _dip,
                )
                from real_user_traffic import _INAPP_PRESET_REFERER

                _dom = _dom_pw(referrer.get("platform_weights"))
                if _dom:
                    plat = plat or _dom
                    _paid = _dip(
                        str(referrer.get("traffic_type") or "auto"),
                        str(referrer.get("campaign_type") or "auto"),
                        _dom,
                    )
                    ref_url = _deep_ref(_dom, target_url or "", is_paid=_paid) or ""
                    if not ref_url:
                        ref_url = str(_INAPP_PRESET_REFERER.get(_dom) or "")
            except Exception:
                pass
        if not plat and ref_url:
            try:
                from real_user_traffic import _platform_from_referer_url
                plat = (_platform_from_referer_url(ref_url) or plat or "").strip().lower()
            except Exception:
                pass
        return _ProfileReferrerState(
            enabled=True,
            referer_url=ref_url or "",
            sec_fetch=sec_fetch,
            accept_language=accept_lang,
            wrapper_redirect=wrapper_redirect,
            wrapper_template=wrapper_template,
            platform=plat or "",
            pro_extras=_extras,
            pass_to_offer=referrer.get("pass_to_offer", True) is not False,
            allow_risky_wrapper=bool(referrer.get("allow_risky_wrapper", False)),
            brand=str(referrer.get("brand") or ""),
            traffic_type=str(referrer.get("traffic_type") or "auto"),
            campaign_type=str(referrer.get("campaign_type") or "auto"),
            click_id=_click_id,
        )
    except Exception as _ref_err:
        logger.debug(f"profile referer state resolve skipped: {_ref_err}")
        return _ProfileReferrerState(enabled=False)


def _is_wrapper_domain(url: str) -> bool:
    low = (url or "").lower()
    return any(
        s in low
        for s in (
            "l.facebook.com/l.php",
            "lm.facebook.com/l.php",
            "m.facebook.com/flx",
            "google.com/url",
            "t.co/",
            "lnkd.in/",
            "l.instagram.com",
            "tiktok.com/link/v2",
        )
    )


def _should_profile_wrapper_bounce(url: str, state: _ProfileReferrerState, ua: str) -> bool:
    # RUT pass_to_offer: direct platform Referer inject — no HTTP wrapper hop.
    if state.pass_to_offer:
        return False
    if not state.wrapper_redirect or not state.wrapper_template:
        return False
    if not url or not url.startswith(("http://", "https://")):
        return False
    if _is_wrapper_domain(url):
        return False
    try:
        from referrer_pro import should_link_wrapper_bounce
        return should_link_wrapper_bounce(
            ua,
            state.platform,
            state.wrapper_template,
            wrapper_redirect_enabled=True,
            allow_risky_wrapper=state.allow_risky_wrapper,
        )
    except Exception:
        if "tiktok.com/link/v2" in (state.wrapper_template or "").lower():
            return False
    return True


def _profile_enrich_platform(state: _ProfileReferrerState) -> str:
    """Resolve platform for URL enrichment — never return empty when referer implies one."""
    plat = (state.platform or "").strip().lower()
    if plat:
        return plat
    ref = (state.referer_url or "").strip()
    if ref:
        try:
            from real_user_traffic import _platform_from_referer_url
            plat = (_platform_from_referer_url(ref) or "").strip().lower()
            if plat:
                return plat
        except Exception:
            pass
    pe = state.pro_extras or {}
    plat = str(pe.get("platform") or "").strip().lower()
    return plat


def _is_neutral_profile_home(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").strip("/")
        neutral_homes = {
            "www.google.com", "google.com", "www.bing.com", "bing.com",
            "duckduckgo.com", "www.duckduckgo.com", "search.yahoo.com",
            "www.facebook.com", "facebook.com", "m.facebook.com",
            "www.instagram.com", "instagram.com", "www.tiktok.com", "tiktok.com",
            "www.youtube.com", "youtube.com", "m.youtube.com",
        }
        return host in neutral_homes and (not path or path in ("", "search", "home", "watch", "shorts"))
    except Exception:
        return False


def _is_affiliate_tracker_url(url: str) -> bool:
    low = (url or "").lower()
    return any(
        tok in low
        for tok in (
            "aff_c", "aff_click", "offer_id", "click_id", "clickid",
            "everflow", "evyy.net", "go2cloud", "voluum", "binom",
            "trk.", "track.", "redirect", "affiliate", "aff_",
            "hasoffers", "cake.", "affise", "redtrack", "subid",
            "utm_source", "utm_medium", "fbclid", "gclid", "ttclid",
        )
    )


def _should_enrich_profile_offer_url(url: str, *, referrer_enabled: bool = False) -> bool:
    """Skip neutral homepages — enrich offer/tracker navigations."""
    if not url or not str(url).startswith(("http://", "https://")):
        return False
    if _is_neutral_profile_home(url):
        return False
    if referrer_enabled:
        return True
    try:
        from referrer_pro import is_krexion_short_link_url

        if is_krexion_short_link_url(url):
            return True
        if _is_affiliate_tracker_url(url):
            return True
    except Exception:
        pass
    return not _is_neutral_profile_home(url)


def _ensure_sticky_profile_params(state: _ProfileReferrerState) -> Dict[str, str]:
    """Build once per session — same clickid/utm on every enriched navigation."""
    pe = dict(state.pro_extras or {})
    sticky = pe.get("_sticky_url_params")
    if isinstance(sticky, dict) and sticky:
        return {str(k): str(v) for k, v in sticky.items() if v is not None}

    plat = _profile_enrich_platform(state)
    if plat and not state.platform:
        state.platform = plat
    try:
        from referrer_pro import build_profile_platform_params
        params = build_profile_platform_params(
            plat or "generic",
            brand=state.brand,
            traffic_type=state.traffic_type,
            campaign_type=state.campaign_type,
            session_id=state.session_id,
            pro_extras=pe,
        )
    except Exception as exc:
        logger.warning(f"[profile-launch] sticky params build failed: {exc}")
        params = {}
    if params:
        pe["_sticky_url_params"] = params
        state.pro_extras = pe
    return params


def _profile_enrich_nav_url(url: str, state: _ProfileReferrerState) -> str:
    """RUT parity — append platform params (fbclid/utm/clickid) on profile navigations."""
    if not state.enabled or not url or not str(url).startswith(("http://", "https://")):
        return url or ""
    if not _should_enrich_profile_offer_url(url, referrer_enabled=state.enabled):
        return url
    plat = _profile_enrich_platform(state)
    if plat and not state.platform:
        state.platform = plat
    sticky = _ensure_sticky_profile_params(state)
    try:
        from referrer_pro import enrich_profile_offer_url, is_krexion_short_link_url
        from real_user_traffic import _rut_append_kx_qs, _rut_build_kx_src_qs

        out = url
        if is_krexion_short_link_url(out) and plat:
            _kx = _rut_build_kx_src_qs(
                plat,
                brand=state.brand,
                traffic_type=str((state.pro_extras or {}).get("traffic_type") or state.traffic_type),
            )
            out = _rut_append_kx_qs(out, _kx)
        out = enrich_profile_offer_url(
            out,
            platform=plat or "generic",
            brand=state.brand,
            pro_extras=state.pro_extras,
            traffic_type=state.traffic_type,
            campaign_type=state.campaign_type,
            session_id=state.session_id,
            referer_url=state.referer_url,
            preset_params=sticky or None,
        )
        if out != url:
            logger.info(
                f"[profile-launch] enriched offer url platform={plat or 'generic'} "
                f"session={str(state.session_id or '')[:8]}"
            )
        return out or url
    except Exception as exc:
        logger.warning(f"[profile-launch] nav url enrich failed: {exc}")
        return url


async def _apply_cdp_user_agent_override(context: Any, ua: str, page: Any = None) -> None:
    """Network-layer UA override so trackers (Everflow) always receive the coerced string."""
    if not ua or not context:
        return
    try:
        _page = page
        if _page is None and getattr(context, "pages", None):
            _page = context.pages[0] if context.pages else None
        if _page is None:
            return
        cdp = await context.new_cdp_session(_page)
        await cdp.send("Network.enable", {})
        _plat = "Android" if "android" in ua.lower() else (
            "iOS" if ("iphone" in ua.lower() or "ipad" in ua.lower()) else ""
        )
        payload: Dict[str, Any] = {"userAgent": ua}
        if _plat:
            payload["platform"] = _plat
        await cdp.send("Network.setUserAgentOverride", payload)
        logger.info(f"[profile-launch] CDP User-Agent override ON ({len(ua)} chars)")
    except Exception as exc:
        logger.debug(f"[profile-launch] CDP UA override skipped: {exc}")


async def _install_profile_cdp_ua_all_pages(context: Any, ua_supplier: Any) -> None:
    """Re-apply CDP UA override on every new tab (multi-tab manual browsing)."""
    _done: set = set()

    async def _bind(page: Any) -> None:
        pid = id(page)
        if pid in _done:
            return
        _done.add(pid)
        ua = ""
        try:
            ua = str(ua_supplier() or "")
        except Exception:
            ua = ""
        if ua:
            await _apply_cdp_user_agent_override(context, ua, page=page)

    def _on_page(page: Any) -> None:
        asyncio.create_task(_bind(page))

    context.on("page", _on_page)
    for pg in list(getattr(context, "pages", []) or []):
        await _bind(pg)


def make_profile_referrer_route_handler(state: _ProfileReferrerState):
    """Combined Sec-CH-UA + sticky Referer injection for ALL tabs/navigations."""
    async def _handler(route, request):
        try:
            headers = dict(request.headers or {})
            ua = (
                state.user_agent
                or headers.get("user-agent")
                or headers.get("User-Agent")
                or ""
            )
            if ua:
                headers["user-agent"] = ua
                headers["User-Agent"] = ua
            headers = {
                key: value for key, value in headers.items()
                if not key.lower().startswith("sec-ch-ua")
            }
            try:
                from referrer_pro import client_hint_headers_for_ua
                _casing = {
                    "sec-ch-ua": "Sec-CH-UA",
                    "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
                    "sec-ch-ua-platform": "Sec-CH-UA-Platform",
                }
                headers.update({
                    _casing[key]: value
                    for key, value in client_hint_headers_for_ua(ua).items()
                })
            except Exception:
                pass

            if (
                state.enabled
                and request.resource_type == "document"
                and _should_profile_wrapper_bounce(request.url, state, ua)
            ):
                try:
                    from referrer_pro import rebuild_referer_with_target as _rrwt
                    wrapper = _rrwt(state.wrapper_template, request.url)
                    if wrapper and wrapper.rstrip("/") != request.url.rstrip("/"):
                        await route.fulfill(
                            status=302,
                            headers={
                                "Location": wrapper,
                                "Referrer-Policy": "unsafe-url",
                            },
                        )
                        return
                except Exception as _wrap_err:
                    logger.debug(f"profile wrapper bounce skipped: {_wrap_err}")

            if state.enabled and state.referer_url and request.resource_type == "document":
                headers.pop("referer", None)
                headers["Referer"] = state.referer_url
                if state.sec_fetch:
                    headers.update(state.sec_fetch)
            nav_url = request.url
            if state.enabled and request.resource_type == "document":
                nav_url = _profile_enrich_nav_url(nav_url, state)
            if (
                state.enabled
                and state.session_id
                and request.resource_type == "document"
            ):
                try:
                    from referrer_pro import (
                        KREXION_PROFILE_SESSION_HEADER,
                        is_krexion_short_link_url,
                    )
                    if is_krexion_short_link_url(request.url):
                        headers[KREXION_PROFILE_SESSION_HEADER.lower()] = state.session_id
                except Exception:
                    pass
            if nav_url != request.url:
                logger.info(
                    f"[profile-launch] route enrich {request.url[:80]} -> {nav_url[:120]}"
                )
                await route.continue_(url=nav_url, headers=headers)
                return
            await route.continue_(headers=headers)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass
    return _handler


async def _resolve_referer_for_goto(
    ua: str,
    profile_config: Dict[str, Any],
    target_url: str,
    *,
    referrer_state: Optional[_ProfileReferrerState] = None,
) -> tuple:
    """Return (referer_url, extra_headers) for the first navigation."""
    state = referrer_state or _resolve_profile_referrer_state(ua, profile_config, target_url)
    if not state.enabled:
        return "", {}
    extra_headers: Dict[str, str] = {}
    if state.accept_language:
        extra_headers["Accept-Language"] = state.accept_language
    if state.sec_fetch:
        extra_headers.update(state.sec_fetch)
    if state.referer_url:
        extra_headers["Referer"] = state.referer_url
    extra_headers["Referrer-Policy"] = "unsafe-url"
    return state.referer_url or "", extra_headers


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
                "Krexion Browser engine is not installed on this host. The Krexion "
                "desktop install should auto-bundle it; please reinstall "
                "or run `python -m playwright install chromium` manually."
            )
            return {"ok": False, "error": f"Playwright not installed: {_ie}"}

        # ── v2.7.37 Pre-flight: FULL Chromium for headed profile launch ───
        # Headed profiles need chromium-{rev}/chrome.exe — NOT headless-shell.
        # Relative \\pw-browsers paths on Windows caused permanent launch
        # failures; normalize + install synchronously before first launch.
        try:
            from real_user_traffic import (  # type: ignore
                get_headed_engine_status,
                _ensure_full_chromium_available,
                normalize_playwright_browsers_path,
                _full_chromium_binary_path,
            )
            normalize_playwright_browsers_path()
            engine = get_headed_engine_status()
            estatus = (engine or {}).get("status") or "error"
            if estatus == "ready":
                pass
            elif estatus == "installing":
                await _notify_error(
                    "Krexion Browser engine is still downloading "
                    "(~150 MB). Please wait ~60 seconds and click "
                    "Launch again."
                )
                return {"ok": False, "session_id": session_id,
                        "error": "chromium_installing"}
            elif estatus == "missing":
                ok = await _ensure_full_chromium_available()
                if not ok or _full_chromium_binary_path() is None:
                    await _notify_error(
                        "Krexion Browser engine is missing — downloading "
                        "it now (~150 MB, takes ~60-90 seconds). Click "
                        "Launch again once this banner clears."
                    )
                    return {"ok": False, "session_id": session_id,
                            "error": "chromium_missing_install_started"}
            else:
                logger.warning(
                    f"[profile-launch] headed chromium status='{estatus}' "
                    f"(msg={(engine or {}).get('message','')}); continuing anyway"
                )
        except ImportError:
            logger.debug("[profile-launch] headed engine helper not importable; skipping pre-check")
        except Exception as _ge:  # noqa: BLE001
            logger.debug(f"[profile-launch] headed chromium pre-check skipped: {_ge}")

        started_at = time.time()
        # Taskbar slot = open-profile number badge (1, 2, 3…) on Krexion icon.
        _used_slots = {
            int(s.get("taskbar_slot") or 0)
            for s in _RUNNING_SESSIONS.values()
            if isinstance(s, dict)
        }
        _taskbar_slot = next(
            (i for i in range(1, 100) if i not in _used_slots),
            max(1, len(_RUNNING_SESSIONS) + 1),
        )
        _RUNNING_SESSIONS[session_id] = {
            "profile_id": profile_id,
            "started_at": started_at,
            "stop_requested": False,
            "taskbar_slot": _taskbar_slot,
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
    # v2.7.74 — Real device CSS viewport from catalog (advertiser sees true res).
    try:
        from mobile_device_viewport import resolve_profile_device_viewport

        _dev_spec = resolve_profile_device_viewport(profile_config)
        if _dev_spec.get("from_catalog") or profile_config.get("device_catalog_id"):
            viewport = {
                "width": int(_dev_spec["width"]),
                "height": int(_dev_spec["height"]),
            }
            profile_config = dict(profile_config)
            profile_config["viewport"] = viewport
            if _dev_spec.get("device_scale_factor"):
                profile_config["device_scale_factor"] = float(_dev_spec["device_scale_factor"])
            logger.info(
                "[profile-launch] device viewport %s → %sx%s (physical ~%sx%s @%s)",
                _dev_spec.get("device_label") or _dev_spec.get("device_id") or "profile",
                viewport["width"],
                viewport["height"],
                _dev_spec.get("physical_width"),
                _dev_spec.get("physical_height"),
                _dev_spec.get("device_scale_factor"),
            )
    except Exception as _dvp_err:
        logger.debug(f"[profile-launch] device viewport resolve skipped: {_dvp_err}")
    is_mobile = bool(
        profile_config.get("is_mobile")
        or str(profile_config.get("device_type") or "").lower() == "mobile"
    )
    has_touch = bool(profile_config.get("has_touch") or is_mobile)
    dsf = float(profile_config.get("device_scale_factor") or (3.0 if is_mobile else 1.0))
    anti = profile_config.get("anti_detect") or {}
    master = bool(anti.get("master", True))
    identity_persist = bool(anti.get("identity_persist", True))
    tls_prewarm = bool(anti.get("tls_prewarm", True)) and master
    behavioral_bio = bool(anti.get("behavioral_bio", True)) and master
    ip_warmup = bool(anti.get("ip_warmup", False)) and master
    paranoia_mode = bool(anti.get("paranoia_mode", False))
    # v2.7.16 — Octo-class kernel (CloakBrowser C++ / Patchright / Firefox)
    try:
        from krexion_browser_kernel import resolve_launch_plan as _resolve_kernel_plan
        _kernel_plan = _resolve_kernel_plan(anti)
    except Exception as _kp_err:
        logger.debug(f"[profile-launch] kernel plan fallback: {_kp_err}")
        _kernel_plan = {
            "engine": "chromium",
            "driver": "playwright",
            "executable_path": "",
            "stealth_args": [],
            "kernel_label": "playwright-chromium",
            "reduce_js_fingerprint_noise": False,
            "preference": "auto",
        }
    # When C++ kernel already patches canvas/WebGL, prefer JS modes → real
    # (CreepJS quiet path). fingerprint_win_prefer_real also coerces leftover
    # "noise" defaults so Stealth kernel + pack don't fight each other.
    _prefer_real = bool(anti.get("fingerprint_win_prefer_real", True))
    if _kernel_plan.get("reduce_js_fingerprint_noise"):
        for _mk in ("canvas_mode", "webgl_mode", "audio_mode", "font_mode"):
            _cur = str(anti.get(_mk) or "").lower().strip()
            if not _cur or (_prefer_real and _cur == "noise"):
                anti[_mk] = "real"
    canvas_mode = str(anti.get("canvas_mode") or "noise").lower().strip()
    webgl_mode = str(anti.get("webgl_mode") or "noise").lower().strip()
    audio_mode = str(anti.get("audio_mode") or "noise").lower().strip()
    font_mode = str(anti.get("font_mode") or "noise").lower().strip()
    webrtc_mode = str(anti.get("webrtc_mode") or "proxy").lower().strip()
    proxy_check_on_launch = bool(anti.get("proxy_check_on_launch", True))
    # Default True when proxy is enabled — old profiles without the flag
    # used to soft-open on real IP; that leak is closed unless Strict is
    # explicitly turned OFF (proxy_check_block_on_fail=False).
    _proxy_cfg_early = profile_config.get("proxy") if isinstance(profile_config.get("proxy"), dict) else {}
    _proxy_on = bool(
        (_proxy_cfg_early or {}).get("enabled")
        or str((_proxy_cfg_early or {}).get("server") or "").strip()
        or str((_proxy_cfg_early or {}).get("provider_id") or "").strip()
        or (_proxy_cfg_early or {}).get("use_proxyjet")
    )
    if "proxy_check_block_on_fail" in anti:
        proxy_check_block_on_fail = bool(anti.get("proxy_check_block_on_fail"))
    else:
        proxy_check_block_on_fail = bool(_proxy_on)
    if anti.get("strict_proxy") is True:
        proxy_check_block_on_fail = True
    if anti.get("strict_proxy") is False and "proxy_check_block_on_fail" not in anti:
        proxy_check_block_on_fail = False
    strict_mobile_shell = bool(anti.get("strict_mobile_shell"))
    # Default ON — matches AntiDetectConfig; old code used False and broke persistence
    use_persistent_context = bool(anti.get("use_persistent_context", True))
    local_api_cdp = bool(
        anti.get("local_api_cdp")
        or profile_config.get("local_api_cdp")
        or os.environ.get("KREXION_PROFILE_CDP", "").strip() == "1"
    )
    disable_ipv6 = bool(anti.get("disable_ipv6", True))
    stealth_profile = str(anti.get("stealth_profile") or "full").lower().strip()
    if stealth_profile not in ("full", "minimal", "safari"):
        stealth_profile = "full"
    if paranoia_mode:
        # Deepen paranoia: no CDP, force WebRTC proxy, IPv6 off, Strict proxy
        local_api_cdp = False
        disable_ipv6 = True
        if webrtc_mode == "real":
            webrtc_mode = "proxy"
        anti = dict(anti)
        anti["fingerprint_win"] = True
        anti["proxy_check_block_on_fail"] = True
        anti["disable_ipv6"] = True
        proxy_check_block_on_fail = True
    anti = dict(anti) if not isinstance(anti, dict) else dict(anti)
    anti["disable_ipv6"] = disable_ipv6
    anti["local_api_cdp"] = local_api_cdp
    anti["stealth_profile"] = stealth_profile

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
    _launch_warnings: List[str] = []
    def _brand_warn(msg: str) -> None:
        try:
            from krexion_profile_branding import sanitize_user_facing as _suf
            _launch_warnings.append(_suf(msg))
        except Exception:
            _launch_warnings.append(msg)
    if paranoia_mode:
        _launch_warnings.append(
            "Paranoia mode: CDP off, WebRTC proxy, IPv6 disabled, Strict proxy ON."
        )
    _lppw = str(profile_config.get("_launch_proxy_probe_warning") or "").strip()
    if _lppw:
        _launch_warnings.append(_lppw)
    _wanted_webkit = _profile_engine == "webkit"
    # v2.7.52 — Resolve referer ONCE per launch (sticky_session parity).
    # Previously _coerce_profile_ua and route setup each called the resolver
    # independently, so platform_pool could pick Facebook for the UA and
    # TikTok for the Referer on the same session.
    _profile_referrer_state = _resolve_profile_referrer_state(
        ua,
        profile_config,
        start_url or "https://www.google.com/",
    )
    _profile_referrer_state.session_id = session_id
    try:
        _ensure_sticky_profile_params(_profile_referrer_state)
    except Exception:
        pass
    try:
        from referrer_pro import dominant_platform_from_weights as _dom_pw
        _ref_cfg = profile_config.get("referrer") or {}
        _uw = _dom_pw(_ref_cfg.get("platform_weights"))
        _profile_referrer_state.ua_platform = (
            _uw or _profile_referrer_state.platform or ""
        )
    except Exception:
        _profile_referrer_state.ua_platform = _profile_referrer_state.platform or ""
    _locale_for_ua = ""
    try:
        _al = str(_profile_referrer_state.accept_language or "").split(",")[0].strip()
        _locale_for_ua = _al.split(";")[0].strip().replace("_", "-") if _al else ""
    except Exception:
        _locale_for_ua = ""
    ua = _coerce_profile_ua(
        ua,
        profile_config,
        referrer_state=_profile_referrer_state,
        locale=_locale_for_ua,
    )
    # v2.7.58 — Sync Chrome major AFTER platform coercion so in-app markers
    # stay intact while the declared version matches the launched binary.
    if _profile_engine != "webkit":
        try:
            from anti_detect_v230 import align_ua_to_chromium as _align_chrome
            _aligned = _align_chrome(ua)
            if _aligned:
                ua = _aligned
        except Exception:
            pass
    _profile_referrer_state.user_agent = ua
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
    # v2.7.30 — Resolve provider / ProxyJet → concrete server (RUT parity).
    _uid = str(profile_config.get("user_id") or "").strip()
    if _uid and not str(proxy_cfg.get("server") or "").strip():
        try:
            from browser_profile_module import resolve_profile_proxy_for_launch
            proxy_cfg = await resolve_profile_proxy_for_launch(
                _uid,
                None,
                proxy_cfg,
                team_dedupe=True,
                profile_country=profile_config.get("country"),
            )
            profile_config = dict(profile_config)
            profile_config["proxy"] = proxy_cfg
        except HTTPException:
            raise
        except Exception as _pr_err:
            logger.warning(f"[profile-launch] inline proxy resolve skipped: {_pr_err}")

    if _uid:
        try:
            from browser_profile_module import resolve_launch_proxy_cfg

            proxy_cfg = await resolve_launch_proxy_cfg(_uid, None, proxy_cfg)
            profile_config = dict(profile_config)
            profile_config["proxy"] = proxy_cfg
        except HTTPException:
            raise
        except Exception as _hydr_err:
            logger.warning(f"[profile-launch] proxy cred hydrate skipped: {_hydr_err}")

    proxy_cfg = profile_config.get("proxy") or proxy_cfg

    proxy_arg = None
    proxy_diag: Dict[str, Any] = {"requested": False, "server": "", "ok": None, "error": ""}
    _proxy_enabled = False
    try:
        from browser_profile_module import proxy_is_active as _proxy_is_active
        _proxy_enabled = _proxy_is_active(proxy_cfg)
    except Exception:
        _proxy_enabled = bool(
            proxy_cfg.get("enabled")
            or proxy_cfg.get("use_proxyjet")
            or str(proxy_cfg.get("provider_id") or "").strip()
        )
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

        username = (username or "").strip()
        password = (password or "").strip()
        # v2.7.127 — Re-hydrate from raw_line right before Playwright so
        # saved-from-list / geo-rewrite never leaves host-only auth.
        if (not username or not password) and proxy_cfg:
            try:
                from browser_profile_module import hydrate_proxy_credentials as _hpc

                _hyd = _hpc(dict(proxy_cfg))
                username = username or str(_hyd.get("username") or "").strip()
                password = password or str(_hyd.get("password") or "").strip()
                if _hyd.get("server"):
                    raw_server = str(_hyd.get("server") or raw_server).strip() or raw_server
            except Exception:
                pass
        # v2.7.125/127 — NEVER launch with a proxy server but missing auth.
        # That is exactly what opens Chromium's "Sign in" dialog for
        # gw.dataimpulse.com / residential gateways.
        if not username or not password:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Proxy server is set but username/password is missing. "
                    "Edit the profile → Proxy → paste a full line "
                    "(user:pass@host:port or host:port:user:pass), or re-add the "
                    "saved proxy with full auth, then launch again. "
                    "Launch is blocked so Chromium cannot show a proxy Sign-in popup "
                    "or leak your real IP."
                ),
            )
        proxy_arg = {
            "server": raw_server,
            "username": username,
            "password": password,
        }
        proxy_diag["requested"] = True
        proxy_diag["server"] = raw_server
    elif _proxy_enabled and not proxy_cfg.get("server"):
        proxy_diag["requested"] = True
        proxy_diag["ok"] = False
        proxy_diag["error"] = (
            "Proxy enabled but no server URL could be resolved "
            "(check Settings → Proxy Providers credentials, or paste a manual line)"
        )

    # Proxy ON + webrtc=real would leak the customer's real IP via STUN.
    try:
        from browser_profile_module import proxy_is_active as _pia_webrtc
        _proxy_on_for_webrtc = _pia_webrtc(proxy_cfg) or bool(proxy_arg)
    except Exception:
        _proxy_on_for_webrtc = bool(proxy_arg) or bool(_proxy_enabled)
    if _proxy_on_for_webrtc and webrtc_mode == "real":
        webrtc_mode = "proxy"
        _launch_warnings.append(
            "WebRTC was set to 'real' while a proxy is enabled — forced to "
            "'proxy' so your real IP cannot leak through WebRTC/STUN."
        )
    if _proxy_on_for_webrtc and webrtc_mode == "proxy":
        _launch_warnings.append(
            "WebRTC mode 'proxy' blocks non-proxied UDP (host ICE). "
            "It does NOT rewrite ICE candidates to the proxy exit IP."
        )
    if tls_prewarm:
        _launch_warnings.append(
            "TLS prewarm seeds cookies via curl_cffi — it does NOT change the "
            "live browser JA3/H2 fingerprint (Playwright/Cloak Chromium still applies)."
        )
    if profile_config.get("geo_follow_proxy") is False and (_proxy_on_for_webrtc or _proxy_enabled):
        _launch_warnings.append(
            "geo_follow_proxy is OFF — timezone/locale may disagree with proxy exit IP "
            "(strong fraud signal on many sites)."
        )
    if is_mobile and (webgl_mode in ("real", "off") or canvas_mode in ("real", "off")):
        _launch_warnings.append(
            f"Mobile profile with canvas={canvas_mode}/webgl={webgl_mode}: "
            "host GPU/fonts may not match the mobile UA — prefer 'noise' unless using Cloak quiet."
        )
    if _profile_engine == "webkit":
        _launch_warnings.append(
            "Krexion Safari: Safari-shaped stealth (no window.chrome / Sec-CH-UA). "
            "Still desktop Krexion Safari — not a physical iPhone."
        )

    # Persist Strict proxy flag for old profiles that never saved it (one-shot migrate)
    if (
        _proxy_on
        and proxy_check_block_on_fail
        and "proxy_check_block_on_fail" not in (profile_config.get("anti_detect") or {})
        and on_session_update
    ):
        try:
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "launching",
                "anti_detect_patch": {"proxy_check_block_on_fail": True},
            })
        except Exception:
            pass

    # v2.7.103 — Dead DNS (BestGo ENOTFOUND etc.): never open browser through
    # an unresolvable gateway. Soft-disable proxy so iPhone/Android still open
    # with Krexion mobile shell; operator fixes host in Proxy Providers.
    # Strict proxy (proxy_check_block_on_fail): abort instead — never leak real IP.
    if proxy_arg and proxy_arg.get("server"):
        _dns_err = _proxy_dns_failure(str(proxy_arg.get("server") or ""))
        if _dns_err:
            if proxy_check_block_on_fail:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Strict proxy: proxy host could not be resolved "
                        f"({_dns_err}). Fix Settings → Proxy Providers "
                        "(working host like gw.dataimpulse.com) or paste a "
                        "fresh manual line, then relaunch. Browser was NOT "
                        "opened on your real IP."
                    ),
                )
            logger.warning(
                f"[profile-launch] proxy DNS soft-disable: {_dns_err} "
                f"session={(session_id or '')[:8]}"
            )
            proxy_diag["requested"] = True
            proxy_diag["ok"] = False
            proxy_diag["error"] = _dns_err
            proxy_diag["soft_disabled"] = True
            proxy_diag["server"] = str(proxy_arg.get("server") or "")
            _launch_warnings.append(
                f"Proxy host could not be resolved ({_dns_err}). "
                "Launched WITHOUT proxy — REAL MACHINE IP may be exposed. "
                "Fix Settings → Proxy Providers (use a working host like "
                "gw.dataimpulse.com) or paste a fresh manual line, then relaunch."
            )
            proxy_arg = None

    # RUT parity: when proxy is live, align timezone/locale/geo to exit IP.
    geo = await _align_profile_geo_from_proxy(geo, proxy_arg, ua, profile_config)
    locale = geo["locale"]
    timezone_id = geo["timezone"]
    accept_lang = geo["accept_language"]

    # v2.7.16 — Patchright driver when plan says so
    try:
        from krexion_browser_kernel import get_async_playwright_factory as _gaf
        async_playwright = _gaf(_kernel_plan)
    except Exception:
        pass
    if str(_kernel_plan.get("engine") or "") == "firefox":
        _profile_engine = "firefox"

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
        # Krexion identity lives on the Windows taskbar (WM_SETICON +
        # AppUserModelID) and a short window-name prefix. Per-tab
        # favicon/title stay site-owned (v2.4.1 customer ask).
        #
        # v2.7.11 — Do NOT pass `--user-data-dir=` as a Chromium CLI arg
        # to `browser_type.launch()`. Modern Playwright rejects that and
        # aborts with: "Pass user_data_dir parameter to
        # launch_persistent_context(...) instead". Profiles persist via
        # Playwright `storage_state` on the context (below), not via a
        # Chrome user-data folder on launch().
        _profile_label = (
            profile_config.get("name")
            or profile_config.get("id")
            or profile_config.get("label")
            or "Profile"
        )
        _profile_first_letter = (str(_profile_label)[:1] or "K").upper()
        _taskbar_slot = int(
            ((_RUNNING_SESSIONS.get(session_id) or {}).get("taskbar_slot")) or 1
        )
        # v2.7.129 — AdsPower-parity window title + Custom Icon identity
        try:
            from krexion_profile_branding import (
                app_user_model_id as _aumid,
                build_window_title as _bwt,
                chromium_app_user_model_arg as _aum_arg,
                resolve_icon_mode as _rim,
            )

            _icon_mode = _rim(anti, profile_config)
            _is_webkit = str(_profile_engine or "").lower() in ("webkit", "safari", "ios")
            _is_phone = bool(is_mobile)
            _window_title = _bwt(
                slot=_taskbar_slot,
                name=str(_profile_label),
                notes=str(profile_config.get("notes") or ""),
                custom_no=str(
                    profile_config.get("custom_no")
                    or profile_config.get("serial_number")
                    or ""
                ),
                icon_mode=_icon_mode,
                webkit=_is_webkit,
                phone=_is_phone,
            )
            _pre_appid = _aumid(_taskbar_slot, phone=_is_phone)
            _aum_cli = _aum_arg(_taskbar_slot)
            try:
                (_RUNNING_SESSIONS.get(session_id) or {}).update({"window_title": _window_title})
            except Exception:
                pass
            # Title keeper starts once HWNDs are known (icon apply paths call it too).
        except Exception:
            _window_title = f"Krexion Browser \u2014 {_taskbar_slot} \u00b7 {str(_profile_label)[:32]}"
            _pre_appid = f"Krexion.BrowserProfile.{_taskbar_slot}"
            _aum_cli = f"--app-user-model-id={_pre_appid}"
        # v2.7.15 — WebRTC launch flags from webrtc_mode (default proxy = current)
        _WEBRTC_FORCE = "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"
        _launch_args = [a for a in _headed_launch_args(anti) if a != _WEBRTC_FORCE]
        if webrtc_mode == "disabled":
            _launch_args.append("--disable-webrtc")
            _launch_args.append(_WEBRTC_FORCE)
        elif webrtc_mode == "real":
            pass  # omit force-webrtc — allow real WebRTC
        else:
            # proxy (default): keep non-proxied UDP disabled
            _launch_args.append(_WEBRTC_FORCE)
        # v2.7.13 / v2.7.129 — AppUserModelID per slot (AdsPower-style taskbar group)
        try:
            if sys.platform.startswith("win"):
                import ctypes as _ctypes_pre
                _ctypes_pre.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_pre_appid)
        except Exception:
            pass
        launch_kwargs: Dict[str, Any] = {
            "headless": False,
            "args": [
                *_launch_args,
                # Durable branded title (title-keeper re-applies after navigation)
                f"--window-name={_window_title}",
                _aum_cli,
            ],
        }
        # Merge CloakBrowser default stealth CLI args (dedupe)
        for _sa in (_kernel_plan.get("stealth_args") or []):
            if _sa and _sa not in launch_kwargs["args"]:
                launch_kwargs["args"].append(_sa)
        if _kernel_plan.get("executable_path"):
            launch_kwargs["executable_path"] = _kernel_plan["executable_path"]
        else:
            try:
                from real_user_traffic import (  # type: ignore
                    normalize_playwright_browsers_path,
                    _full_chromium_binary_path,
                )
                normalize_playwright_browsers_path()
                _fc = _full_chromium_binary_path()
                if _fc is not None:
                    launch_kwargs["executable_path"] = str(_fc)
            except Exception:
                pass
        logger.info(
            f"[profile-launch] kernel={_kernel_plan.get('kernel_label')} "
            f"driver={_kernel_plan.get('driver')} exe={bool(_kernel_plan.get('executable_path'))}"
        )

        async def _krx_launch_chromium() -> Any:
            """Launch Chromium via Cloak exe path / channel / stock."""
            from krexion_browser_kernel import launch_chromium_with_plan as _lcp
            _plan = dict(_kernel_plan)
            variant = (anti.get("browser_variant") or "auto").lower()
            _force_sys = (
                os.environ.get("KREXION_PROFILE_USE_SYSTEM_CHROME", "").strip() == "1"
                or variant == "chrome"
                or _plan.get("preference") == "chrome"
            )
            if _force_sys and not _plan.get("executable_path"):
                _plan["channel"] = "chrome"
                _plan["kernel_label"] = "system-chrome"
            try:
                return await _lcp(p, launch_kwargs, _plan)
            except Exception as _lex:
                logger.warning(f"[profile-launch] kernel launch failed ({_lex}); stock chromium")
                _kw = dict(launch_kwargs)
                try:
                    from real_user_traffic import (  # type: ignore
                        _ensure_full_chromium_available,
                        _full_chromium_binary_path,
                        normalize_playwright_browsers_path,
                    )
                    normalize_playwright_browsers_path()
                    _fc = _full_chromium_binary_path()
                    if _fc is not None:
                        _kw["executable_path"] = str(_fc)
                    else:
                        _kw.pop("executable_path", None)
                except Exception:
                    _kw.pop("executable_path", None)
                try:
                    return await p.chromium.launch(**_kw)
                except Exception as _lex2:
                    _msg = str(_lex2)
                    if "Executable doesn't exist" in _msg or "executable doesn't exist" in _msg.lower():
                        try:
                            from real_user_traffic import (  # type: ignore
                                _ensure_full_chromium_available,
                                _full_chromium_binary_path,
                            )
                            if await _ensure_full_chromium_available():
                                _fc2 = _full_chromium_binary_path()
                                if _fc2 is not None:
                                    _kw["executable_path"] = str(_fc2)
                                    return await p.chromium.launch(**_kw)
                        except Exception as _retry_err:
                            logger.warning(f"[profile-launch] chromium retry failed: {_retry_err}")
                    raise _lex2 from _lex
        # v2.7.13 / v2.7.105e — CDP opt-in ONLY (Local API / env / anti_detect.local_api_cdp).
        # Native/local used to always open --remote-debugging-port → automation surface.
        _cdp_port: Optional[int] = None
        _want_cdp = bool(local_api_cdp)
        if _want_cdp and _profile_engine != "webkit":
            try:
                import socket as _sock

                with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as _s:
                    _s.bind(("127.0.0.1", 0))
                    _cdp_port = int(_s.getsockname()[1])
                launch_kwargs["args"].append(f"--remote-debugging-port={_cdp_port}")
                launch_kwargs["args"].append("--remote-debugging-address=127.0.0.1")
                _launch_warnings.append(
                    "Local API CDP is ON — remote debugging port is open on 127.0.0.1 "
                    "(automation surface). Turn off anti_detect.local_api_cdp if unused."
                )
            except Exception as _cdp_bind_err:
                logger.debug(f"[profile-launch] CDP port bind skipped: {_cdp_bind_err}")
                _cdp_port = None
        # Chromium: proxy on launch. WebKit: prefer proxy on context (below).
        if proxy_arg and _profile_engine != "webkit":
            launch_kwargs["proxy"] = proxy_arg

        context = None
        _persistent_mode = False
        browser = None  # type: ignore

        if _profile_engine == "webkit":
            # Krexion Safari (WebKit) — AdsPower FlowerBrowser-class white-label.
            # Force Safari stealth profile unless user set minimal.
            if stealth_profile == "full":
                stealth_profile = "safari"
            wk_kwargs: Dict[str, Any] = {"headless": False}
            try:
                from krexion_branded_browser import ensure_krexion_safari_binary as _eks
                _safari = _eks()
                if _safari:
                    wk_kwargs["executable_path"] = _safari
            except Exception:
                pass
            try:
                browser = await p.webkit.launch(**wk_kwargs)
            except Exception as _wk_err:
                logger.warning(
                    "WebKit launch failed (%s) — falling back to Chromium",
                    _wk_err,
                )
                _launch_warnings.append(
                    "Krexion Safari unavailable — running Krexion Browser instead. "
                    "This is NOT a real iPhone/iOS Safari. It is a desktop browser "
                    "with a mobile shell (viewport + UA). Advanced trackers can still "
                    "tell it is not a physical iPhone."
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
                browser = await _krx_launch_chromium()
        elif _profile_engine == "firefox":
            ff_kwargs: Dict[str, Any] = {"headless": False}
            if proxy_arg:
                ff_kwargs["proxy"] = proxy_arg
            try:
                browser = await p.firefox.launch(**ff_kwargs)
                logger.info("[profile-launch] Firefox engine ON")
            except Exception as _ff_err:
                logger.warning(f"Firefox launch failed ({_ff_err}) — Chromium fallback")
                _launch_warnings.append(
                    "Firefox engine unavailable — running Chromium instead."
                )
                _profile_engine = "chromium"
                if proxy_arg:
                    launch_kwargs["proxy"] = proxy_arg
                browser = await _krx_launch_chromium()
        else:
            # Prefer CloakBrowser C++ kernel (Octo-class) when available.
            channel: Optional[str] = None
            variant = (anti.get("browser_variant") or "auto").lower()
            _force_sys_chrome = (
                os.environ.get("KREXION_PROFILE_USE_SYSTEM_CHROME", "").strip() == "1"
                or variant == "chrome"
            )
            if _force_sys_chrome:
                channel = "chrome"
            # v2.7.15 / v2.7.105e — Persistent context works WITH Cloak executable_path
            # (previously Cloak blocked user-data-dir — AdsPower-class save never ran).
            _krx_mode = (os.environ.get("KREXION_MODE") or "").lower()
            _want_persist = (
                use_persistent_context
                and _profile_engine not in ("webkit", "firefox")
                and (sys.platform.startswith("win") or sys.platform.startswith("linux"))
                and _krx_mode in ("native", "local", "desktop")
            )
            _persistent_mode = False
            browser = None  # type: ignore
            if _want_persist:
                try:
                    if sys.platform.startswith("win"):
                        _base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
                        _udir = os.path.join(_base, "Krexion", "profile_data", str(profile_id or session_id))
                    else:
                        _base = os.path.expanduser("~/.local/share/Krexion")
                        _udir = os.path.join(_base, "profile_data", str(profile_id or session_id))
                    os.makedirs(_udir, exist_ok=True)
                    _pk: Dict[str, Any] = {
                        "user_data_dir": _udir,
                        "headless": False,
                        "args": list(launch_kwargs.get("args") or []),
                        "user_agent": ua,
                        "viewport": {
                            "width": int(viewport.get("width", 1920)),
                            "height": int(viewport.get("height", 1080)),
                        },
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
                    if proxy_arg:
                        _pk["proxy"] = proxy_arg
                    if storage_state and (storage_state.get("cookies") or storage_state.get("origins")):
                        _pk["storage_state"] = storage_state
                    if channel:
                        _pk["channel"] = channel
                    if launch_kwargs.get("executable_path"):
                        _pk["executable_path"] = launch_kwargs["executable_path"]
                    context = await p.chromium.launch_persistent_context(**_pk)
                    browser = context.browser
                    _persistent_mode = True
                    logger.info(
                        f"[profile-launch] persistent context ON dir={_udir} "
                        f"session={session_id[:8]}"
                    )
                except Exception as _persist_err:
                    logger.warning(
                        f"[profile-launch] persistent context failed ({_persist_err}); "
                        f"falling back to ephemeral launch"
                    )
                    _persistent_mode = False
                    browser = None
            if not _persistent_mode:
                browser = await _krx_launch_chromium()

        # 2026-07 / v2.7.11 — Krexion taskbar brand (Windows).
        # v2.7.13 — Numbered badge = open-profile slot (top-left).
        # v2.7.105d — Early shell + HWND-embed proof; strict abort not swallowed.
        _launch_ui_meta: Dict[str, Any] = {
            "mobile_shell": False,
            "mobile_shell_embedded": False,
            "webkit": _profile_engine == "webkit",
        }
        # Mobile profiles: Strict shell ON unless explicitly disabled
        if is_mobile and "strict_mobile_shell" not in anti:
            strict_mobile_shell = True
        elif is_mobile and anti.get("strict_mobile_shell") is None:
            strict_mobile_shell = True

        def _brand_krexion_taskbar(
            *,
            mobile_shell: bool = False,
            require_embed: bool = True,
            allow_restart: bool = True,
        ) -> None:
            """Apply Krexion phone frame / taskbar brand.

            For mobile: success requires shell process AND engine HWND embedded
            inside the frame (not process-alive alone).
            """
            try:
                from krexion_window_icon import (
                    apply_krexion_icon_to_pids,
                    keep_krexion_window_title,
                    collect_profile_process_tree,
                    resolve_playwright_driver_pid,
                    stop_session_icon_keeper,
                )

                _driver_pid = resolve_playwright_driver_pid(browser, context)
                _launch_ui_meta["driver_pid"] = int(_driver_pid) if _driver_pid else None
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
                        pass
                _cmd_markers = None
                _title_markers = None
                _include_webkit = False
                if _profile_engine == "webkit":
                    _include_webkit = True
                    _title_markers = ["[WebKit]", "Safari", "Krexion"]
                else:
                    _cmd_markers = ["--window-name=Krexion", "--window-name=Krexion Browser", "--window-name=Krexion Safari", "--window-name=Krexion Phone"]
                _family_pids = sorted(
                    collect_profile_process_tree(int(_driver_pid) if _driver_pid else None)
                    or set(_target_pids)
                )
                _poll = 120.0 if _profile_engine == "webkit" else 90.0
                _will_try_mobile_shell = False
                if mobile_shell:
                    try:
                        from krexion_mobile_browser_shell import should_use_mobile_shell

                        _will_try_mobile_shell = should_use_mobile_shell(
                            str(profile_os or ""),
                            bool(is_mobile),
                        )
                    except Exception:
                        _will_try_mobile_shell = False

                _use_mobile_shell = bool(mobile_shell and _will_try_mobile_shell)
                if _use_mobile_shell:
                    try:
                        from krexion_mobile_browser_shell import (
                            apply_krexion_mobile_shell,
                            wait_for_mobile_shell,
                            wait_for_mobile_shell_embedded,
                            is_mobile_shell_alive,
                            is_mobile_shell_embedded,
                            preflight_mobile_shell,
                            mobile_shell_status,
                            force_discover_and_mark_embedded,
                        )

                        _embed_wait = 45.0 if _profile_engine == "webkit" else 30.0

                        # Already framed from early pass — just verify / refresh meta
                        if is_mobile_shell_embedded(session_id):
                            _launch_ui_meta["mobile_shell"] = True
                            _launch_ui_meta["mobile_shell_embedded"] = True
                            stop_session_icon_keeper(str(session_id))
                            return

                        if is_mobile_shell_alive(session_id) and not allow_restart:
                            # Keep living chrome — force discover + longer wait
                            force_discover_and_mark_embedded(
                                str(session_id),
                                parent_pid=int(_driver_pid) if _driver_pid else None,
                                seed_pids=_family_pids,
                                webkit=_profile_engine == "webkit",
                                profile_slot=int(_taskbar_slot),
                            )
                            _embedded = wait_for_mobile_shell_embedded(
                                session_id, timeout_sec=_embed_wait,
                            ) if require_embed else False
                            if _embedded or is_mobile_shell_embedded(session_id):
                                _launch_ui_meta["mobile_shell"] = True
                                _launch_ui_meta["mobile_shell_embedded"] = True
                                stop_session_icon_keeper(str(session_id))
                                return
                            if require_embed:
                                # Last chance without tearing down shell
                                if force_discover_and_mark_embedded(
                                    str(session_id),
                                    parent_pid=int(_driver_pid) if _driver_pid else None,
                                    seed_pids=_family_pids,
                                    webkit=_profile_engine == "webkit",
                                    profile_slot=int(_taskbar_slot),
                                ):
                                    _launch_ui_meta["mobile_shell"] = True
                                    _launch_ui_meta["mobile_shell_embedded"] = True
                                    stop_session_icon_keeper(str(session_id))
                                    return
                                # v2.7.126 — Strict ON: never leave plain Chromium/WebKit
                                # as a "running" Krexion design. Soft path only when
                                # Strict is OFF.
                                if strict_mobile_shell:
                                    try:
                                        from krexion_mobile_browser_shell import (
                                            stop_mobile_shell as _stop_ms,
                                        )
                                        _stop_ms(str(session_id))
                                    except Exception:
                                        pass
                                    raise RuntimeError(
                                        "Strict mobile shell: Krexion phone chrome started "
                                        "but could not frame the browser. Launch aborted — "
                                        "plain Chromium/WebKit will not be shown as Krexion design."
                                    )
                                _launch_warnings.append(
                                    "Krexion phone chrome started but the browser window "
                                    "was not framed inside it — session kept open (Strict shell OFF)."
                                )
                                if _profile_engine == "webkit":
                                    try:
                                        from krexion_mobile_browser_shell import (
                                            polish_webkit_phone_fallback,
                                        )

                                        polish_webkit_phone_fallback(
                                            parent_pid=int(_driver_pid) if _driver_pid else None,
                                            seed_pids=_family_pids,
                                            viewport_width=int(viewport.get("width", 393)),
                                            viewport_height=int(viewport.get("height", 852)),
                                            profile_slot=int(_taskbar_slot),
                                            profile_label=str(_profile_label)[:60] or "Profile",
                                        )
                                    except Exception:
                                        pass
                                _launch_ui_meta["mobile_shell"] = True
                                _launch_ui_meta["mobile_shell_embedded"] = False
                                stop_session_icon_keeper(str(session_id))
                                return
                            # Soft early pass: process alive is enough
                            _launch_ui_meta["mobile_shell"] = True
                            stop_session_icon_keeper(str(session_id))
                            return

                        _pf = preflight_mobile_shell()
                        if not _pf.get("ok"):
                            _msg = str(_pf.get("error") or "Mobile shell preflight failed")
                            _launch_warnings.append(_msg)
                            if strict_mobile_shell:
                                raise RuntimeError(
                                    f"Strict mobile shell: {_msg} Launch aborted — "
                                    "plain Chromium/WebKit would have opened instead."
                                )
                            _use_mobile_shell = False
                        else:
                            _shell_active = False
                            _embedded_ok = False
                            for _shell_try in range(3):
                                apply_krexion_mobile_shell(
                                    _family_pids,
                                    session_key=str(session_id),
                                    parent_pid=int(_driver_pid) if _driver_pid else None,
                                    platform=str(profile_os or "android"),
                                    viewport_width=int(viewport.get("width", 393)),
                                    viewport_height=int(viewport.get("height", 852)),
                                    profile_label=str(_profile_label)[:60] or "Profile",
                                    profile_slot=int(_taskbar_slot),
                                    poll_seconds=_poll,
                                    webkit=_profile_engine == "webkit",
                                    home_url=str(start_url or "https://www.google.com/")[:512],
                                )
                                _shell_active = wait_for_mobile_shell(
                                    session_id, timeout_sec=12.0,
                                )
                                if _shell_active and is_mobile_shell_alive(session_id):
                                    if require_embed:
                                        _embedded_ok = wait_for_mobile_shell_embedded(
                                            session_id, timeout_sec=_embed_wait,
                                        )
                                        if not _embedded_ok:
                                            _embedded_ok = force_discover_and_mark_embedded(
                                                str(session_id),
                                                parent_pid=int(_driver_pid) if _driver_pid else None,
                                                seed_pids=_family_pids,
                                                webkit=_profile_engine == "webkit",
                                                profile_slot=int(_taskbar_slot),
                                            )
                                    else:
                                        _embedded_ok = is_mobile_shell_embedded(session_id)
                                    if _embedded_ok or not require_embed:
                                        break
                                time.sleep(0.55)

                            _st = mobile_shell_status(session_id)
                            # Early pass (require_embed=False): process alive is enough to continue;
                            # post-nav pass requires HWND embed for success.
                            _early_ok = bool(_shell_active and not require_embed)
                            if _st.get("ok") or (_shell_active and _embedded_ok) or _early_ok:
                                _launch_ui_meta["mobile_shell"] = True
                                _launch_ui_meta["mobile_shell_embedded"] = bool(
                                    _st.get("embedded") or _embedded_ok
                                )
                                stop_session_icon_keeper(str(session_id))
                                logger.info(
                                    f"[profile-launch] mobile shell "
                                    f"{'EMBEDDED' if _launch_ui_meta['mobile_shell_embedded'] else 'STARTED'} "
                                    f"session={session_id[:8]}"
                                )
                                if _launch_ui_meta["mobile_shell_embedded"]:
                                    _launch_warnings.append(
                                        "Mobile shell is a desktop browser framed like a phone — "
                                        "not a real iPhone/Android device. Use for UX testing; "
                                        "do not assume undetectable mobile fingerprint."
                                    )
                                apply_krexion_icon_to_pids(
                                    _family_pids,
                                    profile_label=str(_profile_label)[:60] or "Profile",
                                    parent_pid=int(_driver_pid) if _driver_pid else None,
                                    poll_seconds=12.0,
                                    profile_slot=int(_taskbar_slot),
                                    cmdline_markers=_cmd_markers,
                                    window_title_markers=_title_markers,
                                    include_webkit=_include_webkit,
                                    platform=str(profile_os or ""),
                                    session_key=str(session_id),
                                    skip_toolwindow=True,
                                    session_lifetime=False,
                                )
                                try:
                                    # AdsPower-style durable title (site navigations overwrite --window-name)
                                    if _window_title:
                                        keep_krexion_window_title(
                                            [],
                                            str(_window_title),
                                            session_key=f"title:{session_id}",
                                            pids=list(_family_pids or []),
                                        )
                                    _start_title_keeper_for_session(session_id, [])
                                except Exception:
                                    pass
                                return

                            # Process up but HWND never framed — last force discover
                            if _shell_active and not _embedded_ok:
                                if force_discover_and_mark_embedded(
                                    str(session_id),
                                    parent_pid=int(_driver_pid) if _driver_pid else None,
                                    seed_pids=_family_pids,
                                    webkit=_profile_engine == "webkit",
                                    profile_slot=int(_taskbar_slot),
                                ):
                                    _launch_ui_meta["mobile_shell"] = True
                                    _launch_ui_meta["mobile_shell_embedded"] = True
                                    stop_session_icon_keeper(str(session_id))
                                    return
                                logger.warning(
                                    f"[profile-launch] mobile shell process alive but "
                                    f"engine HWND not embedded session={session_id[:8]}"
                                )
                                _launch_warnings.append(
                                    "Krexion phone chrome started but the browser window "
                                    "was not framed inside it — you may see plain Chromium/WebKit."
                                )
                            else:
                                logger.warning(
                                    f"[profile-launch] mobile shell failed to start "
                                    f"session={session_id[:8]} — using engine window only"
                                )
                                _launch_warnings.append(
                                    "Krexion mobile device shell did not start — "
                                    "you are seeing the plain browser window, not the branded iOS/Android shell."
                                )
                            # v2.7.126 — Strict + require_embed: abort. Soft-continue
                            # only when Strict is OFF (or early pass without embed).
                            try:
                                from krexion_window_icon import profile_engine_window_exists
                                _engine_up = profile_engine_window_exists(
                                    int(_driver_pid) if _driver_pid else None,
                                    webkit=_profile_engine == "webkit",
                                )
                            except Exception:
                                _engine_up = bool(_driver_pid)
                            if strict_mobile_shell and require_embed:
                                # v2.7.135 — Last-chance multi-pass discover before abort
                                _final_ok = False
                                for _fd_try in range(6):
                                    try:
                                        if force_discover_and_mark_embedded(
                                            str(session_id),
                                            parent_pid=int(_driver_pid) if _driver_pid else None,
                                            seed_pids=_family_pids,
                                            webkit=_profile_engine == "webkit",
                                            profile_slot=int(_taskbar_slot),
                                        ):
                                            _final_ok = True
                                            break
                                    except Exception:
                                        pass
                                    time.sleep(0.55)
                                if _final_ok or is_mobile_shell_embedded(session_id):
                                    _launch_ui_meta["mobile_shell"] = True
                                    _launch_ui_meta["mobile_shell_embedded"] = True
                                    stop_session_icon_keeper(str(session_id))
                                    return
                                try:
                                    from krexion_mobile_browser_shell import (
                                        stop_mobile_shell as _stop_ms2,
                                    )
                                    _stop_ms2(str(session_id))
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    "Strict mobile shell: Krexion phone chrome did not "
                                    "frame the browser. Launch aborted so plain Chromium/"
                                    "WebKit is not shown as Krexion design."
                                )
                            if _profile_engine == "webkit":
                                try:
                                    from krexion_mobile_browser_shell import (
                                        polish_webkit_phone_fallback,
                                    )

                                    polish_webkit_phone_fallback(
                                        parent_pid=int(_driver_pid) if _driver_pid else None,
                                        seed_pids=_family_pids,
                                        viewport_width=int(viewport.get("width", 393)),
                                        viewport_height=int(viewport.get("height", 852)),
                                        profile_slot=int(_taskbar_slot),
                                        profile_label=str(_profile_label)[:60] or "Profile",
                                    )
                                except Exception as _pol_err:
                                    logger.debug(
                                        f"[profile-launch] webkit polish fallback skipped: {_pol_err}"
                                    )
                            _launch_ui_meta["mobile_shell"] = bool(_shell_active)
                            _launch_ui_meta["mobile_shell_embedded"] = False
                            if _shell_active or _engine_up:
                                _launch_warnings.append(
                                    "Krexion phone chrome could not fully frame the "
                                    "browser — session kept open (Strict shell OFF). "
                                    "Retry Launch or check Windows display scaling / pywebview."
                                )
                                # marker for tests: soft path only when Strict OFF
                            stop_session_icon_keeper(str(session_id))
                            return
                    except RuntimeError:
                        raise
                    except Exception as _ms_err:
                        logger.warning(f"[profile-launch] mobile shell skipped: {_ms_err}")
                        _launch_warnings.append(
                            "Mobile device shell could not be applied — not a real device shell UI."
                        )
                        try:
                            from krexion_window_icon import profile_engine_window_exists
                            _engine_up = profile_engine_window_exists(
                                int(_driver_pid) if _driver_pid else None,
                                webkit=_profile_engine == "webkit",
                            )
                        except Exception:
                            _engine_up = bool(_driver_pid)
                        if strict_mobile_shell and require_embed:
                            try:
                                from krexion_mobile_browser_shell import (
                                    stop_mobile_shell as _stop_ms3,
                                )
                                _stop_ms3(str(session_id))
                            except Exception:
                                pass
                            raise RuntimeError(
                                f"Strict mobile shell: {str(_ms_err)[:200]}"
                            ) from _ms_err
                        if _profile_engine == "webkit":
                            try:
                                from krexion_mobile_browser_shell import (
                                    polish_webkit_phone_fallback,
                                )

                                polish_webkit_phone_fallback(
                                    parent_pid=int(_driver_pid) if _driver_pid else None,
                                    seed_pids=_family_pids,
                                    viewport_width=int(viewport.get("width", 393)),
                                    viewport_height=int(viewport.get("height", 852)),
                                    profile_slot=int(_taskbar_slot),
                                    profile_label=str(_profile_label)[:60] or "Profile",
                                )
                            except Exception:
                                pass
                        _launch_warnings.append(
                            f"Phone chrome error (session kept, Strict OFF): {str(_ms_err)[:120]}"
                        )

                # Non-Windows / shell not attempted: honesty warning for mobile profiles
                if (
                    bool(is_mobile)
                    and not _launch_ui_meta.get("mobile_shell_embedded")
                    and not _launch_ui_meta.get("mobile_shell")
                ):
                    _launch_warnings.append(
                        "Desktop Chromium/WebKit — not a real iPhone/Android device. "
                        "Krexion phone chrome is Windows-only; fingerprint sites may detect desktop."
                    )
                    if strict_mobile_shell and not _use_mobile_shell:
                        raise RuntimeError(
                            "Strict mobile shell: mobile chrome is unavailable on this host "
                            "(Windows + pywebview required). Launch aborted."
                        )

                apply_krexion_icon_to_pids(
                    _family_pids,
                    profile_label=str(_profile_label)[:60] or "Profile",
                    parent_pid=int(_driver_pid) if _driver_pid else None,
                    poll_seconds=_poll,
                    profile_slot=int(_taskbar_slot),
                    cmdline_markers=_cmd_markers,
                    window_title_markers=_title_markers,
                    include_webkit=_include_webkit,
                    platform=str(profile_os or ""),
                    session_key=str(session_id),
                    skip_toolwindow=True,
                    session_lifetime=True,
                )
                try:
                    if _window_title:
                        keep_krexion_window_title(
                            [],
                            str(_window_title),
                            session_key=f"title:{session_id}",
                            pids=list(_family_pids or []),
                        )
                    _start_title_keeper_for_session(session_id, [])
                except Exception:
                    pass
            except RuntimeError:
                raise
            except Exception as _icon_err:
                logger.debug(f"Krexion taskbar-icon override skipped: {_icon_err}")
                if strict_mobile_shell and is_mobile and mobile_shell:
                    raise RuntimeError(
                        f"Strict mobile shell: branding failed ({str(_icon_err)[:160]}). "
                        "Launch aborted."
                    ) from _icon_err

        # Early shell start happens after first page (see below) to shrink
        # the plain Chromium/WebKit window before navigation finishes.

        # Publish CDP websocket for Local API automation clients
        _cdp_ws = ""
        _debugger_addr = ""
        if _cdp_port:
            _debugger_addr = f"127.0.0.1:{_cdp_port}"
            try:
                import httpx as _httpx_cdp

                for _ in range(15):
                    try:
                        _vr = _httpx_cdp.get(
                            f"http://{_debugger_addr}/json/version",
                            timeout=1.5,
                        )
                        if _vr.status_code == 200:
                            _cdp_ws = str((_vr.json() or {}).get("webSocketDebuggerUrl") or "")
                            if _cdp_ws:
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.4)
            except Exception as _cdp_err:
                logger.debug(f"[profile-launch] CDP discover skipped: {_cdp_err}")
            if not _cdp_ws:
                _cdp_ws = f"http://{_debugger_addr}"
            if session_id in _RUNNING_SESSIONS:
                _RUNNING_SESSIONS[session_id]["cdp_ws"] = _cdp_ws
                _RUNNING_SESSIONS[session_id]["debugger_address"] = _debugger_addr

        context_kwargs: Dict[str, Any] = {
            "user_agent": ua,
            "viewport": {"width": int(viewport.get("width", 1920)), "height": int(viewport.get("height", 1080))},
            # v2.7.110 — WebKit MiniBrowser with DSF>1 zooms/crops the page
            # (Google logo cut off, giant ALL/IMAGES). Use DSF=1 for real
            # rendering; stealth fingerprint still reports the real DPR.
            "device_scale_factor": (
                1.0 if (_profile_engine == "webkit" and is_mobile and float(dsf) > 1.01) else dsf
            ),
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
        if _profile_engine == "webkit" and is_mobile and float(dsf) > 1.01:
            _launch_ui_meta["webkit_dsf_context"] = 1.0
            _launch_ui_meta["webkit_dsf_spoof"] = float(dsf)
            logger.info(
                "[profile-launch] WebKit mobile context DSF=1.0 (spoof DPR=%.2f)",
                float(dsf),
            )
        if proxy_arg:
            context_kwargs["proxy"] = proxy_arg
        if storage_state and (storage_state.get("cookies") or storage_state.get("origins")):
            context_kwargs["storage_state"] = storage_state

        if not _persistent_mode:
            try:
                context = await browser.new_context(**context_kwargs)
            except Exception as _ctx_err:
                _ctx_msg = str(_ctx_err)
                if proxy_arg and (
                    _is_dns_proxy_error(_ctx_msg)
                    or "proxy" in _ctx_msg.lower()
                    or "tunnel" in _ctx_msg.lower()
                ):
                    if proxy_check_block_on_fail:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                "Strict proxy: browser could not start with proxy "
                                f"({_ctx_msg[:180]}). Fix Proxy Providers / password, "
                                "then relaunch. Browser was NOT opened on your real IP."
                            ),
                        ) from _ctx_err
                    logger.warning(
                        f"[profile-launch] context+proxy failed ({_ctx_msg[:120]}) "
                        "— retrying WITHOUT proxy (REAL IP may leak) so iOS/Android still open"
                    )
                    context_kwargs.pop("proxy", None)
                    proxy_arg = None
                    proxy_diag["soft_disabled"] = True
                    proxy_diag["ok"] = False
                    proxy_diag["error"] = _ctx_msg[:240]
                    proxy_diag["requested"] = True
                    _launch_warnings.append(
                        "Proxy failed at browser start — opened WITHOUT proxy (REAL MACHINE IP may be exposed). "
                        "Fix Proxy Providers host/password, then relaunch."
                    )
                    context = await browser.new_context(**context_kwargs)
                else:
                    raise

        _webgl_cfg: Optional[Dict[str, Any]] = None
        _profile_ua = str(context_kwargs.get("user_agent") or ua)
        try:
            from anti_detect_v230 import align_webgl_to_ua_deterministic as _align_webgl
            if webgl_mode != "real":
                _webgl_cfg = _align_webgl(_profile_ua, profile_id or session_id)
            else:
                _webgl_cfg = None
        except Exception:
            _webgl_cfg = None
        if webgl_mode == "off":
            _webgl_cfg = {
                "vendor": "Google Inc.",
                "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
                "gpu_family": "generic",
            }
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
        # Krexion branding on Windows taskbar (WM_SETICON above).
        # Each tab keeps the site's real favicon and title.

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

        # _profile_referrer_state resolved once above (v2.7.52 sticky session).
        try:
            if _profile_referrer_state.enabled:
                await context.route(
                    "**/*",
                    make_profile_referrer_route_handler(_profile_referrer_state),
                )
                logger.info(
                    f"[profile-launch] referrer pro ON platform={_profile_referrer_state.platform} "
                    f"ua_platform={_profile_referrer_state.ua_platform} "
                    f"wrapper={_profile_referrer_state.wrapper_redirect} session={session_id[:8]}"
                )
                try:
                    from profile_network_enrich import install_profile_cdp_fetch_enricher
                    await install_profile_cdp_fetch_enricher(
                        context,
                        lambda: _profile_referrer_state,
                        enrich_url_fn=_profile_enrich_nav_url,
                        should_enrich_fn=_should_enrich_profile_offer_url,
                    )
                except Exception as _cdp_fetch_err:
                    logger.warning(
                        f"[profile-launch] CDP Fetch enricher skipped: {_cdp_fetch_err}"
                    )
            else:
                from referrer_pro import make_sec_ch_ua_strip_route_handler
                await context.route("**/*", make_sec_ch_ua_strip_route_handler())
        except Exception as _route_err:
            logger.debug(f"profile referrer/sec-ch route skipped: {_route_err}")
            try:
                from referrer_pro import make_sec_ch_ua_strip_route_handler
                await context.route("**/*", make_sec_ch_ua_strip_route_handler())
            except Exception:
                pass

        _ctx_hdrs = dict(context_kwargs.get("extra_http_headers") or {})
        _ctx_hdrs["Accept-Language"] = accept_lang
        if _profile_referrer_state.enabled:
            if _profile_referrer_state.accept_language:
                _ctx_hdrs["Accept-Language"] = _profile_referrer_state.accept_language
            _ctx_hdrs["Referrer-Policy"] = "unsafe-url"
            if _profile_referrer_state.referer_url:
                _ctx_hdrs["Referer"] = _profile_referrer_state.referer_url
            if _profile_referrer_state.sec_fetch:
                _ctx_hdrs.update(_profile_referrer_state.sec_fetch)

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
                    fingerprint_salt=str(profile_config.get("fingerprint_salt") or ""),
                )
                # v2.7.15 — Apply canvas/webgl/audio/font modes onto fp
                # v2.7.20 — Cloak quiet when Stealth kernel or all modes real/off
                try:
                    from fingerprint_win import should_use_quiet_mode as _quiet_fn
                    _cloak_quiet = _quiet_fn(
                        reduce_js_fingerprint_noise=bool(
                            _kernel_plan.get("reduce_js_fingerprint_noise")
                        ),
                        canvas_mode=canvas_mode,
                        webgl_mode=webgl_mode,
                        audio_mode=audio_mode,
                        font_mode=font_mode,
                    )
                except Exception:
                    _cloak_quiet = bool(_kernel_plan.get("reduce_js_fingerprint_noise"))
                _skip_natural_canvas = canvas_mode in ("off", "real")
                _skip_webgl_align = webgl_mode == "real"
                _fp_salt = str(profile_config.get("fingerprint_salt") or "")
                _stealth_identity = (
                    f"{profile_id}:{_fp_salt}" if _fp_salt else str(profile_id or session_id)
                )
                if canvas_mode in ("off", "real"):
                    _stealth_fp["canvas_seed"] = 0
                if audio_mode in ("off", "real"):
                    _stealth_fp["audio_seed"] = 0
                if font_mode in ("off", "real"):
                    _stealth_fp["font_seed"] = 0
                if webgl_mode == "real":
                    _stealth_fp["webgl_vendor"] = ""
                    _stealth_fp["webgl_renderer"] = ""
                    _stealth_identity = ""
                elif webgl_mode == "off":
                    _stealth_fp["webgl_vendor"] = "Google Inc."
                    _stealth_fp["webgl_renderer"] = (
                        "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"
                    )
                    _stealth_identity = ""  # use generic fp values, don't UA-align
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
                    fp_hash_override=_stable_hash_fn(str(profile_id or session_id) + (f":{_fp_salt}" if _fp_salt else "")),
                    identity_label=_stealth_identity,
                    skip_natural_canvas=_skip_natural_canvas,
                    skip_webgl_align=_skip_webgl_align,
                    fingerprint_win=bool(anti.get("fingerprint_win", True)),
                    cloak_quiet=_cloak_quiet,
                    engine=str(_profile_engine or "chromium"),
                    stealth_profile=stealth_profile,
                )
                logger.info(
                    f"[profile-launch] RUT-parity stealth ON — "
                    f"os={_stealth_fp.get('os')} platform={_stealth_fp.get('platform')} "
                    f"engine={_profile_engine} stealth_profile={stealth_profile} "
                    f"webgl={str(_stealth_fp.get('webgl_renderer') or '')[:48]} "
                    f"canvas={canvas_mode} webrtc={webrtc_mode} "
                    f"fp_win={bool(anti.get('fingerprint_win', True))} "
                    f"cloak_quiet={_cloak_quiet}"
                )

                if paranoia_mode:
                    # Never invent window.chrome on WebKit/Safari path
                    if _profile_engine == "webkit" or stealth_profile == "safari":
                        await context.add_init_script(
                            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                        )
                    else:
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
                    _v230_safari = (
                        _profile_engine == "webkit" or stealth_profile == "safari"
                    )
                    _v230_report = await apply_v230_stealth(
                        context,
                        ua=ua,
                        viewport=viewport,
                        platform="",
                        safari_mode=_v230_safari,
                    )
                    _extra_hdrs = dict(_ctx_hdrs)
                    _extra_hdrs.update(_v230_report.get("headers") or {})
                    if not _v230_safari:
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
                _v230_safari = (
                    _profile_engine == "webkit" or stealth_profile == "safari"
                )
                _v230_report = await apply_v230_stealth(
                    context,
                    ua=ua,
                    viewport=viewport,
                    platform="",
                    safari_mode=_v230_safari,
                )
                _extra_hdrs = dict(_ctx_hdrs)
                _extra_hdrs.update(_v230_report.get("headers") or {})
                if not _v230_safari:
                    _extra_hdrs.update(_profile_ch_hints)
                _extra_hdrs["Accept-Language"] = accept_lang
                await context.set_extra_http_headers(_extra_hdrs)
            except Exception as _v230_err:
                logger.debug(f"v2.3.0 anti-detect apply skipped: {_v230_err}")

        try:
            await _install_profile_cdp_ua_all_pages(
                context,
                lambda: _profile_referrer_state.user_agent or ua,
            )
        except Exception as _cdp_ua_err:
            logger.debug(f"[profile-launch] CDP UA all-pages skipped: {_cdp_ua_err}")

        page = await context.new_page()

        # v2.7.110 — Re-assert CSS viewport (WebKit can ignore first paint size)
        # and spoof devicePixelRatio when context DSF was forced to 1.0.
        try:
            await page.set_viewport_size({
                "width": int(viewport.get("width", 1920)),
                "height": int(viewport.get("height", 1080)),
            })
        except Exception as _svp_err:
            logger.debug(f"[profile-launch] set_viewport_size skipped: {_svp_err}")
        if _profile_engine == "webkit" and is_mobile and float(dsf) > 1.01:
            try:
                await context.add_init_script(
                    f"""(() => {{
  try {{
    Object.defineProperty(window, 'devicePixelRatio', {{
      configurable: true, enumerable: true, get: () => {float(dsf)}
    }});
  }} catch (e) {{}}
}})();"""
                )
            except Exception as _dpr_err:
                logger.debug(f"[profile-launch] WebKit DPR spoof skipped: {_dpr_err}")

        # v2.7.135 — Early Krexion phone chrome: ALWAYS start shell without
        # requiring HWND embed yet. Pre-135 Strict ON aborted here when the
        # engine HWND was not ready ~0.45s after new_page (iOS WebKit + Android
        # Chromium both failed open). Hide naked engine until post-nav embed.
        # Final Strict gate remains AFTER navigation (require_embed=True).
        if is_mobile:
            try:
                # Give headed engine a moment to create its HWND
                for _hwnd_wait in range(12):
                    try:
                        from krexion_window_icon import profile_engine_window_exists
                        if profile_engine_window_exists(
                            int(_launch_ui_meta.get("driver_pid") or 0) or None,
                            webkit=_profile_engine == "webkit",
                        ):
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    await asyncio.sleep(0.35)
                # Soft start — never abort on missing embed in early pass
                _brand_krexion_taskbar(
                    mobile_shell=True,
                    require_embed=False,
                    allow_restart=True,
                )
                # Soft force-discover (best effort); Strict still enforced post-nav
                if not _launch_ui_meta.get("mobile_shell_embedded"):
                    try:
                        from krexion_mobile_browser_shell import (
                            force_discover_and_mark_embedded as _fd_early,
                        )
                        if _fd_early(
                            str(session_id),
                            parent_pid=int(_launch_ui_meta.get("driver_pid") or 0) or None,
                            seed_pids=None,
                            webkit=_profile_engine == "webkit",
                            profile_slot=int(_taskbar_slot),
                        ):
                            _launch_ui_meta["mobile_shell"] = True
                            _launch_ui_meta["mobile_shell_embedded"] = True
                    except Exception:
                        pass
                if strict_mobile_shell and not _launch_ui_meta.get("mobile_shell_embedded"):
                    # Honesty: hide/minimize naked engine so user never sees
                    # plain Chromium/WebKit as "Krexion" before post-nav frame.
                    try:
                        from krexion_window_icon import hide_profile_engine_windows
                        hide_profile_engine_windows(
                            int(_launch_ui_meta.get("driver_pid") or 0) or None,
                            webkit=_profile_engine == "webkit",
                        )
                    except Exception:
                        pass
                    _launch_warnings.append(
                        "Krexion phone chrome started — framing browser after navigation "
                        "(Strict shell will abort only if final embed fails)."
                    )
            except RuntimeError as _early_shell_err:
                # Strict abort — close browser before user mistakes it for Krexion design
                logger.error(f"[profile-launch] strict mobile shell abort: {_early_shell_err}")
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    if browser is not None and not _persistent_mode:
                        await browser.close()
                except Exception:
                    pass
                raise
            except Exception as _early_brand_err:
                logger.debug(f"[profile-launch] early shell skipped: {_early_brand_err}")
                if strict_mobile_shell:
                    try:
                        await context.close()
                    except Exception:
                        pass
                    try:
                        if browser is not None and not _persistent_mode:
                            await browser.close()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Strict mobile shell: {str(_early_brand_err)[:200]}"
                    ) from _early_brand_err

        # WebKit MiniBrowser: rename window ASAP so taskbar/title is Krexion, not [WebKit]
        if _profile_engine == "webkit":
            try:
                await page.evaluate(
                    f"""() => {{ try {{ document.title = {json.dumps('Krexion — ' + str(_profile_label or 'Profile')[:40])}; }} catch (e) {{}} }}"""
                )
            except Exception:
                pass

        # v2.6.32 — TLS prewarm seeds cookies before first navigation (RUT parity).
        _last_tls_prewarm_ok = None
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
                _last_tls_prewarm_ok = bool(_pw_res and _pw_res.get("ok"))
                if _pw_res and _pw_res.get("ok") and _pw_res.get("cookies"):
                    await context.add_cookies(_pw_res["cookies"])
            except Exception as _pw_err:
                _last_tls_prewarm_ok = False
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
            ua,
            profile_config,
            start_url or "https://www.google.com/",
            referrer_state=_profile_referrer_state,
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
        # v2.7.15 — gated by anti.proxy_check_on_launch (default True).
        if proxy_arg is not None and proxy_check_on_launch:
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

        # v2.7.15 — Hard-abort when proxy check failed and block_on_fail is set.
        # Also abort when soft_disabled stripped the proxy (real-IP leak path) —
        # previously soft_disabled set proxy_arg=None so this gate never fired.
        if proxy_check_block_on_fail and (
            proxy_diag.get("soft_disabled")
            or (
                proxy_arg is not None
                and proxy_check_on_launch
                and proxy_diag.get("ok") is False
            )
            or (
                proxy_diag.get("requested")
                and proxy_arg is None
                and proxy_diag.get("ok") is False
            )
        ):
            _abort_msg = str(proxy_diag.get("error") or "proxy check failed")[:300]
            logger.warning(
                f"[profile-launch] proxy_check_block_on_fail — aborting: {_abort_msg}"
            )
            if on_session_update:
                try:
                    await on_session_update({
                        "profile_id": profile_id,
                        "session_id": session_id,
                        "status": "error",
                        "error_message": f"Strict proxy: {_abort_msg}",
                        "last_proxy_check": proxy_diag,
                        "last_tls_prewarm_ok": _last_tls_prewarm_ok,
                        "launch_warnings": list(_launch_warnings),
                    })
                except Exception:
                    pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    await browser.close()
            except Exception:
                pass
            _RUNNING_SESSIONS.pop(session_id, None)
            return {
                "ok": False,
                "session_id": session_id,
                "error": (
                    f"Strict proxy: {_abort_msg}. Browser was NOT opened on your real IP."
                ),
                "proxy_diag": proxy_diag,
                "launch_warnings": list(_launch_warnings),
            }

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
        elif proxy_diag.get("soft_disabled"):
            # DNS soft-disable already stripped proxy — open the real start URL.
            try:
                _target_url = start_url or "https://www.google.com/"
                _target_url = _profile_enrich_nav_url(
                    _target_url, _profile_referrer_state
                )
                await page.goto(
                    _target_url,
                    timeout=45000,
                    wait_until="domcontentloaded",
                    **({"referer": _referer_url} if _referer_url else {}),
                )
            except Exception as _soft_nav_err:
                logger.warning(
                    f"[profile-launch] soft-disable nav failed: {_soft_nav_err}"
                )
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
                    + (
                        "<li><b>DNS could not resolve this proxy hostname</b> — the gateway "
                        "name is wrong, expired, or blocked on this PC. Open Settings → Proxy "
                        "Providers and paste a working host (e.g. DataImpulse "
                        "<code>gw.dataimpulse.com</code>). BestGo hosts like "
                        "<code>*.bestgo.work</code> must resolve in your browser/DNS first.</li>"
                        if ("ENOTFOUND" in _safe_err or "getaddrinfo" in _safe_err.lower()
                            or "Name or service not known" in _safe_err)
                        else
                        "<li>Verify your proxy credentials are still active (Settings → Proxy Providers / ProxyJet)</li>"
                    )
                    + "<li>Try a different country / state or a fresh manual proxy line</li>"
                    "<li>Switch to <code>No Proxy</code> if you only need a clean UA / viewport</li>"
                    "<li>Check that the desktop machine's firewall / DNS allows outbound HTTPS</li>"
                    "</ul>"
                    "<p class='muted'>Note: &quot;Continue without proxy&quot; only opens the start URL "
                    "in this window — the profile proxy setting is unchanged until you edit the profile.</p>"
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
            _target_url = _profile_enrich_nav_url(
                _target_url, _profile_referrer_state
            )
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

        # Finalize branding — verify HWND embed after navigation (early pass may
        # have started the phone chrome already). Restart shell when early pass
        # left chrome un-framed so Krexion design can still apply.
        try:
            await asyncio.sleep(0.35)
            _brand_krexion_taskbar(
                mobile_shell=True,
                require_embed=True,
                allow_restart=not bool(_launch_ui_meta.get("mobile_shell_embedded")),
            )
            if session_id in _RUNNING_SESSIONS:
                _launch_ui_meta["ui_watch_started_mono"] = time.monotonic()
                _RUNNING_SESSIONS[session_id].update(_launch_ui_meta)
        except RuntimeError as _brand_strict_err:
            logger.error(f"[profile-launch] strict mobile shell abort (post-nav): {_brand_strict_err}")
            try:
                await context.close()
            except Exception:
                pass
            try:
                if browser is not None and not _persistent_mode:
                    await browser.close()
            except Exception:
                pass
            raise
        except Exception as _brand_post_err:
            logger.debug(f"[profile-launch] post-nav branding skipped: {_brand_post_err}")

        # Tell cloud the session is now RUNNING
        if on_session_update:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": "running",
                    "fingerprint_hash": _fingerprint_hash,
                    "cdp_ws": _cdp_ws or "",
                    "debugger_address": _debugger_addr or "",
                    "last_tls_prewarm_ok": _last_tls_prewarm_ok,
                    "last_proxy_check": proxy_diag if proxy_diag.get("requested") else {},
                    "browser_kernel": str(_kernel_plan.get("kernel_label") or ""),
                    "launch_warnings": list(_launch_warnings),
                    "mobile_shell_active": bool(
                        _launch_ui_meta.get("mobile_shell_embedded")
                        or _launch_ui_meta.get("mobile_shell")
                    ),
                    "mobile_shell_embedded": bool(_launch_ui_meta.get("mobile_shell_embedded")),
                    "engine_used": str(_profile_engine or "chromium"),
                })
            except Exception:
                pass

        # v2.7.79 — Optional JSON automation (RUT step engine) after first navigation.
        if profile_config.get("_launch_automation", {}).get("enabled"):
            await _run_profile_automation_if_configured(
                page,
                profile_config,
                session_id=session_id,
                profile_id=profile_id,
                on_session_update=on_session_update,
            )

        # ── Wait until the customer closes the browser ───────────────
        # We poll instead of using a single await so we can also respond
        # to a programmatic stop request from the cloud /stop endpoint.
        closed_event = asyncio.Event()
        _last_storage_flush = time.time()
        _tracked_pages: set = set()

        def _track_page(pg: Any) -> None:
            if pg in _tracked_pages:
                return
            _tracked_pages.add(pg)

            def _on_pg_close() -> None:
                _tracked_pages.discard(pg)
                try:
                    live_ctx = [
                        p
                        for p in (getattr(context, "pages", None) or [])
                        if not p.is_closed()
                    ]
                    live_tracked = {p for p in _tracked_pages if not p.is_closed()}
                    if not live_ctx and not live_tracked:
                        _sess = _RUNNING_SESSIONS.get(session_id) or {}
                        _watch = float(_sess.get("ui_watch_started_mono") or 0.0)
                        if _watch > 0 and (time.monotonic() - _watch) < _PROFILE_UI_WATCH_GRACE_SEC:
                            return
                        closed_event.set()
                except Exception:
                    closed_event.set()

            try:
                pg.on("close", lambda *_: _on_pg_close())
            except Exception:
                pass

        for _pg in list(getattr(context, "pages", None) or []):
            _track_page(_pg)
        try:
            context.on("page", lambda pg: _track_page(pg))
        except Exception:
            pass
        try:
            context.on("close", lambda *_: closed_event.set())
        except Exception:
            pass

        def _on_disconnected():
            closed_event.set()

        _br_for_events = browser if browser is not None else getattr(context, "browser", None)
        if _br_for_events is not None:
            _br_for_events.on("disconnected", lambda *_: _on_disconnected())
        else:
            # Persistent context without browser handle — poll context pages
            pass

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
                        if browser is not None and not _persistent_mode:
                            await browser.close()
                    except Exception:
                        pass
                    break
                # v2.7.75 — Auto-stop when user closes browser (X); minimize is OK.
                if _profile_user_closed_ui(session_id, context, browser, _tracked_pages):
                    closed_event.set()
                    break
                # v2.7.76 — Interactive mobile shell (back/forward/reload/tabs).
                if sess.get("mobile_shell"):
                    try:
                        _live_pg = [
                            p for p in (getattr(context, "pages", None) or [])
                            if not p.is_closed()
                        ]
                        _idx = int(sess.get("shell_active_tab") or 0)
                        _shell_pg = (
                            _live_pg[_idx]
                            if _live_pg and _idx < len(_live_pg)
                            else (_live_pg[0] if _live_pg else page)
                        )
                        await _apply_shell_commands(
                            session_id,
                            context,
                            _shell_pg,
                            start_url or "https://www.google.com/",
                        )
                    except Exception as _sh_err:
                        logger.debug(f"[mobile-shell] command poll skipped: {_sh_err}")
                # v2.7.79 — Drain queued JSON automation re-runs (profile still open).
                _auto_q = sess.get("automation_queue") or []
                if (
                    _auto_q
                    and page
                    and not page.is_closed()
                    and not sess.get("automation_running")
                    and not sess.get("automation_cancel_requested")
                ):
                    _next_auto = _auto_q.pop(0)
                    try:
                        _live_pg = [
                            p for p in (getattr(context, "pages", None) or [])
                            if not p.is_closed()
                        ]
                        _auto_pg = _live_pg[0] if _live_pg else page
                        await _run_profile_automation_if_configured(
                            _auto_pg,
                            profile_config,
                            session_id=session_id,
                            profile_id=profile_id,
                            on_session_update=on_session_update,
                            automation_spec=_next_auto,
                        )
                    except Exception as _aq_err:
                        logger.debug(f"[profile-automation] queue run skipped: {_aq_err}")
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
        try:
            from krexion_mobile_browser_shell import stop_mobile_shell
            from krexion_window_icon import stop_session_icon_keeper

            stop_mobile_shell(session_id)
            stop_session_icon_keeper(session_id)
        except Exception:
            pass
        new_storage: Dict[str, Any] = {}
        try:
            _still = True
            try:
                if browser is not None and hasattr(browser, "is_connected"):
                    _still = bool(browser.is_connected())
            except Exception:
                _still = True
            if not _still:
                pass
            else:
                new_storage = await context.storage_state()
                await context.close()
                if browser is not None and not _persistent_mode:
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
    sid = str(session_id or "").strip()
    try:
        from krexion_mobile_browser_shell import stop_mobile_shell
        from krexion_window_icon import stop_session_icon_keeper

        stop_mobile_shell(sid)
        stop_session_icon_keeper(sid)
    except Exception:
        pass
    sess = _RUNNING_SESSIONS.get(session_id)
    if not sess:
        return False
    sess["stop_requested"] = True
    return True


def request_stop_automation(session_id: str) -> bool:
    """Stop JSON automation only — browser profile stays open for manual use."""
    sid = str(session_id or "").strip()
    sess = _RUNNING_SESSIONS.get(sid) or _RUNNING_SESSIONS.get(session_id)
    if not sess:
        return False
    sess["automation_cancel_requested"] = True
    sess["automation_queue"] = []
    task = sess.get("automation_task")
    try:
        if task is not None and hasattr(task, "done") and not task.done():
            task.cancel()
    except Exception:
        pass
    return True


def request_run_automation(session_id: str, automation_spec: Dict[str, Any]) -> bool:
    """Queue JSON automation on a live profile session (Phase 4 re-run)."""
    sid = str(session_id or "").strip()
    if sid not in _RUNNING_SESSIONS:
        return False
    if not isinstance(automation_spec, dict) or not automation_spec.get("enabled"):
        return False
    sess = _RUNNING_SESSIONS[sid]
    queue = sess.setdefault("automation_queue", [])
    queue.append(dict(automation_spec))
    return True


async def _run_profile_automation_if_configured(
    page: Any,
    profile_config: Dict[str, Any],
    *,
    session_id: str,
    profile_id: str,
    on_session_update: Optional[Any],
    automation_spec: Optional[Dict[str, Any]] = None,
) -> None:
    """Run JSON steps when launch spec or queued re-run requests automation."""
    spec = dict(automation_spec or profile_config.get("_launch_automation") or {})
    if not spec.get("enabled"):
        return
    if not spec.get("steps") and not spec.get("smart_funnel_enabled"):
        return
    uid = str(profile_config.get("user_id") or "").strip()
    sess = _RUNNING_SESSIONS.get(session_id)
    if sess and sess.get("automation_running"):
        return
    if sess:
        sess["automation_running"] = True
        sess["automation_cancel_requested"] = False

    def _should_cancel() -> bool:
        s = _RUNNING_SESSIONS.get(session_id) or {}
        return bool(s.get("automation_cancel_requested"))

    _profile_db = None
    if uid:
        try:
            from server import get_user_db

            _profile_db = get_user_db(uid)
        except Exception:
            _profile_db = None

    _max_next_leads = 50
    _next_loops = 0
    try:
        from browser_profile_automation import (
            run_profile_automation,
            claim_next_data_file_row,
            release_reserved_data_file_row,
            _normalize_after_mode,
        )

        while True:
            result = await run_profile_automation(
                page,
                list(spec.get("steps") or []),
                dict(spec.get("lead_row") or {}),
                user_id=uid,
                session_id=session_id,
                profile_id=profile_id,
                on_session_update=on_session_update,
                skip_missing_steps=spec.get("skip_missing_steps", True) is not False,
                self_heal=bool(spec.get("self_heal")),
                should_cancel=_should_cancel,
                data_file_id=str(spec.get("data_file_id") or ""),
                lead_row_index=spec.get("lead_row_index"),
                db=_profile_db,
                smart_funnel_enabled=bool(spec.get("smart_funnel_enabled")),
                smart_funnel_pattern=str(spec.get("smart_funnel_pattern") or "auto"),
                smart_funnel_min_deals=int(spec.get("smart_funnel_min_deals") or 2),
                smart_funnel_wait_until_conversion=bool(
                    spec.get("smart_funnel_wait_until_conversion", True)
                ),
                consume_mode=str(spec.get("consume_mode") or "on_submit"),
                lead_consumed_already=bool(spec.get("lead_consumed_already")),
                lead_fingerprint=str(spec.get("lead_fingerprint") or ""),
                after_mode=str(spec.get("after_mode") or "manual"),
            )

            after = _normalize_after_mode(
                (result or {}).get("after_mode") or spec.get("after_mode") or "manual"
            )
            status = str((result or {}).get("automation_status") or (result or {}).get("status") or "")

            if after == "next_lead" and status in ("completed", "ok", "captcha") and _next_loops < _max_next_leads:
                dfid = str(spec.get("data_file_id") or "").strip()
                if not dfid or _profile_db is None:
                    break
                try:
                    lead, idx, meta = await claim_next_data_file_row(
                        _profile_db,
                        uid,
                        dfid,
                        consume_now=str(spec.get("consume_mode") or "") == "on_start",
                    )
                    spec["lead_row"] = lead
                    spec["lead_row_index"] = idx
                    spec["lead_fingerprint"] = str(meta.get("fingerprint") or "")
                    spec["lead_consumed_already"] = bool(meta.get("consumed_now"))
                    profile_config["_launch_automation"] = spec
                    _next_loops += 1
                    if on_session_update:
                        try:
                            await on_session_update({
                                "profile_id": profile_id,
                                "session_id": session_id,
                                "status": "running",
                                "automation_status": "running",
                                "automation_action": "next_lead",
                                "automation_error": "",
                            })
                        except Exception:
                            pass
                    continue
                except Exception as _nl_err:
                    logger.info(f"[profile-automation] next_lead stopped: {_nl_err}")
                    if on_session_update:
                        try:
                            await on_session_update({
                                "profile_id": profile_id,
                                "session_id": session_id,
                                "status": "running",
                                "automation_status": "completed",
                                "automation_error": f"next_lead ended: {str(_nl_err)[:200]}",
                            })
                        except Exception:
                            pass
                    break

            if after == "close":
                # Request browser stop after JSON finishes (keep open on error/stop).
                if status in ("completed", "ok", "captcha"):
                    try:
                        request_stop(session_id)
                    except Exception as _cls_err:
                        logger.debug(f"[profile-automation] after_mode close skipped: {_cls_err}")
            break
    except asyncio.CancelledError:
        if on_session_update:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": "running",
                    "automation_status": "stopped",
                    "automation_error": "",
                })
            except Exception:
                pass
        # Release soft reservation if lead was never consumed
        try:
            if _profile_db and not bool(spec.get("lead_consumed_already")):
                await release_reserved_data_file_row(
                    _profile_db,
                    uid,
                    str(spec.get("data_file_id") or ""),
                    lead_row_index=spec.get("lead_row_index"),
                    fingerprint=str(spec.get("lead_fingerprint") or ""),
                )
        except Exception:
            pass
    except Exception as exc:
        logger.warning(f"[profile-automation] run failed: {exc}")
        if on_session_update:
            try:
                await on_session_update({
                    "profile_id": profile_id,
                    "session_id": session_id,
                    "status": "running",
                    "automation_status": "error",
                    "automation_error": str(exc)[:512],
                })
            except Exception:
                pass
    finally:
        if sess:
            sess["automation_running"] = False
            sess.pop("automation_task", None)


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
                        {"$set": {
                            "status": "running",
                            "session_id": sid,
                            "last_error": "",
                        }},
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
                    _prof_set: Dict[str, Any] = {
                        "status": "idle" if status in ("stopped", "closed") else "error",
                        "session_id": "",
                    }
                    if status == "error" and body.get("error_message"):
                        _prof_set["last_error"] = str(body.get("error_message"))[:512]
                    await motor_db.browser_profiles.update_one(
                        {"id": profile_id},
                        {"$set": _prof_set},
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


async def warm_profile_cookies(
    profile_config: Dict[str, Any],
    urls: Optional[List[str]] = None,
    max_urls: int = 5,
) -> Dict[str, Any]:
    """Best-effort cookie warm: brief Chromium visits with stealth, return storage_state.

    Default URLs: google + youtube + wikipedia. Max 5 URLs, 15s timeout each.
    """
    default_urls = [
        "https://www.google.com/",
        "https://www.youtube.com/",
        "https://www.wikipedia.org/",
    ]
    targets: List[str] = []
    for u in (urls or default_urls):
        s = str(u or "").strip()
        if s and s not in targets:
            targets.append(s)
        if len(targets) >= max(1, min(int(max_urls or 5), 10)):
            break
    if not targets:
        targets = default_urls[: max(1, min(int(max_urls or 5), 10))]

    visited: List[str] = []
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return {"ok": False, "error": f"playwright unavailable: {e}", "visited": []}

    ua = str(profile_config.get("user_agent") or "") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )
    viewport = profile_config.get("viewport") or {"width": 1920, "height": 1080}
    anti = profile_config.get("anti_detect") or {}
    master = bool(anti.get("master", True))
    profile_id = str(profile_config.get("id") or "warm")
    storage_state = profile_config.get("storage_state") or None
    proxy_cfg = profile_config.get("proxy") or {}
    proxy_arg = None
    if (proxy_cfg.get("enabled") or proxy_cfg.get("use_proxyjet")) and proxy_cfg.get("server"):
        raw = str(proxy_cfg["server"]).strip()
        if "://" not in raw:
            raw = f"http://{raw}"
        _u = str(proxy_cfg.get("username") or "").strip()
        _p = str(proxy_cfg.get("password") or "").strip()
        if not _u or not _p:
            logger.warning(
                "[cookie-robot] proxy server set without username/password — "
                "skipping proxy for warm (would trigger Chromium Sign-in)"
            )
            proxy_arg = None
        else:
            proxy_arg = {"server": raw, "username": _u, "password": _p}

    headless = str(os.environ.get("KREXION_COOKIE_ROBOT_HEADED", "")).strip() != "1"
    try:
        async with async_playwright() as p:
            launch_kwargs: Dict[str, Any] = {
                "headless": headless,
                "args": list(_PROFILE_HEADED_LAUNCH_ARGS),
            }
            if proxy_arg:
                launch_kwargs["proxy"] = proxy_arg
            browser = await p.chromium.launch(**launch_kwargs)
            ctx_kwargs: Dict[str, Any] = {
                "user_agent": ua,
                "viewport": {
                    "width": int(viewport.get("width") or 1920),
                    "height": int(viewport.get("height") or 1080),
                },
                "locale": str(profile_config.get("locale") or "en-US"),
                "timezone_id": str(profile_config.get("timezone") or "America/New_York"),
            }
            if storage_state and (storage_state.get("cookies") or storage_state.get("origins")):
                ctx_kwargs["storage_state"] = storage_state
            context = await browser.new_context(**ctx_kwargs)
            if master:
                try:
                    from anti_detect_v230 import _stable_hash as _stable_hash_fn
                    from real_user_traffic import _rut_apply_context_stealth
                    _fp = _build_profile_stealth_fp(
                        ua,
                        profile_id=profile_id,
                        viewport=ctx_kwargs["viewport"],
                        dsf=float(profile_config.get("device_scale_factor") or 1.0),
                        is_mobile=bool(profile_config.get("is_mobile")),
                        has_touch=bool(profile_config.get("has_touch")),
                        profile_os=str(profile_config.get("os") or "windows"),
                        fingerprint_salt=str(profile_config.get("fingerprint_salt") or ""),
                    )
                    geo = {
                        "locale": ctx_kwargs["locale"],
                        "timezone": ctx_kwargs["timezone_id"],
                        "accept_language": str(profile_config.get("accept_language") or "en-US,en;q=0.9"),
                        "lat": 40.7128,
                        "lon": -74.0060,
                    }
                    await _rut_apply_context_stealth(
                        context,
                        fp=_fp,
                        geo=geo,
                        ua=ua,
                        platform=str(_fp.get("platform") or ""),
                        ctx_headers={"Accept-Language": geo["accept_language"]},
                        fp_hash_override=_stable_hash_fn(
                            profile_id + (f":{profile_config.get('fingerprint_salt') or ''}")
                        ),
                        identity_label=profile_id,
                        fingerprint_win=bool((profile_config.get("anti_detect") or {}).get("fingerprint_win", True)),
                        cloak_quiet=False,
                        engine="chromium",
                        stealth_profile=str(
                            (profile_config.get("anti_detect") or {}).get("stealth_profile") or "full"
                        ),
                    )
                except Exception as _st_err:
                    logger.debug(f"[cookie-robot] stealth skipped: {_st_err}")
            page = await context.new_page()
            for url in targets:
                try:
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    visited.append(url)
                    await asyncio.sleep(0.8)
                except Exception as _nav_err:
                    logger.debug(f"[cookie-robot] visit failed {url}: {_nav_err}")
            ss = await context.storage_state()
            await context.close()
            await browser.close()
            return {"ok": True, "storage_state": ss, "visited": visited}
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:240]}",
            "visited": visited,
        }


__all__ = [
    "launch_profile_session",
    "request_stop",
    "request_stop_automation",
    "request_run_automation",
    "list_running",
    "process_pending_user_session_launches",
    "expire_stale_user_session_launches",
    "warm_profile_cookies",
    "_build_profile_stealth_fp",
    "_PROFILE_HEADED_LAUNCH_ARGS",
]
