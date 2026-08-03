"""Provider state username encoding — permanent state_fmt map."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy_provider_module import (  # noqa: E402
    _PROVIDER_PROFILES,
    _apply_targeting_to_username,
    _detect_profile,
    _format_state_for_profile,
)


def _prof(name: str):
    for p in _PROVIDER_PROFILES:
        if p["name"] == name:
            return p
    raise KeyError(name)


def test_smartproxy_ca_us_california():
    p = _prof("Smartproxy / Decodo")
    assert _format_state_for_profile(p, "CA") == "us_california"
    user = _apply_targeting_to_username(
        "user-sp123", "gate.smartproxy.com", {"country": "US", "state": "CA"}, "Smartproxy"
    )
    assert "us_california" in user.lower()


def test_packetstream_ca_code():
    p = _prof("PacketStream")
    assert _format_state_for_profile(p, "California") == "CA"


def test_brightdata_slug():
    p = _prof("Bright Data")
    assert _format_state_for_profile(p, "NE") == "nebraska"


def test_dataimpulse_lower_code():
    p = _prof("DataImpulse")
    assert _format_state_for_profile(p, "TX") == "tx"


def test_unknown_provider_defaults_slug():
    assert _format_state_for_profile(None, "CA") == "california"
    assert _detect_profile("custom-proxy.example.com", "My Residential")


def test_all_profiles_have_state_fmt():
    for p in _PROVIDER_PROFILES:
        assert p.get("state_fmt"), f"missing state_fmt on {p['name']}"


def test_force_replace_strips_stale_state_and_reapplies():
    """ROW-FIRST must replace wrong embedded state, not skip append."""
    stale = "user-sp123-country-us-state-us_texas-session-999888777"
    user = _apply_targeting_to_username(
        stale,
        "gate.decodo.com",
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
        "Smartproxy",
    )
    low = user.lower()
    assert "us_california" in low
    assert "us_texas" not in low
    assert low.startswith("user-")


def test_gateway_base_username_strips_geo_and_session():
    from proxy_provider_module import _gateway_base_username

    base = _gateway_base_username(
        "sp123-country-us-state-us_nebraska-session-111",
        "gate.decodo.com",
    )
    assert base.lower() == "user-sp123"

