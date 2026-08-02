"""Admin account API model validation."""
from server import AdminChangePasswordReq, UserResponse


def test_admin_change_password_req_accepts_strings():
    req = AdminChangePasswordReq(current_password="old12345", new_password="new12345")
    assert req.current_password == "old12345"
    assert req.new_password == "new12345"


def test_user_response_allow_cloud_heavy_field():
    u = UserResponse(
        id="u1",
        email="a@test.com",
        name="A",
        created_at="2026-01-01T00:00:00+00:00",
        allow_cloud_heavy=True,
    )
    assert u.allow_cloud_heavy is True
