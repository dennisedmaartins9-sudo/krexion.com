"""v2.6.84 — Smartproxy panel DSL: PascalCase states + keep port 3120."""
from __future__ import annotations

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

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _format_gateway_line,
    _format_state_for_profile,
    _SMARTPROXY_SMART_PROFILE,
    _state_targeting_variants,
)
from real_user_traffic import _build_state_targeted_proxy, _parse_proxy_line  # noqa: E402


def test_smart_region_state_fmt_is_pascal_case():
    assert _SMARTPROXY_SMART_PROFILE["state_fmt"] == "{pascal}"
    assert _format_state_for_profile(_SMARTPROXY_SMART_PROFILE, "CA") == "California"
    assert _format_state_for_profile(_SMARTPROXY_SMART_PROFILE, "NY") == "NewYork"


def test_panel_username_uses_state_California():
    user = _apply_targeting_to_username(
        "smart-u0h51gc8hmdw",
        "proxy.smartproxy.net",
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    assert "_state-California" in user, user
    assert "_area-US" in user, user


def test_ny_uses_pascal_newyork():
    user = _apply_targeting_to_username(
        "smart-u0h51gc8hmdw",
        "proxy.smartproxy.net",
        {"country": "US", "state": "NY", "_want_sid": True, "force_replace": True},
    )
    assert "_state-NewYork" in user, user


def test_port_3120_preserved_in_gateway_line():
    line = _format_gateway_line(
        {
            "gateway_host": "proxy.smartproxy.net",
            "gateway_port": "3120",
            "username": "smart-u0h51gc8hmdw",
            "password": "secret",
        },
        "http",
        rotate_session=False,
    )
    assert line is not None
    assert ":3120" in line


def test_build_keeps_customer_port_and_title_state():
    base = _parse_proxy_line(
        "http://smart-u0h51gc8hmdw:pass@proxy.smartproxy.net:3120"
    )
    out = _build_state_targeted_proxy(base, "CA", "US")
    assert ":3120" in (out.get("server") or "")
    assert "_state-California" in (out.get("username") or ""), out.get("username")


def test_variants_prefer_pascal_then_title():
    variants = _state_targeting_variants("CA", _SMARTPROXY_SMART_PROFILE)
    assert variants[0] == "California"
    ny = _state_targeting_variants("NY", _SMARTPROXY_SMART_PROFILE)
    assert ny[0] == "NewYork"
