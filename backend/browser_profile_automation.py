"""
Browser Profile JSON automation (v2.7.79)
=========================================
Reuses RUT Visual Recorder step engine on headed profile sessions.
Default launch = manual browse. Automation runs ONLY when the user
explicitly enables JSON in the launch request.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("browser_profile_automation")


def parse_automation_steps(raw: Any) -> List[Dict[str, Any]]:
    """Normalize upload payload → list of step dicts."""
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"automation JSON parse failed: {exc}") from exc
        if isinstance(parsed, list):
            return [dict(x) for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
            return [dict(x) for x in parsed["steps"] if isinstance(x, dict)]
        raise ValueError("automation JSON must be a list of steps")
    return []


async def load_automation_upload(
    db: Any,
    user_id: str,
    upload_id: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """Load steps from an automation_json upload."""
    uid = str(upload_id or "").strip()
    if not uid:
        return [], ""
    doc = await db.uploaded_resources.find_one(
        {"id": uid, "user_id": user_id, "type": "automation_json"},
        {"_id": 0},
    )
    if not doc:
        raise ValueError("Automation JSON template not found")
    txt = str(doc.get("automation_json") or "").strip()
    items = doc.get("items") or []
    if not txt and items and isinstance(items, list):
        if len(items) == 1:
            txt = str(items[0])
        else:
            try:
                txt = json.dumps(items)
            except Exception:
                txt = ""
    steps = parse_automation_steps(txt)
    if not steps:
        raise ValueError("Automation template has no steps")
    name = str(doc.get("name") or doc.get("filename") or uid[:8])
    return steps, name


async def load_data_file_rows(db: Any, user_id: str, upload_id: str) -> List[Dict[str, Any]]:
    """Load lead rows from a data_file upload (same storage as RUT)."""
    uid = str(upload_id or "").strip()
    if not uid:
        return []
    doc = await db.uploaded_resources.find_one(
        {"id": uid, "user_id": user_id, "type": "data_file"},
        {"_id": 0},
    )
    if not doc:
        raise ValueError("Lead data file not found")
    remaining_fp = str(doc.get("remaining_file_path") or "").strip()
    file_path = (
        remaining_fp
        if remaining_fp and Path(remaining_fp).exists()
        else doc.get("file_path")
    )
    if not file_path or not Path(str(file_path)).exists():
        raise ValueError("Lead data file no longer on disk")
    from form_filler import load_rows_from_excel

    content = Path(str(file_path)).read_bytes()
    rows = load_rows_from_excel(content, doc.get("filename") or "data.xlsx")
    return [dict(r) for r in (rows or []) if isinstance(r, dict)]


async def resolve_launch_automation(
    db: Any,
    user_id: str,
    automation: Optional[Dict[str, Any]],
    profile_doc: Optional[Dict[str, Any]] = None,
    *,
    bulk_row_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build launch-time automation spec. Returns dict with:
      enabled, steps, lead_row, upload_name, total_steps, ...
    """
    prof = dict(profile_doc or {})
    auto = dict(automation or {})
    enabled = bool(auto.get("enabled"))

    upload_id = str(auto.get("automation_upload_id") or "").strip()
    data_file_id = str(auto.get("data_file_id") or "").strip()
    if not data_file_id:
        data_file_id = str(prof.get("default_data_file_id") or "").strip()

    out: Dict[str, Any] = {
        "enabled": False,
        "steps": [],
        "lead_row": {},
        "automation_upload_id": upload_id,
        "data_file_id": data_file_id,
        "upload_name": "",
        "total_steps": 0,
        "lead_row_index": int(auto.get("lead_row_index") or 0),
        "skip_missing_steps": auto.get("skip_missing_steps", True) is not False,
        "self_heal": bool(auto.get("self_heal")),
        "after_mode": str(auto.get("after_mode") or "manual"),
        "save_as_default": bool(auto.get("save_as_default")),
        "proxy_upload_id": str(auto.get("proxy_upload_id") or "").strip(),
    }

    if not enabled or not upload_id:
        return out

    steps, name = await load_automation_upload(db, user_id, upload_id)
    out["steps"] = steps
    out["upload_name"] = name
    out["total_steps"] = len(steps)
    out["enabled"] = True

    if data_file_id:
        rows = await load_data_file_rows(db, user_id, data_file_id)
        if rows:
            idx = out["lead_row_index"]
            if bulk_row_index is not None:
                idx = int(bulk_row_index)
            elif idx < 0:
                idx = 0
            idx = idx % len(rows)
            out["lead_row"] = dict(rows[idx])
            out["lead_row_index"] = idx

    return out


async def consume_data_file_row(
    db: Any,
    user_id: str,
    data_file_id: str,
    row_index: int,
    *,
    lead_row: Optional[Dict[str, Any]] = None,
) -> bool:
    """Remove one consumed lead row from Uploaded Things (RUT parity)."""
    uid = str(data_file_id or "").strip()
    if not uid or db is None:
        return False
    doc = await db.uploaded_resources.find_one(
        {"id": uid, "user_id": user_id, "type": "data_file"},
        {"_id": 0},
    )
    if not doc:
        return False

    from datetime import datetime, timezone

    gsheet_url = str(doc.get("gsheet_url") or "").strip()
    if gsheet_url:
        rows = await load_data_file_rows(db, user_id, uid)
        if not rows or row_index < 0 or row_index >= len(rows):
            return False
        target = dict(lead_row or rows[row_index] or {})
        target_email = ""
        for k in ("email", "email_address", "emailaddress", "e_mail", "mail"):
            v = target.get(k)
            if v and str(v).strip():
                target_email = str(v).strip()
                break
        deleted = False
        if target_email:
            try:
                import asyncio
                import gsheet_writer

                loop = asyncio.get_running_loop()
                deleted = await loop.run_in_executor(
                    None,
                    gsheet_writer.delete_row_by_email,
                    gsheet_url,
                    target_email,
                )
            except Exception as exc:
                logger.debug(f"[profile-automation] gsheet consume skipped: {exc}")
        key_for_audit = (target_email or f"row_{row_index}").lower()
        await db.uploaded_resources.update_one(
            {"id": uid, "user_id": user_id},
            {
                "$addToSet": {"consumed_keys": key_for_audit},
                "$inc": {"consumed_count": 1, "item_count": -1},
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )
        return bool(deleted or target_email)

    try:
        import openpyxl
        import shutil

        UPLOADS_DATA_DIR = Path(__file__).resolve().parent / "uploaded_resources"
        UPLOADS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    remaining_fp = str(doc.get("remaining_file_path") or "").strip()
    original_fp = str(doc.get("file_path") or "").strip()
    if not remaining_fp or not Path(remaining_fp).exists():
        if original_fp and Path(original_fp).exists():
            user_dir = UPLOADS_DATA_DIR / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            remaining_fp = str(user_dir / f"{uid}__remaining.xlsx")
            shutil.copyfile(original_fp, remaining_fp)
            await db.uploaded_resources.update_one(
                {"id": uid, "user_id": user_id},
                {"$set": {"remaining_file_path": remaining_fp}},
            )
        else:
            return False

    fp_str = remaining_fp
    if not Path(fp_str).exists():
        return False

    try:
        wb = openpyxl.load_workbook(fp_str)
        ws = wb.active
        header = [c.value for c in ws[1]] if ws.max_row >= 1 else []
        display_header = [h for h in header if h and str(h) != "_orig_idx"]
        if "_orig_idx" not in header:
            col_idx = len(header) + 1
            ws.cell(row=1, column=col_idx, value="_orig_idx")
            for r in range(2, ws.max_row + 1):
                ws.cell(row=r, column=col_idx, value=r - 2)
            header.append("_orig_idx")
        orig_col = header.index("_orig_idx") + 1
        target_sheet_row = None
        row_values: List[Any] = []
        for r in range(2, ws.max_row + 1):
            val = ws.cell(row=r, column=orig_col).value
            try:
                if int(val) == int(row_index):
                    target_sheet_row = r
                    for c in range(1, len(header) + 1):
                        if header[c - 1] == "_orig_idx":
                            continue
                        row_values.append(ws.cell(row=r, column=c).value)
                    break
            except (TypeError, ValueError):
                continue
        if not target_sheet_row:
            wb.close()
            return False

        used_fp = str(doc.get("used_file_path") or "").strip()
        if not used_fp:
            user_dir = UPLOADS_DATA_DIR / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            used_fp = str(user_dir / f"{uid}__used.xlsx")
        used_wb = openpyxl.load_workbook(used_fp) if Path(used_fp).exists() else openpyxl.Workbook()
        if "used data" in used_wb.sheetnames:
            used_ws = used_wb["used data"]
        else:
            used_ws = used_wb.active
            used_ws.title = "used data"
        if used_ws.max_row == 1 and not used_ws.cell(row=1, column=1).value:
            used_ws.delete_rows(1, 1)
        if used_ws.max_row < 1 or not used_ws.cell(row=1, column=1).value:
            for ci, h in enumerate(display_header or row_values, start=1):
                used_ws.cell(row=1, column=ci, value=h)
        next_used_row = used_ws.max_row + 1
        for ci, val in enumerate(row_values, start=1):
            used_ws.cell(row=next_used_row, column=ci, value=val)
        used_wb.save(used_fp)
        used_wb.close()

        ws.delete_rows(target_sheet_row, 1)
        wb.save(fp_str)
        remaining = max(0, (ws.max_row or 1) - 1)
        wb.close()

        update: Dict[str, Any] = {
            "row_count": remaining,
            "item_count": remaining,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "remaining_file_path": fp_str,
            "used_file_path": used_fp,
        }
        await db.uploaded_resources.update_one(
            {"id": uid, "user_id": user_id},
            {"$set": update, "$inc": {"consumed_count": 1}},
        )
        if remaining == 0:
            try:
                Path(fp_str).unlink(missing_ok=True)
            except Exception:
                pass
            await db.uploaded_resources.update_one(
                {"id": uid, "user_id": user_id},
                {"$set": {
                    "depleted": True,
                    "depleted_at": datetime.now(timezone.utc).isoformat(),
                    "remaining_file_path": None,
                    "item_count": 0,
                    "row_count": 0,
                }},
            )
        return True
    except Exception as exc:
        logger.warning(f"[profile-automation] consume row failed: {exc}")
        return False


async def run_profile_automation(
    page: Any,
    steps: List[Dict[str, Any]],
    lead_row: Dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    profile_id: str,
    on_session_update: Optional[Any] = None,
    skip_missing_steps: bool = True,
    self_heal: bool = False,
    should_cancel: Optional[Any] = None,
    data_file_id: str = "",
    lead_row_index: Optional[int] = None,
    db: Any = None,
    on_lead_submitted: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute RUT automation steps on an open profile page."""
    from real_user_traffic import _execute_automation_steps

    total = len(steps or [])
    if not steps:
        return {"status": "skipped", "executed_steps": 0, "total_steps": 0}

    _lead_consumed = False

    async def _consume_lead(reason: str) -> None:
        nonlocal _lead_consumed
        if _lead_consumed:
            return
        if on_lead_submitted is not None:
            _lead_consumed = True
            await on_lead_submitted(str(reason or "form_submit")[:120])
            return
        if db is None or not data_file_id or lead_row_index is None:
            return
        _lead_consumed = True
        try:
            await consume_data_file_row(
                db, user_id, data_file_id, int(lead_row_index), lead_row=dict(lead_row or {}),
            )
            logger.info(
                f"[profile-automation] lead row #{int(lead_row_index) + 1} consumed ({reason})"
            )
        except Exception as exc:
            _lead_consumed = False
            logger.debug(f"[profile-automation] lead consume failed: {exc}")

    _lead_cb = _consume_lead if (data_file_id and lead_row_index is not None) else on_lead_submitted

    async def _on_progress(payload: Dict[str, Any]) -> None:
        if on_session_update is None:
            return
        try:
            idx = int(payload.get("idx") or payload.get("step_index") or 0)
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "running",
                "automation_status": "running",
                "automation_step": idx + 1,
                "automation_total_steps": total,
                "automation_action": str(payload.get("action") or "")[:64],
            })
        except Exception as exc:
            logger.debug(f"[profile-automation] progress callback skipped: {exc}")

    try:
        if on_session_update:
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "running",
                "automation_status": "running",
                "automation_step": 0,
                "automation_total_steps": total,
            })
    except Exception:
        pass

    result = await _execute_automation_steps(
        page,
        dict(lead_row or {}),
        steps,
        skip_captcha=True,
        self_heal=bool(self_heal),
        user_id=str(user_id or "") or None,
        on_step_progress=_on_progress,
        skip_missing_steps=bool(skip_missing_steps),
        job_id=f"profile-{session_id[:8]}",
        should_cancel=should_cancel,
        on_lead_submitted=_lead_cb,
    )

    auto_status = str(result.get("status") or "failed")
    if auto_status == "cancelled":
        auto_status = "stopped"
    elif auto_status in ("ok", "skipped_captcha"):
        auto_status = "completed" if auto_status == "ok" else "captcha"

    if on_session_update:
        try:
            await on_session_update({
                "profile_id": profile_id,
                "session_id": session_id,
                "status": "running",
                "automation_status": auto_status,
                "automation_step": int(result.get("executed_steps") or 0),
                "automation_total_steps": total,
                "automation_error": str(result.get("error") or "")[:512],
            })
        except Exception:
            pass

    return result
