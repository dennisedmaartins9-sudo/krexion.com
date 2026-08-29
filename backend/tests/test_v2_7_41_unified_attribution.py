"""v2.7.41 — Unified attribution: clicks visibility, conversion bridge, pixel auth."""
from __future__ import annotations

import importlib


def test_completed_click_status_filter_includes_legacy():
    from click_scope import completed_click_status_filter
    filt = completed_click_status_filter()
    assert "$or" in filt
    branches = filt["$or"]
    assert {"click_status": "completed"} in branches
    assert {"click_status": {"$exists": False}} in branches


def test_record_conversion_duplicate():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    conv = importlib.import_module("conversion_module")

    main_db = MagicMock()
    main_db.conversions.find_one = AsyncMock(return_value={"id": "existing", "click_id": "abc"})
    client = MagicMock()

    result = asyncio.run(conv.record_conversion(main_db, client, "abc", 1.0))
    assert result.get("duplicate") is True


def test_build_wrapper_social_still_empty():
    rp = importlib.import_module("referrer_pro")
    dest = "https://offer.example.com/?x=1"
    for plat in ("tiktok", "facebook", "instagram"):
        assert rp.build_wrapper_bounce_url(plat, dest) == ""


def test_tracker_click_doc_has_completed_status():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("server.py").read_text(encoding="utf-8")
    assert '"click_status": "completed"' in src
