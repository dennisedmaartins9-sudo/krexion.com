"""v2.7.101 — Manual rotating gateway launch never hard-blocks on duplicate IP."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_is_rotating_gateway_manual_dataimpulse():
    from browser_profile_module import _is_rotating_gateway_proxy

    assert _is_rotating_gateway_proxy(
        {
            "enabled": True,
            "server": "http://gw.dataimpulse.com:10000",
            "username": "6450a120b611fd3d585d__cr.us;state.newjersey",
            "password": "secret",
        }
    )


def test_defer_launch_proxy_probe_for_manual_rotating():
    from browser_profile_module import _defer_launch_proxy_probe

    assert _defer_launch_proxy_probe(
        {
            "enabled": True,
            "server": "http://gw.dataimpulse.com:823",
            "username": "user__cr.us;state.california",
            "password": "x",
        }
    )
    assert not _defer_launch_proxy_probe(
        {"enabled": True, "server": "http://203.0.113.10:8080", "password": "x"}
    )


def test_rotate_manual_proxy_session_injects_sessid():
    from browser_profile_module import _rotate_manual_proxy_session

    cfg = {
        "server": "http://gw.dataimpulse.com:10000",
        "username": "6450a120b611fd3d585d__cr.us;state.newjersey",
        "password": "secret123",
    }
    out = _rotate_manual_proxy_session(cfg)
    user = out.get("username") or ""
    assert user != cfg["username"]
    assert "sessid" in user.lower()
    assert out.get("raw_line")


@pytest.mark.asyncio
async def test_assert_unique_ip_team_message_not_batch():
    from browser_profile_module import _assert_unique_team_profile_ip
    from fastapi import HTTPException

    used = {"69.119.247.179"}
    with pytest.raises(HTTPException) as exc:
        await _assert_unique_team_profile_ip("u1", "69.119.247.179", used)
    assert exc.value.status_code == 409
    assert "team IP isolation" in str(exc.value.detail)
    assert "in this batch" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_assert_unique_ip_batch_message():
    from browser_profile_module import _assert_unique_team_profile_ip
    from fastapi import HTTPException

    used: set = set()
    batch = {"69.119.247.179"}
    with pytest.raises(HTTPException) as exc:
        await _assert_unique_team_profile_ip(
            "u1", "69.119.247.179", used, batch_assigned=batch,
        )
    assert "in this batch" in str(exc.value.detail)


def test_version_is_2_7_101():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.101"
