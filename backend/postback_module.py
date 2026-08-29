"""Universal affiliate postback parsing — inbound S2S + outbound macro context."""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# Networks use many names for the same field when firing S2S to your tracker.
CLICK_ID_PARAM_ALIASES: Tuple[str, ...] = (
    "clickid", "click_id", "cid", "transaction_id", "transactionid",
    "aff_click_id", "aff_clickid", "external_id", "externalid",
    "subid", "sub_id", "requestid", "request_id", "cnv_id", "cnvid",
    "cd", "lead_id", "leadid", "tid", "tr_id", "trid",
    "sub1", "sub2", "sub3", "s1", "s2", "s3",
    "aff_sub", "aff_sub1", "aff_sub2", "aff_sub3",
    "custom1", "custom2", "custom3",
)

PAYOUT_PARAM_ALIASES: Tuple[str, ...] = (
    "payout", "amount", "sale", "revenue", "sum", "price", "payout_amount",
    "adv1", "adv_1", "payout_usd", "commission", "payout_amount_usd",
    "cost", "value", "earnings",
)

STATUS_PARAM_ALIASES: Tuple[str, ...] = (
    "status", "conversion_status", "event", "type", "goal", "action", "state",
)

TOKEN_PARAM_ALIASES: Tuple[str, ...] = (
    "token", "api_key", "apikey", "key", "secret", "auth", "password",
)

_APPROVED = frozenset({
    "approved", "approve", "conversion", "convert", "sale", "lead",
    "complete", "completed", "success", "accepted", "1", "true", "yes",
})
_REJECTED = frozenset({
    "rejected", "reject", "declined", "decline", "invalid", "failed",
    "chargeback", "reversal", "0", "false", "no",
})

# Statuses that increment link conversions/revenue counters.
COUNTABLE_CONVERSION_STATUSES = frozenset({"approved", "rut_heuristic", "sale", "lead"})


def _first_param(params: Mapping[str, Any], aliases: Tuple[str, ...]) -> str:
    """Case-insensitive lookup — first matching alias wins."""
    if not params:
        return ""
    lower_map: Dict[str, Any] = {}
    for k, v in params.items():
        if k is None:
            continue
        lower_map[str(k).lower().strip()] = v
    for alias in aliases:
        val = lower_map.get(alias.lower())
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


def _parse_payout(raw: str) -> float:
    if not raw:
        return 0.0
    try:
        cleaned = raw.strip().replace(",", "").replace("$", "")
        return float(cleaned)
    except (TypeError, ValueError):
        return 0.0


def normalize_postback_status(raw: str) -> str:
    s = (raw or "approved").strip().lower()
    if not s:
        return "approved"
    if s in _REJECTED:
        return "rejected"
    if s in _APPROVED:
        return "approved"
    if s in ("pending", "hold", "on_hold", "waiting"):
        return "pending"
    return s


def parse_inbound_postback(params: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize GET/POST query/form/JSON into canonical postback fields."""
    click_id = _first_param(params, CLICK_ID_PARAM_ALIASES)
    payout_raw = _first_param(params, PAYOUT_PARAM_ALIASES)
    status_raw = _first_param(params, STATUS_PARAM_ALIASES)
    token = _first_param(params, TOKEN_PARAM_ALIASES)
    return {
        "click_id": click_id,
        "payout": _parse_payout(payout_raw),
        "status": normalize_postback_status(status_raw),
        "token": token,
        "raw_status": status_raw or "approved",
    }


async def find_click_flexible(
    main_db,
    client,
    click_token: str,
) -> Tuple[Optional[Dict[str, Any]], Any]:
    """Resolve click by click_id, id, or sub1/sub2/sub3 (network-specific passthrough)."""
    from conversion_module import find_click_across_dbs

    token = (click_token or "").strip()
    if not token:
        return None, None

    click, src = await find_click_across_dbs(main_db, client, token)
    if click:
        return click, src

    # Some networks echo sub1/sub2/sub3 instead of click_id field name.
    for field in ("sub1", "sub2", "sub3", "id"):
        try:
            doc = await main_db.clicks.find_one({field: token}, {"_id": 0})
            if doc:
                return doc, main_db
        except Exception:
            pass
        try:
            for name in await client.list_database_names():
                if not name.startswith("krexion_user_"):
                    continue
                user_db = client[name]
                doc = await user_db.clicks.find_one({field: token}, {"_id": 0})
                if doc:
                    return doc, user_db
        except Exception as exc:
            logger.warning(f"find_click_flexible scan failed: {exc}")
            break
    return None, None


def conversion_counts_toward_stats(status: str, source: str = "") -> bool:
    """Only approved (and RUT heuristic) conversions affect revenue counters."""
    src = (source or "").strip().lower()
    if src == "rut_heuristic":
        return True
    s = normalize_postback_status(status)
    return s == "approved"


def validate_outbound_postback_url(url: str) -> Dict[str, Any]:
    """Check outbound tracker URL for international macro coverage."""
    u = (url or "").strip()
    if not u:
        return {"ok": False, "status": "missing", "detail": "No outbound postback URL configured"}
    if not u.startswith(("http://", "https://")):
        return {"ok": False, "status": "warn", "detail": "URL should start with http:// or https://"}
    low = u.lower()
    has_click = any(
        m in low
        for m in (
            "{click_id}", "{clickid}", "{transaction_id}", "{cid}",
            "{requestid}", "{cnv_id}", "{sub1}",
        )
    )
    has_payout = any(
        m in low
        for m in ("{payout}", "{amount}", "{sale}", "{sum}", "{price}", "{revenue}")
    )
    issues = []
    if not has_click:
        issues.append("missing click macro ({click_id} or {transaction_id})")
    if not has_payout:
        issues.append("missing payout macro ({payout} or {amount})")
    if issues:
        return {"ok": False, "status": "warn", "detail": "; ".join(issues)}
    return {"ok": True, "status": "pass", "detail": "Click + payout macros present"}


def build_inbound_postback_urls(base_url: str, token_placeholder: str = "YOUR_POSTBACK_TOKEN") -> Dict[str, Any]:
    """Copy-paste inbound S2S URLs for offer networks (international templates)."""
    base = (base_url or "https://krexion.com").rstrip("/")
    tok = token_placeholder
    return {
        "primary_get": (
            f"{base}/api/postback?clickid={{clickid}}&payout={{payout}}"
            f"&status=approved&token={tok}"
        ),
        "primary_post": f"{base}/api/postback",
        "pixel_get": f"{base}/api/pixel?clickid={{clickid}}&payout={{payout}}&token={tok}",
        "network_examples": {
            "voluum": f"{base}/api/postback?clickid={{clickid}}&payout={{payout}}&token={tok}",
            "everflow": f"{base}/api/postback?transaction_id={{transaction_id}}&amount={{payout}}&token={tok}",
            "hasoffers_tune": f"{base}/api/postback?transaction_id={{transaction_id}}&amount={{payout}}&token={tok}",
            "maxbounty": f"{base}/api/postback?cd={{clickid}}&sale={{payout}}&token={tok}",
            "affise": f"{base}/api/postback?clickid={{clickid}}&sum={{payout}}&token={tok}",
            "cake": f"{base}/api/postback?requestid={{clickid}}&price={{payout}}&token={tok}",
            "generic_sub1": f"{base}/api/postback?sub1={{clickid}}&payout={{payout}}&token={tok}",
        },
        "click_id_aliases": list(CLICK_ID_PARAM_ALIASES[:12]),
        "payout_aliases": list(PAYOUT_PARAM_ALIASES[:10]),
        "methods": ["GET", "POST"],
        "notes": (
            "Paste one inbound URL into your offer network's global postback setting. "
            "Krexion forwards to your outbound postback_url with expanded macros."
        ),
    }


def get_postback_international_catalog(base_url: str = "") -> Dict[str, Any]:
    return {
        "version": "v2.7.43",
        "inbound": build_inbound_postback_urls(base_url),
        "outbound_macros": [
            "click_id", "clickid", "transaction_id", "cid", "requestid", "cnv_id",
            "payout", "amount", "sale", "sum", "price", "revenue", "status",
            "sub1", "sub2", "sub3", "source", "country", "ua", "campaign",
        ],
        "supported_networks": [
            "Voluum", "Everflow", "HasOffers/Tune", "Cake", "MaxBounty", "Affise",
            "Glitchy", "PerformCB", "Adsterra", "Binom", "RedTrack", "ClickDealer",
        ],
    }


def build_outbound_postback_context(
    click: Dict[str, Any],
    link: Dict[str, Any],
    click_id: str,
    payout: float,
    status: str,
) -> Dict[str, Any]:
    """Rich macro context for Voluum / Everflow / HasOffers / Affise / MaxBounty / etc."""
    cid = (click_id or click.get("click_id") or click.get("id") or "").strip()
    payout_str = str(payout if payout is not None else 0)
    status_str = str(status or "approved")
    sub1 = str(click.get("sub1") or "")
    sub2 = str(click.get("sub2") or "")
    sub3 = str(click.get("sub3") or "")
    url_params = click.get("url_params") if isinstance(click.get("url_params"), dict) else {}

    return {
        "click_id": cid,
        "clickid": cid,
        "cid": cid,
        "transaction_id": cid,
        "transactionid": cid,
        "requestid": cid,
        "request_id": cid,
        "cnv_id": cid,
        "external_id": cid,
        "aff_click_id": cid,
        "subid": sub1 or cid,
        "payout": payout_str,
        "amount": payout_str,
        "revenue": payout_str,
        "sale": payout_str,
        "sum": payout_str,
        "price": payout_str,
        "commission": payout_str,
        "adv1": payout_str,
        "status": status_str,
        "source": str(click.get("referrer_source") or url_params.get("source") or ""),
        "source_name": str(click.get("referrer_source_name") or ""),
        "platform": str(click.get("referrer_source") or url_params.get("platform") or ""),
        "campaign": str(click.get("utm_campaign") or url_params.get("utm_campaign") or ""),
        "brand": str((link or {}).get("referrer_pro_brand") or ""),
        "country": str(click.get("country") or ""),
        "city": str(click.get("city") or ""),
        "region": str(click.get("region") or ""),
        "ip": str(click.get("ip_address") or ""),
        "ua": str(click.get("user_agent") or ""),
        "user_agent": str(click.get("user_agent") or ""),
        "referer": str(click.get("referrer") or click.get("referrer_pro_simulated") or ""),
        "referrer": str(click.get("referrer") or click.get("referrer_pro_simulated") or ""),
        "sub1": sub1,
        "sub2": sub2,
        "sub3": sub3,
        "s1": sub1,
        "s2": sub2,
        "s3": sub3,
        "utm_source": str(url_params.get("utm_source") or click.get("utm_source") or ""),
        "utm_medium": str(url_params.get("utm_medium") or click.get("utm_medium") or ""),
        "utm_campaign": str(url_params.get("utm_campaign") or click.get("utm_campaign") or ""),
        "utm_content": str(url_params.get("utm_content") or ""),
        "utm_term": str(url_params.get("utm_term") or ""),
    }
