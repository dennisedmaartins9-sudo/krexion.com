"""
Krexion — Team Fleet Command Center (v2.7.32)
==============================================

Team leader controls member native PCs from one cloud dashboard.
VPS only orchestrates (queue, heartbeat, auth, audit) — heavy work
runs on each member's own machine via the existing bridge/sync_client.

Enable/disable: users.team_fleet_enabled (owner toggle in Settings).
Per-member: sub_users.fleet_control_allowed + fleet_permissions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

fleet_router = APIRouter(prefix="/api/team-fleet", tags=["team-fleet"])

_db: Any = None
_get_current_user: Any = None
_is_member_online_fn: Any = None
_enqueue_bridge_job_fn: Any = None
ONLINE_WINDOW_SEC = 300

FLEET_PERMISSIONS_DEFAULT: Dict[str, bool] = {
    "rut": True,
    "links": True,
    "profiles": True,
}

FLEET_PERMISSION_LABELS = {
    "rut": "Real User Traffic",
    "links": "Links",
    "profiles": "Browser Profiles",
}


def _bind(
    *,
    main_db,
    get_current_user,
    is_member_online=None,
    enqueue_bridge_job=None,
    online_window_sec: int = 300,
) -> None:
    global _db, _get_current_user, _is_member_online_fn, _enqueue_bridge_job_fn, ONLINE_WINDOW_SEC
    _db = main_db
    _get_current_user = get_current_user
    _is_member_online_fn = is_member_online
    _enqueue_bridge_job_fn = enqueue_bridge_job
    ONLINE_WINDOW_SEC = online_window_sec


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Shared helpers (imported by server.py / bridge_module) ───────────


def normalize_fleet_permissions(perms: Optional[dict]) -> Dict[str, bool]:
    src = perms or {}
    return {k: bool(src.get(k, FLEET_PERMISSIONS_DEFAULT.get(k, False))) for k in FLEET_PERMISSIONS_DEFAULT}


async def is_fleet_enabled_for_user(user_id: str) -> bool:
    if _db is None:
        return False
    doc = await _db.users.find_one({"id": user_id}, {"team_fleet_enabled": 1, "_id": 0})
    return bool((doc or {}).get("team_fleet_enabled"))


async def assert_fleet_leader(user: dict) -> str:
    """Main account only; returns parent user_id."""
    if user.get("is_sub_user"):
        raise HTTPException(status_code=403, detail="Sub-users cannot access Team Fleet")
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return uid


async def resolve_fleet_member(parent_user_id: str, member_id: str) -> dict:
    if _db is None:
        raise HTTPException(status_code=503, detail="Fleet module not initialised")
    member = await _db.sub_users.find_one(
        {"id": member_id, "parent_user_id": parent_user_id},
        {"_id": 0, "password_hash": 0},
    )
    if not member:
        raise HTTPException(status_code=404, detail="Fleet member not found")
    if not member.get("is_active", True):
        raise HTTPException(status_code=403, detail="Fleet member is deactivated")
    if not member.get("fleet_control_allowed", False):
        raise HTTPException(status_code=403, detail="Fleet control is not allowed for this member")
    member["fleet_permissions"] = normalize_fleet_permissions(member.get("fleet_permissions"))
    return member


async def assert_member_permission(member: dict, permission: str) -> None:
    perms = normalize_fleet_permissions(member.get("fleet_permissions"))
    if not perms.get(permission):
        raise HTTPException(
            status_code=403,
            detail=f"Member does not have fleet permission: {permission}",
        )


async def is_fleet_member_online(member_email: str, parent_user_id: str) -> dict:
    """Online status for a sub-user's paired native PC."""
    if not member_email:
        return {"online": False, "reason": "no_email"}
    if _is_member_online_fn is not None:
        try:
            return await _is_member_online_fn(member_email, parent_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[fleet] is_member_online callback failed: {exc}")

    if _db is None:
        return {"online": False, "reason": "no_db"}

    license_keys: list[str] = []
    try:
        async for lic in _db.licenses.find({"email": member_email}, {"license_key": 1, "_id": 0}):
            lk = (lic or {}).get("license_key")
            if lk:
                license_keys.append(lk)
    except Exception:  # noqa: BLE001
        pass

    or_clauses: list[dict] = [{"email": member_email}]
    if license_keys:
        or_clauses.append({"license_key": {"$in": license_keys}})

    hb = await _db.sync_heartbeats.find_one(
        {"$or": or_clauses},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    if not hb or not hb.get("last_seen"):
        return {"online": False, "reason": "no_heartbeat_ever", "email": member_email}

    try:
        last = datetime.fromisoformat(str(hb["last_seen"]).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return {"online": False, "reason": "bad_heartbeat_ts", "email": member_email}

    age = (_now() - last).total_seconds()
    online = age <= ONLINE_WINDOW_SEC
    return {
        "online": online,
        "email": member_email,
        "hostname": hb.get("hostname") or "",
        "ram_gb": hb.get("ram_gb"),
        "cpu_cores": hb.get("cpu_cores"),
        "platform": hb.get("platform") or "",
        "version": hb.get("version") or "",
        "last_seen": hb.get("last_seen"),
        "last_seen_sec_ago": int(age),
        "reason": None if online else "stale_heartbeat",
        "sub_user_id": hb.get("sub_user_id"),
    }


async def log_fleet_audit(
    *,
    parent_user_id: str,
    leader_email: str,
    member_id: str,
    member_email: str,
    action: str,
    feature: str = "",
    detail: Optional[dict] = None,
    job_id: str = "",
) -> None:
    if _db is None:
        return
    doc = {
        "id": uuid.uuid4().hex,
        "parent_user_id": parent_user_id,
        "leader_email": leader_email,
        "member_id": member_id,
        "member_email": member_email,
        "action": action,
        "feature": feature,
        "detail": detail or {},
        "job_id": job_id,
        "created_at": _now_iso(),
    }
    try:
        await _db.fleet_audit_log.insert_one(doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[fleet] audit log failed: {exc}")


async def register_fleet_job_route(
    *,
    job_id: str,
    parent_user_id: str,
    member_id: str,
    member_email: str,
    feature: str = "rut",
) -> None:
    if _db is None or not job_id:
        return
    try:
        await _db.fleet_job_routes.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "parent_user_id": parent_user_id,
                    "member_id": member_id,
                    "member_email": member_email,
                    "feature": feature,
                    "updated_at": _now_iso(),
                },
                "$setOnInsert": {"created_at": _now_iso()},
            },
            upsert=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[fleet] register job route failed: {exc}")


async def lookup_fleet_job_route(job_id: str) -> Optional[dict]:
    if _db is None or not job_id:
        return None
    try:
        return await _db.fleet_job_routes.find_one({"job_id": job_id}, {"_id": 0})
    except Exception:  # noqa: BLE001
        return None


async def resolve_fleet_context_from_request(
    user: dict,
    fleet_member_id: Optional[str],
) -> Optional[dict]:
    """Validate fleet delegation; return member doc + online status or None."""
    if not fleet_member_id:
        return None
    parent_id = await assert_fleet_leader(user)
    if not await is_fleet_enabled_for_user(parent_id):
        raise HTTPException(status_code=403, detail="Team Fleet Control is disabled")
    member = await resolve_fleet_member(parent_id, fleet_member_id)
    online = await is_fleet_member_online(member["email"], parent_id)
    return {"member": member, "online": online, "parent_user_id": parent_id}


async def get_member_last_rut_job(parent_user_id: str, member_id: str) -> Optional[dict]:
    if _db is None:
        return None
    try:
        route = await _db.fleet_job_routes.find_one(
            {"parent_user_id": parent_user_id, "member_id": member_id, "feature": "rut"},
            {"_id": 0},
            sort=[("updated_at", -1)],
        )
        return route
    except Exception:  # noqa: BLE001
        return None


# ── API models ───────────────────────────────────────────────────────


class FleetSettingsUpdate(BaseModel):
    enabled: bool


class FleetMemberPermissionsUpdate(BaseModel):
    fleet_control_allowed: Optional[bool] = None
    fleet_permissions: Optional[Dict[str, bool]] = None


class FleetDelegateBridgeBody(BaseModel):
    member_id: str
    feature: str = Field(..., min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)
    permission: str = "rut"
    wait_for_result: bool = False
    wait_timeout: int = Field(default=25, ge=5, le=120)


# ── API endpoints ────────────────────────────────────────────────────


async def _fleet_user(request: Request) -> dict:
    if _get_current_user is None:
        raise HTTPException(status_code=500, detail="Fleet module not initialised")
    return await _get_current_user(request)


@fleet_router.get("/settings")
async def fleet_get_settings(request: Request):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    enabled = await is_fleet_enabled_for_user(parent_id)
    count = await _db.sub_users.count_documents({"parent_user_id": parent_id})
    allowed = await _db.sub_users.count_documents(
        {"parent_user_id": parent_id, "fleet_control_allowed": True}
    )
    return {
        "enabled": enabled,
        "member_count": count,
        "fleet_allowed_count": allowed,
    }


@fleet_router.put("/settings")
async def fleet_update_settings(body: FleetSettingsUpdate, request: Request):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    await _db.users.update_one(
        {"id": parent_id},
        {"$set": {"team_fleet_enabled": bool(body.enabled), "team_fleet_updated_at": _now_iso()}},
    )
    await log_fleet_audit(
        parent_user_id=parent_id,
        leader_email=user.get("email") or "",
        member_id="",
        member_email="",
        action="fleet_toggle",
        detail={"enabled": bool(body.enabled)},
    )
    return {"enabled": bool(body.enabled)}


@fleet_router.get("/members")
async def fleet_list_members(request: Request):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    if not await is_fleet_enabled_for_user(parent_id):
        return {"enabled": False, "members": []}

    members = await _db.sub_users.find(
        {"parent_user_id": parent_id},
        {"_id": 0, "password_hash": 0},
    ).to_list(200)

    out: List[dict] = []
    for m in members:
        email = m.get("email") or ""
        online = await is_fleet_member_online(email, parent_id)
        last_job = await get_member_last_rut_job(parent_id, m.get("id") or "")
        out.append({
            "id": m.get("id"),
            "email": email,
            "name": m.get("name") or "",
            "is_active": m.get("is_active", True),
            "fleet_control_allowed": bool(m.get("fleet_control_allowed", False)),
            "fleet_permissions": normalize_fleet_permissions(m.get("fleet_permissions")),
            "last_active": m.get("last_active"),
            "created_at": m.get("created_at"),
            "online": online.get("online", False),
            "local_status": online,
            "last_rut_job_id": (last_job or {}).get("job_id"),
        })

    return {"enabled": True, "members": out, "total": len(out)}


@fleet_router.put("/members/{member_id}")
async def fleet_update_member(member_id: str, body: FleetMemberPermissionsUpdate, request: Request):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    member = await _db.sub_users.find_one(
        {"id": member_id, "parent_user_id": parent_id},
        {"_id": 0},
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    update: dict = {}
    if body.fleet_control_allowed is not None:
        update["fleet_control_allowed"] = bool(body.fleet_control_allowed)
    if body.fleet_permissions is not None:
        update["fleet_permissions"] = normalize_fleet_permissions(body.fleet_permissions)

    if update:
        await _db.sub_users.update_one({"id": member_id}, {"$set": update})

    updated = await _db.sub_users.find_one(
        {"id": member_id},
        {"_id": 0, "password_hash": 0},
    )
    await log_fleet_audit(
        parent_user_id=parent_id,
        leader_email=user.get("email") or "",
        member_id=member_id,
        member_email=updated.get("email") or "",
        action="member_permissions_update",
        detail=update,
    )
    return {
        "member": {
            **updated,
            "fleet_permissions": normalize_fleet_permissions(updated.get("fleet_permissions")),
        }
    }


@fleet_router.post("/delegate/bridge")
async def fleet_delegate_bridge(body: FleetDelegateBridgeBody, request: Request):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    if not await is_fleet_enabled_for_user(parent_id):
        raise HTTPException(status_code=403, detail="Team Fleet Control is disabled")
    if _enqueue_bridge_job_fn is None:
        raise HTTPException(status_code=503, detail="Bridge not available")

    member = await resolve_fleet_member(parent_id, body.member_id)
    await assert_member_permission(member, body.permission)

    online = await is_fleet_member_online(member["email"], parent_id)
    if not online.get("online"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "member_pc_offline",
                "message": (
                    f"{member.get('name') or member['email']}'s PC is offline. "
                    "Ask them to open Krexion on their computer."
                ),
                "local_status": online,
            },
        )

    bridge_user = {"id": parent_id, "email": user.get("email")}
    resp = await _enqueue_bridge_job_fn(
        bridge_user,
        body.feature,
        body.payload,
        wait_for_result=body.wait_for_result,
        wait_timeout=body.wait_timeout,
        target_email=member["email"],
        requested_by=user.get("email"),
        fleet_member_id=member["id"],
        fleet_delegated=True,
    )

    await log_fleet_audit(
        parent_user_id=parent_id,
        leader_email=user.get("email") or "",
        member_id=member["id"],
        member_email=member["email"],
        action="delegate_bridge",
        feature=body.feature,
        detail={"wait_for_result": body.wait_for_result},
        job_id=str(resp.get("job_id") or ""),
    )
    return resp


@fleet_router.get("/audit")
async def fleet_audit_log(request: Request, limit: int = 50):
    user = await _fleet_user(request)
    parent_id = await assert_fleet_leader(user)
    limit = max(1, min(limit, 200))
    cursor = _db.fleet_audit_log.find(
        {"parent_user_id": parent_id},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    items = await cursor.to_list(limit)
    return {"items": items, "total": len(items)}
