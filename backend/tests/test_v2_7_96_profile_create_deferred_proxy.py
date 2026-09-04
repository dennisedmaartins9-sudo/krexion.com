"""v2.7.96 superseded by v2.7.106 — create now binds unique exit IP before save."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_proxy_for_profile_create_helper():
    from browser_profile_module import _prepare_proxy_for_profile_create

    doc = {
        "proxy": {
            "enabled": True,
            "provider_id": "pp-1",
            "server": "",
            "exit_ip": "1.2.3.4",
        },
        "exit_ip": "1.2.3.4",
    }
    _prepare_proxy_for_profile_create(doc)
    assert doc["proxy"]["smart_session"] is True
    assert doc["proxy"]["provider_id"] == "pp-1"
    assert "exit_ip" not in doc["proxy"]
    assert "exit_ip" not in doc


def test_advanced_create_binds_unique_ip():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def advanced_create")
    end = src.index("@router.post(\"/bulk-delete\")", start)
    block = src[start:end]
    assert "_bind_unique_exit_ip_at_create" in block
    assert "unique_ips_bound" in block


def test_create_profile_binds_unique_ip():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def create_profile")
    end = src.index("@router.get(\"/device-catalog\")", start)
    block = src[start:end]
    assert "_bind_unique_exit_ip_at_create" in block


def test_version_is_2_7_96():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 96]
