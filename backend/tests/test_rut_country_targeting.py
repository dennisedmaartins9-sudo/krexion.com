"""RUT job country targeting — proxyjet_country must reach gateway lines + exit-IP gate."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _format_gateway_line,
    _rotate_session_in_username,
)
from real_user_traffic import (  # noqa: E402
    _geo_matches_target_country,
    _parse_proxy_line,
)


def test_bulk_gateway_line_includes_country_us():
    """Simulate get_proxy_lines_from_provider rotating_gateway branch."""
    cfg = {
        "gateway_host": "gate.smartproxy.com",
        "gateway_port": "7000",
        "username": "user-sp123",
        "password": "secret",
    }
    targeting = {"country": "US", "force_replace": True, "_want_sid": True}
    username_tpl = _apply_targeting_to_username(
        cfg["username"],
        cfg["gateway_host"],
        targeting,
        "Smartproxy",
    )
    gw_cfg = {**cfg, "username": username_tpl}
    line = _format_gateway_line(gw_cfg, "http", rotate_session=True)
    assert line
    assert "country-us" in line.lower() or "_area-us" in line.lower()


def test_geo_matches_target_country():
    assert _geo_matches_target_country({"country": "US"}, "US")
    assert not _geo_matches_target_country({"country": "PK"}, "US")
    assert _geo_matches_target_country({"country": "PK"}, "")


def test_legacy_smartproxy_username_gets_country_on_pick():
    from real_user_traffic import _build_state_targeted_proxy

    base = _parse_proxy_line("http://user-sp123:pass@gate.smartproxy.com:7000")
    a = _build_state_targeted_proxy(base, "", "US")
    b = _build_state_targeted_proxy(base, "", "US")
    assert a["username"] != b["username"]
    low = a["username"].lower()
    assert "country-us" in low or "_area-us" in low
