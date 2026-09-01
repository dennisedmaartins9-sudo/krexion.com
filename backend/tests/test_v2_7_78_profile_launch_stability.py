"""v2.7.78 — Profile launch stability: proxy hydrate + auto-close grace."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_version_is_2_7_78():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() >= "2.7.78"


def test_hydrate_provider_gateway_password_fallback():
    from browser_profile_module import hydrate_proxy_credentials

    cfg = hydrate_proxy_credentials(
        {
            "provider_id": "pp_test",
            "server": "http://gw.dataimpulse.com:10000",
            "username": "user__cr.us;sessid.abc123",
        }
    )
    assert not str(cfg.get("password") or "").strip()


def test_hydrate_for_launch_uses_gateway_fallback():
    import asyncio
    from browser_profile_module import hydrate_proxy_credentials_for_launch

    async def _run():
        with patch(
            "proxy_provider_module.get_proxy_from_provider",
            new=AsyncMock(return_value={"proxy": "http://gw.dataimpulse.com:10000"}),
        ), patch(
            "proxy_provider_module.get_provider_gateway_credentials",
            new=AsyncMock(
                return_value={
                    "username": "baseuser",
                    "password": "secretpass",
                    "gateway_host": "gw.dataimpulse.com",
                    "gateway_port": "10000",
                }
            ),
        ):
            return await hydrate_proxy_credentials_for_launch(
                "u1",
                None,
                {
                    "provider_id": "pp1",
                    "server": "http://gw.dataimpulse.com:10000",
                    "username": "user__cr.us;sessid.abc",
                },
            )

    out = asyncio.run(_run())
    assert out["password"] == "secretpass"


def test_profile_user_closed_ui_grace_ignores_missing_window():
    from browser_profile_launcher import (
        _PROFILE_UI_WATCH_GRACE_SEC,
        _RUNNING_SESSIONS,
        _profile_user_closed_ui,
    )

    sid = "sess_grace"
    page = MagicMock(is_closed=lambda: False)
    ctx = MagicMock(pages=[page])
    browser = MagicMock(is_connected=lambda: True)
    _RUNNING_SESSIONS[sid] = {
        "driver_pid": 4242,
        "mobile_shell": True,
        "webkit": False,
        "ui_watch_started_mono": time.monotonic(),
    }

    with patch("browser_profile_launcher.sys.platform", "win32"), patch(
        "krexion_mobile_browser_shell.is_mobile_shell_alive", return_value=False
    ):
        assert _profile_user_closed_ui(sid, ctx, browser, {page}) is False

    _RUNNING_SESSIONS[sid]["ui_watch_started_mono"] = (
        time.monotonic() - _PROFILE_UI_WATCH_GRACE_SEC - 5.0
    )
    with patch("browser_profile_launcher.sys.platform", "win32"), patch(
        "krexion_mobile_browser_shell.is_mobile_shell_alive", return_value=False
    ):
        assert _profile_user_closed_ui(sid, ctx, browser, {page}) is True

    _RUNNING_SESSIONS.pop(sid, None)


def test_launcher_sets_ui_watch_and_shell_gate():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "ui_watch_started_mono" in src
    assert "is_mobile_shell_alive(session_id)" in src
    assert "_PROFILE_UI_WATCH_GRACE_SEC" in src
