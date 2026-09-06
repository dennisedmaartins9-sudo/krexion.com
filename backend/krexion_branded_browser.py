"""
Krexion Branded Browser Binary (v2.7.128)
=========================================
AdsPower-class UX without rebuilding Chromium from source:

1. Copy Cloak / Playwright / system chrome → ``krexion-browser.exe``
2. Launch profiles on that binary so Task Manager / process list say Krexion
3. Optional PE VersionInfo / icon stamp when tools are present
4. Keep Cloak stealth args / Patchright driver on the branded path

True Chromium source rebuild (window-class rename) is out of scope here.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("krexion.branded_browser")

_BRANDED_NAME = "krexion-browser.exe" if sys.platform.startswith("win") else "krexion-browser"
_CACHE_ENV = "KREXION_BRANDED_BROWSER_PATH"


def _icon_candidates() -> list:
    here = Path(__file__).resolve().parent
    roots = [
        here / "assets",
        here.parent / "installer",
        here.parent / "electron-desktop" / "build",
        here.parent / "desktop" / "assets",
    ]
    names = (
        "krexion_browser_p1.ico",
        "krexion.ico",
        "krexion_browser_icon.png",
        "icon.ico",
    )
    out = []
    for root in roots:
        for name in names:
            p = root / name
            if p.is_file():
                out.append(p)
    return out


def _playwright_chrome_path() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and os.path.isfile(path):
                return str(path)
    except Exception as exc:
        logger.debug(f"[branded-browser] playwright chrome probe skipped: {exc}")
    # Common Windows Playwright layout
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        browsers = Path(local) / "ms-playwright"
        if browsers.is_dir():
            for chrome in sorted(browsers.glob("chromium-*/chrome-win/chrome.exe"), reverse=True):
                if chrome.is_file():
                    return str(chrome)
            for chrome in sorted(browsers.glob("chromium-*/chrome-win/chrome"), reverse=True):
                if chrome.is_file():
                    return str(chrome)
    return ""


def _cloak_chrome_path() -> str:
    try:
        from krexion_browser_kernel import cloak_binary_path

        return str(cloak_binary_path() or "")
    except Exception:
        try:
            import cloakbrowser  # type: ignore

            path = cloakbrowser.ensure_binary()
            return str(path) if path and os.path.isfile(path) else ""
        except Exception:
            return ""


def _brand_dir() -> Path:
    override = (os.environ.get("KREXION_BROWSER_BRAND_DIR") or "").strip()
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Krexion" / "browser-engine"
    return Path.home() / ".krexion" / "browser-engine"


def _try_stamp_pe(dst: Path) -> None:
    """Best-effort icon / version stamp (never required for launch)."""
    if not sys.platform.startswith("win"):
        return
    icons = _icon_candidates()
    ico = next((p for p in icons if p.suffix.lower() == ".ico"), None)
    # rcedit-x64 if present on PATH / tools
    for tool in (
        shutil.which("rcedit-x64.exe"),
        shutil.which("rcedit.exe"),
        str(Path(__file__).resolve().parents[1] / "tools" / "rcedit-x64.exe"),
        str(Path(__file__).resolve().parents[1] / "build" / "tools" / "rcedit-x64.exe"),
    ):
        if not tool or not os.path.isfile(tool):
            continue
        try:
            import subprocess

            cmd = [
                tool,
                str(dst),
                "--set-version-string",
                "ProductName",
                "Krexion Browser",
                "--set-version-string",
                "FileDescription",
                "Krexion Browser",
                "--set-version-string",
                "CompanyName",
                "Krexion",
                "--set-version-string",
                "InternalName",
                "krexion-browser",
                "--set-version-string",
                "OriginalFilename",
                _BRANDED_NAME,
            ]
            if ico:
                cmd.extend(["--set-icon", str(ico)])
            subprocess.run(cmd, check=False, capture_output=True, timeout=60)
            logger.info(f"[branded-browser] PE stamped via {tool}")
            return
        except Exception as exc:
            logger.debug(f"[branded-browser] rcedit skipped: {exc}")
    # verpatch fallback
    for tool in (
        shutil.which("verpatch.exe"),
        str(Path(__file__).resolve().parents[1] / "tools" / "verpatch.exe"),
        str(Path(__file__).resolve().parents[1] / "desktop" / "tools" / "verpatch.exe"),
    ):
        if not tool or not os.path.isfile(tool):
            continue
        try:
            import subprocess

            subprocess.run(
                [
                    tool,
                    str(dst),
                    "/va",
                    "/s",
                    "desc",
                    "Krexion Browser",
                    "/s",
                    "product",
                    "Krexion Browser",
                    "/s",
                    "company",
                    "Krexion",
                ],
                check=False,
                capture_output=True,
                timeout=60,
            )
            logger.info(f"[branded-browser] PE stamped via verpatch")
            return
        except Exception as exc:
            logger.debug(f"[branded-browser] verpatch skipped: {exc}")


def ensure_krexion_browser_binary(
    *,
    prefer_cloak: bool = True,
    force_refresh: bool = False,
) -> str:
    """Return path to Krexion-branded browser binary (create/copy if needed)."""
    cached = (os.environ.get(_CACHE_ENV) or "").strip()
    if cached and os.path.isfile(cached) and not force_refresh:
        return cached

    src = ""
    if prefer_cloak:
        src = _cloak_chrome_path()
    if not src:
        src = _playwright_chrome_path()
    if not src and not prefer_cloak:
        src = _cloak_chrome_path()
    if not src or not os.path.isfile(src):
        logger.debug("[branded-browser] no source chrome binary to brand")
        return ""

    # Already branded?
    if Path(src).name.lower() in ("krexion-browser.exe", "krexion-browser"):
        os.environ[_CACHE_ENV] = src
        return src

    dest_dir = _brand_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(f"[branded-browser] brand dir create failed: {exc}")
        return src

    dst = dest_dir / _BRANDED_NAME
    try:
        src_mtime = os.path.getmtime(src)
        needs = force_refresh or (not dst.is_file()) or (os.path.getmtime(dst) < src_mtime)
        if needs:
            # Copy whole chrome-win folder when possible so DLLs stay adjacent
            src_path = Path(src)
            chrome_dir = src_path.parent
            if (chrome_dir / "chrome.dll").is_file() or (chrome_dir / "chrome_elf.dll").is_file():
                # Sync tree into brand dir (skip if same)
                for item in chrome_dir.iterdir():
                    target = dest_dir / item.name
                    try:
                        if item.is_file():
                            if item.name.lower() in ("chrome.exe", "chromium.exe"):
                                continue
                            if (not target.exists()) or item.stat().st_mtime > target.stat().st_mtime:
                                shutil.copy2(item, target)
                        elif item.is_dir() and item.name.lower() not in ("installer",):
                            if not target.exists():
                                shutil.copytree(item, target, dirs_exist_ok=True)
                    except Exception:
                        pass
                shutil.copy2(src, dst)
            else:
                shutil.copy2(src, dst)
            _try_stamp_pe(dst)
            logger.info(f"[branded-browser] ready src={src} → dst={dst}")
    except Exception as exc:
        logger.warning(f"[branded-browser] copy failed ({exc}) — using source path")
        return src

    if dst.is_file():
        os.environ[_CACHE_ENV] = str(dst)
        return str(dst)
    return src


def branded_browser_info() -> Dict[str, Any]:
    path = (os.environ.get(_CACHE_ENV) or "").strip() or ensure_krexion_browser_binary()
    return {
        "path": path,
        "available": bool(path and os.path.isfile(path)),
        "branded_name": _BRANDED_NAME,
        "brand_dir": str(_brand_dir()),
        "source_cloak": bool(_cloak_chrome_path()),
        "source_playwright": bool(_playwright_chrome_path()),
    }


def parent_engine_hwnd_into_shell(engine_hwnd: int, shell_hwnd: int) -> bool:
    """True HWND parenting (AdsPower-like). Best-effort Win32 only."""
    if not sys.platform.startswith("win") or not engine_hwnd or not shell_hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        WS_POPUP = 0x80000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        style = int(user32.GetWindowLongW(int(engine_hwnd), GWL_STYLE) or 0)
        style = (style | WS_CHILD) & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_SYSMENU
        user32.SetWindowLongW(int(engine_hwnd), GWL_STYLE, style)
        prev = user32.SetParent(wintypes.HWND(int(engine_hwnd)), wintypes.HWND(int(shell_hwnd)))
        SWP_FRAMECHANGED = 0x0020
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        # Fill parent client area — caller should SetWindowPos to content rect after.
        user32.SetWindowPos(
            int(engine_hwnd),
            0,
            0,
            0,
            0,
            0,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | 0x0001 | 0x0002,
        )
        # v2.7.138 — NEVER lie. Pre-138 `bool(prev) or True` always returned True,
        # so Strict thought the engine was framed while Playwright stayed naked.
        parent_now = int(user32.GetParent(int(engine_hwnd)) or 0)
        if parent_now != int(shell_hwnd):
            logger.warning(
                "[branded-browser] SetParent did not stick engine=%s shell=%s parent_now=%s prev=%s",
                engine_hwnd, shell_hwnd, parent_now, int(prev or 0),
            )
            return False
        return True
    except Exception as exc:
        logger.debug(f"[branded-browser] SetParent failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# v2.7.129 — Krexion Safari (WebKit) white-label — AdsPower FlowerBrowser parity
# ---------------------------------------------------------------------------

_SAFARI_NAME = "krexion-safari.exe" if sys.platform.startswith("win") else "krexion-safari"
_SAFARI_CACHE_ENV = "KREXION_BRANDED_SAFARI_PATH"


def _playwright_webkit_path() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.webkit.executable_path
            if path and os.path.isfile(path):
                return str(path)
    except Exception as exc:
        logger.debug(f"[branded-safari] playwright webkit probe skipped: {exc}")
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        browsers = Path(local) / "ms-playwright"
        if browsers.is_dir():
            for exe in sorted(browsers.glob("webkit-*/Playwright.exe"), reverse=True):
                if exe.is_file():
                    return str(exe)
            for exe in sorted(browsers.glob("webkit-*/MiniBrowser.exe"), reverse=True):
                if exe.is_file():
                    return str(exe)
            for exe in sorted(browsers.glob("webkit-*/pw_run.sh"), reverse=True):
                # Linux/mac helper — prefer sibling MiniBrowser when present
                mb = exe.parent / "MiniBrowser"
                if mb.is_file():
                    return str(mb)
    return ""


def ensure_krexion_safari_binary(*, force_refresh: bool = False) -> str:
    """Copy WebKit MiniBrowser → krexion-safari.exe (AdsPower FlowerBrowser-class)."""
    cached = (os.environ.get(_SAFARI_CACHE_ENV) or "").strip()
    if cached and os.path.isfile(cached) and not force_refresh:
        return cached

    src = _playwright_webkit_path()
    if not src or not os.path.isfile(src):
        logger.debug("[branded-safari] no WebKit binary to brand")
        return ""

    if Path(src).name.lower() in ("krexion-safari.exe", "krexion-safari"):
        os.environ[_SAFARI_CACHE_ENV] = src
        return src

    dest_dir = _brand_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning(f"[branded-safari] brand dir create failed: {exc}")
        return src

    dst = dest_dir / _SAFARI_NAME
    try:
        src_mtime = os.path.getmtime(src)
        needs = force_refresh or (not dst.is_file()) or (os.path.getmtime(dst) < src_mtime)
        if needs:
            src_path = Path(src)
            wk_dir = src_path.parent
            # Copy adjacent WebKit deps (DLLs / .so) so rename still runs
            for item in wk_dir.iterdir():
                target = dest_dir / item.name
                try:
                    if item.is_file():
                        if item.name.lower() in (
                            "minibrowser.exe",
                            "playwright.exe",
                            "minibrowser",
                        ):
                            continue
                        if (not target.exists()) or item.stat().st_mtime > target.stat().st_mtime:
                            shutil.copy2(item, target)
                    elif item.is_dir() and item.name.lower() not in ("installer",):
                        if not target.exists():
                            shutil.copytree(item, target, dirs_exist_ok=True)
                except Exception:
                    pass
            shutil.copy2(src, dst)
            # Stamp as Krexion Safari when PE tools exist
            if sys.platform.startswith("win"):
                try:
                    _try_stamp_pe_product(dst, "Krexion Safari", "krexion-safari")
                except Exception:
                    _try_stamp_pe(dst)
            logger.info(f"[branded-safari] ready src={src} → dst={dst}")
    except Exception as exc:
        logger.warning(f"[branded-safari] copy failed ({exc}) — using source path")
        return src

    if dst.is_file():
        os.environ[_SAFARI_CACHE_ENV] = str(dst)
        return str(dst)
    return src


def _try_stamp_pe_product(dst: Path, product: str, internal: str) -> None:
    """Stamp PE with a specific product name (Browser vs Safari)."""
    if not sys.platform.startswith("win"):
        return
    icons = _icon_candidates()
    ico = next((p for p in icons if p.suffix.lower() == ".ico"), None)
    for tool in (
        shutil.which("rcedit-x64.exe"),
        shutil.which("rcedit.exe"),
        str(Path(__file__).resolve().parents[1] / "tools" / "rcedit-x64.exe"),
        str(Path(__file__).resolve().parents[1] / "build" / "tools" / "rcedit-x64.exe"),
    ):
        if not tool or not os.path.isfile(tool):
            continue
        try:
            import subprocess

            cmd = [
                tool,
                str(dst),
                "--set-version-string",
                "ProductName",
                product,
                "--set-version-string",
                "FileDescription",
                product,
                "--set-version-string",
                "CompanyName",
                "Krexion",
                "--set-version-string",
                "InternalName",
                internal,
                "--set-version-string",
                "OriginalFilename",
                dst.name,
            ]
            if ico:
                cmd.extend(["--set-icon", str(ico)])
            subprocess.run(cmd, check=False, capture_output=True, timeout=60)
            logger.info(f"[branded-browser] PE stamped {product} via {tool}")
            return
        except Exception as exc:
            logger.debug(f"[branded-browser] rcedit product stamp skipped: {exc}")
