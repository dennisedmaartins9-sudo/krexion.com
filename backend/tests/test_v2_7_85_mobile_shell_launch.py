"""v2.7.85 — Mobile shell sync start + DPI-aware engine window sizing."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_apply_mobile_shell_starts_subprocess_before_thread():
    import krexion_mobile_browser_shell as shell

    started = {"proc": False, "thread": False}

    def _fake_start(*_a, **_k):
        started["proc"] = True
        proc = MagicMock()
        proc.poll.return_value = None
        return proc

    def _fake_loop(*_a, **_k):
        started["thread"] = True

    with patch.object(shell, "_IS_WINDOWS", True), patch.object(
        shell, "_start_shell_process", side_effect=_fake_start
    ), patch.object(
        shell, "_shell_apply_loop", side_effect=_fake_loop
    ), patch.object(shell, "_center_origin", return_value=(100, 80)):
        t = shell.apply_krexion_mobile_shell(
            [1234],
            session_key="sess1",
            parent_pid=1234,
            platform="android",
            viewport_width=393,
            viewport_height=852,
        )
        time.sleep(0.05)
    assert started["proc"] is True
    assert started["thread"] is True
    assert t is not None


def test_wait_for_mobile_shell_eventually_true():
    import krexion_mobile_browser_shell as shell

    calls = {"n": 0}

    def _alive(_key):
        calls["n"] += 1
        return calls["n"] >= 3

    with patch.object(shell, "is_mobile_shell_alive", side_effect=_alive):
        assert shell.wait_for_mobile_shell("sess", timeout_sec=2.0) is True


def test_launcher_uses_wait_for_mobile_shell():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "wait_for_mobile_shell" in src
    assert (
        "timeout_sec=15.0" in src
        or "timeout_sec=30.0" in src
        or "timeout_sec=12.0" in src
        or "timeout_sec=18.0" in src
    )
    assert "is_mobile_shell_alive" in src
    assert "wait_for_mobile_shell_embedded" in src