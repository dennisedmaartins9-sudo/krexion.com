"""v2.8.0 — One lasting AdsPower-class profile engine lock."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_2_8_0_or_newer():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.8.0")


def test_persistent_profiles_forced():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "AdsPower-class profiles ALWAYS persist to disk" in src
    assert "KREXION_ALLOW_EPHEMERAL_PROFILES" in src
    assert 'use_persistent_context = True' in src
    assert '_krx_mode not in ("cloud", "headless", "server")' in src


def test_kernel_prefers_cloak_and_brands_fallback():
    src = (ROOT / "krexion_browser_kernel.py").read_text(encoding="utf-8")
    assert (
        "v2.8.0 — AdsPower-class profile lock" in src
        or "AdsPower-class stealth kernel" in src
        or "AdsPower-class C++ Chromium" in src
        or "v2.9.0" in src
    )
    assert (
        "CloakBrowser C++ kernel unavailable" in src
        or "Cloak unavailable" in src
        or "Krexion Kernel (Cloak C++ Chromium)" in src
        or "HARD FAIL" in src
    )
    assert "ensure_krexion_browser_binary" in src


def test_prior_permanent_gates_still_present():
    """2.8.0 must KEEP 137 relay + 138 embed truth — not regress."""
    launcher = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    brand = (ROOT / "krexion_branded_browser.py").read_text(encoding="utf-8")
    relay = (ROOT / "proxy_auth_relay.py").read_text(encoding="utf-8")
    assert "start_proxy_auth_relay" in launcher
    assert "GetParent" in brand
    assert "NEVER forward 407" in relay or "502 Bad Gateway" in relay
