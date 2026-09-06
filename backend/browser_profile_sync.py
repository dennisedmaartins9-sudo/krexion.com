"""
Browser Profile Multi-Window Synchronizer (v2.7.17)
===================================================
AdsPower-class: master profile actions (navigate / click / type / scroll)
replay onto slave profiles via Playwright connect_over_cdp.

Requires local headed Chromium with CDP (auto-enabled on native/local).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("krexion.profile_sync")

# sync_id -> state
_SYNC_GROUPS: Dict[str, Dict[str, Any]] = {}


def _jitter_ms(base: float = 40.0, spread: float = 80.0) -> float:
    return max(0.0, (base + random.uniform(0, spread)) / 1000.0)


async def _connect_cdp(cdp_ws: str):
    """Return (playwright, browser, context, page) or raise."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    endpoint = (cdp_ws or "").strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        browser = await pw.chromium.connect_over_cdp(endpoint)
    else:
        browser = await pw.chromium.connect_over_cdp(endpoint)
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError("No browser contexts on CDP endpoint")
    ctx = contexts[0]
    pages = ctx.pages
    page = pages[0] if pages else await ctx.new_page()
    return pw, browser, ctx, page


async def _safe_close_pw(pw, browser=None) -> None:
    try:
        if browser:
            await browser.close()
    except Exception:
        pass
    try:
        if pw:
            await pw.stop()
    except Exception:
        pass


async def _replay_navigate(page, url: str, jitter: bool) -> None:
    if not url:
        return
    if jitter:
        await asyncio.sleep(_jitter_ms(30, 120))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        logger.debug(f"[sync] navigate failed: {e}")


async def _replay_click(page, x: float, y: float, button: str, jitter: bool) -> None:
    if jitter:
        await asyncio.sleep(_jitter_ms(20, 90))
        x += random.uniform(-2, 2)
        y += random.uniform(-2, 2)
    try:
        await page.mouse.click(x, y, button=button or "left")
    except Exception as e:
        logger.debug(f"[sync] click failed: {e}")


async def _replay_type(page, text: str, jitter: bool) -> None:
    if not text:
        return
    try:
        for ch in text:
            if jitter:
                await asyncio.sleep(_jitter_ms(15, 55))
            await page.keyboard.type(ch, delay=random.randint(20, 60) if jitter else 0)
    except Exception as e:
        logger.debug(f"[sync] type failed: {e}")


async def _replay_scroll(page, delta_y: float, jitter: bool) -> None:
    if jitter:
        await asyncio.sleep(_jitter_ms(10, 40))
    try:
        await page.mouse.wheel(0, delta_y)
    except Exception as e:
        logger.debug(f"[sync] scroll failed: {e}")


async def _install_master_hooks(page, sync_id: str, modes: Set[str]) -> None:
    """Inject DOM listeners that queue events into Python via expose_binding."""
    group = _SYNC_GROUPS.get(sync_id)
    if not group:
        return

    async def _on_sync_event(source, payload):  # noqa: ARG001
        try:
            if not isinstance(payload, dict):
                return
            await _broadcast_event(sync_id, payload)
        except Exception as e:
            logger.debug(f"[sync] event hook error: {e}")

    await page.expose_binding("krexionSyncEvent", _on_sync_event)

    mode_nav = "navigate" in modes
    mode_click = "click" in modes
    mode_type = "type" in modes
    mode_scroll = "scroll" in modes

    js = f"""
    (() => {{
      if (window.__krexionSyncInstalled) return;
      window.__krexionSyncInstalled = true;
      const modes = {{
        navigate: {str(mode_nav).lower()},
        click: {str(mode_click).lower()},
        type: {str(mode_type).lower()},
        scroll: {str(mode_scroll).lower()},
      }};
      let lastUrl = location.href;
      if (modes.navigate) {{
        setInterval(() => {{
          if (location.href !== lastUrl) {{
            lastUrl = location.href;
            window.krexionSyncEvent({{type:'navigate', url: lastUrl}});
          }}
        }}, 400);
      }}
      if (modes.click) {{
        document.addEventListener('click', (e) => {{
          window.krexionSyncEvent({{
            type:'click', x: e.clientX, y: e.clientY,
            button: e.button === 2 ? 'right' : 'left'
          }});
        }}, true);
      }}
      if (modes.type) {{
        document.addEventListener('keydown', (e) => {{
          if (e.ctrlKey || e.metaKey || e.altKey) return;
          if (e.key && e.key.length === 1) {{
            window.krexionSyncEvent({{type:'type', text: e.key}});
          }} else if (e.key === 'Enter' || e.key === 'Backspace' || e.key === 'Tab') {{
            window.krexionSyncEvent({{type:'key', key: e.key}});
          }}
        }}, true);
      }}
      if (modes.scroll) {{
        let t = 0;
        window.addEventListener('wheel', (e) => {{
          const now = Date.now();
          if (now - t < 80) return;
          t = now;
          window.krexionSyncEvent({{type:'scroll', deltaY: e.deltaY}});
        }}, {{passive:true}});
      }}
    }})();
    """
    await page.add_init_script(js)
    try:
        await page.evaluate(js)
    except Exception:
        pass


async def _broadcast_event(sync_id: str, payload: Dict[str, Any]) -> None:
    group = _SYNC_GROUPS.get(sync_id)
    if not group or not group.get("active"):
        return
    slaves = list(group.get("slaves") or [])
    jitter = bool(group.get("jitter", True))
    et = str(payload.get("type") or "")

    async def _one(slave: Dict[str, Any]) -> None:
        page = slave.get("page")
        if not page:
            return
        try:
            if et == "navigate":
                await _replay_navigate(page, str(payload.get("url") or ""), jitter)
            elif et == "click":
                await _replay_click(
                    page,
                    float(payload.get("x") or 0),
                    float(payload.get("y") or 0),
                    str(payload.get("button") or "left"),
                    jitter,
                )
            elif et == "type":
                await _replay_type(page, str(payload.get("text") or ""), jitter)
            elif et == "key":
                key = str(payload.get("key") or "")
                if key:
                    if jitter:
                        await asyncio.sleep(_jitter_ms(10, 40))
                    await page.keyboard.press(key)
            elif et == "scroll":
                await _replay_scroll(page, float(payload.get("deltaY") or 0), jitter)
            group["events"] = int(group.get("events") or 0) + 1
            group["last_event_at"] = time.time()
        except Exception as e:
            logger.debug(f"[sync] slave replay error: {e}")
            errs = list(group.get("slave_errors") or [])
            errs.append({
                "profile_id": str(slave.get("profile_id") or ""),
                "error": f"{type(e).__name__}: {str(e)[:160]}",
                "event": et,
                "at": time.time(),
            })
            group["slave_errors"] = errs[-40:]
            group["slave_error_count"] = int(group.get("slave_error_count") or 0) + 1

    await asyncio.gather(*[_one(s) for s in slaves], return_exceptions=True)


def resolve_cdp_for_profile(profile_id: str, doc: Optional[Dict[str, Any]] = None) -> str:
    """Prefer in-memory session CDP, then Mongo fields."""
    try:
        from browser_profile_launcher import list_running

        for sess in list_running().values():
            if str(sess.get("profile_id") or "") == str(profile_id):
                ws = str(sess.get("cdp_ws") or "").strip()
                if ws:
                    return ws
                addr = str(sess.get("debugger_address") or "").strip()
                if addr:
                    return f"http://{addr}"
    except Exception:
        pass
    doc = doc or {}
    ws = str(doc.get("cdp_ws") or "").strip()
    if ws:
        return ws
    addr = str(doc.get("debugger_address") or "").strip()
    if addr:
        return f"http://{addr}"
    return ""


async def start_sync(
    *,
    user_id: str,
    master_id: str,
    slave_ids: List[str],
    modes: Optional[List[str]] = None,
    jitter: bool = True,
    master_cdp: str = "",
    slave_cdps: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Attach to master + slaves over CDP and begin mirroring."""
    modes_set: Set[str] = set(modes or ["navigate", "click", "type", "scroll"])
    allowed = {"navigate", "click", "type", "scroll"}
    modes_set &= allowed
    if not modes_set:
        modes_set = {"navigate", "click", "type", "scroll"}

    slave_ids = [s for s in slave_ids if s and s != master_id]
    if not slave_ids:
        raise ValueError("At least one slave profile_id required")
    if not master_cdp:
        raise ValueError("Master CDP endpoint missing — launch profiles with CDP first")

    sync_id = str(uuid.uuid4())
    pw_handles: List[Any] = []
    browsers: List[Any] = []

    try:
        mpw, mbrowser, _mctx, mpage = await _connect_cdp(master_cdp)
        pw_handles.append(mpw)
        browsers.append(mbrowser)

        slaves: List[Dict[str, Any]] = []
        slave_cdps = slave_cdps or {}
        for sid in slave_ids:
            endpoint = (slave_cdps.get(sid) or "").strip()
            if not endpoint:
                raise ValueError(f"Slave {sid} CDP missing — launch it first")
            spw, sbrowser, _sctx, spage = await _connect_cdp(endpoint)
            pw_handles.append(spw)
            browsers.append(sbrowser)
            slaves.append({"profile_id": sid, "page": spage, "browser": sbrowser, "pw": spw})

        group = {
            "id": sync_id,
            "user_id": user_id,
            "master_id": master_id,
            "slave_ids": slave_ids,
            "modes": sorted(modes_set),
            "jitter": bool(jitter),
            "active": True,
            "started_at": time.time(),
            "events": 0,
            "last_event_at": 0.0,
            "master_page": mpage,
            "master_browser": mbrowser,
            "master_pw": mpw,
            "slaves": slaves,
            "pw_handles": pw_handles,
            "browsers": browsers,
        }
        _SYNC_GROUPS[sync_id] = group
        await _install_master_hooks(mpage, sync_id, modes_set)
        logger.info(
            f"[sync] started {sync_id} master={master_id} slaves={len(slaves)} modes={sorted(modes_set)}"
        )
        return status_sync(sync_id)
    except Exception:
        for b, p in zip(browsers, pw_handles):
            await _safe_close_pw(p, b)
        _SYNC_GROUPS.pop(sync_id, None)
        raise


async def stop_sync(sync_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    group = _SYNC_GROUPS.get(sync_id)
    if not group:
        return {"ok": False, "error": "sync not found"}
    if user_id and group.get("user_id") != user_id:
        return {"ok": False, "error": "forbidden"}
    group["active"] = False
    for b, p in zip(group.get("browsers") or [], group.get("pw_handles") or []):
        await _safe_close_pw(p, b)
    # Detach only — do not close user Chromium windows (connect_over_cdp close
    # may disconnect; browsers already closed above disconnects client only).
    snap = status_sync(sync_id)
    _SYNC_GROUPS.pop(sync_id, None)
    snap["ok"] = True
    snap["active"] = False
    return snap


def status_sync(sync_id: str) -> Dict[str, Any]:
    g = _SYNC_GROUPS.get(sync_id) or {}
    return {
        "ok": bool(g),
        "sync_id": sync_id if g else "",
        "active": bool(g.get("active")),
        "master_id": g.get("master_id") or "",
        "slave_ids": list(g.get("slave_ids") or []),
        "modes": list(g.get("modes") or []),
        "jitter": bool(g.get("jitter", True)),
        "events": int(g.get("events") or 0),
        "started_at": g.get("started_at") or 0,
        "last_event_at": g.get("last_event_at") or 0,
        "slave_error_count": int(g.get("slave_error_count") or 0),
        "slave_errors": list(g.get("slave_errors") or [])[-10:],
    }


def list_syncs_for_user(user_id: str) -> List[Dict[str, Any]]:
    out = []
    for sid, g in list(_SYNC_GROUPS.items()):
        if g.get("user_id") == user_id and g.get("active"):
            out.append(status_sync(sid))
    return out


def stop_all_for_user(user_id: str) -> int:
    n = 0
    for sid, g in list(_SYNC_GROUPS.items()):
        if g.get("user_id") == user_id:
            g["active"] = False
            _SYNC_GROUPS.pop(sid, None)
            n += 1
    return n
