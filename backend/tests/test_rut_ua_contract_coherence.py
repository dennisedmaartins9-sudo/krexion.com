import ast
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import referrer_pro as rp  # noqa: E402
from ua_profile_contract import (  # noqa: E402
    client_hint_headers_for_ua,
    detect_app,
    validate_user_agent,
)


ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A.231105.003; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/149.0.7827.114 Mobile Safari/537.36"
)
IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
    "Mobile/15E148 Safari/604.1"
)
CUSTOM_ANDROID_BROWSER = (
    "Mozilla/5.0 (Linux; Android 13; Fairphone 4 Build/TQ3A.230805.001) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.192 "
    "Mobile Safari/537.36"
)


def _load_rut_function(name, namespace):
    path = BACKEND / "real_user_traffic.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def test_rut_headers_are_exact_contract_values_with_playwright_casing():
    builder = _load_rut_function(
        "_build_client_hint_headers",
        {
            "Any": Any,
            "Dict": Dict,
            "client_hint_headers_for_ua": client_hint_headers_for_ua,
        },
    )
    expected = {
        {
            "sec-ch-ua": "Sec-CH-UA",
            "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
            "sec-ch-ua-platform": "Sec-CH-UA-Platform",
        }[key]: value
        for key, value in client_hint_headers_for_ua(ANDROID).items()
    }
    assert builder({}, ANDROID) == expected
    assert '"Android WebView";v="149"' in expected["Sec-CH-UA"]


def test_no_hints_for_ios_crios_firefox_or_safari():
    builder = _load_rut_function(
        "_build_client_hint_headers",
        {
            "Any": Any,
            "Dict": Dict,
            "client_hint_headers_for_ua": client_hint_headers_for_ua,
        },
    )
    crios = IOS.replace("Version/18.5", "CriOS/147.0.7727.102")
    firefox = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) "
        "Gecko/20100101 Firefox/141.0"
    )
    assert builder({}, IOS) == {}
    assert builder({}, crios) == {}
    assert builder({}, firefox) == {}


def test_route_hint_reconciliation_preserves_chromium_high_entropy_only():
    apply_hints = _load_rut_function(
        "_apply_contract_client_hints",
        {
            "Any": Any,
            "Dict": Dict,
            "_build_client_hint_headers": lambda _fp, ua: {
                {
                    "sec-ch-ua": "Sec-CH-UA",
                    "sec-ch-ua-mobile": "Sec-CH-UA-Mobile",
                    "sec-ch-ua-platform": "Sec-CH-UA-Platform",
                }[key]: value
                for key, value in client_hint_headers_for_ua(ua).items()
            },
        },
    )
    negotiated = {
        "sec-ch-ua": '"Wrong";v="1"',
        "Sec-CH-UA-Mobile": "?0",
        "SEC-CH-UA-PLATFORM": '"Windows"',
        "Sec-CH-UA-Model": '"Pixel 8"',
        "Sec-CH-UA-Platform-Version": '"14.0.0"',
        "Sec-CH-UA-Arch": '"arm"',
        "Sec-CH-UA-Bitness": '"64"',
        "Sec-CH-UA-Full-Version-List": '"Google Chrome";v="149.0.7827.114"',
        "X-Test": "keep",
    }
    chromium = apply_hints(negotiated, ANDROID)
    assert chromium["Sec-CH-UA-Model"] == '"Pixel 8"'
    assert chromium["Sec-CH-UA-Platform-Version"] == '"14.0.0"'
    assert chromium["Sec-CH-UA-Arch"] == '"arm"'
    assert chromium["Sec-CH-UA-Bitness"] == '"64"'
    assert "149.0.7827.114" in chromium["Sec-CH-UA-Full-Version-List"]
    assert chromium["Sec-CH-UA-Mobile"] == "?1"
    assert chromium["Sec-CH-UA-Platform"] == '"Android"'
    assert not any(key in chromium for key in ("sec-ch-ua", "SEC-CH-UA-PLATFORM"))

    webkit = apply_hints(negotiated, IOS)
    assert webkit == {"X-Test": "keep"}


def test_coercion_uses_release_contract_and_one_identity_only():
    hybrid = (
        ANDROID
        + " Instagram 437.0.0.33.78 Android (34/14; 420dpi; 1080x2400; "
        "google; Pixel 8; shiba; tensor; en_US; 1011909233; IABMV/1) "
        "[FB_IAB/FB4A;FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;]"
    )
    output = rp.coerce_ua_for_platform(hybrid, "tiktok", "en-GB")
    verdict = validate_user_agent(output, expected_app="tiktok")
    assert verdict["valid"], verdict
    assert detect_app(output)["identities"] == ["tiktok"]
    assert output.count("TikTok/46.4.1") == 1
    assert output.count("musical_ly_2024604010") == 1
    assert "FBAN/TikTokAndroid" not in output
    assert "BytedanceWebview" not in output
    assert "ttwebview" not in output


def test_messenger_is_generic_fallback_only_and_never_maps_to_facebook(caplog):
    with caplog.at_level("WARNING", logger="referrer_pro"):
        output = rp.coerce_ua_for_platform(CUSTOM_ANDROID_BROWSER, "messenger")
    assert output == CUSTOM_ANDROID_BROWSER
    assert detect_app(output)["identities"] == []
    assert "FB_IAB" not in output and "FBAN/" not in output
    assert "fallback-only" in caplog.text


def test_messenger_preset_preserves_supplied_generic_uas_before_coercion():
    presetter = _load_rut_function(
        "_apply_inapp_preset_to_uas",
        {
            "Dict": Dict,
            "List": List,
            "_mobile_ua_for_inapp": lambda: ANDROID,
        },
    )
    desktop = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.7827.114 Safari/537.36"
    )
    supplied = [desktop, CUSTOM_ANDROID_BROWSER]
    assert presetter(supplied, 2, "messenger") == supplied


def test_fallback_preserves_clean_custom_browser_and_cleans_contamination():
    assert rp.coerce_ua_for_platform(CUSTOM_ANDROID_BROWSER, "youtube") == CUSTOM_ANDROID_BROWSER

    contaminated = (
        ANDROID
        + " [FB_IAB/FB4A;FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;]"
    )
    output = rp.coerce_ua_for_platform(contaminated, "messenger")
    assert output != contaminated
    assert detect_app(output)["identities"] == []
    assert "FB_IAB" not in output and "FBAV/" not in output
    assert validate_user_agent(output, expected_app="browser")["valid"]


def test_supported_formats_and_unsupported_clean_fallbacks():
    expected_markers = {
        "facebook": "[FB_IAB/FB4A;FBAV/556.0.0.59.68;IABMV/1;FBBV/681204512;]",
        "pinterest": "[Pinterest/Android]",
        "linkedin": "[LinkedInApp]/2.286.33 com.linkedin.android/212600",
        "reddit": "Reddit/Version 2026.18.0/Build 2618090/Android 14",
        "telegram": "Telegram-Android/12.9.2",
        "whatsapp": "WhatsApp/2.26.5.10 A",
        "google": "GoogleApp/17.36.15",
    }
    for platform, marker in expected_markers.items():
        output = rp.coerce_ua_for_platform(ANDROID, platform)
        assert marker in output

    for platform, base in (
        ("youtube", ANDROID),
        ("youtube", IOS),
        ("whatsapp", IOS),
        ("reddit", IOS),
        ("telegram", IOS),
    ):
        output = rp.coerce_ua_for_platform(base, platform)
        assert detect_app(output)["identities"] == []
        assert "; wv)" not in output or "Safari/" in output


def test_idempotency_requires_a_fully_valid_single_identity():
    valid = rp.coerce_ua_for_platform(ANDROID, "facebook")
    assert rp.coerce_ua_for_platform(valid, "facebook") == valid
    duplicate = valid + " " + valid[valid.index("[FB_IAB/"):]
    repaired = rp.coerce_ua_for_platform(duplicate, "facebook")
    assert repaired.count("[FB_IAB/FB4A;") == 1
    assert validate_user_agent(repaired, expected_app="facebook")["valid"]


def test_mobile_fingerprint_preserves_instagram_resolution_and_dpr():
    fingerprint = _load_rut_function(
        "_fingerprint_from_ua",
        {
            "Any": Any,
            "Dict": Dict,
            "random": random,
            "re": re,
            "ua_parse": lambda _ua: SimpleNamespace(
                is_mobile=True,
                is_tablet=False,
                os=SimpleNamespace(family="Android", version_string="14"),
            ),
            "_os_key_from_ua": lambda _ua: "android",
            "_pick_android_gpu_from_ua": lambda _ua: ("vendor", "renderer", 8, 8),
            "_pick_ios_gpu_from_ua": lambda _ua: ("vendor", "renderer", 6, 8),
            "_extract_chrome_version": lambda _ua: (149, 0),
            "_extract_safari_version": lambda _ua: (18, 5),
            "_extract_chrome_full_version": lambda _ua: "149.0.7827.114",
            "_ua_platform_meta": lambda _os, _ua: {
                "platform_version": "14.0.0",
                "architecture": "arm",
                "ua_model": "Pixel 8",
            },
            "_sanitize_swiftshader_webgl": lambda _os, vendor, renderer: (
                vendor, renderer
            ),
            "_OS_FONTS": {"android": [], "windows": []},
            "client_hint_headers_for_ua": client_hint_headers_for_ua,
        },
    )
    instagram = rp.coerce_ua_for_platform(ANDROID, "instagram", "en-US")
    first = fingerprint(instagram)
    second = fingerprint(instagram)
    assert first["viewport"] == second["viewport"] == {"width": 411, "height": 914}
    assert first["device_scale_factor"] == second["device_scale_factor"] == 2.625
    assert first["screen_width"] == first["viewport"]["width"]
    assert first["explicit_locale"] == "en-US"


def test_user_agent_data_uses_the_same_shared_hint_payload_or_none():
    builder = _load_rut_function(
        "_build_stealth_script",
        {
            "Any": Any,
            "Dict": Dict,
            "Optional": __import__("typing").Optional,
            "random": random,
            "re": re,
        },
    )
    base = {
        "platform": "Linux armv8l", "vendor": "Google Inc.",
        "hardware_concurrency": 8, "device_memory": 8,
        "webgl_vendor": "vendor", "webgl_renderer": "renderer",
        "canvas_seed": 1, "audio_seed": 2, "font_seed": 3,
        "viewport": {"width": 412, "height": 915},
        "is_mobile": True, "chrome_version": 149,
        "chrome_full_version": "149.0.7827.114",
        "device_scale_factor": 2.625, "os": "android",
    }
    geo = {
        "accept_language": "en-US,en;q=0.9",
        "timezone": "America/New_York", "lat": 40.7, "lon": -74.0,
    }

    hints = client_hint_headers_for_ua(ANDROID)
    script = builder({**base, "client_hints": hints}, geo)
    config = json.loads(script.split("const __KX = ", 1)[1].split(";", 1)[0])
    expected_brands = [
        {"brand": brand, "version": version}
        for brand, version in re.findall(r'"([^"]+)";v="([^"]+)"', hints["sec-ch-ua"])
    ]
    assert config["clientHints"] == {
        "brands": expected_brands, "mobile": True, "platform": "Android",
    }

    no_hint_script = builder({**base, "client_hints": {}}, geo)
    no_hint_config = json.loads(
        no_hint_script.split("const __KX = ", 1)[1].split(";", 1)[0]
    )
    assert no_hint_config["clientHints"] is None
    assert "safeDefine(navigator, 'userAgentData', () => undefined)" in no_hint_script


def test_context_accept_language_is_shared_by_every_outbound_request_path():
    source = (BACKEND / "real_user_traffic.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    outbound_values = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not (9950 <= node.lineno <= 12000):
            continue
        for keyword in node.keywords:
            if keyword.arg == "accept_language":
                outbound_values.append(keyword.value)

    assert len(outbound_values) == 4
    assert all(
        isinstance(value, ast.Name) and value.id == "_context_accept_language"
        for value in outbound_values
    )
    assert '_ctx_headers = {"Accept-Language": _context_accept_language}' in source
    assert "_ctx_headers[\"Accept-Language\"] = _context_accept_language" in source
    assert "accept_language=geo.get(\"accept_language\")" not in source


def test_supported_inapp_coerce_never_returns_generic_chrome():
    samsung = (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/145.0.7632.99 Mobile Safari/537.36"
    )
    for platform in ("tiktok", "facebook", "instagram", "snapchat", "linkedin", "twitter"):
        out = rp.coerce_ua_for_platform(samsung, platform, "en-US")
        assert out, platform
        assert "Android 10; K" not in out, (platform, out)
        app = detect_app(out)["app"]
        expected = {
            "tiktok": "tiktok",
            "facebook": "facebook",
            "instagram": "instagram",
            "snapchat": "snapchat",
            "linkedin": "linkedin",
            "twitter": "twitter",
        }[platform]
        assert app == expected, (platform, out)
        assert validate_user_agent(out, expected_app=app)["valid"], (platform, out)


def test_ensure_inapp_platform_ua_rebuilds_until_identity_is_valid():
    junk = "."
    out = rp.ensure_inapp_platform_ua(
        junk,
        "tiktok",
        "en-US",
        mobile_ua_factory=lambda: (
            "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
            "Chrome/145.0.7632.99 Mobile Safari/537.36"
        ),
        attempts=3,
    )
    assert out
    assert detect_app(out)["app"] == "tiktok"
    assert "musical_ly_" in out
    assert "Region/" in out
    assert "Android 10; K" not in out
    assert validate_user_agent(out, expected_app="tiktok")["valid"]


def test_rut_visit_path_skips_instead_of_chrome_leak_on_coerce_failure():
    source = (BACKEND / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "ensure_inapp_platform_ua" in source
    assert 'visit skipped to avoid Chrome/generic browser leak' in source
    assert "skipped_ua" in source
    assert "_mobile_ua_for_inapp()" in source
    assert "_realistic_fallback_ua()" in source
