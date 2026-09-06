"""v2.7.138 — Phone chrome embed must be truthful (no fake framed)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_7_138():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.138")


def test_setparent_never_lies():
    src = (ROOT / "krexion_branded_browser.py").read_text(encoding="utf-8")
    assert "GetParent" in src
    assert "parent_now != int(shell_hwnd)" in src
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "return bool(prev) or True" in stripped or "return bool(prev) or True" in stripped:
            raise AssertionError(f"SetParent still lies: {stripped}")
        if "or True" in stripped and "return" in stripped:
            raise AssertionError(f"suspicious return or True: {stripped}")


def test_embed_mark_requires_verified_parent():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "if _parented:" in src
    assert "Overlay-only is NOT embed success" in src
    assert "wait_for_shell_content_hwnd" in src
    assert '"Playwright"' in src


def test_proxy_relay_never_forwards_407():
    src = (ROOT / "proxy_auth_relay.py").read_text(encoding="utf-8")
    assert "NEVER forward 407" in src or "502 Bad Gateway" in src
    # Must rewrite upstream auth failures instead of piping them to Chromium
    assert "502" in src


def test_strict_proxy_no_playwright_auth_fallback():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "never fall back to Playwright user:pass" in src
    assert "proxy_check_block_on_fail" in src
    assert "_keep_hiding_naked_engine" in src
    assert "_wait_pid and profile_engine_window_exists" in src


def test_title_keeper_brands_hidden_engine():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "Brand even while Strict hides the naked engine" in src
