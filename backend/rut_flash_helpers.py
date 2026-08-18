"""
RUT helpers for FlashRewards-style offers (survey + deals + missing-field
auto-fill).

Three helpers, each safe to call multiple times (idempotent + best-effort):

1. enrich_row_random(row)
   Mutates `row` in place, filling blank values for keys commonly required by
   lead-gen registration forms but missing from the user's Excel:
       • zip      — picked from a state→ZIP table when only state is known
       • gender   — random M/F (60/40 male-female mirroring US-typical lists)
       • day      — random 1-28 (avoids month-edge bugs)
       • month    — random 1-12
       • year     — random 1965-2002 (ages 23-60 in 2026)
   Existing values are NEVER overwritten.

2. survey_click_random_answers(page, max_questions=8)
   FlashRewards-style "3 quick questions" pages where each answer is a plain
   <a> or <button> (Yes/No, multi-choice). _fill_form skips these because
   they are NOT input elements. We look for clickable answer chips whose
   parent contains question-style text and pick a random one. Loops up to
   `max_questions` times so multi-step surveys complete.

3. complete_random_deals(page, count_min=2, count_max=3, ...)
   On the post-survey "deals page" we click `count_min..count_max` random
   deal cards. For each one we open it, watch for credit-card capture (input
   asking for cc-number, cardholder, or stripe iframe) and SKIP / go back if
   detected — user explicitly said "credit card nahi dalne". Otherwise we
   click any visible "Continue" / "Yes" / "Get Offer" CTAs for ~10-25s, then
   navigate back and pick the next deal. Returns # of successfully clicked
   deals (does NOT guarantee the partner network credits us — that depends
   on the deal type).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

logger = logging.getLogger("rut.flash")

# Approximate ZIP per US state (used only when row has state but no zip)
_STATE_ZIP = {
    "AL": "35201", "AK": "99501", "AZ": "85001", "AR": "72201", "CA": "90001",
    "CO": "80201", "CT": "06101", "DE": "19901", "FL": "33101", "GA": "30301",
    "HI": "96801", "ID": "83201", "IL": "60601", "IN": "46201", "IA": "50301",
    "KS": "66101", "KY": "40201", "LA": "70112", "ME": "04101", "MD": "21201",
    "MA": "02101", "MI": "48201", "MN": "55101", "MS": "39201", "MO": "63101",
    "MT": "59101", "NE": "68101", "NV": "89101", "NH": "03101", "NJ": "07101",
    "NM": "87101", "NY": "10001", "NC": "27601", "ND": "58101", "OH": "44101",
    "OK": "73101", "OR": "97201", "PA": "19101", "RI": "02901", "SC": "29201",
    "SD": "57101", "TN": "37201", "TX": "75201", "UT": "84101", "VT": "05601",
    "VA": "23218", "WA": "98101", "WV": "25301", "WI": "53201", "WY": "82001",
    "DC": "20001",
}


def enrich_row_random(row: Dict[str, Any]) -> Dict[str, Any]:
    """In-place fill of blank fields commonly required by US lead-gen forms.

    Existing non-empty values are preserved. Returns the mutated row for
    chaining.
    """
    if not isinstance(row, dict):
        return row

    def _is_blank(v: Any) -> bool:
        return v is None or (isinstance(v, str) and v.strip() == "")

    # ZIP — derive from state if available
    if _is_blank(row.get("zip")) and _is_blank(row.get("zipcode")) and _is_blank(row.get("postal")):
        st = (row.get("state") or "").strip().upper()
        zip_guess = _STATE_ZIP.get(st)
        if not zip_guess:
            # Last resort — random 5-digit US ZIP
            zip_guess = f"{random.randint(10000, 99999)}"
        row["zip"] = zip_guess

    # Gender — M/F (60% F to mirror typical lead-gen lists)
    if _is_blank(row.get("gender")):
        row["gender"] = random.choice(["F", "M", "F", "M", "F"])

    # DOB — day/month/year (age 23-60 in 2026)
    if _is_blank(row.get("day")):
        row["day"] = str(random.randint(1, 28))
    if _is_blank(row.get("month")):
        row["month"] = str(random.randint(1, 12))
    if _is_blank(row.get("year")):
        row["year"] = str(random.randint(1965, 2002))

    return row


# ─────── Survey button click (Yes/No, multi-choice anchors) ────────
# Real-world survey pages use a mix of <a>, <button>, <div role=button>,
# AND custom <div class="choice-btn"> with cursor:pointer + data-answer.
# We try ALL of them so the bot works across FlashRewards, Lovable,
# and other affiliate landing pages.
_SURVEY_ANSWER_SELECTORS = [
    # FlashRewards / RetailProductsUSA — custom div buttons with data-answer
    'div.choice-btn',
    'div[data-answer]',
    'div[data-step]',
    '[role="button"]',
    # Plain anchor / button Yes/No
    'a:has-text("Yes")', 'a:has-text("No")',
    'button:has-text("Yes")', 'button:has-text("No")',
    # FlashRewards Q2 "How do you plan to use your reward?" answers
    'a:has-text("Keep it")', 'a:has-text("Give to a friend")',
    'button:has-text("Keep it")', 'button:has-text("Give to a friend")',
    # FlashRewards Q3 "How many times do you go shopping per week?"
    'a:has-text("1 - 2")', 'a:has-text("3 - 7")', 'a:has-text("7 - 10")', 'a:has-text("10+")',
    'button:has-text("1 - 2")', 'button:has-text("3 - 7")', 'button:has-text("7 - 10")', 'button:has-text("10+")',
    # Generic survey answer chips
    'a.answer', 'button.answer', '.survey-answer', '.option-btn',
]


def _is_short_answer_text(s: str) -> bool:
    """Check if a string looks like a short answer label (Yes/No/multi-choice)."""
    if not s or len(s) > 40:
        return False
    s_l = s.strip().lower()
    return bool(re.match(
        r"^(yes|no|male|female|m|f|keep it|give to a friend|"
        r"1\s*-\s*2|3\s*-\s*7|7\s*-\s*10|10\+|"
        r"daily|weekly|monthly|never|sometimes|often|always|"
        r"\$\d+|under \$\d+)$",
        s_l,
    ))


async def _is_survey_page(page: Page) -> bool:
    """Strict detection — must have BOTH a question header AND visible answer
    elements (incl. custom div.choice-btn). Footer FAQ text alone does not
    count."""
    try:
        result = await page.evaluate(
            """() => {
                const txt = (document.body ? document.body.innerText : '');
                const hasQ = /answer question \\d+ of \\d+/i.test(txt) ||
                             /question \\d+ of \\d+/i.test(txt);
                // Visible elements with short answer-like text
                const all = Array.from(document.querySelectorAll('a,button,div,span,li'));
                let answers = 0;
                for (const el of all) {
                    if (!el.offsetParent) continue;
                    if (el.children && el.children.length > 0) continue;  // leaf only
                    const t = (el.innerText||'').trim();
                    if (!t || t.length > 40) continue;
                    if (/^(yes|no|male|female|keep it|give to a friend|1\\s*-\\s*2|3\\s*-\\s*7|7\\s*-\\s*10|10\\+)$/i.test(t)) {
                        const cur = window.getComputedStyle(el).cursor;
                        if (cur === 'pointer' || el.tagName === 'A' || el.tagName === 'BUTTON') {
                            answers++;
                        }
                    }
                }
                return { hasQ: hasQ, answers: answers };
            }"""
        )
        if not isinstance(result, dict):
            return False
        return bool(result.get("hasQ")) and int(result.get("answers", 0)) >= 2
    except Exception:
        return False


async def _get_question_signature(page: Page) -> str:
    """Return a short signature of the visible question text — used to detect
    whether SPAs have advanced to a new question on same URL."""
    try:
        sig = await page.evaluate(
            """() => {
                const txt = (document.body ? document.body.innerText : '');
                const lines = txt.split('\\n').map(s => s.trim()).filter(Boolean);
                for (const ln of lines) {
                    if (/answer question|how (do|many|fast|often)|do you|where do|what is/i.test(ln)) {
                        return ln.slice(0, 120);
                    }
                }
                return lines.slice(0, 3).join(' | ').slice(0, 120);
            }"""
        )
        return (sig or "").strip()
    except Exception:
        return ""


async def survey_click_random_answers(
    page: Page,
    max_questions: int = 8,
    picker: Optional[Any] = None,
) -> Dict[str, Any]:
    """Click an answer on each survey page. Returns
        {clicks: int, picks: List[(question_sig, answer_text)]}.

    `picker` (optional callable) lets the caller bias the random pick
    toward historically high-converting answers (Thompson-sampling). If
    not provided we fall back to `random.choice`.
    """
    clicks = 0
    picks: List[Any] = []
    last_sig = ""
    same_sig_count = 0
    for _ in range(max_questions):
        # Generous initial wait so SPA can render the next question after a
        # same-page DOM swap (RetailProductsUSA needs ~2.5-3.5s after click).
        try:
            await page.wait_for_timeout(2200 + random.randint(0, 900))
        except Exception:
            pass
        if not await _is_survey_page(page):
            break

        # Detect SPA question advance via DOM text change (URL stays the same)
        sig = await _get_question_signature(page)
        if sig and sig == last_sig:
            same_sig_count += 1
            if same_sig_count >= 2:
                break
        else:
            same_sig_count = 0
        last_sig = sig

        # Collect visible answer candidates — combine CSS-selector pass with
        # a DOM scan that catches custom div.choice-btn / cursor:pointer divs.
        candidates: List[Any] = []
        candidate_pairs: List[Any] = []  # (handle, text)
        for sel in _SURVEY_ANSWER_SELECTORS:
            try:
                els = await page.query_selector_all(sel)
                for el in els:
                    try:
                        if not await el.is_visible():
                            continue
                        txt = (await el.inner_text()).strip()
                        if _is_short_answer_text(txt):
                            candidates.append(el)
                            candidate_pairs.append((el, txt))
                    except Exception:
                        continue
            except Exception:
                continue

        # DOM-scan fallback for cursor:pointer custom buttons
        if not candidates:
            try:
                handles = await page.evaluate_handle(
                    """() => {
                        const all = Array.from(document.querySelectorAll('div,span,li,a,button'));
                        const hits = [];
                        for (const el of all) {
                            if (!el.offsetParent) continue;
                            if (el.children && el.children.length > 0) continue;
                            const t = (el.innerText||'').trim();
                            if (!t || t.length > 40) continue;
                            if (!/^(yes|no|male|female|keep it|give to a friend|1\\s*-\\s*2|3\\s*-\\s*7|7\\s*-\\s*10|10\\+)$/i.test(t)) continue;
                            const cur = window.getComputedStyle(el).cursor;
                            if (cur === 'pointer' || el.tagName === 'A' || el.tagName === 'BUTTON') {
                                hits.push(el);
                            }
                        }
                        return hits;
                    }"""
                )
                props = await handles.get_properties()
                for _, prop in props.items():
                    el = prop.as_element()
                    if el is not None:
                        try:
                            txt = (await el.inner_text()).strip()
                        except Exception:
                            txt = ""
                        candidates.append(el)
                        candidate_pairs.append((el, txt))
            except Exception as e:  # noqa: BLE001
                logger.debug(f"dom-scan answers err: {e}")

        if not candidate_pairs:
            break

        # Pick via Thompson-sampling picker if provided, else uniform random
        if picker is not None:
            try:
                target, target_text = picker(sig, candidate_pairs)
                if target is None:
                    target, target_text = random.choice(candidate_pairs)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"picker err: {e}")
                target, target_text = random.choice(candidate_pairs)
        else:
            target, target_text = random.choice(candidate_pairs)

        try:
            await target.click(timeout=5000)
            clicks += 1
            picks.append((sig, target_text))
            try:
                await page.wait_for_load_state("networkidle", timeout=4500)
            except Exception:
                pass
            await page.wait_for_timeout(800)
        except Exception as e:
            logger.debug(f"survey click err: {e}")
            break

    return {"clicks": clicks, "picks": picks}


# ─────── Deal completion ──────────────────────────────────────────
_DEAL_PAGE_MARKERS = [
    # FlashRewards specific
    "complete offers", "available offers", "select an offer",
    "recommended for you", "level 1", "level 2", "level 3",
    # Generic deals/rewards lists
    "claim your reward", "earn your reward", "complete deals",
    "get offer", "play to earn", "free trial",
    # Header words
    "deals", "offers", "campaigns",
]

_CC_MARKERS = [
    "input[name*='card']", "input[name*='cc']",
    "input[autocomplete='cc-number']", "input[autocomplete='cc-name']",
    "input[name*='cardnumber']", "input[name*='ccnum']",
    "input[id*='card-number']", "iframe[src*='stripe']",
    "iframe[src*='checkout.stripe']", "iframe[name*='card']",
]

_DEAL_LINK_SELECTORS = [
    'a[href*="aff_c"]', 'a[href*="offer"]', 'a[href*="deal"]',
    'a[href*="campaign"]', 'a[href*="track"]',
    '.offer-card a', '.deal-card a', '.lp-offer a',
    'button:has-text("Get Offer")', 'button:has-text("Continue")',
    'button:has-text("Claim")', 'button:has-text("Start")',
]


async def _is_deals_page(page: Page) -> bool:
    try:
        text = (await page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 6000)"
        ) or "").lower()
        return sum(1 for m in _DEAL_PAGE_MARKERS if m in text) >= 1
    except Exception:
        return False


async def _has_credit_card_request(page: Page) -> bool:
    """Detect if current page is asking for credit card info."""
    try:
        for sel in _CC_MARKERS:
            try:
                el = await page.query_selector(sel)
                if el:
                    try:
                        vis = await el.is_visible()
                    except Exception:
                        vis = True
                    if vis:
                        return True
            except Exception:
                continue
        # Text-based fallback
        text = (await page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 4000)"
        ) or "").lower()
        for kw in ("credit card number", "card number", "cardholder name",
                   "cvv", "card verification", "expiration date",
                   "billing address"):
            if kw in text:
                return True
    except Exception:
        return False
    return False


async def complete_random_deals(
    page: Page,
    count_min: int = 2,
    count_max: int = 3,
    per_deal_seconds: int = 18,
    skip_repeat_click: Optional[Any] = None,
) -> int:
    """Click `count_min..count_max` random deals from a deals page.

    Skips deals that ask for credit card. Returns # of deals successfully
    "completed" (i.e. opened, watched, navigated back without CC).
    """
    if not await _is_deals_page(page):
        return 0

    target_count = random.randint(count_min, count_max)
    completed = 0
    deals_root_url = page.url
    visited_hrefs: set = set()

    for _ in range(target_count * 3):  # try up to 3x in case some are CC-only
        if completed >= target_count:
            break

        # Refresh deal links each iteration (deals change after each one)
        deal_links = []
        for sel in _DEAL_LINK_SELECTORS:
            try:
                els = await page.query_selector_all(sel)
                for el in els:
                    try:
                        if not await el.is_visible():
                            continue
                        href = await el.get_attribute("href")
                        if href and href in visited_hrefs:
                            continue
                        if skip_repeat_click and href:
                            try:
                                if skip_repeat_click(href, page.url or ""):
                                    continue
                            except Exception:
                                pass
                        deal_links.append((el, href or ""))
                    except Exception:
                        continue
            except Exception:
                continue

        if not deal_links:
            # Maybe page hasn't loaded all deals yet — small wait + retry
            try:
                await page.wait_for_timeout(1500)
            except Exception:
                pass
            continue

        el, href = random.choice(deal_links)
        if href:
            visited_hrefs.add(href)

        cur_url = page.url
        _ = cur_url  # reserved for future deal-page-change detection
        try:
            try:
                async with page.expect_navigation(timeout=10000, wait_until="domcontentloaded"):
                    await el.click(timeout=6000)
            except Exception:
                # Could be a popup window or in-page swap
                try:
                    await el.click(timeout=4000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    continue

            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass

            # CC check — if present, go back to deals page and try another
            if await _has_credit_card_request(page):
                logger.info("deal requires CC — skipping")
                try:
                    await page.go_back(timeout=10000, wait_until="domcontentloaded")
                except Exception:
                    try:
                        if skip_repeat_click and skip_repeat_click(deals_root_url, ""):
                            raise RuntimeError("skip repeat offer click")
                        await page.goto(deals_root_url, timeout=15000, wait_until="domcontentloaded")
                    except Exception:
                        pass
                continue

            # Spend per_deal_seconds clicking through any visible CTAs that
            # don't require CC (Continue / Yes / Get Offer). Random taps to
            # mimic real interest.
            end_at = asyncio.get_event_loop().time() + per_deal_seconds
            cta_selectors = [
                'button:has-text("Continue")', 'a:has-text("Continue")',
                'button:has-text("Yes")', 'a:has-text("Yes")',
                'button:has-text("Next")', 'a:has-text("Next")',
                'button:has-text("Get")', 'a:has-text("Get")',
                'button:has-text("Start")', 'a:has-text("Start")',
                'button:has-text("Claim")', 'a:has-text("Claim")',
            ]
            while asyncio.get_event_loop().time() < end_at:
                # Re-check CC each cycle
                if await _has_credit_card_request(page):
                    logger.info("deal mid-flow requires CC — stopping deal")
                    break
                clicked = False
                for sel in cta_selectors:
                    try:
                        elx = await page.query_selector(sel)
                        if elx:
                            try:
                                if not await elx.is_visible():
                                    continue
                            except Exception:
                                pass
                            try:
                                await elx.click(timeout=3000)
                                clicked = True
                                await page.wait_for_timeout(random.randint(1500, 3500))
                                try:
                                    await page.wait_for_load_state(
                                        "networkidle", timeout=6000
                                    )
                                except Exception:
                                    pass
                                break
                            except Exception:
                                continue
                    except Exception:
                        continue
                if not clicked:
                    # No CTA — wait a bit, then break (deal page idle)
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    break

            completed += 1
            logger.info(f"deal #{completed} completed (no CC)")

            # Navigate back to deals root for next pick
            try:
                await page.go_back(timeout=10000, wait_until="domcontentloaded")
            except Exception:
                try:
                    if skip_repeat_click and skip_repeat_click(deals_root_url, ""):
                        break
                    await page.goto(deals_root_url, timeout=15000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                except Exception:
                    # If we can't go back, abandon further deals
                    break
            else:
                try:
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"deal iteration err: {e}")
            try:
                await page.go_back(timeout=8000, wait_until="domcontentloaded")
            except Exception:
                try:
                    if skip_repeat_click and skip_repeat_click(deals_root_url, ""):
                        break
                    await page.goto(deals_root_url, timeout=10000, wait_until="domcontentloaded")
                except Exception:
                    pass
            continue

    return completed


# ════════════════════════════════════════════════════════════════════
#  V2 — Comprehensive survey flow (Stage D long survey + multi-select +
#  sponsored-ad bypass + agree-continue). Used after the Stage A pre-pop
#  survey. Designed for FlashRewards / display.optoffers.com style pages
#  where 20+ questions appear with VARIED answer texts (Often, This month,
#  $75k-$100k, Cataracts, Credit Card, etc.) — the original
#  `survey_click_random_answers` only matched a hardcoded regex.
# ════════════════════════════════════════════════════════════════════

# Sponsored-ad bypass — these answer texts (when present alongside CTAs
# like "Yes, get a quote") let us decline insurance/medicare/debt ads
# without committing the user to a phone callback. We click the negative
# answer to ADVANCE the flow, not engage.
_SPONSORED_BYPASS = [
    "no thanks", "no, thanks", "no thank you", "skip",
    "maybe later", "not interested", "no call", "no, continue",
    "don't call", "do not call", "i'm not interested",
    "no, i'm not", "none of the above", "neither",
]

_AGREE_TEXT_PATTERNS = [
    "i agree", "agree to", "accept the", "consent to",
    "terms", "privacy policy", "by clicking",
]


async def _detect_survey_v2(page: Page) -> Dict[str, Any]:
    """Robust detection that finds answer chips PROXIMATE to the question
    heading. Uses a 3-tier strategy:
      Tier 1 — Specific FlashRewards / RetailProductsUSA selectors:
        .choice-btn, [data-answer], [data-step], .answer, .option-btn, etc.
      Tier 2 — Question subtree scan: find the H1/H2/H3 ending in '?',
        then scan its parent + 2 ancestors for clickables (excludes header
        & footer where the same site has marketing/info links).
      Tier 3 — Whole-page fallback: any clickable with cursor:pointer that
        isn't in nav/header/footer/aside.
    Crucially, we FILTER OUT links pointing to offer-tracking domains
    (giftclick.org, aff_c, etc.) unless they're literally the only choice.
    """
    try:
        result = await page.evaluate(
            """() => {
                const txt = (document.body ? document.body.innerText : '');
                const lines = txt.split('\\n').map(s => s.trim()).filter(Boolean);

                // ─── Find the question line ───
                let question = '';
                for (const ln of lines) {
                    if (ln.length > 200) continue;
                    if (/answer question \\d+ of \\d+/i.test(ln) ||
                        /question \\d+ of \\d+/i.test(ln) ||
                        ln.endsWith('?')) {
                        question = ln.slice(0, 160);
                        break;
                    }
                }

                // Helper: is element inside nav/header/footer/aside?
                function inChrome(el) {
                    return !!el.closest('nav, header, footer, aside, [role="navigation"], [role="banner"], [role="contentinfo"]');
                }

                // Helper: extract trimmed innerText
                function elText(el) {
                    return ((el.innerText || el.textContent || '').trim());
                }

                // Helper: is this element a tracking/offer affiliate link?
                function isAffLink(el) {
                    if (el.tagName !== 'A') return false;
                    const href = (el.getAttribute('href') || '').toLowerCase();
                    return /giftclick\\.org|aff_c|affsecid|\\/aff\\/|\\/track\\//.test(href);
                }

                const NAV_RE = /^(home|about|contact|menu|login|sign in|sign up|register|help|faq|terms|privacy|policy|search|disclosure|disclaimer|do not sell|notice of collection|member support|reward status|acceptable use|program requirements|purchase|continue to claim|claim now|click here|learn more)$/i;

                const seen = new Set();
                const answers = [];

                // ─── Tier 1: Specific FlashRewards selectors ───
                // (.yes_btn/.no_btn are RetailProductsUSA SMS-opt-in
                // / "Are you sure" gates that block flow if not handled.)
                const tier1Selectors = [
                    '.choice-btn', '[data-answer]', '[data-step]',
                    '.answer', '.answer-btn', '.option-btn', '.option',
                    '.survey-answer', '.choice', 'button.btn-survey',
                    '[role="radio"]', 'label.answer-label',
                    '.yes_btn', '.no_btn', '.yes-btn', '.no-btn',
                ];
                for (const sel of tier1Selectors) {
                    try {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            if (!el.offsetParent) continue;
                            if (inChrome(el)) continue;
                            const t = elText(el);
                            if (!t || t.length > 100) continue;
                            if (seen.has(t)) continue;
                            seen.add(t);
                            answers.push(t);
                            if (answers.length >= 12) break;
                        }
                    } catch (e) {}
                    if (answers.length >= 12) break;
                }

                // ─── Tier 2: Question-subtree scan ───
                // In question-subtree we DO accept affiliate-link <a> tags
                // because some FlashRewards landing pages (lovable.app)
                // implement Yes/No as <a href="https://giftclick.org/aff_c?...">.
                // Outside the question subtree those would be rejected.
                if (answers.length < 2 && question) {
                    let qEl = null;
                    const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, p, span'));
                    for (const h of headings) {
                        const ht = elText(h);
                        if (ht && (ht === question || ht.includes(question.slice(0, 30)) || question.includes(ht.slice(0, 30)))) {
                            qEl = h; break;
                        }
                    }
                    if (qEl) {
                        let scope = qEl;
                        for (let depth = 0; depth < 4 && scope && scope.parentElement; depth++) {
                            scope = scope.parentElement;
                            const cands = scope.querySelectorAll(
                                'a, button, [role="button"], [role="radio"], label, ' +
                                '.choice-btn, .answer, [data-answer], [data-step]'
                            );
                            for (const el of cands) {
                                if (!el.offsetParent) continue;
                                if (inChrome(el)) continue;
                                const inner = el.querySelector('a, button, [role="button"]');
                                if (inner) continue;
                                const t = elText(el);
                                if (!t || t.length > 100) continue;
                                if (NAV_RE.test(t)) continue;
                                if (seen.has(t)) continue;
                                seen.add(t);
                                answers.push(t);
                                if (answers.length >= 8) break;
                            }
                            if (answers.length >= 4) break;
                        }
                    }
                }

                // ─── Tier 3: Whole-page fallback ───
                // ONLY when tier-1 returned >=1 hit (i.e., we already know
                // this IS a survey page, just need more candidates).
                // We deliberately do NOT fall back to whole-page scan when
                // tier-1 was empty — that risks picking footer / FAQ links
                // when the page actually shows a loading spinner or is in
                // transition between survey and form.
                if (answers.length >= 1 && answers.length < 2) {
                    const tier3 = Array.from(document.querySelectorAll(
                        'a, button, [role="button"], [role="radio"], label'
                    ));
                    const ptrDivs = Array.from(document.querySelectorAll('div, span, li'));
                    for (const el of ptrDivs) {
                        if (!el.offsetParent) continue;
                        try {
                            if (window.getComputedStyle(el).cursor === 'pointer') tier3.push(el);
                        } catch (e) {}
                    }
                    for (const el of tier3) {
                        if (!el.offsetParent) continue;
                        if (inChrome(el)) continue;
                        const inner = el.querySelector('a, button, [role="button"], [role="radio"]');
                        if (inner) continue;
                        const t = elText(el);
                        if (!t || t.length > 100) continue;
                        if (NAV_RE.test(t)) continue;
                        if (isAffLink(el)) continue;
                        if (/^(https?:\\/\\/|www\\.)/i.test(t)) continue;
                        if (/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(t)) continue;
                        // Reject obvious non-answer texts
                        if (/policy|terms|privacy|disclosure|disclaimer|do not sell|notice of|by clicking|click here|learn more|continue to claim|claim now/i.test(t)) continue;
                        if (seen.has(t)) continue;
                        seen.add(t);
                        answers.push(t);
                        if (answers.length >= 12) break;
                    }
                }

                // ─── Deals-page detection (STRICT) ───
                // Only Stage F deals page should match. RetailProductsUSA
                // marketing/FAQ copy mentions "Level 2 Deals" / "Complete
                // 25 Deals" — must NOT trigger.  Strategies:
                //   1. Multiple visible offer-card-like elements
                //   2. Specific CTA phrase that ONLY appears on Stage F
                //      (the speech-bubble "NEXT STEP: Complete N Deal on
                //      this level to continue.")
                //   3. "best match for you" green badge + 2+ Continue btns
                const dealCards = document.querySelectorAll(
                    '.offer-card, .deal-card, .lp-offer, ' +
                    '[class*="offer-tile"], [class*="deal-tile"], ' +
                    '[class*="offerCard"], [class*="dealCard"], ' +
                    '[class*="DealCard"], [class*="OfferCard"]'
                );
                let visibleDeals = 0;
                for (const c of dealCards) { if (c.offsetParent) visibleDeals++; }
                const strictDealText = /complete \\d+ deal on this level to continue|complete deals to claim \\$|next step:\\s*complete/i.test(txt);
                let isDeals = visibleDeals >= 2 || strictDealText;
                if (!isDeals && /best match for you/i.test(txt)) {
                    // count visible "Continue" / "Start Deal" buttons
                    const ctaBtns = document.querySelectorAll(
                        'button, a, [role="button"]'
                    );
                    let ctaCount = 0;
                    for (const b of ctaBtns) {
                        if (!b.offsetParent) continue;
                        const t2 = ((b.innerText || '').trim()).toLowerCase();
                        if (/^(continue|start deal|get offer|claim)$/i.test(t2)) ctaCount++;
                    }
                    if (ctaCount >= 2) isDeals = true;
                }

                // Multi-select markers
                const isMultiSelect = /select all that apply|select all|check all/i.test(txt);

                // Sponsored ad markers — ONLY trigger if a sponsored CTA
                // is actually present (avoid false positives from generic
                // marketing copy mentioning "insurance" etc.)
                const sponsoredCtaPresent = /\\b(yes,? i want|get a quote|find out|check eligibility|get my quote|protect my loved ones)\\b/i.test(txt);
                const sponsored = sponsoredCtaPresent;

                // Form markers — text inputs only
                const inputs = document.querySelectorAll(
                    'input[type="text"], input[type="email"], input[type="tel"], ' +
                    'input[type="number"], input[type="password"], input[type="date"], ' +
                    'input:not([type]), select, textarea'
                );
                let visibleInputs = 0;
                for (const inp of inputs) { if (inp.offsetParent) visibleInputs++; }

                // ─── Tier-1 hard-marker count — real survey answer chips ───
                // Also count .yes_btn/.no_btn (SMS opt-in / "Are you sure"
                // gates need a survey-style click, not form fill).
                let tier1Count = 0;
                for (const sel of [
                    '.choice-btn', '[data-answer]', '[data-step]', '.option-btn',
                    '.yes_btn', '.no_btn', '.yes-btn', '.no-btn',
                ]) {
                    try {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            if (el.offsetParent) tier1Count++;
                        }
                    } catch (e) {}
                }

                return {
                    question: question,
                    answers: answers,
                    isMultiSelect: isMultiSelect,
                    sponsored: sponsored,
                    isDeals: isDeals,
                    visibleInputs: visibleInputs,
                    visibleDeals: visibleDeals,
                    tier1Count: tier1Count,
                };
            }"""
        )
        if not isinstance(result, dict):
            return {"question": "", "answers": [], "isMultiSelect": False,
                    "sponsored": False, "isDeals": False, "visibleInputs": 0}
        return result
    except Exception:
        return {"question": "", "answers": [], "isMultiSelect": False,
                "sponsored": False, "isDeals": False, "visibleInputs": 0}


async def _click_text_in_page(page: Page, target_text: str) -> bool:
    """Click the FIRST visible leaf element with exact text match.
    Returns True if click succeeded."""
    try:
        # Use getByText with exact=True for safety
        loc = page.get_by_text(target_text, exact=True).first
        await loc.wait_for(state="visible", timeout=2500)
        await loc.scroll_into_view_if_needed(timeout=2000)
        await loc.click(timeout=4000)
        return True
    except Exception:
        # Fallback: DOM scan
        try:
            ok = await page.evaluate(
                """(text) => {
                    const all = Array.from(document.querySelectorAll(
                        'a, button, [role="button"], div, span, li, label'
                    ));
                    for (const el of all) {
                        if (!el.offsetParent) continue;
                        if (el.children && el.children.length > 0) continue;
                        if ((el.innerText || '').trim() === text) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                target_text,
            )
            return bool(ok)
        except Exception:
            return False


async def _try_multi_select_done(page: Page) -> bool:
    """If page has a 'select all that apply' question, check 1-2 random
    checkboxes/options then click 'Done' / 'Continue'. Returns True if
    advanced."""
    try:
        # Try real <input type=checkbox> first
        checked = await page.evaluate(
            """() => {
                const cbs = Array.from(document.querySelectorAll('input[type="checkbox"]'))
                    .filter(e => e.offsetParent && !e.disabled);
                if (cbs.length === 0) return 0;
                // Skip "I agree to terms" style — those are handled separately
                const opts = cbs.filter(cb => {
                    const lbl = (cb.closest('label')?.innerText ||
                                 document.querySelector('label[for="'+cb.id+'"]')?.innerText ||
                                 '').toLowerCase();
                    return !/agree|consent|terms|privacy|email me/.test(lbl);
                });
                if (opts.length === 0) return 0;
                // Check 1-2 random
                const n = Math.min(opts.length, Math.random() < 0.5 ? 1 : 2);
                const shuffled = opts.sort(() => 0.5 - Math.random());
                for (let i = 0; i < n; i++) {
                    if (!shuffled[i].checked) {
                        shuffled[i].click();
                    }
                }
                return n;
            }"""
        )
        if not checked:
            return False

        await page.wait_for_timeout(600)

        # Now click "Done" / "Continue" / "Next" / "Submit"
        for txt in ("Done", "Continue", "Next", "Submit", "Save", "Finish"):
            try:
                loc = page.get_by_role("button", name=txt, exact=False).first
                await loc.wait_for(state="visible", timeout=1500)
                await loc.click(timeout=3000)
                await page.wait_for_timeout(1200)
                return True
            except Exception:
                continue
        # Fallback: any visible element with text
        for txt in ("Done", "Continue", "Next", "Submit"):
            if await _click_text_in_page(page, txt):
                await page.wait_for_timeout(1200)
                return True
        return False
    except Exception as e:
        logger.debug(f"multi-select err: {e}")
        return False


async def _try_agree_and_continue(page: Page) -> bool:
    """Detect 'I agree' checkbox + Continue button (final step before
    deal wall). Only fires when there's a CLEAR agreement context — an
    explicit checkbox with agree/consent/terms label, OR explicit
    legalese near a Continue button. Plain Continue buttons on form
    pages don't qualify (those are handled by _fill_form's submit logic).
    Returns True if action taken."""
    try:
        ctx = await page.evaluate(
            """() => {
                // Check for explicit agree-checkbox
                const cbs = Array.from(document.querySelectorAll('input[type="checkbox"]'))
                    .filter(e => e.offsetParent && !e.disabled);
                let agreeCb = null;
                for (const cb of cbs) {
                    const lbl = (cb.closest('label')?.innerText ||
                                 document.querySelector('label[for="'+cb.id+'"]')?.innerText ||
                                 cb.parentElement?.innerText ||
                                 '').toLowerCase();
                    if (/i agree|i consent|i accept|terms|privacy/.test(lbl) &&
                        !/email me|sms|text alert|marketing/.test(lbl)) {
                        agreeCb = { id: cb.id, checked: cb.checked };
                        break;
                    }
                }
                // Check for legalese near a continue button
                const txt = (document.body?.innerText || '').toLowerCase();
                const hasLegalCta = /by clicking (continue|submit|get started|i agree)|i agree to (the )?(terms|email|sms|marketing)/i.test(txt);
                return { agreeCb: agreeCb, hasLegalCta: hasLegalCta };
            }"""
        )
        if not (ctx and (ctx.get("agreeCb") or ctx.get("hasLegalCta"))):
            return False

        # Tick the agree checkbox if present
        agreed = await page.evaluate(
            """() => {
                const cbs = Array.from(document.querySelectorAll('input[type="checkbox"]'))
                    .filter(e => e.offsetParent && !e.disabled);
                let count = 0;
                for (const cb of cbs) {
                    const lbl = (cb.closest('label')?.innerText ||
                                 document.querySelector('label[for="'+cb.id+'"]')?.innerText ||
                                 cb.parentElement?.innerText ||
                                 '').toLowerCase();
                    if (/i agree|i consent|i accept|terms|privacy/.test(lbl) &&
                        !/email me|sms|text alert|marketing/.test(lbl)) {
                        if (!cb.checked) { cb.click(); count++; }
                    }
                }
                return count;
            }"""
        )
        await page.wait_for_timeout(400)

        # Click Continue / Submit
        for txt in ("Continue", "Submit", "Finish", "Get My Reward",
                    "Claim", "I Agree"):
            try:
                loc = page.get_by_role("button", name=txt, exact=False).first
                await loc.wait_for(state="visible", timeout=1500)
                await loc.click(timeout=3000)
                await page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
        for txt in ("Continue", "Submit", "Finish"):
            if await _click_text_in_page(page, txt):
                await page.wait_for_timeout(1500)
                return True
        return bool(agreed)
    except Exception as e:
        logger.debug(f"agree-continue err: {e}")
        return False


async def survey_click_v2(
    page: Page,
    max_iterations: int = 30,
    picker: Optional[Any] = None,
) -> Dict[str, Any]:
    """V2: Comprehensive survey driver for Stage A + D combined.
    Loops up to `max_iterations` times. Each iteration:
        1. Detect survey state
        2. If sponsored-ad pattern, prefer bypass answer
        3. If multi-select, check 1-2 + Done
        4. Else pick random answer + click
    Returns {clicks: int, picks: List[(question_sig, answer)]}.
    """
    clicks = 0
    picks: List[Any] = []
    last_question = ""
    same_count = 0
    empty_attempts = 0  # consecutive iterations that found no question/answers

    for _i in range(max_iterations):
        # Wait extra long on first iteration — SPAs (lovable.app,
        # retailproductsusa.com) need 3-6s after page navigation before
        # answer chips appear. Subsequent iterations only wait 1.8-3s.
        wait_ms = 4500 if _i == 0 else (1800 + random.randint(0, 1200))
        try:
            await page.wait_for_timeout(wait_ms)
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        info = await _detect_survey_v2(page)
        question = info.get("question", "")
        answers = info.get("answers") or []
        is_deals = bool(info.get("isDeals"))
        visible_inputs = int(info.get("visibleInputs") or 0)
        tier1_count = int(info.get("tier1Count") or 0)

        # If we landed on the deals/offers page (Stage F), survey is over.
        if is_deals:
            logger.info("survey v2: deals page reached — stopping survey loop")
            break

        # If a real form (≥1 text input) is showing AND no hard survey markers
        # ([data-answer]/.choice-btn) are present, survey is over — let
        # _fill_form handle Stage B (email gate) or Stage C (personal info).
        if visible_inputs >= 1 and tier1_count == 0:
            logger.info(
                f"survey v2: form page reached "
                f"({visible_inputs} inputs, no tier1 chips) — yielding to _fill_form"
            )
            break

        # Stop if no question + no answers AFTER waiting longer (SPA may
        # still be rendering on first attempt)
        if not question and not answers:
            empty_attempts += 1
            if empty_attempts >= 3:
                # Try one final agree-continue in case it's a thank-you-style page
                try:
                    if await _try_agree_and_continue(page):
                        clicks += 1
                        picks.append((last_question, "[agree-continue]"))
                except Exception:
                    pass
                break
            # Wait extra and retry
            try:
                await page.wait_for_timeout(2500)
            except Exception:
                pass
            continue
        empty_attempts = 0

        # Stuck on same question? Bail.
        if question and question == last_question:
            same_count += 1
            if same_count >= 2:
                break
        else:
            same_count = 0
        last_question = question

        # Multi-select branch — check 1-2 random + click Done
        if info.get("isMultiSelect"):
            if await _try_multi_select_done(page):
                clicks += 1
                picks.append((question, "[multi-select]"))
                continue
            # If multi-select handler failed, fall through to single-pick

        if not answers:
            # No answers but question/markers present — try agree-continue
            if await _try_agree_and_continue(page):
                clicks += 1
                picks.append((question, "[agree-continue]"))
                continue
            break

        # Sponsored-ad branch — prefer bypass texts
        chosen_text = None
        if info.get("sponsored"):
            for ans in answers:
                ans_l = ans.lower()
                for bp in _SPONSORED_BYPASS:
                    if bp in ans_l:
                        chosen_text = ans
                        break
                if chosen_text:
                    break

        # SMS-opt-in / "Are you sure?" gate — prefer the "No thanks" /
        # negative option to skip and advance the flow without opting
        # the user into SMS marketing.
        if chosen_text is None:
            no_pat = re.compile(
                r"^(no|no thanks|no thank you|skip|maybe later|not now|not interested|cancel|don't|do not)\b",
                re.IGNORECASE,
            )
            ans_lowers = [a.strip().lower() for a in answers]
            has_yes = any(("yes" in a or "text me" in a or "i agree" in a) for a in ans_lowers)
            for ans in answers:
                if has_yes and no_pat.match(ans.strip()):
                    chosen_text = ans
                    break

        # Picker-biased random (AI Learning) or uniform random
        if chosen_text is None:
            if picker is not None:
                try:
                    pairs = [(None, a) for a in answers]
                    _, chosen_text = picker(question, pairs)
                except Exception:
                    chosen_text = None
            if chosen_text is None:
                chosen_text = random.choice(answers)

        # Click the chosen text
        if await _click_text_in_page(page, chosen_text):
            clicks += 1
            picks.append((question, chosen_text))
            try:
                await page.wait_for_load_state("networkidle", timeout=4500)
            except Exception:
                pass
            await page.wait_for_timeout(700)
        else:
            logger.debug(f"survey v2: failed to click '{chosen_text}'")
            # Don't break — maybe page transitioning, retry next iter
            empty_attempts += 1
            if empty_attempts >= 3:
                break

    # Final agree-continue attempt (in case last question's "I agree" page
    # doesn't have answer chips)
    try:
        if await _try_agree_and_continue(page):
            clicks += 1
            picks.append((last_question, "[final-agree]"))
    except Exception:
        pass

    return {"clicks": clicks, "picks": picks}
