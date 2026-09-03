"""v2.7.17 — Synchronizer + Team ACL + Cloud Phone hooks (gap fill)."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def test_version_2_7_17():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.17")


def test_sync_module_ast_and_api():
    src = (ROOT / "browser_profile_sync.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "async def start_sync" in src
    assert "async def stop_sync" in src
    assert "resolve_cdp_for_profile" in src
    assert "krexionSyncEvent" in src


def test_module_routes_and_acl_helpers():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert '"/sync/start"' in src
    assert '"/{profile_id}/acl"' in src
    assert '"/{profile_id}/cloud-phone"' in src
    assert '"/{profile_id}/open-on-device"' in src
    assert "def _has_min_role" in src
    assert "class SyncStartBody" in src
    assert "class AclGrantBody" in src
    assert "cdp_ws" in src
    assert "local_api_cdp" in src
    assert '"/sync/start"' in src


def test_launcher_cdp_opt_in():
    """v2.7.105e — CDP is opt-in (local_api_cdp), not always-on for native/local."""
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "CDP opt-in ONLY" in src
    assert "_want_cdp = bool(local_api_cdp)" in src
    assert "remote-debugging-port" in src
    assert "local_api_cdp" in src


def test_frontend_sync_acl_cloud_phone():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    src = fe.read_text(encoding="utf-8")
    assert "bp-sync-start" in src
    assert "bp-share-mode" in src
    assert "bp-cloud-phone-" in src or "bp-cloud-phone-provider" in src
    assert "/sync/start" in src
    assert "/acl" in src


def test_rpa_deep_link_consumes_browser_profile_id():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "RPAStudioPage.js"
    src = fe.read_text(encoding="utf-8")
    assert "browser_profile_id" in src
    assert "useLocation" in src
    assert "rpa-settings-browser-profile-id" in src


def test_role_rank_logic():
    from browser_profile_module import _has_min_role, _normalize_role

    doc = {
        "user_id": "owner1",
        "acl": [
            {"user_id": "u2", "email": "a@b.com", "role": "viewer"},
            {"user_id": "u3", "email": "c@d.com", "role": "editor"},
            {"user_id": "u4", "email": "e@f.com", "role": "admin"},
        ],
    }
    assert _normalize_role("EDITOR") == "editor"
    assert _has_min_role(doc, "owner1", "admin")
    assert _has_min_role(doc, "u4", "admin")
    assert _has_min_role(doc, "u3", "editor")
    assert not _has_min_role(doc, "u2", "editor")
    assert _has_min_role(doc, "u2", "viewer")
    assert not _has_min_role(doc, "nobody", "viewer")
