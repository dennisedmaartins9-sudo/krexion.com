"""v2.7.105b — Proxy secrets redact, strict soft-launch, SOCKS, provider-first."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_sanitize_proxy_redacts_secrets():
    from browser_profile_module import _sanitize_proxy_for_public

    out = _sanitize_proxy_for_public(
        {
            "enabled": True,
            "server": "http://user:secret@gw.example.com:10000",
            "username": "user",
            "password": "secret",
            "raw_line": "gw.example.com:10000:user:secret",
            "provider_id": "abc",
        }
    )
    assert out.get("password") == ""
    assert out.get("has_password") is True
    assert "raw_line" not in out or not out.get("raw_line")
    assert "secret" not in str(out.get("server") or "")
    assert "gw.example.com" in str(out.get("server") or "")


def test_public_view_strips_proxy_password():
    from browser_profile_module import _public_view

    view = _public_view(
        {
            "id": "p1",
            "user_id": "u1",
            "name": "T",
            "proxy": {"enabled": True, "server": "http://h:1", "password": "pw", "username": "u"},
            "anti_detect": {"proxy_check_block_on_fail": True},
            "storage_state": {"cookies": [{"name": "a"}]},
        }
    )
    assert view["proxy"]["password"] == ""
    assert view["proxy"]["has_password"] is True
    assert view.get("strict_proxy") is True
    assert "storage_state" not in view


def test_parse_proxy_line_socks5():
    from browser_profile_module import _parse_proxy_line

    p = _parse_proxy_line("1.2.3.4:1080:user:pass", proxy_type="socks5")
    assert p["server"].startswith("socks5://")
    assert p["username"] == "user"
    assert p["password"] == "pass"

    p2 = _parse_proxy_line("socks5://u:p@5.6.7.8:1080")
    assert p2["server"] == "socks5://5.6.7.8:1080"


def test_strict_soft_launch_helper_raises():
    from fastapi import HTTPException
    from browser_profile_module import _raise_if_strict_soft_launch

    try:
        _raise_if_strict_soft_launch(
            {"anti_detect": {"proxy_check_block_on_fail": True}},
            reason="probe failed",
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "Strict proxy" in str(exc.detail)

    # Non-strict: no raise
    _raise_if_strict_soft_launch({"anti_detect": {}}, reason="x")


def test_health_marks_stale_proxy_check():
    from datetime import datetime, timedelta, timezone

    from browser_profile_health import compute_profile_health

    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    h = compute_profile_health(
        {
            "status": "idle",
            "proxy": {"enabled": True, "server": "http://h:1"},
            "exit_ip": "1.2.3.4",
            "last_proxy_check": {"ok": True, "checked_at": old, "exit_ip": "1.2.3.4"},
            "storage_state": {"cookies": [{}] * 10},
            "fingerprint_hash": "abc123",
        }
    )
    assert h.get("proxy_check_stale") is True
    assert any("stale" in str(i).lower() for i in (h.get("issues") or []))


def test_launcher_webrtc_force_and_provider_copy():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "WebRTC was set to 'real' while a proxy is enabled" in src
    assert "Proxy Providers credentials, or paste a manual line" in src


def test_frontend_provider_first_not_proxyjet_primary():
    fe = (
        ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "bp-proxy-mode-proxyjet" not in fe or "Legacy batch" in fe
    assert "any proxy provider" in fe.lower() or "Not locked to one vendor" in fe
    assert "bp-form-proxy-type" in fe
    assert "•••• saved" in fe or "has_password" in fe
