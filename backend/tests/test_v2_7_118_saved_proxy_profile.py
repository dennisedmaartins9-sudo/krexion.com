"""v2.7.118 — Check proxy → unique exit IPs → Use saved proxy on profile create."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_118():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.118")


def test_proxy_upload_skips_used_exit_ips():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    block = src[src.index("class ProxyUpload") : src.index("class ProxyUpload") + 700]
    assert "skip_used_exit_ips" in block
    assert "exit_ips" in block
    assert "async def _collect_used_exit_ips" in src
    assert "skipped_used_exit" in src


def test_available_for_profiles_route():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert '@api_router.get("/proxies/available-for-profiles")' in src
    assert "async def proxies_available_for_profiles" in src
    assert "bound_profile_id" in src
    assert "detected_ip" in src


def test_adv_proxy_cfg_has_saved_mode():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    block = src[src.index("class AdvProxyCfg") : src.index("class AdvProxyCfg") + 1200]
    assert '"saved"' in block
    assert "saved_proxy_ids" in block
    assert "_proxies_db_for_user" in src
    assert 'proxy_mode == "saved"' in src
    assert "from_saved_proxy" in src
    assert "get_db_for_user" in src  # bound from server


def test_bulk_panel_requires_check_then_unique_exit():
    panel = (REPO / "frontend/src/components/ProxyBulkAddPanel.js").read_text(encoding="utf-8")
    assert "Check proxy" in panel
    assert "skip_used_exit_ips" in panel
    assert "exit_ips" in panel
    assert "unique fresh" in panel.lower() or "unique outbound" in panel.lower() or "unique" in panel


def test_browser_profiles_ui_has_use_saved_proxy():
    page = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert 'data-testid="bp-adv-proxy-saved"' in page
    assert "Use saved proxy" in page
    assert 'mode: "saved"' in page or 'mode === "saved"' in page
    assert "saved_proxy_ids" in page
    assert "available-for-profiles" in page


def test_server_binds_get_db_for_user_to_browser_profiles():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "get_db_for_user=get_db_for_user" in src
    assert "_bp_bind" in src
