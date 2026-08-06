"""Early lead consume: form submit / next page — not conversion wait."""
from __future__ import annotations


def test_post_form_stage_name_hints():
    hints = (
        "survey", "post-form", "post_form", "postform", "thank",
        "deal", "conversion", "offers", "cidmain",
    )

    def implies(name: str) -> bool:
        n = (name or "").strip().lower()
        return any(h in n for h in hints)

    assert implies("Stage: survey (detect post-form / #Qnum1)")
    assert implies("deal complete")
    assert implies("Stage: thank you")
    assert not implies("Stage: questions (always run)")
    assert not implies("Stage: big form (detect #fn)")


def test_pii_bind_tokens():
    tokens = (
        "email", "first", "last", "address", "city", "state",
        "zip", "zip_code", "cellphone", "phone", "mobile", "gender",
    )

    def is_pii(raw) -> bool:
        s = str(raw or "").lower()
        if "{{" not in s:
            return False
        return any(tok in s for tok in tokens)

    assert is_pii("{{email}}")
    assert is_pii("{{zip_code}}")
    assert is_pii("Hello {{first}}")
    assert not is_pii("Continue")
    assert not is_pii("#email")  # selector alone without {{}}
