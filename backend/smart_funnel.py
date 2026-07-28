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

# Deal wall: click CONTINUE on each offer card; count comes from URL BVA/BVC/BVE only.
DEAL_SCRIPT = r"""(function(){window.__krxDealsDone=window.__krxDealsDone||0;window.__krxDealKeys=window.__krxDealKeys||{};var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var bt=(document.body.innerText||'').toLowerCase();var host=(location.host||'').toLowerCase();function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function btns(){return Array.from(document.querySelectorAll('button,a,div,span')).filter(vis);}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}if(/do you already have/i.test(bt)){var no=btns().find(function(e){var t=txt(e).toUpperCase();return t==='NO'||t==='NO!';});if(no){rf(no);return;}}var onDealWall=/uplevelrewards|levelrewards|rewardsgiant|displayoptoffers/i.test(host)||/level\s*\d+\s*deals|best match for you|next step:\s*complete|your cost:\s*\$/i.test(bt);var contBtns=btns().filter(function(e){var t=txt(e);return t==='CONTINUE'||t==='Continue';});if(!onDealWall&&contBtns.length<1)return;for(var i=0;i<contBtns.length;i++){var b=contBtns[i];var card='';try{var p=b.closest('div,section,article,li');if(p)card=(p.innerText||'').slice(0,80);}catch(e){}var key=card+'|'+Math.round(b.getBoundingClientRect().top)+'|'+Math.round(b.getBoundingClientRect().left);if(window.__krxDealKeys[key])continue;window.__krxDealKeys[key]=1;rf(b);return;}})();"""

MODAL_NO_SCRIPT = r"""(function(){var bt=(document.body.innerText||'').toLowerCase();if(!/do you already have/i.test(bt))return;var no=Array.from(document.querySelectorAll('button,a,div,span')).find(function(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var t=((e.innerText||e.textContent||'')+'').trim().toUpperCase();return t==='NO'||t==='NO!';});if(no){try{no.scrollIntoView({block:'center'});no.click();}catch(e){}}})();"""

CONVERSION_SCRIPT = r"""(function(){var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;window.__krxDealsDone=n;var minD=parseInt(window.__krxMinDeals,10);if(isNaN(minD)||minD<1)minD=2;window.__krxConversionSignal=(n>=minD);window.__krxDone=window.__krxConversionSignal;})();"""

THIRD_DEAL_RECOVERY = r"""(function(){var u=location.href;var n=0;if(/BVA=True/i.test(u))n++;if(/BVB=True/i.test(u))n++;if(/BVC=True/i.test(u))n++;if(/BVD=True/i.test(u))n++;if(/BVE=True/i.test(u))n++;var minD=parseInt(window.__krxMinDeals,10);if(isNaN(minD)||minD<1)minD=3;if(n>=minD)return;if(n<minD-1)return;window.__krxDealKeys={};function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function btns(){return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}var nav=btns().find(function(e){return /my deals|view deals|complete deals|see deals|reward status|start earning|complete\s*1\s*deal/i.test(txt(e));});if(nav){rf(nav);return;}try{window.scrollTo(0,0);window.scrollBy(0,450);}catch(e){}var cont=btns().filter(function(e){return /^continue$/i.test(txt(e));});for(var i=0;i<cont.length;i++){rf(cont[i]);return;}var a=document.querySelector('a[href*="uplevelrewards"],a[href*="levelrewards"],a[href*="displayoptoffers"]');if(a&&vis(a)){rf(a);return;}})();"""

RETAIL_REENTRY_SCRIPT = r"""(function(){if(!/retailproductsusa|bckmfr=1|default\.aspx/i.test(location.href))return;function vis(e){var s=getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden'&&e.getBoundingClientRect().width>20;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}var b=Array.from(document.querySelectorAll('button,a,div,span')).filter(vis);var c=b.find(function(e){return /get a quick start|get started|claim my|start earning|continue|next/i.test(txt(e).toLowerCase());});if(c){try{c.click();}catch(e){}}})();"""

RETAIL_PROGRESS_SCRIPT = r"""(function(){if(!/retailproductsusa/i.test(location.host))return;function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;var r=e.getBoundingClientRect();return r.width>20&&r.height>10;}function txt(e){return ((e.innerText||e.textContent||'')+'').trim();}function rf(el){if(!el)return;try{el.scrollIntoView({block:'center'});el.click();}catch(e){}}var b=Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);var yn=b.filter(function(e){var t=txt(e).toLowerCase();return t==='yes'||t==='no';});if(yn.length){rf(yn[Math.floor(Math.random()*yn.length)]);return;}var wk=b.filter(function(e){var t=txt(e).toLowerCase();return t==='weekly'||t==='monthly';});if(wk.length){rf(wk[0]);return;}var cta=b.find(function(e){var t=txt(e).toLowerCase();return /get a quick start|get started|claim my|start earning|activating|continue|next|use it myself|share with family/i.test(t);});if(cta){rf(cta);return;}})();"""

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
  function surveyAnswers(els, body) {
    return els.filter(function (e) {
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
      var t = txt(e).toLowerCase();
      return t === 'yes' || t === 'no';
    });
  } else if (/question 2|what would you do/.test(body)) {
    targets = els.filter(function (e) {
      var t = txt(e).toLowerCase();
      return t.indexOf('use it myself') >= 0 || t.indexOf('share with family') >= 0;
    });
  } else if (/question 3|how often|activating your reward/.test(body)) {
    targets = els.filter(function (e) {
      var t = txt(e).toLowerCase();
      return t === 'weekly' || t === 'monthly' || t === 'daily' || t === 'rarely' || t === 'often';
    });
  } else if (/question 4/.test(body)) {
    targets = surveyAnswers(els, body);
  } else if (/question 5/.test(body)) {
    targets = surveyAnswers(els, body);
  } else {
    targets = els.filter(function (e) {
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
                  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button],label')).filter(vis);
                  var el = els.find(function (e) {
                    var t = txt(e).toLowerCase();
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
                await page.mouse.click(float(coords["x"]), float(coords["y"]))
                await asyncio.sleep(0.8)
                return True
        except Exception:
            continue
    return False


async def _native_click_text(page, text: str, timeout_ms: int = 4000) -> bool:
    """Native click helper — mouse-at-center first, then locator fallback."""
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
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
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
        for role in ("button", "link"):
            try:
                loc = frame.get_by_role(role, name=text).first
                if await loc.count() > 0:
                    box = await loc.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        await asyncio.sleep(0.8)
                        return True
                    await loc.click(timeout=timeout_ms, force=True)
                    return True
            except Exception:
                continue
    return False


async def _retail_body_text(page) -> str:
    try:
        return str(
            await page.evaluate("() => (document.body.innerText || '').slice(0, 3000).toLowerCase()")
        )
    except Exception:
        return ""


async def _native_retail_mouse_click(page) -> bool:
    """Retail survey click — Playwright role locators first, then coords across all frames."""
    body = await _retail_body_text(page)
    if not body or "retailproductsusa" not in (page.url or "").lower():
        if "retailproductsusa" not in body:
            return False

    # Email interstitial on retail host — click Continue, not survey answers
    if "your reward is waiting" in body or "confirm your email" in body or "sign up or resume" in body:
        return await _native_click_text(page, "Continue")

    labels: List[str] = []
    if "question 1" in body or "do you shop at target" in body:
        labels = ["Yes", "No"]
    elif "question 2" in body or "what would you do" in body:
        labels = ["Use it myself", "Share with family"]
    elif "question 3" in body or "how often" in body:
        labels = ["Weekly", "Monthly", "Daily", "Often", "Rarely"]
    elif "question 4" in body or "question 5" in body:
        labels = ["Yes", "No", "Weekly", "Monthly", "Use it myself", "Share with family"]
    else:
        return False

    import random

    for label in random.sample(labels, len(labels)):
        for frame in page.frames:
            try:
                loc = frame.get_by_role("button", name=label).first
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    box = await loc.bounding_box()
                    if box:
                        await page.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        await asyncio.sleep(1.2)
                        logger.debug("retail role click: %s", label)
                        return True
                    await loc.click(timeout=4000, force=True)
                    await asyncio.sleep(1.2)
                    return True
            except Exception:
                continue

    for frame in page.frames:
        try:
            target = await frame.evaluate(RETAIL_MOUSE_TARGET_JS)
            if target and target.get("x") is not None:
                await page.mouse.click(float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                logger.debug("retail mouse click: %s", target.get("label"))
                return True
        except Exception:
            continue

    if "question 1" in body or "do you shop at target" in body:
        x, y = RETAIL_Q1_FALLBACK_COORDS
        await page.mouse.click(float(x), float(y))
        await asyncio.sleep(1.2)
        logger.debug("retail Q1 fallback coord @ %s,%s", x, y)
        return True
    return False


async def _native_email_step(page, row: Dict[str, Any]) -> bool:
    """Fill email + Continue on retail email interstitial."""
    body = await _retail_body_text(page)
    if not any(k in body for k in ("your reward is waiting", "confirm your email", "sign up or resume")):
        return False
    email = str(row.get("email") or row.get("Email") or "").strip()
    if email:
        for frame in page.frames:
            try:
                loc = frame.locator('input[type="email"], input#email, input[name*="email" i]').first
                if await loc.count() > 0:
                    await loc.fill(email, timeout=4000)
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
  window.__krxDealKeys = {};
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
  var b = cont[0];
  try { b.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = b.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, count: cont.length };
}"""


async def _native_deal_continue_burst(page) -> bool:
    """Click next CONTINUE on deal wall via mouse coords (all frames)."""
    for frame in page.frames:
        try:
            target = await frame.evaluate(DEAL_CONTINUE_BURST_JS)
            if target and target.get("x") is not None:
                await page.mouse.click(float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                return True
        except Exception:
            continue
    return await _native_click_text(page, "CONTINUE") or await _native_click_text(page, "Continue")


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
            "window.__krxConversionSignal = false; window.__krxDone = false; }"
        )
        await page.evaluate(
            "(minD) => { window.__krxMinDeals = minD; }",
            min_d,
        )
    except Exception:
        pass

    await _emit("init", "start")

    for iteration in range(1, cfg.max_iterations + 1):
        executed = iteration
        min_d = max(1, int(cfg.min_deals or 2))
        try:
            await page.evaluate(
                "(minD) => { window.__krxMinDeals = minD; "
                "if (typeof window.__krxDealKeys !== 'object') window.__krxDealKeys = {}; }",
                min_d,
            )
        except Exception:
            pass
        metrics = await _metrics_from_page(page)
        deals = int(metrics.get("url_deals") or 0)

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

        if conversion_verified(metrics, min_d, cfg.wait_until_conversion):
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
            except Exception as e:
                logger.debug("smart_funnel retail pre-click: %s", e)

        # Main brain — skip survey/form handler when 3rd deal still needed
        if not need_third_deal:
            try:
                await page.evaluate(handler)
            except Exception as e:
                logger.debug("smart_funnel handler evaluate: %s", e)
        else:
            try:
                await page.evaluate(THIRD_DEAL_RECOVERY)
                await page.evaluate(DEAL_SCRIPT)
                await _native_deal_continue_burst(page)
                await _native_screen_nudge(page, metrics)
            except Exception:
                pass

        # Deal push every iteration
        try:
            await page.evaluate(DEAL_SCRIPT)
            await page.evaluate(MODAL_NO_SCRIPT)
            await page.evaluate(CONVERSION_SCRIPT)
        except Exception:
            pass

        metrics = await _metrics_from_page(page)
        if conversion_verified(metrics, min_d, cfg.wait_until_conversion):
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

        body_l = await _retail_body_text(page)
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
                    await _native_screen_nudge(page, metrics)
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
                await page.evaluate(
                    "(function(){var b=document.querySelector('button,a,div,span');"
                    "if(b){try{b.click();}catch(e){}}})();"
                )
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

    if "confirm your email" in s or "sign up or resume" in s or "your reward is waiting" in s:
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
        or "next step: complete" in s
    ):
        return "deals"
    if "retailproductsusa" in u:
        return "retail"
    if "displayoptoffers" in u or "uplevelrewards" in u or "levelrewards" in u:
        return "offers"
    return "flow"
