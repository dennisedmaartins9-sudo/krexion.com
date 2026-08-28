"""v2.7.28 — Browser profile team-unique exit IP at create time."""
from __future__ import annotations

from cross_user_ip_isolation import (
    PROFILE_IP_OFFER_KEY,
    canonicalize_ip,
)


def test_profile_ip_offer_key_constant():
    assert PROFILE_IP_OFFER_KEY == "__krexion_browser_profile__"


def test_canonicalize_ip_ipv4():
    assert canonicalize_ip("203.0.113.10") == "203.0.113.10"


def test_browser_profile_module_has_ip_helpers():
    from browser_profile_module import (
        _allocate_provider_proxy_lines,
        _finalize_doc_proxy_and_ip,
        _load_team_profile_used_ips,
    )
    assert callable(_load_team_profile_used_ips)
    assert callable(_finalize_doc_proxy_and_ip)
    assert callable(_allocate_provider_proxy_lines)
