"""v2.6.78 — team DB check runs at proxy pick, before 'Unique IP found'."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

_RUT = os.path.join(os.path.dirname(__file__), "..", "real_user_traffic.py")


def _src() -> str:
    with open(_RUT, encoding="utf-8") as f:
        return f.read()


def test_try_team_reserve_helper_exists():
    src = _src()
    assert "async def _try_team_reserve_exit_ip(" in src


def test_proxy_loop_calls_team_before_unique_reserve():
    src = _src()
    assert "team DB BEFORE \"Unique IP\"" in src
    idx = src.index("team DB BEFORE")
    chunk = src[idx : idx + 1200]
    assert "_try_team_reserve_exit_ip(" in chunk
    assert "duplicate_ip_set.add(exit_ip)" in chunk
    assert chunk.index("_try_team_reserve_exit_ip(") < chunk.index("duplicate_ip_set.add(exit_ip)")


def test_team_claim_skipped_when_already_acquired_at_proxy():
    src = _src()
    assert "if not _team_claim_acquired:" in src
    assert "_team_claim_acquired = True" in src


def test_team_duplicate_retries_in_proxy_loop_not_filter_only():
    src = _src()
    assert "team duplicate {exit_ip}, retrying" in src
