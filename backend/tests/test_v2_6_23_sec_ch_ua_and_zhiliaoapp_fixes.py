"""TikTok page-navigation Sec-CH-UA and identity regressions."""
import ast
import random
import sys, re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest

from referrer_pro import is_non_chrome_inapp_ua, coerce_ua_for_platform
from ua_profile_contract import client_hint_headers_for_ua, validate_user_agent


BASE_ANDROID = ("Mozilla/5.0 (Linux; Android 15; SM-S931B Build/AP3A.240905.015; wv) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
                "Chrome/146.0.7432.116 Mobile Safari/537.36")

BASE_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1")

EXTERNAL_CRONET = (
    "Mozilla/5.0 (Linux; U; Android 14; en_US; SM-S928B; "
    "Build/UP1A.231005.007; Cronet/118.0.5993.117) "
    "TikTok/45.8.2 musical_ly_2024508020 JsSdk/1.0 NetType/WIFI "
    "Channel/googleplay AppName/musical_ly app_version/45.8.2 "
    "ByteLocale/en ByteFullLocale/en_US Region/US"
)


def _load_functions(path: Path, names: set[str], namespace: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _server_templates():
    return _load_functions(
        Path(__file__).parent.parent / "server.py",
        {"_ua_android_webview", "_ua_tiktok_android"},
        {
            "random": random,
            "Optional": Optional,
            "_CHROME_VERSIONS": ["149.0.7827.114"],
            "_ANDROID_WEBVIEW_VERSIONS": ["151.0.7922.83"],
            "_APP_RELEASES_RUNTIME": {
                "tiktok": {
                    "android": [{
                        "version": "45.8.2",
                        "version_code": "2024508020",
                    }]
                }
            },
            "_pick_region": lambda _code: {
                "code": "US", "byte_locale": "en-US", "posix_locale": "en_US",
            },
        },
    )


def _client_hint_builder():
    return _load_functions(
        Path(__file__).parent.parent / "real_user_traffic.py",
        {"_extract_chrome_version", "_build_client_hint_headers"},
        {
            "random": random, "re": re, "Any": Any, "Dict": Dict, "Tuple": Tuple,
            "client_hint_headers_for_ua": client_hint_headers_for_ua,
            "_CHROME_VERSION_RE": re.compile(
                r"(?:Chrome|CriOS|Edg|EdgA|EdgiOS|Chromium)/(\d+)(?:\.(\d+))?",
                re.IGNORECASE,
            ),
        },
    )._build_client_hint_headers


# ── is_non_chrome_inapp_ua classifier ──────────────────────────

def test_non_chrome_inapp_true_for_tiktok_android_webview():
    # v2.6.88 — TikTok Android suppresses Sec-CH-UA, so it classifies as
    # non-chrome-inapp (same Everflow path as iOS TikTok).
    tt = coerce_ua_for_platform(BASE_ANDROID, "tiktok")
    assert is_non_chrome_inapp_ua(tt) is True

def test_non_chrome_inapp_detects_tiktok_ios():
    tt = coerce_ua_for_platform(BASE_IOS, "tiktok")
    assert is_non_chrome_inapp_ua(tt) is True


def test_non_chrome_inapp_detects_external_tiktok_cronet():
    assert is_non_chrome_inapp_ua(EXTERNAL_CRONET) is True
    profile = validate_user_agent(EXTERNAL_CRONET, expected_app="tiktok")
    assert profile["valid"] is True
    assert profile["runtime_compatible"] is False

def test_non_chrome_inapp_detects_ig_ios():
    ig = coerce_ua_for_platform(BASE_IOS, "instagram")
    assert is_non_chrome_inapp_ua(ig) is True

def test_non_chrome_inapp_true_for_fb_android():
    # v2.6.88 — FB Android also suppresses Chromium Client Hints.
    fb = coerce_ua_for_platform(BASE_ANDROID, "facebook")
    assert is_non_chrome_inapp_ua(fb) is True

def test_non_chrome_inapp_true_for_ig_android():
    ig = coerce_ua_for_platform(BASE_ANDROID, "instagram")
    assert is_non_chrome_inapp_ua(ig) is True

def test_non_chrome_inapp_false_for_plain_chrome():
    assert is_non_chrome_inapp_ua(BASE_ANDROID) is False
    assert is_non_chrome_inapp_ua(BASE_IOS) is False


# ── com.zhiliaoapp.musically marker present in tiktok UAs ──────

def test_tiktok_android_contains_zhiliaoapp_marker():
    tt = coerce_ua_for_platform(BASE_ANDROID, "tiktok")
    assert "com.zhiliaoapp.musically/" in tt

def test_tiktok_ios_uses_wkwebview_without_android_package_marker():
    tt = coerce_ua_for_platform(BASE_IOS, "tiktok")
    assert "com.zhiliaoapp.musically/" not in tt
    assert "WKWebView/1" in tt


# ── Server-side UA generator matches new format ────────────────

def test_server_ua_tiktok_android_generator_has_zhiliaoapp():
    d = {
        "and_ver": "14", "model": "SM-S928B",
        "build": "UP1A.231005.007",
    }
    ua = _server_templates()._ua_tiktok_android(d, "45.8.2")
    assert "com.zhiliaoapp.musically/" in ua
    assert "musical_ly_" in ua
    for token in ("; wv)", "AppleWebKit/537.36", "Version/4.0", "Chrome/", "Mobile Safari/537.36"):
        assert token in ua
    assert "Cronet/" not in ua


# ── Client hint headers helper: non-chrome in-app UA suppresses Sec-CH-UA brand ──

def test_client_hint_headers_match_tiktok_android_webview():
    """v2.6.88 — TikTok Android must NOT emit Sec-CH-UA Chromium brands.

    Otherwise Everflow labels Browser=Chrome instead of TikTok for Android
    (iOS already had empty CH via wkwebview — that is why only Android broke).
    """
    _build_client_hint_headers = _client_hint_builder()
    tt_ua = coerce_ua_for_platform(BASE_ANDROID, "tiktok")
    fp = {"os": "android", "is_mobile": True}
    h = _build_client_hint_headers(fp, tt_ua)
    assert h == {}
    assert client_hint_headers_for_ua(tt_ua) == {}
    assert "TikTok/" in tt_ua
    assert "musical_ly_" in tt_ua


def test_client_hint_headers_normal_chrome_unchanged():
    _build_client_hint_headers = _client_hint_builder()
    fp = {"os": "windows", "is_mobile": False}
    h = _build_client_hint_headers(fp, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7367.60 Safari/537.36")
    # Chrome desktop must emit brand list
    assert "Sec-CH-UA" in h
    assert "Google Chrome" in h["Sec-CH-UA"]

def test_client_hint_headers_tiktok_ios_no_brand_leak():
    _build_client_hint_headers = _client_hint_builder()
    tt_ua = coerce_ua_for_platform(BASE_IOS, "tiktok")
    fp = {"os": "ios", "is_mobile": True}
    h = _build_client_hint_headers(fp, tt_ua)
    assert h == {}


# ── Advertiser UA parser sees TikTok now (com.zhiliaoapp.musically trigger) ──

def test_ua_parser_libs_recognize_com_zhiliaoapp_musically():
    """When our UA carries `com.zhiliaoapp.musically/`, advertiser
    UA parsers that include a TikTok rule (Everflow / Voluum /
    RedTrack) can match on the package-name substring. This test
    confirms the marker is present in a stable position (space-
    separated, at the tail) so those rules trigger reliably."""
    tt_a = coerce_ua_for_platform(BASE_ANDROID, "tiktok")
    # Package-name substring must be present exactly (case-sensitive)
    assert re.search(r"\bcom\.zhiliaoapp\.musically/\d+", tt_a), (
        f"Missing com.zhiliaoapp.musically/<code> marker in Android TikTok UA: {tt_a}"
    )
    tt_i = coerce_ua_for_platform(BASE_IOS, "tiktok")
    assert "com.zhiliaoapp.musically/" not in tt_i
    assert "WKWebView/1" in tt_i


# ── Regression: v2.6.22 fixes still hold ───────────────────────

def test_regression_tiktok_android_has_coherent_webview():
    tt = coerce_ua_for_platform(BASE_ANDROID, "tiktok")
    for token in ("; wv)", "AppleWebKit/537.36", "Version/4.0", "Chrome/", "Mobile Safari/537.36"):
        assert token in tt
    assert "Cronet/" not in tt

def test_regression_tiktok_ios_no_trailing_safari():
    tt = coerce_ua_for_platform(BASE_IOS, "tiktok")
    assert not re.search(r"\bSafari/[\d.]+\s*$", tt)
    assert "Version/26.4" not in tt
    profile = validate_user_agent(tt, expected_app="tiktok")
    assert profile["profile_type"] == "ios_wkwebview"
    assert profile["valid"]
    assert profile["issues"] == []

def test_regression_facebook_target_keeps_chrome_webview():
    fb = coerce_ua_for_platform(BASE_ANDROID, "facebook")
    assert "FBAV/" in fb
    assert "Chrome/" in fb  # Real FB Android WebView keeps Chrome
    assert "musical_ly" not in fb
