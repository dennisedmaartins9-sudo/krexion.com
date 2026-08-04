"""Visual Recorder sheet_pick — template evaluate + gender normalisation."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from visual_recorder import (  # noqa: E402
    _build_sheet_pick_evaluate,
    _build_option_pick_evaluate,
    _is_gender_header,
    _normalize_gender_click_label,
)


def test_build_sheet_pick_uses_template_not_literal():
    step = _build_sheet_pick_evaluate("gender")
    assert step["action"] == "evaluate"
    assert step["origin"] == "sheet_pick"
    assert step["header_name"] == "gender"
    assert "var raw='{{gender}}'" in step["script"]
    assert "var t='Male'" not in step["script"]
    assert "var t='Female'" not in step["script"]
    # No CSS selector priority block
    assert "document.querySelector" not in step["script"] or "querySelectorAll" in step["script"]


def test_sheet_pick_script_normalises_m_f():
    step = _build_sheet_pick_evaluate("gender")
    script = step["script"]
    assert "raw==='m'" in script
    assert "raw==='f'" in script


def test_is_gender_header():
    assert _is_gender_header("gender")
    assert _is_gender_header("sex")
    assert _is_gender_header("Gender")
    assert not _is_gender_header("first")


def test_normalize_gender_click_label():
    assert _normalize_gender_click_label("M") == "Male"
    assert _normalize_gender_click_label("f") == "Female"
    assert _normalize_gender_click_label("Continue") == "Continue"


def test_build_option_pick_requires_two_labels():
    import pytest
    with pytest.raises(ValueError):
        _build_option_pick_evaluate("choice", ["Yes"])


def test_build_option_pick_uses_template_and_labels():
    step = _build_option_pick_evaluate("gender", ["Male", "Female"])
    assert step["action"] == "evaluate"
    assert step["origin"] == "option_pick"
    assert step["header_name"] == "gender"
    assert step["option_labels"] == ["Male", "Female"]
    assert "var raw='{{gender}}'" in step["script"]
    assert "'Male'" in step["script"]
    assert "'Female'" in step["script"]
