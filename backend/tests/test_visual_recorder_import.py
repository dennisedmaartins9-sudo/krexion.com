"""Regression: visual_recorder must import (RecorderSession dataclass field order)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_visual_recorder_imports():
    import visual_recorder as vr

    assert vr.SESSIONS_ROOT is not None
    assert hasattr(vr, "RecorderSession")
