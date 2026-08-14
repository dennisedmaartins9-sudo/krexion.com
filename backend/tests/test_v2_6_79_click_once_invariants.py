"""v2.6.79 — one click per visit, gateway session rotate, claim finalize."""
import os
import sys
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

_RUT = os.path.join(os.path.dirname(__file__), "..", "real_user_traffic.py")


def _src() -> str:
    with open(_RUT, encoding="utf-8") as f:
        return f.read()


def test_rotate_gateway_session_helper_exists():
    src = _src()
    assert "def _rotate_gateway_session_proxy(" in src


def test_pick_next_proxy_rotates_gateway_session():
    src = _src()
    idx = src.index("def pick_next_proxy()")
    chunk = src[idx : idx + 3200]
    assert "_rotate_gateway_session_proxy(px)" in chunk
    assert chunk.count("_rotate_gateway_session_proxy(px)") >= 2


def test_affiliate_click_fired_set_on_ptro_swap():
    src = _src()
    assert "_affiliate_click_fired = False" in src
    assert "_affiliate_click_fired = True" in src
    # v2.6.90 — pass-to-offer no longer pre-fires; browser goto sets flag.
    goto = src.index("if _is_tracker_target and not _ptro_swapped and not _affiliate_click_fired:")
    assert "_affiliate_click_fired = True" in src[goto : goto + 200]


def test_tunnel_retry_blocked_after_tracker_click():
    src = _src()
    assert "tracker click already sent" in src
    assert "_affiliate_click_fired" in src
    assert "_is_tracker_target" in src
    assert "not _ptro_swapped" in src


def test_follow_redirect_limited_after_ptro():
    src = _src()
    assert "avoid networkidle waits that can pull tracker pixels" in src
    assert "_fr_offer_host" in src


def test_finally_completes_claim_after_touch_not_release():
    src = _src()
    idx = src.index("never release after tracker/offer touch")
    chunk = src[idx : idx + 900]
    assert "complete_team_offer_ip_claim" in chunk
    assert "release_team_offer_ip_claim" in chunk
    assert chunk.index("complete_team_offer_ip_claim") < chunk.index(
        "release_team_offer_ip_claim"
    )


def test_offer_block_retry_completes_team_claim():
    src = _src()
    idx = src.index("if _can_retry_offer_block:")
    chunk = src[idx : idx + 600]
    assert "complete_team_offer_ip_claim" in chunk
