"""Cross-user IP isolation + DB VPS ledger tests."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_isolation_module_exists():
    p = ROOT / "backend" / "cross_user_ip_isolation.py"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "get_isolation_peer_user_ids" in text
    assert "get_vps_ledger_peer_user_ids" in text
    assert "get_vps_ledger_member_ids" in text
    assert "vps_ip_db_enabled" in text
    assert "create_group" in text


def test_dup_ip_loader_uses_vps_ledger_peers():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "_load_ips_for_user" in text
    assert "get_vps_ledger_peer_user_ids" in text
    assert "VPS IP ledger" in text
    assert "vps_ip_db_enabled" in text


def test_persist_burnt_ip_tags_vps_ledger_members():
    text = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "get_vps_ledger_member_ids" in text
    assert '"user_ids": {"$each": _user_ids_to_tag}' in text


def test_admin_user_model_has_db_vps_field():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "vps_ip_db_enabled" in text
    assert "/admin/cross-user-ip-groups" in text


def test_admin_ui_db_vps_toggle():
    dash = (ROOT / "frontend" / "src" / "pages" / "AdminDashboard.js").read_text(encoding="utf-8")
    assert "toggleVpsIpDb" in dash
    assert "DB VPS ON" in dash
    assert "vps_ip_db_enabled" in dash
    panel = (ROOT / "frontend" / "src" / "components" / "CrossUserIpIsolationPanel.js").read_text(
        encoding="utf-8"
    )
    assert "DB VPS ON" in panel
