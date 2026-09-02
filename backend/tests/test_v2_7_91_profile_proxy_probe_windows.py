"""v2.7.91 — Windows-safe provider proxy probe (DataImpulse ; in username)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_proxy_url_for_http_reencodes_embedded_semicolon_username():
    from real_user_traffic import _proxy_url_for_http

    raw = "http://user__cr.us;sessid.abc:secret@gw.dataimpulse.com:10000"
    url = _proxy_url_for_http({"server": raw})
    assert "user__cr.us%3Bsessid.abc" in url
    assert "@gw.dataimpulse.com:10000" in url


def test_proxy_dict_to_probe_url_reencodes_embedded_server_creds():
    from browser_profile_module import _proxy_dict_to_probe_url

    url = _proxy_dict_to_probe_url(
        {"server": "http://login__cr.us;sessid.x:pass@gw.dataimpulse.com:823"}
    )
    assert "login__cr.us%3Bsessid.x" in url
    assert "@gw.dataimpulse.com:823" in url


def test_friendly_probe_error_for_getaddrinfo():
    from browser_profile_module import _friendly_proxy_probe_error

    msg = _friendly_proxy_probe_error(
        "[Errno 11001] getaddrinfo failed",
        "gw.dataimpulse.com",
    )
    assert "gw.dataimpulse.com" in msg
    assert "Proxies" in msg
