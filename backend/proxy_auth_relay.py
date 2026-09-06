"""
v2.7.137 — Local authenticated HTTP CONNECT relay for profile launches.

Why
---
Chromium / WebKit headed launches often show a native
"The proxy … requires a username and password" Sign-in dialog when
Playwright's ``proxy={server, username, password}`` auth is rejected,
mis-encoded, or ignored for some residential gateways (DataImpulse,
BestGo, etc.). AdsPower-class tools avoid that UI by pointing the
browser at a *local* unauthenticated proxy that injects
``Proxy-Authorization`` toward the real upstream.

This module starts a short-lived ``127.0.0.1:<ephemeral>`` CONNECT
relay bound to one profile session. The browser uses::

    {"server": "http://127.0.0.1:PORT"}   # no username/password

so Chromium never pops the Sign-in dialog. Wrong upstream credentials
still fail the page load — but as a clear network error, not a password
prompt that looks like a Krexion bug.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("proxy_auth_relay")

_CONNECT_RE = re.compile(rb"^CONNECT\s+([^\s:]+):(\d+)\s+HTTP/", re.I)
_REQ_LINE_RE = re.compile(rb"^(GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH)\s+(\S+)\s+HTTP/", re.I)


def _basic_auth_header(username: str, password: str) -> bytes:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Proxy-Authorization: Basic {token}\r\n".encode("ascii")


def _parse_upstream(server: str) -> Tuple[str, int, str]:
    raw = (server or "").strip()
    if not raw:
        raise ValueError("empty upstream server")
    if "://" not in raw:
        raw = f"http://{raw}"
    u = urlparse(raw)
    host = (u.hostname or "").strip()
    if not host:
        raise ValueError(f"bad upstream server: {server!r}")
    port = int(u.port or (443 if (u.scheme or "").lower() == "https" else 80))
    scheme = (u.scheme or "http").lower()
    if scheme not in ("http", "https", "socks5", "socks5h", "socks4"):
        scheme = "http"
    return host, port, scheme


async def _pipe(a: asyncio.StreamReader, b: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await a.read(65536)
            if not chunk:
                break
            b.write(chunk)
            await b.drain()
    except Exception:
        pass
    finally:
        try:
            b.close()
        except Exception:
            pass


class ProxyAuthRelay:
    """Local HTTP proxy that injects Basic auth toward one upstream."""

    def __init__(
        self,
        *,
        upstream_host: str,
        upstream_port: int,
        username: str,
        password: str,
        listen_host: str = "127.0.0.1",
    ) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = int(upstream_port)
        self.username = username
        self.password = password
        self.listen_host = listen_host
        self.listen_port = 0
        self._server: Optional[asyncio.AbstractServer] = None
        self._auth = _basic_auth_header(username, password)

    @property
    def browser_proxy(self) -> Dict[str, str]:
        return {"server": f"http://{self.listen_host}:{self.listen_port}"}

    async def start(self) -> "ProxyAuthRelay":
        self._server = await asyncio.start_server(
            self._handle,
            host=self.listen_host,
            port=0,
        )
        socks = self._server.sockets or []
        if not socks:
            raise RuntimeError("proxy auth relay failed to bind")
        self.listen_port = int(socks[0].getsockname()[1])
        logger.info(
            "[proxy-auth-relay] listening on %s:%s → %s:%s",
            self.listen_host,
            self.listen_port,
            self.upstream_host,
            self.upstream_port,
        )
        return self

    async def stop(self) -> None:
        srv = self._server
        self._server = None
        if srv is not None:
            srv.close()
            try:
                await srv.wait_closed()
            except Exception:
                pass

    async def _open_upstream(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection(self.upstream_host, self.upstream_port)

    async def _handle(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        try:
            head = await asyncio.wait_for(
                client_reader.readuntil(b"\r\n\r\n"),
                timeout=20.0,
            )
        except Exception:
            try:
                client_writer.close()
            except Exception:
                pass
            return

        m_conn = _CONNECT_RE.match(head)
        if m_conn:
            await self._handle_connect(
                client_reader,
                client_writer,
                head,
                m_conn.group(1).decode("ascii", "ignore"),
                int(m_conn.group(2)),
            )
            return

        m_req = _REQ_LINE_RE.match(head)
        if m_req:
            await self._handle_forward(client_reader, client_writer, head)
            return

        try:
            client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
        except Exception:
            pass
        try:
            client_writer.close()
        except Exception:
            pass

    async def _handle_connect(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        head: bytes,
        dest_host: str,
        dest_port: int,
    ) -> None:
        try:
            up_reader, up_writer = await self._open_upstream()
        except Exception as exc:
            try:
                msg = f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\nupstream connect failed: {exc}"
                client_writer.write(msg.encode("utf-8", "ignore"))
                await client_writer.drain()
            except Exception:
                pass
            try:
                client_writer.close()
            except Exception:
                pass
            return

        # Strip any client Proxy-Authorization; inject ours.
        lines = head.split(b"\r\n")
        out_lines = [lines[0]]
        for ln in lines[1:]:
            if not ln:
                continue
            low = ln.lower()
            if low.startswith(b"proxy-authorization:"):
                continue
            if low.startswith(b"proxy-connection:"):
                continue
            out_lines.append(ln)
        out_lines.append(self._auth.rstrip(b"\r\n"))
        out_lines.append(b"")
        out_lines.append(b"")
        try:
            up_writer.write(b"\r\n".join(out_lines))
            await up_writer.drain()
            # Read upstream response headers
            resp = await asyncio.wait_for(up_reader.readuntil(b"\r\n\r\n"), timeout=25.0)
            client_writer.write(resp)
            await client_writer.drain()
            # Tunnel bytes both ways after 200
            status_line = resp.split(b"\r\n", 1)[0]
            if b" 200 " not in status_line and not status_line.endswith(b" 200"):
                # Auth failure / reject — close after forwarding status
                try:
                    up_writer.close()
                except Exception:
                    pass
                try:
                    client_writer.close()
                except Exception:
                    pass
                return
            await asyncio.gather(
                _pipe(client_reader, up_writer),
                _pipe(up_reader, client_writer),
            )
        except Exception:
            try:
                up_writer.close()
            except Exception:
                pass
            try:
                client_writer.close()
            except Exception:
                pass

    async def _handle_forward(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        head: bytes,
    ) -> None:
        """Plain HTTP forward (rare for HTTPS sites; needed for http:// probes)."""
        try:
            up_reader, up_writer = await self._open_upstream()
        except Exception:
            try:
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
            except Exception:
                pass
            return
        lines = head.split(b"\r\n")
        out_lines = [lines[0]]
        for ln in lines[1:]:
            if not ln:
                continue
            low = ln.lower()
            if low.startswith(b"proxy-authorization:"):
                continue
            out_lines.append(ln)
        out_lines.append(self._auth.rstrip(b"\r\n"))
        out_lines.append(b"")
        out_lines.append(b"")
        try:
            up_writer.write(b"\r\n".join(out_lines))
            await up_writer.drain()
            await asyncio.gather(
                _pipe(client_reader, up_writer),
                _pipe(up_reader, client_writer),
            )
        except Exception:
            try:
                up_writer.close()
            except Exception:
                pass
            try:
                client_writer.close()
            except Exception:
                pass


async def start_proxy_auth_relay(
    *,
    server: str,
    username: str,
    password: str,
) -> ProxyAuthRelay:
    """Bind local relay for ``server`` using Basic auth credentials."""
    host, port, _scheme = _parse_upstream(server)
    user = (username or "").strip()
    pwd = (password or "").strip()
    if not user or not pwd:
        raise ValueError("username/password required for proxy auth relay")
    relay = ProxyAuthRelay(
        upstream_host=host,
        upstream_port=port,
        username=user,
        password=pwd,
    )
    await relay.start()
    return relay


def maybe_wrap_playwright_proxy(proxy_arg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sync helper used by tests — shape check only."""
    if not proxy_arg:
        return None
    server = str(proxy_arg.get("server") or "").strip()
    user = str(proxy_arg.get("username") or "").strip()
    pwd = str(proxy_arg.get("password") or "").strip()
    if not server or not user or not pwd:
        return dict(proxy_arg)
    # Placeholder — real wrap is async via start_proxy_auth_relay
    return {"server": server, "username": user, "password": pwd}
