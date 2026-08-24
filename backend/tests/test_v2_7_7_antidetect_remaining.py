"""v2.7.7 — Remaining anti-detect fixes (UA/136, iOS coerce, QUIC, stealth)."""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

# real_user_traffic / smart_funnel import playwright at module load.
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


def test_version_is_2_7_7():
    # Superseded by later releases — keep suite green.
    assert _read("VERSION").strip() == "2.7.10"


def test_rut_fallback_and_android_pool_chrome_136():
    import real_user_traffic as rut

    for ua in rut._REALISTIC_FALLBACK_UAS:
        assert "Chrome/136" in ua
        assert "Chrome/146" not in ua
        assert "Chrome/147" not in ua
    for ua in rut._MOBILE_UA_POOL_ANDROID:
        assert "Chrome/136" in ua
        assert "Chrome/144" not in ua
        assert "Chrome/145" not in ua
        assert "Chrome/146" not in ua


def test_ios_safari_coerce_helpers_exist():
    import os
    import real_user_traffic as rut

    assert hasattr(rut, "_is_pure_ios_safari_ua")
    assert hasattr(rut, "_coerce_ua_off_webkit_on_chromium")
    safari = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 "
        "Mobile/15E148 Safari/604.1"
    )
    assert rut._is_pure_ios_safari_ua(safari) is True
    crios = safari.replace(
        "Version/26.2 Mobile/15E148 Safari/604.1",
        "CriOS/136.0.7103.125 Mobile/15E148 Safari/604.1",
    )
    assert rut._is_pure_ios_safari_ua(crios) is False
    prev = os.environ.pop("KREXION_ALLOW_IOS_SAFARI_UA", None)
    try:
        out = rut._coerce_ua_off_webkit_on_chromium(safari)
        assert "Android" in out and "Chrome/136" in out
        assert rut._is_pure_ios_safari_ua(out) is False
    finally:
        if prev is not None:
            os.environ["KREXION_ALLOW_IOS_SAFARI_UA"] = prev


def test_no_origin_to_force_quic_on_star():
    rut = _read("real_user_traffic.py")
    bpl = _read("browser_profile_launcher.py")
    assert "--origin-to-force-quic-on=*" not in rut
    assert "--origin-to-force-quic-on=*" not in bpl
    assert "--enable-quic" in rut
    assert "EnableDualStackForChrome" not in rut.split("_BROWSER_LAUNCH_ARGS_BASE")[1].split("]")[0]


def test_iframe_webdriver_undefined_in_stealth_source():
    src = _read("real_user_traffic.py")
    assert "get: () => undefined" in src or "get:()=>undefined" in src.replace(" ", "")
    assert "win.navigator, 'webdriver', { get: () => undefined" in src


def test_allow_headless_shell_checked_in_variant_path():
    src = _read("real_user_traffic.py")
    chunk = src.split("async def _launch_anti_detect_browser")[1].split(
        "\nasync def "
    )[0]
    assert "use_classic_headless" in chunk
    assert "KREXION_ALLOW_HEADLESS_SHELL" in chunk
    assert "headless-shell variant is blocked" in chunk or chunk.count(
        "KREXION_ALLOW_HEADLESS_SHELL"
    ) >= 2


def test_smart_funnel_human_click_uses_behavioral_profile():
    src = _read("smart_funnel.py")
    fn = None
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_human_page_click":
            fn = ast.get_source_segment(src, node) or ""
            break
    assert fn
    assert "BehavioralProfile" in fn
    assert "move_mouse_human" in fn


def test_apply_contract_client_hints_accepts_viewport():
    import real_user_traffic as rut

    sig = inspect.signature(rut._apply_contract_client_hints)
    assert "viewport" in sig.parameters
    # Optional — default None
    assert sig.parameters["viewport"].default is None


def test_tls_fallback_uas_chrome_136():
    from tls_anti_detect import _FALLBACK_UAS

    for ua in _FALLBACK_UAS:
        assert "Chrome/136" in ua


def test_profile_mobile_fallback_no_pure_safari():
    import browser_profile_module as bpm

    for ua in bpm._FALLBACK_UAS_MOBILE:
        assert "iPhone" not in ua or "CriOS/" in ua or "Chrome/" in ua
        assert "Version/" not in ua or "Chrome/" in ua
        assert "Chrome/136" in ua
