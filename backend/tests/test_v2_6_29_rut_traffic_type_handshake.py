"""v2.6.29 — RUT signed traffic_type handshake + legacy referer extras."""
import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-rut-handshake")

import referrer_pro  # noqa: E402


def _mirror_rut_kx_qs(platform: str, traffic_type: str = "") -> str:
    """Mirror real_user_traffic._rut_build_kx_src_qs traffic_type branch."""
    secret = os.environ["JWT_SECRET_KEY"]
    key = secret.encode("utf-8")
    p = (platform or "").strip().lower()
    sig = hmac.new(key, p.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    qs = f"_kx_src={p}&_kx_sig={sig}"
    tt = (traffic_type or "").strip().lower()
    if tt in ("paid", "organic"):
        tt_sig = hmac.new(key, tt.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
        qs += f"&_kx_traffic_type={tt}&_kx_tt_sig={tt_sig}"
    return qs


def _mirror_kx_tt_verify(traffic_type: str, sig: str) -> bool:
    secret = os.environ["JWT_SECRET_KEY"]
    key = secret.encode("utf-8")
    tt = (traffic_type or "").strip().lower()
    if tt not in ("paid", "organic") or not sig:
        return False
    expected = hmac.new(key, tt.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    return hmac.compare_digest(expected, str(sig)[:12])


def test_kx_qs_includes_signed_traffic_type():
    qs = _mirror_rut_kx_qs("tiktok", traffic_type="paid")
    assert "_kx_traffic_type=paid" in qs
    assert "_kx_tt_sig=" in qs
    tt_sig = qs.split("_kx_tt_sig=")[1]
    assert _mirror_kx_tt_verify("paid", tt_sig)


def test_kx_qs_omits_auto_traffic_type():
    qs = _mirror_rut_kx_qs("facebook", traffic_type="auto")
    assert "_kx_traffic_type" not in qs


def test_detect_is_paid_for_legacy_extras():
    assert referrer_pro.detect_is_paid("paid", "auto", "tiktok") is True
    assert referrer_pro.detect_is_paid("organic", "auto", "google") is False


def test_custom_mode_paid_chain_end_to_end():
    """Mirror custom-mode + in-app-preset: paid verdict → signed tracker qs."""
    verdict = referrer_pro.detect_is_paid("paid", "auto", "tiktok")
    assert verdict is True
    qs = _mirror_rut_kx_qs("tiktok", traffic_type="paid")
    assert "_kx_traffic_type=paid" in qs
    tt_sig = qs.split("_kx_tt_sig=")[1]
    assert _mirror_kx_tt_verify("paid", tt_sig)
