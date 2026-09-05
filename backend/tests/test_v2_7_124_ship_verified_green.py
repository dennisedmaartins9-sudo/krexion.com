"""v2.7.124 — Ship-gate verified green lock (anti-detect + saved-proxy)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_124():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.124")


def test_anti_detect_123_path_still_locked():
    rut = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    ade = (ROOT / "anti_detect_engine.py").read_text(encoding="utf-8")
    fe = (REPO / "frontend/src/pages/RealUserTrafficPage.js").read_text(encoding="utf-8")
    bp = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    launcher = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")

    assert "from krexion_browser_kernel import" in rut
    assert "resolve_launch_plan" in rut
    assert "TLS prewarm OFF for this job" in rut
    assert '"exitIp"' in rut
    assert "typ srflx" in rut
    assert "Chrome/136" in ade
    assert "build_fingerprint_win_js" in ade
    assert "tlsPrewarmEffective" in fe
    assert "rut-ad-chain-honesty" in fe
    assert "bp-strict-proxy-off-warn" in bp
    assert "REAL MACHINE IP may be exposed" in launcher


def test_saved_proxy_path_still_locked():
    bpm = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    srv = (ROOT / "server.py").read_text(encoding="utf-8")
    fe = (REPO / "frontend/src/pages/BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "No profiles were created" in bpm
    assert "require_verified" in srv
    assert "bp-saved-proxy-count-mismatch" in fe or "saved-proxy-count-mismatch" in fe
