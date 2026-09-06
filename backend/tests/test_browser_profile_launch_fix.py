"""
Unit tests for the v2.1.59 browser_profile_launcher.py crash-visibility fix.

Verifies that ANY failure path during a profile launch:
  1. Notifies the cloud via on_session_update(status="error", error_message=...)
  2. Cleans up _RUNNING_SESSIONS so the slot is reclaimed
  3. Does NOT silently swallow the exception (which was the root cause
     of profile cards being stuck on "launching" forever).

Run with:
    cd /app/krexion_repo/backend
    python -m pytest tests/test_browser_profile_launch_fix.py -v --asyncio-mode=auto
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

import browser_profile_launcher as bpl


# Test env doesn't have a real Playwright binary, so inject a stub
# module so the wrapper's `from playwright.async_api import ...` succeeds.
# The actual launch flow is patched per-test via `_launch_profile_session_inner`.
import types
_pw_stub = types.ModuleType("playwright")
_pw_async_stub = types.ModuleType("playwright.async_api")
_pw_async_stub.async_playwright = lambda: None  # type: ignore[attr-defined]
_pw_async_stub.Page = object  # type: ignore[attr-defined]
_pw_async_stub.BrowserContext = object  # type: ignore[attr-defined]
_pw_async_stub.Browser = object  # type: ignore[attr-defined]
sys.modules.setdefault("playwright", _pw_stub)
sys.modules.setdefault("playwright.async_api", _pw_async_stub)


class _UpdateCollector:
    """Records every on_session_update call so the test can assert on them."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, body: Dict[str, Any]) -> None:
        self.calls.append(body)


# ─────────────────────────── Tests ────────────────────────────────────

# Helper: headed Chromium preflight must not block unit tests that only
# exercise the crash-visibility wrapper around `_launch_profile_session_inner`.
_READY_ENGINE = {"status": "ready", "message": "stub"}


def _patch_launch_preflight():
    return (
        patch(
            "real_user_traffic.get_headed_engine_status",
            return_value=dict(_READY_ENGINE),
        ),
        patch(
            "real_user_traffic._full_chromium_binary_path",
            return_value=Path("/tmp/fake-chrome"),
        ),
        patch(
            "real_user_traffic.normalize_playwright_browsers_path",
            return_value="/tmp/pw",
        ),
    )


@pytest.mark.asyncio
async def test_playwright_import_failure_notifies_error():
    """When Playwright is unavailable, the function MUST notify the cloud
    via status="error" so the profile card un-sticks from 'launching'."""
    collector = _UpdateCollector()
    # Remove the stub so the wrapper's import actually fails.
    _saved = (sys.modules.pop("playwright.async_api", None), sys.modules.pop("playwright", None))
    # Mark as unimportable so re-import inside the function raises ImportError
    sys.modules["playwright.async_api"] = None  # type: ignore[assignment]
    try:
        result = await bpl.launch_profile_session(
            {"id": "p1"},
            session_id="s1",
            start_url="https://example.com",
            on_session_update=collector,
        )
    finally:
        # Restore stubs so subsequent tests / modules can import playwright
        sys.modules.pop("playwright.async_api", None)
        sys.modules.pop("playwright", None)
        sys.modules["playwright"] = _pw_stub
        sys.modules["playwright.async_api"] = _pw_async_stub
    assert result["ok"] is False
    assert ("Playwright" in result["error"] or "Krexion Browser engine" in result["error"])
    # Critical assertion — cloud was notified, profile card will un-stick
    assert len(collector.calls) == 1
    notice = collector.calls[0]
    assert notice["status"] == "error"
    assert notice["session_id"] == "s1"
    assert notice["profile_id"] == "p1"
    assert ("Playwright" in notice["error_message"] or "Krexion Browser engine" in notice["error_message"])


@pytest.mark.asyncio
async def test_inner_launch_crash_notifies_and_cleans_up():
    """When the inner browser-launch flow crashes, the wrapper MUST
    a) report the error to the cloud,
    b) clean up _RUNNING_SESSIONS,
    c) return a dict (not raise into the asyncio.create_task void)."""
    collector = _UpdateCollector()

    async def _crash(*_args, **_kwargs):
        raise RuntimeError("simulated chromium launch failed")

    p1, p2, p3 = _patch_launch_preflight()
    with p1, p2, p3, patch.object(bpl, "_launch_profile_session_inner", side_effect=_crash):
        result = await bpl.launch_profile_session(
            {"id": "p2"},
            session_id="s2",
            start_url="https://example.com",
            on_session_update=collector,
        )

    # Function returned cleanly (no exception bubbled into asyncio task)
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert "simulated chromium launch failed" in result["error"]

    # Cloud notified with error
    assert len(collector.calls) == 1
    notice = collector.calls[0]
    assert notice["status"] == "error"
    assert notice["profile_id"] == "p2"
    assert notice["session_id"] == "s2"
    assert "RuntimeError" in notice["error_message"] or "simulated" in notice["error_message"]

    # _RUNNING_SESSIONS cleaned up
    assert "s2" not in bpl._RUNNING_SESSIONS


@pytest.mark.asyncio
async def test_inner_launch_crash_without_callback_still_cleans_up():
    """Even when on_session_update is None (e.g. local desktop direct
    call), the wrapper must not raise and must still clean up state."""

    async def _crash(*_args, **_kwargs):
        raise ValueError("oops")

    p1, p2, p3 = _patch_launch_preflight()
    with p1, p2, p3, patch.object(bpl, "_launch_profile_session_inner", side_effect=_crash):
        result = await bpl.launch_profile_session(
            {"id": "p3"},
            session_id="s3",
            start_url="https://example.com",
            on_session_update=None,
        )

    assert result["ok"] is False
    assert "oops" in result["error"]
    assert "s3" not in bpl._RUNNING_SESSIONS


@pytest.mark.asyncio
async def test_successful_inner_result_returned_verbatim():
    """When the inner launch returns successfully, the wrapper must
    forward the result without modification."""
    collector = _UpdateCollector()

    async def _ok(*_args, **_kwargs):
        return {"ok": True, "session_id": "s4", "duration_sec": 12.3}

    p1, p2, p3 = _patch_launch_preflight()
    with p1, p2, p3, patch.object(bpl, "_launch_profile_session_inner", side_effect=_ok):
        result = await bpl.launch_profile_session(
            {"id": "p4"},
            session_id="s4",
            start_url="https://example.com",
            on_session_update=collector,
        )
    assert result == {"ok": True, "session_id": "s4", "duration_sec": 12.3}
    # No error notice when inner returns cleanly
    assert collector.calls == []
    # Session removed (the inner usually removes itself but the wrapper
    # finally-clause re-removes defensively)
    assert "s4" not in bpl._RUNNING_SESSIONS


@pytest.mark.asyncio
async def test_callback_failure_does_not_raise_during_error_notify():
    """If on_session_update itself raises while notifying the error, the
    wrapper must NOT propagate that to the asyncio task (otherwise we'd
    re-introduce the original silent-crash bug)."""

    async def _crash_callback(_body):
        raise ConnectionError("cloud unreachable")

    async def _crash(*_args, **_kwargs):
        raise RuntimeError("inner crash")

    p1, p2, p3 = _patch_launch_preflight()
    with p1, p2, p3, patch.object(bpl, "_launch_profile_session_inner", side_effect=_crash):
        result = await bpl.launch_profile_session(
            {"id": "p5"},
            session_id="s5",
            start_url="https://example.com",
            on_session_update=_crash_callback,
        )
    assert result["ok"] is False
    assert "inner crash" in result["error"]
    assert "s5" not in bpl._RUNNING_SESSIONS


@pytest.mark.asyncio
async def test_concurrent_launches_isolate_sessions():
    """Two concurrent failing launches must each notify their OWN cloud
    record without bleeding session_ids across notifications."""
    c1 = _UpdateCollector()
    c2 = _UpdateCollector()

    async def _crash_after_delay(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        raise RuntimeError("boom")

    p1, p2, p3 = _patch_launch_preflight()
    with p1, p2, p3, patch.object(bpl, "_launch_profile_session_inner", side_effect=_crash_after_delay):
        r1, r2 = await asyncio.gather(
            bpl.launch_profile_session(
                {"id": "pA"}, session_id="sA", start_url="x", on_session_update=c1
            ),
            bpl.launch_profile_session(
                {"id": "pB"}, session_id="sB", start_url="x", on_session_update=c2
            ),
        )
    assert r1["ok"] is False and r2["ok"] is False
    assert len(c1.calls) == 1 and c1.calls[0]["session_id"] == "sA"
    assert len(c2.calls) == 1 and c2.calls[0]["session_id"] == "sB"
    assert "sA" not in bpl._RUNNING_SESSIONS
    assert "sB" not in bpl._RUNNING_SESSIONS
