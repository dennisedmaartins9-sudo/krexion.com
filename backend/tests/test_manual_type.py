"""Visual Recorder Fix Type — manual_type_at does not append steps."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from visual_recorder import manual_type_at, RecorderSession  # noqa: E402


def test_manual_type_rejects_empty_value():
    sess = RecorderSession(session_id="t", user_id="u", url="https://example.com")
    out = asyncio.run(manual_type_at(sess, 10, 10, ""))
    assert out["typed"] is False
    assert out["recorded"] is False
    assert out.get("error")
