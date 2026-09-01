"""v2.7.84 — Profile proxy auth: provider resolve must keep gateway password."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_parse_proxy_line_urlparse_special_password():
    from browser_profile_module import _parse_proxy_line

    parsed = _parse_proxy_line(
        "http://user__cr.us;sessid.abc:p%40ss%3Aword@gw.dataimpulse.com:10000"
    )
    assert parsed["server"] == "http://gw.dataimpulse.com:10000"
    assert parsed["username"] == "user__cr.us;sessid.abc"
    assert parsed["password"] == "p@ss:word"


def test_format_gateway_line_quotes_credentials():
    from proxy_provider_module import _format_gateway_line

    line = _format_gateway_line(
        {
            "gateway_host": "gw.dataimpulse.com",
            "gateway_port": "10000",
            "username": "user__cr.us;sessid.abc",
            "password": "p@ss:word",
        },
        "http",
        rotate_session=False,
    )
    assert line
    from browser_profile_module import _parse_proxy_line

    parsed = _parse_proxy_line(line)
    assert parsed["password"] == "p@ss:word"
    assert parsed["username"] == "user__cr.us;sessid.abc"


def test_resolve_provider_line_hydrates_gateway_password():
    from browser_profile_module import resolve_profile_proxy_for_launch

    async def _run():
        with patch(
            "browser_profile_module._allocate_provider_proxy_lines",
            new=AsyncMock(
                return_value=["http://gw.dataimpulse.com:10000"]
            ),
        ), patch(
            "proxy_provider_module.get_provider_gateway_credentials",
            new=AsyncMock(
                return_value={
                    "username": "6450a120b611fd3d585d",
                    "password": "gateway-secret",
                    "gateway_host": "gw.dataimpulse.com",
                    "gateway_port": "10000",
                }
            ),
        ), patch(
            "proxy_provider_module.get_proxy_from_provider",
            new=AsyncMock(return_value={"proxy": "http://gw.dataimpulse.com:10000"}),
        ):
            return await resolve_profile_proxy_for_launch(
                "u1",
                {"id": "u1"},
                {
                    "provider_id": "pp_dataimpulse",
                    "enabled": True,
                    "username": "6450a120b611fd3d585d__cr.us;sessid.xyz",
                },
            )

    out = asyncio.run(_run())
    assert out["password"] == "gateway-secret"
    assert out["server"] == "http://gw.dataimpulse.com:10000"


def test_provider_update_preserves_password_when_blank():
    from unittest.mock import MagicMock

    from proxy_provider_module import ProxyProviderUpdate, _db, _update

    stored = {
        "id": "pp1",
        "config": {
            "gateway_host": "gw.dataimpulse.com",
            "gateway_port": "10000",
            "username": "user1",
            "password": "keep-me",
        },
    }

    async def _run():
        mock_coll = MagicMock()
        mock_coll.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        old_db = _db
        try:
            import proxy_provider_module as ppm

            ppm._db = MagicMock()
            ppm._db.user_proxy_providers = mock_coll
            with patch(
                "proxy_provider_module._get",
                new=AsyncMock(return_value=dict(stored)),
            ):
                body = ProxyProviderUpdate(
                    config={
                        "gateway_host": "gw.dataimpulse.com",
                        "gateway_port": "10000",
                        "username": "user1",
                        "password": "",
                    }
                )
                return await _update("u1", "pp1", body), mock_coll.update_one
        finally:
            import proxy_provider_module as ppm

            ppm._db = old_db

    out, update_one = asyncio.run(_run())
    assert out["config"]["password"] == "keep-me"
    saved_cfg = update_one.await_args.args[1]["$set"]["config"]
    assert saved_cfg["password"] == "keep-me"
