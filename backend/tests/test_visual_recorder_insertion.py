"""Focused insertion-cursor and stage-boundary recorder tests."""
import pytest

import visual_recorder as vr


def _session(**kwargs):
    return vr.RecorderSession(
        session_id="test-session",
        user_id="test-user",
        url="https://example.test",
        **kwargs,
    )


def test_default_append_and_cursor_insert_advance_in_order():
    sess = _session()
    sess.append_step({"action": "wait", "ms": 100})
    sess.append_step({"action": "wait", "ms": 400})
    assert [s["ms"] for s in sess.steps] == [100, 400]

    sess.set_insertion_position(1)
    sess.append_step({"action": "wait", "ms": 200})
    sess.append_step({"action": "wait", "ms": 300})

    assert [s["ms"] for s in sess.steps] == [100, 200, 300, 400]
    assert sess.insertion_position == 3


def test_compound_auto_steps_preserve_order_and_advance(monkeypatch):
    monkeypatch.setattr(
        vr,
        "_auto_waits_after_action",
        lambda _action: [
            {"action": "wait", "ms": 10},
            {"action": "wait_for_load", "timeout": 20},
        ],
    )
    sess = _session(auto_insert_waits=True)
    sess.steps = [{"action": "wait", "ms": 1}, {"action": "wait", "ms": 99}]
    sess.set_insertion_position(1)

    sess.append_step({"action": "click", "selector": "#go"})

    assert [s["action"] for s in sess.steps] == [
        "wait", "click", "wait", "wait_for_load", "wait"
    ]
    assert sess.insertion_position == 4


def test_cursor_bounds_clear_and_explicit_manual_position_compatibility():
    sess = _session()
    sess.steps = [{"action": "wait", "ms": 1}]

    assert sess.set_insertion_position(0) == 0
    assert sess.set_insertion_position(1) == 1
    with pytest.raises(ValueError):
        sess.set_insertion_position(2)
    with pytest.raises(ValueError):
        sess.set_insertion_position(-1)

    result = vr.add_manual_step(
        sess, {"action": "wait", "ms": 2}, position=0
    )
    assert result["index"] == 0
    assert [s["ms"] for s in sess.steps] == [2, 1]
    assert sess.insertion_position == 2

    sess.clear_insertion_position()
    assert sess.insertion_position is None


def test_import_clears_cursor_and_preserves_stage_boundaries():
    sess = _session()
    sess.set_insertion_position(0)
    steps = [
        {"action": "stage", "name": "Form", "stage": "Form"},
        {"action": "click", "selector": "#submit"},
        {"action": "stage_end", "stage": "Form"},
    ]

    result = vr.import_steps(sess, steps)

    assert result["insertion_position"] is None
    assert sess.insertion_position is None
    assert sess.steps == steps


def test_stage_start_end_serialization_and_current_stage_reset():
    sess = _session(stage_markers_enabled=True)
    sess.set_insertion_position(0)

    start = vr.add_manual_step(
        sess, {"action": "stage", "name": "Survey", "stage": "Survey"}
    )
    end = vr.add_manual_step(sess, {"action": "stage_end"})

    assert start["step"]["action"] == "stage"
    assert end["step"]["action"] == "stage_end"
    assert end["step"]["stage"] == "Survey"
    assert [s["action"] for s in sess.steps] == ["stage", "stage_end"]
    assert sess.current_stage == ""
    assert sess.insertion_position == 2
