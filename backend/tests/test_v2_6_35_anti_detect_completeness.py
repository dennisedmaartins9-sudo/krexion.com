"""
v2.6.35 — Anti-detect audit completeness fixes
"""
import importlib
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUT_FILE = REPO_ROOT / "real_user_traffic.py"
SERVER_FILE = REPO_ROOT / "server.py"
sys.path.insert(0, str(REPO_ROOT))


def _ad():
    return importlib.import_module("anti_detect_v230")


def test_pixel_prefire_urls_tiktok_non_empty():
    ad = _ad()
    urls = ad.pixel_prefire_urls("tiktok", ttclid="E.C.test123")
    assert urls
    assert any("tiktok.com" in u for u in urls)


def test_intermediate_hop_urls_facebook():
    ad = _ad()
    hops = ad.intermediate_hop_urls("facebook", "https://example.com/offer", hops=1)
    assert len(hops) == 1
    assert any(x in hops[0] for x in ("facebook.com", "messenger.com"))


def test_fire_pixel_prefire_and_navigate_helpers_exist():
    ad = _ad()
    assert inspect.iscoroutinefunction(ad.fire_pixel_prefire)
    assert inspect.iscoroutinefunction(ad.navigate_intermediate_hops)


def test_rut_ad_chain_default_is_disabled():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert re.search(r"tls_prewarm:\s*bool\s*=\s*True", src)
    assert re.search(r"ip_warmup_enabled:\s*bool\s*=\s*False", src)
    assert re.search(r"behavioral_bio_enabled:\s*bool\s*=\s*True", src)
    assert re.search(r"ad_chain_simulation_enabled:\s*bool\s*=\s*False", src)


def test_auto_identity_label():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "def _auto_identity_label(" in src
    assert 'return f"rut-{slug}"' in src
    assert "_auto_identity_label(job_id)" in src


def test_sanitize_swiftshader_webgl():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "def _sanitize_swiftshader_webgl(" in src
    assert "_sanitize_swiftshader_webgl(" in src
    assert "swiftshader" in src.lower()


def test_launch_browser_prefers_executable_path():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "executable_path=str(fc_exe)" in src
    assert "chromium-headless-shell fallback" in src


def test_ad_chain_helpers_remain_compatible_but_execution_is_disabled():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "ad_chain_simulation_enabled" in src
    assert "fire_pixel_prefire" in src
    assert "navigate_intermediate_hops" in src
    assert "if False:  # globally disabled: no pixel prefire/intermediate hop" in src


def test_server_ad_chain_form_default_is_disabled():
    src = SERVER_FILE.read_text(encoding="utf-8")
    assert "tls_prewarm: bool = Form(True)" in src
    assert "ip_warmup_enabled: bool = Form(False)" in src
    assert "behavioral_bio_enabled: bool = Form(True)" in src
    assert "ad_chain_simulation_enabled: bool = Form(False)" in src
    assert "ip_quality_check_enabled: bool = Form(True)" in src


def test_cdp_stealth_in_v230_bundle():
    ad = _ad()
    bundle = ad.build_v230_stealth_bundle()
    assert "cdp_stealth_js" not in bundle  # function name not in output
    assert "__playwright" in bundle or "__pw" in bundle
    src = (REPO_ROOT / "anti_detect_v230.py").read_text(encoding="utf-8")
    assert "def cdp_stealth_js(" in src
    assert "cdp_stealth_js()," in src


def test_tls_companion_prewarm_exists():
    src = (REPO_ROOT / "tls_anti_detect.py").read_text(encoding="utf-8")
    assert "async def prewarm_companion_origins(" in src
    rut = RUT_FILE.read_text(encoding="utf-8")
    assert "prewarm_companion_origins" in rut


def test_ip_quality_assessment_wired():
    src = RUT_FILE.read_text(encoding="utf-8")
    assert "def _assess_ip_quality(" in src
    assert "ip_quality_check_enabled" in src
    assert "skipped_low_quality_ip" in src


def test_chromium_major_detection():
    ad = _ad()
    assert hasattr(ad, "detect_installed_chromium_major")
    assert inspect.isfunction(ad.detect_installed_chromium_major)
