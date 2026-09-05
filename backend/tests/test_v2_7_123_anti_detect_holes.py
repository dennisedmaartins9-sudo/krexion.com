"""v2.7.123 — Anti-detect holes closed (TLS honesty, kernel, WebRTC, UA sync)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_123():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.123")


def test_ua_pool_chrome_136():
    src = (ROOT / "anti_detect_engine.py").read_text(encoding="utf-8")
    pool = src.split("_DEFAULT_UA_POOL")[1].split("]")[0]
    assert "Chrome/136" in pool
    assert "Chrome/131" not in pool
    assert "Chrome/130" not in pool


def test_rut_kernel_launch_wired():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "from krexion_browser_kernel import" in src
    assert "resolve_launch_plan" in src
    assert "launch_chromium_with_plan" in src
    assert "get_async_playwright_factory" in src
    assert "CloakBrowser / Patchright kernel" in src


def test_rut_tls_honesty_when_skip_dup():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "TLS prewarm OFF for this job" in src
    fe = (REPO / "frontend/src/pages/RealUserTrafficPage.js").read_text(encoding="utf-8")
    assert "tlsPrewarmEffective" in fe
    assert "rut-ad-chain-honesty" in fe
    assert "TLS prewarm is forced OFF" in fe


def test_webrtc_exit_ip_rewrite():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert '"exitIp"' in src
    assert "typ srflx" in src


def test_stealth_context_fingerprint_win():
    src = (ROOT / "anti_detect_engine.py").read_text(encoding="utf-8")
    assert "build_fingerprint_win_js" in src


def test_strict_proxy_off_warn():
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "bp-strict-proxy-off-warn" in fe
    launcher = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "REAL MACHINE IP may be exposed" in launcher
