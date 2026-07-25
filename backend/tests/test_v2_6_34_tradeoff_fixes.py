"""v2.6.34 — Remaining tradeoff fixes (JWT persist, offer prewarm, profile warmup)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BACKEND = Path(__file__).resolve().parents[1]
LAUNCHER = BACKEND / "browser_profile_launcher.py"
RUT = BACKEND / "real_user_traffic.py"


def test_jwt_secret_persists_to_file():
    import importlib
    import krexion_auth_secret as kas

    with tempfile.TemporaryDirectory() as tmp:
        os.environ.pop("JWT_SECRET_KEY", None)
        os.environ["KREXION_SECRET_DIR"] = tmp
        kas._SERVER_SECRET = None
        importlib.reload(kas)
        sk = kas.resolve_jwt_secret_for_server()
        assert sk
        assert kas.get_hmac_secret() == sk
        assert (Path(tmp) / "jwt_secret").is_file()


def test_tracker_offer_only_prewarm_in_source():
    src = RUT.read_text(encoding="utf-8")
    assert "TLS prewarm → offer only (not tracker)" in src
    assert "_prewarm_url" in src


def test_browser_profile_behavioral_bio_wired():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert 'anti.get("behavioral_bio"' in src
    assert "_human_warmup" in src


def test_browser_profile_ip_warmup_wired():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert 'anti.get("ip_warmup"' in src
    assert "warm_up_ip" in src
