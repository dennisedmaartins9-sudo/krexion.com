"""v2.7.129 — AdsPower-parity Krexion profile branding (SunBrowser-class UX)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_129():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.129")


def test_profile_branding_api():
    from krexion_profile_branding import (
        ICON_MODES,
        PRODUCT_BROWSER,
        PRODUCT_SAFARI,
        app_user_model_id,
        build_window_title,
        chromium_app_user_model_arg,
        resolve_icon_mode,
        sanitize_user_facing,
    )

    assert PRODUCT_BROWSER == "Krexion Browser"
    assert PRODUCT_SAFARI == "Krexion Safari"
    assert "profile_no" in ICON_MODES
    assert resolve_icon_mode({"taskbar_icon_mode": "notes"}, {}) == "notes"
    title = build_window_title(
        slot=12,
        name="Shop EU",
        notes="fb ads",
        custom_no="99001234",
        icon_mode="custom_no",
    )
    assert "Krexion Browser" in title
    assert "1234" in title
    assert "Shop EU" in title
    safari = build_window_title(slot=1, name="iOS", icon_mode="name", webkit=True)
    assert safari.startswith("Krexion Safari")
    assert app_user_model_id(3) == "Krexion.BrowserProfile.3"
    assert "Krexion.BrowserProfile.3" in chromium_app_user_model_arg(3)
    cleaned = sanitize_user_facing(
        "Opening Chromium… Playwright WebKit MiniBrowser ready"
    )
    assert "Chromium" not in cleaned
    assert "Playwright" not in cleaned
    assert "MiniBrowser" not in cleaned
    assert "Krexion Browser" in cleaned or "Krexion Safari" in cleaned


def test_branded_safari_api_exists():
    import krexion_branded_browser as bb

    assert hasattr(bb, "ensure_krexion_safari_binary")
    assert hasattr(bb, "ensure_krexion_browser_binary")


def test_window_icon_has_title_keeper_and_safari_exe():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "def keep_krexion_window_title" in src
    assert "krexion-safari.exe" in src


def test_launcher_uses_branding_and_safari_binary():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "krexion_profile_branding" in src
    assert "build_window_title" in src
    assert "ensure_krexion_safari_binary" in src
    assert "Opening Krexion Browser" in src or "Krexion Browser engine" in src
    assert "Waiting for Krexion tray" in src and "Krexion Browser" in src
    assert "Chromium browser engine is still downloading" not in src


def test_module_launch_message_branded():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "Opening Krexion Browser on this PC" in src
    assert "Opening Chromium on this PC" not in src


def test_fe_adspower_parity_labels():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(
        encoding="utf-8"
    )
    assert "Krexion Browser opens" in fe or "Krexion Browser opens on" in fe
    assert "bp-taskbar-icon-mode" in fe
    assert "taskbar_icon_mode" in fe
    assert "Krexion Safari" in fe or "Krexion phone shell" in fe
    # Primary UX must not advertise stock Chromium launch
    assert "Chromium opens on this PC" not in fe
    assert "Playwright WebKit +" not in fe
