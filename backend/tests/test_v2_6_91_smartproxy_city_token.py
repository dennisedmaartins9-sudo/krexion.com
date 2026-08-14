"""v2.6.91 — Smartproxy city token must stay LosAngeles not Losangeles."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _format_smartproxy_city,
)


def test_format_smartproxy_city_preserves_camel_case():
    assert _format_smartproxy_city("LosAngeles") == "LosAngeles"
    assert _format_smartproxy_city("NewYork") == "NewYork"
    assert _format_smartproxy_city("LasVegas") == "LasVegas"
    assert _format_smartproxy_city("KansasCity") == "KansasCity"
    assert _format_smartproxy_city("VirginiaBeach") == "VirginiaBeach"


def test_format_smartproxy_city_from_spaced_name():
    assert _format_smartproxy_city("Los Angeles") == "LosAngeles"
    assert _format_smartproxy_city("New York") == "NewYork"


def test_apply_targeting_username_has_correct_city_token():
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
    assert "_city-LosAngeles" in user
    assert "_city-Losangeles" not in user


def test_version_is_2_6_91():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert version == "2.6.91"
