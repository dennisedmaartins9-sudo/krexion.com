"""v2.7.33 — Famous provider catalog + Thordata DSL profile."""
from __future__ import annotations

from proxy_provider_module import PROVIDER_CATALOG, _detect_profile


def test_provider_catalog_has_major_brands():
    ids = {p["id"] for p in PROVIDER_CATALOG}
    for key in ("dataimpulse", "smartproxy", "thordata", "oxylabs", "brightdata", "iproyal", "soax"):
        assert key in ids


def test_detect_thordata_profile_by_host():
    prof = _detect_profile("t.pr.thordata.net", "My Thordata")
    assert prof is not None
    assert prof["name"] == "Thordata"
    assert prof["sid_key"] == "sessid"
    assert prof["ttl_key"] == "sesstime"


def test_detect_dataimpulse_profile():
    prof = _detect_profile("gw.dataimpulse.com", "DataImpulse Main")
    assert prof is not None
    assert prof["name"] == "DataImpulse"


def test_catalog_entries_have_gateway_or_api():
    for item in PROVIDER_CATALOG:
        if item.get("kind") == "api_endpoint":
            assert item.get("api_url")
        else:
            assert item.get("gateway_host")
            assert item.get("gateway_port")
