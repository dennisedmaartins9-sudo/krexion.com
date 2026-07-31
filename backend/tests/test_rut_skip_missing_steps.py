"""RUT should skip steps whose selectors are absent instead of failing the visit."""
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
    pass


_pw_async.Page = _StubPage  # type: ignore[attr-defined]
_pw_async.Browser = type("Browser", (), {})  # type: ignore[attr-defined]
_pw_async.BrowserContext = type("BrowserContext", (), {})  # type: ignore[attr-defined]
_pw_async.async_playwright = lambda: None  # type: ignore[attr-defined]
sys.modules["playwright.async_api"] = _pw_async
sys.modules.setdefault("pandas", types.ModuleType("pandas"))
sys.modules["pandas"].read_excel = lambda *a, **k: None  # type: ignore[attr-defined]
sys.modules.pop("real_user_traffic", None)

import real_user_traffic as rut


def test_is_step_miss_error_detects_timeout_and_not_found():
    assert rut._is_step_miss_error("Timeout 25000ms exceeded waiting for selector")
    assert rut._is_step_miss_error("Element not found: #missing-btn")
    assert rut._is_step_miss_error("waiting for selector div.cta to be visible")
    assert not rut._is_step_miss_error("SyntaxError: unexpected token")
    assert not rut._is_step_miss_error("Step evaluate returned false")


def test_skip_missing_steps_default_enabled_on_executor():
    import inspect

    sig = inspect.signature(rut._execute_automation_steps)
    assert sig.parameters["skip_missing_steps"].default is True
