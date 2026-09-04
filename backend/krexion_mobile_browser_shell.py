"""
Krexion Mobile Browser Shell
============================
Headed mobile profiles get Krexion-branded chrome with platform-native UX:
  • iOS / iPadOS — Safari-like bottom toolbar + URL pill
  • Android — Chrome-like top omnibox + bottom nav

Playwright engine runs in the content area; pywebview renders chrome only.
Shell success requires engine HWND embedded (not process-only).
When strict_mobile_shell is ON, launch must abort if chrome fails.
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
    frame_scale: float = 1.0

    @property
    def content_w(self) -> int:
        return self.viewport_w

    @property
    def content_h(self) -> int:
        return self.viewport_h

    @property
    def display_outer_w(self) -> int:
        fs = max(0.55, min(1.5, float(self.frame_scale or 1.0)))
        return max(280, int(round(self.outer_w * fs)))

    @property
    def display_outer_h(self) -> int:
        fs = max(0.55, min(1.5, float(self.frame_scale or 1.0)))
        return max(400, int(round(self.outer_h * fs)))

    def with_frame_scale(self, scale: float) -> "MobileShellLayout":
        fs = max(0.55, min(1.5, float(scale or 1.0)))
        return MobileShellLayout(
            platform=self.platform,
            viewport_w=self.viewport_w,
            viewport_h=self.viewport_h,
            top_h=self.top_h,
            bottom_h=self.bottom_h,
            bezel=self.bezel,
            outer_w=self.outer_w,
            outer_h=self.outer_h,
            frame_scale=fs,
        )


def compute_fit_frame_scale(layout: MobileShellLayout) -> float:
    """Scale whole phone frame to fit monitor; Playwright viewport stays 1:1."""
    try:
        import ctypes

        sw = int(ctypes.windll.user32.GetSystemMetrics(0))
        sh = int(ctypes.windll.user32.GetSystemMetrics(1))
    except Exception:
        sw, sh = 1920, 1080
    margin_x, margin_y = 24, 96
    avail_w = max(280, sw - margin_x * 2)
    avail_h = max(480, sh - margin_y * 2)
    scale = min(avail_w / max(1, layout.outer_w), avail_h / max(1, layout.outer_h), 1.0)
    return max(0.55, round(min(scale, 0.92), 3))


def adjust_shell_frame_scale(
    session_key: str,
    mode: str,
    *,
    fit_by_default: bool = True,
) -> float:
    """
    Resize visual shell frame without changing Playwright device viewport.
    mode: fit | actual | in | out
    """
    key = str(session_key or "")
    with _LOCK:
        rec = _ACTIVE.get(key)
    if not rec:
        return 1.0
    layout: MobileShellLayout = rec.get("layout")
    if not isinstance(layout, MobileShellLayout):
        return 1.0
    cur = float(layout.frame_scale or 1.0)
    m = (mode or "").strip().lower()
    if m in ("fit", "fit_screen"):
        nxt = compute_fit_frame_scale(layout)
    elif m in ("actual", "actual_size", "100"):
        nxt = 1.0
    elif m in ("in", "zoom_in", "+"):
        nxt = cur * 1.12
    elif m in ("out", "zoom_out", "-"):
        nxt = cur / 1.12
    else:
        nxt = compute_fit_frame_scale(layout) if fit_by_default else cur
    nxt = max(0.55, min(1.5, round(nxt, 3)))
    new_layout = layout.with_frame_scale(nxt)
    ox, oy = _center_origin(new_layout)
    with _LOCK:
        rec = _ACTIVE.get(key)
        if rec:
            rec["layout"] = new_layout
            rec["origin_x"] = ox
            rec["origin_y"] = oy
    return nxt


def get_shell_frame_scale(session_key: str) -> float:
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
    if not rec:
        return 1.0
    layout = rec.get("layout")
    if isinstance(layout, MobileShellLayout):
        return float(layout.frame_scale or 1.0)
    return 1.0


def compute_mobile_shell_layout(
    platform: str,
    viewport_w: int,
    viewport_h: int,
) -> MobileShellLayout:
    plat = (platform or "android").strip().lower()
    vw = max(320, min(1200, int(viewport_w or 393)))
    vh = max(568, min(1600, int(viewport_h or 844)))
    if plat in ("ios", "ipados"):
        top_h, bottom_h, bezel = 28, 82, 0
    else:
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
        frame_scale=1.0,
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
        app_dir = os.path.dirname(os.path.abspath(__file__))
        err_log = os.path.join(
            tempfile.gettempdir(),
            f"krx_shell_{str(session_key)[:8]}_{int(profile_slot)}.log",
        )
        with open(err_log, "wb") as errfh:
            # Prefer runnable .py path (native keeps krexion_mobile_shell_host.py).
            host_py = _host_script_path()
            if os.path.isfile(host_py):
                cmd = [sys.executable, host_py, path]
            else:
                cmd = [sys.executable, "-m", "krexion_mobile_shell_host", path]
            proc = subprocess.Popen(
                cmd,
                cwd=app_dir,
                stdout=subprocess.DEVNULL,
                stderr=errfh,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        time.sleep(0.85)
        if proc.poll() is not None:
            err_tail = ""
            try:
                with open(err_log, encoding="utf-8", errors="replace") as ef:
                    err_tail = ef.read()[-1500:]
            except Exception:
                pass
            logger.warning(
                f"[mobile-shell] host exited rc={proc.returncode} session={str(session_key)[:8]} "
                f"{err_tail[:400]}"
            )
            if not interactive:
                return None
            # Retry static chrome (no interactive IPC) — still shows Krexion design.
            plat = str(layout.platform or "android")
            cfg["interactive"] = False
            cfg["top_html"] = _top_html(profile_label, profile_slot, platform=plat)
            cfg["bottom_html"] = _bottom_html(plat, profile_label=profile_label, slot=profile_slot)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            with open(err_log, "wb") as errfh:
                host_py = _host_script_path()
                if os.path.isfile(host_py):
                    cmd = [sys.executable, host_py, path]
                else:
                    cmd = [sys.executable, "-m", "krexion_mobile_shell_host", path]
                proc = subprocess.Popen(
                    cmd,
                    cwd=app_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=errfh,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            time.sleep(0.85)
            if proc.poll() is not None:
                try:
                    with open(err_log, encoding="utf-8", errors="replace") as ef:
                        err_tail = ef.read()[-1500:]
                except Exception:
                    err_tail = ""
                logger.warning(
                    f"[mobile-shell] static chrome also failed rc={proc.returncode} "
                    f"{err_tail[:400]}"
                )
                return None
        with _LOCK:
            _ACTIVE[session_key] = {
                "proc": proc,
                "cfg_path": path,
                "layout": layout,
                "origin_x": origin_x,
                "origin_y": origin_y,
                "interactive": bool(interactive) and bool(cfg.get("interactive")),
                "err_log": err_log,
                "engine_embedded": False,
                "engine_hwnd": 0,
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


def is_mobile_shell_embedded(session_key: str) -> bool:
    """True only after an engine HWND was positioned inside the phone frame."""
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
    if not rec:
        return False
    if not is_mobile_shell_alive(session_key):
        return False
    return bool(rec.get("engine_embedded"))


def mark_mobile_shell_embedded(session_key: str, *, hwnd: int = 0) -> None:
    with _LOCK:
        rec = _ACTIVE.get(str(session_key or ""))
        if not rec:
            return
        rec["engine_embedded"] = True
        if hwnd:
            rec["engine_hwnd"] = int(hwnd)
        rec["embedded_at"] = time.time()


def wait_for_mobile_shell(session_key: str, *, timeout_sec: float = 30.0) -> bool:
    """Wait until pywebview chrome subprocess is registered and alive."""
    deadline = time.time() + max(2.0, float(timeout_sec or 30.0))
    while time.time() < deadline:
        if is_mobile_shell_alive(session_key):
            return True
        time.sleep(0.2)
    return is_mobile_shell_alive(session_key)


def wait_for_mobile_shell_embedded(
    session_key: str,
    *,
    timeout_sec: float = 25.0,
) -> bool:
    """Wait until engine HWND is framed inside Krexion phone chrome."""
    deadline = time.time() + max(3.0, float(timeout_sec or 25.0))
    while time.time() < deadline:
        if is_mobile_shell_embedded(session_key):
            return True
        if not is_mobile_shell_alive(session_key):
            # Process died — no point waiting for embed
            return False
        time.sleep(0.25)
    return is_mobile_shell_embedded(session_key)


def preflight_mobile_shell() -> Dict[str, Any]:
    """Check whether Windows + pywebview can host Krexion phone chrome."""
    out: Dict[str, Any] = {
        "ok": False,
        "windows": bool(_IS_WINDOWS),
        "webview": False,
        "error": "",
    }
    if not _IS_WINDOWS:
        out["error"] = "Mobile shell requires Windows (pywebview phone frame)."
        return out
    try:
        import webview  # noqa: F401

        out["webview"] = True
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"pywebview import failed: {exc}"[:200]
    return out


def _center_origin(layout: MobileShellLayout) -> Tuple[int, int]:
    try:
        import ctypes

        sw = int(ctypes.windll.user32.GetSystemMetrics(0))
        sh = int(ctypes.windll.user32.GetSystemMetrics(1))
        x = max(0, (sw - layout.display_outer_w) // 2)
        y = max(0, (sh - layout.display_outer_h) // 2)
        return x, y
    except Exception:
        return 120, 80


def stop_mobile_shell(session_key: str) -> None:
    key = str(session_key or "")
    with _LOCK:
        rec = _ACTIVE.pop(key, None)
    if rec:
        stop_ev = rec.get("stop_event")
        if stop_ev is not None:
            try:
                stop_ev.set()
            except Exception:
                pass
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


def _win_dpi_scale() -> float:
    """Windows display scale (1.0 = 96 DPI) for sizing engine HWNDs."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        dpi = float(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))
        user32.ReleaseDC(0, hdc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


def _engine_window_size(layout: MobileShellLayout) -> Tuple[int, int]:
    """Physical pixel size for Playwright engine HWND (match CSS viewport, not DPI²)."""
    fs = max(0.55, min(1.5, float(layout.frame_scale or 1.0)))
    return (
        max(280, int(round(layout.content_w * fs))),
        max(480, int(round(layout.content_h * fs))),
    )


def _shell_content_origin(
    layout: MobileShellLayout,
    origin_xy: Tuple[int, int],
) -> Tuple[int, int]:
    """Content area origin inside the phone frame (logical px, no extra DPI multiply)."""
    ox, oy = origin_xy
    fs = max(0.55, min(1.5, float(layout.frame_scale or 1.0)))
    content_x = int(round((ox + layout.bezel) * fs))
    content_y = int(round((oy + layout.top_h * fs + layout.bezel) * fs))
    return content_x, content_y


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
    """Match headed engine HWND — minimized OK (IsWindow), Chromium class included.

    v2.7.106: previously required IsWindowVisible which missed MiniBrowser /
    Chromium windows during first paint → embed never marked → Strict abort.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value or ""
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        cname = (cls.value or "").lower()
        tlow = title.strip().lower()
        if tlow == "playwright":
            return False
        if webkit:
            return (
                "[webkit]" in tlow
                or "safari" in tlow
                or "krexion orbit" in tlow
                or "krexion" in tlow
                or "webkit" in cname
                or "minibrowser" in cname
            )
        return (
            "chrome" in cname
            or "chromium" in cname
            or title.startswith("Krexion")
            or "krexion orbit" in tlow
        )
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
    origin_xy: Optional[Tuple[int, int]] = None,
    shell_already_started: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        from krexion_window_icon import (
            brand_single_hwnd_krexion,
            collect_profile_process_tree,
            find_chromium_pids_by_cmdline_substrings,
            find_pids_by_window_title_substrings,
            find_webkit_browser_pids,
            hide_hwnd_from_taskbar,
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

        ox, oy = origin_xy if origin_xy else _center_origin(layout)
        with _LOCK:
            rec = _ACTIVE.get(str(session_key or ""))
            if rec:
                ox = int(rec.get("origin_x") or ox)
                oy = int(rec.get("origin_y") or oy)
                lay = rec.get("layout")
                if isinstance(lay, MobileShellLayout):
                    layout = lay
        if not shell_already_started:
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

        deadline = time.time() + max(float(deadline_s or 120.0), 86400.0)
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set |= collect_profile_process_tree(int(parent_pid))
        if webkit:
            pid_set |= find_webkit_browser_pids(parent_pid)
            pid_set |= find_pids_by_window_title_substrings(
                "[WebKit]", "Safari", "Krexion Orbit"
            )
        else:
            pid_set |= find_chromium_pids_by_cmdline_substrings("--window-name=Krexion")

        dpi = _win_dpi_scale()
        fs = max(0.55, min(1.5, float(layout.frame_scale or 1.0)))
        content_x, content_y = _shell_content_origin(layout, (ox, oy))
        eng_w, eng_h = _engine_window_size(layout)
        _positioned: Set[int] = set()
        _shell_branded = False
        _stable_embed_ticks = 0

        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            if parent_pid:
                pid_set |= collect_profile_process_tree(int(parent_pid))
            if webkit:
                pid_set |= find_webkit_browser_pids(parent_pid)
                # Refresh every tick — MiniBrowser often appears after first paint
                pid_set |= find_pids_by_window_title_substrings(
                    "[WebKit]", "Safari", "Krexion Orbit"
                )
            else:
                pid_set |= find_chromium_pids_by_cmdline_substrings("--window-name=Krexion")

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
                if int(hwnd) not in _positioned:
                    _set_window_pos(
                        hwnd,
                        content_x,
                        content_y,
                        eng_w,
                        eng_h,
                    )
                    # One-time show — never every tick (taskbar flicker).
                    user32.ShowWindow(int(hwnd), 8)  # SW_SHOWNA
                    user32.SetWindowTextW(hwnd, f"Krexion Orbit ({profile_slot})")
                    _positioned.add(int(hwnd))
                    mark_mobile_shell_embedded(session_key, hwnd=int(hwnd))
                else:
                    _set_window_pos(
                        hwnd,
                        content_x,
                        content_y,
                        eng_w,
                        eng_h,
                    )
                try:
                    hide_hwnd_from_taskbar(int(hwnd))
                except Exception:
                    pass

            embedded = set(engine_hwnds)
            if embedded:
                _stable_embed_ticks += 1
            else:
                _stable_embed_ticks = 0

            def _hide_stray_cb(hwnd, _lparam):
                try:
                    win_pid = wintypes.DWORD(0)
                    GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    if win_pid.value not in pid_set:
                        return True
                    if int(hwnd) in embedded:
                        return True
                    title_buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title_buf, 512)
                    title = (title_buf.value or "").strip()
                    if title.lower() == "playwright":
                        user32.ShowWindow(int(hwnd), 0)
                        return True
                    if _is_engine_content_hwnd(int(hwnd), webkit=webkit):
                        user32.ShowWindow(int(hwnd), 0)
                except Exception:
                    pass
                return True

            # Only hide strays after stable embed — avoids killing the real
            # content HWND before the first successful frame pass.
            if embedded and _stable_embed_ticks >= 2:
                user32.EnumWindows(EnumWindowsProc(_hide_stray_cb), 0)

            handles = _load_shell_handles(session_key)
            top_hwnd = int(handles.get("top") or 0)
            bottom_hwnd = int(handles.get("bottom") or 0)
            outer_w = int(round(layout.outer_w * dpi * fs))
            top_h = int(round(layout.top_h * dpi * fs))
            bottom_h = int(round(layout.bottom_h * dpi * fs))
            origin_x = int(round(ox * dpi))
            origin_y = int(round(oy * dpi))
            if top_hwnd:
                _set_window_pos(top_hwnd, origin_x, origin_y, outer_w, top_h)
                if not _shell_branded:
                    try:
                        brand_single_hwnd_krexion(
                            top_hwnd,
                            profile_slot=profile_slot,
                            profile_label=profile_label,
                            platform=layout.platform,
                        )
                        _shell_branded = True
                    except Exception:
                        pass
            if bottom_hwnd and layout.bottom_h > 0:
                _set_window_pos(
                    bottom_hwnd,
                    origin_x,
                    origin_y + top_h + int(round(layout.bezel * 2 * dpi * fs)) + eng_h,
                    outer_w,
                    bottom_h,
                )
                try:
                    hide_hwnd_from_taskbar(int(bottom_hwnd))
                except Exception:
                    pass

            if parent_pid:
                try:
                    from krexion_window_icon import is_process_alive

                    if not is_process_alive(int(parent_pid)):
                        break
                except Exception:
                    pass

            time.sleep(interval_s)
    except Exception as exc:
        logger.warning(f"[mobile-shell] loop crashed (chrome kept alive): {exc}")
    finally:
        # Only tear down chrome when intentionally stopped or browser died.
        # A transient EnumWindows exception must NOT kill the phone UI.
        intentional = stop_event is not None and stop_event.is_set()
        parent_dead = False
        if parent_pid:
            try:
                from krexion_window_icon import is_process_alive

                parent_dead = not is_process_alive(int(parent_pid))
            except Exception:
                parent_dead = False
        if intentional or parent_dead:
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
        key = str(session_key or "")
        stop_mobile_shell(key)
        stop_ev = threading.Event()
        layout = compute_mobile_shell_layout(platform, viewport_width, viewport_height)
        layout = layout.with_frame_scale(compute_fit_frame_scale(layout))
        _clean = sorted({int(p) for p in (pids or []) if p})
        if not _clean and not parent_pid:
            return None
        ox, oy = _center_origin(layout)
        proc = None
        for _attempt in range(2):
            if _attempt:
                stop_mobile_shell(key)
                stop_ev = threading.Event()
            proc = _start_shell_process(
                key,
                layout,
                str(profile_label or "")[:60],
                int(profile_slot or 1),
                ox,
                oy,
                home_url=str(home_url or "https://www.google.com/")[:512],
                interactive=True,
            )
            if proc is not None and proc.poll() is None:
                break
            time.sleep(0.35)
        if proc is None or proc.poll() is not None:
            logger.warning(
                f"[mobile-shell] chrome subprocess failed to start session={str(session_key)[:8]}"
            )
            return None
        t = threading.Thread(
            target=_shell_apply_loop,
            args=(
                key,
                _clean,
                parent_pid,
                layout,
                str(profile_label or "")[:60],
                int(profile_slot or 1),
                float(max(poll_seconds or 120.0, 86400.0)),
                float(poll_interval),
            ),
            kwargs={
                "webkit": bool(webkit),
                "home_url": str(home_url or "")[:512],
                "origin_xy": (ox, oy),
                "shell_already_started": True,
                "stop_event": stop_ev,
            },
            daemon=True,
            name=f"KrexionMobileShell-{profile_slot}-{key[:8]}",
        )
        t.start()
        with _LOCK:
            rec = _ACTIVE.get(key)
            if rec is not None:
                rec["stop_event"] = stop_ev
                rec.setdefault("engine_embedded", False)
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
    if plat not in ("ios", "ipados", "android"):
        plat = "android"
    return plat in ("ios", "ipados", "android")


def force_discover_and_mark_embedded(
    session_key: str,
    *,
    parent_pid: Optional[int] = None,
    seed_pids: Optional[List[int]] = None,
    webkit: bool = False,
    profile_slot: int = 1,
) -> bool:
    """One-shot EnumWindows + SetWindowPos + mark. Used before Strict abort.

    Returns True if engine HWND found and marked embedded while shell is alive.
    """
    if not _IS_WINDOWS:
        return False
    key = str(session_key or "")
    if not is_mobile_shell_alive(key):
        return False
    if is_mobile_shell_embedded(key):
        return True
    try:
        import ctypes
        from ctypes import wintypes

        from krexion_window_icon import (
            collect_profile_process_tree,
            find_chromium_pids_by_cmdline_substrings,
            find_pids_by_window_title_substrings,
            find_webkit_browser_pids,
            hide_hwnd_from_taskbar,
        )

        with _LOCK:
            rec = _ACTIVE.get(key)
        if not rec:
            return False
        layout = rec.get("layout")
        if not isinstance(layout, MobileShellLayout):
            return False
        ox = int(rec.get("origin_x") or 120)
        oy = int(rec.get("origin_y") or 80)
        content_x, content_y = _shell_content_origin(layout, (ox, oy))
        eng_w, eng_h = _engine_window_size(layout)

        pid_set: Set[int] = {int(p) for p in (seed_pids or []) if p}
        if parent_pid:
            pid_set |= collect_profile_process_tree(int(parent_pid))
        if webkit:
            pid_set |= find_webkit_browser_pids(parent_pid)
            pid_set |= find_pids_by_window_title_substrings(
                "[WebKit]", "Safari", "Krexion Orbit"
            )
        else:
            pid_set |= find_chromium_pids_by_cmdline_substrings("--window-name=Krexion")
        if not pid_set:
            return False

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
        found: List[int] = []

        def _cb(hwnd, _lparam):
            try:
                win_pid = wintypes.DWORD(0)
                GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value not in pid_set:
                    return True
                if _is_engine_content_hwnd(int(hwnd), webkit=webkit):
                    found.append(int(hwnd))
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        if not found:
            return False
        hwnd = found[0]
        _remove_menu_bar(hwnd)
        _strip_native_caption(hwnd)
        _set_window_pos(hwnd, content_x, content_y, eng_w, eng_h)
        user32.ShowWindow(int(hwnd), 8)
        try:
            user32.SetWindowTextW(hwnd, f"Krexion Orbit ({int(profile_slot or 1)})")
        except Exception:
            pass
        try:
            hide_hwnd_from_taskbar(int(hwnd))
        except Exception:
            pass
        mark_mobile_shell_embedded(key, hwnd=int(hwnd))
        return is_mobile_shell_embedded(key)
    except Exception as exc:
        logger.debug(f"[mobile-shell] force discover failed: {exc}")
        return False


def mobile_shell_status(session_key: str) -> Dict[str, Any]:
    """Snapshot for launcher / UI honesty."""
    key = str(session_key or "")
    alive = is_mobile_shell_alive(key)
    embedded = is_mobile_shell_embedded(key)
    return {
        "alive": alive,
        "embedded": embedded,
        "ok": bool(alive and embedded),
        "windows": bool(_IS_WINDOWS),
    }
