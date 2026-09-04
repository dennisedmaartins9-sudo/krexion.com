"""v2.6.87 — tracker probe skip must define _t_host (offer never opened)."""
from pathlib import Path

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def test_t_host_defined_before_tracker_probe_skip():
    src = RUT.read_text(encoding="utf-8")
    assert "_t_host = _claim_host" in src
    # Message evolved: still must skip pre-flight probe for tracker targets
    assert (
        "Tracker target detected ({_t_host})" in src
        or "Single-click mode — skipping pre-flight reachability probe" in src
    )
    assert "FIX: for tracker targets, SKIP the reachability probe" in src or (
        "_is_tracker_target" in src and "skipping pre-flight" in src.lower()
    )
    assert src.index("_t_host = _claim_host") < src.index(
        "skipping pre-flight reachability probe"
    )


def test_visit_crash_is_logged_to_live_activity():
    src = RUT.read_text(encoding="utf-8")
    assert "Visit crashed before offer open:" in src
    assert "except Exception as _visit_crash:" in src
