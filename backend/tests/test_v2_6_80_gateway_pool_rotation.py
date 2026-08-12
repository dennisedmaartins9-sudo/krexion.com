"""v2.6.80 — ROW-FIRST gateway pool rotation + session preserve."""
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


def test_row_first_rotates_gateway_candidates():
    src = _src()
    assert "_gw_candidates[(attempt - 1) % len(_gw_candidates)]" in src
    assert "_gw_template" not in src


def test_rotate_gateway_preserves_embedded_targeting():
    src = _src()
    chunk = src.split("def _rotate_gateway_session_proxy", 1)[1].split("\ndef ", 1)[0]
    assert "_extract_embedded_gateway_targeting" in chunk
    assert "_build_state_targeted_proxy(base, _state, _country)" in chunk


def test_build_state_targeted_no_early_return_without_state():
    src = _src()
    chunk = src.split("def _build_state_targeted_proxy", 1)[1].split("\ndef ", 1)[0]
    assert "if not _state and not _country:" not in chunk


def test_probe_tries_both_proxy_schemes():
    src = _src()
    assert "def _proxy_url_scheme_variants(" in src
    assert "_proxy_url_scheme_variants(server)" in src
