"""v2.7.76 — Browser profile agency UX: health, trash, templates, import."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_compute_profile_health_good():
    from browser_profile_health import compute_profile_health

    h = compute_profile_health({
        "status": "idle",
        "proxy": {"enabled": True, "server": "http://1.2.3.4:8080"},
        "exit_ip": "1.2.3.4",
        "last_proxy_check": {"ok": True, "ip": "1.2.3.4"},
        "storage_state": {"cookies": [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}, {"n": 5}]},
        "fingerprint_hash": "abc123def456",
        "last_tls_prewarm_ok": True,
    })
    assert h["level"] == "good"
    assert h["score"] >= 75


def test_vendor_import_adspower_shape():
    from browser_profile_import_vendors import parse_vendor_import_payload

    rows = parse_vendor_import_payload({
        "data": {"list": [{
            "name": "AdsPower Profile 1",
            "user_proxy_config": {
                "proxy_soft": "other",
                "proxy_host": "proxy.example.com",
                "proxy_port": "8080",
                "proxy_user": "u",
                "proxy_password": "p",
            },
            "ua": "Mozilla/5.0 Mobile",
            "screen_width": 393,
            "screen_height": 852,
        }]}
    })
    assert len(rows) == 1
    assert rows[0]["name"] == "AdsPower Profile 1"
    assert rows[0]["proxy"]["enabled"] is True


def test_shell_ipc_roundtrip(tmp_path):
    from krexion_mobile_shell_interactive import (
        drain_shell_commands,
        enqueue_shell_command,
        write_shell_state,
        read_shell_state,
    )

    cfg = str(tmp_path / "shell.json")
    open(cfg, "w").close()
    enqueue_shell_command(cfg, "go_back")
    cmds = drain_shell_commands(cfg)
    assert len(cmds) == 1
    assert cmds[0]["cmd"] == "go_back"
    write_shell_state(cfg, {"url": "example.com", "tab_count": 2})
    st = read_shell_state(cfg)
    assert st["url"] == "example.com"
    assert st["tab_count"] == 2


def test_version_is_2_7_76():
        assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.91"


def test_soft_delete_and_restore():
    from browser_profile_module import delete_profile, restore_profile, _not_deleted_filter

    assert "$or" in _not_deleted_filter()

    stored = {"id": "p1", "user_id": "u1", "name": "Test", "status": "idle"}

    class FakeCol:
        async def update_one(self, filt, upd):
            if filt.get("id") == "p1":
                stored.update(upd.get("$set", {}))
                return MagicMock(matched_count=1)
            return MagicMock(matched_count=0)

        async def find_one(self, filt):
            if filt.get("id") == "p1":
                return dict(stored)
            return None

    req = MagicMock()

    async def _run():
        async def _mock_update_many(*_a, **_k):
            return MagicMock()

        with patch("browser_profile_module._resolve_user", return_value={"id": "u1"}), patch(
            "browser_profile_module._resolve_user_or_401", return_value="u1"
        ), patch("browser_profile_module._DB") as mock_db, patch(
            "browser_profile_module._now_iso", return_value="2026-09-01T00:00:00Z"
        ):
            mock_db.browser_profiles = FakeCol()
            mock_db.browser_profile_sessions = MagicMock()
            mock_db.browser_profile_sessions.update_many = _mock_update_many
            r = await delete_profile(req, "p1", permanent=False)
            assert r["soft"] is True
            assert stored.get("deleted_at")
            r2 = await restore_profile(req, "p1")
            assert r2["restored"] is True

    asyncio.run(_run())
