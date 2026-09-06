"""v2.7.137 — Local proxy-auth relay + WebKit Playwright window branding."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_7_137():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.137")


def test_proxy_auth_relay_module_exists():
    src = (ROOT / "proxy_auth_relay.py").read_text(encoding="utf-8")
    assert "class ProxyAuthRelay" in src
    assert "Proxy-Authorization" in src
    assert "async def start_proxy_auth_relay" in src
    assert "browser_proxy" in src


def test_launcher_wires_local_auth_relay():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "start_proxy_auth_relay" in src
    assert "proxy auth relay ON" in src
    assert "proxy_arg = dict(_proxy_auth_relay.browser_proxy)" in src
    assert "proxy_auth_relay" in src
    assert "auth_relay_server" in src
    assert "v2.7.137 — Local auth relay" in src


def test_webkit_title_markers_include_playwright():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert '_title_markers = ["[WebKit]", "Safari", "Krexion", "Playwright"]' in src
    assert "stamp WebKit" in src


def test_window_icon_accepts_playwright_title_for_webkit():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "stock WebKit" in src
    assert "main window IS titled" in src
    assert "playwright.exe" in src
    assert "not include_webkit" in src
    assert 'title.strip().lower() == "playwright"' in src


def test_mobile_shell_accepts_playwright_engine_hwnd():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert 'if tlow == "playwright":' in src
    assert "return bool(webkit)" in src
    assert "Do not hide the WebKit engine titled" in src


def test_relay_injects_basic_auth_on_connect():
    """Spin a tiny upstream + relay and prove Proxy-Authorization is injected."""
    from proxy_auth_relay import start_proxy_auth_relay

    async def _run():
        got = {"raw": b""}

        async def _up_handle(reader, writer):
            try:
                data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
                got["raw"] = data
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            finally:
                writer.close()

        up = await asyncio.start_server(_up_handle, host="127.0.0.1", port=0)
        up_port = up.sockets[0].getsockname()[1]
        relay = await start_proxy_auth_relay(
            server=f"http://127.0.0.1:{up_port}",
            username="di_user",
            password="di_pass",
        )
        try:
            bp = relay.browser_proxy
            assert "username" not in bp and "password" not in bp
            assert bp["server"].startswith("http://127.0.0.1:")
            hostport = bp["server"].split("://", 1)[1]
            rh, rp = hostport.split(":")
            reader, writer = await asyncio.open_connection(rh, int(rp))
            writer.write(
                b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n"
            )
            await writer.drain()
            resp = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            assert b"200" in resp.split(b"\r\n", 1)[0]
            writer.close()
            token = base64.b64encode(b"di_user:di_pass").decode("ascii")
            assert f"Proxy-Authorization: Basic {token}".encode() in got["raw"]
            assert got["raw"].startswith(b"CONNECT example.com:443")
        finally:
            await relay.stop()
            up.close()
            await up.wait_closed()

    asyncio.run(_run())
