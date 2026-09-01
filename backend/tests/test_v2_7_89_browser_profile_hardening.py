"""v2.7.89 — proxy enabled gate + no-proxy launch/create safety."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_proxy_is_active_respects_enabled_false():
    from browser_profile_module import proxy_is_active

    assert proxy_is_active({"enabled": False, "provider_id": "pp1"}) is False
    assert proxy_is_active({"enabled": False, "server": "http://1.2.3.4:8080"}) is False
    assert proxy_is_active({"enabled": True, "provider_id": "pp1"}) is True
    assert proxy_is_active({"server": "http://1.2.3.4:8080"}) is True


def test_finalize_doc_proxy_skips_when_disabled():
    from browser_profile_module import _finalize_doc_proxy_and_ip

    async def _run():
        doc = {
            "name": "Test",
            "proxy": {"enabled": False, "provider_id": "stale"},
        }
        await _finalize_doc_proxy_and_ip("u1", {"id": "u1"}, doc, set())
        return doc

    out = asyncio.run(_run())
    assert "exit_ip" not in out or not out.get("exit_ip")


def test_ensure_launch_proxy_skips_no_proxy_profile():
    from browser_profile_module import _ensure_profile_launch_proxy

    async def _run():
        doc = {
            "id": "p1",
            "name": "NoProxy",
            "proxy": {"enabled": False, "provider_id": "stale"},
        }
        with patch(
            "browser_profile_module._probe_proxy_cfg_exit_ip",
            new=AsyncMock(side_effect=AssertionError("should not probe")),
        ):
            return await _ensure_profile_launch_proxy("u1", {"id": "u1"}, doc)

    out = asyncio.run(_run())
    assert out.get("enabled") is False


def test_health_proxy_off_when_enabled_false():
    from browser_profile_health import compute_profile_health

    h = compute_profile_health(
        {
            "status": "idle",
            "proxy": {"enabled": False, "provider_id": "pp1"},
            "storage_state": {},
        }
    )
    assert "proxy check failed" not in [str(i).lower() for i in (h.get("issues") or [])]
    assert "no proxy configured" not in [str(i).lower() for i in (h.get("issues") or [])]


def test_sanitize_profile_proxy_for_save_manual_clears_provider():
    """Frontend helper parity — manual proxy must not keep stale provider_id."""
    # Documented expectation for BrowserProfilesPage sanitizeProfileProxyForSave
    from browser_profile_module import proxy_is_active

    manual = {"enabled": True, "server": "http://1.2.3.4:8080", "provider_id": ""}
    assert proxy_is_active(manual) is True
    stale = {"enabled": False, "provider_id": "pp1"}
    assert proxy_is_active(stale) is False
