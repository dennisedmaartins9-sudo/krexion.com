"""v2.7.112 — BestGo create exit-IP probe + soft-defer when IP endpoints flake."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_prefer_http_first_detects_bestgo():
    from real_user_traffic import _prefer_http_first_geo_probe

    assert _prefer_http_first_geo_probe("ca.rrp.bestgo.work") is True
    assert _prefer_http_first_geo_probe("us.rrp.bestgo.work") is True
    assert _prefer_http_first_geo_probe("gw.dataimpulse.com") is True
    assert _prefer_http_first_geo_probe("example.com") is False


def test_rotating_gateway_detects_bestgo_rrp():
    from real_user_traffic import _detect_rotating_gateway

    assert _detect_rotating_gateway("ca.rrp.bestgo.work", "") is True
    assert _detect_rotating_gateway("resi.example.net", "user-session-abc") is True


def test_extract_plain_ip_from_html_noise():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "v2.7.112" in src or "BestGo / residential gateways sometimes wrap" in src
    assert "bestgo.work" in src
    assert '"rrp."' in src or '"rrp.",' in src


def test_friendly_error_mentions_bestgo():
    from browser_profile_module import _friendly_proxy_probe_error

    msg = _friendly_proxy_probe_error(
        "geo endpoints returned no IP",
        gateway_host="ca.rrp.bestgo.work",
    )
    assert "Exit IP check failed" in msg
    assert "ca.rrp.bestgo.work" in msg
    assert "BestGo" in msg


def test_probe_uses_username_for_http_first():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "_prefer_http_first_geo_probe(_probe_host, _proxy_user)" in src


def test_bind_hard_fails_when_empty_ip_endpoints():
    """v2.7.114 — soft-defer removed; empty IP endpoints skip the profile."""
    from browser_profile_module import _bind_unique_exit_ip_at_create

    async def _run():
        doc = {
            "id": "prof-bestgo-1",
            "name": "Krexion-iPhone16Pro-US-0905-CWVF",
            "proxy": {
                "enabled": True,
                "provider_id": "pp-bestgo",
                "server": "http://ca.rrp.bestgo.work:10000",
                "username": "user-country-us",
                "password": "secret",
            },
        }
        used: set = set()
        batch: set = set()
        with patch(
            "browser_profile_module._prepare_proxy_for_profile_create",
            side_effect=lambda d: None,
        ), patch(
            "browser_profile_module.proxy_is_active",
            return_value=True,
        ), patch(
            "browser_profile_module._allocate_provider_proxy_lines",
            new=AsyncMock(
                return_value=[
                    "http://user-country-us:secret@ca.rrp.bestgo.work:10000"
                ]
            ),
        ), patch(
            "browser_profile_module._apply_resolved_line_to_proxy_cfg",
            side_effect=lambda cfg, line, provider_id="": {
                **cfg,
                "server": "http://ca.rrp.bestgo.work:10000",
                "username": "user-country-us",
                "password": "secret",
                "provider_id": provider_id or cfg.get("provider_id"),
                "raw_line": line,
            },
        ), patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=AsyncMock(side_effect=lambda u, usr, cfg: cfg),
        ), patch(
            "browser_profile_module._probe_profile_proxy",
            new=AsyncMock(
                return_value={
                    "ok": False,
                    "exit_ip": "",
                    "error": (
                        "Exit IP check failed via 'ca.rrp.bestgo.work' — "
                        "gateway reachable but IP endpoints returned nothing."
                    ),
                }
            ),
        ), patch(
            "browser_profile_module._rotate_manual_proxy_session",
            side_effect=lambda cfg: cfg,
        ), patch(
            "browser_profile_module._canonical_proxy_raw_line",
            return_value="http://user-country-us:secret@ca.rrp.bestgo.work:10000",
        ):
            return await _bind_unique_exit_ip_at_create(
                "uid1",
                {"id": "uid1"},
                doc,
                used_ips=used,
                batch_assigned=batch,
                max_retries=2,
            ), doc

    bind, doc = asyncio.run(_run())
    assert bind.get("ok") is False
    assert not bind.get("deferred")
    assert not bind.get("exit_ip")
    assert not doc.get("exit_ip_deferred")
    assert "returned nothing" in str(bind.get("reason") or "").lower() or "exit ip" in str(bind.get("reason") or "").lower()


def test_advanced_create_returns_deferred_count():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def advanced_create")
    end = src.index("@router.post(\"/bulk-delete\")", start)
    block = src[start:end]
    assert "deferred_count" in block
    assert "deferred_exit_ip_count" in block
    assert "proxy_bind_deferred" in block


def test_frontend_toasts_deferred_create():
    fe = (
        ROOT.parents[0]
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "deferred_exit_ip_count" in fe
    assert "exit IP check deferred" in fe


def test_version_2_7_112():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.112")
