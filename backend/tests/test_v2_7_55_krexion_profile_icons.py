"""v2.7.55 — Krexion numbered icon on all profile engines (WebKit + Chromium)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_2_7_55():
    assert _read("VERSION").strip() == "2.7.64"


def test_collect_profile_process_tree_exists_in_source():
    src = _read("krexion_window_icon.py")
    assert "def collect_profile_process_tree" in src
    assert "krexion-coreapp.exe" in src


def test_launcher_always_applies_krexion_icon_before_ios_shell():
    src = _read("browser_profile_launcher.py")
    assert "collect_profile_process_tree" in src
    idx_icon = src.find("apply_krexion_icon_to_pids")
    idx_shell = src.find("apply_ios_safari_shell_to_pids")
    assert idx_icon != -1 and idx_shell != -1
    assert idx_icon < idx_shell


def test_ios_shell_does_not_set_safari_icon():
    src = _read("krexion_ios_safari_shell.py")
    assert "_safari_ico_path" not in src
    assert "krexion_window_icon" in src


def test_icon_loop_hides_playwright_helper_window():
    src = _read("krexion_window_icon.py")
    assert 'title.strip().lower() == "playwright"' in src
    assert "collect_profile_process_tree" in src
