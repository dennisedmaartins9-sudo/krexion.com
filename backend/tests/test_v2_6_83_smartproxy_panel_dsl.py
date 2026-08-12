"""v2.6.83 — Smartproxy panel DSL: state-California + port 3128."""
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


def test_smart_region_state_fmt_is_title_case():
    assert _SMARTPROXY_SMART_PROFILE["state_fmt"] == "{title}"
    assert _format_state_for_profile(_SMARTPROXY_SMART_PROFILE, "CA") == "California"
    assert _format_state_for_profile(_SMARTPROXY_SMART_PROFILE, "NY") == "New_York"


def test_panel_username_uses_state_California():
    user = _apply_targeting_to_username(
        "smart-u0h51gc8hmdw",
        "proxy.smartproxy.net",
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    assert "_state-California" in user, user
    assert "_area-US" in user, user
    assert user.lower().startswith("smart-u0h51gc8hmdw_area-us")


def test_port_3120_rewritten_to_3128_in_gateway_line():
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
    assert ":3128" in line
    assert ":3120" not in line


def test_build_rewrites_port_and_title_state():
    base = _parse_proxy_line(
        "http://smart-u0h51gc8hmdw:pass@proxy.smartproxy.net:3120"
    )
    out = _build_state_targeted_proxy(base, "CA", "US")
    assert ":3128" in (out.get("server") or "")
    assert "_state-California" in (out.get("username") or ""), out.get("username")


def test_variants_prefer_title_then_slug():
    variants = _state_targeting_variants("CA", _SMARTPROXY_SMART_PROFILE)
    assert variants[0] == "California"
    assert "california" in [v.lower() for v in variants]
