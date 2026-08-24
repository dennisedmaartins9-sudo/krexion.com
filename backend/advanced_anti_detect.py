"""
Krexion — Advanced Anti-Detect Layer
=====================================

Builds on top of `anti_detect_engine.py` with the higher-difficulty
defenses (behavioral biometrics simulation, profile aging, pacing
engine, captcha provider failover, IP warm-up).

The split exists so the base `anti_detect_engine` stays small and
safe to import everywhere, while the advanced features live here
and can be opted into per-job.

Public API
----------
  PacingEngine                — Poisson-ish inter-arrival timing
  IdentityStore               — profile aging with MongoDB persistence
  BehavioralProfile           — Bezier mouse paths, keystroke variance
  warm_up_ip(page, sites)     — visit benign sites first
  pick_captcha_provider()     — round-robin across 2Captcha / AntiCaptcha / CapMonster
  health_check()              — runs a self-test and returns a 0-100 score
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


logger = logging.getLogger("advanced_anti_detect")

# ─── 1. PACING ENGINE ────────────────────────────────────────────────
class PacingEngine:
    """Generates realistic inter-arrival delays for batched visits.

    Real users don't arrive at perfectly even intervals. We model with
    a log-normal distribution centered on `target_per_hour`, with
    occasional bursts (low delay) and lulls (high delay). This defeats
    cohort detection that flags "N visits in M seconds" patterns.

    Usage in a campaign loop:
        pacer = PacingEngine(target_per_hour=10)
        for visit in visits:
            await asyncio.sleep(pacer.next_delay())
            await run_visit(visit)
    """
    def __init__(self, target_per_hour: int = 10, variance: float = 0.4):
        self.target_per_hour = max(1, int(target_per_hour))
        self.variance = max(0.05, min(2.0, variance))
        self._base = 3600.0 / self.target_per_hour

    def next_delay(self) -> float:
        """Returns seconds to wait before next visit. Log-normal jitter."""
        jitter = random.lognormvariate(0, self.variance)
        # Clamp so we don't wait >5x base or <0.2x base
        return max(self._base * 0.2, min(self._base * 5.0, self._base * jitter))

    def cohort_profile(self, total_visits: int) -> List[float]:
        """Generate a full schedule of N delays in advance, ensuring
        the total elapsed time matches the target rate while keeping
        natural variance."""
        delays = [self.next_delay() for _ in range(total_visits)]
        # Re-scale so average matches target (preserves shape, fixes rate)
        target_avg = self._base
        actual_avg = sum(delays) / len(delays) if delays else 1
        scale = target_avg / actual_avg
        return [d * scale for d in delays]


# ─── 2. IDENTITY STORE (PROFILE AGING) ───────────────────────────────
class IdentityStore:
    """Persistent storage of "identities" — fingerprint + cookies + UA
    that get reused across multiple visits over 7-30 days to simulate
    real returning users instead of always-fresh anons.

    Backed by MongoDB collection `anti_detect_identities`. Each record:
        {
          id, owner_user_id, label,
          fingerprint, geo, ua,
          cookies, local_storage, history,
          age_days, visits_count, last_used,
          burnt: false  // set true if a network flags this identity
        }
    """
    def __init__(self, db):
        self.db = db

    async def get_or_create(self, owner_user_id: str, label: str,
                             *, max_age_days: int = 30,
                             min_visits_before_rotate: int = 0,
                             fp_builder=None, geo_builder=None) -> Dict[str, Any]:
        """Returns an existing identity (if fresh & not burnt) or
        creates a brand-new one."""
        from datetime import datetime, timezone
        col = self.db.anti_detect_identities

        now = datetime.now(timezone.utc)
        cutoff_ts = now.timestamp() - max_age_days * 86400

        # Try to find a usable existing identity
        existing = await col.find_one({
            "owner_user_id": owner_user_id,
            "label": label,
            "burnt": False,
            "created_ts": {"$gt": cutoff_ts},
        }, {"_id": 0})

        if existing:
            await col.update_one(
                {"id": existing["id"]},
                {"$set": {"last_used": now.isoformat()},
                 "$inc": {"visits_count": 1}},
            )
            return existing

        # Create a new identity
        import uuid
        new_id = f"id_{uuid.uuid4().hex[:12]}"
        fp = fp_builder() if fp_builder else {}
        geo = geo_builder() if geo_builder else {}
        doc = {
            "id": new_id,
            "owner_user_id": owner_user_id,
            "label": label,
            "fingerprint": fp,
            "geo": geo,
            "ua": fp.get("ua", ""),
            "cookies": [],
            "local_storage": {},
            "history": [],
            "created_ts": now.timestamp(),
            "created_iso": now.isoformat(),
            "last_used": now.isoformat(),
            "visits_count": 1,
            "burnt": False,
        }
        await col.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    async def save_cookies(self, identity_id: str, cookies: List[dict]) -> None:
        await self.db.anti_detect_identities.update_one(
            {"id": identity_id}, {"$set": {"cookies": cookies}}
        )

    async def save_storage_state(self, identity_id: str, storage_state: dict) -> None:
        """Persist the FULL Playwright storage_state (cookies + origins +
        localStorage + sessionStorage). When the same identity_label is
        re-used, `load_storage_state()` returns this so the new context
        boots with the identity's full browsing history baked in — the
        "browser profile aging" effect.

        (2026-02 Step 4 — P1 #7 / P1 #10)
        """
        if not storage_state:
            return
        await self.db.anti_detect_identities.update_one(
            {"id": identity_id},
            {"$set": {
                "storage_state": storage_state,
                "storage_state_updated": _iso_now(),
            }},
        )

    async def pin_ua(self, identity_id: str, ua: str) -> None:
        """Pin UA on first writer only (empty/missing ua) so races don't flip identity."""
        if not identity_id or not (ua or "").strip():
            return
        await self.db.anti_detect_identities.update_one(
            {
                "id": identity_id,
                "$or": [
                    {"ua": {"$exists": False}},
                    {"ua": None},
                    {"ua": ""},
                ],
            },
            {"$set": {"ua": str(ua).strip()}},
        )

    async def load_storage_state(self, identity_id: str) -> Optional[dict]:
        doc = await self.db.anti_detect_identities.find_one(
            {"id": identity_id}, {"_id": 0, "storage_state": 1}
        )
        if not doc:
            return None
        return doc.get("storage_state")

    # ── 2026-02 Step 5 (Big-5) — per-identity rate limiter ────────
    async def reserve_visit_slot(
        self,
        identity_id: str,
        *,
        target_per_hour: int = 0,
        max_wait_seconds: float = 90.0,
    ) -> float:
        """Atomically reserve a visit slot for `identity_id`. Returns the
        seconds the caller must sleep BEFORE starting the visit.

        Coordinates RUT / Form Filler / RPA Studio runs that share the
        same `identity_label` so they don't burst against the same
        identity. Implementation: read `last_visit_at`, compute
        next-slot from `target_per_hour` (60 min / N visits with ±25%
        jitter), bump `last_visit_at` atomically.

        target_per_hour=0 → no rate limit, returns 0 immediately."""
        if not identity_id or target_per_hour <= 0:
            return 0.0
        from datetime import datetime, timezone
        col = self.db.anti_detect_identities
        now_ts = datetime.now(timezone.utc).timestamp()
        # Average inter-visit gap with ±25% jitter for naturalness
        avg_gap = max(2.0, 3600.0 / float(target_per_hour))
        jitter = (random.random() - 0.5) * 0.5 * avg_gap
        target_gap = max(2.0, avg_gap + jitter)
        # Atomic compare-and-set: only succeed if last_visit_at older
        # than our threshold OR field missing. If conflict, return wait.
        threshold = now_ts - target_gap
        res = await col.find_one_and_update(
            {"id": identity_id, "$or": [
                {"last_visit_at": {"$exists": False}},
                {"last_visit_at": {"$lt": threshold}},
            ]},
            {"$set": {"last_visit_at": now_ts}},
            return_document=False,
        )
        if res is not None:
            return 0.0
        # Couldn't reserve — compute wait
        doc = await col.find_one({"id": identity_id}, {"_id": 0, "last_visit_at": 1})
        if not doc or not doc.get("last_visit_at"):
            return 0.0
        wait = max(0.0, doc["last_visit_at"] + target_gap - now_ts)
        wait = min(wait, max_wait_seconds)
        # Reserve the slot we'll occupy after the wait
        new_slot = now_ts + wait
        await col.update_one({"id": identity_id}, {"$set": {"last_visit_at": new_slot}})
        return wait

    # ── 2026-02 Step 5 (Big-6) — per-identity fpHash persistence ──
    async def get_or_set_fp_hash(self, identity_id: str) -> int:
        """Returns a stable fpHash for this identity. First call computes
        + persists a fresh deterministic-random hash; subsequent calls
        return the same value so ClientRects noise + MediaDevices +
        Storage Quota all stay identity-stable across runs (returning
        user pattern)."""
        if not identity_id:
            return 0
        col = self.db.anti_detect_identities
        doc = await col.find_one({"id": identity_id}, {"_id": 0, "fp_hash": 1})
        if doc and isinstance(doc.get("fp_hash"), int) and doc["fp_hash"] != 0:
            return int(doc["fp_hash"]) & 0xFFFFFFFF
        new_hash = random.randint(0x10000000, 0xFFFFFFFF)
        await col.update_one({"id": identity_id}, {"$set": {"fp_hash": new_hash}})
        return new_hash

    async def mark_burnt(self, identity_id: str, reason: str = "") -> None:
        await self.db.anti_detect_identities.update_one(
            {"id": identity_id},
            {"$set": {"burnt": True, "burnt_reason": reason}},
        )


# ─── 3. BEHAVIORAL PROFILE (HUMAN-LIKE INTERACTIONS) ─────────────────
class BehavioralProfile:
    """Generates human-realistic mouse paths, keystroke timing, and
    scroll patterns. Used to defeat behavioral biometrics tools that
    look for "too-perfect" automation patterns.

    Real human characteristics this models:
      • Mouse: bezier curves with overshoot/correction, micro-shakes
      • Keystrokes: log-normal inter-key delay (~50-180ms with bursts)
      • Scroll: variable velocity, occasional read-pauses, back-scrolls
      • Reading: dwell time = words × WPM-noise
    """

    @staticmethod
    def bezier_mouse_path(start: tuple, end: tuple, steps: int = 25) -> List[tuple]:
        """Generates a list of (x, y) points along a Bezier curve from
        `start` to `end`. The curve has a randomized control point to
        produce natural mouse movement, not a straight line."""
        x1, y1 = start
        x2, y2 = end
        # Pick a random control point — biased toward the path but
        # off to one side (real mice rarely go straight)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        offset = random.uniform(20, 80) * random.choice([-1, 1])
        cx = mx + offset * random.uniform(-1, 1)
        cy = my + offset
        points = []
        for i in range(steps + 1):
            t = i / steps
            # Quadratic bezier
            x = (1-t)**2 * x1 + 2*(1-t)*t * cx + t**2 * x2
            y = (1-t)**2 * y1 + 2*(1-t)*t * cy + t**2 * y2
            # Micro-shake
            x += random.uniform(-0.5, 0.5)
            y += random.uniform(-0.5, 0.5)
            points.append((x, y))
        return points

    @staticmethod
    async def move_mouse_human(page, start_xy: Optional[tuple], end_xy: tuple) -> None:
        """Moves the mouse from `start_xy` (or current) to `end_xy`
        along a Bezier path with realistic timing."""
        try:
            start_xy = start_xy or (random.randint(100, 200), random.randint(100, 200))
            steps = random.randint(18, 35)
            path = BehavioralProfile.bezier_mouse_path(start_xy, end_xy, steps=steps)
            for x, y in path:
                await page.mouse.move(x, y)
                # 8-20ms between mouse events — real Chrome fires ~60Hz
                await asyncio.sleep(random.uniform(0.008, 0.020))
        except Exception as e:
            logger.warning(f"human mouse move failed: {e}")

    @staticmethod
    async def type_human(page, selector: str, text: str) -> None:
        """Types text with realistic per-key timing.

        Real humans:
          • Average ~50-180ms between keys
          • Bursts of 3-5 fast keys then a pause
          • Occasional 300-1000ms pauses (thinking)
          • Backspaces occasionally (~2% chance)
        """
        try:
            await page.focus(selector)
            await asyncio.sleep(random.uniform(0.2, 0.5))
            for char in text:
                # Backspace + retype with 2% probability
                if random.random() < 0.02:
                    wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
                    await page.keyboard.type(wrong)
                    await asyncio.sleep(random.uniform(0.1, 0.4))
                    await page.keyboard.press("Backspace")
                    await asyncio.sleep(random.uniform(0.05, 0.2))
                # Type the real character
                await page.keyboard.type(char)
                # Inter-key delay (log-normal)
                base = random.lognormvariate(math.log(0.08), 0.4)
                delay = max(0.04, min(0.6, base))
                # Occasional thinking pause
                if random.random() < 0.05:
                    delay += random.uniform(0.4, 1.2)
                await asyncio.sleep(delay)
        except Exception as e:
            logger.warning(f"human type failed: {e}")

    @staticmethod
    async def scroll_human(page, *, total_distance: int = 1500) -> None:
        """Scrolls down with read-pauses and occasional back-scrolls."""
        try:
            scrolled = 0
            while scrolled < total_distance:
                # Random scroll chunk 100-400px
                chunk = random.randint(80, 380)
                await page.mouse.wheel(0, chunk)
                scrolled += chunk
                # Read pause
                if random.random() < 0.3:
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                else:
                    await asyncio.sleep(random.uniform(0.2, 0.8))
                # Occasional back-scroll (re-read)
                if random.random() < 0.08:
                    back = random.randint(50, 150)
                    await page.mouse.wheel(0, -back)
                    scrolled -= back
                    await asyncio.sleep(random.uniform(0.4, 1.2))
        except Exception as e:
            logger.warning(f"human scroll failed: {e}")


# ─── 4. IP WARM-UP ───────────────────────────────────────────────────
_DEFAULT_WARMUP_SITES = [
    "https://www.google.com",
    "https://www.youtube.com",
    "https://www.wikipedia.org",
    "https://www.reddit.com",
    "https://news.ycombinator.com",
    "https://www.bing.com",
]


async def warm_up_ip(page, sites: Optional[List[str]] = None,
                      visits: int = 2, dwell_sec: float = 6.0) -> List[str]:
    """Visits 2-3 benign sites BEFORE the real target so the IP has
    realistic session history. Defeats "no referrer / no cookies"
    flagging on the actual offer.

    Returns the list of sites visited.
    """
    sites = sites or _DEFAULT_WARMUP_SITES
    selected = random.sample(sites, min(visits, len(sites)))
    visited = []
    for url in selected:
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            visited.append(url)
            # Human-ish dwell
            await BehavioralProfile.scroll_human(page, total_distance=random.randint(200, 800))
            await asyncio.sleep(random.uniform(dwell_sec * 0.6, dwell_sec * 1.4))
        except Exception as e:
            logger.warning(f"warm-up visit to {url} failed: {e}")
    return visited


# ─── 5. CAPTCHA PROVIDER FAILOVER ────────────────────────────────────
_CAPTCHA_PROVIDERS = {
    "2captcha":     {"endpoint_in": "https://2captcha.com/in.php",
                     "endpoint_res": "https://2captcha.com/res.php",
                     "method_recaptcha2": "userrecaptcha",
                     "method_hcaptcha": "hcaptcha",
                     "method_turnstile": "turnstile"},
    "anticaptcha":  {"endpoint_in": "https://api.anti-captcha.com/createTask",
                     "endpoint_res": "https://api.anti-captcha.com/getTaskResult",
                     "method_recaptcha2": "RecaptchaV2TaskProxyless",
                     "method_hcaptcha": "HCaptchaTaskProxyless",
                     "method_turnstile": "TurnstileTaskProxyless"},
    "capmonster":   {"endpoint_in": "https://api.capmonster.cloud/createTask",
                     "endpoint_res": "https://api.capmonster.cloud/getTaskResult",
                     "method_recaptcha2": "NoCaptchaTaskProxyless",
                     "method_hcaptcha": "HCaptchaTaskProxyless",
                     "method_turnstile": "TurnstileTaskProxyless"},
}


def list_captcha_providers() -> List[str]:
    return list(_CAPTCHA_PROVIDERS.keys())


async def solve_captcha_universal(
    *,
    provider: str,
    api_key: str,
    captcha_type: str,
    sitekey: str,
    page_url: str,
    action: Optional[str] = None,
    min_score: float = 0.5,
    image_base64: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified captcha solver across 2Captcha / AntiCaptcha / CapMonster.

    Returns {"ok": True, "token": "..."} or {"error": "..."}.
    """
    import httpx
    provider = provider.lower()
    if provider not in _CAPTCHA_PROVIDERS:
        return {"error": f"Unknown provider: {provider}"}
    if not api_key:
        return {"error": "API key required"}

    cfg = _CAPTCHA_PROVIDERS[provider]
    captcha_type = captcha_type.lower()

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            if provider == "2captcha":
                # GET-based 2Captcha flow
                params = {"key": api_key, "json": 1, "pageurl": page_url, "sitekey": sitekey}
                if captcha_type == "recaptcha_v2":
                    params["method"] = cfg["method_recaptcha2"]
                elif captcha_type == "recaptcha_v3":
                    params["method"] = cfg["method_recaptcha2"]
                    params["version"] = "v3"
                    params["action"] = action or "verify"
                    params["min_score"] = min_score
                elif captcha_type == "hcaptcha":
                    params["method"] = cfg["method_hcaptcha"]
                elif captcha_type == "cloudflare_turnstile":
                    params["method"] = cfg["method_turnstile"]
                elif captcha_type == "image":
                    params["method"] = "base64"
                    params["body"] = image_base64 or ""
                r = await client.get(cfg["endpoint_in"], params=params)
                data = r.json()
                if data.get("status") != 1:
                    return {"error": f"2captcha submit: {data.get('request')}"}
                task_id = data["request"]
                # Poll
                for _ in range(40):
                    await asyncio.sleep(3.0)
                    rr = await client.get(cfg["endpoint_res"], params={
                        "key": api_key, "action": "get", "id": task_id, "json": 1
                    })
                    rd = rr.json()
                    if rd.get("status") == 1:
                        return {"ok": True, "token": rd["request"]}
                    if rd.get("request") != "CAPCHA_NOT_READY":
                        return {"error": rd.get("request")}
                return {"error": "2captcha timeout"}

            else:
                # POST-JSON flow for anti-captcha / capmonster
                task = {"websiteURL": page_url, "websiteKey": sitekey}
                if captcha_type == "recaptcha_v2":
                    task["type"] = cfg["method_recaptcha2"]
                elif captcha_type == "recaptcha_v3":
                    task["type"] = "RecaptchaV3TaskProxyless"
                    task["minScore"] = min_score
                    task["pageAction"] = action or "verify"
                elif captcha_type == "hcaptcha":
                    task["type"] = cfg["method_hcaptcha"]
                elif captcha_type == "cloudflare_turnstile":
                    task["type"] = cfg["method_turnstile"]
                else:
                    return {"error": f"Unsupported type for {provider}: {captcha_type}"}
                create_resp = await client.post(cfg["endpoint_in"],
                                                 json={"clientKey": api_key, "task": task})
                cd = create_resp.json()
                if cd.get("errorId") != 0:
                    return {"error": cd.get("errorDescription") or "create task failed"}
                task_id = cd.get("taskId")
                for _ in range(40):
                    await asyncio.sleep(3.0)
                    rr = await client.post(cfg["endpoint_res"],
                                            json={"clientKey": api_key, "taskId": task_id})
                    rd = rr.json()
                    if rd.get("errorId") != 0:
                        return {"error": rd.get("errorDescription")}
                    if rd.get("status") == "ready":
                        sol = rd.get("solution", {})
                        token = (sol.get("gRecaptchaResponse") or
                                 sol.get("token") or
                                 sol.get("text") or "")
                        return {"ok": True, "token": token}
                return {"error": f"{provider} timeout"}
    except Exception as e:
        return {"error": f"{provider} exception: {e}"}


# ─── 6. ANTI-DETECT HEALTH CHECK ─────────────────────────────────────
async def run_health_check() -> Dict[str, Any]:
    """Self-test that launches the stealth engine and verifies every
    layer works. Returns a 0-100 score + per-check details.

    This is what powers the "Anti-Detect Health" tile on the System
    Health page — customers can see at a glance whether their
    deployment is functioning properly.
    """
    from playwright.async_api import async_playwright
    checks = []
    score = 0
    total = 0

    async def add_check(name, ok, detail=""):
        nonlocal score, total
        total += 1
        if ok:
            score += 1
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:140]})

    try:
        from anti_detect_engine import (
            build_fingerprint, build_geo, build_stealth_script,
            build_client_hint_headers, launch_stealth_session, _resolve_rut
        )
        await add_check("Stealth engine importable", True)
        await add_check("RUT helpers resolved", _resolve_rut())

        fp = build_fingerprint()
        geo = build_geo("US")
        await add_check("Fingerprint generated", "ua" in fp, f"{len(fp)} keys")

        script = build_stealth_script(fp, geo)
        # Full script should be 30k+ chars (the real RUT stealth is ~48k)
        await add_check("Stealth script size > 30k chars",
                        len(script) > 30000,
                        f"{len(script)} chars")
        await add_check("Stealth includes WebGL spoof", "WebGL" in script)
        await add_check("Stealth includes canvas noise",
                        "canvas" in script.lower() or "getImageData" in script)
        await add_check("Stealth includes webdriver patch",
                        "webdriver" in script)
        await add_check("Stealth includes WebRTC block",
                        "RTCPeerConnection" in script or "iceServers" in script)

        # Live browser test
        async with async_playwright() as pw:
            browser, ctx, page = await launch_stealth_session(pw, headless=True)
            wd = await page.evaluate("navigator.webdriver")
            await add_check("navigator.webdriver = false", not wd, repr(wd))
            plat = await page.evaluate("navigator.platform")
            await add_check("navigator.platform spoofed", bool(plat), str(plat))
            plugins = await page.evaluate("navigator.plugins.length")
            await add_check("navigator.plugins >= 3", plugins >= 3, f"{plugins} plugins")
            ua_data = await page.evaluate("navigator.userAgentData ? Object.keys(navigator.userAgentData) : null")
            await add_check("Sec-CH-UA (userAgentData) present", bool(ua_data), str(ua_data)[:60])
            await browser.close()
    except Exception as e:
        await add_check(f"Engine exception", False, str(e)[:140])

    percent = int((score / total) * 100) if total else 0
    return {
        "score": percent,
        "passed": score,
        "total": total,
        "checks": checks,
        "verdict": ("excellent" if percent >= 90 else
                    "good" if percent >= 75 else
                    "partial" if percent >= 50 else "broken"),
    }


__all__ = [
    "PacingEngine",
    "IdentityStore",
    "BehavioralProfile",
    "warm_up_ip",
    "list_captcha_providers",
    "solve_captcha_universal",
    "run_health_check",
]
