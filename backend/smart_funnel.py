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
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_BLOCKED_CLICK_RE = re.compile(
    r"terms\s*(?:and|&)\s*conditions?|terms\s*of\s*(?:service|use)|"
    r"privacy\s*policy|cookie\s*policy|legal\s*notice|disclaimer|"
    r"\bt\s*&\s*c\b|program\s*requirements|member\s*support|about\s*our\s*program|"
    r"about\s*the\s*survey|skip\s*the\s*survey",
    re.I,
)

_BLOCKED_HREF_RE = re.compile(
    r"policies|privacy|terms|legal|flashrewards|contact\.|program|member.?support|disclaimer|cookie",
    re.I,
)


def _href_is_blocked(href: str) -> bool:
    return bool(href and _BLOCKED_HREF_RE.search(href))


def _is_blocked_click_text(text: str) -> bool:
    """Never click Terms & Conditions / privacy footer links."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return False
    if _BLOCKED_CLICK_RE.search(t):
        return True
    tl = t.lower()
    if len(t) <= 64 and any(k in tl for k in ("terms", "privacy", "disclaimer", "legal notice", "about the survey", "about survey")):
        if not re.match(
            r"^(yes|no|continue|next|submit|often|rarely|never|weekly|monthly|daily|today|homeowner|renter)$",
            tl,
            re.I,
        ):
            return True
    return False


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

# Deal wall: click CONTINUE on each offer card; count comes from URL BVA/BVC/BVE only.
DEAL_SCRIPT = r"""(function(){if(window.__krxPythonDeals)return;window.__krxDealsDone=window.__krxDealsDone||0;window.__krxDealKeys=window.__krxDealKeys||{};var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var bt=(document.body.innerText||'').toLowerCase();var host=(location.host||'').toLowerCase();function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function btns(){return Array.from(document.querySelectorAll('button,a,div,span')).filter(vis);}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}if(/do you already have/i.test(bt)){var no=btns().find(function(e){var t=txt(e).toUpperCase();return t==='NO'||t==='NO!';});if(no){rf(no);return;}}var onDealWall=/uplevelrewards|levelrewards|rewardsgiant|displayoptoffers|eward4spot/i.test(host)||/level\s*\d+\s*deals|best match for you|next step:\s*complete|your cost:\s*\$/i.test(bt);var contBtns=btns().filter(function(e){var t=txt(e);return t==='CONTINUE'||t==='Continue';});if(!onDealWall&&contBtns.length<1)return;var pool=[];for(var i=0;i<contBtns.length;i++){var b=contBtns[i];var card='';try{var p=b.closest('div,section,article,li');if(p)card=(p.innerText||'').slice(0,80);}catch(e){}var key=card+'|'+Math.round(b.getBoundingClientRect().top)+'|'+Math.round(b.getBoundingClientRect().left);if(window.__krxDealKeys[key])continue;pool.push({b:b,key:key});}if(!pool.length)return;for(var j=pool.length-1;j>0;j--){var ri=Math.floor(Math.random()*(j+1));var tmp=pool[j];pool[j]=pool[ri];pool[ri]=tmp;}window.__krxDealKeys[pool[0].key]=1;rf(pool[0].b);return;})();"""

MODAL_NO_SCRIPT = r"""(function(){var bt=(document.body.innerText||'').toLowerCase();if(!/do you already have/i.test(bt))return;var no=Array.from(document.querySelectorAll('button,a,div,span')).find(function(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var t=((e.innerText||e.textContent||'')+'').trim().toUpperCase();return t==='NO'||t==='NO!';});if(no){try{no.scrollIntoView({block:'center'});no.click();}catch(e){}}})();"""

CONVERSION_SCRIPT = r"""(function(){var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var minD=parseInt(window.__krxMinDeals,10);if(isNaN(minD)||minD<1)minD=2;window.__krxConversionSignal=(n>=minD);window.__krxDone=window.__krxConversionSignal;})();"""

THIRD_DEAL_RECOVERY = r"""(function(){var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;var minD=parseInt(window.__krxMinDeals,10);if(isNaN(minD)||minD<1)minD=3;if(n>=minD)return;if(n<minD-1)return;window.__krxDealKeys={};function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function btns(){return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}var nav=btns().find(function(e){return /my deals|view deals|complete deals|see deals|reward status|start earning|complete\s*1\s*deal/i.test(txt(e));});if(nav){rf(nav);return;}try{window.scrollTo(0,0);window.scrollBy(0,450);}catch(e){}var cont=btns().filter(function(e){return /^continue$/i.test(txt(e));});for(var i=0;i<cont.length;i++){rf(cont[i]);return;}var a=document.querySelector('a[href*="uplevelrewards"],a[href*="levelrewards"],a[href*="displayoptoffers"]');if(a&&vis(a)){rf(a);return;}})();"""

RETAIL_REENTRY_SCRIPT = r"""(function(){if(!/retailproductsusa|bckmfr=1|default\.aspx/i.test(location.href))return;function vis(e){var s=getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden'&&e.getBoundingClientRect().width>20;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function blocked(e){var t=txt(e).toLowerCase();if(/terms|conditions|privacy|disclaimer/i.test(t))return true;var h=(e.href||e.getAttribute('href')||'').toLowerCase();return/terms|privacy|legal|disclaimer/i.test(h);}var b=Array.from(document.querySelectorAll('button,a,div,span')).filter(vis);var c=b.find(function(e){if(blocked(e))return false;return /get a quick start|get started|claim my|start earning|continue|next/i.test(txt(e).toLowerCase());});if(c){try{c.click();}catch(e){}}})();"""

RETAIL_PROGRESS_SCRIPT = r"""(function(){if(!/retailproductsusa/i.test(location.host))return;function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function blocked(e){var t=txt(e).toLowerCase();if(/terms|conditions|privacy|disclaimer|legal notice|cookie policy/i.test(t))return true;var h=(e.href||e.getAttribute('href')||'').toLowerCase();return/terms|privacy|legal|disclaimer|cookie/i.test(h);}function rf(el){if(!el||blocked(el))return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}var b=Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);var yn=b.filter(function(e){if(blocked(e))return false;var t=txt(e).toLowerCase();return t==='yes'||t==='no';});if(yn.length){rf(yn[Math.floor(Math.random()*yn.length)]);return;}var wk=b.filter(function(e){if(blocked(e))return false;var t=txt(e).toLowerCase();return t==='weekly'||t==='monthly';});if(wk.length){rf(wk[0]);return;}var cta=b.find(function(e){if(blocked(e))return false;var t=txt(e).toLowerCase();return /get a quick start|get started|claim my|start earning|activating|continue|next|use it myself|share with family/i.test(t);});if(cta){rf(cta);return;}})();"""

PROGRESS_FINGERPRINT_JS = (
    "()=>{try{"
    "var b=document.body;var raw=(b&&b.innerText)?b.innerText:'';"
    "var h=2166136261;for(var i=0;i<Math.min(raw.length,8000);i++){h^=raw.charCodeAt(i);h=(h*16777619)>>>0;}"
    "return {url:location.href||'',hash:h,deals:window.__krxDealsDone||0,conv:!!window.__krxConversionSignal};"
    "}catch(e){return {url:'',hash:0,deals:0,conv:false};}}"
)

METRICS_JS = (
    "()=>{"
    "var u=location.href||'';var n=0;"
    "if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;"
    "if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;"
    "var minD=parseInt(window.__krxMinDeals,10);if(isNaN(minD)||minD<1)minD=2;"
    "window.__krxDealsDone=n;"
    "window.__krxConversionSignal=(n>=minD);"
    "return {deals:n,conv:!!window.__krxConversionSignal,url:u,"
    "host:location.host||'',snippet:(document.body.innerText||'').slice(0,120)};"
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
    visual_pause_ms: int = 0  # slow down on phase change (live visual demos)
    require_deal_wall_seen: bool = False  # wait for LEVEL 1 DEALS before conversion
    stop_at_deal_wall: bool = False  # Task 1: success when LEVEL 1 DEALS visible (ignore URL deals)

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
    """True only when URL carries enough BVA/BVC/BVE=True deal markers."""
    del wait_until_conversion  # same strict rule always
    url_deals = url_deals_from_href(str(metrics.get("url") or ""))
    min_d = max(1, int(min_deals or 2))
    return url_deals >= min_d


def _body_on_survey(body: str) -> bool:
    s = (body or "").lower()
    return any(
        k in s
        for k in (
            "finish your survey",
            "skip the survey",
            "are you a homeowner",
            "homeowner",
            "how often do you",
            "credit/debit card",
            "online purchase",
            "generation do you",
            "which generation do you",
            "identify with the most",
            "games do you like",
            "survey to proceed",
            "when did you last",
            "purchase in an app",
            "are you a smoker",
            "active bank account",
            "do you have an active bank",
            "employment status",
            "current employment",
            "credit rating",
            "describe your credit",
            "what kind of debt",
            "select all that apply",
            "household income",
            "combined household income",
            "sponsored ad",
            "question is not required",
        )
    )


def _body_has_deal_wall(body: str, url: str = "") -> bool:
    s = (body or "").lower()
    u = (url or "").lower()
    if _body_on_survey(s):
        return False
    if "question 1" in s or "do you shop at target" in s or "get $750 towards" in s:
        return False
    has_level = "level 1 deals" in s
    has_wall = any(
        k in s
        for k in (
            "best match for you",
            "continue instructions below",
            "next step: complete 1 deal",
            "rocket money",
            "your cost: $0",
        )
    )
    on_deal_host = any(
        h in u
        for h in (
            "displayoptoffers",
            "uplevelrewards",
            "levelrewards",
            "rewardsgiant",
            "eward4spot",
        )
    )
    if has_level and has_wall:
        return True
    if on_deal_host and has_level:
        return True
    return False


def _conversion_ready(
    metrics: Dict[str, Any],
    cfg: SmartFunnelConfig,
    *,
    deal_wall_seen: bool,
    body: str = "",
    survey_active: bool = False,
) -> bool:
    if not conversion_verified(metrics, cfg.min_deals, cfg.wait_until_conversion):
        return False
    if survey_active or _body_on_survey(body):
        return False
    url = str(metrics.get("url") or "").lower()
    if "finish your survey" in (body or "").lower():
        return False
    if cfg.require_deal_wall_seen:
        if not deal_wall_seen and not _body_has_deal_wall(body, url):
            return False
    return True


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


async def _metrics_from_page(page) -> Dict[str, Any]:
    """Merge live page.url with in-page metrics — URL is authoritative for deals."""
    metrics = await _get_metrics(page)
    try:
        href = page.url or ""
    except Exception:
        href = ""
    if href:
        metrics["url"] = href
    return _metrics_with_url_deals(metrics)


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


RETAIL_MOUSE_TARGET_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 24 && r.height >= 14 && r.top >= 0 && r.top < innerHeight * 0.95;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(el) {
    var t = txt(el).toLowerCase();
    if (/terms|conditions|privacy|disclaimer|legal notice|cookie policy|program requirements/i.test(t)) return true;
    var href = (el.href || el.getAttribute('href') || '').toLowerCase();
    return /terms|privacy|legal|disclaimer|cookie/i.test(href);
  }
  function surveyAnswers(els, body) {
    return els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e).toLowerCase();
      var r = e.getBoundingClientRect();
      if (r.top < 280 || r.top > innerHeight * 0.85 || r.height < 30) return false;
      return (
        t === 'yes' || t === 'no' || t === 'weekly' || t === 'monthly' ||
        t.indexOf('use it myself') >= 0 || t.indexOf('share with family') >= 0 ||
        t.indexOf('daily') >= 0 || t.indexOf('rarely') >= 0 || t.indexOf('often') >= 0
      );
    });
  }
  var body = (document.body.innerText || '').toLowerCase();
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button],label')).filter(vis);
  var targets = [];
  if (/question 1|do you shop at target/.test(body)) {
    targets = els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e).toLowerCase();
      return t === 'yes' || t === 'no';
    });
  } else if (/question 2|what would you do/.test(body)) {
    targets = els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e).toLowerCase();
      return t.indexOf('use it myself') >= 0 || t.indexOf('share with family') >= 0;
    });
  } else if (/question 3|how often|activating your reward/.test(body)) {
    targets = els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e).toLowerCase();
      return t === 'weekly' || t === 'monthly' || t === 'daily' || t === 'rarely' || t === 'often';
    });
  } else if (/question 4/.test(body)) {
    targets = surveyAnswers(els, body);
  } else if (/question 5/.test(body)) {
    targets = surveyAnswers(els, body);
  } else {
    targets = els.filter(function (e) {
      if (blocked(e)) return false;
      return /get a quick start|get started|claim my|start earning|continue|next/i.test(txt(e));
    });
  }
  if (!targets.length) return null;
  var preferred = targets.filter(function (e) {
    return (e.tagName === 'A' || e.tagName === 'BUTTON') && e.getAttribute('role') === 'button';
  });
  if (preferred.length) targets = preferred;
  var el = targets[Math.floor(Math.random() * targets.length)];
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
}"""

RETAIL_Q1_FALLBACK_COORDS = (98, 468)  # 390x844 mobile — Yes button center from live DOM inspect
RETAIL_Q3_FALLBACK_COORDS = (98, 520), (290, 520)  # Weekly (left), Monthly (right)
RETAIL_Q5_FALLBACK_COORDS = (98, 560), (290, 560)


async def _human_page_click(page, x: float, y: float) -> None:
    """Trusted mouse click at page coords (isTrusted=true, human-like motion)."""
    import random

    jx = x + random.uniform(-2.5, 2.5)
    jy = y + random.uniform(-2.5, 2.5)
    try:
        await page.mouse.move(jx, jy, steps=random.randint(10, 18))
    except Exception:
        await page.mouse.move(jx, jy)
    await asyncio.sleep(random.uniform(0.05, 0.12))
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.04, 0.1))
    await page.mouse.up()


async def _human_click_locator(page, loc) -> bool:
    """Scroll to element and click via trusted page mouse at locator center."""
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    box = await loc.bounding_box()
    if not box or box["width"] < 8 or box["height"] < 8:
        return False
    await _human_page_click(
        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    )
    return True


async def _trusted_page_tap(page, x: float, y: float) -> None:
    """Trusted CDP click at page coordinates."""
    await _human_page_click(page, x, y)


async def _frame_mouse_click_at(page, frame, x: float, y: float) -> None:
    """Tap at coords relative to frame viewport (handles iframe offset)."""
    try:
        if frame != page.main_frame:
            fe = await frame.frame_element()
            box = await fe.bounding_box()
            if box:
                await _trusted_page_tap(page, box["x"] + x, box["y"] + y)
                return
    except Exception:
        pass
    await _trusted_page_tap(page, x, y)


async def _survey_frames_ordered(page):
    """Return frames with active survey content first (displayoptoffers iframe)."""
    scored: List[tuple] = []
    seen = set()
    for frame in page.frames:
        try:
            url = (frame.url or "").lower()
            text = str(
                await frame.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 2500).toLowerCase()"
                )
            )
            score = 0
            if "displayoptoffers" in url:
                score += 120
            if "eward4spot" in url or "uplevelrewards" in url:
                score += 80
            if _body_on_survey(text):
                score += 60
            if any(
                k in text
                for k in (
                    "credit/debit card",
                    "employment status",
                    "credit rating",
                    "what kind of debt",
                    "select all that apply",
                    "finish your survey",
                )
            ):
                score += 40
            if score > 0:
                scored.append((score, frame))
                seen.add(frame)
        except Exception:
            continue
    scored.sort(key=lambda item: item[0], reverse=True)
    ordered = [frame for _, frame in scored]
    for frame in page.frames:
        if frame not in seen:
            ordered.append(frame)
    return ordered


async def _survey_frame_locator_selectors(page) -> List[str]:
    """CSS selectors for survey iframes (cross-origin safe via frame_locator)."""
    found: List[str] = []
    for sel in (
        'iframe[src*="displayoptoffers"]',
        'iframe[src*="eward4spot"]',
        'iframe[src*="uplevelrewards"]',
        'iframe[id*="survey" i]',
        'iframe[name*="survey" i]',
    ):
        try:
            if await page.locator(sel).count() > 0:
                found.append(sel)
        except Exception:
            continue
    return found


async def _trusted_survey_click(
    page, frame, *, label: str = "", x: Optional[float] = None, y: Optional[float] = None
) -> bool:
    """Trusted Playwright click — human mouse on locator, then iframe-adjusted coords."""
    if label and not _is_blocked_click_text(label):
        for exact in (True, False):
            for role in ("button", ""):
                try:
                    if role:
                        loc = frame.get_by_role(role, name=label).first
                    else:
                        loc = frame.get_by_text(label, exact=exact).first
                    if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                        if await _human_click_locator(page, loc):
                            return True
                except Exception:
                    continue
        for sel in await _survey_frame_locator_selectors(page):
            try:
                fl = page.frame_locator(sel)
                for exact in (True, False):
                    loc = fl.get_by_text(label, exact=exact).first
                    if await loc.count() > 0:
                        if await _human_click_locator(page, loc):
                            return True
            except Exception:
                continue
    if x is not None and y is not None:
        try:
            await _frame_mouse_click_at(page, frame, float(x), float(y))
            return True
        except Exception:
            pass
    return False


async def _try_coord_below_question(page, question: str, option_index: int = 0) -> bool:
    """Click retail answer below question header (Playwright locators)."""
    for frame in page.frames:
        try:
            loc = frame.get_by_text(question, exact=False).first
            if await loc.count() == 0:
                continue
            box = await loc.bounding_box()
            if not box:
                continue
            base_y = box["y"] + box["height"] + 72
            x_positions = [box["x"] + 55, box["x"] + min(box["width"] * 0.75, 250)]
            x = x_positions[option_index % len(x_positions)]
            await page.mouse.click(x, base_y)
            await asyncio.sleep(1.2)
            return True
        except Exception:
            continue
    return False


async def _native_mouse_at_text(page, text: str) -> bool:
    """Click visible text via Playwright mouse at element center (works when JS .click() is ignored)."""
    if not text:
        return False
    for frame in page.frames:
        try:
            coords = await frame.evaluate(
                """(label) => {
                  function vis(e) {
                    var s = getComputedStyle(e);
                    if (s.display === 'none' || s.visibility === 'hidden') return false;
                    var r = e.getBoundingClientRect();
                    return r.width >= 20 && r.height >= 10;
                  }
                  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
                  var want = String(label || '').toLowerCase();
                  var blocked = /terms|conditions|privacy|disclaimer|legal notice|cookie policy|program requirements|member support|about the survey|about our program|policies|flashrewards|contact\./i;
                  var els = Array.from(document.querySelectorAll('button,div,span,[role=button],label')).filter(vis);
                  var el = els.find(function (e) {
                    var t = txt(e).toLowerCase();
                    if (blocked.test(t)) return false;
                    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
                    if (blocked.test(href)) return false;
                    var r = e.getBoundingClientRect();
                    if (r.top > 560) return false;
                    return t === want || t.indexOf(want) >= 0;
                  });
                  if (!el) return null;
                  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
                  var r = el.getBoundingClientRect();
                  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }""",
                text,
            )
            if coords and coords.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(coords["x"]), float(coords["y"]))
                await asyncio.sleep(0.8)
                return True
        except Exception:
            continue
    return False


async def _native_click_text(page, text: str, timeout_ms: int = 4000) -> bool:
    """Native click helper — mouse-at-center first, then locator fallback."""
    if _is_blocked_click_text(text):
        return False
    if await _native_mouse_at_text(page, text):
        return True
    for frame in page.frames:
        for exact in (True, False):
            try:
                loc = frame.get_by_text(text, exact=exact).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    box = await loc.bounding_box()
                    if box:
                        await _trusted_page_tap(
                            page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        )
                        await asyncio.sleep(0.8)
                        return True
                    try:
                        await loc.tap(timeout=timeout_ms)
                        return True
                    except Exception:
                        await loc.click(timeout=timeout_ms, force=True)
                    return True
            except Exception:
                continue
        for role in ("button",):
            try:
                loc = frame.get_by_role(role, name=text).first
                if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                    box = await loc.bounding_box()
                    if box:
                        await _trusted_page_tap(
                            page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        )
                        await asyncio.sleep(0.8)
                        return True
                    await loc.click(timeout=timeout_ms, force=True)
                    return True
            except Exception:
                continue
    return False


async def _locator_is_safe_survey_click(loc) -> bool:
    try:
        text = (await loc.inner_text(timeout=400)).strip()
        if _is_blocked_click_text(text):
            return False
        href = await loc.get_attribute("href")
        if _href_is_blocked(href or ""):
            return False
        box = await loc.bounding_box()
        if not box or box["y"] > 700:
            return False
        return True
    except Exception:
        return False


async def _recover_off_policy_page(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    if not any(
        k in url
        for k in (
            "policies",
            "privacy",
            "/terms",
            "flashrewards",
            "contact.",
            "legal",
            "program-requirements",
        )
    ):
        return False
    try:
        await page.go_back(timeout=12000)
        await asyncio.sleep(1.5)
        return True
    except Exception:
        pass
    for ctx_page in page.context.pages:
        if ctx_page == page:
            continue
        try:
            purl = (ctx_page.url or "").lower()
            if any(k in purl for k in ("displayoptoffers", "eward4spot", "retailproductsusa")):
                await ctx_page.bring_to_front()
                return True
        except Exception:
            continue
    return False


SURVEY_ZONE_ANSWER_JS = r"""() => {
  var body = (document.body.innerText || '').toLowerCase();
  if (/what kind of debt|select all that apply/.test(body)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 80 && r.height >= 30 && r.top >= 80 && r.top <= 620;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|program requirements|member support|about our program|privacy|terms|disclaimer|faq|reward status|medicare|unsubscribe/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\.|legal|program|member/i.test(href)) return true;
    return false;
  }
  var ANSWER = /^(excellent|good|some problems|major problems|i don't know|full time|part time|unemployed|student|self employed|retired|on disability|other|yes|no|often|rarely|never|weekly|monthly|daily|today|homeowner|renter|tax\\/irs debt|credit card|student loan|medical|timeshare|prefer not to answer)$/i;
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button],input[type=button],input[type=submit]')).filter(function (e) {
    if (!vis(e) || blocked(e)) return false;
    var t = txt(e);
    if (!t || t.length > 40) return false;
    return ANSWER.test(t);
  });
  if (!els.length) return null;
  els.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  var el = els[Math.floor(Math.random() * Math.min(els.length, 3))];
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
}"""


async def _click_survey_zone_answer(page) -> bool:
    for frame in await _survey_frames_ordered(page):
        try:
            target = await frame.evaluate(SURVEY_ZONE_ANSWER_JS)
            if target and target.get("x") is not None:
                if await _trusted_survey_click(
                    page,
                    frame,
                    label=str(target.get("label") or ""),
                    x=float(target["x"]),
                    y=float(target["y"]),
                ):
                    await asyncio.sleep(1.5)
                    logger.debug("survey zone click: %s", target.get("label"))
                    return True
        except Exception:
            continue
    return False


async def _page_has_text(page, *needles: str) -> bool:
    for needle in needles:
        if not needle:
            continue
        try:
            if await page.get_by_text(needle, exact=False).count() > 0:
                return True
        except Exception:
            pass
        for frame in page.frames:
            try:
                if await frame.get_by_text(needle, exact=False).count() > 0:
                    return True
            except Exception:
                continue
    return False


async def _click_largest_survey_button(page) -> bool:
    """Click largest visible survey answer button (mobile blue buttons)."""
    skip_re = re.compile(
        r"skip|privacy|terms|faq|program requirements|member support|about the survey|unsubscribe|disclaimer|legal notice|cookie policy",
        re.I,
    )
    for frame in await _survey_frames_ordered(page):
        try:
            locators = frame.locator("button, div, span, [role=button]")
            count = min(await locators.count(), 60)
            best_idx = -1
            best_area = 0
            for i in range(count):
                loc = locators.nth(i)
                try:
                    text = (await loc.inner_text(timeout=400)).strip()
                    box = await loc.bounding_box()
                    tag = await loc.evaluate("el => (el.tagName || '').toUpperCase()")
                except Exception:
                    continue
                if tag == "A":
                    continue
                if not text or not box or skip_re.search(text) or _is_blocked_click_text(text):
                    continue
                if len(text) > 40 or box["height"] < 28 or box["width"] < 80:
                    continue
                if box["y"] < 80 or box["y"] > 680:
                    continue
                area = box["width"] * box["height"]
                if area > best_area:
                    best_area = area
                    best_idx = i
            if best_idx >= 0:
                loc = locators.nth(best_idx)
                if await _human_click_locator(page, loc):
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            continue
    return False


async def _try_skip_survey(page) -> bool:
    for sel in await _survey_frame_locator_selectors(page):
        try:
            fl = page.frame_locator(sel)
            for label in ("Skip the survey", "Skip"):
                loc = fl.get_by_text(label, exact=False).first
                if await loc.count() > 0:
                    if await _human_click_locator(page, loc):
                        await asyncio.sleep(2.0)
                        return True
        except Exception:
            continue
    for frame in page.frames:
        for label in ("Skip the survey", "Skip"):
            try:
                loc = frame.get_by_text(label, exact=False).first
                if await loc.count() > 0:
                    if await _human_click_locator(page, loc):
                        await asyncio.sleep(2.0)
                        return True
            except Exception:
                continue
    return False


async def _survey_active_on_page(page) -> bool:
    return await _page_has_text(
        page,
        "finish your survey",
        "are you a homeowner",
        "how often do you use your credit",
        "credit/debit card",
        "when did you last make an online purchase",
        "purchase in an app",
        "generation do you belong",
        "which generation do you",
        "identify with the most",
        "games do you like",
        "are you a smoker",
        "active bank account",
        "do you have an active bank",
        "employment status",
        "current employment status",
        "credit rating",
        "describe your credit",
        "what kind of debt",
        "select all that apply",
        "household income",
        "combined household income",
    )


async def _deal_wall_on_page(page) -> bool:
    if await _survey_active_on_page(page):
        return False
    if await _page_has_text(page, "question 1", "do you shop at target", "get $750 towards"):
        return False
    has_level_header = await _page_has_text(page, "level 1 deals", "level 2 deals", "level 3 deals")
    has_wall_content = await _page_has_text(
        page,
        "best match for you",
        "continue instructions below",
        "next step: complete 1 deal",
        "rocket money",
        "your cost: $0",
    )
    has_red_continue = False
    try:
        has_red_continue = await page.get_by_text("CONTINUE", exact=True).count() > 0
    except Exception:
        pass
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    on_deal_host = any(
        h in url
        for h in (
            "displayoptoffers",
            "uplevelrewards",
            "levelrewards",
            "rewardsgiant",
            "eward4spot",
        )
    )
    if has_level_header and (has_wall_content or has_red_continue):
        return True
    if on_deal_host and has_level_header:
        return True
    if on_deal_host and has_wall_content and has_red_continue:
        return True
    return False


async def _evaluate_all_frames(page, script: str) -> None:
    for frame in page.frames:
        try:
            await frame.evaluate(script)
        except Exception:
            continue


async def _retail_body_text(page) -> str:
    chunks: List[str] = []
    for frame in page.frames:
        try:
            t = str(
                await frame.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 4000).toLowerCase()"
                )
            )
            if t and len(t.strip()) > 20:
                chunks.append(t.strip())
        except Exception:
            continue
    if not chunks:
        try:
            return str(
                await page.evaluate(
                    "() => (document.body.innerText || '').slice(0, 4000).toLowerCase()"
                )
            )
        except Exception:
            return ""
    # Prefer frame that looks like active survey/deal/form content.
    for c in chunks:
        if any(
            k in c
            for k in (
                "finish your survey",
                "level 1 deals",
                "best match for you",
                "your reward is waiting",
                "confirm your email",
                "sign up or resume",
                "first name",
                "confirm your email",
                "question 1",
                "question 2",
                "question 3",
                "question 4",
                "question 5",
            )
        ):
            return c
    return max(chunks, key=len)


async def _native_retail_mouse_click(page) -> bool:
    """Retail survey click — Playwright locators + mouse coords."""
    body = await _retail_body_text(page)
    url_l = (page.url or "").lower()
    if "retailproductsusa" not in url_l and "retailproductsusa" not in body:
        if not await _page_has_text(page, "question 1", "question 2", "question 3", "do you shop at target"):
            return False

    if "your reward is waiting" in body or "confirm your email" in body or "sign up or resume" in body:
        return await _native_click_text(page, "Continue")

    labels: List[str] = []
    if "question 1" in body or await _page_has_text(page, "question 1", "do you shop at target"):
        labels = ["Yes", "No"]
    elif "question 2" in body or await _page_has_text(page, "question 2", "what would you do"):
        labels = ["Use it myself", "Share with family"]
    elif (
        "question 3" in body
        or "activating your reward" in body
        or "how often do you shop online" in body
        or await _page_has_text(page, "question 3", "how often do you shop online")
    ):
        labels = ["Weekly", "Monthly", "Daily", "Often", "Rarely"]
    elif "question 4" in body or await _page_has_text(page, "question 4"):
        labels = ["Yes", "No", "Weekly", "Monthly", "Use it myself", "Share with family"]
    elif (
        "question 5" in body
        or "how often do you shop online" in body
        or await _page_has_text(page, "question 5")
    ):
        labels = ["Weekly", "Monthly", "Daily", "Often", "Rarely", "Yes", "No"]
    else:
        return False

    import random

    for frame in page.frames:
        try:
            target = await frame.evaluate(RETAIL_MOUSE_TARGET_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                logger.debug("retail mouse click: %s", target.get("label"))
                return True
        except Exception:
            continue

    for label in random.sample(labels, len(labels)):
        if await _click_survey_button(page, label):
            logger.debug("retail click: %s", label)
            return True

    if "question 1" in body or "do you shop at target" in body:
        x, y = RETAIL_Q1_FALLBACK_COORDS
        await page.mouse.click(float(x), float(y))
        await asyncio.sleep(1.2)
        logger.debug("retail Q1 fallback coord @ %s,%s", x, y)
        return True
    if "question 3" in body or "how often do you shop online" in body or "activating your reward" in body:
        import random as _rnd
        for x, y in _rnd.sample(list(RETAIL_Q3_FALLBACK_COORDS), 2):
            await page.mouse.click(float(x), float(y))
            await asyncio.sleep(1.2)
            logger.debug("retail Q3 fallback coord @ %s,%s", x, y)
            return True
        if await _try_coord_below_question(page, "Question 3"):
            return True
    if "question 5" in body:
        import random as _rnd
        for x, y in _rnd.sample(list(RETAIL_Q5_FALLBACK_COORDS), 2):
            await page.mouse.click(float(x), float(y))
            await asyncio.sleep(1.2)
            logger.debug("retail Q5 fallback coord @ %s,%s", x, y)
            return True
        if await _try_coord_below_question(page, "Question 5"):
            return True
    if "question 2" in body or "what would you do" in body:
        if await _try_coord_below_question(page, "Question 2"):
            return True
    if "question 4" in body:
        if await _try_coord_below_question(page, "Question 4"):
            return True
    return False


def _clean_zip(val: Any) -> str:
    s = str(val or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(c for c in s if c.isdigit())
    return digits[:5] if len(digits) >= 5 else digits


def _clean_phone(val: Any) -> str:
    digits = "".join(c for c in str(val or "") if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _birth_year_from_row(row: Dict[str, Any]) -> Optional[int]:
    try:
        raw = row.get("year")
        if raw is None or str(raw).strip() == "":
            return None
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return None


def _generation_label_from_row(row: Dict[str, Any]) -> str:
    """Map lead DOB year to displayoptoffers generation survey button label."""
    year = _birth_year_from_row(row)
    if year is None:
        return "Millennial"
    if year <= 1945:
        return "Silent Generation"
    if year <= 1964:
        return "Baby Boomer"
    if year <= 1980:
        return "Gen X"
    if year <= 1996:
        return "Millennial"
    if year <= 2012:
        return "Gen Z"
    return "Millennial"


def _weighted_yes_no(yes_pct: float = 65.0) -> str:
    """Weighted random Yes/No — default 65% Yes, 35% No."""
    import random

    return "Yes" if random.random() < (yes_pct / 100.0) else "No"


SURVEY_SKIP_CHANCE = 0.20


def _visit_should_skip_survey(page) -> bool:
    """Once per browser context: 20% of visits try Skip the survey."""
    import random

    ctx = page.context
    key = "_krx_survey_skip_roll"
    if not hasattr(ctx, key):
        setattr(ctx, key, random.random() < SURVEY_SKIP_CHANCE)
    return bool(getattr(ctx, key))


def _gender_label_from_row(row: Dict[str, Any]) -> str:
    g = str(row.get("gender") or "").strip().lower()
    if g in ("m", "male", "man"):
        return "Male"
    if g in ("f", "female", "woman"):
        return "Female"
    import random

    return random.choice(["Male", "Female"])


def _data_linked_survey_answer(body: str, row: Dict[str, Any]) -> Optional[List[str]]:
    """Only Excel/lead-data questions — everything else uses visible random pick."""
    b = (body or "").lower()
    row = row or {}
    if any(k in b for k in ("generation do you", "which generation", "identify with the most")):
        return [_generation_label_from_row(row)]
    if any(k in b for k in ("gender", "male or female", "are you male", "are you female")):
        return [_gender_label_from_row(row)]
    return None


def _is_sponsored_ad_body(body: str) -> bool:
    b = (body or "").lower()
    return any(
        k in b
        for k in (
            "sponsored ad",
            "question is not required",
            "sponsored ad;",
            "this is a sponsored",
        )
    )


SPONSORED_AD_SKIP_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 40 && r.height >= 14;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var labels = [
    'Skip Question', 'Skip', 'Next', 'Continue', 'No thanks', 'No Thanks',
    'Finish your survey to continue', 'Finish your survey'
  ];
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  for (var li = 0; li < labels.length; li++) {
    var want = labels[li].toLowerCase();
    var el = els.find(function (e) {
      var t = txt(e).toLowerCase();
      return t === want || t.indexOf(want) === 0;
    });
    if (el) {
      try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
      var r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
    }
  }
  return null;
}"""


async def _skip_sponsored_ad_step(page) -> bool:
    """Skip any sponsored ad interstitial — do not click ad answer options."""
    body = await _survey_body_text(page)
    if not _is_sponsored_ad_body(body):
        return False
    for label in (
        "Skip Question",
        "Skip",
        "Next",
        "Continue",
        "No thanks",
        "No Thanks",
        "Finish your survey to continue",
        "Finish your survey",
    ):
        if await _click_survey_labels(page, [label]):
            await asyncio.sleep(1.5)
            return True
    for frame in await _survey_frames_ordered(page):
        try:
            target = await frame.evaluate(SPONSORED_AD_SKIP_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    try:
        await page.evaluate("window.scrollBy(0, 400)")
        await asyncio.sleep(0.8)
    except Exception:
        pass
    return await _try_skip_survey(page)


SURVEY_RANDOM_VISIBLE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 55 && r.height >= 24 && r.top >= 75 && r.top <= 640;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|program requirements|member support|about our program|privacy policy|terms|disclaimer|faq|reward status|medicare|medicaid|dual eligib|health insurance coverage|licensed sales agent|sponsored ad|unsubscribe|legal notice|cookie policy/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\.|legal|program-requirements/i.test(href)) return true;
    return false;
  }
  var els = Array.from(document.querySelectorAll('button,div,span,a,[role=button],label,li')).filter(vis);
  var opts = els.filter(function (e) {
    if (blocked(e)) return false;
    var t = txt(e);
    if (!t || t.length > 90) return false;
    return true;
  });
  if (!opts.length) return null;
  opts.sort(function (a, b) {
    var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return (rb.width * rb.height) - (ra.width * ra.height);
  });
  var pool = opts.slice(0, Math.min(opts.length, 14));
  var el = pool[Math.floor(Math.random() * pool.length)];
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
}"""


async def _click_random_visible_survey_option(page) -> bool:
    """Pick any visible survey answer button at random — works for unknown/new questions."""
    body = await _survey_body_text(page)
    if _is_sponsored_ad_body(body):
        return await _skip_sponsored_ad_step(page)
    for frame in await _survey_frames_ordered(page):
        try:
            target = await frame.evaluate(SURVEY_RANDOM_VISIBLE_JS)
            if not target or target.get("x") is None:
                continue
            label = str(target.get("label") or "").strip()
            if label in ("Yes", "No"):
                if await _click_survey_yes_no_label(page, label):
                    return True
            if await _trusted_survey_click(
                page,
                frame,
                label=label,
                x=float(target["x"]),
                y=float(target["y"]),
            ):
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _survey_body_text(page) -> str:
    parts: List[str] = []
    for frame in await _survey_frames_ordered(page):
        try:
            t = str(
                await frame.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 2500).toLowerCase()"
                )
            )
            if t.strip():
                parts.append(t.strip())
        except Exception:
            continue
    if parts:
        return "\n".join(parts)
    try:
        return str(
            await page.evaluate(
                "() => (document.body.innerText || '').slice(0, 2500).toLowerCase()"
            )
        )
    except Exception:
        return ""


async def _click_survey_labels(page, labels: List[str]) -> bool:
    if not labels:
        return False
    if len(labels) == 1 and labels[0] in ("Yes", "No"):
        if await _click_survey_yes_no_label(page, labels[0]):
            return True
    for frame in await _survey_frames_ordered(page):
        if await _click_survey_answer_in_frame(page, frame, labels):
            return True
    for label in labels:
        if await _click_survey_button(page, label):
            return True
    return False


YES_NO_SURVEY_COORDS_JS = r"""(label) => {
  var want = String(label || '').trim().toUpperCase();
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 60 && r.height >= 28 && r.top >= 70 && r.top <= 650;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip|about the survey|program requirements|member support|privacy|terms|disclaimer/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  var els = Array.from(document.querySelectorAll('button,div,span,a,[role=button],label')).filter(vis);
  var matches = els.filter(function (e) {
    if (blocked(e)) return false;
    return txt(e).toUpperCase() === want;
  });
  matches.sort(function (a, b) {
    var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return (rb.width * rb.height) - (ra.width * ra.height);
  });
  var el = matches[0];
  if (!el) return null;
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: want };
}"""


async def _click_survey_yes_no_label(page, label: str) -> bool:
    """Click large survey Yes/No blue buttons — coords + frame_locator + locator.click."""
    if label not in ("Yes", "No") or _is_blocked_click_text(label):
        return False
    for frame in await _survey_frames_ordered(page):
        try:
            coords = await frame.evaluate(YES_NO_SURVEY_COORDS_JS, label)
            if coords and coords.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(coords["x"]), float(coords["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    for sel in await _survey_frame_locator_selectors(page):
        try:
            fl = page.frame_locator(sel)
            loc = fl.get_by_text(label, exact=True).first
            if await loc.count() > 0:
                try:
                    await loc.click(force=True, timeout=6000)
                except Exception:
                    if await _human_click_locator(page, loc):
                        pass
                    else:
                        continue
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    for frame in await _survey_frames_ordered(page):
        for exact in (True, False):
            try:
                loc = frame.get_by_text(label, exact=exact).first
                if await loc.count() == 0:
                    continue
                box = await loc.bounding_box()
                if not box or box["height"] < 20 or box["width"] < 40:
                    continue
                if box["y"] < 60 or box["y"] > 720:
                    continue
                try:
                    await loc.click(force=True, timeout=6000)
                except Exception:
                    if not await _human_click_locator(page, loc):
                        continue
                await asyncio.sleep(1.5)
                return True
            except Exception:
                continue
    return False


async def _type_if_present(page, selector: str, value: str, delay_ms: int = 50) -> bool:
    """Type into input character-by-character (no paste)."""
    if not value:
        return False
    for frame in page.frames:
        try:
            loc = frame.locator(selector).first
            if await loc.count() > 0:
                await loc.click(timeout=4000)
                await loc.fill("", timeout=3000)
                await loc.press_sequentially(value, delay=delay_ms, timeout=20000)
                await asyncio.sleep(0.25)
                return True
        except Exception:
            continue
    return False


async def _fill_if_present(page, selector: str, value: str) -> bool:
    return await _type_if_present(page, selector, value)


async def _fill_by_placeholder(page, placeholder: str, value: str) -> bool:
    if not value:
        return False
    return await _type_if_present(page, f"input[placeholder*='{placeholder}' i]", value)


async def _native_form_step(page, row: Dict[str, Any]) -> bool:
    """Fill lead form via Playwright locators (works in iframes)."""
    def _num(field: str, width: int = 0) -> str:
        try:
            v = str(int(float(str(row.get(field) or "0"))))
            return v.zfill(width) if width else v
        except (TypeError, ValueError):
            return ""

    data = {
        "first": str(row.get("first") or "").strip(),
        "last": str(row.get("last") or "").strip(),
        "address": str(row.get("address") or "").strip(),
        "zip": _clean_zip(row.get("zip_code")),
        "city": str(row.get("city") or "").strip(),
        "state": str(row.get("state") or "").strip().upper(),
        "phone": _clean_phone(row.get("cellphone")),
        "email": str(row.get("email") or "").strip(),
        "day": _num("day", 2),
        "month": _num("month", 2),
        "year": _num("year"),
    }
    if not data["first"]:
        return False

    filled = False
    for sel, val in (
        ("#lfirstname, #firstname, input[name*='first' i], input[placeholder*='First' i]", data["first"]),
        ("#llastname, #lastname, input[name*='last' i], input[placeholder*='Last' i]", data["last"]),
        ("#laddress, #address, input[name*='address' i], input[placeholder*='Street' i]", data["address"]),
        ("#lzip, input[name*='zip' i], input[placeholder*='Zip' i]", data["zip"]),
        ("#lcity, input[name*='city' i], input[placeholder*='City' i]", data["city"]),
        ('input[type="email"], input[name*="email" i]', data["email"]),
        ("input[name*='phone' i], input[type='tel'], input[placeholder*='Mobile' i], input[placeholder*='Phone' i]", data["phone"]),
    ):
        if await _fill_if_present(page, sel, val):
            filled = True

    for ph, val in (
        ("Street", data["address"]),
        ("Mobile", data["phone"]),
        ("Phone", data["phone"]),
        ("Month", data["month"]),
        ("Day", data["day"]),
        ("Year", data["year"]),
    ):
        if await _fill_by_placeholder(page, ph, val):
            filled = True

    if data["state"]:
        for frame in page.frames:
            try:
                loc = frame.locator("select[name*='state' i], select#lstate").first
                if await loc.count() > 0:
                    await loc.select_option(value=data["state"])
                    filled = True
                    break
            except Exception:
                try:
                    await loc.select_option(label=data["state"])
                    filled = True
                    break
                except Exception:
                    continue

    for sel, val in (
        ("select[name*='dobmonth' i], select#ldobmonth", data["month"]),
        ("select[name*='dobday' i], select#ldobday", data["day"]),
        ("select[name*='dobyear' i], select#ldobyear", data["year"]),
        ("input[placeholder='Month'], input[name='dobmonth'], input[placeholder*='Month' i]", data["month"]),
        ("input[placeholder='Day'], input[name='dobday'], input[placeholder*='Day' i]", data["day"]),
        ("input[placeholder='Year'], input[name='dobyear'], input[placeholder*='Year' i]", data["year"]),
    ):
        if await _fill_if_present(page, sel, val):
            filled = True
        elif val:
            for frame in page.frames:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() > 0:
                        tag = await loc.evaluate("el => el.tagName.toLowerCase()")
                        if tag == "select":
                            try:
                                await loc.select_option(value=val)
                            except Exception:
                                await loc.select_option(label=val)
                            filled = True
                            break
                except Exception:
                    continue

    phone = data["phone"]
    if len(phone) >= 10:
        for frame in page.frames:
            try:
                area = frame.locator("#lphonecode, #phonecode, input[name*='phonecode' i]").first
                pre = frame.locator("#lphoneprefix, #phoneprefix, input[name*='phoneprefix' i]").first
                suf = frame.locator("#lphonesuffix, #phonesuffix, input[name*='phonesuffix' i]").first
                if await area.count() > 0:
                    await area.click(timeout=3000)
                    await area.fill("")
                    await area.press_sequentially(phone[:3], delay=50, timeout=8000)
                    filled = True
                if await pre.count() > 0:
                    await pre.click(timeout=3000)
                    await pre.fill("")
                    await pre.press_sequentially(phone[3:6], delay=50, timeout=8000)
                    filled = True
                if await suf.count() > 0:
                    await suf.click(timeout=3000)
                    await suf.fill("")
                    await suf.press_sequentially(phone[6:10], delay=50, timeout=8000)
                    filled = True
                if await area.count() > 0:
                    break
            except Exception:
                continue

    gender = str(row.get("gender") or "").strip().lower()
    if gender in ("male", "female"):
        label = gender.capitalize()
        if await _click_survey_button(page, label):
            filled = True
        else:
            for frame in page.frames:
                try:
                    loc = frame.get_by_text(label, exact=True).first
                    if await loc.count() > 0:
                        box = await loc.bounding_box()
                        if box and box["height"] >= 30:
                            try:
                                await loc.tap(force=True, timeout=4000)
                            except Exception:
                                await loc.click(force=True, timeout=4000)
                            filled = True
                            await asyncio.sleep(0.4)
                            break
                except Exception:
                    continue

    for frame in page.frames:
        try:
            cb = frame.locator("input[type=checkbox]").first
            if await cb.count() > 0 and not await cb.is_checked():
                await cb.check(force=True)
                filled = True
        except Exception:
            pass

    if await _click_survey_button(page, "Continue"):
        await asyncio.sleep(1.5)
        return True
    if await _click_survey_button(page, "Submit"):
        await asyncio.sleep(1.5)
        return True
    if await _click_survey_button(page, "Next"):
        await asyncio.sleep(1.5)
        return True
    for frame in page.frames:
        try:
            loc = frame.locator("input[type=submit], button[type=submit]").first
            if await loc.count() > 0:
                await loc.click(timeout=4000, force=True)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    if filled:
        try:
            await page.mouse.click(195, 760)
            await asyncio.sleep(1.5)
            return True
        except Exception:
            pass
    return filled


async def _native_reward_status_optin_step(page, cfg: SmartFunnelConfig) -> bool:
    """Dismiss reward status email prompt (Yes!/No thank you) on offer host."""
    body = await _retail_body_text(page)
    if not any(
        k in body
        for k in ("emailed to you", "status emailed", "explore offers from our sponsors")
    ):
        return False
    for label in ("×", "X", "Close"):
        try:
            loc = page.get_by_text(label, exact=True).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if box and box["width"] <= 48:
                    await _trusted_page_tap(
                        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    await asyncio.sleep(0.6)
                    break
        except Exception:
            pass
    prefer_no = (cfg.email_optin_answer or "yes").strip().lower() in (
        "no",
        "no thanks",
        "no, thanks",
    )
    primary = (
        ["No, thank you", "No thank you", "No Thanks", "No thanks"]
        if prefer_no
        else ["Yes!", "Yes"]
    )
    fallback = ["Yes!", "Yes"] if prefer_no else ["No, thank you", "No thank you"]
    for label in primary + fallback:
        if await _click_survey_yes_no_label(page, label) or await _native_click_text(page, label):
            await asyncio.sleep(1.5)
            return True
    return False


async def _native_email_step(page, row: Dict[str, Any]) -> bool:
    """Fill email + Continue on retail email interstitial."""
    body = await _retail_body_text(page)
    has_email_ui = any(
        k in body for k in ("your reward is waiting", "confirm your email", "sign up or resume")
    )
    if not has_email_ui:
        for frame in page.frames:
            try:
                if await frame.locator('input[type="email"], input#email, input[name*="email" i]').count() > 0:
                    has_email_ui = True
                    break
            except Exception:
                continue
    if not has_email_ui:
        return False
    email = str(row.get("email") or row.get("Email") or "").strip()
    if email:
        for frame in page.frames:
            try:
                loc = frame.locator('input[type="email"], input#email, input[name*="email" i]').first
                if await loc.count() > 0:
                    await loc.click(timeout=4000)
                    await loc.fill("")
                    await loc.press_sequentially(email, delay=45, timeout=20000)
                    await asyncio.sleep(0.4)
                    break
            except Exception:
                continue
    if await _native_click_text(page, "Continue"):
        await asyncio.sleep(1.5)
        return True
    for frame in page.frames:
        try:
            loc = frame.get_by_role("button", name="Continue").first
            if await loc.count() > 0:
                await loc.click(timeout=4000, force=True)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


DEAL_CONTINUE_BURST_JS = r"""() => {
  window.__krxDealKeys = window.__krxDealKeys || {};
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var btns = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  var cont = btns.filter(function (e) { return /^continue$/i.test(txt(e)); });
  if (!cont.length) return null;
  var pick = cont[Math.floor(Math.random() * cont.length)];
  try { pick.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = pick.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, count: cont.length };
}"""


SURVEY_PICK_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 36 && r.height >= 18 && r.top >= 30 && r.top < innerHeight * 0.92;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(el) {
    var t = txt(el).toLowerCase();
    if (/terms|conditions|privacy|disclaimer|legal notice|cookie policy|program requirements/i.test(t)) return true;
    var href = (el.href || el.getAttribute('href') || '').toLowerCase();
    return /terms|privacy|legal|disclaimer|cookie/i.test(href);
  }
  var body = (document.body.innerText || '').toLowerCase();
  var isHomeowner = /are you a homeowner|homeowner/.test(body);
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  var picks = els.filter(function (e) {
    if (blocked(e)) return false;
    var t = txt(e).toLowerCase().replace(/\s+/g, ' ').trim();
    if (!t || t.length > 48) return false;
    if (isHomeowner) {
      return (
        t === 'yes' || t === 'no' || t === 'homeowner' || t === 'renter' ||
        /^yes[,.\s!]/.test(t) || /^no[,.\s!]/.test(t) ||
        t.indexOf('homeowner') >= 0 || t.indexOf('renter') >= 0 ||
        t.indexOf('own my home') >= 0
      );
    }
    return /^(yes|no|often|rarely|sometimes|never|daily|weekly|monthly|homeowner|renter|male|female|single|married|full time|part time|unemployed|student|self employed|retired|on disability|other)$/i.test(t)
      || /born 19|born 20|\(born/i.test(t)
      || t.indexOf('use it myself') >= 0
      || t.indexOf('share with family') >= 0
      || /^(silent generation|baby boomer|gen x|millennial|gen z|puzzle|role playing|casino)/i.test(t);
  });
  if (!picks.length) return null;
  picks.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  var el = picks[0];
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
}"""


async def _native_click_label_coords(page, label: str) -> bool:
    """Click visible label via native Playwright mouse (isTrusted=true). JS is read-only coords."""
    if _is_blocked_click_text(label):
        return False
    if not (label or "").strip():
        return False
    for frame in await _survey_frames_ordered(page):
        try:
            coords = await frame.evaluate(
                """(label) => {
                  function vis(e) {
                    var s = getComputedStyle(e);
                    if (s.display === 'none' || s.visibility === 'hidden') return false;
                    var r = e.getBoundingClientRect();
                    return r.width >= 30 && r.height >= 18 && r.top >= 60 && r.top <= 720;
                  }
                  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
                  function blocked(e) {
                    var t = txt(e).toLowerCase();
                    if (/skip|about the survey|program requirements|member support|privacy|terms|disclaimer/i.test(t)) return true;
                    var href = (e.href || '').toLowerCase();
                    if (/policies|flashrewards|contact\\./.test(href)) return true;
                    return false;
                  }
                  var want = String(label || '').toLowerCase();
                  var el = Array.from(document.querySelectorAll('button,div,span,a,[role=button],label,li')).filter(vis).find(function (e) {
                    if (blocked(e)) return false;
                    var t = txt(e).toLowerCase();
                    return t === want || (t.indexOf(want) >= 0 && t.length <= 48);
                  });
                  if (!el) return null;
                  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
                  var r = el.getBoundingClientRect();
                  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }""",
                label,
            )
            if coords and coords.get("x") is not None:
                if await _trusted_survey_click(
                    page,
                    frame,
                    label=label,
                    x=float(coords["x"]),
                    y=float(coords["y"]),
                ):
                    await asyncio.sleep(1.2)
                    return True
        except Exception:
            continue
    return False


async def _click_survey_button(page, label: str) -> bool:
    """Click a survey answer — coords first, then locators."""
    if await _native_click_label_coords(page, label):
        return True
    if _is_blocked_click_text(label):
        return False
    best_loc = None
    best_y = 9999.0
    for frame in page.frames:
        for exact in (True, False):
            try:
                locators = frame.get_by_text(label, exact=exact)
                count = await locators.count()
                for i in range(count):
                    loc = locators.nth(i)
                    try:
                        box = await loc.bounding_box()
                    except Exception:
                        continue
                    if not box or box["height"] < 18 or box["width"] < 40:
                        continue
                    if box["y"] < 100 or box["y"] > 700:
                        continue
                    if not await _locator_is_safe_survey_click(loc):
                        continue
                    if box["y"] < best_y:
                        best_y = box["y"]
                        best_loc = loc
            except Exception:
                continue
        for role in ("button",):
            try:
                locators = frame.get_by_role(role, name=label)
                count = await locators.count()
                for i in range(count):
                    loc = locators.nth(i)
                    box = await loc.bounding_box()
                    if not box or box["y"] < 100 or box["y"] > 560:
                        continue
                    if not await _locator_is_safe_survey_click(loc):
                        continue
                    if box["y"] < best_y:
                        best_y = box["y"]
                        best_loc = loc
            except Exception:
                continue
    if best_loc:
        try:
            await best_loc.scroll_into_view_if_needed(timeout=2000)
            try:
                await best_loc.tap(force=True, timeout=5000)
            except Exception:
                await best_loc.click(timeout=5000, force=True)
            await asyncio.sleep(1.5)
            return True
        except Exception:
            pass
    return False


async def _generic_visible_answer_click(page) -> bool:
    """Last resort — click largest visible answer-like button on page."""
    try:
        locators = page.locator("button, div, span, [role=button]")
        count = min(await locators.count(), 80)
        best_idx = -1
        best_area = 0
        skip_re = re.compile(
            r"skip|privacy|terms|conditions|faq|member support|unsubscribe|about the survey|program requirements|disclaimer|legal notice|cookie policy",
            re.I,
        )
        for i in range(count):
            loc = locators.nth(i)
            try:
                text = (await loc.inner_text(timeout=500)).strip()
            except Exception:
                continue
            if not text or len(text) > 55 or skip_re.search(text) or _is_blocked_click_text(text):
                continue
            try:
                href = await loc.get_attribute("href")
                if href and _BLOCKED_CLICK_RE.search(href):
                    continue
            except Exception:
                pass
            box = await loc.bounding_box()
            if not box or box["height"] < 26 or box["width"] < 70:
                continue
            if box["y"] < 60 or box["y"] > 700:
                continue
            area = box["width"] * box["height"]
            if area > best_area:
                best_area = area
                best_idx = i
        if best_idx >= 0:
            loc = locators.nth(best_idx)
            await loc.click(timeout=5000, force=True)
            await asyncio.sleep(1.5)
            return True
    except Exception:
        pass
    return False


DEBT_MULTISELECT_JS = r"""() => {
  var body = (document.body.innerText || '').toLowerCase();
  if (!/what kind of debt|select all that apply/.test(body)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 60 && r.height >= 26 && r.top >= 70 && r.top <= 560;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|program requirements|member support|about our program|privacy policy|terms/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  var opts = ['tax/irs debt', 'credit card', 'student loan', 'medical', 'timeshare', 'other', 'prefer not to answer'];
  function findRow(want) {
    var els = Array.from(document.querySelectorAll('button,div,span,a,label,[role=button],li')).filter(vis);
    var matches = els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e).toLowerCase().replace(/\s+/g, ' ');
      return t === want || (t.indexOf(want) >= 0 && t.length <= 42);
    });
    matches.sort(function (a, b) {
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (rb.width * rb.height) - (ra.width * ra.height);
    });
    return matches[0] || null;
  }
  var shuffled = opts.slice();
  for (var i = shuffled.length - 1; i > 0; i--) {
    var j = Math.floor(Math.random() * (i + 1));
    var tmp = shuffled[i]; shuffled[i] = shuffled[j]; shuffled[j] = tmp;
  }
  var picks = [];
  for (var pi = 0; pi < 2; pi++) {
    var el = findRow(shuffled[pi]);
    if (!el) continue;
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    picks.push({ label: shuffled[pi], x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }
  var doneEl = Array.from(document.querySelectorAll('button,div,span,a,[role=button]')).filter(vis).find(function (e) {
    return /^done$/i.test(txt(e));
  });
  var done = null;
  if (doneEl) {
    try { doneEl.scrollIntoView({ block: 'center' }); } catch (e) {}
    var dr = doneEl.getBoundingClientRect();
    done = { x: dr.left + dr.width / 2, y: dr.top + dr.height / 2 };
  }
  if (!picks.length) return null;
  return { picks: picks, done: done };
}"""


async def _native_debt_multiselect_step(page) -> bool:
    """Debt survey: pick 2 unique options then Done (native Playwright mouse)."""
    if not await _page_has_text(page, "what kind of debt", "select all that apply"):
        return False
    for frame in await _survey_frames_ordered(page):
        try:
            result = await frame.evaluate(DEBT_MULTISELECT_JS)
            if not result or not result.get("picks"):
                continue
            clicked = False
            for pick in result["picks"]:
                if pick.get("x") is None:
                    continue
                if await _trusted_survey_click(
                    page,
                    frame,
                    label=str(pick.get("label") or ""),
                    x=float(pick["x"]),
                    y=float(pick["y"]),
                ):
                    await asyncio.sleep(0.7)
                    clicked = True
            done = result.get("done")
            if done and done.get("x") is not None:
                if await _trusted_survey_click(
                    page, frame, label="Done", x=float(done["x"]), y=float(done["y"])
                ):
                    await asyncio.sleep(1.8)
                    return True
            if clicked and len(result["picks"]) >= 2:
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _frame_survey_fingerprint(frame) -> str:
    try:
        return str(
            await frame.evaluate(
                "() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 1200)"
            )
        )
    except Exception:
        return ""


async def _click_survey_answer_in_frame(page, frame, labels: List[str]) -> bool:
    """Click survey answer button by label using trusted human mouse clicks."""
    import random

    for label in random.sample(labels, len(labels)):
        if _is_blocked_click_text(label):
            continue
        label_re = re.compile(re.escape(label), re.I)
        for sel in await _survey_frame_locator_selectors(page):
            try:
                fl = page.frame_locator(sel)
                for exact in (True, False):
                    loc = fl.get_by_text(label, exact=exact).first
                    if await loc.count() > 0:
                        if await _human_click_locator(page, loc):
                            await asyncio.sleep(1.5)
                            return True
            except Exception:
                continue
        try:
            loc = frame.get_by_role("button", name=label_re).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            pass
        try:
            loc = frame.get_by_text(label, exact=True).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            pass
        try:
            loc = frame.get_by_text(label, exact=False).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            pass
        try:
            locators = frame.locator("button, div, span, a, [role=button]").filter(has_text=label_re)
            count = min(await locators.count(), 8)
            for i in range(count):
                loc = locators.nth(i)
                try:
                    box = await loc.bounding_box()
                except Exception:
                    continue
                if not box or box["width"] < 50 or box["height"] < 24:
                    continue
                if box["y"] < 70 or box["y"] > 700:
                    continue
                if not await _locator_is_safe_survey_click(loc):
                    continue
                if await _human_click_locator(page, loc):
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            continue
    return False


async def _native_survey_pick(page, row: Optional[Dict[str, Any]] = None) -> bool:
    """Fully automatic survey — no per-question config needed.

    Order: optional 20% skip entire survey → debt multiselect → sponsored ad skip
    → generation/gender from Excel row → random visible button for anything else.
    """
    row = row or {}

    if _visit_should_skip_survey(page):
        if await _try_skip_survey(page):
            return True

    if await _native_debt_multiselect_step(page):
        return True

    body = await _survey_body_text(page)
    if _is_sponsored_ad_body(body):
        if await _skip_sponsored_ad_step(page):
            return True

    if not body.strip() and not await _survey_active_on_page(page):
        return False

    data_labels = _data_linked_survey_answer(body, row)
    if data_labels and await _click_survey_labels(page, data_labels):
        return True

    if await _click_random_visible_survey_option(page):
        return True

    if await _click_survey_zone_answer(page):
        return True

    return await _click_largest_survey_button(page) or await _generic_visible_answer_click(page)


DEAL_BEST_MATCH_CONTINUE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var sections = Array.from(document.querySelectorAll('div,section,article,li')).filter(function (el) {
    if (!vis(el)) return false;
    var t = (el.innerText || '').toLowerCase();
    return t.indexOf('best match') >= 0 && /continue/i.test(t);
  });
  sections.sort(function (a, b) {
    return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
  });
  for (var si = 0; si < sections.length; si++) {
    var btns = Array.from(sections[si].querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
    var cont = btns.find(function (e) { return /^continue$/i.test(txt(e)); });
    if (cont) {
      try { cont.scrollIntoView({ block: 'center' }); } catch (e) {}
      var r = cont.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'CONTINUE' };
    }
  }
  return null;
}"""

MODAL_NO_COORDS_JS = r"""() => {
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/do you already have/i.test(bt)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var no = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis).find(function (e) {
    var t = txt(e).toUpperCase();
    return t === 'NO' || t === 'NO!';
  });
  if (!no) return null;
  try { no.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = no.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'NO', kind: 'modal' };
}"""

DEAL_WALL_INTERSTITIAL_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  }
  function coords(el, kind, extra) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    var out = { x: r.left + r.width / 2, y: r.top + r.height / 2, kind: kind };
    if (extra) { for (var k in extra) out[k] = extra[k]; }
    return out;
  }
  var bt = (document.body.innerText || '').toLowerCase();
  if (/didn't confirm.*tracking|confirm that tracking|will not get your deal credit/i.test(bt)) {
    var claim = btns().find(function (e) { return /claim deal anyway/i.test(txt(e)); });
    if (claim) return coords(claim, 'tracking', { label: 'CLAIM DEAL ANYWAY' });
    var confirm = btns().find(function (e) { return /confirm tracking/i.test(txt(e)); });
    if (confirm) return coords(confirm, 'tracking', { label: 'CONFIRM TRACKING' });
  }
  if (/alert!|must complete.*deal/i.test(bt)) {
    var links = btns().filter(function (e) { return /^continue$/i.test(txt(e)); });
    for (var i = 0; i < links.length; i++) {
      var el = links[i];
      if (el.tagName === 'A' || el.closest('[role=dialog],.modal,[class*=modal]')) {
        return coords(el, 'alert_continue', { label: 'Continue' });
      }
    }
    if (links.length) return coords(links[links.length - 1], 'alert_continue', { label: 'Continue' });
  }
  if (/do you already have/i.test(bt)) {
    return null;
  }
  return null;
}"""

NATIVE_DEAL_CARD_CONTINUE_JS = r"""() => {
  window.__krxDealKeys = window.__krxDealKeys || {};
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  }
  function dealKey(b) {
    var card = '';
    try {
      var p = b.closest('div,section,article,li');
      if (p) card = (p.innerText || '').slice(0, 80);
    } catch (e) {}
    return card + '|' + Math.round(b.getBoundingClientRect().top) + '|' + Math.round(b.getBoundingClientRect().left);
  }
  function coords(el, kind, extra) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    var out = { x: r.left + r.width / 2, y: r.top + r.height / 2, kind: kind };
    if (extra) { for (var k in extra) out[k] = extra[k]; }
    return out;
  }
  function isGreyDisabled(b) {
    var s = getComputedStyle(b);
    if (s.pointerEvents === 'none' || s.cursor === 'not-allowed') return true;
    if (parseFloat(s.opacity) < 0.45) return true;
    var m = (s.backgroundColor || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (m) {
      var r = +m[1], g = +m[2], bl = +m[3];
      if (Math.abs(r - g) < 18 && Math.abs(g - bl) < 18 && r > 110) return true;
    }
    return false;
  }
  function isFooterContinue(b) {
    if (isGreyDisabled(b)) {
      var r = b.getBoundingClientRect();
      if (r.top > innerHeight * 0.42) return true;
    }
    try {
      var p = b.closest('div,section,article,li');
      for (var up = 0; up < 10 && p; up++) {
        var t = (p.innerText || '').toLowerCase();
        if (/complete 25 deals|complete \d+ deals to claim|must complete 1 deal to continue/i.test(t)) {
          if (!/your cost:|best match for you/i.test(t.slice(0, 250))) return true;
        }
        p = p.parentElement;
      }
    } catch (e) {}
    return false;
  }
  function isDealCardBtn(b) {
    if (isFooterContinue(b)) return false;
    try {
      var p = b.closest('div,section,article,li');
      for (var up = 0; up < 8 && p; up++) {
        var t = (p.innerText || '').toLowerCase();
        if (/your cost:|best match|take survey|sign up|free trial|get paid|credit score|shopper|disney|sofi|chime|rocket money|fillwords|justplay|\$0\.00|\$0 to/i.test(t)) {
          return true;
        }
        p = p.parentElement;
      }
    } catch (e) {}
    var r = b.getBoundingClientRect();
    return r.top < innerHeight * 0.75 && !isGreyDisabled(b);
  }
  try { window.scrollBy(0, 120 + Math.floor(Math.random() * 280)); } catch (e) {}
  var candidates = [];
  var allCont = btns().filter(function (e) {
    if (!/^continue$/i.test(txt(e))) return false;
    if (isGreyDisabled(e)) return false;
    if (!isDealCardBtn(e)) return false;
    return true;
  });
  for (var i = 0; i < allCont.length; i++) {
    var b = allCont[i];
    var k = dealKey(b);
    if (window.__krxDealKeys[k]) continue;
    candidates.push({ btn: b, key: k });
  }
  if (!candidates.length) return null;
  for (var j = candidates.length - 1; j > 0; j--) {
    var ri = Math.floor(Math.random() * (j + 1));
    var tmp = candidates[j];
    candidates[j] = candidates[ri];
    candidates[ri] = tmp;
  }
  var pick = candidates[0];
  window.__krxDealKeys[pick.key] = 1;
  return coords(pick.btn, 'deal_card', { label: 'CONTINUE', key: pick.key });
}"""

NATIVE_DEAL_LEVEL_CONTINUE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  }
  function coords(el, kind, extra) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    var out = { x: r.left + r.width / 2, y: r.top + r.height / 2, kind: kind };
    if (extra) { for (var k in extra) out[k] = extra[k]; }
    return out;
  }
  function isGreyDisabled(b) {
    var s = getComputedStyle(b);
    if (s.pointerEvents === 'none' || s.cursor === 'not-allowed') return true;
    if (parseFloat(s.opacity) < 0.45) return true;
    var m = (s.backgroundColor || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (m) {
      var r = +m[1], g = +m[2], bl = +m[3];
      if (Math.abs(r - g) < 18 && Math.abs(g - bl) < 18 && r > 110) return true;
    }
    return false;
  }
  function isDealCardArea(b) {
    try {
      var p = b.closest('div,section,article,li');
      for (var up = 0; up < 6 && p; up++) {
        var t = (p.innerText || '').toLowerCase();
        if (/your cost:|best match for you/i.test(t)) return true;
        p = p.parentElement;
      }
    } catch (e) {}
    return false;
  }
  try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}
  var cont = btns().filter(function (e) {
    if (!/^continue$/i.test(txt(e))) return false;
    if (isGreyDisabled(e)) return false;
    if (isDealCardArea(e)) return false;
    return e.getBoundingClientRect().top > innerHeight * 0.35;
  });
  if (!cont.length) return null;
  cont.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  return coords(cont[0], 'level_continue', { label: 'CONTINUE' });
}"""

NATIVE_DEAL_WALL_CONTINUE_JS = NATIVE_DEAL_CARD_CONTINUE_JS

POPUP_DISMISS_COORDS_JS = r"""(label) => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var want = String(label || '').toLowerCase();
  var el = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis).find(function (e) {
    var t = txt(e).toLowerCase();
    return t === want || (t.indexOf(want) >= 0 && t.length <= 32);
  });
  if (!el) return null;
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: label };
}"""


async def _popup_frame_mouse_click_at(popup, frame, x: float, y: float) -> None:
    """Trusted mouse click at coords inside a popup (iframe offset aware)."""
    try:
        if frame != popup.main_frame:
            fe = await frame.frame_element()
            box = await fe.bounding_box()
            if box:
                await _human_page_click(popup, box["x"] + x, box["y"] + y)
                return
    except Exception:
        pass
    await _human_page_click(popup, x, y)


async def _native_deal_interstitial_step(page) -> bool:
    """Tracking modal, alert Continue link, or already-have NO on deal wall."""
    for frame in page.frames:
        try:
            target = await frame.evaluate(DEAL_WALL_INTERSTITIAL_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    for label in ("CLAIM DEAL ANYWAY", "Claim Deal Anyway", "CONFIRM TRACKING", "Continue"):
        if await _native_click_text(page, label):
            await asyncio.sleep(1.5)
            return True
    return False


async def _native_popup_deal_claim(popup) -> bool:
    """Claim/dismiss an offer tab opened from deal-wall CONTINUE."""
    for label in (
        "CLAIM DEAL ANYWAY",
        "Claim Deal Anyway",
        "CONFIRM TRACKING",
        "No thanks",
        "No Thanks",
        "Get Started",
        "Sign Up",
        "Join Now",
        "Continue",
        "CONTINUE",
        "Submit",
        "Skip",
        "Close",
    ):
        for frame in popup.frames:
            try:
                coords = await frame.evaluate(POPUP_DISMISS_COORDS_JS, label)
                if coords and coords.get("x") is not None:
                    await _popup_frame_mouse_click_at(
                        popup, frame, float(coords["x"]), float(coords["y"])
                    )
                    await asyncio.sleep(1.0)
                    return True
            except Exception:
                continue
    try:
        body = await popup.evaluate(
            "() => (document.body.innerText || '').slice(0, 2000).toLowerCase()"
        )
    except Exception:
        body = ""
    if "tracking" in body or "claim deal" in body:
        for label in ("CLAIM DEAL ANYWAY", "Claim Deal Anyway"):
            try:
                loc = popup.get_by_text(label, exact=False).first
                if await loc.count() > 0:
                    box = await loc.bounding_box()
                    if box:
                        await _human_page_click(
                            popup, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        )
                        await asyncio.sleep(1.0)
                        return True
            except Exception:
                pass
    return False


async def _wait_and_handle_offer_tabs(page, timeout_s: float = 16.0) -> None:
    """Wait for offer popup tab, claim/dismiss, close, return to main deal page."""
    main = page
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        extras = [p for p in page.context.pages if p != main]
        if extras:
            for popup in extras:
                try:
                    purl = (popup.url or "").lower()
                except Exception:
                    purl = ""
                if any(k in purl for k in ("policies", "privacy", "terms", "flashrewards", "contact.")):
                    try:
                        await popup.close()
                    except Exception:
                        pass
                    continue
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=18000)
                except Exception:
                    pass
                await asyncio.sleep(2.0)
                for _ in range(3):
                    try:
                        if await _native_popup_deal_claim(popup):
                            await asyncio.sleep(2.0)
                    except Exception:
                        pass
                    try:
                        if await _native_popup_dismiss(popup):
                            await asyncio.sleep(1.5)
                    except Exception:
                        pass
                await asyncio.sleep(1.5)
                try:
                    await popup.close()
                except Exception:
                    pass
            try:
                await main.bring_to_front()
            except Exception:
                pass
            return
        await asyncio.sleep(0.5)
    await _close_extra_offer_popups(page)


async def _native_popup_dismiss(popup) -> bool:
    """Dismiss offer popup CTAs via native Playwright mouse (isTrusted=true)."""
    dismiss_labels = (
        "CLAIM DEAL ANYWAY",
        "Claim Deal Anyway",
        "CONFIRM TRACKING",
        "No thanks",
        "No Thanks",
        "Not now",
        "Get Started",
        "Sign Up",
        "Join Now",
        "Skip",
        "Close",
        "Continue",
        "CONTINUE",
        "Submit",
    )
    for label in dismiss_labels:
        for frame in popup.frames:
            try:
                coords = await frame.evaluate(POPUP_DISMISS_COORDS_JS, label)
                if coords and coords.get("x") is not None:
                    await _popup_frame_mouse_click_at(
                        popup, frame, float(coords["x"]), float(coords["y"])
                    )
                    await asyncio.sleep(1.0)
                    return True
            except Exception:
                continue
    return False


async def _close_extra_offer_popups(page) -> None:
    """Close offer popup tabs opened by deal-wall CONTINUE; bring main page front."""
    main = page
    try:
        await main.bring_to_front()
    except Exception:
        pass
    for ctx_page in list(page.context.pages):
        if ctx_page == main:
            continue
        try:
            purl = (ctx_page.url or "").lower()
        except Exception:
            purl = ""
        if any(k in purl for k in ("policies", "privacy", "terms", "flashrewards", "contact.")):
            try:
                await ctx_page.close()
            except Exception:
                pass
            continue
        try:
            await _native_popup_deal_claim(ctx_page)
        except Exception:
            pass
        await asyncio.sleep(0.5)
        try:
            await ctx_page.close()
        except Exception:
            pass
    try:
        await main.bring_to_front()
    except Exception:
        pass


async def _native_deal_modal_no(page) -> bool:
    """Click 'Do you already have' modal NO via native Playwright mouse."""
    if not await _page_has_text(page, "do you already have", "already have this deal"):
        return False
    if await _click_survey_yes_no_label(page, "NO"):
        await asyncio.sleep(1.5)
        return True
    for label in ("NO", "No"):
        try:
            loc = page.get_by_text(label, exact=True).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if box and box["height"] >= 20:
                    await _trusted_page_tap(
                        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    await asyncio.sleep(1.5)
                    return True
        except Exception:
            pass
    for frame in page.frames:
        try:
            target = await frame.evaluate(MODAL_NO_COORDS_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _install_offer_popup_handler(page) -> None:
    """Close offer popups opened by deal-wall CONTINUE; stay on main offer page."""
    context = page.context
    main = page
    guard_key = "_krx_popup_guard_installed"
    if getattr(context, guard_key, False):
        return
    setattr(context, guard_key, True)

    async def _handle_offer_popup(popup) -> None:
        if popup == main:
            return
        try:
            purl = (popup.url or "").lower()
        except Exception:
            purl = ""
        if any(k in purl for k in ("policies", "privacy", "terms", "flashrewards", "contact.")):
            try:
                await popup.close()
            except Exception:
                pass
            try:
                await main.bring_to_front()
            except Exception:
                pass
            return
        try:
            await popup.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        dismissed = False
        try:
            dismissed = await _native_popup_deal_claim(popup)
        except Exception:
            pass
        if not dismissed:
            try:
                dismissed = await _native_popup_dismiss(popup)
            except Exception:
                pass
        if not dismissed:
            for label in ("No thanks", "No Thanks", "Continue", "CONTINUE", "Submit", "Skip", "Close"):
                try:
                    loc = popup.get_by_text(label, exact=False).first
                    if await loc.count() > 0:
                        box = await loc.bounding_box()
                        if box:
                            await _human_page_click(
                                popup,
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                            await asyncio.sleep(1.2)
                            dismissed = True
                            break
                except Exception:
                    pass
        await asyncio.sleep(2.0)
        try:
            await popup.close()
        except Exception:
            pass
        try:
            await main.bring_to_front()
        except Exception:
            pass

    def _on_page(popup) -> None:
        asyncio.create_task(_handle_offer_popup(popup))

    context.on("page", _on_page)


async def _native_click_random_continue(page) -> bool:
    """Pick a random visible CONTINUE on deal wall (fallback path)."""
    import random

    candidates: List[Any] = []
    for label in ("CONTINUE", "Continue"):
        try:
            locs = page.get_by_text(label, exact=True)
            count = await locs.count()
            for i in range(count):
                loc = locs.nth(i)
                box = await loc.bounding_box()
                if box and box["height"] >= 14:
                    candidates.append((loc, box))
        except Exception:
            continue
    if not candidates:
        return False
    loc, box = random.choice(candidates)
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        box = await loc.bounding_box() or box
        await _trusted_page_tap(
            page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        )
        return True
    except Exception:
        return False


def _deals_required_for_wall(body: str) -> int:
    """Level 1 = 1 deal; level 2+ = 3 deals. Ignore footer 'complete 25 deals' copy."""
    s = (body or "").lower()
    if "level 3 deals" in s:
        return 3
    if "level 2 deals" in s:
        return 3
    if "level 1 deals" in s:
        return 1
    if "must complete 1 deal" in s or "next step: complete 1 deal" in s:
        return 1
    m = re.search(r"(?:must complete|next step:\s*complete)\s+([1-5])\s+deal", s)
    if m:
        return int(m.group(1))
    if "complete 3 deal" in s:
        return 3
    return 1


def _deal_wall_level_key(body: str) -> str:
    s = (body or "").lower()
    if "level 3 deals" in s:
        return "L3"
    if "level 2 deals" in s:
        return "L2"
    if "level 1 deals" in s:
        return "L1"
    if "must complete 1 deal" in s or "next step: complete 1 deal" in s:
        return "L1"
    if "complete 3 deal" in s or "complete three deal" in s:
        return "L2"
    return "LX"


async def _sync_deal_level_state(page, body: str) -> None:
    key = _deal_wall_level_key(body)
    ctx = page.context
    if getattr(ctx, "_krx_wall_level", None) == key:
        return
    ctx._krx_wall_level = key
    ctx._krx_level_cards_done = 0
    for frame in page.frames:
        try:
            await frame.evaluate(
                "() => { window.__krxDealKeys = {}; window.__krxLevelCardsDone = 0; }"
            )
        except Exception:
            continue


async def _get_level_cards_done(page) -> int:
    ctx = page.context
    py_done = int(getattr(ctx, "_krx_level_cards_done", 0) or 0)
    try:
        js_done = int(
            await page.evaluate(
                "() => parseInt(window.__krxLevelCardsDone, 10) || 0"
            )
        )
    except Exception:
        js_done = 0
    return max(py_done, js_done)


async def _increment_level_cards_done(page) -> None:
    ctx = page.context
    ctx._krx_level_cards_done = int(getattr(ctx, "_krx_level_cards_done", 0) or 0) + 1
    for frame in page.frames:
        try:
            await frame.evaluate(
                "() => { window.__krxLevelCardsDone = (window.__krxLevelCardsDone || 0) + 1; }"
            )
        except Exception:
            continue


async def _native_deal_card_click(page) -> bool:
    """Click deal-card CONTINUE → NO modal → offer popup tab → back to main."""
    import random

    clicked = False
    for frame in page.frames:
        try:
            target = await frame.evaluate(NATIVE_DEAL_CARD_CONTINUE_JS)
            if not target or target.get("x") is None:
                continue
            await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        try:
            locs = page.get_by_text("CONTINUE", exact=True)
            count = await locs.count()
            for i in range(count):
                loc = locs.nth(i)
                box = await loc.bounding_box()
                if not box or box["height"] < 14:
                    continue
                if box["y"] > 500:
                    continue
                await loc.scroll_into_view_if_needed(timeout=3000)
                box = await loc.bounding_box()
                if box:
                    await _trusted_page_tap(
                        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    clicked = True
                    break
        except Exception:
            pass

    if not clicked:
        return False

    await asyncio.sleep(2.0)
    await _native_deal_modal_no(page)
    await asyncio.sleep(1.0)
    await _native_deal_interstitial_step(page)
    await _wait_and_handle_offer_tabs(page, timeout_s=16.0)
    await _increment_level_cards_done(page)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await asyncio.sleep(random.uniform(1.5, 2.5))
    return True


async def _native_deal_wall_step(page, cfg: SmartFunnelConfig) -> bool:
    """
    Level-aware deal wall:
      Level 1 → 1 deal card → bottom CONTINUE → (survey answer) → Level 2
      Level 2 → 3 deal cards → bottom CONTINUE → conversion
    """
    body = await _retail_body_text(page)
    await _sync_deal_level_state(page, body)

    if any(
        k in body
        for k in ("emailed to you", "explore offers from our sponsors", "status emailed")
    ):
        return await _native_reward_status_optin_step(page, cfg)

    if await _native_deal_interstitial_step(page):
        return True

    required = _deals_required_for_wall(body)
    done = await _get_level_cards_done(page)

    if done < required:
        return await _native_deal_card_click(page)

    if done >= required:
        if await _native_deal_level_continue(page):
            page.context._krx_level_cards_done = 0
            for frame in page.frames:
                try:
                    await frame.evaluate("() => { window.__krxLevelCardsDone = 0; }")
                except Exception:
                    pass
            setattr(page.context, "_krx_wall_level", None)
            await asyncio.sleep(1.5)
            return True

    return await _native_deal_interstitial_step(page)


async def _native_deal_level_continue(page) -> bool:
    """Click enabled bottom CONTINUE to advance to next deal level."""
    import random

    for frame in page.frames:
        try:
            target = await frame.evaluate(NATIVE_DEAL_LEVEL_CONTINUE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(random.uniform(2.0, 3.5))
                await _native_deal_interstitial_step(page)
                return True
        except Exception:
            continue
    return False


async def _native_deal_continue_burst(
    page, cfg: Optional[SmartFunnelConfig] = None
) -> bool:
    """Backward-compatible entry → level-aware deal wall step."""
    return await _native_deal_wall_step(page, cfg or SmartFunnelConfig())


async def _native_screen_nudge(page, metrics: Dict[str, Any]) -> bool:
    """Playwright-native clicks when JS dispatch clicks are ignored (retail/deals)."""
    import random

    url = str(metrics.get("url") or "").lower()
    try:
        body = str(
            await page.evaluate("() => (document.body.innerText || '').slice(0, 2500).toLowerCase()")
        )
    except Exception:
        body = str(metrics.get("snippet") or "").lower()
    host = str(metrics.get("host") or "").lower()

    async def _try(labels: List[str]) -> bool:
        for label in labels:
            if await _native_click_text(page, label):
                await asyncio.sleep(0.8)
                return True
        return False

    async def _try_coord_yes_no() -> bool:
        try:
            loc = page.get_by_text("Question 1", exact=False).first
            if await loc.count() == 0:
                return False
            box = await loc.bounding_box()
            if not box:
                return False
            # Yes button sits below Q1 on the left (mobile layout).
            x = box["x"] + min(90, box["width"] * 0.25)
            y = box["y"] + box["height"] + 70
            await page.mouse.click(x, y)
            await asyncio.sleep(0.8)
            return True
        except Exception:
            return False

    if "retailproductsusa" in url or "retailproductsusa" in host:
        if await _native_retail_mouse_click(page):
            return True
        if "question 1" in body or "do you shop at target" in body:
            if await _try(random.sample(["Yes", "No"], 2)):
                return True
            return await _try_coord_yes_no()
        if "question 2" in body or "what would you do" in body:
            return await _try(["Use it myself", "Share with family"])
        if "question 3" in body or "activating your reward" in body or "how often" in body:
            return await _try(["Weekly", "Monthly", "Daily", "Often", "Rarely"])
        if "question 4" in body or "question 5" in body:
            if await _native_retail_mouse_click(page):
                return True
            return await _try(["Yes", "No", "Weekly", "Monthly", "Use it myself", "Share with family"])
        return await _try(["Get a Quick Start", "Get Started Now", "Continue"])

    if any(x in body for x in ("best match", "your cost:", "level 1 deals")) or "displayoptoffers" in host:
        if await _try(["CONTINUE", "Continue"]):
            return True
        return await _try(["My Deals", "View Deals", "Complete Deals"])

    if "confirm your email" in body or "your reward is waiting" in body:
        return await _try(["Continue"])

    return False


async def _final_conversion_gate(page, cfg: SmartFunnelConfig, deal_wall_seen: bool) -> bool:
    """Block false positives while survey loads or deal wall not yet visible."""
    body_l = await _retail_body_text(page)
    if await _survey_active_on_page(page) or _body_on_survey(body_l):
        return False
    if "finish your survey" in body_l:
        return False
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    metrics = await _metrics_from_page(page)
    if cfg.stop_at_deal_wall:
        return await _deal_wall_on_page(page) or _body_has_deal_wall(body_l, url)
    if not conversion_verified(metrics, cfg.min_deals, cfg.wait_until_conversion):
        return False
    if cfg.require_deal_wall_seen:
        wall = (
            deal_wall_seen
            or await _deal_wall_on_page(page)
            or _body_has_deal_wall(body_l, url)
        )
        if not wall:
            return False
    return True


async def _sync_funnel_frame_flags(page, min_deals: int) -> None:
    """Keep __krxPythonDeals / min deals in sync on main page and iframes."""
    script = """(minD) => {
      window.__krxMinDeals = minD;
      window.__krxPythonDeals = 1;
      if (typeof window.__krxDealKeys !== 'object') window.__krxDealKeys = {};
    }"""
    for frame in page.frames:
        try:
            await frame.evaluate(script, min_deals)
        except Exception:
            continue


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
    stuck_at_deals = 0
    stuck_on_survey = 0
    stuck_deal_wall = 0
    prev_url_deals = 0
    deal_wall_seen = False
    prev_fp = await _page_fingerprint(page)

    async def _emit(phase: str, status: str = "running", extra: Optional[Dict] = None) -> None:
        nonlocal last_phase
        phase_changed = phase != last_phase
        last_phase = phase
        if phase_changed and cfg.visual_pause_ms > 0:
            await asyncio.sleep(cfg.visual_pause_ms / 1000.0)
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
        if ev.get("url") and not ev.get("page_url"):
            ev["page_url"] = ev["url"]
        try:
            await on_step_progress(ev)
        except Exception:
            pass

    min_d = max(1, min(5, int(cfg.min_deals or 2)))

    try:
        await page.evaluate(
            "() => { window.__krxDealsDone = 0; window.__krxDealKeys = {}; "
            "window.__krxConversionSignal = false; window.__krxDone = false; "
            "window.__krxPythonDeals = 1; }"
        )
        await _sync_funnel_frame_flags(page, min_d)
    except Exception:
        pass

    await _emit("init", "start")
    await _install_offer_popup_handler(page)

    for iteration in range(1, cfg.max_iterations + 1):
        executed = iteration
        min_d = max(1, int(cfg.min_deals or 2))
        try:
            await _sync_funnel_frame_flags(page, min_d)
        except Exception:
            pass
        metrics = await _metrics_from_page(page)
        deals = int(metrics.get("url_deals") or 0)
        if deals > prev_url_deals:
            prev_url_deals = deals
            try:
                for frame in page.frames:
                    try:
                        await frame.evaluate("() => { window.__krxDealKeys = {}; }")
                    except Exception:
                        continue
            except Exception:
                pass
        try:
            await _recover_off_policy_page(page)
        except Exception:
            pass
        body_l = await _retail_body_text(page)
        survey_active = await _survey_active_on_page(page)
        if survey_active or _body_on_survey(body_l):
            deal_wall_seen = False
            try:
                if await _page_has_text(page, "what kind of debt", "select all that apply"):
                    await _native_debt_multiselect_step(page)
                await _native_survey_pick(page, row)
            except Exception:
                pass
        elif await _deal_wall_on_page(page) or _body_has_deal_wall(body_l, str(metrics.get("url") or "")):
            deal_wall_seen = True

        if await _page_has_text(
            page,
            "question 1",
            "question 2",
            "question 3",
            "question 4",
            "question 5",
            "do you shop at target",
            "how often do you shop online",
        ):
            try:
                await _native_retail_mouse_click(page)
            except Exception:
                pass

        # Task 1: stop as soon as LEVEL 1 DEALS is visibly on screen (ignore URL deal markers)
        if cfg.stop_at_deal_wall and deal_wall_seen and not survey_active and not _body_on_survey(body_l):
            await asyncio.sleep(1.0)
            if await _deal_wall_on_page(page) and not await _survey_active_on_page(page):
                await _emit("deals", "ok", {"deals": deals, "url": metrics.get("url", ""), "stop": "deal_wall"})
                try:
                    final_url = page.url or metrics.get("url", "")
                except Exception:
                    final_url = metrics.get("url", "")
                return {
                    "status": "ok",
                    "executed_steps": executed,
                    "smart_funnel": True,
                    "deals_done": deals,
                    "url_deals": deals,
                    "conversion_signal": False,
                    "deal_wall_reached": True,
                    "final_url": final_url,
                    "pattern": cfg.normalized_pattern(),
                }

        if deals >= min_d - 1 and deals < min_d:
            stuck_at_deals += 1
            try:
                await page.evaluate(THIRD_DEAL_RECOVERY)
                await _native_click_text(page, "CONTINUE")
                await _native_click_text(page, "Continue")
                await _native_screen_nudge(page, metrics)
            except Exception:
                pass
            if stuck_at_deals >= 6 and stuck_at_deals % 3 == 0:
                try:
                    await page.evaluate(THIRD_DEAL_RECOVERY)
                except Exception:
                    pass
        else:
            stuck_at_deals = 0

        if not cfg.stop_at_deal_wall and _conversion_ready(
            metrics, cfg, deal_wall_seen=deal_wall_seen, body=body_l, survey_active=survey_active
        ):
            if not await _final_conversion_gate(page, cfg, deal_wall_seen):
                prev_fp = await _page_fingerprint(page)
                await _condition_wait(page, prev_fp, cfg, time.monotonic() + cfg.loop_interval_ms / 1000.0)
                continue
            await _emit("conversion", "ok", {"deals": deals, "url": metrics.get("url", "")})
            try:
                final_url = page.url or metrics.get("url", "")
            except Exception:
                final_url = metrics.get("url", "")
            return {
                "status": "ok",
                "executed_steps": executed,
                "smart_funnel": True,
                "deals_done": deals,
                "url_deals": deals,
                "conversion_signal": True,
                "final_url": final_url,
                "pattern": cfg.normalized_pattern(),
            }

        need_third_deal = deals >= min_d - 1 and deals < min_d

        # Retail / email on retail host — native clicks before JS handler
        if not need_third_deal:
            try:
                url_pre = str(metrics.get("url") or "").lower()
                host_pre = str(metrics.get("host") or "").lower()
                body_pre = await _retail_body_text(page)
                if "retailproductsusa" in url_pre or "retailproductsusa" in host_pre:
                    if any(q in body_pre for q in ("question 1", "question 2", "question 3", "question 4", "question 5")):
                        await _native_retail_mouse_click(page)
                    elif any(k in body_pre for k in ("your reward is waiting", "confirm your email", "sign up or resume")):
                        await _native_email_step(page, row or {})
                if any(k in body_pre for k in ("first name", "date of birth", "last name")) or "lfirstname" in url_pre:
                    await _native_form_step(page, row or {})
            except Exception as e:
                logger.debug("smart_funnel retail pre-click: %s", e)

        # Main brain — skip survey/form handler when 3rd deal still needed
        if not need_third_deal:
            try:
                await _evaluate_all_frames(page, handler)
            except Exception as e:
                logger.debug("smart_funnel handler evaluate: %s", e)
        else:
            try:
                await _evaluate_all_frames(page, THIRD_DEAL_RECOVERY)
                await _evaluate_all_frames(page, DEAL_SCRIPT)
                await _native_deal_wall_step(page, cfg)
                await _native_screen_nudge(page, metrics)
            except Exception:
                pass

        # Deal push every iteration
        try:
            await _evaluate_all_frames(page, DEAL_SCRIPT)
            await _evaluate_all_frames(page, MODAL_NO_SCRIPT)
            await _evaluate_all_frames(page, CONVERSION_SCRIPT)
        except Exception:
            pass

        metrics = await _metrics_from_page(page)
        body_l = await _retail_body_text(page)
        survey_active = await _survey_active_on_page(page)
        if survey_active or _body_on_survey(body_l):
            deal_wall_seen = False
        elif await _deal_wall_on_page(page) or _body_has_deal_wall(body_l, str(metrics.get("url") or "")):
            deal_wall_seen = True

        if cfg.stop_at_deal_wall and deal_wall_seen and not survey_active and not _body_on_survey(body_l):
            await asyncio.sleep(1.0)
            if await _deal_wall_on_page(page) and not await _survey_active_on_page(page):
                deals = int(metrics.get("url_deals") or 0)
                await _emit("deals", "ok", {"deals": deals, "url": metrics.get("url", ""), "stop": "deal_wall"})
                try:
                    final_url = page.url or metrics.get("url", "")
                except Exception:
                    final_url = metrics.get("url", "")
                return {
                    "status": "ok",
                    "executed_steps": executed,
                    "smart_funnel": True,
                    "deals_done": deals,
                    "url_deals": deals,
                    "conversion_signal": False,
                    "deal_wall_reached": True,
                    "final_url": final_url,
                    "pattern": cfg.normalized_pattern(),
                }

        if not cfg.stop_at_deal_wall and _conversion_ready(
            metrics, cfg, deal_wall_seen=deal_wall_seen, body=body_l, survey_active=survey_active
        ):
            if not await _final_conversion_gate(page, cfg, deal_wall_seen):
                prev_fp = await _page_fingerprint(page)
                await _condition_wait(page, prev_fp, cfg, time.monotonic() + cfg.loop_interval_ms / 1000.0)
                continue
            deals = int(metrics.get("url_deals") or 0)
            await _emit("conversion", "ok", {"deals": deals, "url": metrics.get("url", "")})
            try:
                final_url = page.url or metrics.get("url", "")
            except Exception:
                final_url = metrics.get("url", "")
            return {
                "status": "ok",
                "executed_steps": executed,
                "smart_funnel": True,
                "deals_done": deals,
                "url_deals": deals,
                "conversion_signal": True,
                "final_url": final_url,
                "pattern": cfg.normalized_pattern(),
            }

        # Retail Q1–Q5 — force native tap every loop (JS clicks ignored on this offer)
        try:
            url_l = str(metrics.get("url") or "").lower()
            if "retailproductsusa" in url_l and any(
                q in body_l for q in ("question 1", "question 2", "question 3", "question 4", "question 5")
            ):
                await _native_screen_nudge(page, metrics)
        except Exception as e:
            logger.debug("smart_funnel retail native: %s", e)

        phase = _guess_phase(metrics.get("snippet", ""), metrics.get("url", ""), body_l)
        if any(k in body_l for k in ("your reward is waiting", "confirm your email", "sign up or resume")):
            phase = "email"
        if any(k in body_l for k in ("emailed to you", "explore offers from our sponsors", "status emailed")):
            phase = "email"
        if survey_active or _body_on_survey(body_l):
            phase = "survey"
        on_survey = phase == "survey" or survey_active or _body_on_survey(body_l)
        if phase == "form":
            try:
                await _native_form_step(page, row or {})
            except Exception:
                pass
        if phase == "email":
            try:
                if any(
                    k in body_l
                    for k in ("emailed to you", "explore offers from our sponsors", "status emailed")
                ):
                    await _native_reward_status_optin_step(page, cfg)
                else:
                    await _native_email_step(page, row or {})
            except Exception:
                pass
        if on_survey:
            stuck_on_survey += 1
            try:
                if await _page_has_text(page, "what kind of debt", "select all that apply"):
                    await _native_debt_multiselect_step(page)
                await _native_survey_pick(page, row)
                if stuck_on_survey >= 2:
                    await _click_largest_survey_button(page)
                if stuck_on_survey >= 3:
                    await _click_survey_zone_answer(page)
            except Exception:
                pass
        else:
            stuck_on_survey = 0
        on_deal_flow = (
            await _deal_wall_on_page(page)
            or (
                phase in ("deals", "offers")
                and not on_survey
                and (
                    _body_has_deal_wall(body_l, str(metrics.get("url") or ""))
                    or "eward4spot" in str(metrics.get("url") or "").lower()
                    or "displayoptoffers" in str(metrics.get("url") or "").lower()
                )
            )
        )
        if on_deal_flow and not on_survey:
            stuck_deal_wall += 1
            if stuck_deal_wall >= 8:
                try:
                    await page.evaluate(
                        "() => { window.__krxDealKeys = {}; window.__krxLevelCardsDone = 0; "
                        "try { window.scrollBy(0, 450); } catch(e) {} }"
                    )
                    setattr(page.context, "_krx_wall_level", None)
                except Exception:
                    pass
            try:
                await _native_deal_wall_step(page, cfg)
            except Exception:
                pass
        elif phase in ("deals", "offers") and not on_survey:
            try:
                await _native_deal_wall_step(page, cfg)
            except Exception:
                pass
        else:
            stuck_deal_wall = 0
        if phase == "retail" and iteration == 1:
            last_phase = ""  # force emit retail on first pass
        await _emit(phase, "running", {"deals": metrics.get("url_deals", 0), "url": metrics.get("url", "")})

        cur_fp = await _page_fingerprint(page)
        if cur_fp.get("hash") == prev_fp.get("hash") and cur_fp.get("url") == prev_fp.get("url"):
            stuck_same_screen += 1
            if stuck_same_screen >= 3 and stuck_same_screen % 3 == 0:
                try:
                    await page.evaluate("window.scrollBy(0, 350)")
                except Exception:
                    pass
            if phase == "retail" and stuck_same_screen >= 3:
                try:
                    if any(k in body_l for k in ("your reward is waiting", "confirm your email", "sign up or resume")):
                        await _native_email_step(page, row or {})
                    else:
                        await _native_retail_mouse_click(page)
                        await _native_screen_nudge(page, metrics)
                except Exception:
                    pass
            if phase == "survey" and stuck_same_screen >= 3:
                try:
                    await _click_largest_survey_button(page)
                    await _generic_visible_answer_click(page)
                except Exception:
                    pass
            if phase == "form" and stuck_same_screen >= 3:
                try:
                    await _native_form_step(page, row or {})
                except Exception:
                    pass
            if phase == "retail" and stuck_same_screen >= 6 and stuck_same_screen % 2 == 0:
                try:
                    await page.evaluate(RETAIL_PROGRESS_SCRIPT)
                except Exception:
                    pass
            if "bckmfr" in (metrics.get("url") or "").lower():
                try:
                    await page.evaluate(RETAIL_REENTRY_SCRIPT)
                except Exception:
                    pass
        else:
            stuck_same_screen = 0
            prev_fp = cur_fp

        deadline = time.monotonic() + cfg.loop_interval_ms / 1000.0
        await _condition_wait(page, prev_fp, cfg, deadline)

        if stuck_same_screen >= 5 and phase in ("deals", "offers"):
            try:
                await page.evaluate(
                    "() => { window.__krxDealKeys = {}; try { window.scrollBy(0, 400); } catch(e) {} }"
                )
                if deals >= min_d - 1 and deals < min_d:
                    await page.evaluate(THIRD_DEAL_RECOVERY)
            except Exception:
                pass

        if stuck_same_screen >= int(cfg.max_idle_before_nudge_ms / max(cfg.loop_interval_ms, 1)):
            try:
                if on_survey:
                    await _click_largest_survey_button(page)
                elif await _deal_wall_on_page(page):
                    await _native_deal_wall_step(page, cfg)
            except Exception:
                pass
            stuck_same_screen = 0

    # Safety cap reached — report URL-authoritative deal count only
    metrics = await _metrics_from_page(page)
    deals = int(metrics.get("url_deals") or 0)
    verified = conversion_verified(metrics, cfg.min_deals, cfg.wait_until_conversion)
    try:
        final_url = page.url or metrics.get("url", "")
    except Exception:
        final_url = metrics.get("url", "")
    return {
        "status": "ok" if verified else "incomplete",
        "executed_steps": executed,
        "smart_funnel": True,
        "deals_done": deals,
        "url_deals": deals,
        "conversion_signal": verified,
        "final_url": final_url,
        "pattern": cfg.normalized_pattern(),
        "error": None if verified else f"Max iterations ({cfg.max_iterations}) without {cfg.min_deals} URL deal markers",
    }


def _guess_phase(snippet: str, url: str, body: str = "") -> str:
    s = (body or snippet or "").lower()
    u = (url or "").lower()
    on_retail_host = "retailproductsusa" in u

    if _body_on_survey(s):
        return "survey"
    if "confirm your email" in s or "sign up or resume" in s or "your reward is waiting" in s:
        return "email"
    if "emailed to you" in s or "explore offers from our sponsors" in s:
        return "email"
    if "date of birth" in s or "first name" in s or "lfirstname" in u:
        return "form"
    if on_retail_host and "question" in s:
        return "retail"
    if "question" in s or "how often" in s or "homeowner" in s:
        return "survey"
    if not on_retail_host and (
        "best match" in s
        or "your cost:" in s
        or "level 1 deals" in s
        or "level 2 deals" in s
        or "level 3 deals" in s
        or "next step: complete" in s
    ):
        return "deals"
    if "retailproductsusa" in u:
        return "retail"
    if "displayoptoffers" in u or "uplevelrewards" in u or "levelrewards" in u or "eward4spot" in u:
        if _body_on_survey(s):
            return "survey"
        if "level 1 deals" in s or "best match" in s:
            return "deals"
        return "offers"
    return "flow"
