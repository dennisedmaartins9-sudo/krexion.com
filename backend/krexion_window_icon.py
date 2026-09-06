"""
Krexion Browser Taskbar Icon (Windows only)
===========================================
Headed Browser Profiles show the Krexion *browser* icon on the Windows
taskbar (not Chrome), with a Chrome-style profile number badge in the
top-left corner (1, 2, 3…) for each open profile window.

Approach
--------
1. Base art: `assets/krexion_browser_icon.png` (incognito + neon ring).
2. Per open profile, bake a numbered ICO (top-left badge) into %TEMP%.
3. Unique AppUserModelID per slot (`Krexion.BrowserProfile.N`) so Windows
   shows separate taskbar buttons, each with its own numbered icon via
   PKEY_AppUserModel_RelaunchIconResource + WM_SETICON.
4. Re-apply for ~90s because Chromium resets icons after first paint.

Failures are swallowed — branding must never break Launch.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("krexion.window_icon")

_IS_WINDOWS = sys.platform.startswith("win")
_KREXION_APP_ID_BASE = "Krexion.BrowserProfile"

_ICONED_HWNDS: Set[int] = set()
_SESSION_ICON_STOP: Dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def stop_session_icon_keeper(session_key: str) -> None:
    """Stop the per-session taskbar icon loop (call when profile session ends)."""
    key = str(session_key or "").strip()
    if not key:
        return
    with _LOCK:
        ev = _SESSION_ICON_STOP.pop(key, None)
    if ev is not None:
        ev.set()


def _hwnd_is_toolwindow(hwnd: int) -> bool:
    """True when HWND is already marked TOOLWINDOW (hidden from taskbar)."""
    if not _IS_WINDOWS or not hwnd:
        return False
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        style = int(ctypes.windll.user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE) or 0)
        return bool(style & WS_EX_TOOLWINDOW)
    except Exception:
        return False


def hide_hwnd_from_taskbar(hwnd: int) -> None:
    """Remove an embedded engine HWND from the taskbar (shell owns the button).

    Never call ShowWindow(SW_SHOW) here — that re-activates the window and
    causes the recurring taskbar flicker (appear → hide → appear).
    """
    if not _IS_WINDOWS or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        style = int(user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE) or 0)
        new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if new_style == style:
            return
        user32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, new_style)
        # Frame change only — no SW_SHOW (flicker root cause).
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        user32.SetWindowPos(
            int(hwnd),
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception as exc:
        logger.debug(f"[krexion-icon] hide hwnd from taskbar skipped: {exc}")



def show_hwnd_on_taskbar(hwnd: int) -> None:
    """Restore APPWINDOW so a fallback engine stays visible on the taskbar."""
    if not _IS_WINDOWS or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        style = int(user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE) or 0)
        new_style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        if new_style == style:
            return
        user32.SetWindowLongW(int(hwnd), GWL_EXSTYLE, new_style)
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        user32.SetWindowPos(
            int(hwnd), 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def profile_engine_visible_on_taskbar(
    driver_pid: Optional[int],
    *,
    webkit: bool = False,
) -> bool:
    """True when a profile engine HWND still has a taskbar button (not TOOLWINDOW)."""
    if not _IS_WINDOWS or not driver_pid:
        return False
    pid_set = collect_profile_process_tree(int(driver_pid))
    if webkit:
        try:
            pid_set |= find_webkit_browser_pids(int(driver_pid))
        except Exception:
            pass
    if not pid_set:
        return False
    visible = False
    try:
        import ctypes
        from ctypes import wintypes

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

        def _cb(hwnd, _lparam):
            nonlocal visible
            if visible:
                return True
            try:
                win_pid = wintypes.DWORD(0)
                GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value not in pid_set:
                    return True
                if not _is_profile_engine_hwnd(int(hwnd), webkit=webkit):
                    return True
                if not _hwnd_is_toolwindow(int(hwnd)):
                    visible = True
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        # Conservative: if we cannot inspect styles, fall back to existence.
        return bool(profile_engine_window_exists(int(driver_pid), webkit=webkit))
    return visible


def _app_id_for_slot(slot: int) -> str:
    n = max(1, int(slot or 1))
    return f"{_KREXION_APP_ID_BASE}.{n}"


def _browser_png_candidates() -> list:
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.environ.get("KREXION_BROWSER_ICON_PATH") or "",
        os.path.join(here, "assets", "krexion_browser_icon.png"),
        r"C:\ProgramData\Krexion\krexion_browser_icon.png",
        r"C:\Program Files\Krexion\krexion_browser_icon.png",
        os.path.join(here, "assets", "krexion_browser_icon.png"),
    ]


def _official_ico_candidates() -> list:
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.environ.get("KREXION_ICON_PATH") or "",
        r"C:\Program Files\Krexion\krexion.ico",
        os.path.join(here, "krexion.ico"),
        os.path.join(here, "..", "installer", "krexion.ico"),
        os.path.join(here, "..", "desktop", "icons", "krexion.ico"),
    ]


def _find_existing(paths: list) -> str:
    for cand in paths:
        try:
            p = os.path.normpath(cand) if cand else ""
            if p and os.path.isfile(p) and os.path.getsize(p) > 200:
                return p
        except Exception:
            continue
    return ""


def _normalize_platform_key(platform: str) -> str:
    plat = (platform or "").strip().lower()
    if plat in ("ios", "ipados"):
        return "ios"
    if plat == "android":
        return "android"
    return ""


def _load_base_rgba(size: int = 256, platform: str = ""):
    """Load official Krexion browser PNG as-is (no platform tint)."""
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    png = _find_existing(_browser_png_candidates())
    if png:
        img = Image.open(png).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        return img

    # Fallback: cyan K tile
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        draw.rounded_rectangle(
            [(0, 0), (size - 1, size - 1)],
            radius=max(8, size // 8),
            fill=(34, 211, 238, 255),
        )
    except Exception:
        draw.rectangle([(0, 0), (size - 1, size - 1)], fill=(34, 211, 238, 255))
    font = None
    for name in ("segoeuib.ttf", "SegoeUI-Bold.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(name, max(20, size // 2))
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = "K"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (size - tw) // 2 - bbox[0]
        ty = (size - th) // 2 - bbox[1]
    except Exception:
        tw, th = draw.textsize(text, font=font)
        tx, ty = (size - tw) // 2, (size - th) // 2
    draw.text((tx, ty), text, fill=(11, 18, 32, 255), font=font)
    return img


def _draw_profile_badge(img, slot: int, platform: str = "") -> None:
    """Chrome-style number badge, top-left corner."""
    from PIL import ImageDraw, ImageFont  # type: ignore

    size = img.size[0]
    draw = ImageDraw.Draw(img)
    n = max(1, min(99, int(slot or 1)))
    label = str(n)
    rim = (56, 189, 248, 255)
    # Badge box ~18% of icon, inset slightly
    pad = max(2, size // 48)
    bw = max(14, int(size * 0.20))
    bh = max(14, int(size * 0.20))
    x0, y0 = pad, pad
    x1, y1 = x0 + bw, y0 + bh
    # Dark glass + cyan rim (matches product art)
    try:
        draw.rounded_rectangle(
            [(x0, y0), (x1, y1)],
            radius=max(3, bw // 5),
            fill=(12, 18, 32, 230),
            outline=rim,
            width=max(1, size // 64),
        )
    except Exception:
        draw.rectangle([(x0, y0), (x1, y1)], fill=(12, 18, 32, 230), outline=rim)

    font = None
    font_size = max(10, int(bh * 0.62))
    for name in ("segoeuib.ttf", "SegoeUI-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = x0 + (bw - tw) // 2 - bbox[0]
        ty = y0 + (bh - th) // 2 - bbox[1] - max(0, size // 128)
    except Exception:
        tw, th = draw.textsize(label, font=font)
        tx = x0 + (bw - tw) // 2
        ty = y0 + (bh - th) // 2
    draw.text((tx, ty), label, fill=(255, 255, 255, 255), font=font)


def _png_to_ico_bytes(png_bytes: bytes, width: int = 256, height: int = 256) -> bytes:
    """Vista+ ICO that embeds a full PNG (sharp taskbar icons)."""
    import struct

    # width/height 0 in ICONDIRENTRY means 256
    w = 0 if width >= 256 else int(width)
    h = 0 if height >= 256 else int(height)
    header = struct.pack("<HHH", 0, 1, 1)
    offset = 6 + 16
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png_bytes), offset)
    return header + entry + png_bytes


def build_profile_taskbar_ico(slot: int = 1, platform: str = "") -> str:
    """Return numbered Krexion-browser ICO path for this profile slot."""
    n = max(1, min(99, int(slot or 1)))
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "assets", f"krexion_browser_p{min(n, 20)}.ico")
    if n <= 20 and os.path.isfile(bundled) and os.path.getsize(bundled) > 2000:
        return bundled

    out_dir = os.path.join(tempfile.gettempdir(), "krexion_profile_icons")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = tempfile.gettempdir()
    out = os.path.join(out_dir, f"krexion_browser_p{n}.ico")
    png_src = _find_existing(_browser_png_candidates())
    need_build = True
    try:
        if os.path.isfile(out) and os.path.getsize(out) > 2000:
            if not png_src or os.path.getmtime(out) >= os.path.getmtime(png_src):
                need_build = False
    except Exception:
        pass
    if not need_build:
        return out

    try:
        from PIL import Image  # type: ignore

        base = _load_base_rgba(256, platform=platform)
        _draw_profile_badge(base, n, platform=platform)
        import io

        buf = io.BytesIO()
        base.save(buf, format="PNG")
        ico_bytes = _png_to_ico_bytes(buf.getvalue(), 256, 256)
        with open(out, "wb") as fh:
            fh.write(ico_bytes)
        if os.path.getsize(out) > 2000:
            return out
    except Exception as e:
        logger.debug(f"[krexion-icon] numbered ICO build failed: {e}")

    if os.path.isfile(bundled) and os.path.getsize(bundled) > 500:
        return bundled
    return _krexion_ico_path_plain()


def browser_icon_data_uri(platform: str = "", size: int = 32) -> str:
    """Inline PNG for mobile shell HTML (official art, unchanged).

    Falls back to raw asset bytes when Pillow is unavailable so shell chrome
    still gets the Krexion mark on lean native installs / CI.
    """
    import base64
    import io

    try:
        from PIL import Image  # type: ignore

        px = max(16, min(128, int(size or 32)))
        img = _load_base_rgba(px, platform=platform)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        logger.debug(f"[krexion-icon] data-uri PIL path skipped: {exc}")
    try:
        found = _find_existing(_browser_png_candidates())
        if found and os.path.isfile(found):
            with open(found, "rb") as fh:
                raw = fh.read()
            if len(raw) > 200:
                b64 = base64.b64encode(raw).decode("ascii")
                return f"data:image/png;base64,{b64}"
    except Exception as exc2:
        logger.debug(f"[krexion-icon] data-uri file fallback skipped: {exc2}")
    return ""


def browser_icon_file_uri(platform: str = "") -> str:
    """file:// URI for pywebview when data-uri is too large."""
    try:
        from pathlib import Path

        out_dir = os.path.join(tempfile.gettempdir(), "krexion_profile_icons")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "krexion_mark.png")
        img = _load_base_rgba(64, platform=platform)
        img.save(out, format="PNG")
        return Path(out).resolve().as_uri()
    except Exception:
        return ""


def _krexion_ico_path_plain() -> str:
    found = _find_existing(_official_ico_candidates())
    if found:
        return found
    out = os.path.join(tempfile.gettempdir(), "krexion_taskbar.ico")
    if os.path.exists(out) and os.path.getsize(out) > 200:
        return out
    try:
        from PIL import Image  # type: ignore

        img = _load_base_rgba(64)
        img.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        return out
    except Exception:
        return ""


def _krexion_ico_path() -> str:
    """Back-compat: unnumbered product/browser icon."""
    return build_profile_taskbar_ico(1) if _find_existing(_browser_png_candidates()) else _krexion_ico_path_plain()


def _minimal_16x16_cyan_ico() -> bytes:
    import struct

    w = h = 16
    header = struct.pack("<HHH", 0, 1, 1)
    dib_size = 40 + (w * h * 4) + ((w * h) // 8)
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, dib_size, 22)
    bih = struct.pack(
        "<IIIHHIIIIII",
        40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0,
    )
    pixel = struct.pack("<BBBB", 0xEE, 0xD3, 0x22, 0xFF) * (w * h)
    mask = b"\x00" * ((w * h) // 8)
    return header + entry + bih + pixel + mask


def _ensure_start_menu_shortcut(ico_path: str, profile_label: str = "Krexion", app_id: str = "") -> None:
    if not _IS_WINDOWS or not ico_path:
        return
    app_id = app_id or _KREXION_APP_ID_BASE
    try:
        programs = os.path.join(
            os.environ.get("APPDATA") or "",
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "Krexion",
        )
        os.makedirs(programs, exist_ok=True)
        # One shortcut per AppID slot so taskbar can resolve icons.
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in app_id)[-40:]
        lnk_path = os.path.join(programs, f"Krexion Browser {safe}.lnk")
        target = os.environ.get("KREXION_SHORTCUT_TARGET") or r"C:\Program Files\Krexion\bin\krexion-coreapp.exe"
        if not os.path.isfile(target):
            target = sys.executable

        created = False
        try:
            from win32com.client import Dispatch  # type: ignore

            shell = Dispatch("WScript.Shell")
            sc = shell.CreateShortCut(lnk_path)
            sc.Targetpath = target
            sc.WorkingDirectory = os.path.dirname(target)
            sc.IconLocation = f"{ico_path},0"
            sc.Description = f"Krexion Browser — {profile_label}"
            sc.Arguments = "-m desktop.krexion_dashboard"
            sc.save()
            created = True
        except Exception:
            try:
                import subprocess

                ps = (
                    f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}');"
                    f"$s.TargetPath='{target}';"
                    f"$s.WorkingDirectory='{os.path.dirname(target)}';"
                    f"$s.IconLocation='{ico_path},0';"
                    f"$s.Description='Krexion Browser';"
                    f"$s.Arguments='-m desktop.krexion_dashboard';"
                    f"$s.Save()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    check=False,
                    capture_output=True,
                    timeout=15,
                )
                created = os.path.isfile(lnk_path)
            except Exception as ps_err:
                logger.debug(f"[krexion-icon] PS shortcut skipped: {ps_err}")

        if not created:
            return
        try:
            from win32com.propsys import propsys, pscon  # type: ignore

            store = propsys.SHGetPropertyStoreFromParsingName(lnk_path)
            store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id))
            store.Commit()
        except Exception as prop_err:
            logger.debug(f"[krexion-icon] shortcut AppID stamp skipped: {prop_err}")
    except Exception as e:
        logger.debug(f"[krexion-icon] Start Menu shortcut skipped: {e}")


def _set_window_app_identity(
    hwnd: int,
    ico_path: str,
    display_name: str,
    app_id: str = "",
) -> bool:
    app_id = app_id or _KREXION_APP_ID_BASE
    try:
        import pythoncom  # type: ignore
        from win32com.propsys import propsys, pscon  # type: ignore

        pythoncom.CoInitialize()
        try:
            store = propsys.SHGetPropertyStoreForWindow(int(hwnd))
            store.SetValue(
                pscon.PKEY_AppUserModel_RelaunchIconResource,
                propsys.PROPVARIANTType(f"{ico_path},0"),
            )
            store.SetValue(
                pscon.PKEY_AppUserModel_RelaunchDisplayNameResource,
                propsys.PROPVARIANTType(display_name or "Krexion Browser"),
            )
            try:
                store.SetValue(
                    pscon.PKEY_AppUserModel_PreventPinning,
                    propsys.PROPVARIANTType(True),
                )
            except Exception:
                pass
            store.SetValue(
                pscon.PKEY_AppUserModel_ID,
                propsys.PROPVARIANTType(app_id),
            )
            try:
                store.Commit()
            except Exception:
                pass
            return True
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[krexion-icon] AppUserModelID set failed hwnd={hwnd}: {e}")
        return False


def brand_single_hwnd_krexion(
    hwnd: int,
    *,
    profile_slot: int = 1,
    profile_label: str = "Profile",
    ico_path: str = "",
    app_id: str = "",
    display_name: str = "",
    platform: str = "",
) -> bool:
    """Apply numbered Krexion icon + AppUserModelID to one visible HWND."""
    if not _IS_WINDOWS or not hwnd:
        return False
    try:
        slot = max(1, min(99, int(profile_slot or 1)))
        app_id = app_id or _app_id_for_slot(slot)
        path = ico_path or build_profile_taskbar_ico(slot, platform=platform)
        if not path or not os.path.exists(path):
            return False
        display = display_name or f"Krexion — {profile_label} ({slot})"
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        hicon_small = user32.LoadImageW(None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_large = user32.LoadImageW(None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        _set_window_app_identity(hwnd, path, display, app_id=app_id)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_large:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_large)
        try:
            SetClassLongPtrW = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
            GCLP_HICON = -14
            GCLP_HICONSM = -34
            if hicon_large:
                SetClassLongPtrW(hwnd, GCLP_HICON, hicon_large)
            if hicon_small:
                SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)
        except Exception:
            pass
        with _LOCK:
            _ICONED_HWNDS.add(int(hwnd))
        return True
    except Exception as e:
        logger.debug(f"[krexion-icon] single hwnd brand failed: {e}")
        return False


def apply_krexion_icon_to_pid(
    pid: int,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
    profile_slot: int = 1,
    platform: str = "",
) -> Optional[threading.Thread]:
    return apply_krexion_icon_to_pids(
        [pid],
        profile_label=profile_label,
        poll_seconds=poll_seconds,
        poll_interval=poll_interval,
        profile_slot=profile_slot,
        platform=platform,
    )


def apply_krexion_icon_to_pids(
    pids: list,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
    parent_pid: Optional[int] = None,
    profile_slot: int = 1,
    cmdline_markers: Optional[list] = None,
    window_title_markers: Optional[list] = None,
    include_webkit: bool = False,
    platform: str = "",
    session_key: str = "",
    skip_toolwindow: bool = True,
    session_lifetime: bool = True,
) -> Optional[threading.Thread]:
    """Brand Chromium HWNDs as Krexion Browser with profile number badge."""
    if not _IS_WINDOWS:
        return None
    try:
        sk = str(session_key or "").strip()
        if sk:
            stop_session_icon_keeper(sk)
        stop_ev = threading.Event()
        if sk:
            with _LOCK:
                _SESSION_ICON_STOP[sk] = stop_ev

        slot = max(1, min(99, int(profile_slot or 1)))
        app_id = _app_id_for_slot(slot)
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass

        ico_path = build_profile_taskbar_ico(slot, platform=platform)
        if not ico_path or not os.path.exists(ico_path):
            logger.debug("[krexion-icon] no ICO available — skipping")
            return None

        _ensure_start_menu_shortcut(ico_path, profile_label=profile_label, app_id=app_id)

        _clean = sorted({int(p) for p in (pids or []) if p})
        if cmdline_markers:
            _clean = sorted(set(_clean) | find_chromium_pids_by_cmdline_substrings(*cmdline_markers))
        if include_webkit or window_title_markers:
            _clean = sorted(set(_clean) | find_webkit_browser_pids(parent_pid))
        if window_title_markers:
            _clean = sorted(
                set(_clean) | find_pids_by_window_title_substrings(*window_title_markers)
            )
        if (
            not _clean
            and not parent_pid
            and not cmdline_markers
            and not window_title_markers
        ):
            return None

        display = f"Krexion Browser ({slot})"
        if profile_label:
            display = f"Krexion — {profile_label} ({slot})"
        # Session-bound keepers re-apply icons; Chromium/WebKit reset after paint.
        # When mobile shell owns the taskbar button, callers pass a short poll
        # and stop the keeper after shell attaches (session_lifetime=False).
        if sk and session_lifetime:
            session_poll = 86400.0
        else:
            session_poll = float(poll_seconds or 90.0)
        # WebKit MiniBrowser: slower interval reduces taskbar flicker.
        interval = float(poll_interval or 0.6)
        if include_webkit:
            interval = max(interval, 1.25)
        t = threading.Thread(
            target=_icon_apply_loop_multi,
            args=(
                _clean,
                parent_pid,
                ico_path,
                display,
                app_id,
                session_poll,
                interval,
                list(cmdline_markers or []),
                list(window_title_markers or []),
                bool(include_webkit),
            ),
            kwargs={
                "stop_event": stop_ev if sk else None,
                "skip_toolwindow": bool(skip_toolwindow),
            },
            daemon=True,
            name=f"KrexionIcon-{slot}-{parent_pid or (_clean[0] if _clean else slot)}",
        )
        t.start()
        return t
    except Exception as e:
        logger.debug(f"[krexion-icon] apply failed: {e}")
        return None


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


def resolve_playwright_driver_pid(browser: Any = None, context: Any = None) -> Optional[int]:
    """Best-effort PID for Playwright Browser / persistent BrowserContext."""
    for obj in (browser, context):
        if obj is None:
            continue
        try:
            impl = getattr(obj, "_impl_obj", obj)
            proc = getattr(impl, "_process", None)
            if proc is not None:
                pid = getattr(proc, "pid", None)
                if pid:
                    return int(pid)
        except Exception:
            pass
        try:
            impl = getattr(obj, "_impl_obj", obj)
            inner = getattr(impl, "_browser", None) or getattr(impl, "browser", None)
            if inner is not None:
                proc = getattr(getattr(inner, "_impl_obj", inner), "_process", None)
                if proc is not None:
                    pid = getattr(proc, "pid", None)
                    if pid:
                        return int(pid)
        except Exception:
            pass
    return None



def keep_krexion_window_title(
    hwnds: list,
    title: str,
    *,
    poll_seconds: float = 120.0,
    poll_interval: float = 2.0,
    session_key: str = "",
    pids: Optional[list] = None,
) -> Optional[threading.Thread]:
    """AdsPower-style: re-assert branded window title after navigations overwrite it."""
    if not _IS_WINDOWS or not title:
        return None
    stop_event = threading.Event()
    key = str(session_key or f"title:{id(hwnds) if hwnds else id(title)}").strip()
    pid_set = {int(p) for p in (pids or []) if p}

    def _discover_hwnds() -> list:
        found = [int(h) for h in (hwnds or []) if h]
        if found and not pid_set:
            return found
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            out: list = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _lp):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid_set and int(pid.value) not in pid_set:
                        return True
                    if not pid_set:
                        # Fallback: only windows already titled Krexion*
                        buf = ctypes.create_unicode_buffer(512)
                        user32.GetWindowTextW(hwnd, buf, 512)
                        if "krexion" not in (buf.value or "").lower():
                            return True
                    out.append(int(hwnd))
                except Exception:
                    pass
                return True

            user32.EnumWindows(_cb, 0)
            return out or found
        except Exception:
            return found

    def _loop() -> None:
        import time
        import ctypes

        deadline = time.time() + max(5.0, float(poll_seconds or 120.0))
        user32 = ctypes.windll.user32
        while time.time() < deadline and not stop_event.is_set():
            for hwnd in _discover_hwnds():
                try:
                    if hwnd and user32.IsWindow(int(hwnd)):
                        user32.SetWindowTextW(int(hwnd), str(title)[:240])
                except Exception:
                    pass
            stop_event.wait(max(0.5, float(poll_interval or 2.0)))
        with _LOCK:
            _SESSION_ICON_STOP.pop(key, None)

    with _LOCK:
        old = _SESSION_ICON_STOP.pop(key, None)
        if old is not None:
            old.set()
        _SESSION_ICON_STOP[key] = stop_event
    th = threading.Thread(target=_loop, name=f"krexion-title-{key[:40]}", daemon=True)
    th.start()
    return th


def find_webkit_browser_pids(parent_pid: Optional[int] = None) -> Set[int]:
    """Locate Playwright WebKit MiniBrowser PIDs (Windows headed iOS profiles).

    When *parent_pid* is known, ONLY return WebKit processes inside that
    profile's process tree — never every MiniBrowser on the machine (that
    caused cross-profile taskbar flicker when Android + iOS launched together).
    """
    out: Set[int] = set()
    _webkit_names = {
        "minibrowser.exe",
        "webkitwebprocess.exe",
        "webkitnetworkprocess.exe",
        "webkit.exe",
        # v2.7.129 — white-label AdsPower FlowerBrowser-class binary
        "krexion-safari.exe",
        "krexion-safari",
    }
    try:
        import psutil as _psu

        tree: Optional[Set[int]] = None
        if parent_pid:
            tree = set(collect_profile_process_tree(int(parent_pid)))
            tree.add(int(parent_pid))
        for proc in _psu.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname not in _webkit_names:
                    continue
                pid = int(proc.info["pid"])
                if tree is not None and pid not in tree:
                    continue
                out.add(pid)
            except Exception:
                pass
    except Exception:
        pass
    return out


def find_pids_by_window_title_substrings(*needles: str) -> Set[int]:
    """Map top-level HWND titles → owning PIDs (WebKit MiniBrowser / Safari titles).

    v2.7.108: use IsWindow (not IsWindowVisible) so first-paint / cloaked
    MiniBrowser windows still join the PID set for phone-chrome framing.
    """
    clean = [str(n).strip() for n in needles if str(n or "").strip()]
    if not _IS_WINDOWS or not clean:
        return set()
    out: Set[int] = set()
    try:
        import ctypes
        from ctypes import wintypes

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

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindow(hwnd):
                    return True
                title_buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title_buf, 512)
                title = title_buf.value or ""
                if not any(n in title for n in clean):
                    return True
                win_pid = wintypes.DWORD(0)
                GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value:
                    out.add(int(win_pid.value))
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        pass
    return out


def find_chromium_pids_by_cmdline_substrings(*needles: str) -> Set[int]:
    """Locate chrome/chromium PIDs whose command line contains all needles."""
    clean = [str(n).strip() for n in needles if str(n or "").strip()]
    if not clean:
        return set()
    out: Set[int] = set()
    try:
        import psutil as _psu

        for proc in _psu.process_iter(["pid", "name", "cmdline"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname not in (
                    "chrome.exe",
                    "chromium.exe",
                    "msedge.exe",
                    "chrome",
                    "chromium",
                    # v2.7.128 — white-label AdsPower-style binary name
                    "krexion-browser.exe",
                    "krexion-browser",
                    "krexionbrowser.exe",
                ):
                    continue
                cmdline = proc.info.get("cmdline") or []
                joined = " ".join(str(x) for x in cmdline)
                if all(n in joined for n in clean):
                    out.add(int(proc.info["pid"]))
            except Exception:
                pass
    except Exception:
        pass
    return out


def collect_profile_process_tree(driver_pid: Optional[int]) -> Set[int]:
    """Playwright browser + driver PIDs (WebKit MiniBrowser, node, Chromium)."""
    out: Set[int] = set()
    if not driver_pid:
        return out
    try:
        import psutil as _psu

        try:
            proc = _psu.Process(int(driver_pid))
        except Exception:
            return out
        out.add(int(driver_pid))
        out |= _walk_descendants(int(driver_pid))
        cur = proc
        for _ in range(8):
            try:
                parent = cur.parent()
            except Exception:
                break
            if not parent:
                break
            out.add(int(parent.pid))
            out |= _walk_descendants(int(parent.pid))
            pname = (parent.name() or "").lower()
            cur = parent
            if pname in (
                "python.exe",
                "pythonw.exe",
                "krexion-coreapp.exe",
                "krexion.exe",
            ):
                break
    except Exception:
        pass
    return out


def _icon_apply_loop_multi(
    seed_pids: list,
    parent_pid: Optional[int],
    ico_path: str,
    display_name: str,
    app_id: str,
    deadline_s: float,
    interval_s: float,
    cmdline_markers: Optional[list] = None,
    window_title_markers: Optional[list] = None,
    include_webkit: bool = False,
    stop_event: Optional[threading.Event] = None,
    skip_toolwindow: bool = True,
) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010

        # Do NOT use LR_SHARED — each slot needs its own HICON from file.
        hicon_small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_large = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not hicon_small and not hicon_large:
            logger.debug("[krexion-icon] LoadImageW returned 0 for both sizes")
            return

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        GetWindowThreadProcessId.restype = wintypes.DWORD

        # Honour caller poll_seconds — do NOT force 86400 just because stop_event exists.
        poll_s = max(5.0, float(deadline_s or 90.0))
        session_mode = poll_s >= 86000.0
        deadline = time.time() + poll_s
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set.add(int(parent_pid))
        last_force = 0.0
        force_every = 8.0 if include_webkit else 3.0

        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            if parent_pid:
                pid_set |= collect_profile_process_tree(int(parent_pid))
            if cmdline_markers:
                pid_set |= find_chromium_pids_by_cmdline_substrings(*cmdline_markers)
            if include_webkit or window_title_markers:
                pid_set |= find_webkit_browser_pids(parent_pid)
            if window_title_markers:
                pid_set |= find_pids_by_window_title_substrings(*window_title_markers)

            found_hwnds = []

            def _cb(hwnd, _lparam):
                try:
                    win_pid = wintypes.DWORD(0)
                    GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    title_buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title_buf, 512)
                    title = title_buf.value or ""
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    if skip_toolwindow and _hwnd_is_toolwindow(int(hwnd)):
                        return True
                    if title.startswith("KrexionShell-"):
                        return True
                    pid_match = win_pid.value in pid_set
                    title_match = bool(
                        window_title_markers
                        and any(n in title for n in window_title_markers)
                    )
                    if not pid_match and not title_match:
                        return True
                    # Playwright / stock Chromium helpers — hide so only Krexion-
                    # branded phone chrome / Orbit window stays on the taskbar
                    # (AdsPower-style: user should not see Playwright icons).
                    _tlow = title.strip().lower()
                    if (
                        _tlow == "playwright"
                        or _tlow.startswith("playwright ")
                        or _tlow == "chromium"
                    ):
                        user32.ShowWindow(hwnd, 0)  # SW_HIDE
                        return True
                    found_hwnds.append(int(hwnd))
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(_cb), 0)

            now = time.time()
            force_all = session_mode or (now - last_force) >= force_every or (deadline - now) > (poll_s - 15.0)
            if force_all:
                last_force = now

            for hwnd in found_hwnds:
                with _LOCK:
                    already = hwnd in _ICONED_HWNDS
                if already and not force_all:
                    continue
                try:
                    _set_window_app_identity(hwnd, ico_path, display_name, app_id=app_id)
                    if hicon_small:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                    if hicon_large:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_large)
                    GCLP_HICON = -14
                    GCLP_HICONSM = -34
                    try:
                        SetClassLongPtrW = getattr(
                            user32, "SetClassLongPtrW", user32.SetClassLongW
                        )
                        if hicon_large:
                            SetClassLongPtrW(hwnd, GCLP_HICON, hicon_large)
                        if hicon_small:
                            SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)
                    except Exception:
                        pass
                    with _LOCK:
                        _ICONED_HWNDS.add(hwnd)
                except Exception as se:
                    logger.debug(f"[krexion-icon] brand failed hwnd={hwnd}: {se}")

            if parent_pid:
                try:
                    proc = kernel32.OpenProcess(0x1000, False, int(parent_pid))
                    if not proc:
                        return
                    kernel32.CloseHandle(proc)
                except Exception:
                    pass

            time.sleep(max(0.4, float(interval_s or 0.6)))
    except Exception as e:
        logger.debug(f"[krexion-icon] loop crashed: {e}")


def is_process_alive(pid: Optional[int]) -> bool:
    """True if OS process exists (used for profile auto-stop on window close)."""
    if not pid:
        return True
    try:
        import psutil as _psu

        return bool(_psu.pid_exists(int(pid)))
    except Exception:
        try:
            import ctypes

            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return True


def _is_profile_engine_hwnd(hwnd: int, *, webkit: bool) -> bool:
    """Engine content window — includes minimized (IsWindow), not only visible."""
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
        if title.strip().lower() == "playwright":
            return False
        if webkit:
            return (
                "[webkit]" in title.lower()
                or "safari" in title.lower()
                or "webkit" in cname
                or "minibrowser" in cname
                or "krexion-safari" in cname
            )
        return (
            "chrome" in cname
            or "chromium" in cname
            or title.startswith("Krexion")
            or "krexion orbit" in title.lower()
        )
    except Exception:
        return False


def profile_engine_window_exists(driver_pid: Optional[int], *, webkit: bool = False) -> bool:
    """True while the headed profile engine window still exists (minimize OK)."""
    if not driver_pid:
        return True
    pid_set = collect_profile_process_tree(int(driver_pid))
    if webkit:
        pid_set |= find_webkit_browser_pids(int(driver_pid))
    if not pid_set:
        return False
    found = False
    try:
        import ctypes
        from ctypes import wintypes

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

        def _cb(hwnd, _lparam):
            nonlocal found
            if found:
                return True
            try:
                win_pid = wintypes.DWORD(0)
                GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value not in pid_set:
                    return True
                if _is_profile_engine_hwnd(int(hwnd), webkit=webkit):
                    found = True
            except Exception:
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        return True
    return found


def hide_profile_engine_windows(driver_pid: Optional[int], *, webkit: bool = False) -> int:
    """Best-effort hide/minimize naked engine HWNDs until Krexion phone chrome frames them.

    v2.7.135 — Used when Strict shell is ON but early embed has not completed yet,
    so the operator never sees plain Chromium/WebKit as "Krexion".
    """
    if not driver_pid:
        return 0
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return 0
    try:
        pids = collect_profile_process_tree(int(driver_pid))
    except Exception:
        pids = {int(driver_pid)}
    if webkit:
        try:
            pids |= find_webkit_browser_pids(int(driver_pid))
        except Exception:
            pass
    else:
        try:
            pids |= find_chromium_pids_by_cmdline_substrings("--window-name=Krexion")
        except Exception:
            pass
    if not pids:
        return 0
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    hidden = 0

    def _cb(hwnd, _lp):
        nonlocal hidden
        try:
            pid = wintypes.DWORD(0)
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids:
                return True
            if not user32.IsWindowVisible(hwnd):
                return True
            # SW_HIDE — shell apply loop will ShowWindow again after frame
            user32.ShowWindow(hwnd, 0)
            try:
                hide_hwnd_from_taskbar(int(hwnd))
            except Exception:
                pass
            hidden += 1
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        return hidden
    return hidden


