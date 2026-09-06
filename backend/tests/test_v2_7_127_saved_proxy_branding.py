"""v2.7.127 — Saved-proxy Sign-in gate + AdsPower-style Krexion branding."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_127():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.127")


def test_saved_create_requires_proxy_auth():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "Saved proxy is missing username AND password after parse" in src
    assert 'proxy_mode == "saved"' in src


def test_soft_launch_ready_needs_auth_not_just_rotating_host():
    from browser_profile_module import _proxy_ready_for_soft_launch

    assert not _proxy_ready_for_soft_launch(
        {"server": "http://gw.dataimpulse.com:10009"}
    )
    assert not _proxy_ready_for_soft_launch(
        {"server": "http://gw.dataimpulse.com:10009", "username": "u"}
    )
    assert _proxy_ready_for_soft_launch(
        {
            "server": "http://gw.dataimpulse.com:10009",
            "username": "u",
            "password": "p",
        }
    )
    assert _proxy_ready_for_soft_launch(
        {"server": "http://gw.dataimpulse.com:10009", "provider_id": "pp-1"}
    )


def test_fe_rejects_host_only_saved_proxy():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(
        encoding="utf-8"
    )
    assert "Saved proxy needs full auth" in fe
    assert "host-only lines cause Chromium Sign-in" in fe


def test_launcher_rehydrates_and_blocks_signin():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "hydrate_proxy_credentials" in src
    assert "username/password is missing" in src
    assert "require_embed=bool(strict_mobile_shell)" in src


def test_shell_host_sets_krexion_appid():
    src = (ROOT / "krexion_mobile_shell_host.py").read_text(encoding="utf-8")
    assert "SetCurrentProcessExplicitAppUserModelID" in src
    assert "Krexion.PhoneChrome" in src


def test_taskbar_hides_playwright_helpers():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert '== "playwright"' in src
    assert "AdsPower-style" in src or "phone chrome" in src.lower()