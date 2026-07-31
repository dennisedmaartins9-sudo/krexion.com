"""RUT iframe_path helper — frame_locator chain from step fallbacks."""
from __future__ import annotations

import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

sys.modules.setdefault("user_agents", types.ModuleType("user_agents"))
sys.modules["user_agents"].parse = lambda *a, **k: None  # type: ignore[attr-defined]

sys.modules["playwright"] = types.ModuleType("playwright")
_pw_async = types.ModuleType("playwright.async_api")


class _StubPage:
    def frame_locator(self, sel):
        return _StubFrameLocator(sel)


class _StubFrameLocator:
    def __init__(self, sel):
        self._sel = sel

    def frame_locator(self, sel):
        return _StubFrameLocator(f"{self._sel}>{sel}")

    def locator(self, inner):
        return inner


_pw_async.Page = _StubPage  # type: ignore[attr-defined]
_pw_async.Browser = type("Browser", (), {})  # type: ignore[attr-defined]
_pw_async.BrowserContext = type("BrowserContext", (), {})  # type: ignore[attr-defined]
_pw_async.async_playwright = lambda: None  # type: ignore[attr-defined]
sys.modules["playwright.async_api"] = _pw_async
sys.modules.setdefault("pandas", types.ModuleType("pandas"))
sys.modules.pop("real_user_traffic", None)

import real_user_traffic as rut


def test_step_iframe_path_from_fallbacks():
    step = {"action": "click", "selector": "#btn", "fallbacks": {"iframe_path": ["iframe#modal", "iframe.nested"]}}
    assert rut._step_iframe_path(step) == ["iframe#modal", "iframe.nested"]


def test_step_iframe_path_top_level():
    step = {"iframe_path": ["iframe#a"]}
    assert rut._step_iframe_path(step) == ["iframe#a"]


def test_frame_locator_chain_builds_nested():
    page = _StubPage()
    step = {"fallbacks": {"iframe_path": ["iframe#outer", "iframe#inner"]}}
    fl = rut._frame_locator_for_step(page, step)
    assert fl is not None
    assert isinstance(fl, _StubFrameLocator)
    assert fl._sel == "iframe#outer>iframe#inner"
