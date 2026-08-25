"""v2.7.12 — Browser Profiles mix % + device catalog + bulk actions."""
from __future__ import annotations

from pathlib import Path

import browser_profile_module as bpm

ROOT = Path(__file__).resolve().parents[1]


def test_split_mix_counts_exact_total():
    plan = bpm._split_mix_counts(10, 50, 30, 20)
    assert plan is not None
    assert sum(n for _, n in plan) == 10
    by = dict(plan)
    assert by.get("ios") == 5
    assert by.get("android") == 3
    assert by.get("desktop") == 2


def test_split_mix_disabled_when_zero():
    assert bpm._split_mix_counts(5, 0, 0, 0) is None


def test_auto_name_device_includes_slug():
    name = bpm._auto_name_device("us", "iPhone15")
    assert name.startswith("Krexion-iPhone15-US-")
    assert len(name.split("-")[-1]) == 4


def test_pick_device_prefers_unused():
    used = set()
    a = bpm._pick_device("android", device_mode="random", used_ids=used)
    b = bpm._pick_device("android", device_mode="random", used_ids=used)
    assert a["id"] in used and b["id"] in used
    # With enough catalog entries, first two should differ when possible
    android_n = len(bpm._devices_for_platform("android"))
    if android_n >= 2:
        assert a["id"] != b["id"]


def test_viewport_match_and_exact():
    dev = bpm._find_device("iphone15")
    assert dev is not None
    vp = bpm._viewport_for_device(dev, resolution_mode="match_device")
    assert vp["width"] == 390 and vp["height"] == 844
    vp2 = bpm._viewport_for_device(dev, resolution_mode="exact", width=800, height=600)
    assert vp2 == {"width": 800, "height": 600}


def test_source_has_bulk_routes_and_catalog():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '@router.post("/bulk-launch")' in src
    assert '@router.post("/bulk-delete")' in src
    assert '@router.post("/bulk-stop")' in src
    assert '@router.get("/device-catalog")' in src
    assert "mix_ios_pct" in src


def test_frontend_has_mix_and_selection():
    fe = (ROOT.parent / "frontend" / "src" / "pages" / "BrowserProfilesPage.js").read_text(encoding="utf-8")
    assert "advMix" in fe
    assert "bp-bulk-launch" in fe
    assert "mix_ios_pct" in fe
    assert "bp-select-all" in fe
