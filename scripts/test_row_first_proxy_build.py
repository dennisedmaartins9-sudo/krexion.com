#!/usr/bin/env python3
"""Standalone regression test for ROW-FIRST proxy URL building.

Does not import real_user_traffic (Playwright). Validates the logic
that caused 100% probe failures when credentials were double-embedded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _gateway_base_username,
    _rotate_session_in_username,
)


def parse_proxy_line(line: str) -> dict:
    s = (line or "").strip()
    scheme = "http"
    if s.startswith("http://"):
        s = s[7:]
    elif s.startswith("https://"):
        s = s[8:]
        scheme = "https"
    user, pwd = None, None
    if "@" in s:
        auth, s = s.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
    host, port = s.split(":", 1)
    out = {"server": f"{scheme}://{host}:{port}", "raw": line.strip()}
    if user:
        out["username"] = user
    if pwd:
        out["password"] = pwd
    return out


def proxy_url_for_http(proxy: dict) -> str:
    server = (proxy.get("server") or "").strip()
    if "://" not in server:
        server = f"http://{server}"
    prefix, rest = server.split("://", 1)
    if "@" in rest:
        return server
    user = proxy.get("username") or ""
    pwd = proxy.get("password") or ""
    if user:
        return f"{prefix}://{quote(str(user), safe='')}:{quote(str(pwd), safe='')}@{rest}"
    return server


def build_state_targeted_proxy(base: dict, state_code: str, country: str = "US") -> dict:
    server = base.get("server") or ""
    scheme = "https" if server.startswith("https://") else "http"
    username = (base.get("username") or "").strip()
    password = base.get("password") or ""
    host = server.split("://", 1)[-1].split("@")[-1].split(":")[0]
    username = _gateway_base_username(username, host)
    targeted_user = _apply_targeting_to_username(
        username,
        host,
        {
            "country": country or "US",
            "state": state_code,
            "_want_sid": True,
            "force_replace": True,
        },
    )
    targeted_user = _rotate_session_in_username(targeted_user)
    port_part = server.split("@")[-1] if "@" in server else server.split("://", 1)[-1]
    new_server = f"{scheme}://{port_part}"
    out = dict(base)
    out["server"] = new_server
    out["username"] = targeted_user
    out["password"] = password
    return out


def run_tests() -> None:
    cases = [
        "http://user-sp123:secret@gate.decodo.com:7000",
        "http://user-sp123-country-us-state-us_nebraska-session-111:pass@gate.decodo.com:7000",
        "http://sp456:pass@us.smartproxy.net:3128",
        "http://smart-u0h51gc8hmdw_area-US_state-california_life-120_session-vMPdPfj97:bsNDKlwpUV4DpIDP@proxy.smartproxy.net:3120",
    ]
    failures = 0
    for line in cases:
        base = parse_proxy_line(line)
        out = build_state_targeted_proxy(base, "CA", "US")
        url = proxy_url_for_http(out)
        un = (out.get("username") or "").lower()

        checks = [
            ("@" not in out["server"], f"server must be host:port only, got {out['server']!r}"),
            (url.count("@") == 1, f"proxy URL must have exactly one @, got {url!r}"),
            ("us_california" in un or "_state-california" in un,
             f"username missing CA state encoding: {un!r}"),
            (not re.search(r"user:[^@]+@user:", url), f"double-auth in URL: {url!r}"),
        ]
        if "smart-" in line or "_area-" in line:
            checks.extend([
                (un.startswith("smart-"), f"Smart Region must keep smart- prefix: {un!r}"),
                ("_area-us" in un, f"missing _area-US: {un!r}"),
                ("_state-california" in un, f"missing _state-california: {un!r}"),
                ("-country-us" not in un, f"legacy DSL appended: {un!r}"),
                (not un.startswith("user-"), f"must not add user- prefix: {un!r}"),
                ("_life-" in un and "-120" not in un.split("_area-")[0], f"bad base before _area: {un!r}"),
                (re.search(r"smart-u0h51gc8hmdw_area-us_state-california_life-[0-9]+_session-", un),
                 f"expected panel-shaped username: {un!r}"),
            ])
        else:
            checks.extend([
                (un.startswith("user-"), f"Decodo username must start with user-: {un!r}"),
                ("nebraska" not in un, f"stale nebraska in username: {un!r}"),
            ])
        for ok, msg in checks:
            if not ok:
                print(f"FAIL [{line[:50]}...]: {msg}")
                failures += 1
            else:
                print(f"OK   {msg}")

    # Simulate old broken v2.6.57 behaviour — must fail this check
    broken = {
        "server": "http://user:pass@gate.decodo.com:7000",
        "username": "user",
        "password": "pass",
    }
    old_style_url = f"http://{broken['username']}:{broken['password']}@{broken['server'].split('://',1)[1]}"
    if old_style_url.count("@") > 1:
        print("OK   old double-embed pattern correctly detected as invalid")
    else:
        print(f"FAIL old pattern should double-embed: {old_style_url!r}")
        failures += 1

    if failures:
        print(f"\n{failures} assertion(s) failed")
        sys.exit(1)
    print("\nAll ROW-FIRST proxy URL build tests passed.")


if __name__ == "__main__":
    run_tests()
