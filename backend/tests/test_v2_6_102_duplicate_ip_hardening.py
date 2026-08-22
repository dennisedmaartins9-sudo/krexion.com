"""v2.6.102 — RUT duplicate-IP hardening (bypass lock, rotate retry, smart pre-probe)."""
from __future__ import annotations

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
    _exit_ips_match,
    _is_ipv6_exit_ip,
)

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_exit_ips_match_canonical():
    assert _exit_ips_match("38.59.42.230", "38.59.42.230") is True
    assert _exit_ips_match("38.59.42.230", "173.91.236.131") is False
    assert _exit_ips_match("", "1.1.1.1") is False


def test_is_ipv6_exit_ip():
    assert _is_ipv6_exit_ip("2603:6010::1") is True
    assert _is_ipv6_exit_ip("192.0.2.1") is False


def test_bypass_ip_mismatch_raises_retry_not_click():
    src = _src()
    assert "Bypass IP mismatch" in src
    assert 'reason="bypass_ip_mismatch"' in src
    assert "no click" in src and "registered" in src


def test_tunnel_rebind_failure_retries_slot():
    src = _src()
    assert 'reason="tunnel_rebind_failed"' in src
    assert "retrying visit" in src
    assert "stopping proxy rotation" not in src


def test_pre_probe_enabled_only_for_direct_offers():
    src = _src()
    assert "_pre_probe_offer =" in src
    assert "and not _is_tracker_target" in src
    assert "and not bool(_referer_cfg.get(\"pass_to_offer\"))" in src
    assert "if _pre_probe_offer:" in src
    assert "if False and _can_retry_offer_block" not in src


def test_proxyjet_picked_removed_at_pick_time():
    src = _src()
    assert 'reason="proxyjet_picked"' not in src
    assert "_spawn_persist_used_exit_ip" in src
    assert 'reason="visit_used"' in src


def test_ipv6_rejected_on_legacy_geo_path():
    src = _src()
    assert 'reason="ipv6_exit"' in src
    assert "_is_ipv6_exit_ip(geo.get(\"exit_ip\")" in src
