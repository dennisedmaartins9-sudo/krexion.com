"""
CPI (Cost-Per-Install) Module for Krexion
==========================================

Purpose:
  Cloud-orchestrated CPI install pipeline that runs alongside the existing
  RUT (Real User Traffic) and Form Filler engines. The orchestrator (this
  module) runs in the home-PC backend; actual Android/iOS install execution
  is performed by a separate `krexion-cpi-worker` process which polls jobs
  from this orchestrator and reports results back.

Phase 1 (this file) covers:
  • Mongo models + per-user database scoping (matches existing pattern)
  • CRUD APIs for offers, jobs, devices, smart-links
  • SmartLink OS-routing public redirect with click tracking
  • Worker protocol: poll, claim, report (stateless HTTP, simple to scale)
  • Live install-attempts log for the UI dashboard
  • Earnings / conversion-rate aggregation for dashboard cards

Conversion model (per user request):
  We DO NOT receive postbacks from CPI networks. Instead the worker reports
  "install + behavior simulation completed" → backend marks the attempt as
  `conversion_likely` after a configurable settle delay. The user verifies
  real conversion on the network panel themselves. This keeps zero
  network-side footprint (no postback URL leak).
"""
from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query, Body
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ConfigDict
from user_agents import parse as parse_ua

logger = logging.getLogger("cpi")

# These will be injected by server.py at import time via _bind()
_main_db = None
_get_db_for_user = None
_get_current_user = None
_get_current_user_with_fresh_data = None
_check_user_feature = None
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bind(main_db, get_db_for_user, get_current_user, get_current_user_with_fresh_data,
          check_user_feature, get_user_db=None, load_upload_items=None,
          consume_uploads=None):
    """Inject server.py dependencies once at startup."""
    global _main_db, _get_db_for_user, _get_current_user
    global _get_current_user_with_fresh_data, _check_user_feature
    global _get_user_db, _load_upload_items, _consume_uploads
    _main_db = main_db
    _get_db_for_user = get_db_for_user
    _get_current_user = get_current_user
    _get_current_user_with_fresh_data = get_current_user_with_fresh_data
    _check_user_feature = check_user_feature
    _get_user_db = get_user_db
    _load_upload_items = load_upload_items
    _consume_uploads = consume_uploads


# Optional helpers (set by _bind) — used for "use Uploaded Things" integration
_get_user_db = None
_load_upload_items = None
_consume_uploads = None


# ────────────────────────────────────────────────────────────────────────
# Models
# ────────────────────────────────────────────────────────────────────────

# ── 2026-02 v2.1.31 — Behavior Simulator plan builder ────────────────────
# AppsFlyer Protect360 v2024 + Adjust + Kochava all run ML that flags
# attribution events with "zero engagement after install". A real user
# opens the app multiple times in the first 24-72h, swipes around,
# triggers events (level_up, screen_view, …). We emit a per-attempt
# schedule the worker can follow. This file is the source of truth so
# the schedule is deterministic-per-attempt (worker can re-poll without
# producing wildly different plans).
import random as _bp_random

_INTENSITY_ACTIONS_PER_DAY = {
    "low":    4,
    "medium": 10,
    "high":   20,
}
# Realistic action mix observed in real user sessions
_ACTION_BUCKETS = [
    ("app_open",        0.32),  # cold-start the app
    ("app_resume",      0.22),  # foreground from background
    ("scroll",          0.15),
    ("tap",             0.15),
    ("swipe",           0.07),
    ("screen_view",     0.05),  # navigate to a screen → fires AF screen event
    ("session_idle",    0.04),  # leave app open 30-120s without interaction
]

def _pick_action() -> str:
    r = _bp_random.random()
    acc = 0.0
    for name, w in _ACTION_BUCKETS:
        acc += w
        if r <= acc:
            return name
    return _ACTION_BUCKETS[0][0]


def build_behavior_plan(
    intensity: str = "medium",
    window_hours: int = 24,
    *,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return a sequence of post-install actions the worker executes
    over `window_hours` to defeat zero-engagement detection.

    Each entry: ``{at_offset_seconds, action, params}``.

    ``at_offset_seconds`` is measured from the install moment. The first
    action is delayed at least 60s (real users rarely open immediately)
    and the rest cluster non-uniformly with longer night-time gaps to
    mimic human circadian patterns.
    """
    rng = _bp_random.Random(seed) if seed is not None else _bp_random.Random()
    intensity = (intensity or "medium").lower()
    per_day = _INTENSITY_ACTIONS_PER_DAY.get(intensity, 10)
    window_hours = max(1, min(168, int(window_hours or 24)))
    total_actions = max(2, int(per_day * (window_hours / 24.0)))
    total_seconds = window_hours * 3600

    # Generate offsets using a beta-skewed distribution so MOST actions
    # happen in first 4-8h (matching real install→engagement curves).
    offsets: List[int] = []
    for _ in range(total_actions):
        # alpha=1.5, beta=4 → bell skewed toward t=0 with a long tail
        t = rng.betavariate(1.5, 4.0) * total_seconds
        offsets.append(int(t))
    offsets.sort()
    # Ensure first action ≥ 60s after install (real users don't insta-open)
    if offsets and offsets[0] < 60:
        offsets[0] = 60 + rng.randint(0, 120)
    # Enforce ≥ 90s gap between consecutive actions
    for i in range(1, len(offsets)):
        if offsets[i] - offsets[i - 1] < 90:
            offsets[i] = offsets[i - 1] + 90 + rng.randint(0, 180)

    plan: List[Dict[str, Any]] = []
    for off in offsets:
        action = _pick_action()
        params: Dict[str, Any] = {}
        if action == "swipe":
            params = {
                "direction": rng.choice(["up", "down", "left", "right"]),
                "distance_px": rng.randint(180, 720),
                "duration_ms": rng.randint(180, 420),
            }
        elif action == "tap":
            params = {"jitter_px": rng.randint(0, 8)}
        elif action == "scroll":
            params = {
                "direction": rng.choice(["up", "down"]),
                "steps": rng.randint(2, 6),
            }
        elif action == "session_idle":
            params = {"hold_seconds": rng.randint(30, 120)}
        elif action == "app_open" or action == "app_resume":
            params = {"min_dwell_seconds": rng.randint(8, 45)}
        elif action == "screen_view":
            params = {"screen": rng.choice([
                "home", "profile", "offers", "settings", "rewards", "history",
            ])}
        plan.append({
            "at_offset_seconds": int(off),
            "action": action,
            "params": params,
        })
    return plan


class CPIOfferIn(BaseModel):
    name: str
    network: Optional[str] = ""
    target_os: str = "android"  # "android" | "ios" | "both"
    tracker_url: str
    smart_link_code: Optional[str] = None
    apk_url: Optional[str] = None       # Android direct-APK
    ipa_url: Optional[str] = None       # iOS sideload IPA
    package_name: Optional[str] = None
    ios_app_id: Optional[str] = None
    payout: float = 0.0
    geo: Optional[str] = ""             # comma-separated ISO-2 codes
    daily_cap: int = 0
    notes: Optional[str] = ""
    status: str = "active"              # "active" | "paused"


class CPIOffer(CPIOfferIn):
    id: str
    user_id: str
    created_at: str
    updated_at: str
    total_clicks: int = 0
    total_installs: int = 0
    total_conversions: int = 0
    total_earnings: float = 0.0


class CPIJobIn(BaseModel):
    offer_id: str
    target_count: int = 10
    concurrency: int = 2
    delay_min_seconds: int = 60
    delay_max_seconds: int = 300
    proxies: List[str] = Field(default_factory=list)        # "ip:port:user:pass"
    user_agents: List[str] = Field(default_factory=list)
    leads: List[Dict[str, str]] = Field(default_factory=list)  # [{email,first,last,phone}, ...]
    settle_seconds: int = 45                                # wait after install before marking "conversion_likely"
    # Pull from Uploaded Things (Krexion's existing resource pool)
    upload_proxy_id: Optional[str] = None
    upload_ua_id: Optional[str] = None
    # ── 2026-01 v2.4.0 — Optional multi-provider proxy dropdown ──────
    # When set (from settings > Proxy Providers), the CPI job start
    # resolver adds a resolved proxy line into the pool. Empty ⇒ 100 %
    # legacy behavior.
    proxy_provider_id: Optional[str] = None
    # Auto-consume used resources after job completes (mirrors RUT behavior)
    auto_consume: bool = True
    # ── 2026-02 v2.1.31 — Mobile CPI Behavior Simulator ──────────────
    # When True, the orchestrator emits a `behavior_plan` along with each
    # claimed attempt in the /worker/poll response. The worker uses the
    # plan to simulate post-install activity (random app opens, swipes,
    # in-app session beats) over `behavior_sim_window_hours`. Bypasses
    # AppsFlyer Protect360 v2024 + Adjust's "no engagement after install"
    # ML detector. Workers that don't recognise the field ignore it
    # gracefully (forward-compatible).
    behavior_sim_enabled: bool = False
    # "low" = ~4 actions/day, "medium" = ~10/day, "high" = ~20/day
    behavior_sim_intensity: str = "medium"
    # Distribute actions across this many hours (typical: 24, 48, 72)
    behavior_sim_window_hours: int = 24


class CPIJob(BaseModel):
    id: str
    user_id: str
    offer_id: str
    offer_name: str
    target_os: str
    target_count: int
    concurrency: int
    delay_min_seconds: int
    delay_max_seconds: int
    settle_seconds: int
    proxies_count: int
    uas_count: int
    leads_count: int
    status: str = "queued"        # queued | running | paused | completed | stopped | failed
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    # ── 2026-02 v2.1.31 — Behavior Simulator (read-back) ──
    behavior_sim_enabled: bool = False
    behavior_sim_intensity: str = "medium"
    behavior_sim_window_hours: int = 24


class CPIInstallAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    job_id: str
    offer_id: str
    user_id: str
    device_id: Optional[str] = None
    device_label: Optional[str] = None
    proxy_used: Optional[str] = None
    ua_used: Optional[str] = None
    lead_used: Optional[Dict[str, str]] = None
    click_id: Optional[str] = None
    status: str = "queued"        # queued | running | installed | completed | failed | conversion_likely
    failure_reason: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)  # worker reports staged progress
    created_at: str


class CPIDeviceRegister(BaseModel):
    device_id: str                # worker-generated stable ID (e.g., adb serial / iOS UDID)
    device_type: str              # android_real | android_emulator | android_cloud | ios_real | …
    label: Optional[str] = None
    model: Optional[str] = None
    os_version: Optional[str] = None
    worker_token: Optional[str] = None  # worker authenticates to backend with this


class CPIDeviceActionBody(BaseModel):
    """Queue an action for the home-PC worker (open_url / install_apk)."""
    type: str = Field(..., max_length=32)  # open_url | install_apk
    url: str = Field(default="", max_length=1024)
    apk_url: str = Field(default="", max_length=1024)
    package_name: str = Field(default="", max_length=200)


class CPICloudPhoneProvisionBody(BaseModel):
    """Register a partner ARM cloud phone ADB tunnel (no USB phone)."""
    label: str = Field(default="Cloud Phone", max_length=120)
    adb_endpoint: str = Field(..., min_length=3, max_length=120)  # host:port
    provider: str = Field(default="partner", max_length=40)  # partner|geelark|redfinger|custom
    external_id: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)


class CPIAndroidEnableBody(BaseModel):
    """One-click Krexion Android farm enable."""
    instances: int = Field(default=1, ge=1, le=8)


class CPIApkLibraryBody(BaseModel):
    apk_url: str = Field(..., min_length=8, max_length=1024)
    label: str = Field(default="", max_length=120)
    package_name: str = Field(default="", max_length=200)


class CPIDevice(BaseModel):
    id: str
    user_id: str
    device_id: str
    device_type: str
    label: str
    model: Optional[str] = None
    os_version: Optional[str] = None
    status: str = "offline"        # online | busy | offline | error | needs_attention
    last_heartbeat: Optional[str] = None
    last_install_at: Optional[str] = None
    total_installs: int = 0
    successful_installs: int = 0
    needs_action: Optional[Any] = None  # dict action or legacy string
    adb_endpoint: Optional[str] = None
    cloud_provider: Optional[str] = None
    created_at: str


class CPISmartLinkIn(BaseModel):
    name: str
    offer_id: Optional[str] = None
    android_url: Optional[str] = None
    ios_url: Optional[str] = None
    desktop_url: Optional[str] = None
    fallback_url: Optional[str] = "https://www.google.com/"


class CPISmartLink(CPISmartLinkIn):
    id: str
    user_id: str
    code: str
    total_clicks: int = 0
    android_clicks: int = 0
    ios_clicks: int = 0
    desktop_clicks: int = 0
    created_at: str


# ────────────────────────────────────────────────────────────────────────
# Router
# ────────────────────────────────────────────────────────────────────────

cpi_router = APIRouter(prefix="/api/cpi", tags=["cpi"])

FEATURE_KEY = "cpi"


def _new_id() -> str:
    return secrets.token_hex(12)


def _short_code(n: int = 8) -> str:
    return secrets.token_urlsafe(n)[:n]


async def _require_cpi_user(request: Request) -> dict:
    """Authenticated user with CPI feature flag enabled."""
    user = await _get_current_user_with_fresh_data(request)
    _check_user_feature(user, FEATURE_KEY)
    return user


def _detect_os_from_ua(ua_string: str) -> str:
    if not ua_string:
        return "unknown"
    try:
        ua = parse_ua(ua_string)
        if ua.os.family.lower().startswith("ios") or ua.os.family.lower() == "ios":
            return "ios"
        if "iphone" in ua_string.lower() or "ipad" in ua_string.lower():
            return "ios"
        if "android" in ua_string.lower():
            return "android"
        if ua.is_pc or ua.is_bot or "windows" in ua_string.lower() or "mac os" in ua_string.lower():
            return "desktop"
        return "unknown"
    except Exception:
        return "unknown"


# ────────────────────────────────────────────────────────────────────────
# OFFERS
# ────────────────────────────────────────────────────────────────────────

@cpi_router.post("/offers", response_model=CPIOffer)
async def create_offer(payload: CPIOfferIn, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    now = _iso_now()
    offer_id = _new_id()
    doc = {
        **payload.model_dump(),
        "id": offer_id,
        "user_id": user["id"],
        "created_at": now,
        "updated_at": now,
        "total_clicks": 0,
        "total_installs": 0,
        "total_conversions": 0,
        "total_earnings": 0.0,
    }
    if not doc.get("smart_link_code"):
        doc["smart_link_code"] = _short_code(10)
    await db.cpi_offers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@cpi_router.get("/offers", response_model=List[CPIOffer])
async def list_offers(request: Request, status: Optional[str] = None):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    q = {"user_id": user["id"]}
    if status:
        q["status"] = status
    cursor = db.cpi_offers.find(q, {"_id": 0}).sort("created_at", -1)
    return [doc async for doc in cursor]


@cpi_router.get("/offers/{offer_id}", response_model=CPIOffer)
async def get_offer(offer_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    doc = await db.cpi_offers.find_one({"id": offer_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Offer not found")
    return doc


@cpi_router.put("/offers/{offer_id}", response_model=CPIOffer)
async def update_offer(offer_id: str, payload: CPIOfferIn, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    update = {**payload.model_dump(), "updated_at": _iso_now()}
    res = await db.cpi_offers.find_one_and_update(
        {"id": offer_id, "user_id": user["id"]},
        {"$set": update},
        return_document=True,
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Offer not found")
    return res


@cpi_router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    await db.cpi_offers.delete_one({"id": offer_id, "user_id": user["id"]})
    return {"ok": True}


# ────────────────────────────────────────────────────────────────────────
# SMART LINKS  (public redirect + click tracking)
# ────────────────────────────────────────────────────────────────────────

@cpi_router.post("/smartlinks", response_model=CPISmartLink)
async def create_smartlink(payload: CPISmartLinkIn, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    code = _short_code(10)
    while await db.cpi_smartlinks.find_one({"code": code}):
        code = _short_code(10)
    doc = {
        **payload.model_dump(),
        "id": _new_id(),
        "user_id": user["id"],
        "code": code,
        "total_clicks": 0,
        "android_clicks": 0,
        "ios_clicks": 0,
        "desktop_clicks": 0,
        "created_at": _iso_now(),
    }
    await db.cpi_smartlinks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@cpi_router.get("/smartlinks", response_model=List[CPISmartLink])
async def list_smartlinks(request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    cursor = db.cpi_smartlinks.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    return [doc async for doc in cursor]


@cpi_router.delete("/smartlinks/{sl_id}")
async def delete_smartlink(sl_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    await db.cpi_smartlinks.delete_one({"id": sl_id, "user_id": user["id"]})
    return {"ok": True}


@cpi_router.get("/sl/{code}")
async def smartlink_redirect(code: str, request: Request):
    """PUBLIC: Hit by users / our worker. Detects OS, redirects, logs click."""
    # Search across ALL user dbs by indexing on the smart-links collection.
    # For now we mirror the row in main_db at creation time? Simpler: scan user
    # databases via list of users. The expected hit volume is low (worker
    # mostly bypasses this and goes direct to tracker_url) so we accept the
    # cost. Fast path: cache the lookup in-memory.
    cache = smartlink_redirect.__dict__.setdefault("_cache", {})
    entry = cache.get(code)
    if entry is None or (datetime.now(timezone.utc).timestamp() - entry["t"]) > 60:
        # find it
        users = [u async for u in _main_db.users.find({}, {"id": 1, "_id": 0})]
        sl_doc = None
        owner_id = None
        for u in users:
            udb = _get_db_for_user(u)
            d = await udb.cpi_smartlinks.find_one({"code": code}, {"_id": 0})
            if d:
                sl_doc = d
                owner_id = u["id"]
                break
        cache[code] = {"t": datetime.now(timezone.utc).timestamp(), "doc": sl_doc, "owner": owner_id}
        entry = cache[code]
    sl_doc = entry.get("doc")
    if not sl_doc:
        raise HTTPException(status_code=404, detail="Smart-link not found")
    owner_id = entry["owner"]

    ua = request.headers.get("user-agent", "")
    os_kind = _detect_os_from_ua(ua)
    target_url = (
        sl_doc.get("android_url") if os_kind == "android"
        else sl_doc.get("ios_url") if os_kind == "ios"
        else sl_doc.get("desktop_url") if os_kind == "desktop"
        else None
    ) or sl_doc.get("fallback_url") or "https://www.google.com/"

    # Log click (non-blocking, best-effort)
    try:
        owner = {"id": owner_id, "is_sub_user": False}
        udb = _get_db_for_user(owner)
        await udb.cpi_smartlinks.update_one(
            {"id": sl_doc["id"]},
            {"$inc": {
                "total_clicks": 1,
                f"{os_kind}_clicks": 1 if os_kind in ("android", "ios", "desktop") else 0,
            }},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[cpi-sl] click log failed: {e}")

    return RedirectResponse(target_url, status_code=302)


# ────────────────────────────────────────────────────────────────────────
# DEVICES (worker registers here)
# ────────────────────────────────────────────────────────────────────────

@cpi_router.post("/devices/register", response_model=CPIDevice)
async def register_device(payload: CPIDeviceRegister, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    existing = await db.cpi_devices.find_one(
        {"device_id": payload.device_id, "user_id": user["id"]}, {"_id": 0}
    )
    if existing:
        await db.cpi_devices.update_one(
            {"id": existing["id"]},
            {"$set": {
                "device_type": payload.device_type,
                "label": payload.label or existing["label"],
                "model": payload.model or existing.get("model"),
                "os_version": payload.os_version or existing.get("os_version"),
                "status": "online",
                "last_heartbeat": _iso_now(),
            }},
        )
        existing.update({"status": "online", "last_heartbeat": _iso_now()})
        return existing
    doc = {
        "id": _new_id(),
        "user_id": user["id"],
        "device_id": payload.device_id,
        "device_type": payload.device_type,
        "label": payload.label or payload.device_id[:12],
        "model": payload.model,
        "os_version": payload.os_version,
        "status": "online",
        "last_heartbeat": _iso_now(),
        "last_install_at": None,
        "total_installs": 0,
        "successful_installs": 0,
        "needs_action": None,
        "created_at": _iso_now(),
    }
    await db.cpi_devices.insert_one(doc)
    doc.pop("_id", None)
    return doc


@cpi_router.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(device_id: str, request: Request, payload: Dict[str, Any] = Body(default={})):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    update = {"last_heartbeat": _iso_now()}
    if "status" in payload:
        update["status"] = payload["status"]
    # Worker may ACK a prior open_url / needs_action
    clear_action = bool(payload.get("clear_needs_action") or payload.get("ack_action"))
    if "needs_action" in payload and payload.get("needs_action") is None:
        clear_action = True
    if clear_action:
        update["needs_action"] = None
    elif "needs_action" in payload:
        update["needs_action"] = payload["needs_action"]
    res = await db.cpi_devices.update_one(
        {"id": device_id, "user_id": user["id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        # also try by hardware device_id
        res = await db.cpi_devices.update_one(
            {"device_id": device_id, "user_id": user["id"]}, {"$set": update}
        )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    doc = await db.cpi_devices.find_one(
        {"$or": [{"id": device_id}, {"device_id": device_id}], "user_id": user["id"]},
        {"_id": 0},
    )
    pending = (doc or {}).get("needs_action")
    return {"ok": True, "needs_action": pending}


@cpi_router.get("/devices", response_model=List[CPIDevice])
async def list_devices(request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    # Auto-mark devices offline if heartbeat older than 90 seconds
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    await db.cpi_devices.update_many(
        {"user_id": user["id"], "last_heartbeat": {"$lt": cutoff}, "status": {"$in": ["online", "busy"]}},
        {"$set": {"status": "offline"}},
    )
    cursor = db.cpi_devices.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    return [doc async for doc in cursor]


@cpi_router.delete("/devices/{device_id}")
async def delete_device(device_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    await db.cpi_devices.delete_one({"id": device_id, "user_id": user["id"]})
    return {"ok": True}


@cpi_router.post("/devices/{device_id}/action")
async def queue_device_action(device_id: str, request: Request, body: CPIDeviceActionBody):
    """Queue open_url / install_apk for the CPI worker (no USB required if emulator/cloud online)."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    device = await db.cpi_devices.find_one(
        {"$or": [{"id": device_id}, {"device_id": device_id}], "user_id": user["id"]},
        {"_id": 0},
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    atype = (body.type or "").strip().lower()
    if atype not in ("open_url", "install_apk", "install"):
        raise HTTPException(status_code=400, detail="type must be open_url or install_apk")
    action: Dict[str, Any] = {"type": atype, "queued_at": _iso_now()}
    if atype == "open_url":
        url = (body.url or "").strip()
        if not url.startswith("http"):
            raise HTTPException(status_code=400, detail="url must be http(s)")
        action["url"] = url[:1024]
    else:
        apk = (body.apk_url or body.url or "").strip()
        if not apk.startswith("http"):
            raise HTTPException(status_code=400, detail="apk_url required")
        action["apk_url"] = apk[:1024]
        if body.package_name:
            action["package_name"] = body.package_name.strip()[:200]
        # Remember APK in library for next Install
        try:
            now = _iso_now()
            existing = await db.cpi_apk_library.find_one(
                {"user_id": user["id"], "apk_url": action["apk_url"]}, {"_id": 0}
            )
            if existing:
                await db.cpi_apk_library.update_one(
                    {"id": existing["id"]},
                    {"$set": {"last_used_at": now, "use_count": int(existing.get("use_count") or 0) + 1}},
                )
            else:
                await db.cpi_apk_library.insert_one({
                    "id": _new_id(),
                    "user_id": user["id"],
                    "apk_url": action["apk_url"],
                    "label": action["apk_url"].rsplit("/", 1)[-1][:120],
                    "package_name": action.get("package_name") or "",
                    "use_count": 1,
                    "created_at": now,
                    "last_used_at": now,
                })
        except Exception as e:
            logger.debug(f"apk library upsert skipped: {e}")
    await db.cpi_devices.update_one(
        {"id": device["id"]},
        {"$set": {"needs_action": action, "updated_at": _iso_now()}},
    )
    return {"ok": True, "device_id": device["id"], "needs_action": action}


@cpi_router.post("/cloud-phone/provision")
async def provision_cloud_phone(request: Request, body: CPICloudPhoneProvisionBody):
    """Register Krexion Cloud Android ADB endpoint (admin/advanced — white-labeled)."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    ep = (body.adb_endpoint or "").strip()
    if ":" not in ep or not ep.split(":")[-1].isdigit():
        raise HTTPException(status_code=400, detail="Invalid Krexion Cloud Android endpoint")
    device_key = f"cloud:{ep}"
    existing = await db.cpi_devices.find_one(
        {"user_id": user["id"], "device_id": device_key}, {"_id": 0}
    )
    label = (body.label or "Krexion Cloud Android").strip()[:120]
    if existing:
        await db.cpi_devices.update_one(
            {"id": existing["id"]},
            {"$set": {
                "label": label,
                "adb_endpoint": ep,
                "cloud_provider": "krexion",
                "external_id": (body.external_id or "")[:120],
                "notes": (body.notes or "")[:500],
                "device_type": "android_cloud",
                "updated_at": _iso_now(),
            }},
        )
        existing.update({"adb_endpoint": ep, "label": label, "device_type": "android_cloud"})
        return {"ok": True, "device": existing, "message": "Krexion Cloud Android updated — worker will connect automatically"}
    doc = {
        "id": _new_id(),
        "user_id": user["id"],
        "device_id": device_key,
        "device_type": "android_cloud",
        "label": label,
        "model": "Krexion Cloud Android",
        "os_version": "Android",
        "status": "offline",
        "last_heartbeat": None,
        "last_install_at": None,
        "total_installs": 0,
        "successful_installs": 0,
        "needs_action": None,
        "adb_endpoint": ep,
        "cloud_provider": "krexion",
        "external_id": (body.external_id or "")[:120],
        "notes": (body.notes or "")[:500],
        "created_at": _iso_now(),
    }
    await db.cpi_devices.insert_one(doc)
    doc.pop("_id", None)
    # Also queue ensure so worker picks up cloud_adb from device list via command
    await db.cpi_worker_commands.insert_one({
        "id": _new_id(),
        "user_id": user["id"],
        "type": "ensure_android",
        "status": "queued",
        "created_at": _iso_now(),
        "result": {},
        "adb_endpoint": ep,
    })
    return {
        "ok": True,
        "device": doc,
        "message": "Krexion Cloud Android registered. Keep CPI Worker running.",
    }


@cpi_router.get("/cloud-phone/guide")
async def cloud_phone_guide(request: Request):
    """Customer-facing guide — Krexion branding only (no third-party names)."""
    await _require_cpi_user(request)
    return {
        "paths": [
            {
                "id": "krexion_android",
                "title": "Krexion Android Farm (recommended)",
                "steps": [
                    "Click Enable Krexion Android — choose 1–8 phones for a farm",
                    "Keep Krexion CPI Worker running on this PC",
                    "Krexion Android Engine downloads and starts automatically",
                    "Use Browse / Install APK, or bind phones from Browser Profiles",
                ],
            },
            {
                "id": "krexion_cloud",
                "title": "Krexion Cloud Android",
                "steps": [
                    "Add Cloud Android endpoint on the Devices page (host:port)",
                    "Worker connects automatically — no USB phone required",
                ],
            },
        ],
        "note": "Everything runs as Krexion. No third-party emulator apps to install.",
    }


@cpi_router.post("/android/enable")
async def enable_krexion_android(
    request: Request,
    body: CPIAndroidEnableBody = Body(default_factory=CPIAndroidEnableBody),
):
    """One-click: queue silent Krexion Android Engine farm on the worker."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    instances = max(1, min(8, int(getattr(body, "instances", 1) or 1)))
    cmd = {
        "id": _new_id(),
        "user_id": user["id"],
        "type": "ensure_android",
        "status": "queued",
        "created_at": _iso_now(),
        "result": {},
        "instances": instances,
    }
    await db.cpi_worker_commands.insert_one(cmd)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "cpi_android_auto": True,
            "cpi_android_instances": instances,
            "updated_at": _iso_now(),
        }},
    )
    cmd.pop("_id", None)
    msg = (
        "Krexion Android is starting on your PC worker."
        if instances <= 1
        else f"Krexion Android farm ({instances} phones) is starting on your PC worker."
    )
    return {
        "ok": True,
        "command": cmd,
        "instances": instances,
        "message": msg + " This page will show devices when ready.",
    }


@cpi_router.get("/android/status")
async def krexion_android_status(request: Request):
    """Aggregate device + last command result for the UI spinner."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    devices = [
        d async for d in db.cpi_devices.find(
            {"user_id": user["id"], "device_type": {"$regex": "^android_"}},
            {"_id": 0},
        )
    ]
    online = [d for d in devices if d.get("status") in ("online", "busy")]
    last_cmd = await db.cpi_worker_commands.find_one(
        {"user_id": user["id"], "type": "ensure_android"},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    farm_target = int((last_cmd or {}).get("instances") or user.get("cpi_android_instances") or 1)
    return {
        "brand": "Krexion Android",
        "ready": len(online) > 0,
        "online_count": len(online),
        "device_count": len(devices),
        "farm_target": farm_target,
        "farm_ready": len(online) >= farm_target,
        "instances": [
            {
                "id": d.get("id"),
                "label": d.get("label") or d.get("model") or "Krexion Android",
                "status": d.get("status"),
                "device_type": d.get("device_type"),
                "adb_endpoint": d.get("adb_endpoint") or "",
            }
            for d in devices
        ],
        "last_command": last_cmd,
        "message": (
            f"Krexion Android farm ready ({len(online)} online)"
            if online
            else "Waiting for Krexion CPI Worker — click Enable Krexion Android if needed"
        ),
    }


@cpi_router.get("/android/catalog")
async def android_device_catalog(request: Request):
    """Hardware profiles for Krexion Android farm (AVD skins — white-label)."""
    await _require_cpi_user(request)
    return {
        "brand": "Krexion Android",
        "profiles": [
            {"id": "pixel_7", "label": "Krexion Phone 7", "api": 34, "abi": "x86_64", "ram_mb": 2048},
            {"id": "pixel_6a", "label": "Krexion Phone 6a", "api": 34, "abi": "x86_64", "ram_mb": 2048},
            {"id": "galaxy_s23", "label": "Krexion Phone S", "api": 34, "abi": "x86_64", "ram_mb": 3072},
            {"id": "compact", "label": "Krexion Phone Compact", "api": 34, "abi": "x86_64", "ram_mb": 1536},
        ],
        "max_instances": 8,
        "note": "Farm runs silently as Krexion Android on your PC worker.",
    }


@cpi_router.get("/apk-library")
async def list_apk_library(request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    rows = [
        r async for r in db.cpi_apk_library.find(
            {"user_id": user["id"]}, {"_id": 0}
        ).sort("last_used_at", -1).limit(40)
    ]
    return {"items": rows}


@cpi_router.post("/apk-library")
async def upsert_apk_library(request: Request, body: CPIApkLibraryBody):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    url = (body.apk_url or "").strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="apk_url must be http(s)")
    now = _iso_now()
    existing = await db.cpi_apk_library.find_one(
        {"user_id": user["id"], "apk_url": url[:1024]}, {"_id": 0}
    )
    if existing:
        await db.cpi_apk_library.update_one(
            {"id": existing["id"]},
            {"$set": {
                "label": (body.label or existing.get("label") or "")[:120],
                "package_name": (body.package_name or existing.get("package_name") or "")[:200],
                "last_used_at": now,
                "use_count": int(existing.get("use_count") or 0) + 1,
            }},
        )
        existing.update({"last_used_at": now})
        return {"ok": True, "item": existing}
    doc = {
        "id": _new_id(),
        "user_id": user["id"],
        "apk_url": url[:1024],
        "label": (body.label or url.rsplit("/", 1)[-1])[:120],
        "package_name": (body.package_name or "")[:200],
        "use_count": 1,
        "created_at": now,
        "last_used_at": now,
    }
    await db.cpi_apk_library.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "item": doc}


@cpi_router.delete("/apk-library/{item_id}")
async def delete_apk_library_item(item_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    await db.cpi_apk_library.delete_one({"id": item_id, "user_id": user["id"]})
    return {"ok": True}


@cpi_router.get("/worker/commands")
async def list_worker_commands(request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    cur = db.cpi_worker_commands.find(
        {"user_id": user["id"], "status": "queued"},
        {"_id": 0},
    ).sort("created_at", 1).limit(10)
    return {"commands": [c async for c in cur]}


@cpi_router.post("/worker/commands/{command_id}/ack")
async def ack_worker_command(command_id: str, request: Request, body: Dict[str, Any] = Body(default={})):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    ok = bool((body or {}).get("ok", True))
    result = (body or {}).get("result") if isinstance((body or {}).get("result"), dict) else {}
    res = await db.cpi_worker_commands.update_one(
        {"id": command_id, "user_id": user["id"]},
        {"$set": {
            "status": "done" if ok else "error",
            "result": result,
            "acked_at": _iso_now(),
        }},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"ok": True}


# ────────────────────────────────────────────────────────────────────────
# JOBS
# ────────────────────────────────────────────────────────────────────────

_INTERNAL_PROJECTION = {
    "_id": 0, "_proxies": 0, "_user_agents": 0, "_leads": 0,
    "_proxies_used": 0, "_uas_used": 0,
    "_consume_upload_ids": 0, "_auto_consume": 0,
}


@cpi_router.post("/jobs", response_model=CPIJob)
async def create_job(payload: CPIJobIn, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    offer = await db.cpi_offers.find_one({"id": payload.offer_id, "user_id": user["id"]}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    # Resolve resource pools — paste wins, else load from Uploaded Things
    proxies = list(payload.proxies)
    user_agents = list(payload.user_agents)
    consume_upload_ids: List[str] = []

    if not proxies and payload.upload_proxy_id and _load_upload_items:
        items = await _load_upload_items(user["id"], payload.upload_proxy_id, "proxies")
        proxies = items
        if items and payload.auto_consume:
            consume_upload_ids.append(payload.upload_proxy_id)

    if not user_agents and payload.upload_ua_id and _load_upload_items:
        items = await _load_upload_items(user["id"], payload.upload_ua_id, "user_agents")
        user_agents = items
        if items and payload.auto_consume:
            consume_upload_ids.append(payload.upload_ua_id)

    # ── v2.4.0 wire-up (CPI): multi-provider proxy dropdown ──────────
    # If the customer picked a proxy provider in the job UI, resolve
    # one proxy line now and prepend it. Silent no-op when the provider
    # is empty / disabled / errors — legacy paste + upload flow always
    # wins as a fallback.
    #
    # 2026-07 v2.5.3 — For rotating_gateway providers this used to emit
    # ONE identical line so subsequent CPI visits reused the same
    # sticky IP. We now request `target_count` rotated-session lines so
    # each visit gets a fresh IP.
    if getattr(payload, "proxy_provider_id", None):
        try:
            import importlib
            _pp_mod = importlib.import_module("proxy_provider_module")
            _pp_bulk = getattr(_pp_mod, "get_proxy_lines_from_provider", None)
            _pp_get = getattr(_pp_mod, "get_proxy_from_provider", None)
            _added: list = []
            if _pp_bulk:
                try:
                    _cnt = int(getattr(payload, "target_count", 0) or 0) or 10
                except Exception:
                    _cnt = 10
                _pp_res = await _pp_bulk(user["id"], payload.proxy_provider_id, _cnt)
                _added = list(_pp_res.get("lines") or [])
            if not _added and _pp_get:
                _pp_res = await _pp_get(user["id"], payload.proxy_provider_id)
                if _pp_res.get("proxy"):
                    _added = [_pp_res["proxy"]]
            if _added:
                proxies = [*_added, *proxies]
        except Exception:
            pass

    if not proxies:
        raise HTTPException(status_code=400, detail="At least one proxy is required (paste or pick from Uploaded Things)")
    if not user_agents:
        raise HTTPException(status_code=400, detail="At least one user-agent is required (paste or pick from Uploaded Things)")

    job = {
        "id": _new_id(),
        "user_id": user["id"],
        "offer_id": offer["id"],
        "offer_name": offer["name"],
        "target_os": offer.get("target_os", "android"),
        "target_count": payload.target_count,
        "concurrency": payload.concurrency,
        "delay_min_seconds": payload.delay_min_seconds,
        "delay_max_seconds": payload.delay_max_seconds,
        "settle_seconds": payload.settle_seconds,
        "proxies_count": len(proxies),
        "uas_count": len(user_agents),
        "leads_count": len(payload.leads),
        "status": "queued",
        "completed": 0,
        "failed": 0,
        "in_progress": 0,
        "started_at": None,
        "completed_at": None,
        "created_at": _iso_now(),
        # Internal pools (NOT returned via the response_model below)
        "_proxies": proxies,
        "_user_agents": user_agents,
        "_leads": payload.leads,
        "_proxies_used": [],
        "_uas_used": [],
        "_consume_upload_ids": consume_upload_ids,
        "_auto_consume": bool(payload.auto_consume),
        # 2026-02 v2.1.31 — Behavior Simulator settings
        "behavior_sim_enabled": bool(payload.behavior_sim_enabled),
        "behavior_sim_intensity": (payload.behavior_sim_intensity or "medium").lower(),
        "behavior_sim_window_hours": max(1, min(168, int(payload.behavior_sim_window_hours or 24))),
    }
    await db.cpi_jobs.insert_one(job)

    # Pre-create attempt placeholders (queued)
    attempts = [
        {
            "id": _new_id(),
            "job_id": job["id"],
            "offer_id": offer["id"],
            "user_id": user["id"],
            "device_id": None,
            "device_label": None,
            "proxy_used": None,
            "ua_used": None,
            "lead_used": None,
            "click_id": None,
            "status": "queued",
            "failure_reason": None,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "steps": [],
            "created_at": _iso_now(),
        }
        for _ in range(payload.target_count)
    ]
    if attempts:
        await db.cpi_install_attempts.insert_many(attempts)

    job.pop("_id", None)
    # Return without internal pools
    job_safe = {k: v for k, v in job.items() if not k.startswith("_")}
    return job_safe


@cpi_router.get("/jobs", response_model=List[CPIJob])
async def list_jobs(request: Request, status: Optional[str] = None, limit: int = 100):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    q = {"user_id": user["id"]}
    if status:
        q["status"] = status
    cursor = (
        db.cpi_jobs.find(q, _INTERNAL_PROJECTION)
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


@cpi_router.get("/jobs/{job_id}", response_model=CPIJob)
async def get_job(job_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    doc = await db.cpi_jobs.find_one(
        {"id": job_id, "user_id": user["id"]},
        _INTERNAL_PROJECTION,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return doc


@cpi_router.post("/jobs/{job_id}/start")
async def start_job(job_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    res = await db.cpi_jobs.find_one_and_update(
        {"id": job_id, "user_id": user["id"], "status": {"$in": ["queued", "paused"]}},
        {"$set": {"status": "running", "started_at": _iso_now()}},
        return_document=True,
        projection=_INTERNAL_PROJECTION,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Job cannot be started (not queued/paused or not found)")
    return res


@cpi_router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    res = await db.cpi_jobs.find_one_and_update(
        {"id": job_id, "user_id": user["id"], "status": "running"},
        {"$set": {"status": "paused"}},
        return_document=True,
        projection=_INTERNAL_PROJECTION,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Job not running")
    return res


@cpi_router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    res = await db.cpi_jobs.find_one_and_update(
        {"id": job_id, "user_id": user["id"], "status": {"$in": ["running", "paused", "queued"]}},
        {"$set": {"status": "stopped", "completed_at": _iso_now()}},
        return_document=True,
        projection=_INTERNAL_PROJECTION,
    )
    if not res:
        raise HTTPException(status_code=400, detail="Job is not active")
    # Mark queued attempts as cancelled
    await db.cpi_install_attempts.update_many(
        {"job_id": job_id, "status": "queued"},
        {"$set": {"status": "failed", "failure_reason": "job_stopped", "completed_at": _iso_now()}},
    )
    return res


@cpi_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    await db.cpi_jobs.delete_one({"id": job_id, "user_id": user["id"]})
    await db.cpi_install_attempts.delete_many({"job_id": job_id, "user_id": user["id"]})
    return {"ok": True}


@cpi_router.get("/jobs/{job_id}/attempts", response_model=List[CPIInstallAttempt])
async def list_job_attempts(job_id: str, request: Request, limit: int = 200):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    cursor = (
        db.cpi_install_attempts.find(
            {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
        )
        .sort("created_at", 1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


# ────────────────────────────────────────────────────────────────────────
# WORKER PROTOCOL
# ────────────────────────────────────────────────────────────────────────

@cpi_router.get("/behavior-plan/preview")
async def behavior_plan_preview(
    request: Request,
    intensity: str = "medium",
    window_hours: int = 24,
):
    """Preview a behavior simulation plan in the UI before launching a job.
    Lets customers see exactly which post-install actions the worker will
    execute (proves anti-detect value at sale time). Seed is fresh so
    repeated previews look slightly different each time — like real users."""
    await _require_cpi_user(request)
    try:
        plan = build_behavior_plan(
            intensity=intensity,
            window_hours=max(1, min(168, int(window_hours))),
        )
        return {
            "intensity": intensity,
            "window_hours": window_hours,
            "actions_count": len(plan),
            "first_action_offset_seconds": plan[0]["at_offset_seconds"] if plan else 0,
            "last_action_offset_seconds": plan[-1]["at_offset_seconds"] if plan else 0,
            "plan": plan,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@cpi_router.post("/worker/poll")
async def worker_poll(request: Request, payload: Dict[str, Any] = Body(default={})):
    """Worker calls this every few seconds. We claim ONE queued attempt
    that matches the worker's available device types and return the full
    install instructions."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    available_types = payload.get("device_types") or [
        "android_real",
        "android_genymotion",
        "android_emulator",
        "android_ldplayer",
        "android_bluestacks",
        "android_cloud",
        "android_krexion",
        "ios_real",
    ]
    device_id_db = payload.get("device_id")  # optional: lock to this device

    # Find a running job that has queued attempts
    running_jobs_cursor = db.cpi_jobs.find(
        {"user_id": user["id"], "status": "running"},
        {"_id": 0},
    ).sort("created_at", 1)
    running_jobs = [j async for j in running_jobs_cursor]
    for job in running_jobs:
        # Skip if target_os incompatible with worker's available types
        target_os = job.get("target_os", "android")
        if target_os == "android" and not any(t.startswith("android") for t in available_types):
            continue
        if target_os == "ios" and "ios_real" not in available_types:
            continue
        # "both" → prefer android (cheaper) if available
        # Atomic claim: queued → running, attach device
        attempt = await db.cpi_install_attempts.find_one_and_update(
            {"job_id": job["id"], "status": "queued"},
            {"$set": {
                "status": "running",
                "started_at": _iso_now(),
                "device_id": device_id_db,
            }},
            return_document=True,
            projection={"_id": 0},
        )
        if not attempt:
            continue
        # Pick proxy + UA + lead (round-robin via job pool)
        full_job = await db.cpi_jobs.find_one({"id": job["id"]}, {"_id": 0})
        proxies = full_job.get("_proxies") or []
        uas = full_job.get("_user_agents") or []
        leads = full_job.get("_leads") or []
        used_count = full_job.get("completed", 0) + full_job.get("in_progress", 0)
        proxy = proxies[used_count % len(proxies)] if proxies else None
        ua = uas[used_count % len(uas)] if uas else None
        lead = leads[used_count % len(leads)] if leads else None

        await db.cpi_install_attempts.update_one(
            {"id": attempt["id"]},
            {"$set": {"proxy_used": proxy, "ua_used": ua, "lead_used": lead}},
        )
        await db.cpi_jobs.update_one({"id": job["id"]}, {"$inc": {"in_progress": 1}})

        # Pull offer for full instructions
        offer = await db.cpi_offers.find_one({"id": job["offer_id"]}, {"_id": 0}) or {}

        # ── 2026-02 v2.1.31 — Behavior Simulator plan ──
        # When the job opted in, emit a per-attempt plan the worker
        # executes after install. Seeded by the attempt id so re-polls
        # of the same attempt produce the same plan (idempotent for the
        # worker's retry logic).
        behavior_plan: List[Dict[str, Any]] = []
        if full_job.get("behavior_sim_enabled"):
            try:
                # Stable per-attempt seed → reproducible plan
                _seed = abs(hash(attempt["id"])) & 0xFFFFFFFF
                behavior_plan = build_behavior_plan(
                    intensity=full_job.get("behavior_sim_intensity") or "medium",
                    window_hours=int(full_job.get("behavior_sim_window_hours") or 24),
                    seed=_seed,
                )
            except Exception as _bp_err:  # noqa: BLE001
                logger.warning(f"[cpi] behavior_plan generation failed: {_bp_err}")
                behavior_plan = []

        return {
            "has_work": True,
            "attempt": {**attempt, "proxy_used": proxy, "ua_used": ua, "lead_used": lead},
            "job": {k: v for k, v in full_job.items() if not k.startswith("_")},
            "offer": offer,
            # Behavior plan is emitted alongside the attempt so workers
            # don't need a second API roundtrip. Workers that don't
            # recognise this key simply ignore it.
            "behavior_plan": behavior_plan,
        }

    return {"has_work": False}


@cpi_router.post("/worker/result")
async def worker_result(request: Request, payload: Dict[str, Any] = Body(...)):
    """Worker reports completion (success or failure)."""
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)
    attempt_id = payload.get("attempt_id")
    success = bool(payload.get("success"))
    failure_reason = payload.get("failure_reason")
    duration = payload.get("duration_seconds")
    steps = payload.get("steps") or []
    click_id = payload.get("click_id")
    device_id = payload.get("device_id")
    device_label = payload.get("device_label")

    attempt = await db.cpi_install_attempts.find_one(
        {"id": attempt_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    new_status = "conversion_likely" if success else "failed"
    update = {
        "status": new_status,
        "failure_reason": failure_reason,
        "duration_seconds": duration,
        "completed_at": _iso_now(),
        "steps": steps,
        "click_id": click_id,
        "device_id": device_id or attempt.get("device_id"),
        "device_label": device_label,
    }
    await db.cpi_install_attempts.update_one({"id": attempt_id}, {"$set": update})

    inc = {"in_progress": -1}
    if success:
        inc["completed"] = 1
    else:
        inc["failed"] = 1
    update_ops: Dict[str, Any] = {"$inc": inc}

    # Track which proxy / UA actually got used (for selective auto-consume of
    # the originating Uploaded Things batch — same logic RUT uses).
    push_ops: Dict[str, Any] = {}
    if attempt.get("proxy_used"):
        push_ops["_proxies_used"] = attempt["proxy_used"]
    if attempt.get("ua_used"):
        push_ops["_uas_used"] = attempt["ua_used"]
    if push_ops:
        update_ops["$push"] = {k: v for k, v in push_ops.items()}

    job = await db.cpi_jobs.find_one_and_update(
        {"id": attempt["job_id"]},
        update_ops,
        return_document=True,
    )

    # Auto-complete + auto-consume Uploaded Things when all attempts settled
    if job and (job.get("completed", 0) + job.get("failed", 0)) >= job["target_count"] and job.get("in_progress", 0) <= 0:
        await db.cpi_jobs.update_one(
            {"id": job["id"]},
            {"$set": {"status": "completed", "completed_at": _iso_now()}},
        )
        # Auto-consume — selectively prune ONLY actually-used items from the
        # originating Uploaded Things batches. Mirrors RUT/Form Filler behavior.
        if (job.get("_auto_consume") and _consume_uploads
                and job.get("_consume_upload_ids")):
            try:
                await _consume_uploads(
                    user_id=user["id"],
                    upload_ids=job["_consume_upload_ids"],
                    used_proxy_raws=job.get("_proxies_used") or [],
                    used_ua_strings=job.get("_uas_used") or [],
                    pending_leads_path=None,
                )
                logger.info(f"[cpi] auto-consumed uploads for job {job['id']}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[cpi] auto-consume failed for job {job['id']}: {e}")

    # Update offer counters
    if success:
        await db.cpi_offers.update_one(
            {"id": attempt["offer_id"]},
            {"$inc": {"total_installs": 1, "total_conversions": 1}},
        )
        offer = await db.cpi_offers.find_one({"id": attempt["offer_id"]}, {"_id": 0})
        if offer and offer.get("payout"):
            await db.cpi_offers.update_one(
                {"id": attempt["offer_id"]},
                {"$inc": {"total_earnings": float(offer["payout"])}},
            )

    # Update device counters
    if device_id:
        device_inc = {"total_installs": 1}
        if success:
            device_inc["successful_installs"] = 1
        await db.cpi_devices.update_one(
            {"device_id": device_id, "user_id": user["id"]},
            {"$inc": device_inc, "$set": {"last_install_at": _iso_now(), "status": "online"}},
        )

    return {"ok": True, "status": new_status}


# ────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ────────────────────────────────────────────────────────────────────────

@cpi_router.get("/dashboard/stats")
async def dashboard_stats(request: Request, period: str = "today"):
    user = await _require_cpi_user(request)
    db = _get_db_for_user(user)

    if period == "today":
        cutoff = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)).isoformat()
    elif period == "week":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif period == "month":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    else:
        cutoff = "1970-01-01"

    # Aggregate per offer
    pipeline = [
        {"$match": {"user_id": user["id"], "completed_at": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
        }},
    ]
    by_status = {}
    async for row in db.cpi_install_attempts.aggregate(pipeline):
        by_status[row["_id"]] = row["count"]

    completed = by_status.get("conversion_likely", 0)
    failed = by_status.get("failed", 0)
    running = by_status.get("running", 0)
    total = completed + failed + running

    # Earnings: pull from offers' payout × completed-in-period
    earn_pipeline = [
        {"$match": {"user_id": user["id"], "status": "conversion_likely",
                    "completed_at": {"$gte": cutoff}}},
        {"$lookup": {
            "from": "cpi_offers", "localField": "offer_id",
            "foreignField": "id", "as": "offer"
        }},
        {"$unwind": "$offer"},
        {"$group": {
            "_id": None,
            "earnings": {"$sum": "$offer.payout"},
        }},
    ]
    earnings = 0.0
    async for row in db.cpi_install_attempts.aggregate(earn_pipeline):
        earnings = float(row.get("earnings") or 0)

    devices_online = await db.cpi_devices.count_documents(
        {"user_id": user["id"], "status": {"$in": ["online", "busy"]}}
    )
    active_jobs = await db.cpi_jobs.count_documents(
        {"user_id": user["id"], "status": "running"}
    )

    return {
        "period": period,
        "completed_installs": completed,
        "failed_installs": failed,
        "running_installs": running,
        "total_attempts": total,
        "success_rate": round((completed / total) * 100, 1) if total else 0.0,
        "earnings": round(earnings, 2),
        "devices_online": devices_online,
        "active_jobs": active_jobs,
    }
