"""v2.6.30–v2.6.31 — anti-detect + platform meta regression tests."""
from __future__ import annotations

from anti_detect_v230 import full_client_hints
from referrer_pro import is_non_chrome_inapp_ua

TIKTOK_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S918B Build/TP1A.220624.014; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.146 "
    "Mobile Safari/537.36 musical_ly_2024109030 JsSdk/1.0 NetType/WIFI Channel/googleplay "
    "AppName/musical_ly app_version/40.9.3 ByteLocale/en ByteFullLocale/en Region/US "
    "AppId/1233 Spark/1.7.2 AppVersion/40.9.3 PIA/2.5.3 RevealType/Dialog "
    "BytedanceWebView/d8a21c6 RevealType/Dialog"
)


def test_full_client_hints_suppresses_tiktok_brands():
    assert is_non_chrome_inapp_ua(TIKTOK_UA) is True
    hints = full_client_hints(TIKTOK_UA)
    assert hints.get("Sec-CH-UA") == ""
    assert "Google Chrome" not in str(hints.values())


def test_full_client_hints_chrome_still_emits_brands():
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    hints = full_client_hints(ua)
    assert "Google Chrome" in hints.get("Sec-CH-UA", "")
    assert hints.get("Sec-CH-UA-Platform") == '"Windows"'


def test_full_client_hints_ios_parses_platform_version():
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 musical_ly_2024109030"
    )
    hints = full_client_hints(ua)
    assert hints.get("Sec-CH-UA-Platform-Version") == '"17.4.0"'


def test_launch_args_no_webrtc_mdns_disable():
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("real_user_traffic.py").read_text(encoding="utf-8")
    assert "WebRtcHideLocalIpsWithMdns" not in text.split("_BROWSER_LAUNCH_ARGS_BASE")[1].split("]")[0]
    assert "AutomationControlled" in text


def test_ua_platform_meta_ios_in_source():
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("real_user_traffic.py").read_text(encoding="utf-8")
    assert "def _ua_platform_meta(" in text
    assert "iPhone OS (\\d+)_(\\d+)" in text


def test_make_sec_ch_ua_strip_route_handler_exists():
    from referrer_pro import make_sec_ch_ua_strip_route_handler

    handler = make_sec_ch_ua_strip_route_handler()
    assert callable(handler)


def test_tls_async_session_kwargs_includes_http2():
    from tls_anti_detect import _async_session_kwargs

    kw = _async_session_kwargs(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    assert "impersonate" in kw
    assert "http2_settings" in kw or "http2_headers_order" in kw
