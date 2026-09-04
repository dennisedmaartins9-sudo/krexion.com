"""v2.7.10 — WebKit bundled in native EXE (no manual playwright install)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_2_7_10():
    from releases_module import _parse as _semver_parse
    assert _semver_parse((ROOT / "backend" / "VERSION").read_text(encoding="utf-8").strip()) >= _semver_parse("2.7.10")


def test_windows_release_workflow_installs_webkit():
    src = (ROOT / ".github" / "workflows" / "build-windows-release.yml").read_text(
        encoding="utf-8"
    )
    assert "playwright install chromium chromium-headless-shell webkit" in src
    assert "webkit-*" in src or "WebKit present" in src


def test_local_build_script_installs_webkit():
    src = (ROOT / "Build-Krexion-Windows.ps1").read_text(encoding="utf-8")
    assert "webkit" in src.lower()
    assert "chromium-headless-shell" in src or "chromium" in src


def test_inno_ships_browser_engine_bundle():
    src = (ROOT / "installer" / "krexion-setup.iss").read_text(encoding="utf-8")
    assert r"{app}\browser-engine" in src
    assert "chromium-bundle" in src
    assert "WebKit" in src or "webkit" in src.lower()


def test_server_schedules_webkit_ensure_on_startup():
    src = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "_ensure_playwright_webkit" in src
    assert "_ensure_webkit_available" in src


def test_bootstrap_ensures_webkit():
    src = (ROOT / "backend" / "browser_bootstrap.py").read_text(encoding="utf-8")
    assert "ensure_webkit_installed" in src
    assert "ensure_webkit_installed" in src.split("__all__")[-1]
