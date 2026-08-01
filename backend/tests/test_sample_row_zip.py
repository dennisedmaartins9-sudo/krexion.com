"""Sample row zip/postal normalisation during Visual Recorder recording."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from visual_recorder import (  # noqa: E402
    RecorderSession,
    _format_sample_cell_value,
    _resolve_live_value,
)


def test_format_zip_from_excel_float():
    assert _format_sample_cell_value("zip_code", 92335.0) == "92335"


def test_format_zip_from_numeric_string():
    assert _format_sample_cell_value("zip", "92335") == "92335"


def test_resolve_zip_code_synonym():
    sess = RecorderSession(session_id="t", user_id="u", url="https://example.com")
    sess.sample_row = {"zip_code": 92335}
    assert _resolve_live_value(sess, "zip") == "92335"
    assert _resolve_live_value(sess, "zip_code") == "92335"
