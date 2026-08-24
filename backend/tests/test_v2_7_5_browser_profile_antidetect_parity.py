"""v2.7.5 — Browser Profiles RUT-parity anti-detect (unit tests)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# real_user_traffic imports playwright at module load — stub for unit tests.
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault(
    "playwright.async_api",
    MagicMock(async_playwright=MagicMock(), Page=object, BrowserContext=object, Browser=object),
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import browser_profile_launcher as bpl  # noqa: E402


UA_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_headed_launch_args_include_webrtc_and_rut_flags():
    args = bpl._PROFILE_HEADED_LAUNCH_ARGS
    joined = " ".join(args)
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in joined
    assert "--disable-blink-features=AutomationControlled" in joined
    assert "--enable-quic" in joined
    assert "headless" not in joined.lower()


def test_build_profile_stealth_fp_has_required_rut_keys():
    fp = bpl._build_profile_stealth_fp(
        UA_WIN,
        profile_id="prof-stable-1",
        viewport={"width": 1440, "height": 900},
        dsf=1.25,
        is_mobile=False,
        has_touch=False,
        profile_os="windows",
    )
    for key in (
        "platform",
        "vendor",
        "hardware_concurrency",
        "device_memory",
        "webgl_vendor",
        "webgl_renderer",
        "canvas_seed",
        "audio_seed",
        "font_seed",
        "fonts",
        "screen_width",
        "max_touch_points",
    ):
        assert key in fp, f"missing {key}"
        assert fp[key] not in (None, ""), f"empty {key}"

    # Profile viewport kept (not RUT random)
    assert fp["viewport"]["width"] == 1440
    assert fp["viewport"]["height"] == 900
    assert float(fp["device_scale_factor"]) == 1.25
    assert fp["is_mobile"] is False


def test_build_profile_stealth_fp_stable_across_calls():
    kwargs = dict(
        profile_id="prof-stable-2",
        viewport={"width": 1280, "height": 720},
        dsf=1.0,
        is_mobile=False,
        has_touch=False,
        profile_os="windows",
    )
    a = bpl._build_profile_stealth_fp(UA_WIN, **kwargs)
    b = bpl._build_profile_stealth_fp(UA_WIN, **kwargs)
    assert a["canvas_seed"] == b["canvas_seed"]
    assert a["audio_seed"] == b["audio_seed"]
    assert a["hardware_concurrency"] == b["hardware_concurrency"]
    assert a["webgl_vendor"] == b["webgl_vendor"]
    assert a["webgl_renderer"] == b["webgl_renderer"]


def test_build_profile_stealth_fp_mobile_touch():
    fp = bpl._build_profile_stealth_fp(
        UA_ANDROID,
        profile_id="prof-mobile-1",
        viewport={"width": 412, "height": 915},
        dsf=2.625,
        is_mobile=True,
        has_touch=True,
        profile_os="android",
    )
    assert fp["is_mobile"] is True
    assert fp["has_touch"] is True
    assert int(fp["max_touch_points"]) >= 1
    assert fp["viewport"]["width"] == 412


def test_launcher_wires_rut_parity_path():
    src = _read("browser_profile_launcher.py")
    assert "_build_profile_stealth_fp" in src
    assert "_rut_apply_context_stealth" in src
    assert "_align_profile_geo_from_proxy" in src
    assert '"permissions": ["geolocation"]' in src
    assert "_PROFILE_HEADED_LAUNCH_ARGS" in src
