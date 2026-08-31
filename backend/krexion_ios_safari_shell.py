"""
iOS Safari shell polish (Windows WebKit MiniBrowser)
======================================================
Headed Playwright WebKit on Windows shows a developer MiniBrowser titled
``[WebKit]`` with File/View/History/Develop menus. iOS Browser Profiles
should feel like real iPhone Safari — no WebKit branding exposed to users.

Approach (best-effort, never breaks launch)
-------------------------------------------
1. Retitle window → ``Safari`` (taskbar + title bar).
2. Remove Win32 menu bar (File/View/History/Develop/Help).
3. Hide MiniBrowser toolbar/address child HWNDs when detectable.
4. Resize + center to iPhone viewport (+ minimal chrome padding).

Taskbar icon + AppUserModelID are handled by ``krexion_window_icon`` (numbered
Krexion browser badge). This module only polishes in-window Safari UX.

Runs in a background poll loop (~2 min) because WebKit may reset chrome
after first paint — same pattern as ``krexion_window_icon``.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import List, Optional, Set, Tuple

logger = logging.getLogger("krexion.ios_safari_shell")

_IS_WINDOWS = sys.platform.startswith("win")
_SAFARI_DISPLAY = "Safari"
_SHELL_HWNDS: Set[int] = set()
_LOCK = threading.Lock()


def _walk_descendants(parent_pid: int) -> Set[int]:
    out: Set[int] = set()
    try:
        import psutil as _psu

        try:
            proc = _psu.Process(parent_pid)
        except Exception:
            return out
        for child in proc.children(recursive=True):
            try:
                out.add(int(child.pid))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _window_title(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value or ""
    except Exception:
        return ""


def _class_name(hwnd: int) -> str:
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value or ""
    except Exception:
        return ""


def _is_webkit_browser_hwnd(hwnd: int) -> bool:
    title = _window_title(hwnd)
    if "[WebKit]" in title or title.strip() == "Safari":
        return True
    cls = _class_name(hwnd).lower()
    return "webkit" in cls or "minibrowser" in cls


def _phone_window_size(viewport_w: int, viewport_h: int) -> Tuple[int, int]:
    vw = max(320, min(520, int(viewport_w or 393)))
    vh = max(568, min(1200, int(viewport_h or 852)))
    # MiniBrowser keeps a compact nav strip even after menu removal.
    chrome_h = 72
    border_w = 16
    return vw + border_w, vh + chrome_h


def _center_window(hwnd: int, width: int, height: int) -> None:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        sw = int(user32.GetSystemMetrics(0))
        sh = int(user32.GetSystemMetrics(1))
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        user32.SetWindowPos(
            hwnd, 0, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE
        )
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


def _hide_toolbar_children(parent_hwnd: int) -> None:
    """Hide MiniBrowser nav/address child windows (heuristic, safe)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        SW_HIDE = 0
        parent_rect = wintypes.RECT()
        if not user32.GetWindowRect(parent_hwnd, ctypes.byref(parent_rect)):
            return
        parent_w = parent_rect.right - parent_rect.left

        EnumChildProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def _cb(child, _lparam):
            try:
                if not user32.IsWindowVisible(child):
                    return True
                cls = _class_name(child).lower()
                title = _window_title(child).lower()
                rect = wintypes.RECT()
                if not user32.GetWindowRect(child, ctypes.byref(rect)):
                    return True
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                rel_top = rect.top - parent_rect.top
                looks_like_bar = (
                    rel_top <= 120
                    and h <= 120
                    and w >= int(parent_w * 0.45)
                    and (
                        "toolbar" in cls
                        or "address" in cls
                        or "navigation" in cls
                        or "rebar" in cls
                        or "msctls" in cls
                        or "edit" in cls
                        or "http" in title
                        or "https" in title
                    )
                )
                if looks_like_bar:
                    user32.ShowWindow(child, SW_HIDE)
            except Exception:
                pass
            return True

        user32.EnumChildWindows(parent_hwnd, EnumChildProc(_cb), 0)
    except Exception:
        pass


def _apply_shell_once(
    hwnd: int,
    win_w: int,
    win_h: int,
    *,
    force: bool,
    profile_slot: int = 1,
    profile_label: str = "",
) -> None:
    with _LOCK:
        seen = hwnd in _SHELL_HWNDS
    if seen and not force:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindowVisible(hwnd):
            return
        if not _is_webkit_browser_hwnd(hwnd):
            return
        _remove_menu_bar(hwnd)
        _hide_toolbar_children(hwnd)
        user32.SetWindowTextW(hwnd, _SAFARI_DISPLAY)
        _center_window(hwnd, win_w, win_h)
        try:
            from krexion_window_icon import brand_single_hwnd_krexion

            brand_single_hwnd_krexion(
                int(hwnd),
                profile_slot=int(profile_slot or 1),
                profile_label=str(profile_label or "Profile")[:60],
                platform="ios",
            )
        except Exception as _ico_err:
            logger.debug(f"[ios-safari-shell] icon brand skipped: {_ico_err}")
        with _LOCK:
            _SHELL_HWNDS.add(hwnd)
    except Exception as e:
        logger.debug(f"[ios-safari-shell] apply failed hwnd={hwnd}: {e}")


def _shell_apply_loop(
    seed_pids: List[int],
    parent_pid: Optional[int],
    viewport_w: int,
    viewport_h: int,
    profile_label: str,
    deadline_s: float,
    interval_s: float,
    profile_slot: int = 1,
) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        from krexion_window_icon import (
            collect_profile_process_tree,
            find_pids_by_window_title_substrings,
            find_webkit_browser_pids,
        )

        user32 = ctypes.windll.user32
        win_w, win_h = _phone_window_size(viewport_w, viewport_h)
        _title_markers = ("[WebKit]", "Safari")

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        GetWindowThreadProcessId.restype = wintypes.DWORD

        deadline = time.time() + deadline_s
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set |= collect_profile_process_tree(int(parent_pid))
        pid_set |= find_webkit_browser_pids(parent_pid)
        pid_set |= find_pids_by_window_title_substrings(*_title_markers)
        last_force = 0.0

        while time.time() < deadline:
            if parent_pid:
                pid_set |= collect_profile_process_tree(int(parent_pid))
            pid_set |= find_webkit_browser_pids(parent_pid)
            pid_set |= find_pids_by_window_title_substrings(*_title_markers)

            found: List[int] = []

            def _cb(hwnd, _lparam):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    title = _window_title(int(hwnd))
                    win_pid = wintypes.DWORD(0)
                    GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    pid_match = win_pid.value in pid_set
                    title_match = any(m in title for m in _title_markers)
                    if pid_match or title_match:
                        found.append(int(hwnd))
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(_cb), 0)

            now = time.time()
            force_all = (now - last_force) >= 3.0 or (deadline - now) > (
                deadline_s - 15.0
            )
            if force_all:
                last_force = now

            for hwnd in found:
                _apply_shell_once(
                    hwnd,
                    win_w,
                    win_h,
                    force=force_all,
                    profile_slot=profile_slot,
                    profile_label=profile_label,
                )

            if parent_pid:
                try:
                    proc = ctypes.windll.kernel32.OpenProcess(
                        0x1000, False, int(parent_pid)
                    )
                    if not proc:
                        return
                    ctypes.windll.kernel32.CloseHandle(proc)
                except Exception:
                    pass

            time.sleep(interval_s)
    except Exception as e:
        logger.debug(f"[ios-safari-shell] loop crashed: {e}")


def apply_ios_safari_shell_to_pids(
    pids: list,
    *,
    parent_pid: Optional[int] = None,
    viewport_width: int = 393,
    viewport_height: int = 852,
    profile_label: str = "",
    poll_seconds: float = 120.0,
    poll_interval: float = 0.5,
    profile_slot: int = 1,
) -> Optional[threading.Thread]:
    """Polish Playwright WebKit windows to feel like iPhone Safari."""
    if not _IS_WINDOWS:
        return None
    try:
        from krexion_window_icon import (
            find_pids_by_window_title_substrings,
            find_webkit_browser_pids,
        )

        _clean = sorted({int(p) for p in (pids or []) if p})
        _clean = sorted(
            set(_clean)
            | find_webkit_browser_pids(parent_pid)
            | find_pids_by_window_title_substrings("[WebKit]", "Safari")
        )
        if not _clean and not parent_pid:
            return None
        t = threading.Thread(
            target=_shell_apply_loop,
            args=(
                _clean,
                parent_pid,
                int(viewport_width or 393),
                int(viewport_height or 852),
                str(profile_label or "")[:60],
                float(poll_seconds),
                float(poll_interval),
                int(profile_slot or 1),
            ),
            daemon=True,
            name=f"KrexionSafariShell-{parent_pid or (_clean[0] if _clean else 0)}",
        )
        t.start()
        return t
    except Exception as e:
        logger.debug(f"[ios-safari-shell] apply failed: {e}")
        return None
