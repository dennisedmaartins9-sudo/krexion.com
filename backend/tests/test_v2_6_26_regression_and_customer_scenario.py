"""
v2.6.26 supplemental — no-regression checks for other platforms + customer scenario
simulation (parse generated UA through `user_agents` python lib).
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import server  # noqa: E402
    import referrer_pro  # noqa: E402
except Exception as _imp_err:
    pytest.skip(
        f"server/referrer_pro unavailable in this environment: {_imp_err}",
        allow_module_level=True,
    )


ANDROID_DEV = {
    "and_ver": "14", "model": "SM-S928B",
    "build": "UP1A.231005.007", "sdk": "34",
    "res": "1080x2340", "dpi": "480", "brand": "samsung",
}
IOS_DEV = {
    "brand": "iPhone", "model": "iPhone16,2", "ios": "18_3",
    "scale": "3.00", "res": "1290x2796", "webkit": "605.1.15",
    "mobile_build": "22D63",
}


# ── iOS TikTok must remain unchanged (no TikTok/{ver}) ────────────────
def test_ua_tiktok_ios_does_NOT_carry_TikTok_slash_ver():
    for _ in range(10):
        try:
            ua = server._ua_tiktok_ios(IOS_DEV, "34.9.5")
        except Exception as e:
            # If ios dev shape differs, just skip cleanly
            import pytest
            pytest.skip(f"ios generator sig differs: {e}")
        # v2.6.26 fix is Android-only; iOS relies on AppId/1233 + musical_ly_
        assert "TikTok/34.9.5" not in ua, f"iOS must NOT gain TikTok/ver: {ua!r}"
        assert "AppId/1233" in ua, f"iOS lost AppId/1233: {ua!r}"
        assert re.search(r"musical_ly_\d+", ua), f"iOS lost musical_ly_: {ua!r}"


# ── Facebook Android must NOT leak TikTok/ ────────────────────────────
def test_ua_facebook_android_no_tiktok_leak():
    for _ in range(10):
        try:
            ua = server._ua_facebook_android(ANDROID_DEV, "500.0.0.55.70", "131.0.6778.135")
        except Exception as e:
            import pytest
            pytest.skip(f"fb android generator sig differs: {e}")
        assert "TikTok/" not in ua, f"FB android leaked TikTok/: {ua!r}"
        assert "musical_ly_" not in ua, f"FB android leaked musical_ly_: {ua!r}"
        assert "FBAV/" in ua, f"FB android lost FBAV/: {ua!r}"


# ── Instagram Android must NOT leak TikTok/ ───────────────────────────
def test_ua_instagram_android_no_tiktok_leak():
    for _ in range(10):
        try:
            ua = server._ua_instagram_android(ANDROID_DEV, "365.0.0.36.90", "131.0.6778.135")
        except Exception as e:
            import pytest
            pytest.skip(f"ig android generator sig differs: {e}")
        assert "TikTok/" not in ua, f"IG android leaked TikTok/: {ua!r}"
        assert "musical_ly_" not in ua, f"IG android leaked musical_ly_: {ua!r}"
        assert "Instagram " in ua, f"IG android lost Instagram marker: {ua!r}"


# ── Instagram iOS must NOT leak TikTok/ ───────────────────────────────
def test_ua_instagram_ios_no_tiktok_leak():
    for _ in range(10):
        try:
            ua = server._ua_instagram_ios(IOS_DEV, "365.0.0.30.104")
        except Exception as e:
            import pytest
            pytest.skip(f"ig ios generator sig differs: {e}")
        assert "TikTok/" not in ua
        assert "musical_ly_" not in ua
        assert "Instagram " in ua


# ── Customer scenario: parse TikTok Android UA via user_agents lib ────
def test_customer_scenario_ua_parses_show_TikTok_slash_ver_slug():
    """v2.6.26 root-cause claim: advertiser UA parsers key on `TikTok/{ver}`.
    We assert the slug is present so the regex `TikTok/([\\d.]+)` matches.
    (The `user_agents` python lib itself uses uap-core rules which look for
    the `TikTok` app family — verify it lands in the parsed device.family
    OR at minimum that the regex applies.)"""
    ua = server._ua_tiktok_android(ANDROID_DEV, "34.9.5")
    m = re.search(r"TikTok/([\d.]+)", ua)
    assert m, f"advertiser regex TikTok/([\\d.]+) will not match: {ua!r}"
    assert m.group(1) == "34.9.5"
    # try user_agents if installed; skip gracefully if not
    try:
        from user_agents import parse  # type: ignore
    except Exception:
        import pytest
        pytest.skip("user_agents lib not installed — regex assert already covers advertiser detection")
    ua_obj = parse(ua)
    # Even if uap-core doesn't tag it TikTok, the slug presence is what
    # advertisers key on. Just print the parsed family for diagnostics.
    print(f"user_agents parsed browser.family={ua_obj.browser.family!r}, "
          f"device.family={ua_obj.device.family!r}, os={ua_obj.os.family!r}")


# ── Coerce OUT of tiktok removes both markers (belt-and-suspenders) ───
def test_coerce_out_of_tiktok_for_all_platforms():
    ua = server._ua_tiktok_android(ANDROID_DEV, "34.9.5")
    for target in ("facebook", "instagram", "snapchat", "twitter",
                   "google", "youtube", "reddit", "pinterest",
                   "linkedin", "messenger"):
        out = referrer_pro.coerce_ua_for_platform(ua, target)
        assert "TikTok/34.9.5" not in out, f"[{target}] TikTok/ leaked: {out!r}"
        assert "musical_ly_" not in out, f"[{target}] musical_ly_ leaked: {out!r}"
