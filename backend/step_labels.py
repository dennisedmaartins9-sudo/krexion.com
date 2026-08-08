"""Human-readable labels for Visual Recorder / RUT automation steps.

Used so step lists and live progress show what the step does
(e.g. "Click: No thanks", "Fill: {{email}}") instead of bare "click".
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _clip(s: str, n: int = 40) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[: max(1, n - 1)] + "…"


def _fallback_text(step: Dict[str, Any]) -> str:
    fb = step.get("fallbacks")
    if isinstance(fb, dict):
        t = (fb.get("text") or "").strip()
        if t:
            return t
    return ""


def _placeholder_name(value: Any) -> str:
    """{{email}} / {{first_name}} → email / first_name."""
    import re
    m = re.fullmatch(r"\s*\{\{\s*([^}]+?)\s*\}\}\s*", str(value or ""))
    if m:
        return m.group(1).strip()
    return ""


def friendly_step_label(step: Optional[Dict[str, Any]], *, max_len: int = 72) -> str:
    """Return a short operator-facing label for a step.

    Prefers an existing ``name`` when set. Otherwise builds from action +
    button text / field / wait target so VR lists and live job feeds stay
    readable even when the operator never renamed the step.
    """
    if not isinstance(step, dict):
        return "Step"
    existing = (step.get("name") or "").strip()
    if existing:
        return _clip(existing, max_len)

    action = (step.get("action") or "").strip().lower() or "step"
    text = (step.get("text") or step.get("hint_text") or "").strip() or _fallback_text(step)
    sel = (step.get("selector") or "").strip()
    val = step.get("value")
    ph = _placeholder_name(val)

    if action in ("click", "evaluate"):
        # evaluate often carries CTA text from recorder
        if text:
            return _clip(f"Click: {text}", max_len)
        if step.get("option_pick_text"):
            return _clip(f"Click: {step.get('option_pick_text')}", max_len)
        if sel:
            return _clip(f"Click {sel}", max_len)
        return "Click"

    if action in ("fill", "type"):
        field = ph or (step.get("header_name") or "").strip()
        if field:
            return _clip(f"Fill: {field}", max_len)
        if sel:
            # input[name='email'] → email
            import re
            m = re.search(r"""(?:name|id)=['\"]?([A-Za-z0-9_\-]+)""", sel)
            if m:
                return _clip(f"Fill: {m.group(1)}", max_len)
            return _clip(f"Fill {sel}", max_len)
        if val not in (None, ""):
            return _clip(f"Type → {val}", max_len)
        return "Fill"

    if action == "select":
        field = ph or (step.get("header_name") or "").strip()
        if field and val not in (None, ""):
            return _clip(f"Select {field} → {val}", max_len)
        if field:
            return _clip(f"Select: {field}", max_len)
        if val not in (None, ""):
            return _clip(f"Select → {val}", max_len)
        return "Select"

    if action == "check":
        return _clip(f"Check: {text or sel or 'box'}", max_len)
    if action == "uncheck":
        return _clip(f"Uncheck: {text or sel or 'box'}", max_len)

    if action == "wait":
        return f"Wait {int(step.get('ms') or 0)}ms"
    if action in ("wait_for_load", "wait_for_navigation", "wait_for_networkidle"):
        return "Wait for page load"
    if action == "wait_for_selector":
        return _clip(f"Wait for: {sel or 'selector'}", max_len)
    if action == "wait_for_text":
        return _clip(f"Wait for text: {step.get('text') or ''}", max_len)
    if action == "wait_for_url":
        return _clip(f"Wait for URL: {step.get('contains') or step.get('url') or ''}", max_len)

    if action == "press":
        return f"Press {step.get('key') or 'key'}"
    if action == "hover":
        return _clip(f"Hover: {text or sel or 'element'}", max_len)
    if action == "scroll":
        return "Scroll ↑" if (step.get("dir") or "").lower() == "up" else "Scroll ↓"
    if action == "screenshot":
        return _clip(f"Screenshot: {step.get('name') or 'capture'}", max_len)
    if action == "stage":
        return _clip(f"Stage: {step.get('name') or step.get('stage') or 'unnamed'}", max_len)
    if action == "stage_end":
        stage = step.get("stage") or step.get("name")
        return _clip(f"Stage End: {stage}" if stage else "Stage End", max_len)
    if action == "stage_markers":
        return "Stage markers ON" if step.get("enabled", True) else "Stage markers OFF"
    if action == "branch":
        n = len(step.get("branches") or []) if isinstance(step.get("branches"), list) else 0
        return f"If/Else ({n} paths)"
    if action in ("goto", "navigate"):
        return _clip(f"Go to {step.get('url') or step.get('value') or ''}", max_len)
    if action in ("close", "close_browser"):
        return "Close browser"
    if action == "dismiss_popups":
        return "Dismiss popups"
    if action in ("auto_continue", "auto_continue_survey"):
        return "Auto-Continue"

    # Generic fallback
    if text:
        return _clip(f"{action}: {text}", max_len)
    if sel:
        return _clip(f"{action} {sel}", max_len)
    return action.replace("_", " ").title()
