"""Tests for Separate Data v2 generic column filter."""
from __future__ import annotations

import io

import pandas as pd
import pytest

from separate_data_utils import (
    build_column_suggestions,
    detect_best_column,
    filter_dataframe,
    infer_column_type,
    normalize_cell,
    parse_values_text,
    read_spreadsheet,
    resolve_match_type,
)


def _xlsx_bytes(rows, columns):
    df = pd.DataFrame(rows, columns=columns)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_normalize_email():
    assert normalize_cell("  Alice@Example.COM  ", "email") == "alice@example.com"
    assert normalize_cell("no-at-sign", "email") is None


def test_normalize_phone_ignores_formatting():
    assert normalize_cell("(555) 123-4567", "phone") == "5551234567"
    assert normalize_cell("555-123-4567", "phone") == "5551234567"
    assert normalize_cell("abc", "phone") is None


def test_normalize_text_case_insensitive():
    assert normalize_cell("  John  ", "text") == "john"
    assert normalize_cell("SARAH", "text") == "sarah"


def test_normalize_date_iso():
    assert normalize_cell("01/15/1990", "date") == "1990-01-15"
    assert normalize_cell("1990-01-15", "date") == "1990-01-15"


def test_filter_by_phone_preserves_all_columns():
    df = pd.DataFrame([
        {"Phone": "5551112222", "First Name": "Alice", "State": "NY"},
        {"Phone": "5559998888", "First Name": "Bob", "State": "CA"},
        {"Phone": "5553334444", "First Name": "Carol", "State": "TX"},
    ])
    keys, _ = parse_values_text("5551112222\n5559998888", "phone")
    matched, found = filter_dataframe(df, "Phone", "phone", set(keys))
    assert len(matched) == 2
    assert set(matched["First Name"].tolist()) == {"Alice", "Bob"}
    assert list(matched.columns) == ["Phone", "First Name", "State"]
    assert found == {"5551112222", "5559998888"}


def test_phone_formatting_matches_digits():
    df = pd.DataFrame([
        {"Phone": "(555) 111-2222", "First Name": "Alice"},
    ])
    keys, _ = parse_values_text("5551112222", "phone")
    matched, _ = filter_dataframe(df, "Phone", "phone", set(keys))
    assert len(matched) == 1
    assert matched.iloc[0]["First Name"] == "Alice"


def test_filter_by_text_first_name():
    df = pd.DataFrame([
        {"First Name": "John", "Email": "j@x.com"},
        {"First Name": "Sarah", "Email": "s@x.com"},
    ])
    keys, _ = parse_values_text("john\nmike", "text")
    matched, found = filter_dataframe(df, "First Name", "text", set(keys))
    assert len(matched) == 1
    assert matched.iloc[0]["First Name"] == "John"
    assert found == {"john"}


def test_detect_phone_column():
    rows = [
        {"Phone": "5551234567", "First Name": "Ann"},
        {"Phone": "5559876543", "First Name": "Bob"},
    ]
    col, typ = detect_best_column(["First Name", "Phone"], rows)
    assert col == "Phone"
    assert typ == "phone"


def test_infer_column_from_header():
    assert infer_column_type("Mobile Phone", ["5551234567"]) == "phone"
    assert infer_column_type("Date of Birth", ["01/01/1990"]) == "date"
    assert infer_column_type("First Name", ["John"]) == "text"


def test_read_spreadsheet_xlsx():
    raw = _xlsx_bytes(
        [["a@x.com", "5551112222"], ["b@y.com", "5552223333"]],
        ["Email", "Phone"],
    )
    df = read_spreadsheet(raw, "test.xlsx")
    assert list(df.columns) == ["Email", "Phone"]
    assert len(df) == 2


def test_build_column_suggestions():
    rows = [
        {"Email": "a@b.com", "Phone": "5551234567", "First Name": "Ann"},
    ] * 5
    suggestions = build_column_suggestions(["Email", "Phone", "First Name"], rows)
    assert suggestions["Email"] == "email"
    assert suggestions["Phone"] == "phone"
    assert suggestions["First Name"] == "text"


def test_resolve_match_type_auto():
    assert resolve_match_type("auto", "Phone", ["5551234567"]) == "phone"
    assert resolve_match_type("text", "Phone", ["5551234567"]) == "text"


def test_parse_values_dedupes():
    keys, display = parse_values_text("a@x.com\nA@X.COM\nb@y.com", "email")
    assert keys == ["a@x.com", "b@y.com"]
    assert len(display) == 2
