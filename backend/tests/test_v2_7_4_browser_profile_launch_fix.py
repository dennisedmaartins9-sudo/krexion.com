"""v2.7.4 — Browser Profile launch reliability (local mode + tray watchdog)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import browser_profile_launcher as bpl  # noqa: E402


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_local_desktop_mode_includes_native_and_local():
    src = _read("browser_profile_module.py")
    assert '_mode in ("native", "local")' in src
    assert src.count('_mode in ("native", "local")') >= 2


def test_queued_status_mirrored_as_queued_not_launching():
    src = _read("browser_profile_module.py")
    assert 'prof_update = {"status": "queued", "session_id": sid}' in src
    assert 'elif status == "queued":' in src


def test_launch_conflict_includes_queued():
    src = _read("browser_profile_module.py")
    assert '("running", "launching", "stopping", "queued")' in src


def test_pickup_watchdog_and_expire_helpers_exist():
    assert hasattr(bpl, "_watch_user_session_pickup")
    assert hasattr(bpl, "expire_stale_user_session_launches")
    assert "expire_stale_user_session_launches" in bpl.__all__
    src = _read("browser_profile_launcher.py")
    assert "_USER_SESSION_PICKUP_TIMEOUT_SEC" in src
    assert "tray helper did not pick up" in src


def test_expire_stale_marks_queued_as_error():
    async def _run():
        coll = MagicMock()
        docs = [{
            "id": "sess-old",
            "status": "queued",
            "queued_at": "2020-01-01T00:00:00+00:00",
            "profile_config": {"id": "prof-1", "user_id": "u1"},
        }]

        class _Cursor:
            def __init__(self, items):
                self._items = items

            def __aiter__(self):
                self._iter = iter(self._items)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration as exc:
                    raise StopAsyncIteration from exc

        coll.find = MagicMock(return_value=_Cursor(docs))
        coll.update_one = AsyncMock()
        db = MagicMock()
        db.__getitem__.return_value = coll
        db.browser_profile_sessions = MagicMock()
        db.browser_profile_sessions.update_one = AsyncMock()
        db.browser_profiles = MagicMock()
        db.browser_profiles.update_one = AsyncMock()

        n = await bpl.expire_stale_user_session_launches(db, older_than_sec=30)
        assert n == 1
        coll.update_one.assert_awaited()
        db.browser_profiles.update_one.assert_awaited()

    asyncio.run(_run())


def test_enqueue_schedules_pickup_watchdog():
    import types

    fake_collection = AsyncMock()
    fake_collection.insert_one = AsyncMock()
    fake_db = MagicMock()
    fake_db.__getitem__.return_value = fake_collection
    callback = AsyncMock()
    fake_server = types.ModuleType("server")
    fake_server.db = fake_db
    created = []

    def _capture_task(coro):
        created.append(coro)
        # Close coroutine to avoid "never awaited" warnings
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch.dict(sys.modules, {"server": fake_server}), \
         patch.object(bpl.asyncio, "create_task", side_effect=_capture_task):
        result = asyncio.run(bpl._enqueue_for_user_session(
            profile_config={"id": "profile-xyz", "user_id": "u1"},
            session_id="session-abc",
            start_url="https://example.com",
            on_session_update=callback,
        ))
    assert result["queued"] is True
    assert len(created) >= 1
    callback.assert_awaited()
    assert callback.await_args.args[0]["status"] == "queued"
