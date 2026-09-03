"""v2.7.102 — Permanent mobile shell + taskbar flicker fixes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hide_hwnd_no_showwindow_sw_show():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    # Must not re-ShowWindow after TOOLWINDOW — that caused taskbar flicker.
    assert "SW_SHOW — refresh taskbar grouping" not in src
    assert "SWP_FRAMECHANGED" in src
    assert "def _hwnd_is_toolwindow" in src


def test_webkit_pids_scoped_to_parent_tree():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "ONLY return WebKit processes inside that" in src
    assert "if tree is not None and pid not in tree:" in src


def test_icon_loop_skips_toolwindow_and_shell():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "skip_toolwindow" in src
    assert 'title.startswith("KrexionShell-")' in src
    assert "Honour caller poll_seconds" in src


def test_launcher_shell_before_icon_keeper():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    # v2.7.105d — early phone chrome + stop icon keeper when shell embeds
    assert "Early Krexion phone chrome" in src
    assert "stop_session_icon_keeper(str(session_id))" in src
    assert "session_lifetime=False" in src
    assert "is_mobile_shell_alive(session_id)" in src
    assert "wait_for_mobile_shell_embedded" in src


def test_shell_loop_does_not_kill_chrome_on_crash():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "chrome kept alive" in src
    assert "intentional or parent_dead" in src
    assert "SW_SHOWNA" in src
    assert "host_py = _host_script_path()" in src


def test_proxy_diag_mentions_dns_enotfound():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "DNS could not resolve this proxy hostname" in src
    assert "ENOTFOUND" in src


def test_version_is_2_7_102():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 103]
