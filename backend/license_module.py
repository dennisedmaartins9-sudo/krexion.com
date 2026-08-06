"""
Krexion — License & Subscription Module
========================================

A self-contained FastAPI router that handles:

* Public license endpoints (called by the desktop installer + the
  locally-running app on each customer's PC):
    GET  /api/license/config             — current pricing / trial / rules
    POST /api/license/start-trial        — create a trial license
    POST /api/license/activate           — bind license to a machine
    POST /api/license/validate           — heartbeat / status check
    POST /api/license/checkout           — create Stripe Checkout
    GET  /api/license/status/{sid}       — poll Stripe payment status
    POST /api/webhook/stripe             — Stripe webhook

* Admin endpoints (require existing admin JWT):
    GET  /api/admin/license/config       — view config
    PUT  /api/admin/license/config       — edit pricing/rules globally
    GET  /api/admin/license/list         — list all licenses
    POST /api/admin/license/revoke/{key} — revoke a license
    POST /api/admin/license/extend/{key} — manually extend N days

Storage: three MongoDB collections inside the MAIN database
(not per-user — this is global SaaS state):
    license_config            — single document, the live ruleset
    licenses                  — one row per customer
    payment_transactions      — one row per checkout (Stripe playbook req)
"""

from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)
license_router = APIRouter(prefix="/api", tags=["license"])

# ─── State injected from server.py via _bind() ────────────────────────
_db: Any = None
_get_current_admin: Any = None
_get_current_user: Any = None
_send_email: Any = None  # optional email helper (notifications.py)


def _bind(*, main_db, get_current_admin, get_current_user=None, send_email=None) -> None:
    """Wire up dependencies. Called once from server.py."""
    global _db, _get_current_admin, _get_current_user, _send_email
    _db = main_db
    _get_current_admin = get_current_admin
    _get_current_user = get_current_user
    _send_email = send_email


# ─── Helpers ──────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _as_aware(dt: Any) -> Optional[datetime]:
    """Normalize a possibly-naive datetime (e.g. from Mongo BSON) to UTC.
    Accepts datetime, ISO string, or None. Returns tz-aware UTC datetime."""
    if not dt:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:  # noqa: BLE001
            return None
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt if isinstance(dt, datetime) else None


def _gen_license_key() -> str:
    """Format: KRX-XXXX-XXXX-XXXX-XXXX (19 chars + 4 dashes)."""
    raw = uuid.uuid4().hex.upper()[:16]
    return "KRX-" + "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def _default_config() -> Dict[str, Any]:
    return {
        "id": "global",
        "product_name": "Krexion",
        "monthly_price": 29.0,
        "currency": "usd",
        "trial_days": 7,
        "max_pcs_per_license": 1,
        "enabled": True,
        # Manual purchase flow — installer shows these to customers
        # instead of a Stripe checkout button. Aap admin panel se
        # globally edit kar sakte hain.
        "admin_contact_email": "admin@krexion.local",
        "admin_contact_message": (
            "To purchase a license, please email the admin with your name, "
            "company (optional), and preferred payment method (crypto / "
            "bank transfer / etc.). The admin will reply with a license "
            "key once payment is received."
        ),
        "checkout_success_url_suffix": "/license/success",
        "checkout_cancel_url_suffix": "/license/cancel",
        "updated_at": _now().isoformat(),
    }


async def get_config() -> Dict[str, Any]:
    """Read the single config document; seed default if missing.
    Also back-fills any newly-added fields from _default_config() so
    older databases automatically pick up new keys (e.g. admin_contact_*)
    without an explicit migration."""
    defaults = _default_config()
    cfg = await _db.license_config.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        await _db.license_config.insert_one(defaults.copy())
        return defaults
    # Back-fill any keys missing from older config docs
    missing = {k: v for k, v in defaults.items() if k not in cfg}
    if missing:
        await _db.license_config.update_one({"id": "global"}, {"$set": missing})
        cfg.update(missing)
    return cfg


def _get_machine_label(license_doc: Dict[str, Any]) -> str:
    """Human label for emails / admin UI."""
    mid = license_doc.get("machine_id")
    return mid[:8] + "…" if mid else "(unbound)"


async def _maybe_notify(subject: str, body: str) -> None:
    """Fire-and-forget email to admin if helper is bound."""
    try:
        if _send_email:
            admin_email = os.environ.get("ADMIN_EMAIL") or "admin@krexion.local"
            await _send_email(to=admin_email, subject=subject, body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"License notification email failed: {e}")


def _expired(lic: Dict[str, Any]) -> bool:
    """Return True if the license should be treated as expired right now."""
    now = _now()
    status_ = (lic.get("status") or "").lower()
    if status_ in ("revoked", "expired"):
        return True
    if status_ == "trial":
        ends = _as_aware(lic.get("trial_ends_at"))
        if ends and ends < now:
            return True
    if status_ == "active":
        ends = _as_aware(lic.get("subscription_ends_at"))
        if ends and ends < now:
            return True
    return False


def _public_license(lic: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internals before returning to client."""
    return {
        "license_key": lic.get("license_key"),
        "email": lic.get("email"),
        "status": lic.get("status"),
        "trial_ends_at": _iso(lic.get("trial_ends_at")),
        "subscription_ends_at": _iso(lic.get("subscription_ends_at")),
        "machine_id": lic.get("machine_id"),
        "activated_at": _iso(lic.get("activated_at")),
    }


# ─── Pydantic request models ──────────────────────────────────────────
class StartTrialRequest(BaseModel):
    email: EmailStr
    machine_id: Optional[str] = None


class ActivateRequest(BaseModel):
    license_key: str
    machine_id: str
    machine_label: Optional[str] = None


class ValidateRequest(BaseModel):
    license_key: str
    machine_id: str
    # 2026-01 Phase D anti-crack — optional hardening payload sent by
    # the local Krexion process. Older clients (no hardening) just omit
    # these and the server treats absent values as "no data" (no
    # enforcement). Newer customer builds send the real values and the
    # admin dashboard can react if anything looks suspicious.
    hwid: Optional[str] = None
    debug_tools_detected: Optional[List[str]] = None
    integrity_ok: Optional[bool] = None
    integrity_hash: Optional[str] = None
    build_type: Optional[str] = None
    platform_info: Optional[str] = None


class CheckoutRequest(BaseModel):
    license_key: str
    origin_url: str = Field(..., description="Frontend origin, e.g. https://app.example.com")


class VerifyForDownloadRequest(BaseModel):
    license_key: str


class ConfigUpdate(BaseModel):
    product_name: Optional[str] = None
    monthly_price: Optional[float] = Field(None, ge=0.5, le=10000.0)
    currency: Optional[str] = Field(None, pattern=r"^[a-z]{3}$")
    trial_days: Optional[int] = Field(None, ge=0, le=365)
    max_pcs_per_license: Optional[int] = Field(None, ge=1, le=1000)
    enabled: Optional[bool] = None
    admin_contact_email: Optional[EmailStr] = None
    admin_contact_message: Optional[str] = Field(None, max_length=2000)


# ═════════════════════════════════════════════════════════════════════
# PUBLIC ENDPOINTS (called by the installer + locally-running app)
# ═════════════════════════════════════════════════════════════════════

@license_router.get("/license/config")
async def license_config_public():
    """Current pricing / trial / rules. Cached client-side by installer."""
    cfg = await get_config()
    return {
        "product_name": cfg["product_name"],
        "monthly_price": cfg["monthly_price"],
        "currency": cfg["currency"],
        "trial_days": cfg["trial_days"],
        "max_pcs_per_license": cfg["max_pcs_per_license"],
        "enabled": cfg["enabled"],
        "admin_contact_email": cfg.get("admin_contact_email", ""),
        "admin_contact_message": cfg.get("admin_contact_message", ""),
    }


@license_router.post("/license/start-trial")
async def start_trial(body: StartTrialRequest):
    cfg = await get_config()
    if not cfg["enabled"]:
        raise HTTPException(403, "Licensing is currently disabled. Please contact the admin.")
    if cfg["trial_days"] <= 0:
        raise HTTPException(400, "Free trial is currently disabled. Please purchase a license.")

    # Prevent multi-trial abuse: one trial per email
    existing = await _db.licenses.find_one({"email": body.email.lower()}, {"_id": 0})
    if existing:
        return {"license_key": existing["license_key"], "reused": True, "message": "Existing license returned."}

    key = _gen_license_key()
    lic = {
        "license_key": key,
        "email": body.email.lower(),
        "status": "trial",
        "trial_ends_at": _now() + timedelta(days=cfg["trial_days"]),
        "subscription_ends_at": None,
        "machine_id": body.machine_id,
        "machine_label": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "activated_at": _now() if body.machine_id else None,
        "created_at": _now(),
        "last_validated_at": _now(),
    }
    await _db.licenses.insert_one(lic.copy())
    await _maybe_notify(
        subject=f"[Krexion] New trial: {body.email}",
        body=f"License key: {key}\nTrial ends: {_iso(lic['trial_ends_at'])}\nMachine: {_get_machine_label(lic)}",
    )
    return {"license_key": key, "reused": False, "trial_ends_at": _iso(lic["trial_ends_at"])}


@license_router.post("/license/activate")
async def activate(body: ActivateRequest):
    cfg = await get_config()
    if not cfg["enabled"]:
        raise HTTPException(403, "Licensing is currently disabled.")

    lic = await _db.licenses.find_one({"license_key": body.license_key}, {"_id": 0})
    if not lic:
        raise HTTPException(404, "License key not found.")
    if lic.get("status") == "revoked":
        raise HTTPException(403, "This license has been revoked.")
    if _expired(lic):
        raise HTTPException(403, f"This license has expired ({lic.get('status')}).")

    # Machine binding — v1.0.14 "auto-takeover" model.
    # Customer requirement: "aik licence key aik pc k liye … agr wahi
    # key pehle kabi kisi app se connected ho ge to os pr band ho
    # jay ge auto new app pr jidar use ho rahi hai odar connected
    # rahe ge".
    # Translation: ONE active machine at a time, but a fresh activation
    # from a NEW PC silently DEACTIVATES the old PC and takes the seat.
    # No more 'contact the seller to transfer it' error - the customer
    # can move between their own PCs freely.
    bound_id = lic.get("machine_id")
    max_pcs = max(1, int(cfg.get("max_pcs_per_license", 1)))
    if max_pcs == 1:
        if bound_id and bound_id != body.machine_id:
            # Auto-takeover: record the old machine as deactivated.
            await _db.license_events.insert_one({
                "license_key": body.license_key,
                "type": "auto_takeover",
                "old_machine_id": bound_id,
                "old_machine_label": lic.get("machine_label"),
                "new_machine_id": body.machine_id,
                "new_machine_label": body.machine_label,
                "at": _now(),
            })
            logger.info(
                f"[license] auto-takeover for {body.license_key[-6:]}: "
                f"{(bound_id or '')[:12]} -> {body.machine_id[:12]}"
            )
        update = {"machine_id": body.machine_id}
    else:
        # multi-PC: track in machines[] array, allow up to max_pcs
        machines = lic.get("machines") or []
        if body.machine_id not in machines:
            if len(machines) >= max_pcs:
                raise HTTPException(409, f"License already used on {max_pcs} PCs (the limit).")
            machines.append(body.machine_id)
        update = {"machine_id": body.machine_id, "machines": machines}

    update.update({
        "machine_label": body.machine_label,
        "activated_at": lic.get("activated_at") or _now(),
        "last_validated_at": _now(),
    })
    await _db.licenses.update_one({"license_key": body.license_key}, {"$set": update})
    lic.update(update)

    await _maybe_notify(
        subject=f"[Krexion] License activated: {lic['email']}",
        body=f"Key: {body.license_key}\nMachine: {body.machine_label or body.machine_id[:12]}\nStatus: {lic.get('status')}",
    )
    return {"ok": True, "license": _public_license(lic)}


@license_router.post("/license/validate")
async def validate(body: ValidateRequest):
    """Called by the locally-running Krexion app on startup +
    every N hours. Returns current authoritative status."""
    cfg = await get_config()
    if not cfg["enabled"]:
        return {"ok": True, "status": "active", "reason": "licensing_disabled"}

    lic = await _db.licenses.find_one({"license_key": body.license_key}, {"_id": 0})
    if not lic:
        raise HTTPException(404, "License key not recognized.")

    # v1.0.14: validate path now respects the auto-takeover model.
    # If a different machine_id is now bound (because the user activated
    # on a new PC), the OLD PC's heartbeat ends up here and gets a
    # special "deactivated_by_takeover" status. The desktop dashboard
    # on the old PC will surface this as "License Inactive - opened on
    # another PC" so the customer immediately knows what happened.
    max_pcs = max(1, int(cfg.get("max_pcs_per_license", 1)))
    if max_pcs == 1:
        bound = lic.get("machine_id")
        if bound and bound != body.machine_id:
            return {
                "ok": False,
                "status": "deactivated_by_takeover",
                "reason": (
                    "This license is now active on another PC. "
                    "Re-activate here to take the seat back."
                ),
                "bound_machine_id": bound,
            }
    else:
        machines = lic.get("machines") or ([lic.get("machine_id")] if lic.get("machine_id") else [])
        if body.machine_id not in machines:
            return {"ok": False, "status": "wrong_machine",
                    "reason": "This PC is not registered on the license."}

    if lic.get("status") == "revoked":
        return {"ok": False, "status": "revoked", "reason": "License was revoked."}
    if _expired(lic):
        # mark it expired so admin UI shows it
        await _db.licenses.update_one(
            {"license_key": body.license_key},
            {"$set": {"status": "expired"}},
        )
        return {"ok": False, "status": "expired",
                "reason": "Subscription / trial period has ended.",
                "license": _public_license({**lic, "status": "expired"})}

    await _db.licenses.update_one(
        {"license_key": body.license_key},
        {"$set": {"last_validated_at": _now()}},
    )
    # 2026-01 Phase D — record optional hardening telemetry alongside the
    # heartbeat. Older clients send no hardening fields and this block is
    # a no-op. Newer customer builds report HWID, debugger-tool scan,
    # integrity hash; admin dashboard can flag suspicious values without
    # forcibly killing the session (kill switch is admin-driven via the
    # /admin/license/revoke endpoint that already exists).
    try:
        hardening_updates: Dict[str, Any] = {}
        if body.hwid:
            hardening_updates["hardening.hwid"] = body.hwid
        if body.debug_tools_detected is not None:
            hardening_updates["hardening.debug_tools_detected"] = list(body.debug_tools_detected)
            if body.debug_tools_detected:
                hardening_updates["hardening.last_debug_tools_at"] = _now()
        if body.integrity_ok is not None:
            hardening_updates["hardening.integrity_ok"] = bool(body.integrity_ok)
        if body.integrity_hash:
            hardening_updates["hardening.integrity_hash"] = body.integrity_hash
        if body.build_type:
            hardening_updates["hardening.build_type"] = body.build_type
        if body.platform_info:
            hardening_updates["hardening.platform_info"] = body.platform_info
        if hardening_updates:
            hardening_updates["hardening.updated_at"] = _now()
            await _db.licenses.update_one(
                {"license_key": body.license_key}, {"$set": hardening_updates}
            )
    except Exception as _hd_err:
        # Hardening telemetry is best-effort; never break the heartbeat.
        logger.debug(f"hardening telemetry update skipped: {_hd_err}")
    return {"ok": True, "status": lic.get("status"), "license": _public_license(lic)}


# ═════════════════════════════════════════════════════════════════════
# CUSTOMER-FACING LICENSE DASHBOARD (v2.1.14)
# ─────────────────────────────────────────────────────────────────────
# These endpoints let the logged-in customer SEE their own license
# (status, days remaining, currently-bound PC) and DEACTIVATE the
# current PC from inside the desktop app — so they don't have to email
# support to move their seat to a different machine.
#
# Auth: standard customer JWT (same dependency used by every other
# /api/* customer endpoint). Lookup happens on `lic.email ==
# user.email` (case-insensitive) — the same key used everywhere else
# in the license module.
# ═════════════════════════════════════════════════════════════════════
def _user_dep():
    """Resolve the bound customer-auth dependency. Same pattern as
    `_admin_dep()` so we don't import server-level helpers at module
    load time."""
    async def _resolved(request: Request):
        if _get_current_user is None:
            raise HTTPException(503, "Customer auth not wired into license module.")
        return await _get_current_user(request)
    return Depends(_resolved)


def _days_remaining(lic: Dict[str, Any]) -> Optional[int]:
    """Return the integer days remaining for whichever clock applies
    (subscription if present, else trial). None when neither is set."""
    end = _as_aware(lic.get("subscription_ends_at") or lic.get("trial_ends_at"))
    if not end:
        return None
    delta = end - _now()
    return max(0, int(delta.total_seconds() // 86400))


def _customer_view(lic: Dict[str, Any]) -> Dict[str, Any]:
    """Customer-safe license view. Hides admin-only fields (stripe ids,
    hardening telemetry, raw machine fingerprints). Adds the
    `days_remaining` convenience field the dashboard renders directly."""
    return {
        "license_key": lic.get("license_key"),
        "email": lic.get("email"),
        "status": lic.get("status"),
        "trial_ends_at": _iso(lic.get("trial_ends_at")),
        "subscription_ends_at": _iso(lic.get("subscription_ends_at")),
        "activated_at": _iso(lic.get("activated_at")),
        "last_validated_at": _iso(lic.get("last_validated_at")),
        "machine_label": lic.get("machine_label"),
        "machine_id_short": (lic.get("machine_id") or "")[:8] or None,
        "machines_used": len(lic.get("machines") or
                              ([lic.get("machine_id")] if lic.get("machine_id") else [])),
        "days_remaining": _days_remaining(lic),
    }


@license_router.get("/license/me")
async def my_license(user: dict = _user_dep()):
    """Return the logged-in customer's own license info.
    Returns ``{license: null}`` if no license is tied to this email yet."""
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"ok": True, "licensing_enabled": False, "license": None,
                "max_pcs": int(cfg.get("max_pcs_per_license", 1))}

    email = (user.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, "Current user has no email — cannot look up license.")

    lic = await _db.licenses.find_one({"email": email}, {"_id": 0})
    return {
        "ok": True,
        "licensing_enabled": True,
        "max_pcs": int(cfg.get("max_pcs_per_license", 1)),
        "license": _customer_view(lic) if lic else None,
    }


class DeactivateMeRequest(BaseModel):
    # Optional, lets the dashboard double-confirm which PC is being released.
    # If omitted we release whatever machine is currently bound.
    machine_id: Optional[str] = None


@license_router.post("/license/deactivate-me")
async def deactivate_me(body: DeactivateMeRequest, user: dict = _user_dep()):
    """Release the current PC binding so the customer can re-activate
    on another machine. Does NOT cancel the license, expire it, or
    refund — purely clears the seat. The auto-takeover model in
    `/license/activate` already allows seamless PC switching, so this
    is mostly used when a customer is decommissioning a PC and wants
    to remove it cleanly from their account."""
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"ok": True, "status": "licensing_disabled"}

    email = (user.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, "Current user has no email.")

    lic = await _db.licenses.find_one({"email": email}, {"_id": 0})
    if not lic:
        raise HTTPException(404, "No license is tied to your account.")

    max_pcs = max(1, int(cfg.get("max_pcs_per_license", 1)))
    old_id = lic.get("machine_id")
    old_label = lic.get("machine_label")

    if max_pcs == 1:
        # Single-seat: just blank the bound machine
        update = {
            "machine_id": None,
            "machine_label": None,
            "machines": [],
        }
    else:
        # Multi-seat: drop only the specified machine_id (or the currently-bound one)
        target = (body.machine_id or old_id or "").strip()
        if not target:
            raise HTTPException(400, "No machine to release.")
        machines = [m for m in (lic.get("machines") or []) if m and m != target]
        update = {
            "machines": machines,
            # If we removed the primary, clear the singular pointer too
            "machine_id": (None if target == old_id else old_id),
            "machine_label": (None if target == old_id else old_label),
        }

    await _db.licenses.update_one({"email": email}, {"$set": update})
    await _db.license_events.insert_one({
        "license_key": lic.get("license_key"),
        "type": "customer_deactivate",
        "email": email,
        "old_machine_id": old_id,
        "old_machine_label": old_label,
        "at": _now(),
    })
    await _maybe_notify(
        subject=f"[Krexion] Customer self-deactivated: {email}",
        body=f"Key: {lic.get('license_key')}\nReleased PC: {old_label or (old_id or '')[:12]}",
    )

    # Return fresh view
    fresh = await _db.licenses.find_one({"email": email}, {"_id": 0})
    return {"ok": True, "license": _customer_view(fresh) if fresh else None}


# ═════════════════════════════════════════════════════════════════════
# DOWNLOAD GATE — verify license key before installer download
# ═════════════════════════════════════════════════════════════════════
@license_router.post("/license/verify-for-download")
async def verify_for_download(body: VerifyForDownloadRequest):
    """Verify a license key WITHOUT binding it to a machine. Used by the
    public DownloadPage to gate the installer download:

      • Customer purchases license → admin emails KRX-XXXX-… key
      • Customer enters key on /download page
      • This endpoint confirms key exists, isn't revoked, isn't expired
      • DownloadPage then enables the "Download installer" button which
        pulls /api/license/download-installer/{key} — the streamed ZIP
        has the key pre-embedded so the installer auto-fills it.

    Returns 404 if key is unknown, 410 if revoked/expired, 200 if ok.
    Never auto-creates anything; never binds to a machine. Purely a
    read-only check + a soft 'last_verified_at' touch on the doc.
    """
    cfg = await get_config()
    if not cfg.get("enabled", True):
        # Licensing disabled globally → no key check needed, just say OK.
        return {"ok": True, "status": "licensing_disabled", "license": None}

    key = (body.license_key or "").strip().upper()
    if not key:
        raise HTTPException(400, "License key is required.")

    lic = await _db.licenses.find_one({"license_key": key}, {"_id": 0})
    if not lic:
        raise HTTPException(404, "License key not recognized. Please check the key in the email we sent after your purchase, or contact support.")

    if lic.get("status") == "revoked":
        raise HTTPException(410, "This license has been revoked. Please contact support.")

    if _expired(lic):
        # Persist the expired status so admin UI reflects it.
        await _db.licenses.update_one(
            {"license_key": key}, {"$set": {"status": "expired"}}
        )
        raise HTTPException(410, "This license / trial period has ended. Please renew before downloading the installer.")

    # Soft touch — useful in admin UI to see "key was verified for download at …"
    try:
        await _db.licenses.update_one(
            {"license_key": key},
            {"$set": {"last_download_verify_at": _now().isoformat()}},
        )
    except Exception:  # noqa: BLE001
        pass

    max_pcs = max(1, int(cfg.get("max_pcs_per_license", 1)))
    machines = lic.get("machines") or ([lic.get("machine_id")] if lic.get("machine_id") else [])
    return {
        "ok": True,
        "status": lic.get("status"),
        "license": _public_license(lic),
        "max_pcs": max_pcs,
        "machines_used": len(machines),
        "machines_remaining": max(0, max_pcs - len(machines)),
    }


@license_router.get("/license/download-installer/{license_key}")
async def download_installer_with_key(license_key: str, request: Request):
    """Stream a personalized installer ZIP with the customer's license
    key pre-embedded as `license-key.txt` at the root. The bundled
    `install-master.ps1` reads this file and auto-fills the LICENSE_KEY=
    line in the generated .env — so the customer doesn't have to copy
    the key manually on their PC.

    Same validity gates as /license/verify-for-download. Streams a
    StreamingResponse so we don't buffer the full ZIP in RAM.

    Source files: backend's neighbouring `Krexion-User-Package/` dir
    (the canonical installer payload tracked in this repo). If that
    directory isn't present (e.g. dev environment without the payload
    yet), returns 503 with a clear admin-actionable message instead of
    a 500 stack trace.
    """
    import io
    import zipfile
    from pathlib import Path
    from fastapi.responses import StreamingResponse, RedirectResponse

    # ── 1. Verify the key (re-uses the same logic; never bind machine) ──
    cfg = await get_config()
    licensing_enabled = bool(cfg.get("enabled", True))
    key = (license_key or "").strip().upper()
    if not key:
        raise HTTPException(400, "License key is required.")

    lic_doc: Optional[Dict[str, Any]] = None
    if licensing_enabled:
        lic_doc = await _db.licenses.find_one({"license_key": key}, {"_id": 0})
        if not lic_doc:
            raise HTTPException(404, "License key not recognized.")
        if lic_doc.get("status") == "revoked":
            raise HTTPException(410, "This license has been revoked.")
        if _expired(lic_doc):
            await _db.licenses.update_one(
                {"license_key": key}, {"$set": {"status": "expired"}}
            )
            raise HTTPException(410, "License / trial expired.")

    # ── 2026-02: Native installer redirect ─────────────────────────────
    # If the admin has published a release with a `download_url` set
    # (e.g. a GitHub Releases asset for the Krexion-Setup-x.x.x.exe),
    # short-circuit the legacy ZIP build and send the customer to the
    # native installer directly. This is the white-label single-.exe
    # flow that replaces the Docker-based ZIP for new customers.
    try:
        latest_rel = await _db.app_releases.find_one(
            {"published": True, "download_url": {"$regex": r"\.exe(\?|$)"}},
            sort=[("created_at", -1)],
            projection={"_id": 0, "download_url": 1, "version": 1},
        )
    except Exception:
        latest_rel = None

    # Fallback when no admin-published release row exists yet: serve
    # the native Windows installer from the VPS CDN (written by the
    # build-windows-release workflow). Prefer native Setup.exe over
    # Electron — Local PC Dashboard silent updates must install the
    # same product customers already have (Inno / Krexion-Setup).
    # Override with KREXION_NATIVE_INSTALLER_URL or legacy
    # KREXION_DESKTOP_INSTALLER_URL.
    if not latest_rel or not latest_rel.get("download_url"):
        fallback_url = (
            os.environ.get("KREXION_NATIVE_INSTALLER_URL")
            or os.environ.get("KREXION_DESKTOP_INSTALLER_URL")
            or "https://krexion.com/downloads/windows/Krexion-Setup-latest.exe"
        )
        # Read current VERSION file for analytics tagging
        try:
            from pathlib import Path as _P
            fallback_version = (
                _P(__file__).resolve().parent / "VERSION"
            ).read_text(encoding="utf-8").strip() or "2.1.24"
        except Exception:  # noqa: BLE001
            fallback_version = "2.1.24"
        latest_rel = {"download_url": fallback_url, "version": fallback_version}

    if latest_rel and latest_rel.get("download_url"):
        # Soft analytics — same fields the ZIP path writes, so the
        # admin "downloads" counter keeps incrementing regardless of
        # which payload was served.
        try:
            await _db.licenses.update_one(
                {"license_key": key},
                {"$set": {
                    "installer_downloaded_at": _now().isoformat(),
                    "installer_kind": "native-exe",
                    "installer_version": latest_rel.get("version") or "",
                    "installer_downloaded_count": (lic_doc.get("installer_downloaded_count") or 0) + 1 if lic_doc else 1,
                }},
            )
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "[download-installer] redirecting key=%s to native installer v%s",
            key[:8] + "…", latest_rel.get("version", "?"),
        )
        # 302 with Cache-Control so browsers don't cache and miss
        # future installer-URL updates.
        return RedirectResponse(
            url=latest_rel["download_url"],
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    # ── 3. Legacy fallback: build the Docker-based ZIP in-memory ───────
    # Used only when no native release with a `.exe` download_url has
    # been published yet. Older customers stay on this path so they
    # don't break mid-rollout.
    backend_dir = Path(__file__).resolve().parent
    candidates = [
        backend_dir.parent / "Krexion-User-Package",   # /app/Krexion-User-Package
        backend_dir / "Krexion-User-Package",          # fallback inside backend/
    ]
    payload_dir = next((p for p in candidates if p.is_dir()), None)
    if payload_dir is None:
        logger.error("[download-installer] payload dir not found in any of: %s", candidates)
        raise HTTPException(
            status_code=503,
            detail=(
                "Installer is not yet available. Admin: publish a release "
                "with a `download_url` pointing to the native "
                "Krexion-Setup-*.exe, or restore the `Krexion-User-Package/` "
                "folder in the repo root."
            ),
        )

    # ── 3. Build customised ZIP in-memory ──────────────────────────────
    # Small enough (~100 KB of .bat/.ps1 scripts) that an in-memory
    # buffer is fine. If the payload ever grows past ~5 MB we should
    # switch to a temp file. For now this is cleaner + atomic.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in payload_dir.rglob("*"):
            if item.is_file():
                arcname = "Krexion-User-Package/" + str(item.relative_to(payload_dir)).replace("\\", "/")
                zf.write(item, arcname=arcname)
        # Inject the license-key file at the package root. The installer
        # PowerShell script checks for this and substitutes it into the
        # generated .env during STEP 6.
        email_line = (lic_doc.get("email") if lic_doc else "") or ""
        status_line = (lic_doc.get("status") if lic_doc else "licensing_disabled") or "active"
        # license-key.txt: ASCII + CRLF so PowerShell `Get-Content` on
        # every Windows locale reads it cleanly regardless of $OutputEncoding
        # or chcp. Pure ASCII (em-dash replaced with `-`) means even an
        # ANSI-default Notepad-style read will work.
        license_blob = (
            "# Krexion auto-generated license file - DO NOT EDIT.\r\n"
            f"# Issued for: {email_line}\r\n"
            f"# Status at download time: {status_line}\r\n"
            f"# Generated at: {_now().isoformat()}\r\n"
            f"{key}\r\n"
        )
        zf.writestr("Krexion-User-Package/license-key.txt", license_blob)

    buf.seek(0)

    # Soft analytics so admin sees "installer was actually downloaded"
    try:
        await _db.licenses.update_one(
            {"license_key": key},
            {"$set": {
                "installer_downloaded_at": _now().isoformat(),
                "installer_downloaded_count": (lic_doc.get("installer_downloaded_count") or 0) + 1 if lic_doc else 1,
            }},
        )
    except Exception:  # noqa: BLE001
        pass

    filename = f"Krexion-User-Package-{key.replace('-', '')[-8:]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@license_router.post("/license/checkout")
async def checkout(body: CheckoutRequest, http_request: Request):
    """DEPRECATED — Stripe payment flow has been removed. Customers now
    contact the admin manually (crypto / bank transfer / etc.) and the
    admin issues a license key from the admin panel. Endpoint kept only
    so older installers don't crash hard; it returns a friendly 410."""
    raise HTTPException(
        status_code=410,
        detail="Online payments are disabled. Please email the admin to purchase a license."
    )


@license_router.get("/license/status/{session_id}")
async def license_status_deprecated(session_id: str):
    """DEPRECATED — see /license/checkout note."""
    raise HTTPException(status_code=410, detail="Online payments are disabled.")


@license_router.post("/webhook/stripe")
async def stripe_webhook_deprecated(request: Request):
    """DEPRECATED — see /license/checkout note. Always 200 so any stale
    Stripe-Dashboard webhook config doesn't loop and retry forever."""
    return {"received": True, "deprecated": True}


# ═════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS  (gated by existing get_current_admin)
# ═════════════════════════════════════════════════════════════════════

def _admin_dep():
    """Lazy resolver — _get_current_admin is set by _bind() at app startup."""
    async def _resolved(request: Request):
        if _get_current_admin is None:
            raise HTTPException(503, "Admin auth not wired yet.")
        return await _get_current_admin(request)
    return Depends(_resolved)


@license_router.get("/admin/license/config")
async def admin_get_config(admin: dict = _admin_dep()):
    return await get_config()


@license_router.put("/admin/license/config")
async def admin_update_config(patch: ConfigUpdate, admin: dict = _admin_dep()):
    cfg = await get_config()
    updates = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return cfg
    updates["updated_at"] = _now().isoformat()
    await _db.license_config.update_one(
        {"id": "global"}, {"$set": updates}, upsert=True,
    )
    return await get_config()


@license_router.get("/admin/license/list")
async def admin_list_licenses(
    skip: int = 0,
    limit: int = 200,
    q: Optional[str] = None,
    admin: dict = _admin_dep(),
):
    filt: Dict[str, Any] = {}
    if q:
        rx = re.escape(q)
        filt = {"$or": [
            {"license_key": {"$regex": rx, "$options": "i"}},
            {"email": {"$regex": rx, "$options": "i"}},
            {"machine_id": {"$regex": rx, "$options": "i"}},
        ]}
    total = await _db.licenses.count_documents(filt)
    rows: List[Dict[str, Any]] = []
    cursor = _db.licenses.find(filt, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    async for r in cursor:
        for k in ("trial_ends_at", "subscription_ends_at", "activated_at",
                  "created_at", "last_validated_at"):
            r[k] = _iso(r.get(k))
        rows.append(r)
    return {"total": total, "items": rows}


@license_router.post("/admin/license/revoke/{key}")
async def admin_revoke(key: str, admin: dict = _admin_dep()):
    r = await _db.licenses.update_one(
        {"license_key": key},
        {"$set": {"status": "revoked", "revoked_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "License not found.")
    return {"ok": True}


@license_router.post("/admin/license/extend/{key}")
async def admin_extend(key: str, days: int = 31, admin: dict = _admin_dep()):
    if days < 1 or days > 3650:
        raise HTTPException(400, "days must be between 1 and 3650.")
    lic = await _db.licenses.find_one({"license_key": key}, {"_id": 0})
    if not lic:
        raise HTTPException(404, "License not found.")
    base = _as_aware(lic.get("subscription_ends_at"))
    if not base or base < _now():
        base = _now()
    new_end = base + timedelta(days=days)
    await _db.licenses.update_one(
        {"license_key": key},
        {"$set": {"status": "active", "subscription_ends_at": new_end}},
    )
    return {"ok": True, "subscription_ends_at": _iso(new_end)}


@license_router.delete("/admin/license/{key}")
async def admin_delete_license(key: str, admin: dict = _admin_dep()):
    """Permanently delete a license key from the database.
    Customer's local heartbeat will fail validation next cycle.
    Useful for cleaning up trial keys, revoked keys, mistakes, etc."""
    r = await _db.licenses.delete_one({"license_key": key})
    if r.deleted_count == 0:
        raise HTTPException(404, "License not found.")
    return {"ok": True, "deleted": key}


@license_router.post("/admin/license/bulk-delete")
async def admin_bulk_delete(payload: dict, admin: dict = _admin_dep()):
    """Bulk-delete licenses by filter.
    Body: {
      "status": "revoked" | "trial" | "active" | "expired" | "all",   (optional)
      "keys":   ["RFLW-...", "RFLW-..."],                              (optional, takes priority)
      "expired_only": true|false,                                       (optional)
      "unactivated_only": true|false                                    (optional - never bound to a machine)
    }
    Returns: { "ok": true, "deleted_count": N }
    """
    keys = payload.get("keys")
    lic_status = payload.get("status")
    expired_only = bool(payload.get("expired_only"))
    unactivated_only = bool(payload.get("unactivated_only"))

    if keys and isinstance(keys, list) and len(keys) > 0:
        # Whitelist explicit keys (safest)
        r = await _db.licenses.delete_many({"license_key": {"$in": keys}})
        return {"ok": True, "deleted_count": r.deleted_count, "by": "keys"}

    query: Dict[str, Any] = {}
    if lic_status and lic_status != "all":
        # "expired" is a logical filter, not a stored status
        if lic_status == "expired":
            expired_only = True
        else:
            query["status"] = lic_status
    if expired_only:
        # subscription_ends_at < now OR trial_ends_at < now (and no active sub)
        query["$or"] = [
            {"subscription_ends_at": {"$lt": _now()}, "status": {"$ne": "active"}},
            {"trial_ends_at": {"$lt": _now()}, "status": "trial"},
        ]
    if unactivated_only:
        query["machine_id"] = None

    if not query:
        raise HTTPException(400, "Refusing bulk-delete with empty filter. Specify status / keys / expired_only / unactivated_only.")

    r = await _db.licenses.delete_many(query)
    return {"ok": True, "deleted_count": r.deleted_count, "by": "filter", "filter": query}


@license_router.post("/admin/license/cleanup")
async def admin_cleanup(admin: dict = _admin_dep()):
    """One-click cleanup: deletes all revoked + all expired licenses.
    Keeps active and unexpired trial licenses untouched."""
    # 1. Revoked
    r1 = await _db.licenses.delete_many({"status": "revoked"})
    # 2. Expired trials
    r2 = await _db.licenses.delete_many({
        "status": "trial",
        "trial_ends_at": {"$lt": _now()},
    })
    # 3. Expired active subscriptions (subscription_ends_at past)
    r3 = await _db.licenses.delete_many({
        "subscription_ends_at": {"$lt": _now()},
        "status": {"$in": ["active", "expired"]},
    })
    return {
        "ok": True,
        "deleted": {
            "revoked": r1.deleted_count,
            "expired_trials": r2.deleted_count,
            "expired_subscriptions": r3.deleted_count,
            "total": r1.deleted_count + r2.deleted_count + r3.deleted_count,
        },
    }


@license_router.post("/admin/license/issue")
async def admin_issue_license(
    email: EmailStr,
    days: int = 31,
    admin: dict = _admin_dep(),
):
    """Manually issue an active license without Stripe (e.g. comp / vendor)."""
    key = _gen_license_key()
    lic = {
        "license_key": key,
        "email": email.lower(),
        "status": "active",
        "subscription_ends_at": _now() + timedelta(days=days),
        "trial_ends_at": None,
        "machine_id": None,
        "machine_label": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "activated_at": None,
        "created_at": _now(),
        "last_validated_at": _now(),
        "issued_by_admin": True,
    }
    await _db.licenses.insert_one(lic.copy())
    return {"ok": True, "license_key": key, "subscription_ends_at": _iso(lic["subscription_ends_at"])}


@license_router.get("/admin/license/transactions")
async def admin_transactions(skip: int = 0, limit: int = 200, admin: dict = _admin_dep()):
    total = await _db.payment_transactions.count_documents({})
    rows = []
    cursor = _db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    async for r in cursor:
        for k in ("created_at", "updated_at"):
            r[k] = _iso(r.get(k))
        rows.append(r)
    return {"total": total, "items": rows}
