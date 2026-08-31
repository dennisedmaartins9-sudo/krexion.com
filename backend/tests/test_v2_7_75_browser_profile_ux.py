"""v2.7.75 — Browser profile UX: auto-stop on close, templates API."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_profile_user_closed_ui_no_live_pages():
    from browser_profile_launcher import _RUNNING_SESSIONS, _profile_user_closed_ui

    sid = "sess_test_close"
    _RUNNING_SESSIONS[sid] = {"driver_pid": 99999, "mobile_shell": False, "webkit": False}
    ctx = MagicMock()
    closed_page = MagicMock(is_closed=lambda: True)
    ctx.pages = [closed_page]
    browser = MagicMock(is_connected=lambda: True)

    with patch("browser_profile_launcher.sys.platform", "linux"):
        assert _profile_user_closed_ui(sid, ctx, browser, set()) is True

    _RUNNING_SESSIONS.pop(sid, None)


def test_profile_user_closed_ui_minimize_keeps_session_on_linux():
    from browser_profile_launcher import _RUNNING_SESSIONS, _profile_user_closed_ui

    sid = "sess_test_alive"
    _RUNNING_SESSIONS[sid] = {"driver_pid": 12345, "mobile_shell": False}
    page = MagicMock(is_closed=lambda: False)
    ctx = MagicMock(pages=[page])
    browser = MagicMock(is_connected=lambda: True)

    with patch("browser_profile_launcher.sys.platform", "linux"):
        assert _profile_user_closed_ui(sid, ctx, browser, {page}) is False

    _RUNNING_SESSIONS.pop(sid, None)


def test_is_mobile_shell_alive_false_when_not_registered():
    from krexion_mobile_browser_shell import is_mobile_shell_alive

    assert is_mobile_shell_alive("missing-session-key") is False


def test_profile_engine_window_exists_unknown_pid():
    from krexion_window_icon import profile_engine_window_exists

    assert profile_engine_window_exists(None) is True
    assert profile_engine_window_exists(0) is True


def test_profile_templates_crud():
    import asyncio
    from browser_profile_module import save_profile_template, list_profile_templates, delete_profile_template
    from browser_profile_module import SaveProfileTemplateBody

    class FakeCursor:
        def __init__(self, docs):
            self._docs = list(docs)

        def sort(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def __aiter__(self):
            async def _gen():
                for d in self._docs:
                    yield d

            return _gen()

    inserted = {}

    class FakeCol:
        async def insert_one(self, doc):
            inserted.update(doc)

        def find(self, filt):
            if filt.get("user_id") == "u1":
                return FakeCursor([inserted] if inserted.get("user_id") == "u1" else [])
            return FakeCursor([])

        async def delete_one(self, filt):
            if inserted.get("id") == filt.get("id") and inserted.get("user_id") == filt.get("user_id"):
                inserted.clear()
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

    req = MagicMock()

    async def _run():
        with patch("browser_profile_module._resolve_user", return_value={"id": "u1"}), patch(
            "browser_profile_module._resolve_user_or_401", return_value="u1"
        ), patch("browser_profile_module._DB") as mock_db, patch(
            "browser_profile_module._now_iso", return_value="2026-08-31T00:00:00Z"
        ), patch("browser_profile_module.secrets.token_hex", return_value="abc12345"):
            mock_db.browser_profile_templates = FakeCol()
            body = SaveProfileTemplateBody(
                name="US Mobile Proxy",
                settings={"advMix": {"ios": 0, "android": 100, "desktop": 0}},
            )
            saved = await save_profile_template(req, body)
            assert saved["ok"] is True
            tid = saved["template"]["id"]
            assert tid.startswith("bpt_")

            listed = await list_profile_templates(req)
            assert len(listed["templates"]) == 1
            assert listed["templates"][0]["name"] == "US Mobile Proxy"

            deleted = await delete_profile_template(req, tid)
            assert deleted["deleted"] is True

            listed2 = await list_profile_templates(req)
            assert listed2["templates"] == []

    asyncio.run(_run())
