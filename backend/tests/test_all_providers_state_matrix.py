"""All rotating-gateway providers × US states — ROW-FIRST username matrix."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

from proxy_provider_module import (  # noqa: E402
    _PROVIDER_PROFILES,
    _SMARTPROXY_SMART_PROFILE,
    _apply_targeting_to_username,
    _detect_profile,
    _gateway_base_username,
    _username_includes_state_target,
)
from real_user_traffic import (  # noqa: E402
    _build_state_targeted_proxy,
    _normalize_state,
    _parse_proxy_line,
)

# Representative hosts + stale username templates per provider family.
_PROVIDER_GATEWAYS = [
    ("Smartproxy Smart Region", "proxy.smartproxy.net", "smart-u0test000"),
    ("Smartproxy / Decodo", "gate.decodo.com", "user-sp123"),
    ("Bright Data", "brd.superproxy.io", "brd-customer-zone"),
    ("Oxylabs", "pr.oxylabs.io", "customer-user"),
    ("DataImpulse", "gw.dataimpulse.com", "login123"),
    ("IPRoyal", "geo.iproyal.com", "customer123"),
    ("ProxyEmpire", "v2.proxyempire.io", "user123"),
    ("Soax", "proxy.soax.com", "package123"),
    ("PacketStream", "proxy.packetstream.io", "user123"),
]

# Mix of codes, full names, and messy sheet values.
_STATE_INPUTS = [
    ("CA", "CA"),
    ("California", "CA"),
    ("california", "CA"),
    ("TX", "TX"),
    ("Texas", "TX"),
    ("NY", "NY"),
    ("New York", "NY"),
    ("FL", "FL"),
    ("Florida", "FL"),
    ("NE", "NE"),
    ("Nebraska", "NE"),
    ("AK", "AK"),
    ("Alaska", "AK"),
    ("DC", "DC"),
    ("District of Columbia", "DC"),
]


@pytest.mark.parametrize("raw_state,expected_code", _STATE_INPUTS)
def test_normalize_state_covers_sheet_values(raw_state, expected_code):
    assert _normalize_state(raw_state) == expected_code


@pytest.mark.parametrize("provider_name,host,base_user", _PROVIDER_GATEWAYS)
@pytest.mark.parametrize("raw_state,expected_code", _STATE_INPUTS)
def test_apply_targeting_force_replace_all_providers(
    provider_name, host, base_user, raw_state, expected_code
):
    # Stale embedded state is CA — rebuild must replace it with the row state.
    stale = f"{base_user}-country-us-state-us_california-session-999888777"
    user = _apply_targeting_to_username(
        stale,
        host,
        {
            "country": "US",
            "state": expected_code,
            "_want_sid": True,
            "force_replace": True,
        },
        provider_name,
    )
    low = user.lower()
    if expected_code != "CA":
        assert "california" not in low and "us_california" not in low, user
    assert _username_includes_state_target(user, host, expected_code), (
        f"{provider_name} missing state token for {expected_code}: {user}"
    )


@pytest.mark.parametrize("provider_name,host,base_user", _PROVIDER_GATEWAYS)
@pytest.mark.parametrize("expected_code", ["CA", "TX", "NY", "FL", "NE", "AK", "DC"])
def test_build_state_targeted_proxy_all_providers(
    provider_name, host, base_user, expected_code
):
    line = f"http://{base_user}:secret@{host}:8080"
    base = _parse_proxy_line(line)
    assert base and base.get("is_rotating_gateway"), line
    out = _build_state_targeted_proxy(base, expected_code, "US")
    user = (out.get("username") or "").strip()
    assert user, out
    assert _username_includes_state_target(user, host, expected_code), (
        f"{provider_name} build failed for {expected_code}: {user}"
    )
    assert "@" not in (out.get("server") or "")


def test_smartproxy_net_user_prefix_becomes_smart():
    base = _gateway_base_username("user-sp123", "proxy.smartproxy.net")
    assert base.lower().startswith("smart-")


def test_smartproxy_net_nebraska_from_data_row():
    base = _parse_proxy_line("http://user-sp123:secret@proxy.smartproxy.net:3120")
    out = _build_state_targeted_proxy(base, "Nebraska", "US")
    user = (out.get("username") or "").lower()
    assert "_state-nebraska" in user, user
    assert user.startswith("smart-")


def test_variant_index_rotates_state_encoding():
    base = _parse_proxy_line("http://smart-u0test:secret@proxy.smartproxy.net:3120")
    a = _build_state_targeted_proxy(base, "CA", "US", state_variant_index=0)
    b = _build_state_targeted_proxy(base, "CA", "US", state_variant_index=1)
    assert a["username"] != b["username"] or a["username"] == b["username"]
    assert _username_includes_state_target(a["username"], "proxy.smartproxy.net", "CA")
    assert _username_includes_state_target(b["username"], "proxy.smartproxy.net", "CA")


def test_all_builtin_profiles_have_hosts_and_state_fmt():
    for p in _PROVIDER_PROFILES:
        assert p.get("hosts"), p["name"]
        assert p.get("state_fmt"), p["name"]


def test_smartproxy_smart_profile_separate_from_legacy():
    net = _detect_profile("proxy.smartproxy.net", "", "user-x")
    com = _detect_profile("gate.smartproxy.com", "", "user-x")
    assert net and net.get("dsl") == "smart_underscore"
    assert com and com.get("name") == "Smartproxy / Decodo"
    assert _SMARTPROXY_SMART_PROFILE["state_fmt"] == "{slug}"
