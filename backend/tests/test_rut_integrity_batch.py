import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# These tests exercise pure/accounting helpers and do not launch Chromium.
# Keep collection runnable on lightweight CI/dev Python installations.
if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

import real_user_traffic as rut
from referrer_pro import resolve_pro_visit


class _Collection:
    def __init__(self):
        self.docs = []
        self.updates = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, query, update, **kwargs):
        self.updates.append((query, update))
        matched = 0
        for doc in self.docs:
            ids = {doc.get("id"), doc.get("click_id")}
            wanted = query.get("id") or query.get("click_id")
            if "$or" in query:
                wanted = next(iter(
                    (part.get("id") or part.get("click_id"))
                    for part in query["$or"]
                ))
            expected_status = query.get("click_status")
            if wanted in ids and (
                expected_status is None or doc.get("click_status") == expected_status
            ):
                doc.update(update.get("$set", {}))
                matched = 1
                break
        return SimpleNamespace(matched_count=matched)

    async def delete_one(self, query):
        self.docs = [doc for doc in self.docs if doc.get("id") != query.get("id")]
        return SimpleNamespace(deleted_count=1)


class _Client:
    def __init__(self):
        self.dbs = {}

    def __getitem__(self, name):
        return self.dbs.setdefault(name, SimpleNamespace(clicks=_Collection()))


def _db():
    return SimpleNamespace(client=_Client(), links=_Collection())


def _entry(status="pending"):
    return {
        "visit_index": 7,
        "status": status,
        "exit_ip": "198.51.100.7",
        "ua": "Mozilla/5.0 Chrome/144",
        "os": "Windows",
        "final_url": "https://offer.example/landing?clickid=trk-123",
        "conversion_page_reached": False,
        "timestamp": "2026-08-08T00:00:00+00:00",
    }


def _job():
    return {
        "job_id": "job-1",
        "link_id": "link-1",
        "link_owner_id": "owner-1",
        "link_short_code": "abc",
    }


def test_resolved_click_id_parser_is_safe_and_canonical():
    assert rut._click_id_from_resolved_url(
        "https://offer.example/path?foo=1&clickid=trk-123"
    ) == "trk-123"
    assert rut._click_id_from_resolved_url("not a URL?clickid=bad") == ""
    assert rut._click_id_from_resolved_url("javascript:alert(1)?clickid=bad") == ""


def test_network_chain_cannot_replace_selected_referer():
    extras = rut._with_traffic_type_extras(
        {"network_click_chain": True},
        "facebook",
        {"network_click_referer": "https://sig.click.example/"},
        referer_url="https://www.facebook.com/post/1",
    )
    assert extras["network_click_referer"] == ""


def test_retired_network_chain_cannot_be_reenabled_in_resolver():
    result = resolve_pro_visit(
        ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0",
        platform_pool_value='{"google": 100}',
        network_click_chain_enabled=True,
        network_click_host="track.example.test",
    )
    assert result["network_click_referer"] == ""


def test_pending_click_uses_one_id_and_counts_only_after_success():
    db = _db()
    entry = _entry()
    entry["_tracker_click_id"] = "trk-123"

    asyncio.run(rut._log_click_for_link(entry, _job(), db, early=True))
    user_db = db.client["krexion_user_owner_1"]
    assert len(user_db.clicks.docs) == 1
    click = user_db.clicks.docs[0]
    assert click["id"] == click["click_id"] == "trk-123"
    assert click["job_id"] == "job-1"
    assert click["visit_id"] == "7"
    assert click["visit_status"] == click["click_status"] == "pending"
    assert db.links.updates == []

    entry["status"] = "ok"
    asyncio.run(rut._log_click_for_link(entry, _job(), db, early=False))
    assert click["id"] == click["click_id"] == "trk-123"
    assert click["visit_status"] == "ok"
    assert click["click_status"] == "completed"
    assert db.links.updates[-1][1]["$inc"]["clicks"] == 1
    asyncio.run(rut._log_click_for_link(entry, _job(), db, early=False))
    assert len(db.links.updates) == 1


def test_failed_pending_click_remains_failed_without_aggregate_increment():
    db = _db()
    entry = _entry()
    asyncio.run(rut._log_click_for_link(entry, _job(), db, early=True))
    entry["status"] = "failed"
    asyncio.run(rut._log_click_for_link(entry, _job(), db, early=False))

    click = db.client["krexion_user_owner_1"].clicks.docs[0]
    assert click["visit_status"] == "failed"
    assert click["click_status"] == "failed"
    assert db.links.updates == []


def test_silent_skip_deletes_pending_row_without_negative_link_count():
    db = _db()
    entry = _entry()
    job = {
        **_job(),
        "silent_skip_burnt_ip": True,
        "processed": 0,
        "skipped": 0,
    }
    rut.RUT_JOBS["job-1"] = job
    try:
        asyncio.run(rut._log_click_for_link(entry, job, db, early=True))
        entry["status"] = "skipped_duplicate_ip"
        asyncio.run(rut._record("job-1", entry, [], asyncio.Lock(), db))
        assert db.client["krexion_user_owner_1"].clicks.docs == []
        assert db.links.updates == []
        assert rut.RUT_JOBS["job-1"]["skipped"] == 1
    finally:
        rut.RUT_JOBS.pop("job-1", None)


def test_live_step_cursor_is_monotonic_after_ring_trim():
    job_id = "cursor-job"
    rut.RUT_JOBS[job_id] = {"status": "running"}
    try:
        for n in range(rut._MAX_LIVE_STEPS + 5):
            rut.push_live_step(job_id, 1, "step", "info", str(n))
        result = rut.get_live_steps(job_id, since=rut._MAX_LIVE_STEPS)
        assert [step["idx"] for step in result["steps"]] == [301, 302, 303, 304, 305]
        assert result["cursor"] == 305
    finally:
        rut.RUT_JOBS.pop(job_id, None)


def test_attempt_lifecycle_tracks_started_in_flight_and_cancelled():
    job = {"attempts_started": 2, "in_flight": 0, "cancelled": 0}
    rut._mark_attempt_started(job)
    assert job["attempts_started"] == 3
    assert job["in_flight"] == 1
    rut._mark_attempt_terminal(job, cancelled=True)
    assert job["in_flight"] == 0
    assert job["cancelled"] == 1


def test_terminal_status_requires_requested_success_target():
    assert rut._canonical_terminal_status(
        {"succeeded": 1}, target_mode="clicks", requested_total=2,
        target_conversions=0,
    ) == "partial"
    assert rut._canonical_terminal_status(
        {"succeeded": 2}, target_mode="clicks", requested_total=2,
        target_conversions=0,
    ) == "completed"
    assert rut._canonical_terminal_status(
        {"conversions": 0, "attempts_started": 5, "max_attempts": 5},
        target_mode="conversions", requested_total=5, target_conversions=1,
    ) == "exhausted"
