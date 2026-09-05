"""v2.7.120 — Hard gates: short pool fail, rotating live probe, verified upload."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_120():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.120")


def test_saved_pool_hard_fails_when_short():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "No profiles were created" in src
    assert "status_code=400" in src
    assert "Need {count} free saved proxies with verified outbound IP" in src
    assert "_saved_rotating" in src
    assert "_is_rotating_gateway_proxy" in src
    assert "live RUT probe" in src
    assert "Saved mode never creates proxy-less profiles" in src


def test_upload_requires_verified_exit():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "require_verified_exit: bool = True" in src
    assert "require_verified and not verified_exit" in src
    assert "Classic Upload without Check proxy is blocked" in src
    assert "get_all_click_ips_from_entire_database(user_id=main_uid)" in src
    assert "lines = [str(x).strip() for x in raw_lines if str(x).strip()][:100]" in src


def test_frontend_hard_fail_and_classic_block():
    page = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "Need ${count} free saved proxies" in page
    assert "bp-saved-proxy-count-mismatch" in page
    proxies = (REPO / "frontend/src/pages/ProxiesPage.js").read_text(encoding="utf-8")
    assert "Classic Upload is blocked without verified outbound IPs" in proxies
    panel = (REPO / "frontend/src/components/ProxyBulkAddPanel.js").read_text(encoding="utf-8")
    assert "require_verified_exit: true" in panel
