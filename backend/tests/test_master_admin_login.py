"""Master owner login (.env MASTER_ADMIN_*) regression tests."""


def test_master_login_matches_when_configured():
    import server

    server.MASTER_ADMIN_EMAIL = "owner@krexion.com"
    server.MASTER_ADMIN_PASSWORD = "SuperSecretMasterPass"
    assert server._master_admin_login_matches("owner@krexion.com", "SuperSecretMasterPass")
    assert server._master_admin_login_matches("Owner@Krexion.com", "SuperSecretMasterPass")
    assert not server._master_admin_login_matches("admin@krexion.com", "SuperSecretMasterPass")
    assert not server._master_admin_login_matches("owner@krexion.com", "wrong")


def test_master_login_disabled_when_not_configured():
    import server

    server.MASTER_ADMIN_EMAIL = ""
    server.MASTER_ADMIN_PASSWORD = ""
    assert not server._master_admin_configured()
    assert not server._master_admin_login_matches("owner@krexion.com", "anything")
