"""Stage marker skip-block behavior (v2.6.66 prep) — unit-level helpers."""
import pytest


def _simulate_stage_skips(steps, *, gate_on=True, open_results=None):
    """Pure simulation of stage gate: open_results maps stage-name -> bool."""
    open_results = open_results or {}
    out = []
    skip = False
    for i, step in enumerate(steps):
        action = (step.get("action") or "").strip().lower()
        if action == "stage_markers":
            gate_on = bool(step.get("enabled", True))
            skip = False
            out.append((i, "control", False))
            continue
        if gate_on and skip and action not in ("stage", "stage_markers"):
            out.append((i, "skipped", True))
            continue
        if action == "stage":
            if not gate_on:
                skip = False
                out.append((i, "stage_ignored", False))
                continue
            name = step.get("name") or step.get("stage") or f"s{i}"
            ow = step.get("open_when")
            if not ow:
                skip = False
                out.append((i, "stage_open", False))
            else:
                opened = bool(open_results.get(name, False))
                skip = (not opened) and bool(step.get("skip_if_not_open", True))
                out.append((i, "stage_open" if opened else "stage_closed", skip))
            continue
        out.append((i, "run", False))
    return out


def test_form_stage_skipped_instantly_when_not_open():
    steps = [
        {"action": "stage_markers", "enabled": True},
        {"action": "stage", "name": "Email"},
        {"action": "fill", "selector": "#email"},
        {"action": "stage", "name": "Form fill", "open_when": {"type": "selector_visible", "selector": "#first"}, "skip_if_not_open": True},
        {"action": "fill", "selector": "#first"},
        {"action": "fill", "selector": "#last"},
        {"action": "click", "selector": "#submit"},
        {"action": "stage", "name": "Survey"},
        {"action": "click", "selector": ".q1"},
    ]
    sim = _simulate_stage_skips(steps, open_results={"Form fill": False})
    # Email fill runs; three form steps skipped; survey click runs
    by_i = {i: (kind, sk) for i, kind, sk in sim}
    assert by_i[2] == ("run", False)
    assert by_i[4][1] is True and by_i[5][1] is True and by_i[6][1] is True
    assert by_i[8] == ("run", False)


def test_form_stage_runs_when_open():
    steps = [
        {"action": "stage", "name": "Form fill", "open_when": {"selector": "#first"}, "skip_if_not_open": True},
        {"action": "fill", "selector": "#first"},
        {"action": "fill", "selector": "#last"},
    ]
    sim = _simulate_stage_skips(steps, open_results={"Form fill": True})
    assert all(not sk for _, _, sk in sim)


def test_stage_markers_off_ignores_gates():
    steps = [
        {"action": "stage_markers", "enabled": False},
        {"action": "stage", "name": "Form fill", "open_when": {"selector": "#first"}, "skip_if_not_open": True},
        {"action": "fill", "selector": "#first"},
    ]
    sim = _simulate_stage_skips(steps, open_results={"Form fill": False})
    assert sim[2] == (2, "run", False)
