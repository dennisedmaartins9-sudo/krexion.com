"""v2.7.16 — CloakBrowser / Patchright kernel path to close Octo gap."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_kernel_module_exists():
    src = (ROOT / "krexion_browser_kernel.py").read_text(encoding="utf-8")
    assert "cloak_binary_path" in src
    assert "resolve_launch_plan" in src
    assert "cloakbrowser-cpp" in src
    assert "patchright" in src


def test_antidetect_has_browser_kernel():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig()
    assert cfg.browser_kernel == "auto"


def test_launcher_wires_kernel_plan():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "resolve_launch_plan" in src
    assert "_krx_launch_chromium" in src
    assert "reduce_js_fingerprint_noise" in src
    assert 'engine") or "") == "firefox"' in src or '== "firefox"' in src


def test_local_kernel_route():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/local/kernel"' in src
    assert "Octium" in src or "cloak" in src.lower()


def test_frontend_kernel_select():
    fe = ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"
    text = fe.read_text(encoding="utf-8")
    assert 'browser_kernel: "auto"' in text
    assert 'data-testid="bp-browser-kernel"' in text
    # White-label: customer UI shows Krexion Browser Stealth (no CloakBrowser vendor string)
    assert "Krexion Browser Stealth" in text or "Krexion Stealth" in text
    assert "CloakBrowser" not in text
    assert 'value="cloak"' in text  # internal kernel value
    # v2.9.1 — stock Playwright / Patchright / system Chrome removed from UI
    assert 'value="playwright"' not in text
    assert 'value="patchright"' not in text
    assert 'value="chrome"' not in text
    assert "bundled Krexion C++ stealth kernel" in text
    assert "Stock Playwright Chromium is not used" in text


def test_resolve_plan_smoke(monkeypatch):
    # v2.9.0 — playwright preference requires stock escape hatch for headed plans
    monkeypatch.setenv("KREXION_ALLOW_STOCK_CHROMIUM", "1")
    from krexion_browser_kernel import resolve_launch_plan

    plan = resolve_launch_plan({"browser_kernel": "playwright"})
    assert plan["driver"] == "playwright"
    assert plan["engine"] == "chromium"
    plan_ff = resolve_launch_plan({"browser_kernel": "firefox"})
    assert plan_ff["engine"] == "firefox"
