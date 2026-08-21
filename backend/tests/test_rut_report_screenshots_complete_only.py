"""Report ZIP screenshots — complete visits only (Live Activity/Grid unchanged)."""
from __future__ import annotations

from pathlib import Path

from real_user_traffic import (
    _purge_incomplete_report_screenshots,
    _report_visit_is_complete,
    _shots_matching_visit_indexes,
)


def test_report_visit_is_complete_ok_status():
    assert _report_visit_is_complete({"status": "ok", "visit_index": 1}) is True
    assert _report_visit_is_complete({"status": "OK", "visit_index": 1}) is True


def test_report_visit_is_complete_conversion_flags():
    assert _report_visit_is_complete(
        {"status": "failed", "conversion_page_reached": True, "visit_index": 2}
    ) is True
    assert _report_visit_is_complete(
        {"status": "failed", "thank_you_reached": True, "visit_index": 3}
    ) is True


def test_report_visit_is_complete_rejects_incomplete():
    assert _report_visit_is_complete({"status": "failed", "visit_index": 1}) is False
    assert _report_visit_is_complete({"status": "skipped_captcha", "visit_index": 1}) is False
    assert _report_visit_is_complete({"status": "pending", "visit_index": 1}) is False
    assert _report_visit_is_complete(None) is False
    assert _report_visit_is_complete({}) is False


def test_shots_matching_and_purge(tmp_path: Path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    (shots / "visit_00001_landing.png").write_bytes(b"ok1")
    (shots / "visit_00001_thankyou.png").write_bytes(b"ok1b")
    (shots / "visit_00002_landing.jpg").write_bytes(b"fail2")
    (shots / "visit_00002_final.png").write_bytes(b"fail2b")
    (shots / "visit_00003_post_submit.png").write_bytes(b"ok3")
    (shots / "other.png").write_bytes(b"ignore")

    report = [
        {"visit_index": 1, "status": "ok"},
        {"visit_index": 2, "status": "failed"},
        {"visit_index": 3, "status": "failed", "conversion_page_reached": True},
    ]
    complete_idxs = {
        int(e["visit_index"]) for e in report if _report_visit_is_complete(e)
    }
    assert complete_idxs == {1, 3}
    kept = {p.name for p in _shots_matching_visit_indexes(shots, complete_idxs)}
    assert kept == {
        "visit_00001_landing.png",
        "visit_00001_thankyou.png",
        "visit_00003_post_submit.png",
    }

    removed = _purge_incomplete_report_screenshots(shots, report)
    assert removed == 2
    remaining = {p.name for p in shots.iterdir()}
    assert remaining == {
        "visit_00001_landing.png",
        "visit_00001_thankyou.png",
        "visit_00003_post_submit.png",
        "other.png",
    }
