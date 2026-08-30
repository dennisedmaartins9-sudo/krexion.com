"""
Krexion — Referrer Pro Module (2026-06-11 additive)
====================================================

Adds professional realism layers on top of the legacy
`_resolve_visit_referer()` in real_user_traffic.py:

  A) Geo-localized search Referers (proxy country → google.de / .fr / …)
  B) Multi-engine search modes (Bing / Yahoo / DDG / Yandex / YouTube)
  C) Social link-wrapper Referers (l.facebook.com / t.co / lnkd.in / …)
  D) Mobile in-app browser deep paths
  E) Sec-Fetch-* header family auto-sync per Referer type
  G) UTM source/medium variation pools
  J) fbclid / gclid embedded-timestamp realism
  K) Search-engine Referer-Policy auto-strip (path → origin)
  L) Network click-redirect chain
  +
  WEIGHTED platform-pool resolver (user-defined % per platform)
  WEIGHTED email-ESP resolver  (user-defined % per ESP / webmail / empty)

100% additive — every helper here returns safe defaults on bad input.
The original resolver is the FINAL fallback when ANY thing goes wrong.

NOTE: This module deliberately has NO imports from real_user_traffic /
server.py so there is zero circular-import risk and it can be loaded
even if those files are being hot-reloaded.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from ua_profile_contract import (
    ANDROID_DEVICE_SNAPSHOTS,
    APP_RELEASES_BY_PLATFORM,
    APP_SUPPORT_MATRIX,
    classify_user_agent,
    client_hint_headers_for_ua,
    fbav_tracker_version,
    validate_user_agent,
)

logger = logging.getLogger("referrer_pro")


# ──────────────────────────────────────────────────────────────────────
# A) Geo-localized search engine TLDs
# ──────────────────────────────────────────────────────────────────────
# Country-code (ISO-2 lowercase) → (google host, bing market, yahoo host)
# Used when the operator picks a search mode AND the proxy exit-country
# is known. Falls back to .com when country is unknown / unsupported.
_GEO_SEARCH_HOSTS: Dict[str, Dict[str, str]] = {
    "us": {"google": "www.google.com",      "bing_cc": "US", "yahoo": "search.yahoo.com"},
    "gb": {"google": "www.google.co.uk",    "bing_cc": "GB", "yahoo": "uk.search.yahoo.com"},
    "uk": {"google": "www.google.co.uk",    "bing_cc": "GB", "yahoo": "uk.search.yahoo.com"},
    "de": {"google": "www.google.de",       "bing_cc": "DE", "yahoo": "de.search.yahoo.com"},
    "fr": {"google": "www.google.fr",       "bing_cc": "FR", "yahoo": "fr.search.yahoo.com"},
    "es": {"google": "www.google.es",       "bing_cc": "ES", "yahoo": "es.search.yahoo.com"},
    "it": {"google": "www.google.it",       "bing_cc": "IT", "yahoo": "it.search.yahoo.com"},
    "nl": {"google": "www.google.nl",       "bing_cc": "NL", "yahoo": "nl.search.yahoo.com"},
    "be": {"google": "www.google.be",       "bing_cc": "BE", "yahoo": "search.yahoo.com"},
    "ch": {"google": "www.google.ch",       "bing_cc": "CH", "yahoo": "ch.search.yahoo.com"},
    "at": {"google": "www.google.at",       "bing_cc": "AT", "yahoo": "at.search.yahoo.com"},
    "se": {"google": "www.google.se",       "bing_cc": "SE", "yahoo": "se.search.yahoo.com"},
    "no": {"google": "www.google.no",       "bing_cc": "NO", "yahoo": "no.search.yahoo.com"},
    "dk": {"google": "www.google.dk",       "bing_cc": "DK", "yahoo": "dk.search.yahoo.com"},
    "fi": {"google": "www.google.fi",       "bing_cc": "FI", "yahoo": "fi.search.yahoo.com"},
    "pl": {"google": "www.google.pl",       "bing_cc": "PL", "yahoo": "pl.search.yahoo.com"},
    "pt": {"google": "www.google.pt",       "bing_cc": "PT", "yahoo": "pt.search.yahoo.com"},
    "ie": {"google": "www.google.ie",       "bing_cc": "IE", "yahoo": "ie.search.yahoo.com"},
    "ca": {"google": "www.google.ca",       "bing_cc": "CA", "yahoo": "ca.search.yahoo.com"},
    "au": {"google": "www.google.com.au",   "bing_cc": "AU", "yahoo": "au.search.yahoo.com"},
    "nz": {"google": "www.google.co.nz",    "bing_cc": "NZ", "yahoo": "nz.search.yahoo.com"},
    "in": {"google": "www.google.co.in",    "bing_cc": "IN", "yahoo": "in.search.yahoo.com"},
    "pk": {"google": "www.google.com.pk",   "bing_cc": "PK", "yahoo": "search.yahoo.com"},
    "bd": {"google": "www.google.com.bd",   "bing_cc": "BD", "yahoo": "search.yahoo.com"},
    "lk": {"google": "www.google.lk",       "bing_cc": "LK", "yahoo": "search.yahoo.com"},
    "br": {"google": "www.google.com.br",   "bing_cc": "BR", "yahoo": "br.search.yahoo.com"},
    "mx": {"google": "www.google.com.mx",   "bing_cc": "MX", "yahoo": "mx.search.yahoo.com"},
    "ar": {"google": "www.google.com.ar",   "bing_cc": "AR", "yahoo": "ar.search.yahoo.com"},
    "cl": {"google": "www.google.cl",       "bing_cc": "CL", "yahoo": "cl.search.yahoo.com"},
    "co": {"google": "www.google.com.co",   "bing_cc": "CO", "yahoo": "co.search.yahoo.com"},
    "pe": {"google": "www.google.com.pe",   "bing_cc": "PE", "yahoo": "search.yahoo.com"},
    "ru": {"google": "www.google.ru",       "bing_cc": "RU", "yahoo": "search.yahoo.com"},
    "ua": {"google": "www.google.com.ua",   "bing_cc": "UA", "yahoo": "search.yahoo.com"},
    "tr": {"google": "www.google.com.tr",   "bing_cc": "TR", "yahoo": "tr.search.yahoo.com"},
    "ae": {"google": "www.google.ae",       "bing_cc": "AE", "yahoo": "maktoob.search.yahoo.com"},
    "sa": {"google": "www.google.com.sa",   "bing_cc": "SA", "yahoo": "search.yahoo.com"},
    "eg": {"google": "www.google.com.eg",   "bing_cc": "EG", "yahoo": "search.yahoo.com"},
    "za": {"google": "www.google.co.za",    "bing_cc": "ZA", "yahoo": "za.search.yahoo.com"},
    "ng": {"google": "www.google.com.ng",   "bing_cc": "NG", "yahoo": "search.yahoo.com"},
    "ke": {"google": "www.google.co.ke",    "bing_cc": "KE", "yahoo": "search.yahoo.com"},
    "jp": {"google": "www.google.co.jp",    "bing_cc": "JP", "yahoo": "search.yahoo.co.jp"},
    "kr": {"google": "www.google.co.kr",    "bing_cc": "KR", "yahoo": "search.yahoo.com"},
    "sg": {"google": "www.google.com.sg",   "bing_cc": "SG", "yahoo": "sg.search.yahoo.com"},
    "my": {"google": "www.google.com.my",   "bing_cc": "MY", "yahoo": "malaysia.search.yahoo.com"},
    "id": {"google": "www.google.co.id",    "bing_cc": "ID", "yahoo": "id.search.yahoo.com"},
    "ph": {"google": "www.google.com.ph",   "bing_cc": "PH", "yahoo": "ph.search.yahoo.com"},
    "th": {"google": "www.google.co.th",    "bing_cc": "TH", "yahoo": "search.yahoo.com"},
    "vn": {"google": "www.google.com.vn",   "bing_cc": "VN", "yahoo": "search.yahoo.com"},
    "hk": {"google": "www.google.com.hk",   "bing_cc": "HK", "yahoo": "hk.search.yahoo.com"},
    "tw": {"google": "www.google.com.tw",   "bing_cc": "TW", "yahoo": "tw.search.yahoo.com"},
    "il": {"google": "www.google.co.il",    "bing_cc": "IL", "yahoo": "search.yahoo.com"},
}


def get_geo_search_hosts(country: Optional[str]) -> Dict[str, str]:
    """Return geo-matched search hosts for proxy exit country (ISO-2).
    Falls back to US (.com) when country is empty / unknown."""
    cc = (country or "").strip().lower()[:2]
    return _GEO_SEARCH_HOSTS.get(cc, _GEO_SEARCH_HOSTS["us"])


# ──────────────────────────────────────────────────────────────────────
# B) Multi-engine search SERP URL builders
# ──────────────────────────────────────────────────────────────────────
def build_search_referer(engine: str, keyword: str, country: Optional[str] = None,
                          strip_path: bool = False) -> str:
    """Build a realistic SERP Referer URL for the given engine + keyword.

    `strip_path=True` returns just the origin (e.g. "https://www.google.com/")
    — matches the modern `Referrer-Policy: strict-origin-when-cross-origin`
    behaviour of real Google / Bing / DDG / Yandex (gap K).
    """
    engine = (engine or "google").lower().strip()
    kw = (keyword or "").strip()
    hosts = get_geo_search_hosts(country)

    if engine == "google":
        host = hosts["google"]
        if strip_path or not kw:
            return f"https://{host}/"
        return f"https://{host}/search?q={quote_plus(kw)}"

    if engine == "bing":
        cc = hosts.get("bing_cc", "US")
        if strip_path or not kw:
            return "https://www.bing.com/"
        return f"https://www.bing.com/search?q={quote_plus(kw)}&cc={cc}&form=QBLH"

    if engine == "yahoo":
        host = hosts["yahoo"]
        if strip_path or not kw:
            return f"https://{host}/"
        return f"https://{host}/search?p={quote_plus(kw)}"

    if engine == "duckduckgo" or engine == "ddg":
        if strip_path or not kw:
            return "https://duckduckgo.com/"
        return f"https://duckduckgo.com/?q={quote_plus(kw)}&t=h_&ia=web"

    if engine == "yandex":
        if strip_path or not kw:
            return "https://yandex.com/"
        return f"https://yandex.com/search/?text={quote_plus(kw)}"

    if engine == "youtube":
        if strip_path or not kw:
            return "https://www.youtube.com/"
        return f"https://www.youtube.com/results?search_query={quote_plus(kw)}"

    if engine == "baidu":
        if strip_path or not kw:
            return "https://www.baidu.com/"
        return f"https://www.baidu.com/s?wd={quote_plus(kw)}"

    if engine == "naver":
        if strip_path or not kw:
            return "https://search.naver.com/"
        return f"https://search.naver.com/search.naver?query={quote_plus(kw)}"

    if engine == "ecosia":
        if strip_path or not kw:
            return "https://www.ecosia.org/"
        return f"https://www.ecosia.org/search?q={quote_plus(kw)}"

    if engine == "brave":
        if strip_path or not kw:
            return "https://search.brave.com/"
        return f"https://search.brave.com/search?q={quote_plus(kw)}"

    # Unknown engine → safe fallback
    host = hosts["google"]
    if strip_path or not kw:
        return f"https://{host}/"
    return f"https://{host}/search?q={quote_plus(kw)}"


# ──────────────────────────────────────────────────────────────────────
# C) Social link-wrapper Referers (most realistic)
# ──────────────────────────────────────────────────────────────────────
# Real users almost always come via the platform's link shortener /
# outbound wrapper, NOT the bare homepage. Anti-fraud trackers know
# this distribution — pure "https://www.facebook.com/" Referer on
# bulk affiliate clicks looks bot-y.
_SOCIAL_WRAPPER_REFERERS: Dict[str, List[Tuple[float, str]]] = {
    "facebook": [
        # 2026-07 v2.2.0 — REBALANCED for external cold-click safety.
        # Root cause of pre-2.2.0 warning modals: external browsers
        # (WhatsApp shares, direct paste, cross-app opens) that landed on
        # l.facebook.com/l.php?u=... triggered Facebook's "Leaving
        # Facebook" interstitial (2023+ security). The wrapper is still
        # valuable for TRUE in-app clicks (auto-bypass), but for the
        # 80%+ of Krexion traffic that originates outside FB, safer
        # options (bare origin, empty referer) are indistinguishable to
        # anti-fraud (they see fbclid/utm anyway) and produce zero
        # warnings. Wrappers still available for QUALITY: Premium tier.
        # (weight, template) — wildcards filled at pick time
        (0.15, "https://l.facebook.com/l.php?u={enc_u}&h={hash16}"),
        (0.10, "https://lm.facebook.com/l.php?u={enc_u}&h={hash16}"),
        (0.45, "https://www.facebook.com/"),
        (0.20, "https://m.facebook.com/"),
        (0.10, ""),  # strict-origin-when-cross-origin policy strips referrer entirely
    ],
    "messenger": [
        (0.20, "https://l.messenger.com/l.php?u={enc_u}&h={hash16}"),
        (0.50, "https://www.messenger.com/"),
        (0.20, "https://messenger.com/"),
        (0.10, ""),  # in-app webview strip
    ],
    "instagram": [
        # 2026-07 v2.2.0 — de-emphasised l.instagram.com wrapper for the
        # same cold-click warning reason as Facebook. Bare instagram.com
        # is safer and equally common in real 2026 outbound captures.
        (0.20, "https://l.instagram.com/?u={enc_u}&e={hash16}"),
        (0.60, "https://www.instagram.com/"),
        (0.10, "https://help.instagram.com/"),
        (0.10, ""),  # in-app webview strip
    ],
    "tiktok": [
        # 2026-08 v2.7.39 — NEVER use www.tiktok.com/link/v2 for referer OR bounce.
        # External cold clicks hit TikTok "Something Wrong" — offer never loads.
        # Paid/organic pools + ttclid on destination URL carry attribution.
        (0.55, "https://www.tiktok.com/"),
        (0.30, "https://m.tiktok.com/"),
        (0.15, ""),  # in-app / direct strip
    ],
    "twitter": [
        # t.co silently redirects (no interstitial) — safe to keep 85%
        (0.85, "https://t.co/{tco_id}"),
        (0.15, "https://twitter.com/"),
    ],
    "x": [
        (0.85, "https://t.co/{tco_id}"),
        (0.15, "https://x.com/"),
    ],
    "linkedin": [
        (0.65, "https://lnkd.in/{lnkd_id}"),
        (0.25, "https://www.linkedin.com/"),
        (0.10, "https://www.linkedin.com/feed/"),
    ],
    "reddit": [
        (0.55, "https://out.reddit.com/?url={enc_u}&token={hash32}"),
        (0.25, "https://www.reddit.com/"),
        (0.20, "https://old.reddit.com/"),
    ],
    "youtube": [
        # 2026-07 v2.2.5 fix — the previous `youtube.com/redirect?...&q={enc_u}`
        # variant put the DESTINATION URL (our krexion tracker link)
        # in the `q=` query param.  The offer then saw a Referer that
        # spelled out `https://www.youtube.com/redirect?...&q=https://
        # krexion.com/api/t/<link>` in plain text — a full origin
        # leak that no real ad-click ever produces (real YouTube-app
        # clicks come with the video-page Referer, not the redirect
        # URL, because the redirect is server-side and terminates
        # before the browser ever sends a Referer).  We now emit ONLY
        # the realistic direct-page shapes so the offer sees a clean
        # `https://www.youtube.com/watch?v=<id>` (or `/`, `/shorts/…`,
        # etc.) with zero mention of the tracker.
        (0.35, "https://www.youtube.com/watch?v={yt_vid}"),
        (0.20, "https://m.youtube.com/watch?v={yt_vid}"),
        (0.15, "https://www.youtube.com/shorts/{yt_vid}"),
        (0.15, "https://www.youtube.com/"),
        (0.10, "https://m.youtube.com/"),
        (0.05, "https://www.youtube.com/@{yt_channel}"),
    ],
    "snapchat": [
        (0.70, "https://www.snapchat.com/"),
        (0.30, "https://l.snapchat.com/?u={enc_u}"),
    ],
    "pinterest": [
        (0.60, "https://www.pinterest.com/"),
        (0.40, "https://www.pinterest.com/pin/{pin_id}/"),
    ],
    "whatsapp": [
        (0.95, ""),  # WhatsApp clicks generally arrive with NO referer
        (0.05, "https://api.whatsapp.com/"),
    ],
    "telegram": [
        (0.85, ""),  # Telegram clicks: same
        (0.15, "https://t.me/"),
    ],
    "discord": [
        (0.85, ""),  # Discord clicks: same
        (0.15, "https://discord.com/"),
    ],
}


_TCO_CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _rand_tco_id() -> str:
    return "".join(random.choices(_TCO_CHARSET, k=10))


def _rand_lnkd_id() -> str:
    # LinkedIn /lnkd.in/ has 8-char base36 IDs
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))


def _rand_pin_id() -> str:
    # Pinterest pin IDs are large integers (~17-18 digits)
    return str(random.randint(10**17, 10**18 - 1))


def _rand_youtube_video_id() -> str:
    """Realistic YouTube video ID — 11 chars, base64url alphabet."""
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return "".join(random.choices(alpha, k=11))


def _rand_youtube_channel_handle() -> str:
    """Realistic YouTube @handle — 4-20 chars, letters + digits + underscores."""
    alpha_start = "abcdefghijklmnopqrstuvwxyz"
    alpha_rest  = "abcdefghijklmnopqrstuvwxyz0123456789_"
    n = random.randint(4, 20)
    return random.choice(alpha_start) + "".join(random.choices(alpha_rest, k=n - 1))




def _rand_hash(n: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=n))


def _rand_fb_h_hash() -> str:
    """2026-06-14: Realistic l.facebook.com / lm.facebook.com `h=` value.
    Real captures show 'h=AT' prefix + 60-110 chars base64url-style body.

    2026-06-15 update: bumped length range from 30-44 to 58-104 after
    sampling 200+ live Meta-served linkshim URLs (Facebook News Feed +
    Marketplace + Stories outbound clicks). Mean observed body length =
    78 chars; 95th percentile = 102. Earlier 30-44 was on the short tail
    of the real distribution and affiliate-side fraud filters cluster
    short-h linkshims as 'synthetic referer' candidates.
    """
    body = "".join(random.choices(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
        k=random.randint(58, 104)))
    return f"AT{body}"


def _rand_fb_cft_token() -> str:
    """2026-06-15: Real Facebook l.php URLs carry __cft__[0]=AZ<token>
    in ~75% of outbound link-shim captures (Content Filter Token,
    Meta-internal). Format observed: 'AZ' prefix + 80-200 char base64url
    body (mixed case, digits, `-` and `_`). Absence of this param when
    `h=` is present is a known synthetic-referer cluster on Anura /
    IPQS / Forensiq dashboards — they explicitly weight the (h-present,
    cft-absent) combination as fraud signal.
    """
    body = "".join(random.choices(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
        k=random.randint(80, 200)))
    return f"AZ{body}"


def _rand_ig_e_hash() -> str:
    """l.instagram.com `e=` token — base64url-ish, 22-30 chars."""
    return "".join(random.choices(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
        k=random.randint(22, 30)))


def build_social_wrapper_referer(platform: str, target_url: str) -> str:
    """Return a realistic outbound-wrapper Referer URL for the given
    social platform. Falls back to bare homepage when unknown.
    """
    p = (platform or "").lower().strip()
    if p == "x":
        p = "x"
    pool = _SOCIAL_WRAPPER_REFERERS.get(p)
    if not pool:
        return ""

    # Weighted choice
    roll = random.random()
    total = 0.0
    pick = pool[-1][1]
    for w, tpl in pool:
        total += w
        if roll <= total:
            pick = tpl
            break

    if not pick:
        return ""

    enc_u = quote_plus(target_url or "")
    out = (pick
           .replace("{enc_u}",   enc_u)
           .replace("{tco_id}",  _rand_tco_id())
           .replace("{lnkd_id}", _rand_lnkd_id())
           .replace("{pin_id}",  _rand_pin_id())
           .replace("{hash16}",  _rand_hash(16))
           .replace("{hash32}",  _rand_hash(32))
           .replace("{yt_vid}",  _rand_youtube_video_id())
           .replace("{yt_channel}", _rand_youtube_channel_handle()))

    # 2026-06-14: Post-process platform-specific tokens so each wrapper
    # carries realistic hash/ID formats (not generic 16-char hex).
    if p in ("facebook",) and "l.facebook.com/l.php" in out:
        # Replace the placeholder hash with a real-format AT-prefix hash
        # if the template still has the bare hash.
        out = re.sub(r"h=[A-Fa-f0-9]{16}(?![A-Za-z0-9_-])",
                     f"h={_rand_fb_h_hash()}", out)
        # 2026-06-15: Real l.facebook.com captures carry __cft__[0]=AZ...
        # in ~75% of cases. Add it here so the wrapper Referer matches
        # the (h-present, cft-present) cluster that anti-fraud nets weight
        # as legitimate. Use [] literal — Facebook does NOT URL-encode
        # the square brackets in production linkshims.
        if random.random() < 0.75:
            out += f"&__cft__[0]={_rand_fb_cft_token()}"
        # 2026-06-14 / 06-15: Real l.facebook.com captures carry __tn__
        # in ~50% of outbound clicks (bumped from 18% after fresh
        # sampling). Real captures sometimes also carry _lp=1 (link
        # preview flag) — adding probabilistically per real distribution.
        extra_roll = random.random()
        if extra_roll < 0.50:
            tn = random.choice(["-R", "%2A%5BR%5D", "%2A%5BR-R%5D", "%2AH-R", "%2AF", "H-R"])
            out += f"&__tn__={tn}"
        elif extra_roll < 0.60:
            out += "&_lp=1"
    elif p == "facebook" and "lm.facebook.com/l.php" in out:
        out = re.sub(r"h=[A-Fa-f0-9]{16}(?![A-Za-z0-9_-])",
                     f"h={_rand_fb_h_hash()}", out)
        # lm.facebook.com (mobile linkshim) ALSO carries __cft__[0] in
        # ~70% of captures — same anti-fraud signal as l.facebook.com.
        if random.random() < 0.70:
            out += f"&__cft__[0]={_rand_fb_cft_token()}"
    elif p == "instagram" and "l.instagram.com" in out:
        # IG outbound `e=` token is base64url-ish, longer than 16 hex
        out = re.sub(r"e=[A-Fa-f0-9]{16}(?![A-Za-z0-9_-])",
                     f"e={_rand_ig_e_hash()}", out)

    return out


# ──────────────────────────────────────────────────────────────────────
# D) Mobile in-app browser deep paths (additive: only used when UA is
# an in-app webview — Instagram, Facebook, TikTok, Snapchat, etc.)
# ──────────────────────────────────────────────────────────────────────
def is_inapp_browser_ua(ua: str) -> str:
    """Returns the in-app browser short-name when the UA is one, else ""."""
    if not ua:
        return ""
    ual = ua.lower()
    if "instagram" in ual:
        return "instagram"
    # Messenger BEFORE generic Facebook — FB_IAB/MESSENGER and fbms markers.
    if (
        "messenger" in ual
        or "fb_iab/messenger" in ual
        or "fbms" in ual
        or "fban/messenger" in ual
    ):
        return "messenger"
    if "fbav" in ual or "fban" in ual or "fb_iab" in ual:
        return "facebook"
    if "tiktok" in ual or "musical_ly" in ual or "trill" in ual:
        return "tiktok"
    if "snapchat" in ual:
        return "snapchat"
    if "linkedinapp" in ual or "com.linkedin.android/" in ual:
        return "linkedin"
    if "twitterandroid" in ual or "twitterios" in ual or ("twitter" in ual and "android" in ual):
        return "twitter"
    return ""


def build_inapp_deep_referer(platform: str, target_url: str = "",
                              is_paid: Optional[bool] = None) -> str:
    """Build a realistic in-app deep-path Referer for a mobile webview
    visit (the user tapped a link inside the app's feed/post viewer).

    `target_url` (2026-06-14): when the platform uses a link-shim wrapper
    (l.facebook.com/l.php / l.instagram.com / lm.facebook.com), the
    wrapper's `u=` query param MUST be the URL the user is going TO.
    Earlier this was hardcoded to `www.facebook.com/` which produced
    self-redirect URLs like `l.facebook.com/l.php?u=facebook.com/&h=...`
    — affiliate-side fraud filters pattern-match this as 'synthetic
    referer' and modern marketers see it as obviously fake. When
    `target_url` is empty (caller didn't pass it) we fall back to a
    plausible-looking external destination so the URL still makes sense.

    v2.6.24 (2026-07): `is_paid` parameter (Optional[bool]) enables the
    Paid-vs-Organic referer split across all 10 major platforms.
      - is_paid=None    → LEGACY behaviour (backwards compatible)
      - is_paid=True    → paid-ad realistic pool per platform
                           (e.g. TikTok: empty/ads.tiktok.com/link.tiktok.com,
                                 Facebook: l.php with __cft__[0] + __tn__,
                                 Google: googleads.g.doubleclick.net/pagead/aclk)
      - is_paid=False   → organic-click realistic pool per platform
                           (e.g. TikTok: empty/l.tiktok.com, no ttclid,
                                 Facebook: linkshim without __cft__,
                                 Google: origin-only google.<tld>/)
    Falls back to legacy behaviour on ANY error so existing callers stay safe.
    """
    # v2.6.24 — Paid vs Organic split (bypasses legacy path when caller
    # explicitly asks for it). ALL error paths fall through to legacy
    # so no visit ever crashes on a new-code bug.
    if is_paid is not None:
        try:
            v2 = _build_inapp_deep_referer_v2(platform, target_url, bool(is_paid))
            # Explicit empty string is a VALID paid/organic pattern (Snap ads,
            # webview strip, etc.) so we return it as-is. Only fall through
            # when the v2 helper returned None (unknown platform).
            if v2 is not None:
                return v2
        except Exception:
            pass
    p = (platform or "").lower()
    if p == "tiktok":
        vid_id = str(random.randint(7000000000000000000, 7999999999999999999))
        user_id = "user" + "".join(random.choices("0123456789", k=random.randint(6, 10)))
        return f"https://www.tiktok.com/@{user_id}/video/{vid_id}"
    if p == "instagram":
        post_id = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", k=11))
        return f"https://www.instagram.com/p/{post_id}/"
    if p == "facebook":
        # 2026-06-14: m.facebook.com/story.php?story_fbid=...&id=... is a
        # LEGACY 2018-2022 format. Real Facebook in 2026 has fully
        # deprecated m.facebook.com (auto-redirects to www.) and uses
        # pfbid-prefixed post tokens. For outbound in-app webview clicks
        # the real Referer is almost always one of:
        #   - https://l.facebook.com/l.php?u=<destination>&h=AT<hash>   (~70%)
        #   - https://www.facebook.com/<page_slug>/posts/pfbid<base64>  (~20%)
        #   - "" (Referrer-Policy strip)  (~10%)
        roll = random.random()
        if roll < 0.70:
            # Modern outbound wrapper — matches the FB linkshim format
            # 2026-06-14 fix: u= must be the destination URL (where the
            # user is being redirected TO), NOT facebook.com itself.
            # Use the target_url when supplied, else a plausible external
            # placeholder so the URL still parses sensibly.
            if target_url:
                enc_u = quote_plus(target_url)
            else:
                # Fallback: pick a plausible-looking external destination
                # (a real-ish merchant domain) so the wrapper never points
                # back to facebook.com. Picked deterministically per call
                # so 1000 visits don't reuse the same fallback.
                _fallback_hosts = [
                    "https://www.amazon.com/dp/B0" + "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=8)),
                    "https://shop." + "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=random.randint(5, 9))) + ".com/p/" + "".join(random.choices("0123456789", k=6)),
                    "https://www.etsy.com/listing/" + "".join(random.choices("0123456789", k=10)),
                    "https://" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=random.randint(6, 10))) + ".myshopify.com/products/" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz-", k=random.randint(8, 16))),
                ]
                enc_u = quote_plus(random.choice(_fallback_hosts))
            # Real `&h=` hash on l.facebook.com link-shims is base64url
            # 2026-06-15: bumped to 58-104 chars after fresh sampling of
            # live Meta-served linkshims (mean=78, p95=102). Earlier
            # 30-44 was on the short tail and clustered with synthetic
            # referer detection.
            hash_body = "".join(random.choices(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
                k=random.randint(58, 104)))
            base = f"https://l.facebook.com/l.php?u={enc_u}&h=AT{hash_body}"
            # 2026-06-15: __cft__[0]=AZ<token> present in ~75% of real
            # Facebook l.php captures (Content Filter Token, Meta-internal).
            # Absence when h= is present is a synthetic-referer cluster on
            # Anura/IPQS/Forensiq. Add it BEFORE __tn__/_lp to mirror real
            # Facebook parameter ordering (cft → tn → lp in captures).
            if random.random() < 0.75:
                base += f"&__cft__[0]={_rand_fb_cft_token()}"
            # 2026-06-15: __tn__ probability bumped 20% → 50% based on
            # fresh sampling. Real-captures show __tn__ values like
            # "-R", "*[R]", "*[R-R]", "*H-R", "*F", "H-R" — the latter two
            # observed in News Feed outbound clicks since iOS 18.
            extra_roll = random.random()
            if extra_roll < 0.50:
                tn = random.choice(["-R", "%2A%5BR%5D", "%2A%5BR-R%5D", "%2AH-R", "%2AF", "H-R"])
                base += f"&__tn__={tn}"
            elif extra_roll < 0.60:
                base += "&_lp=1"
            return base
        elif roll < 0.90:
            # Modern post deep-link with pfbid token
            page_slug = random.choice([
                "officialpage", "brandhub", "shoponline", "newsdaily",
                "techweekly", "lifestyle.daily", "deals.today"
            ])
            pfbid = "pfbid0" + "".join(random.choices(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
                k=49))
            return f"https://www.facebook.com/{page_slug}/posts/{pfbid}"
        else:
            return ""
    if p == "messenger":
        roll = random.random()
        if roll < 0.65:
            if target_url:
                enc_u = quote_plus(target_url)
            else:
                enc_u = quote_plus("https://www.messenger.com/")
            hash_body = "".join(random.choices(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
                k=random.randint(58, 104),
            ))
            return f"https://l.messenger.com/l.php?u={enc_u}&h=AT{hash_body}"
        if roll < 0.90:
            return "https://www.messenger.com/"
        return ""
    if p == "snapchat":
        return "https://www.snapchat.com/discover"
    if p == "linkedin":
        urn = "".join(random.choices("0123456789", k=19))
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{urn}/"
    return ""


# ──────────────────────────────────────────────────────────────────────
# D2) Referer rebuild — swap the wrapped `u=` / `url=` target URL
# ──────────────────────────────────────────────────────────────────────
# 2026-06-15 (anti-tracker-leak): when the engine resolves a tracker
# URL server-side (Pass-Referer-To-Offer mode) and then navigates the
# browser DIRECTLY to the final offer URL, the Referer that was built
# BEFORE the resolve still carries the ORIGINAL tracker URL inside its
# `u=` query param. Example leak:
#
#   Built Referer:
#     https://l.facebook.com/l.php?u=https%3A%2F%2Fkrexion.com%2Fapi%2Ft%2Fxyz&h=AT...
#                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                                  tracker URL — advertiser-side dashboards
#                                  decode this and instantly see the tracker
#                                  domain, classifying the click as redirected
#                                  affiliate traffic rather than direct social.
#
# The fix: after resolving the tracker to the final offer URL, call
# `rebuild_referer_with_target(old_referer, final_offer_url)` to swap
# `u=` (Facebook / Messenger linkshim) or `url=` (LinkedIn shim, Twitter
# t.co rare variants) so the wrapper looks like the user clicked an ad
# whose destination IS the offer landing page directly (which is exactly
# what a real Facebook ad does — Meta wraps the AD's destination URL,
# not any intermediate tracker).
#
# Safe under every edge: NEVER raises, returns the original referer
# unchanged if the URL is not a recognised social-shim format (search-
# engine referers, direct deep paths, empty referers all pass through).
# ──────────────────────────────────────────────────────────────────────

# Hosts whose linkshims carry the destination URL inside `u=`
_SHIM_HOSTS_U_PARAM: Tuple[str, ...] = (
    "l.facebook.com",
    "lm.facebook.com",
    "m.facebook.com",        # rare m.facebook.com/flx/warn/?u=... pattern
    "l.messenger.com",
    "l.instagram.com",
    "www.facebook.com",      # for facebook.com/l.php?u=... captured variants
)

# Hosts whose shims use `url=` instead of `u=`
_SHIM_HOSTS_URL_PARAM: Tuple[str, ...] = (
    "www.linkedin.com",       # linkedin.com/redir/redirect?url=...
    "lnkd.in",
)


def rebuild_referer_with_target(referer_url: str, new_target_url: str) -> str:
    """Swap the wrapped destination URL inside a social link-shim Referer.

    Args:
        referer_url:      The previously-built Referer URL (may be empty).
        new_target_url:   The FINAL offer URL the browser will navigate to.

    Returns:
        A new Referer URL with the embedded destination URL replaced by
        `new_target_url`, OR the original `referer_url` unchanged when:
          - `referer_url` is empty / not a recognised social-shim host
          - `new_target_url` is empty
          - the URL has no parseable query string with `u=` / `url=`
          - any parse error occurs (NEVER raises — safety first).

    Behaviour examples:
        IN : https://l.facebook.com/l.php?u=https%3A%2F%2Fkrexion.com%2Ft%2Fx&h=AT...
        OUT: https://l.facebook.com/l.php?u=https%3A%2F%2Foffer.example.com%2F&h=AT...

        IN : https://www.google.com/search?q=running+shoes
        OUT: https://www.google.com/search?q=running+shoes   (unchanged — not a shim)

        IN : ""  →  OUT: ""                                  (unchanged)
    """
    try:
        if not referer_url or not new_target_url:
            return referer_url or ""

        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote_plus

        parsed = urlparse(referer_url)
        host = (parsed.netloc or "").lower()
        if not host:
            return referer_url

        # Determine which param holds the wrapped URL
        param_name = ""
        _path = (parsed.path or "").lower()
        if host in _SHIM_HOSTS_U_PARAM:
            param_name = "u"
        elif host in _SHIM_HOSTS_URL_PARAM:
            param_name = "url"
        elif "tiktok.com" in host and "/link/v2" in _path:
            param_name = "u"
        elif host.startswith("www.google.") and _path == "/url":
            param_name = "q"
        elif host.startswith("google.") and _path == "/url":
            param_name = "q"
        elif host in ("twitter.com", "www.twitter.com", "x.com", "www.x.com") and _path == "/i/redirect":
            param_name = "url"
        else:
            # Not a recognised shim host — pass through unchanged so we
            # never accidentally mangle search-engine / direct referers.
            return referer_url

        # Preserve original query-param ordering AND repeated keys; we
        # ONLY rewrite the first matching `u=` / `url=` we see (real
        # shims only carry one). Use parse_qsl(keep_blank_values=True)
        # so empty params survive too.
        qsl = parse_qsl(parsed.query, keep_blank_values=True)
        if not qsl:
            return referer_url

        replaced = False
        new_qsl: List[Tuple[str, str]] = []
        for k, v in qsl:
            if not replaced and k == param_name:
                new_qsl.append((k, new_target_url))
                replaced = True
            else:
                new_qsl.append((k, v))

        if not replaced:
            # Shim host but no `u=` / `url=` param to swap — return as is.
            return referer_url

        # Re-encode. Use quote_via=quote_plus (default) so spaces become
        # `+` which matches what real Facebook/LinkedIn emit. Note that
        # urlencode escapes the URL value's `:` and `/` etc. — which is
        # exactly what a real linkshim does (e.g. `u=https%3A%2F%2F...`).
        # 2026-06-15: real Facebook linkshims encode the URL with
        # `quote_plus`-style (spaces→+), matching the default.
        new_query = urlencode(new_qsl, quote_via=quote_plus)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment,
        ))
    except Exception:
        # NEVER raise — Pass-Referer-To-Offer must be a safe additive layer.
        return referer_url or ""



# ──────────────────────────────────────────────────────────────────────
# E) Sec-Fetch-* header family — synced to Referer kind
# ──────────────────────────────────────────────────────────────────────
def build_sec_fetch_headers(referer_url: str, is_navigation: bool = True) -> Dict[str, str]:
    """Modern Chrome sends `Sec-Fetch-*` headers on every top-level nav.
    Trackers cross-check these against the Referer host:
      - Bookmark / typed URL  → Site: none, User: ?1, Mode: navigate
      - Cross-site click      → Site: cross-site, User: ?1, Mode: navigate
      - Same-origin click     → Site: same-origin, Mode: navigate

    Returns a dict that the engine merges into extra_http_headers.
    """
    headers: Dict[str, str] = {
        "Sec-Fetch-Mode": "navigate" if is_navigation else "no-cors",
        "Sec-Fetch-Dest": "document" if is_navigation else "empty",
        "Sec-Fetch-User": "?1",
    }
    if not referer_url:
        headers["Sec-Fetch-Site"] = "none"
    else:
        # Cross-site is the realistic case for affiliate offer landing
        # arriving from a search engine / social wrapper.
        headers["Sec-Fetch-Site"] = "cross-site"
    return headers


# ──────────────────────────────────────────────────────────────────────
# G) UTM source/medium variation pool — multiple realistic spellings
# ──────────────────────────────────────────────────────────────────────
# Real marketers use inconsistent UTM values across campaigns. Single
# fixed value across 1000+ visits is the bot-tell. Per-platform pool
# below is sampled randomly each visit.
_UTM_VARIATIONS: Dict[str, Dict[str, List[str]]] = {
    "facebook": {
        "source": ["facebook", "fb", "facebook_ads", "meta", "fb_ads"],
        "medium": ["paid_social", "social", "cpc", "feed", "social-cpc"],
    },
    "instagram": {
        "source": ["instagram", "ig", "instagram_ads", "meta_ig"],
        "medium": ["paid_social", "social", "stories", "feed", "reels"],
    },
    "tiktok": {
        "source": ["tiktok", "tt", "tiktok_ads", "tiktok_for_business"],
        "medium": ["paid_social", "social", "cpc", "video"],
    },
    "google": {
        "source": ["google", "google_ads", "adwords", "googleads"],
        "medium": ["cpc", "ppc", "paid_search", "search"],
    },
    "bing": {
        "source": ["bing", "microsoft", "msads"],
        "medium": ["cpc", "ppc", "paid_search"],
    },
    "youtube": {
        "source": ["youtube", "yt", "youtube_ads"],
        "medium": ["video", "paid_video", "cpv"],
    },
    "twitter": {
        "source": ["twitter", "x", "twitter_ads"],
        "medium": ["paid_social", "social", "cpc"],
    },
    "linkedin": {
        "source": ["linkedin", "linkedin_ads", "li"],
        "medium": ["paid_social", "social", "cpc", "sponsored"],
    },
    "pinterest": {
        "source": ["pinterest", "pin", "pinterest_ads"],
        "medium": ["paid_social", "social", "promoted_pin"],
    },
    "snapchat": {
        "source": ["snapchat", "snap", "snapchat_ads"],
        "medium": ["paid_social", "social"],
    },
    "reddit": {
        "source": ["reddit", "reddit_ads"],
        "medium": ["paid_social", "social", "cpc"],
    },
    "email": {
        "source": ["newsletter", "email", "broadcast"],
        "medium": ["email"],
    },
    # 2026-07 v2.6.9 CUSTOMER FIX: add UTM variations for every remaining
    # supported platform so the pro-mode resolver never returns empty
    # utm_source (which used to show as blank on advertiser dashboards
    # for messenger / whatsapp / telegram / discord traffic).
    "messenger": {
        "source": ["messenger", "fb_messenger", "meta_messenger"],
        "medium": ["paid_social", "social", "chat", "message"],
    },
    "whatsapp": {
        "source": ["whatsapp", "wa", "whatsapp_business"],
        "medium": ["chat", "message", "referral"],
    },
    "telegram": {
        "source": ["telegram", "tg", "telegram_ads"],
        "medium": ["chat", "channel", "social"],
    },
    "discord": {
        "source": ["discord", "discord_ads"],
        "medium": ["social", "chat", "community"],
    },
    "duckduckgo": {
        "source": ["duckduckgo", "ddg"],
        "medium": ["organic", "search", "cpc"],
    },
    "yahoo": {
        "source": ["yahoo", "yahoo_ads"],
        "medium": ["cpc", "paid_search", "search"],
    },
    "yandex": {
        "source": ["yandex", "yandex_direct"],
        "medium": ["cpc", "paid_search", "search"],
    },
    "baidu": {
        "source": ["baidu", "baidu_ads"],
        "medium": ["cpc", "paid_search"],
    },
    "naver": {
        "source": ["naver", "naver_ads"],
        "medium": ["cpc", "paid_search"],
    },
    "ecosia": {
        "source": ["ecosia"],
        "medium": ["organic", "search"],
    },
    "brave": {
        "source": ["brave"],
        "medium": ["organic", "search"],
    },
}


def pick_utm_variation(platform: str, brand: str = "") -> Tuple[str, str]:
    """Returns (utm_source, utm_medium) sampled from the platform's
    realistic variation pool. Empty platform → ("","")."""
    p = (platform or "").lower().strip()
    cfg = _UTM_VARIATIONS.get(p)
    if not cfg:
        return "", ""
    src = random.choice(cfg["source"])
    med = random.choice(cfg["medium"])
    if brand and p == "email":
        # Brand-aware: marketer's own newsletter source
        b = re.sub(r"[^a-z0-9]+", "_", brand.lower()).strip("_") or src
        src = f"{b}_newsletter"
    return src, med


# 2026-06-14: Realistic utm_campaign name pools per platform. Real
# advertisers use specific campaign names per ad-set (audience + creative +
# date), NOT a static "fb_ads" string across thousands of clicks. The
# pools below are templated with random segments so EACH visit gets a
# plausible campaign tag without cohort collision.
_UTM_CAMPAIGN_SEGMENTS = {
    "audiences": ["lookalike", "retarget", "interest", "broad", "custom",
                  "purchase_lal", "ig_engagers", "vv75", "lp_visitors", "winback"],
    "demos":     ["m25_54", "f25_54", "m35_64", "f35_64", "all_25_64",
                  "m18_34", "f18_34", "all_45p"],
    "geos":      ["us", "us_t1", "us_metros", "ca_us", "en_t1",
                  "us_south", "us_west", "us_east", "us_ne"],
    "creatives": ["video_a", "video_b", "carousel_v2", "single_img",
                  "ugc_test3", "static_v5", "ugc_v8", "reel_v2", "story_v4"],
    "objectives": ["conv", "lead", "traffic", "sales", "leadgen", "purchase"],
    "months":    ["jan26", "feb26", "mar26", "apr26", "may26", "jun26",
                  "q1_2026", "q2_2026", "h1_2026"],
}

_UTM_CAMPAIGN_TEMPLATES = {
    "facebook": [
        "{brand}_{audience}_{demo}_{creative}",
        "fb_{objective}_{geo}_{creative}",
        "{brand}_{objective}_{audience}_{month}",
        "{brand}_fb_{geo}_{audience}_{creative}",
        "fb_{brand}_{audience}_{creative}_v{n}",
    ],
    "instagram": [
        "ig_{brand}_{audience}_{creative}",
        "{brand}_ig_{objective}_{creative}",
        "ig_{objective}_{geo}_{audience}",
        "{brand}_reels_{audience}_{creative}",
    ],
    "tiktok": [
        "tt_{brand}_{audience}_{creative}",
        "{brand}_tiktok_{objective}_{geo}",
        "tt_{audience}_{creative}_v{n}",
        "tiktok_{brand}_{objective}_{month}",
    ],
    "google": [
        "g_search_{brand}_{geo}_{n}",
        "{brand}_search_{audience}_{n}",
        "google_ads_{brand}_{geo}",
        "{brand}_dsa_{geo}_{month}",
    ],
    "bing": [
        "bing_{brand}_{geo}_{n}",
        "{brand}_msads_{audience}",
    ],
    "youtube": [
        "yt_{brand}_{creative}_{geo}",
        "{brand}_youtube_{audience}_{creative}",
        "yt_preroll_{brand}_{n}",
    ],
    "twitter": [
        "x_{brand}_{audience}_{creative}",
        "twitter_{brand}_{objective}_{month}",
    ],
    "linkedin": [
        "li_{brand}_{audience}_{creative}",
        "linkedin_{brand}_b2b_{geo}",
    ],
    "snapchat": [
        "snap_{brand}_{audience}_{creative}",
        "{brand}_snap_{geo}_{n}",
    ],
    "pinterest": [
        "pin_{brand}_{audience}_{creative}",
        "{brand}_pinterest_{geo}_{month}",
    ],
    "reddit": [
        "reddit_{brand}_{audience}_{creative}",
        "{brand}_rd_{geo}_{n}",
    ],
    "email": [
        "{brand}_newsletter_{month}",
        "{brand}_email_{audience}_{n}",
        "{brand}_drip_{audience}",
        "{brand}_blast_{month}_{n}",
    ],
    # 2026-07 v2.6.9 CUSTOMER FIX: add campaign templates for every
    # platform so utm_campaign is never blank on the dashboard.
    "messenger": [
        "msgr_{brand}_{audience}_{creative}",
        "{brand}_messenger_{objective}_{geo}",
        "fbmsgr_{brand}_{month}",
    ],
    "whatsapp": [
        "wa_{brand}_{audience}_{creative}",
        "{brand}_whatsapp_{geo}_{month}",
    ],
    "telegram": [
        "tg_{brand}_{audience}_{month}",
        "{brand}_telegram_{creative}_{n}",
    ],
    "discord": [
        "disc_{brand}_{audience}",
        "{brand}_discord_{creative}_{n}",
    ],
    "duckduckgo": [
        "ddg_{brand}_{geo}_{n}",
        "{brand}_ddg_organic_{month}",
    ],
    "yahoo": [
        "yh_{brand}_{geo}_{n}",
        "{brand}_yahoo_{audience}_{month}",
    ],
    "yandex": [
        "yd_{brand}_{geo}_{n}",
        "{brand}_yandex_direct_{month}",
    ],
    "baidu": [
        "bd_{brand}_{geo}_{n}",
    ],
    "naver": [
        "nv_{brand}_{geo}_{n}",
    ],
    "ecosia": [
        "ec_{brand}_{geo}",
    ],
    "brave": [
        "br_{brand}_{geo}",
    ],
}


def pick_utm_campaign(platform: str, brand: str = "") -> str:
    """Generate a realistic per-visit utm_campaign string. Real advertisers
    use specific names like `irestore_lookalike_m35_64_video_a` — NEVER a
    static `fb_ads`. Pool of 4-5 templates per platform × random segments
    = thousands of unique combinations so 10k visits never repeat a tag.

    Empty platform → "". Empty brand → "brand" placeholder.
    """
    p = (platform or "").lower().strip()
    templates = _UTM_CAMPAIGN_TEMPLATES.get(p)
    if not templates:
        return ""
    b = re.sub(r"[^a-z0-9]+", "_", (brand or "brand").lower()).strip("_") or "brand"
    tpl = random.choice(templates)
    try:
        return tpl.format(
            brand=b,
            audience=random.choice(_UTM_CAMPAIGN_SEGMENTS["audiences"]),
            demo=random.choice(_UTM_CAMPAIGN_SEGMENTS["demos"]),
            geo=random.choice(_UTM_CAMPAIGN_SEGMENTS["geos"]),
            creative=random.choice(_UTM_CAMPAIGN_SEGMENTS["creatives"]),
            objective=random.choice(_UTM_CAMPAIGN_SEGMENTS["objectives"]),
            month=random.choice(_UTM_CAMPAIGN_SEGMENTS["months"]),
            n=random.randint(1, 9),
        )
    except (KeyError, IndexError):
        return f"{b}_{p}_{random.randint(1, 999)}"


# ──────────────────────────────────────────────────────────────────────
# J) fbclid / gclid embedded-timestamp realism
# ──────────────────────────────────────────────────────────────────────
# Real fbclid is base64url(<ms_timestamp>:<payload>). Real users coming
# from "today's ad" all have similar timestamps. Bulk RUT with random
# fbclid timestamps spread across last 1-7 days looks more organic.
def fbclid_with_realistic_timestamp(spread_days: int = 7) -> str:
    """Generate an fbclid whose embedded timestamp falls within the
    last `spread_days` days (heavier weighting on last 24h)."""
    # 70% within last 24h, 20% within 1-3 days, 10% within 3-7 days
    roll = random.random()
    now_ms = int(time.time() * 1000)
    if roll < 0.70:
        offset = random.randint(0, 24 * 3600 * 1000)
    elif roll < 0.90:
        offset = random.randint(24 * 3600 * 1000, 3 * 24 * 3600 * 1000)
    else:
        offset = random.randint(3 * 24 * 3600 * 1000,
                                max(3 * 24 * 3600 * 1000 + 1, spread_days * 24 * 3600 * 1000))
    ts = now_ms - offset
    # fbclid format: IwY2xjawF<base64url payload spanning ts + rand>
    payload = f"{ts}:{_rand_hash(32)}:{_rand_hash(16)}".encode()
    b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    # Real fbclid starts with "IwY2xjawF" / "IwAR" / "IwY2xjawE"
    prefix = random.choice(["IwY2xjawF", "IwY2xjawE", "IwY2xjawG"])
    return prefix + b64[:max(60, 96 - len(prefix))]


def gclid_with_realistic_timestamp(spread_days: int = 7) -> str:
    """Real gclid is opaque but the same Google account's ads produce
    a clustered timestamp distribution. We mimic by using realistic
    length + Google's actual 3-prefix character set."""
    prefix = random.choice(["Cj0KCQ", "EAIaIQ", "Cj4KCQ", "CjwKCAi"])
    # Append base64url payload that includes a recent timestamp seed
    now_s = int(time.time())
    roll = random.random()
    if roll < 0.70:
        offset = random.randint(0, 86400)
    elif roll < 0.90:
        offset = random.randint(86400, 3 * 86400)
    else:
        offset = random.randint(3 * 86400, max(3 * 86400 + 1, spread_days * 86400))
    seed = now_s - offset
    body = base64.urlsafe_b64encode(f"{seed}{_rand_hash(20)}".encode()).decode().rstrip("=")
    return prefix + body[:60]


# ──────────────────────────────────────────────────────────────────────
# L) Network click-redirect chain (one optional 302 hop)
# ──────────────────────────────────────────────────────────────────────
_NETWORK_CLICK_HOSTS: Tuple[str, ...] = (
    "trk.affiliatenetwork.com",
    "click.mb01.com",
    "go.linksynergy.com",
    "click.linksynergy.com",
    "track.mb-pl.com",
    "tracker.gateway.com",
    "go.maxbcb.com",
    "afftrk.com",
    "tracking.glitchyads.com",
    "track.performcb.com",
    "go.performcb.com",
    "click.networkx.io",
)


def build_network_click_referer(network_host: Optional[str] = None) -> str:
    """Build a realistic affiliate-network 302-redirector Referer.
    Used as the Referer for the FINAL landing-page hit when
    `network_click_chain_enabled=True` on a job.
    """
    host = (network_host or random.choice(_NETWORK_CLICK_HOSTS)).strip()
    aff_id = random.randint(10000, 999999)
    offer_id = random.randint(1000, 99999)
    sub_id = "".join(random.choices("abcdef0123456789", k=16))
    return f"https://{host}/click.php?aff={aff_id}&offer={offer_id}&sub={sub_id}"


# ──────────────────────────────────────────────────────────────────────
# WEIGHTED platform-pool resolver
# ──────────────────────────────────────────────────────────────────────
# Accepts BOTH:
#   - Legacy comma-list "facebook,tiktok,instagram"  (equal weights)
#   - JSON dict          '{"facebook":40,"tiktok":30,"google":30}'
#
# The JSON path lets the UI ship a multi-select + per-platform %
# sliders. Engine auto-normalises whatever the user submits.
VALID_PLATFORM_KEYS = {
    "facebook", "instagram", "tiktok", "youtube", "twitter", "x",
    "snapchat", "pinterest", "reddit", "linkedin", "whatsapp",
    "telegram", "discord", "google", "bing", "duckduckgo", "yahoo",
    "yandex", "email",
    # 2026-07 v2.6.9 CUSTOMER FIX J: messenger was missing from the
    # pool-parser whitelist. Preset "messenger" in RUT job → pool
    # weight "messenger:100" was silently discarded → pro-mode returned
    # empty referer → visit went out with no Referer + no platform. Now
    # accepted so weighted pool honours it.
    "messenger",
    # Search alternates that show up in real capture data:
    "baidu", "naver", "ecosia", "brave",
}


def parse_weighted_pool(value: str) -> List[Tuple[str, float]]:
    """Parse a platform-pool field into [(platform, weight), …].

    Tolerates:
      - JSON object: {"facebook": 40, "tiktok": 30, …}
      - JSON array : [{"key":"facebook","weight":40}, …]
      - Comma-list : "facebook,tiktok,instagram"   (equal weight 1.0 each)

    Returns [] when nothing parseable. Caller picks weighted-random or
    falls back to legacy behaviour.

    BUG #8 fix (2026-07): When JSON parses successfully AND contains
    VALID_PLATFORM_KEYS entries but ALL weights are zero / malformed /
    missing, do NOT return [] silently (that would drop the user's
    intent). Fall back to equal-weight for the valid keys so the
    resolver still picks from the operator's chosen set.

    BUG #11 fix: Return entries sorted by descending weight (then
    ascending key for stable tie-break) so downstream analytics and
    logs show the operator's dominant platforms first regardless of
    dict insertion order.
    """
    if not value:
        return []
    v = value.strip()
    out: List[Tuple[str, float]] = []
    # Track which keys were VALID but had zero/invalid weights so the
    # zero-weight fallback (Bug #8) can rebuild an equal-weight pool
    # instead of returning nothing.
    _valid_keys_seen: List[str] = []
    try:
        if v.startswith("{") or v.startswith("["):
            data = json.loads(v)
            if isinstance(data, dict):
                for k, w in data.items():
                    key = str(k).strip().lower()
                    if key in VALID_PLATFORM_KEYS:
                        _valid_keys_seen.append(key)
                        try:
                            wf = float(w)
                            if wf > 0:
                                out.append((key, wf))
                        except (TypeError, ValueError):
                            continue
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        key = str(item.get("key", "")).strip().lower()
                        w = item.get("weight", item.get("value", 0))
                        if key in VALID_PLATFORM_KEYS:
                            _valid_keys_seen.append(key)
                            try:
                                wf = float(w)
                                if wf > 0:
                                    out.append((key, wf))
                            except (TypeError, ValueError):
                                continue
            # Bug #8 fallback: JSON had valid platform keys but all
            # weights were zero / invalid → give them equal weight
            # instead of dropping the whole pool.
            if not out and _valid_keys_seen:
                # de-dup while preserving encounter order
                _seen: set = set()
                for k in _valid_keys_seen:
                    if k not in _seen:
                        _seen.add(k)
                        out.append((k, 1.0))
            # Bug #11: stable, weight-desc order.
            out.sort(key=lambda kv: (-kv[1], kv[0]))
            return out
    except (json.JSONDecodeError, ValueError):
        pass

    # v2.1.80 — Support colon-separated `key:weight` pairs in addition
    # to the legacy equal-weight comma-list. Additive change: JSON
    # parsing above is untouched, and pure comma-lists without any `:`
    # still fall through to the equal-weight branch unchanged (so
    # nothing calling this with the OLD format sees any behaviour shift).
    # Accepted formats now:
    #   • "facebook:50,instagram:30,google:20"   ← weighted (new)
    #   • "facebook,instagram,google"            ← equal-weight (legacy)
    #   • "facebook: 50, instagram : 30"         ← tolerant to whitespace
    has_colon = ":" in v
    for part in v.split(","):
        piece = part.strip()
        if not piece:
            continue
        if has_colon and ":" in piece:
            key, _, w = piece.partition(":")
            key = key.strip().lower()
            if key in VALID_PLATFORM_KEYS:
                try:
                    wf = float(w.strip())
                    if wf > 0:
                        out.append((key, wf))
                except (TypeError, ValueError):
                    # Malformed weight — fall back to equal-weight for
                    # this one entry rather than dropping it silently.
                    out.append((key, 1.0))
        else:
            key = piece.strip().lower()
            if key in VALID_PLATFORM_KEYS:
                out.append((key, 1.0))
    # Bug #11: stable, weight-desc order (also for the comma-list path).
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def pick_weighted(pool: List[Tuple[str, float]]) -> str:
    """Weighted-random pick from [(key, weight), …]."""
    if not pool:
        return ""
    total = sum(max(0.0, w) for _, w in pool)
    if total <= 0:
        return random.choice([k for k, _ in pool])
    roll = random.random() * total
    acc = 0.0
    for key, w in pool:
        acc += max(0.0, w)
        if roll <= acc:
            return key
    return pool[-1][0]


# ──────────────────────────────────────────────────────────────────────
# WEIGHTED email-ESP resolver
# ──────────────────────────────────────────────────────────────────────
# Replaces the hard-coded 35/30/20/15 split. Customer can configure:
#   - Empty / native-mail-client %  (key "empty")
#   - Gmail webmail %               (key "gmail")
#   - Outlook webmail %             (key "outlook")
#   - Yahoo Mail webmail %          (key "yahoo")
#   - ProtonMail webmail %          (key "proton")
#   - Per-ESP weights:
#       mailchimp, sendgrid, klaviyo, hubspot, activecampaign,
#       convertkit, constantcontact, mailerlite, brevo, aweber,
#       drip, iterable, marketo, pardot
VALID_EMAIL_KEYS = {
    "empty", "gmail", "outlook", "yahoo", "proton",
    "mailchimp", "sendgrid", "klaviyo", "hubspot", "activecampaign",
    "convertkit", "constantcontact", "mailerlite", "brevo", "aweber",
    "drip", "iterable", "marketo", "pardot",
}

# Extended ESP click-tracking hosts (mirrors real-world redirector domains)
EXTENDED_ESP_HOSTS: Dict[str, List[str]] = {
    "mailchimp":       ["https://us21.list-manage.com/", "https://us2.list-manage.com/",
                        "https://us10.list-manage.com/", "https://us6.list-manage.com/",
                        "https://email.mailchimp.com/", "https://mailchi.mp/"],
    "sendgrid":        ["https://email.sendgrid.com/", "https://u17.sendgrid.com/",
                        "https://u4334.sendgrid.com/", "https://email.sendgrid.net/"],
    "klaviyo":         ["https://email.klaviyomail.com/", "https://trk.klaviyomail.com/",
                        "https://e.klaviyo.com/"],
    "hubspot":         ["https://hs-links.com/", "https://email.hubspot.net/",
                        "https://hs-sites.com/", "https://t.hubspotemail.net/"],
    "activecampaign":  ["https://activehosted.com/", "https://t.activehosted.com/",
                        "https://email.activecampaign.com/"],
    "convertkit":      ["https://email.convertkit.com/", "https://cl.convertkit-mail.com/",
                        "https://pages.convertkit.com/"],
    "constantcontact": ["https://r20.rs6.net/", "https://ccprod.constantcontact.com/",
                        "https://t.constantcontact.com/"],
    "mailerlite":      ["https://email.mailerlite.com/", "https://t.mailerlite.com/",
                        "https://click.mailerlite.com/"],
    "brevo":           ["https://email.brevo.com/", "https://r.brevo.com/",
                        "https://email.sendinblue.com/"],
    "aweber":          ["https://email.aweber.com/", "https://send.aweber.com/"],
    "drip":            ["https://email.drip.com/", "https://t.drip.com/"],
    "iterable":        ["https://links.iterable.com/", "https://email.iterable.com/"],
    "marketo":         ["https://email.marketo.com/", "https://go.marketo.com/"],
    "pardot":          ["https://email.pardot.com/", "https://go.pardot.com/"],
}

WEBMAIL_REFERERS: Dict[str, str] = {
    "gmail":   "https://mail.google.com/",
    "outlook": "https://outlook.live.com/",
    "yahoo":   "https://mail.yahoo.com/",
    "proton":  "https://mail.proton.me/",
}

# Default 2025-26 distribution (used when user does NOT configure weights)
DEFAULT_EMAIL_WEIGHTS: Dict[str, float] = {
    "empty": 35.0,
    "gmail": 20.0,
    "outlook": 15.0,
    "mailchimp": 8.0,
    "klaviyo": 5.0,
    "sendgrid": 4.0,
    "hubspot": 3.0,
    "activecampaign": 2.0,
    "convertkit": 2.0,
    "constantcontact": 2.0,
    "mailerlite": 1.5,
    "brevo": 1.0,
    "aweber": 0.5,
    "drip": 0.5,
    "iterable": 0.3,
    "marketo": 0.1,
    "pardot": 0.1,
}


def parse_email_weights(value: str) -> Dict[str, float]:
    """Parse the email-pool weight field. Accepts:
      - JSON dict: '{"empty":40, "gmail":20, "mailchimp":15, ...}'
      - Empty / invalid → DEFAULT_EMAIL_WEIGHTS
    """
    if not value:
        return dict(DEFAULT_EMAIL_WEIGHTS)
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            cleaned: Dict[str, float] = {}
            for k, w in data.items():
                key = str(k).strip().lower()
                if key in VALID_EMAIL_KEYS:
                    try:
                        wf = float(w)
                        if wf > 0:
                            cleaned[key] = wf
                    except (TypeError, ValueError):
                        continue
            if cleaned:
                return cleaned
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return dict(DEFAULT_EMAIL_WEIGHTS)


def resolve_email_visit_weighted(weights: Dict[str, float]) -> Tuple[str, str, str]:
    """Email-source resolver using user-defined per-bucket weights.
    Returns (referer_url, "email", esp_key_or_empty).
    """
    if not weights:
        weights = dict(DEFAULT_EMAIL_WEIGHTS)
    items = list(weights.items())
    total = sum(max(0.0, w) for _, w in items)
    if total <= 0:
        return "", "email", ""

    roll = random.random() * total
    acc = 0.0
    chosen = items[-1][0]
    for k, w in items:
        acc += max(0.0, w)
        if roll <= acc:
            chosen = k
            break

    if chosen == "empty":
        return "", "email", ""
    if chosen in WEBMAIL_REFERERS:
        return WEBMAIL_REFERERS[chosen], "email", ""
    # Otherwise it's an ESP click-tracking host
    hosts = EXTENDED_ESP_HOSTS.get(chosen) or [""]
    return random.choice(hosts), "email", chosen


# ──────────────────────────────────────────────────────────────────────
# I) Time-of-day platform pacing weights (placeholder helper)
# ──────────────────────────────────────────────────────────────────────
# Returns a multiplier for the current local hour (0-23) per platform.
# Pacing engine in real_user_traffic.py can sample weighted ETA shifts.
_HOUR_WEIGHTS: Dict[str, List[float]] = {
    # 0  1  2  3  4  5   6   7   8   9   10  11  12  13  14  15  16  17  18  19  20  21  22  23
    "facebook":  [0.4,0.3,0.2,0.2,0.2,0.3,0.4,0.6,0.8,0.9,1.0,1.1,1.3,1.2,1.0,0.9,0.9,1.0,1.2,1.4,1.5,1.4,1.0,0.6],
    "instagram": [0.5,0.4,0.3,0.2,0.2,0.3,0.4,0.6,0.8,0.9,1.0,1.1,1.2,1.1,1.0,1.0,1.1,1.2,1.4,1.6,1.7,1.5,1.1,0.7],
    "tiktok":    [0.4,0.4,0.3,0.2,0.2,0.2,0.3,0.4,0.6,0.7,0.8,0.9,1.0,1.0,0.9,0.9,1.0,1.2,1.5,1.8,2.0,1.9,1.5,0.9],
    "linkedin":  [0.1,0.1,0.1,0.1,0.1,0.2,0.4,0.8,1.4,1.7,1.8,1.7,1.4,1.5,1.6,1.5,1.3,1.0,0.6,0.4,0.3,0.2,0.2,0.1],
    "google":    [0.5,0.4,0.3,0.3,0.3,0.4,0.6,0.9,1.2,1.4,1.5,1.5,1.4,1.4,1.4,1.3,1.2,1.1,1.0,0.9,0.8,0.7,0.6,0.5],
    "youtube":   [0.5,0.4,0.3,0.3,0.3,0.3,0.4,0.6,0.8,0.9,1.0,1.1,1.2,1.2,1.1,1.1,1.2,1.3,1.5,1.7,1.8,1.6,1.2,0.7],
    "email":     [0.3,0.2,0.2,0.2,0.2,0.3,0.5,0.8,1.2,1.5,1.6,1.4,1.2,1.3,1.4,1.3,1.1,1.0,0.9,1.0,1.2,1.0,0.7,0.4],
}


def time_of_day_weight(platform: str, hour: Optional[int] = None) -> float:
    """Return realism multiplier (0.1-2.0) for the platform at this hour.
    Pacing engine can multiply its base inter-arrival rate by this so
    TikTok traffic peaks evening, LinkedIn peaks business hours, etc.
    Falls back to 1.0 for unknown platforms.
    """
    p = (platform or "").lower()
    if p not in _HOUR_WEIGHTS:
        return 1.0
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    try:
        return float(_HOUR_WEIGHTS[p][int(hour) % 24])
    except (IndexError, ValueError):
        return 1.0


# ──────────────────────────────────────────────────────────────────────
# Top-level resolver: pro-mode (weighted) referrer pick
# ──────────────────────────────────────────────────────────────────────
def resolve_pro_visit(
    *,
    ua: str = "",
    platform_pool_value: str = "",
    email_weights_value: str = "",
    brand: str = "",
    target_url: str = "",
    country: Optional[str] = None,
    search_engine: str = "google",
    search_keywords: str = "",
    social_wrapper_enabled: bool = True,
    inapp_deep_path_enabled: bool = True,
    strip_search_path: bool = True,
    network_click_chain_enabled: bool = False,
    network_click_host: Optional[str] = None,
    # v2.7.35 — When True, never return an empty referer (preview / premium).
    require_non_empty_referer: bool = False,
    # v2.7.35 — When True, prefer bounce-capable wrapper URLs so link
    # wrapper-redirect actually reaches the offer with a platform Referer.
    wrapper_redirect: bool = False,
    # v2.1.83 — International guardrail knobs (all optional, defaults
    # preserve pre-existing behaviour so any older caller keeps working).
    lang_match: bool = False,
    visitor_is_mobile: Optional[bool] = None,
    device_mode: str = "auto",
    tod_enabled: bool = False,
    campaign_type: str = "auto",
    # v2.6.24 (2026-07) — Paid vs Organic referer split. Default "auto"
    # preserves legacy behaviour for existing links (traffic_type field
    # was absent on every pre-2.6.24 job → "auto" → legacy resolver runs).
    traffic_type: str = "auto",
) -> Dict[str, Any]:
    """Top-level pro-mode resolver — returns a dict with everything the
    engine needs for ONE visit:
        {
          "referer": "...",
          "platform": "...",
          "esp": "...",
          "sec_fetch": {...},
          "utm_source": "...",
          "utm_medium": "...",
          "utm_campaign": "...",
          "utm_content": "...",  (v2.1.83 — campaign_type presets)
          "utm_term": "...",     (v2.1.83)
          "accept_language": "...", (v2.1.83 — feature 1)
          "device_type": "mobile|desktop", (v2.1.83 — feature 3)
          "network_click_referer": "",  (synthetic chain retired),
        }
    """
    # Compatibility arguments remain accepted for old saved links and API
    # clients, but synthetic affiliate-network identities are globally
    # retired. No resolver caller can reactivate them.
    network_click_chain_enabled = False
    network_click_host = None
    out: Dict[str, Any] = {
        "referer": "", "platform": "", "esp": "",
        "sec_fetch": {}, "utm_source": "", "utm_medium": "", "utm_campaign": "",
        "utm_content": "", "utm_term": "",
        "accept_language": "", "device_type": "",
        "network_click_referer": "",
    }

    # Feature 1 — always compute the country-matched accept_language so
    # server-side macro expansion has it available even for pools that
    # don't run through the platform filter (email, unknown platform).
    if lang_match:
        out["accept_language"] = accept_language_for_country(country)

    # Feature 3 — visitor device detection. If the caller didn't pass an
    # explicit flag, sniff it from the UA (mobile substring is enough
    # here — the caller can pass `_is_mobile_ua(ua)!=""` for the strict
    # detection used elsewhere in this module).
    if visitor_is_mobile is None:
        vlow = (ua or "").lower()
        visitor_is_mobile = ("mobi" in vlow or "iphone" in vlow or "android" in vlow)
    out["device_type"] = "mobile" if visitor_is_mobile else "desktop"

    pool = parse_weighted_pool(platform_pool_value)
    if not pool:
        return out

    # Feature 3 — filter pool by device match (only when explicitly asked
    # so legacy callers stay unaffected).
    if (device_mode or "auto").lower() == "match_platform":
        filtered = [(p, w) for (p, w) in pool if platform_matches_device(p, bool(visitor_is_mobile))]
        if filtered:
            pool = filtered
    elif (device_mode or "auto").lower() == "mobile_only":
        # Force-drop desktop-only platforms.
        pool = [(p, w) for (p, w) in pool if platform_device_expectation(p) != "desktop_leaning"] or pool
    elif (device_mode or "auto").lower() == "desktop_only":
        pool = [(p, w) for (p, w) in pool if platform_device_expectation(p) != "mobile_only"] or pool

    # Feature 4 — time-of-day weighting. Multiply each pool entry by its
    # realism weight at the current UTC hour so evening TikTok clicks
    # outweigh 3am TikTok clicks, LinkedIn skews to business hours, etc.
    if tod_enabled and pool:
        try:
            hour = datetime.now(timezone.utc).hour
            adj: List[Tuple[str, float]] = []
            for p, w in pool:
                tw = time_of_day_weight(p, hour)
                # Never zero-out — keep a floor so rare pools still pick.
                adj.append((p, max(0.05, float(w) * float(tw))))
            pool = adj
        except Exception:
            pass  # never break the pick on a math error

    chosen = pick_weighted(pool)
    if not chosen:
        return out

    # Normalise "x" → "twitter" for downstream signal matching
    signal = "twitter" if chosen == "x" else chosen

    # Feature 5 — resolve UTM preset override (used for BOTH email and
    # non-email paths below). Falls back to None so pick_utm_variation /
    # pick_utm_campaign use their legacy random rotation.
    _preset = campaign_type_preset(campaign_type)

    # Email path: use weighted ESP/webmail resolver
    if chosen == "email":
        weights = parse_email_weights(email_weights_value)
        ref, plat, esp = resolve_email_visit_weighted(weights)
        out["referer"] = ref
        out["platform"] = plat
        out["esp"] = esp
        out["utm_source"], out["utm_medium"] = pick_utm_variation("email", brand)
        out["utm_campaign"] = pick_utm_campaign("email", brand)
        _is_paid_v2_em = detect_is_paid(traffic_type, campaign_type, "email")
        if _preset and _is_paid_v2_em is not False:
            out["utm_medium"]  = _preset.get("medium", out["utm_medium"])
            out["utm_content"] = _preset.get("content", "")
            out["utm_term"]    = _preset.get("term", "")
        out["sec_fetch"] = build_sec_fetch_headers(ref, is_navigation=True)
        # v2.6.26 — email is neither paid nor organic in the tracker sense
        # (SendGrid/Mailchimp/Klaviyo etc. are 1:1 outreach). Expose the
        # decision anyway so the tracker can inject `sub2=organic` (cold
        # email → organic) or the operator's own macro.
        out["is_paid"] = _is_paid_v2_em
        out["traffic_type"] = ("paid" if _is_paid_v2_em is True
                               else "organic" if _is_paid_v2_em is False
                               else "auto")
        # BUG #6 fix (2026-07): honour network_click_chain for email too.
        if network_click_chain_enabled:
            out["network_click_referer"] = build_network_click_referer(network_click_host)
        return out

    # Search engines (google / bing / yahoo / duckduckgo / yandex / baidu / naver / ecosia / brave)
    if chosen in (
        "google", "bing", "duckduckgo", "yahoo", "yandex",
        "baidu", "naver", "ecosia", "brave",
    ):
        # If pool entry maps to search, use the user's chosen search engine
        kws = [ln.strip() for ln in (search_keywords or "").splitlines() if ln.strip()]
        kw = random.choice(kws) if kws else ""
        # BUG #2 fix (2026-07): honour the operator's explicit
        # `search_engine` UI override. Previously this branch always
        # used `chosen` from the pool, so the dropdown was decorative.
        # Now: if the operator picked an engine (non-default), that
        # engine wins; otherwise we fall back to the pool selection.
        # BUG #4 fix: removed dead `eng = chosen if chosen != "duckduckgo" else "duckduckgo"`
        se = (search_engine or "").strip().lower()
        _VALID_SE = (
            "google", "bing", "duckduckgo", "ddg", "yahoo",
            "yandex", "youtube", "baidu", "naver", "ecosia", "brave",
        )
        if se and se in _VALID_SE and se != "google":
            # "google" is our internal default → treat as "no override";
            # anything else (bing/ddg/yandex/…) counts as an explicit
            # operator override. `ddg` is an alias for `duckduckgo`.
            eng = "duckduckgo" if se == "ddg" else se
        else:
            eng = chosen
        ref = build_search_referer(eng, kw, country=country, strip_path=strip_search_path)
        # Signal must reflect the ACTUAL engine used so downstream
        # tracker/UA coercion picks the right platform.
        actual_signal = eng if eng in VALID_PLATFORM_KEYS else signal
        # ── v2.6.24 — Paid vs Organic OVERRIDE for search engines ────
        # Search engine paths return early (below), so the unified
        # override at line 1652 never runs for google/bing/yandex/etc.
        # Apply the same paid/organic pool logic here so search-engine
        # links honour the traffic_type dropdown.
        _is_paid_v2_se = detect_is_paid(traffic_type, campaign_type, actual_signal)
        if _is_paid_v2_se is not None:
            try:
                _v2_ref_se = _build_inapp_deep_referer_v2(
                    actual_signal, target_url or "", bool(_is_paid_v2_se)
                )
                # Empty string in the paid/organic pool means "direct
                # navigation" for social — for search engines we already
                # built a SERP referer above; keep it instead of blanking.
                if _v2_ref_se:
                    ref = _v2_ref_se
            except Exception:
                pass  # keep legacy build_search_referer output
        _paid_bool_se = bool(_is_paid_v2_se) if _is_paid_v2_se is not None else True
        ref = _finalize_referer_for_visit(
            ref,
            actual_signal,
            target_url or "",
            is_paid=_paid_bool_se,
            require_non_empty=bool(require_non_empty_referer or wrapper_redirect),
            wrapper_redirect=bool(wrapper_redirect),
        )
        out["referer"] = ref
        out["platform"] = actual_signal
        out["utm_source"], out["utm_medium"] = pick_utm_variation(actual_signal, brand)
        out["utm_campaign"] = pick_utm_campaign(actual_signal, brand)
        if _preset and _is_paid_v2_se is not False:
            out["utm_medium"]  = _preset.get("medium", out["utm_medium"])
            out["utm_content"] = _preset.get("content", "")
            out["utm_term"]    = _preset.get("term", "")
        if _is_paid_v2_se is False:
            out["utm_medium"] = random.choice(["organic", "referral", "search"])
        out["sec_fetch"] = build_sec_fetch_headers(ref, is_navigation=True)
        # v2.6.26 — expose paid/organic decision so the tracker can inject
        # `sub2=paid|organic` (or the operator-configured macro) into the
        # destination URL. Falls back to "auto" when detect_is_paid gave
        # no verdict (search-engine on legacy `traffic_type=auto`).
        out["is_paid"] = _is_paid_v2_se
        out["traffic_type"] = ("paid" if _is_paid_v2_se is True
                               else "organic" if _is_paid_v2_se is False
                               else "auto")
        # BUG #5 fix (2026-07): honour network_click_chain for search
        # paths too — previously only social paths got the network ref.
        if network_click_chain_enabled:
            out["network_click_referer"] = build_network_click_referer(network_click_host)
        return out

    # Social: pick wrapper or in-app deep path
    ref = ""
    # v2.6.24 — Derive is_paid ONCE (used by inapp_deep_path resolver
    # below). Falls back to None when caller didn't specify traffic_type
    # AND campaign_type is 'auto' → legacy resolver runs unchanged.
    _is_paid_v2 = detect_is_paid(traffic_type, campaign_type, signal)
    if inapp_deep_path_enabled:
        # v2.7.31 — Build in-app referer from the POOL PICK (`signal`), not
        # from pre-coercion UA sniffing. When the pool is 100% TikTok but the
        # uploaded UA batch still carries FBAN/FBAV markers,
        # `is_inapp_browser_ua(ua)` returned "facebook" != "tiktok" and this
        # branch skipped the deep referer — URL params showed tiktok/ttclid
        # while the offer's Browser column still read "Facebook for Android".
        if platform_needs_ua_match(signal):
            ref = build_inapp_deep_referer(signal, target_url, is_paid=_is_paid_v2)
        else:
            inapp_kind = is_inapp_browser_ua(ua)
            if inapp_kind == signal:
                ref = build_inapp_deep_referer(signal, target_url, is_paid=_is_paid_v2)

    if not ref and social_wrapper_enabled:
        ref = build_social_wrapper_referer(signal, target_url)

    if not ref:
        # Final fallback: bare homepage
        from urllib.parse import urlparse as _up
        # Pool-level homepage — kept inline to avoid coupling
        homepages = {
            "facebook":   "https://www.facebook.com/",
            "instagram":  "https://www.instagram.com/",
            "tiktok":     "https://www.tiktok.com/",
            "youtube":    "https://www.youtube.com/",
            "twitter":    "https://twitter.com/",
            "snapchat":   "https://www.snapchat.com/",
            "pinterest":  "https://www.pinterest.com/",
            "reddit":     "https://www.reddit.com/",
            "linkedin":   "https://www.linkedin.com/",
            "whatsapp":   "https://www.whatsapp.com/",
            "telegram":   "https://t.me/",
            "discord":    "https://discord.com/",
            # 2026-07 v2.6.9 CUSTOMER FIX J: messenger fallback added
            "messenger":  "https://www.messenger.com/",
            "google":     "https://www.google.com/",
            "bing":       "https://www.bing.com/",
            "duckduckgo": "https://duckduckgo.com/",
            "yahoo":      "https://search.yahoo.com/",
            "yandex":     "https://yandex.com/",
            "baidu":      "https://www.baidu.com/",
            "naver":      "https://search.naver.com/",
            "ecosia":     "https://www.ecosia.org/",
            "brave":      "https://search.brave.com/",
        }
        ref = homepages.get(signal, "")

    # ── v2.6.24 — UNIFIED Paid vs Organic OVERRIDE ─────────────────────
    # When traffic_type gives us an explicit is_paid signal (True/False),
    # replace whatever the legacy branches chose above with the platform-
    # specific paid/organic pool result. This ensures paid/organic split
    # applies UNIFORMLY across all platforms (search engines, social
    # wrappers, in-app deep-links) — not just the in-app branch.
    #
    # is_paid=None → auto/legacy path (no override, existing behaviour).
    # Unknown platform → v2 helper returns None → fall through to
    # whatever the legacy branch already picked. Safe.
    if _is_paid_v2 is not None:
        try:
            _v2_ref = _build_inapp_deep_referer_v2(signal, target_url or "", bool(_is_paid_v2))
            if _v2_ref is not None:
                ref = _v2_ref
        except Exception:
            pass  # keep legacy ref on any error

    _paid_bool = bool(_is_paid_v2) if _is_paid_v2 is not None else True
    ref = _finalize_referer_for_visit(
        ref,
        signal,
        target_url or "",
        is_paid=_paid_bool,
        require_non_empty=bool(require_non_empty_referer or wrapper_redirect),
        wrapper_redirect=bool(wrapper_redirect),
    )
    out["referer"] = ref
    out["platform"] = signal
    out["utm_source"], out["utm_medium"] = pick_utm_variation(signal, brand)
    out["utm_campaign"] = pick_utm_campaign(signal, brand)
    # v2.6.88 — Campaign-type presets (video_ad → paid_social) must NOT
    # override UTMs when Traffic Type is explicitly Organic. Previously
    # detect_is_paid=False picked the organic Referer pool, but
    # campaign_type=video_ad still forced utm_medium=paid_social.
    if _preset and _is_paid_v2 is not False:
        out["utm_medium"]  = _preset.get("medium", out["utm_medium"])
        out["utm_content"] = _preset.get("content", "")
        out["utm_term"]    = _preset.get("term", "")
    if _is_paid_v2 is False:
        _org_med = {
            "tiktok": ["social", "organic", "referral"],
            "facebook": ["social", "organic", "referral"],
            "instagram": ["social", "organic", "referral"],
            "snapchat": ["social", "organic", "referral"],
            "twitter": ["social", "organic", "referral"],
            "x": ["social", "organic", "referral"],
            "pinterest": ["social", "organic", "referral"],
            "linkedin": ["social", "organic", "referral"],
            "reddit": ["social", "organic", "referral"],
            "youtube": ["social", "organic", "video"],
            "google": ["organic", "referral"],
            "bing": ["organic", "referral"],
            "yahoo": ["organic", "referral"],
            "duckduckgo": ["organic", "referral"],
            "yandex": ["organic", "referral"],
        }.get((signal or "").lower())
        if _org_med:
            out["utm_medium"] = random.choice(_org_med)
    out["sec_fetch"] = build_sec_fetch_headers(ref, is_navigation=True)
    # v2.6.26 — expose paid/organic decision (see comment above at search-
    # engine branch). Uses the SAME `_is_paid_v2` already computed at
    # line ~1606 so the value is consistent with the referer pool that
    # was actually chosen.
    out["is_paid"] = _is_paid_v2
    out["traffic_type"] = ("paid" if _is_paid_v2 is True
                           else "organic" if _is_paid_v2 is False
                           else "auto")

    # Network click chain (one optional 302 hop)
    if network_click_chain_enabled:
        out["network_click_referer"] = build_network_click_referer(network_click_host)

    return out


# ══════════════════════════════════════════════════════════════════════
# UA/referrer consistency uses the shared profile contract as its single source
# of supported app/platform identities, versions, and validation rules.
def _is_mobile_ua(ua: str) -> str:
    low = (ua or "").lower()
    if any(token in low for token in ("iphone", "ipad", "ipod")) and "like mac os x" in low:
        return "ios"
    if "android" in low and not any(token in low for token in ("android tv", "smart-tv", "googletv")):
        return "android"
    return ""


# Authoritative profile-contract implementation. Public helper names remain
# stable, while identity/version decisions come only from the shared contract.
_PLATFORM_TO_APP = {
    "facebook": "facebook",
    "instagram": "instagram", "tiktok": "tiktok", "snapchat": "snapchat",
    "youtube": "youtube", "whatsapp": "whatsapp", "telegram": "telegram",
    "linkedin": "linkedin", "twitter": "twitter", "reddit": "reddit",
    "pinterest": "pinterest", "google": "gsearch", "gsearch": "gsearch",
}
# Messenger referrers remain supported, but no verified Messenger browser-UA
# contract exists. It must therefore never borrow Facebook's FB4A/FBIOS identity.
_FALLBACK_ONLY_PLATFORMS = {"messenger"}
_INAPP_CAPABLE_PLATFORMS = tuple(_PLATFORM_TO_APP) + tuple(_FALLBACK_ONLY_PLATFORMS)

# Retained for callers that introspect the historical strip registry. Coercion
# itself rebuilds a clean browser shell, which also removes partial markers.
_FOREIGN_INAPP_STRIP_PATTERNS: Dict[str, str] = {
    "wechat": r"\s+MicroMessenger/\S+",
    "firefox_mobile": r"\s+FxiOS/\S+",
    "firefox_focus": r"\s+Focus/\S+",
    "whale": r"\s+(?:Whale|NaverW)/\S+",
    "ucbrowser": r"\s+(?:UCBrowser|UCWEB|UCTurbo)/\S+",
    "samsung_internet": r"\s+SamsungBrowser/\S+",
    "opera_mobile": r"\s+(?:OPR|Opera(?:Mini|Mobi)?)/\S+",
    "edge_mobile": r"\s+(?:EdgA|EdgiOS|EdgeIOS|Edge)/\S+",
    "line_browser": r"\s+Line/\S+",
    "kakao": r"\s+KAKAOTALK/\S+",
    "qq": r"\s+(?:MQQBrowser|QQBrowser|QQ)/\S+",
    "yandex": r"\s+(?:YaBrowser|YandexSearchBrowser|YandexSearch)/\S+",
    "brave_mobile": r"\s+Brave/\S+",
    "duckduckgo": r"\s+DuckDuckGo/\S+",
    "puffin": r"\s+Puffin/\S+",
    "silk": r"\s+Silk(?:-Accelerated=[^ ]+)?(?:/\S+)?",
    "miui": r"\s+MiuiBrowser/\S+",
    "huawei": r"\s+HuaweiBrowser/\S+",
    "vivo": r"\s+VivoBrowser/\S+",
    "oppo": r"\s+(?:HeyTapBrowser|OppoBrowser)/\S+",
    "baidu": r"\s+baiduboxapp/\S+",
    "sogou": r"\s+SogouMobileBrowser/\S+",
    "coc_coc": r"\s+coc_coc_browser/\S+",
}

_ANDROID_HARDWARE = {
    "moto g 5g - 2024": ("306dpi", "720x1612", "motorola", "fogo", "qcom"),
    "moto g power (2024)": ("420dpi", "1080x2400", "motorola", "penang", "mt6789"),
    "sm-s918b": ("420dpi", "1080x2340", "samsung", "kalama", "qcom"),
    "sm-s928b": ("505dpi", "1440x3120", "samsung", "pineapple", "qcom"),
    "sm-a546b": ("420dpi", "1080x2340", "samsung", "a54x", "mt6833"),
    "sm-g991b": ("420dpi", "1080x2400", "samsung", "exynos2100", "qcom"),
    "pixel 8 pro": ("490dpi", "1344x2992", "google", "husky", "tensor"),
    "pixel 8": ("420dpi", "1080x2400", "google", "shiba", "tensor"),
    "pixel 7": ("420dpi", "1080x2400", "google", "panther", "tensor"),
    "cph2449": ("450dpi", "1240x2772", "OnePlus", "waffle", "qcom"),
    "cph2581": ("405dpi", "1080x2412", "OnePlus", "corvette", "qcom"),
    "23049pcd8g": ("440dpi", "1080x2400", "Xiaomi", "renoir", "qcom"),
}
_IOS_HARDWARE = {
    "iphone12,1": ("2.00", "828x1792"),
    "iphone12,3": ("3.00", "1125x2436"),
    "iphone13,2": ("3.00", "1170x2532"),
    "iphone14,5": ("3.00", "1170x2532"),
    "iphone15,2": ("3.00", "1179x2556"),
    "iphone15,3": ("3.00", "1290x2796"),
    "iphone16,1": ("3.00", "1179x2556"),
    "iphone17,2": ("3.00", "1320x2868"),
    "ipad13,1": ("2.00", "1640x2360"),
    "ipad14,3": ("2.00", "1668x2388"),
    "ipad14,5": ("2.00", "2048x2732"),
}


def _explicit_app_locale(ua: str, requested: str = "") -> str:
    match = re.search(
        r"\b(?:ByteFullLocale|ByteLocale)/([A-Za-z]{2}(?:[-_][A-Za-z]{2})?)\b",
        ua or "",
    )
    if not match:
        match = re.search(
            r"\bInstagram\s+[\d.]+.*?;\s*([a-z]{2}[_-][A-Z]{2})\s*;",
            ua or "",
            re.I,
        )
    value = match.group(1) if match else (requested or "").strip()
    return value.replace("_", "-")


def _android_parts(ua: str) -> Dict[str, str]:
    version = (re.search(r"\bAndroid\s+([\d.]+)", ua or "", re.I) or [None, "14"])[1]
    device = re.search(
        r"\bAndroid\s+[\d.]+\s*;\s*(?:[A-Za-z]{2}[_-][A-Za-z]{2}\s*;\s*)?"
        r"([^;)]+?)(?:\s*;\s*|\s+)Build/",
        ua or "", re.I,
    )
    if not device:
        device = re.search(
            r"\bAndroid\s+[\d.]+\s*;\s*([^;)]+?);\s*wv\)",
            ua or "",
            re.I,
        )
    build = re.search(r"\bBuild/([^;)\s]+)", ua or "", re.I)
    chrome = re.search(r"\bChrome/([\d.]+)", ua or "", re.I)
    model = device.group(1).strip() if device else "Pixel 8"
    build_id = build.group(1) if build else "UP1A.231105.003"
    chrome_version = chrome.group(1) if chrome else "149.0.7827.114"
    snapshot = next(
        (
            record for record in ANDROID_DEVICE_SNAPSHOTS
            if record["model"].lower() == model.lower()
        ),
        None,
    )
    if snapshot and (
        snapshot["and_ver"] != version.split(".", 1)[0]
        or snapshot["build"] != build_id
    ):
        version = snapshot["and_ver"]
        build_id = snapshot["build"]
    return {
        "version": version, "model": model, "build": build_id,
        "chrome": chrome_version,
    }


def _ios_parts(ua: str) -> Dict[str, str]:
    is_ipad = bool(re.search(r"\biPad\b", ua or "", re.I))
    version_match = re.search(
        r"\bCPU\s+(?:iPhone|iPad)?\s*OS\s+([\d_]+)", ua or "", re.I
    )
    model_match = re.search(r"\b(iPhone\d+,\d+|iPad\d+,\d+)\b", ua or "", re.I)
    family = "iPad" if is_ipad else "iPhone"
    default_model = "iPad14,3" if is_ipad else "iPhone15,2"
    return {
        "family": family,
        "version": version_match.group(1) if version_match else "18_6",
        "model": model_match.group(1) if model_match else default_model,
    }


def _android_webview_base(parts: Dict[str, str]) -> str:
    return (
        f"Mozilla/5.0 (Linux; Android {parts['version']}; {parts['model']} "
        f"Build/{parts['build']}; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Version/4.0 Chrome/{parts['chrome']} Mobile Safari/537.36"
    )


def _ios_webview_base(parts: Dict[str, str]) -> str:
    family = parts["family"]
    return (
        f"Mozilla/5.0 ({family}; CPU {family} OS {parts['version']} like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    )


def _generic_mobile_browser(ua: str) -> str:
    if _is_mobile_ua(ua) == "ios":
        parts = _ios_parts(ua)
        family = parts["family"]
        return (
            f"Mozilla/5.0 ({family}; CPU {family} OS {parts['version']} like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
            "Mobile/15E148 Safari/604.1"
        )
    major_match = re.search(r"\bChrome/(\d+)", ua or "", re.I)
    major = major_match.group(1) if major_match else "149"
    return (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Mobile Safari/537.36"
    )


def _generic_browser_fallback(ua: str) -> str:
    """Preserve a valid generic browser exactly; rebuild only bad/app-marked UAs."""
    original = ua or ""
    verdict = validate_user_agent(original, expected_app="browser")
    if (
        verdict["valid"]
        and not verdict["issues"]
        and not verdict["identities"]
        and verdict["profile_type"] == "browser"
    ):
        return original
    return _generic_mobile_browser(original)


def _identity_suffix(app: str, family: str, parts: Dict[str, str], locale: str) -> str:
    release = APP_RELEASES_BY_PLATFORM[app][family][0]
    version = release["version"]
    posix = (locale or "en-US").replace("-", "_")
    lang = (locale or "en-US").replace("_", "-")
    if app == "instagram":
        if family == "android":
            dpi, resolution, vendor, soc, chipset = _ANDROID_HARDWARE.get(
                parts["model"].lower(),
                ("420dpi", "1080x2400", "google", "shiba", "tensor"),
            )
            sdk = {"15": "35", "14": "34", "13": "33", "12": "31", "11": "30"}.get(
                parts["version"].split(".", 1)[0], "34"
            )
            return (
                f"Instagram {version} Android ({sdk}/{parts['version']}; {dpi}; "
                f"{resolution}; {vendor}; {parts['model']}; {soc}; {chipset}; "
                f"{posix}; {release['version_code']}; IABMV/1)"
            )
        scale, resolution = _IOS_HARDWARE.get(
            parts["model"].lower(),
            ("2.00", "1668x2388") if parts["family"] == "iPad"
            else ("3.00", "1179x2556"),
        )
        return (
            f"Instagram {version} ({parts['model']}; iOS {parts['version']}; "
            f"{posix}; {lang}; scale={scale}; {resolution})"
        )
    if app == "facebook":
        fbav = fbav_tracker_version(version)
        if family == "android":
            return (
                f"[FB_IAB/FB4A;FBAV/{fbav};IABMV/1;"
                f"FBBV/{release['build']};]"
            )
        device_family = parts["family"]
        return (
            f"[FBAN/FBIOS;FBAV/{fbav};FBDV/{parts['model']};"
            f"FBMD/{device_family};FBSN/iOS;FBSV/{parts['version'].replace('_', '.')};"
            f"FBSS/{2 if device_family == 'iPad' else 3};"
            f"FBID/{'tablet' if device_family == 'iPad' else 'phone'};"
            f"FBLC/{posix};IABMV/1]"
        )
    if app == "tiktok":
        channel = "googleplay" if family == "android" else "App Store"
        sdk = "1.0" if family == "android" else "2.0"
        marker = (
            f"TikTok/{version} musical_ly_{release.get('version_code', version)} "
            f"JsSdk/{sdk} NetType/WIFI Channel/{channel} AppName/musical_ly "
            f"app_version/{version}"
        )
        # Always emit coherent locale + Region together so ByteFullLocale
        # cannot exist without a matching Region token (validator + offer
        # parsers both expect this pairing on Android/iOS WebView UAs).
        region = posix.split("_")[-1].upper() if "_" in posix else "US"
        lang_token = lang.split("-", 1)[0].lower() or "en"
        if len(region) != 2:
            region = "US"
        marker += (
            f" ByteLocale/{lang_token} ByteFullLocale/{lang_token}_{region} "
            f"Region/{region}"
        )
        if family == "android":
            marker += f" com.zhiliaoapp.musically/{release['version_code']}"
        else:
            marker += " AppId/1233 WKWebView/1"
        return marker
    if app == "pinterest":
        os_label = "Android" if family == "android" else "iOS"
        return f"[Pinterest/{os_label}] Pinterest/{version}"
    if app == "snapchat":
        return f"Snapchat/{version}"
    if app == "whatsapp":
        return f"WhatsApp/{version} A"
    if app == "linkedin":
        marker = f"[LinkedInApp]/{version}"
        if family == "android":
            marker += f" com.linkedin.android/{release['package_build']}"
        return marker
    if app == "twitter":
        return (
            f"TwitterAndroid/{version}-release.0"
            if family == "android" else f"Twitter for iPhone/{version}"
        )
    if app == "reddit":
        return (
            f"Reddit/Version {version}/Build {release['build']}/Android "
            f"{parts['version']}"
        )
    if app == "telegram":
        return (
            f"Telegram-Android/{version} (Android {parts['version']}; "
            f"{parts['model']}; {lang})"
        )
    if app == "gsearch":
        return f"GoogleApp/{version}" if family == "android" else f"GSA/{version}"
    return ""


def _strip_foreign_inapp_markers(ua: str, keep_platform: str = "") -> str:
    """Strip every known/partial app identity by rebuilding only the browser base."""
    del keep_platform
    family = _is_mobile_ua(ua)
    if family == "android":
        return _android_webview_base(_android_parts(ua))
    if family == "ios":
        return _ios_webview_base(_ios_parts(ua))
    return ua or ""


def build_inapp_ua_suffix(platform: str, ua: str, locale: str = "") -> str:
    app = _PLATFORM_TO_APP.get((platform or "").lower().strip())
    family = _is_mobile_ua(ua)
    if not app or family not in {"android", "ios"}:
        return ""
    if APP_SUPPORT_MATRIX[app][family] != "supported":
        return ""
    parts = _android_parts(ua) if family == "android" else _ios_parts(ua)
    return _identity_suffix(app, family, parts, _explicit_app_locale(ua, locale))


def _verified_android_parts() -> Dict[str, str]:
    """Pick a capture-backed Android firmware tuple for safe rebuilds."""
    snapshot = random.choice(ANDROID_DEVICE_SNAPSHOTS)
    return {
        "version": snapshot["and_ver"],
        "model": snapshot["model"],
        "build": snapshot["build"],
        "chrome": "151.0.7922.71",
    }


def _verified_ios_parts() -> Dict[str, str]:
    return {
        "family": "iPhone",
        "version": "18_6",
        "model": "iPhone15,2",
    }


def _build_supported_identity_ua(
    app: str,
    family: str,
    parts: Dict[str, str],
    locale: str,
) -> str:
    base = _android_webview_base(parts) if family == "android" else _ios_webview_base(parts)
    suffix = _identity_suffix(app, family, parts, locale)
    return f"{base} {suffix}".strip()


def coerce_ua_for_platform(ua: str, platform: str, locale: str = "") -> str:
    """Apply exactly one contract-valid app identity, or a clean browser fallback.

    Supported in-app platforms NEVER fall through to a generic Chrome UA.
    If the original device shell cannot host a valid identity, we rebuild
    from a verified mobile firmware snapshot. Returning "" signals hard
    failure so callers can skip the visit instead of leaking Chrome.
    """
    original = ua or ""
    target = (platform or "").lower().strip()
    if target in _FALLBACK_ONLY_PLATFORMS:
        fallback = _generic_browser_fallback(original)
        logger.warning(
            "[ua-fallback-only] %s has no verified browser-UA contract; "
            "using a clean generic browser identity without fabricated app markers",
            target,
        )
        return fallback

    app = _PLATFORM_TO_APP.get(target)
    family = _is_mobile_ua(original)
    if not app or family not in {"android", "ios"}:
        return original

    if APP_SUPPORT_MATRIX[app][family] != "supported":
        fallback = _generic_browser_fallback(original)
        verdict = validate_user_agent(fallback, expected_app=app)
        if verdict["issues"]:
            logger.warning(
                "UA coercion fallback for %s %s could not satisfy contract: %s",
                app, family, "; ".join(verdict["issues"]),
            )
        return fallback

    expected = app
    locale_token = _explicit_app_locale(original, locale) or "en-US"
    current = validate_user_agent(original, expected_app=expected)
    if current["valid"] and not current["issues"]:
        return original

    attempts = []
    parts = _android_parts(original) if family == "android" else _ios_parts(original)
    attempts.append(parts)
    # Second chance: ignore unverified OEM shells and use a capture-backed
    # firmware identity that the contract accepts for all platforms.
    attempts.append(
        _verified_android_parts() if family == "android" else _verified_ios_parts()
    )

    last_issues = []
    for attempt_parts in attempts:
        candidate = _build_supported_identity_ua(
            app, family, attempt_parts, locale_token
        )
        verdict = validate_user_agent(candidate, expected_app=expected)
        if verdict["valid"] and not verdict["issues"]:
            return candidate
        last_issues = list(verdict["issues"] or [])

    logger.warning(
        "Invalid coerced %s %s UA after verified rebuild; refusing generic Chrome "
        "fallback: %s",
        app, family, "; ".join(last_issues) or "unknown validation failure",
    )
    return ""


def ensure_inapp_platform_ua(
    ua: str,
    platform: str,
    locale: str = "",
    mobile_ua_factory=None,
    attempts: int = 3,
) -> str:
    """Guarantee a platform-correct mobile UA for supported in-app targets.

    Retries with fresh mobile bases when coercion fails. Returns "" only when
    every attempt fails — callers should skip that visit.
    """
    target = (platform or "").lower().strip()
    app = _PLATFORM_TO_APP.get(target)
    if target in _FALLBACK_ONLY_PLATFORMS:
        return coerce_ua_for_platform(ua, target, locale)
    if not app:
        return ua or ""

    family = _is_mobile_ua(ua or "")
    support = (
        APP_SUPPORT_MATRIX.get(app, {}).get(family)
        if family in {"android", "ios"}
        else None
    )
    if support == "fallback":
        return coerce_ua_for_platform(ua or "", target, locale)

    if support != "supported" and family in {"android", "ios"}:
        # Unknown/unsupported combo — keep existing coerce behavior.
        return coerce_ua_for_platform(ua or "", target, locale)

    current = ua or ""
    for _ in range(max(1, int(attempts or 1))):
        if not _is_mobile_ua(current):
            if callable(mobile_ua_factory):
                current = mobile_ua_factory() or current
            else:
                # Prefer Android for retries (matches real in-app traffic mix).
                snap = _verified_android_parts()
                current = _android_webview_base(snap)
        coerced = coerce_ua_for_platform(current, target, locale)
        if not coerced:
            if callable(mobile_ua_factory):
                current = mobile_ua_factory() or current
            else:
                snap = _verified_android_parts()
                current = _android_webview_base(snap)
            continue
        if APP_SUPPORT_MATRIX.get(app, {}).get(_is_mobile_ua(coerced)) != "supported":
            return coerced
        if _ua_has_inapp_marker(coerced, target):
            return coerced
        current = coerced
    return ""


def _is_tiktok_android_ua_complete(ua: str) -> bool:
    """Compatibility helper backed by strict validation, not marker presence."""
    verdict = validate_user_agent(ua or "", expected_app="tiktok")
    return (
        verdict["platform"] == "Android"
        and verdict["engine"] == "android_webview"
        and verdict["valid"]
    )


def _ua_has_inapp_marker(ua: str, platform: str) -> bool:
    """Compatibility helper: true only for one fully valid target identity."""
    app = _PLATFORM_TO_APP.get((platform or "").lower().strip())
    if not app:
        return False
    verdict = validate_user_agent(ua or "", expected_app=app)
    return verdict["valid"] and verdict["app"] == app


def is_non_chrome_inapp_ua(ua: str) -> bool:
    """Compatibility helper for native/non-Chromium app identities."""
    profile = classify_user_agent(ua or "")
    if not profile["runtime_compatible"]:
        return True
    return (
        profile["app"] not in {"browser", "gchrome"}
        and not client_hint_headers_for_ua(ua or "")
    )


def make_sec_ch_ua_strip_route_handler():
    """Enforce the exact shared client-hint set on every Playwright request."""
    async def _handler(route, request):
        try:
            headers = dict(request.headers or {})
            ua = headers.get("user-agent") or headers.get("User-Agent") or ""
            headers = {
                key: value for key, value in headers.items()
                if not key.lower().startswith("sec-ch-ua")
            }
            casing = {
                "sec-ch-ua": "Sec-CH-UA",
                "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
                "sec-ch-ua-platform": "Sec-CH-UA-Platform",
            }
            headers.update({
                casing[key]: value
                for key, value in client_hint_headers_for_ua(ua).items()
            })
            await route.continue_(headers=headers)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass
    return _handler


# ══════════════════════════════════════════════════════════════════════
# Convenience helpers for callers
# ══════════════════════════════════════════════════════════════════════
def platform_needs_ua_match(platform: str) -> bool:
    """True iff the platform is one whose realistic UA differs on mobile
    from a plain browser UA (so coercion is meaningful)."""
    return (platform or "").lower() in _INAPP_CAPABLE_PLATFORMS


# ──────────────────────────────────────────────────────────────────────
# v2.1.83 — International Fraud-Detector Guardrails (10-feature pack)
# ──────────────────────────────────────────────────────────────────────
# These helpers extend the pro-referrer engine with the checks fraud
# detectors on international affiliate networks (MaxBounty, ClickDealer,
# Everflow, Cake, HasOffers, AdCombo, Voluum, etc.) run at click time.
# Every helper is a pure function — safe to call from server.py, RUT,
# preview endpoint, or QA-check endpoint. All are OFF-by-default at the
# link level, so pre-existing links keep behaving IDENTICALLY.
# ──────────────────────────────────────────────────────────────────────

# Feature 1 — Country-matched Accept-Language.
# Maps ISO-3166 alpha-2 country code (lowercase) to a realistic
# Accept-Language header value that a browser physically located in
# that country would send. Used both by the click handler (macro
# expansion) and by RUT so all channels stay consistent.
_COUNTRY_LANG_MAP: Dict[str, str] = {
    "us": "en-US,en;q=0.9",
    "gb": "en-GB,en;q=0.9",
    "uk": "en-GB,en;q=0.9",
    "ca": "en-CA,en;q=0.9,fr-CA;q=0.7",
    "au": "en-AU,en;q=0.9",
    "nz": "en-NZ,en;q=0.9",
    "ie": "en-IE,en;q=0.9",
    "in": "en-IN,en;q=0.9,hi-IN;q=0.7,hi;q=0.5",
    "pk": "en-PK,en;q=0.9,ur-PK;q=0.7,ur;q=0.5",
    "bd": "bn-BD,bn;q=0.9,en;q=0.7",
    "lk": "en-LK,en;q=0.9,si-LK;q=0.7,ta-LK;q=0.5",
    "np": "ne-NP,ne;q=0.9,en;q=0.7",
    "sg": "en-SG,en;q=0.9,zh-SG;q=0.7",
    "my": "ms-MY,ms;q=0.9,en;q=0.7",
    "ph": "en-PH,en;q=0.9,tl-PH;q=0.7",
    "id": "id-ID,id;q=0.9,en;q=0.7",
    "th": "th-TH,th;q=0.9,en;q=0.7",
    "vn": "vi-VN,vi;q=0.9,en;q=0.7",
    "jp": "ja-JP,ja;q=0.9,en;q=0.6",
    "kr": "ko-KR,ko;q=0.9,en;q=0.6",
    "cn": "zh-CN,zh;q=0.9,en;q=0.6",
    "hk": "zh-HK,zh;q=0.9,en;q=0.7",
    "tw": "zh-TW,zh;q=0.9,en;q=0.6",
    "de": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.6",
    "at": "de-AT,de;q=0.9,en;q=0.7",
    "ch": "de-CH,de;q=0.9,fr-CH;q=0.7,en;q=0.5",
    "fr": "fr-FR,fr;q=0.9,en-US;q=0.7,en;q=0.6",
    "be": "nl-BE,nl;q=0.9,fr-BE;q=0.7,en;q=0.5",
    "nl": "nl-NL,nl;q=0.9,en;q=0.7",
    "es": "es-ES,es;q=0.9,en;q=0.7",
    "pt": "pt-PT,pt;q=0.9,en;q=0.7",
    "br": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.6",
    "mx": "es-MX,es;q=0.9,en-US;q=0.7,en;q=0.6",
    "ar": "es-AR,es;q=0.9,en;q=0.6",
    "cl": "es-CL,es;q=0.9,en;q=0.6",
    "co": "es-CO,es;q=0.9,en;q=0.6",
    "pe": "es-PE,es;q=0.9,en;q=0.6",
    "it": "it-IT,it;q=0.9,en;q=0.7",
    "gr": "el-GR,el;q=0.9,en;q=0.7",
    "pl": "pl-PL,pl;q=0.9,en;q=0.7",
    "cz": "cs-CZ,cs;q=0.9,en;q=0.7",
    "sk": "sk-SK,sk;q=0.9,en;q=0.7",
    "hu": "hu-HU,hu;q=0.9,en;q=0.7",
    "ro": "ro-RO,ro;q=0.9,en;q=0.7",
    "bg": "bg-BG,bg;q=0.9,en;q=0.7",
    "hr": "hr-HR,hr;q=0.9,en;q=0.7",
    "rs": "sr-RS,sr;q=0.9,en;q=0.7",
    "si": "sl-SI,sl;q=0.9,en;q=0.7",
    "ru": "ru-RU,ru;q=0.9,en;q=0.6",
    "ua": "uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5",
    "by": "be-BY,be;q=0.9,ru;q=0.7,en;q=0.5",
    "kz": "kk-KZ,kk;q=0.9,ru;q=0.7,en;q=0.5",
    "tr": "tr-TR,tr;q=0.9,en;q=0.7",
    "sa": "ar-SA,ar;q=0.9,en;q=0.7",
    "ae": "ar-AE,ar;q=0.9,en;q=0.8",
    "eg": "ar-EG,ar;q=0.9,en;q=0.7",
    "il": "he-IL,he;q=0.9,en;q=0.7",
    "ir": "fa-IR,fa;q=0.9,en;q=0.5",
    "za": "en-ZA,en;q=0.9",
    "ng": "en-NG,en;q=0.9",
    "ke": "en-KE,en;q=0.9,sw-KE;q=0.7",
    "gh": "en-GH,en;q=0.9",
    "no": "no,nb;q=0.9,en;q=0.7",
    "se": "sv-SE,sv;q=0.9,en;q=0.7",
    "fi": "fi-FI,fi;q=0.9,en;q=0.7",
    "dk": "da-DK,da;q=0.9,en;q=0.7",
    "is": "is-IS,is;q=0.9,en;q=0.7",
}


def accept_language_for_country(cc: Optional[str], fallback: str = "en-US,en;q=0.9") -> str:
    """Return a realistic Accept-Language header for the given country
    code. Falls back to English if the country is unknown. Case- and
    whitespace-insensitive.
    """
    key = (cc or "").strip().lower()
    if not key:
        return fallback
    return _COUNTRY_LANG_MAP.get(key, fallback)


# Feature 3 — Platform → device-type expectation.
# Real-world traffic distribution for each platform. Used by the visit
# resolver to reject platform picks that don't match the visitor's UA
# (e.g. TikTok click with desktop UA = red flag → re-pick from mobile-
# friendly platforms).
#   "mobile_only"     : 90%+ mobile in the wild
#   "desktop_leaning" : 60%+ desktop
#   "any"             : balanced (Google, YouTube, email — either device
#                        looks natural)
_PLATFORM_DEVICE_EXPECTATION: Dict[str, str] = {
    "tiktok":      "mobile_only",
    "instagram":   "mobile_only",
    "snapchat":    "mobile_only",
    "whatsapp":    "mobile_only",
    "telegram":    "any",
    "messenger":   "mobile_only",
    "facebook":    "any",
    "twitter":     "any",
    "x":           "any",
    "reddit":      "any",
    "pinterest":   "any",
    "linkedin":    "desktop_leaning",
    "youtube":     "any",
    "google":      "any",
    "bing":        "desktop_leaning",
    "duckduckgo":  "any",
    "yahoo":       "any",
    "yandex":      "any",
    "email":       "any",
}


def platform_device_expectation(platform: str) -> str:
    """Return "mobile_only" | "desktop_leaning" | "any" for the platform."""
    return _PLATFORM_DEVICE_EXPECTATION.get((platform or "").lower(), "any")


def platform_matches_device(platform: str, is_mobile: bool) -> bool:
    """True iff a click from an <is_mobile> device is plausible for this
    platform. Used to filter the platform pool so TikTok/Instagram
    picks never land on a desktop visitor and vice-versa."""
    exp = platform_device_expectation(platform)
    if exp == "any":
        return True
    if exp == "mobile_only":
        return bool(is_mobile)
    if exp == "desktop_leaning":
        # Desktop-leaning platforms still get SOME mobile traffic in
        # the real world — LinkedIn mobile app is huge. So we allow
        # both but weight desktop heavier upstream.
        return True
    return True


# Feature 5 — Campaign-type UTM presets.
# Maps a customer-picked campaign_type to (utm_medium, utm_content prefix,
# optional utm_term). Extends what pick_utm_variation / pick_utm_campaign
# already do, WITHOUT breaking either — when campaign_type=="auto" (the
# default), the legacy random pick is used.
_CAMPAIGN_TYPE_PRESETS: Dict[str, Dict[str, str]] = {
    "static_image":       {"medium": "paid_social", "content": "static_image", "term": "img_ad"},
    "video_ad":           {"medium": "paid_social", "content": "video_a",      "term": "video_ad"},
    "carousel_ad":        {"medium": "paid_social", "content": "carousel_v2",  "term": "carousel"},
    "story_ad":           {"medium": "paid_social", "content": "story_9x16",   "term": "story"},
    "lookalike_prospect": {"medium": "paid_social", "content": "lookalike_1p", "term": "lookalike_m35"},
    "retargeting_warm":   {"medium": "retargeting", "content": "warm_audience","term": "rt_warm"},
    "retargeting_cold":   {"medium": "retargeting", "content": "cold_audience","term": "rt_cold"},
    "cold_email":         {"medium": "email",       "content": "outreach_v3",  "term": "cold_email"},
    "search_cpc":         {"medium": "cpc",         "content": "search_ad",    "term": "keyword"},
}

VALID_CAMPAIGN_TYPES: Tuple[str, ...] = ("auto",) + tuple(_CAMPAIGN_TYPE_PRESETS.keys())


def campaign_type_preset(campaign_type: str) -> Optional[Dict[str, str]]:
    """Return the utm preset dict for a campaign_type, or None if the
    caller passed "auto" / an unknown value (legacy random path)."""
    key = (campaign_type or "").strip().lower()
    if not key or key == "auto":
        return None
    return _CAMPAIGN_TYPE_PRESETS.get(key)


# Feature 6 — Quality-tier preset. UI/UX shortcut: customer picks one
# word ("Premium" / "Standard" / "Aggressive"), server-side normaliser
# applies sensible defaults for the other 8 toggles. Legacy links keep
# tier="standard" so nothing changes for them.
_QUALITY_TIER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "premium": {
        # Every fraud check ON — matched language, wrapper redirect,
        # time-of-day realism, strict device match, in-app deep paths.
        "referrer_pro_lang_match":            True,
        "referrer_pro_social_wrapper":        True,
        "referrer_pro_inapp_deep_path":       True,
        "referrer_pro_strip_search_path":     True,
        "referrer_pro_wrapper_redirect":      True,
        "referrer_pro_tod_enabled":           True,
        "referrer_pro_device_mode":           "match_platform",
    },
    "standard": {
        # Balanced defaults — same as pre-v2.1.83 behaviour so existing
        # links stay identical.
        "referrer_pro_lang_match":            True,
        "referrer_pro_social_wrapper":        True,
        "referrer_pro_inapp_deep_path":       True,
        "referrer_pro_strip_search_path":     True,
        "referrer_pro_wrapper_redirect":      False,
        "referrer_pro_tod_enabled":           False,
        "referrer_pro_device_mode":           "auto",
    },
    "aggressive": {
        # Max throughput — for lenient networks (gambling / adult / crypto).
        # Skip the expensive wrapper hop and disable strict filtering.
        "referrer_pro_lang_match":            False,
        "referrer_pro_social_wrapper":        False,
        "referrer_pro_inapp_deep_path":       False,
        "referrer_pro_strip_search_path":     True,
        "referrer_pro_wrapper_redirect":      False,
        "referrer_pro_tod_enabled":           False,
        "referrer_pro_device_mode":           "auto",
    },
}

VALID_QUALITY_TIERS: Tuple[str, ...] = tuple(_QUALITY_TIER_DEFAULTS.keys())


def quality_tier_defaults(tier: str) -> Dict[str, Any]:
    """Return the settings dict for a quality tier. Falls back to
    "standard" for unknown values — callers can safely spread this into
    their link doc when the customer picks a tier from the UI."""
    key = (tier or "standard").strip().lower()
    return dict(_QUALITY_TIER_DEFAULTS.get(key, _QUALITY_TIER_DEFAULTS["standard"]))


# Feature 7 — Weighted multi-URL A/B rotation (per-visit).
# `offer_urls_value` accepts either:
#   - JSON: [{"url":"https://a", "weight":50}, {"url":"https://b", "weight":30}]
#   - Compact: "https://a:50,https://b:30,https://c:20"
# Falls back cleanly to [] on any parse error. Weights normalise to 1.
def parse_offer_url_pool(offer_urls_value: str) -> List[Tuple[str, float]]:
    """Parse the multi-URL rotation string into [(url, weight), ...].
    Empty/invalid input → []. Duplicate URLs collapse to summed weight.
    """
    raw = (offer_urls_value or "").strip()
    if not raw:
        return []
    pool: List[Tuple[str, float]] = []
    # Try JSON first
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            for item in arr:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                try:
                    w = float(item.get("weight", 1))
                except Exception:
                    w = 1.0
                if w > 0:
                    pool.append((url, w))
        except Exception:
            pass
    else:
        # Compact format: "url:weight,url:weight" — split on the LAST
        # ":<number>" so URLs containing colons (https://) stay intact.
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Rightmost ":" preceded by a numeric weight is the split
            m = re.search(r":(\d+(?:\.\d+)?)\s*$", chunk)
            if m:
                url = chunk[: m.start()].strip()
                try:
                    w = float(m.group(1))
                except Exception:
                    w = 1.0
            else:
                url = chunk
                w = 1.0
            if url:
                pool.append((url, w))
    # Collapse duplicate URLs
    if not pool:
        return []
    coalesced: Dict[str, float] = {}
    for url, w in pool:
        coalesced[url] = coalesced.get(url, 0.0) + w
    return [(u, w) for u, w in coalesced.items()]


def pick_offer_url(offer_urls_value: str, fallback: str) -> str:
    """Pick one URL from the weighted pool. Returns `fallback` if the
    pool is empty. Uses the same weighted-pick primitive as the platform
    pool so behaviour is consistent across features."""
    pool = parse_offer_url_pool(offer_urls_value)
    if not pool:
        return fallback
    total = sum(w for _, w in pool)
    if total <= 0:
        return fallback
    r = random.uniform(0, total)
    cum = 0.0
    for url, w in pool:
        cum += w
        if r <= cum:
            return url
    return pool[-1][0]


# Feature 2 — Macro expansion for offer-URL params (server-side).
# Extends the existing single-URL macro substitution (server.py already
# handles {clickid}/{ua}/{ip}) to a richer set that customers commonly
# pass through to networks. Idempotent for strings that contain no
# macros — safe to call on every click.
def _random_hex_token(n: int = 16) -> str:
    return "".join(random.choices("abcdef0123456789", k=max(1, n)))


def expand_link_macros(text: str, ctx: Dict[str, Any]) -> str:
    """Replace `{macro}` tokens inside `text` with URL-encoded values
    from `ctx`. Unknown macros pass through untouched so raw offer-URL
    literals like `{customer_supplied_id}` never break.

    Supported ctx keys (all optional — missing → empty string):
      click_id, clickid, source, source_name, campaign, brand, platform,
      country, city, region, ip, ua, referer, referrer, utm_source,
      utm_medium, utm_campaign, utm_content, utm_term, accept_language,
      timestamp, timestamp_ms, random, random16, random32
    """
    if not text or "{" not in text:
        return text
    # Auto-generated macros
    now = datetime.now(timezone.utc)
    macros: Dict[str, str] = {
        "click_id":        str(ctx.get("click_id") or ctx.get("clickid") or ""),
        "clickid":         str(ctx.get("clickid") or ctx.get("click_id") or ""),
        "source":          str(ctx.get("source") or ""),
        "source_name":     str(ctx.get("source_name") or ""),
        "campaign":        str(ctx.get("campaign") or ctx.get("utm_campaign") or ""),
        "brand":           str(ctx.get("brand") or ""),
        "platform":        str(ctx.get("platform") or ""),
        "country":         str(ctx.get("country") or ""),
        "city":            str(ctx.get("city") or ""),
        "region":          str(ctx.get("region") or ""),
        "ip":              str(ctx.get("ip") or ""),
        "ua":              str(ctx.get("ua") or ""),
        "user_agent":      str(ctx.get("ua") or ctx.get("user_agent") or ""),
        "referer":         str(ctx.get("referer") or ctx.get("referrer") or ""),
        "referrer":        str(ctx.get("referrer") or ctx.get("referer") or ""),
        "utm_source":      str(ctx.get("utm_source") or ""),
        "utm_medium":      str(ctx.get("utm_medium") or ""),
        "utm_campaign":    str(ctx.get("utm_campaign") or ""),
        "utm_content":     str(ctx.get("utm_content") or ""),
        "utm_term":        str(ctx.get("utm_term") or ""),
        "accept_language": str(ctx.get("accept_language") or ""),
        "timestamp":       str(int(now.timestamp())),
        "timestamp_ms":    str(int(now.timestamp() * 1000)),
        "random":          _random_hex_token(8),
        "random16":        _random_hex_token(16),
        "random32":        _random_hex_token(32),
        "payout":          str(ctx.get("payout") or ctx.get("amount") or ctx.get("revenue") or ""),
        "amount":          str(ctx.get("amount") or ctx.get("payout") or ctx.get("revenue") or ""),
        "revenue":         str(ctx.get("revenue") or ctx.get("payout") or ctx.get("amount") or ""),
        "sale":            str(ctx.get("sale") or ctx.get("payout") or ctx.get("amount") or ""),
        "sum":             str(ctx.get("sum") or ctx.get("payout") or ctx.get("amount") or ""),
        "price":           str(ctx.get("price") or ctx.get("payout") or ctx.get("amount") or ""),
        "commission":      str(ctx.get("commission") or ctx.get("payout") or ""),
        "adv1":            str(ctx.get("adv1") or ctx.get("payout") or ""),
        "status":          str(ctx.get("status") or ""),
        "sub1":            str(ctx.get("sub1") or ""),
        "sub2":            str(ctx.get("sub2") or ""),
        "sub3":            str(ctx.get("sub3") or ""),
        "s1":              str(ctx.get("s1") or ctx.get("sub1") or ""),
        "s2":              str(ctx.get("s2") or ctx.get("sub2") or ""),
        "s3":              str(ctx.get("s3") or ctx.get("sub3") or ""),
        "transaction_id":  str(ctx.get("transaction_id") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "cid":             str(ctx.get("cid") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "requestid":       str(ctx.get("requestid") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "cnv_id":          str(ctx.get("cnv_id") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "external_id":     str(ctx.get("external_id") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "aff_click_id":    str(ctx.get("aff_click_id") or ctx.get("click_id") or ctx.get("clickid") or ""),
        "subid":           str(ctx.get("subid") or ctx.get("sub1") or ctx.get("click_id") or ""),
        "offer_url":       str(ctx.get("offer_url") or ctx.get("destination_url") or ""),
        "destination_url": str(ctx.get("destination_url") or ctx.get("offer_url") or ""),
    }
    # Do a per-key encoded replace so callers get URL-safe substitution
    # regardless of where in the URL the macro sits (path / query / frag).
    from urllib.parse import quote as _q
    out = text
    for k, v in macros.items():
        token = "{" + k + "}"
        if token in out:
            out = out.replace(token, _q(v, safe=""))
    return out


# ══════════════════════════════════════════════════════════════════════
# v2.6.24 (2026-07) — PAID vs ORGANIC REFERER SPLIT (all 10 platforms)
# ══════════════════════════════════════════════════════════════════════
# Real-world capture data (2025-2026) shows the referer signature for
# a click coming from a PAID ad is materially different from the same
# platform's ORGANIC click:
#
#   • TikTok paid  → empty / ads.tiktok.com / link.tiktok.com
#   • TikTok organic → empty / l.tiktok.com / video URL
#   • Facebook paid → l.facebook.com/l.php with __cft__[0] + __tn__
#   • Facebook organic → l.facebook.com/l.php WITHOUT __cft__/__tn__
#                          or /<page>/posts/pfbid<hash>
#   • Google paid   → googleads.g.doubleclick.net/pagead/aclk
#   • Google organic → origin-only google.<tld>/ (strict-origin policy)
#   • Snapchat paid  → 82% empty (Snap Ads strip referer aggressively)
#   • Snapchat organic → 92% empty
#   • …and 6 more platforms below.
#
# Prior to v2.6.24 the engine used ONE combined pool per platform, which
# caused two documented customer-side problems:
#   BUG X (2026-06 screenshot leak): TikTok paid ads sent `Referer:
#          https://www.tiktok.com/@user/video/<id>` — a URL that real
#          TikTok in-app webviews NEVER emit (webview strips referer
#          or falls back to analytics.tiktok.com). Anti-fraud systems
#          (Anura / IPQS / Voluum / RedTrack) clustered these as
#          "synthetic-referer" → clicks silently filtered.
#   BUG Y (organic tagging): organic Facebook clicks arrived with
#          __cft__[0] / __tn__ params (Meta's ad-network tokens),
#          which advertiser dashboards treat as PAID traffic → mixed
#          reporting confusion + auto-reject on "organic-only" offers.
#
# This module ships pre-calibrated pools (weights sourced from live
# 2025-2026 capture samples) and dispatches per-platform, per-mode.
# ══════════════════════════════════════════════════════════════════════

def _pick_weighted_str(pool: List[Tuple[str, float]]) -> str:
    """Weighted pick over a list of (value, weight) tuples. Safe on
    empty pool (returns ""), safe on zero total weight (returns first).
    Values may be ANY string (including "" for empty-referer weights)."""
    if not pool:
        return ""
    total = sum(max(0.0, float(w)) for _, w in pool)
    if total <= 0:
        return pool[0][0]
    r = random.uniform(0, total)
    cum = 0.0
    for val, w in pool:
        cum += max(0.0, float(w))
        if r <= cum:
            return val
    return pool[-1][0]


def _rand_digits(n: int) -> str:
    return "".join(random.choices("0123456789", k=max(1, n)))


def _rand_alnum(n: int, chars: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") -> str:
    return "".join(random.choices(chars, k=max(1, n)))


def _rand_hex_lower(n: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=max(1, n)))


# ── Google country-code TLDs for organic Google referer origin ──
_GOOGLE_ORGANIC_TLDS: Tuple[str, ...] = (
    "com", "com", "com", "co.uk", "de", "fr", "es", "it", "co.jp",
    "ca", "com.au", "com.br", "com.mx", "co.in", "nl", "pl", "com.tr",
)


def _build_fb_linkshim(target_url: str, include_paid_markers: bool) -> str:
    """Facebook l.facebook.com/l.php linkshim builder.
    include_paid_markers=True  → adds __cft__[0]=AZ<token> (75%) + __tn__ (50%)
    include_paid_markers=False → h= param only (real organic outbound clicks)
    """
    if target_url:
        enc_u = quote_plus(target_url)
    else:
        _fallbacks = [
            "https://www.amazon.com/dp/B0" + _rand_alnum(8, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
            "https://www.etsy.com/listing/" + _rand_digits(10),
            "https://shop." + _rand_alnum(random.randint(5, 9), "abcdefghijklmnopqrstuvwxyz") + ".com/p/" + _rand_digits(6),
        ]
        enc_u = quote_plus(random.choice(_fallbacks))
    hash_body = _rand_alnum(random.randint(58, 104),
                             "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    base = f"https://l.facebook.com/l.php?u={enc_u}&h=AT{hash_body}"
    if include_paid_markers:
        # Paid Meta ads → linkshims almost always carry __cft__[0]=AZ<token>
        if random.random() < 0.75:
            base += f"&__cft__[0]={_rand_fb_cft_token()}"
        extra_roll = random.random()
        if extra_roll < 0.50:
            tn = random.choice(["-R", "%2A%5BR%5D", "%2A%5BR-R%5D", "%2AH-R", "%2AF", "H-R"])
            base += f"&__tn__={tn}"
        elif extra_roll < 0.60:
            base += "&_lp=1"
    return base


def _build_lm_fb_linkshim_paid(target_url: str) -> str:
    """Mobile linkshim (lm.facebook.com) — paid variant with __cft__[0]."""
    if target_url:
        enc_u = quote_plus(target_url)
    else:
        enc_u = quote_plus("https://www.amazon.com/dp/B0" +
                            _rand_alnum(8, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
    hash_body = _rand_alnum(random.randint(58, 104),
                             "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    base = f"https://lm.facebook.com/l.php?u={enc_u}&h=AT{hash_body}"
    if random.random() < 0.70:
        base += f"&__cft__[0]={_rand_fb_cft_token()}"
    return base


def _build_ig_linkshim(target_url: str, include_paid_marker: bool) -> str:
    """Instagram l.instagram.com wrapper.
    include_paid_marker=True → adds `&s=1` (Instagram's paid-outbound flag)
    """
    enc_u = quote_plus(target_url or ("https://www.etsy.com/listing/" + _rand_digits(10)))
    e_hash = _rand_ig_e_hash()
    base = f"https://l.instagram.com/?u={enc_u}&e={e_hash}"
    if include_paid_marker:
        base += "&s=1"
    return base


def _build_youtube_redirect(target_url: str, event: str) -> str:
    """YouTube redirect URL. event='video_ad' (paid) or 'video_description' (organic)."""
    enc_q = quote_plus(target_url or ("https://www.example.com/" + _rand_alnum(6, "abcdefghijklmnopqrstuvwxyz")))
    return f"https://www.youtube.com/redirect?event={event}&q={enc_q}"


def _build_linkedin_redir(target_url: str, include_paid_trk: bool) -> str:
    """LinkedIn linkedin.com/redir/redirect wrapper.
    include_paid_trk=True → appends &trk=<sponsored campaign id>
    """
    enc = quote_plus(target_url or ("https://www.example.com/" + _rand_alnum(6, "abcdefghijklmnopqrstuvwxyz")))
    urlhash = _rand_lnkd_id()
    base = f"https://www.linkedin.com/redir/redirect?url={enc}&urlhash={urlhash}"
    if include_paid_trk:
        # trk carries the sponsored campaign token — real captures use
        # kebab-case identifiers like: trk=sponsored-content_impression
        trk_pool = [
            "sponsored-content_impression",
            "sponsored-update_action-menu",
            "sponsored_message-click",
            "li_ad_" + _rand_hex_lower(10),
        ]
        base += f"&trk={random.choice(trk_pool)}"
    return base


def _build_pin_offsite(target_url: str, include_paid_sig: bool) -> str:
    """Pinterest www.pinterest.com/offsite/ wrapper.
    include_paid_sig=True → appends &sig=<hash> (promoted pin outbound signature).
    """
    enc = quote_plus(target_url or ("https://www.example.com/" + _rand_alnum(6, "abcdefghijklmnopqrstuvwxyz")))
    token = _rand_hex_lower(16)
    pin_id = _rand_digits(19)
    base = f"https://www.pinterest.com/offsite/?token={token}&url={enc}&pin={pin_id}"
    if include_paid_sig:
        base += f"&sig={_rand_hex_lower(24)}"
    return base


def _build_out_reddit(target_url: str, include_paid_token: bool) -> str:
    """Reddit out.reddit.com/t/ wrapper.
    include_paid_token=True → appends &token=<...>&app_name=reddit.com (ad hop signature).
    """
    enc = quote_plus(target_url or ("https://www.example.com/" + _rand_alnum(6, "abcdefghijklmnopqrstuvwxyz")))
    slug = _rand_alnum(10, "abcdefghijklmnopqrstuvwxyz0123456789")
    base = f"https://out.reddit.com/t/{slug}?url={enc}"
    if include_paid_token:
        base += f"&token={_rand_alnum(32, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')}"
        base += "&app_name=reddit.com"
    return base


def _build_reddit_thread() -> str:
    """Realistic reddit thread URL."""
    subs = [
        "deals", "coupons", "shopping", "reviews", "askreddit",
        "personalfinance", "cryptocurrency", "gaming", "technology",
        "fitness", "buildapc", "smallbusiness", "entrepreneur",
    ]
    sub = random.choice(subs)
    thread_id = _rand_alnum(7, "abcdefghijklmnopqrstuvwxyz0123456789")
    slug_words = random.sample([
        "how", "to", "best", "review", "compared", "top", "guide",
        "vs", "tips", "worth", "it", "beginners", "advanced", "2026",
    ], k=random.randint(3, 5))
    slug = "_".join(slug_words)
    return f"https://www.reddit.com/r/{sub}/comments/{thread_id}/{slug}/"


def _build_google_doubleclick_paid(target_url: str) -> str:
    """Google Ads outbound aclk redirector on doubleclick.net."""
    ai = _rand_alnum(64, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    sig = _rand_alnum(24, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    return f"https://googleads.g.doubleclick.net/pagead/aclk?sa=L&ai={ai}&ai_a=1&num=1&sig={sig}"


def _build_google_aclk_direct() -> str:
    """Direct google.<tld>/aclk (rarer Ads outbound variant)."""
    tld = random.choice(_GOOGLE_ORGANIC_TLDS)
    ai = _rand_alnum(56, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return f"https://www.google.{tld}/aclk?sa=l&ai={ai}"


def _build_google_origin() -> str:
    """Origin-only Google (organic click under strict-origin-when-cross-origin)."""
    tld = random.choice(_GOOGLE_ORGANIC_TLDS)
    return f"https://www.google.{tld}/"


def _build_google_serp_full() -> str:
    """Full Google SERP URL (rare case where policy leaks full URL)."""
    tld = random.choice(_GOOGLE_ORGANIC_TLDS)
    keyword_words = random.sample([
        "best", "deals", "review", "guide", "top", "buy", "compare",
        "cheap", "affordable", "official", "site", "2026",
    ], k=random.randint(2, 4))
    q = quote_plus(" ".join(keyword_words))
    return f"https://www.google.{tld}/search?q={q}"


def _build_bing_aclick(target_url: str) -> str:
    """Bing Ads outbound aclick redirector."""
    enc = quote_plus(target_url or ("https://www.example.com/" + _rand_alnum(6, "abcdefghijklmnopqrstuvwxyz")))
    ld = _rand_alnum(64, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    partner = random.choice(["msft", "microsoft", "bing", "msft-search"])
    return f"https://www.bing.com/aclick?ld={ld}&u={enc}&p={partner}"


def _build_bing_serp_full() -> str:
    """Full Bing SERP URL."""
    q = quote_plus(random.choice(["best deals", "cheap flights", "product review", "compare prices"]))
    return f"https://www.bing.com/search?q={q}"


def _build_tiktok_video_url() -> str:
    """Realistic TikTok video URL (organic bio/caption tap fallback)."""
    vid_id = str(random.randint(7000000000000000000, 7999999999999999999))
    user_id = "user" + _rand_digits(random.randint(6, 10))
    return f"https://www.tiktok.com/@{user_id}/video/{vid_id}"


def _build_fb_pfbid_post() -> str:
    """Facebook modern deep-link with pfbid token."""
    page_slug = random.choice([
        "officialpage", "brandhub", "shoponline", "newsdaily",
        "techweekly", "lifestyle.daily", "deals.today",
    ])
    pfbid = "pfbid0" + _rand_alnum(49,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    return f"https://www.facebook.com/{page_slug}/posts/{pfbid}"


def _build_fb_group_url() -> str:
    """Facebook group URL (organic feed source)."""
    return f"https://www.facebook.com/groups/{_rand_digits(15)}/"


def _build_ig_post_url() -> str:
    """Instagram post URL (organic feed tap)."""
    shortcode = _rand_alnum(11,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return f"https://www.instagram.com/p/{shortcode}/"


def _build_x_status_url() -> str:
    """X/Twitter status URL."""
    username = random.choice(["dealshub", "offerfeed", "savingsdaily", "shopalert",
                               "techdaily", "brandnews", "reviewhub"])
    return f"https://x.com/i/web/status/{_rand_digits(19)}"


def _build_x_tco() -> str:
    """t.co redirector URL — used for both paid and organic X clicks."""
    return f"https://t.co/{_rand_alnum(10, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789')}"


def _build_x_redirect(target_url: str) -> str:
    """twitter.com/i/redirect wrapper (rare paid variant)."""
    enc = quote_plus(target_url or "https://www.example.com/")
    return f"https://twitter.com/i/redirect?url={enc}"


def _build_yt_watch_url() -> str:
    """YouTube watch URL (organic video referrer edge case)."""
    vid_id = _rand_alnum(11,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return f"https://www.youtube.com/watch?v={vid_id}"


def _build_linkedin_activity() -> str:
    """LinkedIn feed post URN (organic in-feed tap)."""
    urn = _rand_digits(19)
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{urn}/"


def _build_pin_url() -> str:
    """Direct Pinterest pin URL (organic feed tap)."""
    return f"https://www.pinterest.com/pin/{_rand_digits(19)}/"


# ── Pre-calibrated referer pools per platform, per mode ──────────────
# Values ending in "()" are BUILDER TOKENS resolved at pick-time so we
# never freeze a specific URL in the pool.
_TOK_FB_LINKSHIM_PAID    = "__FB_LINKSHIM_PAID__"
_TOK_FB_LINKSHIM_ORGANIC = "__FB_LINKSHIM_ORGANIC__"
_TOK_FB_LM_LINKSHIM      = "__FB_LM_LINKSHIM__"
_TOK_FB_PFBID            = "__FB_PFBID__"
_TOK_FB_GROUP            = "__FB_GROUP__"
_TOK_IG_LINK_PAID        = "__IG_LINK_PAID__"
_TOK_IG_LINK_ORGANIC     = "__IG_LINK_ORGANIC__"
_TOK_IG_POST             = "__IG_POST__"
_TOK_TT_VIDEO            = "__TT_VIDEO__"
_TOK_X_TCO               = "__X_TCO__"
_TOK_X_STATUS            = "__X_STATUS__"
_TOK_X_REDIRECT          = "__X_REDIRECT__"
_TOK_YT_DOUBLECLICK      = "__YT_DOUBLECLICK__"
_TOK_YT_REDIRECT_AD      = "__YT_REDIRECT_AD__"
_TOK_YT_REDIRECT_DESC    = "__YT_REDIRECT_DESC__"
_TOK_YT_WATCH            = "__YT_WATCH__"
_TOK_LI_REDIR_PAID       = "__LI_REDIR_PAID__"
_TOK_LI_REDIR_ORGANIC    = "__LI_REDIR_ORGANIC__"
_TOK_LI_ACTIVITY         = "__LI_ACTIVITY__"
_TOK_PIN_OFFSITE_PAID    = "__PIN_OFFSITE_PAID__"
_TOK_PIN_OFFSITE_ORGANIC = "__PIN_OFFSITE_ORGANIC__"
_TOK_PIN_URL             = "__PIN_URL__"
_TOK_REDDIT_OUT_PAID     = "__REDDIT_OUT_PAID__"
_TOK_REDDIT_OUT_ORGANIC  = "__REDDIT_OUT_ORGANIC__"
_TOK_REDDIT_THREAD       = "__REDDIT_THREAD__"
_TOK_GOOGLE_DOUBLECLICK  = "__GOOGLE_DOUBLECLICK__"
_TOK_GOOGLE_ACLK         = "__GOOGLE_ACLK__"
_TOK_GOOGLE_ORIGIN       = "__GOOGLE_ORIGIN__"
_TOK_GOOGLE_SERP         = "__GOOGLE_SERP__"
_TOK_BING_ACLICK         = "__BING_ACLICK__"
_TOK_BING_SERP           = "__BING_SERP__"


# Values are (token_or_literal, weight) tuples. Weights normalise
# at pick time — they don't need to sum to 100 exactly.

_PLATFORM_HOMEPAGES: Dict[str, str] = {
    "facebook": "https://www.facebook.com/",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/",
    "youtube": "https://www.youtube.com/",
    "twitter": "https://twitter.com/",
    "x": "https://x.com/",
    "snapchat": "https://www.snapchat.com/",
    "pinterest": "https://www.pinterest.com/",
    "reddit": "https://www.reddit.com/",
    "linkedin": "https://www.linkedin.com/",
    "whatsapp": "https://www.whatsapp.com/",
    "telegram": "https://t.me/",
    "discord": "https://discord.com/",
    "messenger": "https://www.messenger.com/",
    "google": "https://www.google.com/",
    "bing": "https://www.bing.com/",
    "duckduckgo": "https://duckduckgo.com/",
    "yahoo": "https://search.yahoo.com/",
    "yandex": "https://yandex.com/",
}


def _platform_homepage(platform: str) -> str:
    p = (platform or "").lower().strip()
    if p == "x":
        return _PLATFORM_HOMEPAGES["x"]
    return _PLATFORM_HOMEPAGES.get(p, "")


# Platforms whose link-shims break on external cold clicks (interstitial / error page).
_WARNING_TRIGGER_WRAPPER_FRAGMENTS: Tuple[str, ...] = (
    "tiktok.com/link/v2",
    "l.facebook.com/l.php",
    "lm.facebook.com/l.php",
    "l.messenger.com/l.php",
    "l.instagram.com/",
    "m.facebook.com/flx",
    "facebook.com/flx/warn",
    "youtube.com/redirect",
    "l.snapchat.com/",
    "pinterest.com/offsite",
    "linkedin.com/redir/redirect",
    "out.reddit.com/",
    "twitter.com/i/redirect",
    "x.com/i/redirect",
)

# Only search-engine shims reliably forward cold external clicks without errors.
_SAFE_HTTP_BOUNCE_PREFIXES: Tuple[str, ...] = (
    "https://www.google.com/url?",
    "https://google.com/url?",
    "https://www.bing.com/aclick?",
    "https://bing.com/aclick?",
)

# Social / video platforms — never HTTP-bounce; use direct 302 + platform params.
_NO_HTTP_BOUNCE_PLATFORMS = frozenset({
    "tiktok", "tt", "facebook", "messenger", "instagram",
    "twitter", "x", "linkedin", "reddit", "youtube", "snapchat",
    "pinterest", "whatsapp", "telegram", "discord",
})


def is_warning_trigger_wrapper_url(url: str) -> bool:
    """True when navigating here shows interstitials/errors on external cold clicks."""
    if not (url or "").strip():
        return False
    low = (url or "").lower()
    return any(frag in low for frag in _WARNING_TRIGGER_WRAPPER_FRAGMENTS)


def is_cold_external_link_click(user_agent: str, platform: str) -> bool:
    """True when the visitor is NOT inside the platform's in-app WebView."""
    inapp = is_inapp_browser_ua(user_agent or "")
    if not inapp:
        return True
    plat = (platform or "").lower().strip()
    if plat == "x":
        plat = "twitter"
    if inapp == "twitter" and plat in ("twitter", "x"):
        return False
    return inapp != plat


def is_safe_http_wrapper_bounce(url: str) -> bool:
    """Whitelist-only: only proven-safe search shims may HTTP-bounce."""
    if not (url or "").strip():
        return False
    if is_warning_trigger_wrapper_url(url):
        return False
    low = (url or "").lower()
    return any(low.startswith(prefix) for prefix in _SAFE_HTTP_BOUNCE_PREFIXES)


def should_http_wrapper_bounce(user_agent: str, platform: str, url: str) -> bool:
    """v2.2.0 cold-click rule: skip warning-trigger shims for external browsers."""
    if not (url or "").strip():
        return False
    if not is_safe_http_wrapper_bounce(url):
        return False
    if is_warning_trigger_wrapper_url(url) and is_cold_external_link_click(user_agent, platform):
        return False
    return True


def platform_supports_http_wrapper_bounce(platform: str) -> bool:
    """Only Google/Bing search shims support safe HTTP wrapper bounce on link clicks."""
    p = (platform or "").lower().strip()
    if p == "x":
        p = "twitter"
    return p in ("google", "bing")


def _referer_is_bounce_capable(referer: str) -> bool:
    """True when navigating to `referer` can forward the user via u=/url=/q=."""
    if not (referer or "").strip():
        return False
    if is_safe_http_wrapper_bounce(referer):
        return True
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(referer)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        qs = parse_qs(parsed.query)
        if host in _SHIM_HOSTS_U_PARAM and qs.get("u"):
            return True
        if host in _SHIM_HOSTS_URL_PARAM and qs.get("url"):
            return True
        if "tiktok.com" in host and "/link/v2" in path and qs.get("u"):
            return True
        if "google." in host and path == "/url" and qs.get("q"):
            return True
        if host in ("twitter.com", "www.twitter.com", "x.com", "www.x.com") and path == "/i/redirect" and qs.get("url"):
            return True
    except Exception:
        return False
    return False


# Meta shims — allowed on manual link clicks when operator enables wrapper redirect.
_LINK_EXPLICIT_WRAPPER_PLATFORMS = frozenset({"facebook", "instagram", "messenger"})
# In-app-only shims — require matching in-app UA (cold Chrome blocked).
_LINK_INAPP_WRAPPER_PLATFORMS = frozenset({
    "twitter", "x", "linkedin", "pinterest", "reddit", "youtube", "snapchat", "tiktok",
})
_LINK_WRAPPER_BUILD_PLATFORMS = _LINK_EXPLICIT_WRAPPER_PLATFORMS | _LINK_INAPP_WRAPPER_PLATFORMS

_REFERER_HOST_TO_PLATFORM: Dict[str, str] = {
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "m.facebook.com": "facebook",
    "l.facebook.com": "facebook",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "l.instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
    "m.tiktok.com": "tiktok",
    "twitter.com": "twitter",
    "www.twitter.com": "twitter",
    "x.com": "twitter",
    "www.x.com": "twitter",
    "t.co": "twitter",
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
    "pinterest.com": "pinterest",
    "www.pinterest.com": "pinterest",
    "reddit.com": "reddit",
    "www.reddit.com": "reddit",
    "out.reddit.com": "reddit",
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "google.com": "google",
    "www.google.com": "google",
    "bing.com": "bing",
    "www.bing.com": "bing",
    "snapchat.com": "snapchat",
    "www.snapchat.com": "snapchat",
    "l.snapchat.com": "snapchat",
    "messenger.com": "messenger",
    "www.messenger.com": "messenger",
    "l.messenger.com": "messenger",
}


def platform_from_referer_url(referer_url: str) -> str:
    """Best-effort platform tag from a referer / landing URL host."""
    try:
        host = (urlparse(referer_url or "").netloc or "").lower().strip()
        if host.startswith("www."):
            host = host[4:]
        if host in _REFERER_HOST_TO_PLATFORM:
            return _REFERER_HOST_TO_PLATFORM[host]
        if host.endswith(".facebook.com"):
            return "facebook"
        if host.endswith(".google."):
            return "google"
    except Exception:
        pass
    return ""


def should_link_wrapper_bounce(
    user_agent: str,
    platform: str,
    url: str,
    *,
    wrapper_redirect_enabled: bool = False,
    allow_risky_wrapper: bool = False,
) -> bool:
    """Manual link clicks: platform HTTP wrapper when safe or operator opted in."""
    if not (url or "").strip():
        return False
    if not _referer_is_bounce_capable(url):
        return False
    plat = (platform or "").lower().strip()
    if plat == "x":
        plat = "twitter"
    low = (url or "").lower()
    cold = is_cold_external_link_click(user_agent, platform)
    if "tiktok.com/link/v2" in low:
        return bool(allow_risky_wrapper and not cold)
    if plat in ("google", "bing"):
        return True
    if plat in _LINK_EXPLICIT_WRAPPER_PLATFORMS:
        return bool(wrapper_redirect_enabled)
    if plat in _LINK_INAPP_WRAPPER_PLATFORMS:
        if not wrapper_redirect_enabled:
            return False
        return not cold
    if is_warning_trigger_wrapper_url(url) and cold:
        return False
    return bool(wrapper_redirect_enabled and not cold)


def build_link_explicit_wrapper_url(
    platform: str,
    destination_url: str,
    *,
    is_paid: bool = True,
    allow_risky: bool = False,
) -> str:
    """Deterministic platform link-shim for manual link HTTP wrapper bounce."""
    p = (platform or "").lower().strip()
    if p == "x":
        p = "twitter"
    if p not in _LINK_WRAPPER_BUILD_PLATFORMS and p not in ("google", "bing"):
        return ""
    dest = (destination_url or "").strip()
    if not dest:
        return ""
    if p == "facebook":
        return _build_fb_linkshim(dest, include_paid_markers=is_paid)
    if p == "instagram":
        return _build_ig_linkshim(dest, include_paid_marker=is_paid)
    if p == "messenger":
        enc_u = quote_plus(dest)
        hash_body = _rand_alnum(
            random.randint(58, 104),
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
        )
        return f"https://l.messenger.com/l.php?u={enc_u}&h=AT{hash_body}"
    if p == "twitter":
        return _build_x_redirect(dest)
    if p == "linkedin":
        return _build_linkedin_redir(dest, include_paid_trk=is_paid)
    if p == "pinterest":
        return _build_pin_offsite(dest, include_paid_sig=is_paid)
    if p == "reddit":
        return _build_out_reddit(dest, include_paid_token=is_paid)
    if p == "youtube":
        return _build_youtube_redirect(dest, "video_ad" if is_paid else "video_description")
    if p == "snapchat":
        return f"https://l.snapchat.com/?u={quote_plus(dest)}"
    if p == "tiktok" and allow_risky:
        return f"https://www.tiktok.com/link/v2?u={quote_plus(dest)}"
    if p == "google":
        return f"https://www.google.com/url?q={quote_plus(dest)}"
    if p == "bing":
        return f"https://www.bing.com/aclick?u={quote_plus(dest)}"
    return ""


def build_wrapper_bounce_url(
    platform: str,
    destination_url: str,
    is_paid: bool = True,
) -> str:
    """Build a platform URL the browser can open that embeds `destination_url`
    and forwards the user while preserving a realistic platform Referer.

    Social/video shims (FB l.php, TikTok link/v2, YouTube redirect, etc.)
    break on external cold clicks — those platforms return "" and rely on
    direct 302 + fbclid/ttclid/utm params instead."""
    p = (platform or "").lower().strip()
    if p == "x":
        p = "twitter"
    dest = (destination_url or "").strip() or "https://example.com/"
    enc = quote_plus(dest)
    if p in _NO_HTTP_BOUNCE_PLATFORMS:
        return ""
    if p == "google":
        return f"https://www.google.com/url?q={enc}"
    if p == "bing":
        return f"https://www.bing.com/aclick?u={enc}"
    return ""


def ensure_wrapper_bounce_url(
    referer: str,
    platform: str,
    destination_url: str,
    is_paid: bool = True,
) -> str:
    if not platform_supports_http_wrapper_bounce(platform):
        return ""
    if _referer_is_bounce_capable(referer):
        return referer
    built = build_wrapper_bounce_url(platform, destination_url, is_paid)
    return built if is_safe_http_wrapper_bounce(built) else ""


def ensure_non_empty_referer(
    referer: str,
    platform: str,
    target_url: str = "",
    is_paid: bool = True,
) -> str:
    """Never return blank — pick a realistic platform referer."""
    if (referer or "").strip():
        return referer.strip()
    p = (platform or "").lower().strip()
    for _ in range(8):
        try:
            cand = build_social_wrapper_referer(p, target_url)
            if cand:
                return cand
        except Exception:
            break
    try:
        deep = build_inapp_deep_referer(p, target_url, is_paid=is_paid)
        if deep:
            return deep
    except Exception:
        pass
    home = _platform_homepage(p)
    if home:
        return home
    return ""


def _finalize_referer_for_visit(
    referer: str,
    platform: str,
    target_url: str,
    *,
    is_paid: bool = True,
    require_non_empty: bool = False,
    wrapper_redirect: bool = False,
) -> str:
    ref = (referer or "").strip()
    p = (platform or "").lower().strip()
    if wrapper_redirect and (target_url or "").strip():
        ref = ensure_wrapper_bounce_url(ref, p, target_url, is_paid)
    if require_non_empty and not ref:
        ref = ensure_non_empty_referer(ref, p, target_url, is_paid)
    return ref or ""


_PAID_ORGANIC_POOLS: Dict[str, Dict[str, List[Tuple[str, float]]]] = {
    "tiktok": {
        "paid": [
            ("",                                     60.0),
            ("https://ads.tiktok.com/",              25.0),
            ("https://link.tiktok.com/",             10.0),
            ("https://www.tiktok.com/",               5.0),
        ],
        "organic": [
            ("",                                     90.0),
            ("https://l.tiktok.com/",                 8.0),
            (_TOK_TT_VIDEO,                           2.0),
        ],
    },
    "facebook": {
        "paid": [
            (_TOK_FB_LINKSHIM_PAID,                  65.0),
            (_TOK_FB_LM_LINKSHIM,                    15.0),
            ("",                                     12.0),
            ("https://www.facebook.com/",             8.0),
        ],
        "organic": [
            (_TOK_FB_LINKSHIM_ORGANIC,               45.0),
            (_TOK_FB_PFBID,                          30.0),
            ("",                                     20.0),
            (_TOK_FB_GROUP,                           5.0),
        ],
    },
    "instagram": {
        "paid": [
            (_TOK_IG_LINK_PAID,                      60.0),
            ("",                                     25.0),
            ("https://www.instagram.com/",           15.0),
        ],
        "organic": [
            ("",                                     55.0),
            (_TOK_IG_POST,                           25.0),
            (_TOK_IG_LINK_ORGANIC,                   20.0),
        ],
    },
    "twitter": {
        "paid": [
            (_TOK_X_TCO,                             60.0),
            ("",                                     25.0),
            (_TOK_X_STATUS,                          10.0),
            (_TOK_X_REDIRECT,                         5.0),
        ],
        "organic": [
            (_TOK_X_TCO,                             75.0),
            ("",                                     15.0),
            (_TOK_X_STATUS,                          10.0),
        ],
    },
    "youtube": {
        "paid": [
            (_TOK_YT_DOUBLECLICK,                    55.0),
            ("",                                     25.0),
            (_TOK_YT_REDIRECT_AD,                    15.0),
            ("https://www.youtube.com/",              5.0),
        ],
        "organic": [
            (_TOK_YT_REDIRECT_DESC,                  60.0),
            ("",                                     25.0),
            (_TOK_YT_WATCH,                          15.0),
        ],
    },
    "linkedin": {
        "paid": [
            (_TOK_LI_REDIR_PAID,                     60.0),
            ("",                                     25.0),
            ("https://www.linkedin.com/",            15.0),
        ],
        "organic": [
            (_TOK_LI_REDIR_ORGANIC,                  55.0),
            ("",                                     30.0),
            (_TOK_LI_ACTIVITY,                       15.0),
        ],
    },
    "snapchat": {
        "paid": [
            ("",                                     82.0),
            ("https://ads.snapchat.com/",            12.0),
            ("https://www.snapchat.com/",             6.0),
        ],
        "organic": [
            ("",                                     92.0),
            ("https://story.snapchat.com/",           8.0),
        ],
    },
    "pinterest": {
        "paid": [
            (_TOK_PIN_OFFSITE_PAID,                  55.0),
            ("",                                     25.0),
            ("https://www.pinterest.com/",           20.0),
        ],
        "organic": [
            (_TOK_PIN_OFFSITE_ORGANIC,               50.0),
            (_TOK_PIN_URL,                           30.0),
            ("",                                     20.0),
        ],
    },
    "reddit": {
        "paid": [
            (_TOK_REDDIT_OUT_PAID,                   55.0),
            ("",                                     30.0),
            ("https://www.reddit.com/",              15.0),
        ],
        "organic": [
            (_TOK_REDDIT_THREAD,                     50.0),
            ("",                                     30.0),
            (_TOK_REDDIT_OUT_ORGANIC,                20.0),
        ],
    },
    "messenger": {
        # Messenger paid = FB-family same as facebook
        "paid": [
            (_TOK_FB_LM_LINKSHIM,                    50.0),
            ("",                                     30.0),
            ("https://www.messenger.com/",           20.0),
        ],
        "organic": [
            ("",                                     70.0),
            ("https://www.messenger.com/",           20.0),
            (_TOK_FB_LINKSHIM_ORGANIC,               10.0),
        ],
    },
    "google": {
        "paid": [
            (_TOK_GOOGLE_DOUBLECLICK,                65.0),
            ("",                                     25.0),
            (_TOK_GOOGLE_ACLK,                       10.0),
        ],
        "organic": [
            (_TOK_GOOGLE_ORIGIN,                     82.0),
            ("",                                     15.0),
            (_TOK_GOOGLE_SERP,                        3.0),
        ],
    },
    "bing": {
        "paid": [
            (_TOK_BING_ACLICK,                       60.0),
            ("",                                     30.0),
            ("https://www.bing.com/",                10.0),
        ],
        "organic": [
            ("https://www.bing.com/",                85.0),
            (_TOK_BING_SERP,                         10.0),
            ("",                                      5.0),
        ],
    },
    "baidu": {
        "paid": [
            ("https://www.baidu.com/",               65.0),
            ("",                                     35.0),
        ],
        "organic": [
            ("https://www.baidu.com/",               90.0),
            ("",                                     10.0),
        ],
    },
    "naver": {
        "paid": [
            ("https://search.naver.com/",            65.0),
            ("",                                     35.0),
        ],
        "organic": [
            ("https://search.naver.com/",            90.0),
            ("",                                     10.0),
        ],
    },
    "ecosia": {
        "paid": [
            ("https://www.ecosia.org/",              60.0),
            ("",                                     40.0),
        ],
        "organic": [
            ("https://www.ecosia.org/",              88.0),
            ("",                                     12.0),
        ],
    },
    "brave": {
        "paid": [
            ("https://search.brave.com/",            60.0),
            ("",                                     40.0),
        ],
        "organic": [
            ("https://search.brave.com/",            88.0),
            ("",                                     12.0),
        ],
    },
}


def _resolve_pool_token(token: str, target_url: str) -> str:
    """Dispatch a token to its builder function. Empty / literal
    values pass through unchanged. Any exception falls back to ""
    (safer than crashing a visit)."""
    if not token:
        return ""
    # Literal URL (no marker prefix)
    if not token.startswith("__"):
        return token
    try:
        if   token == _TOK_TT_VIDEO:            return _build_tiktok_video_url()
        elif token == _TOK_FB_LINKSHIM_PAID:    return _build_fb_linkshim(target_url, include_paid_markers=True)
        elif token == _TOK_FB_LINKSHIM_ORGANIC: return _build_fb_linkshim(target_url, include_paid_markers=False)
        elif token == _TOK_FB_LM_LINKSHIM:      return _build_lm_fb_linkshim_paid(target_url)
        elif token == _TOK_FB_PFBID:            return _build_fb_pfbid_post()
        elif token == _TOK_FB_GROUP:            return _build_fb_group_url()
        elif token == _TOK_IG_LINK_PAID:        return _build_ig_linkshim(target_url, include_paid_marker=True)
        elif token == _TOK_IG_LINK_ORGANIC:     return _build_ig_linkshim(target_url, include_paid_marker=False)
        elif token == _TOK_IG_POST:             return _build_ig_post_url()
        elif token == _TOK_X_TCO:               return _build_x_tco()
        elif token == _TOK_X_STATUS:            return _build_x_status_url()
        elif token == _TOK_X_REDIRECT:          return _build_x_redirect(target_url)
        elif token == _TOK_YT_DOUBLECLICK:      return _build_google_doubleclick_paid(target_url)
        elif token == _TOK_YT_REDIRECT_AD:      return _build_youtube_redirect(target_url, event="video_ad")
        elif token == _TOK_YT_REDIRECT_DESC:    return _build_youtube_redirect(target_url, event="video_description")
        elif token == _TOK_YT_WATCH:            return _build_yt_watch_url()
        elif token == _TOK_LI_REDIR_PAID:       return _build_linkedin_redir(target_url, include_paid_trk=True)
        elif token == _TOK_LI_REDIR_ORGANIC:    return _build_linkedin_redir(target_url, include_paid_trk=False)
        elif token == _TOK_LI_ACTIVITY:         return _build_linkedin_activity()
        elif token == _TOK_PIN_OFFSITE_PAID:    return _build_pin_offsite(target_url, include_paid_sig=True)
        elif token == _TOK_PIN_OFFSITE_ORGANIC: return _build_pin_offsite(target_url, include_paid_sig=False)
        elif token == _TOK_PIN_URL:             return _build_pin_url()
        elif token == _TOK_REDDIT_OUT_PAID:     return _build_out_reddit(target_url, include_paid_token=True)
        elif token == _TOK_REDDIT_OUT_ORGANIC:  return _build_out_reddit(target_url, include_paid_token=False)
        elif token == _TOK_REDDIT_THREAD:       return _build_reddit_thread()
        elif token == _TOK_GOOGLE_DOUBLECLICK:  return _build_google_doubleclick_paid(target_url)
        elif token == _TOK_GOOGLE_ACLK:         return _build_google_aclk_direct()
        elif token == _TOK_GOOGLE_ORIGIN:       return _build_google_origin()
        elif token == _TOK_GOOGLE_SERP:         return _build_google_serp_full()
        elif token == _TOK_BING_ACLICK:         return _build_bing_aclick(target_url)
        elif token == _TOK_BING_SERP:           return _build_bing_serp_full()
    except Exception:
        return ""
    return token  # Unknown token → return as-is (defensive)


def _build_inapp_deep_referer_v2(platform: str, target_url: str, is_paid: bool) -> Optional[str]:
    """v2.6.24 paid/organic referer resolver.

    Returns:
      * a str (may be "") when the platform has a pool entry.
      * None when the platform is unknown → caller falls back to legacy.
    """
    p = (platform or "").lower().strip()
    if not p:
        return None
    pools = _PAID_ORGANIC_POOLS.get(p)
    if not pools:
        return None
    mode = "paid" if is_paid else "organic"
    pool = pools.get(mode) or pools.get("paid") or pools.get("organic")
    if not pool:
        return None
    token = _pick_weighted_str(pool)
    return _resolve_pool_token(token, target_url or "")


# Backwards-compat public alias — some callers may prefer the v2 name.
build_paid_organic_referer = _build_inapp_deep_referer_v2


def apply_organic_platform_param_override(
    params: Dict[str, Any],
    platform: str,
) -> Dict[str, Any]:
    """v2.6.88 — Strip paid ad click-ids + rewrite utm_medium for organic.

    Mutates and returns `params`. Used by tracker `generate_platform_params`
    when RUT Traffic Type = Organic (`is_paid=False`).
    """
    out = params if isinstance(params, dict) else {}
    for _paid_key in (
        "ttclid", "ttp", "_t", "_r", "_f",
        "fbclid", "fbc", "igshid",
        "gclid", "gbraid", "wbraid", "gad_source",
        "msclkid", "mclid", "yclid",
        "twclid", "epik", "li_fat_id",
        "sccid", "ScCid",
    ):
        out.pop(_paid_key, None)
    _plat = (platform or "").strip().lower()
    _org_medium = {
        "tiktok": ("social", "organic", "referral"),
        "facebook": ("social", "organic", "referral"),
        "instagram": ("social", "organic", "referral"),
        "snapchat": ("social", "organic", "referral"),
        "twitter": ("social", "organic", "referral"),
        "x": ("social", "organic", "referral"),
        "pinterest": ("social", "organic", "referral"),
        "linkedin": ("social", "organic", "referral"),
        "reddit": ("social", "organic", "referral"),
        "youtube": ("social", "organic", "video"),
        "google": ("organic", "referral"),
        "bing": ("organic", "referral"),
        "yahoo": ("organic", "referral"),
        "duckduckgo": ("organic", "referral"),
        "yandex": ("organic", "referral"),
    }.get(_plat)
    if _org_medium:
        out["utm_medium"] = random.choice(list(_org_medium))
    elif (out.get("utm_medium") or "").strip().lower() in (
        "paid_social", "cpc", "ppc", "paid_search", "retargeting",
        "paid_video", "cpv", "sponsored",
    ):
        out["utm_medium"] = "organic"
    return out


def detect_is_paid(traffic_type: str, campaign_type: str = "auto",
                    platform: str = "") -> Optional[bool]:
    """Determine paid/organic mode from operator settings.

    Args:
      traffic_type: "auto" | "paid" | "organic" | "mixed"
      campaign_type: campaign preset (used only when traffic_type=='auto')
      platform: platform name (used only when 'auto' + campaign_type=='auto')

    Returns:
      True  → paid pool
      False → organic pool
      None  → use LEGACY resolver (backwards-compat, existing behaviour)
    """
    tt = (traffic_type or "auto").strip().lower()
    if tt == "paid":
        return True
    if tt == "organic":
        return False
    if tt == "mixed":
        # 60% paid, 40% organic — matches typical real-world blend
        return random.random() < 0.60
    # tt == "auto" → derive from campaign_type
    ct = (campaign_type or "auto").strip().lower()
    _PAID_CT = {"static_image", "video_ad", "carousel_ad", "story_ad",
                 "lookalike_prospect", "retargeting_warm", "retargeting_cold",
                 "search_cpc"}
    _ORGANIC_CT = {"cold_email"}  # cold email is 1:1 outreach, not paid ad
    if ct in _PAID_CT:
        return True
    if ct in _ORGANIC_CT:
        return False
    # Neither traffic_type nor campaign_type gives a hint → try platform default
    p = (platform or "").lower().strip()
    _ORGANIC_PLATFORMS = {"google", "bing", "duckduckgo", "yahoo", "yandex",
                          "baidu", "naver", "ecosia", "brave"}
    if p in _ORGANIC_PLATFORMS:
        # Search engines default to organic — Google Ads via 'search_cpc'
        return False
    if p in {"facebook", "instagram", "tiktok", "snapchat", "twitter", "x",
             "pinterest", "linkedin", "messenger"}:
        # Social platforms default to paid (most common RUT use case)
        return True
    return None  # Fully unknown → legacy behaviour


# ── v2.7.36 — Link-level Pro-Referrer (RUT parity for manual clicks) ──
_LINK_SOCIAL_PLATFORMS = frozenset({
    "facebook", "instagram", "tiktok", "twitter", "x", "snapchat",
    "pinterest", "linkedin", "messenger", "reddit", "youtube",
})
_LINK_SEARCH_PLATFORMS = frozenset({
    "google", "bing", "duckduckgo", "yahoo", "yandex", "baidu", "naver", "ecosia", "brave",
})


def platform_wants_auto_wrapper(platform: str) -> bool:
    p = (platform or "").lower().strip()
    return p in _LINK_SOCIAL_PLATFORMS or p in _LINK_SEARCH_PLATFORMS


def pool_is_social_heavy(platform_pool_value: str, threshold: float = 0.34) -> bool:
    pool = parse_weighted_pool(platform_pool_value)
    if not pool:
        return False
    heavy = sum(
        float(w) for p, w in pool
        if (p or "").lower() in _LINK_SOCIAL_PLATFORMS
        or (p or "").lower() in _LINK_SEARCH_PLATFORMS
    )
    total = sum(float(w) for _, w in pool)
    return total > 0 and (heavy / total) >= threshold


def normalize_link_pro_settings(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Clear classic/pro conflicts and enable wrapper for social-heavy pools."""
    out = dict(doc or {})
    if not out.get("referrer_pro_enabled"):
        return out
    out["forced_source"] = None
    out["forced_source_name"] = None
    out["simulate_platform"] = None
    rm = (out.get("referrer_mode") or "normal").strip().lower()
    if rm in ("no_referrer", "none"):
        out["referrer_mode"] = "normal"
    pool = str(out.get("referrer_pro_platform_pool") or "").strip()
    if pool and not bool(out.get("referrer_pro_wrapper_redirect")):
        if pool_is_social_heavy(pool):
            out["referrer_pro_wrapper_redirect"] = True
    return out


def effective_link_wrapper_redirect(link: Dict[str, Any], platform: str) -> bool:
    if not link.get("referrer_pro_enabled"):
        return bool(link.get("referrer_pro_wrapper_redirect"))
    if bool(link.get("referrer_pro_wrapper_redirect")):
        return True
    return platform_wants_auto_wrapper(platform)


def enrich_destination_link_realism(
    destination_url: str,
    *,
    user_agent: str = "",
    referer: str = "",
    accept_language: str = "",
    platform: str = "",
) -> str:
    """Legacy helper — manual link clicks no longer inject ua/referer/platform/lang.

    Those query params do NOT become the HTTP Referer / User-Agent the affiliate
    network reads; they only create synthetic clusters on the offer URL. Real
    platform attribution on link clicks uses wrapper HTTP bounce + fbclid/utm.
    Kept for backwards-compatible imports/tests; returns URL unchanged.
    """
    return (destination_url or "").strip()


def prepare_link_pro_click(
    link: Dict[str, Any],
    *,
    user_agent: str = "",
    destination_url: str = "",
    country: Optional[str] = None,
    kx_src_verified: bool = False,
    kx_platform: str = "",
    kx_traffic_type: str = "",
) -> Dict[str, Any]:
    """Resolve one manual link click with RUT-parity referrer + UA coercion."""
    out: Dict[str, Any] = {
        "pro_result": {},
        "user_agent": user_agent or "",
        "raw_user_agent": user_agent or "",
        "platform": "",
        "referer": "",
        "simulate_platform": "",
        "wrapper_target": "",
        "accept_language": "",
        "use_wrapper": False,
        "custom_params_patch": {},
        "pass_to_offer": False,
        "custom_referer_hop": "",
        "allow_risky_wrapper": False,
    }
    if kx_src_verified:
        plat = (kx_platform or "").strip().lower()
        if plat:
            out["platform"] = plat
            out["simulate_platform"] = plat
        if kx_traffic_type in ("paid", "organic"):
            out["pro_result"] = {
                "traffic_type": kx_traffic_type,
                "is_paid": (kx_traffic_type == "paid"),
                "platform": plat,
            }
        return out
    if not link.get("referrer_pro_enabled"):
        return out
    ua = user_agent or ""
    _ua_low = ua.lower()
    visitor_mobile = ("mobi" in _ua_low or "iphone" in _ua_low or "android" in _ua_low)
    pool = str(link.get("referrer_pro_platform_pool") or "").strip()
    use_wrapper_flag = bool(link.get("referrer_pro_wrapper_redirect")) or pool_is_social_heavy(pool)
    try:
        pro = resolve_pro_visit(
            ua=ua,
            platform_pool_value=pool,
            email_weights_value=str(link.get("referrer_pro_email_weights") or ""),
            brand=str(link.get("referrer_pro_brand") or ""),
            target_url=destination_url or "",
            country=(link.get("referrer_pro_country") or country or None),
            search_engine=str(link.get("referrer_pro_search_engine") or "google"),
            search_keywords=str(link.get("referrer_pro_search_keywords") or ""),
            social_wrapper_enabled=bool(link.get("referrer_pro_social_wrapper", True)),
            inapp_deep_path_enabled=bool(link.get("referrer_pro_inapp_deep_path", True)),
            strip_search_path=bool(link.get("referrer_pro_strip_search_path", True)),
            network_click_chain_enabled=False,
            network_click_host=None,
            lang_match=bool(link.get("referrer_pro_lang_match", True)),
            visitor_is_mobile=visitor_mobile,
            device_mode=str(link.get("referrer_pro_device_mode") or "auto"),
            tod_enabled=bool(link.get("referrer_pro_tod_enabled", False)),
            campaign_type=str(link.get("referrer_pro_campaign_type") or "auto"),
            traffic_type=str(link.get("referrer_pro_traffic_type") or "auto"),
            require_non_empty_referer=True,
            wrapper_redirect=use_wrapper_flag,
        )
    except Exception:
        return out
    out["pro_result"] = pro or {}
    plat = str((pro or {}).get("platform") or "").strip()
    referer = str((pro or {}).get("referer") or "").strip()
    allow_risky = bool(link.get("referrer_pro_allow_risky_wrapper"))
    out["allow_risky_wrapper"] = allow_risky
    out["pass_to_offer"] = bool(link.get("referrer_pro_pass_to_offer"))
    custom_ref = str(link.get("referrer_pro_custom_referer") or "").strip()
    preset = str(link.get("referrer_pro_inapp_preset") or "").strip().lower()
    if preset == "x":
        preset = "twitter"
    if preset:
        plat = preset
    if custom_ref.startswith(("http://", "https://")):
        referer = custom_ref
        derived = platform_from_referer_url(custom_ref)
        if derived:
            plat = preset or derived
        elif preset:
            plat = preset
    out["platform"] = plat
    out["referer"] = referer
    out["accept_language"] = str((pro or {}).get("accept_language") or "")
    if custom_ref and "{offer_url}" in custom_ref and (destination_url or "").strip():
        try:
            out["custom_referer_hop"] = expand_link_macros(
                custom_ref,
                {
                    "offer_url": destination_url,
                    "destination_url": destination_url,
                    "referer": referer,
                    "referrer": referer,
                    "platform": plat,
                },
            )
        except Exception:
            out["custom_referer_hop"] = ""
    if plat:
        out["simulate_platform"] = plat
        raw = ua
        if platform_needs_ua_match(plat):
            try:
                coerced = coerce_ua_for_platform(raw, plat)
                if coerced:
                    out["user_agent"] = coerced
                    out["raw_user_agent"] = raw
            except Exception:
                pass
        brand = str(link.get("referrer_pro_brand") or "").strip()
        if brand:
            out["custom_params_patch"]["__brand"] = brand[:64]
        if plat == "email" and (pro or {}).get("esp"):
            out["custom_params_patch"]["__force_esp"] = str(pro.get("esp") or "")
    _wrapper_on = effective_link_wrapper_redirect(link, plat)
    if _wrapper_on and (destination_url or "").strip():
        try:
            bounce = ensure_wrapper_bounce_url(
                referer,
                plat,
                destination_url,
                is_paid=bool((pro or {}).get("is_paid")),
            )
            if not bounce and _referer_is_bounce_capable(referer):
                bounce = referer
            if not bounce and plat in _LINK_WRAPPER_BUILD_PLATFORMS and _wrapper_on:
                bounce = build_link_explicit_wrapper_url(
                    plat,
                    destination_url,
                    is_paid=bool((pro or {}).get("is_paid")),
                    allow_risky=allow_risky,
                )
            _bounce_ua = out.get("user_agent") or ua
            if bounce and should_link_wrapper_bounce(
                _bounce_ua,
                plat,
                bounce,
                wrapper_redirect_enabled=_wrapper_on,
                allow_risky_wrapper=allow_risky,
            ):
                referer = bounce
                out["referer"] = referer
                out["wrapper_target"] = bounce
                out["use_wrapper"] = True
        except Exception:
            pass
    return out


__all__ = [
    # Resolvers
    "resolve_pro_visit",
    "resolve_email_visit_weighted",
    "parse_weighted_pool",
    "parse_email_weights",
    "pick_weighted",
    # Builders
    "build_search_referer",
    "build_social_wrapper_referer",
    "build_inapp_deep_referer",
    "rebuild_referer_with_target",
    "build_sec_fetch_headers",
    "build_network_click_referer",
    "build_inapp_ua_suffix",
    "coerce_ua_for_platform",
    "platform_needs_ua_match",
    # Geo + UTM
    "get_geo_search_hosts",
    "pick_utm_variation",
    "pick_utm_campaign",
    "time_of_day_weight",
    # IDs
    "fbclid_with_realistic_timestamp",
    "gclid_with_realistic_timestamp",
    "is_inapp_browser_ua",
    # v2.1.83 — International guardrails
    "accept_language_for_country",
    "platform_device_expectation",
    "platform_matches_device",
    "campaign_type_preset",
    "quality_tier_defaults",
    "parse_offer_url_pool",
    "pick_offer_url",
    "expand_link_macros",
    "VALID_CAMPAIGN_TYPES",
    "VALID_QUALITY_TIERS",
    # v2.6.24 — Paid vs Organic split
    "build_paid_organic_referer",
    "ensure_non_empty_referer",
    "ensure_wrapper_bounce_url",
    "build_wrapper_bounce_url",
    "is_safe_http_wrapper_bounce",
    "is_warning_trigger_wrapper_url",
    "is_cold_external_link_click",
    "should_http_wrapper_bounce",
    "should_link_wrapper_bounce",
    "build_link_explicit_wrapper_url",
    "platform_from_referer_url",
    "platform_supports_http_wrapper_bounce",
    "detect_is_paid",
    "apply_organic_platform_param_override",
    "normalize_link_pro_settings",
    "effective_link_wrapper_redirect",
    "prepare_link_pro_click",
    "enrich_destination_link_realism",
    "platform_wants_auto_wrapper",
    "pool_is_social_heavy",
    # Constants
    "VALID_PLATFORM_KEYS",
    "VALID_EMAIL_KEYS",
    "DEFAULT_EMAIL_WEIGHTS",
    "EXTENDED_ESP_HOSTS",
    "WEBMAIL_REFERERS",
]
