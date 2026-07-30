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
    from smart_funnel import SMART_FUNNEL_PATTERNS, list_patterns, rut_config_for_pattern

    patterns = list_patterns()
    assert len(patterns) >= 3
    assert "auto" in SMART_FUNNEL_PATTERNS
    assert "reward" in SMART_FUNNEL_PATTERNS
    assert any(p["id"] == "reward" for p in patterns)
    assert not any(p["id"] == "reward_survey_funnel" for p in patterns)
    cfg = rut_config_for_pattern("reward", min_deals=2, wait_until_conversion=True)
    assert cfg.normalized_pattern() == "reward"
    assert cfg.min_deals >= 3
    assert cfg.survey_skip_chance == 0.0
    assert cfg.guided_deal_cycles == 3
    assert cfg.guided_deal_l3_cycles == 3


def test_smart_funnel_config_normalizes_pattern():
    from smart_funnel import SmartFunnelConfig

    cfg = SmartFunnelConfig(pattern="UNKNOWN")
    assert cfg.normalized_pattern() == "auto"
    cfg2 = SmartFunnelConfig(pattern="reward_survey_funnel", min_deals=3)
    assert cfg2.normalized_pattern() == "reward"
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


def test_survey_tcpa_and_instant_helpers():
    from smart_funnel import (
        _body_on_survey,
        _is_agree_continue_body,
        _survey_instant_enabled,
        _survey_labels_for_body,
    )

    tcpa = "have you been in a car accident? yes maybe later no call finish your survey"
    assert _body_on_survey(tcpa)
    assert not _is_agree_continue_body(tcpa + " i agree phone number email address")
    assert _is_agree_continue_body("i agree esign email address phone number continue")
    assert isinstance(_survey_instant_enabled(), bool)
    purchase = "when did you last make an online purchase? finish your survey"
    assert "Today" in _survey_labels_for_body(purchase)
    assert "Past 2 weeks" in _survey_labels_for_body(purchase)


def test_guess_phase_deals():
    from smart_funnel import _body_on_survey, _guess_phase

    assert _guess_phase("your cost: $1.00 complete 2 deals", "https://x.com") == "deals"
    assert _guess_phase("first name last name", "https://x.com") == "form"
    assert _guess_phase("how often do you shop", "https://survey.com") == "survey"
    assert _body_on_survey("have you been in a car accident in the past year? skip the survey")


def test_deals_required_for_wall():
    from smart_funnel import _deals_required_for_wall

    assert _deals_required_for_wall("level 1 deals") == 3
    assert _deals_required_for_wall("you must complete 1 deal to continue") == 3


def test_deal_wall_level_key():
    from smart_funnel import _deal_wall_level_key, _is_level3_wall, _is_level1_wall

    assert _deal_wall_level_key("level 1 deals best match") == "L1"
    assert _deal_wall_level_key("next step: complete 3 more deals") == "L3"
    assert _deal_wall_level_key("level 3 deals") == "L3"
    assert _deal_wall_level_key("must complete 1 deal to continue") == "L1"
    assert _is_level3_wall("NEXT STEP: Complete 3 More Deals to continue.")
    assert _is_level3_wall("Keep Going & Qualify For $100 Cashout!")
    assert not _is_level1_wall("complete 3 more deals level 3")


def test_body_on_offers_info():
    from smart_funnel import _body_on_offers_info, _body_on_survey, _guess_phase

    assert _body_on_offers_info("check out ways to claim other rewards complete 25 deals")
    assert not _body_on_offers_info("level 1 deals best match for you")
    assert not _body_on_survey(
        "finish your survey claim other rewards get a quick start towards target reward progress"
    )
    assert _guess_phase("", "https://www.retailproductsusa.com/x", "claim other rewards get a quick start") == "offers"


def test_count_offer_tabs_is_sync():
    import inspect

    from smart_funnel import _count_offer_tabs

    assert not inspect.iscoroutinefunction(_count_offer_tabs)
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


# ---------------------------------------------------------------------------
# v2.6.49 regression tests for reward-pattern bug fixes
# ---------------------------------------------------------------------------


def test_v2_6_49_stuck_deal_wall_dead_code_removed():
    """Bug #4: `stuck_deal_wall` variable removed from execute_smart_funnel."""
    import inspect

    from smart_funnel import execute_smart_funnel

    src = inspect.getsource(execute_smart_funnel)
    assert "stuck_deal_wall" not in src, (
        "stuck_deal_wall dead code should be removed"
    )


def test_v2_6_49_on_deal_wall_early_initialised_before_use():
    """Bug #9: `on_deal_wall_early` must be initialised before the loop reads it."""
    import inspect

    from smart_funnel import execute_smart_funnel

    src = inspect.getsource(execute_smart_funnel)
    init_pos = src.find("on_deal_wall_early = False")
    first_use_pos = src.find("and not on_deal_wall_early")
    assert init_pos != -1, "on_deal_wall_early not initialised"
    assert first_use_pos != -1
    assert init_pos < first_use_pos, (
        "on_deal_wall_early must be initialised before its first use"
    )


def test_v2_6_49_deal_flow_complete_not_hardcoded():
    """Bug #1: `deal_flow_complete` must not be hardcoded to literal True.

    Both conversion-return branches should reflect the actual
    ``_krx_l3_complete`` context flag.
    """
    import inspect

    from smart_funnel import execute_smart_funnel

    src = inspect.getsource(execute_smart_funnel)
    # No literal `"deal_flow_complete": True,` allowed in the return dicts
    assert '"deal_flow_complete": True' not in src, (
        "deal_flow_complete must be sourced from _krx_l3_complete, not hardcoded"
    )
    assert '"deal_flow_complete": bool(getattr(page.context, "_krx_l3_complete"' in src


def test_v2_6_49_survey_click_verifies_in_instant_mode():
    """Bug #2: instant mode must at least do a zero-wait fingerprint compare."""
    import inspect

    from smart_funnel import _survey_click_ok

    src = inspect.getsource(_survey_click_ok)
    # Old behaviour: bare `return True` when instant enabled — no verification
    assert "_survey_fingerprint" in src, (
        "_survey_click_ok must verify fingerprint even in instant mode"
    )


def test_v2_6_49_native_survey_burst_has_fallback_and_more_rounds():
    """Bug #3: instant burst should have >2 rounds and try labeled-choice fallback."""
    import inspect

    from smart_funnel import _native_survey_burst

    src = inspect.getsource(_native_survey_burst)
    # Old cap was `max_rounds = 2 if instant else ...`
    assert "max_rounds = 2 if instant" not in src, (
        "instant-mode burst cap must be >2 to allow retry strategies"
    )
    assert "_click_standard_survey_choice" in src, (
        "instant burst must fall back to labeled-choice click when fast click fails"
    )


def test_v2_6_49_reward_pattern_config_still_enforces_min_3():
    """Bug #7: backend still forces min-deals 3 for reward pattern."""
    from smart_funnel import rut_config_for_pattern

    cfg = rut_config_for_pattern("reward", min_deals=1, wait_until_conversion=True)
    assert cfg.min_deals == 3
    cfg2 = rut_config_for_pattern("reward", min_deals=4, wait_until_conversion=True)
    assert cfg2.min_deals == 4  # user-picked higher value must be respected


def test_v2_6_49_sms_optin_detects_reward_variant():
    """Bug #11: retailproductsusa reward-flow SMS variant must be detected.

    Screen text observed live: "Want to track your progress? Sign up for
    SMS alerts to keep you up to date on your Reward status and Deal
    credits." + "Get a Quick Start" button. Before fix, _body_on_sms_optin
    only matched "sign up for text messages" / "text me reward updates"
    so this variant was silently ignored and the outer retail handler
    treated "Get a Quick Start" as a plain CTA — opting the user INTO
    SMS collection and stalling the visit.
    """
    import asyncio

    from smart_funnel import _body_on_sms_optin

    variant = (
        "Want to track your progress? Sign up for SMS alerts to keep you "
        "up to date on your Reward status and Deal credits. Get a Quick Start"
    )
    assert asyncio.get_event_loop().run_until_complete(_body_on_sms_optin(variant)), (
        "reward-flow SMS opt-in variant must be detected"
    )
    # Backwards-compat: the original phrases must still match
    for legacy in (
        "Sign up for text messages",
        "text me reward updates",
        "We'll text you at",
        "explore offers from our sponsors",
    ):
        assert asyncio.new_event_loop().run_until_complete(_body_on_sms_optin(legacy)), (
            f"legacy SMS-optin phrase '{legacy}' regressed"
        )
    # Deal-wall page must NOT trip the SMS detector — it also mentions
    # "progress" but never in the SMS-opt-in sense.
    assert not asyncio.new_event_loop().run_until_complete(
        _body_on_sms_optin(
            "Level 1 deals — complete 3 more deals · Your progress: 0/3"
        )
    )


def test_v2_6_49_retail_scripts_guard_sms_optin():
    """Bug #11: RETAIL_REENTRY_SCRIPT + RETAIL_PROGRESS_SCRIPT must contain
    an inline SMS opt-in guard so JS-level fallback clicks never target
    "Get a Quick Start" when the modal is present."""
    from smart_funnel import RETAIL_PROGRESS_SCRIPT, RETAIL_REENTRY_SCRIPT

    for src in (RETAIL_REENTRY_SCRIPT, RETAIL_PROGRESS_SCRIPT):
        assert "sms" in src.lower() and "no thanks" in src.lower(), (
            "retail JS script missing SMS opt-in guard"
        )
        assert "track your progress" in src.lower(), (
            "retail JS script missing reward-variant SMS check"
        )
