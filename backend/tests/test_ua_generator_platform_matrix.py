"""Focused UA-generator template and endpoint-contract matrix."""
import ast
import asyncio
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest


BACKEND = Path(__file__).resolve().parents[1]
SERVER_FILE = BACKEND / "server.py"
sys.path.insert(0, str(BACKEND))

from ua_profile_contract import (  # noqa: E402
    ANDROID_DEVICE_SNAPSHOTS,
    APP_RELEASES_BY_PLATFORM,
    APP_SUPPORT_MATRIX,
    validate_user_agent,
)


ANDROID = {
    "brand": "Google", "model": "Pixel 9", "vendor": "google",
    "chipset": "tensor", "soc": "tokay", "res": "1080x2424",
    "dpi": "422dpi", "and_ver": "15", "sdk": "35",
    "build": "AP3A.240905.015",
}
IPHONE = {
    "brand": "iPhone", "model": "iPhone17,1", "name": "iPhone 16 Pro",
    "ios": "26_4_1", "res": "1206x2622", "scale": "3.00",
}
IPAD = {
    "brand": "iPad", "model": "iPad14,3", "name": 'iPad Pro 11"',
    "ios": "26_4", "res": "1668x2388", "scale": "2.00",
}
REGION = {
    "code": "US", "country": "United States", "byte_locale": "en",
    "posix_locale": "en_US", "lang_tag": "en-US",
}
WEBVIEW = "151.0.7922.83"
DESKTOP_CHROME = "151.0.7922.109"


def _templates():
    names = {
        "_ua_android_webview", "_ua_ios_wkwebview",
        "_ua_instagram_android", "_ua_instagram_ios",
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
        "_ua_firefox_desktop",
    }
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    runtime_releases = {
        app: {
            platform: [dict(record) for record in records]
            for platform, records in platforms.items()
        }
        for app, platforms in APP_RELEASES_BY_PLATFORM.items()
    }
    runtime_releases["gsearch"]["android"] = [{"version": "17.36.15"}]
    namespace = {
        "random": random,
        "Optional": Optional,
        "Dict": Dict,
        "List": List,
        "APP_RELEASES_BY_PLATFORM": APP_RELEASES_BY_PLATFORM,
        "_APP_RELEASES_RUNTIME": runtime_releases,
        "_CHROME_VERSIONS": [DESKTOP_CHROME],
        "_ANDROID_WEBVIEW_VERSIONS": [WEBVIEW],
        "_FIREFOX_VERSIONS": ["141.0.2"],
        "_pick_region": lambda _code: REGION,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER_FILE), "exec"), namespace)
    return SimpleNamespace(**namespace)


def _version(app: str, platform: str) -> str:
    if app == "gsearch" and platform == "android":
        return "17.36.15"
    return APP_RELEASES_BY_PLATFORM[app][platform][0]["version"]


def _generate(app: str, platform: str, device=None) -> str:
    t = _templates()
    d = device or (ANDROID if platform == "android" else IPHONE)
    version = _version(app, platform) if app != "chrome" else DESKTOP_CHROME
    if app == "chrome":
        return (
            t._ua_chrome_android(d, DESKTOP_CHROME)
            if platform == "android"
            else t._ua_safari_ios(d)
        )
    function = getattr(t, f"_ua_{app}_{platform}")
    if app == "instagram":
        return function(d, version, WEBVIEW, region=REGION) if platform == "android" else function(d, version, region=REGION)
    if app == "facebook":
        return function(d, version, WEBVIEW, region=REGION) if platform == "android" else function(d, version, region=REGION)
    if app in {"tiktok", "youtube", "whatsapp", "gsearch", "gchrome"}:
        return function(d, version, region=REGION)
    return function(d, version)


APPS = [
    "instagram", "facebook", "tiktok", "pinterest", "snapchat",
    "youtube", "whatsapp", "linkedin", "twitter", "reddit",
    "telegram", "gsearch", "gchrome", "chrome",
]


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_14_app_platform_template_matrix(app, platform):
    ua = _generate(app, platform)
    assert ua.startswith("Mozilla/5.0 ")
    assert not any(
        foreign in ua
        for foreign in {
            "FBAN/TikTokAndroid", "FBOP/", "ttwebview/", "BytedanceWebview/",
            "TwitterIOS/", "TelegramIOS/",
        }
    )

    fallback = (
        app == "youtube"
        or (platform == "ios" and app in {"whatsapp", "reddit", "telegram"})
        or (platform == "android" and app == "gchrome")
    )
    expected = app if app != "chrome" else None
    profile = validate_user_agent(ua, expected_app=expected)
    assert profile["valid"], (app, platform, profile)
    assert profile["runtime_compatible"], (app, platform, profile)
    if fallback:
        assert profile["support_state"] == "fallback"
        assert profile["app"] == "browser"
        assert profile["identity_supported"] is False
    elif app == "chrome":
        assert profile["support_state"] == "generic"
        assert profile["app"] == "browser"
        assert profile["identity_supported"] is False
    else:
        assert profile["support_state"] == "supported"
        assert profile["identity_supported"] is True


def test_exact_android_mapped_fields_and_no_fabricated_builds():
    samples = {
        "instagram": _generate("instagram", "android"),
        "facebook": _generate("facebook", "android"),
        "tiktok": _generate("tiktok", "android"),
        "linkedin": _generate("linkedin", "android"),
        "reddit": _generate("reddit", "android"),
    }
    assert "1011909233; IABMV/1" in samples["instagram"]
    assert samples["facebook"].count("[FB_IAB/FB4A;") == 1
    assert "FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;" in samples["facebook"]
    assert "FBAN/" not in samples["facebook"] and "FBOP/" not in samples["facebook"]
    assert "musical_ly_2024508020" in samples["tiktok"]
    assert "app_version/45.8.2" in samples["tiktok"]
    assert "com.zhiliaoapp.musically/2024508020" in samples["tiktok"]
    assert "[LinkedInApp]/2.286.33 com.linkedin.android/212600" in samples["linkedin"]
    assert "Reddit/Version 2026.18.0/Build 2618090/" in samples["reddit"]


def test_required_marker_shapes_and_reduced_chrome():
    assert "[Pinterest/Android]" in _generate("pinterest", "android")
    assert "Pinterest/" not in _generate("pinterest", "android").replace("[Pinterest/Android]", "")
    assert "WhatsApp/2.26.5.10 A" in _generate("whatsapp", "android")
    assert "WhatsApp/2.26.5.10/A" not in _generate("whatsapp", "android")
    assert "TwitterAndroid/11.95.1-release.0" in _generate("twitter", "android")
    assert "Twitter for iPhone/10.98.0" in _generate("twitter", "ios")
    assert "Telegram-Android/12.9.2 (Android 15; Pixel 9; en-US)" in _generate("telegram", "android")
    assert "GoogleApp/17.36.15" in _generate("gsearch", "android")
    chrome = _generate("chrome", "android")
    assert "Android 10; K" in chrome
    assert "Chrome/151.0.0.0" in chrome
    assert "Pixel" not in chrome and "Build/" not in chrome


@pytest.mark.parametrize("app", APPS)
def test_all_ios_templates_are_ipad_safe(app):
    ua = _generate(app, "ios", IPAD)
    assert "(iPad; CPU iPad OS " in ua
    assert "CPU iPhone OS" not in ua
    assert validate_user_agent(ua)["issues"] == []


def test_fallback_helpers_emit_no_foreign_native_package_markers():
    for app in ("youtube", "whatsapp", "reddit", "telegram"):
        ua = _generate(app, "ios")
        assert validate_user_agent(ua, expected_app=app)["support_state"] == "fallback"
        assert not any(token in ua for token in ("com.google.", "WhatsApp/", "Reddit/", "Telegram"))
    youtube_android = _generate("youtube", "android")
    assert "com.google.android.youtube" not in youtube_android
    assert "Android 10; K" in youtube_android


def test_server_source_enforces_endpoint_validation_and_platform_records():
    source = SERVER_FILE.read_text(encoding="utf-8")
    assert '"app_versions_by_platform": _APP_RELEASES_RUNTIME' in source
    assert "Unknown app:" in source and "Unknown platform:" in source
    assert "Pinned device pool contradicts selected platforms" in source
    assert "conflicts with pinned device firmware" in source
    assert "does not encode resolution in this UA" in source
    assert "_APP_RELEASES_RUNTIME[app_key][\"ios\"]" in source
    assert "_APP_RELEASES_RUNTIME[app_key][\"android\"] =" not in source
    assert '"ua_checker": True' in source
    assert '"ua_checker":           "ua_checker"' in source
    assert "Pinned device selection cannot be combined with multiple platforms" in source
    assert "platforms/webview/channels/stable/versions" in source


def _load_server_functions(names, namespace):
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER_FILE), "exec"), namespace)
    return namespace


def test_pinned_platform_mix_rejected_and_desktop_any_preserved():
    from fastapi import HTTPException

    ns = _load_server_functions(
        {"_selected_platforms_for_pins"},
        {
            "Optional": Optional,
            "List": List,
            "Set": set,
            "HTTPException": HTTPException,
        },
    )
    select = ns["_selected_platforms_for_pins"]
    with pytest.raises(HTTPException) as exc:
        select("any", ["android", "ios"], "android", set())
    assert exc.value.status_code == 400
    assert select("any", None, "desktop", set()) == {"desktop"}


def test_android_16_capture_profiles_and_webview_source_are_separate():
    snapshots = {
        (row["model"], row["and_ver"], row["build"])
        for row in ANDROID_DEVICE_SNAPSHOTS
    }
    assert ("2510ERA8BG", "16", "BP2A.250605.031.A3") in snapshots
    assert ("Pixel 9", "16", "CP1A.260505.005") in snapshots

    t = _templates()
    webview = t._ua_tiktok_android(ANDROID, _version("tiktok", "android"), REGION)
    standalone = t._ua_chrome_android(ANDROID, DESKTOP_CHROME)
    assert f"Chrome/{WEBVIEW}" in webview
    assert f"Chrome/{DESKTOP_CHROME.split('.')[0]}.0.0.0" in standalone
    assert WEBVIEW != DESKTOP_CHROME


def test_entitlement_mapping_includes_checker_and_explicit_false_denies():
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"))
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"DEFAULT_FEATURES", "SUB_USER_PERMISSION_MAP"}
    }
    assert assignments["DEFAULT_FEATURES"]["ua_checker"] is True
    assert assignments["SUB_USER_PERMISSION_MAP"]["ua_checker"] == "ua_checker"

    ns = _load_server_functions(
        {"_build_sub_user_features"},
        {"SUB_USER_PERMISSION_MAP": assignments["SUB_USER_PERMISSION_MAP"]},
    )
    build = ns["_build_sub_user_features"]
    assert build(
        {"ua_generator": True, "ua_checker": False},
        {"ua_generator": True, "ua_checker": True},
    )["ua_checker"] is False


def test_flat_legacy_snapshot_cannot_contaminate_ios_releases():
    class Settings:
        async def find_one(self, *_args, **_kwargs):
            return {
                "app_versions": {
                    "instagram": [
                        APP_RELEASES_BY_PLATFORM["instagram"]["android"][0]["version"]
                    ]
                }
            }

    runtime = {
        app: {
            platform: [dict(record) for record in records]
            for platform, records in platforms.items()
        }
        for app, platforms in APP_RELEASES_BY_PLATFORM.items()
    }
    ns = _load_server_functions(
        {"_load_ua_versions_snapshot"},
        {
            "main_db": SimpleNamespace(settings=Settings()),
            "_APP_RELEASES_RUNTIME": runtime,
            "APP_RELEASES_BY_PLATFORM": APP_RELEASES_BY_PLATFORM,
            "_APP_VERSIONS": {},
            "_legacy_app_versions": lambda: {},
            "_IOS_OS_VERSIONS": [],
            "_CHROME_VERSIONS": [],
            "_ANDROID_WEBVIEW_VERSIONS": [],
            "_FIREFOX_VERSIONS": [],
            "_UA_VERSIONS_META": {},
            "logger": SimpleNamespace(warning=lambda *_args: None),
        },
    )
    before = list(runtime["instagram"]["ios"])
    asyncio.run(ns["_load_ua_versions_snapshot"]())
    assert runtime["instagram"]["ios"] == before

