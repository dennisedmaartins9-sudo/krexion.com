"""v2.6.33 — RUT anti-detect + referrer hardening (P0/P1/P2)."""
import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-rut-v2633")

import referrer_pro  # noqa: E402
from krexion_auth_secret import get_hmac_secret, resolve_jwt_secret_for_server  # noqa: E402

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
_RUT_SRC = os.path.join(_BACKEND, "real_user_traffic.py")


def _rut_source() -> str:
    with open(_RUT_SRC, encoding="utf-8") as f:
        return f.read()


def test_hmac_secret_matches_server():
    sk = resolve_jwt_secret_for_server()
    assert get_hmac_secret() == sk
    assert get_hmac_secret() == os.environ["JWT_SECRET_KEY"]


def test_rut_build_kx_src_uses_shared_secret():
    src = _rut_source()
    assert "from krexion_auth_secret import get_hmac_secret" in src
    assert 'secret = get_hmac_secret()' in src


def test_legacy_direct_mode_source_has_traffic_type_extras():
    src = _rut_source()
    assert 'if mode in ("direct", "none", ""):' in src
    assert "_with_traffic_type_extras(cfg, \"\", referer_url=\"\")" in src


def test_legacy_auto_mode_sec_fetch_in_with_traffic_type_extras():
    src = _rut_source()
    assert "def _with_traffic_type_extras(" in src
    assert "build_sec_fetch_headers" in src
    assert 'merged["network_click_referer"] = ""' in src
    assert "referer_url: str = \"\"" in src


def test_sync_fingerprint_helper_in_source():
    src = _rut_source()
    assert "def _sync_fingerprint_to_ua(" in src
    assert "_sync_fingerprint_to_ua(ua, fp" in src
    assert "align_ua_to_chromium" in src


def test_context_retry_does_not_reroll_referer():
    src = _rut_source()
    marker = "v2.6.33 — FREEZE referer on context retry"
    assert marker in src
    idx = src.index(marker)
    chunk = src[idx : idx + 2500]
    assert "_resolve_visit_referer(ua, _referer_cfg)" not in chunk


def test_tunnel_retry_full_stealth_in_source():
    src = _rut_source()
    marker = "v2.6.33 — Re-probe geo on rotated proxy"
    assert marker in src
    idx = src.index(marker)
    # Code between geo re-probe and stealth grew; keep a wide window.
    chunk = src[idx : idx + 20000]
    assert "_rut_apply_context_stealth(" in chunk
    assert "force_referer=" in chunk


def test_rut_apply_context_stealth_helper_in_source():
    src = _rut_source()
    assert "async def _rut_apply_context_stealth(" in src
    assert "natural_canvas_js" in src
    assert "apply_v230_stealth" in src


def test_tracker_s2s_uses_curl_cffi_resolve():
    src = _rut_source()
    assert "TLS-impersonated S2S resolve first" in src
    assert "await _tls_ad.resolve_redirect_location(" in src


def test_tls_resolve_redirect_location_exported():
    from tls_anti_detect import resolve_redirect_location
    import inspect

    assert inspect.iscoroutinefunction(resolve_redirect_location)
    assert "proxy" in inspect.signature(resolve_redirect_location).parameters


def test_detect_is_paid_for_legacy_extras():
    assert referrer_pro.detect_is_paid("paid", "auto", "tiktok") is True
    assert referrer_pro.detect_is_paid("organic", "auto", "google") is False
