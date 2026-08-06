"""Tests for friendly step labels (VR / RUT readability)."""
from step_labels import friendly_step_label


def test_click_uses_button_text():
    assert "No thanks" in friendly_step_label({
        "action": "click", "text": "No thanks", "selector": "button.x",
    })


def test_fill_uses_placeholder_or_name():
    assert "email" in friendly_step_label({
        "action": "fill", "value": "{{email}}", "selector": "input",
    }).lower()
    assert "first" in friendly_step_label({
        "action": "fill", "selector": "input[name='first_name']",
    }).lower()


def test_wait_and_stage():
    assert "2000" in friendly_step_label({"action": "wait", "ms": 2000})
    assert "Form fill" in friendly_step_label({
        "action": "stage", "name": "Form fill",
    })


def test_existing_name_wins():
    assert friendly_step_label({
        "action": "click", "name": "My CTA", "text": "Continue",
    }) == "My CTA"
