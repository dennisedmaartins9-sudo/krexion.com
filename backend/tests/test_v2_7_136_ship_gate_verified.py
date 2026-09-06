"""v2.7.136 — ship-gate verified green after Strict shell frame fix."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_7_136():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.136")


def test_early_soft_start_and_strict_post_nav_locked():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "require_embed=False" in src
    assert "Last-chance multi-pass discover" in src
    assert "Launch aborted so plain Chromium/" in src
