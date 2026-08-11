"""v2.6.77 — Pass-Referer-To-Offer must hit the tracker via unique proxy IP.

Affiliate Clicks vs Hosts broke when resolve used the customer PC + XFF.
These tests lock the proxy-first path and the no-XFF-on-external rule.
"""
import inspect
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

from tls_anti_detect import resolve_redirect_location
from real_user_traffic import (
    _pass_to_offer_resolve_headers,
    _safe_tracker_redirect_location,
)

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
_RUT_SRC = os.path.join(_BACKEND, "real_user_traffic.py")
_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36"
)


def _rut_source() -> str:
    with open(_RUT_SRC, encoding="utf-8") as f:
        return f.read()


def test_pass_to_offer_headers_omit_xff_on_proxy_path():
    headers = _pass_to_offer_resolve_headers(_UA, referer="https://www.tiktok.com/")
    assert "X-Forwarded-For" not in headers
    assert "X-Real-IP" not in headers
    assert "True-Client-IP" not in headers
    assert headers["User-Agent"] == _UA
    assert headers["Referer"] == "https://www.tiktok.com/"


def test_pass_to_offer_headers_xff_only_when_spoofed():
    headers = _pass_to_offer_resolve_headers(_UA, spoof_xff_ip="203.0.113.9")
    assert headers["X-Forwarded-For"] == "203.0.113.9"
    assert headers["X-Real-IP"] == "203.0.113.9"


def test_safe_redirect_rejects_loopback():
    assert _safe_tracker_redirect_location("https://offer.example/x") == "https://offer.example/x"
    assert _safe_tracker_redirect_location("http://127.0.0.1:8001/offer") is None
    assert _safe_tracker_redirect_location("http://localhost/offer") is None
    assert _safe_tracker_redirect_location("") is None


def test_tls_resolve_redirect_accepts_proxy():
    params = inspect.signature(resolve_redirect_location).parameters
    assert "proxy" in params


def test_pass_to_offer_call_passes_visit_proxy():
    src = _rut_source()
    assert "proxy=_effective_proxy or proxy," in src
    assert "allow_direct_xff=True," in src
    assert "proxy: Optional[Dict[str, Any]] = None," in src
    assert "allow_direct_xff: bool = False," in src


def test_external_tracker_does_not_fallback_to_pc_xff():
    src = _rut_source()
    assert "if not own_tracker and not allow_direct_xff:" in src
    assert "return None" in src
    assert "External affiliate trackers never fall back to PC-IP + XFF" in src


def test_defer_qs_only_for_own_tracker():
    src = _rut_source()
    assert "own_tracker and (visit_token or \"\").strip()" in src
    assert "target_url = _append_rut_defer_click_qs(target_url, visit_token)" in src


def test_ui_copy_no_longer_promises_xff_click_ip():
    frontend = os.path.join(_BACKEND, "..", "frontend", "src", "pages", "RealUserTrafficPage.js")
    text = open(frontend, encoding="utf-8").read()
    assert "through your unique residential proxy" in text
    assert "click is still recorded with the proxy exit IP via" not in text
