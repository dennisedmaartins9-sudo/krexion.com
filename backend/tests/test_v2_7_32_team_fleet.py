"""v2.7.32 — Team Fleet Command Center (delegated bridge + sub-user license)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import bridge_module
import sync_module
import team_fleet_module


async def _async_iter(items):
    for item in items:
        yield item


def test_validate_license_resolves_sub_user_to_parent():
    db = MagicMock()
    db.licenses.find_one = AsyncMock(
        return_value={"license_key": "KRX-TEST", "email": "member@test.com", "status": "active"}
    )

    async def users_find_one(query, *args, **kwargs):
        if query.get("email") == "member@test.com":
            return None
        if query.get("id") == "parent-1":
            return {"id": "parent-1", "email": "owner@test.com", "name": "Owner"}
        return None

    db.users.find_one = AsyncMock(side_effect=users_find_one)
    db.sub_users.find_one = AsyncMock(
        return_value={
            "id": "sub-1",
            "email": "member@test.com",
            "parent_user_id": "parent-1",
        }
    )
    sync_module._db = db
    lic, user = asyncio.run(sync_module._validate_license("KRX-TEST"))
    assert user["id"] == "parent-1"
    assert user["is_fleet_worker"] is True
    assert user["fleet_worker_email"] == "member@test.com"
    assert user["sub_user_id"] == "sub-1"
    assert lic["license_key"] == "KRX-TEST"


def test_is_fleet_member_online_by_email():
    db = MagicMock()
    db.licenses.find = MagicMock(return_value=_async_iter([{"license_key": "KRX-M1"}]))
    now = datetime.now(timezone.utc).isoformat()
    db.sync_heartbeats.find_one = AsyncMock(
        return_value={
            "email": "member@test.com",
            "hostname": "PC-MEMBER",
            "ram_gb": 16,
            "last_seen": now,
        }
    )
    bridge_module._db = db
    bridge_module.ONLINE_WINDOW_SEC = 300
    status = asyncio.run(bridge_module.is_fleet_member_online("member@test.com", "parent-1"))
    assert status["online"] is True
    assert status["hostname"] == "PC-MEMBER"


def test_enqueue_bridge_job_sets_target_email():
    db = MagicMock()
    db.bridge_jobs.insert_one = AsyncMock()
    bridge_module._db = db
    bridge_module.ONLINE_WINDOW_SEC = 300

    with patch.object(
        bridge_module,
        "is_fleet_member_online",
        AsyncMock(return_value={"online": True, "email": "member@test.com"}),
    ):
        out = asyncio.run(
            bridge_module.enqueue_bridge_job(
                {"id": "parent-1", "email": "owner@test.com"},
                "real-user-traffic/jobs",
                {"method": "POST"},
                target_email="member@test.com",
                fleet_member_id="sub-1",
                fleet_delegated=True,
            )
        )
    assert out["status"] == "pending"
    doc = db.bridge_jobs.insert_one.call_args[0][0]
    assert doc["target_email"] == "member@test.com"
    assert doc["fleet_member_id"] == "sub-1"
    assert doc["fleet_delegated"] is True


def test_normalize_fleet_permissions_defaults():
    perms = team_fleet_module.normalize_fleet_permissions({"rut": False})
    assert perms["rut"] is False
    assert perms["links"] is True
    assert perms["profiles"] is True


def test_resolve_fleet_member_requires_allowed():
    db = MagicMock()
    db.sub_users.find_one = AsyncMock(
        return_value={
            "id": "sub-1",
            "email": "m@test.com",
            "fleet_control_allowed": False,
            "is_active": True,
        }
    )
    team_fleet_module._db = db
    with pytest.raises(HTTPException) as exc:
        asyncio.run(team_fleet_module.resolve_fleet_member("parent-1", "sub-1"))
    assert "not allowed" in str(exc.value.detail).lower()
