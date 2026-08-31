"""v2.7.74 — Real device viewport resolution for mobile shell."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_iphone15_pro_max_viewport():
    from mobile_device_viewport import resolve_device_spec

    spec = resolve_device_spec(device_id="iphone15promax")
    assert spec["width"] == 430
    assert spec["height"] == 932
    assert spec["physical_width"] == 1290
    assert spec["physical_height"] == 2796


def test_iphone15_pro_viewport():
    from mobile_device_viewport import resolve_device_spec

    spec = resolve_device_spec(device_id="iphone15pro")
    assert spec["width"] == 393
    assert spec["height"] == 852


def test_galaxy_s24_viewport():
    from mobile_device_viewport import resolve_device_spec

    spec = resolve_device_spec(device_id="galaxys24")
    assert spec["width"] == 360
    assert spec["height"] == 780


def test_shell_accepts_pro_max_width():
    from krexion_mobile_browser_shell import compute_mobile_shell_layout

    lay = compute_mobile_shell_layout("ios", 430, 932)
    assert lay.viewport_w == 430
    assert lay.viewport_h == 932


def test_profile_resolves_catalog():
    from mobile_device_viewport import resolve_profile_device_viewport

    spec = resolve_profile_device_viewport(
        {
            "device_catalog_id": "iphone15pro",
            "viewport": {"width": 390, "height": 844},
        }
    )
    assert spec["width"] == 393
    assert spec["height"] == 852
    assert spec["from_catalog"] is True
