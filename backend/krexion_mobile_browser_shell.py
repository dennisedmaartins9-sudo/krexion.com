"""
Krexion Mobile Browser Shell
============================
Headed mobile profiles get Krexion-branded chrome with platform-native UX:
  • iOS / iPadOS — Safari-like bottom toolbar + URL pill
  • Android — Chrome-like top omnibox + bottom nav

Playwright engine runs in the content area; pywebview renders chrome only.
Failures are swallowed — launch must never abort.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("krexion.mobile_shell")

_IS_WINDOWS = sys.platform.startswith("win")
_ACTIVE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# Krexion palette — not Apple/Google Material
_KRX_BG = "#0b0b12"
_KRX_GOLD = "#eed322"
_KRX_CYAN = "#22d3ee"
_KRX_VIOLET = "#7c3aed"


@dataclass
class MobileShellLayout:
    platform: str
    viewport_w: int
    viewport_h: int
    top_h: int
    bottom_h: int
    bezel: int
    outer_w: int
    outer_h: int

    @property
    def content_w(self) -> int:
        return self.viewport_w

    @property
    def content_h(self) -> int:
        return self.viewport_h


def compute_mobile_shell_layout(
    platform: str,
    viewport_w: int,
    viewport_h: int,
) -> MobileShellLayout:
    plat = (platform or "android").strip().lower()
    vw = max(320, min(1200, int(viewport_w or 393)))
    vh = max(568, min(1600, int(viewport_h or 844)))
    if plat in ("ios", "ipados"):
        # Safari: minimal top, main chrome at bottom (URL pill + toolbar).
        top_h, bottom_h, bezel = 28, 82, 0
    else:
        # Chrome Android: omnibox top + bottom nav row.
        top_h, bottom_h, bezel = 56, 52, 0
    outer_w = vw + bezel * 2
    outer_h = top_h + vh + bottom_h + bezel * 2
    return MobileShellLayout(
        platform=plat,
        viewport_w=vw,
        viewport_h=vh,
        top_h=top_h,
        bottom_h=bottom_h,
        bezel=bezel,
        outer_w=outer_w,
        outer_h=outer_h,
    )


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _shell_css_ios() -> str:
    return f"""
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 100%; height: 100%; overflow: hidden;
      background: #12121a; color: #e4e4e7;
      font-family: -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
      -webkit-user-select: none; user-select: none;
    }}
    .ios-top {{
      width: 100%; height: 100%; display: flex; align-items: center;
      justify-content: center; background: #12121a;
      border-bottom: 1px solid rgba(238,211,34,.12);
      font-size: 11px; font-weight: 600; letter-spacing: .14em;
      color: {_KRX_CYAN}; text-transform: uppercase;
    }}
    .safari-bottom {{
      width: 100%; height: 100%; display: flex; flex-direction: column;
      justify-content: flex-end; padding: 6px 10px 8px; gap: 8px;
      background: linear-gradient(180deg, #14141c, #0b0b12);
      border-top: 1px solid rgba(34,211,238,.15);
    }}
    .url-pill {{
      display: flex; align-items: center; justify-content: center; gap: 6px;
      height: 34px; border-radius: 999px;
      background: rgba(255,255,255,.08); border: 1px solid rgba(238,211,34,.2);
      padding: 0 14px; margin: 0 auto; width: calc(100% - 8px); max-width: 100%;
    }}
    .url-pill span {{
      font-size: 12px; color: #d4d4d8; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }}
    .tool-row {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 6px;
    }}
    .tool {{
      width: 44px; height: 36px; border: none; background: transparent;
      color: {_KRX_CYAN}; font-size: 20px; line-height: 1;
      display: flex; align-items: center; justify-content: center;
      border-radius: 8px;
    }}
    .tool.disabled {{ color: #52525b; opacity: .45; }}
    .tool.tabs {{ font-size: 17px; position: relative; }}
    .tool.tabs em {{
      font-style: normal; font-size: 9px; font-weight: 700;
      position: absolute; top: 4px; right: 8px; color: {_KRX_GOLD};
    }}
    .k-mark-sm {{
      width: 18px; height: 18px; border-radius: 5px; object-fit: cover; flex-shrink: 0;
    }}
    """


def _shell_css_android() -> str:
    return f"""
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 100%; height: 100%; overflow: hidden;
      background: #0b0b12; color: #e4e4e7;
      font-family: "Segoe UI", Roboto, system-ui, sans-serif;
      -webkit-user-select: none; user-select: none;
    }}
    .chrome-top {{
      width: 100%; height: 100%; display: flex; align-items: center;
      padding: 8px 10px; background: #0b0b12;
      border-bottom: 1px solid rgba(124,58,237,.35);
    }}
    .omnibox {{
      flex: 1; height: 40px; border-radius: 999px;
      background: #1a1a28; border: 1px solid rgba(34,211,238,.25);
      display: flex; align-items: center; gap: 8px; padding: 0 12px;
    }}
    .omnibox .url {{
      flex: 1; font-size: 13px; color: #cbd5e1;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .tab-badge {{
      min-width: 18px; height: 18px; border-radius: 4px;
      border: 1.5px solid {_KRX_CYAN}; color: {_KRX_CYAN};
      font-size: 10px; font-weight: 700;
      display: flex; align-items: center; justify-content: center;
    }}
    .menu-dot {{
      color: #a1a1aa; font-size: 18px; line-height: 1; padding-left: 2px;
    }}
    .k-mark-sm {{
      width: 20px; height: 20px; border-radius: 5px; object-fit: cover; flex-shrink: 0;
    }}
    .chrome-bottom {{
      width: 100%; height: 100%; display: flex; align-items: center;
      justify-content: space-around; padding: 0 8px;
      background: #12121a; border-top: 1px solid rgba(124,58,237,.3);
    }}
    .nav-btn {{
      width: 48px; height: 40px; display: flex; align-items: center;
      justify-content: center; color: {_KRX_CYAN}; font-size: 20px;
      border-radius: 8px;
    }}
    .nav-btn.off {{ color: #52525b; opacity: .4; }}
    .k-badge {{
      width: 20px; height: 20px; border-radius: 5px;
      background: linear-gradient(145deg, {_KRX_GOLD}, {_KRX_VIOLET});
      color: #0b0b12; font-weight: 800; font-size: 11px;
      display: flex; align-items: center; justify-content: center;
    }}
    """


def _krexion_mark_html(platform: str, size: int = 20, css_class: str = "k-mark-sm") -> str:
    """Official Krexion browser emblem inline in chrome bars."""
    try:
        from krexion_window_icon import browser_icon_data_uri

        uri = browser_icon_data_uri(platform, size=max(40, size * 2))
        if uri:
            return (
                f'<img class="{css_class}" src="{uri}" alt="Krexion" '
                f'width="{size}" height="{size}" />'
            )
    except Exception:
        pass
    return '<div class="k-badge">K</div>'


def _top_html_ios(profile_label: str, slot: int, platform: str = "ios") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_ios()}</style></head>
<body><div class="ios-top">Krexion · #{slot}</div></body></html>"""


def _top_html_android(profile_label: str, slot: int, platform: str = "android") -> str:
    safe = _esc((profile_label or "Profile")[:48])
    mark = _krexion_mark_html(platform, size=20)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_android()}</style></head>
<body><div class="chrome-top"><div class="omnibox">
  {mark}
  <span class="url">{safe}</span>
  <span class="tab-badge">{slot}</span>
  <span class="menu-dot">⋮</span>
</div></div></body></html>"""


def _bottom_html_ios(profile_label: str, slot: int, platform: str = "ios") -> str:
    safe = _esc((profile_label or "Profile")[:40])
    mark = _krexion_mark_html(platform, size=18)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_ios()}</style></head>
<body><div class="safari-bottom">
  <div class="url-pill">{mark}<span>⟡ {safe}</span></div>
  <div class="tool-row">
    <button class="tool" type="button" aria-label="Back">‹</button>
    <button class="tool disabled" type="button" aria-label="Forward">›</button>
    <button class="tool" type="button" aria-label="Share">↗</button>
    <button class="tool" type="button" aria-label="Bookmarks">☆</button>
    <button class="tool tabs" type="button" aria-label="Tabs">▢<em>{slot}</em></button>
  </div>
</div></body></html>"""


def _bottom_html_android(profile_label: str, slot: int, platform: str = "android") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_shell_css_android()}</style></head>
<body><div class="chrome-bottom">
  <div class="nav-btn" aria-label="Home">⌂</div>
  <div class="nav-btn" aria-label="Back">‹</div>
  <div class="nav-btn off" aria-label="Forward">›</div>
  <div class="nav-btn" aria-label="Share">↗</div>
  <div class="nav-btn" aria-label="Menu">⋮</div>
</div></body></html>"""


def _top_html(profile_label: str, slot: int, platform: str = "") -> str:
    plat = (platform or "").strip().lower()
    if plat in ("ios", "ipados"):
        return _top_html_ios(profile_label, slot, platform=plat)
    return _top_html_android(profile_label, slot, platform=plat or "android")


def _bottom_html(platform: str, profile_label: str = "", slot: int = 1) -> str:
    plat = (platform or "").strip().lower()
    if plat in ("ios", "ipados"):
        return _bottom_html_ios(profile_label, slot, platform=plat)
    return _bottom_html_android(profile_label, slot, platform=plat or "android")


def _host_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "krexion_mobile_shell_host.py")


def _start_shell_process(
    session_key: str,
    layout: MobileShellLayout,
    profile_label: str,
    profile_slot: int,
    origin_x: int,
    origin_y: int,
    *,
    home_url: str = "https://www.google.com/",
    interactive: bool = True,
) -> Optional[subprocess.Popen]:
    if not _IS_WINDOWS:
        return None
    try:
        plat = str(layout.platform or "android")
        if interactive:
            try:
                from krexion_mobile_shell_interactive import (
                    interactive_bottom_html,
                    interactive_top_html,
                )

                top_html = interactive_top_html(profile_label, profile_slot, plat)
                bottom_html = interactive_bottom_html(plat, profile_label, profile_slot)
            except Exception:
                interactive = False
                top_html = _top_html(profile_label, profile_slot, platform=plat)
                bottom_html = _bottom_html(plat, profile_label=profile_label, slot=profile_slot)
        else:
            top_html = _top_html(profile_label, profile_slot, platform=plat)
            bottom_html = _bottom_html(plat, profile_label=profile_label, slot=profile_slot)
        cfg = {
            "session_key": session_key,
            "slot": int(profile_slot),
            "platform": layout.platform,
            "outer_w": layout.outer_w,
            "top_h": layout.top_h,
            "bottom_h": layout.bottom_h,
            "viewport_h": layout.viewport_h,
            "bezel": layout.bezel,
            "x": int(origin_x),
            "y": int(origin_y),
            "top_html": top_html,
            "bottom_html": bottom_html,
            "show_bottom": layout.bottom_h > 0,
            "handles": {"top": 0, "bottom": 0},
            "home_url": str(home_url or "https://www.google.com/")[:512],
            "profile_label": str(profile_label or "")[:60],
            "interactive": bool(interactive),
        }
        fd, path = tempfile.mkstemp(prefix="krx_shell_", suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        proc = subprocess.Popen(
            [sys.executable, _host_script_path(), path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with _LOCK:
            _ACTIVE[session_key] = {
                "proc": proc,
                "cfg_path": path,
                "layout": layout,
                "origin_x": origin_x,
                "origin_y": origin_y,
                "interactive": bool(interactive),
            }
        return proc
    except Exception as exc:
        logger.debug(f"[mobile-shell] chrome process skipped: {exc}")
        return None


def is_mobile_shell_alive(session_key: str) -> bool:
    """True while the pywebview shell subprocess is still running."""
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
    if not rec:
        return False
    proc = rec.get("proc")
    if proc is None:
        return False
    try:
        return proc.poll() is None
    except Exception:
        return False


def stop_mobile_shell(session_key: str) -> None:
    with _LOCK:
        rec = _ACTIVE.pop(str(session_key or ""), None)
    if not rec:
        return
    proc = rec.get("proc")
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    try:
        os.remove(str(rec.get("cfg_path") or ""))
    except Exception:
        pass


def _center_origin(layout: MobileShellLayout) -> Tuple[int, int]:
    try:
        import ctypes

        sw = int(ctypes.windll.user32.GetSystemMetrics(0))
        sh = int(ctypes.windll.user32.GetSystemMetrics(1))
        x = max(0, (sw - layout.outer_w) // 2)
        y = max(0, (sh - layout.outer_h) // 2)
        return x, y
    except Exception:
        return 120, 80


def _strip_native_caption(hwnd: int) -> None:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(
            hwnd,
            GWL_STYLE,
            style & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_SYSMENU,
        )
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # SWP_NOMOVE|SWP_NOSIZE|FRAME changed
    except Exception:
        pass


def _remove_menu_bar(hwnd: int) -> None:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hmenu = user32.GetMenu(hwnd)
        if hmenu:
            user32.SetMenu(hwnd, 0)
            user32.DrawMenuBar(hwnd)
    except Exception:
        pass


def _is_engine_content_hwnd(hwnd: int, *, webkit: bool) -> bool:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindowVisible(hwnd):
            return False
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value or ""
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        cname = (cls.value or "").lower()
        if title.strip().lower() == "playwright":
            return False
        if webkit:
            return (
                "[webkit]" in title.lower()
                or "safari" in title.lower()
                or "webkit" in cname
                or "minibrowser" in cname
            )
        return "chrome" in cname or title.startswith("Krexion")
    except Exception:
        return False


def _set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    try:
        import ctypes

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE
        )
    except Exception:
        pass


def _load_shell_handles(session_key: str) -> Dict[str, int]:
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
    if not rec:
        return {}
    path = str(rec.get("cfg_path") or "")
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        h = data.get("handles") or {}
        return {"top": int(h.get("top") or 0), "bottom": int(h.get("bottom") or 0)}
    except Exception:
        return {}


def _shell_apply_loop(
    session_key: str,
    seed_pids: List[int],
    parent_pid: Optional[int],
    layout: MobileShellLayout,
    profile_label: str,
    profile_slot: int,
    deadline_s: float,
    interval_s: float,
    *,
    webkit: bool,
    home_url: str = "https://www.google.com/",
) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        from krexion_window_icon import (
            brand_single_hwnd_krexion,
            collect_profile_process_tree,
            find_pids_by_window_title_substrings,
            find_webkit_browser_pids,
        )

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        GetWindowThreadProcessId.restype = wintypes.DWORD

        ox, oy = _center_origin(layout)
        _start_shell_process(
            session_key,
            layout,
            profile_label,
            profile_slot,
            ox,
            oy,
            home_url=home_url,
            interactive=True,
        )

        deadline = time.time() + deadline_s
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set |= collect_profile_process_tree(int(parent_pid))
        if webkit:
            pid_set |= find_webkit_browser_pids(parent_pid)
            pid_set |= find_pids_by_window_title_substrings("[WebKit]", "Safari")

        content_x = ox + layout.bezel
        content_y = oy + layout.top_h + layout.bezel
        last_layout = (content_x, content_y, layout.content_w, layout.content_h)

        while time.time() < deadline:
            if parent_pid:
                pid_set |= collect_profile_process_tree(int(parent_pid))
            if webkit:
                pid_set |= find_webkit_browser_pids(parent_pid)

            engine_hwnds: List[int] = []

            def _cb(hwnd, _lparam):
                try:
                    win_pid = wintypes.DWORD(0)
                    GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    if win_pid.value not in pid_set:
                        return True
                    if _is_engine_content_hwnd(int(hwnd), webkit=webkit):
                        engine_hwnds.append(int(hwnd))
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(_cb), 0)

            for hwnd in engine_hwnds:
                _remove_menu_bar(hwnd)
                _strip_native_caption(hwnd)
                _set_window_pos(
                    hwnd,
                    content_x,
                    content_y,
                    layout.content_w,
                    layout.content_h,
                )
                user32.SetWindowTextW(hwnd, f"Krexion Orbit ({profile_slot})")
                try:
                    brand_single_hwnd_krexion(
                        hwnd,
                        profile_slot=profile_slot,
                        profile_label=profile_label,
                        platform=layout.platform,
                    )
                except Exception:
                    pass

            handles = _load_shell_handles(session_key)
            top_hwnd = int(handles.get("top") or 0)
            bottom_hwnd = int(handles.get("bottom") or 0)
            if top_hwnd:
                _set_window_pos(top_hwnd, ox, oy, layout.outer_w, layout.top_h)
            if bottom_hwnd and layout.bottom_h > 0:
                _set_window_pos(
                    bottom_hwnd,
                    ox,
                    oy + layout.top_h + layout.bezel * 2 + layout.content_h,
                    layout.outer_w,
                    layout.bottom_h,
                )

            if parent_pid:
                try:
                    from krexion_window_icon import is_process_alive

                    if not is_process_alive(int(parent_pid)):
                        return
                except Exception:
                    pass

            time.sleep(interval_s)
    except Exception as exc:
        logger.debug(f"[mobile-shell] loop crashed: {exc}")
    finally:
        stop_mobile_shell(session_key)


def apply_krexion_mobile_shell(
    pids: list,
    *,
    session_key: str,
    parent_pid: Optional[int] = None,
    platform: str = "android",
    viewport_width: int = 393,
    viewport_height: int = 852,
    profile_label: str = "",
    profile_slot: int = 1,
    poll_seconds: float = 120.0,
    poll_interval: float = 0.55,
    webkit: bool = False,
    home_url: str = "https://www.google.com/",
) -> Optional[threading.Thread]:
    """Start Krexion Option-B mobile chrome around a headed profile engine."""
    if not _IS_WINDOWS:
        return None
    try:
        layout = compute_mobile_shell_layout(platform, viewport_width, viewport_height)
        _clean = sorted({int(p) for p in (pids or []) if p})
        if not _clean and not parent_pid:
            return None
        t = threading.Thread(
            target=_shell_apply_loop,
            args=(
                str(session_key),
                _clean,
                parent_pid,
                layout,
                str(profile_label or "")[:60],
                int(profile_slot or 1),
                float(poll_seconds),
                float(poll_interval),
            ),
            kwargs={"webkit": bool(webkit), "home_url": str(home_url or "")[:512]},
            daemon=True,
            name=f"KrexionMobileShell-{profile_slot}-{session_key[:8]}",
        )
        t.start()
        return t
    except Exception as exc:
        logger.debug(f"[mobile-shell] apply failed: {exc}")
        return None


def get_shell_cfg_path(session_key: str) -> str:
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
    if not rec:
        return ""
    return str(rec.get("cfg_path") or "")


def should_use_mobile_shell(profile_os: str, is_mobile: bool) -> bool:
    if not _IS_WINDOWS or not is_mobile:
        return False
    plat = (profile_os or "").strip().lower()
    return plat in ("ios", "ipados", "android")
