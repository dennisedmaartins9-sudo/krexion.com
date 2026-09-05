"""v2.7.106 — Create binds unique exit IP; mobile shell embed hardening."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_proxy_hydrates_without_stale_exit_ip():
    from browser_profile_module import _prepare_proxy_for_profile_create

    doc = {
        "proxy": {
            "enabled": True,
            "provider_id": "pp-1",
            "server": "",
            "exit_ip": "1.2.3.4",
        },
        "exit_ip": "1.2.3.4",
    }
    _prepare_proxy_for_profile_create(doc)
    assert doc["proxy"]["smart_session"] is True
    assert doc["proxy"]["provider_id"] == "pp-1"
    assert "exit_ip" not in doc["proxy"]
    assert "exit_ip" not in doc


def test_advanced_create_binds_unique_ip_helper():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def advanced_create")
    end = src.index("@router.post(\"/bulk-delete\")", start)
    block = src[start:end]
    assert "_bind_unique_exit_ip_at_create" in block
    assert "unique_ips_bound" in block
    assert "skipped_profiles" in block
    # v2.7.112+ — deferred flag is dynamic (soft-defer when IP endpoints flake)
    assert "proxy_bind_deferred" in block
    assert "deferred_count" in block or "deferred_exit_ip_count" in block

def test_create_profile_requires_unique_ip_when_proxy_on():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def create_profile")
    end = src.index("@router.get(\"/device-catalog\")", start)
    block = src[start:end]
    assert "_bind_unique_exit_ip_at_create" in block
    assert "Profile was NOT saved" in block


def test_bind_unique_exit_ip_at_create_success():
    import asyncio
    from browser_profile_module import _bind_unique_exit_ip_at_create

    doc = {
        "id": "p-test-1",
        "name": "T1",
        "proxy": {
            "enabled": True,
            "server": "http://gw.dataimpulse.com:10000",
            "username": "user__cr.us;sessid.abc",
            "password": "secret",
        },
    }
    used: set = set()
    batch: set = set()

    async def _run():
        with patch(
            "browser_profile_module._probe_profile_proxy",
            new=AsyncMock(
                return_value={
                    "exit_ip": "203.0.113.10",
                    "ok": True,
                    "is_vpn": False,
                    "country": "US",
                    "region": "NY",
                }
            ),
        ), patch(
            "browser_profile_module._assert_unique_team_profile_ip",
            new=AsyncMock(return_value="203.0.113.10"),
        ), patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=AsyncMock(side_effect=lambda u, usr, cfg: cfg),
        ), patch(
            "browser_profile_module.hydrate_proxy_credentials",
            side_effect=lambda cfg: cfg,
        ), patch(
            "browser_profile_module._apply_create_geo_targeting",
            side_effect=lambda cfg, t, variant_index=0: cfg,
        ):
            return await _bind_unique_exit_ip_at_create(
                "uid1", {"id": "uid1"}, doc, used_ips=used, batch_assigned=batch,
                targeting={"country": "US"},
            )

    out = asyncio.run(_run())
    assert out["ok"] is True
    assert out["exit_ip"] == "203.0.113.10"
    assert doc["exit_ip"] == "203.0.113.10"
    assert doc["proxy"]["sticky_session"] is True


def test_bind_unique_skips_on_duplicate_static():
    import asyncio
    from browser_profile_module import _bind_unique_exit_ip_at_create
    from fastapi import HTTPException

    doc = {
        "id": "p-test-2",
        "name": "T2",
        "proxy": {
            "enabled": True,
            "server": "http://203.0.113.50:8080",
            "username": "u",
            "password": "p",
        },
    }
    used = {"203.0.113.99"}
    batch: set = set()

    async def _run():
        with patch(
            "browser_profile_module._probe_profile_proxy",
            new=AsyncMock(
                return_value={
                    "exit_ip": "203.0.113.99",
                    "ok": True,
                    "is_vpn": False,
                    "country": "US",
                    "region": "TX",
                }
            ),
        ), patch(
            "browser_profile_module._assert_unique_team_profile_ip",
            new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Duplicate")),
        ), patch(
            "browser_profile_module._is_rotating_gateway_proxy",
            return_value=False,
        ), patch(
            "browser_profile_module.hydrate_proxy_credentials",
            side_effect=lambda cfg: cfg,
        ), patch(
            "browser_profile_module._apply_create_geo_targeting",
            side_effect=lambda cfg, t, variant_index=0: cfg,
        ):
            return await _bind_unique_exit_ip_at_create(
                "uid1", {"id": "uid1"}, doc, used_ips=used, batch_assigned=batch,
                targeting={"country": "US"},
                max_retries=2,
            )

    out = asyncio.run(_run())
    assert out["ok"] is False
    assert "Duplicate" in out["reason"] or "unique" in out["reason"].lower()


def test_shell_engine_hwnd_uses_iswindow_not_visible_only():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "def _is_engine_content_hwnd" in src
    chunk = src.split("def _is_engine_content_hwnd")[1].split("def _set_window_pos")[0]
    # Gate on IsWindow (minimized OK); must not call IsWindowVisible
    assert "user32.IsWindow(hwnd)" in chunk
    assert "user32.IsWindowVisible(hwnd)" not in chunk
    assert "chromium" in chunk
    assert "force_discover_and_mark_embedded" in src
    assert "Krexion Orbit" in src


def test_launcher_force_discover_before_strict_abort():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "force_discover_and_mark_embedded" in src
    assert "_embed_wait = 45.0 if _profile_engine == \"webkit\" else 30.0" in src


def test_frontend_unique_ip_create_copy():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    src = fe.read_text(encoding="utf-8")
    assert "Unique exit IP verified before save" in src
    assert "unique_ips_bound" in src
    assert "skipped" in src


def test_version_2_7_106():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.106")
