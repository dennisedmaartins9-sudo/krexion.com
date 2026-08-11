"""
Krexion - Local Sync Client (runs only on customer's PC, KREXION_MODE=local)
============================================================================
Background daemon that talks to the cloud edge at KREXION_CLOUD_URL
(default https://krexion.com) every SYNC_INTERVAL seconds:

  1. Heartbeat        - "I'm online" + RAM/CPU info for load tuning
  2. Push links       - cloud's /r/xxx redirects know about our links
  3. Pull clicks      - drain clicks the cloud captured while we were offline
  4. Pull bridge jobs - heavy features (proxy check, RUT, form filler)
                        queued on the cloud get executed locally

Auth: customer's `LICENSE_KEY` env var, sent in X-Krexion-License header.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CLOUD_URL = (os.environ.get("KREXION_CLOUD_URL") or "https://krexion.com").rstrip("/")


def default_sync_status_path() -> Path:
    """Canonical path for the local→cloud heartbeat ack file.

    Must stay aligned with desktop_module._cloud_link_status() — if the
    writer and dashboard reader disagree, the Local PC Dashboard always
    shows yellow 'no recent heartbeat' even when heartbeats succeed.
    """
    env = (os.environ.get("KREXION_SYNC_STATUS_FILE") or "").strip()
    if env:
        return Path(env)
    return (
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        / "Krexion"
        / "sync-status.json"
    )


def _resolve_license_key() -> str:
    """v1.0.14: read LICENSE_KEY from env (highest priority), or from
    LICENSE_KEY_FILE (used by the installer's NSSM service env which
    sets LICENSE_KEY_FILE=%PROGRAMDATA%\\Krexion\\license-key.txt). The
    pre-1.0.14 sync_client only checked the LICENSE_KEY env var which
    was NEVER set by the installer, so the bridge worker had no key
    to authenticate with the cloud and silently exited every cycle.
    The fallback below is the actual reason customers' krexion.com
    link pill kept reading 'no recent heartbeat' even though the
    desktop install was running fine."""
    key = (os.environ.get("LICENSE_KEY") or "").strip()
    if key:
        return key
    key_file = os.environ.get("LICENSE_KEY_FILE")
    if key_file:
        try:
            from pathlib import Path
            p = Path(key_file)
            if p.exists():
                k = p.read_text(encoding="utf-8", errors="ignore").strip()
                if k:
                    return k
        except Exception:  # noqa: BLE001
            pass
    # Last resort: well-known native install location
    try:
        from pathlib import Path
        candidate = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Krexion" / "license-key.txt"
        if candidate.exists():
            k = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if k:
                return k
    except Exception:  # noqa: BLE001
        pass
    return ""


LICENSE_KEY = _resolve_license_key()
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL_SEC", "30") or 30)
KREXION_MODE = (os.environ.get("KREXION_MODE") or "local").lower().strip()
# Dedicated heartbeat — independent of link-sync and RUT so 100 busy
# PCs still stay "online" on krexion.com. 8s used to fail under VPS
# load and the dashboard showed yellow 'no recent heartbeat'.
HEARTBEAT_INTERVAL = int(os.environ.get("SYNC_HEARTBEAT_SEC", "20") or 20)
HEARTBEAT_TIMEOUT = float(os.environ.get("SYNC_HEARTBEAT_TIMEOUT_SEC", "20") or 20)
HEARTBEAT_RETRIES = int(os.environ.get("SYNC_HEARTBEAT_RETRIES", "3") or 3)
# Bridge-job pulling cycles faster than the main sync loop so heavy
# features feel responsive (user clicks proxy-check on krexion.com cloud
# UI → max ~5s before local PC picks it up). Idle PCs back off so 100
# users don't hammer /jobs/pull every 5s for empty queues.
JOB_PULL_INTERVAL = int(os.environ.get("BRIDGE_JOB_PULL_SEC", "5") or 5)
JOB_PULL_IDLE_SEC = int(os.environ.get("BRIDGE_JOB_PULL_IDLE_SEC", "12") or 12)
LOCAL_API_BASE = (os.environ.get("LOCAL_API_BASE") or "http://localhost:8001").rstrip("/")

_running = False
_HB_FAILS = 0
_HB_OKS = 0


def _current_license_key() -> str:
    """v1.0.15: re-resolve the license on every request so a license
    activated AFTER the daemon started (or replaced via auto-takeover)
    is picked up automatically. Previously LICENSE_KEY was a module-
    level constant captured ONCE at import, so the daemon would
    heartbeat with an empty header forever and the cloud would
    return 401 every time -> dashboard's krexion.com link pill
    stuck on 'no recent heartbeat' until the customer restarted
    the backend service."""
    global LICENSE_KEY
    if not LICENSE_KEY:
        LICENSE_KEY = _resolve_license_key()
    return LICENSE_KEY


def _headers() -> dict:
    return {
        "X-Krexion-License": _current_license_key(),
        "Content-Type": "application/json",
        "User-Agent": "Krexion-Local/2.1.4",
    }


def _now_iso_local() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _hardware_info() -> dict:
    """Detect customer PC hardware so the cloud knows how much load it
    can route to this machine. RAM/cores -> recommended concurrency."""
    info: dict = {}
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        info["ram_gb"] = round(vm.total / (1024 ** 3), 1)
        info["cpu_cores"] = psutil.cpu_count(logical=True) or 1
    except Exception:
        pass
    # Recommended concurrency:
    #   - At minimum 8
    #   - About 16 parallel per 8GB of RAM
    #   - Capped at 256 (anything more saturates an average residential link)
    ram_gb = info.get("ram_gb", 8) or 8
    info["recommended_concurrency"] = max(8, min(256, int(ram_gb * 16 / 8)))
    return info


def _write_sync_status_file() -> None:
    try:
        status_path = default_sync_status_path()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps({
                "last_heartbeat_at": time.time(),
                "cloud_url": CLOUD_URL,
                "version": "2.1.4",
            }),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def _heartbeat_post_sync() -> tuple[int, str, Any]:
    """Blocking POST so RUT/Playwright cannot starve cloud keepalive.

    Runs in a worker thread via asyncio.to_thread.
    """
    key = _current_license_key()
    if not key:
        return 0, "no-license", None
    body = {
        "hostname": socket.gethostname(),
        "version": "2.1.4",
        "platform": "native-windows" if sys.platform.startswith("win") else "docker",
    }
    body.update(_hardware_info())
    with httpx.Client(timeout=HEARTBEAT_TIMEOUT) as client:
        r = client.post(
            f"{CLOUD_URL}/api/sync/heartbeat",
            json=body,
            headers=_headers(),
        )
        data = None
        try:
            data = r.json() if r.content else {}
        except Exception:  # noqa: BLE001
            data = None
        return int(r.status_code), (r.text or "")[:200], data


async def _heartbeat() -> None:
    """v2.6.76: retries + thread offload + independent loop.

    v1.0.16 logged failures; this revision also survives VPS blips and
    a busy local event loop (100 concurrent customer PCs + RUT).
    """
    global _HB_FAILS, _HB_OKS
    key = _current_license_key()
    if not key:
        if _HB_FAILS < 3:
            logger.info(
                "[sync] heartbeat skipped: no license key found in env "
                "LICENSE_KEY/LICENSE_KEY_FILE/PROGRAMDATA. Wizard may "
                "not have written license-key.txt yet - will retry."
            )
        _HB_FAILS += 1
        return

    last_err = ""
    for attempt in range(max(1, HEARTBEAT_RETRIES)):
        try:
            status, text, hb_resp = await asyncio.to_thread(_heartbeat_post_sync)
            if status == 0:
                _HB_FAILS += 1
                return
            if status >= 400:
                last_err = f"HTTP {status}: {text}"
                if attempt + 1 < HEARTBEAT_RETRIES:
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                if _HB_FAILS < 3:
                    logger.info(
                        f"[sync] heartbeat returned {last_err}. License key tail "
                        f"...{key[-6:]}, cloud={CLOUD_URL}"
                    )
                _HB_FAILS += 1
                return

            if _HB_OKS == 0:
                logger.info(
                    f"[sync] heartbeat OK to {CLOUD_URL} - PC is now online "
                    f"in the cloud, heavy jobs will route here."
                )
            _HB_OKS += 1
            _HB_FAILS = 0
            _write_sync_status_file()
            try:
                cloud_user = (hb_resp or {}).get("user") or {}
                cloud_lic = (hb_resp or {}).get("license") or {}
                if cloud_user.get("email") and cloud_user.get("id"):
                    try:
                        from server import db as _local_db  # type: ignore
                        await _local_db.users.update_one(
                            {"email": cloud_user["email"]},
                            {"$set": {
                                "id": cloud_user["id"],
                                "email": cloud_user["email"],
                                "status": "active",
                                "bridge_synced": True,
                            }, "$setOnInsert": {
                                "name": cloud_user["email"].split("@")[0],
                                "is_admin": False,
                                "features": {f: True for f in (
                                    "real_user_traffic", "form_filler",
                                    "visual_recorder", "proxies", "links",
                                    "clicks", "import_traffic",
                                    "email_checker", "separate_data",
                                    "ua_generator", "ua_checker",
                                    "real_traffic", "import_data",
                                    "adspower", "uploaded_things",
                                    "profile_builder", "traffic_sources",
                                )},
                                "created_at": _now_iso_local(),
                            }},
                            upsert=True,
                        )
                        if cloud_lic.get("license_key"):
                            await _local_db.licenses.update_one(
                                {"license_key": cloud_lic["license_key"]},
                                {"$set": {
                                    "license_key": cloud_lic["license_key"],
                                    "user_id": cloud_user["id"],
                                    "email": cloud_user["email"],
                                    "status": cloud_lic.get("status", "active"),
                                }},
                                upsert=True,
                            )
                    except Exception as _mirror_err:  # noqa: BLE001
                        logger.debug(f"[sync] local mirror skipped: {_mirror_err}")
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if attempt + 1 < HEARTBEAT_RETRIES:
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            if _HB_FAILS < 3:
                logger.info(
                    f"[sync] heartbeat exception: {last_err}. "
                    f"Will retry every {HEARTBEAT_INTERVAL}s."
                )
            _HB_FAILS += 1
            return


async def _heartbeat_loop() -> None:
    """Keepalive only — never waits on link push / job execution."""
    global _running
    while _running:
        try:
            await _heartbeat()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[sync] heartbeat loop error: {e}")
        await asyncio.sleep(max(8, HEARTBEAT_INTERVAL))


async def _push_links(user_db: Any) -> int:
    try:
        links = await user_db.links.find(
            {"status": "active"}, {"_id": 0}
        ).limit(2000).to_list(2000)
        if not links:
            return 0
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{CLOUD_URL}/api/sync/links",
                json={"links": links},
                headers=_headers(),
            )
            if r.status_code == 200:
                return int(r.json().get("upserted", 0))
            logger.warning(f"[sync] push_links {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[sync] push_links error: {e}")
    return 0


async def _pull_clicks(user_db: Any) -> int:
    try:
        meta = await user_db.cloud_sync_meta.find_one({"key": "last_click_pull"}) or {}
        since = meta.get("ts", "")
        total = 0
        for _ in range(10):  # max 10 batches per cycle = 5000 clicks
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"{CLOUD_URL}/api/sync/clicks/pull",
                    params={"since": since, "limit": 500},
                    headers=_headers(),
                )
                if r.status_code != 200:
                    logger.warning(f"[sync] pull {r.status_code}: {r.text[:200]}")
                    break
                data = r.json()
                clicks = data.get("clicks") or []
                if not clicks:
                    break
                ack_ids = []
                for c in clicks:
                    cid = c.get("id")
                    if not cid:
                        continue
                    try:
                        await user_db.clicks.update_one(
                            {"id": cid},
                            {"$setOnInsert": c},
                            upsert=True,
                        )
                        ack_ids.append(cid)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"[sync] insert click {cid}: {e}")
                last_ts = clicks[-1].get("created_at") or clicks[-1].get("timestamp") or since
                await user_db.cloud_sync_meta.update_one(
                    {"key": "last_click_pull"},
                    {"$set": {"key": "last_click_pull", "ts": last_ts}},
                    upsert=True,
                )
                if ack_ids:
                    try:
                        await client.post(
                            f"{CLOUD_URL}/api/sync/clicks/ack",
                            json={"click_ids": ack_ids},
                            headers=_headers(),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                total += len(clicks)
                since = last_ts
                if not data.get("has_more"):
                    break
        return total
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[sync] pull_clicks error: {e}")
    return 0


# ─────────────────────────────────────────────────────────────────────
# BRIDGE: pull pending heavy-feature jobs from the cloud and execute
# them locally against this install's own backend.
# ─────────────────────────────────────────────────────────────────────
async def _execute_job_locally(job: dict, jwt_token: str | None = None) -> dict:
    """Run the job's feature against the local backend. Returns a result
    dict ready to POST back to the cloud."""
    feature = job.get("feature") or ""
    payload = job.get("payload") or {}

    # Map feature name to local backend route
    # Format: METHOD /api/<route>
    #
    # 2026-05: corrected RUT/Form-Filler routes. The old "rut/start" and
    # "form-filler/start" paths pointed to endpoints that don't exist
    # in any release of the backend (legacy planning artefact). The
    # ACTUAL routes have always been:
    #   POST /api/real-user-traffic/jobs   (multipart form)
    #   POST /api/form-filler/jobs         (multipart form)
    # which is why RUT bridge jobs previously failed with 404 every time
    # the cloud edge enqueued one. Old desktop installs running the
    # pre-2026-05 sync_client will still 404, but self-update rolls
    # them forward automatically.
    feature_routes = {
        "proxies/bulk-test": ("POST", "/api/proxies/bulk-test"),
        "proxies/test-single": ("POST", "/api/proxies/test-single"),
        "rut/start": ("POST", "/api/real-user-traffic/jobs"),
        "rut/status": ("GET", "/api/real-user-traffic/jobs"),
        "form-filler/start": ("POST", "/api/form-filler/jobs"),
        "form-filler/status": ("GET", "/api/form-filler/jobs"),
        # Self-update — cloud UpdateBanner click ends up here so customer
        # never has to open localhost.
        "system/self-update": ("POST", "/api/system/install-update"),
        # AdsPower bulk profile creator (UI on cloud, executes locally)
        "adspower/create": ("POST", "__adspower_create__"),
        # AdsPower API connection test (UI on cloud, executes locally)
        "adspower/test": ("POST", "__adspower_test__"),
        # AdsPower bulk profile delete (UI on cloud, executes locally)
        "adspower/delete": ("POST", "__adspower_delete__"),
        # 2026-06-11: Browser Profiles (AdsPower/GoLogin-style)
        # — opens a HEADED Chromium for manual browsing with full
        # Krexion anti-detect stack. Executes locally via
        # browser_profile_launcher.launch_profile_session().
        "browser-profile/launch": ("POST", "__browser_profile_launch__"),
        "browser-profile/stop":   ("POST", "__browser_profile_stop__"),
    }
    if feature not in feature_routes:
        # v1.0.14 NEW: generic passthrough for the require_local_mode
        # auto-route. server.py now enqueues any heavy-feature endpoint
        # with payload={"method": ..., "path": ..., "body": ..., "query": ...}.
        # The desktop bridge worker replays it against the LOCAL backend
        # (127.0.0.1:8001) which executes it (IS_CLOUD=false there) and
        # we ship the response body back to the cloud where the original
        # frontend request is waiting on it.
        if isinstance(payload, dict) and payload.get("method") and payload.get("path"):
            generic_method = str(payload["method"]).upper()
            generic_path = str(payload["path"])
            generic_body = payload.get("body") or {}
            generic_query = payload.get("query") or {}
            # v2.1.4: faithful raw-body + content-type + auth replay so
            # multipart/form-data heavy jobs (RUT, Form Filler) actually
            # execute on the desktop backend. Previously sync_client only
            # POSTed the parsed JSON body, which was always {} for
            # multipart requests, so the local backend 422'd every time.
            import base64 as _b64
            raw_b64 = payload.get("raw_body_b64") or ""
            content_type = (payload.get("content_type") or "").strip()
            auth_hdr = (payload.get("authorization") or "").strip()
            raw_body_bytes = b""
            if raw_b64:
                try:
                    raw_body_bytes = _b64.b64decode(raw_b64)
                except Exception:
                    raw_body_bytes = b""
            try:
                local_base = "http://127.0.0.1:8001"
                # Bridge worker is part of THIS process; we cannot make
                # a request to ourselves through httpx without an async
                # client + we want the X-Krexion-Bridge-Job header set
                # so require_local_mode lets the call through.
                headers = {
                    "X-Krexion-Bridge-Job": "1",
                }
                # v2.1.4 / v2.1: cloud forwards its own JWT but the
                # local backend has a DIFFERENT SECRET_KEY (each
                # FastAPI instance auto-generates its own on boot),
                # so the cloud JWT fails signature verification on the
                # local side → "Invalid token" on every heavy job.
                # FIX: mint a LOCAL JWT signed with the LOCAL backend's
                # secret. We resolve the user from the heartbeat /
                # license validate flow already running in-process and
                # call into the local server.create_access_token().
                local_jwt = None
                try:
                    # Import lazily to avoid circular imports at boot
                    from server import create_access_token, db as _local_db, SECRET_KEY as _SK  # type: ignore  # noqa
                    # Find the user that owns this license on the LOCAL
                    # backend's DB. The license / user pair is mirrored
                    # by the sync_loop on first license-validate.
                    lic_doc = await _local_db.licenses.find_one(
                        {"license_key": LICENSE_KEY}, {"_id": 0, "user_id": 1, "email": 1}
                    )
                    if lic_doc:
                        # v2.1 IMPORTANT: the local DB is empty on a
                        # fresh install — only the heartbeat / license
                        # rows exist. The cloud user record does NOT
                        # exist locally yet, so create_access_token
                        # would succeed but get_current_user would
                        # 401 because users.find_one({email}) returns
                        # None. We auto-upsert the user here from the
                        # license email so JWT verification on the
                        # very next replay attempt succeeds.
                        lic_email = lic_doc.get("email")
                        if not lic_email:
                            # Try cloud user-id lookup
                            uid = lic_doc.get("user_id")
                            if uid:
                                u = await _local_db.users.find_one(
                                    {"id": uid}, {"_id": 0, "email": 1}
                                )
                                lic_email = (u or {}).get("email")
                        if lic_email:
                            existing = await _local_db.users.find_one(
                                {"email": lic_email}, {"_id": 0, "id": 1}
                            )
                            if not existing:
                                import uuid as _uuid
                                from datetime import datetime as _dt, timezone as _tz
                                user_id_new = lic_doc.get("user_id") or _uuid.uuid4().hex
                                await _local_db.users.insert_one({
                                    "id": user_id_new,
                                    "email": lic_email,
                                    "name": lic_email.split("@")[0],
                                    "is_admin": False,
                                    "created_at": _dt.now(_tz.utc).isoformat(),
                                    "bridge_synced": True,
                                })
                                logger.info(
                                    f"[bridge] auto-created local user {lic_email} "
                                    f"(id={user_id_new[:8]}) for JWT bridge replay"
                                )
                            local_jwt = create_access_token({"sub": lic_email})
                            logger.info(
                                f"[bridge] minted local JWT for {lic_email} "
                                f"(replacing cloud JWT for replay)"
                            )
                except Exception as _mint_err:  # noqa: BLE001
                    logger.warning(f"[bridge] could not mint local JWT: {_mint_err}")

                if local_jwt:
                    headers["Authorization"] = f"Bearer {local_jwt}"
                elif auth_hdr:
                    # Fallback: forward the cloud JWT. Will fail
                    # signature on local backend but useful for endpoints
                    # that do their own auth (license-based).
                    headers["Authorization"] = auth_hdr
                # ALWAYS include the license header so any endpoint that
                # supports license auth can use it as a secondary path.
                headers["X-Krexion-License"] = LICENSE_KEY
                # Pass through the original Content-Type when we have
                # raw bytes (multipart, urlencoded, etc.). For empty raw
                # body fall back to JSON.
                use_raw = bool(raw_body_bytes) and content_type and (
                    "multipart/form-data" in content_type.lower()
                    or "application/x-www-form-urlencoded" in content_type.lower()
                )
                if use_raw:
                    headers["Content-Type"] = content_type
                    # v2.1.4 SANITY: verify the multipart boundary
                    # declared in Content-Type ALSO appears in the raw
                    # body bytes. If not, the upload was corrupted in
                    # transit (base64 round-trip + MongoDB document
                    # storage can mangle some edge bytes). Log a
                    # WARNING so the next 422 'Field required' has a
                    # breadcrumb. We always set Content-Length too —
                    # httpx normally auto-computes but a few intermediate
                    # proxies (Starlette form parser inclusive) refuse
                    # to parse multipart without an explicit length.
                    if "multipart/form-data" in content_type.lower():
                        try:
                            ct_lower = content_type.lower()
                            bnd_idx = ct_lower.find("boundary=")
                            if bnd_idx >= 0:
                                bnd = content_type[bnd_idx + len("boundary="):].split(";")[0].strip().strip('"')
                                if bnd:
                                    bnd_bytes = bnd.encode("utf-8", errors="ignore")
                                    if bnd_bytes and bnd_bytes not in raw_body_bytes:
                                        logger.warning(
                                            f"[bridge] multipart boundary '{bnd[:30]}' "
                                            f"NOT FOUND in raw_body_bytes "
                                            f"({len(raw_body_bytes)} bytes) - "
                                            f"replay will likely 422!"
                                        )
                                    else:
                                        logger.info(
                                            f"[bridge] multipart OK boundary={bnd[:30]} "
                                            f"bytes={len(raw_body_bytes)}"
                                        )
                        except Exception as _bnd_err:  # noqa: BLE001
                            logger.debug(f"[bridge] boundary sanity check failed: {_bnd_err}")
                    headers["Content-Length"] = str(len(raw_body_bytes))
                else:
                    headers["Content-Type"] = "application/json"
                logger.info(
                    f"[bridge] replay {generic_method} {generic_path} "
                    f"ct={headers.get('Content-Type','')[:40]} "
                    f"raw_bytes={len(raw_body_bytes)} json_body={bool(generic_body)}"
                )
                # v2.1.4: 422-retry loop for multipart replays. The first
                # attempt sometimes fails because Starlette's form parser
                # cached an EMPTY body from the cloud-side _BridgeDone
                # short-circuit. A clean second attempt with a freshly
                # constructed AsyncClient always succeeds.
                async def _do_replay():
                    async with httpx.AsyncClient(timeout=600.0) as client:
                        if generic_method == "GET":
                            return await client.get(
                                f"{local_base}{generic_path}",
                                headers=headers,
                                params=generic_query,
                            )
                        elif use_raw:
                            return await client.request(
                                generic_method,
                                f"{local_base}{generic_path}",
                                headers=headers,
                                params=generic_query,
                                content=raw_body_bytes,
                            )
                        else:
                            return await client.request(
                                generic_method,
                                f"{local_base}{generic_path}",
                                headers=headers,
                                params=generic_query,
                                json=generic_body,
                            )

                r = await _do_replay()
                if r.status_code == 422 and use_raw:
                    # Detect the specific "body.* required" Pydantic error
                    # that means form parsing failed even though our body
                    # had the bytes. Retry ONCE with a fresh request.
                    try:
                        err_json = r.json()
                        detail = err_json.get("detail") if isinstance(err_json, dict) else None
                        is_form_missing = False
                        if isinstance(detail, list):
                            for d in detail:
                                if isinstance(d, dict) and d.get("type") == "missing":
                                    loc = d.get("loc") or []
                                    if len(loc) >= 2 and loc[0] == "body":
                                        is_form_missing = True
                                        break
                        if is_form_missing:
                            logger.warning(
                                f"[bridge] replay 1st attempt got 422 form-missing — "
                                f"retrying once (raw_bytes={len(raw_body_bytes)})"
                            )
                            r = await _do_replay()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    body_back = r.json()
                except Exception:
                    # v2.1.4: when response isn't JSON (e.g.
                    # /visual-recorder/{id}/screenshot returns
                    # image/jpeg), base64-encode the raw bytes so the
                    # cloud can decode + forward as binary. Previously
                    # we stuffed r.text[:4000] which mangled any
                    # non-ASCII byte and broke screenshot bridging.
                    import base64 as _b64sub
                    body_back = {
                        "__binary_b64__": _b64sub.b64encode(r.content).decode("ascii"),
                        "__content_type__": r.headers.get("content-type", "application/octet-stream"),
                    }
                logger.info(
                    f"[bridge] replay → HTTP {r.status_code} for {generic_path}"
                )
                return {
                    "status": "done",
                    "result": {"status": r.status_code, "body": body_back},
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[bridge] local replay failed for {generic_path}: {exc}")
                return {"status": "failed", "error": f"local replay failed: {exc}"}
        return {"status": "failed", "error": f"unknown feature: {feature}"}

    method, route = feature_routes[feature]

    # Helper: try Bearer + fallback URLs for AdsPower's local API.
    # AdsPower 8.4+ requires "Bearer <key>", older versions accept the raw
    # key. local.adspower.net may fail DNS on some machines → 127.0.0.1.
    async def _call_adspower(path: str, http_method: str, json_body: dict | None,
                             requested_host: str, api_key: str) -> dict:
        bases = [
            (requested_host or "http://local.adspower.net:50325").rstrip("/"),
            "http://127.0.0.1:50325",
        ]
        # dedupe while keeping order
        seen: set = set()
        bases = [b for b in bases if not (b in seen or seen.add(b))]
        auths = [f"Bearer {api_key}", api_key] if api_key else [""]
        last_err = None
        last_data: dict = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for base in bases:
                for auth in auths:
                    try:
                        headers = {"Content-Type": "application/json"}
                        if auth:
                            headers["Authorization"] = auth
                        if http_method == "GET":
                            r = await client.get(f"{base}{path}", headers=headers, timeout=15)
                        else:
                            r = await client.post(f"{base}{path}", json=json_body, headers=headers, timeout=30)
                        try:
                            data = r.json()
                        except Exception:
                            data = {"text": r.text[:2000]}
                        last_data = data
                        if r.status_code >= 400:
                            last_err = f"AdsPower {r.status_code}: {data.get('msg') or data}"
                            continue
                        msg_l = str(data.get("msg", "")).lower()
                        if data.get("code") not in (0, None) and ("api-key" in msg_l or "api_key" in msg_l or "auth" in msg_l):
                            last_err = f"AdsPower rejected auth: {data.get('msg')}"
                            continue
                        return {"ok": True, "data": data}
                    except Exception as e:  # noqa: BLE001
                        last_err = str(e)
                        continue
        return {"ok": False, "error": last_err or "unreachable", "data": last_data}

    # Special handler: AdsPower API connection test
    if route == "__adspower_test__":
        host = payload.get("host") or "http://local.adspower.net:50325"
        api_key = payload.get("api_key") or ""
        res = await _call_adspower("/status", "GET", None, host, api_key)
        if res["ok"]:
            return {"status": "done", "result": {"reachable": True, "raw": res["data"]}}
        return {"status": "failed", "error": res["error"]}

    # Special handler: AdsPower local API call (not a local backend route)
    if route == "__adspower_create__":
        host = payload.get("host") or "http://local.adspower.net:50325"
        api_key = payload.get("api_key") or ""
        body = {k: v for k, v in payload.items() if k not in ("host", "api_key")}
        res = await _call_adspower("/api/v1/user/create", "POST", body, host, api_key)
        if res["ok"]:
            return {"status": "done", "result": res["data"]}
        return {"status": "failed", "error": res["error"]}

    # Special handler: AdsPower bulk delete
    if route == "__adspower_delete__":
        host = payload.get("host") or "http://local.adspower.net:50325"
        api_key = payload.get("api_key") or ""
        user_ids = payload.get("user_ids") or []
        if not user_ids:
            return {"status": "failed", "error": "no user_ids provided"}
        res = await _call_adspower(
            "/api/v1/user/delete", "POST",
            {"user_ids": user_ids}, host, api_key,
        )
        if res["ok"]:
            return {"status": "done", "result": res["data"]}
        return {"status": "failed", "error": res["error"]}

    # ── 2026-06-11: Browser Profile launcher (manual anti-detect browsing) ──
    if route == "__browser_profile_launch__":
        try:
            from browser_profile_launcher import launch_profile_session
            import httpx as _httpx
            profile_config = payload.get("profile_config") or {}
            session_id = str(payload.get("session_id") or "")
            start_url = str(payload.get("start_url") or "https://www.google.com/")

            # Callback that POSTs session events back to the cloud
            cloud_base = os.environ.get("KREXION_CLOUD_BASE", "https://krexion.com")
            session_update_url = f"{cloud_base}/api/browser-profiles/_bridge/session-update"
            bearer = jwt_token or ""

            async def _on_update(body: dict):
                try:
                    async with _httpx.AsyncClient(timeout=20) as c:
                        h = {"Content-Type": "application/json"}
                        if bearer:
                            h["Authorization"] = f"Bearer {bearer}"
                        h["X-Krexion-License"] = LICENSE_KEY
                        await c.post(session_update_url, json=body, headers=h)
                except Exception as e:
                    logger.debug(f"session update push failed: {e}")

            # Run the launch in the BACKGROUND so the bridge job can be
            # marked done immediately — the headed browser stays open
            # for the customer to manually browse. Stop is delivered via
            # a separate "browser-profile/stop" bridge job.
            asyncio.create_task(launch_profile_session(
                profile_config,
                session_id=session_id,
                start_url=start_url,
                on_session_update=_on_update,
            ))
            return {"status": "done", "result": {"launched": True, "session_id": session_id}}
        except Exception as e:
            return {"status": "failed", "error": f"browser-profile launch failed: {e}"}

    if route == "__browser_profile_stop__":
        try:
            from browser_profile_launcher import request_stop
            session_id = str(payload.get("session_id") or "")
            ok = request_stop(session_id)
            return {"status": "done", "result": {"stopped": ok, "session_id": session_id}}
        except Exception as e:
            return {"status": "failed", "error": f"browser-profile stop failed: {e}"}

    url = f"{LOCAL_API_BASE}{route}"
    headers = {"Content-Type": "application/json"}
    # Forward the user's JWT if we have one cached, otherwise rely on local
    # license-key based auth fallback (most local endpoints accept either)
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    headers["X-Krexion-License"] = LICENSE_KEY
    headers["X-Krexion-Bridge-Job"] = job.get("id", "")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            if method == "POST":
                r = await client.post(url, json=payload, headers=headers)
            else:
                r = await client.get(url, params=payload, headers=headers)
        if r.status_code < 400:
            try:
                return {"status": "done", "result": r.json()}
            except Exception:
                return {"status": "done", "result": {"text": r.text[:50000]}}
        return {"status": "failed", "error": f"local backend {r.status_code}: {r.text[:500]}"}
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": f"local execution error: {e}"}


async def _pull_and_run_jobs() -> int:
    """Pull up to 5 pending jobs from cloud, execute each locally, post
    result back. Returns count of jobs processed."""
    if not (CLOUD_URL and LICENSE_KEY):
        return 0
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{CLOUD_URL}/api/sync/jobs/pull",
                params={"limit": 5, "hostname": socket.gethostname(), "worker_type": "python"},
                headers=_headers(),
            )
        if r.status_code != 200:
            return 0
        jobs = (r.json() or {}).get("jobs") or []
        if not jobs:
            return 0
        logger.info(f"[bridge] pulled {len(jobs)} job(s) from cloud")

        async def _run_one(job: dict) -> None:
            result = await _execute_job_locally(job)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(
                        f"{CLOUD_URL}/api/sync/jobs/result",
                        json={"job_id": job.get("id"), **result},
                        headers=_headers(),
                    )
                logger.info(
                    f"[bridge] job {(job.get('id') or '')[:8]} -> {result.get('status')}"
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[bridge] result post failed: {e}")

        await asyncio.gather(*[_run_one(j) for j in jobs], return_exceptions=True)
        return len(jobs)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[bridge] pull/run cycle failed: {e}")
        return 0


async def _bridge_loop() -> None:
    """Faster cycle dedicated to bridge job pulling for responsive UX.

    Idle PCs poll slower so ~100 online installs don't stampede the
    cloud every 5s for empty queues. After a claimed job, resume the
    snappy interval.
    """
    global _running
    while _running:
        n = 0
        try:
            if LICENSE_KEY or _current_license_key():
                n = await _pull_and_run_jobs()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[bridge] loop error: {e}")
        wait = JOB_PULL_INTERVAL if n else max(JOB_PULL_INTERVAL, JOB_PULL_IDLE_SEC)
        await asyncio.sleep(wait)


async def _sync_loop(main_db, get_db_for_user) -> None:
    global LICENSE_KEY
    logger.info(
        f"[sync] daemon started - cloud={CLOUD_URL}, interval={SYNC_INTERVAL}s, "
        f"heartbeat={HEARTBEAT_INTERVAL}s, bridge_pull={JOB_PULL_INTERVAL}s/"
        f"idle={JOB_PULL_IDLE_SEC}s"
    )

    while _running:
        try:
            if not LICENSE_KEY:
                try:
                    lic_doc = await main_db.licenses.find_one(
                        {"status": {"$in": ["active", "issued"]}},
                        sort=[("created_at", -1)],
                        projection={"_id": 0, "license_key": 1},
                    )
                    if lic_doc and lic_doc.get("license_key"):
                        LICENSE_KEY = lic_doc["license_key"]
                        logger.info(f"[sync] license key resolved from DB ({LICENSE_KEY[:12]}...)")
                except Exception:
                    pass

            if not LICENSE_KEY:
                await asyncio.sleep(SYNC_INTERVAL)
                continue

            lic = await main_db.licenses.find_one(
                {"license_key": LICENSE_KEY}, {"_id": 0}
            )
            if lic:
                user = await main_db.users.find_one(
                    {"email": lic["email"]}, {"_id": 0}
                )
                if user:
                    user_db = get_db_for_user(user)
                    pushed = await _push_links(user_db)
                    pulled = await _pull_clicks(user_db)
                    if pushed or pulled:
                        logger.info(
                            f"[sync] cycle ok - pushed={pushed} pulled={pulled}"
                        )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[sync] loop error: {e}")

        await asyncio.sleep(SYNC_INTERVAL)


def start_if_local(main_db, get_db_for_user) -> bool:
    """Called from server.py on startup. No-op if not configured for sync.

    v1.0.14 fix: previously checked `KREXION_MODE == 'local'` strict-equal.
    But the actual NSSM service installer's `AppEnvironmentExtra` line
    in krexion-setup.iss sets `KREXION_MODE=native` (not "local").
    Result: every native customer install had the sync daemon DISABLED
    on startup, no heartbeats reached the cloud, the krexion.com link
    pill in the dashboard read 'no recent heartbeat' forever, AND every
    heavy job submitted from krexion.com was rejected with
    'local_pc_offline'. This is THE root cause of the v1.0.12-1.0.13
    'heavy jobs ni chal rahe' report.

    Now we treat ANY non-'cloud' mode as a customer install that needs
    to talk to the cloud. Only KREXION_MODE='cloud' (the VPS deploy)
    skips this path.
    """
    global _running
    if KREXION_MODE == "cloud":
        logger.info("[sync] disabled - KREXION_MODE=cloud (this IS the cloud edge)")
        return False
    if not CLOUD_URL:
        logger.info("[sync] disabled - KREXION_CLOUD_URL not set")
        return False
    # v2.1.4: kill the legacy PowerShell `KrexionBridge` scheduled task
    # if it exists. Older installs (pre-native bundle, or PCs that ever
    # ran the cloud's "Pair my PC" PowerShell snippet) have a Scheduled
    # Task that polls /api/sync/jobs/pull every 5 s with NO feature
    # filter. It races the Python sync_client and atomically claims
    # heavy jobs like visual-recorder/start, only to immediately mark
    # them failed with "feature not supported by the PowerShell bridge
    # worker." That is exactly what the customer is reporting in
    # v2.1.4 logs. Deleting the task on startup is idempotent
    # (schtasks /Delete returns non-zero if task absent — fine).
    if sys.platform.startswith("win"):
        try:
            import subprocess as _sp
            for _task in ("KrexionBridge", "KrexionHeartbeat"):
                try:
                    _sp.run(
                        ["schtasks", "/Delete", "/TN", _task, "/F"],
                        capture_output=True,
                        timeout=10,
                        creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                    )
                except Exception:  # noqa: BLE001
                    pass
            logger.info("[sync] legacy KrexionBridge / KrexionHeartbeat scheduled tasks cleaned up (if present)")
        except Exception as _cleanup_err:  # noqa: BLE001
            logger.debug(f"[sync] legacy task cleanup skipped: {_cleanup_err}")
    try:
        _running = True
        asyncio.create_task(_heartbeat_loop())
        asyncio.create_task(_sync_loop(main_db, get_db_for_user))
        asyncio.create_task(_bridge_loop())
        logger.info(
            f"[sync] daemon enabled for mode={KREXION_MODE!r}, cloud={CLOUD_URL}, "
            f"license_key_present={bool(LICENSE_KEY)}"
        )
        if not LICENSE_KEY:
            logger.info(
                "[sync] no LICENSE_KEY env - daemon will pick it up from "
                "the licenses collection once the user activates."
            )
        return True
    except RuntimeError:
        logger.warning("[sync] no running loop - schedule from startup event")
        return False
