"""v2.7.45 — Manual link clicks: real HTTP Referer via wrapper, no synthetic URL params."""
from __future__ import annotations

import importlib

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_FB_SHIM = "https://l.facebook.com/l.php?u=https%3A%2F%2Foffer.example.com%2F"
_IG_SHIM = "https://l.instagram.com/?u=https%3A%2F%2Foffer.example.com%2F"
_TT_SHIM = "https://www.tiktok.com/link/v2?u=https%3A%2F%2Foffer.example.com%2F"
_GOOGLE_SHIM = "https://www.google.com/url?q=https%3A%2F%2Foffer.example.com%2F"


def _rp():
    return importlib.import_module("referrer_pro")


_FB_INAPP_UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile "
    "Safari/537.36 [FB_IAB/FB4A;FBAV/450.0.0.0.0;]"
)


def test_should_link_wrapper_bounce_meta_skips_cold_desktop():
    rp = _rp()
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "facebook", _FB_SHIM, wrapper_redirect_enabled=True
    )
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "instagram", _IG_SHIM, wrapper_redirect_enabled=True
    )
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "facebook", _FB_SHIM, wrapper_redirect_enabled=False
    )


def test_should_link_wrapper_bounce_meta_when_inapp():
    rp = _rp()
    assert rp.should_link_wrapper_bounce(
        _FB_INAPP_UA, "facebook", _FB_SHIM, wrapper_redirect_enabled=True
    )


def test_should_link_wrapper_bounce_tiktok_always_blocked():
    rp = _rp()
    assert not rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "tiktok", _TT_SHIM, wrapper_redirect_enabled=True
    )


def test_should_link_wrapper_bounce_google_always_allowed():
    rp = _rp()
    assert rp.should_link_wrapper_bounce(
        _DESKTOP_UA, "google", _GOOGLE_SHIM, wrapper_redirect_enabled=False
    )


def test_referer_is_bounce_capable_detects_meta_shim():
    rp = _rp()
    assert rp._referer_is_bounce_capable(_FB_SHIM)
    assert rp._referer_is_bounce_capable(_GOOGLE_SHIM)
    assert not rp._referer_is_bounce_capable("https://www.tiktok.com/")
