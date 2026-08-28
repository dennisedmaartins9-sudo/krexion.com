"""v2.7.30 — Browser profile proxy resolve matches RUT provider path."""
from __future__ import annotations

from browser_profile_module import (
    _apply_resolved_line_to_proxy_cfg,
    _profile_provider_targeting,
)


def test_profile_provider_targeting_from_country():
    t = _profile_provider_targeting(
        {"proxyjet_state": "FL"},
        profile_country="us",
    )
    assert t == {"country": "US", "state": "FL"}


def test_profile_provider_targeting_skips_any():
    assert _profile_provider_targeting({"proxyjet_country": "ANY"}) is None


def test_apply_resolved_line_parses_gateway():
    cfg = _apply_resolved_line_to_proxy_cfg(
        {},
        "http://user:pass@gw.dataimpulse.com:10000",
        provider_id="prov-1",
    )
    assert cfg["enabled"] is True
    assert cfg["provider_id"] == "prov-1"
    assert cfg["server"] == "http://gw.dataimpulse.com:10000"
    assert cfg["username"] == "user"
    assert cfg["password"] == "pass"
    assert cfg["use_proxyjet"] is False
