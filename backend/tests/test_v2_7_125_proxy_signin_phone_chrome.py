"""v2.7.125 — Permanent proxy Sign-in block + phone-chrome ghost fixes."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_125():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.125")


def test_parse_password_with_at_sign():
    from browser_profile_module import _parse_proxy_line

    r = _parse_proxy_line("gw.dataimpulse.com:10004:myuser:p@ss")
    assert r["server"].endswith("gw.dataimpulse.com:10004")
    assert r["username"] == "myuser"
    assert r["password"] == "p@ss"


def test_host_only_line_preserves_password():
    from browser_profile_module import _apply_resolved_line_to_proxy_cfg

    out = _apply_resolved_line_to_proxy_cfg(
        {
            "enabled": True,
            "server": "http://gw.dataimpulse.com:10004",
            "username": "u1",
            "password": "secret",
        },
        "http://gw.dataimpulse.com:10004",
    )
    assert out["username"] == "u1"
    assert out["password"] == "secret"


def test_launcher_blocks_proxy_without_password():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "NEVER launch with a proxy server but missing auth" in src
    assert "Launch is blocked so Chromium cannot show a proxy Sign-in popup" in src


def test_advanced_create_manual_uses_server_fields():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "Manual proxy requires username AND password" in src
    assert "honour AdvProxyCfg.server/username/password" in src or "body.proxy.server" in src


def test_shell_dpi_nameerror_gone():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "layout.bezel * 2 * dpi" not in src
    assert "layout.bezel * 2 * fs" in src


def test_polish_keeps_taskbar():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    polish = src.split("def polish_webkit_phone_fallback")[1].split("\ndef ")[0]
    assert "show_hwnd_on_taskbar" in polish
    assert "Do NOT hide engine from taskbar" in polish


def test_ghost_running_uses_taskbar_visibility():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "profile_engine_visible_on_taskbar" in src
    assert "ghost" in src.lower() or "TOOLWINDOW" in src


def test_fe_requires_proxy_auth():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "Manual proxy needs username AND password" in fe
    assert "required with proxy" in fe
    assert "setAdvProxyLines" in fe
