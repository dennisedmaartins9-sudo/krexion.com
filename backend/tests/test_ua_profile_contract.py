import ast
import random
import re
import sys
from pathlib import Path
from typing import Optional

import pytest


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from ua_profile_contract import (  # noqa: E402
    APP_VERSION_POOLS,
    classify_user_agent,
    client_hint_headers_for_ua,
    validate_header_coherence,
    validate_user_agent,
)


TIKTOK_CRONET = (
    "Mozilla/5.0 (Linux; U; Android 14; en_GB; SM-S928B; "
    "Build/UP1A.231005.007; Cronet/118.0.5993.117) "
    "TikTok/44.7.0 musical_ly_4470000000 JsSdk/1.0 NetType/WIFI "
    "Channel/googleplay AppName/musical_ly app_version/44.7.0 "
    "ByteLocale/en-GB ByteFullLocale/en-GB Region/GB "
    "BytedanceWebview/abc1234 ttwebview/12345678"
)

GOOD_WEBVIEW = (
    "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/149.0.7827.114 Mobile Safari/537.36 Instagram 425.0.0 Android"
)


def test_cronet_is_native_not_android_webview():
    profile = validate_user_agent(TIKTOK_CRONET, expected_app="tiktok")
    assert profile["engine"] == "cronet"
    assert profile["profile_type"] == "native_network"
    assert profile["runtime_compatible"] is False
    assert profile["issues"] == []
    assert all("Mobile Safari" not in issue for issue in profile["issues"])
    assert profile["warnings"]


def test_actual_malformed_android_webview_is_flagged():
    malformed = GOOD_WEBVIEW.replace(" Mobile Safari/537.36", "")
    profile = validate_user_agent(malformed, expected_app="instagram")
    assert profile["engine"] == "android_webview"
    assert any("mobile safari/537.36" in issue.lower() for issue in profile["issues"])

    badly_malformed = GOOD_WEBVIEW.replace("; wv)", ")").replace("Version/4.0 ", "")
    profile = validate_user_agent(badly_malformed, expected_app="instagram")
    assert profile["engine"] == "android_webview"
    assert any("version/4.0" in issue.lower() for issue in profile["issues"])


def test_header_contract_emits_only_for_chromium_profiles():
    hints = client_hint_headers_for_ua(GOOD_WEBVIEW)
    assert '"149"' in hints["sec-ch-ua"]
    assert hints["sec-ch-ua-platform"] == '"Android"'
    assert hints["sec-ch-ua-mobile"] == "?1"
    assert validate_header_coherence(GOOD_WEBVIEW, hints) == []

    assert client_hint_headers_for_ua(TIKTOK_CRONET) == {}
    assert validate_header_coherence(TIKTOK_CRONET, hints)

    safari = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 "
        "Mobile/15E148 Safari/604.1"
    )
    assert classify_user_agent(safari)["engine"] == "webkit"
    assert client_hint_headers_for_ua(safari) == {}
    assert validate_header_coherence(safari, hints)


def test_locale_region_mismatch_is_not_false_green():
    bad = TIKTOK_CRONET.replace("ByteFullLocale/en-GB", "ByteFullLocale/en-US")
    profile = validate_user_agent(bad)
    assert any("locale region" in issue.lower() for issue in profile["issues"])


def test_supported_app_markers_share_one_detection_contract():
    android_base = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/149.0.7827.114 Mobile Safari/537.36 "
    )
    ios_base = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    )
    samples = {
        "facebook": android_base + "[FB_IAB/FB4A;FBAV/557.0.0;]",
        "instagram": android_base + "Instagram 425.0.0 Android",
        "pinterest": android_base + "Pinterest/14.14",
        "snapchat": android_base + "Snapchat/13.88.0.56",
        "linkedin": android_base + "com.linkedin.android/9.32.512",
        "twitter": android_base + "TwitterAndroid/12345678",
        "reddit": android_base + "Reddit/Version 2024.28.0/Build 1502487",
        "telegram": android_base + "TelegramAndroid/11.12.0",
        "youtube": "com.google.android.youtube/20.15.3 (Linux; U; Android 14; Pixel 8) gzip",
        "whatsapp": "WhatsApp/25.4.82 CFNetwork/3826.500.131 Darwin/24.5.0",
        "tiktok": TIKTOK_CRONET,
        "ios-wkwebview": ios_base + "Instagram 425.0.0",
    }
    for expected, ua in samples.items():
        profile = validate_user_agent(ua)
        if expected != "ios-wkwebview":
            assert profile["app"] == expected
        assert profile["engine"] != "unknown"
        if not profile["runtime_compatible"]:
            assert profile["warnings"]


def test_server_wires_shared_contract_and_compatible_response_schema():
    source = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "user_agent: Optional[str] = None" in source
    assert "validate_user_agent(ua" in source
    assert '"user_agents": [r["user_agent"] for r in results]' in source
    assert '"profiles": results' in source
    assert '"results": results' in source
    assert '"engine": profile["engine"]' in source
    assert '"runtime_compatible": profile["runtime_compatible"]' in source


def _load_server_template_namespace():
    source = (BACKEND / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_rand_build_id", "_ua_android_webview", "_ua_ios_wkwebview",
        "_ua_instagram_android", "_ua_instagram_ios", "_fbav_3part",
        "_ua_facebook_android", "_ua_facebook_ios",
        "_ua_pinterest_android", "_ua_pinterest_ios",
        "_ua_snapchat_android", "_ua_snapchat_ios",
        "_ua_tiktok_android", "_ua_tiktok_ios",
        "_ua_youtube_android", "_ua_youtube_ios",
        "_ua_whatsapp_android", "_ua_whatsapp_ios",
        "_ua_linkedin_android", "_ua_linkedin_ios",
        "_ua_twitter_android", "_ua_twitter_ios",
        "_ua_reddit_android", "_ua_reddit_ios",
        "_ua_telegram_android", "_ua_telegram_ios",
        "_ua_gsearch_android", "_ua_gsearch_ios",
        "_ua_gchrome_android", "_ua_gchrome_ios",
        "_ua_chrome_android", "_ua_safari_ios",
    }
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    namespace = {
        "random": random,
        "re": re,
        "Optional": Optional,
        "_CHROME_VERSIONS": ["149.0.7827.114"],
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "server.py", "exec"), namespace)
    return namespace


SUPPORTED_GENERATOR_APPS = [
    "instagram", "facebook", "tiktok", "pinterest", "snapchat",
    "youtube", "whatsapp", "linkedin", "twitter", "reddit",
    "telegram", "gsearch", "gchrome", "chrome",
]


@pytest.mark.parametrize("app", SUPPORTED_GENERATOR_APPS)
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_all_generated_mobile_templates_round_trip_cleanly(app, platform):
    ns = _load_server_template_namespace()
    android = {
        "brand": "Samsung", "model": "SM-S928B", "vendor": "samsung",
        "chipset": "qcom", "soc": "pineapple", "res": "1440x3120",
        "dpi": "505dpi", "and_ver": "14", "sdk": "34",
        "build": "UP1A.231005.007",
    }
    ios = {
        "brand": "iPhone", "model": "iPhone17,2",
        "name": "iPhone 16 Pro Max", "ios": "26_4_1",
        "res": "1320x2868", "scale": "3.00",
    }
    region = {
        "code": "GB", "country": "United Kingdom", "byte_locale": "en-GB",
        "posix_locale": "en_GB", "lang_tag": "en-GB",
    }
    version = APP_VERSION_POOLS.get(app, ["1.0.0"])[0]
    chrome = "149.0.7827.114"

    if app == "instagram":
        ua = ns[f"_ua_instagram_{platform}"](
            android if platform == "android" else ios,
            version,
            chrome if platform == "android" else region,
            region if platform == "android" else None,
        )
    elif app == "facebook":
        args = [android if platform == "android" else ios, version]
        if platform == "android":
            args.extend([chrome, region])
        else:
            args.append(region)
        ua = ns[f"_ua_facebook_{platform}"](*args)
    elif app in {"tiktok", "youtube", "whatsapp", "gsearch", "gchrome"}:
        ua = ns[f"_ua_{app}_{platform}"](
            android if platform == "android" else ios, version, region
        )
    elif app in {"pinterest", "snapchat", "linkedin", "twitter", "reddit", "telegram"}:
        ua = ns[f"_ua_{app}_{platform}"](
            android if platform == "android" else ios, version
        )
    elif app == "chrome" and platform == "android":
        ua = ns["_ua_chrome_android"](android, chrome)
    else:
        ua = ns["_ua_safari_ios"](ios)

    expected_app = None if app in {"chrome", "gchrome"} else app
    profile = validate_user_agent(ua, expected_app=expected_app)
    assert profile["runtime_compatible"] is True, (app, platform, profile)
    assert profile["issues"] == [], (app, platform, profile, ua)
    if platform == "android" and app not in {"chrome", "gchrome"}:
        assert profile["engine"] == "android_webview"
    if platform == "ios" and app not in {"chrome"}:
        assert profile["profile_type"] in {"ios_wkwebview", "browser"}


def test_tiktok_coercion_uses_webview_for_page_navigation():
    import referrer_pro

    plain = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.114 "
        "Mobile Safari/537.36"
    )
    for source in (plain, TIKTOK_CRONET):
        coerced = referrer_pro.coerce_ua_for_platform(source, "tiktok")
        profile = validate_user_agent(coerced, expected_app="tiktok")
        assert "Cronet/" not in coerced
        assert "; wv)" in coerced
        assert "Version/4.0" in coerced
        assert profile["engine"] == "android_webview"
        assert profile["runtime_compatible"] is True
        assert profile["issues"] == []
        assert referrer_pro.is_non_chrome_inapp_ua(coerced) is False
        assert referrer_pro.coerce_ua_for_platform(coerced, "tiktok") == coerced
