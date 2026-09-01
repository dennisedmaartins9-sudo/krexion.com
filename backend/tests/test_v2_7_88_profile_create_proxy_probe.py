"""v2.7.88 — advanced-create provider proxy parse + gateway password hydrate."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_hydrate_prefers_gateway_password_for_provider():
    from browser_profile_module import hydrate_proxy_credentials_for_launch

    async def _run():
        with patch(
            "proxy_provider_module.get_provider_gateway_credentials",
            new=AsyncMock(
                return_value={
                    "username": "gw-user",
                    "password": "real-secret",
                    "gateway_host": "gw.dataimpulse.com",
                    "gateway_port": "10000",
                }
            ),
        ):
            return await hydrate_proxy_credentials_for_launch(
                "u1",
                {"id": "u1"},
                {
                    "provider_id": "pp1",
                    "server": "http://gw.dataimpulse.com:10000",
                    "username": "bad-user",
                    "password": "wrong",
                },
            )

    out = asyncio.run(_run())
    assert out["password"] == "real-secret"


def test_advanced_create_parse_uses_urlparse_password():
    from browser_profile_module import _parse_proxy_line

    parsed = _parse_proxy_line(
        "http://user__cr.us;sessid.abc:p%40ss%3Aword@gw.dataimpulse.com:10000"
    )
    assert parsed["password"] == "p@ss:word"
    assert parsed["server"] == "http://gw.dataimpulse.com:10000"


def test_build_proxy_probe_url_preserves_https_scheme():
    from browser_profile_module import _build_proxy_probe_url

    raw = (
        "https://user__cr.us;sessid.abc:secret@gw.dataimpulse.com:10000"
    )
    assert _build_proxy_probe_url(raw) == raw


def test_proxy_dict_to_probe_url_rebuilds_hydrated_creds():
    from browser_profile_module import _proxy_dict_to_probe_url

    url = _proxy_dict_to_probe_url(
        {
            "server": "https://gw.dataimpulse.com:10000",
            "username": "user__cr.us;sessid.abc",
            "password": "gateway-pwd",
        }
    )
    assert url.startswith("https://")
    assert "user__cr.us%3Bsessid.abc" in url
    assert "gateway-pwd" in url
    assert "@gw.dataimpulse.com:10000" in url


def test_proxy_dict_to_probe_url_uses_raw_line_when_no_server():
    from browser_profile_module import _proxy_dict_to_probe_url

    url = _proxy_dict_to_probe_url(
        {"raw_line": "http://gw.dataimpulse.com:10000"},
    )
    assert url == "http://gw.dataimpulse.com:10000"
