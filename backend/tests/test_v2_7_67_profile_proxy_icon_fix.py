"""v2.7.67 — Profile launch proxy auth hydrate + taskbar PID fallback."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_is_2_7_68_proxy_icon():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 67]


def test_hydrate_proxy_from_raw_line():
    from browser_profile_module import hydrate_proxy_credentials

    cfg = hydrate_proxy_credentials(
        {
            "server": "http://gw.dataimpulse.com:10000",
            "raw_line": "http://user123:secret456@gw.dataimpulse.com:10000",
        }
    )
    assert cfg["server"] == "http://gw.dataimpulse.com:10000"
    assert cfg["username"] == "user123"
    assert cfg["password"] == "secret456"


def test_hydrate_proxy_from_embedded_server_url():
    from browser_profile_module import hydrate_proxy_credentials

    cfg = hydrate_proxy_credentials(
        {"server": "http://abc:xyz@gw.dataimpulse.com:10000"}
    )
    assert cfg["username"] == "abc"
    assert cfg["password"] == "xyz"
    assert "@" not in cfg["server"]


def test_launcher_hydrates_before_proxy_arg():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "resolve_launch_proxy_cfg" in src
    assert "resolve_playwright_driver_pid" in src
    assert "cmdline_markers" in src


def test_icon_module_cmdline_pid_finder():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    assert "find_chromium_pids_by_cmdline_substrings" in src
    assert "resolve_playwright_driver_pid" in src
