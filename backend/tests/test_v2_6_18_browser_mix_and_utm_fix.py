"""
Regression tests — v2.6.18 browser-mixing + UTM-forwarding fix pack.

Covers:
  1. _apply_inapp_preset_to_uas now scrubs third-party mobile browsers
     (WeChat, Firefox, Whale, UC, Samsung, Opera, Edge, Line, Kakao, …).
  2. _strip_foreign_inapp_markers regex list expanded with the same
     third-party browsers so coerce_ua_for_platform produces a clean UA.
  3. /r/{short_code} + /t/{short_code} + /api/t/{short_code} +
     /api/r/{short_code} all forward incoming utm_* / click_id / sub_* /
     tid / gclid / fbclid / ttclid / etc. to the destination URL.
"""

import ast
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUT_FILE = REPO_ROOT / "real_user_traffic.py"
REFERRER_FILE = REPO_ROOT / "referrer_pro.py"
SERVER_FILE = REPO_ROOT / "server.py"


def test_version_bumped_to_2_6_18_or_higher():
    v = (REPO_ROOT / "VERSION").read_text().strip()
    parts = tuple(int(p) for p in v.split("."))
    assert parts >= (2, 6, 18), f"Expected >= 2.6.18, got {v!r}"


def test_third_party_browser_scrub_in_preset_gate():
    """`_apply_inapp_preset_to_uas` must scrub UAs containing WeChat /
    Firefox / Whale / UC / Samsung / Opera / Edge / Line / Kakao / etc."""
    src = RUT_FILE.read_text(encoding="utf-8")
    # The new list of markers is defined right above _FOREIGN_MARKERS
    assert '_THIRD_PARTY_MOBILE_BROWSERS' in src
    for needle in [
        '"micromessenger"',    # WeChat
        '"fxios"',             # Firefox iOS
        '"whale"',             # Naver Whale
        '"ucbrowser"',         # UC Browser
        '"samsungbrowser"',    # Samsung Internet
        '"opr/"',              # Opera
        '"edga/"',             # Edge Android
        '"line/"',             # Line
        '"kakaotalk"',         # Kakao
        '"mqqbrowser"',        # QQ
        '"duckduckgo"',        # DuckDuckGo
        '"brave/"',            # Brave
    ]:
        assert needle in src, f"third-party marker {needle} missing"


def test_apply_inapp_preset_replaces_third_party_browsers():
    """Empirical: calling _apply_inapp_preset_to_uas with tiktok preset
    and a mixed pool must strip all third-party markers."""
    sys.path.insert(0, str(RUT_FILE.parent))
    tree = ast.parse(RUT_FILE.read_text(encoding="utf-8"))
    wanted_functions = {"_mobile_ua_for_inapp", "_apply_inapp_preset_to_uas"}
    wanted_constants = {"_MOBILE_UA_POOL_IOS", "_MOBILE_UA_POOL_ANDROID"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            nodes.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in wanted_constants:
                nodes.append(node)
    # v2.7.9 — extracted helpers call module-level dual-engine guards;
    # stub them so this AST-isolated exec stays self-contained.
    namespace = {
        "random": random, "Dict": Dict, "List": List, "Tuple": Tuple,
        "_allow_ios_safari_ua": lambda: False,
        "_webkit_runtime_available": lambda: False,
        "_is_ios_webkit_ua": lambda _u: False,
        "_is_ios_claiming_ua": lambda _u: False,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUT_FILE), "exec"), namespace)
    rut = SimpleNamespace(**namespace)

    input_uas = [
        # WeChat iOS mobile UA
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a2f) NetType/WIFI Language/en",
        # Whale mobile UA
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 NAVER(inapp; whale)/2.0 Whale/2.0.0",
        # Firefox iOS UA
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/128.0 Mobile/15E148 Safari/605.1.15",
        # Samsung Internet UA
        "Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/22.0 Chrome/115.0.0.0 Mobile Safari/537.36",
        # Plain mobile Chrome (safe baseline)
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Mobile Safari/537.36",
    ]
    out = rut._apply_inapp_preset_to_uas(input_uas, want_count=len(input_uas), preset_platform="tiktok")
    assert len(out) == 5
    # None of the outputs should still carry the third-party marker
    for ua in out:
        ual = ua.lower()
        assert "micromessenger" not in ual, f"WeChat leaked: {ua[:100]}"
        assert "fxios" not in ual, f"Firefox iOS leaked: {ua[:100]}"
        assert "whale" not in ual, f"Whale leaked: {ua[:100]}"
        assert "samsungbrowser" not in ual, f"Samsung leaked: {ua[:100]}"


def test_strip_foreign_inapp_markers_covers_third_party():
    """_FOREIGN_INAPP_STRIP_PATTERNS in referrer_pro must include new
    third-party browser strippers so coerce_ua_for_platform emits a
    clean UA."""
    src = REFERRER_FILE.read_text(encoding="utf-8")
    for key in [
        '"wechat":', '"firefox_mobile":', '"firefox_focus":',
        '"whale":', '"ucbrowser":', '"samsung_internet":',
        '"opera_mobile":', '"edge_mobile":', '"line_browser":',
        '"kakao":', '"qq":', '"yandex":', '"brave_mobile":',
        '"duckduckgo":', '"puffin":', '"silk":',
        '"miui":', '"huawei":', '"vivo":', '"oppo":',
        '"baidu":', '"sogou":', '"coc_coc":',
    ]:
        assert key in src, f"strip pattern {key} missing"


def test_coerce_ua_strips_wechat_and_appends_tiktok():
    """End-to-end: WeChat UA + tiktok platform → NO wechat leftover +
    musical_ly marker appended."""
    import importlib
    import sys
    sys.path.insert(0, str(REFERRER_FILE.parent))
    rp = importlib.import_module("referrer_pro")
    input_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "MicroMessenger/8.0.42 NetType/WIFI Language/en"
    )
    out = rp.coerce_ua_for_platform(input_ua, "tiktok")
    assert "MicroMessenger" not in out, f"WeChat marker leaked: {out}"
    assert "musical_ly" in out.lower(), f"TikTok marker missing: {out}"


def test_incoming_query_params_forwarded_to_destination():
    """server.py's redirect_link handler forwards utm_/click_id/sub_*/
    tid/gclid/fbclid/ttclid etc. from incoming request query to the
    destination URL."""
    src = SERVER_FILE.read_text(encoding="utf-8")
    assert "FORWARD INCOMING TRACKING QUERY PARAMS" in src
    assert "_PASSTHROUGH_KEYS = {" in src
    for k in ['"utm_source"', '"click_id"', '"gclid"', '"fbclid"',
              '"ttclid"', '"ttp"', '"msclkid"', '"twclid"',
              '"li_fat_id"', '"yclid"', '"sub1"', '"sub10"',
              '"p1"', '"pub1"', '"tid"', '"transaction_id"']:
        assert k in src, f"passthrough key {k} missing from whitelist"
    # Existing dest params always win
    assert "if _k not in _existing_qs:" in src


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
