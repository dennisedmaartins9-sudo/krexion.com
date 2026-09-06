"""v2.7.128 — Krexion branded browser binary (AdsPower-style one-window UX)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_128():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.128")


def test_branded_browser_module_api():
    import krexion_branded_browser as bb

    assert hasattr(bb, "ensure_krexion_browser_binary")
    assert hasattr(bb, "parent_engine_hwnd_into_shell")
    assert hasattr(bb, "branded_browser_info")
    info = bb.branded_browser_info()
    assert "path" in info and "available" in info


def test_kernel_applies_branded_binary():
    src = (ROOT / "krexion_browser_kernel.py").read_text(encoding="utf-8")
    assert "_apply_krexion_brand_binary" in src
    assert "ensure_krexion_browser_binary" in src
    assert "krexion-stealth-browser" in src
    assert "krexion-browser" in src


def test_pid_finder_includes_krexion_browser_exe():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "krexion-browser.exe" in src


def test_shell_host_has_content_hwnd_and_krexion_title():
    src = (ROOT / "krexion_mobile_shell_host.py").read_text(encoding="utf-8")
    assert 'handles["content"]' in src or '"content"' in src
    assert "Krexion.PhoneChrome" in src
    assert "KrexionContent-" in src or "content host" in src.lower()


def test_shell_loop_setparent_into_content():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "parent_engine_hwnd_into_shell" in src
    assert 'handles.get("content")' in src


def test_fe_krexion_browser_labels_not_chromium():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(
        encoding="utf-8"
    )
    assert "Krexion Browser (auto)" in fe
    assert "Krexion Browser Stealth" in fe
    # Primary options must not say stock Chromium to the user
    assert "Krexion Stealth Chromium" not in fe
