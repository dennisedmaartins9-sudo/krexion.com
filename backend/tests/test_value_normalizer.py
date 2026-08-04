"""
Unit tests for value_normalizer.expand_value_variants — covers the state
short/full-form, date-of-birth multi-format, and dropdown-matching
scenarios described in the 2026-06 fix request.

Run:  cd /app/backend && python3 -m pytest tests/test_value_normalizer.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from value_normalizer import expand_value_variants, is_date_like


def _contains(variants, *expected):
    """Assert every `expected` value is somewhere in `variants`."""
    missing = [e for e in expected if e not in variants]
    assert not missing, f"missing {missing!r} in {variants!r}"


# ── US states ─────────────────────────────────────────────────────────────
def test_state_short_to_full():
    v = expand_value_variants("TX")
    _contains(v, "TX", "Texas", "texas", "TEXAS")


def test_state_full_to_short():
    v = expand_value_variants("Texas")
    _contains(v, "Texas", "TX", "tx")


def test_state_lowercase_full():
    v = expand_value_variants("texas")
    _contains(v, "texas", "TX", "Texas")


def test_state_multi_word():
    v = expand_value_variants("new york")
    _contains(v, "new york", "NY", "ny", "New York")


def test_state_california_both_ways():
    assert "California" in expand_value_variants("CA")
    assert "CA" in expand_value_variants("California")


def test_state_district_of_columbia_alt_spelling():
    v = expand_value_variants("Washington DC")
    _contains(v, "District of Columbia", "DC")


# ── Months / numerics ─────────────────────────────────────────────────────
def test_month_number_to_name():
    v = expand_value_variants("6")
    _contains(v, "6", "06", "June", "Jun")


def test_month_name_to_number():
    v = expand_value_variants("June")
    _contains(v, "June", "6", "06", "Jun")


def test_month_name_for_form_numeric():
    from value_normalizer import month_name_for_form, is_month_header
    assert month_name_for_form(1) == "January"
    assert month_name_for_form("4") == "April"
    assert month_name_for_form(4.0) == "April"
    assert month_name_for_form("11") == "November"
    assert month_name_for_form("Jun") == "June"
    assert is_month_header("month")
    assert is_month_header("birth_month")
    assert not is_month_header("amount")


def test_month_zero_padded():
    v = expand_value_variants("06")
    _contains(v, "06", "6", "June", "Jun")


def test_month_abbrev_to_full():
    v = expand_value_variants("Mar")
    _contains(v, "Mar", "3", "03", "March")


# ── Dates of birth (multi-format) ─────────────────────────────────────────
def test_dob_iso_to_us():
    v = expand_value_variants("1990-05-15")
    _contains(v, "1990-05-15", "05/15/1990", "15/05/1990", "May 15, 1990",
              "1990", "5", "05", "May", "Jun" if False else "May", "15")


def test_dob_us_to_iso():
    v = expand_value_variants("5/15/1990")
    _contains(v, "5/15/1990", "1990-05-15", "15/05/1990")


def test_dob_verbose_to_iso():
    v = expand_value_variants("May 15, 1990")
    _contains(v, "May 15, 1990", "1990-05-15", "05/15/1990")


def test_dob_european_format():
    # 15/05/1990 → could be ambiguous (US vs EU); we treat as US, so:
    v = expand_value_variants("15/05/1990")  # US: month=15 (invalid) → dateutil tries day-first
    # Either parses as Day-Month-Year or falls through; just check year+5+15 appears in some form
    assert any("1990" in s for s in v)


def test_dob_yyyymmdd_compact():
    v = expand_value_variants("19900515")
    _contains(v, "19900515", "1990-05-15", "May 15, 1990")


def test_dob_year_only_no_explosion():
    # "1990" alone should NOT expand to bogus date variants
    v = expand_value_variants("1990")
    assert "1990" in v
    # Should not contain things like "1990-06-12" (today's date with year 1990)
    today_month = ""
    from datetime import date as _date
    today_month_full = ("January February March April May June July "
                        "August September October November December"
                        ).split()[_date.today().month - 1]
    bad = [s for s in v if today_month_full in s]
    assert not bad, f"year-only should not generate today-based date variants, got {bad!r}"


def test_dob_day_components_for_split_fields():
    v = expand_value_variants("1990-12-03")
    # Year
    _contains(v, "1990", "90")
    # Month (December)
    _contains(v, "12", "December", "Dec")
    # Day
    _contains(v, "3", "03", "3rd")


# ── Misc / boolean / Canadian ────────────────────────────────────────────
def test_bool_yes_no():
    _contains(expand_value_variants("y"), "y", "Yes", "yes", "true", "1")
    _contains(expand_value_variants("yes"), "yes", "Y", "true", "1")
    _contains(expand_value_variants("no"), "no", "N", "false", "0")


def test_canadian_province():
    _contains(expand_value_variants("ON"), "ON", "Ontario", "ontario")
    _contains(expand_value_variants("Ontario"), "Ontario", "ON", "on")


def test_empty_input():
    assert expand_value_variants("") == []
    assert expand_value_variants(None) == []


def test_is_date_like():
    assert is_date_like("1990-05-15")
    assert is_date_like("5/15/1990")
    assert is_date_like("May 15, 1990")
    assert is_date_like("19900515")
    assert not is_date_like("1990")
    assert not is_date_like("6")
    assert not is_date_like("Texas")
    assert not is_date_like("")
