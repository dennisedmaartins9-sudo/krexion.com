"""v2.7.15 — Krexion antidetect WIN bundle (modes, local API, fingerprint, cookie-robot)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_antidetect_config_has_new_fields():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig()
    assert cfg.canvas_mode == "noise"
    assert cfg.webgl_mode == "noise"
    assert cfg.audio_mode == "noise"
    assert cfg.font_mode == "noise"
    assert cfg.webrtc_mode == "proxy"
    assert cfg.use_persistent_context is False
    assert cfg.proxy_check_on_launch is True
    assert cfg.proxy_check_block_on_fail is False
    assert cfg.tls_prewarm is True


def test_launcher_tls_prewarm_default_true_and_modes():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert 'anti.get("tls_prewarm", True)' in src
    assert "webrtc_mode" in src
    assert "canvas_mode" in src
    assert "warm_profile_cookies" in src
    assert "proxy_check_on_launch" in src
    assert "launch_persistent_context" in src


def test_local_docs_and_profiles_routes_exist():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/local/docs"' in src
    assert '"/local/profiles"' in src
    assert '"/local/profiles/{profile_id}/cookies"' in src
    assert "KREXION_LOCAL_API_KEY" in src
    assert "_enforce_local_api_key" in src


def test_cookie_robot_and_fingerprint_routes_exist():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/{profile_id}/cookie-robot"' in src
    assert '"/{profile_id}/fingerprint"' in src
    assert "CookieRobotBody" in src
    assert "fingerprint_preview" in src


def test_version_2_7_15_or_newer():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    # Bundle introduced in 2.7.15; later patches keep features
    assert ver >= "2.7.15"
