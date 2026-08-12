"""v2.6.81 — ROW-FIRST state targeting for all gateway providers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _detect_profile,
    _state_targeting_variants,
    _username_includes_state_target,
)


def test_smartproxy_net_always_smart_underscore_profile():
    prof = _detect_profile("proxy.smartproxy.net", "", "user-legacy123")
    assert prof is not None
    assert prof.get("dsl") == "smart_underscore"


def test_smartproxy_net_ca_username_has_state_california():
    user = _apply_targeting_to_username(
        "user-legacy123",
        "proxy.smartproxy.net",
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    low = user.lower()
    assert "_state-california" in low or "_state-California".lower() in low, user
    # Panel docs use Title Case: state-California
    assert "_state-california" in user.lower(), user
    assert _username_includes_state_target(user, "proxy.smartproxy.net", "CA")


def test_state_variants_include_slug_for_smart_region():
    prof = _detect_profile("proxy.smartproxy.net", "", "smart-u0h51gc8hmdw")
    variants = _state_targeting_variants("CA", prof)
    assert variants[0] == "California"
    assert any(v.lower() == "california" for v in variants)
    ny = _state_targeting_variants("NY", prof)
    assert ny[0] == "NewYork"


def test_meaningful_attempts_budget_in_source():
    rut = Path(__file__).resolve().parents[1] / "real_user_traffic.py"
    src = rut.read_text(encoding="utf-8")
    assert '"meaningful_attempts": 0' in src
    assert 'get("meaningful_attempts")' in src
