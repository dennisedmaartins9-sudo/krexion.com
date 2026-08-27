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
from typing import Optional, Set

logger = logging.getLogger("krexion.window_icon")

_IS_WINDOWS = sys.platform.startswith("win")
_KREXION_APP_ID_BASE = "Krexion.BrowserProfile"

_ICONED_HWNDS: Set[int] = set()
_LOCK = threading.Lock()


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


def _load_base_rgba(size: int = 256):
    """Load browser PNG (cover baked-in sample badge) or fall back to K tile."""
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    png = _find_existing(_browser_png_candidates())
    if png:
        img = Image.open(png).convert("RGBA")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        # Wipe any sample number badge in the source mock (top-left ~22%).
        draw = ImageDraw.Draw(img)
        cut = max(8, int(size * 0.24))
        # Match near-black canvas behind the art.
        draw.rectangle([(0, 0), (cut, cut)], fill=(5, 8, 16, 255))
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


def _draw_profile_badge(img, slot: int) -> None:
    """Chrome-style number badge, top-left corner."""
    from PIL import ImageDraw, ImageFont  # type: ignore

    size = img.size[0]
    draw = ImageDraw.Draw(img)
    n = max(1, min(99, int(slot or 1)))
    label = str(n)
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
            outline=(56, 189, 248, 255),
            width=max(1, size // 64),
        )
    except Exception:
        draw.rectangle([(x0, y0), (x1, y1)], fill=(12, 18, 32, 230), outline=(56, 189, 248, 255))

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


def build_profile_taskbar_ico(slot: int = 1) -> str:
    """Return numbered Krexion-browser ICO path for this profile slot."""
    n = max(1, min(99, int(slot or 1)))
    here = os.path.dirname(os.path.abspath(__file__))
    # Prefer shipping prebuilt assets (no Pillow required at runtime).
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
    # Rebuild when missing, tiny, or older than source art
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

        base = _load_base_rgba(256)
        _draw_profile_badge(base, n)
        # Embed 256px PNG inside ICO (Pillow's multi-size ICO often collapses)
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


def apply_krexion_icon_to_pid(
    pid: int,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
    profile_slot: int = 1,
) -> Optional[threading.Thread]:
    return apply_krexion_icon_to_pids(
        [pid],
        profile_label=profile_label,
        poll_seconds=poll_seconds,
        poll_interval=poll_interval,
        profile_slot=profile_slot,
    )


def apply_krexion_icon_to_pids(
    pids: list,
    profile_label: str = "Krexion",
    poll_seconds: float = 90.0,
    poll_interval: float = 0.6,
    parent_pid: Optional[int] = None,
    profile_slot: int = 1,
) -> Optional[threading.Thread]:
    """Brand Chromium HWNDs as Krexion Browser with profile number badge."""
    if not _IS_WINDOWS:
        return None
    try:
        slot = max(1, min(99, int(profile_slot or 1)))
        app_id = _app_id_for_slot(slot)
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass

        ico_path = build_profile_taskbar_ico(slot)
        if not ico_path or not os.path.exists(ico_path):
            logger.debug("[krexion-icon] no ICO available — skipping")
            return None

        _ensure_start_menu_shortcut(ico_path, profile_label=profile_label, app_id=app_id)

        _clean = sorted({int(p) for p in (pids or []) if p})
        if not _clean and not parent_pid:
            return None

        display = f"Krexion Browser ({slot})"
        if profile_label:
            display = f"Krexion — {profile_label} ({slot})"
        t = threading.Thread(
            target=_icon_apply_loop_multi,
            args=(_clean, parent_pid, ico_path, display, app_id, poll_seconds, poll_interval),
            daemon=True,
            name=f"KrexionIcon-{slot}-{parent_pid or _clean[0]}",
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
    app_id: str,
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

        deadline = time.time() + deadline_s
        pid_set: Set[int] = {int(p) for p in seed_pids or []}
        if parent_pid:
            pid_set.add(int(parent_pid))
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
            force_all = (now - last_force) >= 3.0 or (deadline - now) > (deadline_s - 15.0)
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

            time.sleep(interval_s)
    except Exception as e:
        logger.debug(f"[krexion-icon] loop crashed: {e}")

