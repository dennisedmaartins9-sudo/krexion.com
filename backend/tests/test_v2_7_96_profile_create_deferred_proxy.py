"""v2.7.96 — Profile create never blocks on live proxy probe (permanent 502 fix)."""
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


def test_advanced_create_defers_proxy_finalize():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def advanced_create")
    end = src.index("@router.post(\"/bulk-delete\")", start)
    block = src[start:end]
    assert "_prepare_proxy_for_profile_create" in block
    assert "_finalize_doc_proxy_and_ip" not in block
    assert "_allocate_provider_proxy_lines" not in block


def test_create_profile_defers_proxy_probe():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def create_profile")
    end = src.index("@router.get(\"/device-catalog\")", start)
    block = src[start:end]
    assert "_prepare_proxy_for_profile_create" in block
    assert "_finalize_doc_proxy_and_ip" not in block


def test_version_is_2_7_96():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "2.7.96"
