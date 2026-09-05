"""v2.7.113 — Manual DataImpulse launch keeps server URL + geo sessid rotate."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]

DI_LINE = (
    "6450a120b611fd3d585d__cr.us;state.alabama:9a042f96d62aa99d@"
    "gw.dataimpulse.com:10000"
)


def test_parse_dataimpulse_semicolon_username():
    from browser_profile_module import _parse_proxy_line

    p = _parse_proxy_line(DI_LINE)
    assert p["server"] == "http://gw.dataimpulse.com:10000"
    assert p["username"] == "6450a120b611fd3d585d__cr.us;state.alabama"
    assert p["password"] == "9a042f96d62aa99d"


def test_rotate_manual_preserves_dataimpulse_geo():
    from browser_profile_module import _rotate_manual_proxy_session

    out = _rotate_manual_proxy_session(
        {
            "server": "http://gw.dataimpulse.com:10000",
            "username": "6450a120b611fd3d585d__cr.us;state.alabama",
            "password": "secret",
        }
    )
    user = out.get("username") or ""
    assert "__cr.us" in user
    assert "state.alabama" in user
    assert "sessid." in user.lower()
    assert out.get("server") == "http://gw.dataimpulse.com:10000"


def test_ensure_launch_keeps_manual_rotating_server():
    from browser_profile_module import _ensure_profile_launch_proxy, _parse_proxy_line

    parsed = _parse_proxy_line(DI_LINE)

    async def _run():
        doc = {
            "id": "prof-di-1",
            "name": "Krexion-GalaxyS24-US-0905-SCI7",
            "user_id": "uid1",
            "proxy": {
                "enabled": True,
                "server": parsed["server"],
                "username": parsed["username"],
                "password": parsed["password"],
                "raw_line": DI_LINE,
            },
        }

        async def _resolve(uid, user, proxy_cfg, **kw):
            return dict(proxy_cfg)

        async def _fin(uid, user, cfg):
            return dict(cfg)

        async def _bind(uid, user, doc, proxy_cfg, **kw):
            return dict(proxy_cfg)

        with patch(
            "browser_profile_module.resolve_profile_proxy_for_launch",
            new=_resolve,
        ), patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=_fin,
        ), patch(
            "browser_profile_module._defer_launch_proxy_probe",
            return_value=True,
        ), patch(
            "browser_profile_module._load_team_profile_used_ips",
            new=AsyncMock(return_value=set()),
        ), patch(
            "browser_profile_module._profile_provider_targeting",
            return_value={},
        ), patch(
            "browser_profile_module._best_effort_bind_exit_ip_at_launch",
            new=_bind,
        ):
            return await _ensure_profile_launch_proxy(
                "uid1", {"id": "uid1"}, doc
            )

    out = asyncio.run(_run())
    assert "gw.dataimpulse.com" in (out.get("server") or "")
    assert "__cr.us" in (out.get("username") or "")
    assert "state.alabama" in (out.get("username") or "")


def test_ensure_source_manual_branch():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def _ensure_profile_launch_proxy")
    end = src.index("\nasync def ", start + 10)
    block = src[start:end]
    assert "_manual_rotating" in block
    assert "_rotate_manual_proxy_session" in block
    assert "_fresh_rotating" in block


def test_version_2_7_113():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.113")
