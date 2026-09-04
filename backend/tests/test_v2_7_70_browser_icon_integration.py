"""v2.7.70 — Official Krexion browser emblem in taskbar + mobile shell."""
from __future__ import annotations

from pathlib import Path


def test_version_is_2_7_76():
    root = Path(__file__).resolve().parents[1]
    from releases_module import _parse as _semver_parse
    assert _semver_parse((root / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.96")


def test_official_browser_icon_asset_exists():
    assets = Path(__file__).resolve().parents[1] / "assets"
    icon = assets / "krexion_browser_icon.png"
    assert icon.is_file(), "krexion_browser_icon.png must ship with backend"
    assert icon.stat().st_size > 5000


def test_build_profile_taskbar_ico_accepts_platform():
    src = Path(__file__).resolve().parents[1] / "krexion_window_icon.py"
    text = src.read_text(encoding="utf-8")
    assert "def build_profile_taskbar_ico(slot: int = 1, platform: str = \"\")" in text
    assert "def browser_icon_data_uri" in text
    assert "_apply_platform_tint" not in text


def test_mobile_shell_uses_official_mark():
    src = Path(__file__).resolve().parents[1] / "krexion_mobile_browser_shell.py"
    text = src.read_text(encoding="utf-8")
    assert "_krexion_mark_html" in text
    assert "browser_icon_data_uri" in text
    assert 'class="k-mark-sm"' in text or "k-mark-sm" in text


def test_launcher_passes_platform_to_icon_branding():
    src = Path(__file__).resolve().parents[1] / "browser_profile_launcher.py"
    text = src.read_text(encoding="utf-8")
    assert "platform=str(profile_os or \"\")" in text


def test_browser_icon_data_uri_builds():
    from krexion_window_icon import browser_icon_data_uri

    ios_uri = browser_icon_data_uri("ios", size=32)
    android_uri = browser_icon_data_uri("android", size=32)
    assert ios_uri.startswith("data:image/png;base64,")
    assert android_uri.startswith("data:image/png;base64,")
    assert ios_uri == android_uri
