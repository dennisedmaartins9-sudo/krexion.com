"""Behavior tests for exact-offer team IP isolation."""
from __future__ import annotations

import asyncio
import functools
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError

from cross_user_ip_isolation import (
    acquire_team_offer_ip_claim,
    canonical_offer_identity,
    canonicalize_ip,
    complete_team_offer_ip_claim,
    invalidate_group_cache,
    list_team_shared_used_ips,
    release_team_offer_ip_claim,
    resolve_isolation_scope,
    team_offer_claim_required,
)


@pytest.fixture(autouse=True)
def _clear_isolation_caches():
    invalidate_group_cache()
    yield
    invalidate_group_cache()


def _async_test(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper


class _Result:
    def __init__(self, modified=0, deleted=0):
        self.modified_count = modified
        self.deleted_count = deleted


def _matches(doc, query):
    for key, wanted in query.items():
        actual = doc.get(key)
        if isinstance(wanted, dict) and "$in" in wanted:
            choices = wanted["$in"]
            if isinstance(actual, list):
                if not any(item in choices for item in actual):
                    return False
            elif actual not in choices:
                return False
        elif isinstance(actual, list):
            if wanted not in actual:
                return False
        elif actual != wanted:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, limit):
        return [dict(doc) for doc in self.docs[:limit]]

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return dict(next(self._iter))
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Collection:
    def __init__(self, docs=None, unique_claim=False):
        self.docs = list(docs or [])
        self.unique_claim = unique_claim
        self.lock = asyncio.Lock()
        self.insert_error = None

    def find(self, query, projection=None):
        return _Cursor([doc for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query, projection=None):
        for doc in self.docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc):
        if self.insert_error:
            raise self.insert_error
        async with self.lock:
            if self.unique_claim:
                key = (doc["scope_key"], doc["offer_key"], doc["ip"])
                if any((row["scope_key"], row["offer_key"], row["ip"]) == key for row in self.docs):
                    raise DuplicateKeyError("duplicate")
            self.docs.append(dict(doc))

    async def update_one(self, query, update):
        for doc in self.docs:
            if _matches(doc, query):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    doc.pop(key, None)
                return _Result(modified=1)
        return _Result()

    async def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs.pop(index)
                return _Result(deleted=1)
        return _Result()


class _DB:
    def __init__(self):
        self.groups = _Collection([{
            "id": "stable-group-id", "enabled": True, "user_ids": ["office01", "office02"]
        }])
        self.users = _Collection([
            {"id": "office01", "vps_ip_db_enabled": True},
            {"id": "office02", "vps_ip_db_enabled": True},
        ])
        self.claims = _Collection(unique_claim=True)
        self.rut_burnt_offer_ips = _Collection()

    def __getitem__(self, name):
        if name == "cross_user_ip_groups":
            return self.groups
        if name == "team_offer_ip_claims":
            return self.claims
        if name == "rut_burnt_offer_ips":
            return self.rut_burnt_offer_ips
        raise KeyError(name)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.8", "203.0.113.8"),
        ("::ffff:203.0.113.8", "203.0.113.8"),
        ("2001:0db8::1", "2001:db8::1"),
        ("unknown", None),
        ("not-an-ip", None),
    ],
)
def test_ip_normalization(raw, expected):
    assert canonicalize_ip(raw) == expected


def test_offer_url_normalization_preserves_business_query():
    left = canonical_offer_identity(
        "HTTPS://Example.COM:443/deal/?b=2&a=1&clickid=abc&_kx_visit_token=x#frag"
    )
    right = canonical_offer_identity("https://example.com/deal?a=1&b=2")
    assert left == right
    assert canonical_offer_identity("https://example.com/deal?campaign=A")[1] != right[1]


def test_shared_scope_cannot_opt_out_but_solo_scope_can():
    assert team_offer_claim_required({"shared": True}, False)
    assert not team_offer_claim_required({"shared": False}, False)


@_async_test
@pytest.mark.parametrize(("first", "second"), [("office01", "office02"), ("office02", "office01")])
async def test_two_links_same_offer_conflict_both_orders(first, second):
    db = _DB()
    one = await acquire_team_offer_ip_claim(
        db, first, "https://offer.example/path?b=2&a=1", "203.0.113.8", "visit-one"
    )
    two = await acquire_team_offer_ip_claim(
        db, second, "HTTPS://OFFER.EXAMPLE:443/path/?a=1&b=2&click_id=x",
        "::ffff:203.0.113.8", "visit-two",
    )
    assert one["status"] == "acquired"
    assert two["status"] == "conflict"


@_async_test
async def test_same_second_concurrency_exactly_one_acquired():
    db = _DB()
    results = await asyncio.gather(*[
        acquire_team_offer_ip_claim(
            db, user, "https://offer.example/", "198.51.100.5", f"token-{user}"
        )
        for user in ("office01", "office02")
    ])
    assert sum(result["status"] == "acquired" for result in results) == 1
    assert sum(result["status"] == "conflict" for result in results) == 1


@_async_test
async def test_different_offer_allowed_release_complete_and_idempotency():
    db = _DB()
    first = await acquire_team_offer_ip_claim(
        db, "office01", "https://offer.example/a", "198.51.100.9", "same-visit"
    )
    retry = await acquire_team_offer_ip_claim(
        db, "office02", "https://offer.example/a/", "198.51.100.9", "same-visit"
    )
    other = await acquire_team_offer_ip_claim(
        db, "office02", "https://offer.example/b", "198.51.100.9", "other-visit"
    )
    assert first["status"] == "acquired"
    assert retry["status"] == "idempotent"  # tracker + direct RUT acquire
    assert other["status"] == "acquired"

    assert await release_team_offer_ip_claim(
        db, "office01", "https://offer.example/a", "198.51.100.9", "same-visit"
    )
    teammate_retry = await acquire_team_offer_ip_claim(
        db, "office02", "https://offer.example/a", "198.51.100.9", "replacement"
    )
    assert teammate_retry["status"] == "acquired"
    assert await complete_team_offer_ip_claim(
        db, "office02", "https://offer.example/a", "198.51.100.9", "replacement"
    )
    assert not await release_team_offer_ip_claim(
        db, "office02", "https://offer.example/a", "198.51.100.9", "replacement"
    )
    blocked = await acquire_team_offer_ip_claim(
        db, "office01", "https://offer.example/a", "198.51.100.9", "later"
    )
    assert blocked["status"] == "conflict"


@_async_test
async def test_membership_change_keeps_stable_group_scope_id():
    db = _DB()
    invalidate_group_cache()
    before = await resolve_isolation_scope(db, "office01")
    db.groups.docs[0]["user_ids"].append("office03")
    db.users.docs.append({"id": "office03", "vps_ip_db_enabled": True})
    invalidate_group_cache()
    after = await resolve_isolation_scope(db, "office01")
    assert before["scope_key"] == after["scope_key"] == "group:stable-group-id"
    assert "office03" in after["member_ids"]


@_async_test
async def test_list_team_shared_used_ips_merges_claims_and_burnt():
    invalidate_group_cache()
    db = _DB()
    await acquire_team_offer_ip_claim(
        db, "office01", "https://offer.example/x", "203.0.113.10", "v1"
    )
    db.rut_burnt_offer_ips.docs.append({
        "ip": "203.0.113.11",
        "user_id": "office02",
        "offer_scope_key": canonical_offer_identity("https://offer.example/x")[1],
    })
    used = await list_team_shared_used_ips(db, "office01", "https://offer.example/x")
    assert "203.0.113.10" in used
    assert "203.0.113.11" in used


@_async_test
async def test_historical_teammate_click_blocks_even_without_claim_row():
    """Isolation purpose: one used IP is dead for the whole team."""
    invalidate_group_cache()
    db = _DB()
    offer = "https://offer.example/hist"
    offer_key = canonical_offer_identity(offer)[1]
    class _Clicks:
        async def find_one(self, query, projection=None):
            blob = str(query)
            if "198.51.100.77" in blob and offer_key in blob:
                return {"ip_address": "198.51.100.77", "offer_scope_key": offer_key}
            return None

    class _UserDB:
        def __init__(self, clicks):
            self.clicks = clicks

    def get_user_db(uid):
        if uid == "office01":
            return _UserDB(_Clicks())
        return _UserDB(_Collection())

    blocked = await acquire_team_offer_ip_claim(
        db, "office02", offer, "198.51.100.77", "later-visit",
        get_user_db=get_user_db,
    )
    assert blocked["status"] == "conflict"
    assert blocked["acquired"] is False

    allowed = await acquire_team_offer_ip_claim(
        db, "office02", offer, "198.51.100.78", "fresh-visit",
        get_user_db=get_user_db,
    )
    assert allowed["acquired"] is True


@_async_test
async def test_claim_store_error_raises_for_fail_closed_caller():
    db = _DB()
    db.claims.insert_error = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await acquire_team_offer_ip_claim(
            db, "office01", "https://offer.example/a", "203.0.113.1", "visit"
        )


def test_rut_job_params_persist_target_and_offer_contract():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert '"target_url": target' in source
    assert '"offer_scope_key": _rut_offer_scope_key' in source
    assert '"offer_url_normalized": _rut_offer_url_normalized' in source


def test_current_ip_precedence_and_subuser_scope_contract():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert "if _signed_rut and forwarded:" in source
    assert "elif cf_ip:" in source
    assert "forwarded.split(\",\", 1)[0].strip()" in source
    assert 'engine_user_id=user.get("parent_user_id") or user["id"]' in source


def test_group_id_index_reuses_existing_production_name():
    source = (
        Path(__file__).resolve().parents[1] / "cross_user_ip_isolation.py"
    ).read_text(encoding="utf-8")
    assert 'create_index("id", unique=True)' in source
    assert 'name="uniq_isolation_group_id"' not in source
