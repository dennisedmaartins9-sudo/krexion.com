"""
value_normalizer.py — shared helpers for expanding a raw cell value into a
list of variant strings, so dropdown matching / form-fill matching can
succeed against many different option-label / option-value conventions.

This module exists because BOTH the Visual Recorder (recording-time live
select) AND the Real-User-Traffic engine (replay-time) need to match a
single raw value (e.g. "TX", "1990-05-15", "y") against dropdown options
that may use the FULL name, abbreviation, lower/upper case, padded /
unpadded numeric, or any of a dozen date formats.

Public API
----------
expand_value_variants(value) -> List[str]
    Given any raw cell value, return an ordered list of variants
    (including the raw value itself first). Order matters — earliest
    variants are most-likely matches.

is_date_like(value) -> bool
    Quick heuristic to decide whether to expand date variants.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import List, Optional

# ── US states + territories (USPS abbreviations) ─────────────────────────
US_STATES: dict = {
    "AL": "Alabama", "AK": "Alaska", "AS": "American Samoa",
    "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FM": "Federated States of Micronesia",
    "FL": "Florida", "GA": "Georgia", "GU": "Guam",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MH": "Marshall Islands", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "MP": "Northern Mariana Islands",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PW": "Palau", "PA": "Pennsylvania", "PR": "Puerto Rico",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VI": "Virgin Islands", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming",
}
# Reverse map (full-name lower-case → abbreviation), built once.
_US_NAME_TO_CODE: dict = {v.lower(): k for k, v in US_STATES.items()}

# ── Canadian provinces / territories ─────────────────────────────────────
CA_PROVINCES: dict = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island",
    "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}
_CA_NAME_TO_CODE: dict = {v.lower(): k for k, v in CA_PROVINCES.items()}

# Common alternate spellings → canonical full name (so user data variations
# all map to ONE variant set). Keep this small — only universally accepted.
_ALT_STATE_SPELLINGS: dict = {
    "washington dc": "District of Columbia",
    "washington d.c.": "District of Columbia",
    "d.c.": "District of Columbia",
    "newfoundland": "Newfoundland and Labrador",
    "puerto-rico": "Puerto Rico",
}

# ── Months ───────────────────────────────────────────────────────────────
_MONTHS_FULL = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_LOOKUP: dict = {}
for _i, _m in enumerate(_MONTHS_FULL, start=1):
    _MONTH_LOOKUP[_m.lower()] = _i
    _MONTH_LOOKUP[_m.lower()[:3]] = _i

_MONTH_HEADER_KEYS = frozenset({
    "month", "birth_month", "birthmonth", "dob_month", "dmonth", "bmonth", "birth_m",
})


def is_month_header(name: str) -> bool:
    """True when an Excel/header name refers to a birth-month field."""
    k = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if k in _MONTH_HEADER_KEYS:
        return True
    return "month" in k and "amount" not in k and "monthly" not in k


def month_name_for_form(value, *, abbrev: bool = False) -> str:
    """Convert 1-12 (or 01 / 4.0 / Jun) to an English month label for text fill.

    Used by Visual Recorder live fill and RUT ``fill`` steps where dropdown
    variant expansion does not run. ``abbrev=True`` returns ``Jan``..``Dec``.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        raw = str(int(value))
    elif isinstance(value, int) and not isinstance(value, bool):
        raw = str(value)
    else:
        raw = str(value).strip()
    if not raw:
        return ""
    if raw.lstrip("-").replace(".", "", 1).isdigit():
        try:
            n = int(float(raw))
            if 1 <= n <= 12:
                full = _MONTHS_FULL[n - 1]
                return full[:3] if abbrev else full
        except (ValueError, OverflowError):
            pass
    lower = raw.lower()
    if lower in _MONTH_LOOKUP:
        full = _MONTHS_FULL[_MONTH_LOOKUP[lower] - 1]
        return full[:3] if abbrev else full
    return raw

# ── Boolean-ish ──────────────────────────────────────────────────────────
_TRUE_TOKENS = {"y", "yes", "true", "1", "on", "checked"}
_FALSE_TOKENS = {"n", "no", "false", "0", "off", "unchecked"}


def _add_unique(out: List[str], seen: set, val: Optional[str]) -> None:
    """Append `val` to `out` only if non-empty AND not seen before."""
    if val is None:
        return
    s = str(val)
    if not s:
        return
    if s in seen:
        return
    seen.add(s)
    out.append(s)


def _add_case_variants(out: List[str], seen: set, val: str) -> None:
    """Add uppercase / lowercase / title / capitalize variants of `val`."""
    if not val:
        return
    _add_unique(out, seen, val)
    _add_unique(out, seen, val.lower())
    _add_unique(out, seen, val.upper())
    # Title-case ("texas" → "Texas", "new york" → "New York")
    _add_unique(out, seen, val.title())
    # Capitalize first letter only ("new york" → "New york")
    _add_unique(out, seen, val.capitalize())


# ── Date parsing ─────────────────────────────────────────────────────────
# Ordered list of strptime patterns we attempt. First match wins.
# Order: ISO → US-style → European → verbose → year-month
_DATE_PATTERNS: tuple = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%m/%d/%y", "%d/%m/%y", "%y-%m-%d",
    "%B %d, %Y", "%B %d %Y", "%d %B %Y", "%d %B, %Y",
    "%b %d, %Y", "%b %d %Y", "%d %b %Y", "%d %b, %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y%m%d",
)


def _try_parse_date(value: str) -> Optional[date]:
    """Attempt to parse `value` as a date using known patterns. Also tries
    `python-dateutil` as a fallback if installed (handles even more
    formats). Returns a `date` or None.

    To avoid false positives (e.g. "1990" or "6" or "June" being parsed
    as today's date with substituted components), we REQUIRE that `value`
    contains enough date-like structure: a separator OR a month name
    alongside other tokens OR a pure 8-digit YYYYMMDD.
    """
    s = (value or "").strip()
    if not s or len(s) > 40:
        return None
    # Date-like structure guard: must have a separator, OR be an 8-digit
    # YYYYMMDD, OR contain a month name token alongside other text.
    has_sep = any(c in s for c in "/-.") or " " in s or "T" in s
    is_yyyymmdd = bool(re.fullmatch(r"\d{8}", s))
    has_month_name = False
    if not has_sep and not is_yyyymmdd:
        # Check for a month name embedded in the string
        lower = s.lower()
        for _m in _MONTHS_FULL:
            if _m.lower() in lower or _m.lower()[:3] in lower:
                has_month_name = True
                break
    if not (has_sep or is_yyyymmdd or has_month_name):
        return None
    # Strip trailing fractional seconds / timezone for the ISO datetime case
    s_clean = re.sub(r"\.\d+(?:[+-]\d{2}:?\d{2}|Z)?$", "", s)
    for pat in _DATE_PATTERNS:
        try:
            return datetime.strptime(s_clean, pat).date()
        except ValueError:
            continue
    # Fallback to dateutil for everything else (e.g. "May 15th, 1990")
    try:
        from dateutil import parser as _du  # type: ignore
        # dayfirst=False matches US default; we don't try both ways to
        # avoid ambiguity (e.g. "05/06/1990" → only May-6, not Jun-5).
        # `default` set to a sentinel so dateutil doesn't silently fill
        # missing components from "today" (e.g. "1990" → "1990-<today>").
        _sentinel = datetime(1900, 1, 1)
        parsed = _du.parse(s_clean, dayfirst=False, fuzzy=False, default=_sentinel)
        # Reject if the parser had to invent both month AND day from the
        # sentinel — that means the input wasn't really a full date.
        if parsed.month == 1 and parsed.day == 1 and "1" not in s_clean and "jan" not in s_clean.lower():
            return None
        return parsed.date()
    except Exception:
        return None


def is_date_like(value: str) -> bool:
    """Cheap check: does `value` look like a date string?"""
    return _try_parse_date(value) is not None


def _add_date_variants(out: List[str], seen: set, d: date) -> None:
    """Add many date / year / month / day variant strings derived from `d`.

    ORDERING is important for split-field DOB dropdowns:
      1. Full-date strings first (for single-field date inputs)
      2. Year-only variants (year dropdowns usually have only year values)
      3. Day-only variants (day dropdowns have values "1".."31")
      4. Month-only variants LAST (month dropdowns: "1".."12" or names)

    Reason for putting Day BEFORE Month: when data is "1990-05-15" and
    we match against a Day select with options "01".."31", we want "15"
    to win over "05" (the month). Month select with options "01".."12"
    won't match "15" anyway → it will fall through to month variants.
    """
    y, m, dd = d.year, d.month, d.day
    month_full = _MONTHS_FULL[m - 1]
    month_abbrev = month_full[:3]

    # 1. Full-date string variants (single-field date inputs)
    fmts = (
        d.strftime("%Y-%m-%d"),
        d.strftime("%m/%d/%Y"),
        d.strftime("%d/%m/%Y"),
        d.strftime("%m-%d-%Y"),
        d.strftime("%d-%m-%Y"),
        d.strftime("%Y/%m/%d"),
        f"{month_full} {dd}, {y}",
        f"{month_full} {dd} {y}",
        f"{dd} {month_full} {y}",
        f"{month_abbrev} {dd}, {y}",
        f"{dd} {month_abbrev} {y}",
        d.strftime("%m/%d/%y"),
        d.strftime("%d/%m/%y"),
    )
    for f in fmts:
        _add_unique(out, seen, f)

    # 2. Year-only (year dropdowns)
    _add_unique(out, seen, str(y))
    _add_unique(out, seen, f"{y % 100:02d}")  # "1990" → "90"

    # 3. Day-only (day dropdowns: "1".."31")
    _add_unique(out, seen, str(dd))               # "15"
    _add_unique(out, seen, f"{dd:02d}")           # "15" or "05"
    _add_unique(out, seen, _ordinal_suffix(dd))   # "15th"

    # 4. Month-only LAST (month dropdowns: "1".."12" or names)
    _add_unique(out, seen, str(m))                # "5"
    _add_unique(out, seen, f"{m:02d}")            # "05"
    _add_unique(out, seen, month_full)            # "May"
    _add_unique(out, seen, month_full.lower())
    _add_unique(out, seen, month_full.upper())
    _add_unique(out, seen, month_abbrev)          # "May" (abbrev == full for May)
    _add_unique(out, seen, month_abbrev.lower())
    _add_unique(out, seen, month_abbrev.upper())
    # Combined "5 - May" style (some dropdowns use this)
    _add_unique(out, seen, f"{m} - {month_full}")
    _add_unique(out, seen, f"{m:02d} - {month_full}")


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ── Main entry-point ─────────────────────────────────────────────────────
def expand_value_variants(value) -> List[str]:
    """Given any cell value, return an ordered list of string variants to
    try when matching against a dropdown option / select option. The
    original value (stringified) is always first.

    Variants generated (when applicable):
      • raw value, stripped, lower / upper / title case
      • zero-padded / un-padded numeric ("6" ↔ "06")
      • month-number ↔ month-name ("6" ↔ "June" ↔ "Jun")
      • US state code ↔ full name ("TX" ↔ "Texas")
      • Canadian province code ↔ full name ("ON" ↔ "Ontario")
      • date parsed → all formats (Y-M-D, M/D/Y, "Month D, Y", etc.)
      • date components (year, month, day) for split-field DOBs
      • boolean variants ("y" ↔ "yes" ↔ "true" ↔ "1")
    """
    out: List[str] = []
    seen: set = set()

    # Normalise to string
    if value is None:
        return out
    if isinstance(value, (datetime, date)):
        # Datetime/date objects → format ourselves
        d = value.date() if isinstance(value, datetime) else value
        _add_unique(out, seen, d.strftime("%Y-%m-%d"))
        _add_date_variants(out, seen, d)
        return out

    raw = str(value)
    stripped = raw.strip()
    _add_unique(out, seen, raw)
    _add_unique(out, seen, stripped)
    if not stripped:
        return out

    lower = stripped.lower()

    # ── Numeric variants ──
    if stripped.lstrip("-").isdigit():
        n = int(stripped)
        _add_unique(out, seen, str(n))
        _add_unique(out, seen, f"{n:02d}")
        # Month number → name (only 1-12 makes sense)
        if 1 <= n <= 12:
            full = _MONTHS_FULL[n - 1]
            abbrev = full[:3]
            for v in (full, abbrev, full.lower(), abbrev.lower(),
                      full.upper(), abbrev.upper()):
                _add_unique(out, seen, v)

    # ── Month-name variants ──
    if lower in _MONTH_LOOKUP:
        mi = _MONTH_LOOKUP[lower]
        _add_unique(out, seen, str(mi))
        _add_unique(out, seen, f"{mi:02d}")
        full = _MONTHS_FULL[mi - 1]
        _add_unique(out, seen, full)
        _add_unique(out, seen, full[:3])

    # ── Boolean variants ──
    if lower in _TRUE_TOKENS:
        for t in ("Yes", "yes", "YES", "Y", "y", "true", "True", "1", "on", "checked"):
            _add_unique(out, seen, t)
    elif lower in _FALSE_TOKENS:
        for t in ("No", "no", "NO", "N", "n", "false", "False", "0", "off", "unchecked"):
            _add_unique(out, seen, t)

    # ── US state variants ──
    if len(stripped) == 2 and stripped.upper() in US_STATES:
        # User gave a code → also try the full name
        full = US_STATES[stripped.upper()]
        _add_case_variants(out, seen, full)
    else:
        # User gave a name → also try the code
        key = lower
        if key in _ALT_STATE_SPELLINGS:
            key = _ALT_STATE_SPELLINGS[key].lower()
            _add_case_variants(out, seen, _ALT_STATE_SPELLINGS[lower])
        if key in _US_NAME_TO_CODE:
            code = _US_NAME_TO_CODE[key]
            _add_unique(out, seen, code)
            _add_unique(out, seen, code.lower())

    # ── Canadian province variants ──
    if len(stripped) == 2 and stripped.upper() in CA_PROVINCES:
        full = CA_PROVINCES[stripped.upper()]
        _add_case_variants(out, seen, full)
    elif lower in _CA_NAME_TO_CODE:
        code = _CA_NAME_TO_CODE[lower]
        _add_unique(out, seen, code)
        _add_unique(out, seen, code.lower())

    # ── Date variants ──
    parsed = _try_parse_date(stripped)
    if parsed:
        _add_date_variants(out, seen, parsed)

    # ── Generic case variants for free-text (last, to keep order useful) ──
    _add_case_variants(out, seen, stripped)

    return out


__all__ = [
    "expand_value_variants",
    "is_date_like",
    "is_month_header",
    "month_name_for_form",
    "US_STATES",
    "CA_PROVINCES",
]
