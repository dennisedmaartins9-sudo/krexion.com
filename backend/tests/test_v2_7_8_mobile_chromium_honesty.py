"""v2.7.8 — Mobile Chromium honesty (iOS/WebKit → Android Chrome)."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault(
    "playwright.async_api",
    MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    ),
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 "
    "Mobile/15E148 Safari/604.1"
)
WKWEBVIEW = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "[FBAN/FBIOS;FBAV/512.0.0.0.0;]"
)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.7103.125 Mobile Safari/537.36"
)


def test_version_is_2_7_8():
    # Superseded by later releases — keep suite green.
    from releases_module import _parse as _semver_parse
    assert _semver_parse(_read("VERSION").strip()) >= _semver_parse("2.7.10")


def test_is_ios_webkit_ua_safari_and_wkwebview():
    import real_user_traffic as rut

    assert rut._is_ios_webkit_ua(SAFARI) is True
    assert rut._is_ios_webkit_ua(WKWEBVIEW) is True
    assert rut._is_pure_ios_safari_ua(SAFARI) is True
    assert rut._is_pure_ios_safari_ua(WKWEBVIEW) is False
    crios = SAFARI.replace(
        "Version/26.2 Mobile/15E148 Safari/604.1",
        "CriOS/136.0.7103.125 Mobile/15E148 Safari/604.1",
    )
    assert rut._is_ios_webkit_ua(crios) is False
    assert rut._is_ios_webkit_ua(ANDROID_CHROME) is False


def test_coerce_swaps_safari_and_wkwebview_to_android_chrome_136():
    import real_user_traffic as rut

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        for src in (SAFARI, WKWEBVIEW):
            out = rut._coerce_ua_off_webkit_on_chromium(src)
            assert "Android" in out
            assert "Chrome/136" in out
            assert rut._is_ios_webkit_ua(out) is False
            # Alias helper
            assert "Android" in rut._coerce_ios_webview_off_chromium(src)
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_normalize_meta_os_android_after_coerce():
    import real_user_traffic as rut
    from unittest.mock import patch

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        # Chromium-only normalize still swaps (legacy helper).
        out, meta = rut._normalize_mobile_ua_for_chromium(SAFARI)
        assert meta["swapped_ios"] is True
        assert meta["os"] == "android"
        assert meta["is_mobile"] is True
        assert "Android" in out and "Chrome/136" in out
        assert "Chromium honesty" in (meta.get("note") or "")

        # CriOS also swapped unless allow
        crios = SAFARI.replace(
            "Version/26.2 Mobile/15E148 Safari/604.1",
            "CriOS/136.0.7103.125 Mobile/15E148 Safari/604.1",
        )
        out2, meta2 = rut._normalize_mobile_ua_for_chromium(crios)
        assert meta2["swapped_ios"] is True
        assert meta2["os"] == "android"
        assert "Android" in out2

        # Visit normalize: when WebKit missing, same Android swap.
        with patch.object(rut, "_webkit_runtime_available", return_value=False):
            out3, meta3 = rut._normalize_mobile_ua_for_visit(SAFARI)
        assert meta3["engine"] == "chromium"
        assert meta3["swapped_ios"] is True
        assert "Android" in out3
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_android_pool_has_app_and_webview():
    import real_user_traffic as rut

    app = [u for u in rut._MOBILE_UA_POOL_ANDROID if "; wv)" not in u]
    wv = [u for u in rut._MOBILE_UA_POOL_ANDROID if "; wv)" in u]
    assert app, "expected Chrome Mobile app UAs (no wv)"
    assert wv, "expected WebView UAs (wv)"
    for ua in rut._MOBILE_UA_POOL_ANDROID:
        assert "Chrome/136" in ua


def test_profile_module_create_sets_os_android_for_android_ua():
    import browser_profile_module as bpm
    from browser_profile_module import ProfileBody
    from unittest.mock import patch

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        body = ProfileBody(
            name="t",
            country="us",
            device_type="mobile",
            is_mobile=True,
            os="ios",  # operator said ios, but UA is Android after coerce
            user_agent=ANDROID_CHROME,
        )
        doc = bpm._profile_doc("user-1", body)
        assert "Android" in doc["user_agent"]
        assert doc["os"] == "android"
        assert doc["is_mobile"] is True
        assert doc["has_touch"] is True

        # v2.7.9 — Safari UA stored as requested (launch path decides engine).
        body2 = ProfileBody(
            name="t2",
            country="us",
            device_type="mobile",
            is_mobile=True,
            os="ios",
            user_agent=SAFARI,
        )
        doc2 = bpm._profile_doc("user-1", body2)
        assert "iPhone" in doc2["user_agent"]
        assert doc2["os"] == "ios"

        # When WebKit missing at visit-normalize time, chromium path still swaps.
        import real_user_traffic as rut

        with patch.object(rut, "_webkit_runtime_available", return_value=False):
            out, meta = rut._normalize_mobile_ua_for_visit(SAFARI)
        assert meta["swapped_ios"] is True
        assert "Android" in out
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_honest_ua_platform_maps_ios_to_android():
    import browser_profile_module as bpm
    from unittest.mock import patch

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        with patch(
            "real_user_traffic._webkit_runtime_available", return_value=False
        ):
            assert bpm._honest_ua_platform_for_profiles("", is_mobile=True) == "android"
            assert bpm._honest_ua_platform_for_profiles("ios", is_mobile=True) == "android"
            assert bpm._honest_ua_platform_for_profiles("android", is_mobile=True) == "android"
        with patch(
            "real_user_traffic._webkit_runtime_available", return_value=True
        ):
            assert bpm._honest_ua_platform_for_profiles("ios", is_mobile=True) == "ios"
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_server_clamp_chrome_versions_exists_and_clamps():
    # Importing full server is heavy; assert source + call the helper via
    # ast/exec of the function body, or import if available.
    src = _read("server.py")
    assert "def _clamp_chrome_versions" in src
    assert "_chromium_honesty_max_major" in src

    # Execute just the clamp helper
    ns: dict = {}
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_clamp_chrome_versions",
            "_chromium_honesty_max_major",
        ):
            code = compile(ast.Module(body=[node], type_ignores=[]), "server.py", "exec")
            exec(code, ns)
    clamp = ns["_clamp_chrome_versions"]
    out = clamp(["149.0.1.0", "136.0.7103.125", "135.0.1.0"], max_major=136)
    assert all(int(v.split(".", 1)[0]) <= 136 for v in out)
    assert "136.0.7103.125" in out
    assert "149.0.1.0" not in out


def test_inapp_preset_replaces_ios_uas_source_and_runtime():
    import real_user_traffic as rut
    from unittest.mock import patch

    src = _read("real_user_traffic.py")
    assert "_is_ios_webkit_ua" in src
    assert "Scrub iOS/WebKit" in src or "_is_ios_webkit_ua(u)" in src

    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        # When WebKit unavailable — scrub iOS bases (v2.7.8 behaviour).
        with patch.object(rut, "_webkit_runtime_available", return_value=False):
            out = rut._apply_inapp_preset_to_uas(
                [SAFARI, WKWEBVIEW, ANDROID_CHROME],
                want_count=3,
                preset_platform="tiktok",
            )
        assert len(out) == 3
        for ua in out:
            assert rut._is_ios_webkit_ua(ua) is False
            assert "Android" in ua or "android" in ua.lower()
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_fingerprint_android_fonts_not_linux_remap():
    """Linux host remaps windows/macos fonts only — android stays android."""
    import real_user_traffic as rut

    src = _read("real_user_traffic.py")
    assert 'os_key in ("windows", "macos")' in src
    fp = rut._fingerprint_from_ua(ANDROID_CHROME)
    assert fp["os"] == "android"
    assert fp["fonts"] == rut._OS_FONTS["android"]


def test_referrer_pro_android_ua_gets_android_markers():
    from referrer_pro import coerce_ua_for_platform

    out = coerce_ua_for_platform(ANDROID_CHROME, "facebook")
    assert "FB4A" in out or "FB_IAB" in out
    assert "FBIOS" not in out
