"""
proxy_provider_module.py — Multi-provider proxy source manager
════════════════════════════════════════════════════════════════════════

Every customer can add multiple proxy providers of 4 kinds:
  1. rotating_gateway  — single sticky/rotating gateway (e.g. Bright Data,
                          Oxylabs, Soax, IPRoyal Gateway).
                          Config: gateway_host, gateway_port, username,
                                  password, proxy_type (http/https/socks5)
  2. api_endpoint      — an API that returns a fresh proxy on demand
                          (SmartProxy, Webshare, custom).
                          Config: api_url, method (GET/POST), headers,
                                  body_json, response_path (JSON key
                                  or regex to pluck the proxy from response),
                                  proxy_type
  3. manual_list       — user-uploaded list of static proxies (one per line).
                          Config: lines: List[str], proxy_type
  4. native_proxyjet   — Krexion's built-in ProxyJet with per-provider
                          country + state overrides (existing engine).
                          Config: country, state (optional), gateway (opt)

Anywhere in the app that currently accepts a `proxy` param can now
accept `proxy_provider_id` instead — the caller resolves it via
`get_proxy_from_provider(user_id, provider_id)`.

BACKWARD COMPAT
───────────────
- 100% opt-in. If the customer never adds any providers, every legacy
  path (RUT, Browser Profile launch, Click Proxy, CPI Job, ProxiesPage
  bulk test) uses its existing default flow.
- The dropdown always includes a "(default — existing behavior)" option
  which resolves to None → legacy path.
"""
from __future__ import annotations

import re
import uuid
import json
import random
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger("proxy_provider_module")

_db = None
_get_current_user_dep = None

SUPPORTED_KINDS = ("rotating_gateway", "api_endpoint", "manual_list", "native_proxyjet")
SUPPORTED_TYPES = ("http", "https", "socks5", "socks5h", "socks4")


# ─── Pydantic Models ─────────────────────────────────────────────────
class ProxyProviderCreate(BaseModel):
    name: str
    kind: str  # one of SUPPORTED_KINDS
    proxy_type: str = "http"  # http|https|socks5|socks5h|socks4
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class ProxyProviderUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    proxy_type: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


# ─── DB helpers ──────────────────────────────────────────────────────
async def _list(user_id: str) -> List[Dict[str, Any]]:
    docs = await _db.user_proxy_providers.find({"user_id": user_id}, {"_id": 0}).to_list(None)
    docs.sort(key=lambda d: (0 if d.get("enabled") else 1, d.get("created_at", "")))
    return docs


async def _get(user_id: str, provider_id: str) -> Optional[Dict[str, Any]]:
    return await _db.user_proxy_providers.find_one(
        {"id": provider_id, "user_id": user_id}, {"_id": 0}
    )


def _sanitize_provider_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Strip whitespace from gateway credential fields before persisting."""
    if not config:
        return {}
    cfg = dict(config)
    for key in ("gateway_host", "gateway_port", "username", "password"):
        if key in cfg and cfg[key] is not None:
            cfg[key] = str(cfg[key]).strip()
    return cfg


async def _create(user_id: str, data: ProxyProviderCreate) -> Dict[str, Any]:
    if data.kind not in SUPPORTED_KINDS:
        raise HTTPException(400, f"kind must be one of {SUPPORTED_KINDS}")
    if data.proxy_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"proxy_type must be one of {SUPPORTED_TYPES}")

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": data.name.strip() or f"{data.kind}-{now[-8:]}",
        "kind": data.kind,
        "proxy_type": data.proxy_type,
        "enabled": bool(data.enabled),
        "config": _sanitize_provider_config(data.config or {}),
        "created_at": now,
        "last_used_at": None,
        "use_count": 0,
    }
    await _db.user_proxy_providers.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


async def _update(user_id: str, provider_id: str, data: ProxyProviderUpdate) -> Dict[str, Any]:
    updates = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    if "kind" in updates and updates["kind"] not in SUPPORTED_KINDS:
        raise HTTPException(400, f"kind must be one of {SUPPORTED_KINDS}")
    if "proxy_type" in updates and updates["proxy_type"] not in SUPPORTED_TYPES:
        raise HTTPException(400, f"proxy_type must be one of {SUPPORTED_TYPES}")
    if "config" in updates:
        new_cfg = _sanitize_provider_config(updates["config"] or {})
        existing = await _get(user_id, provider_id)
        old_cfg = (existing or {}).get("config") or {}
        if not str(new_cfg.get("password") or "").strip():
            old_pwd = str(old_cfg.get("password") or "").strip()
            if old_pwd:
                new_cfg["password"] = old_pwd
        updates["config"] = new_cfg
    res = await _db.user_proxy_providers.update_one(
        {"id": provider_id, "user_id": user_id},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Provider not found")
    doc = await _get(user_id, provider_id)
    return doc  # type: ignore


async def _delete(user_id: str, provider_id: str) -> None:
    res = await _db.user_proxy_providers.delete_one({"id": provider_id, "user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Provider not found")


# ─── Proxy string resolver ───────────────────────────────────────────

# 2026-07 v2.5.3 — Session token auto-rotation for Rotating Gateway.
# Popular residential/rotating gateway providers embed a session id in
# the username. Keeping the same session id → the gateway returns the
# SAME sticky IP on every connection. To get a fresh IP per visit,
# the session id must change. We auto-detect the common patterns so
# customers don't have to add {sid} placeholders manually.
#
# Supported tokens (case-insensitive, match the numeric/alnum value
# right after the token name, up to the next '-' or '_'):
#   -session-XXXX          (Bright Data, BestGo, IPRoyal, SmartProxy)
#   -sessid-XXXX           (Oxylabs alternate)
#   -sessionid-XXXX        (Soax)
#   -sess-XXXX             (short-form)
#   -sessionduration-XXX   (NOT rotated — this is duration, not id)
# Placeholder overrides:
#   {sid}  → replaced with a fresh random id per line
_SESSION_TOKEN_RE = re.compile(
    r"(-(?:session(?:id)?|sessid|sess)-)([A-Za-z0-9]+)",
    re.IGNORECASE,
)
# DataImpulse (and similar) use `;sessid.XXXX` / `__sessid.XXXX`, not `-sessid-`.
_DOT_SESSID_ROTATE_RE = re.compile(
    r"((?:;|__)(?:sessid|sessionid)\.)([A-Za-z0-9]+)",
    re.IGNORECASE,
)
_DOT_SESSID_STRIP_RE = re.compile(
    r"(?:;|__)(?:sessid|sessionid)\.[A-Za-z0-9_{}]+",
    re.IGNORECASE,
)
_DOT_TTL_STRIP_RE = re.compile(
    r"(?:;|__)sessttl\.[A-Za-z0-9]+",
    re.IGNORECASE,
)
# Smartproxy Smart Region panel (proxy.smartproxy.net) — underscore DSL:
#   smart-{subid}_area-US_state-california_life-120_session-{id}
_SMARTPROXY_SMART_SESSION_RE = re.compile(r"(_session-)([A-Za-z0-9]+)", re.IGNORECASE)
_SMARTPROXY_SMART_PARAM_RES = (
    ("area", re.compile(r"_area-[A-Za-z0-9]+", re.IGNORECASE)),
    ("state", re.compile(r"_state-[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE)),
    ("city", re.compile(r"_city-[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE)),
    ("asn", re.compile(r"_asn-[A-Za-z0-9]+", re.IGNORECASE)),
    ("life", re.compile(r"_life-[0-9]+", re.IGNORECASE)),
    ("session", _SMARTPROXY_SMART_SESSION_RE),
)

# Smartproxy Smart Region — panel (proxy.smartproxy.net):
#   state-California · state-NewYork · city-NewYork · area-US · life-120
# Multi-word states use PascalCase (no underscores), matching the panel.
_SMARTPROXY_SMART_PROFILE: Dict[str, Any] = {
    "name": "Smartproxy Smart Region",
    "hosts": ["smartproxy.net", "smartproxy.com"],
    "dsl": "smart_underscore",
    "state_fmt": "{pascal}",
    "default_life_minutes": 120,
    "preferred_ports": ("3120", "3128", "7000"),
}


def _is_smartproxy_smart_username(username: str) -> bool:
    u = (username or "").lower()
    return u.startswith("smart-") or "_area-" in u or "_state-" in u


def _strip_smartproxy_smart_params(username: str, *, keep_life: bool = False) -> str:
    """Strip Smart Region geo/session tokens from a smart-* username."""
    if not username:
        return username
    out = username
    # Strip session + life BEFORE state so `_state-california_life` is never matched.
    out = _SMARTPROXY_SMART_SESSION_RE.sub("", out, count=1)
    if not keep_life:
        out = re.sub(r"_life-[0-9]+", "", out, flags=re.IGNORECASE)
    for pat in (
        re.compile(r"_city-[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE),
        re.compile(r"_state-[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE),
        re.compile(r"_area-[A-Za-z0-9]+", re.IGNORECASE),
        re.compile(r"_asn-[A-Za-z0-9]+", re.IGNORECASE),
    ):
        out = pat.sub("", out)
    return out


def _extract_smartproxy_life_minutes(username: str) -> int:
    m = re.search(r"_life-([0-9]+)", username or "", re.IGNORECASE)
    if m:
        try:
            return max(1, int(m.group(1)))
        except ValueError:
            pass
    return int(_SMARTPROXY_SMART_PROFILE.get("default_life_minutes") or 120)


def _make_smart_session_id() -> str:
    """Alphanumeric session id matching Smartproxy panel (e.g. vMPdPfj97)."""
    import string
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(9))


def _smartproxy_smart_base(username: str) -> str:
    """Account id only: smart-u0h51gc8hmdw (no _area/_state/_life/_session suffix)."""
    u = username or ""
    for marker in ("_area-", "_state-", "_city-", "_life-", "_session-"):
        idx = u.lower().find(marker)
        if idx > 0:
            return u[:idx]
    return u


def _normalize_smartproxy_smart_account_base(username: str) -> str:
    """Smart Region accounts must use smart-* — not legacy user-* on .net gateways."""
    base = _smartproxy_smart_base(_strip_smartproxy_smart_params(username or ""))
    low = base.lower().strip()
    if low.startswith("user-") and not low.startswith("smart-"):
        return "smart-" + base.split("-", 1)[1]
    return base


def _extract_embedded_gateway_targeting(username: str) -> Dict[str, Any]:
    """Read country/state/life hints embedded in a gateway username string."""
    out: Dict[str, Any] = {}
    u = username or ""
    m = re.search(r"_area-([A-Za-z0-9]+)", u, re.I)
    if m:
        out["country"] = m.group(1).upper()
    m = re.search(r"_state-([a-z0-9]+(?:_[a-z0-9]+)*)", u, re.I)
    if m:
        out["state_slug"] = m.group(1).lower()
    m = re.search(r"_life-([0-9]+)", u, re.I)
    if m:
        try:
            out["sticky_minutes"] = int(m.group(1))
        except ValueError:
            pass
    return out


def _state_targeting_variants(
    state_code: str,
    profile: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Ordered state values to try when a gateway rejects geo targeting."""
    raw = (state_code or "").strip()
    st = _state_code(raw) or raw.upper()
    if not st:
        return [""]
    variants: List[str] = []
    if profile:
        primary = _format_state_for_profile(profile, st)
        if primary:
            variants.append(primary)
        # Smart Region panel accepts Title Case first (state-California).
        if profile.get("dsl") == "smart_underscore":
            for extra in (
                _state_pascal(st),
                _state_title(st),
                _state_slug(st),
                _state_code(st),
            ):
                if extra and extra not in variants:
                    variants.append(extra)
        else:
            slug = _state_slug(st)
            code = _state_code(st)
            for extra in (slug, code, code.lower() if code else "", raw):
                if extra and extra not in variants:
                    variants.append(extra)
            if profile.get("state_fmt") == "us_{slug}" and slug:
                us_slug = f"us_{slug}" if not slug.startswith("us_") else slug
                if us_slug not in variants:
                    variants.append(us_slug)
    else:
        variants.append(st)
        for extra in (_state_title(st), _state_slug(st)):
            if extra and extra not in variants:
                variants.append(extra)
    out: List[str] = []
    seen: set = set()
    for v in variants:
        key = str(v or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(v).strip())
    return out or [st]


def _expected_state_tokens_in_username(
    state_code: str,
    profile: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Lowercase tokens that may appear in a correctly targeted gateway username."""
    st = _state_code(state_code) or (state_code or "").strip().upper()
    if not st:
        return []
    tokens: List[str] = []
    for val in _state_targeting_variants(st, profile):
        tok = str(val or "").strip().lower()
        if tok and tok not in tokens:
            tokens.append(tok)
    slug = _state_slug(st)
    if slug and slug not in tokens:
        tokens.append(slug)
    code = _state_code(st)
    if code and code.lower() not in tokens:
        tokens.append(code.lower())
    if code and code not in tokens:
        tokens.append(code)
    return tokens


def _username_includes_state_target(
    username: str,
    host: str,
    state_code: str,
    *,
    state_literal: str = "",
) -> bool:
    """True when the gateway username encodes the requested US state."""
    st = _state_code(state_code) or (state_code or "").strip().upper()
    if not st:
        return True
    u = (username or "").lower()
    if not u:
        return False
    profile = _detect_profile(host or "", "", username or "")
    tokens = _expected_state_tokens_in_username(st, profile)
    if state_literal:
        lit = str(state_literal).strip().lower()
        if lit and lit not in tokens:
            tokens.insert(0, lit)
    if not tokens:
        return False
    if profile and profile.get("dsl") == "smart_underscore":
        return any(f"_state-{t}" in u for t in tokens if t)
    if profile:
        pk = (profile.get("keys") or {}).get("state") or "state"
        kv = profile.get("kv") or "-"
        prefix = profile.get("prefix") or ""
        delim = profile.get("delim") or ""
        for t in tokens:
            if not t:
                continue
            needles = [
                f"_state-{t}",
                f"{pk}{kv}{t}",
                f"{prefix}{pk}{kv}{t}",
                f"{delim}{pk}{kv}{t}",
                f"__{pk}.{t}",
                f";{pk}-{t}",
                f"-{pk}-{t}",
            ]
            if any(n in u for n in needles):
                return True
        return False
    return any(t in u for t in tokens if t)


def _apply_smartproxy_smart_targeting(
    username_base: str,
    targeting: Dict[str, Any],
    *,
    original_username: str = "",
) -> str:
    """Build smart-…_area-US_state-California_life-120_session-{sid} (panel DSL)."""
    profile = _SMARTPROXY_SMART_PROFILE
    base = _normalize_smartproxy_smart_account_base(username_base)
    parts: List[str] = []
    country = str(targeting.get("country") or "US").strip().upper() or "US"
    parts.append(f"_area-{country}")
    state_val = targeting.get("state")
    if state_val:
        # Sheet codes (CA) → panel Title Case (California).
        # Variant rotation may already pass California / california / NewYork.
        raw = str(state_val).strip()
        st_code = _state_code(raw)
        if not raw:
            token = ""
        elif len(raw) <= 2 or (st_code and raw.upper() == st_code):
            token = _format_state_for_profile(profile, st_code or raw)
        else:
            token = raw.replace(" ", "_")
        if token:
            parts.append(f"_state-{token}")
    city_val = targeting.get("city")
    if city_val:
        parts.append(f"_city-{_format_smartproxy_city(str(city_val))}")
    life = targeting.get("sticky_minutes")
    if not life:
        life = _extract_smartproxy_life_minutes(original_username or username_base)
    parts.append(f"_life-{int(life)}")
    if targeting.get("_want_sid") or targeting.get("session_mode", "sticky") == "sticky":
        parts.append("_session-{sid}")
    return base + "".join(parts)


def _make_session_id() -> str:
    """Generate a fresh random session id (8-digit numeric — matches
    the format BestGo/Bright Data/IPRoyal accept)."""
    return str(random.randint(10**7, 10**9 - 1))


def _strip_provider_session(username: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """Remove embedded session tokens so ROW-FIRST can inject a fresh one."""
    if not username:
        return username
    out = username.replace("{sid}", "")
    if (profile or {}).get("dsl") == "smart_underscore" or _is_smartproxy_smart_username(out):
        out = _SMARTPROXY_SMART_SESSION_RE.sub("", out, count=1)
    if _SESSION_TOKEN_RE.search(out):
        out = _SESSION_TOKEN_RE.sub("", out, count=1)
    if profile:
        delim = str(profile.get("delim") or "-")
        prefix = str(profile.get("prefix") or "")
        kv = str(profile.get("kv") or "-")
        seps: List[str] = []
        for sep in (prefix, delim):
            if sep and sep not in seps:
                seps.append(sep)
        if seps:
            sep_alt = "|".join(re.escape(s) for s in seps)
            for key_name in ("sid_key", "ttl_key"):
                pk = profile.get(key_name)
                if not pk:
                    continue
                pat = (
                    rf"(?:{sep_alt}){re.escape(str(pk))}"
                    rf"{re.escape(kv)}[A-Za-z0-9_{{}}]+"
                )
                out = re.sub(pat, "", out, flags=re.IGNORECASE)
    out = _DOT_SESSID_STRIP_RE.sub("", out)
    out = _DOT_TTL_STRIP_RE.sub("", out)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    out = re.sub(r";{2,}", ";", out).strip(";")
    return out


def _strip_legacy_gateway_geo(username: str) -> str:
    """Strip pasted geo/session tokens from ANY gateway username (mixed formats)."""
    out = username or ""
    if not out:
        return out
    for pat in (
        r"-country-[a-z0-9]+",
        r"-state-[a-z0-9_]+",
        r"-city-[a-z0-9_]+",
        r"-region-[a-z0-9_]+",
        r"-cc-[a-z0-9]+",
        r"-st-[a-z0-9_]+",
        r"-session(?:duration)?-[a-z0-9]+",
        r"-sessid-[a-z0-9]+",
        r"-sesstime-[a-z0-9]+",
        r"-sessttl-[a-z0-9]+",
        r";country-[a-z0-9]+",
        r";region-[a-z0-9_]+",
        r";sessionid-[a-z0-9]+",
        r"__cr\.[a-z0-9]+",
        r";st\.[a-z0-9]+",
        r";state\.[a-z0-9_]+",
        r";city\.[a-z0-9_]+",
        r"(?:;|__)sessid\.[A-Za-z0-9_{}]+",
        r"(?:;|__)sessionid\.[A-Za-z0-9_{}]+",
        r"(?:;|__)sessttl\.[A-Za-z0-9]+",
    ):
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    out = re.sub(r";{2,}", ";", out).strip(";")
    return out


def _strip_provider_geo_params(username: str, profile: Optional[Dict[str, Any]]) -> str:
    """Strip country/state/city/zip/asn tokens from a gateway username."""
    if not username:
        return username
    if (profile or {}).get("dsl") == "smart_underscore" or (
        not profile and _is_smartproxy_smart_username(username)
    ):
        return _strip_smartproxy_smart_params(username, keep_life=False)
    if not profile:
        return username
    out = username
    prefix = profile.get("prefix") or ""
    delim = profile.get("delim") or "-"
    kv = profile.get("kv") or "-"
    for key in ("country", "state", "city", "zip", "asn"):
        pk = (profile.get("keys") or {}).get(key)
        if not pk:
            continue
        # Provider DSL token, e.g. -state-us_california or __st.ca (DataImpulse)
        pat = (
            rf"(?:{re.escape(prefix)}|{re.escape(delim)})"
            rf"{re.escape(pk)}{re.escape(kv)}[A-Za-z0-9_]+"
        )
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    for key in ("country", "state", "city", "zip", "asn"):
        out = re.sub(rf"[;,\-_]?\{{{key}\}}", "", out, flags=re.IGNORECASE)
    out = re.sub(r"-{2,}", "-", out).strip("-")
    return out


def _ensure_provider_user_prefix(username: str, profile: Optional[Dict[str, Any]]) -> str:
    """Decodo legacy gate usernames start with user-; Smart Region uses smart-."""
    if not username or not profile:
        return username
    if profile.get("dsl") == "smart_underscore" or username.lower().startswith("smart-"):
        return username
    if profile.get("name") != "Smartproxy / Decodo":
        return username
    low = username.lower()
    if low.startswith("user-"):
        return username
    return f"user-{username}"


def _gateway_base_username(
    username: str,
    gateway_host: str,
    provider_name: str = "",
) -> str:
    """Return a clean gateway username (no geo/session) for ROW-FIRST rebuilds."""
    profile = _detect_profile(gateway_host or "", provider_name, username)
    out = _strip_legacy_gateway_geo(username)
    if profile and profile.get("dsl") == "smart_underscore":
        out = _normalize_smartproxy_smart_account_base(out)
        out = _strip_smartproxy_smart_params(out)
    else:
        out = _strip_provider_session(out, profile)
        out = _strip_provider_geo_params(out, profile)
    out = _ensure_provider_user_prefix(out, profile)
    return out


def _rotate_session_in_username(username: str) -> str:
    """Return `username` with any embedded session token replaced by a
    fresh random id. If no known token is present:
      • honour `{sid}` placeholder if the user added one manually
      • otherwise return the string unchanged (caller may still emit
        multiple identical lines — the gateway may rotate on its own
        without a session param, e.g. per-connect rotation providers).
    """
    if not username:
        return username
    if "{sid}" in username:
        sid = _make_smart_session_id() if _is_smartproxy_smart_username(username) else _make_session_id()
        return username.replace("{sid}", sid)
    if _SMARTPROXY_SMART_SESSION_RE.search(username):
        return _SMARTPROXY_SMART_SESSION_RE.sub(
            lambda m: f"{m.group(1)}{_make_smart_session_id()}",
            username,
            count=1,
        )
    if _SESSION_TOKEN_RE.search(username):
        return _SESSION_TOKEN_RE.sub(
            lambda m: f"{m.group(1)}{_make_session_id()}",
            username,
            count=1,
        )
    if _DOT_SESSID_ROTATE_RE.search(username):
        return _DOT_SESSID_ROTATE_RE.sub(
            lambda m: f"{m.group(1)}{_make_session_id()}",
            username,
            count=1,
        )
    return username


# ─── Provider-aware targeting profiles (2026-07 v2.6.3) ──────────────
# Every rotating-gateway provider uses its own username DSL for geo /
# session targeting. To let ANY provider be targeted from a single
# universal UI (country / state / city / zip / ASN / session TTL /
# session ID), we detect the provider from its gateway hostname and
# apply the matching syntax when the customer picks values in the
# on-demand generator.
#
# For unknown providers OR when the customer prefers manual control,
# `{country}`, `{state}`, `{city}`, `{zip}`, `{asn}`, `{ttl}`, `{sid}`
# placeholders in the saved username template are substituted from the
# targeting overrides. Placeholders always win over auto-detection.
#
# Sources for each provider's DSL:
#   • DataImpulse:  docs.dataimpulse.com/proxies/parameters
#   • Bright Data:  docs.brightdata.com   (`-country-us-state-fl-city-…`)
#   • Oxylabs:      developers.oxylabs.io (`-cc-us-st-california-city-…`)
#   • Smartproxy:   help.smartproxy.com  (`-country-us-city-newyork-…`)
#   • IPRoyal:      docs.iproyal.com     (`_country-us_state-florida_…`)
#   • ProxyEmpire:  docs.proxyempire.io  (`-country-us-region-fl-city-…`)
#   • Soax:         docs.soax.com        (`country-us;region-florida;city-…`)
#   • PacketStream: packetstream.io/docs (`_country-UnitedStates_state-FL`)
#
# Each profile is a dict: sep=(prefix, kv_sep), keys={country:'cr',...}
# meaning: prefix param starts with '__' or '-', each key is joined
# using kv_sep. Session id key + session ttl key differ per provider.
#
# `state_fmt` controls how a sheet STATE value (CA / California) is
# encoded in the gateway username. Tokens: {slug}=california/new_york,
# {code}=CA, {code_lower}=ca. Special: us_{slug}=us_california (Decodo).

_PROVIDER_PROFILES: List[Dict[str, Any]] = [
    {
        "name": "DataImpulse",
        "hosts": ["dataimpulse.com"],
        "prefix": "__",          # first param separator (from login)
        "delim": ";",             # between params
        "kv": ".",                # key.value
        "keys": {
            "country": "cr", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{slug}",
        "sid_key": "sessid",
        "ttl_key": "sessttl",     # minutes
        "ttl_unit": "min",
    },
    {
        "name": "Bright Data",
        "hosts": ["brd.superproxy.io", "brdcorp.com", "luminati.io", "lum-superproxy.io"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",                # key-value (single dash between key and value token)
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{slug}",
        "sid_key": "session",
        "ttl_key": None,          # Bright Data configures TTL in dashboard, not URL
        "ttl_unit": None,
    },
    {
        "name": "Oxylabs",
        "hosts": ["oxylabs.io", "pr.oxylabs.io"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",
        "keys": {
            "country": "cc", "state": "st", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{slug}",
        "sid_key": "sessid",
        "ttl_key": "sesstime",    # minutes
        "ttl_unit": "min",
    },
    {
        "name": "Smartproxy / Decodo",
        "hosts": ["smartproxy.com", "smartproxy.net", "decodo.com", "smart-proxy.com"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "us_{slug}",
        "sid_key": "session",
        "ttl_key": "sessionduration",   # minutes
        "ttl_unit": "min",
    },
    {
        "name": "IPRoyal",
        "hosts": ["iproyal.com"],
        "prefix": "_",
        "delim": "_",
        "kv": "-",
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{slug}",
        "sid_key": "session",
        "ttl_key": "lifetime",     # minutes
        "ttl_unit": "min",
    },
    {
        "name": "ProxyEmpire",
        "hosts": ["proxyempire.io"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",
        "keys": {
            "country": "country", "state": "region", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{code_lower}",
        "sid_key": "session",
        "ttl_key": "lifetime",
        "ttl_unit": "min",
    },
    {
        "name": "Soax",
        "hosts": ["soax.com"],
        "prefix": ";",           # Soax uses semicolon prefix
        "delim": ";",
        "kv": "-",
        "keys": {
            "country": "country", "state": "region", "city": "city",
            "zip": "zip", "asn": "isp",
        },
        "state_fmt": "{slug}",
        "sid_key": "sessionid",
        "ttl_key": "sessionlength",
        "ttl_unit": "sec",         # Soax uses seconds — will multiply by 60
    },
    {
        "name": "PacketStream",
        "hosts": ["packetstream.io", "proxy.packetstream.io"],
        "prefix": "_",
        "delim": "_",
        "kv": "-",
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{code}",
        "sid_key": "session",
        "ttl_key": None,
        "ttl_unit": None,
    },
    {
        # Thordata residential — dash DSL in username:
        # td-customer-USER-country-us-state-california-sessid-XXX-sesstime-10
        "name": "Thordata",
        "hosts": ["thordata.net", "t.pr.thordata.net", "t.na.thordata.net", "pr.thordata.net"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{slug}",
        "sid_key": "sessid",
        "ttl_key": "sesstime",
        "ttl_unit": "min",
    },
    {
        "name": "NetNut",
        "hosts": ["netnut.io", "gw.netnut.net", "rotating-residential.netnut.io"],
        "prefix": "-",
        "delim": "-",
        "kv": "-",
        "keys": {
            "country": "country", "state": "state", "city": "city",
            "zip": "zip", "asn": "asn",
        },
        "state_fmt": "{code_lower}",
        "sid_key": "session",
        "ttl_key": "sessionduration",
        "ttl_unit": "min",
    },
]

# v2.7.33 — One-click famous provider presets (Settings › Proxy Providers).
# Customer picks a brand, enters dashboard username + password only —
# gateway host/port and auto-targeting DSL are pre-filled.
PROVIDER_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "dataimpulse",
        "name": "DataImpulse",
        "tagline": "Residential · auto cr/state/sessid DSL",
        "gateway_host": "gw.dataimpulse.com",
        "gateway_port": "823",
        "alt_ports": ["10000", "822"],
        "username_hint": "Dashboard username (e.g. abc123__cr.us or full gateway user)",
        "docs_url": "https://docs.dataimpulse.com/",
        "proxy_type": "http",
    },
    {
        "id": "smartproxy",
        "name": "Smartproxy / Decodo",
        "tagline": "Residential · gate.smartproxy.com",
        "gateway_host": "gate.smartproxy.com",
        "gateway_port": "7000",
        "alt_ports": ["10000", "10001"],
        "username_hint": "user-USERNAME or smart-… (from Smartproxy dashboard)",
        "docs_url": "https://help.smartproxy.com/",
        "proxy_type": "http",
    },
    {
        "id": "smartproxy_smart",
        "name": "Smartproxy Smart Region",
        "tagline": "Underscore DSL · proxy.smartproxy.net",
        "gateway_host": "proxy.smartproxy.net",
        "gateway_port": "3120",
        "alt_ports": ["7000"],
        "username_hint": "smart-{id}_area-US_state-california_life-120 (from panel)",
        "docs_url": "https://help.smartproxy.com/",
        "proxy_type": "http",
    },
    {
        "id": "thordata",
        "name": "Thordata",
        "tagline": "Residential · t.pr.thordata.net",
        "gateway_host": "t.pr.thordata.net",
        "gateway_port": "9999",
        "alt_ports": ["7777", "5555"],
        "username_hint": "td-customer-USERNAME (proxy user from Thordata panel)",
        "docs_url": "https://doc.thordata.com/",
        "proxy_type": "http",
    },
    {
        "id": "oxylabs",
        "name": "Oxylabs",
        "tagline": "Residential · pr.oxylabs.io",
        "gateway_host": "pr.oxylabs.io",
        "gateway_port": "7777",
        "alt_ports": ["8001"],
        "username_hint": "customer-USER-cc-US (from Oxylabs dashboard)",
        "docs_url": "https://developers.oxylabs.io/",
        "proxy_type": "http",
    },
    {
        "id": "brightdata",
        "name": "Bright Data",
        "tagline": "Luminati / Bright Data gateway",
        "gateway_host": "brd.superproxy.io",
        "gateway_port": "33335",
        "alt_ports": ["22225", "24000"],
        "username_hint": "brd-customer-XXX-zone-resi (from Bright Data)",
        "docs_url": "https://docs.brightdata.com/",
        "proxy_type": "http",
    },
    {
        "id": "iproyal",
        "name": "IPRoyal",
        "tagline": "Residential gateway",
        "gateway_host": "geo.iproyal.com",
        "gateway_port": "12321",
        "alt_ports": ["11200"],
        "username_hint": "IPRoyal gateway username from dashboard",
        "docs_url": "https://docs.iproyal.com/",
        "proxy_type": "http",
    },
    {
        "id": "soax",
        "name": "Soax",
        "tagline": "Mobile/residential · semicolon DSL",
        "gateway_host": "proxy.soax.com",
        "gateway_port": "5000",
        "alt_ports": ["9000"],
        "username_hint": "Soax package username from dashboard",
        "docs_url": "https://help.soax.com/",
        "proxy_type": "http",
    },
    {
        "id": "proxyempire",
        "name": "ProxyEmpire",
        "tagline": "Residential rotating gateway",
        "gateway_host": "rotating.proxyempire.io",
        "gateway_port": "9000",
        "alt_ports": [],
        "username_hint": "ProxyEmpire username from dashboard",
        "docs_url": "https://docs.proxyempire.io/",
        "proxy_type": "http",
    },
    {
        "id": "packetstream",
        "name": "PacketStream",
        "tagline": "P2P residential",
        "gateway_host": "proxy.packetstream.io",
        "gateway_port": "31112",
        "alt_ports": [],
        "username_hint": "PacketStream username",
        "docs_url": "https://packetstream.io/",
        "proxy_type": "http",
    },
    {
        "id": "netnut",
        "name": "NetNut",
        "tagline": "Residential · gw.netnut.net",
        "gateway_host": "gw.netnut.net",
        "gateway_port": "5959",
        "alt_ports": ["7777"],
        "username_hint": "NetNut sub-user username",
        "docs_url": "https://help.netnut.io/",
        "proxy_type": "http",
    },
    {
        "id": "webshare",
        "name": "Webshare",
        "tagline": "Static/rotating — paste or API",
        "kind": "api_endpoint",
        "api_url": "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=1",
        "method": "GET",
        "username_hint": "Use API token in headers — see Webshare docs",
        "docs_url": "https://apidocs.webshare.io/",
        "proxy_type": "http",
    },
]

# Placeholder tokens the customer may embed manually in a saved
# username template — always take precedence over provider auto-detect.
_TARGETING_PLACEHOLDER_KEYS = ("country", "state", "city", "zip", "asn", "ttl", "sid")


def _detect_profile(
    host: str,
    provider_name: str = "",
    username: str = "",
) -> Optional[Dict[str, Any]]:
    h = (host or "").lower().strip()
    n = (provider_name or "").lower().strip()
    u = (username or "").lower().strip()
    # Smartproxy Smart Region panel (proxy.smartproxy.net:3120) — ALWAYS
    # underscore DSL. Using legacy Decodo dash DSL here yields random US
    # exit IPs (e.g. DC when the lead needs CA).
    if "smartproxy.net" in h:
        return dict(_SMARTPROXY_SMART_PROFILE)
    # smartproxy.com may be legacy Decodo OR Smart Region — detect from username.
    if any(needle in h for needle in ("smartproxy.com",)):
        if _is_smartproxy_smart_username(u) or u.startswith("smart-"):
            return dict(_SMARTPROXY_SMART_PROFILE)
    for prof in _PROVIDER_PROFILES:
        for needle in prof["hosts"]:
            if needle in h:
                return prof
    # Fallback: match common provider names when gateway host is custom/CDN.
    _name_needles = {
        "dataimpulse": "DataImpulse",
        "bright data": "Bright Data",
        "luminati": "Bright Data",
        "oxylabs": "Oxylabs",
        "smartproxy": "Smartproxy / Decodo",
        "decodo": "Smartproxy / Decodo",
        "iproyal": "IPRoyal",
        "proxyempire": "ProxyEmpire",
        "soax": "Soax",
        "packetstream": "PacketStream",
        "webshare": "IPRoyal",
        "netnut": "NetNut",
        "thordata": "Thordata",
    }
    for needle, pname in _name_needles.items():
        if needle in n:
            for prof in _PROVIDER_PROFILES:
                if prof["name"] == pname:
                    return prof
    return None


def _state_slug(val: str) -> str:
    """Normalise a US state code or name to a lowercase underscore slug."""
    v = str(val or "").strip()
    if not v:
        return ""
    try:
        from value_normalizer import US_STATES  # noqa: WPS433
    except Exception:
        US_STATES = {}
    if len(v) == 2 and v.upper() in US_STATES:
        return US_STATES[v.upper()].lower().replace(" ", "_")
    return v.lower().replace(" ", "_")


def _state_title(val: str) -> str:
    """Smartproxy panel style: California / New_York."""
    slug = _state_slug(val)
    if not slug:
        return ""
    return "_".join(part.capitalize() for part in slug.split("_") if part)


def _state_pascal(val: str) -> str:
    """Compact PascalCase: California / NewYork (matches city-NewYork style)."""
    slug = _state_slug(val)
    if not slug:
        return ""
    return "".join(part.capitalize() for part in slug.split("_") if part)


def _format_smartproxy_city(val: str) -> str:
    """Smartproxy panel city token — LosAngeles / NewYork / LasVegas.

    v2.6.91 fix: ``_state_pascal("LosAngeles")`` wrongly became ``Losangeles``
    (only first letter capped), which makes the gateway hang until geo probe
    times out for every customer on ROW-FIRST state match.
    """
    v = str(val or "").strip()
    if not v:
        return ""
    if " " in v:
        return "".join(part.capitalize() for part in v.split() if part)
    # Already compact PascalCase (LosAngeles, KansasCity, VirginiaBeach, …).
    if len(v) > 1 and v[0].isupper() and any(ch.isupper() for ch in v[1:]):
        return v
    return _state_pascal(v) or v.replace(" ", "")


def _state_code(val: str) -> str:
    """Resolve CA / California / california → CA."""
    v = str(val or "").strip()
    if not v:
        return ""
    try:
        from value_normalizer import US_STATES  # noqa: WPS433
    except Exception:
        US_STATES = {}
    if len(v) == 2 and v.upper() in US_STATES:
        return v.upper()
    slug = v.lower().replace(" ", "_")
    for code, name in US_STATES.items():
        if name.lower() == v.lower() or name.lower().replace(" ", "_") == slug:
            return code
    return v.upper()[:2] if len(v) >= 2 else v.upper()


def _format_state_for_profile(profile: Optional[Dict[str, Any]], val: str) -> str:
    """Encode sheet STATE for a provider gateway username (permanent DSL map)."""
    slug = _state_slug(val)
    code = _state_code(val)
    title = _state_title(val)
    pascal = _state_pascal(val)
    fmt = (profile or {}).get("state_fmt") or "{slug}"
    if fmt == "us_{slug}":
        if slug.startswith("us_"):
            return slug
        return f"us_{slug}" if slug else ""
    if fmt == "{slug}":
        return slug
    if fmt == "{title}":
        return title
    if fmt == "{pascal}":
        return pascal
    if fmt == "{code}":
        return code
    if fmt == "{code_lower}":
        return code.lower()
    try:
        return fmt.format(
            slug=slug,
            code=code,
            code_lower=code.lower(),
            title=title,
            pascal=pascal,
        )
    except Exception:
        return slug or title


def _norm_target_val(profile: Dict[str, Any], key: str, val: str) -> str:
    """Normalise a targeting value for the given provider."""
    v = str(val or "").strip()
    if not v:
        return ""
    if key == "country":
        return v.lower()[:3]
    if key == "state":
        return _format_state_for_profile(profile, v)
    if key == "city":
        return v.lower().replace(" ", "")
    if key == "zip":
        return re.sub(r"[^A-Za-z0-9\-]", "", v)
    if key == "asn":
        return re.sub(r"[^A-Za-z0-9]", "", v).lower()
    return v


def _apply_targeting_to_username(
    username_tpl: str,
    gateway_host: str,
    targeting: Dict[str, Any],
    provider_name: str = "",
) -> str:
    """Return the username template with targeting overrides applied.

    Order of precedence:
      1.  `{country}`/`{state}`/`{city}`/`{zip}`/`{asn}`/`{ttl}` placeholders
          in the saved template — always substituted first.
      2.  For known providers (detected via gateway_host), APPEND the
          matching key/value tokens using the provider's DSL — but only
          for keys not already present in the template (avoid clobbering
          the customer's manual configuration).
      3.  `{sid}` is deliberately NOT substituted here — that happens
          later per-line via `_rotate_session_in_username` so each
          generated line gets a distinct session id.

    `targeting` is a dict with keys: country, state, city, zip, asn,
    sticky_minutes (int, optional). Any value that is None/'' is
    ignored.
    """
    if not username_tpl:
        return username_tpl
    if not targeting:
        return username_tpl

    profile = _detect_profile(gateway_host or "", provider_name, username_tpl)
    force_replace = bool(targeting.get("force_replace"))

    out = username_tpl
    original_username = username_tpl
    if force_replace and profile:
        out = _strip_legacy_gateway_geo(out)
        if profile.get("dsl") == "smart_underscore":
            out = _normalize_smartproxy_smart_account_base(out)
            out = _strip_smartproxy_smart_params(out)
        else:
            out = _strip_provider_geo_params(out, profile)
            out = _strip_provider_session(out, profile)
        out = _ensure_provider_user_prefix(out, profile)
    elif force_replace:
        out = _strip_legacy_gateway_geo(out)
        out = _strip_provider_session(out)

    # Smartproxy Smart Region — rebuild _area/_state/_life/_session suffix.
    if profile and profile.get("dsl") == "smart_underscore":
        if force_replace or any(
            targeting.get(k) for k in ("country", "state", "city", "zip", "asn")
        ):
            return _apply_smartproxy_smart_targeting(
                out, targeting, original_username=original_username,
            )

    # 1. Placeholder substitution — universal, provider-agnostic.
    for key in ("country", "state", "city", "zip", "asn"):
        val = targeting.get(key)
        placeholder = "{" + key + "}"
        if placeholder in out:
            if val:
                nv = _norm_target_val(profile or {}, key, val) if profile else str(val).strip().lower()
                out = out.replace(placeholder, nv)
            else:
                # Strip empty placeholders and any orphaned separator
                # immediately preceding them (handles ";st.{state}"
                # collapsing cleanly to "").
                out = re.sub(r"[;,\-_]?" + re.escape(placeholder), "", out)
    if "{ttl}" in out:
        ttl = targeting.get("sticky_minutes")
        if ttl:
            out = out.replace("{ttl}", str(int(ttl)))
        else:
            out = re.sub(r"[;,\-_]?\{ttl\}", "", out)

    # 2. Provider-aware DSL append — only for keys NOT already present.
    if profile:
        parts_to_append: List[str] = []
        for key in ("country", "state", "city", "zip", "asn"):
            val = targeting.get(key)
            if not val:
                continue
            provider_key = profile["keys"].get(key)
            if not provider_key:
                continue
            # If the template already contains this provider key, skip
            # (customer already configured it manually) — unless force_replace
            # cleared stale geo tokens above (ROW-FIRST state match).
            if not force_replace and re.search(
                rf"(^|[{re.escape(profile['delim'])}{re.escape(profile['prefix'])}]){re.escape(provider_key)}{re.escape(profile['kv'])}",
                out,
            ):
                continue
            nv = _norm_target_val(profile, key, val)
            if nv:
                parts_to_append.append(f"{provider_key}{profile['kv']}{nv}")

        # Session TTL
        ttl = targeting.get("sticky_minutes")
        if ttl and profile.get("ttl_key"):
            ttl_key = profile["ttl_key"]
            # Skip if already present
            if not re.search(rf"(^|[{re.escape(profile['delim'])}{re.escape(profile['prefix'])}]){re.escape(ttl_key)}{re.escape(profile['kv'])}", out):
                ttl_val = int(ttl) * 60 if profile.get("ttl_unit") == "sec" else int(ttl)
                parts_to_append.append(f"{ttl_key}{profile['kv']}{ttl_val}")

        # Session id — inject with {sid} placeholder so per-line
        # rotation replaces it later. Only inject if template has no
        # existing session token/placeholder — this preserves customer
        # intent when they manually set one.
        want_sid = targeting.get("session_mode", "sticky") == "sticky" or targeting.get("_want_sid")
        if want_sid and profile.get("sid_key"):
            sid_key = profile["sid_key"]
            if "{sid}" not in out and not re.search(
                rf"(^|[{re.escape(profile['delim'])}{re.escape(profile['prefix'])}]){re.escape(sid_key)}{re.escape(profile['kv'])}",
                out,
            ):
                parts_to_append.append(f"{sid_key}{profile['kv']}{{sid}}")

        if parts_to_append:
            joined = profile["delim"].join(parts_to_append)
            if profile["prefix"] and profile["prefix"] not in out:
                # First targeting param → use provider's prefix token
                out = f"{out}{profile['prefix']}{joined}"
            else:
                out = f"{out}{profile['delim']}{joined}"

    return out


def _format_gateway_line(cfg: Dict[str, Any], proxy_type: str,
                        rotate_session: bool = False) -> Optional[str]:
    from urllib.parse import quote

    host = str(cfg.get("gateway_host") or "").strip()
    port = str(cfg.get("gateway_port") or "").strip()
    user = str(cfg.get("username") or "").strip()
    pwd = str(cfg.get("password") or "").strip()
    if not host or not port:
        return None
    if rotate_session and user:
        user = _rotate_session_in_username(user)
    scheme = proxy_type or "http"
    if user and pwd:
        return (
            f"{scheme}://{quote(user, safe='')}:{quote(pwd, safe='')}"
            f"@{host}:{port}"
        )
    return f"{scheme}://{host}:{port}"


def _pick_from_manual_list(cfg: Dict[str, Any]) -> Optional[str]:
    lines_raw = cfg.get("lines") or ""
    if isinstance(lines_raw, list):
        lines = [str(x).strip() for x in lines_raw if str(x).strip()]
    else:
        lines = [ln.strip() for ln in str(lines_raw).splitlines() if ln.strip()]
    if not lines:
        return None
    return random.choice(lines)


async def _pick_from_api(cfg: Dict[str, Any], proxy_type: str) -> Optional[str]:
    api_url = str(cfg.get("api_url") or "").strip()
    if not api_url:
        return None
    method = str(cfg.get("method") or "GET").upper()
    headers = cfg.get("headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except Exception:
            headers = {}
    body = cfg.get("body")
    if isinstance(body, str) and body.strip().startswith(("{", "[")):
        try:
            body = json.loads(body)
        except Exception:
            pass
    response_path = str(cfg.get("response_path") or "").strip()  # e.g. "data.0.proxy" or "proxy"

    try:
        async with httpx.AsyncClient(timeout=8) as c:
            if method == "POST":
                r = await c.post(api_url, headers=headers, json=body if isinstance(body, (dict, list)) else None,
                                 data=body if isinstance(body, (str, bytes)) else None)
            else:
                r = await c.get(api_url, headers=headers, params=body if isinstance(body, dict) else None)
            if r.status_code != 200:
                logger.warning(f"[proxy-api] provider api returned {r.status_code}")
                return None
            text = r.text
            # Try JSON path first
            if response_path:
                try:
                    j = r.json()
                    val: Any = j
                    for key in response_path.split("."):
                        if key.isdigit() and isinstance(val, list):
                            val = val[int(key)]
                        elif isinstance(val, dict):
                            val = val.get(key)
                        else:
                            val = None
                        if val is None:
                            break
                    if val:
                        line = str(val).strip()
                        if not re.match(r"^[a-zA-Z]+://", line):
                            line = f"{proxy_type}://{line}"
                        return line
                except Exception:
                    pass
            # Fallback: first non-empty line that looks like proxy
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.search(r"[a-zA-Z0-9\.]+:\d+", line):
                    if not re.match(r"^[a-zA-Z]+://", line):
                        line = f"{proxy_type}://{line}"
                    return line
            return None
    except Exception as e:
        logger.warning(f"[proxy-api] provider fetch failed: {e}")
        return None


async def get_provider_gateway_credentials(
    user_id: str, provider_id: str,
) -> Dict[str, str]:
    """Return stored gateway username/password for a rotating provider (no rotation)."""
    provider = await _get(user_id, provider_id)
    if not provider:
        return {}
    cfg = provider.get("config") or {}
    return {
        "username": str(cfg.get("username") or "").strip(),
        "password": str(cfg.get("password") or "").strip(),
        "gateway_host": str(cfg.get("gateway_host") or "").strip(),
        "gateway_port": str(cfg.get("gateway_port") or "").strip(),
    }


async def get_proxy_from_provider(user_id: str, provider_id: str) -> Dict[str, Any]:
    """
    Returns {"proxy": "<scheme>://user:pass@host:port", "proxy_type": "...",
             "kind": "...", "provider_id": "...", "provider_name": "..."}
    or {"proxy": None, "error": "..."} on failure.
    Special kind='native_proxyjet' returns {"proxy": None, "use_proxyjet": True,
                                            "country": "...", "state": "..."}
    which the caller should feed into the existing ProxyJet auto flow.
    """
    if not provider_id:
        return {"proxy": None, "error": "no provider_id supplied"}
    provider = await _get(user_id, provider_id)
    if not provider:
        return {"proxy": None, "error": "provider not found"}
    if not provider.get("enabled"):
        return {"proxy": None, "error": "provider is disabled"}

    kind = provider.get("kind")
    cfg = provider.get("config") or {}
    proxy_type = provider.get("proxy_type") or "http"
    ret_common = {
        "provider_id": provider.get("id"),
        "provider_name": provider.get("name"),
        "kind": kind,
        "proxy_type": proxy_type,
    }

    if kind == "rotating_gateway":
        proxy = _format_gateway_line(cfg, proxy_type)
        await _bump_use(user_id, provider["id"])
        return {"proxy": proxy, **ret_common} if proxy else {"proxy": None, "error": "gateway_host/port missing", **ret_common}
    if kind == "manual_list":
        proxy = _pick_from_manual_list(cfg)
        if proxy and not re.match(r"^[a-zA-Z]+://", proxy):
            proxy = f"{proxy_type}://{proxy}"
        await _bump_use(user_id, provider["id"])
        return {"proxy": proxy, **ret_common} if proxy else {"proxy": None, "error": "manual list empty", **ret_common}

    if kind == "api_endpoint":
        proxy = await _pick_from_api(cfg, proxy_type)
        await _bump_use(user_id, provider["id"])
        return {"proxy": proxy, **ret_common} if proxy else {"proxy": None, "error": "api call failed", **ret_common}

    if kind == "native_proxyjet":
        await _bump_use(user_id, provider["id"])
        return {
            "proxy": None,
            "use_proxyjet": True,
            "country": cfg.get("country") or "US",
            "state": cfg.get("state") or "",
            "gateway": cfg.get("gateway") or "",
            **ret_common,
        }

    return {"proxy": None, "error": f"unknown kind: {kind}", **ret_common}


# ─── Smart proxy string parser (Task 1) ──────────────────────────────
# Understand ANY proxy string a customer may paste in.
# Supported input shapes (case-insensitive scheme prefix optional):
#   • http://host:port
#   • http://user:pass@host:port
#   • https://user:pass@host:port
#   • socks5://user:pass@host:port
#   • socks5h://user:pass@host:port
#   • socks4://host:port
#   • user:pass@host:port                (scheme = auto/http default)
#   • host:port                          (scheme = auto/http default)
#   • host:port:user:pass                (Webshare / common list style)
#   • user:pass:host:port                (alt style)
#   • host,port,user,pass                (comma-separated)
# Returns dict per line:
#   {"raw", "ok", "proxy_type", "host", "port", "username", "password",
#    "normalized"}  — normalized is `<scheme>://user:pass@host:port` or
#                     `<scheme>://host:port`.
_SCHEME_ALIASES = {
    "http": "http", "https": "https",
    "socks5": "socks5", "socks5h": "socks5h", "socks4": "socks4",
    "socks": "socks5",  # user shorthand
    "s5": "socks5", "s4": "socks4",
}


def _looks_like_host(s: str) -> bool:
    if not s:
        return False
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s):
        return True
    if re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$", s):
        return "." in s or s in ("localhost",)
    return False


def _looks_like_port(s: str) -> bool:
    if not s or not s.isdigit():
        return False
    n = int(s)
    return 1 <= n <= 65535


def parse_proxy_string(raw: str, default_type: str = "http") -> Dict[str, Any]:
    """Auto-detect any common proxy string layout."""
    result = {
        "raw": raw,
        "ok": False,
        "proxy_type": default_type,
        "host": "",
        "port": "",
        "username": "",
        "password": "",
        "normalized": "",
        "error": "",
    }
    if not raw:
        result["error"] = "empty"
        return result
    line = raw.strip().strip("'\"")
    if not line:
        result["error"] = "empty"
        return result

    # 1) Strip and detect scheme
    scheme = default_type
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9]*)://(.+)$", line)
    if m:
        raw_scheme = m.group(1).lower()
        scheme = _SCHEME_ALIASES.get(raw_scheme, raw_scheme)
        if scheme not in SUPPORTED_TYPES:
            scheme = default_type
        line = m.group(2)

    user = pwd = host = port = ""

    # 2) Handle user:pass@host:port pattern
    if "@" in line:
        auth, hostpart = line.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
        else:
            user = auth
        if ":" in hostpart:
            host, port = hostpart.split(":", 1)
        else:
            host = hostpart
    else:
        # 3) Handle colon/comma-separated flat lists (host:port[:user:pass] or reverse)
        sep = "," if "," in line and ":" not in line else ":"
        parts = [p.strip() for p in line.split(sep) if p.strip()]
        if len(parts) == 2:
            host, port = parts[0], parts[1]
        elif len(parts) == 4:
            # ambiguous: could be host:port:user:pass OR user:pass:host:port
            a, b, c, d = parts
            if _looks_like_host(a) and _looks_like_port(b):
                host, port, user, pwd = a, b, c, d
            elif _looks_like_host(c) and _looks_like_port(d):
                user, pwd, host, port = a, b, c, d
            else:
                # fallback: assume host:port:user:pass
                host, port, user, pwd = a, b, c, d
        elif len(parts) == 3:
            # host:port:user  (no password)  — rare but possible
            host, port, user = parts[0], parts[1], parts[2]
        else:
            result["error"] = f"unrecognised format ({len(parts)} parts)"
            return result

    # Cleanup
    host = host.strip().strip("/")
    port = port.strip()
    user = user.strip()
    pwd = pwd.strip()

    if not _looks_like_host(host):
        result["error"] = f"invalid host '{host}'"
        return result
    if not _looks_like_port(port):
        result["error"] = f"invalid port '{port}'"
        return result

    result.update({
        "ok": True,
        "proxy_type": scheme,
        "host": host,
        "port": port,
        "username": user,
        "password": pwd,
    })
    if user and pwd:
        result["normalized"] = f"{scheme}://{user}:{pwd}@{host}:{port}"
    elif user:
        result["normalized"] = f"{scheme}://{user}@{host}:{port}"
    else:
        result["normalized"] = f"{scheme}://{host}:{port}"
    return result


def _bulk_parse(strings: List[str], default_type: str = "http") -> Dict[str, Any]:
    """Parse a list of strings; return per-line results + summary."""
    lines = []
    for raw in strings:
        if isinstance(raw, str):
            for chunk in raw.splitlines():
                chunk = chunk.strip()
                if chunk:
                    lines.append(chunk)
    parsed = [parse_proxy_string(ln, default_type) for ln in lines]
    ok = [p for p in parsed if p["ok"]]
    # Detect dominant proxy_type (majority wins)
    type_votes: Dict[str, int] = {}
    for p in ok:
        type_votes[p["proxy_type"]] = type_votes.get(p["proxy_type"], 0) + 1
    dominant = default_type
    if type_votes:
        dominant = sorted(type_votes.items(), key=lambda x: -x[1])[0][0]

    # Suggest a provider config:
    # - If exactly 1 line with credentials → suggest rotating_gateway (one host)
    # - Else → suggest manual_list with all normalized lines
    suggested_kind = "manual_list"
    suggested_config: Dict[str, Any] = {}
    if len(ok) == 1 and ok[0]["username"] and ok[0]["password"]:
        suggested_kind = "rotating_gateway"
        suggested_config = {
            "gateway_host": ok[0]["host"],
            "gateway_port": ok[0]["port"],
            "username": ok[0]["username"],
            "password": ok[0]["password"],
        }
    else:
        suggested_config = {"lines": "\n".join(p["normalized"] for p in ok)}

    return {
        "parsed": parsed,
        "ok_count": len(ok),
        "fail_count": len(parsed) - len(ok),
        "dominant_type": dominant,
        "suggested_kind": suggested_kind,
        "suggested_proxy_type": dominant,
        "suggested_config": suggested_config,
    }


async def _bump_use(user_id: str, provider_id: str) -> None:
    try:
        await _db.user_proxy_providers.update_one(
            {"id": provider_id, "user_id": user_id},
            {"$set": {"last_used_at": datetime.now(timezone.utc).isoformat()},
             "$inc": {"use_count": 1}},
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# 2026-07 v2.6.10 CUSTOMER-REQUEST — Unique-IP + VPN/Datacenter guard
# ─────────────────────────────────────────────────────────────────────
# Customer complained that even with strict "no duplicate IP" enabled,
# CSV click reports showed 8 unique IPs → 17 clicks (dupes) with the
# error "Traffic from proxies is blocked" — because the provider's
# rotating gateway sometimes returns the SAME exit-IP for a fresh
# session OR returns a datacenter-flagged IP that offer trackers
# blacklist.
#
# This module now offers a per-provider "guarantee": before handing
# out a proxy line, probe the exit-IP through the proxy itself,
# classify it (residential vs datacenter/proxy/mobile), and:
#   • strict_unique_ip=True  → retry session up to 5x if the IP has
#                              already been used in this batch
#   • skip_datacenter_ip=True → retry session up to 5x if the IP is
#                              flagged as hosting/datacenter/proxy
#
# Results are cached in `ip_reputation_cache` (Mongo) for 7 days so
# repeat probes on the same IP are near-free.
#
# Provider that supports session rotation (rotating_gateway with a
# recognised session token OR {sid} placeholder) benefits fully;
# providers without rotation still probe the IP so the caller can
# decide whether to use the line.

_IP_PROBE_URL = "http://ip-api.com/json/?fields=status,query,proxy,hosting,mobile,countryCode,city,isp"
_IP_PROBE_TIMEOUT = 6.0
_IP_REP_CACHE_TTL_DAYS = 7


async def _get_cached_ip_reputation(ip: str) -> Optional[Dict[str, Any]]:
    if not ip or _db is None:
        return None
    try:
        doc = await _db.ip_reputation_cache.find_one({"ip": ip}, {"_id": 0})
    except Exception:
        return None
    if not doc:
        return None
    fetched_at = doc.get("fetched_at")
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except Exception:
        return None
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    if age_days > _IP_REP_CACHE_TTL_DAYS:
        return None
    return doc


async def _set_cached_ip_reputation(ip: str, data: Dict[str, Any]) -> None:
    if not ip or _db is None:
        return
    try:
        doc = {
            "ip": ip,
            "is_proxy":     bool(data.get("proxy")),
            "is_hosting":   bool(data.get("hosting")),
            "is_mobile":    bool(data.get("mobile")),
            "country_code": str(data.get("countryCode") or ""),
            "city":         str(data.get("city") or ""),
            "isp":          str(data.get("isp") or ""),
            "fetched_at":   datetime.now(timezone.utc).isoformat(),
        }
        await _db.ip_reputation_cache.update_one(
            {"ip": ip}, {"$set": doc}, upsert=True
        )
    except Exception:
        pass


async def _probe_ip_via_proxy(proxy_url: str) -> Optional[Dict[str, Any]]:
    """Probe the exit-IP + classification through the given proxy.
    Returns dict with keys `ip, is_proxy, is_hosting, is_mobile,
    country_code, city, isp` or None on any failure.
    Cached in Mongo `ip_reputation_cache` (7-day TTL) so repeat probes
    on the same IP are near-instant. First-time probe adds ~1.5-3 s.
    """
    if not proxy_url:
        return None
    try:
        # First step: ONLY discover the exit IP through the proxy
        # (fast, single request). Then check cache before classifying.
        async with httpx.AsyncClient(
            proxy=proxy_url, timeout=_IP_PROBE_TIMEOUT, verify=False, trust_env=False,
        ) as c:
            r = await c.get(_IP_PROBE_URL)
            if r.status_code != 200:
                logger.debug(f"[ip-probe] non-200 status {r.status_code}")
                return None
            data = r.json() or {}
            if str(data.get("status") or "").lower() != "success":
                return None
    except Exception as e:
        logger.debug(f"[ip-probe] fetch failed via proxy: {e}")
        return None

    ip = str(data.get("query") or "").strip()
    if not ip:
        return None

    cached = await _get_cached_ip_reputation(ip)
    if cached:
        return {
            "ip":           ip,
            "is_proxy":     bool(cached.get("is_proxy")),
            "is_hosting":   bool(cached.get("is_hosting")),
            "is_mobile":    bool(cached.get("is_mobile")),
            "country_code": str(cached.get("country_code") or ""),
            "city":         str(cached.get("city") or ""),
            "isp":          str(cached.get("isp") or ""),
        }

    # Persist to cache for the next probe.
    await _set_cached_ip_reputation(ip, data)

    return {
        "ip":           ip,
        "is_proxy":     bool(data.get("proxy")),
        "is_hosting":   bool(data.get("hosting")),
        "is_mobile":    bool(data.get("mobile")),
        "country_code": str(data.get("countryCode") or ""),
        "city":         str(data.get("city") or ""),
        "isp":          str(data.get("isp") or ""),
    }


# 2026-07 v2.5.3 — Bulk resolver for jobs that need many unique lines.
async def get_proxy_lines_from_provider(
    user_id: str, provider_id: str, count: int,
    unique_ip_seen: Optional[set] = None,
    strict_unique_ip: Optional[bool] = None,
    skip_datacenter_ip: Optional[bool] = None,
    targeting: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fetch `count` proxy lines from a single provider. Rotating-gateway
    kind auto-rotates the session token per line so the customer gets
    a fresh sticky-IP per visit (critical for RUT `no_repeated_proxy`
    mode — before this fix, rotating gateways emitted ONE line and RUT
    aborted with "No more proxies available" after visit #1).

    v2.6.10 CUSTOMER-REQUEST — Unique-IP + Non-VPN guarantee
    ─────────────────────────────────────────────────────────
    When the provider's config has `strict_unique_ip` (default True)
    or `skip_datacenter_ip` (default True), each generated line is
    probed through-proxy against ip-api.com to fetch:
      • the actual exit IP
      • proxy/hosting/mobile flags (VPN & datacenter detection)
    Lines that fail the check are re-generated with a fresh session
    id (up to 5 retries per slot). Guaranteed output: N lines where
    every exit IP is unique AND passes the anti-VPN filter (or
    fewer lines with a `warnings` field if the provider's IP pool
    was exhausted).

    Overrides via the function args always win over the provider
    config — RUT engine passes its own `unique_ip_seen` set so the
    dedup carries across the entire job's proxy pool.

    Return shape:
      { "lines": ["scheme://user:pass@host:port", ...],
        "kind":  "...",
        "provider_id": "...",
        "provider_name": "...",
        "proxy_type": "...",
        "use_proxyjet": bool          (native_proxyjet kind only)
        "country": "US" (native_proxyjet kind only)
        "state": "CA"  (native_proxyjet kind only, may be "")
        "unique_ip_hits": int         (v2.6.10 — how many proxies
                                       passed the unique-IP filter)
        "warnings": ["..."]           (v2.6.10 — non-fatal notes,
                                       e.g. "pool exhausted after 12/17")
        "error": "..." (only when nothing usable came back)
      }
    """
    if not provider_id:
        return {"lines": [], "error": "no provider_id supplied"}
    provider = await _get(user_id, provider_id)
    if not provider:
        return {"lines": [], "error": "provider not found"}
    if not provider.get("enabled"):
        return {"lines": [], "error": "provider is disabled"}

    kind = provider.get("kind")
    cfg = provider.get("config") or {}
    proxy_type = provider.get("proxy_type") or "http"
    ret_common = {
        "provider_id": provider.get("id"),
        "provider_name": provider.get("name"),
        "kind": kind,
        "proxy_type": proxy_type,
    }

    # v2.6.10 — resolve unique/VPN toggles (arg > provider cfg > default True)
    if strict_unique_ip is None:
        strict_unique_ip = bool(cfg.get("strict_unique_ip", True))
    if skip_datacenter_ip is None:
        skip_datacenter_ip = bool(cfg.get("skip_datacenter_ip", True))
    if unique_ip_seen is None:
        unique_ip_seen = set()
    warnings: List[str] = []
    unique_ip_hits = 0
    # Probing is expensive-ish (1-3s first time per IP); only enable
    # when the caller/provider asks for the guarantee. Rotating
    # gateway is the primary target — manual_list / api_endpoint
    # still probe if strict_unique_ip is on.
    probe_enabled = bool(strict_unique_ip or skip_datacenter_ip)

    try:
        count = max(1, int(count))
    except Exception:
        count = 1
    count = min(count, 5000)  # hard cap

    async def _line_passes(candidate: str) -> tuple:
        """Probe candidate proxy → (ok: bool, ip: str, reason: str)."""
        if not probe_enabled:
            return True, "", ""
        info = await _probe_ip_via_proxy(candidate)
        if not info:
            # Probe failed — network hiccup / provider blocking probes.
            # Do not reject the line; let the RUT engine's own
            # duplicate_ip_set + rut_burnt_ips catch problems later.
            return True, "", "probe_failed"
        ip = info["ip"]
        if strict_unique_ip and ip in unique_ip_seen:
            return False, ip, "duplicate_ip"
        if skip_datacenter_ip and (info["is_hosting"] or info["is_proxy"]):
            return False, ip, "datacenter_or_vpn"
        return True, ip, ""

    if kind == "rotating_gateway":
        host = str(cfg.get("gateway_host") or "").strip()
        port = str(cfg.get("gateway_port") or "").strip()
        if not host or not port:
            return {"lines": [], "error": "gateway_host/port missing", **ret_common}
        username_tpl = str(cfg.get("username") or "").strip()
        # RUT Auto Mode passes job geo hints (proxyjet_country/state) here
        # so Smartproxy / Decodo / Bright Data lines honour the operator's
        # Country dropdown — previously only session ids rotated.
        _tgt = targeting or {}
        if _tgt and username_tpl:
            _apply_tgt = {
                k: _tgt[k]
                for k in ("country", "state", "city", "zip", "asn", "sticky_minutes")
                if _tgt.get(k)
            }
            if _apply_tgt:
                _apply_tgt["_want_sid"] = True
                _apply_tgt["force_replace"] = True
                username_tpl = _apply_targeting_to_username(
                    username_tpl,
                    host,
                    _apply_tgt,
                    str(provider.get("name") or ""),
                )
        lines: List[str] = []
        MAX_RETRIES_PER_SLOT = 5
        exhaustion_streak = 0     # consecutive slots that gave up
        _gw_cfg = {**cfg, "username": username_tpl}
        for _ in range(count):
            ln = None
            for _try in range(MAX_RETRIES_PER_SLOT):
                candidate = _format_gateway_line(_gw_cfg, proxy_type, rotate_session=True)
                if not candidate:
                    break
                ok, exit_ip, reason = await _line_passes(candidate)
                if ok:
                    ln = candidate
                    if exit_ip:
                        unique_ip_seen.add(exit_ip)
                        unique_ip_hits += 1
                    break
                # else: try again with a fresh session
            if ln:
                lines.append(ln)
                exhaustion_streak = 0
            else:
                exhaustion_streak += 1
                # If 3 slots in a row exhaust their 5 retries, the
                # pool is effectively empty for our filters — stop
                # burning provider quota and return what we have.
                if exhaustion_streak >= 3:
                    warnings.append(
                        f"pool exhausted after {len(lines)}/{count} unique lines — "
                        "provider ran out of clean/unique IPs"
                    )
                    break
        await _bump_use(user_id, provider["id"])
        return {"lines": lines, "unique_ip_hits": unique_ip_hits,
                "warnings": warnings, **ret_common}

    if kind == "manual_list":
        lines_raw = cfg.get("lines") or ""
        if isinstance(lines_raw, list):
            pool = [str(x).strip() for x in lines_raw if str(x).strip()]
        else:
            pool = [ln.strip() for ln in str(lines_raw).splitlines() if ln.strip()]
        if not pool:
            return {"lines": [], "error": "manual list empty", **ret_common}
        def _prefix(x: str) -> str:
            return x if re.match(r"^[a-zA-Z]+://", x) else f"{proxy_type}://{x}"

        # Normalise + shuffle (v2.6.10: no more picks-with-replacement
        # when strict_unique_ip is on — replacement would immediately
        # violate the guarantee).
        prefixed = [_prefix(ln) for ln in pool]
        random.shuffle(prefixed)

        if not probe_enabled:
            # Legacy fast path: with-replacement if pool < count.
            take = prefixed[:count] if count <= len(prefixed) else []
            if not take:
                bucket = []
                cur = prefixed[:]
                while len(bucket) < count:
                    if not cur:
                        cur = prefixed[:]
                        random.shuffle(cur)
                    bucket.append(cur.pop())
                take = bucket
            await _bump_use(user_id, provider["id"])
            return {"lines": take, **ret_common}

        # Filtered path: probe each candidate, keep only those that
        # pass the guarantee. NO with-replacement.
        picked: List[str] = []
        for candidate in prefixed:
            if len(picked) >= count:
                break
            ok, exit_ip, reason = await _line_passes(candidate)
            if ok:
                picked.append(candidate)
                if exit_ip:
                    unique_ip_seen.add(exit_ip)
                    unique_ip_hits += 1
        if len(picked) < count:
            warnings.append(
                f"manual list yielded only {len(picked)}/{count} unique/clean lines "
                "— add more proxies to the list or disable strict_unique_ip"
            )
        await _bump_use(user_id, provider["id"])
        return {"lines": picked, "unique_ip_hits": unique_ip_hits,
                "warnings": warnings, **ret_common}

    if kind == "api_endpoint":
        lines: List[str] = []
        attempts = 0
        max_attempts = count * 3  # 3x headroom for the filter
        while len(lines) < count and attempts < max_attempts:
            attempts += 1
            p = await _pick_from_api(cfg, proxy_type)
            if not p:
                continue
            ok, exit_ip, reason = await _line_passes(p)
            if ok:
                lines.append(p)
                if exit_ip:
                    unique_ip_seen.add(exit_ip)
                    unique_ip_hits += 1
        if not lines:
            return {"lines": [], "error": "api_endpoint returned no usable proxies", **ret_common}
        if len(lines) < count:
            warnings.append(
                f"api endpoint yielded only {len(lines)}/{count} unique/clean proxies"
            )
        await _bump_use(user_id, provider["id"])
        return {"lines": lines, "unique_ip_hits": unique_ip_hits,
                "warnings": warnings, **ret_common}

    if kind == "native_proxyjet":
        await _bump_use(user_id, provider["id"])
        return {
            "lines": [],
            "use_proxyjet": True,
            "country": cfg.get("country") or "US",
            "state": cfg.get("state") or "",
            "gateway": cfg.get("gateway") or "",
            **ret_common,
        }

    return {"lines": [], "error": f"unknown kind: {kind}", **ret_common}



# ─── Router factory ──────────────────────────────────────────────────
def init_router(main_db, get_current_user_dep) -> APIRouter:
    global _db, _get_current_user_dep
    _db = main_db
    _get_current_user_dep = get_current_user_dep

    router = APIRouter(prefix="/proxy-providers", tags=["proxy-providers"])

    @router.get("")
    async def list_providers(user=Depends(_get_current_user_dep)):
        return await _list(user["id"])

    @router.post("")
    async def create_provider(body: ProxyProviderCreate, user=Depends(_get_current_user_dep)):
        return await _create(user["id"], body)

    @router.get("/{provider_id}")
    async def get_provider(provider_id: str, user=Depends(_get_current_user_dep)):
        doc = await _get(user["id"], provider_id)
        if not doc:
            raise HTTPException(404, "Not found")
        return doc

    @router.put("/{provider_id}")
    async def update_provider(provider_id: str, body: ProxyProviderUpdate,
                              user=Depends(_get_current_user_dep)):
        return await _update(user["id"], provider_id, body)

    @router.delete("/{provider_id}")
    async def delete_provider(provider_id: str, user=Depends(_get_current_user_dep)):
        await _delete(user["id"], provider_id)
        return {"ok": True}

    @router.post("/{provider_id}/test")
    async def test_provider(provider_id: str, user=Depends(_get_current_user_dep)):
        """Attempt to fetch one proxy from the provider and return the result."""
        result = await get_proxy_from_provider(user["id"], provider_id)
        if result.get("proxy") or result.get("use_proxyjet"):
            return {"ok": True, "sample": result}
        return {"ok": False, "error": result.get("error") or "unknown"}

    @router.post("/{provider_id}/ip-quality-check")
    async def ip_quality_check(
        provider_id: str,
        body: Dict[str, Any] = Body(default_factory=dict),
        user=Depends(_get_current_user_dep),
    ):
        """v2.6.10 — Provider health probe.
        Fetches N proxies from the provider (default 5) and reports
        for each:
          • exit IP
          • is_proxy / is_hosting / is_mobile flags (VPN/DC detection)
          • ISP + country + city
        Also returns a summary: unique IP count, datacenter count,
        residential count. Frontend uses this to warn the customer
        BEFORE burning a real click job's quota.
        """
        provider = await _get(user["id"], provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        try:
            n = max(1, min(int(body.get("count") or 5), 20))
        except Exception:
            n = 5

        # Force-enable probing regardless of provider toggles.
        seen: set = set()
        res = await get_proxy_lines_from_provider(
            user["id"], provider_id, n,
            unique_ip_seen=seen,
            strict_unique_ip=True,
            skip_datacenter_ip=False,   # keep datacenter lines in report
        )
        # For each returned line, probe again to enrich the report
        # (cached, so ~free).
        report: List[Dict[str, Any]] = []
        for line in (res.get("lines") or []):
            info = await _probe_ip_via_proxy(line)
            report.append({
                "proxy":     line.split("@")[-1] if "@" in line else line,
                "ip":        (info or {}).get("ip", "") or "unknown",
                "is_proxy":  bool((info or {}).get("is_proxy")),
                "is_hosting": bool((info or {}).get("is_hosting")),
                "is_mobile": bool((info or {}).get("is_mobile")),
                "country":   (info or {}).get("country_code", ""),
                "city":      (info or {}).get("city", ""),
                "isp":       (info or {}).get("isp", ""),
                "probe_ok":  info is not None,
            })
        ips = {r["ip"] for r in report if r["ip"] and r["ip"] != "unknown"}
        dc_count = sum(1 for r in report if r["is_hosting"] or r["is_proxy"])
        return {
            "ok": bool(report),
            "provider_name": provider.get("name"),
            "kind": provider.get("kind"),
            "requested": n,
            "returned": len(report),
            "unique_ips": len(ips),
            "datacenter_or_vpn": dc_count,
            "residential": len(report) - dc_count,
            "report": report,
            "verdict": (
                "excellent" if dc_count == 0 and len(ips) == len(report) and report else
                "good"      if dc_count <= len(report) * 0.2 and len(ips) >= len(report) * 0.8 else
                "poor"      if report else
                "failed"
            ),
        }

    # ── 2026-01 v2.5.0 — Provider-agnostic on-demand batch generator ─
    # Wraps ProxyJet's per-user unique batch generation for ANY selected
    # provider kind. Frontend "Auto Mode" toggle + Proxies page batch
    # generator both hit this single endpoint so customers no longer
    # need ProxyJet credentials specifically — whichever provider they
    # picked in Settings › Proxy Providers becomes the batch source.
    #
    # Behavior per kind:
    #   • native_proxyjet     → uses ProxyJet's existing generate_unique_proxies()
    #   • rotating_gateway    → generates N gateway lines. When cfg has
    #                           `session_param` (username token e.g.
    #                           "-session-{sid}"), each line rotates the
    #                           token so the gateway rotates IPs per
    #                           session. Otherwise returns N identical
    #                           gateway lines (still correct — the
    #                           gateway rotates IPs on every connect).
    #   • api_endpoint        → calls the API N times (with small retry
    #                           per failure).
    #   • manual_list         → random samples from user's list. If the
    #                           user asks for more than the list size,
    #                           picks with replacement (shuffled).
    #
    # Request body (all optional except count):
    #   {
    #     "count": 10,
    #     "country": "US",          // hint for providers that support geo
    #     "state":   "CA",          // ProxyJet & any provider that supports geo
    #     "sticky_minutes": null,   // ProxyJet only
    #     "proxy_type": "socks5"    // override scheme prefix on the output
    #                               //   accepted: http/https/socks5/socks5h/socks4
    #   }
    @router.post("/{provider_id}/generate-batch")
    async def provider_generate_batch(
        provider_id: str,
        body: Dict[str, Any] = Body(default_factory=dict),
        user=Depends(_get_current_user_dep),
    ):
        try:
            count = int(body.get("count") or 10)
        except Exception:
            count = 10
        count = max(1, min(count, 5000))
        country = str(body.get("country") or "").strip().upper() or None
        state = str(body.get("state") or "").strip().upper() or None
        # v2.6.3 — universal targeting overrides (work for every
        # rotating_gateway provider, not just native_proxyjet).
        city = str(body.get("city") or "").strip() or None
        zip_code = str(body.get("zip") or body.get("zip_code") or "").strip() or None
        asn = str(body.get("asn") or body.get("isp") or "").strip() or None
        session_mode = str(body.get("session_mode") or "").strip().lower() or "rotating"
        sticky_minutes = body.get("sticky_minutes")
        try:
            sticky_minutes = int(sticky_minutes) if sticky_minutes else None
        except Exception:
            sticky_minutes = None
        proxy_type_override = str(body.get("proxy_type") or "").strip().lower() or None
        if proxy_type_override and proxy_type_override not in SUPPORTED_TYPES:
            proxy_type_override = None

        # Package targeting for the provider-aware username transformer.
        targeting = {
            "country": country, "state": state, "city": city,
            "zip": zip_code, "asn": asn,
            "sticky_minutes": sticky_minutes,
            "session_mode": session_mode,
            "_want_sid": session_mode in ("sticky", "rotating"),
        }

        provider = await _get(user["id"], provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        if not provider.get("enabled"):
            raise HTTPException(400, "Provider is disabled")

        kind = provider.get("kind")
        cfg = provider.get("config") or {}
        proxy_type = proxy_type_override or provider.get("proxy_type") or "http"

        def _apply_scheme(line: str) -> str:
            """Ensure the returned proxy string has the requested scheme
            prefix. Strips any existing scheme first so the caller-
            chosen format wins."""
            if not line:
                return line
            m = re.match(r"^([a-zA-Z][a-zA-Z0-9+\-.]*)://(.*)$", line)
            body_part = m.group(2) if m else line
            return f"{proxy_type}://{body_part}"

        out: List[str] = []

        if kind == "native_proxyjet":
            # Delegate to the existing ProxyJet generator (with per-user
            # session dedup). Merge provider's saved country/state as
            # defaults when the request didn't specify them.
            try:
                import proxyjet_module as _pj  # local import to avoid cycles
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"ProxyJet module unavailable: {e}")
            try:
                out = await _pj.generate_unique_proxies(
                    _db,
                    user["id"],
                    count=count,
                    country=country or (cfg.get("country") or "US").upper(),
                    state=state or ((cfg.get("state") or "").upper() or None),
                    sticky_minutes=sticky_minutes,
                )
            except RuntimeError as e:
                raise HTTPException(400, str(e))
            # Apply proxy_type override on top of ProxyJet's user:pass@host:port
            # string (ProxyJet returns bare user:pass@host:port with no scheme,
            # so _apply_scheme just prepends).
            if proxy_type_override:
                out = [_apply_scheme(ln) for ln in out]

        elif kind == "rotating_gateway":
            # Build gateway lines. Support optional `session_param`
            # template so power users can force per-line rotation by
            # tokenising their username (e.g.
            #   "brd-customer-XXX-zone-Y-session-{sid}"
            # becomes 10 unique session-suffixed usernames when count=10).
            # 2026-07 v2.5.3 — Auto-detect common session tokens
            # (-session-XXX, -sessid-XXX, -sessionid-XXX, -sess-XXX)
            # so customers don't have to add {sid} placeholders.
            # 2026-07 v2.6.3 — Universal targeting overrides (country,
            # state, city, zip, ASN, session TTL) applied via provider-
            # aware DSL detection. Works for DataImpulse, Bright Data,
            # Oxylabs, Smartproxy, IPRoyal, ProxyEmpire, Soax, Packet-
            # Stream, and any custom gateway that uses {country}/{state}
            # /{city}/{zip}/{asn}/{ttl} placeholders in the username.
            host = str(cfg.get("gateway_host") or "").strip()
            port = str(cfg.get("gateway_port") or "").strip()
            username_tpl = str(cfg.get("username") or "").strip()
            pwd = str(cfg.get("password") or "").strip()
            if not host or not port:
                raise HTTPException(400, "gateway_host / gateway_port not configured")

            # Apply targeting overrides ONCE to the template (session id
            # is left as {sid} placeholder, rotated per-line below).
            has_targeting = any(
                targeting.get(k) for k in ("country", "state", "city", "zip", "asn", "sticky_minutes")
            )
            if has_targeting:
                username_tpl = _apply_targeting_to_username(
                    username_tpl, host, targeting, str(provider.get("name") or "")
                )

            for _ in range(count):
                # For sticky mode we still need unique per-line session
                # ids so each line points to a different sticky IP. For
                # rotating mode, gateways rotate on their own — but
                # {sid} rotation is harmless (many providers just ignore
                # the tag when rotation is dashboard-controlled).
                user_final = _rotate_session_in_username(username_tpl)
                if user_final and pwd:
                    line = f"{proxy_type}://{user_final}:{pwd}@{host}:{port}"
                else:
                    line = f"{proxy_type}://{host}:{port}"
                out.append(line)
            await _bump_use(user["id"], provider["id"])

        elif kind == "manual_list":
            lines_raw = cfg.get("lines") or ""
            if isinstance(lines_raw, list):
                lines = [str(x).strip() for x in lines_raw if str(x).strip()]
            else:
                lines = [ln.strip() for ln in str(lines_raw).splitlines() if ln.strip()]
            if not lines:
                raise HTTPException(400, "manual_list is empty")
            random.shuffle(lines)
            if count <= len(lines):
                out = lines[:count]
            else:
                # more requested than available → cycle with reshuffle
                out = []
                pool = lines[:]
                while len(out) < count:
                    if not pool:
                        pool = lines[:]
                        random.shuffle(pool)
                    out.append(pool.pop())
            # apply scheme override
            out = [_apply_scheme(ln) for ln in out]
            await _bump_use(user["id"], provider["id"])

        elif kind == "api_endpoint":
            # Call the provider API `count` times. Best-effort — skip
            # failures so a slow API doesn't abort the whole batch.
            fetched = 0
            attempts = 0
            max_attempts = count * 2  # simple safety cap
            while fetched < count and attempts < max_attempts:
                attempts += 1
                proxy = await _pick_from_api(cfg, proxy_type)
                if proxy:
                    out.append(_apply_scheme(proxy))
                    fetched += 1
            if not out:
                raise HTTPException(400, "api_endpoint returned no proxies")
            await _bump_use(user["id"], provider["id"])

        else:
            raise HTTPException(400, f"unknown provider kind: {kind}")

        # Honour provider strict/DC toggles — same guarantees as bulk fetch.
        _strict = bool(cfg.get("strict_unique_ip", True))
        _skip_dc = bool(cfg.get("skip_datacenter_ip", True))
        if out and (_strict or _skip_dc):
            _seen_ips: set = set()
            _filtered: List[str] = []
            _probe_enabled = True
            for _line in out:
                if not _probe_enabled:
                    _filtered.append(_line)
                    continue
                _info = await _probe_ip_via_proxy(_line)
                if not _info:
                    _filtered.append(_line)
                    continue
                _ip = _info.get("ip") or ""
                if _strict and _ip and _ip in _seen_ips:
                    continue
                if _skip_dc and (_info.get("is_hosting") or _info.get("is_proxy")):
                    continue
                if _ip:
                    _seen_ips.add(_ip)
                _filtered.append(_line)
            out = _filtered
            if not out:
                raise HTTPException(
                    400,
                    "No proxies passed strict unique / datacenter checks after probing",
                )

        return {
            "ok": True,
            "count": len(out),
            "proxies": out,
            "provider_id": provider["id"],
            "provider_name": provider["name"],
            "kind": kind,
            "proxy_type": proxy_type,
        }

    @router.post("/_smart-parse")
    async def smart_parse(
        body: Dict[str, Any] = Body(default_factory=dict),
        user=Depends(_get_current_user_dep),
    ):
        """Parse ANY pasted proxy strings (1-N lines, any format) and
        return per-line normalized results + a suggested provider
        config (rotating_gateway for a single credentialed line, or
        manual_list for many)."""
        strings = body.get("strings") or []
        if isinstance(strings, str):
            strings = [strings]
        default_type = str(body.get("default_type") or "http").lower()
        if default_type not in SUPPORTED_TYPES:
            default_type = "http"
        result = _bulk_parse(list(strings), default_type=default_type)
        return result

    @router.get("/{provider_id}/targeting-profile")
    async def provider_targeting_profile(
        provider_id: str,
        user=Depends(_get_current_user_dep),
    ):
        """Return the targeting fields this provider supports so the UI
        can render the correct on-demand generator (v2.6.3).

        Detection strategy:
          1. Known providers (DataImpulse, Bright Data, Oxylabs, …) →
             lookup by gateway_host substring.
          2. Custom rotating_gateway with `{country}`/`{state}`/…
             placeholders in the saved username template.
          3. Fallback → session-mode only (no geo).

        Also returns the sticky-session TTL cap (in minutes) that the
        provider is known to support, so the UI can validate the input.
        """
        provider = await _get(user["id"], provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        kind = provider.get("kind")
        cfg = provider.get("config") or {}

        supported = {
            "country": True, "state": True, "city": True,
            "zip": True, "asn": True,
            "sticky_minutes": True, "session_mode": True,
        }
        detected_provider = None
        ttl_cap_min = 120
        hint = ""
        provider_name = str(provider.get("name") or "")

        if kind == "native_proxyjet":
            detected_provider = "ProxyJet (native)"
            ttl_cap_min = 120
            hint = "Native ProxyJet — country + US state + sticky window supported."

        elif kind == "rotating_gateway":
            host = str(cfg.get("gateway_host") or "").strip()
            username_tpl = str(cfg.get("username") or "")
            profile = _detect_profile(host, provider_name)
            if profile:
                detected_provider = profile["name"]
                caps = {
                    "DataImpulse": 120,
                    "Bright Data": 30,
                    "Oxylabs": 30,
                    "Smartproxy / Decodo": 30,
                    "IPRoyal": 60,
                    "ProxyEmpire": 60,
                    "Soax": 60,
                    "PacketStream": 30,
                    "Thordata": 90,
                    "NetNut": 30,
                }
                ttl_cap_min = caps.get(profile["name"], 120)
                hint = f"{profile['name']} detected — auto-applies its DSL for the fields you fill."
            if "{ttl}" in username_tpl or (profile and profile.get("ttl_key")):
                supported["sticky_minutes"] = True
            if not detected_provider and any(
                ph in username_tpl for ph in ("{country}", "{state}", "{city}", "{zip}", "{asn}", "{ttl}", "{sid}")
            ):
                detected_provider = "Custom gateway (via {placeholders})"
                hint = "Custom gateway — placeholders detected in the username template."
            if not detected_provider:
                detected_provider = "Custom gateway"
                hint = (
                    "All targeting fields are available. For unknown gateways, add "
                    "{country}/{state}/{city}/{zip}/{asn}/{ttl}/{sid} placeholders to the username "
                    "in Settings, or use a known provider host/name so Krexion auto-detects the DSL."
                )

        elif kind == "api_endpoint":
            detected_provider = "API endpoint"
            hint = "All fields shown — geo/session values apply only if your API URL/body uses {country}/{state}/… placeholders."

        elif kind == "manual_list":
            detected_provider = "Manual list"
            hint = "Static proxy list — count/format apply; geo targeting is ignored for manual lists."

        return {
            "provider_id": provider_id,
            "provider_name": provider.get("name"),
            "kind": kind,
            "proxy_type": provider.get("proxy_type"),
            "detected_provider": detected_provider,
            "hint": hint,
            "supported": supported,
            "ttl_cap_min": ttl_cap_min,
        }

    @router.get("/_meta/catalog")
    async def provider_catalog():
        """Famous proxy brands — pre-filled gateway settings for one-click add."""
        return {"providers": PROVIDER_CATALOG, "total": len(PROVIDER_CATALOG)}

    @router.get("/_meta/kinds")
    async def kinds_meta():
        """Metadata for the frontend Add Provider dialog."""
        return {
            "kinds": [
                {
                    "key": "rotating_gateway",
                    "label": "Rotating Gateway",
                    "description": "Single sticky/rotating gateway URL (Bright Data, Oxylabs, IPRoyal Gateway, Soax, etc.)",
                    "fields": [
                        {"key": "gateway_host", "label": "Gateway host", "placeholder": "gate.brightdata.com", "type": "text"},
                        {"key": "gateway_port", "label": "Port", "placeholder": "7000", "type": "text"},
                        {"key": "username", "label": "Username (optional)", "placeholder": "brd-customer-xxx-zone-resi", "type": "text"},
                        {"key": "password", "label": "Password (optional)", "placeholder": "•••••••", "type": "password"},
                    ],
                },
                {
                    "key": "api_endpoint",
                    "label": "API Endpoint",
                    "description": "REST API that returns a proxy on demand (SmartProxy, Webshare, custom).",
                    "fields": [
                        {"key": "api_url", "label": "API URL", "placeholder": "https://provider.example.com/proxies?token=xxx", "type": "text"},
                        {"key": "method", "label": "Method", "placeholder": "GET", "type": "text"},
                        {"key": "headers", "label": "Headers (JSON, optional)", "placeholder": '{"Authorization":"Bearer xxx"}', "type": "textarea"},
                        {"key": "body", "label": "Body / Params (JSON, optional)", "placeholder": '{"country":"US"}', "type": "textarea"},
                        {"key": "response_path", "label": "Response path (JSON key/dot, optional)", "placeholder": "data.0.proxy", "type": "text"},
                    ],
                },
                {
                    "key": "manual_list",
                    "label": "Manual List / Paste Strings",
                    "description": "Paste ANY proxy strings — the tool auto-detects http/https/socks5 etc. Use the Smart Paste button above to bulk-import.",
                    "fields": [
                        {"key": "lines", "label": "Proxies (one per line, any format)", "placeholder": "socks5://user:pass@host:port\nhttp://host:port\nuser:pass@host:port\nhost:port:user:pass", "type": "textarea"},
                    ],
                },
                # v2.6.2 — Native ProxyJet kind removed from the picker.
                # Any provider (rotating gateway / API endpoint / manual
                # list) is enough — customers no longer have to configure
                # a special "ProxyJet" entry.
            ],
            "proxy_types": list(SUPPORTED_TYPES),
        }

    logger.info("Proxy provider module wired — /api/proxy-providers/*")
    return router
