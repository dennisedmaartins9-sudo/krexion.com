"""v2.6.86 — PyMongo Database must not be used in boolean context."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

import real_user_traffic as rut  # noqa: E402


def test_team_reserve_none_db_short_circuits():
    ok, result = asyncio.run(
        rut._try_team_reserve_exit_ip(
            db=None,
            engine_user_id="user-1",
            offer_url="https://example.com/offer",
            exit_ip="1.2.3.4",
            visit_token="tok",
            skip_duplicate_ip=True,
            tracker_missing_offer=False,
        )
    )
    assert ok is True
    assert result == {}


def test_source_uses_db_is_not_none():
    src = Path(rut.__file__).read_text(encoding="utf-8")
    assert "if not (db and engine_user_id" not in src
    assert "db is None or not (engine_user_id" in src


def test_team_reserve_bool_db_would_crash_old_code():
    """Document the PyMongo failure mode we fixed."""
    class _FakeDb:
        def __bool__(self):
            raise NotImplementedError("database is not None")

    db = _FakeDb()
    raised = False
    try:
        bool(db)
    except NotImplementedError:
        raised = True
    assert raised
    # New guard must use identity check, not bool().
    assert (db is None) is False
