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


def test_version_is_2_6_95():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert version == "2.6.95"
