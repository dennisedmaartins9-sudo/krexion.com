"""Visual Recorder modal click capture — bestElementAtPoint + live click helper."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from visual_recorder import (  # noqa: E402
    _DETECT_POPUP_BUTTONS_JS,
    _RICH_ELEMENT_CAPTURE_JS,
    _build_text_click_evaluate,
    _live_click_captured,
    _locator_candidates_from_info,
)


def test_rich_capture_js_has_modal_aware_hit_testing():
    assert "bestElementAtPoint" in _RICH_ELEMENT_CAPTURE_JS
    assert "elementsFromPoint" in _RICH_ELEMENT_CAPTURE_JS
    assert "findModalContainer" in _RICH_ELEMENT_CAPTURE_JS
    assert "isBackdropOrOverlay" in _RICH_ELEMENT_CAPTURE_JS


def test_locator_candidates_from_modal_button_info():
    info = {
        "id": "cpa_linkout_btn",
        "tag": "BUTTON",
        "attrs": {
            "id": "cpa_linkout_btn",
            "name": "start_deal",
            "data-testid": "start-deal-cta",
            "aria-label": "START DEAL",
        },
    }
    cands = _locator_candidates_from_info(info)
    assert '[data-testid="start-deal-cta"]' in cands
    assert "#cpa_linkout_btn" in cands
    assert 'button[name="start_deal"]' in cands
    assert '[aria-label="START DEAL"]' in cands


def test_build_text_click_evaluate_includes_id_selector():
    info = {
        "id": "cpa_linkout_btn",
        "tag": "BUTTON",
        "text": "START DEAL",
        "attrs": {"id": "cpa_linkout_btn"},
    }
    step = _build_text_click_evaluate("START DEAL", info)
    assert step["action"] == "evaluate"
    assert "#cpa_linkout_btn" in step["script"]
    assert "_krxClick" in step["script"]


class _StubLocator:
    def __init__(self, label: str, click_ok: bool = True, force_ok: bool = True):
        self._label = label
        self._click_ok = click_ok
        self._force_ok = force_ok
        self.clicked = False
        self.force = False

    @property
    def first(self):
        return self

    async def click(self, timeout=3000, force=False):
        if force:
            if not self._force_ok:
                raise RuntimeError(f"force click failed: {self._label}")
        elif not self._click_ok:
            raise RuntimeError(f"click failed: {self._label}")
        self.clicked = True
        self.force = force

    async def evaluate(self, script: str):
        if not self._click_ok:
            raise RuntimeError(f"evaluate failed: {self._label}")
        return True


class _StubFrameLocator:
    def __init__(self, sel: str, locator_map: Dict[str, _StubLocator]):
        self._sel = sel
        self._locator_map = locator_map

    def frame_locator(self, sel: str):
        return _StubFrameLocator(f"{self._sel}>{sel}", self._locator_map)

    def locator(self, inner: str):
        key = f"{self._sel}|locator|{inner}"
        return self._locator_map.setdefault(key, _StubLocator(key))

    def get_by_text(self, text: str, exact=False):
        key = f"{self._sel}|text|{text}|{exact}"
        return self._locator_map.setdefault(key, _StubLocator(key))


class _StubPage:
    def __init__(self):
        self._locator_map: Dict[str, _StubLocator] = {}
        self.evaluate = AsyncMock(return_value=True)
        self.mouse = MagicMock()
        self.mouse.click = AsyncMock(return_value=True)

    def frame_locator(self, sel: str):
        return _StubFrameLocator(sel, self._locator_map)

    def locator(self, inner: str):
        key = f"page|locator|{inner}"
        return self._locator_map.setdefault(key, _StubLocator(key))

    def get_by_text(self, text: str, exact=False):
        key = f"page|text|{text}|{exact}"
        return self._locator_map.setdefault(key, _StubLocator(key))


def test_detect_popup_buttons_js_scans_top_popup_only():
    assert "findPopupAtViewportCenter" in _DETECT_POPUP_BUTTONS_JS
    assert "scanPopups" in _DETECT_POPUP_BUTTONS_JS
    assert "isTopHit" in _DETECT_POPUP_BUTTONS_JS
    assert "isClickableInPopup" in _DETECT_POPUP_BUTTONS_JS
    assert "top_popup_only" in _DETECT_POPUP_BUTTONS_JS


def test_rich_capture_prefers_interactive_in_modal():
    assert "bestInteractive" in _RICH_ELEMENT_CAPTURE_JS
    assert "cursor === 'pointer'" in _RICH_ELEMENT_CAPTURE_JS


def test_live_click_captured_force_fallback_after_normal_fails():
    page = _StubPage()
    info = {
        "id": "cpa_linkout_btn",
        "tag": "BUTTON",
        "text": "",
        "x": 200,
        "y": 400,
        "attrs": {"id": "cpa_linkout_btn"},
    }
    loc = page.locator("#cpa_linkout_btn")
    loc._click_ok = False
    loc._force_ok = True
    page.evaluate = AsyncMock(side_effect=RuntimeError("js failed"))
    ok = asyncio.run(_live_click_captured(page, info))
    assert ok is True
    assert loc.force is True


def test_live_click_captured_prefers_coordinate_robust_click():
    """Grey React CTAs: coordinate pointer-click runs before id locator."""
    page = _StubPage()
    info = {
        "id": "cpa_linkout_btn",
        "tag": "BUTTON",
        "text": "START DEAL",
        "x": 200,
        "y": 400,
        "attrs": {"id": "cpa_linkout_btn"},
    }
    ok = asyncio.run(_live_click_captured(page, info))
    assert ok is True
    page.evaluate.assert_called_once()
    loc = page.locator("#cpa_linkout_btn")
    assert loc.clicked is False
    page.mouse.click.assert_not_called()


def test_live_click_captured_uses_id_locator():
    page = _StubPage()
    page.evaluate = AsyncMock(return_value=False)
    info = {
        "id": "cpa_linkout_btn",
        "tag": "BUTTON",
        "text": "START DEAL",
        "x": 200,
        "y": 400,
        "attrs": {"id": "cpa_linkout_btn"},
    }
    ok = asyncio.run(_live_click_captured(page, info))
    assert ok is True
    loc = page.locator("#cpa_linkout_btn")
    assert loc.clicked is True
    page.mouse.click.assert_not_called()


def test_live_click_captured_iframe_path_chain():
    page = _StubPage()
    info = {
        "id": "submitBtn",
        "tag": "BUTTON",
        "text": "Submit",
        "iframe_path": ["iframe#modal", "iframe.nested"],
        "attrs": {"id": "submitBtn"},
    }
    ok = asyncio.run(_live_click_captured(page, info))
    assert ok is True
    fl_key = "iframe#modal>iframe.nested|locator|#submitBtn"
    assert fl_key in page._locator_map
    assert page._locator_map[fl_key].clicked is True


def test_live_click_captured_falls_back_to_mouse():
    page = _StubPage()
    # Force all locators to fail
    for loc in page._locator_map.values():
        loc._click_ok = False
    page.evaluate = AsyncMock(side_effect=RuntimeError("js failed"))

    info = {"text": "", "x": 150, "y": 250, "attrs": {}}
    ok = asyncio.run(_live_click_captured(page, info))
    assert ok is True
    page.mouse.click.assert_called_once_with(150, 250)
