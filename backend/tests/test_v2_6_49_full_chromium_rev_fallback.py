"""v2.6.49 Bug #10 regression test — full-chromium binary detection when
Playwright's SDK-pinned revision (browsers.json) does NOT match the
actually-installed on-disk revision.

Scenario reproduced live during the 2026-07-30 Reward-pattern live test:
  * Playwright driver pinned rev = 1148 (checked via browsers.json)
  * `playwright install chromium --no-shell` fetched rev = 1208
  * On-disk directory = /pw-browsers/chromium-1208/
  * Pre-fix `_full_chromium_binary_path()` returned None because it only
    looked for `chromium-1148/` — so every RUT job silently fell back
    to chromium-headless-shell (weaker anti-detect stealth, hurting
    Smart Funnel Reward pattern success rate).

Post-fix: the helper falls back to scanning every `chromium-<rev>/`
directory under each search root and picking the highest-numbered rev
that actually contains a launchable binary. Headless-shell dirs are
explicitly excluded so we never conflate the two engines.
"""
from __future__ import annotations

import sys
from pathlib import Path


def test_full_chromium_scan_fallback_picks_stale_rev(tmp_path, monkeypatch):
    """Playwright pinned rev is missing but a higher rev is on disk → return it."""
    # Isolate: force our fake `/pw-browsers` root
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    # Fresh import to pick up the patched env
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import importlib

    import real_user_traffic  # noqa: E402
    importlib.reload(real_user_traffic)

    # Force the SDK-pinned rev to something that is NOT present on disk
    monkeypatch.setattr(real_user_traffic, "_chromium_revision_from_playwright", lambda: "1148")
    # Isolate search roots so the host's real /pw-browsers can't leak in
    monkeypatch.setattr(real_user_traffic, "_browsers_search_roots", lambda: [tmp_path])

    # Only create chromium-1208 on disk (mimicking the live-test finding)
    plat = real_user_traffic._pw_platform_dir()
    binary_name = real_user_traffic._chrome_binary_name()

    def _plant(rev: int) -> Path:
        d = tmp_path / f"chromium-{rev}" / plat
        d.mkdir(parents=True, exist_ok=True)
        bp = d / binary_name
        bp.write_text("#!/bin/sh\n:\n")
        bp.chmod(0o755)
        return bp

    # Plant a headless-shell dir too — MUST be ignored by the fallback
    (tmp_path / "chromium_headless_shell-1148" / plat).mkdir(parents=True, exist_ok=True)
    (tmp_path / "chromium_headless_shell-1148" / plat / binary_name).write_text("#!/bin/sh\n:\n")

    planted_1208 = _plant(1208)

    got = real_user_traffic._full_chromium_binary_path()
    assert got is not None, "fallback failed to find any full-chromium binary"
    assert got.resolve() == planted_1208.resolve(), (
        f"expected chromium-1208 binary, got {got}"
    )
    # Assertion 2: helper must NOT return the headless-shell binary
    assert "headless_shell" not in str(got)


def test_full_chromium_picks_highest_rev_when_multiple_exist(tmp_path, monkeypatch):
    """Multiple stale revs on disk → pick the highest one."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import importlib

    import real_user_traffic  # noqa: E402
    importlib.reload(real_user_traffic)

    monkeypatch.setattr(real_user_traffic, "_chromium_revision_from_playwright", lambda: "0000")
    monkeypatch.setattr(real_user_traffic, "_browsers_search_roots", lambda: [tmp_path])

    plat = real_user_traffic._pw_platform_dir()
    binary_name = real_user_traffic._chrome_binary_name()

    for rev in (1100, 1208, 1180):
        d = tmp_path / f"chromium-{rev}" / plat
        d.mkdir(parents=True, exist_ok=True)
        bp = d / binary_name
        bp.write_text("#!/bin/sh\n:\n")
        bp.chmod(0o755)

    got = real_user_traffic._full_chromium_binary_path()
    assert got is not None
    assert "chromium-1208" in str(got), f"expected highest rev 1208, got {got}"


def test_full_chromium_returns_none_when_nothing_installed(tmp_path, monkeypatch):
    """No chromium dirs at all → return None so headless-shell fallback fires."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import importlib

    import real_user_traffic  # noqa: E402
    importlib.reload(real_user_traffic)

    monkeypatch.setattr(real_user_traffic, "_chromium_revision_from_playwright", lambda: "1148")
    monkeypatch.setattr(real_user_traffic, "_browsers_search_roots", lambda: [tmp_path])

    # Only headless-shell present — must NOT be treated as full chromium
    plat = real_user_traffic._pw_platform_dir()
    binary_name = real_user_traffic._chrome_binary_name()
    (tmp_path / "chromium_headless_shell-1148" / plat).mkdir(parents=True, exist_ok=True)
    (tmp_path / "chromium_headless_shell-1148" / plat / binary_name).write_text(":\n")

    assert real_user_traffic._full_chromium_binary_path() is None
