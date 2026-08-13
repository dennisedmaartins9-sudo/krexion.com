import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from ua_profile_contract import (  # noqa: E402
    ANDROID_DEVICE_SNAPSHOTS,
    APP_RELEASES_BY_PLATFORM,
    APP_SUPPORT_MATRIX,
    APP_VERSION_POOLS,
    classify_user_agent,
    client_hint_headers_for_ua,
    detect_app,
    replace_verified_app_releases,
    validate_header_coherence,
    validate_user_agent,
)


ANDROID_WEBVIEW = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240505.005; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/149.0.7827.114 Mobile Safari/537.36 "
)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.7827.114 Mobile Safari/537.36"
)
IOS_WEBVIEW = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
)
IOS_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
    "Mobile/15E148 Safari/604.1"
)
INSTAGRAM_ANDROID = (
    ANDROID_WEBVIEW
    + "Instagram 437.0.0.33.78 Android "
    "(34/14; 420dpi; 1080x2400; google; Pixel 8; husky; tensor; en_US; "
    "1011909233; IABMV/1)"
)
FACEBOOK_ANDROID = (
    ANDROID_WEBVIEW
    + "[FB_IAB/FB4A;FBAV/556.0.0.59.68;"
    "IABMV/1;FBBV/681204512;]"
)
TIKTOK_ANDROID = (
    ANDROID_WEBVIEW
    + "TikTok/45.8.2 musical_ly_2024508020 JsSdk/1.0 NetType/WIFI "
    "Channel/googleplay AppName/musical_ly app_version/45.8.2 "
    "ByteLocale/en ByteFullLocale/en_GB Region/GB "
    "com.zhiliaoapp.musically/2024508020"
)


def test_platform_release_contract_and_legacy_pools_are_exported():
    assert APP_RELEASES_BY_PLATFORM["instagram"]["android"] == [
        {"version": "437.0.0.33.78", "version_code": "1011909233"}
    ]
    assert APP_RELEASES_BY_PLATFORM["tiktok"]["android"][0] == {
        "version": "46.4.1",
        "version_code": "2024604010",
    }
    assert {"version": "45.8.2", "version_code": "2024508020"} in (
        APP_RELEASES_BY_PLATFORM["tiktok"]["android"]
    )
    assert APP_RELEASES_BY_PLATFORM["linkedin"]["android"][0]["package_build"] == "212600"
    assert APP_RELEASES_BY_PLATFORM["reddit"]["android"][0]["build"] == "2618090"
    assert APP_RELEASES_BY_PLATFORM["telegram"]["android"][0]["version"] == "12.9.2"
    assert APP_RELEASES_BY_PLATFORM["instagram"]["ios"][0]["version"] == "425.0.0"
    assert APP_VERSION_POOLS["instagram"][0] == "437.0.0.33.78"
    assert APP_SUPPORT_MATRIX["youtube"] == {"android": "fallback", "ios": "fallback"}
    assert APP_SUPPORT_MATRIX["whatsapp"]["ios"] == "fallback"
    assert APP_SUPPORT_MATRIX["reddit"]["ios"] == "fallback"
    assert APP_SUPPORT_MATRIX["telegram"]["ios"] == "fallback"
    assert APP_SUPPORT_MATRIX["gchrome"]["android"] == "fallback"


def test_verified_android_records_validate_without_authenticity_claim():
    linkedin = (
        ANDROID_WEBVIEW
        + "[LinkedInApp]/2.286.33 com.linkedin.android/212600"
    )
    reddit = ANDROID_WEBVIEW + "Reddit/Version 2026.18.0/Build 2618090/Android 14"
    samples = {
        "instagram": INSTAGRAM_ANDROID,
        "facebook": FACEBOOK_ANDROID,
        "tiktok": TIKTOK_ANDROID,
        "whatsapp": ANDROID_WEBVIEW + "WhatsApp/2.26.5.10 A",
        "linkedin": linkedin,
        "twitter": ANDROID_WEBVIEW + "TwitterAndroid/11.95.1",
        "reddit": reddit,
        "telegram": ANDROID_WEBVIEW + "Telegram-Android/12.9.2",
    }
    for app, ua in samples.items():
        result = validate_user_agent(ua, expected_app=app)
        assert result["valid"], (app, result)
        assert result["support_state"] == "supported"


def test_detect_app_collects_every_identity_and_observed_markers():
    hybrid = INSTAGRAM_ANDROID + " Snapchat/13.88.0.56"
    detected = detect_app(hybrid)
    assert detected["app"] == "instagram"
    assert detected["identities"] == ["instagram", "snapchat"]

    cases = {
        "[LinkedInApp]/2.286.33": ("linkedin", "2.286.33"),
        "Twitter for iPhone/10.98.0": ("twitter", "10.98.0"),
        "Telegram-Android/12.9.2": ("telegram", "12.9.2"),
        "[Pinterest/Android]": ("pinterest", None),
        "GoogleApp/332.0.755318947": ("gsearch", "332.0.755318947"),
        "GSA/332.0.755318947": ("gsearch", "332.0.755318947"),
        "musical_ly_44.7.0": ("tiktok", "44.7.0"),
    }
    for marker, expected in cases.items():
        result = detect_app(marker)
        assert (result["app"], result["app_version"]) == expected


def test_hybrids_duplicate_blocks_and_expected_mismatch_are_rejected():
    hybrid = validate_user_agent(
        INSTAGRAM_ANDROID + " Snapchat/13.88.0.56",
        expected_app="instagram",
    )
    assert any("multiple foreign app identities" in issue for issue in hybrid["issues"])

    duplicate = validate_user_agent(INSTAGRAM_ANDROID + " Instagram 437.0.0.33.78 Android")
    assert any("duplicate instagram" in issue.lower() for issue in duplicate["issues"])

    mismatch = validate_user_agent(INSTAGRAM_ANDROID, expected_app="facebook")
    assert any("recognizable facebook" in issue.lower() for issue in mismatch["issues"])


def test_incompatible_apple_device_claims_are_rejected():
    bad = IOS_SAFARI.replace("(iPhone;", "(iPad;").replace(
        "CPU iPhone OS", "CPU iPhone OS"
    ) + " iPhone"
    result = validate_user_agent(bad)
    assert any("incompatible" in issue.lower() for issue in result["issues"])


def test_tiktok_release_fields_must_all_agree():
    assert validate_user_agent(TIKTOK_ANDROID, expected_app="tiktok")["valid"]
    for bad in (
        TIKTOK_ANDROID.replace("app_version/45.8.2", "app_version/45.8.1"),
        TIKTOK_ANDROID.replace("musical_ly_2024508020", "musical_ly_2024508021"),
        TIKTOK_ANDROID.replace(
            "com.zhiliaoapp.musically/2024508020",
            "com.zhiliaoapp.musically/2024508021",
        ),
    ):
        result = validate_user_agent(bad, expected_app="tiktok")
        assert any("conflict" in issue.lower() for issue in result["issues"])


def test_facebook_requires_one_full_verified_android_block():
    truncated = FACEBOOK_ANDROID.replace("556.0.0.59.68", "556.0.0")
    result = validate_user_agent(truncated, expected_app="facebook")
    assert any("five-part" in issue or "verified release" in issue for issue in result["issues"])

    duplicate = validate_user_agent(
        FACEBOOK_ANDROID + " "
        "[FB_IAB/FB4A;FBAV/556.0.0.59.68;"
        "IABMV/1;FBBV/681204512;]",
        expected_app="facebook",
    )
    assert any("duplicate facebook" in issue.lower() for issue in duplicate["issues"])
    assert any("exactly one" in issue.lower() for issue in duplicate["issues"])


def test_malformed_linkedin_telegram_and_twitter_formats_are_rejected():
    malformed = {
        "linkedin": ANDROID_WEBVIEW + "LinkedInApp/2.286.33",
        "telegram": ANDROID_WEBVIEW + "TelegramAndroid/12.9.2",
        "twitter": IOS_WEBVIEW + "TwitterIOS/10.98.0",
    }
    for app, ua in malformed.items():
        result = validate_user_agent(ua, expected_app=app)
        assert not result["valid"], (app, result)
        assert any(app in issue.lower() or "package" in issue.lower() for issue in result["issues"])


def test_known_oem_firmware_requires_exact_snapshot_tuple():
    bad = INSTAGRAM_ANDROID.replace("Android 14", "Android 13")
    result = validate_user_agent(
        bad,
        expected_app="instagram",
        require_verified_device=True,
    )
    assert any("verified device snapshot" in issue.lower() for issue in result["issues"])


def test_unknown_external_oem_build_warns_instead_of_false_failure():
    external = INSTAGRAM_ANDROID.replace("Pixel 8", "OEM-X", 1)
    result = validate_user_agent(external, expected_app="instagram")
    assert result["valid"], result
    assert any("could not be verified" in warning.lower() for warning in result["warnings"])


def test_android_16_capture_tuples_validate():
    for model, build in (
        ("Pixel 8", "CP1A.260505.005"),
        ("Pixel 9", "CP1A.260505.005"),
        ("2510ERA8BG", "BP2A.250605.031.A3"),
    ):
        ua = (
            f"Mozilla/5.0 (Linux; Android 16; {model} Build/{build}; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
            "Chrome/151.0.7922.83 Mobile Safari/537.36 "
            "[Pinterest/Android]"
        )
        result = validate_user_agent(ua, expected_app="pinterest")
        assert result["valid"], result
    assert {row["and_ver"] for row in ANDROID_DEVICE_SNAPSHOTS} == {
        "13", "14", "15", "16"
    }


def test_trusted_ios_refresh_updates_shared_validation_contract():
    original = [
        dict(record) for record in APP_RELEASES_BY_PLATFORM["instagram"]["ios"]
    ]
    refreshed = "999.1.2"
    ua = IOS_WEBVIEW + f"Instagram {refreshed}"
    try:
        assert not validate_user_agent(ua, expected_app="instagram")["valid"]
        replace_verified_app_releases(
            "instagram",
            "ios",
            [{"version": refreshed}, *original],
        )
        result = validate_user_agent(ua, expected_app="instagram")
        assert result["valid"], result
        assert result["identity_supported"] is True
        assert result["support_state"] == "supported"
    finally:
        replace_verified_app_releases("instagram", "ios", original)


def test_unsupported_expected_app_accepts_generic_fallback_with_warning():
    result = validate_user_agent(IOS_SAFARI, expected_app="whatsapp")
    assert result["valid"]
    assert result["app"] == "browser"
    assert result["support_state"] == "fallback"
    assert result["identity_supported"] is False
    assert any("generic browser fallback" in warning.lower() for warning in result["warnings"])

    youtube = validate_user_agent(ANDROID_CHROME, expected_app="youtube")
    assert youtube["valid"]
    assert youtube["support_state"] == "fallback"


def test_android_webview_and_chrome_get_distinct_exact_hints():
    # v2.6.88 — In-app Android WebView (Instagram) must emit NO Chromium
    # Client Hints so Everflow labels "Instagram" / "TikTok for Android"
    # from the UA string instead of "Chrome".
    assert client_hint_headers_for_ua(INSTAGRAM_ANDROID) == {}
    assert validate_header_coherence(INSTAGRAM_ANDROID, {}) == []
    assert validate_header_coherence(
        INSTAGRAM_ANDROID,
        {"Sec-CH-UA": '"Android WebView";v="149", "Chromium";v="149", "Not=A?Brand";v="24"'},
    )

    chrome_hints = client_hint_headers_for_ua(ANDROID_CHROME)
    assert chrome_hints["sec-ch-ua"] == (
        '"Google Chrome";v="149", "Chromium";v="149", "Not=A?Brand";v="24"'
    )
    assert validate_header_coherence(ANDROID_CHROME, chrome_hints) == []
    assert validate_header_coherence(
        ANDROID_CHROME,
        {"Sec-CH-UA": chrome_hints["sec-ch-ua"]},
    )


def test_crios_webkit_and_gecko_emit_no_hints_and_reject_them():
    crios = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/147.0.7727.102 "
        "Mobile/15E148 Safari/604.1"
    )
    firefox = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) "
        "Gecko/20100101 Firefox/141.0"
    )
    fake_hints = {
        "sec-ch-ua": '"Google Chrome";v="149"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    assert classify_user_agent(crios)["engine"] == "webkit"
    assert client_hint_headers_for_ua(crios) == {}
    assert client_hint_headers_for_ua(firefox) == {}
    assert validate_header_coherence(crios, fake_hints)
    assert validate_header_coherence(firefox, fake_hints)


def test_cronet_remains_native_and_tiktok_consistent():
    cronet = TIKTOK_ANDROID.replace(
        "; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/149.0.7827.114 Mobile Safari/537.36 ",
        "; Cronet/118.0.5993.117) ",
    )
    result = validate_user_agent(cronet, expected_app="tiktok")
    assert result["valid"]
    assert result["engine"] == "cronet"
    assert result["runtime_compatible"] is False
    assert result["warnings"]
