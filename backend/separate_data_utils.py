"""Separate Data v2 — filter spreadsheet rows by any column (email, phone, text, date)."""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s\-\(\)\.]{5,20}\d)")

PHONE_HEADER_HINTS = ("phone", "mobile", "cell", "msisdn", "tel", "whatsapp")
EMAIL_HEADER_HINTS = ("email", "e-mail", "mail")
DATE_HEADER_HINTS = ("dob", "birth", "date", "bday", "birthday")

VALID_MATCH_TYPES = frozenset({"auto", "email", "phone", "text", "date"})


def read_spreadsheet(contents: bytes, filename: str) -> pd.DataFrame:
    """Load Excel/CSV/txt into a string-typed DataFrame."""
    name = (filename or "").lower()
    if name.endswith(".csv") or name.endswith(".txt"):
        df = pd.read_csv(io.BytesIO(contents), dtype=str, keep_default_na=False)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        engine = "openpyxl" if name.endswith(".xlsx") else "xlrd"
        df = pd.read_excel(io.BytesIO(contents), engine=engine, dtype=str)
    else:
        raise ValueError("Supported formats: .xlsx, .xls, .csv, .txt")
    df = df.fillna("")
    df.columns = [str(c) for c in df.columns]
    return df


def rows_from_dataframe(df: pd.DataFrame, limit: int = 10) -> List[Dict[str, str]]:
    rows = df.head(limit).to_dict(orient="records")
    return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]


def _header_hint_type(column_name: str) -> Optional[str]:
    cl = str(column_name or "").lower().replace("_", " ").replace("-", " ")
    if any(h in cl for h in EMAIL_HEADER_HINTS):
        return "email"
    if any(h in cl for h in PHONE_HEADER_HINTS):
        return "phone"
    if any(h in cl for h in DATE_HEADER_HINTS):
        return "date"
    return None


def _count_type_in_samples(values: List[str], match_type: str) -> int:
    count = 0
    for raw in values:
        if normalize_cell(raw, match_type):
            count += 1
    return count


def infer_column_type(column_name: str, sample_values: List[str]) -> str:
    """Best-effort type for one column: email | phone | date | text."""
    hinted = _header_hint_type(column_name)
    scores = {
        "email": _count_type_in_samples(sample_values, "email"),
        "phone": _count_type_in_samples(sample_values, "phone"),
        "date": _count_type_in_samples(sample_values, "date"),
    }
    best_type = max(scores, key=scores.get)
    if scores[best_type] > 0:
        if hinted and scores.get(hinted, 0) >= max(1, scores[best_type] // 2):
            return hinted
        return best_type
    return hinted or "text"


def build_column_suggestions(columns: List[str], rows: List[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for col in columns:
        samples = [str(r.get(col, "")) for r in rows[:300]]
        out[col] = infer_column_type(col, samples)
    return out


def detect_best_column(
    columns: List[str],
    rows: List[Dict[str, str]],
    *,
    preferred_column: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """Pick match column + type. Prefers explicit column when valid."""
    suggestions = build_column_suggestions(columns, rows)
    if preferred_column and preferred_column in columns:
        return preferred_column, suggestions.get(preferred_column, "text")

    best_col: Optional[str] = None
    best_score = 0
    best_type = "text"
    best_hinted = False

    for col in columns:
        samples = [str(r.get(col, "")) for r in rows[:300]]
        col_type = suggestions[col]
        score = _count_type_in_samples(samples, col_type)
        hinted = _header_hint_type(col) == col_type
        if score > best_score or (
            score == best_score
            and score > 0
            and hinted
            and not best_hinted
        ):
            best_score = score
            best_col = col
            best_type = col_type
            best_hinted = hinted

    if best_col:
        return best_col, best_type
    return (columns[0] if columns else None), "text"


def resolve_match_type(
    match_type: Optional[str],
    column_name: str,
    sample_values: List[str],
) -> str:
    mt = (match_type or "auto").strip().lower()
    if mt not in VALID_MATCH_TYPES:
        mt = "auto"
    if mt == "auto":
        return infer_column_type(column_name, sample_values)
    return mt


def normalize_cell(value: Any, match_type: str) -> Optional[str]:
    """Normalize one cell to a comparison key for the given match type."""
    raw = str(value or "").strip()
    if not raw:
        return None

    if match_type == "email":
        m = EMAIL_PATTERN.search(raw)
        return m.group(0).strip().lower() if m else None

    if match_type == "phone":
        digits = re.sub(r"\D", "", raw)
        if 7 <= len(digits) <= 15:
            return digits
        m = PHONE_PATTERN.search(raw)
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            if 7 <= len(digits) <= 15:
                return digits
        return None

    if match_type == "date":
        try:
            from dateutil import parser as date_parser

            dt = date_parser.parse(raw, dayfirst=False, fuzzy=True)
            return dt.date().isoformat()
        except Exception:
            return None

    # text — exact match after normalisation
    collapsed = " ".join(raw.split()).lower()
    return collapsed if collapsed else None


def parse_values_text(raw: str, match_type: str) -> Tuple[List[str], List[str]]:
    """Parse pasted/uploaded value list.

    Returns:
        normalized_values — unique keys in first-seen order (for not-found tracking)
        display_values    — human-readable originals aligned to normalized_values
    """
    parts = re.split(r"[\n,;]+", raw or "")
    normalized: List[str] = []
    display: List[str] = []
    seen: Set[str] = set()

    for part in parts:
        original = (part or "").strip()
        if not original:
            continue
        key = normalize_cell(original, match_type)
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
        display.append(original)
    return normalized, display


def merge_values_text(primary: str, secondary: str) -> str:
    chunks = [c.strip() for c in (primary, secondary) if c and c.strip()]
    return "\n".join(chunks)


def filter_dataframe(
    df: pd.DataFrame,
    match_column: str,
    match_type: str,
    target_keys: Set[str],
) -> Tuple[pd.DataFrame, Set[str]]:
    """Return rows where normalized match_column value is in target_keys."""
    if match_column not in df.columns:
        raise ValueError(f"Column not found: {match_column}")

    def _cell_matches(value: Any) -> bool:
        key = normalize_cell(value, match_type)
        return bool(key and key in target_keys)

    matched_mask = df[match_column].apply(_cell_matches)
    matched_df = df[matched_mask].copy()

    found: Set[str] = set()
    for value in matched_df[match_column].tolist():
        key = normalize_cell(value, match_type)
        if key:
            found.add(key)
    return matched_df, found


def build_filter_workbook(
    *,
    matched_df: pd.DataFrame,
    all_columns: List[str],
    not_found_display: List[str],
    summary_rows: List[Dict[str, Any]],
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if len(matched_df) > 0:
            matched_df.to_excel(writer, sheet_name="Matched Rows", index=False)
        else:
            pd.DataFrame(columns=all_columns).to_excel(
                writer, sheet_name="Matched Rows", index=False,
            )
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        if not_found_display:
            pd.DataFrame({"Value (not found in file)": not_found_display}).to_excel(
                writer, sheet_name="Not Found", index=False,
            )
    output.seek(0)
    return output.getvalue()
