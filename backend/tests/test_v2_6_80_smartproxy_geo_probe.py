"""v2.6.80 — Smartproxy Smart Region (proxy.smartproxy.net) geo probe."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

_RUT = os.path.join(os.path.dirname(__file__), "..", "real_user_traffic.py")


def _src() -> str:
    with open(_RUT, encoding="utf-8") as f:
        return f.read()


def test_smartproxy_net_host_detected_in_source():
    src = _src()
    assert "smartproxy.net" in src
    assert "def _is_smartproxy_gateway_host(" in src
    assert "_is_decodo = _is_smartproxy_gateway_host(_probe_host)" in src
    assert "def _prefer_http_first_geo_probe(" in src


def test_minimal_ip_and_enrich_helpers_exist():
    src = _src()
    assert "async def _try_minimal_ip(" in src
    assert "async def _enrich_geo_from_exit_ip(" in src
    assert "api.ipify.org" in src
    assert "http://api.ipify.org/?format=text" in src
