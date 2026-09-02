"""Browser Profile audit log — lead rows, sessions, automation (v2.7.94)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("browser_profile_audit")

COLLECTION = "browser_profile_audit"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_profile_event(
    db: Any,
    *,
    user_id: str,
    profile_id: str,
    event_type: str,
    session_id: str = "",
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one audit row (best-effort, never raises to caller)."""
    if db is None or not user_id or not profile_id:
        return
    try:
        doc = {
            "id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "profile_id": str(profile_id),
            "session_id": str(session_id or "")[:64],
            "event_type": str(event_type or "event")[:64],
            "detail": dict(detail or {}),
            "created_at": _now_iso(),
        }
        await db[COLLECTION].insert_one(doc)
    except Exception as exc:
        logger.debug(f"[profile-audit] insert skipped: {exc}")


async def list_profile_audit(
    db: Any,
    user_id: str,
    profile_id: str,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 100), 500))
    cursor = db[COLLECTION].find(
        {"user_id": user_id, "profile_id": profile_id},
        {"_id": 0},
    ).sort("created_at", -1).limit(lim)
    return [doc async for doc in cursor]
