"""Admin-configured cross-user IP isolation groups.

When users A, B, C are in the same enabled group **and** each has
Admin › Users › **DB VPS** (`vps_ip_db_enabled`) ON, RUT duplicate-IP
checks merge click + burnt-IP history across those VPS-ON members —
none may reuse an exit IP another VPS-ON teammate already used.

DB VPS OFF → user keeps only their own IP history (no peer merge),
even if they sit in an isolation group.

``vps_ip_claims`` — atomic same-second IP reservation (unique on
ledger_key+ip) so two teammates cannot both pass the tracker before
either finishes the slow geo/VPN path and writes a full click row.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

COLLECTION = "cross_user_ip_groups"
CLAIMS_COLLECTION = "vps_ip_claims"
TEAM_OFFER_CLAIMS_COLLECTION = "team_offer_ip_claims"
# Pending claim TTL — was 240s which locked an IP for the WHOLE team
# when one visit hung. 90s is enough for geo/VPN + first navigation.
PENDING_CLAIM_SECONDS = 90

_PLACEHOLDER_IPS = frozenset(
    {"", "unknown", "Unknown", "no-ipv4-detected", "no-ip-detected"}
)

_GROUP_CACHE: Dict[str, Any] = {"at": 0.0, "user_to_peers": {}}
_GROUP_CACHE_TTL = 60.0
_SCOPE_CACHE: Dict[str, Any] = {}
_SCOPE_CACHE_TTL = 30.0


def canonicalize_ip(raw: Any) -> Optional[str]:
    """Return one database-safe IP spelling, or None for invalid input."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or value.lower() in {str(v).lower() for v in _PLACEHOLDER_IPS}:
        return None
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return str(parsed.ipv4_mapped)
    return parsed.compressed


def canonical_primary_ip(*candidates: Any) -> Optional[str]:
    """Choose exactly one authoritative IP; never create partial multi-IP claims."""
    for candidate in candidates:
        canonical = canonicalize_ip(candidate)
        if canonical:
            return canonical
    return None


def canonical_offer_identity(url: str) -> tuple[str, str]:
    """Normalize an underlying offer URL and return (URL, stable SHA-256 key).

    Business query parameters are preserved. Only per-click/internal parameters
    are removed, so two tracker records pointing at the same offer share scope.
    """
    raw = (url or "").strip()
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("offer URL must be absolute http(s)")
        host_raw = parsed.hostname
        try:
            host = str(ipaddress.ip_address(host_raw))
        except ValueError:
            host = host_raw.encode("idna").decode("ascii").lower()
        port = parsed.port
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        else:
            netloc = f"[{host}]" if ":" in host else host
        if parsed.username or parsed.password:
            raise ValueError("offer URL credentials are not supported")
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in {"clickid", "click_id"} and not key.lower().startswith("_kx_")
        ]
        query.sort(key=lambda item: (item[0], item[1]))
        normalized = urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid offer URL") from exc
    return normalized, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def resolve_isolation_scope(db, user_id: str) -> Dict[str, Any]:
    """Resolve membership live for the critical claim path.

    One user should belong to at most one enabled group. Admin writes enforce a
    conflict check; if legacy corruption exists, claims fail closed.

    Cached ~30s so 10–100 teammates hitting the tracker do not each
    re-query groups+users on every click / RUT visit.
    """
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    now = time.time()
    hit = _SCOPE_CACHE.get(uid)
    if hit and (now - float(hit.get("at") or 0)) < _SCOPE_CACHE_TTL:
        return dict(hit["scope"])
    def _store(scope: Dict[str, Any]) -> Dict[str, Any]:
        _SCOPE_CACHE[uid] = {"at": now, "scope": scope}
        return dict(scope)

    if not await _user_vps_ip_db_enabled(db, uid):
        return _store({"scope_key": f"user:{uid}", "group_id": None, "member_ids": [uid], "shared": False})
    groups = await db[COLLECTION].find(
        {"enabled": True, "user_ids": uid}, {"id": 1, "user_ids": 1, "_id": 0}
    ).to_list(2)
    if len(groups) > 1:
        raise RuntimeError("user belongs to multiple enabled isolation groups")
    if not groups:
        return _store({"scope_key": f"user:{uid}", "group_id": None, "member_ids": [uid], "shared": False})
    group = groups[0]
    gid = str(group.get("id") or "").strip()
    if not gid:
        raise RuntimeError("enabled isolation group has no stable id")
    candidates = sorted({str(v).strip() for v in group.get("user_ids") or [] if str(v).strip()})
    eligible: Set[str] = set()
    async for doc in db.users.find(
        {"id": {"$in": candidates}, "vps_ip_db_enabled": True}, {"id": 1, "_id": 0}
    ):
        if doc.get("id"):
            eligible.add(str(doc["id"]))
    if uid not in eligible or len(eligible) < 2:
        return _store({"scope_key": f"user:{uid}", "group_id": None, "member_ids": [uid], "shared": False})
    return _store({
        "scope_key": f"group:{gid}",
        "group_id": gid,
        "member_ids": sorted(eligible),
        "shared": True,
    })


def team_offer_claim_required(scope: Dict[str, Any], duplicate_opt_in: bool) -> bool:
    """Shared DB-VPS isolation is mandatory; solo users retain their opt-out."""
    return bool(scope.get("shared")) or bool(duplicate_opt_in)


async def ensure_team_offer_claim_indexes(db) -> None:
    await db[TEAM_OFFER_CLAIMS_COLLECTION].create_index(
        [("scope_key", 1), ("offer_key", 1), ("ip", 1)],
        unique=True,
        name="uniq_scope_offer_ip",
    )
    await db[TEAM_OFFER_CLAIMS_COLLECTION].create_index(
        [("expires_at", 1)], expireAfterSeconds=0, name="pending_expiry"
    )
    await db[TEAM_OFFER_CLAIMS_COLLECTION].create_index(
        [("visit_token", 1), ("scope_key", 1)], name="visit_scope_lookup"
    )
    # This collection already has the production index named ``id_1`` from
    # server startup. Let Mongo/PyMongo derive that same name so deployment is
    # idempotent; requesting a second custom name for the identical key raises
    # IndexOptionsConflict and prevents the backend from starting.
    await db[COLLECTION].create_index("id", unique=True)
    await db[COLLECTION].create_index([("enabled", 1), ("user_ids", 1)], name="enabled_group_members")
    try:
        await db.rut_burnt_offer_ips.create_index(
            [("offer_scope_key", 1), ("user_id", 1), ("ip", 1)],
            name="burnt_offer_user_ip",
        )
    except Exception:
        pass


async def _team_ip_already_used(
    db,
    scope: Dict[str, Any],
    offer_key: str,
    canonical_ip: str,
    get_user_db: Optional[Callable[[str], Any]] = None,
) -> bool:
    """Strict history check for THIS ip+offer across the whole team.

    Does not load every teammate IP. Looks up one IP in burnt + each
    member clicks DB (parallel, capped). Timeout on a shared team fails
    closed so a slow Mongo never accidentally allows a duplicate.
    """
    members = [str(m).strip() for m in (scope.get("member_ids") or []) if str(m).strip()]
    if not members or not canonical_ip or not offer_key:
        return False
    burnt = getattr(db, "rut_burnt_offer_ips", None)
    if burnt is None:
        try:
            burnt = db["rut_burnt_offer_ips"]
        except Exception:
            burnt = None
    if burnt is not None:
        try:
            hit = await burnt.find_one(
                {
                    "offer_scope_key": offer_key,
                    "ip": canonical_ip,
                    "user_id": {"$in": members},
                },
                {"_id": 1},
            )
            if hit:
                return True
        except Exception:
            if scope.get("shared"):
                return True
    if get_user_db is None:
        return False

    async def _member_has_click(uid: str) -> bool:
        try:
            udb = get_user_db(uid)
            doc = await udb.clicks.find_one(
                {
                    "$and": [
                        {"$or": [
                            {"ip_address": canonical_ip},
                            {"ipv4": canonical_ip},
                            {"detected_ip": canonical_ip},
                        ]},
                        {"offer_scope_key": offer_key},
                    ]
                },
                {"_id": 1},
            )
            return bool(doc)
        except Exception:
            return False

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *[_member_has_click(uid) for uid in members[:100]],
                return_exceptions=True,
            ),
            timeout=2.5,
        )
    except asyncio.TimeoutError:
        return bool(scope.get("shared"))
    return any(item is True for item in results)


async def acquire_team_offer_ip_claim(
    db,
    user_id: str,
    offer_url: str,
    ip: str,
    visit_token: str,
    get_user_db: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Atomically reserve exact (stable scope, offer, canonical IP).

    Unique index = 100 teammates cannot share one IP on one offer.
    History lookup closes the gap for clicks recorded before claims.
    """
    token = (visit_token or "").strip()
    canonical_ip = canonicalize_ip(ip)
    normalized_url, offer_key = canonical_offer_identity(offer_url)
    if not token or len(token) > 256:
        raise ValueError("visit_token is required")
    if not canonical_ip:
        raise ValueError("valid canonical IP is required")
    scope = await resolve_isolation_scope(db, user_id)
    conflict = {
        "status": "conflict", "acquired": False,
        "scope_key": scope["scope_key"], "offer_key": offer_key,
        "offer_url_normalized": normalized_url, "ip": canonical_ip,
    }
    if await _team_ip_already_used(db, scope, offer_key, canonical_ip, get_user_db):
        return conflict
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "scope_key": scope["scope_key"],
        "group_id": scope["group_id"],
        "offer_key": offer_key,
        "offer_url_normalized": normalized_url,
        "ip": canonical_ip,
        "visit_token": token,
        "user_id": str(user_id).strip(),
        "status": "pending",
        "claimed_at": now,
        "expires_at": now + timedelta(seconds=PENDING_CLAIM_SECONDS),
    }
    try:
        await db[TEAM_OFFER_CLAIMS_COLLECTION].insert_one(doc)
        return {"status": "acquired", "acquired": True, **{k: doc[k] for k in (
            "scope_key", "offer_key", "offer_url_normalized", "ip", "visit_token"
        )}}
    except Exception as exc:
        try:
            from pymongo.errors import DuplicateKeyError
        except Exception:  # pragma: no cover
            DuplicateKeyError = ()  # type: ignore[assignment]
        if DuplicateKeyError and not isinstance(exc, DuplicateKeyError):
            raise
        existing = await db[TEAM_OFFER_CLAIMS_COLLECTION].find_one(
            {"scope_key": scope["scope_key"], "offer_key": offer_key, "ip": canonical_ip},
            {"_id": 0},
        )
        if not existing:
            raise
        if existing.get("visit_token") == token:
            return {
                "status": "idempotent", "acquired": True,
                "scope_key": scope["scope_key"], "offer_key": offer_key,
                "offer_url_normalized": normalized_url, "ip": canonical_ip,
                "visit_token": token,
            }
        return {
            "status": "conflict", "acquired": False,
            "scope_key": scope["scope_key"], "offer_key": offer_key,
            "offer_url_normalized": normalized_url, "ip": canonical_ip,
        }


async def complete_team_offer_ip_claim(
    db, user_id: str, offer_url: str, ip: str, visit_token: str
) -> bool:
    scope = await resolve_isolation_scope(db, user_id)
    _, offer_key = canonical_offer_identity(offer_url)
    canonical_ip = canonicalize_ip(ip)
    if not canonical_ip:
        return False
    result = await db[TEAM_OFFER_CLAIMS_COLLECTION].update_one(
        {
            "scope_key": scope["scope_key"], "offer_key": offer_key, "ip": canonical_ip,
            "visit_token": (visit_token or "").strip(), "status": "pending",
        },
        {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)},
         "$unset": {"expires_at": ""}},
    )
    if result.modified_count:
        return True
    existing = await db[TEAM_OFFER_CLAIMS_COLLECTION].find_one({
        "scope_key": scope["scope_key"], "offer_key": offer_key, "ip": canonical_ip,
        "visit_token": (visit_token or "").strip(), "status": "completed",
    })
    return bool(existing)


async def release_team_offer_ip_claim(
    db, user_id: str, offer_url: str, ip: str, visit_token: str
) -> bool:
    scope = await resolve_isolation_scope(db, user_id)
    _, offer_key = canonical_offer_identity(offer_url)
    canonical_ip = canonicalize_ip(ip)
    if not canonical_ip:
        return False
    result = await db[TEAM_OFFER_CLAIMS_COLLECTION].delete_one({
        "scope_key": scope["scope_key"], "offer_key": offer_key, "ip": canonical_ip,
        "visit_token": (visit_token or "").strip(), "status": "pending",
    })
    return bool(result.deleted_count)


async def find_team_offer_ip_conflict(db, user_id: str, offer_url: str, ip: str) -> Optional[Dict[str, Any]]:
    scope = await resolve_isolation_scope(db, user_id)
    _, offer_key = canonical_offer_identity(offer_url)
    canonical_ip = canonicalize_ip(ip)
    if not canonical_ip:
        return None
    return await db[TEAM_OFFER_CLAIMS_COLLECTION].find_one(
        {"scope_key": scope["scope_key"], "offer_key": offer_key, "ip": canonical_ip},
        {"_id": 0},
    )


async def list_team_offer_claimed_ips(db, user_id: str, offer_url: str) -> Set[str]:
    scope = await resolve_isolation_scope(db, user_id)
    _, offer_key = canonical_offer_identity(offer_url)
    out: Set[str] = set()
    async for doc in db[TEAM_OFFER_CLAIMS_COLLECTION].find(
        {"scope_key": scope["scope_key"], "offer_key": offer_key}, {"ip": 1, "_id": 0}
    ):
        canonical = canonicalize_ip(doc.get("ip"))
        if canonical:
            out.add(canonical)
    return out


async def list_team_shared_used_ips(db, user_id: str, offer_url: str) -> Set[str]:
    """Team used-IPs in 1–2 queries (claims + burnt), never N full peer scans.

    Calling ``_load_ips_for_user`` per teammate was O(N) distinct/aggregate
    over every tenant clicks DB — 10–100 VPS-ON users in one group stalled
    the whole VPS (and a global dup-IP lock then stalled unrelated customers).
    """
    out = await list_team_offer_claimed_ips(db, user_id, offer_url)
    try:
        scope = await resolve_isolation_scope(db, user_id)
        if not offer_url or not scope.get("member_ids"):
            return out
        _, offer_key = canonical_offer_identity(offer_url)
        members = list(scope.get("member_ids") or [])
        burnt = getattr(db, "rut_burnt_offer_ips", None)
        if burnt is None:
            try:
                burnt = db["rut_burnt_offer_ips"]
            except Exception:
                burnt = None
        if burnt is not None and members:
            async for doc in burnt.find(
                {"offer_scope_key": offer_key, "user_id": {"$in": members}},
                {"ip": 1, "_id": 0},
            ):
                canonical = canonicalize_ip(doc.get("ip"))
                if canonical:
                    out.add(canonical)
    except ValueError:
        pass
    return out


def invalidate_group_cache() -> None:
    _GROUP_CACHE["user_to_peers"] = {}
    _GROUP_CACHE["at"] = 0.0
    _SCOPE_CACHE.clear()


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


def _clean_claim_ips(ips: List[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for raw in ips or []:
        if not isinstance(raw, str):
            continue
        ip = raw.strip()
        if not ip or ip in _PLACEHOLDER_IPS or ip in seen:
            continue
        seen.add(ip)
        out.append(ip)
    return out


async def ledger_key_for_user(db, user_id: str) -> str:
    """Stable key for the shared IP claim namespace (self or VPS-ON team)."""
    members = await get_vps_ledger_member_ids(db, user_id)
    if not members:
        uid = (user_id or "").strip()
        return uid
    return "|".join(members)


async def ensure_vps_ip_claim_indexes(db) -> None:
    """Unique (ledger_key, ip) — first open wins the same-second race."""
    await db[CLAIMS_COLLECTION].create_index(
        [("ledger_key", 1), ("ip", 1)],
        unique=True,
        name="uniq_ledger_ip",
    )
    await db[CLAIMS_COLLECTION].create_index(
        [("ip", 1), ("claimed_at", -1)],
        name="ip_claimed_at",
    )


async def find_vps_ip_claim(db, user_id: str, ips: List[str]) -> Optional[str]:
    """Return a claimed IP if any candidate is already reserved on this ledger."""
    clean = _clean_claim_ips(ips)
    if not clean or not (user_id or "").strip():
        return None
    key = await ledger_key_for_user(db, user_id)
    if not key:
        return None
    doc = await db[CLAIMS_COLLECTION].find_one(
        {"ledger_key": key, "ip": {"$in": clean}},
        {"ip": 1, "_id": 0},
    )
    if doc and doc.get("ip"):
        return str(doc["ip"])
    return None


async def claim_vps_ips(
    db,
    user_id: str,
    ips: List[str],
    *,
    link_id: str = "",
    short_code: str = "",
) -> Optional[str]:
    """Atomically reserve IPs for this user's ledger.

    Returns the conflicting IP when another request already claimed it
    (lost the race); returns None when all inserts succeeded.
    """
    uid = (user_id or "").strip()
    clean = _clean_claim_ips(ips)
    if not uid or not clean:
        return None
    key = await ledger_key_for_user(db, uid)
    if not key:
        return None
    now = datetime.now(timezone.utc).isoformat()
    try:
        from pymongo.errors import DuplicateKeyError as _DupKey
    except Exception:  # noqa: BLE001
        _DupKey = Exception  # type: ignore[misc, assignment]

    for ip in clean:
        try:
            await db[CLAIMS_COLLECTION].insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "ledger_key": key,
                    "ip": ip,
                    "user_id": uid,
                    "link_id": (link_id or "").strip() or None,
                    "short_code": (short_code or "").strip() or None,
                    "claimed_at": now,
                }
            )
        except _DupKey:
            return ip
        except Exception:
            # Index missing / race without unique — fall back to find
            existing = await db[CLAIMS_COLLECTION].find_one(
                {"ledger_key": key, "ip": ip},
                {"ip": 1, "user_id": 1, "_id": 0},
            )
            if existing and str(existing.get("user_id") or "") != uid:
                return ip
            if existing:
                return ip
            raise
    return None


async def list_claimed_ips_for_user(db, user_id: str) -> Set[str]:
    """All IPs already claimed on this user's ledger (for RUT dup sets)."""
    uid = (user_id or "").strip()
    if not uid:
        return set()
    key = await ledger_key_for_user(db, uid)
    if not key:
        return set()
    out: Set[str] = set()
    async for doc in db[CLAIMS_COLLECTION].find({"ledger_key": key}, {"ip": 1, "_id": 0}):
        ip = doc.get("ip")
        if isinstance(ip, str) and ip.strip() and ip.strip() not in _PLACEHOLDER_IPS:
            out.add(ip.strip())
    return out


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


async def _assert_no_enabled_group_conflict(
    db, user_ids: List[str], *, except_group_id: Optional[str] = None
) -> None:
    """Admin-write guard for the one-user-one-enabled-group invariant.

    The live claim path independently detects legacy/concurrent corruption and
    fails closed; this check prevents an admin request knowingly creating it.
    """
    query: Dict[str, Any] = {"enabled": True, "user_ids": {"$in": user_ids}}
    if except_group_id:
        query["id"] = {"$ne": except_group_id}
    conflict = await db[COLLECTION].find_one(query, {"id": 1, "name": 1, "_id": 0})
    if conflict:
        raise ValueError("One or more users already belong to another enabled isolation group")


async def create_group(db, *, name: str, user_ids: List[str], enabled: bool = True) -> Dict[str, Any]:
    clean_ids = sorted({str(u).strip() for u in user_ids if str(u).strip()})
    if len(clean_ids) < 2:
        raise ValueError("Select at least 2 users for an isolation group")
    nm = (name or "").strip() or "Isolation Group"
    now = datetime.now(timezone.utc).isoformat()
    if enabled:
        await _assert_no_enabled_group_conflict(db, clean_ids)
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
        patch["user_ids"] = clean_ids
    if enabled is not None:
        patch["enabled"] = bool(enabled)

    resulting_users = patch.get("user_ids", existing.get("user_ids") or [])
    resulting_enabled = patch.get("enabled", existing.get("enabled", True))
    if resulting_enabled:
        await _assert_no_enabled_group_conflict(db, resulting_users, except_group_id=gid)

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
