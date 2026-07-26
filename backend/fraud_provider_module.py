"""
fraud_provider_module.py — Multi-account fraud detection service manager
════════════════════════════════════════════════════════════════════════

Lets each customer add MULTIPLE api-key accounts per fraud service
(Scamalytics, IPQualityScore, IPHub, ProxyCheck, custom). When one
account hits its quota limit or gets rate-limited, the next enabled
account for the same service is automatically used.

BACKWARD COMPAT (CRITICAL):
- If the user has NOT enabled personal fraud filter, this module is
  100% skipped and the existing admin-panel `check_vpn_detailed(ip)`
  behavior is preserved unchanged.
- If personal filter is ON but no accounts are configured, we fall
  back to the admin defaults (unless the user explicitly disables the
  fallback in their fraud settings).
- No existing endpoint / signature / response shape changes.

Data model
──────────
  user_fraud_settings  (per-user document):
    { user_id: str,
      personal_filter_enabled: bool,   # master switch
      fallback_to_defaults: bool,      # if all my accounts fail → use admin defaults
      updated_at: iso                 }

  user_fraud_accounts  (per-user, one row per account):
    { id: str (uuid),
      user_id: str,
      service: str,          # scamalytics | ipqualityscore | iphub | proxycheck | custom
      account_name: str,     # user-friendly label, e.g. "Primary US"
      api_key: str,
      api_user: str,         # some services need username too (e.g. scamalytics)
      endpoint: str,         # optional override (for custom)
      enabled: bool,
      priority: int,         # lower = tried first (default 100)
      quota_daily: int,      # 0 = unlimited
      quota_used: int,       # resets every 24h
      quota_reset_at: iso,   # next reset timestamp
      rate_limited_until: iso | None,
      created_at: iso,
      last_used_at: iso | None }

Public API
──────────
  init_router(main_db, existing_check_vpn_fn) -> APIRouter
    Wires the collection ref, registers routes under /api/fraud/*.

  check_ip_for_user(user_id, ip) -> dict
    Async. Respects user's fraud settings. Returns same shape as the
    existing check_vpn_detailed():
      {is_vpn: bool, vpn_score: int, risk: str, source: str, ...}
"""
from __future__ import annotations

import os
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger("fraud_provider_module")


# ─── Module-level state (populated by init_router) ───────────────────
_db = None                          # main_db from server.py
_existing_check_vpn = None          # fallback function pointer
_get_current_user_dep = None        # FastAPI dep resolver (from server.py)


# ─── Models ──────────────────────────────────────────────────────────
class FraudSettings(BaseModel):
    personal_filter_enabled: bool = False
    fallback_to_defaults: bool = True
    # 2026-07 — fraud score threshold. Any IP whose vpn_score (aka
    # fraud_score) meets or exceeds this value is forcibly flagged as
    # `is_vpn=True` in check_ip_for_user(), so downstream skip_vpn
    # filters (RUT, browser profile) can block it even when the raw
    # provider response didn't set the boolean flag. Range 0-100.
    # Default 75 — matches IPQualityScore's own recommended "block"
    # threshold for affiliate traffic.
    min_fraud_score: int = 75


class FraudAccountCreate(BaseModel):
    service: str = Field(..., description="scamalytics|ipqualityscore|iphub|proxycheck|custom")
    account_name: str
    api_key: str
    api_user: str = ""
    endpoint: str = ""
    enabled: bool = True
    priority: int = 100
    quota_daily: int = 0  # 0 = unlimited


class FraudAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    api_key: Optional[str] = None
    api_user: Optional[str] = None
    endpoint: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    quota_daily: Optional[int] = None


# 2026-07 — Custom fraud rules. Applied AFTER the provider check so
# they can override the raw provider result. Example use cases:
#   - Whitelist mode: only accept IPs from US/GB/CA
#   - Blacklist ASN 15169 (Google Cloud) & 16509 (AWS) to filter datacenter
#   - Auto-block Tor exit nodes regardless of fraud score
#   - Block "hosting" IP types that provider marks (IPQS proxy_type=hosting)
class FraudRules(BaseModel):
    enabled: bool = False
    # ISO country codes uppercase (e.g. ["US","GB","CA"]). Empty = allow all.
    allowed_countries: List[str] = Field(default_factory=list)
    # ISO country codes to force-block regardless of score.
    blocked_countries: List[str] = Field(default_factory=list)
    # ASN numbers to force-block (integers). Datacenter ASNs commonly:
    # 15169 Google, 16509 Amazon, 8075 Microsoft, 14061 DigitalOcean,
    # 63949 Linode, 20473 Vultr, 24940 Hetzner.
    blocked_asns: List[int] = Field(default_factory=list)
    block_hosting: bool = True         # provider says type=hosting
    block_tor: bool = True             # provider says tor exit / anonymous_proxy
    block_datacenter: bool = True      # provider says type=datacenter/proxy


# 2026-07 — Historical IP reputation cache. When check_ip_for_user()
# resolves an IP through a paying provider, the result is stashed in
# `user_fraud_cache` with a 30-day TTL. Repeat lookups skip the
# provider call entirely (huge quota saving on high-volume RUT jobs)
# and only re-fetch when the cached entry has expired OR the IP was
# marked "clean" but with a very-low score margin (borderline cases
# get re-verified).
_CACHE_TTL_DAYS = 30
_CACHE_REVERIFY_SCORE_MARGIN = 10  # if cached score is within N of threshold, re-verify


# ─── Built-in endpoints per service (used if account.endpoint is blank) ─
_SERVICE_DEFAULT_ENDPOINT = {
    "scamalytics": "https://api11.scamalytics.com/{user}/",
    "ipqualityscore": "https://ipqualityscore.com/api/json/ip/",
    "iphub": "http://v2.api.iphub.info/ip/",
    "proxycheck": "http://proxycheck.io/v2/",
}


# ─── DB helpers ──────────────────────────────────────────────────────
async def _get_settings(user_id: str) -> Dict[str, Any]:
    doc = await _db.user_fraud_settings.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return {"personal_filter_enabled": False, "fallback_to_defaults": True, "min_fraud_score": 75}
    # Backfill default for legacy docs that don't have the field yet.
    doc.setdefault("min_fraud_score", 75)
    return doc


async def _set_settings(user_id: str, settings: FraudSettings) -> None:
    # Clamp the threshold to a safe range so we can't be broken by
    # bad frontend input. 0 = never block on score, 100 = block only
    # on absolute-certain fraud.
    _mfs = int(settings.min_fraud_score)
    if _mfs < 0:
        _mfs = 0
    elif _mfs > 100:
        _mfs = 100
    await _db.user_fraud_settings.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "personal_filter_enabled": settings.personal_filter_enabled,
            "fallback_to_defaults": settings.fallback_to_defaults,
            "min_fraud_score": _mfs,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


# ─── Custom rules ────────────────────────────────────────────────────
async def _get_rules(user_id: str) -> Dict[str, Any]:
    doc = await _db.user_fraud_rules.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return FraudRules().model_dump()
    # Backfill any missing keys from the model default.
    default = FraudRules().model_dump()
    for k, v in default.items():
        doc.setdefault(k, v)
    return doc


async def _set_rules(user_id: str, rules: FraudRules) -> None:
    # Uppercase + strip country codes for consistent matching.
    _allowed = [str(c).strip().upper() for c in rules.allowed_countries if str(c).strip()]
    _blocked = [str(c).strip().upper() for c in rules.blocked_countries if str(c).strip()]
    _asns = [int(a) for a in rules.blocked_asns if isinstance(a, (int, str)) and str(a).strip().isdigit()]
    await _db.user_fraud_rules.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "enabled": bool(rules.enabled),
            "allowed_countries": _allowed,
            "blocked_countries": _blocked,
            "blocked_asns": _asns,
            "block_hosting": bool(rules.block_hosting),
            "block_tor": bool(rules.block_tor),
            "block_datacenter": bool(rules.block_datacenter),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


def _enrich_provider_geo(result: Dict[str, Any]) -> Dict[str, Any]:
    """Fill country/asn/hosting flags from provider raw payloads for custom rules."""
    if not result:
        return result
    raw = result.get("raw") or {}
    if isinstance(raw, dict) and len(raw) == 1:
        only_val = next(iter(raw.values()))
        if isinstance(only_val, dict):
            raw = only_val
    if not result.get("country"):
        result["country"] = str(
            raw.get("country_code")
            or raw.get("countryCode")
            or raw.get("country")
            or result.get("country_code")
            or ""
        ).upper()
    if not result.get("country_code") and result.get("country"):
        result["country_code"] = result["country"]
    if not result.get("asn"):
        asn = raw.get("ASN") or raw.get("asn") or raw.get("as")
        if asn:
            result["asn"] = asn
    ptype = str(raw.get("connection_type") or raw.get("usage_type") or raw.get("type") or "").lower()
    if "hosting" in ptype or raw.get("hosting"):
        result["is_hosting"] = True
    if "datacenter" in ptype or "data center" in ptype:
        result["is_datacenter"] = True
    if raw.get("tor"):
        result["is_tor"] = True
    return result


async def _enrich_geo_for_rules(ip: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill country/ASN via ip-api when providers omit geo fields."""
    result = _enrich_provider_geo(result)
    if (result.get("country") or result.get("country_code")) and result.get("asn"):
        return result
    if not ip:
        return result
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode,as,hosting,proxy,mobile"
            )
            if r.status_code != 200:
                return result
            data = r.json() or {}
            if str(data.get("status") or "").lower() != "success":
                return result
            if not result.get("country"):
                result["country"] = str(data.get("countryCode") or "").upper()
                result["country_code"] = result["country"]
            if not result.get("asn") and data.get("as"):
                result["asn"] = data.get("as")
            if data.get("hosting"):
                result["is_hosting"] = True
            if data.get("proxy"):
                result["is_proxy"] = True
    except Exception:
        pass
    return result


def _apply_rules(result: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    """Post-process a provider result through the user's custom rules.

    Called from check_ip_for_user() right before the result is
    returned. Sets is_vpn=True + annotates vpn_reason when any rule
    matches, so downstream skip_vpn filters block the IP with a
    clear explanation. Never returns None — safe on missing fields.
    """
    if not rules or not rules.get("enabled"):
        return result

    _country = str(result.get("country") or result.get("country_code") or "").upper()
    _asn = result.get("asn") or 0
    try:
        _asn_i = int(str(_asn).replace("AS", "").strip())
    except (TypeError, ValueError):
        _asn_i = 0
    _ptype = str(result.get("proxy_type") or result.get("connection_type") or result.get("type") or "").lower()
    _is_tor = bool(result.get("is_tor") or result.get("tor") or "tor" in _ptype)
    _is_host = bool(result.get("is_hosting") or "hosting" in _ptype)
    _is_dc = bool(result.get("is_datacenter") or "datacenter" in _ptype or "data center" in _ptype)

    reasons: List[str] = []
    allowed = rules.get("allowed_countries") or []
    blocked = rules.get("blocked_countries") or []
    blocked_asns = rules.get("blocked_asns") or []

    if allowed and _country and _country not in allowed:
        reasons.append(f"country {_country} not in allowlist")
    if blocked and _country and _country in blocked:
        reasons.append(f"country {_country} on blocklist")
    if blocked_asns and _asn_i and _asn_i in blocked_asns:
        reasons.append(f"ASN {_asn_i} on blocklist")
    if rules.get("block_tor") and _is_tor:
        reasons.append("Tor exit node")
    if rules.get("block_hosting") and _is_host:
        reasons.append("hosting IP")
    if rules.get("block_datacenter") and _is_dc:
        reasons.append("datacenter IP")

    if reasons:
        result["is_vpn"] = True
        result["risk"] = result.get("risk") or "high"
        result["source"] = f"{result.get('source', '')}+rules"
        result["rule_reasons"] = reasons
        # Prepend to any existing reason so operator sees rule trigger first.
        _prev = result.get("vpn_reason") or ""
        result["vpn_reason"] = f"Blocked by rule: {'; '.join(reasons)}" + (f" | {_prev}" if _prev else "")
    return result


# ─── Historical IP reputation cache ──────────────────────────────────
async def _cache_get(user_id: str, ip: str, min_fraud_score: int) -> Optional[Dict[str, Any]]:
    """Return cached result for this (user_id, ip) if still fresh.

    Re-verify when:
      - Cache is older than _CACHE_TTL_DAYS (Mongo TTL index handles the
        actual eviction; we double-check the timestamp defensively).
      - Cached score is within _CACHE_REVERIFY_SCORE_MARGIN of the current
        threshold (edge cases where a small threshold change could flip
        the decision — safer to re-fetch).
    """
    if not ip:
        return None
    doc = await _db.user_fraud_cache.find_one({"user_id": user_id, "ip": ip}, {"_id": 0})
    if not doc:
        return None
    try:
        _cached_at = datetime.fromisoformat(str(doc.get("cached_at", "")))
        _age = datetime.now(timezone.utc) - _cached_at
        if _age > timedelta(days=_CACHE_TTL_DAYS):
            return None
    except (ValueError, TypeError):
        return None
    _score = int(doc.get("vpn_score", 0) or 0)
    if abs(_score - int(min_fraud_score)) <= _CACHE_REVERIFY_SCORE_MARGIN:
        # Borderline case — re-fetch to avoid stale flip-flop.
        return None
    result = dict(doc)
    result.pop("cached_at", None)
    result.pop("user_id", None)
    result.pop("ip", None)
    result["source"] = f"cache:{result.get('source', 'unknown')}"
    return result


async def _cache_put(user_id: str, ip: str, result: Dict[str, Any]) -> None:
    """Persist a provider result for future lookups.

    Only cache results that came from a REAL provider call — cached
    admin-fallback results have low signal value (free-tier changes
    hourly). Never cache rule-only results (source ends with '+rules'
    with empty base) because those are computed from the rules,
    not from the IP itself.
    """
    if not ip:
        return
    _source = str(result.get("source", "") or "")
    if not _source or _source.startswith("cache:"):
        return  # don't recursively cache
    # We DO cache admin-fallback results but with a shorter effective
    # TTL managed by the caller — MongoDB TTL index applies uniformly.
    payload = {
        "user_id": user_id,
        "ip": ip,
        "is_vpn": bool(result.get("is_vpn", False)),
        "vpn_score": int(result.get("vpn_score", 0) or 0),
        "risk": str(result.get("risk", "") or ""),
        "source": _source,
        "country": str(result.get("country") or result.get("country_code") or ""),
        "asn": result.get("asn"),
        "proxy_type": result.get("proxy_type") or result.get("type"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await _db.user_fraud_cache.update_one(
            {"user_id": user_id, "ip": ip},
            {"$set": payload},
            upsert=True,
        )
    except Exception:
        # Cache write failure must never break the fraud check flow.
        pass


async def _cache_clear(user_id: str) -> int:
    """Delete all cached IP reputation entries for a user. Returns count."""
    r = await _db.user_fraud_cache.delete_many({"user_id": user_id})
    return int(r.deleted_count or 0)


async def _cache_stats(user_id: str) -> Dict[str, Any]:
    """Aggregate cache stats: total, clean, blocked, providers used."""
    coll = _db.user_fraud_cache
    total = await coll.count_documents({"user_id": user_id})
    blocked = await coll.count_documents({"user_id": user_id, "is_vpn": True})
    return {
        "total": total,
        "blocked": blocked,
        "clean": total - blocked,
        "block_rate_pct": round((blocked / total) * 100, 1) if total else 0.0,
    }


async def _list_accounts(user_id: str, service: Optional[str] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"user_id": user_id}
    if service:
        q["service"] = service
    docs = await _db.user_fraud_accounts.find(q, {"_id": 0}).to_list(None)
    docs.sort(key=lambda d: (d.get("priority", 100), d.get("created_at", "")))
    return docs


async def _create_account(user_id: str, data: FraudAccountCreate) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "service": data.service.strip().lower(),
        "account_name": data.account_name.strip() or f"{data.service}-{now.strftime('%H%M%S')}",
        "api_key": data.api_key,
        "api_user": data.api_user,
        "endpoint": data.endpoint.strip(),
        "enabled": bool(data.enabled),
        "priority": int(data.priority),
        "quota_daily": max(0, int(data.quota_daily)),
        "quota_used": 0,
        "quota_reset_at": (now + timedelta(days=1)).isoformat(),
        "rate_limited_until": None,
        "created_at": now.isoformat(),
        "last_used_at": None,
    }
    await _db.user_fraud_accounts.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


async def _update_account(user_id: str, account_id: str, data: FraudAccountUpdate) -> Dict[str, Any]:
    updates = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    res = await _db.user_fraud_accounts.update_one(
        {"id": account_id, "user_id": user_id},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Account not found")
    doc = await _db.user_fraud_accounts.find_one({"id": account_id, "user_id": user_id}, {"_id": 0})
    return doc  # type: ignore


async def _delete_account(user_id: str, account_id: str) -> None:
    res = await _db.user_fraud_accounts.delete_one({"id": account_id, "user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Account not found")


async def _record_usage(user_id: str, account_id: str, ok: bool, rate_limited: bool) -> None:
    now = datetime.now(timezone.utc)
    updates: Dict[str, Any] = {"last_used_at": now.isoformat()}
    if ok:
        updates["$inc"] = {"quota_used": 1}
    if rate_limited:
        updates["rate_limited_until"] = (now + timedelta(minutes=10)).isoformat()

    upd_doc: Dict[str, Any] = {"$set": {"last_used_at": now.isoformat()}}
    if ok:
        upd_doc["$inc"] = {"quota_used": 1}
    if rate_limited:
        upd_doc["$set"]["rate_limited_until"] = (now + timedelta(minutes=10)).isoformat()
    await _db.user_fraud_accounts.update_one(
        {"id": account_id, "user_id": user_id}, upd_doc
    )


def _is_quota_exhausted(acc: Dict[str, Any]) -> bool:
    q = int(acc.get("quota_daily") or 0)
    if q <= 0:
        return False
    used = int(acc.get("quota_used") or 0)
    reset_iso = acc.get("quota_reset_at")
    if reset_iso:
        try:
            reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= reset_dt:
                return False  # reset overdue, treat as fresh
        except Exception:
            pass
    return used >= q


def _is_rate_limited(acc: Dict[str, Any]) -> bool:
    until = acc.get("rate_limited_until")
    if not until:
        return False
    try:
        dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < dt
    except Exception:
        return False


# ─── Per-service HTTP calls ──────────────────────────────────────────
async def _call_scamalytics(ip: str, acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user = acc.get("api_user") or ""
    key = acc.get("api_key") or ""
    if not user or not key:
        return None
    endpoint = acc.get("endpoint") or _SERVICE_DEFAULT_ENDPOINT["scamalytics"].format(user=user)
    url = f"{endpoint.rstrip('/')}/{ip}"
    params = {"key": key}
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url, params=params)
            if r.status_code == 429:
                return {"__rate_limited": True}
            if r.status_code != 200:
                return None
            data = r.json()
            score = int(data.get("score", data.get("fraud_score", 0)) or 0)
            risk = str(data.get("risk", "")).lower()
            is_vpn = score >= 50 or risk in ("high", "very high")
            return {
                "is_vpn": is_vpn,
                "vpn_score": score,
                "risk": "high" if score >= 66 else ("medium" if score >= 33 else "low"),
                "source": f"scamalytics:{acc.get('account_name')}",
                "raw": {"score": score, "risk": risk},
            }
    except Exception as e:
        logger.debug("scamalytics call failed: %s", e)
        return None


async def _call_ipqualityscore(ip: str, acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = acc.get("api_key") or ""
    if not key:
        return None
    endpoint = acc.get("endpoint") or _SERVICE_DEFAULT_ENDPOINT["ipqualityscore"]
    url = f"{endpoint.rstrip('/')}/{key}/{ip}"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url)
            if r.status_code == 429:
                return {"__rate_limited": True}
            if r.status_code != 200:
                return None
            data = r.json()
            score = int(data.get("fraud_score", 0) or 0)
            is_vpn = bool(data.get("vpn") or data.get("proxy") or data.get("tor"))
            return _enrich_provider_geo({
                "is_vpn": is_vpn,
                "vpn_score": score,
                "risk": "high" if score >= 75 else ("medium" if score >= 40 else "low"),
                "source": f"ipqualityscore:{acc.get('account_name')}",
                "country": str(data.get("country_code") or "").upper(),
                "country_code": str(data.get("country_code") or "").upper(),
                "asn": data.get("ASN") or data.get("asn"),
                "is_tor": bool(data.get("tor")),
                "is_hosting": bool(data.get("hosting")),
                "is_datacenter": str(data.get("connection_type") or "").lower() == "datacenter",
                "raw": data,
            })
    except Exception as e:
        logger.debug("ipqualityscore call failed: %s", e)
        return None


async def _call_iphub(ip: str, acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = acc.get("api_key") or ""
    if not key:
        return None
    endpoint = acc.get("endpoint") or _SERVICE_DEFAULT_ENDPOINT["iphub"]
    url = f"{endpoint.rstrip('/')}/{ip}"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url, headers={"X-Key": key})
            if r.status_code == 429:
                return {"__rate_limited": True}
            if r.status_code != 200:
                return None
            data = r.json()
            block = int(data.get("block", 0) or 0)
            score = 100 if block == 2 else (60 if block == 1 else 0)
            return _enrich_provider_geo({
                "is_vpn": block >= 1,
                "vpn_score": score,
                "risk": "high" if block == 2 else ("medium" if block == 1 else "low"),
                "source": f"iphub:{acc.get('account_name')}",
                "country": str(data.get("countryCode") or data.get("country") or "").upper(),
                "country_code": str(data.get("countryCode") or data.get("country") or "").upper(),
                "asn": data.get("asn"),
                "raw": data,
            })
    except Exception as e:
        logger.debug("iphub call failed: %s", e)
        return None


async def _call_proxycheck(ip: str, acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = acc.get("api_key") or ""
    endpoint = acc.get("endpoint") or _SERVICE_DEFAULT_ENDPOINT["proxycheck"]
    url = f"{endpoint.rstrip('/')}/{ip}"
    params: Dict[str, Any] = {"vpn": 1, "risk": 1}
    if key:
        params["key"] = key
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url, params=params)
            if r.status_code == 429:
                return {"__rate_limited": True}
            if r.status_code != 200:
                return None
            data = r.json()
            entry = data.get(ip) or {}
            proxy = str(entry.get("proxy", "no")).lower() == "yes"
            risk = int(entry.get("risk", 0) or 0)
            score = risk if risk else (100 if proxy else 0)
            return _enrich_provider_geo({
                "is_vpn": proxy or risk >= 66,
                "vpn_score": score,
                "risk": "high" if score >= 66 else ("medium" if score >= 33 else "low"),
                "source": f"proxycheck:{acc.get('account_name')}",
                "country": str(entry.get("country") or entry.get("isocode") or "").upper(),
                "country_code": str(entry.get("isocode") or entry.get("country") or "").upper(),
                "asn": entry.get("asn"),
                "raw": entry,
            })
    except Exception as e:
        logger.debug("proxycheck call failed: %s", e)
        return None


_SERVICE_CALLERS = {
    "scamalytics": _call_scamalytics,
    "ipqualityscore": _call_ipqualityscore,
    "iphub": _call_iphub,
    "proxycheck": _call_proxycheck,
}


# ─── Core public function ────────────────────────────────────────────
async def check_ip_for_user(user_id: str, ip: str) -> Dict[str, Any]:
    """
    Fraud-check `ip` respecting the user's personal fraud settings.

    Fallback chain:
      1. If personal_filter_enabled == False → delegate to existing
         admin-level check_vpn_detailed(ip)  (existing behavior).
      2. If enabled but no accounts → same delegate  (safe default).
      3. Otherwise walk through user's enabled accounts sorted by
         priority; skip quota-exhausted / rate-limited; return the
         FIRST successful result. If all fail and
         fallback_to_defaults == True → delegate to existing check.
      4. If fallback disabled and all fail → return neutral "unknown".
    """
    settings = await _get_settings(user_id)
    _threshold = int(settings.get("min_fraud_score", 75))
    _rules = await _get_rules(user_id)

    def _apply_threshold(res: Dict[str, Any]) -> Dict[str, Any]:
        try:
            _score = int(res.get("vpn_score") or 0)
        except (TypeError, ValueError):
            _score = 0
        if _score >= _threshold and not res.get("is_vpn"):
            res["is_vpn"] = True
            res["risk"] = res.get("risk") or "high"
            res["source"] = f"{res.get('source', 'user-account')}:threshold({_threshold})"
        res["min_fraud_score"] = _threshold
        return res

    async def _finalize(res: Dict[str, Any]) -> Dict[str, Any]:
        res = await _enrich_geo_for_rules(ip, res)
        res = _apply_threshold(res)
        res = _apply_rules(res, _rules)
        await _cache_put(user_id, ip, res)
        return res

    # Custom rules can run even when personal premium providers are OFF.
    if not settings.get("personal_filter_enabled"):
        res = await _existing_check_vpn(ip)
        return await _finalize(res)

    # 2026-07 — historical cache lookup FIRST. Saves provider quota
    # dramatically on repeat visits (RUT jobs often hit same IPs).
    _threshold_for_cache = int(settings.get("min_fraud_score", 75))
    cached = await _cache_get(user_id, ip, _threshold_for_cache)
    if cached is not None:
        cached["min_fraud_score"] = _threshold
        cached = await _enrich_geo_for_rules(ip, cached)
        cached = _apply_threshold(cached)
        return _apply_rules(cached, _rules)

    accounts = await _list_accounts(user_id)
    usable = [a for a in accounts if a.get("enabled") and not _is_quota_exhausted(a) and not _is_rate_limited(a)]

    if not usable:
        if settings.get("fallback_to_defaults", True):
            res = await _existing_check_vpn(ip)
            res["source"] = f"admin-fallback:{res.get('source','')}"
            return await _finalize(res)
        return _apply_rules({"is_vpn": False, "vpn_score": 0, "risk": "unknown", "source": "user-fallback-disabled", "min_fraud_score": _threshold}, _rules)

    for acc in usable:
        service = acc.get("service", "")
        caller = _SERVICE_CALLERS.get(service)
        if not caller:
            continue
        result = await caller(ip, acc)
        if result and result.get("__rate_limited"):
            await _record_usage(user_id, acc["id"], ok=False, rate_limited=True)
            continue
        if result:
            await _record_usage(user_id, acc["id"], ok=True, rate_limited=False)
            return await _finalize(result)

    # All accounts failed
    if settings.get("fallback_to_defaults", True):
        res = await _existing_check_vpn(ip)
        res["source"] = f"admin-fallback:{res.get('source','')}"
        return await _finalize(res)
    return _apply_rules({"is_vpn": False, "vpn_score": 0, "risk": "unknown", "source": "all-accounts-failed", "min_fraud_score": _threshold}, _rules)


# ─── Router factory ──────────────────────────────────────────────────
def init_router(main_db, existing_check_vpn_fn: Callable[[str], Awaitable[Dict[str, Any]]],
                get_current_user_dep) -> APIRouter:
    """
    Called from server.py after startup. Wires the module state and
    returns an APIRouter that MUST be included with `/api` prefix.
    """
    global _db, _existing_check_vpn, _get_current_user_dep
    _db = main_db
    _existing_check_vpn = existing_check_vpn_fn
    _get_current_user_dep = get_current_user_dep

    router = APIRouter(prefix="/fraud", tags=["fraud"])

    @router.get("/settings")
    async def get_settings(user=Depends(_get_current_user_dep)):
        return await _get_settings(user["id"])

    @router.put("/settings")
    async def update_settings(body: FraudSettings, user=Depends(_get_current_user_dep)):
        await _set_settings(user["id"], body)
        return await _get_settings(user["id"])

    @router.get("/accounts")
    async def list_accounts(service: Optional[str] = None, user=Depends(_get_current_user_dep)):
        return await _list_accounts(user["id"], service)

    @router.post("/accounts")
    async def create_account(body: FraudAccountCreate, user=Depends(_get_current_user_dep)):
        return await _create_account(user["id"], body)

    @router.put("/accounts/{account_id}")
    async def update_account(account_id: str, body: FraudAccountUpdate, user=Depends(_get_current_user_dep)):
        return await _update_account(user["id"], account_id, body)

    @router.delete("/accounts/{account_id}")
    async def delete_account(account_id: str, user=Depends(_get_current_user_dep)):
        await _delete_account(user["id"], account_id)
        return {"ok": True}

    @router.post("/accounts/{account_id}/test")
    async def test_account(account_id: str, body: Dict[str, Any] = Body(default={}),
                           user=Depends(_get_current_user_dep)):
        """Quick health-check: run this account against `1.1.1.1` (or user-provided ip)."""
        ip = str(body.get("ip") or "1.1.1.1")
        acc = await _db.user_fraud_accounts.find_one({"id": account_id, "user_id": user["id"]}, {"_id": 0})
        if not acc:
            raise HTTPException(404, "Account not found")
        caller = _SERVICE_CALLERS.get(acc.get("service"))
        if not caller:
            return {"ok": False, "reason": f"unsupported service: {acc.get('service')}"}
        result = await caller(ip, acc)
        if result and result.get("__rate_limited"):
            return {"ok": False, "reason": "rate limited"}
        if result:
            return {"ok": True, "result": result}
        return {"ok": False, "reason": "no response / auth failed"}

    @router.get("/services")
    async def list_services():
        """Static list of supported services + how many accounts the user has each."""
        return {
            "services": [
                {"key": "scamalytics", "name": "Scamalytics", "needs_user": True,
                 "signup_url": "https://scamalytics.com/ip/api"},
                {"key": "ipqualityscore", "name": "IPQualityScore", "needs_user": False,
                 "signup_url": "https://www.ipqualityscore.com/create-account"},
                {"key": "iphub", "name": "IPHub", "needs_user": False,
                 "signup_url": "https://iphub.info/register"},
                {"key": "proxycheck", "name": "ProxyCheck.io", "needs_user": False,
                 "signup_url": "https://proxycheck.io/dashboard/"},
            ]
        }

    # ─── Custom rules ─────────────────────────────────────────────
    @router.get("/rules")
    async def get_rules(user=Depends(_get_current_user_dep)):
        return await _get_rules(user["id"])

    @router.put("/rules")
    async def update_rules(body: FraudRules, user=Depends(_get_current_user_dep)):
        await _set_rules(user["id"], body)
        return await _get_rules(user["id"])

    # ─── Historical IP reputation cache ──────────────────────────
    @router.get("/cache/stats")
    async def cache_stats(user=Depends(_get_current_user_dep)):
        return await _cache_stats(user["id"])

    @router.get("/cache")
    async def list_cache(limit: int = 100, blocked_only: bool = False,
                         user=Depends(_get_current_user_dep)):
        """List recent cached IP reputation entries for review/audit."""
        q: Dict[str, Any] = {"user_id": user["id"]}
        if blocked_only:
            q["is_vpn"] = True
        docs = await _db.user_fraud_cache.find(q, {"_id": 0, "user_id": 0}) \
            .sort("cached_at", -1).limit(max(1, min(500, int(limit)))).to_list(None)
        return {"items": docs, "count": len(docs)}

    @router.delete("/cache")
    async def clear_cache(user=Depends(_get_current_user_dep)):
        deleted = await _cache_clear(user["id"])
        return {"ok": True, "deleted": deleted}

    @router.delete("/cache/{ip}")
    async def clear_one(ip: str, user=Depends(_get_current_user_dep)):
        r = await _db.user_fraud_cache.delete_one({"user_id": user["id"], "ip": ip})
        return {"ok": True, "deleted": int(r.deleted_count or 0)}

    # ─── MongoDB TTL index (auto-expire cache entries after 30d) ─
    # Guarded so we don't crash on re-init (Motor throws if index
    # exists with a different expireAfterSeconds).
    async def _ensure_indexes():
        try:
            await _db.user_fraud_cache.create_index(
                [("cached_at", 1)],
                expireAfterSeconds=_CACHE_TTL_DAYS * 86400,
                name="ttl_cached_at",
            )
        except Exception as _ie:
            logger.debug(f"[fraud] TTL index already exists or failed: {_ie}")
        try:
            await _db.user_fraud_cache.create_index(
                [("user_id", 1), ("ip", 1)],
                unique=True,
                name="uniq_user_ip",
            )
        except Exception:
            pass

    # Kick off index creation in background (non-blocking startup).
    import asyncio as _asyncio
    try:
        _loop = _asyncio.get_event_loop()
        _loop.create_task(_ensure_indexes())
    except Exception:
        pass

    logger.info("Fraud provider module wired — /api/fraud/*")
    return router
