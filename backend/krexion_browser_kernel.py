"""
Krexion Browser Kernel Resolver (v2.8.0 — AdsPower-class profile lock)
=========================================
Closes the Octo/AdsPower "custom Chromium kernel" gap by optionally
launching profiles on CloakBrowser (source-level C++ stealth Chromium)
or Patchright, with safe fallback to stock Playwright Chromium.

Order for browser_kernel=auto:
  1) CloakBrowser binary (ensure_binary) if importable
  2) Patchright chromium if importable
  3) Playwright bundled chromium

Env overrides:
  KREXION_BROWSER_KERNEL=auto|cloak|patchright|playwright|firefox
  CLOAKBROWSER_BINARY_PATH / CLOAKBROWSER_LICENSE_KEY (upstream)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("krexion.browser_kernel")


def resolve_kernel_preference(anti: Optional[Dict[str, Any]] = None) -> str:
    # v2.8.0 — Profile default is AdsPower-class stealth kernel (Cloak C++),
    # not stock Playwright. Operators may still force playwright via env/anti.
    env = (os.environ.get("KREXION_BROWSER_KERNEL") or "").strip().lower()
    if env in ("auto", "cloak", "patchright", "playwright", "firefox", "chrome"):
        return env
    anti = anti or {}
    pref = str(anti.get("browser_kernel") or "auto").strip().lower()
    if pref in ("auto", "cloak", "patchright", "playwright", "firefox", "chrome"):
        return pref
    return "auto"


def cloak_binary_path() -> str:
    """Return CloakBrowser chrome path or '' if unavailable."""
    try:
        import cloakbrowser  # type: ignore

        path = cloakbrowser.ensure_binary()
        if path and os.path.isfile(path):
            return str(path)
    except Exception as e:
        logger.debug(f"[kernel] cloak ensure_binary skipped: {e}")
    # Explicit env path
    env_path = (os.environ.get("CLOAKBROWSER_BINARY_PATH") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    return ""


def cloak_info() -> Dict[str, Any]:
    out: Dict[str, Any] = {"available": False, "path": "", "version": "", "tier": ""}
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
        out["error"] = str(e)[:200]
    return out


def patchright_available() -> bool:
    try:
        import patchright  # noqa: F401

        return True
    except Exception:
        return False


def resolve_launch_plan(anti: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Return {
      engine: chromium|firefox|webkit,
      driver: playwright|patchright|cloak,
      executable_path: optional str,
      stealth_args: list[str],
      kernel_label: str,
      reduce_js_fingerprint_noise: bool,  # Cloak already C++-patches canvas/etc.
      branded: bool,  # launched via krexion-browser.exe white-label binary
    }
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
    }

    if pref == "firefox":
        plan["engine"] = "firefox"
        plan["kernel_label"] = "playwright-firefox"
        return plan

    if pref == "chrome":
        plan["kernel_label"] = "system-chrome"
        plan["channel"] = "chrome"
        return plan

    # Prefer Cloak for auto/cloak
    if pref in ("auto", "cloak"):
        path = cloak_binary_path()
        if path:
            plan["driver"] = "cloak"
            plan["executable_path"] = path
            plan["kernel_label"] = "cloakbrowser-cpp"
            plan["reduce_js_fingerprint_noise"] = True
            try:
                import cloakbrowser  # type: ignore

                plan["stealth_args"] = list(cloakbrowser.get_default_stealth_args() or [])
            except Exception:
                plan["stealth_args"] = []
            return _apply_krexion_brand_binary(plan)
        if pref == "cloak":
            logger.warning("[kernel] CloakBrowser requested but unavailable — falling back")

    # Patchright next
    if pref in ("auto", "patchright") and patchright_available():
        plan["driver"] = "patchright"
        plan["kernel_label"] = "patchright-cdp"
        return _apply_krexion_brand_binary(plan)

    # Last resort stock Chromium — still white-label as krexion-browser.exe
    # so users never see chrome.exe / Playwright branding on headed profiles.
    plan["kernel_label"] = "playwright-chromium"
    logger.warning(
        "[kernel] CloakBrowser C++ kernel unavailable — using branded Chromium fallback. "
        "Install CloakBrowser for AdsPower-class source-level stealth."
    )
    return _apply_krexion_brand_binary(plan)


def _apply_krexion_brand_binary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """v2.7.128 — Prefer krexion-browser.exe so OS shows Krexion, not chrome.exe."""
    if plan.get("engine") != "chromium":
        return plan
    if (os.environ.get("KREXION_DISABLE_BRANDED_BROWSER") or "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return plan
    try:
        from krexion_branded_browser import ensure_krexion_browser_binary

        branded = ensure_krexion_browser_binary(
            prefer_cloak=bool(plan.get("driver") == "cloak" or plan.get("executable_path")),
        )
        if branded and os.path.isfile(branded):
            plan["executable_path"] = branded
            plan["branded"] = True
            # User-facing label — never advertise stock Chromium
            label = str(plan.get("kernel_label") or "")
            if "cloak" in label:
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
    """Launch chromium using resolved plan. Mutates launch_kwargs args safely."""
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
