"""v2.7.98 — Permanent profile launch UI: one shell, stable taskbar icon."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_brands_once_after_navigation():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_brand_krexion_taskbar(mobile_shell=False)" not in src
    assert "Early Krexion phone chrome" in src
    assert "post-nav" in src.lower()
    assert "require_embed=True" in src


def test_launcher_passes_session_key_to_icon_keeper():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "session_key=str(session_id)" in src
    assert "stop_session_icon_keeper" in src


def test_legacy_ios_shell_not_with_mobile_shell():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_will_try_mobile_shell" in src
    assert "apply_ios_safari_shell_to_pids" not in src


def test_window_icon_session_keeper():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "stop_session_icon_keeper" in src
    assert "hide_hwnd_from_taskbar" in src
    assert "stop_event" in src


def test_mobile_shell_hides_engine_from_taskbar():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "hide_hwnd_from_taskbar" in src
    assert "stop_event" in src


def test_shell_death_keeps_session_only_if_engine_on_taskbar():
    # v2.7.125 — hidden TOOLWINDOW engines must NOT stay "running" (ghost).
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "profile_engine_visible_on_taskbar" in src
    assert 'sess["mobile_shell"] = False' in src


def test_version_is_2_7_98():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 98]
