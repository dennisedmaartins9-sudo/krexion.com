"""
Krexion Browser Kernel Resolver (v2.9.0 — AdsPower-class C++ Chromium LOCK)
=========================================================================
Product decision: headed Chromium Browser Profiles MUST run on CloakBrowser —
a source-level C++ patched Chromium (AdsPower SunBrowser class), white-labeled
as ``krexion-browser.exe``.

Honest scope
------------
* This is NOT "compile Google Chromium from scratch in this repo" (multi-month
  fork team). CloakBrowser IS the C++ kernel layer AdsPower-class products use
  when they do not maintain a private Chromium tree.
* Stock Playwright Chromium is BANNED for headed profile Open unless the
  operator explicitly sets ``KREXION_ALLOW_STOCK_CHROMIUM=1`` (tests / emergency).

Order for browser_kernel=auto (headed Chromium profiles):
  1) Installer-bundled Krexion Kernel (``KREXION_KERNEL_PATH`` / krexion-kernel/)
  2) CloakBrowser C++ binary → branded as krexion-browser.exe
  3) HARD FAIL (no silent Playwright fallback)

Env:
  KREXION_BROWSER_KERNEL=auto|cloak|patchright|playwright|firefox|chrome
  KREXION_ALLOW_STOCK_CHROMIUM=1   # escape hatch only
  CLOAKBROWSER_BINARY_PATH / CLOAKBROWSER_LICENSE_KEY
  KREXION_KERNEL_PATH              # installer-bundled chrome path
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("krexion.browser_kernel")


def stock_chromium_allowed() -> bool:
    return (os.environ.get("KREXION_ALLOW_STOCK_CHROMIUM") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def resolve_kernel_preference(anti: Optional[Dict[str, Any]] = None) -> str:
    env = (os.environ.get("KREXION_BROWSER_KERNEL") or "").strip().lower()
    if env in ("auto", "cloak", "patchright", "playwright", "firefox", "chrome"):
        return env
    anti = anti or {}
    pref = str(anti.get("browser_kernel") or "auto").strip().lower()
    if pref in ("auto", "cloak", "patchright", "playwright", "firefox", "chrome"):
        return pref
    return "auto"


def _bundled_kernel_candidates() -> list:
    """Installer / Electron paths that ship Cloak as Krexion Kernel."""
    out: list = []
    for key in ("KREXION_KERNEL_PATH", "CLOAKBROWSER_BINARY_PATH"):
        p = (os.environ.get(key) or "").strip()
        if p:
            out.append(Path(p))

    here = Path(__file__).resolve()
    roots = [
        here.parent,  # backend/
        here.parent.parent,  # repo / app root
        Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").parent
        if os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        else None,
    ]
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(sys.executable).resolve().parent.parent)

    if sys.platform.startswith("win"):
        pf = os.environ.get("PROGRAMFILES") or r"C:\Program Files"
        roots.append(Path(pf) / "Krexion")
        local = os.environ.get("LOCALAPPDATA") or ""
        if local:
            roots.append(Path(local) / "Programs" / "Krexion")
            roots.append(Path(local) / "Krexion")

    names = (
        ("krexion-kernel", "chrome.exe"),
        ("krexion-kernel", "chrome"),
        ("krexion-kernel", "krexion-browser.exe"),
        ("krexion-kernel", "krexion-browser"),
        ("resources", "krexion-kernel", "chrome.exe"),
        ("resources", "krexion", "krexion-kernel", "chrome.exe"),
        ("resources", "krexion", "krexion-kernel", "chrome"),
    )
    for root in roots:
        if not root:
            continue
        try:
            root = Path(root)
        except Exception:
            continue
        for parts in names:
            out.append(root.joinpath(*parts))
    return out


def cloak_binary_path() -> str:
    """Return CloakBrowser / installer-bundled Krexion Kernel chrome path."""
    for cand in _bundled_kernel_candidates():
        try:
            if cand.is_file():
                return str(cand)
        except Exception:
            continue
    try:
        import cloakbrowser  # type: ignore

        path = cloakbrowser.ensure_binary()
        if path and os.path.isfile(path):
            return str(path)
    except Exception as e:
        logger.debug(f"[kernel] cloak ensure_binary skipped: {e}")
    return ""


def ensure_krexion_cpp_kernel(*, force: bool = False) -> str:
    """Download/ensure Cloak C++ Chromium; return binary path or ''."""
    if not force:
        existing = cloak_binary_path()
        if existing:
            return existing
    try:
        import cloakbrowser  # type: ignore

        path = cloakbrowser.ensure_binary()
        if path and os.path.isfile(path):
            os.environ.setdefault("CLOAKBROWSER_BINARY_PATH", str(path))
            return str(path)
    except Exception as e:
        logger.warning(f"[kernel] CloakBrowser ensure failed: {e}")
    return cloak_binary_path()


def cloak_info() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": False,
        "path": "",
        "version": "",
        "tier": "",
        "kernel_class": "cloak-cpp-chromium",
        "adspower_class": True,
    }
    try:
        import cloakbrowser  # type: ignore

        out["version"] = str(getattr(cloakbrowser, "__version__", "") or "")
        out["chromium"] = str(getattr(cloakbrowser, "CHROMIUM_VERSION", "") or "")
        try:
            info = cloakbrowser.binary_info() or {}
            out.update({k: info.get(k) for k in ("tier", "path", "version") if k in info})
        except Exception:
            pass
        path = cloak_binary_path()
        out["path"] = path
        out["available"] = bool(path)
    except Exception as e:
        path = cloak_binary_path()
        out["path"] = path
        out["available"] = bool(path)
        if not path:
            out["error"] = str(e)[:200]
    return out


def patchright_available() -> bool:
    try:
        import patchright  # noqa: F401

        return True
    except Exception:
        return False


class KrexionKernelMissingError(RuntimeError):
    """Raised when AdsPower-class C++ kernel cannot be resolved for headed profiles."""


def resolve_launch_plan(
    anti: Optional[Dict[str, Any]] = None,
    *,
    headed_profile: bool = True,
) -> Dict[str, Any]:
    """
    Return launch plan. For headed Chromium profiles, Cloak C++ is mandatory
    unless KREXION_ALLOW_STOCK_CHROMIUM=1.
    """
    pref = resolve_kernel_preference(anti)
    plan: Dict[str, Any] = {
        "engine": "chromium",
        "driver": "playwright",
        "executable_path": "",
        "stealth_args": [],
        "kernel_label": "playwright-chromium",
        "reduce_js_fingerprint_noise": False,
        "preference": pref,
        "branded": False,
        "cpp_kernel": False,
        "adspower_class": False,
    }

    if pref == "firefox":
        plan["engine"] = "firefox"
        plan["kernel_label"] = "playwright-firefox"
        return plan

    if pref == "chrome":
        if headed_profile and not stock_chromium_allowed():
            raise KrexionKernelMissingError(
                "System Chrome is not allowed for Krexion profiles. "
                "AdsPower-class Cloak C++ kernel is required (krexion-browser)."
            )
        plan["kernel_label"] = "system-chrome"
        plan["channel"] = "chrome"
        return plan

    if headed_profile and pref in ("playwright", "patchright") and not stock_chromium_allowed():
        raise KrexionKernelMissingError(
            f"browser_kernel={pref} is blocked for headed profiles. "
            "Krexion 2.9+ requires Cloak C++ Chromium (AdsPower-class kernel). "
            "Set browser_kernel=auto|cloak, or KREXION_ALLOW_STOCK_CHROMIUM=1 for emergency only."
        )

    if pref in ("auto", "cloak"):
        path = ensure_krexion_cpp_kernel(force=True)
        if path:
            plan["driver"] = "cloak"
            plan["executable_path"] = path
            plan["kernel_label"] = "cloakbrowser-cpp"
            plan["reduce_js_fingerprint_noise"] = True
            plan["cpp_kernel"] = True
            plan["adspower_class"] = True
            try:
                import cloakbrowser  # type: ignore

                fn = getattr(cloakbrowser, "get_default_stealth_args", None) or getattr(
                    cloakbrowser, "default_stealth_args", None
                )
                plan["stealth_args"] = list(fn() or []) if callable(fn) else []
            except Exception:
                plan["stealth_args"] = []
            return _apply_krexion_brand_binary(plan)

        if headed_profile and not stock_chromium_allowed():
            raise KrexionKernelMissingError(
                "Krexion Kernel (Cloak C++ Chromium) is missing. "
                "Reinstall Krexion Desktop/Native so the AdsPower-class browser "
                "engine is bundled, or run: python -m cloakbrowser ensure "
                "(then relaunch the profile)."
            )
        logger.warning("[kernel] Cloak unavailable — stock Chromium escape hatch active")

    if pref in ("auto", "patchright") and patchright_available() and stock_chromium_allowed():
        plan["driver"] = "patchright"
        plan["kernel_label"] = "patchright-cdp"
        return _apply_krexion_brand_binary(plan)

    if not stock_chromium_allowed() and headed_profile:
        raise KrexionKernelMissingError(
            "Krexion Kernel (Cloak C++ Chromium) required for headed profiles."
        )

    plan["kernel_label"] = "playwright-chromium"
    logger.warning(
        "[kernel] Using branded Chromium fallback (KREXION_ALLOW_STOCK_CHROMIUM=1). "
        "This is NOT AdsPower-class C++ stealth."
    )
    return _apply_krexion_brand_binary(plan)


def _apply_krexion_brand_binary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer krexion-browser.exe so OS shows Krexion, not chrome.exe."""
    if plan.get("engine") != "chromium":
        return plan
    if (os.environ.get("KREXION_DISABLE_BRANDED_BROWSER") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return plan
    try:
        from krexion_branded_browser import ensure_krexion_browser_binary

        branded = ensure_krexion_browser_binary(
            prefer_cloak=bool(
                plan.get("driver") == "cloak"
                or plan.get("cpp_kernel")
                or plan.get("executable_path")
            ),
        )
        if branded and os.path.isfile(branded):
            plan["executable_path"] = branded
            plan["branded"] = True
            label = str(plan.get("kernel_label") or "")
            if "cloak" in label or plan.get("cpp_kernel"):
                plan["kernel_label"] = "krexion-stealth-browser"
            elif "patchright" in label:
                plan["kernel_label"] = "krexion-hardened-browser"
            else:
                plan["kernel_label"] = "krexion-browser"
            plan.pop("channel", None)
    except Exception as exc:
        logger.debug(f"[kernel] branded browser apply skipped: {exc}")
    return plan


async def launch_chromium_with_plan(
    playwright_or_patchright: Any,
    launch_kwargs: Dict[str, Any],
    plan: Dict[str, Any],
) -> Any:
    """Launch chromium using resolved plan."""
    kwargs = dict(launch_kwargs or {})
    args = list(kwargs.get("args") or [])
    for a in plan.get("stealth_args") or []:
        if a and a not in args:
            args.append(a)
    kwargs["args"] = args

    exe = (plan.get("executable_path") or "").strip()
    if exe:
        kwargs["executable_path"] = exe
        kwargs.pop("channel", None)

    channel = plan.get("channel")
    browser_type = playwright_or_patchright.chromium
    if channel and not exe:
        return await browser_type.launch(channel=channel, **kwargs)
    return await browser_type.launch(**kwargs)


def get_async_playwright_factory(plan: Dict[str, Any]):
    """Return async_playwright callable from patchright or playwright."""
    if plan.get("driver") == "patchright":
        try:
            from patchright.async_api import async_playwright as _ap  # type: ignore

            return _ap
        except Exception as e:
            logger.debug(f"[kernel] patchright async_api failed: {e}")
    from playwright.async_api import async_playwright as _ap  # type: ignore

    return _ap
