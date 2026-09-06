"""Form fill must not re-open the offer/tracker URL (1 click == 1 host)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

from real_user_traffic import (  # noqa: E402
    _click_url_fingerprint,
    _is_repeat_offer_click,
    _url_has_affiliate_click_params,
)

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"
FF = Path(__file__).resolve().parents[1] / "form_filler.py"
FLASH = Path(__file__).resolve().parents[1] / "rut_flash_helpers.py"


def test_same_affise_offer_is_repeat_even_with_extra_query():
    orig = "https://adsmain.affise.com/click?offer_id=99&sub1=tiktok"
    again = "https://adsmain.affise.com/click?offer_id=99&sub1=retry"
    assert _is_repeat_offer_click(again, orig) is True


def test_different_affise_offer_id_is_not_repeat():
    orig = "https://adsmain.affise.com/click?offer_id=99"
    deal = "https://adsmain.affise.com/click?offer_id=100"
    assert _is_repeat_offer_click(deal, orig) is False


def test_krexion_tracker_code_is_repeat():
    orig = "https://krexion.com/api/t/abc123?kx=1"
    again = "https://krexion.com/api/t/abc123"
    other = "https://krexion.com/api/t/other"
    assert _is_repeat_offer_click(again, orig) is True
    assert _is_repeat_offer_click(other, orig) is False


def test_relative_aff_c_href_resolved_against_page():
    orig = "https://giftclick.org/aff_c?offer_id=7"
    assert _is_repeat_offer_click(
        "/aff_c?offer_id=7", orig, "https://giftclick.org/landing"
    ) is True


def test_fingerprint_strips_sub_params():
    a = _click_url_fingerprint("https://x.affise.com/click?offer_id=1&sub1=a")
    b = _click_url_fingerprint("https://x.affise.com/click?offer_id=1&sub2=b")
    assert a == b


def test_macro_guard_aborts_after_first_click():
    src = RUT.read_text(encoding="utf-8")
    assert "click_once_guard" in src
    assert "if click_once_guard and click_once_guard.get(\"fired\"):" in src
    assert "_is_repeat_offer_click(url, orig)" in src
    assert "await route.abort()" in src


def test_form_fill_skips_offer_href_cta():
    src = FF.read_text(encoding="utf-8")
    assert "skip_repeat_click" in src
    assert "if href and skip_repeat_click(href, page_url):" in src


def test_deals_skip_same_offer_href_and_prefer_go_back():
    src = FLASH.read_text(encoding="utf-8")
    assert "skip_repeat_click" in src
    assert "if skip_repeat_click(href, page.url or \"\"):" in src
    assert "await page.go_back(" in src


def test_auto_continue_does_not_assign_tracker_hrefs():
    src = RUT.read_text(encoding="utf-8")
    assert "if(href && /" in src
    assert "affise.com" in src
    assert "/api/t/" in src


def test_automation_goto_skips_repeat_offer_url():
    src = RUT.read_text(encoding="utf-8")
    assert "click_once_guard=_click_once_guard" in src
    assert "_is_repeat_offer_click(_dest, _orig)" in src


def test_aff_c_query_param_detected():
    """?aff_c= in query string must be caught (not just /aff_c in path)."""
    assert _url_has_affiliate_click_params("https://offer.com/page?aff_c=123") is True
    assert _url_has_affiliate_click_params("https://offer.com/page?sub1=x&aff_c=offer_59804") is True
    assert _url_has_affiliate_click_params("https://offer.com/page?sub1=x") is False
    assert _url_has_affiliate_click_params("https://x.com/click.php?o=1") is True
    assert _url_has_affiliate_click_params("https://x.affise.com/go") is False  # no aff params
    assert _url_has_affiliate_click_params("https://krexion.com/api/t/ABC") is True


def test_offer_url_stored_in_guard_after_redirect():
    src = RUT.read_text(encoding="utf-8")
    assert 'offer_url' in src
    assert '_click_once_guard["offer_url"]' in src


def test_guard_checks_offer_url_and_aff_params():
    src = RUT.read_text(encoding="utf-8")
    assert 'click_once_guard.get("offer_url")' in src
    assert '_url_has_affiliate_click_params' in src


def test_skip_repeat_checks_offer_url():
    src = RUT.read_text(encoding="utf-8")
    idx = src.index("def _skip_repeat_click_href")
    block = src[idx : idx + 800]
    assert 'offer_url' in block
    assert '_url_has_affiliate_click_params' in block


def test_auto_continue_regex_catches_query_aff_c():
    """JS regex must match ?aff_c= and &aff_c= (not just /aff_c)."""
    src = RUT.read_text(encoding="utf-8")
    assert "[\\\\/?&]aff_c" in src or "[?&]aff_c" in src


def test_robust_click_js_skips_aff_links():
    src = RUT.read_text(encoding="utf-8")
    idx = src.index("_ROBUST_CLICK_SELECTOR_JS")
    block = src[idx : idx + 1500]
    assert "aff_c" in block
    assert "offer_id" in block


def test_automation_continue_js_has_href_filter():
    src = RUT.read_text(encoding="utf-8")
    idx = src.index("_ac_continue_js")
    block = src[idx : idx + 1500]
    assert "aff_c" in block


def test_version_is_current():
    from releases_module import _parse
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert _parse(version) >= _parse("2.6.95")
