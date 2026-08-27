"""v2.7.13 — Numbered Krexion browser taskbar icons for open profiles."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_numbered_ico_assets_shipped():
    assets = ROOT / "assets"
    assert (assets / "krexion_browser_icon.png").is_file()
    for n in (1, 2, 5, 10, 20):
        ico = assets / f"krexion_browser_p{n}.ico"
        assert ico.is_file(), f"missing {ico.name}"
        assert ico.stat().st_size > 2000, f"{ico.name} too small"


def test_build_profile_taskbar_ico_prefers_bundled():
    from krexion_window_icon import build_profile_taskbar_ico

    p2 = Path(build_profile_taskbar_ico(2))
    assert p2.name == "krexion_browser_p2.ico"
    assert p2.stat().st_size > 2000


def test_launcher_passes_profile_slot():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "taskbar_slot" in src
    assert "profile_slot=" in src
    assert "Krexion.BrowserProfile.{_taskbar_slot}" in src
    assert "KREXION_PROFILE_USE_SYSTEM_CHROME" in src


def test_icon_module_slot_app_id():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "build_profile_taskbar_ico" in src
    assert "profile_slot" in src
    assert "_png_to_ico_bytes" in src
    assert "Krexion.BrowserProfile" in src
