"""Email profile picture checker — Gmail-assisted + public fallbacks."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

VALID_CHECK_MODES = frozenset({"gmail", "all", "contacts_only", "public"})


def normalize_check_mode(mode: Optional[str]) -> str:
    m = (mode or "gmail").strip().lower()
    if m == "public":
        return "public"
    if m == "contacts_only":
        return "contacts_only"
    if m in ("all", "public_fallback"):
        return "all"
    return "gmail"


def _photo_is_real(url: Optional[str], *, default_flag: bool = False) -> bool:
    if default_flag:
        return False
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    if "default" in low and "googleusercontent" in low:
        return False
    return True


def _pick_photo_from_person(person: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """Return (url, is_default) from a People API person object."""
    for photo in person.get("photos") or []:
        url = (photo.get("url") or "").strip()
        is_default = bool(photo.get("default"))
        if _photo_is_real(url, default_flag=is_default):
            return url, is_default
    return None, True


def _person_matches_email(person: Dict[str, Any], email: str) -> bool:
    target = email.lower().strip()
    for entry in person.get("emailAddresses") or []:
        val = (entry.get("value") or "").strip().lower()
        if val == target:
            return True
    return False


async def load_google_oauth_record(db: Any, user_id: str) -> Optional[Dict[str, Any]]:
    if db is None or not user_id:
        return None
    try:
        doc = await db.user_google_oauth.find_one({"user_id": user_id}, {"_id": 0})
        return doc
    except Exception as e:
        logger.warning("load_google_oauth_record failed: %s", e)
        return None


async def save_google_oauth_record(
    db: Any,
    user_id: str,
    *,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: float,
    google_email: Optional[str],
) -> None:
    if db is None or not user_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "access_token": access_token,
        "expires_at": expires_at,
        "google_email": google_email or "",
        "updated_at": now,
    }
    if refresh_token:
        payload["refresh_token"] = refresh_token
    try:
        await db.user_google_oauth.update_one(
            {"user_id": user_id},
            {"$set": payload, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    except Exception as e:
        logger.warning("save_google_oauth_record failed: %s", e)


async def delete_google_oauth_record(db: Any, user_id: str) -> Optional[Dict[str, Any]]:
    if db is None or not user_id:
        return None
    try:
        doc = await db.user_google_oauth.find_one_and_delete({"user_id": user_id})
        return doc
    except Exception as e:
        logger.warning("delete_google_oauth_record failed: %s", e)
        return None


async def refresh_google_oauth_token(
    db: Any,
    user_id: str,
    *,
    client_id: str,
    client_secret: str,
) -> Optional[Dict[str, Any]]:
    import aiohttp

    token_data = await load_google_oauth_record(db, user_id)
    if not token_data or not token_data.get("refresh_token"):
        raise Exception("No refresh token")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": token_data["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                raise Exception("Failed to refresh token")
            tokens = await resp.json()

    access_token = tokens.get("access_token") or token_data.get("access_token")
    expires_at = datetime.now(timezone.utc).timestamp() + float(tokens.get("expires_in", 3600))
    await save_google_oauth_record(
        db,
        user_id,
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        google_email=token_data.get("google_email"),
    )
    return await load_google_oauth_record(db, user_id)


async def get_valid_google_access_token(
    db: Any,
    user_id: str,
    *,
    client_id: str,
    client_secret: str,
) -> Optional[str]:
    token_data = await load_google_oauth_record(db, user_id)
    if not token_data:
        return None
    if token_data.get("expires_at", 0) < datetime.now(timezone.utc).timestamp():
        try:
            token_data = await refresh_google_oauth_token(
                db, user_id, client_id=client_id, client_secret=client_secret,
            )
        except Exception:
            return None
    return (token_data or {}).get("access_token")


class GmailProfileIndex:
    """Warm People API caches once, then O(1) email lookups."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._by_email: Dict[str, Dict[str, Any]] = {}

    async def warm(self) -> None:
        import aiohttp

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            await self._paginate_connections(session, headers)
            await self._paginate_other_contacts(session, headers)

    async def _paginate_connections(self, session: Any, headers: Dict[str, str]) -> None:
        import aiohttp

        page_token = ""
        for _ in range(20):
            url = (
                "https://people.googleapis.com/v1/people/me/connections"
                "?personFields=photos,emailAddresses&pageSize=1000"
            )
            if page_token:
                url += f"&pageToken={quote(page_token)}"
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
            except Exception:
                break
            for person in data.get("connections") or []:
                self._index_person(person, method="google_contacts_cache")
            page_token = data.get("nextPageToken") or ""
            if not page_token:
                break

    async def _paginate_other_contacts(self, session: Any, headers: Dict[str, str]) -> None:
        import aiohttp

        page_token = ""
        for _ in range(20):
            url = (
                "https://people.googleapis.com/v1/otherContacts"
                "?readMask=photos,emailAddresses&pageSize=1000"
            )
            if page_token:
                url += f"&pageToken={quote(page_token)}"
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
            except Exception:
                break
            for person in data.get("otherContacts") or []:
                self._index_person(person, method="google_other_contacts_cache")
            page_token = data.get("nextPageToken") or ""
            if not page_token:
                break

    def _index_person(self, person: Dict[str, Any], *, method: str) -> None:
        pic_url, _ = _pick_photo_from_person(person)
        if not pic_url:
            return
        for entry in person.get("emailAddresses") or []:
            email = (entry.get("value") or "").strip().lower()
            if email and "@" in email and email not in self._by_email:
                self._by_email[email] = {
                    "email": email,
                    "has_pic": True,
                    "pic_url": pic_url,
                    "method": method,
                    "note": None,
                }

    def lookup(self, email: str) -> Optional[Dict[str, Any]]:
        return self._by_email.get(email.lower().strip())


async def _people_search_endpoint(
    session: Any,
    headers: Dict[str, str],
    url: str,
    email: str,
    method: str,
    *,
    people_key: str = "results",
    nested_person: bool = True,
) -> Optional[Dict[str, Any]]:
    import aiohttp

    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    items = data.get(people_key) or []
    for item in items:
        person = item.get("person", item) if nested_person else item
        if not _person_matches_email(person, email):
            continue
        pic_url, _ = _pick_photo_from_person(person)
        if pic_url:
            return {
                "email": email,
                "has_pic": True,
                "pic_url": pic_url,
                "method": method,
                "note": None,
            }
    return None


async def check_with_google_people_api(
    email: str,
    access_token: str,
    *,
    index: Optional[GmailProfileIndex] = None,
) -> Optional[Dict[str, Any]]:
    if index:
        hit = index.lookup(email)
        if hit:
            return hit

    import aiohttp

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    q = quote(email)
    async with aiohttp.ClientSession() as session:
        searches = (
            (
                f"https://people.googleapis.com/v1/people:searchContacts?query={q}&readMask=photos,emailAddresses,names",
                "google_search_contacts",
                "results",
                True,
            ),
            (
                f"https://people.googleapis.com/v1/otherContacts:search?query={q}&readMask=photos,emailAddresses,names",
                "google_search_other_contacts",
                "results",
                True,
            ),
            (
                f"https://people.googleapis.com/v1/people:searchDirectoryPeople?query={q}"
                f"&readMask=photos,emailAddresses&sources=DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
                "google_directory",
                "people",
                False,
            ),
        )
        for url, method, people_key, nested in searches:
            hit = await _people_search_endpoint(
                session, headers, url, email, method,
                people_key=people_key, nested_person=nested,
            )
            if hit:
                return hit
    return None


async def _fetch_image_ok(session: Any, url: str, *, min_bytes: int = 180) -> bool:
    import aiohttp

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as resp:
            if resp.status != 200:
                return False
            ct = (resp.headers.get("content-type") or "").lower()
            if "image" not in ct:
                return False
            data = await resp.read()
            return len(data) >= min_bytes
    except Exception:
        return False


async def check_public_profile_pic(email: str) -> Dict[str, Any]:
    import aiohttp

    result = {
        "email": email,
        "has_pic": False,
        "pic_url": None,
        "method": None,
        "note": None,
    }
    email = email.lower().strip()
    email_hash = hashlib.md5(email.encode()).hexdigest()

    candidates = [
        ("unavatar", f"https://unavatar.io/{email}?fallback=false"),
        ("unavatar_google", f"https://unavatar.io/google/{email}?fallback=false"),
        ("gravatar", f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=200"),
        ("libravatar", f"https://seccdn.libravatar.org/avatar/{email_hash}?d=404&s=200"),
    ]
    if email.endswith("@gmail.com") or email.endswith("@googlemail.com"):
        candidates.extend([
            ("google_s2_public", f"https://www.google.com/s2/photos/public/{email}"),
            ("google_s2_profile", f"https://www.google.com/s2/photos/profile/{email}"),
        ])

    async with aiohttp.ClientSession() as session:
        for method, url in candidates:
            for attempt in range(2):
                ok = await _fetch_image_ok(
                    session,
                    url,
                    min_bytes=800 if method.startswith("google_s2") else 180,
                )
                if ok:
                    result["has_pic"] = True
                    result["pic_url"] = url.split("?")[0] if "unavatar" in method else url
                    result["method"] = method
                    return result
                if attempt == 0:
                    continue
        if email.endswith("@gmail.com") or email.endswith("@googlemail.com"):
            result["note"] = (
                "No public profile pic found. Connect Google (Gmail mode) for "
                "People API lookup — matches Gmail compose much better."
            )
        else:
            result["note"] = (
                "No public profile pic on Gravatar/Unavatar/social sources. "
                "Try Gmail mode with Google connected."
            )
    return result


async def check_email_profile_pic(
    email: str,
    *,
    access_token: Optional[str],
    check_mode: str,
    index: Optional[GmailProfileIndex] = None,
) -> Dict[str, Any]:
    """Main entry — returns dict with email, has_pic, pic_url, method, note."""
    mode = normalize_check_mode(check_mode)
    email = email.lower().strip()

    if mode == "contacts_only":
        if not access_token:
            return {
                "email": email,
                "has_pic": False,
                "pic_url": None,
                "method": None,
                "note": "Connect Google account first.",
            }
        hit = await check_with_google_people_api(email, access_token, index=index)
        if hit:
            return hit
        return {
            "email": email,
            "has_pic": False,
            "pic_url": None,
            "method": None,
            "note": "Not found in Google Contacts / Other contacts / Directory.",
        }

    if mode == "public":
        return await check_public_profile_pic(email)

    # gmail (default) or all
    if access_token:
        hit = await check_with_google_people_api(email, access_token, index=index)
        if hit:
            return hit

    if mode == "gmail" and access_token:
        # Google connected but not in People data — try public as secondary
        public = await check_public_profile_pic(email)
        if public.get("has_pic"):
            return public
        public["note"] = (
            (public.get("note") or "")
            + " Gmail login active but this address was not found in your Google "
            "People data (Contacts/Other Contacts). Gmail compose may still show "
            "a photo via Google's private graph — not exposed to third-party APIs."
        ).strip()
        return public

    if mode == "gmail" and not access_token:
        return {
            "email": email,
            "has_pic": False,
            "pic_url": None,
            "method": None,
            "note": "Connect Google and use Gmail mode for best accuracy (matches compose).",
        }

    # mode == all (legacy)
    public = await check_public_profile_pic(email)
    if public.get("has_pic"):
        return public
    if access_token:
        hit = await check_with_google_people_api(email, access_token, index=index)
        if hit:
            return hit
    return public
