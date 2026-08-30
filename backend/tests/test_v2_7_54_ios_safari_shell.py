"""v2.7.54 — iOS profile Safari shell (hide Playwright [WebKit] dev chrome)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault(
    "playwright.async_api",
    MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    ),
)
sys.modules.setdefault("playwright.sync_api", MagicMock())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_version_is_2_7_54():
    assert _read("VERSION").strip() == "2.7.65"


def test_ios_safari_shell_module_exports():
    import krexion_ios_safari_shell as shell

    assert hasattr(shell, "apply_ios_safari_shell_to_pids")
    assert shell._SAFARI_DISPLAY == "Safari"
    assert shell._phone_window_size(393, 852)[0] >= 393
    assert shell._phone_window_size(393, 852)[1] >= 852


def test_profile_launcher_wires_ios_safari_shell():
    src = _read("browser_profile_launcher.py")
    assert "apply_ios_safari_shell_to_pids" in src
    assert 'profile_os or "").lower() in' in src or "profile_os" in src
    assert "webkit" in src


def test_frontend_does_not_expose_webkit_to_users():
    fe = (
        Path(__file__).resolve().parent.parent.parent
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    ).read_text(encoding="utf-8")
    assert "WebKit" not in fe
    assert "Safari" in fe
    assert "Chromium" in fe


def test_apply_ios_safari_shell_starts_thread_on_windows():
    import krexion_ios_safari_shell as shell

    with patch.object(shell, "_IS_WINDOWS", True):
        with patch.object(shell.threading, "Thread") as mock_thread:
            inst = MagicMock()
            mock_thread.return_value = inst
            shell.apply_ios_safari_shell_to_pids([1234], parent_pid=1234)
            mock_thread.assert_called_once()
            inst.start.assert_called_once()


def test_is_webkit_browser_hwnd_detects_title():
    import krexion_ios_safari_shell as shell

    with patch.object(shell, "_window_title", return_value="[WebKit]"):
        with patch.object(shell, "_class_name", return_value="Foo"):
            assert shell._is_webkit_browser_hwnd(1) is True
    with patch.object(shell, "_window_title", return_value="Safari"):
        with patch.object(shell, "_class_name", return_value="Foo"):
            assert shell._is_webkit_browser_hwnd(1) is True
