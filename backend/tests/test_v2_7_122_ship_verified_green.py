"""v2.7.122 — Ship-gate verified green lock for saved-proxy AdsPower path."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_122():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.122")


def test_saved_proxy_path_still_locked():
    bp = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    srv = (ROOT / "server.py").read_text(encoding="utf-8")
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    px = (REPO / "frontend/src/pages/ProxiesPage.js").read_text(encoding="utf-8")
    panel = (REPO / "frontend/src/components/ProxyBulkAddPanel.js").read_text(encoding="utf-8")

    assert "No profiles were created" in bp
    assert "_saved_rotating" in bp
    assert "find_one_and_update" in bp
    assert "include_proxy_list_ips=False" in srv
    assert "require_verified = True" in srv
    assert '@api_router.post("/proxies/upload"' in srv
    assert '@api_router.get("/proxies/available-for-profiles"' in srv
    assert "Need ${count} free saved proxies" in fe
    assert "bp-saved-proxy-count-mismatch" in fe
    assert "Classic Upload is blocked without verified outbound IPs" in px
    assert "require_verified_exit: true" in panel
    assert "skip_used_exit_ips" in panel
