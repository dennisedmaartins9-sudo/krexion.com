"""v2.9.0 — AdsPower-class Cloak C++ kernel is MANDATORY for headed profiles."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_2_9_0_or_newer():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.0")


def test_kernel_module_mandates_cloak_cpp():
    src = (ROOT / "krexion_browser_kernel.py").read_text(encoding="utf-8")
    assert "v2.9.0" in src
    assert "KrexionKernelMissingError" in src
    assert "KREXION_ALLOW_STOCK_CHROMIUM" in src
    assert "HARD FAIL" in src or "hard fail" in src.lower() or "HARD FAIL" in src.upper()
    assert "KREXION_KERNEL_PATH" in src
    assert "adspower_class" in src
    assert "cpp_kernel" in src


def test_launcher_never_swallows_kernel_missing():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "KrexionKernelMissingError" in src
    assert "stock Chromium fallback is disabled" in src or "stock chromium fallback is disabled" in src.lower()
    assert "AdsPower-class Cloak C++" in src or "AdsPower-class Cloak C++" in src


def test_resolve_plan_blocks_playwright_without_escape(monkeypatch):
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    monkeypatch.delenv("KREXION_BROWSER_KERNEL", raising=False)
    from krexion_browser_kernel import KrexionKernelMissingError, resolve_launch_plan

    with pytest.raises(KrexionKernelMissingError):
        resolve_launch_plan({"browser_kernel": "playwright"}, headed_profile=True)


def test_resolve_plan_allows_playwright_with_escape(monkeypatch):
    monkeypatch.setenv("KREXION_ALLOW_STOCK_CHROMIUM", "1")
    from krexion_browser_kernel import resolve_launch_plan

    plan = resolve_launch_plan({"browser_kernel": "playwright"}, headed_profile=True)
    assert plan["engine"] == "chromium"
    assert plan["driver"] == "playwright"


def test_resolve_plan_auto_prefers_cloak_when_present(monkeypatch):
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    from krexion_browser_kernel import cloak_binary_path, resolve_launch_plan

    path = cloak_binary_path()
    if not path:
        pytest.skip("Cloak binary not installed in this environment")
    plan = resolve_launch_plan({"browser_kernel": "auto"}, headed_profile=True)
    assert plan.get("cpp_kernel") is True
    assert plan.get("adspower_class") is True
    assert plan.get("driver") == "cloak"
    assert plan.get("executable_path")


def test_headless_rut_may_use_stock_without_escape(monkeypatch):
    """RUT / automation uses headed_profile=False so stock Chromium remains OK."""
    monkeypatch.delenv("KREXION_ALLOW_STOCK_CHROMIUM", raising=False)
    monkeypatch.setenv("KREXION_BROWSER_KERNEL", "playwright")
    from krexion_browser_kernel import resolve_launch_plan

    plan = resolve_launch_plan({"browser_kernel": "playwright"}, headed_profile=False)
    assert plan["driver"] == "playwright"


def test_installer_and_electron_bundle_kernel():
    repo = ROOT.parent
    iss = (repo / "installer" / "krexion-setup.iss").read_text(encoding="utf-8", errors="ignore")
    assert "krexion-kernel" in iss
    assert "KREXION_KERNEL_PATH" in iss
    main_js = (repo / "electron-desktop" / "src" / "main.js").read_text(encoding="utf-8")
    assert "KREXION_KERNEL_PATH" in main_js
    prepare = (repo / "electron-desktop" / "scripts" / "prepare-resources.js").read_text(
        encoding="utf-8"
    )
    assert "prepareKrexionKernel" in prepare
    assert (ROOT / "scripts" / "bundle_krexion_kernel.py").is_file()


def test_prior_locks_still_present():
    """2.9.0 must KEEP 2.8.0 persist + 137 relay + 138 embed truth."""
    launcher = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    brand = (ROOT / "krexion_branded_browser.py").read_text(encoding="utf-8")
    relay = (ROOT / "proxy_auth_relay.py").read_text(encoding="utf-8")
    assert "AdsPower-class profiles ALWAYS persist to disk" in launcher or "ALWAYS persist" in launcher
    assert "GetParent" in brand
    assert "NEVER forward 407" in relay or "502 Bad Gateway" in relay
