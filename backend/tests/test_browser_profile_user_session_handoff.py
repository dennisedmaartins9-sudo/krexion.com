"""
test_browser_profile_user_session_handoff.py
=============================================
2026-06-28 — Verify browser-profile launches on NSSM-installed Windows
build are deferred to a user-session helper (tray app) instead of being
spawned by the Windows Service backend (which runs in Session 0 and
cannot display GUI windows on the user's desktop).

Before this fix: customer clicks Launch → backend (Session 0) spawns
Chromium → Chromium process exists but no window appears → profile
stuck on "launching..." forever. THE root cause of the customer report
"Browser Profile launch karte hein pr launch nahi hoti, proper chalti
nahi". Electron build never hit this because its backend is a child of
the user-session main process.

These tests verify:
  1. `_should_defer_to_user_session()` returns True only when
     `KREXION_BUILD_TYPE=binary` on Windows.
  2. `_should_defer_to_user_session()` returns False on Linux/macOS
     (cloud VPS, dev machines), regardless of env vars.
  3. `_should_defer_to_user_session()` returns False on Windows when
     `KREXION_BUILD_TYPE` is not set (Electron build).
  4. `launch_profile_session()` routes through `_enqueue_for_user_session`
     when defer is True.
  5. `launch_profile_session()` routes through `_launch_session_inline`
     when defer is False.
  6. `_enqueue_for_user_session()` inserts a record with the right shape
     into `browser_launch_queue` and notifies the callback with
     status="queued".
  7. `process_pending_user_session_launches()` atomically claims a
     queued record and starts a background task that calls
     `_launch_session_inline`.
  8. Stop requests on already-claimed entries propagate via
     `request_stop()` and are marked acknowledged so they don't loop.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import browser_profile_launcher as bpl  # noqa: E402


# ── _should_defer_to_user_session() ─────────────────────────────────

def test_defer_on_windows_binary_build():
    with patch.object(bpl.sys, "platform", "win32"), \
         patch.dict(bpl.os.environ, {"KREXION_BUILD_TYPE": "binary"}, clear=False):
        assert bpl._should_defer_to_user_session() is True


def test_no_defer_on_windows_without_build_type():
    with patch.object(bpl.sys, "platform", "win32"), \
         patch.dict(bpl.os.environ, {}, clear=True):
        # Electron build: KREXION_BUILD_TYPE unset → spawn inline
        assert bpl._should_defer_to_user_session() is False


def test_no_defer_on_windows_with_other_build_type():
    with patch.object(bpl.sys, "platform", "win32"), \
         patch.dict(bpl.os.environ, {"KREXION_BUILD_TYPE": "electron"}, clear=False):
        assert bpl._should_defer_to_user_session() is False


def test_no_defer_on_linux_even_with_binary_build_type():
    with patch.object(bpl.sys, "platform", "linux"), \
         patch.dict(bpl.os.environ, {"KREXION_BUILD_TYPE": "binary"}, clear=False):
        # Should never defer on non-Windows — cloud VPS is always inline
        assert bpl._should_defer_to_user_session() is False


def test_no_defer_on_darwin():
    with patch.object(bpl.sys, "platform", "darwin"), \
         patch.dict(bpl.os.environ, {"KREXION_BUILD_TYPE": "binary"}, clear=False):
        assert bpl._should_defer_to_user_session() is False


# ── launch_profile_session() routing ────────────────────────────────

def test_launch_routes_to_enqueue_on_session0_service():
    """When defer=True, the function MUST go via the queue, never spawn
    Chromium directly. This is the entire fix."""
    fake_enqueue = AsyncMock(return_value={"ok": True, "queued": True})
    fake_inline = AsyncMock(return_value={"ok": True, "duration_sec": 1})
    with patch.object(bpl, "_should_defer_to_user_session", return_value=True), \
         patch.object(bpl, "_enqueue_for_user_session", fake_enqueue), \
         patch.object(bpl, "_launch_session_inline", fake_inline):
        result = asyncio.run(bpl.launch_profile_session(
            {"id": "p1"}, session_id="s1", start_url="https://example.com",
        ))
        fake_enqueue.assert_awaited_once()
        fake_inline.assert_not_called()
        assert result["queued"] is True


def test_launch_routes_to_inline_on_normal_environment():
    """When defer=False (cloud, Electron, dev), spawn inline — preserving
    existing behaviour for all non-NSSM-service deployments."""
    fake_enqueue = AsyncMock(return_value={"ok": True, "queued": True})
    fake_inline = AsyncMock(return_value={"ok": True, "duration_sec": 1})
    with patch.object(bpl, "_should_defer_to_user_session", return_value=False), \
         patch.object(bpl, "_enqueue_for_user_session", fake_enqueue), \
         patch.object(bpl, "_launch_session_inline", fake_inline):
        result = asyncio.run(bpl.launch_profile_session(
            {"id": "p1"}, session_id="s1", start_url="https://example.com",
        ))
        fake_inline.assert_awaited_once()
        fake_enqueue.assert_not_called()
        assert result["duration_sec"] == 1


# ── _enqueue_for_user_session() ─────────────────────────────────────

def test_enqueue_inserts_record_and_notifies():
    """The enqueue helper must write a complete queue record AND call
    the on_session_update callback with status='queued' so the frontend
    flips off the 'launching...' state immediately."""
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
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch.dict(sys.modules, {"server": fake_server}), \
         patch.object(bpl.asyncio, "create_task", side_effect=_capture_task):
        result = asyncio.run(bpl._enqueue_for_user_session(
            profile_config={"id": "profile-xyz", "name": "Test"},
            session_id="session-abc",
            start_url="https://example.com",
            on_session_update=callback,
        ))

    # Record inserted
    fake_collection.insert_one.assert_awaited_once()
    inserted = fake_collection.insert_one.call_args[0][0]
    assert inserted["id"] == "session-abc"
    assert inserted["profile_id"] == "profile-xyz"
    assert inserted["status"] == "queued"
    assert inserted["start_url"] == "https://example.com"
    assert inserted["profile_config"]["name"] == "Test"

    # Callback received status=queued
    callback.assert_awaited_once()
    cb_arg = callback.call_args[0][0]
    assert cb_arg["status"] == "queued"
    assert cb_arg["session_id"] == "session-abc"

    assert result["queued"] is True
    assert result["ok"] is True
    assert len(created) >= 1  # tray pickup watchdog scheduled


# ── process_pending_user_session_launches() ─────────────────────────

def test_process_pending_claims_queued_entry_and_runs_launch():
    """Tray-app helper claims queued entries (up to KREXION_TRAY_MAX_PARALLEL),
    marks each claimed, and spawns background inline launches."""
    queued_record = {
        "id": "session-001",
        "profile_id": "profile-001",
        "profile_config": {"id": "profile-001"},
        "start_url": "https://example.com",
        "status": "queued",
    }

    queue_collection = AsyncMock()
    # First claim returns the doc; subsequent polls see empty queue.
    queue_collection.find_one_and_update = AsyncMock(
        side_effect=[queued_record, None]
    )
    queue_collection.update_one = AsyncMock()
    queue_collection.find = MagicMock(return_value=_async_iter([]))

    sessions_collection = AsyncMock()
    profiles_collection = AsyncMock()

    motor_db = MagicMock()
    motor_db.__getitem__.return_value = queue_collection
    motor_db.browser_profile_sessions = sessions_collection
    motor_db.browser_profiles = profiles_collection

    inline_calls = []

    async def fake_inline(profile_config, **kwargs):
        inline_calls.append((profile_config, kwargs))
        return {"ok": True, "session_id": kwargs.get("session_id")}

    async def run_test():
        with patch.object(bpl, "_launch_session_inline", fake_inline):
            processed = await bpl.process_pending_user_session_launches(motor_db)
            # Let the fire-and-forget background task complete
            await asyncio.sleep(0.05)
            return processed

    processed = asyncio.run(run_test())
    assert processed == 1
    queue_collection.find_one_and_update.assert_awaited()
    assert len(inline_calls) == 1
    cfg, kwargs = inline_calls[0]
    assert cfg["id"] == "profile-001"
    assert kwargs["session_id"] == "session-001"


def test_process_pending_returns_zero_when_queue_empty():
    """No queued entries → returns 0 quickly, doesn't spawn anything."""
    queue_collection = AsyncMock()
    queue_collection.find_one_and_update = AsyncMock(return_value=None)
    queue_collection.find = MagicMock(return_value=_async_iter([]))

    motor_db = MagicMock()
    motor_db.__getitem__.return_value = queue_collection

    async def run_test():
        with patch.object(bpl, "_launch_session_inline", AsyncMock()):
            return await bpl.process_pending_user_session_launches(motor_db)

    processed = asyncio.run(run_test())
    assert processed == 0


def test_stop_request_propagates_via_request_stop():
    """When a backend writes stop_requested=True on a claimed entry,
    the tray-app helper must forward it to the in-process
    `request_stop()` so the headed browser closes correctly."""
    stop_record = {
        "id": "session-stop-1",
        "profile_id": "profile-stop-1",
        "status": "claimed",
        "stop_requested": True,
    }
    queue_collection = AsyncMock()
    def _find_side_effect(query):
        q = query or {}
        if q.get("status") == "queued":
            return _async_iter([])
        if q.get("status") == "claimed":
            return _async_iter([stop_record])
        return _async_iter([])

    queue_collection.find = MagicMock(side_effect=_find_side_effect)
    queue_collection.update_one = AsyncMock()
    queue_collection.find_one_and_update = AsyncMock(return_value=None)

    motor_db = MagicMock()
    motor_db.__getitem__.return_value = queue_collection

    with patch.object(bpl, "request_stop") as mock_stop:
        asyncio.run(bpl.process_pending_user_session_launches(motor_db))
        mock_stop.assert_called_once_with("session-stop-1")
    # Should also mark the stop as acknowledged so it doesn't loop
    queue_collection.update_one.assert_awaited()
    ack_call_args = queue_collection.update_one.call_args
    assert "$set" in ack_call_args[0][1]
    assert ack_call_args[0][1]["$set"]["stop_acknowledged"] is True


# ── Helpers ─────────────────────────────────────────────────────────

def _async_iter(items):
    """Simulate motor's AsyncIOMotorCursor for `async for` consumption."""
    class _Iter:
        def __init__(self, items):
            self._items = list(items)
            self._idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(self._items):
                raise StopAsyncIteration
            v = self._items[self._idx]
            self._idx += 1
            return v
    return _Iter(items)
