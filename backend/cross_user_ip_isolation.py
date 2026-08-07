"""Admin-configured cross-user IP isolation groups.

When users A, B, C are in the same enabled group **and** each has
Admin › Users › **DB VPS** (`vps_ip_db_enabled`) ON, RUT duplicate-IP
checks merge click + burnt-IP history across those VPS-ON members —
none may reuse an exit IP another VPS-ON teammate already used.

DB VPS OFF → user keeps only their own IP history (no peer merge),
even if they sit in an isolation group.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

COLLECTION = "cross_user_ip_groups"

_GROUP_CACHE: Dict[str, Any] = {"at": 0.0, "user_to_peers": {}}
_GROUP_CACHE_TTL = 60.0


def invalidate_group_cache() -> None:
    _GROUP_CACHE["user_to_peers"] = {}
    _GROUP_CACHE["at"] = 0.0


async def _load_user_to_peers(db) -> Dict[str, Set[str]]:
    now = time.time()
    cached = _GROUP_CACHE.get("user_to_peers") or {}
    if cached and (now - float(_GROUP_CACHE.get("at") or 0)) < _GROUP_CACHE_TTL:
        return cached

    mapping: Dict[str, Set[str]] = {}
    async for doc in db[COLLECTION].find({"enabled": True}, {"user_ids": 1, "_id": 0}):
        uids = [str(u).strip() for u in (doc.get("user_ids") or []) if u]
        if len(uids) < 2:
            continue
        uid_set = set(uids)
        for uid in uids:
            mapping.setdefault(uid, set()).update(uid_set - {uid})

    _GROUP_CACHE["user_to_peers"] = mapping
    _GROUP_CACHE["at"] = now
    return mapping


async def get_isolation_peer_user_ids(db, user_id: str) -> List[str]:
    """Other main-user IDs in the same enabled isolation group (raw)."""
    uid = (user_id or "").strip()
    if not uid:
        return []
    mapping = await _load_user_to_peers(db)
    return sorted(mapping.get(uid, set()))


async def get_isolation_group_member_ids(db, user_id: str) -> List[str]:
    """All main-user IDs in the same group (including `user_id`)."""
    uid = (user_id or "").strip()
    if not uid:
        return []
    peers = await get_isolation_peer_user_ids(db, uid)
    if not peers:
        return [uid]
    return sorted(set([uid] + peers))


async def _user_vps_ip_db_enabled(db, user_id: str) -> bool:
    uid = (user_id or "").strip()
    if not uid:
        return False
    doc = await db.users.find_one({"id": uid}, {"vps_ip_db_enabled": 1, "_id": 0})
    return bool(doc and doc.get("vps_ip_db_enabled"))


async def get_vps_ledger_peer_user_ids(db, user_id: str) -> List[str]:
    """Isolation peers who also have Admin **DB VPS** ON.

    Returns [] when the caller does not have DB VPS enabled — they only
    use their own IP history.
    """
    uid = (user_id or "").strip()
    if not uid:
        return []
    if not await _user_vps_ip_db_enabled(db, uid):
        return []
    peers = await get_isolation_peer_user_ids(db, uid)
    if not peers:
        return []
    enabled: Set[str] = set()
    async for doc in db.users.find(
        {"id": {"$in": peers}, "vps_ip_db_enabled": True},
        {"id": 1, "_id": 0},
    ):
        pid = doc.get("id")
        if pid:
            enabled.add(str(pid))
    return sorted(enabled)


async def get_vps_ledger_member_ids(db, user_id: str) -> List[str]:
    """Self + VPS-ON isolation peers (for tagging ``rut_burnt_ips``).

    If self has DB VPS OFF, only ``[self]`` is returned so burnt rows
    stay private to that user.
    """
    uid = (user_id or "").strip()
    if not uid:
        return []
    if not await _user_vps_ip_db_enabled(db, uid):
        return [uid]
    peers = await get_vps_ledger_peer_user_ids(db, uid)
    return sorted(set([uid] + peers))


async def list_groups(db) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    async for doc in db[COLLECTION].find({}, {"_id": 0}).sort("name", 1):
        groups.append(doc)
    return groups


async def _remove_users_from_other_groups(db, user_ids: List[str], except_group_id: Optional[str] = None) -> None:
    if not user_ids:
        return
    q: Dict[str, Any] = {"user_ids": {"$in": user_ids}}
    if except_group_id:
        q["id"] = {"$ne": except_group_id}
    async for doc in db[COLLECTION].find(q, {"id": 1, "user_ids": 1, "_id": 0}):
        new_uids = [u for u in (doc.get("user_ids") or []) if u not in user_ids]
        await db[COLLECTION].update_one(
            {"id": doc["id"]},
            {"$set": {"user_ids": new_uids, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )


async def create_group(db, *, name: str, user_ids: List[str], enabled: bool = True) -> Dict[str, Any]:
    clean_ids = sorted({str(u).strip() for u in user_ids if str(u).strip()})
    if len(clean_ids) < 2:
        raise ValueError("Select at least 2 users for an isolation group")
    nm = (name or "").strip() or "Isolation Group"
    now = datetime.now(timezone.utc).isoformat()
    await _remove_users_from_other_groups(db, clean_ids)
    doc = {
        "id": str(uuid.uuid4()),
        "name": nm[:120],
        "user_ids": clean_ids,
        "enabled": bool(enabled),
        "created_at": now,
        "updated_at": now,
    }
    await db[COLLECTION].insert_one(doc)
    invalidate_group_cache()
    doc.pop("_id", None)
    return doc


async def update_group(
    db,
    group_id: str,
    *,
    name: Optional[str] = None,
    user_ids: Optional[List[str]] = None,
    enabled: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    gid = (group_id or "").strip()
    if not gid:
        return None
    existing = await db[COLLECTION].find_one({"id": gid}, {"_id": 0})
    if not existing:
        return None

    patch: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if name is not None:
        patch["name"] = (name or "").strip()[:120] or existing.get("name") or "Isolation Group"
    if user_ids is not None:
        clean_ids = sorted({str(u).strip() for u in user_ids if str(u).strip()})
        if len(clean_ids) < 2:
            raise ValueError("Select at least 2 users for an isolation group")
        await _remove_users_from_other_groups(db, clean_ids, except_group_id=gid)
        patch["user_ids"] = clean_ids
    if enabled is not None:
        patch["enabled"] = bool(enabled)

    await db[COLLECTION].update_one({"id": gid}, {"$set": patch})
    invalidate_group_cache()
    return await db[COLLECTION].find_one({"id": gid}, {"_id": 0})


async def delete_group(db, group_id: str) -> bool:
    gid = (group_id or "").strip()
    if not gid:
        return False
    res = await db[COLLECTION].delete_one({"id": gid})
    if res.deleted_count:
        invalidate_group_cache()
        return True
    return False
