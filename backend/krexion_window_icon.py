"""
Krexion Window Icon Override (Windows only)
============================================
Makes headed Browser Profile windows show the Krexion logo on the
Windows taskbar (instead of the Chrome / Chromium logo).

Why WM_SETICON alone is not enough
----------------------------------
On Windows 7+ the taskbar button icon is driven primarily by the
window's AppUserModelID + RelaunchIconResource (or a Start Menu
shortcut with the same AppID). Chromium / Google Chrome keep resetting
WM_SETICON and register their own Chrome.* AppID, so a one-shot
SendMessage(WM_SETICON) often leaves the Chrome logo on the taskbar.

Reliable approach (Microsoft AppUserModelID docs)
-------------------------------------------------
1. Prefer the real installer `krexion.ico` (fallback: generated badge).
2. For every visible Chromium HWND:
     • SHGetPropertyStoreForWindow
     • Set PKEY_AppUserModel_RelaunchIconResource = "<ico>,0"
     • Set PKEY_AppUserModel_RelaunchDisplayNameResource = "Krexion"
     • Set PKEY_AppUserModel_ID last (= "Krexion.BrowserProfile")
3. Also WM_SETICON / class-icon for title-bar + alt-tab.
4. Keep re-applying for ~90s (Chrome resets icons after first paint).

All failures are swallowed — icon branding must never break Launch.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time
from typing import Optional, Set

logger = logging.getLogger("krexion.window_icon")

_IS_WINDOWS = sys.platform.startswith("win")

# Stable AppID so every profile groups under one Krexion taskbar brand.
_KREXION_APP_ID = "Krexion.BrowserProfile"

_ICONED_HWNDS: Set[int] = set()
_LOCK = threading.Lock()


def _official_ico_candidates() -> list:
    """Known on-disk locations for the real Krexion product icon."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = [
        os.environ.get("KREXION_ICON_PATH") or "",
        r"C:\Program Files\Krexion\krexion.ico",
        os.path.join(here, "krexion.ico"),
        os.path.join(here, "..", "krexion.ico"),
        os.path.join(here, "..", "installer", "krexion.ico"),
        os.path.join(here, "..", "desktop", "icons", "krexion.ico"),
        os.path.join(here, "..", "desktop", "krexion.ico"),
    ]
    return [os.path.normpath(p) for p in out if p]


def _krexion_ico_path() -> str:
    """Prefer the real product ICO; fall back to a generated K-badge."""
    for cand in _official_ico_candidates():
        try:
            if cand and os.path.isfile(cand) and os.path.getsize(cand) > 200:
                return cand
        except Exception:
            continue
    return _generate_fallback_ico()


def _generate_fallback_ico() -> str:
    out = os.path.join(tempfile.gettempdir(), "krexion_taskbar.ico")
    if os.path.exists(out) and os.path.getsize(out) > 200:
        return out
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            draw.rounded_rectangle(
                [(0, 0), (size - 1, size - 1)],
                radius=14,
                fill=(34, 211, 238, 255),
            )
        except Exception:
            draw.rectangle([(0, 0), (size - 1, size - 1)], fill=(34, 211, 238, 255))
        font = None
        for name in ("segoeuib.ttf", "SegoeUI-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(name, 42)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        text = "K"
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (size - tw) // 2 - bbox[0]
            ty = (size - th) // 2 - bbox[1] - 2
        except Exception:
            tw, th = draw.textsize(text, font=font)
            tx = (size - tw) // 2
            ty = (size - th) // 2 - 2
        draw.text((tx, ty), text, fill=(11, 18, 32, 255), font=font)
        img.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        return out
    except Exception as e:
        logger.debug(f"[krexion-icon] Pillow ICO gen failed, using stub: {e}")
        try:
            with open(out, "wb") as f:
                f.write(_minimal_16x16_cyan_ico())
            return out
        except Exception:
            return ""


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


def _ensure_start_menu_shortcut(ico_path: str, profile_label: str = "Krexion") -> None:
    """Register a Start Menu .lnk with our AppID + Krexion icon.

    Taskbar looks this up when a window advertises the same AppUserModelID.
    Best-effort — missing shortcut still works if RelaunchIconResource is set.
    """
    if not _IS_WINDOWS or not ico_path:
        return
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
        lnk_path = os.path.join(programs, "Krexion Browser.lnk")

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
            sc.Description = "Krexion Browser Profile"
            sc.Arguments = "-m desktop.krexion_dashboard"
            sc.save()
            created = True
        except Exception:
            # Fallback when pywin32 is missing (dev host) — PowerShell COM.
            try:
                import subprocess

                ps = (
                    f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}');"
                    f"$s.TargetPath='{target}';"
                    f"$s.WorkingDirectory='{os.path.dirname(target)}';"
                    f"$s.IconLocation='{ico_path},0';"
                    f"$s.Description='Krexion Browser Profile';"
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
            store.SetValue(
                pscon.PKEY_AppUserModel_ID,
                propsys.PROPVARIANTType(_KREXION_APP_ID),
            )
            store.Commit()
        except Exception as prop_err:
            logger.debug(f"[krexion-icon] shortcut AppID stamp skipped: {prop_err}")
    except Exception as e:
        logger.debug(f"[krexion-icon] Start Menu shortcut skipped: {e}")


def _set_window_app_identity(hwnd: int, ico_path: str, display_name: str) -> bool:
    """Set AppUserModelID + RelaunchIconResource on a top-level HWND."""
    try:
        import pythoncom  # type: ignore
        from win32com.propsys import propsys, pscon  # type: ignore

        pythoncom.CoInitialize()
        try:
            store = propsys.SHGetPropertyStoreForWindow(int(hwnd))
            # Order matters: relaunch props BEFORE AppUserModelID.
            store.SetValue(
                pscon.PKEY_AppUserModel_RelaunchIconResource,
                propsys.PROPVARIANTType(f"{ico_path},0"),
            )
            store.SetValue(
                pscon.PKEY_AppUserModel_RelaunchDisplayNameResource,
                propsys.PROPVARIANTType(display_name or "Krexion"),
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
                propsys.PROPVARIANTType(_KREXION_APP_ID),
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


def apply_krexion_icon_to_pid(
    pid: int,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
) -> Optional[threading.Thread]:
    return apply_krexion_icon_to_pids(
        [pid],
        profile_label=profile_label,
        poll_seconds=poll_seconds,
        poll_interval=poll_interval,
    )


def apply_krexion_icon_to_pids(
    pids: list,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
    parent_pid: Optional[int] = None,
) -> Optional[threading.Thread]:
    """Keep Chromium HWNDs branded as Krexion for `poll_seconds`."""
    if not _IS_WINDOWS:
        return None
    try:
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_KREXION_APP_ID)
        except Exception:
            pass

        ico_path = _krexion_ico_path()
        if not ico_path or not os.path.exists(ico_path):
            logger.debug("[krexion-icon] no ICO available — skipping")
            return None

        _ensure_start_menu_shortcut(ico_path, profile_label=profile_label)

        _clean = sorted({int(p) for p in (pids or []) if p})
        if not _clean and not parent_pid:
            return None

        display = f"Krexion — {profile_label}" if profile_label else "Krexion"
        t = threading.Thread(
            target=_icon_apply_loop_multi,
            args=(_clean, parent_pid, ico_path, display, poll_seconds, poll_interval),
            daemon=True,
            name=f"KrexionIcon-{parent_pid or _clean[0]}",
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


def _icon_apply_loop_multi(
    seed_pids: list,
    parent_pid: Optional[int],
    ico_path: str,
    display_name: str,
    deadline_s: float,
    interval_s: float,
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
        LR_SHARED = 0x00008000

        hicon_small = user32.LoadImageW(
            None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE | LR_SHARED
        )
        hicon_large = user32.LoadImageW(
            None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE | LR_SHARED
        )
        if not hicon_small and not hicon_large:
            logger.debug("[krexion-icon] LoadImageW returned 0 for both sizes")
            return

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        GetWindowThreadProcessId.restype = wintypes.DWORD

        deadline = time.time() + deadline_s
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set.add(int(parent_pid))

        # First ~12s: always re-apply (Chrome paints late and overwrites).
        # After that: refresh every ~4s so resets are corrected.
        last_force = 0.0

        while time.time() < deadline:
            if parent_pid:
                pid_set |= _walk_descendants(int(parent_pid))

            found_hwnds = []

            def _cb(hwnd, _lparam):
                try:
                    win_pid = wintypes.DWORD(0)
                    GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    if win_pid.value in pid_set and user32.IsWindowVisible(hwnd):
                        found_hwnds.append(int(hwnd))
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(_cb), 0)

            now = time.time()
            force_all = (now - last_force) >= 4.0 or (deadline - now) > (deadline_s - 12.0)
            if force_all:
                last_force = now

            for hwnd in found_hwnds:
                with _LOCK:
                    already = hwnd in _ICONED_HWNDS
                if already and not force_all:
                    continue
                try:
                    _set_window_app_identity(hwnd, ico_path, display_name)
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
                    logger.debug(f"[krexion-icon] branded hwnd={hwnd}")
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

            time.sleep(interval_s)
    except Exception as e:
        logger.debug(f"[krexion-icon] loop crashed: {e}")


def _icon_apply_loop_LEGACY_do_not_call(pid: int, ico_path: str, deadline_s: float, interval_s: float) -> None:
    apply_krexion_icon_to_pid(pid, poll_seconds=deadline_s, poll_interval=interval_s)
