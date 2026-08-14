"""
Regression tests — v2.6.17 comprehensive duplicate-IP fix.

Covers:
  1. Per-offer scoping in get_all_click_ips_from_entire_database
  2. Burnt-IP admin cleanup endpoints (stats / preview / purge)
  3. TTL-index compatibility (last_detected_dt as BSON Date)
  4. VPN phrase list tightening (no more "access denied" false-positives)
  5. TLS prewarm skipped for tracker targets
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUT_FILE = REPO_ROOT / "real_user_traffic.py"
SERVER_FILE = REPO_ROOT / "server.py"


def test_version_bumped_to_2_6_17_or_higher():
    version = (REPO_ROOT / "VERSION").read_text().strip()
    parts = tuple(int(p) for p in version.split("."))
    assert parts >= (2, 6, 17), f"Expected >= 2.6.17, got {version!r}"


def test_access_denied_removed_from_vpn_phrases():
    """v2.6.17 removed 'access denied' — was too generic and burned
    clean IPs on legitimate 200 pages. Traxun's actual block screen
    always has 'traxun security shield' too, which is preserved."""
    import re as _re
    src = RUT_FILE.read_text(encoding="utf-8")
    # Find the _VPN_BLOCK_PAGE_PHRASES list and check its contents
    marker = "_VPN_BLOCK_PAGE_PHRASES = ["
    idx = src.find(marker)
    assert idx >= 0
    end = src.find("\n]", idx)
    body = src[idx:end]
    # Strip comments — the fix note itself mentions the removed phrase.
    # Only match actual list ITEMS (lines that ARE the string literal).
    non_comment = "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )
    # A real list item looks like `    "access denied",`
    assert not _re.search(r'^\s*"access denied",?\s*$', non_comment, _re.MULTILINE), (
        "'access denied' MUST be removed from _VPN_BLOCK_PAGE_PHRASES list items"
    )
    # Ensure specific phrases are still present as list items
    assert '"traxun security shield"' in body
    assert '"vpn/proxy detected"' in body


def test_detectors_accept_http_status_param():
    """Phrase detectors now take an optional http_status arg so rich
    200-OK landing pages skip phrase matching."""
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "async def _detect_offer_duplicate_ip_block(\n    page:" in src
    assert "http_status: Optional[int] = None," in src
    assert "async def _detect_offer_vpn_block(\n    page:" in src


def test_tls_prewarm_skipped_for_tracker_targets():
    """v2.6.89 — TLS prewarm must not GET tracker/offer when click is committed."""
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "_tls_prewarm_effective = bool(tls_prewarm)" in src
    assert "TLS prewarm skipped — browser is the sole affiliate click" in src
    assert "_is_tracker_target" in src
    assert "_affiliate_click_fired" in src


def test_persist_burnt_ip_writes_bson_date():
    """_persist_burnt_ip now stores last_detected_dt as BSON Date so
    the TTL index can auto-expire rows."""
    src = RUT_FILE.read_text(encoding="utf-8")
    assert '"last_detected_dt": _now_dt' in src, "BSON Date field missing"
    assert '"first_detected_dt": _now_dt' in src


def test_server_get_all_click_ips_accepts_offer_url():
    """server.py get_all_click_ips_from_entire_database now takes
    offer_url= param and filters rut_burnt_ips accordingly."""
    src = SERVER_FILE.read_text(encoding="utf-8")
    assert "offer_url: Optional[str] = None," in src
    # Ensure the burnt-IP query uses offer_urls when scoped
    assert '_burnt_query["offer_urls"] = offer_url' in src
    # Ensure the RUT job runner passes target_url through
    assert "_dup_offer_url = params.get(\"target_url\")" in src


def test_burnt_ip_admin_endpoints_exist():
    """Three new admin endpoints for burnt-IP management."""
    src = SERVER_FILE.read_text(encoding="utf-8")
    assert '@api_router.post("/admin/rut-burnt-ips/preview")' in src
    assert '@api_router.post("/admin/rut-burnt-ips/purge")' in src
    assert '@api_router.get("/admin/rut-burnt-ips/stats")' in src
    # Refuses empty filter
    assert 'At least one filter (offer_url_contains, reason, user_id, burnt_before_iso, or ip) is required.' in src


def test_ttl_index_setup_in_startup():
    """Startup event creates TTL + compound indexes on rut_burnt_ips."""
    src = SERVER_FILE.read_text(encoding="utf-8")
    assert '"last_detected_dt", expireAfterSeconds=_ttl_seconds' in src
    assert 'RUT_BURNT_IP_TTL_DAYS' in src
    assert 'db.rut_burnt_ips.create_index([("user_ids", 1), ("offer_urls", 1)])' in src


def test_re_module_imported():
    """server.py must import `re` at module level for admin purge regex."""
    src = SERVER_FILE.read_text(encoding="utf-8")
    # Confirm the import statement is present
    assert "\nimport re\n" in src or "\nimport re " in src


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
