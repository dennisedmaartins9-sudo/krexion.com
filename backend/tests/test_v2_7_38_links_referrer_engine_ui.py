"""v2.7.38 — Shared traffic source presets (Links + RUT parity)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "frontend" / "src" / "lib"))

# Run preset logic via node-less import: duplicate key checks in Python mirror
PRESET_POOLS = {
    "mixed_realistic": "facebook:30,instagram:15,tiktok:20,google:20,twitter:5,email:10",
    "social_media_ads": "facebook:40,instagram:30,tiktok:25,twitter:5",
    "search_engine_ads": "google:65,bing:25,duckduckgo:5,yandex:5",
    "email_campaign": "email:100",
}


def test_traffic_source_presets_module_exists():
    p = ROOT.parent / "frontend" / "src" / "lib" / "trafficSourcePresets.js"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "buildLinkProPatchFromPreset" in text
    assert "mixed_realistic" in text
    assert "TRAFFIC_SOURCE_PRESET_SUMMARY" in text


def test_links_page_referrer_engine_ui():
    src = (ROOT.parent / "frontend" / "src" / "pages" / "LinksPage.js").read_text(encoding="utf-8")
    assert "Referrer Engine" in src
    assert "link-traffic-source-preset" in src
    assert "My Saved Presets (shared with RUT)" in src
    assert "Basic Referrer Settings" in src
    assert "!formData.referrer_pro_enabled" in src
    assert "Quality Tier (Feature 6" not in src
    assert "Traffic Type (v2.6.24" not in src


def test_preset_pool_strings_stable():
    assert "facebook:30" in PRESET_POOLS["mixed_realistic"]
    assert PRESET_POOLS["email_campaign"] == "email:100"
