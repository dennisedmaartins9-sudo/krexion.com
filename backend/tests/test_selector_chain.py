"""Selector + xpath fallback chain for RUT replay."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

pytest = __import__("pytest")
playwright = pytest.importorskip("playwright")

from real_user_traffic import _selector_chain_for_step, _step_fallbacks  # noqa: E402


def test_step_fallbacks_includes_xpath():
    step = {
        "selector": "#sub-btn",
        "xpath": "//button[@id='sub-btn']",
        "fallbacks": {
            "xpath": "//button[@id='sub-btn']",
            "xpath_abs": "/html/body/div[1]/button[1]",
            "tag": "button",
            "attrs": {"id": "sub-btn"},
        },
    }
    alts = _step_fallbacks(step)
    assert any("xpath=" in a or a.startswith("//") for a in alts)
    assert any("sub-btn" in a for a in alts)


def test_selector_chain_primary_then_xpath():
    step = {
        "selector": "#sub-btn",
        "xpath": "//button[@id='sub-btn']",
        "fallbacks": {"xpath": "//button[@id='sub-btn']", "tag": "button"},
    }
    chain = _selector_chain_for_step(step, "#sub-btn")
    assert chain[0] == "#sub-btn"
    assert any("xpath" in c or c.startswith("//") for c in chain[1:])
