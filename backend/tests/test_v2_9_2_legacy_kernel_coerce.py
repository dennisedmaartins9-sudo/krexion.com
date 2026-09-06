"""v2.9.2 — Legacy browser_kernel prefs coerce to auto on Open."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_9_2():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.2")


def test_launcher_coerces_legacy_stock_kernel_prefs():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "coercing legacy browser_kernel" in src
    assert 'anti["browser_kernel"] = "auto"' in src
    assert '("playwright", "patchright", "chrome")' in src
    assert '_ad_patch["browser_kernel"] = "auto"' in src
    assert "_coerced_legacy_kernel" in src


def test_public_view_coerces_legacy_kernel_for_ui(monkeypatch):
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    from browser_profile_module import _public_view

    out = _public_view(
        {
            "id": "p1",
            "user_id": "u1",
            "name": "legacy",
            "anti_detect": {"browser_kernel": "playwright", "master": True},
        }
    )
    assert (out.get("anti_detect") or {}).get("browser_kernel") == "auto"


def test_kernel_still_blocks_explicit_playwright_without_escape(monkeypatch):
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    from krexion_browser_kernel import KrexionKernelMissingError, resolve_launch_plan
    import pytest

    with pytest.raises(KrexionKernelMissingError):
        resolve_launch_plan({"browser_kernel": "playwright"}, headed_profile=True)
