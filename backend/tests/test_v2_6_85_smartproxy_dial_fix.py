"""v2.6.85 — Smartproxy dial fix: nested Decodo JSON, city-from-attempt-1, dial sem."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

import real_user_traffic as rut  # noqa: E402
from proxy_provider_module import _apply_targeting_to_username  # noqa: E402


def test_apply_decodo_nested_payload_california():
    result: dict = {}
    ok = rut._apply_decodo_geo_payload(
        {
            "proxy": {"ip": "76.33.130.153"},
            "country": {"name": "United States", "code": "US"},
            "city": {
                "name": "Los Angeles",
                "code": "CA",
                "state": "California",
                "time_zone": "America/Los_Angeles",
                "latitude": 34.05,
                "longitude": -118.24,
            },
            "isp": {"isp": "Spectrum", "organization": "Charter", "asn": 20001},
        },
        result,
    )
    assert ok is True
    assert result["exit_ip"] == "76.33.130.153"
    assert result["country"] == "US"
    assert result["region"] == "CA"
    assert result["city"] == "Los Angeles"
    assert rut._geo_exit_state_code(result) == "CA"


def test_apply_decodo_flat_payload_still_works():
    result: dict = {}
    ok = rut._apply_decodo_geo_payload(
        {
            "ip": "1.2.3.4",
            "country_code": "US",
            "region": "TX",
            "regionName": "Texas",
            "city": "Houston",
        },
        result,
    )
    assert ok is True
    assert result["exit_ip"] == "1.2.3.4"
    assert result["region"] == "TX"
    assert rut._geo_exit_state_code(result) == "TX"


def test_geo_exit_state_from_city_when_region_missing():
    assert rut._geo_exit_state_code({"city": "Los Angeles"}) == "CA"
    assert rut._geo_exit_state_code({"city": "Miami"}) == "FL"


def test_heal_california_canada_collision():
    geo = {
        "country": "CA",
        "region": "CA",
        "region_name": "California",
        "city": "Los Angeles",
    }
    rut._heal_california_canada_collision(geo)
    assert geo["country"] == "US"
    assert rut._geo_matches_target_country(geo, "US") is True


def test_smartproxy_city_token_from_attempt_one_in_source():
    src = Path(rut.__file__).read_text(encoding="utf-8")
    assert "_SMARTPROXY_STATE_CITY" in src
    assert "_smartproxy_dial_sem" in src
    assert "city-LosAngeles" in src or '"LosAngeles"' in src
    assert "geo probe timed out after 18s" in src
    assert "not _is_decodo" in src  # skip TLS path for Smartproxy
    assert "_apply_decodo_geo_payload" in src


def test_build_state_targeted_proxy_includes_city_losangeles():
    base = {
        "server": "http://proxy.smartproxy.net:3120",
        "username": "smart-u0h51gc8hmdw",
        "password": "secret",
        "is_rotating_gateway": True,
    }
    parsed = rut._build_state_targeted_proxy(
        base, "CA", "US", city="LosAngeles"
    )
    user = (parsed.get("username") or "").lower()
    assert "state-california" in user
    assert "city-losangeles" in user
    assert "area-us" in user or "area-US".lower() in user


def test_apply_targeting_city_pascal():
    user = _apply_targeting_to_username(
        "smart-u0h51gc8hmdw",
        "proxy.smartproxy.net",
        {
            "country": "US",
            "state": "California",
            "city": "LosAngeles",
            "_want_sid": True,
            "force_replace": True,
        },
    )
    low = user.lower()
    assert "_state-california" in low
    assert "_city-losangeles" in low
