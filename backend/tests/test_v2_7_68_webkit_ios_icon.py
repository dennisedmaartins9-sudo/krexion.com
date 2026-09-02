"""v2.7.68 — WebKit / iOS Safari profile taskbar + title-bar icon."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_68():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 68]


def test_webkit_pid_and_title_helpers():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "find_webkit_browser_pids" in src
    assert "find_pids_by_window_title_substrings" in src
    assert "brand_single_hwnd_krexion" in src
    assert "minibrowser.exe" in src


def test_launcher_webkit_icon_markers():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "include_webkit=_include_webkit" in src
    assert 'window_title_markers=_title_markers' in src
    assert '"[WebKit]"' in src


def test_ios_shell_applies_krexion_icon():
    src = (ROOT / "krexion_ios_safari_shell.py").read_text(encoding="utf-8")
    assert "brand_single_hwnd_krexion" in src
    assert "profile_slot" in src
    assert "find_webkit_browser_pids" in src
