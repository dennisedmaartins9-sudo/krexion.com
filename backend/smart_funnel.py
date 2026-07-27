"""
Native Smart Funnel engine for RUT jobs.

Replaces 400+ step JSON loops with a single adaptive brain that:
  - Detects the current screen (survey, form, deal, email popup)
  - Acts immediately on DOM/URL change (condition-based pacing)
  - Waits until conversion / min deals (no fixed step count)
  - Cleans Excel data (zip .0, DOB, phone)

Pattern families are metadata for UI/logging; the handler script is
page-order agnostic and works across reward-offer funnels.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_HANDLER_BASENAME = "smart_flow_handler.js"


def _resolve_handler_path() -> Path:
    """Find smart_flow_handler.js in native install, dev repo, or legacy scripts/."""
    module_dir = Path(__file__).resolve().parent
    candidates = [
        module_dir / _HANDLER_BASENAME,
        module_dir.parent / "scripts" / _HANDLER_BASENAME,
        module_dir.parents[1] / "scripts" / _HANDLER_BASENAME,
    ]
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Smart funnel handler not found. Tried: "
        + ", ".join(str(p) for p in candidates)
    )


SMART_FUNNEL_PATTERNS: Dict[str, Dict[str, str]] = {
    "auto": {
        "label": "Auto Detect",
        "description": "Detect retail → survey → form → deals automatically",
    },
    "reward_survey_funnel": {
        "label": "Reward Survey Funnel",
        "description": "Retail Q1–Q3 → email → surveys → form → 2–3 deals",
    },
    "survey_form_deals": {
        "label": "Survey + Form + Deals",
        "description": "Long survey path then lead form and deal wall",
    },
    "form_deals": {
        "label": "Form + Deals",
        "description": "Lead form then deal completion",
    },
}

# Safety cap — ~25 min at 1.5s/action; conversion usually ~8–15 min
MAX_ITERATIONS_DEFAULT = 1000

# Deal clicks only — deal COUNT comes from URL params (BVA/BVC/BVE), not button clicks.
DEAL_SCRIPT = r"""(function(){window.__krxDealsDone=window.__krxDealsDone||0;window.__krxDealKeys=window.__krxDealKeys||{};var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var bt=(document.body.innerText||'').toLowerCase();var host=(location.host||'').toLowerCase();function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function btns(){return Array.from(document.querySelectorAll('button,a,div,span')).filter(vis);}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}if(/do you already have/i.test(bt)){var no=btns().find(function(e){var t=txt(e).toUpperCase();return t==='NO'||t==='NO!';});if(no){rf(no);return;}}var hasCost=/your cost:\s*\$|minimum\s*deposit|best match for you|complete\s*\d+\s*deal/i.test(bt);var contBtns=btns().filter(function(e){var t=txt(e);return t==='CONTINUE'||t==='Continue';});if(!hasCost&&contBtns.length<1&&!( /uplevelrewards|levelrewards|rewardsgiant/i.test(host)))return;for(var i=0;i<contBtns.length;i++){var b=contBtns[i];var key=(b.href||'')+'|'+txt(b)+'|'+Math.round(b.getBoundingClientRect().top);if(window.__krxDealKeys[key])continue;window.__krxDealKeys[key]=1;rf(b);return;}})();"""

MODAL_NO_SCRIPT = r"""(function(){var bt=(document.body.innerText||'').toLowerCase();if(!/do you already have/i.test(bt))return;var no=Array.from(document.querySelectorAll('button,a,div,span')).find(function(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var t=((e.innerText||e.textContent||'')+'').trim().toUpperCase();return t==='NO'||t==='NO!';});if(no){try{no.scrollIntoView({block:'center'});no.click();}catch(e){}}})();"""

CONVERSION_SCRIPT = r"""(function(){var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var bt=(document.body.innerText||'').toLowerCase();var url=(location.href||'').toLowerCase();var host=(location.host||'').toLowerCase();var retail=/retailproductsusa|displayoptoffers/i.test(host);var onDealHost=/uplevelrewards|levelrewards|rewardsgiant|myprize/i.test(host);var pageWin=!retail&&onDealHost&&(/congrat|thank you|success|completed|you.?re all set|all deals/i.test(bt)||/congrat|thank-you|success/i.test(url));window.__krxConversionSignal=(n>=2)||pageWin;window.__krxDone=window.__krxConversionSignal;})();"""

PROGRESS_FINGERPRINT_JS = (
    "()=>{try{"
    "var b=document.body;var raw=(b&&b.innerText)?b.innerText:'';"
    "var h=2166136261;for(var i=0;i<Math.min(raw.length,8000);i++){h^=raw.charCodeAt(i);h=(h*16777619)>>>0;}"
    "return {url:location.href||'',hash:h,deals:window.__krxDealsDone||0,conv:!!window.__krxConversionSignal};"
    "}catch(e){return {url:'',hash:0,deals:0,conv:false};}}"
)

METRICS_JS = (
    "()=>({"
    "deals:window.__krxDealsDone||0,"
    "conv:!!window.__krxConversionSignal,"
    "url:location.href||'',"
    "host:location.host||'',"
    "snippet:(document.body.innerText||'').slice(0,120)"
    "})"
)


@dataclass
class SmartFunnelConfig:
    pattern: str = "auto"
    min_deals: int = 2
    wait_until_conversion: bool = True
    loop_interval_ms: int = 1500
    idle_poll_ms: int = 400
    max_idle_before_nudge_ms: int = 8000
    max_iterations: int = MAX_ITERATIONS_DEFAULT
    sms_answer: str = "no thanks"
    email_optin_answer: str = "yes"

    def normalized_pattern(self) -> str:
        p = (self.pattern or "auto").strip().lower()
        return p if p in SMART_FUNNEL_PATTERNS else "auto"


def load_handler_script() -> str:
    return _resolve_handler_path().read_text(encoding="utf-8").strip()


def handler_path_for_tests() -> Path:
    return _resolve_handler_path()


def url_deals_from_href(url: str) -> int:
    """Count completed deals from authoritative URL params (BVA…BVE=True)."""
    if not url:
        return 0
    u = url.upper()
    return sum(
        1
        for tag in ("BVA=TRUE", "BVB=TRUE", "BVC=TRUE", "BVD=TRUE", "BVE=TRUE")
        if tag in u
    )


def conversion_verified(metrics: Dict[str, Any], min_deals: int, wait_until_conversion: bool) -> bool:
    """True only when URL deal params (or deal-host win) satisfy min_deals."""
    url = str(metrics.get("url") or "")
    host = str(metrics.get("host") or "").lower()
    url_deals = url_deals_from_href(url)
    min_d = max(1, int(min_deals or 2))

    if url_deals >= min_d:
        return True

    if not wait_until_conversion:
        return False

    # Retail interstitial must never convert without URL deal markers.
    if any(h in host for h in ("retailproductsusa", "displayoptoffers")):
        return False

    if bool(metrics.get("conv")) and any(
        h in host for h in ("uplevelrewards", "levelrewards", "rewardsgiant", "myprize")
    ):
        return True

    return False


def _metrics_with_url_deals(metrics: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(metrics)
    url_deals = url_deals_from_href(str(out.get("url") or ""))
    out["deals"] = url_deals
    out["url_deals"] = url_deals
    return out


def list_patterns() -> List[Dict[str, str]]:
    out = []
    for key, meta in SMART_FUNNEL_PATTERNS.items():
        out.append({"id": key, "label": meta["label"], "description": meta["description"]})
    return out


async def _page_fingerprint(page) -> Dict[str, Any]:
    try:
        return await page.evaluate(PROGRESS_FINGERPRINT_JS)
    except Exception:
        return {"url": "", "hash": 0, "deals": 0, "conv": False}


async def _get_metrics(page) -> Dict[str, Any]:
    try:
        return await page.evaluate(METRICS_JS)
    except Exception:
        return {"deals": 0, "conv": False, "url": "", "host": "", "snippet": ""}


async def _condition_wait(
    page,
    prev: Dict[str, Any],
    cfg: SmartFunnelConfig,
    deadline: float,
) -> None:
    """Wait until page fingerprint changes or interval elapsed."""
    start = time.monotonic()
    while time.monotonic() < deadline:
        await asyncio.sleep(cfg.idle_poll_ms / 1000.0)
        cur = await _page_fingerprint(page)
        if cur.get("url") != prev.get("url") or cur.get("hash") != prev.get("hash"):
            return
        if cur.get("conv"):
            return
        if time.monotonic() - start >= cfg.loop_interval_ms / 1000.0:
            return


async def execute_smart_funnel(
    page,
    row: Dict[str, Any],
    *,
    substitute: Callable[[str, Dict[str, Any]], str],
    config: Optional[SmartFunnelConfig] = None,
    on_step_progress: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    job_id: Optional[str] = None,
    visit_idx: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the adaptive smart funnel until conversion or safety cap.

    Returns same shape as _execute_automation_steps for drop-in use.
    """
    cfg = config or SmartFunnelConfig()
    handler_raw = load_handler_script()
    handler = substitute(handler_raw, row or {})

    executed = 0
    last_phase = ""
    stuck_same_screen = 0
    prev_fp = await _page_fingerprint(page)

    async def _emit(phase: str, status: str = "running", extra: Optional[Dict] = None) -> None:
        nonlocal last_phase
        last_phase = phase
        if not on_step_progress:
            return
        ev = {
            "idx": executed,
            "action": "smart_funnel",
            "phase": phase,
            "status": status,
            "pattern": cfg.normalized_pattern(),
        }
        if extra:
            ev.update(extra)
        try:
            await on_step_progress(ev)
        except Exception:
            pass

    try:
        await page.evaluate(
            "() => { window.__krxDealsDone = 0; window.__krxDealKeys = {}; "
            "window.__krxConversionSignal = false; window.__krxDone = false; }"
        )
    except Exception:
        pass

    await _emit("init", "start")

    for iteration in range(1, cfg.max_iterations + 1):
        executed = iteration
        metrics = _metrics_with_url_deals(await _get_metrics(page))
        deals = int(metrics.get("url_deals") or 0)
        min_d = max(1, int(cfg.min_deals or 2))

        if conversion_verified(metrics, min_d, cfg.wait_until_conversion):
            await _emit("conversion", "ok", {"deals": deals, "url": metrics.get("url", "")})
            return {
                "status": "ok",
                "executed_steps": executed,
                "smart_funnel": True,
                "deals_done": deals,
                "url_deals": deals,
                "conversion_signal": True,
                "final_url": metrics.get("url", ""),
                "pattern": cfg.normalized_pattern(),
            }

        # Main brain
        try:
            await page.evaluate(handler)
        except Exception as e:
            logger.debug("smart_funnel handler evaluate: %s", e)

        # Deal push every iteration
        try:
            await page.evaluate(DEAL_SCRIPT)
            await page.evaluate(MODAL_NO_SCRIPT)
            await page.evaluate(CONVERSION_SCRIPT)
        except Exception:
            pass

        metrics = _metrics_with_url_deals(await _get_metrics(page))
        phase = _guess_phase(metrics.get("snippet", ""), metrics.get("url", ""))
        await _emit(phase, "running", {"deals": metrics.get("url_deals", 0), "url": metrics.get("url", "")})

        cur_fp = await _page_fingerprint(page)
        if cur_fp.get("hash") == prev_fp.get("hash") and cur_fp.get("url") == prev_fp.get("url"):
            stuck_same_screen += 1
            if stuck_same_screen >= 3 and stuck_same_screen % 3 == 0:
                try:
                    await page.evaluate("window.scrollBy(0, 350)")
                except Exception:
                    pass
        else:
            stuck_same_screen = 0
            prev_fp = cur_fp

        deadline = time.monotonic() + cfg.loop_interval_ms / 1000.0
        await _condition_wait(page, prev_fp, cfg, deadline)

        if stuck_same_screen >= int(cfg.max_idle_before_nudge_ms / max(cfg.loop_interval_ms, 1)):
            try:
                await page.evaluate(
                    "(function(){var b=document.querySelector('button,a,div,span');"
                    "if(b){try{b.click();}catch(e){}}})();"
                )
            except Exception:
                pass
            stuck_same_screen = 0

    # Safety cap reached — report URL-authoritative deal count only
    metrics = _metrics_with_url_deals(await _get_metrics(page))
    deals = int(metrics.get("url_deals") or 0)
    verified = conversion_verified(metrics, cfg.min_deals, cfg.wait_until_conversion)
    return {
        "status": "ok" if verified else "incomplete",
        "executed_steps": executed,
        "smart_funnel": True,
        "deals_done": deals,
        "url_deals": deals,
        "conversion_signal": verified,
        "final_url": metrics.get("url", ""),
        "pattern": cfg.normalized_pattern(),
        "error": None if verified else f"Max iterations ({cfg.max_iterations}) without {cfg.min_deals} URL deal markers",
    }


def _guess_phase(snippet: str, url: str) -> str:
    s = (snippet or "").lower()
    u = (url or "").lower()
    if "best match" in s or "your cost:" in s or "complete" in s and "deal" in s:
        return "deals"
    if "date of birth" in s or "first name" in s or "lfirstname" in u:
        return "form"
    if "confirm your email" in s or "sign up or resume" in s:
        return "email"
    if "question" in s or "survey" in s or "how often" in s or "homeowner" in s:
        return "survey"
    if "retailproductsusa" in u:
        return "retail"
    if "displayoptoffers" in u:
        return "offers"
    return "flow"
