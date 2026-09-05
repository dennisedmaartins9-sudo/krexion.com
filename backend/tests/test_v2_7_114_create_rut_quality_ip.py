"""v2.7.114 — Create binds RUT-quality unique non-VPN state-matched exit IP."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def test_gates_reject_vpn_and_wrong_state():
    from browser_profile_module import _create_probe_passes_rut_gates

    ok, reason = _create_probe_passes_rut_gates(
        {
            "exit_ip": "203.0.113.10",
            "is_vpn": True,
            "vpn_reason": "hosting",
            "country": "US",
            "region": "AL",
        },
        {"country": "US", "state": "AL"},
    )
    assert ok is False
    assert "flagged" in reason.lower() or "vpn" in reason.lower()

    ok, reason = _create_probe_passes_rut_gates(
        {
            "exit_ip": "203.0.113.11",
            "is_vpn": False,
            "country": "US",
            "region": "CA",
        },
        {"country": "US", "state": "AL"},
    )
    assert ok is False
    assert "state" in reason.lower()


def test_gates_accept_clean_matching_state():
    from browser_profile_module import _create_probe_passes_rut_gates

    ok, reason = _create_probe_passes_rut_gates(
        {
            "exit_ip": "203.0.113.12",
            "is_vpn": False,
            "is_low_quality": False,
            "country": "US",
            "region": "AL",
        },
        {"country": "US", "state": "AL"},
    )
    assert ok is True
    assert reason == ""


def test_bind_rejects_vpn_then_accepts_clean(monkeypatch):
    from browser_profile_module import _bind_unique_exit_ip_at_create

    calls = {"n": 0}

    async def _probe(doc, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "ok": True,
                "exit_ip": "198.51.100.1",
                "is_vpn": True,
                "vpn_reason": "datacenter",
                "country": "US",
                "region": "AL",
            }
        return {
            "ok": True,
            "exit_ip": "198.51.100.2",
            "is_vpn": False,
            "country": "US",
            "region": "AL",
        }

    async def _run():
        doc = {
            "id": "prof-rut-1",
            "name": "AL-1",
            "proxy": {
                "enabled": True,
                "provider_id": "pp1",
                "server": "http://gw.dataimpulse.com:10000",
                "username": "u",
                "password": "p",
            },
        }
        with patch(
            "browser_profile_module._prepare_proxy_for_profile_create",
            side_effect=lambda d: None,
        ), patch(
            "browser_profile_module.proxy_is_active",
            return_value=True,
        ), patch(
            "browser_profile_module._allocate_provider_proxy_lines",
            new=AsyncMock(return_value=["http://u:p@gw.dataimpulse.com:10000"]),
        ), patch(
            "browser_profile_module._apply_resolved_line_to_proxy_cfg",
            side_effect=lambda cfg, line, provider_id="": {
                **cfg,
                "server": "http://gw.dataimpulse.com:10000",
                "username": "u__cr.us;state.alabama",
                "password": "p",
                "provider_id": provider_id or cfg.get("provider_id"),
                "raw_line": line,
            },
        ), patch(
            "browser_profile_module._apply_create_geo_targeting",
            side_effect=lambda cfg, t, variant_index=0: cfg,
        ), patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=AsyncMock(side_effect=lambda u, usr, cfg: cfg),
        ), patch(
            "browser_profile_module._probe_profile_proxy",
            new=_probe,
        ), patch(
            "browser_profile_module._assert_unique_team_profile_ip",
            new=AsyncMock(side_effect=lambda *a, **k: a[1]),
        ), patch(
            "browser_profile_module._canonical_proxy_raw_line",
            return_value="http://u:p@gw.dataimpulse.com:10000",
        ), patch(
            "browser_profile_module._rotate_manual_proxy_session",
            side_effect=lambda cfg: cfg,
        ):
            return await _bind_unique_exit_ip_at_create(
                "uid1",
                {"id": "uid1"},
                doc,
                used_ips=set(),
                batch_assigned=set(),
                targeting={"country": "US", "state": "AL"},
                max_retries=4,
            ), doc

    bind, doc = asyncio.run(_run())
    assert bind.get("ok") is True
    assert bind.get("exit_ip") == "198.51.100.2"
    assert doc.get("proxy", {}).get("sticky_session") is True
    assert doc.get("proxy", {}).get("exit_ip_verified_at_create") is True
    assert calls["n"] >= 2


def test_bind_no_soft_defer_on_empty_probe():
    from browser_profile_module import _bind_unique_exit_ip_at_create

    async def _run():
        doc = {
            "id": "prof-empty",
            "name": "E",
            "proxy": {
                "enabled": True,
                "provider_id": "pp1",
                "server": "http://ca.rrp.bestgo.work:10000",
                "username": "u",
                "password": "p",
            },
        }
        with patch(
            "browser_profile_module._prepare_proxy_for_profile_create",
            side_effect=lambda d: None,
        ), patch(
            "browser_profile_module.proxy_is_active",
            return_value=True,
        ), patch(
            "browser_profile_module._allocate_provider_proxy_lines",
            new=AsyncMock(return_value=["http://u:p@ca.rrp.bestgo.work:10000"]),
        ), patch(
            "browser_profile_module._apply_resolved_line_to_proxy_cfg",
            side_effect=lambda cfg, line, provider_id="": {
                **cfg,
                "server": "http://ca.rrp.bestgo.work:10000",
                "username": "u",
                "password": "p",
            },
        ), patch(
            "browser_profile_module._apply_create_geo_targeting",
            side_effect=lambda cfg, t, variant_index=0: cfg,
        ), patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=AsyncMock(side_effect=lambda u, usr, cfg: cfg),
        ), patch(
            "browser_profile_module._probe_profile_proxy",
            new=AsyncMock(
                return_value={
                    "ok": False,
                    "exit_ip": "",
                    "error": "Exit IP check failed — IP endpoints returned nothing",
                }
            ),
        ), patch(
            "browser_profile_module._rotate_manual_proxy_session",
            side_effect=lambda cfg: cfg,
        ):
            return await _bind_unique_exit_ip_at_create(
                "uid1",
                {"id": "uid1"},
                doc,
                used_ips=set(),
                batch_assigned=set(),
                targeting={"country": "US", "state": "AL"},
                max_retries=2,
            )

    bind = asyncio.run(_run())
    assert bind.get("ok") is False
    assert not bind.get("deferred")


def test_launch_prefers_create_verified_sticky():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def _ensure_profile_launch_proxy")
    end = src.index("\nasync def ", start + 10)
    block = src[start:end]
    assert "exit_ip_verified_at_create" in block
    assert "reused create-verified" in block


def test_frontend_skip_toast_still_clear():
    fe = (
        ROOT.parents[0]
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "unique exit IP unavailable" in fe or "skipped" in fe


def test_version_2_7_114():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.114")
