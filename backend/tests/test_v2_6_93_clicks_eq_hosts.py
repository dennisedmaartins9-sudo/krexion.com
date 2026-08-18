"""v2.6.93 — one Affise/Everflow document GET per exit IP (Clicks == Hosts)."""
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

from real_user_traffic import _url_is_affiliate_click_target  # noqa: E402

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_affise_and_krexion_are_click_once_urls():
    assert _url_is_affiliate_click_target("https://krexion.com/api/t/abc") is True
    assert _url_is_affiliate_click_target("https://adsmain.affise.com/click") is True
    assert _url_is_affiliate_click_target("https://giftclick.org/aff_c?offer_id=1") is True
    assert _url_is_affiliate_click_target("https://www.tiktok.com/@x") is False
    assert _url_is_affiliate_click_target("https://offer-landing.example/form") is False


def test_err_aborted_does_not_retry_click_url():
    src = _src()
    assert "ERR_ABORTED on click URL — not retrying goto" in src
    assert "_click_once_nav" in src
    idx = src.index("ERR_ABORTED on click URL — not retrying goto")
    assert "page.goto" not in src[idx : idx + 200]


def test_form_reload_skips_tracker_url():
    src = _src()
    assert "not re-opening tracker URL" in src
    assert "await page.reload(" in src
    idx = src.index("Invalid-lead retry on current page")
    chunk = src[idx - 900 : idx + 200]
    assert "page.reload(" in chunk
    assert "page.goto(_visit_target_url" not in chunk


def test_networkidle_skipped_on_click_once():
    src = _src()
    assert "never networkidle on click-once flows" in src
