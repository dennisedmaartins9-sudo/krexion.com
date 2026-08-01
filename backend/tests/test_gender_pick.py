"""Visual Recorder gender_pick — Male+Female pool + sheet column."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from visual_recorder import (  # noqa: E402
    _build_gender_pick_evaluate,
    _classify_gender_side,
    _split_gender_button_labels,
)


def test_split_gender_labels():
    male, female = _split_gender_button_labels(["Male", "Female"])
    assert male == ["Male"]
    assert female == ["Female"]


def test_split_gender_shorthand():
    male, female = _split_gender_button_labels(["M", "F"])
    assert "M" in male
    assert "F" in female


def test_build_gender_pick_template_and_labels():
    step = _build_gender_pick_evaluate("gender", ["Male"], ["Female"])
    assert step["origin"] == "gender_pick"
    assert step["header_name"] == "gender"
    assert "var raw='{{gender}}'" in step["script"]
    assert "'Male'" in step["script"]
    assert "'Female'" in step["script"]
    assert step["gender_labels"]["male"] == ["Male"]
    assert step["gender_labels"]["female"] == ["Female"]


def test_classify_gender_side():
    assert _classify_gender_side("M") == "male"
    assert _classify_gender_side("female") == "female"
    assert _classify_gender_side("Continue") is None
