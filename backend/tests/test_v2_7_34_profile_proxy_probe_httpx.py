"""v2.7.34 — Profile exit-IP probe must use httpx 0.28+ proxy API."""
from __future__ import annotations

import inspect
from pathlib import Path


def test_probe_profile_proxy_uses_httpx28_transport():
    src = Path(__file__).resolve().parents[1].joinpath("browser_profile_module.py").read_text(
        encoding="utf-8"
    )
    assert "async def _probe_profile_proxy(" in src
    assert "AsyncClient(proxies=" not in src
    # httpx 0.28+: either proxy= URL or httpx.Proxy(...) — never proxies=
    assert ("proxy=server" in src) or ("proxy=" in src and "AsyncClient(" in src) or (
        "httpx.Proxy(url=" in src
    )
    assert "async def _quick_http_exit_ip_via_proxy" in src


def test_httpx28_has_proxy_not_proxies_kwarg():
    import httpx

    params = inspect.signature(httpx.AsyncClient.__init__).parameters
    assert "proxy" in params
    assert "proxies" not in params
