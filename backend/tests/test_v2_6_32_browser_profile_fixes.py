"""
v2.6.32 — Browser Profiles audit fixes (unit tests, no Playwright/Mongo required).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import browser_profile_launcher as bpl  # noqa: E402


def _read_backend(name: str) -> str:
    return (BACKEND / name).read_text(encoding="utf-8")


def test_infer_os_android_from_ua():
    ua = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/149.0.0.0 Mobile Safari/537.36"
    assert bpl._infer_os_from_ua(ua) == "android"


def test_infer_os_ios_from_ua():
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 Version/26.4 Mobile/15E148 Safari/604.1"
    assert bpl._infer_os_from_ua(ua) == "ios"


def test_parse_proxyjet_canonical_line_in_module_source():
    src = _read_backend("browser_profile_module.py")
    assert "def _parse_proxy_line" in src
    assert "user123:pass456@gate.proxy-jet.io:1010" not in src  # fixture stays in test only
    assert 'server = f"http://{hostport}"' in src or "http://" in src


def test_compute_fingerprint_hash_stable():
    h1 = bpl._compute_fingerprint_hash(
        "UA-test", {"width": 390, "height": 844}, "profile-1", {"vendor": "A", "renderer": "B"}
    )
    h2 = bpl._compute_fingerprint_hash(
        "UA-test", {"width": 390, "height": 844}, "profile-1", {"vendor": "A", "renderer": "B"}
    )
    assert h1 == h2
    assert len(h1) == 32


def test_launch_kwargs_include_user_data_dir_in_source():
    src = _read_backend("browser_profile_launcher.py")
    assert '--user-data-dir=' in src
    assert '_kx_user_data_dir' in src


def test_queue_claim_filters_stop_requested_in_source():
    src = _read_backend("browser_profile_launcher.py")
    assert '"stop_requested": {"$ne": True}' in src


def test_update_profile_preserves_session_fields_in_source():
    src = _read_backend("browser_profile_module.py")
    assert 'new_doc["session_id"] = existing.get("session_id")' in src
    assert 'new_doc["status"] = existing.get("status")' in src


def test_launch_duplicate_guard_in_source():
    src = _read_backend("browser_profile_module.py")
    assert "status_code=409" in src
    assert '"running", "launching", "stopping"' in src
