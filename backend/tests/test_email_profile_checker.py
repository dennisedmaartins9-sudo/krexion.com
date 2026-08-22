"""Tests for Gmail-assisted email profile checker."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from email_profile_checker import (
    GmailProfileIndex,
    _person_matches_email,
    _pick_photo_from_person,
    check_email_profile_pic,
    load_google_oauth_record,
    normalize_check_mode,
    save_google_oauth_record,
)


def test_normalize_check_mode_defaults():
    assert normalize_check_mode(None) == "gmail"
    assert normalize_check_mode("GMAIL") == "gmail"
    assert normalize_check_mode("all") == "all"
    assert normalize_check_mode("public") == "public"
    assert normalize_check_mode("contacts_only") == "contacts_only"


def test_pick_photo_from_person_skips_default():
    person = {
        "photos": [
            {"url": "https://lh3.googleusercontent.com/default-user", "default": True},
            {"url": "https://lh3.googleusercontent.com/real-photo", "default": False},
        ]
    }
    url, is_default = _pick_photo_from_person(person)
    assert url == "https://lh3.googleusercontent.com/real-photo"
    assert is_default is False


def test_person_matches_email():
    person = {"emailAddresses": [{"value": "Test@Example.com"}]}
    assert _person_matches_email(person, "test@example.com") is True
    assert _person_matches_email(person, "other@example.com") is False


def test_gmail_profile_index_lookup():
    index = GmailProfileIndex("token")
    index._by_email["a@b.com"] = {
        "email": "a@b.com",
        "has_pic": True,
        "pic_url": "https://example.com/p.jpg",
        "method": "google_contacts_cache",
        "note": None,
    }
    hit = index.lookup("a@b.com")
    assert hit and hit["has_pic"] is True


def test_gmail_mode_without_token_returns_connect_note():
    result = asyncio.run(
        check_email_profile_pic("x@gmail.com", access_token=None, check_mode="gmail")
    )
    assert result["has_pic"] is False
    assert "Connect Google" in (result.get("note") or "")


def test_contacts_only_requires_token():
    result = asyncio.run(
        check_email_profile_pic("x@gmail.com", access_token=None, check_mode="contacts_only")
    )
    assert result["has_pic"] is False
    assert "Connect Google" in (result.get("note") or "")


def test_check_email_profile_pic_uses_warmed_index():
    index = GmailProfileIndex("token")
    index._by_email["hit@gmail.com"] = {
        "email": "hit@gmail.com",
        "has_pic": True,
        "pic_url": "https://lh3.googleusercontent.com/pic",
        "method": "google_other_contacts_cache",
        "note": None,
    }
    result = asyncio.run(
        check_email_profile_pic(
            "hit@gmail.com",
            access_token="fake-token",
            check_mode="gmail",
            index=index,
        )
    )
    assert result["has_pic"] is True
    assert result["method"] == "google_other_contacts_cache"


def test_save_and_load_oauth_record():
    db = MagicMock()
    db.user_google_oauth = MagicMock()
    db.user_google_oauth.find_one = AsyncMock(return_value={"user_id": "u1", "access_token": "tok"})
    db.user_google_oauth.update_one = AsyncMock()

    asyncio.run(
        save_google_oauth_record(
            db,
            "u1",
            access_token="tok",
            refresh_token="ref",
            expires_at=9999999999.0,
            google_email="me@gmail.com",
        )
    )
    db.user_google_oauth.update_one.assert_awaited_once()

    doc = asyncio.run(load_google_oauth_record(db, "u1"))
    assert doc["access_token"] == "tok"
