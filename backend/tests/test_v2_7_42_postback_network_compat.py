"""v2.7.42 — Universal affiliate network postback compatibility."""
from __future__ import annotations

import importlib


def test_parse_inbound_click_id_aliases():
    pb = importlib.import_module("postback_module")
    cases = (
        ({"clickid": "abc-123"}, "abc-123"),
        ({"transaction_id": "tx-99"}, "tx-99"),
        ({"sub1": "sub-id-1"}, "sub-id-1"),
        ({"cid": "cid-55"}, "cid-55"),
        ({"CLICK_ID": "upper-1"}, "upper-1"),
        ({"requestid": "req-7"}, "req-7"),
    )
    for params, expected in cases:
        out = pb.parse_inbound_postback(params)
        assert out["click_id"] == expected, params


def test_parse_inbound_payout_aliases():
    pb = importlib.import_module("postback_module")
    assert pb.parse_inbound_postback({"clickid": "x", "amount": "12.50"})["payout"] == 12.5
    assert pb.parse_inbound_postback({"clickid": "x", "sale": "$3.25"})["payout"] == 3.25
    assert pb.parse_inbound_postback({"clickid": "x", "adv1": "9"})["payout"] == 9.0
    assert pb.parse_inbound_postback({"clickid": "x"})["payout"] == 0.0


def test_normalize_postback_status():
    pb = importlib.import_module("postback_module")
    assert pb.normalize_postback_status("sale") == "approved"
    assert pb.normalize_postback_status("rejected") == "rejected"
    assert pb.normalize_postback_status("pending") == "pending"


def test_build_outbound_context_network_macros():
    pb = importlib.import_module("postback_module")
    rp = importlib.import_module("referrer_pro")
    ctx = pb.build_outbound_postback_context(
        {
            "click_id": "uuid-1",
            "sub1": "s1val",
            "referrer_source": "tiktok",
            "country": "US",
            "user_agent": "Mozilla/5.0",
        },
        {"referrer_pro_brand": "brandX"},
        "uuid-1",
        4.5,
        "approved",
    )
    url = rp.expand_link_macros(
        "https://track.example.com/pb?cid={cid}&transaction_id={transaction_id}"
        "&amount={amount}&sale={sale}&sub1={sub1}&status={status}",
        ctx,
    )
    assert "uuid-1" in url
    assert "4.5" in url
    assert "s1val" in url
    assert "approved" in url


def test_expand_link_macros_has_offer_aliases():
    rp = importlib.import_module("referrer_pro")
    url = rp.expand_link_macros(
        "https://network.go2cloud.org/aff_lsr?transaction_id={transaction_id}&amount={amount}",
        {"click_id": "abc", "payout": "10", "status": "approved"},
    )
    assert "abc" in url
    assert "10" in url
