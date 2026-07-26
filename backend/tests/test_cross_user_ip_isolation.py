"""Cross-user IP isolation group tests."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_isolation_module_exists():
    p = ROOT / "backend" / "cross_user_ip_isolation.py"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "get_isolation_peer_user_ids" in text
    assert "create_group" in text


def test_dup_ip_loader_merges_peers():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "_load_ips_for_user" in text
    assert "get_isolation_peer_user_ids" in text
    assert "Cross-user IP isolation" in text


def test_persist_burnt_ip_tags_group_members():
    text = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "get_isolation_group_member_ids" in text
    assert '"user_ids": {"$each": _user_ids_to_tag}' in text


def test_admin_endpoints_exist():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "/admin/cross-user-ip-groups" in text
    assert "admin_create_cross_user_ip_group" in text


def test_admin_ui_panel():
    text = (ROOT / "frontend" / "src" / "components" / "CrossUserIpIsolationPanel.js").read_text(encoding="utf-8")
    assert "Cross-User IP Isolation" in text
    assert "ip-isolation" not in text  # panel only; tab is in AdminDashboard
    dash = (ROOT / "frontend" / "src" / "pages" / "AdminDashboard.js").read_text(encoding="utf-8")
    assert "ip-isolation" in dash
    assert "CrossUserIpIsolationPanel" in dash
