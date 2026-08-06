"""Unit tests for sheet-bound Option Pick / Gender Pick label resolution."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# real_user_traffic imports playwright at module load — stub it for unit tests.
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from real_user_traffic import (  # noqa: E402
    _normalize_gender_click_label,
    _resolve_sheet_option_pick_label,
)


def _gender_step(**extra):
    step = {
        "action": "evaluate",
        "origin": "gender_pick",
        "header_name": "gender",
        "gender_labels": {
            "male": ["Male", "M", "male", "m"],
            "female": ["Female", "F", "female", "f"],
        },
        "script": "var raw='{{gender}}'",
    }
    step.update(extra)
    return step


def test_normalize_mf_shorthands():
    assert _normalize_gender_click_label("M") == "Male"
    assert _normalize_gender_click_label("f") == "Female"
    assert _normalize_gender_click_label("male") == "Male"
    assert _normalize_gender_click_label("Woman") == "Female"


def test_sheet_m_clicks_male_button():
    assert _resolve_sheet_option_pick_label(_gender_step(), {"gender": "M"}) == "Male"
    assert _resolve_sheet_option_pick_label(_gender_step(), {"gender": "male"}) == "Male"


def test_sheet_f_clicks_female_button():
    assert _resolve_sheet_option_pick_label(_gender_step(), {"gender": "F"}) == "Female"
    assert _resolve_sheet_option_pick_label(_gender_step(), {"gender": "Female"}) == "Female"


def test_option_pick_labels_gender_aliases():
    step = {
        "action": "evaluate",
        "origin": "option_pick",
        "header_name": "gender",
        "option_labels": ["Male", "Female"],
        "script": "x",
    }
    assert _resolve_sheet_option_pick_label(step, {"gender": "m"}) == "Male"
    assert _resolve_sheet_option_pick_label(step, {"gender": "f"}) == "Female"


def test_blank_gender_returns_none():
    assert _resolve_sheet_option_pick_label(_gender_step(), {"gender": ""}) is None
    assert _resolve_sheet_option_pick_label(_gender_step(), {}) is None


def test_non_pick_step_returns_none():
    assert _resolve_sheet_option_pick_label({"action": "evaluate", "script": "1+1"}, {"gender": "M"}) is None
