"""
Krexion - Bridge Module (Cloud-Orchestrated Local Execution)
=============================================================

When a user is logged into the krexion.com cloud dashboard and clicks a
HEAVY feature (proxy bulk-test, RUT, form filler, visual recorder), this
module:

  1. Detects whether their local PC install is online (heartbeat < 90s).
  2. If ONLINE → enqueues the job into Mongo collection `bridge_jobs`,
     returns 202 + job_id to the frontend.
  3. If OFFLINE → returns 503 with a friendly "turn on your PC" message.

The local PC's sync_client.py pulls pending jobs every ~5s, executes
them against its own local backend, and posts the result back. The
frontend polls /api/bridge/jobs/{id} for the final result.

This means:
  - UI stays on krexion.com (no redirect to localhost)
  - Heavy CPU/RAM load runs on the customer's own machine
  - Cloud server stays light (just orchestrates)
  - Light features (links, clicks DB, redirects) stay 100% cloud
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

logger = logging.getLogger(__name__)

bridge_router = APIRouter(prefix="/api/bridge", tags=["bridge"])
bridge_sync_router = APIRouter(prefix="/api/sync", tags=["bridge-sync"])

# Bound by server.py on startup
_db: Any = None
_get_current_user: Any = None
_validate_license: Any = None

# Online threshold - heartbeat must be within this many seconds.
# 5 min — brief VPS/Mongo blips must not mark 100 busy PCs offline.
ONLINE_WINDOW_SEC = int(os.environ.get("BRIDGE_ONLINE_WINDOW_SEC", "300") or 300)

# How long a job can stay pending before we give up and tell the user.
JOB_TIMEOUT_SEC = int(os.environ.get("BRIDGE_JOB_TIMEOUT_SEC", "1800") or 1800)


def _bind(*, main_db, get_current_user, validate_license) -> None:
    global _db, _get_current_user, _validate_license
    _db = main_db
    _get_current_user = get_current_user
    _validate_license = validate_license


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ─────────────────────────────────────────────────────────────────────
# Helpers used by server.py heavy endpoints
# ─────────────────────────────────────────────────────────────────────
async def is_user_local_online(user_id: str) -> dict:
    """Returns {online: bool, hostname, ram_gb, last_seen_sec_ago}."""
    # v1.0.21: sort by last_seen DESC so we always pick the FRESHEST
    # heartbeat document. Previously find_one returned ANY match —
    # and because sync_heartbeats is keyed on license_key (one doc
    # per license), a user who re-paired/re-installed could end up
    # with multiple heartbeat docs and the cloud might pick a stale
    # one, declaring the user offline even though the new install
    # was happily heartbeating every 5 s.
    #
    # v1.0.23: ALSO match by every license_key owned by this user.
    # Customer reported: desktop logs show heartbeat POST 200 OK every
    # 5 s against krexion.com (verified in logs.zip), but cloud says
    # "last seen 12614 s ago". That mathematically requires the cloud
    # to be reading a DIFFERENT heartbeat doc than the one the desktop
    # is writing — i.e. user_id mismatch. Most likely cause: customer
    # paired the desktop with license_key K when on account A, later
    # logged into account B which now owns license K (admin re-issued
    # or license was reassigned), but the heartbeat doc still has the
    # OLD user_id of account A. The desktop is happily heartbeating
    # to K, the cloud reads "show me heartbeats for B's user_id" —
    # finds nothing (or finds a STALE doc from a previous pair).
    # Fix: query by ($or user_id OR license_key in user's licenses).
    license_keys: list[str] = []
    try:
        async for lic in _db.licenses.find({"user_id": user_id}, {"license_key": 1, "_id": 0}):
            lk = (lic or {}).get("license_key")
            if lk:
                license_keys.append(lk)
    except Exception:  # noqa: BLE001
        pass
    or_clauses: list[dict] = [{"user_id": user_id}]
    if license_keys:
        or_clauses.append({"license_key": {"$in": license_keys}})
    hb = await _db.sync_heartbeats.find_one(
        {"$or": or_clauses},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    if not hb or not hb.get("last_seen"):
        logger.info(
            f"[bridge] is_user_local_online user_id={user_id[:8]} "
            f"licenses={len(license_keys)} → no heartbeat doc found"
        )
        return {"online": False, "reason": "no_heartbeat_ever"}
    try:
        last = datetime.fromisoformat(str(hb["last_seen"]).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return {"online": False, "reason": "bad_heartbeat_ts"}
    age = (_now() - last).total_seconds()
    online = age <= ONLINE_WINDOW_SEC
    return {
        "online": online,
        "hostname": hb.get("hostname") or "",
        "ram_gb": hb.get("ram_gb"),
        "cpu_cores": hb.get("cpu_cores"),
        "platform": hb.get("platform") or "",
        "version": hb.get("version") or "",
        "last_seen": hb.get("last_seen"),
        "last_seen_sec_ago": int(age),
        "reason": None if online else "stale_heartbeat",
    }


async def enqueue_bridge_job(
    user: dict,
    feature: str,
    payload: dict,
    *,
    wait_for_result: bool = False,
    wait_timeout: int = 25,
) -> dict:
    """Create a pending job for the user's local PC to execute.

    If `wait_for_result` is True we wait inline up to `wait_timeout`s for the
    local worker to complete the job (so the frontend gets a synchronous
    response for short jobs). Otherwise returns {job_id, status:'pending'}
    and the frontend polls /api/bridge/jobs/{id}.
    """
    status = await is_user_local_online(user["id"])
    if not status["online"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "local_pc_offline",
                "message": (
                    "Connection lost. Please open Krexion on your computer "
                    "and keep AdsPower running — Krexion will reconnect "
                    "automatically within a few seconds."
                ),
                "local_status": status,
            },
        )

    job_id = uuid.uuid4().hex
    now_iso = _now_iso()
    # v1.0.19: pre-exclude the legacy PowerShell stub from claiming
    # any heavy job (anything that ISN'T an adspower/* call). The PS
    # stub doesn't know how to run real-user-traffic/start,
    # visual-recorder/start, form-filler/run etc., so without this
    # filter it would race the Python sync_client, claim the job
    # first, fail it with "feature not supported", and the customer
    # would see "Start failed" before Python ever got a chance.
    excluded_workers: list[str] = []
    if not str(feature).startswith("adspower/"):
        excluded_workers.append("powershell")
    doc = {
        "id": job_id,
        "user_id": user["id"],
        "email": user.get("email"),
        "feature": feature,
        "payload": payload,
        "status": "pending",
        "result": None,
        "error": None,
        "created_at": now_iso,
        "started_at": None,
        "completed_at": None,
        "claimed_by": None,
        "excluded_workers": excluded_workers,
    }
    await _db.bridge_jobs.insert_one(doc)
    logger.info(
        f"[bridge] enqueued job {job_id[:8]} feature={feature} user={user.get('email')} "
        f"hostname={status.get('hostname','?')} wait_for_result={wait_for_result} "
        f"timeout={wait_timeout}s"
    )

    if not wait_for_result:
        # Return without _id from MongoDB
        doc_clean = {k: v for k, v in doc.items() if k != "_id"}
        return {"job_id": job_id, "status": "pending", "local": status, "job": doc_clean}

    # Inline poll for short jobs
    deadline = asyncio.get_event_loop().time() + wait_timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)
        j = await _db.bridge_jobs.find_one({"id": job_id}, {"_id": 0})
        if j and j.get("status") in ("done", "failed"):
            logger.info(
                f"[bridge] job {job_id[:8]} completed inline → {j.get('status')}"
            )
            return {"job_id": job_id, "status": j["status"], "result": j.get("result"), "error": j.get("error")}
    logger.info(f"[bridge] job {job_id[:8]} still pending after {wait_timeout}s — handing back to caller")
    return {"job_id": job_id, "status": "pending", "local": status, "timeout": True}


# ─────────────────────────────────────────────────────────────────────
# Frontend-facing endpoints — REGISTERED FROM server.py
# (server.py has direct access to its JWT get_current_user dependency)
# Helper functions used by those routes are below.
# ─────────────────────────────────────────────────────────────────────
async def get_my_local_status_for(user_id: str) -> dict:
    return await is_user_local_online(user_id)


async def get_my_job(job_id: str, user_id: str, email: Optional[str] = None) -> dict:
    # v2.1.70 HEAL: same user_id-OR-email pattern as worker_pull_jobs
    # so a stale users-collection duplicate doesn't 404 the customer.
    _u: list = [{"user_id": user_id}]
    if email:
        _u.append({"email": email})
    j = await _db.bridge_jobs.find_one({"id": job_id, "$or": _u}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.get("status") == "pending":
        try:
            created = datetime.fromisoformat(str(j["created_at"]).replace("Z", "+00:00"))
            if (_now() - created).total_seconds() > JOB_TIMEOUT_SEC:
                await _db.bridge_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"status": "failed", "error": "timeout: local PC did not pick up job", "completed_at": _now_iso()}},
                )
                j["status"] = "failed"
                j["error"] = "timeout: local PC did not pick up job"
        except Exception:
            pass
    return j


async def list_jobs_for(user_id: str, limit: int = 50, email: Optional[str] = None) -> list:
    # v2.1.70 HEAL: same user_id-OR-email pattern.
    _u: list = [{"user_id": user_id}]
    if email:
        _u.append({"email": email})
    cursor = _db.bridge_jobs.find({"$or": _u}, {"_id": 0}).sort("created_at", -1).limit(min(limit, 200))
    return await cursor.to_list(200)


async def get_or_create_license_for_user(user: dict) -> dict:
    """Find an existing active license for the user, or generate a new
    one. Used by the 'Pair my PC' flow to give the customer a key they
    can drop into their local install's .env file so heartbeats start
    landing in the cloud DB."""
    existing = await _db.licenses.find_one(
        {"email": user["email"], "status": {"$in": ["active", "issued"]}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if existing and existing.get("license_key"):
        return {"license_key": existing["license_key"], "created": False, "license": existing}

    # Generate a new license key
    new_key = "KRX-" + uuid.uuid4().hex.upper()[:24]
    doc = {
        "id": uuid.uuid4().hex,
        "license_key": new_key,
        "email": user["email"],
        "user_id": user["id"],
        "plan": "self-paired",
        "status": "active",
        "created_at": _now_iso(),
        "expires_at": None,
        "machine_fingerprint": None,
        "source": "self-pair",
    }
    await _db.licenses.insert_one(doc)
    logger.info(f"[bridge.pair] new license created for {user['email']}: {new_key[:18]}...")
    doc_clean = {k: v for k, v in doc.items() if k != "_id"}
    return {"license_key": new_key, "created": True, "license": doc_clean}


# ─────────────────────────────────────────────────────────────────────
# Local-worker endpoints (auth = X-Krexion-License)
# ─────────────────────────────────────────────────────────────────────
@bridge_sync_router.get("/jobs/pull")
async def worker_pull_jobs(
    request: Request,
    x_krexion_license: Optional[str] = Header(None),
    limit: int = 5,
    hostname: Optional[str] = None,
    feature_prefix: Optional[str] = None,
):
    """Local sync_client pulls up to `limit` pending jobs for its user.
    Marks them as 'running' so other workers (if any) don't double-run.

    v1.0.19: `feature_prefix` lets a limited worker (e.g. the legacy
    PowerShell `KrexionBridge` scheduled task that ONLY knows the
    adspower/* features) opt-in to only the jobs it can actually
    execute. Without this filter the PowerShell stub was racing the
    Python sync_client, claiming heavy jobs like visual-recorder/start
    and immediately failing them with 'feature not supported by the
    PowerShell bridge worker', which is what the customer reported."""
    if _validate_license is None:
        raise HTTPException(status_code=500, detail="Bridge not initialised")
    lic, user = await _validate_license(x_krexion_license)
    limit = max(1, min(limit, 20))

    claimed = []
    # v2.1.70 HEAL: match by user_id OR email so a stale users-collection
    # duplicate (where find_one({"email": ...}) returns a different
    # `id` than the one the cloud enqueue path saw) doesn't strand the
    # bridge job in "pending" forever. Same pattern that v1.0.23 added
    # to sync_heartbeats — see sync_module.py:197 comment.
    _user_match: list = [{"user_id": user["id"]}]
    if user.get("email"):
        _user_match.append({"email": user["email"]})
    base_query: dict = {"$or": _user_match, "status": "pending"}
    # v1.0.19: workers identify themselves via `worker_type` (free-form
    # string). The Python sync_client passes `worker_type=python`, the
    # legacy PowerShell scheduled task passes nothing. Any job that was
    # already once rejected by the PS stub gets `excluded_workers` set
    # and we filter it out for any worker whose type is in that list.
    worker_type = (request.query_params.get("worker_type") or "").lower().strip()
    if not worker_type:
        # Legacy PS stub never sends worker_type — treat that as PS so
        # requeued jobs go straight to the Python sync_client (which
        # always sends worker_type=python in v1.0.19+).
        worker_type = "powershell"
    if worker_type:
        base_query["excluded_workers"] = {"$nin": [worker_type]}
    if feature_prefix:
        # Match any feature that begins with the given prefix (e.g.
        # "adspower/" matches "adspower/test", "adspower/create" …)
        # Escape regex specials so a stray '.' or '?' can't broaden it.
        import re as _re
        base_query["feature"] = {"$regex": "^" + _re.escape(feature_prefix)}

    for _ in range(limit):
        # Atomic find-and-claim
        doc = await _db.bridge_jobs.find_one_and_update(
            base_query,
            {
                "$set": {
                    "status": "running",
                    "started_at": _now_iso(),
                    "claimed_by": (hostname or "")[:120],
                }
            },
            sort=[("created_at", 1)],
            projection={"_id": 0},
        )
        if not doc:
            break
        claimed.append(doc)
    if claimed:
        logger.info(
            f"[bridge] worker {hostname or '?'} prefix={feature_prefix or '*'} "
            f"claimed {len(claimed)} job(s) for user={user.get('email')}: "
            + ", ".join(f"{j['id'][:8]}={j.get('feature','?')}" for j in claimed)
        )
    return {"jobs": claimed, "server_time": _now_iso()}


@bridge_sync_router.post("/jobs/result")
async def worker_post_result(
    body: dict,
    x_krexion_license: Optional[str] = Header(None),
):
    if _validate_license is None:
        raise HTTPException(status_code=500, detail="Bridge not initialised")
    lic, user = await _validate_license(x_krexion_license)
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id required")

    # v1.0.19: when the legacy PowerShell stub returns "feature not
    # supported by the PowerShell bridge worker" for a job, the right
    # behaviour is to PUT IT BACK in the queue (status=pending) so the
    # Python sync_client running on the same PC can pick it up next
    # cycle — NOT to mark it failed and surface that misleading error
    # to the customer (which is exactly what they were seeing for
    # visual-recorder/start, real-user-traffic/start, form-filler/run
    # etc). The PowerShell bridge only knows the adspower/* features.
    new_status = body.get("status", "done")
    err_text = (body.get("error") or "").lower()
    if new_status == "failed" and (
        "not supported by the powershell bridge worker" in err_text
        or "unhandled feature" in err_text
    ):
        # Track requeue count to avoid an infinite ping-pong if the
        # Python sync_client is somehow absent or also broken. After
        # 3 requeues we let the failure stand.
        # v2.1.71 HEAL: same user_id-OR-email pattern.
        _u_rq: list = [{"user_id": user["id"]}]
        if user.get("email"):
            _u_rq.append({"email": user["email"]})
        existing = await _db.bridge_jobs.find_one(
            {"id": job_id, "$or": _u_rq}, {"requeue_count": 1}
        )
        requeue_count = int((existing or {}).get("requeue_count") or 0)
        if requeue_count >= 3:
            logger.warning(
                f"[bridge] job {job_id[:8]} requeued {requeue_count}x already; "
                f"letting PowerShell failure stand."
            )
        else:
            logger.info(
                f"[bridge] requeue {job_id[:8]} (#{requeue_count + 1}) — claimed by "
                f"legacy PowerShell stub which can't run this feature. Will be "
                f"picked up by the Python sync_client on next pull."
            )
            await _db.bridge_jobs.update_one(
                {"id": job_id, "$or": _u_rq},
                {
                    "$set": {
                        "status": "pending",
                        "started_at": None,
                        "claimed_by": None,
                        "result": None,
                        "error": None,
                        # After a PowerShell stub rejection, mark this
                        # job to skip the PS worker on future pulls.
                        # The PS pull endpoint passes feature_prefix=
                        # adspower/ so it can't match anyway, but for
                        # legacy installs that DON'T pass the prefix
                        # we also gate via job's `excluded_workers`
                        # list. Cloud-side guard below in pull.
                        "excluded_workers": ["powershell"],
                    },
                    "$inc": {"requeue_count": 1},
                },
            )
            return {"updated": 0, "requeued": True}

    # v2.1.71 HEAL: same user_id-OR-email pattern as worker_pull_jobs.
    # Desktop side resolves user via license; cloud side may have a
    # different user.id for the same email. Result-post must also
    # widen its match, else claimed jobs get stuck in "running" and
    # the cloud's wait_for_result times out at 35 s.
    _u_post: list = [{"user_id": user["id"]}]
    if user.get("email"):
        _u_post.append({"email": user["email"]})
    update = {
        "$set": {
            "status": new_status,
            "result": body.get("result"),
            "error": body.get("error"),
            "completed_at": _now_iso(),
        }
    }
    res = await _db.bridge_jobs.update_one(
        {"id": job_id, "$or": _u_post, "status": {"$in": ["running", "pending"]}},
        update,
    )
    logger.info(
        f"[bridge] worker posted result for {job_id[:8]} → "
        f"status={new_status} err={(body.get('error') or '')[:120]} "
        f"updated={res.modified_count}"
    )
    return {"updated": res.modified_count}
