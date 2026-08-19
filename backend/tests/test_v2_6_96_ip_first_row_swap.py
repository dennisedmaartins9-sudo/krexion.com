"""v2.6.96 — Two fixes for DataImpulse state targeting:
1. DataImpulse key corrected from 'st' to 'state', format from code to slug
   (st.nc → state.north_carolina) so the provider actually targets correctly.
2. IP-first row swap: when gateway returns a valid IP for a different state,
   swap to a lead row for that state instead of wasting 50 retries."""
from __future__ import annotations

from pathlib import Path

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"
PPM = Path(__file__).resolve().parents[1] / "proxy_provider_module.py"


def _rut_src() -> str:
    return RUT.read_text(encoding="utf-8")


def _ppm_src() -> str:
    return PPM.read_text(encoding="utf-8")


def test_swap_block_exists():
    src = _rut_src()
    assert "IP-FIRST SWAP" in src
    assert "pick_next_row_for_state(_exit_st)" in src


def test_swap_releases_original_row():
    src = _rut_src()
    idx = src.index("IP-FIRST SWAP")
    block = src[idx : idx + 2000]
    assert "consumed_row_indices.discard(_row_idx)" in block


def test_swap_updates_row_state_code():
    src = _rut_src()
    idx = src.index("IP-FIRST SWAP")
    block = src[idx : idx + 2000]
    assert "row_state_code = _exit_st" in block
    assert "entry[" in block
    assert "lead_state" in block


def test_swap_updates_on_demand_row_pick():
    src = _rut_src()
    idx = src.index("IP-FIRST SWAP")
    block = src[idx : idx + 2000]
    assert "on_demand_row_pick = _swap_pick" in block


def test_no_swap_when_no_row_available():
    src = _rut_src()
    idx = src.index("IP-FIRST SWAP")
    block = src[idx : idx + 2500]
    assert "if not _swapped:" in block
    assert "retrying" in block.lower() or "!= {row_state_code}" in block


def test_swap_logs_live_step():
    src = _rut_src()
    idx = src.index("IP-FIRST SWAP")
    block = src[idx : idx + 2000]
    assert "swapped to row" in block


def test_dataimpulse_uses_state_key_not_st():
    src = _ppm_src()
    idx = src.index('"DataImpulse"')
    block = src[idx : idx + 400]
    assert '"state": "state"' in block
    assert '"state": "st"' not in block


def test_dataimpulse_uses_slug_format():
    src = _ppm_src()
    idx = src.index('"DataImpulse"')
    block = src[idx : idx + 400]
    assert '"state_fmt": "{slug}"' in block
    assert '"state_fmt": "{code_lower}"' not in block


def test_version_is_2_6_96():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert int(version.replace(".", "")) >= 2696
