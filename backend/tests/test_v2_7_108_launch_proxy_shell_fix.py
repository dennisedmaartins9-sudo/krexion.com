"""v2.7.108 — Launch proxy fresh sessid + shell PID discover + soft frame fallback."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_launch_clears_raw_line_for_fresh_session():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def _ensure_profile_launch_proxy")
    end = src.index("\nasync def ", start + 10)
    block = src[start:end]
    # Provider / ProxyJet path still clears sticky create sessid.
    assert 'proxy_cfg.pop("raw_line"' in block
    assert "_fresh_rotating" in block
    assert 'proxy_cfg["username"] = ""' in block
    # v2.7.113 — manual rotating keeps host:port (does not wipe server).
    assert "_manual_rotating" in block


def test_refresh_proxy_clears_raw_line():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def refresh_profile_proxy")
    end = src.index("\n@router.", start + 10)
    block = src[start:end]
    assert 'proxy.pop("raw_line"' in block
    assert "_rotate_manual_proxy_session" in block


def test_title_pid_scan_uses_iswindow():
    src = (ROOT / "krexion_window_icon.py").read_text(encoding="utf-8")
    chunk = src.split("def find_pids_by_window_title_substrings")[1].split(
        "def find_chromium_pids_by_cmdline_substrings"
    )[0]
    assert "user32.IsWindow(hwnd)" in chunk
    assert "user32.IsWindowVisible(hwnd)" not in chunk


def test_shell_loop_unions_chromium_cmdline_pids():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "find_chromium_pids_by_cmdline_substrings" in src
    assert "--window-name=Krexion" in src


def test_launcher_strict_aborts_when_shell_not_embedded():
    """v2.7.126 — Strict ON must not soft-continue with plain Chromium/WebKit."""
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "profile_engine_window_exists" in src
    assert "plain Chromium/WebKit will not be shown as Krexion design." in src
    assert "strict_mobile_shell and require_embed" in src
    assert (
        'allow_restart=not bool(_launch_ui_meta.get("mobile_shell_embedded"))' in src
    )
    # Soft-continue wording only when Strict OFF
    assert "session kept open (Strict shell OFF)" in src
    assert "_USER_SESSION_PICKUP_TIMEOUT_SEC = 120.0" in src


def test_mirror_persists_last_proxy_check():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    chunk = src.split("async def _mirror_profile_session")[1].split(
        "async def ", 1
    )[0]
    assert '"last_proxy_check"' in chunk


def test_health_penalizes_unverified_create_exit_ip():
    from browser_profile_health import compute_profile_health

    h = compute_profile_health(
        {
            "status": "error",
            "proxy": {"enabled": True},
            "exit_ip": "1.2.3.4",
            "last_proxy_check": {},
            "cookie_count": 0,
            "fingerprint_hash": "",
        }
    )
    assert h["score"] <= 30
    assert any("not re-verified" in i for i in h.get("issues") or [])


def test_version_2_7_108():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.108")
