"""v2.7.109 — Create-time unique exit-IP probe hardened for DataImpulse."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_prefer_http_first_detects_dataimpulse():
    from real_user_traffic import _prefer_http_first_geo_probe

    assert _prefer_http_first_geo_probe("gw.dataimpulse.com") is True
    assert _prefer_http_first_geo_probe("gate.smartproxy.com") is True
    assert _prefer_http_first_geo_probe("proxy.oxylabs.io") is True
    assert _prefer_http_first_geo_probe("example.com") is False


def test_minimal_ip_urls_are_http_first():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    start = src.index("async def _try_minimal_ip")
    end = src.index("\n    try:", start)
    block = src[start:end]
    assert "http://api.ipify.org/?format=text" in block
    assert "http://checkip.amazonaws.com/" in block
    # HTTPS must not be the first probe URL
    first_url = block.split("for url in (")[1].split(",")[0]
    assert "http://" in first_url
    assert "https://" not in first_url


def test_probe_skips_tls_for_http_first_hosts():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "_http_first = _prefer_http_first_geo_probe(_probe_host)" in src
    assert "not _http_first" in src
    assert "ok = await _try_minimal_ip(cli)" in src


def test_probe_profile_has_quick_http_fallback():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "async def _quick_http_exit_ip_via_proxy" in src
    assert "quick_http_fallback" in src
    assert "Exit IP check failed" in src


def test_quick_http_exit_ip_parses_plain_body():
    from browser_profile_module import _quick_http_exit_ip_via_proxy

    class _Resp:
        status_code = 200
        text = "203.0.113.44\n"

    class _Cli:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Resp()

    async def _run():
        with patch("real_user_traffic._proxy_url_for_http", return_value="http://u:p@gw.dataimpulse.com:10000"), patch(
            "httpx.AsyncClient", return_value=_Cli()
        ):
            return await _quick_http_exit_ip_via_proxy(
                {"server": "http://gw.dataimpulse.com:10000", "username": "u", "password": "p"}
            )

    assert asyncio.run(_run()) == "203.0.113.44"


def test_probe_profile_uses_fallback_when_geo_fails():
    from browser_profile_module import _probe_profile_proxy

    async def _run():
        with patch(
            "browser_profile_module._finalize_proxy_cfg_for_launch",
            new=AsyncMock(side_effect=lambda u, usr, cfg: cfg),
        ), patch(
            "real_user_traffic._proxy_url_for_http",
            return_value="http://u:p@gw.dataimpulse.com:10000",
        ), patch(
            "real_user_traffic._host_from_proxy_server",
            return_value="gw.dataimpulse.com",
        ), patch(
            "real_user_traffic._probe_proxy_geo",
            new=AsyncMock(return_value={"ok": False, "exit_ip": "", "probe_error": "geo endpoints returned no IP"}),
        ), patch(
            "browser_profile_module._quick_http_exit_ip_via_proxy",
            new=AsyncMock(return_value="198.51.100.9"),
        ):
            return await _probe_profile_proxy(
                {
                    "proxy": {
                        "enabled": True,
                        "server": "http://gw.dataimpulse.com:10000",
                        "username": "u",
                        "password": "p",
                    },
                    "user_id": "uid1",
                },
                {"id": "uid1"},
            )

    out = asyncio.run(_run())
    assert out["ok"] is True
    assert out["exit_ip"] == "198.51.100.9"
    assert out.get("probe_path") == "quick_http_fallback"


def test_version_2_7_109():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.109")
