"""Shared click-list query helpers for local/cloud link ID alignment."""


def clicks_owner_user_id(user: dict) -> str:
    if user.get("is_sub_user"):
        return str(user.get("parent_user_id") or user.get("id") or "")
    return str(user.get("id") or "")


def build_user_clicks_scope_query(
    user: dict,
    user_links: list,
    *,
    link_id: str = None,
) -> dict:
    """Match clicks for this user's links.

    Local/native RUT may log clicks with a cloud link_id that is absent
    from the local links collection. Those rows still carry short_code +
    user_id — include them so the Clicks page is not empty.
    """
    link_ids = [link["id"] for link in user_links if link.get("id")]
    short_codes = sorted({
        str(link.get("short_code") or "").strip()
        for link in user_links
        if str(link.get("short_code") or "").strip()
    })
    owner_id = clicks_owner_user_id(user)

    if link_id and link_id in link_ids:
        return {"link_id": link_id}

    clauses: list = []
    if link_ids:
        clauses.append({"link_id": {"$in": link_ids}})
    if short_codes and owner_id:
        clauses.append({"short_code": {"$in": short_codes}, "user_id": owner_id})
    if not clauses:
        return {"link_id": {"$in": []}}
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def completed_click_status_filter() -> dict:
    """Visible clicks: completed rows + legacy docs without click_status."""
    return {
        "$or": [
            {"click_status": "completed"},
            {"click_status": {"$exists": False}},
        ]
    }


def merge_click_filters(scope: dict, extra: dict) -> dict:
    if not extra:
        return dict(scope)
    if "$or" in scope or "$and" in scope:
        return {"$and": [scope, extra]}
    return {**scope, **extra}


def apply_click_created_at_filter(query: dict, created_at: dict) -> dict:
    if not created_at:
        return query
    return merge_click_filters(query, {"created_at": created_at})
