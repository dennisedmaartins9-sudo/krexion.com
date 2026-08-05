"""
Krexion — Browser Binary Rotation (Step 3 / 2026-02 v2.1.31)
==============================================================

Defeats the "everyone uses Chromium" cohort tell. Real users surf with
a mix of Chrome, Brave, Edge, Vivaldi, Opera. Affiliate networks and
anti-fraud ML (Anura Premium, Sift, IPQS Deep) cluster traffic by
"engine signature" — when 100% of your visits come from
`chromium-headless-shell` or `chrome-headless-new` with the EXACT same
revision string, even a perfect anti-detect layer leaves that one
giveaway.

This module exposes a tiny variant picker:
    pick_browser_executable(variant="auto", rotate_pool=None)
        -> { "executable_path": str | None, "variant": str, "args_extra": [...] }

Variants supported (gracefully degrade when a binary isn't installed):
    "auto"           — current default behaviour (full chromium > shell)
    "chromium"       — force the full Chromium binary (--headless=new)
    "headless-shell" — force the lightweight chromium-headless-shell
    "brave"          — use Brave at standard install paths if available
                       (falls back to "auto" when Brave isn't present)
    "rotate"         — random pick per visit from `rotate_pool` (default
                       ["chromium", "brave", "headless-shell"] limited to
                       what's actually installed)

Safe-by-default: the existing `real_user_traffic._use_full_chromium()`
contract is preserved when `variant="auto"`. Callers opting into rotation
get reliable fallback to a working binary, NEVER a crash.
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("browser_variants")


# ──────────────────────────────────────────────────────────────────────
# Binary discovery
# ──────────────────────────────────────────────────────────────────────

# Brave installs at well-known paths across platforms. We probe in
# priority order: native VPS Linux first (servers), then desktop OSes.
_BRAVE_PATHS = [
    # ── 2026-02 Step 6: Auto-bootstrap install paths (zero-touch) ──
    # `browser_bootstrap.py` downloads Brave portable to these locations
    # on first backend boot. Checked FIRST so even if a system-wide
    # Brave exists, the Krexion-managed copy (known-good version) wins.
    str(Path(os.environ.get("LOCALAPPDATA", os.environ.get("APPDATA", str(Path.home())))) / "Krexion" / "browsers" / "brave" / "brave.exe"),
    str(Path.home() / "Library" / "Application Support" / "Krexion" / "browsers" / "brave" / "Brave Browser.app" / "Contents" / "MacOS" / "Brave Browser"),
    str(Path(os.environ.get("HOME", "/root")) / ".krexion" / "browsers" / "brave" / "brave-browser"),
    # Linux (apt/snap/flatpak/portable)
    "/usr/bin/brave-browser",
    "/usr/bin/brave",
    "/opt/brave.com/brave/brave",
    "/opt/brave.com/brave-browser/brave-browser",
    "/snap/bin/brave",
    "/var/lib/flatpak/exports/bin/com.brave.Browser",
    # macOS (when Electron runs natively)
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    # Windows (when Electron is bundled inside Krexion Windows Native)
    "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    "C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
]


def _exists(path: str) -> bool:
    try:
        return bool(path) and Path(path).exists()
    except Exception:
        return False


def find_brave_executable() -> Optional[str]:
    """Return the first Brave binary that actually exists on this host.
    Override via `KREXION_BRAVE_PATH` env (lets ops point at a portable
    Brave shipped inside the Krexion Native Desktop installer)."""
    env_path = os.environ.get("KREXION_BRAVE_PATH", "").strip()
    if env_path and _exists(env_path):
        return env_path
    for p in _BRAVE_PATHS:
        if _exists(p):
            return p
    return None


def find_full_chromium_executable() -> Optional[str]:
    """Delegates to `real_user_traffic._full_chromium_binary_path` so we
    don't drift from the source-of-truth path resolver."""
    try:
        from real_user_traffic import _full_chromium_binary_path  # type: ignore
        bp = _full_chromium_binary_path()
        return str(bp) if bp else None
    except Exception:
        return None


def find_headless_shell_executable() -> Optional[str]:
    """The lightweight chromium-headless-shell that ships with
    Playwright. Searches PLAYWRIGHT_BROWSERS_PATH + native Krexion
    browser-engine roots (Windows installer path included)."""
    try:
        roots: List[str] = []
        env_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        if env_root:
            roots.append(env_root)
        roots.append("/pw-browsers")
        # Native Windows installer default
        roots.append(r"C:\Program Files\Krexion\browser-engine")
        try:
            from real_user_traffic import _browsers_search_roots  # type: ignore
            for r in _browsers_search_roots():
                roots.append(str(r))
        except Exception:
            pass
        seen = set()
        for browsers_root in roots:
            if not browsers_root or browsers_root in seen:
                continue
            seen.add(browsers_root)
            root = Path(browsers_root)
            if not root.is_dir():
                continue
            # Playwright uses BOTH layouts depending on rev:
            #   chromium-headless-shell-<rev>/.../headless_shell
            #   chromium_headless_shell-<rev>/.../headless_shell(.exe)
            for glob in ("chromium-headless-shell-*", "chromium_headless_shell-*"):
                for p in root.glob(glob):
                    for cand in p.rglob("headless_shell*"):
                        name = cand.name.lower()
                        if name in ("headless_shell", "headless_shell.exe") and cand.is_file():
                            return str(cand)
        return None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# Public picker
# ──────────────────────────────────────────────────────────────────────

_DEFAULT_ROTATE_POOL = ["chromium", "brave", "headless-shell"]


def list_available_variants() -> List[str]:
    """Return the set of variants that have a runnable binary on this
    host RIGHT NOW. Used by the UI to show only realistic options."""
    out: List[str] = []
    if find_full_chromium_executable():
        out.append("chromium")
    if find_brave_executable():
        out.append("brave")
    if find_headless_shell_executable():
        out.append("headless-shell")
    out.append("auto")  # always available — falls through to default flow
    out.append("rotate")  # always available — auto-narrows to installed
    return out


def pick_browser_executable(
    variant: str = "auto",
    *,
    rotate_pool: Optional[List[str]] = None,
    visit_index: int = 0,
) -> Dict[str, Any]:
    """Resolve a single visit's browser variant choice.

    Returns:
        {
            "executable_path": str | None,   # pass to chromium.launch(executable_path=...)
            "variant": str,                  # what was actually picked
            "args_extra": [str, ...],        # additional launch args
            "is_brave": bool,                # convenience flag
            "engine_label": str,             # for log lines / dashboard
        }

    `executable_path=None` means "let Playwright pick its default" (the
    `real_user_traffic._use_full_chromium()` flow handles --headless=new
    selection downstream).
    """
    variant = (variant or "auto").strip().lower()

    if variant == "rotate":
        pool = list(rotate_pool or _DEFAULT_ROTATE_POOL)
        # Drop variants that don't have a binary installed
        available_brave = bool(find_brave_executable())
        available_full = bool(find_full_chromium_executable())
        available_shell = bool(find_headless_shell_executable())
        pool = [
            v for v in pool
            if (v == "brave" and available_brave)
            or (v == "chromium" and available_full)
            or (v == "headless-shell" and available_shell)
        ]
        if not pool:
            return _result("auto", None, args_extra=[], engine_label="auto-fallback")
        # Deterministic per visit_index so a job's worker fan-out gives a
        # roughly even distribution without seeding global RNG.
        random.seed(visit_index ^ 0xA17EB7)
        variant = random.choice(pool)
        random.seed()  # restore

    if variant == "brave":
        path = find_brave_executable()
        if path:
            # Brave needs Chromium-compatible flags + `--password-store=basic`
            # so it doesn't try to talk to GNOME keyring on headless servers.
            extra = [
                "--password-store=basic",
                "--no-default-browser-check",
                # Disable Brave's onboarding / first-run sync flow
                "--disable-features=BraveRewards,BraveAds,BraveSearchOmniboxBanner",
            ]
            return _result("brave", path, args_extra=extra, engine_label=f"brave({Path(path).name})")
        # Fallback: behave like auto
        logger.debug("brave variant requested but no binary found — falling back to auto")
        return _result("auto", None, args_extra=[], engine_label="auto-fallback(no-brave)")

    if variant == "chromium":
        path = find_full_chromium_executable()
        if path:
            return _result("chromium", path, args_extra=["--headless=new"], engine_label="full-chromium")
        return _result("auto", None, args_extra=[], engine_label="auto-fallback(no-full-chromium)")

    if variant == "headless-shell":
        path = find_headless_shell_executable()
        if path:
            return _result("headless-shell", path, args_extra=[], engine_label="headless-shell")
        return _result("auto", None, args_extra=[], engine_label="auto-fallback(no-shell)")

    # "auto" or anything unrecognised
    return _result("auto", None, args_extra=[], engine_label="auto")


def _result(variant: str, executable_path: Optional[str], *, args_extra: List[str], engine_label: str) -> Dict[str, Any]:
    return {
        "executable_path": executable_path,
        "variant": variant,
        "args_extra": args_extra,
        "is_brave": variant == "brave",
        "engine_label": engine_label,
    }


__all__ = [
    "pick_browser_executable",
    "list_available_variants",
    "find_brave_executable",
    "find_full_chromium_executable",
    "find_headless_shell_executable",
]
