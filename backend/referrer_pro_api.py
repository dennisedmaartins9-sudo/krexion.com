"""
Krexion — Referrer Pro API endpoints (2026-06-11)
==================================================

Standalone router for the Referrer Pro module's user-facing endpoints:

  POST /api/referrer-pro/generate-keywords
      → AI-powered (Claude Sonnet 4.6 via EMERGENT_LLM_KEY) per-offer
        keyword pool. Customer provides offer name + vertical + country,
        gets back 15-20 realistic search queries to feed into RUT's
        "search_keywords" pool.

  GET  /api/referrer-pro/defaults
      → Returns default email weights, platform list, supported
        search engines, country list — used by the UI to render
        multi-select chips + sliders.

Wired up in server.py via `app.include_router(referrer_pro_api.router)`.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("referrer_pro_api")

router = APIRouter(prefix="/api/referrer-pro", tags=["referrer-pro"])


# ─── Bound in by server.py via `bind_deps()` so we re-use the existing
# auth dependency without circular-import pain.
_DEPS: Dict[str, Any] = {"get_current_user": None}


def bind_deps(*, get_current_user) -> None:
    """Called once by server.py at import time."""
    _DEPS["get_current_user"] = get_current_user


def _auth_dep():
    """Return the actual auth dependency at request time (post-bind)."""
    return _DEPS.get("get_current_user")


# ──────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────
class KeywordsRequest(BaseModel):
    offer_name: str = Field(..., min_length=1, max_length=200)
    vertical: Optional[str] = Field(default="", max_length=120)
    country: Optional[str] = Field(default="us", max_length=8)
    language: Optional[str] = Field(default="en", max_length=8)
    count: int = Field(default=15, ge=5, le=40)
    intent_mix: Optional[str] = Field(default="balanced",
                                       description="balanced|informational|commercial|branded")


class KeywordsResponse(BaseModel):
    keywords: List[str]
    model_used: str
    raw_provider: str


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────
@router.get("/defaults")
async def get_defaults():
    """Return the static defaults the multi-select UI needs."""
    try:
        from referrer_pro import (
            DEFAULT_EMAIL_WEIGHTS,
            VALID_PLATFORM_KEYS,
            VALID_EMAIL_KEYS,
        )
    except Exception as e:
        logger.exception(f"referrer_pro import failed: {e}")
        raise HTTPException(status_code=500, detail="referrer_pro module unavailable")

    # Stable display order for UI rendering
    platform_order = [
        "facebook", "messenger", "instagram", "tiktok", "youtube", "twitter",
        "snapchat", "pinterest", "reddit", "linkedin",
        "google", "bing", "duckduckgo", "yahoo", "yandex",
        "baidu", "naver", "ecosia", "brave",
        "email", "whatsapp", "telegram", "discord",
    ]
    email_order = [
        "empty", "gmail", "outlook", "yahoo", "proton",
        "mailchimp", "klaviyo", "sendgrid", "hubspot", "activecampaign",
        "convertkit", "constantcontact", "mailerlite", "brevo",
        "aweber", "drip", "iterable", "marketo", "pardot",
    ]
    platforms = [p for p in platform_order if p in VALID_PLATFORM_KEYS]
    emails = [k for k in email_order if k in VALID_EMAIL_KEYS]

    return {
        "platforms": platforms,
        "email_buckets": emails,
        "email_default_weights": DEFAULT_EMAIL_WEIGHTS,
        "search_engines": [
            "google", "bing", "yahoo", "duckduckgo",
            "yandex", "youtube", "baidu", "naver", "ecosia", "brave",
        ],
        "countries": [
            # Common affiliate-traffic countries (ISO-2)
            "US", "GB", "CA", "AU", "NZ", "IE",
            "DE", "FR", "ES", "IT", "NL", "BE", "CH", "AT",
            "SE", "NO", "DK", "FI", "PL", "PT",
            "BR", "MX", "AR", "CL", "CO", "PE",
            "IN", "PK", "BD", "LK", "ID", "PH", "MY", "SG", "TH", "VN",
            "JP", "KR", "TW", "HK",
            "RU", "UA", "TR",
            "AE", "SA", "EG", "ZA", "NG", "KE", "IL",
        ],
        "intent_mixes": ["balanced", "informational", "commercial", "branded"],
    }


@router.post("/generate-keywords", response_model=KeywordsResponse)
async def generate_keywords(payload: KeywordsRequest):
    """Generate a realistic per-offer keyword pool via Claude Sonnet.

    Returns 15-20 search queries the operator can paste into RUT's
    "search_keywords" field for the search-engine Referer modes.
    """
    auth = _auth_dep()
    if auth is None:
        raise HTTPException(status_code=503, detail="Auth dependency not bound")

    # Auth gate
    try:
        from fastapi import Request  # noqa: F401
    except Exception:
        pass

    api_key = os.environ.get("EMERGENT_LLM_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503,
                            detail="EMERGENT_LLM_KEY not configured on server.")

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        logger.exception(f"emergentintegrations missing: {e}")
        raise HTTPException(status_code=503, detail="LLM library not installed")

    # ── Build prompt ────────────────────────────────────────────────
    intent = (payload.intent_mix or "balanced").lower().strip()
    intent_guidance = {
        "balanced":      "Mix 40% commercial-intent (sign-up / buy / discount), 30% informational (review / how-to / best), 30% branded (offer-name + variations).",
        "informational": "Pure informational — \"how to\", \"best\", \"review\", \"guide\", \"vs\", \"alternatives\".",
        "commercial":    "Pure high-intent — \"sign up\", \"buy\", \"discount code\", \"free trial\", \"download\", \"promo\".",
        "branded":       "Pure branded — variations of the offer name only, including misspellings + \"<name> login\", \"<name> review\", \"<name> sign up\".",
    }.get(intent, "Mix realistic search intents.")

    system = (
        "You are an SEO + paid-traffic expert specialising in affiliate-marketing "
        "offers. Output ONLY a valid JSON array of search-query strings — no "
        "commentary, no markdown, no code fences. Each query must look like "
        "something a real human would type into Google. Vary length: short "
        "(2-3 words) and long-tail (5-9 words). Use the target language only."
    )
    user_prompt = (
        f"Offer: {payload.offer_name}\n"
        f"Vertical: {payload.vertical or 'unspecified'}\n"
        f"Country: {(payload.country or 'us').upper()}\n"
        f"Language: {payload.language or 'en'}\n"
        f"Intent mix: {intent_guidance}\n"
        f"Return EXACTLY {payload.count} search queries as a JSON array of strings. "
        f"Example shape: [\"query 1\", \"query 2\", \"query 3\"]"
    )

    chat = (
        LlmChat(
            api_key=api_key,
            session_id=f"kw-{payload.offer_name[:40]}",
            system_message=system,
        )
        .with_model("anthropic", "claude-sonnet-4-6")
    )

    try:
        reply = await chat.send_message(UserMessage(text=user_prompt))
    except Exception as e:
        logger.exception(f"LLM call failed: {e}")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    raw = (reply or "").strip()
    # Strip code-fence wrapping if Claude added it despite the system msg
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    # Best-effort JSON parse
    keywords: List[str] = []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            keywords = [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        # Fallback: extract one query per non-empty line
        for ln in raw.splitlines():
            ln = ln.strip().lstrip("-*0123456789.) ").strip().strip('",')
            if ln and len(ln) <= 200:
                keywords.append(ln)

    # Hard-cap so the UI list stays sane
    keywords = keywords[:payload.count]
    if not keywords:
        raise HTTPException(status_code=502, detail="LLM returned no parseable keywords")

    return KeywordsResponse(
        keywords=keywords,
        model_used="claude-sonnet-4-6",
        raw_provider="anthropic",
    )


@router.post("/test-resolve")
async def test_resolve(payload: Dict[str, Any]):
    """Dry-run helper — given the operator's pro-mode config, returns
    a sample of N visit resolutions so the UI can show "preview" output
    before the actual job runs.
    """
    try:
        from referrer_pro import resolve_pro_visit
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"referrer_pro import failed: {e}")

    samples = max(1, min(int(payload.get("samples") or 10), 50))
    out: List[Dict[str, Any]] = []
    for _ in range(samples):
        try:
            r = resolve_pro_visit(
                ua=str(payload.get("ua") or ""),
                platform_pool_value=str(payload.get("platform_weights") or ""),
                email_weights_value=str(payload.get("email_weights") or ""),
                brand=str(payload.get("brand") or ""),
                target_url=str(payload.get("target_url") or ""),
                country=payload.get("country") or None,
                search_engine=str(payload.get("search_engine") or "google"),
                search_keywords=str(payload.get("search_keywords") or ""),
                social_wrapper_enabled=bool(payload.get("social_wrapper", True)),
                inapp_deep_path_enabled=bool(payload.get("inapp_deep_path", True)),
                strip_search_path=bool(payload.get("strip_search_path", True)),
                network_click_chain_enabled=bool(payload.get("network_click_chain", False)),
            )
            out.append(r)
        except Exception as e:
            out.append({"error": str(e)})
    return {"samples": out, "count": len(out)}
