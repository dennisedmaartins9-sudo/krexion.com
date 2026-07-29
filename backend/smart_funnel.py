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
import hashlib
import logging
import os
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

MODAL_NO_SCRIPT = r"""(function(){var bt=(document.body.innerText||'').toLowerCase();if(!/do you already have/i.test(bt))return;function vis(e){var s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden'||s.pointerEvents==='none')return false;var r=e.getBoundingClientRect();return r.width>=80&&r.height>=28&&r.top>=0&&r.top<innerHeight;}function txt(e){return ((e.innerText||e.textContent||e.value||'')+'').trim();}function isNo(e){var t=txt(e).toUpperCase();return t==='NO'||t==='NO!';}function clickEl(e){try{e.scrollIntoView({block:'center'});}catch(x){}try{e.focus();}catch(x){}try{e.click();return true;}catch(x){}try{e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));return true;}catch(x2){}return false;}var roots=Array.from(document.querySelectorAll('div,section,article,dialog,[role=dialog]')).filter(function(el){var t=(el.innerText||'').slice(0,800).toLowerCase();return /do you already have/i.test(t)&&/\byes\b/i.test(t)&&/\bno\b/i.test(t);});roots.sort(function(a,b){return a.getBoundingClientRect().width*a.getBoundingClientRect().height-b.getBoundingClientRect().width*b.getBoundingClientRect().height;});var root=roots.length?roots[roots.length-1]:document.body;var pool=Array.from(root.querySelectorAll('button,a,input[type=button],input[type=submit],div,span,[role=button]')).filter(function(e){return vis(e)&&isNo(e);});if(!pool.length)return;pool.sort(function(a,b){return b.getBoundingClientRect().top-a.getBoundingClientRect().top;});clickEl(pool[0]);})();"""

MODAL_NO_DIRECT_CLICK_JS = r"""() => {
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/do you already have/i.test(bt)) return { ok: false, reason: 'no_modal' };
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 80 && r.height >= 28 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function isNo(e) { var t = txt(e).toUpperCase(); return t === 'NO' || t === 'NO!'; }
  function isYes(e) { var t = txt(e).toUpperCase(); return t === 'YES' || t === 'YES!'; }
  function clickEl(el) {
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
    try { el.focus(); } catch (e) {}
    try { el.click(); return true; } catch (e) {}
    try {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      return true;
    } catch (e2) {}
    return false;
  }
  var roots = Array.from(document.querySelectorAll('div,section,article,dialog,[role=dialog]')).filter(function (el) {
    var t = (el.innerText || '').slice(0, 900).toLowerCase();
    return /do you already have/i.test(t) && /\byes\b/i.test(t) && /\bno\b/i.test(t);
  });
  roots.sort(function (a, b) {
    return a.getBoundingClientRect().width * a.getBoundingClientRect().height
      - b.getBoundingClientRect().width * b.getBoundingClientRect().height;
  });
  var root = roots.length ? roots[roots.length - 1] : document.body;
  var yes = Array.from(root.querySelectorAll('button,a,input[type=button],input[type=submit],div,span,[role=button]')).filter(function (e) {
    return vis(e) && isYes(e);
  });
  yes.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  var pool = Array.from(root.querySelectorAll('button,a,input[type=button],input[type=submit],div,span,[role=button]')).filter(function (e) {
    if (!vis(e) || !isNo(e)) return false;
    var tag = (e.tagName || '').toUpperCase();
    if (tag === 'SPAN' || tag === 'DIV') {
      var r = e.getBoundingClientRect();
      if (r.width < 100 || r.height < 32) return false;
    }
    return true;
  });
  if (yes.length && pool.length) {
    var yr = yes[0].getBoundingClientRect();
    var below = pool.filter(function (e) {
      var r = e.getBoundingClientRect();
      return r.top >= yr.top + 8;
    });
    below.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
    if (below.length && clickEl(below[0])) {
      var br = below[0].getBoundingClientRect();
      return { ok: true, method: 'below_yes', x: br.left + br.width / 2, y: br.top + br.height / 2, label: txt(below[0]) };
    }
  }
  pool.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  if (pool.length && clickEl(pool[0])) {
    var r = pool[0].getBoundingClientRect();
    return { ok: true, method: 'lowest_no', x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(pool[0]) };
  }
  return { ok: false, reason: 'no_button' };
}"""

MODAL_NO_BELOW_YES_JS = r"""() => {
  if (!/do you already have/i.test(document.body.innerText || '')) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 50 && r.height >= 24 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function clickTarget(el) {
    if (!el) return null;
    var cur = el;
    for (var i = 0; i < 5; i++) {
      if (!cur) break;
      var tag = (cur.tagName || '').toUpperCase();
      if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT') return cur;
      if (cur.getAttribute && cur.getAttribute('role') === 'button') return cur;
      if (cur.onclick || (cur.getAttribute && cur.getAttribute('onclick'))) return cur;
      var s = getComputedStyle(cur);
      if (s.cursor === 'pointer' && cur.getBoundingClientRect().height >= 28) return cur;
      cur = cur.parentElement;
    }
    return el;
  }
  function fireClick(el) {
    if (!el) return false;
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
    var target = clickTarget(el);
    try { target.focus(); } catch (e) {}
    try { target.click(); return true; } catch (e) {}
    try {
      ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function (t) {
        target.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
      });
      return true;
    } catch (e2) {}
    return false;
  }
  var yes = [], no = [];
  Array.from(document.querySelectorAll(
    'button,a,input[type=button],input[type=submit],div,span,[role=button],label'
  )).forEach(function (e) {
    if (!vis(e)) return;
    var t = txt(e).toUpperCase();
    if (t === 'YES' || t === 'YES!') yes.push(e);
    if (t === 'NO' || t === 'NO!') no.push(e);
  });
  yes.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  no.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  var yesEl = yes[0] || null;
  var noEl = null;
  if (yesEl && no.length) {
    var yt = yesEl.getBoundingClientRect().top;
    noEl = no.find(function (e) { return e.getBoundingClientRect().top >= yt + 5; }) || no[no.length - 1];
  } else if (no.length) {
    noEl = no[no.length - 1];
  }
  if (noEl) {
    fireClick(noEl);
    var nr = clickTarget(noEl).getBoundingClientRect();
    return { x: nr.left + nr.width / 2, y: nr.top + nr.height / 2, method: 'no_element', clicked: true };
  }
  if (yesEl) {
    var yr = yesEl.getBoundingClientRect();
    return {
      x: yr.left + yr.width / 2,
      y: yr.bottom + Math.max(yr.height * 0.45, 40),
      method: 'below_yes_guess',
      clicked: false,
    };
  }
  return null;
}"""

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
    fast_survey: bool = True  # shorter pauses between survey answers only
    survey_settle_ms: int = 0  # ms after each survey click (0 = instant in fast mode)
    survey_loop_interval_ms: int = 0  # no idle wait between survey answers
    survey_idle_poll_ms: int = 12  # DOM poll during survey
    survey_burst_clicks: int = 10  # rapid answers per loop while question visible
    survey_skip_chance: float = 0.0  # RUT jobs set 0.35 — once per visit roll
    form_type_delay_ms: int = 50  # character typing speed — keep human-normal
    form_loop_interval_ms: int = 900  # do not rush form phase like survey
    require_deal_wall_seen: bool = False  # wait for LEVEL 1 DEALS before conversion
    stop_at_deal_wall: bool = False  # Task 1: success when LEVEL 1 DEALS visible (ignore URL deals)
    pause_at_deal_wall: bool = False  # reach deal page then stop — no auto deal clicks (guided setup)
    guided_deal_step: int = 0  # steps per deal: 1=CONTINUE … 5=BACK TO DEALS, 6=footer, 7=ALERT
    guided_deal_cycles: int = 3  # L1: repeat steps 1–5 on different deals
    guided_deal_l3_cycles: int = 3  # L3: same 5-step cycle after ALERT Continue

    def normalized_pattern(self) -> str:
        p = (self.pattern or "auto").strip().lower()
        return p if p in SMART_FUNNEL_PATTERNS else "auto"


def _cfg_stop_at_deal_wall(cfg: SmartFunnelConfig) -> bool:
    """True when funnel should exit once LEVEL 1 DEALS is visible (no auto deal clicks if pause)."""
    return bool(cfg.stop_at_deal_wall or cfg.pause_at_deal_wall)


def _deal_user_flow_config(cfg: SmartFunnelConfig) -> SmartFunnelConfig:
    """
    User SS deal flow (steps 1–8) — auto mode uses same steps as guided:
      L1: 3× (CONTINUE→NO→START DEAL→main tab→BACK TO DEALS) → footer CONTINUE → ALERT Continue
      L3: 3× same cycle → conversion
    """
    if cfg.pause_at_deal_wall and int(cfg.guided_deal_step or 0) > 0:
        return cfg
    return SmartFunnelConfig(
        pattern=cfg.pattern,
        min_deals=cfg.min_deals,
        wait_until_conversion=cfg.wait_until_conversion,
        loop_interval_ms=cfg.loop_interval_ms,
        idle_poll_ms=cfg.idle_poll_ms,
        max_idle_before_nudge_ms=cfg.max_idle_before_nudge_ms,
        max_iterations=cfg.max_iterations,
        sms_answer=cfg.sms_answer,
        email_optin_answer=cfg.email_optin_answer,
        visual_pause_ms=cfg.visual_pause_ms,
        fast_survey=cfg.fast_survey,
        survey_settle_ms=cfg.survey_settle_ms,
        survey_loop_interval_ms=cfg.survey_loop_interval_ms,
        survey_idle_poll_ms=cfg.survey_idle_poll_ms,
        survey_burst_clicks=cfg.survey_burst_clicks,
        survey_skip_chance=cfg.survey_skip_chance,
        form_type_delay_ms=cfg.form_type_delay_ms,
        form_loop_interval_ms=cfg.form_loop_interval_ms,
        require_deal_wall_seen=cfg.require_deal_wall_seen,
        stop_at_deal_wall=cfg.stop_at_deal_wall,
        pause_at_deal_wall=False,
        guided_deal_step=7,
        guided_deal_cycles=3,
        guided_deal_l3_cycles=3,
    )


async def _survey_settle(page=None, cfg: Optional[SmartFunnelConfig] = None, *, slow: bool = False) -> None:
    """Brief pause after survey tap — fast mode ~25ms; instant when KRX_SURVEY_INSTANT=1."""
    env_ms = os.environ.get("KRX_SURVEY_SETTLE_MS")
    if env_ms is not None and str(env_ms).strip() != "":
        ms = int(env_ms)
        if ms <= 0:
            return
        await asyncio.sleep(max(0.01, ms / 1000.0))
        return
    if os.environ.get("KRX_SURVEY_INSTANT", "").strip().lower() in ("1", "true", "yes"):
        return
    settle_s: Optional[float] = None
    if page is not None:
        try:
            settle_s = getattr(page.context, "_krx_survey_settle_s", None)
        except Exception:
            settle_s = None
    if settle_s is None:
        cfg = cfg or SmartFunnelConfig()
        settle_s = (
            max(0.02, int(cfg.survey_settle_ms or 25) / 1000.0)
            if cfg.fast_survey
            else 1.5
        )
    if slow:
        settle_s = max(float(settle_s), 0.45)
    if settle_s <= 0:
        return
    await asyncio.sleep(float(settle_s))


def _survey_instant_enabled(page=None) -> bool:
    if os.environ.get("KRX_SURVEY_INSTANT", "").strip().lower() in ("1", "true", "yes"):
        return True
    if page is not None:
        try:
            if getattr(page.context, "_krx_fast_survey", False):
                return True
        except Exception:
            pass
    return False


async def _survey_fingerprint(page) -> str:
    """Hash survey-visible text across iframes — detects question changes main fp misses."""
    body = await _survey_body_text(page)
    return hashlib.md5(body[:2500].encode("utf-8", errors="ignore")).hexdigest()


async def _survey_state_changed(page, before: str) -> bool:
    wait_s = 0.09 if _survey_instant_enabled() else 0.035
    await asyncio.sleep(wait_s)
    return await _survey_fingerprint(page) != before


async def _survey_click_ok(page, before: str, clicked: bool) -> bool:
    """True when click succeeded; instant mode trusts click if page is slow to repaint."""
    if not clicked:
        return False
    if await _survey_state_changed(page, before):
        return True
    return _survey_instant_enabled()


def _guided_pause_complete(cfg: SmartFunnelConfig, ctx: Any) -> bool:
    """True when guided pause can exit (L1 + post steps + L3 all done)."""
    if not cfg.pause_at_deal_wall:
        return True
    max_step = max(0, int(cfg.guided_deal_step or 0))
    cycles_need = max(0, int(cfg.guided_deal_cycles or 0))
    l3_need = max(0, int(cfg.guided_deal_l3_cycles or 0))
    cycle_steps = 5
    if cycles_need > 0:
        cycles_done = int(getattr(ctx, "_krx_guided_cycles_done", 0) or 0)
        if cycles_done < cycles_need:
            return False
        if max_step <= cycle_steps:
            if l3_need <= 0:
                return True
        else:
            post_need = max_step - cycle_steps
            post_done = int(getattr(ctx, "_krx_guided_post_step_done", 0) or 0)
            if post_done < post_need:
                return False
        if l3_need <= 0:
            return True
        l3_done = int(getattr(ctx, "_krx_guided_l3_cycles_done", 0) or 0)
        return l3_done >= l3_need
    if max_step <= 0:
        return True
    return int(getattr(ctx, "_krx_guided_step_done", 0) or 0) >= max_step


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
    if any(
        k in s
        for k in (
            "level 1 deals",
            "level 2 deals",
            "level 3 deals",
            "best match for you",
            "your cost:",
            "do you already have",
            "how to complete",
            "start deal",
            "next step: complete",
            "continue instructions below",
        )
    ):
        return False
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
            "what type of migraines",
            "migraines do you",
            "do you suffer from",
            "chronic",
            "cluster",
            "episodic",
            "car accident",
            "been in a car accident",
            "been in an accident",
        )
    )


def _body_on_form(body: str, url: str = "") -> bool:
    """Lead form (page 1 or page 2 — street/phone/DOB/gender)."""
    s = (body or "").lower()
    u = (url or "").lower()
    if any(
        k in s
        for k in (
            "street address",
            "please enter a street address",
            "please enter a zip",
            "city/town",
            "mobile phone",
            "select gender",
            "last few details",
            "please complete date of birth",
            "please select gender",
            "first name",
            "last name",
            "date of birth",
        )
    ):
        return True
    return "lfirstname" in u or "laddress" in u or "default.aspx" in u and "street" in s


async def _form_active_on_page(page) -> bool:
    return await _page_has_text(
        page,
        "Street Address",
        "street address",
        "Last few details",
        "Mobile Phone",
        "Select Gender",
        "City/Town",
        "First Name",
        "Last Name",
        "Date of Birth",
        "Please enter a street address",
        "Please select gender",
    )


def _body_has_deal_wall(body: str, url: str = "") -> bool:
    s = (body or "").lower()
    u = (url or "").lower()
    on_deal_host = any(
        h in u
        for h in (
            "displayoptoffers",
            "uplevelrewards",
            "levelrewards",
            "rewardsgiant",
            "eward4spot",
            "reward4spot",
        )
    )
    has_level = any(k in s for k in ("level 1 deals", "level 2 deals", "level 3 deals"))
    has_l3_prompt = "complete 3 more deal" in s or "next step: complete 3" in s
    has_wall = any(
        k in s
        for k in (
            "best match for you",
            "continue instructions below",
            "next step: complete",
            "follow instructions to earn",
            "complete 1 deal on this level",
            "your cost:",
            "do you already have",
            "how to complete",
            "start deal",
            "keep going & qualify",
        )
    )
    if on_deal_host and (has_level or has_wall or has_l3_prompt):
        return True
    if "question 1" in s or "do you shop at target" in s or "get $750 towards" in s:
        return False
    if _body_on_survey(s) and not has_level:
        return False
    if has_level and has_wall:
        return True
    return False


def _conversion_ready(
    metrics: Dict[str, Any],
    cfg: SmartFunnelConfig,
    *,
    deal_wall_seen: bool,
    body: str = "",
    survey_active: bool = False,
    deal_flow_complete: bool = False,
) -> bool:
    if deal_flow_complete and cfg.wait_until_conversion:
        return True
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
    *,
    poll_ms: Optional[int] = None,
) -> None:
    """Wait until page fingerprint changes or interval elapsed."""
    poll = max(30, int(poll_ms if poll_ms is not None else cfg.idle_poll_ms))
    start = time.monotonic()
    while time.monotonic() < deadline:
        await asyncio.sleep(poll / 1000.0)
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


async def _human_page_click(page, x: float, y: float, *, fast: Optional[bool] = None) -> None:
    """Trusted mouse click at page coords (isTrusted=true). Fast path skips human motion delays."""
    if fast is None:
        try:
            fast = bool(getattr(page.context, "_krx_fast_survey", False))
        except Exception:
            fast = False
    if fast:
        try:
            await page.mouse.click(x, y)
        except Exception:
            await page.mouse.move(x, y)
            await page.mouse.down()
            await page.mouse.up()
        return
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


async def _human_click_locator(page, loc, *, fast: Optional[bool] = None) -> bool:
    """Scroll to element and click via trusted page mouse at locator center."""
    if fast is None:
        try:
            fast = bool(getattr(page.context, "_krx_fast_survey", False))
        except Exception:
            fast = False
    try:
        await loc.scroll_into_view_if_needed(timeout=800 if fast else 3000)
    except Exception:
        pass
    box = await loc.bounding_box()
    if not box or box["width"] < 8 or box["height"] < 8:
        return False
    await _human_page_click(
        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, fast=fast
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
            await _survey_settle(page)
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
  var ANSWER = /^(excellent|good|some problems|major problems|i don't know|full time|part time|unemployed|student|self employed|retired|on disability|other|yes|no|maybe later|no call|no thanks|not now|often|rarely|never|weekly|monthly|daily|today|homeowner|renter|tax\\/irs debt|credit card|student loan|medical|timeshare|prefer not to answer)$/i;
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
                    await _survey_settle(page)
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
    body = await _survey_body_text(page)
    if "select all that apply" in (body or "").lower():
        return await _native_multiselect_step(page)
    skip_re = re.compile(
        r"skip|privacy|terms|faq|program requirements|member support|about the survey|unsubscribe|disclaimer|legal notice|cookie policy",
        re.I,
    )
    for frame in await _survey_frames_ordered(page):
        try:
            locators = frame.locator("button, a, div, span, [role=button], input[type=button], input[type=submit]")
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
                    try:
                        href = await loc.get_attribute("href")
                        if href and _href_is_blocked(href):
                            continue
                    except Exception:
                        pass
                if not text or not box or skip_re.search(text) or _is_blocked_click_text(text):
                    continue
                if "?" in text or (len(text) > 24 and re.match(r"^(have you|do you|which|what|when|how|are you)\b", text, re.I)):
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
                    await _survey_settle(page)
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
                        await _survey_settle(page)
                        return True
        except Exception:
            continue
    for frame in page.frames:
        for label in ("Skip the survey", "Skip"):
            try:
                loc = frame.get_by_text(label, exact=False).first
                if await loc.count() > 0:
                    if await _human_click_locator(page, loc):
                        await _survey_settle(page)
                        return True
            except Exception:
                continue
    return False


async def _survey_active_on_page(page) -> bool:
    return await _page_has_text(
        page,
        "finish your survey",
        "sponsored ad",
        "question is not required",
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
        "what type of migraines",
        "migraines do you suffer",
        "do you suffer from",
        "car accident",
        "been in a car accident",
        "been in an accident",
    )


async def _deal_wall_on_page(page) -> bool:
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
    has_level_header = await _page_has_text(page, "level 1 deals", "level 2 deals", "level 3 deals")
    has_deal_modal = await _page_has_text(
        page, "do you already have", "how to complete", "start deal", "best match for you"
    )
    if on_deal_host and (has_level_header or has_deal_modal):
        return True
    if await _page_has_text(page, "question 1", "do you shop at target", "get $750 towards"):
        return False
    if await _survey_active_on_page(page) and not has_level_header:
        return False
    has_wall_content = await _page_has_text(
        page,
        "best match for you",
        "continue instructions below",
        "next step: complete",
        "your cost:",
    )
    has_red_continue = False
    try:
        has_red_continue = await page.get_by_text("CONTINUE", exact=True).count() > 0
    except Exception:
        pass
    if has_level_header and (has_wall_content or has_red_continue):
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
                "what type of migraines",
                "sign up for text messages",
                "explore offers from our sponsors",
                "level 1 deals",
                "level 2 deals",
                "level 3 deals",
                "best match for you",
                "continue instructions below",
                "next step: complete",
                "your cost:",
                "your reward is waiting",
                "confirm your email",
                "sign up or resume",
                "first name",
                "street address",
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


SURVEY_SKIP_CHANCE = 0.35  # fallback when config not passed


def _visit_should_skip_survey(page, cfg: Optional[SmartFunnelConfig] = None) -> bool:
    """Once per browser context: roll skip based on survey_skip_chance (RUT default 35%)."""
    import random

    ctx = page.context
    key = "_krx_survey_skip_roll"
    if not hasattr(ctx, key):
        if cfg is not None:
            chance = float(cfg.survey_skip_chance or 0.0)
        else:
            chance = float(getattr(ctx, "_krx_survey_skip_chance", SURVEY_SKIP_CHANCE))
        setattr(ctx, key, random.random() < chance)
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


SURVEY_AGREE_CONTINUE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 40 && r.height >= 14;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  var agree = Array.from(document.querySelectorAll('button,div,span,label,[role=button],input[type=checkbox]')).filter(vis);
  var agreeBtn = agree.find(function (e) { return /^i agree$/i.test(txt(e)); });
  if (agreeBtn) { try { agreeBtn.click(); } catch (e) {} }
  var cb = document.querySelector('input[type=checkbox]');
  if (cb && !cb.checked) { try { cb.click(); } catch (e) {} }
  var cont = agree.concat(Array.from(document.querySelectorAll('button,a,[role=button]')).filter(vis)).find(function (e) {
    var t = txt(e).toLowerCase().replace(/\u2192/g, '').trim();
    return t === 'continue' || /^continue\b/.test(t);
  });
  if (!cont) return null;
  try { cont.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = cont.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(cont) };
}"""


def _is_agree_continue_body(body: str) -> bool:
    b = (body or "").lower()
    # TCPA survey questions embed "I agree" + phone in disclaimers — not the e-sign gate.
    if any(
        k in b
        for k in (
            "car accident",
            "been in a car accident",
            "been in an accident",
            "maybe later",
            "no call",
            "finish your survey",
        )
    ):
        return False
    return "i agree" in b and ("email address" in b or "phone number" in b or "esign" in b)


async def _native_agree_continue_step(page) -> bool:
    """Fast-path: I AGREE + Continue on displayoptoffers consent page."""
    body = await _survey_body_text(page)
    if not _is_agree_continue_body(body):
        return False
    for frame in await _survey_frames_ordered(page):
        try:
            target = await frame.evaluate(SURVEY_AGREE_CONTINUE_JS)
            if target and target.get("x") is not None:
                if await _trusted_survey_click(
                    page,
                    frame,
                    label=str(target.get("label") or "Continue"),
                    x=float(target["x"]),
                    y=float(target["y"]),
                ):
                    await asyncio.sleep(0.5)
                    return True
        except Exception:
            continue
    for label in ("I AGREE", "I Agree"):
        try:
            loc = page.get_by_text(label, exact=True).first
            if await loc.count() > 0:
                await _human_click_locator(page, loc)
                await asyncio.sleep(0.25)
        except Exception:
            pass
    for label in ("Continue →", "Continue", "CONTINUE"):
        if await _click_survey_labels(page, [label]):
            await asyncio.sleep(0.5)
            return True
    return False


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


SPONSORED_AD_ANSWER_JS = r"""() => {
  window.__krxSponsoredPicks = window.__krxSponsoredPicks || {};
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 100 && r.height >= 28 && r.top >= 70 && r.top <= 680;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|privacy|terms|disclaimer|unsubscribe|cookie|legal notice|finish your survey|program requirements|member support/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|legal|flashrewards/i.test(href)) return true;
    return false;
  }
  function looksLikeAnswer(t) {
    var tl = t.toLowerCase();
    return /yes|maybe|protect|hear more|get a quote|find out|check eligibility|sign up|interested|not interested|learn more|tell me more|get started|continue|no thanks/i.test(tl);
  }
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button],label')).filter(vis);
  var opts = els.filter(function (e) {
    if (blocked(e)) return false;
    var t = txt(e);
    if (!t || t.length < 8 || t.length > 130) return false;
    return looksLikeAnswer(t);
  });
  if (!opts.length) {
    opts = els.filter(function (e) {
      if (blocked(e)) return false;
      var t = txt(e);
      return t.length >= 10 && t.length <= 120;
    });
  }
  if (!opts.length) return null;
  var candidates = [];
  for (var i = 0; i < opts.length; i++) {
    var key = txt(opts[i]).slice(0, 72);
    if (window.__krxSponsoredPicks[key]) continue;
    candidates.push({ el: opts[i], key: key });
  }
  if (!candidates.length) {
    for (var j = 0; j < opts.length; j++) {
      candidates.push({ el: opts[j], key: txt(opts[j]).slice(0, 72) });
    }
  }
  for (var k = candidates.length - 1; k > 0; k--) {
    var ri = Math.floor(Math.random() * (k + 1));
    var tmp = candidates[k];
    candidates[k] = candidates[ri];
    candidates[ri] = tmp;
  }
  var pick = candidates[0];
  window.__krxSponsoredPicks[pick.key] = 1;
  try { pick.el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = pick.el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(pick.el) };
}"""


async def _click_sponsored_ad_random(page) -> bool:
    """Sponsored ad interstitial — pick a random visible answer (unique per visit)."""
    body = await _survey_body_text(page)
    if not _is_sponsored_ad_body(body):
        return False
    for label in ("Skip Question", "Skip"):
        if await _click_survey_labels(page, [label]):
            await _survey_settle(page)
            return True
    for frame in await _survey_frames_ordered(page):
        try:
            target = await frame.evaluate(SPONSORED_AD_ANSWER_JS)
            if not target or target.get("x") is None:
                continue
            label = str(target.get("label") or "").strip()
            if await _trusted_survey_click(
                page,
                frame,
                label=label,
                x=float(target["x"]),
                y=float(target["y"]),
            ):
                await _survey_settle(page, slow=True)
                return True
        except Exception:
            continue
    try:
        await page.evaluate("window.scrollBy(0, 320)")
        await asyncio.sleep(0.6)
    except Exception:
        pass
    return await _click_random_visible_survey_option(page, allow_sponsored=True)


SURVEY_RANDOM_VISIBLE_JS = r"""() => {
  var body = (document.body.innerText || '').toLowerCase();
  if (/select all that apply/.test(body)) return null;
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
    if (!t || t.length > 90 || t.indexOf('?') >= 0) return false;
    if (/^(have you|do you|which|what|when|how|are you)\b/i.test(t) && t.length > 24) return false;
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


async def _click_random_visible_survey_option(page, *, allow_sponsored: bool = False) -> bool:
    """Pick any visible survey answer button at random — works for unknown/new questions."""
    body = await _survey_body_text(page)
    if "select all that apply" in (body or "").lower():
        return await _native_multiselect_step(page)
    if _is_sponsored_ad_body(body) and not allow_sponsored:
        return await _click_sponsored_ad_random(page)
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
                if not getattr(page.context, "_krx_fast_survey", False):
                    await _survey_settle(page)
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
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function norm(t) { return String(t || '').replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim().toUpperCase(); }
  function matchesLabel(elText, want) {
    var t = norm(elText);
    return t === want || t.indexOf(want) === 0;
  }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip|about the survey|program requirements|member support|privacy|terms|disclaimer/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  var els = Array.from(document.querySelectorAll('button,div,span,a,[role=button],label,input[type=button],input[type=submit]')).filter(vis);
  var matches = els.filter(function (e) {
    if (blocked(e)) return false;
    return matchesLabel(txt(e), norm(want));
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
    raw = str(label or "").strip()
    variants: List[str] = []
    if raw.upper() == "NO":
        variants = ["NO", "No", "no"]
    elif raw.upper() == "YES":
        variants = ["YES", "Yes", "yes"]
    elif raw.lower() == "maybe later":
        variants = ["Maybe Later", "MAYBE LATER", "maybe later"]
    elif raw.lower() == "no call":
        variants = ["No Call", "NO CALL", "no call"]
    elif raw.lower() == "no thanks":
        variants = ["No Thanks", "NO THANKS", "no thanks", "No, Thanks"]
    elif raw.lower() == "not now":
        variants = ["Not Now", "NOT NOW", "not now"]
    else:
        variants = [raw]
    for norm in variants:
        if _is_blocked_click_text(norm):
            continue
        for frame in await _survey_frames_ordered(page):
            try:
                coords = await frame.evaluate(YES_NO_SURVEY_COORDS_JS, norm)
                if coords and coords.get("x") is not None:
                    await _frame_mouse_click_at(page, frame, float(coords["x"]), float(coords["y"]))
                    await _survey_settle(page)
                    return True
            except Exception:
                continue
        for sel in await _survey_frame_locator_selectors(page):
            try:
                fl = page.frame_locator(sel)
                loc = fl.get_by_text(norm, exact=True).first
                if await loc.count() > 0:
                    try:
                        await loc.click(force=True, timeout=6000)
                    except Exception:
                        if await _human_click_locator(page, loc):
                            pass
                        else:
                            continue
                    await _survey_settle(page)
                    return True
            except Exception:
                continue
        for frame in await _survey_frames_ordered(page):
            for exact in (True, False):
                try:
                    loc = frame.get_by_text(norm, exact=exact).first
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
                    await _survey_settle(page)
                    return True
                except Exception:
                    continue
    return False


async def _locator_current_value(loc) -> str:
    try:
        tag = await loc.evaluate("el => (el.tagName || '').toLowerCase()")
        if tag == "select":
            return str(
                await loc.evaluate(
                    "el => { var o = el.options[el.selectedIndex]; return ((o && o.text) || el.value || '').trim(); }"
                )
            )
        return (await loc.input_value(timeout=2000)).strip()
    except Exception:
        return ""


def _field_values_match(current: str, target: str, *, digits_only: bool = False) -> bool:
    cur = (current or "").strip()
    tgt = (target or "").strip()
    if not tgt:
        return True
    if not cur:
        return False
    if cur.lower() == tgt.lower():
        return True
    if digits_only or (tgt.isdigit() and any(c.isdigit() for c in cur)):
        c = re.sub(r"\D", "", cur)
        t = re.sub(r"\D", "", tgt)
        if not t:
            return bool(c)
        if c == t:
            return True
        if len(t) >= 10 and c.endswith(t[-10:]):
            return True
        return False
    month_map = {
        "01": "jan", "02": "feb", "03": "mar", "04": "apr", "05": "may", "06": "jun",
        "07": "jul", "08": "aug", "09": "sep", "10": "oct", "11": "nov", "12": "dec",
    }
    cl, tl = cur.lower(), tgt.lower()
    if tl in month_map and month_map.get(tl.zfill(2) if tl.isdigit() else tl, tl[:3]) in cl:
        return True
    if tl.isdigit() and len(tl) <= 2:
        mname = month_map.get(tl.zfill(2), "")
        if mname and mname in cl:
            return True
    if tl in cl or cl in tl:
        return True
    return False


async def _type_if_present(
    page, selector: str, value: str, delay_ms: Optional[int] = None, *, digits_only: bool = False
) -> bool:
    """Type into input only when empty or value differs (no double-type)."""
    if not value:
        return False
    if delay_ms is None:
        try:
            delay_ms = int(getattr(page.context, "_krx_form_type_delay_ms", 50) or 50)
        except Exception:
            delay_ms = 50
    delay_ms = max(35, int(delay_ms))
    for frame in page.frames:
        try:
            loc = frame.locator(selector).first
            if await loc.count() > 0:
                current = await _locator_current_value(loc)
                if _field_values_match(current, value, digits_only=digits_only):
                    return True
                await loc.click(timeout=4000)
                await loc.fill("", timeout=3000)
                await loc.press_sequentially(value, delay=delay_ms, timeout=20000)
                try:
                    settle = float(getattr(page.context, "_krx_form_field_settle_s", 0.5) or 0.5)
                except Exception:
                    settle = 0.5
                await asyncio.sleep(settle)
                return True
        except Exception:
            continue
    return False


async def _fill_if_present(page, selector: str, value: str) -> bool:
    return await _type_if_present(page, selector, value)


def _form_page_key(body: str, url: str = "") -> str:
    """Stable form page id — ignore validation error text churn."""
    s = (body or "").lower()
    u = (url or "").lower()
    parts: List[str] = []
    if "first name" in s or "lfirstname" in u:
        parts.append("p1")
    if "street address" in s or "last few details" in s or "mobile phone" in s:
        parts.append("p2")
    if "select gender" in s or "date of birth" in s:
        parts.append("p3")
    if not parts:
        parts.append("form")
    return f"{u.split('?')[0]}|{'-'.join(parts)}"


async def _fill_by_placeholder(page, placeholder: str, value: str, *, digits_only: bool = False) -> bool:
    if not value:
        return False
    return await _type_if_present(
        page, f"input[placeholder*='{placeholder}' i]", value, digits_only=digits_only
    )


def _month_select_values(month: str) -> List[str]:
    """Month tokens for <select> options (03, MAR, March, ...)."""
    names = (
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    )
    full = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    out: List[str] = []
    m = str(month or "").strip()
    if not m:
        return out
    if m.isdigit():
        n = int(m)
        if 1 <= n <= 12:
            out.extend([str(n), str(n).zfill(2), names[n - 1], full[n - 1]])
    else:
        out.append(m)
        up = m.upper()[:3]
        if up in names:
            idx = names.index(up) + 1
            out.extend([str(idx), str(idx).zfill(2), names[idx - 1], full[idx - 1]])
    seen: set = set()
    deduped: List[str] = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped


async def _select_if_present(page, selector: str, value: str) -> bool:
    if not value:
        return False
    candidates = _month_select_values(value) if "dobmonth" in selector.lower() or "month" in selector.lower() else [value]
    for frame in page.frames:
        try:
            loc = frame.locator(selector).first
            if await loc.count() == 0:
                continue
            current = await _locator_current_value(loc)
            if _field_values_match(current, value):
                return True
            for cand in candidates:
                try:
                    await loc.select_option(value=cand)
                    return True
                except Exception:
                    try:
                        await loc.select_option(label=cand)
                        return True
                    except Exception:
                        continue
        except Exception:
            continue
    return False


FORM_CONTINUE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 70 && r.height >= 28 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  var cont = Array.from(document.querySelectorAll('button,a,div,span,input[type=submit],[role=button]')).filter(vis).filter(function (e) {
    var t = txt(e).toLowerCase().replace(/\u2192/g, '').trim();
    return t === 'continue' || /^continue\b/.test(t) || t === 'submit' || t === 'next';
  });
  if (!cont.length) return null;
  cont.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  var el = cont[0];
  try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
}"""


async def _native_form_click_continue(page) -> bool:
    for frame in page.frames:
        try:
            target = await frame.evaluate(FORM_CONTINUE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(0.8)
                return True
        except Exception:
            continue
    if await _click_survey_button(page, "Continue"):
        await asyncio.sleep(0.8)
        return True
    if await _click_survey_button(page, "Submit"):
        await asyncio.sleep(0.8)
        return True
    for frame in page.frames:
        try:
            loc = frame.locator("input[type=submit], button[type=submit]").first
            if await loc.count() > 0:
                await loc.click(timeout=3000, force=True)
                await asyncio.sleep(0.8)
                return True
        except Exception:
            continue
    return False


async def _native_form_step(page, row: Dict[str, Any]) -> bool:
    """Fill lead form once — skip fields that already match Excel data."""
    body = await _retail_body_text(page)
    url_l = (page.url or "").lower()
    if not _body_on_form(body, url_l) and not await _form_active_on_page(page):
        return False

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
    if not any(data[k] for k in ("first", "email", "address", "phone")):
        return False

    filled = False
    phone_filled = False
    for sel, val, opts in (
        ("#lfirstname, #firstname, input[name*='first' i], input[placeholder*='First' i]", data["first"], {}),
        ("#llastname, #lastname, input[name*='last' i], input[placeholder*='Last' i]", data["last"], {}),
        ("#laddress, #address, input[name*='address' i], input[placeholder*='Street' i]", data["address"], {}),
        ("#lzip, input[name*='zip' i], input[placeholder*='Zip' i]", data["zip"], {"digits_only": True}),
        ("#lcity, input[name*='city' i], input[placeholder*='City' i]", data["city"], {}),
        ('input[type="email"], input[name*="email" i]', data["email"], {}),
    ):
        if val and await _type_if_present(page, sel, val, **opts):
            filled = True

    if data["phone"]:
        if await _type_if_present(
            page,
            "input[name*='phone' i], input[type='tel'], input[placeholder*='Mobile' i], input[placeholder*='Phone' i]",
            data["phone"],
            digits_only=True,
        ):
            filled = True
            phone_filled = True

    if data["address"] and not phone_filled:
        if await _fill_by_placeholder(page, "Street", data["address"]):
            filled = True

    if data["phone"] and not phone_filled:
        if await _fill_by_placeholder(page, "Mobile", data["phone"], digits_only=True):
            filled = True
            phone_filled = True

    if data["state"]:
        for frame in page.frames:
            try:
                loc = frame.locator("select[name*='state' i], select#lstate").first
                if await loc.count() > 0:
                    current = await _locator_current_value(loc)
                    if not _field_values_match(current, data["state"]):
                        try:
                            await loc.select_option(value=data["state"])
                        except Exception:
                            await loc.select_option(label=data["state"])
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            if await _type_if_present(
                page, "input[placeholder*='State' i], input[name*='state' i]", data["state"]
            ):
                filled = True

    for sel, val in (
        ("select[name*='dobmonth' i], select#ldobmonth", data["month"]),
        ("select[name*='dobday' i], select#ldobday", data["day"]),
        ("select[name*='dobyear' i], select#ldobyear", data["year"]),
        ("input[placeholder='Month'], input[name='dobmonth'], input[placeholder*='Month' i]", data["month"]),
        ("input[placeholder='Day'], input[name='dobday'], input[placeholder*='Day' i]", data["day"]),
        ("input[placeholder='Year'], input[name='dobyear'], input[placeholder*='Year' i]", data["year"]),
    ):
        if not val:
            continue
        if "select" in sel and await _select_if_present(page, sel, val):
            filled = True
        elif await _type_if_present(page, sel, val):
            filled = True

    phone = data["phone"]
    if len(phone) >= 10 and not phone_filled:
        for frame in page.frames:
            try:
                area = frame.locator("#lphonecode, #phonecode, input[name*='phonecode' i]").first
                pre = frame.locator("#lphoneprefix, #phoneprefix, input[name*='phoneprefix' i]").first
                suf = frame.locator("#lphonesuffix, #phonesuffix, input[name*='phonesuffix' i]").first
                if await area.count() == 0:
                    continue
                for loc, segment in ((area, phone[:3]), (pre, phone[3:6]), (suf, phone[6:10])):
                    if await loc.count() == 0:
                        continue
                    current = await _locator_current_value(loc)
                    if _field_values_match(current, segment, digits_only=True):
                        continue
                    await loc.click(timeout=3000)
                    await loc.fill("")
                    await loc.press_sequentially(segment, delay=50, timeout=8000)
                    filled = True
                phone_filled = True
                break
            except Exception:
                continue

    gender_label = _gender_label_from_row(row)
    if await _click_survey_button(page, gender_label):
        filled = True
    else:
        for frame in page.frames:
            try:
                loc = frame.get_by_text(gender_label, exact=True).first
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

    for _ in range(3):
        if await _native_form_click_continue(page):
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass
            return True
        await asyncio.sleep(0.6)
    try:
        await page.keyboard.press("Enter")
    except Exception:
        pass
    return filled


async def _body_on_sms_optin(body: str) -> bool:
    s = (body or "").lower()
    return any(
        k in s
        for k in (
            "sign up for text messages",
            "text me reward updates",
            "we'll text you at",
            "explore offers from our sponsors",
            "progress updates & reminders",
        )
    )


async def _native_sms_optin_step(page, cfg: SmartFunnelConfig) -> bool:
    """SMS opt-in interstitial — default No thanks (cfg.sms_answer)."""
    body = await _retail_body_text(page)
    if not await _body_on_sms_optin(body):
        return False
    prefer_no = (cfg.sms_answer or "no thanks").strip().lower().startswith("no")
    primary = (
        ["No thanks", "No Thanks", "No, thank you", "No thank you"]
        if prefer_no
        else ["Text me Reward updates", "Text me reward updates"]
    )
    fallback = (
        ["Text me Reward updates", "Text me reward updates"]
        if prefer_no
        else ["No thanks", "No Thanks"]
    )
    for label in primary + fallback:
        if await _click_survey_yes_no_label(page, label):
            await asyncio.sleep(1.5)
            return True
        if await _native_click_text(page, label):
            await asyncio.sleep(1.5)
            return True
    for frame in page.frames:
        try:
            target = await frame.evaluate(
                """() => {
                  function vis(e) {
                    var s = getComputedStyle(e);
                    if (s.display === 'none' || s.visibility === 'hidden') return false;
                    var r = e.getBoundingClientRect();
                    return r.width >= 60 && r.height >= 24 && r.top >= 0 && r.top < innerHeight;
                  }
                  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
                  var bt = (document.body.innerText || '').toLowerCase();
                  if (!/text messages|text me reward|explore offers from our sponsors/i.test(bt)) return null;
                  var pick = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis).find(function (e) {
                    return /^no thanks$/i.test(txt(e));
                  });
                  if (!pick) return null;
                  try { pick.scrollIntoView({ block: 'center' }); } catch (e) {}
                  var r = pick.getBoundingClientRect();
                  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(pick) };
                }"""
            )
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _native_reward_status_optin_step(page, cfg: SmartFunnelConfig) -> bool:
    """Dismiss reward status / SMS / email prompt on offer host."""
    body = await _retail_body_text(page)
    if await _body_on_sms_optin(body):
        return await _native_sms_optin_step(page, cfg)
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
    return /^(yes|no|often|rarely|sometimes|never|daily|weekly|monthly|homeowner|renter|male|female|single|married|full time|part time|unemployed|student|self employed|retired|on disability|other|maybe later|no call|no thanks|not now)$/i.test(t)
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
                    if box["y"] < 70 or box["y"] > 700:
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
                    if not box or box["y"] < 70 or box["y"] > 560:
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
            await _survey_settle(page)
            return True
        except Exception:
            pass
    return False


async def _generic_visible_answer_click(page) -> bool:
    """Last resort — click largest visible answer-like button on page."""
    body = await _survey_body_text(page)
    if "select all that apply" in (body or "").lower():
        return await _native_multiselect_step(page)
    skip_re = re.compile(
        r"skip|privacy|terms|conditions|faq|member support|unsubscribe|about the survey|program requirements|disclaimer|legal notice|cookie policy",
        re.I,
    )

    async def _pick_largest_in_frame(frame) -> bool:
        try:
            locators = frame.locator("button, div, span, [role=button], input[type=button], a")
            count = min(await locators.count(), 80)
            best_idx = -1
            best_area = 0
            for i in range(count):
                loc = locators.nth(i)
                try:
                    text = (await loc.inner_text(timeout=500)).strip()
                    if not text:
                        text = (await loc.get_attribute("value") or "").strip()
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
                if await _human_click_locator(page, loc):
                    await _survey_settle(page)
                    return True
        except Exception:
            pass
        return False

    for frame in await _survey_frames_ordered(page):
        if await _pick_largest_in_frame(frame):
            return True
    return await _pick_largest_in_frame(page)


GENERIC_MULTISELECT_JS = r"""() => {
  var body = (document.body.innerText || '').toLowerCase();
  if (!/select all that apply/.test(body)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 160 && r.height >= 30 && r.top >= 70 && r.top <= 620;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|program requirements|member support|about our program|privacy|terms|disclaimer|reward status|finish your survey/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  function isSelected(el) {
    var s = getComputedStyle(el);
    var bg = s.backgroundColor || '';
    var parts = bg.match(/\d+/g);
    if (parts && parts.length >= 3) {
      var r = parseInt(parts[0], 10), g = parseInt(parts[1], 10), b = parseInt(parts[2], 10);
      if (g > 90 && g > r + 20 && g > b + 10) return true;
    }
    var html = (el.innerHTML || '').toLowerCase();
    if (/checkmark|fa-check|icon-check|✓|✔|polyline/.test(html)) return true;
    return false;
  }
  var raw = Array.from(document.querySelectorAll('button,a,div,span,[role=button],label,li')).filter(vis);
  var byText = {};
  raw.forEach(function (e) {
    if (blocked(e)) return;
    var t = txt(e);
    if (!t || t.length < 6 || t.length > 140) return;
    if (/^done$/i.test(t)) return;
    var r = e.getBoundingClientRect();
    if (r.width < 180 || r.height < 32) return;
    var key = t.slice(0, 96).toLowerCase().replace(/\s+/g, ' ');
    var area = r.width * r.height;
    if (!byText[key] || area > byText[key].area) byText[key] = { el: e, area: area, t: t };
  });
  var options = Object.keys(byText).map(function (k) {
    var o = byText[k];
    var el = o.el;
    var r = el.getBoundingClientRect();
    return {
      label: o.t,
      x: r.left + r.width / 2,
      y: r.top + r.height / 2,
      selected: isSelected(el)
    };
  });
  options.sort(function (a, b) { return a.y - b.y; });
  if (!options.length) return null;
  var doneEl = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis).find(function (e) {
    return /^done$/i.test(txt(e));
  });
  var done = null;
  if (doneEl) {
    try { doneEl.scrollIntoView({ block: 'center' }); } catch (e) {}
    var dr = doneEl.getBoundingClientRect();
    done = { x: dr.left + dr.width / 2, y: dr.top + dr.height / 2 };
  }
  var selectedCount = options.filter(function (o) { return o.selected; }).length;
  var unselected = options.filter(function (o) { return !o.selected; });
  var doneEnabled = false;
  if (doneEl) {
    var ds = getComputedStyle(doneEl);
    doneEnabled = ds.pointerEvents !== 'none' && parseFloat(ds.opacity || '1') >= 0.55;
    if (doneEnabled) {
      var dm = (ds.backgroundColor || '').match(/\d+/g);
      if (dm && dm.length >= 3) {
        var dr = +dm[0], dg = +dm[1], db = +dm[2];
        if (Math.abs(dr - dg) < 22 && Math.abs(dg - db) < 22 && dr >= 95 && dr <= 210) doneEnabled = false;
      }
    }
  }
  return { options: options, unselected: unselected.slice(0, 2), selectedCount: selectedCount, done: done, doneEnabled: doneEnabled || selectedCount >= 1 };
}"""


async def _is_multiselect_survey_page(page) -> bool:
    return await _page_has_text(page, "select all that apply")


async def _native_multiselect_step(page) -> bool:
    """Select-all-that-apply: one option click, wait for Done active, then Done — no toggle loop."""
    if not await _is_multiselect_survey_page(page):
        return False
    ctx = page.context
    body = await _survey_body_text(page)
    fp = str(hash(body[:400]))
    already_picked = getattr(ctx, "_krx_multi_picked_fp", None) == fp

    async def _eval_frame(frame):
        return await frame.evaluate(GENERIC_MULTISELECT_JS)

    async def _click_done(frame, result) -> bool:
        done = result.get("done")
        if done and done.get("x") is not None:
            await _frame_mouse_click_at(page, frame, float(done["x"]), float(done["y"]))
            await asyncio.sleep(0.08)
            await _frame_mouse_click_at(page, frame, float(done["x"]), float(done["y"]))
            return True
        return await _click_survey_button(page, "Done")

    frames = await _survey_frames_ordered(page)
    for frame in frames:
        try:
            result = await _eval_frame(frame)
            if not result or not result.get("options"):
                continue
            selected_count = int(result.get("selectedCount") or 0)
            unselected = result.get("unselected") or []

            if not already_picked and selected_count < 1 and unselected:
                pick = unselected[0]
                if pick.get("x") is not None:
                    await _frame_mouse_click_at(
                        page, frame, float(pick["x"]), float(pick["y"])
                    )
                elif pick.get("label"):
                    await _click_survey_button(page, str(pick["label"]))
                ctx._krx_multi_picked_fp = fp
                already_picked = True
                await asyncio.sleep(0.18)

            for _ in range(10):
                result = await _eval_frame(frame)
                if not result:
                    break
                if int(result.get("selectedCount") or 0) >= 1 or result.get("doneEnabled"):
                    if await _click_done(frame, result):
                        await asyncio.sleep(0.15)
                        if not await _is_multiselect_survey_page(page):
                            ctx._krx_multi_picked_fp = None
                            return True
                await asyncio.sleep(0.1)
        except Exception:
            continue

    ctx._krx_multi_picked_fp = None
    return False


async def _native_debt_multiselect_step(page) -> bool:
    """Backward-compatible alias — all select-all-that-apply pages use generic handler."""
    return await _native_multiselect_step(page)


DEBT_MULTISELECT_JS = GENERIC_MULTISELECT_JS


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
                            await _survey_settle(page)
                            return True
            except Exception:
                continue
        try:
            loc = frame.get_by_role("button", name=label_re).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await _survey_settle(page)
                    return True
        except Exception:
            pass
        try:
            loc = frame.get_by_text(label, exact=True).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await _survey_settle(page)
                    return True
        except Exception:
            pass
        try:
            loc = frame.get_by_text(label, exact=False).first
            if await loc.count() > 0 and await _locator_is_safe_survey_click(loc):
                if await _human_click_locator(page, loc):
                    await _survey_settle(page)
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
                    await _survey_settle(page)
                    return True
        except Exception:
            continue
    return False


STANDARD_SURVEY_CLICK_JS = r"""(labels) => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 55 && r.height >= 24 && r.top >= 70 && r.top <= 680;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function norm(t) { return String(t || '').replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim().toUpperCase(); }
  function matchesLabel(elText, want) {
    var t = norm(elText);
    return t === want || t.indexOf(want) === 0;
  }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/skip the survey|about the survey|program requirements|member support|privacy policy|terms|disclaimer|unsubscribe/i.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  var els = Array.from(document.querySelectorAll('button,div,span,a,p,[role=button],label,input[type=button],input[type=submit],[class*="btn"],[class*="button"]')).filter(vis);
  var order = Array.isArray(labels) ? labels : [];
  for (var li = 0; li < order.length; li++) {
    var want = norm(order[li]);
    var matches = els.filter(function (e) {
      if (blocked(e)) return false;
      return matchesLabel(txt(e), want);
    });
    matches.sort(function (a, b) {
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (rb.width * rb.height) - (ra.width * ra.height);
    });
    var el = matches[0];
    if (!el) continue;
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    try { el.click(); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { clicked: true, label: order[li], x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }
  return { clicked: false };
}"""


async def _click_standard_survey_choice(page) -> bool:
    """Click known single-choice survey answers (Yes / Maybe Later / No Call / No)."""
    body = (await _survey_body_text(page) or "").lower()
    legal_q = any(
        k in body
        for k in (
            "car accident",
            "been in an accident",
            "been in a car accident",
            "injured in",
            "personal injury",
            "attorney",
            "legal claim",
        )
    )
    if legal_q:
        labels = ("Maybe Later", "No Call", "No", "Yes")
    else:
        labels = ("Yes", "Maybe Later", "No Call", "No", "No Thanks", "Not Now")
    before = await _survey_fingerprint(page)

    for label in labels:
        if await _click_survey_yes_no_label(page, label):
            if await _survey_click_ok(page, before, True):
                return True
        if await _click_survey_button(page, label):
            if await _survey_click_ok(page, before, True):
                return True
    for frame in await _survey_frames_ordered(page):
        if await _click_survey_answer_in_frame(page, frame, list(labels)):
            if await _survey_click_ok(page, before, True):
                return True

    for frame in await _survey_frames_ordered(page):
        try:
            result = await frame.evaluate(STANDARD_SURVEY_CLICK_JS, list(labels))
            if result and result.get("clicked"):
                if result.get("x") is not None:
                    await _frame_mouse_click_at(
                        page, frame, float(result["x"]), float(result["y"])
                    )
                if not _survey_instant_enabled(page):
                    await _survey_settle(page)
                if await _survey_click_ok(page, before, True):
                    return True
        except Exception:
            continue

    return False


async def _native_survey_pick(
    page, row: Optional[Dict[str, Any]] = None, cfg: Optional[SmartFunnelConfig] = None
) -> bool:
    """Fully automatic survey — no per-question config needed."""
    row = row or {}
    before = await _survey_fingerprint(page)

    if await _native_multiselect_step(page):
        return await _survey_click_ok(page, before, True)

    body = await _survey_body_text(page)
    body_l = (body or "").lower()
    if "select all that apply" in body_l:
        return await _survey_click_ok(page, before, await _native_multiselect_step(page))
    if _is_sponsored_ad_body(body):
        if await _click_sponsored_ad_random(page):
            return await _survey_click_ok(page, before, True)

    if not body.strip() and not await _survey_active_on_page(page):
        return False

    data_labels = _data_linked_survey_answer(body, row)
    if data_labels and await _click_survey_labels(page, data_labels):
        return await _survey_click_ok(page, before, True)

    if await _click_standard_survey_choice(page):
        return True
    if await _click_survey_zone_answer(page):
        return await _survey_click_ok(page, before, True)
    if await _click_largest_survey_button(page):
        return await _survey_click_ok(page, before, True)
    if await _click_random_visible_survey_option(page):
        return await _survey_click_ok(page, before, True)
    if await _generic_visible_answer_click(page):
        return await _survey_click_ok(page, before, True)

    if _is_agree_continue_body(body) and await _native_agree_continue_step(page):
        return await _survey_click_ok(page, before, True)

    if cfg is not None and _visit_should_skip_survey(page, cfg):
        if await _try_skip_survey(page):
            return await _survey_click_ok(page, before, True)

    return False


async def _native_survey_burst(
    page,
    row: Optional[Dict[str, Any]],
    cfg: SmartFunnelConfig,
) -> bool:
    """Answer survey questions immediately — hammer until question advances or cap."""
    if await _is_multiselect_survey_page(page):
        return await _native_multiselect_step(page)
    if not cfg.fast_survey:
        return await _native_survey_pick(page, row, cfg)

    instant = _survey_instant_enabled(page)
    max_rounds = max(10, int(cfg.survey_burst_clicks or 10))
    start_fp = await _survey_fingerprint(page)
    clicked_any = False

    for _ in range(max_rounds):
        try:
            if await _is_multiselect_survey_page(page):
                ok = await _native_multiselect_step(page)
                clicked_any = clicked_any or ok
                if await _survey_fingerprint(page) != start_fp:
                    return True
                continue

            before = await _survey_fingerprint(page)
            picked = await _native_survey_pick(page, row, cfg)
            if picked:
                clicked_any = True
            if await _survey_fingerprint(page) != start_fp:
                return True

            if await _click_standard_survey_choice(page):
                clicked_any = True
                if await _survey_fingerprint(page) != start_fp:
                    return True
            if await _click_survey_zone_answer(page):
                clicked_any = True
                if await _survey_fingerprint(page) != start_fp:
                    return True
            if await _click_largest_survey_button(page):
                clicked_any = True
                if await _survey_fingerprint(page) != start_fp:
                    return True

            if not instant:
                break
            if await _survey_fingerprint(page) == before:
                continue
        except Exception:
            break
    return clicked_any


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
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 60 && r.height >= 24 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button],input[type=button]')).filter(vis);
  }
  function coords(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el), kind: 'modal_no' };
  }
  var all = btns();
  var yes = all.filter(function (e) { return /^yes!?$/i.test(txt(e)); });
  var no = all.filter(function (e) { return /^no!?$/i.test(txt(e)); });
  if (yes.length && no.length) {
    yes.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
    no.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
    var yr = yes[0].getBoundingClientRect();
    var belowNo = no.filter(function (e) {
      var nr = e.getBoundingClientRect();
      return nr.top >= yr.top + 8 && Math.abs(nr.left + nr.width / 2 - (yr.left + yr.width / 2)) < 90;
    });
    belowNo.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
    if (belowNo.length) return coords(belowNo[0]);
    var rightNo = no.filter(function (e) {
      var nr = e.getBoundingClientRect();
      return nr.left >= yr.left - 8 && Math.abs(nr.top - yr.top) < 40;
    });
    rightNo.sort(function (a, b) { return b.getBoundingClientRect().left - a.getBoundingClientRect().left; });
    if (rightNo.length) return coords(rightNo[0]);
  }
  if (!no.length) return null;
  var roots = Array.from(document.querySelectorAll('div,section,article,dialog,[role=dialog]')).filter(function (el) {
    var t = (el.innerText || '').slice(0, 600).toLowerCase();
    return /do you already have/i.test(t) && /\byes\b/i.test(t) && /\bno\b/i.test(t);
  });
  roots.sort(function (a, b) {
    return a.getBoundingClientRect().width * a.getBoundingClientRect().height
      - b.getBoundingClientRect().width * b.getBoundingClientRect().height;
  });
  if (roots.length) {
    var root = roots[roots.length - 1];
    var inRoot = Array.from(root.querySelectorAll('button,a,div,span,[role=button],input[type=button]')).filter(vis)
      .filter(function (e) { return /^no!?$/i.test(txt(e)); });
    inRoot.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    if (inRoot.length) return coords(inRoot[0]);
  }
  no.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  return coords(no[0]);
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
  if (/alert!|must complete.*deal to continue/i.test(bt)) {
    var links = btns().filter(function (e) {
      var t = txt(e).toLowerCase();
      if (/go back|back to deals/i.test(t)) return false;
      return /^continue$/i.test(txt(e)) || (e.tagName === 'A' && t === 'continue');
    });
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

NATIVE_ALERT_CONTINUE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 20 && r.height >= 10 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  }
  function coords(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'Continue' };
  }
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/alert!/i.test(bt)) return null;
  var goBack = btns().find(function (e) { return /go back/i.test(txt(e)); });
  var links = btns().filter(function (e) {
    if (!/^continue$/i.test(txt(e))) return false;
    if (/go back/i.test(txt(e))) return false;
    if (goBack && (goBack === e || goBack.contains(e))) return false;
    return true;
  });
  if (goBack) {
    var gr = goBack.getBoundingClientRect();
    var below = links.filter(function (e) { return e.getBoundingClientRect().top > gr.top + 8; });
    if (below.length) return coords(below[0]);
  }
  var anchor = Array.from(document.querySelectorAll('a')).filter(vis).find(function (e) {
    return /^continue$/i.test(txt(e));
  });
  if (anchor) return coords(anchor);
  if (links.length) return coords(links[links.length - 1]);
  return null;
}"""

FOOTER_GREY_CONTINUE_JS = r"""() => {
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/must complete.*deal to continue/i.test(bt)) return null;
  try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 70 && r.height >= 26 && r.top >= innerHeight * 0.35;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function coords(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'CONTINUE', kind: 'footer_grey' };
  }
  var cont = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(function (e) {
    if (!vis(e) || !/^continue$/i.test(txt(e))) return false;
    try {
      var p = e.closest('div,section,article,li');
      for (var up = 0; up < 10 && p; up++) {
        var t = (p.innerText || '').toLowerCase();
        if (/must complete.*deal to continue/i.test(t) && !/your cost:/i.test(t.slice(0, 220))) return true;
        p = p.parentElement;
      }
    } catch (e) {}
    return e.getBoundingClientRect().top > innerHeight * 0.55;
  });
  cont.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  if (cont.length) return coords(cont[0]);
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
        if (/your cost:|best match|take survey|sign up|free trial|get paid|get paid early|credit score|shopper|disney|sofi|chime|rocket money|fillwords|justplay|hulu|expressvpn|harry|numberguru|\$0\.00|\$0 to/i.test(t)) {
          return true;
        }
        p = p.parentElement;
      }
    } catch (e) {}
    var r = b.getBoundingClientRect();
    return r.top < innerHeight * 0.75 && !isGreyDisabled(b);
  }
  try { window.scrollTo(0, 0); } catch (e) {}
  try { window.scrollBy(0, 120); } catch (e) {}
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
    var costFree = false;
    try {
      var p = b.closest('div,section,article,li');
      if (p && /\$0\.00|\$0 to|your cost:\s*\$0/i.test(p.innerText || '')) costFree = true;
    } catch (e) {}
    candidates.push({ btn: b, key: k, free: costFree });
  }
  if (!candidates.length) {
    try { window.scrollBy(0, 400); } catch (e) {}
    return null;
  }
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

NATIVE_START_DEAL_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 80 && r.height >= 28 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/how to complete/i.test(bt)) return null;
  var pool = Array.from(document.querySelectorAll('button,a,input[type=button],input[type=submit],div,span,[role=button]')).filter(function (e) {
    return vis(e) && /^start deal!?$/i.test(txt(e));
  });
  if (!pool.length) return null;
  var back = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(function (e) {
    return vis(e) && /^back to deals$/i.test(txt(e));
  });
  back.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  if (back.length) {
    var btTop = back[0].getBoundingClientRect().top;
    var above = pool.filter(function (e) { return e.getBoundingClientRect().bottom <= btTop + 8; });
    above.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    if (above.length) pool = [above[0]];
  }
  pool.sort(function (a, b) { return (b.getBoundingClientRect().width * b.getBoundingClientRect().height) - (a.getBoundingClientRect().width * a.getBoundingClientRect().height); });
  var start = pool[0];
  try { start.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = start.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'START DEAL' };
}"""

START_DEAL_DIRECT_CLICK_JS = r"""() => {
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/how to complete/i.test(bt)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 80 && r.height >= 28 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || e.value || '') + '').trim(); }
  function isStart(e) { return /^start deal!?$/i.test(txt(e)); }
  function isBack(e) { return /^back to deals$/i.test(txt(e)); }
  function clickTarget(el) {
    if (!el) return null;
    var cur = el;
    for (var i = 0; i < 5; i++) {
      if (!cur) break;
      var tag = (cur.tagName || '').toUpperCase();
      if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT') return cur;
      if (cur.getAttribute && cur.getAttribute('role') === 'button') return cur;
      if (cur.onclick || (cur.getAttribute && cur.getAttribute('onclick'))) return cur;
      var s = getComputedStyle(cur);
      if (s.cursor === 'pointer' && cur.getBoundingClientRect().height >= 28) return cur;
      cur = cur.parentElement;
    }
    return el;
  }
  function fireClick(el) {
    if (!el) return false;
    var target = clickTarget(el);
    try { target.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
    try { target.focus(); } catch (e) {}
    try { target.click(); return true; } catch (e) {}
    try {
      ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function (t) {
        target.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
      });
      return true;
    } catch (e2) {}
    return false;
  }
  var roots = Array.from(document.querySelectorAll('div,section,article,dialog,[role=dialog]')).filter(function (el) {
    var t = (el.innerText || '').slice(0, 900).toLowerCase();
    return /how to complete/i.test(t) && /start deal/i.test(t);
  });
  roots.sort(function (a, b) {
    return a.getBoundingClientRect().width * a.getBoundingClientRect().height
      - b.getBoundingClientRect().width * b.getBoundingClientRect().height;
  });
  var root = roots.length ? roots[roots.length - 1] : document.body;
  var pool = Array.from(root.querySelectorAll('button,a,input[type=button],input[type=submit],div,span,[role=button]')).filter(function (e) {
    return vis(e) && isStart(e);
  });
  var back = Array.from(root.querySelectorAll('button,a,div,span,[role=button]')).filter(function (e) {
    return vis(e) && isBack(e);
  });
  back.sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
  var pick = null;
  if (back.length && pool.length) {
    var btTop = back[0].getBoundingClientRect().top;
    var above = pool.filter(function (e) { return e.getBoundingClientRect().bottom <= btTop + 8; });
    above.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    pick = above[0] || pool[0];
  } else if (pool.length) {
    pool.sort(function (a, b) {
      return (b.getBoundingClientRect().width * b.getBoundingClientRect().height)
        - (a.getBoundingClientRect().width * a.getBoundingClientRect().height);
    });
    pick = pool[0];
  }
  if (!pick) return null;
  fireClick(pick);
  var r = clickTarget(pick).getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: 'START DEAL', clicked: true };
}"""

NATIVE_DEAL_MUST_COMPLETE_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 30 && r.height >= 14;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function coords(el, kind) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el), kind: kind };
  }
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/you must complete.*deal to continue|must complete 1 deal to continue/i.test(bt)) return null;
  try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}
  function isFooterContinue(b) {
    var r = b.getBoundingClientRect();
    if (r.top <= innerHeight * 0.35) return false;
    try {
      var p = b.closest('div,section,article,li');
      for (var up = 0; up < 8 && p; up++) {
        var t = (p.innerText || '').toLowerCase();
        if (/must complete.*deal to continue/i.test(t) && !/your cost:/i.test(t.slice(0, 200))) return true;
        p = p.parentElement;
      }
    } catch (e) {}
    return r.top > innerHeight * 0.55;
  }
  var cont = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis).filter(function (e) {
    if (!/^continue$/i.test(txt(e))) return false;
    return isFooterContinue(e);
  });
  cont.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
  if (cont.length) return coords(cont[0], 'footer_continue');
  var msg = Array.from(document.querySelectorAll('div,span,p,a,button')).filter(vis).filter(function (e) {
    var t = txt(e).toLowerCase();
    return /must complete.*deal to continue/i.test(t) && t.length < 120;
  });
  if (msg.length) {
    msg.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    return coords(msg[0], 'footer_message');
  }
  return null;
}"""

NATIVE_BACK_TO_DEALS_JS = r"""() => {
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width >= 70 && r.height >= 20 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function btns() {
    return Array.from(document.querySelectorAll('button,a,div,span,[role=button],input[type=button]')).filter(vis);
  }
  var all = btns();
  var backs = all.filter(function (e) { return /back to deals/i.test(txt(e)); });
  if (!backs.length) return null;
  var start = all.find(function (e) { return /^start deal$/i.test(txt(e)); });
  var pick = backs[0];
  if (start) {
    var sr = start.getBoundingClientRect();
    var below = backs.filter(function (e) { return e.getBoundingClientRect().top >= sr.top - 4; });
    below.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    if (below.length) pick = below[0];
  }
  try { pick.scrollIntoView({ block: 'center' }); } catch (e) {}
  var r = pick.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(pick) };
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
    """Tracking modal or claim-deal dismiss — not the ALERT Continue link."""
    if await _alert_popup_visible(page):
        return await _native_deal_alert_continue(page)
    for frame in page.frames:
        try:
            target = await frame.evaluate(DEAL_WALL_INTERSTITIAL_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    for label in ("CLAIM DEAL ANYWAY", "Claim Deal Anyway", "CONFIRM TRACKING"):
        if await _native_click_text(page, label):
            await asyncio.sleep(1.5)
            return True
    return False


async def _alert_popup_visible(page) -> bool:
    """True when ALERT modal is on screen (Go back + Continue link)."""
    for frame in page.frames:
        try:
            snippet = str(
                await frame.evaluate(
                    "() => (document.body.innerText || '').slice(0, 2200).toLowerCase()"
                )
            )
            if "alert!" in snippet and "go back" in snippet and "continue" in snippet:
                return True
        except Exception:
            continue
    return False


async def _native_deal_alert_continue(page) -> bool:
    """Step 7: ALERT popup — underlined Continue link (never Go back)."""
    for attempt in range(8):
        for frame in await _deal_wall_frames(page) + [page.main_frame]:
            try:
                target = await frame.evaluate(NATIVE_ALERT_CONTINUE_JS)
                if target and target.get("x") is not None:
                    await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                    await asyncio.sleep(1.5)
                    if not await _alert_popup_visible(page):
                        ctx = page.context
                        ctx._krx_l1_footer_done = True
                        ctx._krx_level_cards_done = 0
                        ctx._krx_start_deal_clicked_for_modal = False
                        _set_deal_state(ctx, "idle")
                        setattr(ctx, "_krx_wall_level", "L3")
                        for fr in page.frames:
                            try:
                                await fr.evaluate(
                                    "() => { window.__krxDealKeys = {}; window.__krxLevelCardsDone = 0; }"
                                )
                            except Exception:
                                continue
                        _log_deal_step(page, "step7: ALERT Continue — Level 3")
                        return True
            except Exception:
                continue
        try:
            loc = page.get_by_role("link", name=re.compile(r"^Continue$", re.I)).first
            if await loc.count() > 0 and await _human_click_locator(page, loc):
                await asyncio.sleep(1.5)
                if not await _alert_popup_visible(page):
                    ctx = page.context
                    ctx._krx_l1_footer_done = True
                    ctx._krx_level_cards_done = 0
                    setattr(ctx, "_krx_wall_level", "L3")
                    _log_deal_step(page, "step7: ALERT Continue link")
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.35)
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


def _count_offer_tabs(page) -> int:
    """Extra browser tabs opened from START DEAL (offer pages — kept open)."""
    main = page
    count = 0
    for p in page.context.pages:
        if p == main:
            continue
        try:
            u = (p.url or "").lower()
        except Exception:
            u = ""
        if any(k in u for k in ("policies", "privacy", "terms", "flashrewards", "contact.")):
            continue
        count += 1
    return count


_DEAL_STATES = ("idle", "on_no_modal", "on_howto", "start_clicked", "need_back")


def _log_deal_step(page, msg: str) -> None:
    """Debug logging for deal wall automation (always, or when KRX_DEAL_DEBUG=1)."""
    if os.environ.get("KRX_DEAL_DEBUG", "1").lower() not in ("0", "false", "no", "off"):
        try:
            url = (page.url or "")[:80]
        except Exception:
            url = ""
        logger.info("[deal_wall] %s | url=%s", msg, url)


def _get_deal_state(ctx) -> str:
    state = getattr(ctx, "_krx_deal_state", "idle")
    return state if state in _DEAL_STATES else "idle"


def _set_deal_state(ctx, state: str) -> None:
    if state in _DEAL_STATES:
        ctx._krx_deal_state = state


async def _sync_deal_state_from_dom(page) -> str:
    """Sync _krx_deal_state from visible modals; preserve mid-cycle states."""
    ctx = page.context
    if getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
        _set_deal_state(ctx, "need_back")
        return "need_back"
    cur = _get_deal_state(ctx)
    if cur in ("start_clicked", "need_back"):
        return cur
    if await _how_to_complete_modal_open(page):
        _set_deal_state(ctx, "on_howto")
        return "on_howto"
    if await _page_has_text_in_deal_frames(page, "do you already have"):
        _set_deal_state(ctx, "on_no_modal")
        return "on_no_modal"
    if await _page_has_text(page, "do you already have", "already have this deal"):
        _set_deal_state(ctx, "on_no_modal")
        return "on_no_modal"
    _set_deal_state(ctx, "idle")
    return "idle"


async def _deal_wall_step_allowed(page) -> bool:
    """Prevent double _native_deal_wall_step within 1.2s (never throttle mid-cycle)."""
    ctx = page.context
    state = _get_deal_state(ctx)
    if getattr(ctx, "_krx_start_deal_clicked_for_modal", False) or state in (
        "start_clicked",
        "need_back",
        "on_no_modal",
        "on_howto",
    ):
        return True
    now = time.monotonic()
    last = float(getattr(ctx, "_krx_deal_step_ts", 0.0) or 0.0)
    if now - last < 0.85:
        _log_deal_step(page, f"step throttled ({now - last:.2f}s since last)")
        return False
    ctx._krx_deal_step_ts = now
    return True


async def _wait_deal_condition(page, fn, timeout_s: float = 12.0) -> bool:
    """Poll until async predicate(fn(page)) is True."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if await fn(page):
                return True
        except Exception:
            pass
        await asyncio.sleep(0.35)
    return False


async def _how_to_complete_modal_open(page) -> bool:
    """True when how-to-complete modal is visible (must include 'how to complete')."""
    if await _page_has_text_in_deal_frames(page, "how to complete"):
        return True
    if not await _page_has_text(page, "how to complete"):
        return False
    has_start = await _page_has_text(page, "START DEAL", "Start Deal")
    has_back = await _page_has_text(page, "BACK TO DEALS", "Back to Deals")
    return has_start or has_back


async def _already_have_modal_open(page) -> bool:
    if await _page_has_text_in_deal_frames(page, "do you already have"):
        return True
    return await _page_has_text(page, "do you already have", "already have this deal")


async def _sync_guided_deal_counters(page, *, l3: bool = False) -> None:
    """Keep guided cycle counters aligned with completed deal cards."""
    ctx = page.context
    done = await _get_level_cards_done(page)
    if l3:
        ctx._krx_guided_l3_cycles_done = done
    else:
        ctx._krx_guided_cycles_done = done


async def _native_deal_how_to_complete_step(page) -> bool:
    """
    User steps 3–5 on how-to modal:
      3 START DEAL → 4 offer tab open + main tab wapas → 5 BACK TO DEALS
    """
    ctx = page.context

    if not await _how_to_complete_modal_open(page):
        if (
            getattr(ctx, "_krx_start_deal_clicked_for_modal", False)
            and await _how_to_complete_modal_closed(page)
        ):
            ctx._krx_start_deal_clicked_for_modal = False
            _set_deal_state(ctx, "idle")
            await _increment_level_cards_done(page)
            body = await _retail_body_text(page)
            await _sync_guided_deal_counters(page, l3=_is_level3_wall(body))
            _log_deal_step(page, "how-to modal closed — deal counted")
            return True
        return False

    if not getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
        if not await _native_deal_guided_step(page, 3):
            return False
    if not await _native_deal_guided_step(page, 4):
        return False
    return await _native_deal_guided_step(page, 5)


async def _mark_deal_flow_conversion(page, cfg: SmartFunnelConfig) -> None:
    """Full L1+L3 user flow finished — allow conversion phase."""
    ctx = page.context
    ctx._krx_l3_complete = True
    try:
        await page.evaluate(
            "() => { window.__krxConversionSignal = true; window.__krxDone = true; }"
        )
        for frame in page.frames:
            try:
                await frame.evaluate(
                    "() => { window.__krxConversionSignal = true; window.__krxDone = true; }"
                )
            except Exception:
                continue
    except Exception:
        pass
    _log_deal_step(page, "deal flow complete — conversion ready")


async def _native_deal_start_deal(page) -> bool:
    """Click START DEAL on how-to-complete modal (red button above BACK TO DEALS)."""
    if not await _how_to_complete_modal_open(page):
        return False
    _log_deal_step(page, "step3: click START DEAL on how-to modal")

    frames: List[Any] = []
    seen = set()
    for fr in [page.main_frame] + await _deal_wall_frames(page) + list(page.frames):
        if fr in seen:
            continue
        seen.add(fr)
        frames.append(fr)

    start_re = re.compile(r"^START DEAL!?$", re.I)

    async def _clicked_ok() -> bool:
        await asyncio.sleep(0.6)
        try:
            extras = [p for p in page.context.pages if p != page]
            if extras:
                return True
        except Exception:
            pass
        if _count_offer_tabs(page) > 0:
            return True
        try:
            for p in page.context.pages:
                if p == page:
                    continue
                u = (p.url or "").lower()
                if u and "eward4spot" not in u and "displayoptoffers" not in u:
                    if not any(k in u for k in ("policies", "privacy", "terms", "flashrewards")):
                        return True
        except Exception:
            pass
        return False

    for attempt in range(10):
        for frame in frames:
            try:
                target = await frame.evaluate(START_DEAL_DIRECT_CLICK_JS)
                if target and target.get("x") is not None:
                    await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                    if await _clicked_ok():
                        _log_deal_step(page, f"START DEAL ok (direct) attempt {attempt + 1}")
                        return True
            except Exception:
                continue

        for frame in frames:
            try:
                target = await frame.evaluate(NATIVE_START_DEAL_JS)
                if target and target.get("x") is not None:
                    for _ in range(2):
                        await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                        await asyncio.sleep(0.2)
                    if await _clicked_ok():
                        _log_deal_step(page, "START DEAL ok (coords)")
                        return True
            except Exception:
                continue

        for frame in frames:
            try:
                for loc_src in (
                    frame.get_by_role("button", name=start_re),
                    frame.locator("button, a, input[type=button], [role=button]").filter(
                        has_text=start_re
                    ),
                    frame.get_by_text("START DEAL", exact=True),
                ):
                    count = min(await loc_src.count(), 8)
                    best = None
                    best_area = 0.0
                    for i in range(count):
                        el = loc_src.nth(i)
                        try:
                            text = (await el.inner_text(timeout=400)).strip()
                            if not start_re.match(text):
                                continue
                            box = await el.bounding_box()
                        except Exception:
                            continue
                        if not box or box["height"] < 24 or box["width"] < 70:
                            continue
                        area = box["width"] * box["height"]
                        if area > best_area:
                            best_area = area
                            best = el
                    if best is None:
                        continue
                    try:
                        await best.evaluate(
                            """el => {
                              var cur = el;
                              for (var i = 0; i < 5; i++) {
                                if (!cur) break;
                                var tag = (cur.tagName || '').toUpperCase();
                                if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT') { cur.click(); return; }
                                cur = cur.parentElement;
                              }
                              el.click();
                            }"""
                        )
                    except Exception:
                        try:
                            await best.click(force=True, timeout=5000)
                        except Exception:
                            if not await _human_click_locator(page, best):
                                continue
                    if await _clicked_ok():
                        _log_deal_step(page, "START DEAL ok (locator)")
                        return True
            except Exception:
                continue

        await asyncio.sleep(0.35)

    return False


async def _how_to_complete_modal_closed(page) -> bool:
    """True when deal list is back (modal gone)."""
    if await _how_to_complete_modal_open(page):
        return False
    body = await _retail_body_text(page)
    return any(
        k in body
        for k in (
            "level 1 deals",
            "level 2 deals",
            "level 3 deals",
            "best match for you",
            "your cost:",
            "continue instructions below",
        )
    )


async def _native_deal_start_deal_with_tab(page, timeout_s: float = 14.0) -> bool:
    """Click START DEAL and wait for offer tab — tab stays open, main page refocused."""
    context = page.context
    before_pages = set(context.pages)
    try:
        async with context.expect_page(timeout=int(timeout_s * 1000)) as page_info:
            if not await _native_deal_start_deal(page):
                return False
        await page_info.value
    except Exception:
        deadline = time.monotonic() + timeout_s
        found = False
        while time.monotonic() < deadline:
            if len(context.pages) > len(before_pages):
                found = True
                break
            await asyncio.sleep(0.35)
        if not found:
            return False
    await asyncio.sleep(0.6)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return True


async def _native_deal_click_back_to_deals(page) -> bool:
    """Click BACK TO DEALS — white outlined button below START DEAL; force double-tap."""
    _log_deal_step(page, "attempting BACK TO DEALS click")

    async def _force_tap(x: float, y: float, frame=None) -> None:
        if frame is not None:
            await _frame_mouse_click_at(page, frame, x, y)
        else:
            await _trusted_page_tap(page, x, y)

    for frame in await _deal_wall_frames(page):
        try:
            target = await frame.evaluate(NATIVE_BACK_TO_DEALS_JS)
            if target and target.get("x") is not None:
                x, y = float(target["x"]), float(target["y"])
                await _force_tap(x, y, frame)
                await asyncio.sleep(0.35)
                await _force_tap(x, y, frame)
                _log_deal_step(page, "BACK TO DEALS via deal frame JS (double-tap)")
                return True
        except Exception:
            continue

    for frame in page.frames:
        try:
            target = await frame.evaluate(NATIVE_BACK_TO_DEALS_JS)
            if target and target.get("x") is not None:
                x, y = float(target["x"]), float(target["y"])
                await _force_tap(x, y, frame)
                await asyncio.sleep(0.35)
                await _force_tap(x, y, frame)
                _log_deal_step(page, "BACK TO DEALS via JS coords (double-tap)")
                return True
        except Exception:
            continue

    for frame in page.frames:
        try:
            loc = frame.get_by_text("BACK TO DEALS", exact=True).first
            if await loc.count() > 0:
                fe = await frame.frame_element()
                box = await loc.bounding_box()
                fbox = await fe.bounding_box()
                if box and fbox:
                    cx = fbox["x"] + box["x"] + box["width"] / 2
                    cy = fbox["y"] + box["y"] + box["height"] / 2
                    await _force_tap(cx, cy)
                    await asyncio.sleep(0.35)
                    await _force_tap(cx, cy)
                    _log_deal_step(page, "BACK TO DEALS via frame locator (double-tap)")
                    return True
        except Exception:
            continue

    try:
        loc = page.get_by_text("BACK TO DEALS", exact=True).first
        if await loc.count() > 0:
            box = await loc.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await _force_tap(cx, cy)
                await asyncio.sleep(0.35)
                await _force_tap(cx, cy)
                _log_deal_step(page, "BACK TO DEALS via page locator (double-tap)")
                return True
    except Exception:
        pass

    for label in ("BACK TO DEALS", "Back to Deals"):
        if await _native_click_text(page, label):
            await asyncio.sleep(0.35)
            await _native_click_text(page, label)
            _log_deal_step(page, f"BACK TO DEALS via text click {label!r}")
            return True
    return False


async def _native_deal_back_to_deals_wait(page, timeout_s: float = 15.0) -> bool:
    """After START DEAL tab opens: focus main page and click BACK TO DEALS until modal closes."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            await page.bring_to_front()
        except Exception:
            pass
        if await _how_to_complete_modal_closed(page):
            try:
                await page.evaluate("try { window.scrollTo(0, 0); } catch (e) {}")
            except Exception:
                pass
            return True
        if await _native_deal_click_back_to_deals(page):
            await asyncio.sleep(1.8)
            if await _how_to_complete_modal_closed(page):
                try:
                    await page.evaluate("try { window.scrollTo(0, 0); } catch (e) {}")
                except Exception:
                    pass
                return True
        await asyncio.sleep(0.5)
    return False


async def _native_deal_start_and_return(page, timeout_s: float = 18.0) -> bool:
    """START DEAL → new tab (stay open) → main page → BACK TO DEALS. Never double START DEAL."""
    if _count_offer_tabs(page) > 0 and await _how_to_complete_modal_open(page):
        return await _native_deal_back_to_deals_wait(page, timeout_s=15.0)
    if not await _native_deal_start_deal_with_tab(page, timeout_s=timeout_s):
        return False
    return await _native_deal_back_to_deals_wait(page, timeout_s=15.0)


async def _native_deal_modal_no_wait(page, timeout_s: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await _page_has_text(page, "do you already have", "already have this deal"):
            if await _native_deal_modal_no(page):
                return True
        await asyncio.sleep(0.4)
    return False


async def _native_deal_click_card_continue(page) -> bool:
    """Click red CONTINUE on a random unclicked deal card (not footer)."""
    import random

    tried: set = set()
    for frame in await _deal_wall_frames(page):
        tried.add(frame)
        try:
            target = await frame.evaluate(NATIVE_DEAL_CARD_CONTINUE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                return True
        except Exception:
            continue

    for frame in page.frames:
        if frame in tried:
            continue
        try:
            target = await frame.evaluate(NATIVE_DEAL_CARD_CONTINUE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                return True
        except Exception:
            continue

    candidates: List[Any] = []
    for frame in page.frames:
        try:
            locs = frame.get_by_text("CONTINUE", exact=True)
            count = await locs.count()
            for i in range(count):
                loc = locs.nth(i)
                try:
                    box = await loc.bounding_box()
                    if not box or box["height"] < 18 or box["width"] < 60:
                        continue
                    if box["y"] < 40:
                        continue
                    parent = await loc.evaluate(
                        """el => {
                          var p = el.closest('div,section,article,li');
                          return ((p && p.innerText) || '').slice(0, 320).toLowerCase();
                        }"""
                    )
                    parent = str(parent or "").lower()
                    if any(
                        k in parent
                        for k in (
                            "must complete 1 deal to continue",
                            "must complete 3 deal",
                            "complete 25 deals",
                            "complete 20 deals total",
                        )
                    ) and "your cost:" not in parent:
                        continue
                    if "your cost:" in parent or "$0.00" in parent or "$0 to" in parent:
                        candidates.append((loc, box, parent))
                except Exception:
                    continue
        except Exception:
            continue

    if not candidates:
        try:
            locs = page.get_by_text("CONTINUE", exact=True)
            count = await locs.count()
            for i in range(count):
                loc = locs.nth(i)
                box = await loc.bounding_box()
                if box and box["height"] >= 18 and box["y"] > 80 and box["y"] < 780:
                    candidates.append((loc, box, ""))
        except Exception:
            pass

    if not candidates:
        return False

    loc, box, parent = random.choice(candidates)
    try:
        await loc.scroll_into_view_if_needed(timeout=4000)
        box = await loc.bounding_box() or box
        deal_key = f"{parent[:80]}|{round(box['y'])}|{round(box['x'])}"
        await _trusted_page_tap(
            page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        )
        for frame in page.frames:
            try:
                await frame.evaluate(
                    "(k) => { window.__krxDealKeys = window.__krxDealKeys || {}; window.__krxDealKeys[k] = 1; }",
                    deal_key,
                )
            except Exception:
                continue
        return True
    except Exception:
        return False


async def _native_deal_run_full_cycle(page, timeout_s: float = 55.0) -> bool:
    """
    One full deal cycle — exact user SS steps 1–5:
      1 CONTINUE → 2 NO → 3 START DEAL → 4 main tab → 5 BACK TO DEALS
    """
    ctx = page.context
    deadline = time.monotonic() + timeout_s

    async def _run_step(step: int) -> bool:
        if time.monotonic() > deadline:
            return False
        if step == 2:
            for attempt in range(12):
                if await _native_deal_modal_no(page):
                    return True
                await asyncio.sleep(0.35)
            return False
        ok = await _native_deal_guided_step(page, step)
        if ok or step in (3, 4):
            return ok
        if step == 1:
            await asyncio.sleep(0.45)
            return await _native_deal_guided_step(page, 1)
        return ok

    if getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
        if await _run_step(4) and await _run_step(5):
            return True
        return await _native_deal_how_to_complete_step(page)

    if await _how_to_complete_modal_open(page):
        if getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
            if await _run_step(4) and await _run_step(5):
                return True
        for s in (3, 4, 5):
            if not await _run_step(s):
                return False
        return True

    if await _already_have_modal_open(page):
        for s in (2, 3, 4, 5):
            if s == 3 and not await _wait_deal_condition(page, _how_to_complete_modal_open, 12.0):
                _log_deal_step(page, "timeout waiting for how-to after NO")
                return False
            if not await _run_step(s):
                return False
        return True

    if not await _run_step(1):
        try:
            await page.evaluate("try { window.scrollBy(0, 380); } catch (e) {}")
        except Exception:
            pass
        await asyncio.sleep(0.5)
        if not await _run_step(1):
            _log_deal_step(page, "no deal card CONTINUE found")
            return False

    if not await _wait_deal_condition(page, _already_have_modal_open, min(14.0, timeout_s * 0.35)):
        _log_deal_step(page, "timeout waiting for already-have modal after card")
        return False

    for s in (2, 3, 4, 5):
        if s == 3 and not await _wait_deal_condition(page, _how_to_complete_modal_open, 12.0):
            _log_deal_step(page, "timeout waiting for how-to modal after NO")
            return False
        if not await _run_step(s):
            return False
    return True


async def _native_deal_footer_continue_trigger(page) -> bool:
    """Step 6: footer grey CONTINUE under 'You must complete 1 deal to continue!'"""
    try:
        await page.evaluate("try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}")
    except Exception:
        pass
    await asyncio.sleep(0.6)
    for frame in await _deal_wall_frames(page):
        try:
            target = await frame.evaluate(FOOTER_GREY_CONTINUE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(0.35)
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                _log_deal_step(page, "step6: footer grey CONTINUE clicked")
                return True
        except Exception:
            continue
    for frame in await _deal_wall_frames(page):
        try:
            target = await frame.evaluate(NATIVE_DEAL_MUST_COMPLETE_JS)
            if target and target.get("x") is not None and target.get("kind") == "footer_continue":
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                return True
        except Exception:
            continue
    frames_extra = list(await _deal_wall_frames(page))
    seen = set(frames_extra)
    for frame in page.frames:
        if frame not in seen:
            frames_extra.append(frame)
    for frame in frames_extra:
        try:
            target = await frame.evaluate(NATIVE_DEAL_MUST_COMPLETE_JS)
            if target and target.get("x") is not None:
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                await asyncio.sleep(1.2)
                return True
        except Exception:
            continue
    return False


async def _native_deal_keep_offer_tab_return_main(page, timeout_s: float = 20.0) -> bool:
    """Leave START DEAL offer tab(s) open; bring main deal page back to front."""
    main = page
    ctx = page.context
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        offer_tabs = []
        for popup in ctx.pages:
            if popup == main:
                continue
            try:
                purl = (popup.url or "").lower()
            except Exception:
                purl = ""
            if any(k in purl for k in ("policies", "privacy", "terms", "flashrewards", "contact.")):
                continue
            offer_tabs.append(popup)
        if offer_tabs:
            for popup in offer_tabs:
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
            try:
                await main.bring_to_front()
            except Exception:
                pass
            ctx._krx_offer_tabs_kept = len(offer_tabs)
            _log_deal_step(page, f"offer tab(s) open={len(offer_tabs)} — returned to main deal page")
            return True
        await asyncio.sleep(0.35)
    try:
        await main.bring_to_front()
    except Exception:
        pass
    return _count_offer_tabs(page) > 0


async def _wait_for_offer_tab_open(page, timeout_s: float = 18.0) -> bool:
    """Wait for START DEAL popup tab — leave it open, return focus to main deal page."""
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
                    await popup.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(2.0)
            try:
                await main.bring_to_front()
            except Exception:
                pass
            return True
        await asyncio.sleep(0.4)
    try:
        await main.bring_to_front()
    except Exception:
        pass
    return False


async def _wait_and_handle_offer_tabs(page, timeout_s: float = 16.0) -> None:
    """Legacy alias — open tab stays open; main page brought front."""
    await _wait_for_offer_tab_open(page, timeout_s=timeout_s)


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
    """Bring main deal page front — offer tabs stay open until visit ends."""
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


async def _native_deal_handle_blocking_modal(page, cfg: SmartFunnelConfig) -> bool:
    """User step order: already-have NO -> how-to -> ALERT — always before deal card clicks."""
    if await _alert_popup_visible(page):
        _log_deal_step(page, "blocking modal: ALERT Continue")
        return await _native_deal_alert_continue(page)
    if await _how_to_complete_modal_open(page):
        _log_deal_step(page, "blocking modal: how-to / START DEAL / BACK TO DEALS")
        return await _native_deal_how_to_complete_step(page)
    if await _already_have_modal_open(page):
        _set_deal_state(page.context, "on_no_modal")
        _log_deal_step(page, "blocking modal: Do you already have -> NO")
        if await _native_deal_modal_no(page):
            await asyncio.sleep(0.8)
            return True
        return False
    return False


async def _native_deal_modal_no(page) -> bool:
    """Click 'Do you already have X?' modal NO — red button below YES (Whatnot/Chime/etc)."""
    if not await _already_have_modal_open(page):
        return False
    _log_deal_step(page, "step2: click NO on already-have modal")

    async def _dismissed() -> bool:
        await asyncio.sleep(0.55)
        return not await _already_have_modal_open(page)

    frames: List[Any] = []
    seen = set()
    for fr in [page.main_frame] + await _deal_wall_frames(page) + list(page.frames):
        if fr in seen:
            continue
        seen.add(fr)
        frames.append(fr)

    no_re = re.compile(r"^NO!?$", re.I)

    for attempt in range(10):
        # A) YES ke neeche NO — JS + mouse (eward4spot / Whatnot modal)
        for frame in frames:
            try:
                target = await frame.evaluate(MODAL_NO_BELOW_YES_JS)
                if not target or target.get("x") is None:
                    continue
                if not target.get("clicked"):
                    await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                    await asyncio.sleep(0.2)
                await _frame_mouse_click_at(page, frame, float(target["x"]), float(target["y"]))
                if await _dismissed():
                    _log_deal_step(page, f"NO ok ({target.get('method')}) attempt {attempt + 1}")
                    _set_deal_state(page.context, "on_howto")
                    return True
            except Exception:
                continue

        # B) Direct JS click chain
        for frame in frames:
            try:
                result = await frame.evaluate(MODAL_NO_DIRECT_CLICK_JS)
                if result and result.get("ok") and result.get("x") is not None:
                    await _frame_mouse_click_at(page, frame, float(result["x"]), float(result["y"]))
                    if await _dismissed():
                        _log_deal_step(page, f"NO ok direct ({result.get('method')})")
                        _set_deal_state(page.context, "on_howto")
                        return True
            except Exception:
                continue

        # C) Playwright locator — lowest exact NO (page viewport coords)
        for frame in frames:
            try:
                for loc_src in (
                    frame.get_by_role("button", name=no_re),
                    frame.locator("button, a, input[type=button], input[type=submit], [role=button]").filter(
                        has_text=no_re
                    ),
                    frame.get_by_text("NO", exact=True),
                ):
                    count = min(await loc_src.count(), 16)
                    best = None
                    best_y = -1.0
                    for i in range(count):
                        el = loc_src.nth(i)
                        try:
                            text = (await el.inner_text(timeout=400)).strip()
                            if not no_re.match(text):
                                continue
                            box = await el.bounding_box()
                        except Exception:
                            continue
                        if not box or box["height"] < 22 or box["width"] < 50:
                            continue
                        if box["y"] > best_y:
                            best_y = box["y"]
                            best = el
                    if best is None:
                        continue
                    try:
                        await best.evaluate(
                            """el => {
                              var cur = el;
                              for (var i = 0; i < 5; i++) {
                                if (!cur) break;
                                var tag = (cur.tagName || '').toUpperCase();
                                if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT') { cur.click(); return; }
                                if (cur.getAttribute && cur.getAttribute('role') === 'button') { cur.click(); return; }
                                cur = cur.parentElement;
                              }
                              el.click();
                            }"""
                        )
                    except Exception:
                        try:
                            await best.click(force=True, timeout=4000)
                        except Exception:
                            if not await _human_click_locator(page, best):
                                continue
                    if await _dismissed():
                        _log_deal_step(page, "NO ok locator")
                        _set_deal_state(page.context, "on_howto")
                        return True
            except Exception:
                continue

        # D) YES ke neeche coordinate guess
        for frame in frames:
            try:
                yes_loc = frame.get_by_text("YES", exact=True).first
                if await yes_loc.count() == 0:
                    continue
                box = await yes_loc.bounding_box()
                if not box or box["height"] < 20:
                    continue
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] + max(box["height"] * 0.55, 42)
                await _human_page_click(page, cx, cy)
                if await _dismissed():
                    _log_deal_step(page, "NO ok below YES coords")
                    _set_deal_state(page.context, "on_howto")
                    return True
            except Exception:
                continue

        await asyncio.sleep(0.35)

    return False


async def _install_offer_popup_handler(page) -> None:
    """Track offer popups from START DEAL — leave tabs open, keep main page active."""
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
        await asyncio.sleep(1.5)
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
    """3 random unique deal cards per level (L1 then L3). Ignore page footer 'complete 1 deal' copy."""
    del body
    return 3


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
    if "complete 3 more deal" in s or "next step: complete 3" in s:
        return "L3"
    if "complete 3 deal" in s or "complete three deal" in s:
        return "L3"
    return "LX"


async def _sync_deal_level_state(page, body: str) -> None:
    key = _deal_wall_level_key(body)
    ctx = page.context
    if getattr(ctx, "_krx_wall_level", None) == key:
        return
    ctx._krx_wall_level = key
    ctx._krx_level_cards_done = 0
    ctx._krx_start_deal_clicked_for_modal = False
    _set_deal_state(ctx, "idle")
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


async def _native_deal_return_to_wall(page) -> bool:
    """After START DEAL tab opens, click BACK TO DEALS and return to deal list."""
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return await _native_deal_back_to_deals_wait(page, timeout_s=12.0)


async def _native_deal_complete_one_offer(page) -> bool:
    """Legacy wrapper — deal wall step now runs one action per call."""
    return await _native_deal_wall_step(page, SmartFunnelConfig())


async def _native_deal_card_click(page) -> bool:
    """Alias — one full offer cycle."""
    return await _native_deal_complete_one_offer(page)


def _is_level3_wall(body: str) -> bool:
    s = (body or "").lower()
    return any(
        k in s
        for k in (
            "level 3 deals",
            "complete 3 more deal",
            "next step: complete 3",
            "complete 3 deal",
            "keep going",
            "qualify for",
            "100 cashout",
        )
    )


def _is_level1_wall(body: str) -> bool:
    s = (body or "").lower()
    if _is_level3_wall(s):
        return False
    return any(
        k in s
        for k in (
            "level 1 deals",
            "next step: complete 1 deal",
            "must complete 1 deal",
        )
    )


async def _deal_wall_frames(page) -> List[Any]:
    """Frames that contain the active deal wall (reward4spot iframe)."""
    hits: List[tuple] = []
    for frame in page.frames:
        try:
            text = str(
                await frame.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 2500).toLowerCase()"
                )
            )
            score = 0
            if any(k in text for k in ("level 1 deals", "level 3 deals", "how to complete", "best match for you")):
                score += 80
            if "complete 3 more deal" in text or "next step: complete" in text:
                score += 60
            if "do you already have" in text or "start deal" in text:
                score += 100
            if "eward4spot" in (frame.url or "").lower() or "displayoptoffers" in (frame.url or "").lower():
                score += 50
            if score > 0:
                hits.append((score, frame))
        except Exception:
            continue
    hits.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in hits] or [page.main_frame]


async def _page_has_text_in_deal_frames(page, *needles: str) -> bool:
    frames = await _deal_wall_frames(page)
    for needle in needles:
        if not needle:
            continue
        for frame in frames:
            try:
                if await frame.get_by_text(needle, exact=False).count() > 0:
                    return True
            except Exception:
                continue
    return await _page_has_text(page, *needles)


async def _native_deal_smart_workflow(page, cfg: SmartFunnelConfig, timeout_s: float = 110.0) -> bool:
    """
    Full deal-wall brain — L1 and L3:
      3 deals (CONTINUE→NO→START DEAL→BACK TO DEALS) per level
      L1: footer grey CONTINUE → ALERT Continue link → L3
      L3: 3 more deals → conversion ready
    """
    ctx = page.context
    ctx._krx_deal_step_ts = 0.0
    deadline = time.monotonic() + timeout_s
    progress = False

    while time.monotonic() < deadline:
        body = await _retail_body_text(page)
        await _sync_deal_level_state(page, body)
        level_key = getattr(ctx, "_krx_wall_level", None) or _deal_wall_level_key(body)
        is_l3 = _is_level3_wall(body) or level_key == "L3"
        is_l1 = _is_level1_wall(body) or level_key == "L1"

        if any(
            k in body
            for k in ("emailed to you", "explore offers from our sponsors", "status emailed")
        ):
            if await _native_reward_status_optin_step(page, cfg):
                progress = True
            await asyncio.sleep(0.8)
            continue

        if await _alert_popup_visible(page):
            _log_deal_step(page, "smart: ALERT Continue link")
            if await _native_deal_alert_continue(page):
                ctx._krx_l1_footer_done = True
                progress = True
                await asyncio.sleep(2.5)
                continue
            return progress

        if await _already_have_modal_open(page):
            _log_deal_step(page, "smart: already-have modal -> NO")
            if await _native_deal_modal_no(page):
                progress = True
                await asyncio.sleep(0.8)
                continue
            await asyncio.sleep(0.35)
            continue

        if await _how_to_complete_modal_open(page):
            _log_deal_step(page, "smart: how-to modal -> START DEAL / BACK TO DEALS")
            if await _native_deal_how_to_complete_step(page):
                progress = True
                await asyncio.sleep(0.8)
                continue
            await asyncio.sleep(0.35)
            continue

        state = await _sync_deal_state_from_dom(page)
        mid_cycle = bool(getattr(ctx, "_krx_start_deal_clicked_for_modal", False)) or state in (
            "start_clicked",
            "need_back",
        )
        if (
            mid_cycle
            or await _how_to_complete_modal_open(page)
            or await _already_have_modal_open(page)
        ):
            if await _native_deal_run_full_cycle(page):
                progress = True
                await asyncio.sleep(1.0)
                continue
            await asyncio.sleep(0.45)
            continue

        if any(k in body for k in ("claim deal anyway", "confirm tracking", "didn't confirm")):
            if await _native_deal_interstitial_step(page):
                progress = True
            await asyncio.sleep(0.8)
            continue

        done = await _get_level_cards_done(page)
        required = _deals_required_for_wall(body)
        _log_deal_step(
            page,
            f"smart: level={level_key} L1={is_l1} L3={is_l3} deals={done}/{required}",
        )

        if done >= required:
            if is_l1 and not getattr(ctx, "_krx_l1_footer_done", False):
                _log_deal_step(page, "smart: L1 footer CONTINUE (must complete 1 deal)")
                for frame in await _deal_wall_frames(page):
                    try:
                        await frame.evaluate(
                            "try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(0.8)
                if await _native_deal_footer_continue_trigger(page):
                    ctx._krx_l1_footer_done = True
                    progress = True
                    await asyncio.sleep(2.0)
                    continue
                await asyncio.sleep(0.5)
                continue

            if is_l3:
                ctx._krx_l3_complete = True
                _log_deal_step(page, "smart: L3 complete — 3 deals done, conversion ready")
                await _mark_deal_flow_conversion(page, cfg)
                return True

            if getattr(ctx, "_krx_l1_footer_done", False):
                await asyncio.sleep(0.5)
                continue

        if await _native_deal_run_full_cycle(page):
            progress = True
            await asyncio.sleep(1.0)
            continue

        try:
            for frame in await _deal_wall_frames(page):
                try:
                    await frame.evaluate("try { window.scrollBy(0, 320); } catch (e) {}")
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(0.6)

    return progress


async def _reset_deal_level_state(page) -> None:
    ctx = page.context
    ctx._krx_level_cards_done = 0
    ctx._krx_start_deal_clicked_for_modal = False
    _set_deal_state(ctx, "idle")
    setattr(ctx, "_krx_wall_level", None)
    for frame in page.frames:
        try:
            await frame.evaluate(
                "() => { window.__krxDealKeys = {}; window.__krxLevelCardsDone = 0; }"
            )
        except Exception:
            continue


async def _native_deal_guided_step(page, step: int) -> bool:
    """
    User SS deal steps (exact order):
      1 random deal card CONTINUE
      2 NO on 'Do you already have?'
      3 START DEAL (once)
      4 offer tab open — main tab wapas
      5 BACK TO DEALS
      6 footer grey CONTINUE ('must complete 1 deal')
      7 ALERT Continue link (not Go back)
    """
    if step == 1:
        if await _already_have_modal_open(page):
            return False
        _log_deal_step(page, "guided step 1: random deal card CONTINUE")
        return await _native_deal_click_card_continue(page)
    if step == 2:
        if not await _already_have_modal_open(page):
            return False
        _log_deal_step(page, "guided step 2: NO on 'Do you already have?' modal")
        if await _native_deal_modal_no(page):
            return True
        return False
    if step == 3:
        if not await _wait_deal_condition(page, _how_to_complete_modal_open, 12.0):
            return False
        if not await _how_to_complete_modal_open(page):
            return False
        ctx = page.context
        if getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
            return True
        _log_deal_step(page, "guided step 3: START DEAL (once only)")
        for attempt in range(10):
            clicked = await _native_deal_start_deal(page)
            if clicked:
                ctx._krx_start_deal_clicked_for_modal = True
                _set_deal_state(ctx, "start_clicked")
                _set_deal_state(ctx, "need_back")
                return True
            await asyncio.sleep(0.35)
        ctx._krx_start_deal_clicked_for_modal = False
        _set_deal_state(ctx, "on_howto")
        return False
    if step == 4:
        ctx = page.context
        if not getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
            return False
        _log_deal_step(page, "guided step 4: offer tab open rakho, main deal tab par wapas aao")
        return await _native_deal_keep_offer_tab_return_main(page)
    if step == 5:
        ctx = page.context
        if not getattr(ctx, "_krx_start_deal_clicked_for_modal", False):
            return False
        if not await _how_to_complete_modal_open(page):
            if await _deal_wall_on_page(page):
                ctx._krx_start_deal_clicked_for_modal = False
                _set_deal_state(ctx, "idle")
                return True
            return False
        _log_deal_step(page, "guided step 5: BACK TO DEALS → main deal page")
        if await _native_deal_back_to_deals_wait(page, timeout_s=20.0):
            ctx._krx_start_deal_clicked_for_modal = False
            _set_deal_state(ctx, "idle")
            await _increment_level_cards_done(page)
            return True
        return False
    if step == 6:
        body = await _retail_body_text(page)
        if not re.search(r"must complete.*deal to continue", body, re.I):
            try:
                await page.evaluate("try { window.scrollTo(0, document.body.scrollHeight); } catch (e) {}")
            except Exception:
                pass
            await asyncio.sleep(0.5)
            body = await _retail_body_text(page)
        if not re.search(r"must complete.*deal to continue", body, re.I):
            return False
        _log_deal_step(page, "guided step 6: footer grey CONTINUE (must complete 1 deal)")
        return await _native_deal_footer_continue_trigger(page)
    if step == 7:
        if not await _alert_popup_visible(page):
            return False
        _log_deal_step(page, "guided step 7: ALERT popup → Continue link (not Go back)")
        return await _native_deal_alert_continue(page)
    return False


async def _native_deal_run_guided_l3_cycles(page, cfg: SmartFunnelConfig) -> bool:
    """After L1 footer+ALERT: repeat steps 1–5 on Level 3 (3 different deals)."""
    ctx = page.context
    l3_need = max(0, int(cfg.guided_deal_l3_cycles or 0))
    if l3_need <= 0:
        return False
    l3_done = int(getattr(ctx, "_krx_guided_l3_cycles_done", 0) or 0)
    if l3_done >= l3_need:
        return False
    step_in_cycle = int(getattr(ctx, "_krx_guided_l3_step_in_cycle", 0) or 0)
    cycle_steps = 5
    progressed = False
    deadline = time.monotonic() + 180.0
    while l3_done < l3_need and time.monotonic() < deadline:
        body = await _retail_body_text(page)
        if step_in_cycle == 0 and not _is_level3_wall(body):
            if not await _page_has_text_in_deal_frames(page, "level 3 deals", "complete 3 more"):
                await asyncio.sleep(1.0)
                continue
        if step_in_cycle < cycle_steps:
            next_step = step_in_cycle + 1
            if not await _native_deal_guided_step(page, next_step):
                break
            step_in_cycle += 1
            ctx._krx_guided_l3_step_in_cycle = step_in_cycle
            progressed = True
            if step_in_cycle < cycle_steps:
                await asyncio.sleep(1.0)
                continue
        if step_in_cycle >= cycle_steps:
            l3_done += 1
            ctx._krx_guided_l3_cycles_done = l3_done
            step_in_cycle = 0
            ctx._krx_guided_l3_step_in_cycle = 0
            _log_deal_step(page, f"guided L3 cycle {l3_done}/{l3_need} complete")
            progressed = True
            if l3_done < l3_need:
                await asyncio.sleep(1.5)
                continue
        break
    if l3_done >= l3_need:
        await _mark_deal_flow_conversion(page, cfg)
    return progressed


async def _native_deal_run_guided_steps(page, cfg: SmartFunnelConfig) -> bool:
    """Run guided steps 1–5 × cycles, then post steps 6+ (footer → ALERT Continue)."""
    ctx = page.context
    max_step = max(0, int(cfg.guided_deal_step or 0))
    cycles_need = max(0, int(cfg.guided_deal_cycles or 0))
    cycle_steps = 5
    if max_step <= 0:
        return False

    progressed = False
    cycles_done = int(getattr(ctx, "_krx_guided_cycles_done", 0) or 0)

    if cycles_need > 0 and cycles_done < cycles_need:
        step_in_cycle = int(getattr(ctx, "_krx_guided_step_in_cycle", 0) or 0)
        while cycles_done < cycles_need:
            if step_in_cycle < cycle_steps:
                next_step = step_in_cycle + 1
                if not await _native_deal_guided_step(page, next_step):
                    break
                step_in_cycle += 1
                ctx._krx_guided_step_in_cycle = step_in_cycle
                progressed = True
                if step_in_cycle < cycle_steps:
                    await asyncio.sleep(1.0)
                    continue
            if step_in_cycle >= cycle_steps:
                cycles_done += 1
                ctx._krx_guided_cycles_done = cycles_done
                step_in_cycle = 0
                ctx._krx_guided_step_in_cycle = 0
                ctx._krx_guided_step_done = cycles_done * cycle_steps
                _log_deal_step(page, f"guided cycle {cycles_done}/{cycles_need} complete")
                progressed = True
                if cycles_done < cycles_need:
                    await asyncio.sleep(1.5)
                    continue
            break

    if cycles_need > 0 and cycles_done >= cycles_need and max_step > cycle_steps:
        post_done = int(getattr(ctx, "_krx_guided_post_step_done", 0) or 0)
        post_need = max_step - cycle_steps
        while post_done < post_need:
            next_step = cycle_steps + post_done + 1
            if not await _native_deal_guided_step(page, next_step):
                break
            post_done += 1
            ctx._krx_guided_post_step_done = post_done
            progressed = True
            if post_done < post_need:
                await asyncio.sleep(1.5)
        if int(getattr(ctx, "_krx_guided_l3_cycles_done", 0) or 0) < int(cfg.guided_deal_l3_cycles or 0):
            if await _native_deal_run_guided_l3_cycles(page, cfg):
                progressed = True
        elif int(getattr(ctx, "_krx_guided_l3_cycles_done", 0) or 0) >= int(cfg.guided_deal_l3_cycles or 0):
            await _mark_deal_flow_conversion(page, cfg)
            progressed = True
        return progressed

    if cycles_need > 0:
        return progressed

    done = int(getattr(ctx, "_krx_guided_step_done", 0) or 0)
    if done >= max_step:
        return False
    while done < max_step:
        next_step = done + 1
        if not await _native_deal_guided_step(page, next_step):
            break
        done += 1
        ctx._krx_guided_step_done = done
        progressed = True
        if done < max_step:
            await asyncio.sleep(1.0)
    return progressed


async def _native_deal_wall_step(page, cfg: SmartFunnelConfig) -> bool:
    """
    Deal wall — user 8-step flow (reward4spot):
      L1: 3× (CONTINUE→NO→START DEAL→tab→BACK TO DEALS) → footer → ALERT → L3 ×3 → conversion
    """
    flow_cfg = _deal_user_flow_config(cfg)
    if not await _deal_wall_step_allowed(page):
        return False

    ctx = page.context
    body = await _retail_body_text(page)
    await _sync_deal_level_state(page, body)

    if await _alert_popup_visible(page):
        return await _native_deal_alert_continue(page)
    if await _already_have_modal_open(page):
        return await _native_deal_modal_no(page)
    if await _how_to_complete_modal_open(page):
        return await _native_deal_how_to_complete_step(page)

    cycles_need = max(1, int(flow_cfg.guided_deal_cycles or 3))
    l3_need = max(1, int(flow_cfg.guided_deal_l3_cycles or 3))
    cycles_done = int(getattr(ctx, "_krx_guided_cycles_done", 0) or 0)
    l3_done = int(getattr(ctx, "_krx_guided_l3_cycles_done", 0) or 0)
    post_done = int(getattr(ctx, "_krx_guided_post_step_done", 0) or 0)
    is_l3 = _is_level3_wall(body) or getattr(ctx, "_krx_wall_level", None) == "L3"

    if is_l3 or getattr(ctx, "_krx_l1_footer_done", False):
        if is_l3 or await _page_has_text_in_deal_frames(page, "level 3 deals", "complete 3 more"):
            if l3_done >= l3_need:
                await _mark_deal_flow_conversion(page, flow_cfg)
                return True
            if await _native_deal_run_full_cycle(page):
                await _sync_guided_deal_counters(page, l3=True)
                return True
            return await _native_deal_run_guided_l3_cycles(page, flow_cfg)

    if cycles_done < cycles_need:
        if await _native_deal_run_full_cycle(page):
            await _sync_guided_deal_counters(page, l3=False)
            return True
        return await _native_deal_guided_step(page, 1)

    if cycles_done >= cycles_need and post_done < 1:
        if await _native_deal_guided_step(page, 6):
            ctx._krx_guided_post_step_done = 1
            ctx._krx_l1_footer_done = True
            return True
        return False

    return await _native_deal_run_guided_steps(page, flow_cfg)


async def _native_deal_level_continue(page) -> bool:
    """Click enabled bottom CONTINUE, or footer grey → alert Continue link."""
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
    if await _native_deal_footer_continue_trigger(page):
        await asyncio.sleep(1.0)
        if await _native_deal_interstitial_step(page):
            return True
    return False


async def _native_deal_continue_burst(
    page, cfg: Optional[SmartFunnelConfig] = None
) -> bool:
    """Backward-compatible entry → level-aware deal wall step."""
    return await _native_deal_wall_step(page, cfg or SmartFunnelConfig())


OFFERS_NAV_JS = r"""() => {
  var host = (location.host || '').toLowerCase();
  var bt = (document.body.innerText || '').toLowerCase();
  if (!/displayoptoffers|uplevelrewards|levelrewards|rewardsgiant|eward4spot|retailproductsusa/.test(host)) return null;
  if (/level 1 deals|level 2 deals|level 3 deals|best match for you|do you already have|how to complete/.test(bt)) return null;
  function vis(e) {
    var s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || s.pointerEvents === 'none') return false;
    var r = e.getBoundingClientRect();
    return r.width > 30 && r.height > 14 && r.top >= 0 && r.top < innerHeight;
  }
  function txt(e) { return ((e.innerText || e.textContent || '') + '').trim(); }
  function blocked(e) {
    var t = txt(e).toLowerCase();
    if (/terms|privacy|disclaimer|program requirements|member support|about our program|skip the survey|finish your survey/.test(t)) return true;
    var href = (e.href || e.getAttribute('href') || '').toLowerCase();
    if (/policies|privacy|terms|flashrewards|contact\./.test(href)) return true;
    return false;
  }
  function coords(el) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: txt(el) };
  }
  var anchors = Array.from(document.querySelectorAll('a[href]')).filter(vis);
  for (var i = 0; i < anchors.length; i++) {
    var a = anchors[i];
    if (blocked(a)) continue;
    var h = (a.href || '').toLowerCase();
    if (/uplevelrewards|levelrewards|rewardsgiant|getmy|deals\.|displayoptoffers|complete.*deal|reward.*status/i.test(h)) {
      return coords(a);
    }
  }
  var els = Array.from(document.querySelectorAll('button,a,div,span,[role=button]')).filter(vis);
  var patterns = [
    /^view deals$/i, /^my deals$/i, /^complete deals$/i, /^see deals$/i,
    /^reward status$/i, /^start earning$/i, /^get started$/i,
    /^complete 1 deal$/i, /^continue$/i, /^continue →$/i
  ];
  for (var pi = 0; pi < patterns.length; pi++) {
    var match = els.find(function (e) {
      if (blocked(e)) return false;
      return patterns[pi].test(txt(e));
    });
    if (match) return coords(match);
  }
  if (/towards target|towards amazon|reward progress|next step|complete 20 deals|continue instructions|track your reward/.test(bt)) {
    var cta = els.find(function (e) {
      if (blocked(e)) return false;
      return /view deals|my deals|complete deal|see deals|start deal|reward status|continue/i.test(txt(e).toLowerCase());
    });
    if (cta) return coords(cta);
  }
  return null;
}"""


async def _native_offers_nav_step(page) -> bool:
    """Navigate post-survey / reward-progress screens to the deal wall."""
    for frame in page.frames:
        try:
            target = await frame.evaluate(OFFERS_NAV_JS)
            if target and target.get("x") is not None:
                if await _trusted_survey_click(
                    page,
                    frame,
                    label=str(target.get("label") or ""),
                    x=float(target["x"]),
                    y=float(target["y"]),
                ):
                    await asyncio.sleep(0.35)
                    return True
        except Exception:
            continue
    for label in (
        "View Deals",
        "My Deals",
        "Complete Deals",
        "See Deals",
        "Reward Status",
        "Start Earning",
        "Get Started",
        "Continue",
        "CONTINUE",
    ):
        if await _native_click_text(page, label):
            await asyncio.sleep(0.35)
            return True
    return False


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
        if await _how_to_complete_modal_open(page):
            return False
        if await _page_has_text(page, "do you already have", "already have this deal"):
            return False
        if await _try(["CONTINUE", "Continue"]):
            return True
        if await _try(["My Deals", "View Deals", "Complete Deals"]):
            return True
        return await _native_offers_nav_step(page)

    if "confirm your email" in body or "your reward is waiting" in body:
        return await _try(["Continue"])

    return False


async def _final_conversion_gate(page, cfg: SmartFunnelConfig, deal_wall_seen: bool) -> bool:
    """Block false positives while survey loads or deal wall not yet visible."""
    if getattr(page.context, "_krx_l3_complete", False):
        return True
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
    if _cfg_stop_at_deal_wall(cfg):
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
      window.__krxPythonForm = 1;
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
    try:
        page.context._krx_fast_survey = bool(cfg.fast_survey)
        page.context._krx_survey_skip_chance = float(cfg.survey_skip_chance or 0.0)
        if cfg.fast_survey:
            os.environ.setdefault("KRX_SURVEY_INSTANT", "1")
        page.context._krx_survey_settle_s = (
            max(0.0, int(cfg.survey_settle_ms or 0) / 1000.0)
            if cfg.fast_survey
            else 1.5
        )
        page.context._krx_form_type_delay_ms = max(35, int(cfg.form_type_delay_ms or 50))
        page.context._krx_form_field_settle_s = 0.5
    except Exception:
        pass
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
            "window.__krxPythonDeals = 1; window.__krxPythonForm = 1; }"
        )
        page.context._krx_l1_footer_done = False
        page.context._krx_l3_complete = False
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
        if deals > prev_url_deals and not on_deal_wall_early:
            prev_url_deals = deals
            try:
                for frame in page.frames:
                    try:
                        await frame.evaluate("() => { window.__krxDealKeys = {}; }")
                    except Exception:
                        continue
            except Exception:
                pass
        elif deals > prev_url_deals:
            prev_url_deals = deals
        try:
            await _recover_off_policy_page(page)
        except Exception:
            pass
        body_l = await _retail_body_text(page)
        url_early = str(metrics.get("url") or "").lower()
        on_deal_wall_early = _body_has_deal_wall(body_l, url_early) or await _deal_wall_on_page(page)
        survey_active = await _survey_active_on_page(page)
        if (survey_active or _body_on_survey(body_l)) and not on_deal_wall_early:
            deal_wall_seen = False
            try:
                if await _page_has_text(page, "what kind of debt", "select all that apply"):
                    await _native_multiselect_step(page)
                await _native_survey_burst(page, row, cfg)
            except Exception:
                pass
        elif on_deal_wall_early:
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

        # Task 1: stop once LEVEL 1 DEALS visible (after guided steps if configured)
        if (
            _cfg_stop_at_deal_wall(cfg)
            and deal_wall_seen
            and not survey_active
            and not _body_on_survey(body_l)
            and _guided_pause_complete(cfg, page.context)
        ):
            await asyncio.sleep(1.0)
            if await _deal_wall_on_page(page) and not await _survey_active_on_page(page):
                guided_done = int(getattr(page.context, "_krx_guided_step_done", 0) or 0)
                guided_cycles = int(getattr(page.context, "_krx_guided_cycles_done", 0) or 0)
                guided_post = int(getattr(page.context, "_krx_guided_post_step_done", 0) or 0)
                await _emit(
                    "deals",
                    "ok",
                    {
                        "deals": deals,
                        "url": metrics.get("url", ""),
                        "stop": "deal_wall",
                        "paused_for_guidance": bool(cfg.pause_at_deal_wall),
                        "guided_step_done": guided_done,
                        "guided_cycles_done": guided_cycles,
                        "guided_post_step_done": guided_post,
                        "guided_l3_cycles_done": int(getattr(page.context, "_krx_guided_l3_cycles_done", 0) or 0),
                    },
                )
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
                    "paused_for_guidance": bool(cfg.pause_at_deal_wall),
                    "guided_step_done": guided_done,
                    "guided_cycles_done": int(getattr(page.context, "_krx_guided_cycles_done", 0) or 0),
                    "guided_post_step_done": int(getattr(page.context, "_krx_guided_post_step_done", 0) or 0),
                    "guided_l3_cycles_done": int(getattr(page.context, "_krx_guided_l3_cycles_done", 0) or 0),
                    "final_url": final_url,
                    "pattern": cfg.normalized_pattern(),
                }

        if (
            not on_deal_wall_early
            and not await _deal_wall_on_page(page)
            and deals >= min_d - 1
            and deals < min_d
        ):
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

        on_deal_wall_now = on_deal_wall_early or await _deal_wall_on_page(page)
        on_survey_fast = (
            cfg.fast_survey
            and (survey_active or _body_on_survey(body_l))
            and not on_deal_wall_now
        )
        need_third_deal = (
            not on_deal_wall_now and deals >= min_d - 1 and deals < min_d
        )

        if not cfg.stop_at_deal_wall and _conversion_ready(
            metrics,
            cfg,
            deal_wall_seen=deal_wall_seen,
            body=body_l,
            survey_active=survey_active,
            deal_flow_complete=bool(getattr(page.context, "_krx_l3_complete", False)),
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

        # Main brain — skip JS handler on deal wall (Python owns deal flow)
        skip_handler = on_deal_wall_now or on_survey_fast
        if not need_third_deal and not skip_handler:
            try:
                await _evaluate_all_frames(page, handler)
            except Exception as e:
                logger.debug("smart_funnel handler evaluate: %s", e)
        elif need_third_deal and not on_deal_wall_now and not cfg.pause_at_deal_wall:
            try:
                await _evaluate_all_frames(page, THIRD_DEAL_RECOVERY)
                await _evaluate_all_frames(page, DEAL_SCRIPT)
                await _native_deal_wall_step(page, cfg)
                await _native_screen_nudge(page, metrics)
            except Exception:
                pass

        # Deal push — skip JS deal scripts on deal wall (Python native owns full cycle)
        if not on_deal_wall_now and not on_survey_fast:
            try:
                await _evaluate_all_frames(page, DEAL_SCRIPT)
                await _evaluate_all_frames(page, MODAL_NO_SCRIPT)
                await _evaluate_all_frames(page, CONVERSION_SCRIPT)
            except Exception:
                pass
        else:
            try:
                await _evaluate_all_frames(page, CONVERSION_SCRIPT)
                if await _already_have_modal_open(page):
                    await _evaluate_all_frames(page, MODAL_NO_SCRIPT)
                    await _native_deal_modal_no(page)
            except Exception:
                pass

        metrics = await _metrics_from_page(page)
        body_l = await _retail_body_text(page)
        survey_active = await _survey_active_on_page(page)
        if survey_active or _body_on_survey(body_l):
            deal_wall_seen = False
        elif await _deal_wall_on_page(page) or _body_has_deal_wall(body_l, str(metrics.get("url") or "")):
            deal_wall_seen = True

        if (
            _cfg_stop_at_deal_wall(cfg)
            and deal_wall_seen
            and not survey_active
            and not _body_on_survey(body_l)
            and _guided_pause_complete(cfg, page.context)
        ):
            await asyncio.sleep(1.0)
            if await _deal_wall_on_page(page) and not await _survey_active_on_page(page):
                deals = int(metrics.get("url_deals") or 0)
                guided_done = int(getattr(page.context, "_krx_guided_step_done", 0) or 0)
                guided_cycles = int(getattr(page.context, "_krx_guided_cycles_done", 0) or 0)
                guided_post = int(getattr(page.context, "_krx_guided_post_step_done", 0) or 0)
                await _emit(
                    "deals",
                    "ok",
                    {
                        "deals": deals,
                        "url": metrics.get("url", ""),
                        "stop": "deal_wall",
                        "paused_for_guidance": bool(cfg.pause_at_deal_wall),
                        "guided_step_done": guided_done,
                        "guided_cycles_done": guided_cycles,
                        "guided_post_step_done": guided_post,
                        "guided_l3_cycles_done": int(getattr(page.context, "_krx_guided_l3_cycles_done", 0) or 0),
                    },
                )
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
                    "paused_for_guidance": bool(cfg.pause_at_deal_wall),
                    "guided_step_done": guided_done,
                    "guided_cycles_done": int(getattr(page.context, "_krx_guided_cycles_done", 0) or 0),
                    "guided_post_step_done": int(getattr(page.context, "_krx_guided_post_step_done", 0) or 0),
                    "guided_l3_cycles_done": int(getattr(page.context, "_krx_guided_l3_cycles_done", 0) or 0),
                    "final_url": final_url,
                    "pattern": cfg.normalized_pattern(),
                }

        if not cfg.stop_at_deal_wall and _conversion_ready(
            metrics,
            cfg,
            deal_wall_seen=deal_wall_seen,
            body=body_l,
            survey_active=survey_active,
            deal_flow_complete=bool(getattr(page.context, "_krx_l3_complete", False)),
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
        url_l = str(metrics.get("url") or "").lower()
        on_deal_host = any(
            h in url_l
            for h in (
                "displayoptoffers",
                "uplevelrewards",
                "levelrewards",
                "rewardsgiant",
                "eward4spot",
            )
        )
        has_deal_wall = (
            _body_has_deal_wall(body_l, url_l)
            or await _deal_wall_on_page(page)
            or (
                on_deal_host
                and any(
                    k in body_l
                    for k in (
                        "level 1 deals",
                        "level 2 deals",
                        "level 3 deals",
                        "best match for you",
                        "do you already have",
                        "how to complete",
                    )
                )
            )
        )
        if any(k in body_l for k in ("your reward is waiting", "confirm your email", "sign up or resume")):
            phase = "email"
        if await _body_on_sms_optin(body_l):
            phase = "email"
        elif any(k in body_l for k in ("emailed to you", "explore offers from our sponsors", "status emailed")):
            phase = "email"
        if await _survey_active_on_page(page) or _body_on_survey(body_l):
            if not has_deal_wall:
                phase = "survey"
        on_form_raw = _body_on_form(body_l, url_l) or await _form_active_on_page(page)
        survey_now = (
            survey_active
            or _body_on_survey(body_l)
            or await _survey_active_on_page(page)
        )
        if has_deal_wall:
            phase = "deals"
            on_form = False
        elif survey_now and not has_deal_wall:
            phase = "survey"
            on_form = False
        elif on_form_raw:
            phase = "form"
            on_form = True
        else:
            on_form = False
        on_survey = (phase == "survey" or survey_now) and not has_deal_wall and not on_form
        if on_form:
            try:
                await _native_form_step(page, row or {})
            except Exception:
                pass
        elif phase == "email":
            try:
                if await _body_on_sms_optin(body_l) or any(
                    k in body_l
                    for k in ("explore offers from our sponsors", "sign up for text messages")
                ):
                    await _native_sms_optin_step(page, cfg)
                elif any(
                    k in body_l
                    for k in ("emailed to you", "status emailed")
                ):
                    await _native_reward_status_optin_step(page, cfg)
                else:
                    await _native_email_step(page, row or {})
            except Exception:
                pass
        if on_survey:
            cur_sfp = await _survey_fingerprint(page)
            new_q = cur_sfp != getattr(page.context, "_krx_last_survey_loop_fp", "")
            if new_q:
                stuck_on_survey = 0
                page.context._krx_last_survey_loop_fp = cur_sfp
            stuck_on_survey += 1
            try:
                body_survey = await _survey_body_text(page)
                if _is_sponsored_ad_body(body_survey):
                    await _click_sponsored_ad_random(page)
                elif await _page_has_text(page, "what kind of debt", "select all that apply"):
                    await _native_multiselect_step(page)
                else:
                    await _native_survey_burst(page, row, cfg)
                if cfg.fast_survey and stuck_on_survey >= 1 and not await _is_multiselect_survey_page(page):
                    await _click_standard_survey_choice(page)
                if cfg.fast_survey:
                    if stuck_on_survey >= 2 and not await _is_multiselect_survey_page(page):
                        await _click_largest_survey_button(page)
                    if stuck_on_survey >= 3 and not await _is_multiselect_survey_page(page):
                        await _click_survey_zone_answer(page)
                    if stuck_on_survey >= 6:
                        await _try_skip_survey(page)
                else:
                    if stuck_on_survey >= 2 and _is_sponsored_ad_body(body_survey):
                        await _click_sponsored_ad_random(page)
                    elif stuck_on_survey >= 2:
                        await _click_largest_survey_button(page)
                    if stuck_on_survey >= 3:
                        await _click_survey_zone_answer(page)
            except Exception:
                pass
        else:
            stuck_on_survey = 0
        if has_deal_wall:
            deal_wall_seen = True
            try:
                await _native_deal_wall_step(page, cfg)
            except Exception:
                pass
        elif phase in ("deals", "offers") and not on_survey and not cfg.pause_at_deal_wall:
            try:
                if await _survey_active_on_page(page) or _body_on_survey(body_l):
                    await _native_survey_burst(page, row, cfg)
                elif await _body_on_sms_optin(body_l):
                    await _native_sms_optin_step(page, cfg)
                elif has_deal_wall or await _deal_wall_on_page(page):
                    await _native_deal_wall_step(page, cfg)
                elif phase == "offers":
                    await _native_offers_nav_step(page)
                else:
                    await _native_offers_nav_step(page)
            except Exception:
                pass
        else:
            stuck_deal_wall = 0
        if phase == "retail" and iteration == 1:
            last_phase = ""  # force emit retail on first pass
        await _emit(phase, "running", {"deals": metrics.get("url_deals", 0), "url": metrics.get("url", "")})

        cur_fp = await _page_fingerprint(page)
        screen_unchanged = (
            cur_fp.get("hash") == prev_fp.get("hash") and cur_fp.get("url") == prev_fp.get("url")
        )
        if on_survey:
            cur_sfp = await _survey_fingerprint(page)
            if cur_sfp != getattr(page.context, "_krx_prev_survey_fp", ""):
                screen_unchanged = False
                page.context._krx_prev_survey_fp = cur_sfp
        if screen_unchanged:
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
            if phase in ("deals", "offers") and stuck_same_screen >= 2 and not cfg.pause_at_deal_wall:
                try:
                    if await _survey_active_on_page(page) or _body_on_survey(body_l):
                        await _native_survey_burst(page, row, cfg)
                    elif await _body_on_sms_optin(body_l):
                        await _native_sms_optin_step(page, cfg)
                    elif has_deal_wall or await _deal_wall_on_page(page):
                        await _native_deal_wall_step(page, cfg)
                    else:
                        await _native_offers_nav_step(page)
                except Exception:
                    pass
            if phase == "survey" and stuck_same_screen >= 2:
                try:
                    body_stuck = await _survey_body_text(page)
                    if _is_sponsored_ad_body(body_stuck):
                        await _click_sponsored_ad_random(page)
                    else:
                        await _click_standard_survey_choice(page)
                        await _click_largest_survey_button(page)
                        await _generic_visible_answer_click(page)
                except Exception:
                    pass
            if on_form and stuck_same_screen >= 2:
                try:
                    await _native_form_click_continue(page)
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

        loop_ms = cfg.loop_interval_ms
        poll_ms = cfg.idle_poll_ms
        if on_survey and cfg.fast_survey:
            loop_ms = int(cfg.survey_loop_interval_ms or 0)
            poll_ms = min(poll_ms, int(cfg.survey_idle_poll_ms or 20))
        elif on_form:
            loop_ms = max(loop_ms, int(cfg.form_loop_interval_ms or 900))
        if on_survey and cfg.fast_survey and loop_ms <= 0:
            pass
        elif on_survey and cfg.fast_survey:
            await asyncio.sleep(max(0, loop_ms) / 1000.0)
        else:
            deadline = time.monotonic() + max(loop_ms, 15) / 1000.0
            await _condition_wait(page, prev_fp, cfg, deadline, poll_ms=poll_ms)

        if stuck_same_screen >= 5 and phase in ("deals", "offers"):
            try:
                on_wall_now = await _deal_wall_on_page(page) or _body_has_deal_wall(
                    body_l, str(metrics.get("url") or "")
                )
                if not on_wall_now:
                    await page.evaluate(
                        "() => { window.__krxDealKeys = {}; try { window.scrollBy(0, 400); } catch(e) {} }"
                    )
                if not on_wall_now and deals >= min_d - 1 and deals < min_d:
                    await page.evaluate(THIRD_DEAL_RECOVERY)
            except Exception:
                pass

        if stuck_same_screen >= int(cfg.max_idle_before_nudge_ms / max(cfg.loop_interval_ms, 1)):
            try:
                if on_survey:
                    await _click_largest_survey_button(page)
                elif await _deal_wall_on_page(page) and not cfg.pause_at_deal_wall:
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

    if on_deal_host and any(
        k in s
        for k in (
            "level 1 deals",
            "level 2 deals",
            "level 3 deals",
            "best match for you",
            "do you already have",
            "how to complete",
            "start deal",
            "your cost:",
            "continue instructions below",
            "next step: complete",
        )
    ):
        return "deals"
    if "confirm your email" in s or "sign up or resume" in s or "your reward is waiting" in s:
        return "email"
    if "emailed to you" in s or "explore offers from our sponsors" in s:
        return "email"
    if _body_on_form(s, u):
        return "form"
    if "date of birth" in s or "first name" in s or "lfirstname" in u:
        return "form"
    if on_retail_host and "question" in s:
        return "retail"
    if _body_on_survey(s):
        return "survey"
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
    if on_deal_host:
        return "offers"
    return "flow"
