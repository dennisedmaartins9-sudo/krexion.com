"""Clicks scope matches cloud-logged RUT rows by short_code on local installs."""
from click_scope import build_user_clicks_scope_query, merge_click_filters


def test_scope_includes_short_code_when_cloud_link_id_differs():
    user = {"id": "0ac07926-b359-4c02-9a87-239900bccdbf"}
    user_links = [
        {
            "id": "27c8f52b-969f-435c-bb69-584b44a51460",
            "short_code": "test",
        }
    ]
    scope = build_user_clicks_scope_query(user, user_links)
    assert scope == {
        "$or": [
            {"link_id": {"$in": ["27c8f52b-969f-435c-bb69-584b44a51460"]}},
            {
                "short_code": {"$in": ["test"]},
                "user_id": "0ac07926-b359-4c02-9a87-239900bccdbf",
            },
        ]
    }
    query = merge_click_filters(scope, {"click_status": "completed"})
    assert query["$and"][0] == scope
    assert query["$and"][1] == {"click_status": "completed"}


def test_scope_honours_explicit_local_link_id():
    user = {"id": "owner-1"}
    user_links = [{"id": "local-link", "short_code": "test"}]
    scope = build_user_clicks_scope_query(user, user_links, link_id="local-link")
    assert scope == {"link_id": "local-link"}
