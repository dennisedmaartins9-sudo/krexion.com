"""v2.7.126 — Krexion phone chrome must launch; no plain Chromium/WebKit under Strict."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_126():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.126")


def test_strict_aborts_plain_engine_as_krexion_design():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "plain Chromium/WebKit will not be shown as Krexion design." in src
    assert "strict_mobile_shell and require_embed" in src
    # Old soft-continue gate (abort only when engine DOWN) must be gone
    assert "strict_mobile_shell and not _engine_up" not in src


def test_post_nav_restarts_shell_when_not_embedded():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert (
        'allow_restart=not bool(_launch_ui_meta.get("mobile_shell_embedded"))' in src
    )


def test_hwnd_match_minibrowser_empty_title():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    chunk = src.split("def _is_engine_content_hwnd")[1].split("\ndef ")[0]
    assert "chrome_widgetwin" in chunk
    assert "about:blank" in chunk
    assert "minibrowser" in chunk.lower()


def test_frontend_honesty_still_warns_when_off():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(
        encoding="utf-8"
    )
    assert "phone chrome off / unavailable" in fe
    assert "strict_mobile_shell" in fe
