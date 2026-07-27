"""Unit tests for native Smart Funnel engine."""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_handler_script_exists():
    from smart_funnel import handler_path_for_tests, load_handler_script

    p = handler_path_for_tests()
    assert p.is_file(), f"missing {p}"
    text = load_handler_script()
    assert "SMART_FLOW" in text or "function" in text
    assert len(text) > 500
    assert (ROOT / "backend" / "smart_flow_handler.js").is_file(), "bundled backend copy missing"


def test_smart_funnel_patterns():
    from smart_funnel import SMART_FUNNEL_PATTERNS, list_patterns

    patterns = list_patterns()
    assert len(patterns) >= 3
    assert "auto" in SMART_FUNNEL_PATTERNS
    assert any(p["id"] == "reward_survey_funnel" for p in patterns)


def test_smart_funnel_config_normalizes_pattern():
    from smart_funnel import SmartFunnelConfig

    cfg = SmartFunnelConfig(pattern="UNKNOWN")
    assert cfg.normalized_pattern() == "auto"
    cfg2 = SmartFunnelConfig(pattern="reward_survey_funnel", min_deals=3)
    assert cfg2.normalized_pattern() == "reward_survey_funnel"
    assert cfg2.min_deals == 3


def test_run_real_user_traffic_job_accepts_smart_funnel_kwargs():
    src = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    for name in (
        "smart_funnel_enabled",
        "smart_funnel_pattern",
        "smart_funnel_min_deals",
        "smart_funnel_wait_until_conversion",
    ):
        assert f"{name}:" in src or f"{name}=" in src, f"missing param {name} in run_real_user_traffic_job"


def test_guess_phase_deals():
    from smart_funnel import _guess_phase

    assert _guess_phase("your cost: $1.00 complete 2 deals", "https://x.com") == "deals"
    assert _guess_phase("first name last name", "https://x.com") == "form"
    assert _guess_phase("how often do you shop", "https://survey.com") == "survey"


def test_url_deals_from_href():
    from smart_funnel import conversion_verified, url_deals_from_href

    u = "https://x.com/?BVA=True&BVC=True&BVE=True"
    assert url_deals_from_href(u) == 3
    assert url_deals_from_href("https://retailproductsusa.com/rewards") == 0
    assert conversion_verified(
        {"url": u, "host": "x.com", "conv": False}, min_deals=2, wait_until_conversion=True
    )
    assert not conversion_verified(
        {"url": "https://retailproductsusa.com/", "host": "retailproductsusa.com", "conv": True},
        min_deals=2,
        wait_until_conversion=True,
    )
