"""v2.6.30–v2.6.31 — anti-detect + platform meta regression tests."""
from __future__ import annotations

from anti_detect_v230 import full_client_hints
from referrer_pro import is_non_chrome_inapp_ua

TIKTOK_UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9 Build/AP3A.240905.015; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/149.0.7827.114 "
    "Mobile Safari/537.36 TikTok/45.8.2 musical_ly_2024508020 JsSdk/1.0 "
    "NetType/WIFI Channel/googleplay AppName/musical_ly app_version/45.8.2 "
    "ByteLocale/en ByteFullLocale/en Region/US "
    "com.zhiliaoapp.musically/2024508020"
)


def test_full_client_hints_keeps_tiktok_browser_runtime():
    assert is_non_chrome_inapp_ua(TIKTOK_UA) is False
    hints = full_client_hints(TIKTOK_UA)
    assert "Chromium" in hints.get("Sec-CH-UA", "")
    assert hints.get("Sec-CH-UA-Mobile") == "?1"


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
