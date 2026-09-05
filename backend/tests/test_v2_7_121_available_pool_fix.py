"""v2.7.121 — available-for-profiles must not self-exclude free pool IPs."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_7_121():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.121")


def test_available_excludes_only_profiles_and_clicks():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "include_proxy_list_ips: bool = True" in src
    assert "include_proxy_list_ips=False" in src
    assert "do NOT self-exclude" in src
    assert "seen_exit" in src
    assert "require_verified = True  # v2.7.120 — always required" in src


def test_saved_assign_atomic_claim():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "find_one_and_update" in src
    assert "Atomic claim then delete" in src
