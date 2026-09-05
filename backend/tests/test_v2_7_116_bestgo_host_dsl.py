"""v2.7.116 — BestGo host wins over DataImpulse provider label (correct dash DSL)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bestgo_host_detected_even_when_named_dataimpulse():
    from proxy_provider_module import _detect_profile

    prof = _detect_profile("ca.rrp.bestgo.work", "dataimpulse azlan", "USER123")
    assert prof is not None
    assert prof["name"] == "BestGo"
    assert "bestgo.work" in prof["hosts"]


def test_bestgo_username_uses_dash_dsl_not_dataimpulse_cr():
    from proxy_provider_module import _apply_targeting_to_username

    user = _apply_targeting_to_username(
        "USER123",
        "ca.rrp.bestgo.work",
        {
            "country": "US",
            "state": "alabama",
            "force_replace": True,
            "_want_sid": True,
            "sticky_minutes": 10,
        },
        "dataimpulse azlan",
    )
    low = user.lower()
    assert "__cr" not in low
    assert "cr.us" not in low
    assert ";state." not in low
    assert "country-us" in low
    assert "state-alabama" in low
    assert "session-" in low or "{sid}" in low


def test_dataimpulse_host_still_uses_cr_dsl():
    from proxy_provider_module import _detect_profile, _apply_targeting_to_username

    prof = _detect_profile("gw.dataimpulse.com", "dataimpulse azlan", "USER123")
    assert prof["name"] == "DataImpulse"
    user = _apply_targeting_to_username(
        "USER123",
        "gw.dataimpulse.com",
        {
            "country": "US",
            "state": "alabama",
            "force_replace": True,
            "_want_sid": True,
            "sticky_minutes": 10,
        },
        "dataimpulse azlan",
    )
    assert "__cr" in user.lower() or "cr.us" in user.lower()


def test_bestgo_in_provider_catalog():
    from proxy_provider_module import PROVIDER_CATALOG

    ids = {c["id"] for c in PROVIDER_CATALOG}
    assert "bestgo" in ids
    entry = next(c for c in PROVIDER_CATALOG if c["id"] == "bestgo")
    assert "bestgo" in entry["gateway_host"]


def test_friendly_error_mentions_label_mismatch():
    from browser_profile_module import _friendly_proxy_probe_error

    msg = _friendly_proxy_probe_error(
        "ip endpoints returned no ip",
        "ca.rrp.bestgo.work",
    )
    assert "BestGo" in msg
    assert "DataImpulse" in msg or "__cr" in msg or "bestgo.work" in msg.lower()


def test_create_geo_build_uses_bestgo_dsl():
    from real_user_traffic import _build_state_targeted_proxy

    out = _build_state_targeted_proxy(
        {
            "server": "http://ca.rrp.bestgo.work:10000",
            "username": "USER123",
            "password": "secret",
            "is_rotating_gateway": True,
        },
        "AL",
        "US",
    )
    user = (out.get("username") or "").lower()
    assert "country-us" in user
    assert "__cr" not in user


def test_version_at_least_2_7_116():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.116")
