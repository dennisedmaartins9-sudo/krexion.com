"""v2.7.77 — Browser profile polish: permanent delete, template edit API, refresh-proxy, extensions."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_77():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.91"


def test_anti_detect_allow_extensions_fields():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig(allow_extensions=True, extensions_dir="/tmp/ext")
    assert cfg.allow_extensions is True
    assert cfg.extensions_dir == "/tmp/ext"


def test_list_profiles_has_more_flag():
    from browser_profile_module import list_profiles

    async def _run():
        docs = [{"id": f"p{i}", "user_id": "u1", "name": f"P{i}"} for i in range(3)]

        class FakeCur:
            def sort(self, *_a, **_k):
                return self

            def skip(self, *_a, **_k):
                return self

            def limit(self, n):
                self._limit = n
                return self

            async def to_list(self, length):
                return docs[: length]

        req = MagicMock()
        with patch("browser_profile_module._resolve_user", return_value={"id": "u1"}), patch(
            "browser_profile_module._resolve_user_or_401", return_value="u1"
        ), patch("browser_profile_module._DB") as mock_db, patch(
            "browser_profile_module._public_view_for", side_effect=lambda d, _u: d
        ):
            mock_db.browser_profiles.find.return_value = FakeCur()
            r = await list_profiles(req, limit=2, skip=0, sort="updated_at")
            assert r["has_more"] is True
            assert r["limit"] == 2
            assert len(r["profiles"]) == 2

    asyncio.run(_run())


def test_permanent_delete():
    from browser_profile_module import delete_profile

    stored = {"id": "p1", "user_id": "u1", "name": "Trash", "deleted_at": "2026-09-01T00:00:00Z"}

    class FakeCol:
        async def delete_one(self, filt):
            if filt.get("id") == "p1":
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

    req = MagicMock()

    async def _run():
        async def _mock_delete_many(*_a, **_k):
            return MagicMock()

        with patch("browser_profile_module._resolve_user", return_value={"id": "u1"}), patch(
            "browser_profile_module._resolve_user_or_401", return_value="u1"
        ), patch("browser_profile_module._DB") as mock_db:
            mock_db.browser_profiles = FakeCol()
            mock_db.browser_profile_sessions = MagicMock()
            mock_db.browser_profile_sessions.delete_many = _mock_delete_many
            r = await delete_profile(req, "p1", permanent=True)
            assert r["permanent"] is True

    asyncio.run(_run())


def test_update_profile_template_body():
    from browser_profile_module import UpdateProfileTemplateBody

    b = UpdateProfileTemplateBody(name="Updated", settings={"form": {"country": "us"}})
    assert b.name == "Updated"
    assert b.settings["form"]["country"] == "us"


def test_bulk_delete_permanent_flag_on_body():
    from browser_profile_module import BulkIdsBody

    b = BulkIdsBody(profile_ids=["a"], permanent=True)
    assert b.permanent is True
