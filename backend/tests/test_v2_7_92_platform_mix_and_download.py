"""v2.7.92 — platform mix desktop=0 + license-gated download helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_split_mix_zero_desktop_never_allocates_desktop():
    from browser_profile_module import _split_mix_counts

    plan = _split_mix_counts(5, 50, 50, 0)
    assert plan is not None
    counts = dict(plan)
    assert counts.get("desktop", 0) == 0
    assert counts.get("ios", 0) + counts.get("android", 0) == 5


def test_split_mix_all_mobile_rounding():
    from browser_profile_module import _split_mix_counts

    plan = _split_mix_counts(3, 50, 50, 0)
    counts = dict(plan)
    assert counts.get("desktop", 0) == 0
    assert sum(counts.values()) == 3
