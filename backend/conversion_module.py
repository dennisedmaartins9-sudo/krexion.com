"""Unified conversion recording — postback, pixel, and RUT heuristic paths."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


async def find_click_across_dbs(main_db, client, clickid: str) -> Tuple[Optional[Dict[str, Any]], Any]:
    """Find click by click_id in main DB or any krexion_user_* tenant DB."""
    cid = (clickid or "").strip()
    if not cid:
        return None, None
    try:
        click = await main_db.clicks.find_one({"click_id": cid}, {"_id": 0})
        if click:
            return click, main_db
    except Exception:
        pass
    try:
        for name in await client.list_database_names():
            if not name.startswith("krexion_user_"):
                continue
            user_db = client[name]
            click = await user_db.clicks.find_one({"click_id": cid}, {"_id": 0})
            if click:
                return click, user_db
    except Exception as exc:
        logger.warning(f"find_click_across_dbs scan failed for {cid}: {exc}")
    return None, None


async def _fire_outbound_postback(main_db, link_id: str, click: Dict[str, Any], click_id: str,
                                  payout: float, status: str) -> None:
    try:
        link = await main_db.links.find_one({"id": link_id}, {"_id": 0})
        pb_url = str((link or {}).get("postback_url") or "").strip()
        if not pb_url:
            return
        from referrer_pro import expand_link_macros as _exp_macros
        from postback_module import build_outbound_postback_context

        ctx = build_outbound_postback_context(click, link or {}, click_id, payout, status)
        final_pb = _exp_macros(pb_url, ctx)

        async def _fire(url: str) -> None:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as ac:
                    r = await ac.get(url)
                    logger.info(f"[postback-forward] {url[:120]}... → {r.status_code}")
                    await main_db.links.update_one(
                        {"id": link_id},
                        {"$set": {
                            "last_postback_fired_at": datetime.now(timezone.utc).isoformat(),
                            "last_postback_status_code": r.status_code,
                            "last_postback_url": url[:512],
                        }},
                    )
            except Exception as pbe:
                logger.warning(f"[postback-forward] failed: {pbe}")
                try:
                    await main_db.links.update_one(
                        {"id": link_id},
                        {"$set": {
                            "last_postback_fired_at": datetime.now(timezone.utc).isoformat(),
                            "last_postback_status_code": -1,
                            "last_postback_error": str(pbe)[:200],
                        }},
                    )
                except Exception:
                    pass

        asyncio.create_task(_fire(final_pb))
    except Exception as outer:
        logger.debug(f"[postback-forward] setup skipped: {outer}")


async def record_conversion(
    main_db,
    client,
    click_id: str,
    payout: float,
    *,
    status: str = "approved",
    source: str = "postback",
    forward_outbound: bool = True,
) -> Dict[str, Any]:
    """Insert conversion, bump link stats, reset auto-pause streak."""
    cid = (click_id or "").strip()
    if not cid:
        return {"ok": False, "error": "missing_click_id"}

    existing = await main_db.conversions.find_one({"click_id": cid})
    if existing:
        return {
            "ok": False,
            "duplicate": True,
            "conversion_id": str(existing.get("id") or ""),
        }

    click, _ = await find_click_across_dbs(main_db, client, cid)
    if not click:
        try:
            from postback_module import find_click_flexible
            click, _ = await find_click_flexible(main_db, client, cid)
        except Exception:
            pass
    if not click:
        logger.warning(f"[conversion] click not found for {cid} (source={source})")
        return {"ok": False, "error": "click_not_found"}

    conv_id = str(uuid.uuid4())
    st_norm = str(status or "approved").strip().lower()
    src_norm = str(source or "postback").strip().lower()
    countable = False
    try:
        from postback_module import conversion_counts_toward_stats
        countable = conversion_counts_toward_stats(st_norm, src_norm)
    except Exception:
        countable = st_norm in ("approved", "rut_heuristic")

    conversion_doc = {
        "id": conv_id,
        "click_id": cid,
        "link_id": click["link_id"],
        "payout": float(payout or 0) if countable else 0.0,
        "status": st_norm,
        "source": src_norm,
        "ip_address": click.get("ip_address", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await main_db.conversions.insert_one(conversion_doc)

    if countable:
        await main_db.links.update_one(
            {"id": click["link_id"]},
            {
                "$inc": {"conversions": 1, "revenue": float(payout or 0)},
                "$set": {"consecutive_no_conversions": 0},
            },
        )
    try:
        for name in await client.list_database_names():
            if not name.startswith("krexion_user_"):
                continue
            user_db = client[name]
            await user_db.clicks.update_one(
                {"click_id": cid},
                {"$set": {
                    "conversion_recorded": True,
                    "conversion_source": src_norm,
                }},
            )
    except Exception:
        pass

    if forward_outbound and countable:
        await _fire_outbound_postback(
            main_db, click["link_id"], click, cid, float(payout or 0), st_norm,
        )
    return {"ok": True, "conversion_id": conv_id}
