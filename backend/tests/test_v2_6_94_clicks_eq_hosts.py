"""v2.6.94 — Affise Clicks must equal Hosts (one click per unique exit IP)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
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

from real_user_traffic import (  # noqa: E402
    _dup_set_contains,
    _reserve_unique_exit_ip,
)

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"
SERVER = Path(__file__).resolve().parents[1] / "server.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_empty_dup_set_is_active_not_off():
    """Python empty set is falsy — that used to skip the first concurrent wave."""
    empty: set = set()
    assert _dup_set_contains(empty, "1.2.3.4") is False
    assert _dup_set_contains(None, "1.2.3.4") is False


def test_reserve_rejects_second_claim_on_same_ip():
    dup: set = set()

    async def _run():
        lock = asyncio.Lock()
        first = await _reserve_unique_exit_ip(dup, lock, "8.8.8.8")
        second = await _reserve_unique_exit_ip(dup, lock, "8.8.8.8")
        other = await _reserve_unique_exit_ip(dup, lock, "1.1.1.1")
        return first, second, other

    first, second, other = asyncio.run(_run())
    assert first is True
    assert second is False
    assert other is True
    assert _dup_set_contains(dup, "8.8.8.8")
    assert _dup_set_contains(dup, "1.1.1.1")


def test_concurrent_workers_cannot_share_one_exit_ip():
    dup: set = set()

    async def _run():
        lock = asyncio.Lock()

        async def _worker():
            return await _reserve_unique_exit_ip(dup, lock, "74.102.81.241")

        results = await asyncio.gather(*[_worker() for _ in range(5)])
        return results

    results = asyncio.run(_run())
    assert results.count(True) == 1
    assert results.count(False) == 4


def test_none_set_means_uniqueness_off():
    async def _run():
        return await _reserve_unique_exit_ip(None, None, "8.8.8.8")

    assert asyncio.run(_run()) is True


def test_row_first_uses_atomic_reserve_not_falsy_set():
    src = _src()
    assert "and duplicate_ip_set and exit_ip in duplicate_ip_set" not in src
    assert "await _reserve_unique_exit_ip(" in src
    assert "duplicate_ip_lock = asyncio.Lock()" in src
    assert "skip_duplicate_ip and duplicate_ip_set is None" in src


def test_click_once_never_retries_same_proxy():
    src = _src()
    assert "Click-once: not retrying same proxy" in src
    idx = src.index("Click-once: not retrying same proxy")
    assert "same_proxy_retry += 1" not in src[idx : idx + 180]


def test_networkidle_gated_on_click_once():
    src = _src()
    assert "never networkidle on click-once" in src
    # The old unconditional 6s settle wait must not remain.
    assert (
        'await page.wait_for_load_state("networkidle", timeout=6000)'
        in src
    )
    idx = src.index("v2.6.94 — never networkidle on click-once")
    chunk = src[idx : idx + 350]
    assert "_click_once_nav" in chunk


def test_dup_fetch_failure_keeps_in_job_set():
    text = SERVER.read_text(encoding="utf-8")
    assert "continuing with empty in-job set" in text
    assert "dup_ip_set = None" not in text.split("dup-IP fetch failed")[1][:400]
