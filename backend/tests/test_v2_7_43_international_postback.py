"""v2.7.43 — International postback perfection checks."""
from __future__ import annotations

import importlib


def test_rejected_conversion_not_countable():
    pb = importlib.import_module("postback_module")
    assert pb.conversion_counts_toward_stats("approved", "postback") is True
    assert pb.conversion_counts_toward_stats("rejected", "postback") is False
    assert pb.conversion_counts_toward_stats("pending", "postback") is False
    assert pb.conversion_counts_toward_stats("rut_heuristic", "rut_heuristic") is True


def test_validate_outbound_postback_url():
    pb = importlib.import_module("postback_module")
    bad = pb.validate_outbound_postback_url("https://track.com/pb?x=1")
    assert bad["ok"] is False
    good = pb.validate_outbound_postback_url(
        "https://voluum.com/postback?cid={click_id}&payout={payout}"
    )
    assert good["ok"] is True


def test_inbound_catalog_has_network_examples():
    pb = importlib.import_module("postback_module")
    cat = pb.get_postback_international_catalog("https://krexion.com")
    assert "Everflow" in cat["supported_networks"]
    assert "everflow" in cat["inbound"]["network_examples"]
    assert "clickid" in cat["inbound"]["primary_get"]
