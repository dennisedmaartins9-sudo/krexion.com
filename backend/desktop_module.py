"""
Krexion — Desktop Companion Endpoints
=====================================
Serves the locally-running PyWebView dashboard (desktop/krexion_dashboard.py)
with the live stats it needs to render its widgets.

These endpoints intentionally only do anything meaningful on the
CUSTOMER's local backend (KREXION_MODE=native). On the cloud edge
(krexion.com) they're still mounted — but they return a clear "not
applicable here" payload so any accidental hit from the wrong place
doesn't leak host stats.

Endpoints:

  GET  /api/desktop/stats        Live snapshot for the dashboard
  POST /api/desktop/run-update   Triggers desktop.updater.apply_update()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("krexion.desktop_module")

# In the NATIVE Windows bundle the `desktop/` package sits at
# {app}/bin/app/desktop and `app/` is on sys.path via python311._pth.
# In the dev container the repo root holds it at /app/desktop. We add
# the repo root once so `from desktop.system_info import ...` succeeds
# in both layouts without an env-var dance.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

desktop_router = APIRouter(prefix="/api/desktop", tags=["desktop"])

# Bound by server.py on startup
_db: Any = None
_get_bridge_stats: Any = None

# ── v2.6.64 — Non-blocking keepalive during RUT / Live Test ──────────
# Problem: single uvicorn worker + Playwright RUT can starve the
# asyncio event loop so /api/desktop/stats times out → dashboard shows
# "Backend offline" even though KrexionBackend is RUNNING.
# Fix: (1) cache last-good stats (2) thread sidecar on :8002 that always
# answers (3) heavy-job busy counter so UI says "busy" not "crashed".
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STATS_CACHE: dict[str, Any] = {}
_STATS_CACHE_TS: float = 0.0
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL_S = 2.5
# Match native heartbeat retries + cloud online window so RUT load
# does not flash yellow 'no recent heartbeat' on the Local PC Dashboard.
CLOUD_LINK_FRESH_SEC = int(os.environ.get("KREXION_CLOUD_LINK_FRESH_SEC", "300") or 300)
_LAST_GOOD_CLOUD_LINK: Optional[dict] = None
_LAST_GOOD_CLOUD_TS: float = 0.0

_HEAVY_BUSY = 0
_HEAVY_BUSY_LOCK = threading.Lock()
_HEAVY_LABEL = ""

_SIDECAR_SERVER: Any = None
_SIDECAR_THREAD: Any = None
_SIDECAR_PORT = int(os.environ.get("KREXION_DESKTOP_HEARTBEAT_PORT", "8002") or "8002")
_PROCESS_STARTED_AT = time.time()


def _bind(*, main_db, get_bridge_stats=None) -> None:
    global _db, _get_bridge_stats
    _db = main_db
    _get_bridge_stats = get_bridge_stats
    if _is_local_mode():
        try:
            start_desktop_heartbeat_sidecar()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Desktop heartbeat sidecar failed to start: {exc}")


def mark_heavy_job_busy(label: str = "heavy job") -> None:
    """Call when RUT / Live Test / Form Filler starts on this PC."""
    global _HEAVY_BUSY, _HEAVY_LABEL
    with _HEAVY_BUSY_LOCK:
        _HEAVY_BUSY += 1
        _HEAVY_LABEL = (label or "heavy job")[:80]


def mark_heavy_job_idle(label: str = "") -> None:
    """Call when a heavy job finishes (success or fail)."""
    global _HEAVY_BUSY, _HEAVY_LABEL
    with _HEAVY_BUSY_LOCK:
        _HEAVY_BUSY = max(0, _HEAVY_BUSY - 1)
        if _HEAVY_BUSY == 0:
            _HEAVY_LABEL = ""
        elif label:
            _HEAVY_LABEL = (label or _HEAVY_LABEL)[:80]


def heavy_job_status() -> dict:
    with _HEAVY_BUSY_LOCK:
        n = int(_HEAVY_BUSY)
        label = _HEAVY_LABEL
    return {"busy": n > 0, "active_count": n, "label": label}


def _cache_stats_payload(payload: dict) -> None:
    global _STATS_CACHE, _STATS_CACHE_TS
    with _STATS_CACHE_LOCK:
        _STATS_CACHE = dict(payload)
        _STATS_CACHE_TS = time.time()


def _cached_stats_payload(*, max_age_s: float = 30.0) -> Optional[dict]:
    with _STATS_CACHE_LOCK:
        if not _STATS_CACHE:
            return None
        age = time.time() - _STATS_CACHE_TS
        if age > max_age_s:
            return None
        out = dict(_STATS_CACHE)
        out["_cache_age_s"] = round(age, 2)
        out["_from_cache"] = True
        return out


def _heartbeat_snapshot() -> dict:
    """Tiny payload the sidecar always returns — never touches Mongo/Playwright."""
    busy = heavy_job_status()
    cached = _cached_stats_payload(max_age_s=120.0) or {}
    return {
        "ok": True,
        "alive": True,
        "mode": (os.environ.get("KREXION_MODE") or "local").lower(),
        "backend_version": _read_version(),
        "uptime_s": int(time.time() - _PROCESS_STARTED_AT),
        "heavy": busy,
        "sidecar": True,
        "sidecar_port": _SIDECAR_PORT,
        "main_port": 8001,
        "cached_stats": bool(cached),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


class _HeartbeatHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return  # silence access log spam

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0]
        if path in ("/ping", "/api/desktop/ping", "/"):
            self._send_json(200, _heartbeat_snapshot())
            return
        if path in ("/stats", "/api/desktop/stats"):
            cached = _cached_stats_payload(max_age_s=120.0)
            if cached is not None:
                cached = dict(cached)
                cached["heavy"] = heavy_job_status()
                cached["sidecar"] = True
                self._send_json(200, cached)
                return
            self._send_json(200, _heartbeat_snapshot())
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def start_desktop_heartbeat_sidecar(port: Optional[int] = None) -> dict:
    """Start (or no-op) the threaded keepalive HTTP server on 127.0.0.1."""
    global _SIDECAR_SERVER, _SIDECAR_THREAD, _SIDECAR_PORT
    if not _is_local_mode():
        return {"started": False, "reason": "cloud mode"}
    if _SIDECAR_SERVER is not None:
        return {"started": True, "already": True, "port": _SIDECAR_PORT}
    p = int(port or _SIDECAR_PORT or 8002)
    _SIDECAR_PORT = p

    def _run() -> None:
        global _SIDECAR_SERVER
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), _HeartbeatHandler)
            srv.daemon_threads = True
            _SIDECAR_SERVER = srv
            logger.info(f"Desktop heartbeat sidecar listening on 127.0.0.1:{p}")
            srv.serve_forever(poll_interval=0.5)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Desktop heartbeat sidecar stopped: {exc}")
            _SIDECAR_SERVER = None

    t = threading.Thread(target=_run, name="krexion-desktop-heartbeat", daemon=True)
    _SIDECAR_THREAD = t
    t.start()
    return {"started": True, "port": p}


# ── Helpers ─────────────────────────────────────────────────────────

def _is_local_mode() -> bool:
    return (os.environ.get("KREXION_MODE") or "local").lower().strip() in {"local", "native"}


def _read_license_summary() -> dict:
    """Best-effort license info read.

    v1.0.13 fix: previously this only read from `_LICENSE_KEY_CACHE`
    which is populated by `license_module.validate_license_key()` —
    a function that ONLY fires when the customer-side proxy validation
    request reaches it. On a fresh native install, before the first
    heartbeat round-trip, the cache is empty and the dashboard shows
    "Inactive" even when a perfectly valid license-key.txt is on disk.
    Now we ALSO fall back to reading the install-time license file at
    `%PROGRAMDATA%\\Krexion\\license-key.txt` so the dashboard says
    "Active" the moment the customer finishes the wizard.
    """
    info = {"active": False, "email": None, "expires_at": None, "key_tail": None}
    # Path 1: runtime in-memory cache (populated after first cloud validation)
    try:
        from license_module import _LICENSE_KEY_CACHE  # type: ignore
        cached = _LICENSE_KEY_CACHE or {}
        if cached:
            info["active"] = bool(cached.get("active", True))
            info["email"] = cached.get("email")
            info["expires_at"] = cached.get("expires_at")
            info["key_tail"] = (cached.get("license_key") or "")[-6:] or None
            if info["active"]:
                return info
    except Exception:  # noqa: BLE001
        pass
    # Path 2: on-disk license file written by the installer's [Code] section
    try:
        candidates = [
            Path(os.environ.get("KREXION_LICENSE_FILE", "")) if os.environ.get("KREXION_LICENSE_FILE") else None,
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Krexion" / "license-key.txt",
            Path("/etc/krexion/license-key.txt"),
        ]
        for p in candidates:
            if not p:
                continue
            try:
                if p.exists():
                    raw = p.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw:
                        info["active"] = True
                        info["key_tail"] = raw[-6:]
                        info["email"] = "—"  # email fetched on next cloud heartbeat
                        return info
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return info


def _read_version() -> str:
    """v1.0.13 fix: original implementation only looked at
    `Path(__file__).parent / 'VERSION'`. In a native install the layout
    is:
        H:\\Krexion\\bin\\app\\backend\\desktop_module.py
        H:\\Krexion\\bin\\app\\backend\\VERSION
    which works IF the VERSION file got copied. But our build-backend.py
    copies the source tree without dotfile filtering, so VERSION should
    be there. The customer is still seeing 0.0.0 in the dashboard which
    means EITHER the file is missing OR something is making the relative
    resolution fail at runtime.
    Now we check multiple known locations and the embedded fallback in
    desktop/__init__.__version__ so the badge is NEVER 0.0.0 on a real
    install."""
    candidates = [
        Path(__file__).parent / "VERSION",                # bin/app/backend/VERSION
        Path(__file__).parent.parent / "backend" / "VERSION",  # bin/app/backend/VERSION (alt path)
        Path(__file__).parent.parent / "VERSION",          # bin/app/VERSION (defensive)
    ]
    for p in candidates:
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except Exception:  # noqa: BLE001
            continue
    # Last-ditch: the desktop package itself carries __version__
    try:
        from desktop import __version__  # type: ignore
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "0.0.0"


async def _db_health() -> dict:
    """Returns {connected, collections, last_error}. Wraps in a 2 s
    timeout so a dead Mongo never hangs the dashboard."""
    if _db is None:
        return {"connected": False, "collections": 0, "last_error": "db not bound"}
    try:
        names = await asyncio.wait_for(_db.list_collection_names(), timeout=2.0)
        return {"connected": True, "collections": len(names), "last_error": None}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "collections": 0, "last_error": str(exc)[:200]}


def _sync_status_candidates() -> list[Path]:
    """Paths where sync_client may have written the heartbeat ack.

    Order: explicit env → ProgramData (native Windows writer default) →
    legacy /tmp path (old dashboard reader default). Must stay aligned
    with sync_client.default_sync_status_path().
    """
    paths: list[Path] = []
    env = (os.environ.get("KREXION_SYNC_STATUS_FILE") or "").strip()
    if env:
        paths.append(Path(env))
    paths.append(
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        / "Krexion"
        / "sync-status.json"
    )
    paths.append(Path("/tmp/krexion-sync-status.json"))
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


async def _cloud_link_status() -> dict:
    """Reads the last heartbeat ack time from the sync_client side. On
    local installs `sync_client.py` updates a tiny status file each
    successful heartbeat — we read that here instead of doing an HTTP
    round-trip every 2 s.

    v2.6.75: also check ProgramData (writer default). Pre-fix the
    dashboard only looked at /tmp/... so Windows native always showed
    yellow 'no recent heartbeat' even when heartbeats succeeded.

    v2.6.76: 5-minute freshness window + last-good cache so a busy RUT
    event loop / VPS blip does not flash yellow on every PC.
    """
    global _LAST_GOOD_CLOUD_LINK, _LAST_GOOD_CLOUD_TS
    best: Optional[dict] = None
    for status_file in _sync_status_candidates():
        try:
            if not status_file.exists():
                continue
            d = json.loads(status_file.read_text(encoding="utf-8-sig"))
            last = d.get("last_heartbeat_at")
            if not last:
                continue
            age_sec = int(time.time() - float(last))
            cand = {"connected": age_sec < CLOUD_LINK_FRESH_SEC, "last_sync_age": age_sec}
            if best is None or age_sec < int(best.get("last_sync_age") or 10**9):
                best = cand
        except Exception:  # noqa: BLE001
            continue
    if best and best.get("connected"):
        _LAST_GOOD_CLOUD_LINK = dict(best)
        _LAST_GOOD_CLOUD_TS = time.time()
        return best
    if best is not None:
        return best
    if _LAST_GOOD_CLOUD_TS and (time.time() - _LAST_GOOD_CLOUD_TS) < CLOUD_LINK_FRESH_SEC:
        age = int(time.time() - _LAST_GOOD_CLOUD_TS)
        return {"connected": True, "last_sync_age": age}
    return {"connected": False, "last_sync_age": None}


def _feature_to_label(feature: str) -> str:
    """Turn a bridge job's `feature` (e.g. 'visual-recorder/start',
    'real-user-traffic/jobs', 'form-filler/jobs', 'adspower/create')
    into a friendly label suitable for the Native dashboard's
    'Active Heavy Jobs' / 'Recent Activity' rows. We don't want raw
    REST-style identifiers on a customer-facing UI."""
    if not feature:
        return "job"
    f = str(feature).strip().lower()
    # Strip leading /api/ in case the cloud auto-route stored the full path
    if f.startswith("/api/"):
        f = f[5:]
    f = f.strip("/")
    # Pretty-print known prefixes — fallback to the prefix itself
    mapping = {
        "visual-recorder": "Visual Recorder",
        "real-user-traffic": "Real User Traffic",
        "rut": "Real User Traffic",
        "form-filler": "Form Filler",
        "proxies": "Proxy Check",
        "adspower": "AdsPower",
        "browser-profile": "Browser Profile",
        "cpi": "CPI",
        "system": "System",
        "sync": "Sync",
        "proxyjet": "ProxyJet",
    }
    head = f.split("/", 1)[0]
    base = mapping.get(head, head.replace("-", " ").title() or "Job")
    # Append sub-action when present (e.g. "Visual Recorder · start")
    tail = f.split("/", 1)[1] if "/" in f else ""
    if tail:
        # Drop any UUID-looking trailing path segments
        parts = [p for p in tail.split("/") if p and not _looks_like_id(p)]
        if parts:
            return f"{base} · {parts[0].replace('-', ' ')}"
    return base


def _looks_like_id(s: str) -> bool:
    """Lightweight UUID/hex/int detector so we don't pollute job labels
    with random ids like '7f3a...'. """
    if not s:
        return False
    if "-" in s and len(s) >= 16:
        return True
    if len(s) >= 8 and all(c in "0123456789abcdefABCDEF" for c in s):
        return True
    if s.isdigit():
        return True
    return False


def _bridge_detail(doc: dict) -> str:
    """Extract a one-line human-readable detail from a bridge_jobs doc.
    Order of preference:
      1. payload.body.url           (RUT / VR / FF target page)
      2. payload.path               (heavy-feature replay path)
      3. error                       (when status=failed)
      4. result.body.session_id     (VR session id, useful on Recent)
    """
    try:
        payload = doc.get("payload") or {}
        body = payload.get("body") if isinstance(payload, dict) else None
        if isinstance(body, dict):
            url = body.get("url") or body.get("offer_url") or body.get("target_url")
            if url:
                return str(url)[:80]
            name = body.get("name") or body.get("label")
            if name:
                return str(name)[:80]
        err = doc.get("error")
        if err:
            return f"⚠ {str(err)[:78]}"
        path = (payload.get("path") if isinstance(payload, dict) else "") or ""
        if path:
            return str(path)[:80]
        result = doc.get("result") or {}
        if isinstance(result, dict):
            rb = result.get("body") or {}
            if isinstance(rb, dict):
                sid = rb.get("session_id") or rb.get("job_id")
                if sid:
                    return f"id={str(sid)[:12]}"
    except Exception:  # noqa: BLE001
        pass
    return ""


async def _active_and_recent_jobs() -> dict:
    """Pulls active + recent heavy jobs from the bridge_jobs collection
    (which is what sync_client.py pulls from).

    v2.1.59 fix: previously the queries used WRONG field names that
    do not exist on bridge_jobs documents at all:
        - projected `kind`     → actual field is `feature`
        - projected `detail`   → no such field; derive from payload
        - filtered `finished_at` and sorted on it → actual is `completed_at`
        - filtered status `completed`/`error` → actual is `done`/`failed`
    Net effect: Recent Activity panel ALWAYS showed "No recent activity"
    even when many jobs were running/completing, and Active Heavy Jobs
    only ever showed bare "job" rows with no description. This restored
    the live activity feed the customer reported missing."""
    out = {"active": [], "recent": [], "throughput": {"jobs_per_hour": 0, "success_rate_pct": 0}}
    if _db is None:
        return out
    try:
        # 1. Active jobs (running or queued on this PC)
        cursor = _db.bridge_jobs.find(
            {"status": {"$in": ["pending", "running"]}},
            projection={
                "_id": 0,
                "feature": 1,
                "status": 1,
                "started_at": 1,
                "created_at": 1,
                "payload": 1,
                "error": 1,
                "result": 1,
            },
            sort=[("created_at", -1)],
            limit=10,
        )
        now = datetime.now(timezone.utc)
        async for doc in cursor:
            start_iso = doc.get("started_at") or doc.get("created_at")
            ago = _humanise_age(start_iso, now)
            out["active"].append({
                "kind": _feature_to_label(doc.get("feature") or ""),
                "status": doc.get("status") or "running",
                "detail": _bridge_detail(doc)[:80],
                "started_ago": ago,
            })

        # 1b. 2026-06 — ALSO surface in-flight RUT / Form-Filler jobs
        # that live in the per-feature collections. The bridge_job
        # itself flips to "done" the moment the desktop replays the
        # POST response (a few seconds), but the real RUT visit loop
        # continues running asynchronously for the next 5-30 minutes.
        # Customer reported "active heavy job mein kuch nazar ni a
        # raha ho ta jab job chal rahi hoti" — exactly because the
        # dashboard was only inspecting bridge_jobs. Add the live
        # RUT + FF + VR collections so the Active Heavy Jobs card
        # reflects ground truth for the duration of the visit loop.
        try:
            rut_cursor = _db.real_user_traffic_jobs.find(
                {"status": {"$in": ["prepping", "running", "queued"]}},
                projection={
                    "_id": 0, "job_id": 1, "status": 1, "target_url": 1,
                    "total": 1, "processed": 1, "succeeded": 1, "failed": 1,
                    "created_at": 1, "prep_step": 1,
                },
                sort=[("created_at", -1)],
                limit=5,
            )
            async for jd in rut_cursor:
                processed = int(jd.get("processed") or 0)
                total = int(jd.get("total") or 0)
                succ = int(jd.get("succeeded") or 0)
                detail = (
                    f"{processed}/{total} visits · {succ} ok"
                    if total
                    else (jd.get("prep_step") or "preparing…")[:60]
                )
                out["active"].append({
                    "kind": "Real User Traffic",
                    "status": jd.get("status") or "running",
                    "detail": detail[:80],
                    "started_ago": _humanise_age(jd.get("created_at"), now),
                })
        except Exception:  # noqa: BLE001
            pass
        try:
            ff_cursor = _db.form_filler_jobs.find(
                {"status": {"$in": ["prepping", "running", "queued"]}},
                projection={
                    "_id": 0, "job_id": 1, "status": 1, "total": 1,
                    "processed": 1, "succeeded": 1, "created_at": 1,
                },
                sort=[("created_at", -1)],
                limit=5,
            )
            async for jd in ff_cursor:
                detail = (
                    f"{int(jd.get('processed') or 0)}/{int(jd.get('total') or 0)} rows"
                )
                out["active"].append({
                    "kind": "Form Filler",
                    "status": jd.get("status") or "running",
                    "detail": detail[:80],
                    "started_ago": _humanise_age(jd.get("created_at"), now),
                })
        except Exception:  # noqa: BLE001
            pass

        # 2. Recent completed/failed (last 8)
        cursor = _db.bridge_jobs.find(
            {"status": {"$in": ["done", "failed"]}},
            projection={
                "_id": 0,
                "feature": 1,
                "status": 1,
                "completed_at": 1,
                "payload": 1,
                "error": 1,
                "result": 1,
            },
            sort=[("completed_at", -1)],
            limit=8,
        )
        async for doc in cursor:
            finished = doc.get("completed_at")
            # Map internal "done" → user-facing "completed" so the green
            # badge css class (.job-status-completed) lights up.
            disp_status = "completed" if doc.get("status") == "done" else (doc.get("status") or "completed")
            out["recent"].append({
                "kind": _feature_to_label(doc.get("feature") or ""),
                "status": disp_status,
                "detail": _bridge_detail(doc)[:80],
                "started_ago": _humanise_age(finished, now),
            })

        # 3. Throughput — last hour
        try:
            from datetime import timedelta
            since = now - timedelta(hours=1)
            since_iso = since.isoformat()
            total = await _db.bridge_jobs.count_documents({"completed_at": {"$gte": since_iso}})
            ok = await _db.bridge_jobs.count_documents({
                "completed_at": {"$gte": since_iso}, "status": "done",
            })
            out["throughput"] = {
                "jobs_per_hour": total,
                "success_rate_pct": (100.0 * ok / total) if total else 0.0,
            }
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"job stats query failed: {exc}")
    return out


def _humanise_age(iso_value, now) -> str:
    if not iso_value:
        return ""
    try:
        if isinstance(iso_value, str):
            ts = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        else:
            ts = iso_value
        delta = (now - ts).total_seconds()
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return f"{int(delta // 86400)}d ago"
    except Exception:  # noqa: BLE001
        return ""


async def _dependency_health() -> dict:
    """v2.1.59 — Single-shot check of every external dependency a Krexion
    feature needs so the dashboard can show GREEN/YELLOW/RED for each
    one and the customer knows which feature is usable.

    Currently covers:
        chromium      Playwright browser engine (RUT, Visual Recorder,
                      Browser Profiles, Form Filler all need this)
        playwright    The Python package itself
        adb           Android Debug Bridge (CPI module — Android only)

    Each entry: {status: "ok"|"installing"|"missing"|"error", message: str}
    `status="ok"` means the feature that needs it WILL work right now.
    Anything else is a clear, actionable hint the UI can show.
    """
    out: dict = {}

    # ── Playwright package import ───────────────────────────────────
    try:
        import importlib
        importlib.import_module("playwright.async_api")
        out["playwright"] = {"status": "ok", "message": "package importable"}
    except Exception as exc:  # noqa: BLE001
        out["playwright"] = {
            "status": "missing",
            "message": f"playwright package not importable: {exc}",
        }

    # ── Playwright Chromium binary (the file Playwright actually runs) ─
    try:
        from real_user_traffic import get_engine_status  # type: ignore
        engine = get_engine_status()
        s = (engine or {}).get("status") or "error"
        # 2026-06: `get_engine_status()` historically returns "ready"
        # when the binary is on disk, but the dashboard UI only knows
        # the four canonical states {ok, installing, missing, error}.
        # An unmapped "ready" silently fell through to the red "error"
        # badge — UI showed "Chromium browser · error" with a green
        # "Chromium ready · using full chromium (--headless=new)"
        # message right below it, which was confusing and made
        # customers think the engine was broken when it wasn't.
        # Normalise "ready" → "ok" here.
        if s == "ready":
            s = "ok"
        out["chromium"] = {
            "status": s,
            "message": (engine or {}).get("message") or "",
            "expected_revision": (engine or {}).get("expected_revision"),
        }
    except Exception as exc:  # noqa: BLE001
        out["chromium"] = {
            "status": "error",
            "message": f"engine status helper failed: {str(exc)[:120]}",
        }

    # ── adb (Android Debug Bridge) — needed for the CPI Android flow ─
    # Lazy: don't crash this whole endpoint if shutil is funky on the
    # native install (we've seen weird PATH situations on Windows).
    try:
        import shutil as _sh
        adb_path = _sh.which("adb")
        if adb_path:
            out["adb"] = {
                "status": "ok",
                "message": f"adb on PATH: {adb_path}",
            }
        else:
            out["adb"] = {
                "status": "missing",
                "message": (
                    "adb.exe not on PATH. Required for CPI Android flow. "
                    "Install Android Platform-Tools or use the Krexion "
                    "CPI worker which bundles it."
                ),
            }
    except Exception as exc:  # noqa: BLE001
        out["adb"] = {"status": "error", "message": str(exc)[:120]}

    return out


# ── Routes ──────────────────────────────────────────────────────────

@desktop_router.get("/ping")
async def desktop_ping():
    """Ultra-light liveness for the Local PC Dashboard. Never hits Mongo
    or Playwright — safe to call every 2s even during RUT."""
    return _heartbeat_snapshot()


@desktop_router.get("/stats")
async def desktop_stats():
    """One-shot snapshot the PyWebView dashboard polls every 2s. We
    keep it heterogeneous (system + license + jobs + cloud-link +
    dependency-health) so the dashboard makes ONE request, not five.

    v2.6.64 — Prefer a fresh cache (<=2.5s) so concurrent RUT workers
    don't pile Mongo/psutil work onto the event loop. Sync get_specs()
    runs in a thread pool. Soft timeouts on DB sections.
    """
    # Serve very-fresh cache immediately (RUT-friendly).
    cached = _cached_stats_payload(max_age_s=_STATS_CACHE_TTL_S)
    if cached is not None:
        cached["heavy"] = heavy_job_status()
        return cached

    loop = asyncio.get_running_loop()
    try:
        system = await loop.run_in_executor(None, _safe_get_specs)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"system_info unavailable on this host: {exc}")
        system = {
            "ram_gb": 0, "cpu_cores": 0, "ram_used_gb": 0, "ram_used_pct": 0,
            "cpu_pct": 0, "tier": "unknown", "max_concurrent_heavy_jobs": 2,
            "detected_by": "fallback",
        }

    try:
        db_health = await asyncio.wait_for(_db_health(), timeout=2.5)
    except Exception:  # noqa: BLE001
        db_health = {"connected": False, "collections": 0, "last_error": "timeout"}

    try:
        cloud_link = await asyncio.wait_for(_cloud_link_status(), timeout=1.5)
    except Exception:  # noqa: BLE001
        if _LAST_GOOD_CLOUD_TS and (time.time() - _LAST_GOOD_CLOUD_TS) < CLOUD_LINK_FRESH_SEC:
            cloud_link = {
                "connected": True,
                "last_sync_age": int(time.time() - _LAST_GOOD_CLOUD_TS),
            }
        else:
            cloud_link = {"connected": False, "last_sync_age": None}

    if _is_local_mode():
        try:
            jobs = await asyncio.wait_for(_active_and_recent_jobs(), timeout=2.5)
        except Exception:  # noqa: BLE001
            jobs = {
                "active": [], "recent": [],
                "throughput": {"jobs_per_hour": 0, "success_rate_pct": 0},
            }
        try:
            deps = await asyncio.wait_for(_dependency_health(), timeout=2.0)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"dependency health check failed: {exc}")
            deps = {}
    else:
        jobs = {
            "active": [], "recent": [],
            "throughput": {"jobs_per_hour": 0, "success_rate_pct": 0},
        }
        deps = {}

    try:
        license_info = await loop.run_in_executor(None, _read_license_summary)
    except Exception:  # noqa: BLE001
        license_info = {"active": False, "email": None, "expires_at": None, "key_tail": None}

    payload = {
        "ok": True,
        "mode": (os.environ.get("KREXION_MODE") or "local").lower(),
        "backend_version": _read_version(),
        "system": system,
        "database": db_health,
        "cloud": cloud_link,
        "license": license_info,
        "jobs": jobs,
        "dependencies": deps,
        "heavy": heavy_job_status(),
        "heartbeat_port": _SIDECAR_PORT if _is_local_mode() else None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _cache_stats_payload(payload)
    return payload


def _safe_get_specs() -> dict:
    try:
        from desktop.system_info import get_specs  # type: ignore
        return get_specs()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"system_info unavailable: {exc}")
        return {
            "ram_gb": 0, "cpu_cores": 0, "ram_used_gb": 0, "ram_used_pct": 0,
            "cpu_pct": 0, "tier": "unknown", "max_concurrent_heavy_jobs": 2,
            "detected_by": "fallback",
        }


@desktop_router.post("/run-update")
async def desktop_run_update(request: Request):
    """Triggered when the customer clicks the "Update Now" banner in
    the dashboard. Calls `desktop.updater.apply_update()` which:
      1. Downloads the latest Krexion-Setup.exe to %TEMP%
      2. Launches it with /VERYSILENT /SUPPRESSMSGBOXES
      3. Installer stops services, swaps files, restarts services
    """
    if not _is_local_mode():
        # Refuse on cloud edge — VPS doesn't run an installer
        raise HTTPException(400, "Updates only run on the customer's local install.")

    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        pass
    target_version = (body or {}).get("target_version")

    try:
        from desktop.updater import apply_update  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Updater module unavailable: {exc}")

    # apply_update is sync (subprocess + requests) — run in thread pool
    # so we don't block the asyncio loop while downloading 400 MB.
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, apply_update, target_version)
    return result


@desktop_router.get("/specs")
async def desktop_specs():
    """Tiny read-only endpoint a future Settings tab could call. Same
    payload as the `system` block in /stats — exposed separately so the
    settings page can display the install-time specs without polling
    the full live snapshot.

    On the cloud edge (where the `desktop` package isn't mounted into
    the backend Docker container), we degrade gracefully and return a
    fallback payload rather than 500 — the cloud frontend never calls
    this endpoint anyway, but better to be quiet than noisy.
    """
    try:
        from desktop.system_info import get_specs  # type: ignore
        return get_specs()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"system_info unavailable on this host: {exc}")
        return {
            "ram_gb": 0,
            "cpu_cores": 0,
            "ram_used_gb": 0,
            "ram_used_pct": 0,
            "cpu_pct": 0,
            "tier": "unknown",
            "max_concurrent_heavy_jobs": 2,
            "detected_by": "fallback",
            "note": "desktop package not available on this host (cloud edge)",
        }
