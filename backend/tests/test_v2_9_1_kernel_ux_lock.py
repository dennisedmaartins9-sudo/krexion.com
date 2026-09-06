"""v2.9.1 — Residual AdsPower-kernel UX lock (no stock options in UI/API)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_2_9_1_or_newer():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.1")


def test_fe_removed_stock_kernel_options():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    text = fe.read_text(encoding="utf-8")
    assert 'value="cloak"' in text
    assert 'value="playwright"' not in text
    assert 'value="patchright"' not in text
    assert 'value="chrome"' not in text


def test_api_rejects_stock_kernel_without_escape(monkeypatch):
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    from browser_profile_module import AntiDetectConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AntiDetectConfig(browser_kernel="playwright")
    with pytest.raises(ValidationError):
        AntiDetectConfig(browser_kernel="chrome")
    assert AntiDetectConfig(browser_kernel="auto").browser_kernel == "auto"
    assert AntiDetectConfig(browser_kernel="cloak").browser_kernel == "cloak"


def test_api_allows_stock_kernel_with_escape(monkeypatch):
    monkeypatch.setenv("KREXION_ALLOW_STOCK_CHROMIUM", "1")
    from browser_profile_module import AntiDetectConfig

    assert AntiDetectConfig(browser_kernel="playwright").browser_kernel == "playwright"
