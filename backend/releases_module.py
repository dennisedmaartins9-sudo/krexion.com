"""
Krexion — App Releases & Auto-Update Module
============================================
Admin publishes releases at https://krexion.com → customer's local install
polls for updates → shows a "New version available" banner → one-click apply.

Endpoints:
  Admin (cloud, JWT-required):
    POST   /api/admin/releases                — create a release
    GET    /api/admin/releases                — list all releases
    PATCH  /api/admin/releases/{id}           — edit notes / severity
    DELETE /api/admin/releases/{id}           — remove a release

  Customer (license-auth):
    GET    /api/system/latest-version         — newest published release
    GET    /api/system/version                — current local version (no-auth)

  Customer (local-only, JWT-required):
    POST   /api/system/install-update         — write flag file so the host
                                                updater script picks it up

A `VERSION` file at /app/backend/VERSION holds the running version on each
install (cloud OR local). Updater compares semver strings.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

logger = logging.getLogger(__name__)
releases_router = APIRouter(tags=["releases"])

# Bound from server.py
_db: Any = None
_get_current_admin: Any = None
_get_current_user: Any = None

VERSION_FILE = Path(__file__).parent / "VERSION"
UPDATE_FLAG_FILE = Path("/data/update_requested.flag")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].+)?$")


def _bind(*, main_db, get_current_admin, get_current_user) -> None:
    global _db, _get_current_admin, _get_current_user
    _db = main_db
    _get_current_admin = get_current_admin
    _get_current_user = get_current_user


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:  # noqa: BLE001
        pass
    return "0.0.0"


# ── 2026-01: DB-aware version display ────────────────────────────────
# The static VERSION file gets reset to whatever's in git on every
# container restart / git-pull, which means after an admin publishes a
# new release (writes the file → record in DB), the next deployment
# wipes the file back to 1.0.4 and the banner permanently shows the
# wrong "you're on v1.0.4" message.
#
# Fix: every customer-facing version-display endpoint now consults the
# DB's latest PUBLISHED release in addition to the file, and returns the
# NEWER of the two. The publish flow still writes VERSION_FILE (so a
# fresh-clone customer install starts at the right version), but the
# admin panel never depends solely on the static file.
async def _displayed_current_version() -> str:
    """Return the version to display in UI. Prefers the latest published
    release in the DB over the static VERSION file. Falls back to the
    file when DB lookup fails or no published release exists.

    v1.0.11 fix: also require the DB record to carry a non-empty
    ``download_url`` AND the URL must look like a real GitHub Releases
    asset (not a placeholder / orphan). Pre-1.0.11 the cloud admin DB
    accumulated an orphan ``v1.1.20`` "Update available" record from a
    prior session that was never actually built or attached to a
    GitHub Release - this caused customer dashboards to show "v1.1.20"
    in the sidebar badge even though the installed product and the
    GitHub Releases page were all on 1.0.x. Filtering on the URL
    shape silently hides that orphan without forcing the admin to
    manually delete the DB row (matches user's "kuch delete na ho"
    rule).
    """
    file_ver = current_version()
    mode = (os.environ.get("KREXION_MODE") or "local").lower()
    # Native/local installs must reflect the ACTUAL Python bundle on disk.
    # Showing the cloud-published release here misled customers into thinking
    # they were on v2.6.79 while the engine was still v2.6.74.
    if mode in ("native", "local"):
        return file_ver
    try:
        if _db is None:
            return file_ver
        rel = await _db.app_releases.find_one(
            {"published": True},
            sort=[("created_at", -1)],
            projection={"version": 1, "download_url": 1, "_id": 0},
        )
        if rel and rel.get("version"):
            db_ver = str(rel["version"]).strip()
            url = (rel.get("download_url") or "").strip().lower()
            looks_real = (
                url.startswith("http")
                and "/releases/download/" in url
                and url.endswith(".exe")
            )
            # Return the newer of the two - but only if the DB record is
            # backed by a real downloadable asset.
            if looks_real and is_newer(db_ver, file_ver):
                return db_ver
    except Exception:  # noqa: BLE001
        pass
    return file_ver


def _parse(v: str) -> tuple:
    s = (v or "").strip().lstrip("vV")
    m = SEMVER_RE.match(s)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer(remote: str, local: str) -> bool:
    return _parse(remote) > _parse(local)


def _github_native_download_url(version: str) -> str:
    """Stable GitHub Releases asset URL for the native Windows installer."""
    ver = (version or "").strip().lstrip("vV")
    repo = os.environ.get("GITHUB_REPOSITORY", "krexion-com-final/krexion.com-final")
    return (
        f"https://github.com/{repo}/releases/download/v{ver}/"
        f"Krexion-Setup-v{ver}.exe"
    )


async def sync_deployed_release_record() -> dict[str, Any]:
    """Upsert a published release row matching backend/VERSION after VPS deploy.

    Keeps /download, /api/system/installer-info, and customer update banners
    aligned with the live CDN without manual Quick Publish.
    """
    ver = current_version().strip().lstrip("vV")
    if not ver or ver == "0.0.0":
        return {"ok": False, "reason": "no_version"}
    if _db is None:
        return {"ok": False, "reason": "db_unbound"}

    download_url = _github_native_download_url(ver)
    payload = {
        "version": ver,
        "title": f"Krexion {ver}",
        "notes": f"Live on krexion.com — native + desktop CDN synced for v{ver}.",
        "severity": "recommended",
        "download_url": download_url,
        "published": True,
        "source": "deploy-sync",
        "updated_at": _now_iso(),
    }
    existing = await _db.app_releases.find_one({"version": ver}, {"_id": 0, "id": 1})
    if existing:
        await _db.app_releases.update_one({"version": ver}, {"$set": payload})
        release_id = existing.get("id")
    else:
        doc = {
            "id": str(uuid.uuid4()),
            "created_at": _now_iso(),
            **payload,
        }
        await _db.app_releases.insert_one(doc)
        release_id = doc["id"]
    logger.info("[releases] deploy-sync v%s (id=%s)", ver, release_id)
    return {"ok": True, "version": ver, "id": release_id, "download_url": download_url}


def _bump_patch(version: str) -> str:
    """Bump the patch component of a semver version (1.0.4 → 1.0.5)."""
    major, minor, patch = _parse(version)
    if (major, minor, patch) == (0, 0, 0):
        return "1.0.0"
    return f"{major}.{minor}.{patch + 1}"


# Commit subjects we never want to surface in release notes — these are
# generated by the platform's auto-snapshot feature, not real changes the
# admin made.
_AUTO_COMMIT_PATTERNS = (
    "auto-commit for",
    "auto-generated changes",
)


def _collect_commits_since(since_iso: Optional[str], limit: int = 100) -> list[dict]:
    """Return a list of commits on the current branch made after `since_iso`.

    If `since_iso` is None, returns the most recent `limit` commits.
    Auto-generated platform commits keep their subjects (they ARE the
    real change checkpoints) but they're flagged so the caller can fall
    back to a file-based summary instead of bulleting the raw subjects.
    Returns [] silently if git is unavailable.
    """
    repo_root = Path(__file__).resolve().parent.parent  # /app
    if not (repo_root / ".git").exists():
        return []

    cmd = ["git", "-C", str(repo_root), "log",
           "--pretty=format:%H|%h|%s|%an|%ad", "--date=iso", "HEAD"]
    if since_iso:
        cmd.insert(4, f"--since={since_iso}")
    else:
        cmd.insert(4, f"-{int(limit)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[releases] git log failed: {e}")
        return []

    commits = []
    for line in (result.stdout or "").splitlines():
        parts = line.split("|", 4)
        if len(parts) < 3:
            continue
        subject = parts[2].strip()
        if not subject:
            continue
        subj_lc = subject.lower()
        is_auto = any(p in subj_lc for p in _AUTO_COMMIT_PATTERNS)
        commits.append({
            "full_hash": parts[0],
            "hash": parts[1],
            "subject": subject,
            "author": parts[3] if len(parts) > 3 else "",
            "date": parts[4] if len(parts) > 4 else "",
            "is_auto": is_auto,
        })
        if len(commits) >= limit:
            break
    return commits


def _collect_changed_files_since(since_iso: Optional[str]) -> list[str]:
    """Return a deduplicated list of repo-relative file paths that changed
    in commits made after `since_iso` (or all of recent history if None).
    """
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / ".git").exists():
        return []

    cmd = ["git", "-C", str(repo_root), "log", "--name-only", "--pretty=format:", "HEAD"]
    if since_iso:
        cmd.insert(4, f"--since={since_iso}")
    else:
        cmd.insert(4, "-50")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[releases] git log --name-only failed: {e}")
        return []

    files = set()
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line:
            files.add(line)
    return sorted(files)


def _summarize_file_changes(files: list[str]) -> tuple[list[str], dict]:
    """Group changed files into human-readable categories and return
    (bullet_lines, raw_groups). Used when commit subjects are too noisy
    to use directly.
    """
    groups = {
        "Pages": [],
        "UI Components": [],
        "Backend modules": [],
        "Backend (server)": [],
        "Styles & theme": [],
        "Config & deployment": [],
        "Docs & guides": [],
        "Other": [],
    }
    for f in files:
        fl = f.lower()
        if f.startswith("frontend/src/pages/"):
            groups["Pages"].append(Path(f).stem)
        elif f.startswith("frontend/src/components/"):
            groups["UI Components"].append(Path(f).stem)
        elif f.startswith("frontend/src/") and (fl.endswith(".css") or "theme" in fl):
            groups["Styles & theme"].append(Path(f).name)
        elif f.startswith("backend/server.py"):
            groups["Backend (server)"].append("server.py")
        elif f.startswith("backend/") and f.endswith(".py"):
            groups["Backend modules"].append(Path(f).stem)
        elif fl.endswith((".md", ".txt")):
            groups["Docs & guides"].append(Path(f).name)
        elif fl.endswith((".yml", ".yaml", ".json", ".conf", "dockerfile", ".env.example", ".bat", ".ps1", ".sh")):
            groups["Config & deployment"].append(Path(f).name)
        else:
            groups["Other"].append(f)

    bullets: list[str] = []
    for label, items in groups.items():
        if not items:
            continue
        # Deduplicate and cap
        uniq = sorted(set(items))
        shown = uniq[:8]
        more = len(uniq) - len(shown)
        line = f"- {label} updated: " + ", ".join(shown)
        if more > 0:
            line += f" (+{more} more)"
        bullets.append(line)
    return bullets, groups


# ─── License → user resolver (shared with sync module) ────────────────
async def _validate_license(license_key: Optional[str]):
    if not license_key:
        raise HTTPException(status_code=401, detail="Missing X-Krexion-License header")
    lic = await _db.licenses.find_one({"license_key": license_key.strip()}, {"_id": 0})
    if not lic:
        raise HTTPException(status_code=401, detail="Invalid license key")
    if lic.get("status") and lic["status"] not in ("active", "issued"):
        raise HTTPException(status_code=403, detail=f"License is {lic['status']}")
    return lic


# ─── Admin endpoints ──────────────────────────────────────────────────
# 2026-07 — removed a stub POST /api/admin/releases handler that
# always raised HTTP 500. The real handler is registered via
# _build_admin_endpoints() below and mounted on the app AFTER _bind().


# We need real admin dependency injection - we'll register handlers
# dynamically after _bind() is called from server.py. To keep it simple,
# define handlers that accept `admin` via the late-bound dependency.

def _build_admin_endpoints(get_admin_dep):
    """Register the actual admin endpoints with the correct admin dep."""
    router = APIRouter(tags=["releases-admin"])

    @router.post("/api/admin/releases")
    async def create(body: dict, admin: dict = Depends(get_admin_dep)):
        ver = (body.get("version") or "").strip()
        if not SEMVER_RE.match(ver):
            raise HTTPException(400, "version must be semver like 1.2.3")
        existing = await _db.app_releases.find_one({"version": ver})
        if existing:
            raise HTTPException(409, f"Version {ver} already exists")
        doc = {
            "id": str(uuid.uuid4()),
            "version": ver,
            "title": body.get("title", f"Krexion {ver}"),
            "notes": body.get("notes", ""),
            "severity": body.get("severity", "recommended"),  # info|recommended|critical
            "download_url": body.get("download_url", ""),
            "min_required_version": body.get("min_required_version", ""),
            "published": bool(body.get("published", True)),
            "created_at": _now_iso(),
            "created_by": admin.get("email") or admin.get("id"),
        }
        await _db.app_releases.insert_one(doc)
        doc.pop("_id", None)
        # ── 2026-05: Sync VERSION file with the published release so the
        # customer's local install shows the SAME number after pulling
        # the repo. Without this the file stays at whatever was last
        # committed (e.g. 1.0.4) and customers always see an outdated
        # version even after admin clicks Quick Publish.
        if doc.get("published"):
            try:
                VERSION_FILE.write_text(ver + "\n", encoding="utf-8")
                logger.info(f"VERSION file updated to {ver}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not update VERSION file: {e}")
        return doc

    @router.get("/api/admin/releases")
    async def list_releases(admin: dict = Depends(get_admin_dep)):
        items = await _db.app_releases.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
        # 2026-01: DB-aware version (newest of file + latest published)
        # so the admin panel always shows the freshly-published version
        # even when the static VERSION file is stale.
        return {"releases": items, "current_version": await _displayed_current_version()}

    @router.get("/api/admin/releases/auto-detect")
    async def auto_detect(admin: dict = Depends(get_admin_dep)):
        """Detect whether a new release should be published.

        Returns a suggested next version + draft release notes built from
        git activity since the last published release.  The admin can
        review and click "Publish release" — nothing is created here.

        Notes are built from real commit subjects when available; if the
        history is dominated by platform auto-checkpoints (no meaningful
        subjects) we fall back to a smart summary of changed files
        grouped by area (Pages, Components, Backend modules, etc.).
        """
        last_rel = await _db.app_releases.find_one(
            {"published": True}, sort=[("created_at", -1)], projection={"_id": 0}
        )
        since_iso = last_rel["created_at"] if last_rel else None
        commits = _collect_commits_since(since_iso, limit=100)
        files_changed = _collect_changed_files_since(since_iso)

        base_ver = (last_rel["version"] if last_rel else current_version()) or "0.0.0"
        suggested_version = _bump_patch(base_ver)

        # Ensure suggested version doesn't collide with an existing one
        # (e.g. unpublished draft). If it does, keep bumping.
        existing = await _db.app_releases.find({}, {"_id": 0, "version": 1}).to_list(500)
        existing_versions = {r.get("version") for r in existing}
        while suggested_version in existing_versions:
            suggested_version = _bump_patch(suggested_version)

        meaningful_commits = [c for c in commits if not c.get("is_auto")]
        notes_source = "none"
        notes = ""
        if meaningful_commits:
            notes = "\n".join(f"- {c['subject']}" for c in meaningful_commits)
            notes_source = "commits"
        elif files_changed:
            bullets, _grp = _summarize_file_changes(files_changed)
            if bullets:
                notes = "\n".join(bullets)
                notes_source = "files"

        # A release is "needed" if there is any change at all since the
        # last published version — either real commits or file changes.
        needs_release = bool(commits) or bool(files_changed)

        if needs_release:
            change_count = len(meaningful_commits) if meaningful_commits else len(files_changed)
            unit = "change" if meaningful_commits else "file"
            title = f"Krexion {suggested_version} — {change_count} {unit}{'s' if change_count != 1 else ''} updated"
        else:
            title = f"Krexion {suggested_version}"

        return {
            "needs_release": needs_release,
            "last_release_version": last_rel["version"] if last_rel else None,
            "last_release_date": last_rel["created_at"] if last_rel else None,
            "suggested_version": suggested_version,
            "suggested_title": title,
            "suggested_notes": notes,
            "suggested_severity": "recommended",
            "commit_count": len(commits),
            "meaningful_commit_count": len(meaningful_commits),
            "files_changed_count": len(files_changed),
            "notes_source": notes_source,  # "commits" | "files" | "none"
            "commits": commits[:50],
            "current_version": current_version(),
        }

    @router.post("/api/admin/releases/quick-publish")
    async def quick_publish(admin: dict = Depends(get_admin_dep)):
        """One-click publish — bundles auto-detect + create release.

        Behaviour:
          1. Run the same change-detection logic as `auto-detect`.
          2. Use the suggested version / title / notes when available.
          3. If no git history is available on this host (the typical
             VPS rsync deployment excludes the `.git` directory for
             security), gracefully fall back to bumping the patch
             component of the last published version and use a
             timestamped generic title + notes — so the admin still
             gets a single-click publish and customers get notified.
          4. Create the release with `published=true` immediately.

        Returns the inserted release document on success.
        """
        # Step 1 — change detection (same as auto-detect)
        last_rel = await _db.app_releases.find_one(
            {"published": True}, sort=[("created_at", -1)], projection={"_id": 0}
        )
        since_iso = last_rel["created_at"] if last_rel else None
        commits = _collect_commits_since(since_iso, limit=100)
        files_changed = _collect_changed_files_since(since_iso)

        base_ver = (last_rel["version"] if last_rel else current_version()) or "0.0.0"
        suggested_version = _bump_patch(base_ver)

        # Avoid collisions with any existing (draft or published) release
        existing = await _db.app_releases.find({}, {"_id": 0, "version": 1}).to_list(500)
        existing_versions = {r.get("version") for r in existing}
        while suggested_version in existing_versions:
            suggested_version = _bump_patch(suggested_version)

        meaningful_commits = [c for c in commits if not c.get("is_auto")]

        # Build title + notes — prefer real commit history, else fall
        # back to a file-summary, else fall back to a generic "hotfix"
        # message so quick-publish ALWAYS produces a usable release
        # (works on VPS hosts where .git is intentionally excluded
        # from the rsync deployment).
        if meaningful_commits:
            notes = "\n".join(f"- {c['subject']}" for c in meaningful_commits)
            change_count = len(meaningful_commits)
            unit = "change"
            title = f"v{suggested_version} — {change_count} {unit}{'s' if change_count != 1 else ''} updated"
        elif files_changed:
            bullets, _grp = _summarize_file_changes(files_changed)
            notes = "\n".join(bullets) if bullets else f"- Updated {len(files_changed)} file(s)"
            change_count = len(files_changed)
            title = f"v{suggested_version} — {change_count} file{'s' if change_count != 1 else ''} updated"
        else:
            # Generic fallback when no git history is available locally.
            # The release is still useful: it bumps the version, fires
            # the customer-side update banner, and triggers each
            # customer PC to pull the latest code from GitHub.
            notes = (
                "Latest updates, performance improvements, and bug fixes from "
                "the main branch. Install this update to pull the newest code "
                "and rebuild your local services."
            )
            title = f"v{suggested_version} — Update available"

        # Step 2 — create + publish immediately
        doc = {
            "id": str(uuid.uuid4()),
            "version": suggested_version,
            "title": title,
            "notes": notes,
            "severity": "recommended",
            "download_url": "",
            "min_required_version": "",
            "published": True,
            "created_at": _now_iso(),
            "created_by": admin.get("email") or admin.get("id"),
            "source": "quick-publish",
            "auto_detected": {
                "commit_count": len(commits),
                "meaningful_commit_count": len(meaningful_commits),
                "files_changed_count": len(files_changed),
                "used_fallback": not (meaningful_commits or files_changed),
            },
        }
        await _db.app_releases.insert_one(doc)
        doc.pop("_id", None)
        logger.info(
            f"[releases] quick-publish v{suggested_version} by "
            f"{doc['created_by']} (fallback={doc['auto_detected']['used_fallback']})"
        )
        return {
            "ok": True,
            "release": doc,
            "message": (
                f"Release v{suggested_version} published — all customers will "
                "be notified within 10 minutes."
            ),
        }

    @router.patch("/api/admin/releases/{rid}")
    async def patch_release(rid: str, body: dict, admin: dict = Depends(get_admin_dep)):
        allowed = {"title", "notes", "severity", "download_url", "published", "min_required_version"}
        upd = {k: v for k, v in body.items() if k in allowed}
        if not upd:
            raise HTTPException(400, "No editable fields supplied")
        upd["updated_at"] = _now_iso()
        r = await _db.app_releases.update_one({"id": rid}, {"$set": upd})
        if r.matched_count == 0:
            raise HTTPException(404, "Release not found")
        return {"updated": True}

    @router.delete("/api/admin/releases/{rid}")
    async def delete_release(rid: str, admin: dict = Depends(get_admin_dep)):
        r = await _db.app_releases.delete_one({"id": rid})
        if r.deleted_count == 0:
            raise HTTPException(404, "Release not found")
        return {"deleted": True}

    return router


def _build_customer_endpoints(get_user_dep):
    """Register customer-facing endpoints."""
    router = APIRouter(tags=["releases-customer"])

    @router.get("/api/system/version")
    async def get_version():
        """Public — returns the running version of this install."""
        # 2026-01: DB-aware so the displayed version survives static
        # VERSION-file resets caused by container restarts / git pulls.
        mode = (os.environ.get("KREXION_MODE") or "local").lower()
        if mode == "native":
            backend_version = current_version()
        else:
            backend_version = await _displayed_current_version()
        payload = {
            "version": backend_version,
            "mode": mode,
        }
        try:
            from frontend_bundle import frontend_sync_status

            sync = frontend_sync_status()
            payload["frontend_version"] = sync.get("frontend_version")
            payload["frontend_sync_needed"] = bool(sync.get("frontend_sync_needed"))
        except Exception:  # noqa: BLE001
            pass
        return payload

    @router.post("/api/system/sync-frontend")
    async def sync_frontend_bundle():
        """Native-only — replace stale bundled UI from the cloud CDN zip."""
        mode = (os.environ.get("KREXION_MODE") or "local").lower()
        if mode != "native":
            raise HTTPException(404, "Frontend sync is only available on native installs")

        import asyncio
        from frontend_bundle import frontend_sync_status, sync_frontend_from_cloud

        status = frontend_sync_status()
        if not status.get("frontend_sync_needed"):
            return {"ok": True, "already_current": True, "version": status.get("backend_version")}

        result = await asyncio.to_thread(sync_frontend_from_cloud)
        if not result.get("ok"):
            raise HTTPException(502, result)
        return result

    # v1.0.11 fix: filter that excludes orphan release records (those
    # without a real GitHub Releases .exe URL). Pre-1.0.11 the cloud DB
    # had a "v1.1.20" record marked as published from a prior session
    # that was never actually built / released - it kept poisoning
    # the cloud dashboard's "Update available" badge with a phantom
    # version. We require the download_url to be a github.com
    # /releases/download/.../*.exe URL before considering the row.
    _REAL_RELEASE_FILTER = {
        "published": True,
        "download_url": {"$regex": r"^https?://[^\s]+/releases/download/[^\s]+\.exe(\?|$)"},
    }

    @router.get("/api/system/latest-version")
    async def latest_version(
        x_krexion_license: Optional[str] = Header(None),
        current: Optional[str] = Query(None),
    ):
        """License-authenticated - returns the latest published release plus
        whether the caller is behind.

        Pass ``?current=X.Y.Z`` for the installer's local version so
        update_available is correct even when cloud VERSION already
        matches the published release.
        """
        await _validate_license(x_krexion_license)
        file_ver = current_version()
        client_ver = (current or "").strip().lstrip("vV") or None
        baseline = client_ver or file_ver
        rel = await _db.app_releases.find_one(
            _REAL_RELEASE_FILTER, sort=[("created_at", -1)], projection={"_id": 0}
        )
        if not rel:
            # Fall back to cloud file VERSION as "latest" signal
            if client_ver and is_newer(file_ver, client_ver):
                return {
                    "current": baseline,
                    "latest": {"version": file_ver, "title": f"Krexion {file_ver}"},
                    "update_available": True,
                }
            return {"current": baseline, "latest": None, "update_available": False}
        return {
            "current": baseline,
            "latest": rel,
            "update_available": is_newer(rel["version"], baseline),
        }

    @router.get("/api/system/public-latest")
    async def public_latest(current: Optional[str] = Query(None)):
        """No-auth lite endpoint for the Local PC Dashboard banner.

        Pass ``?current=X.Y.Z`` = the customer's *installed* version so
        ``update_available`` compares against their PC — not the cloud
        VERSION file. After a release is published, cloud VERSION ==
        latest, so comparing against cloud alone always hid updates
        from every customer still on an older Setup.exe.

        Does not expose the download URL (installer goes through
        license download / CDN).
        """
        rel = await _db.app_releases.find_one(
            _REAL_RELEASE_FILTER,
            sort=[("created_at", -1)],
            projection={"_id": 0, "version": 1, "title": 1, "severity": 1, "created_at": 1, "notes": 1},
        )
        # Cloud file VERSION (what just shipped to VPS) — useful when
        # admin hasn't Quick-Published a DB row yet but CDN already
        # has Krexion-Setup-latest.exe matching this build.
        file_ver = current_version()
        client_ver = (current or "").strip().lstrip("vV") or None

        # Prefer a real published release; fall back to cloud file ver.
        latest_ver = None
        latest_payload = None
        if rel and rel.get("version"):
            latest_ver = str(rel["version"]).strip().lstrip("vV")
            latest_payload = rel
        elif file_ver and file_ver != "0.0.0":
            latest_ver = file_ver.lstrip("vV")
            latest_payload = {
                "version": latest_ver,
                "title": f"Krexion {latest_ver}",
                "severity": "normal",
                "notes": "Latest build on krexion.com",
            }

        # Baseline for "are YOU behind?": client's installed version
        # when provided; otherwise cloud file (legacy callers).
        # Never use _displayed_current_version() here — that returns
        # the published release itself and makes update_available
        # permanently false after every successful publish.
        baseline = client_ver or file_ver
        available = bool(latest_ver) and is_newer(latest_ver, baseline)
        return {
            "current": baseline,
            "cloud": file_ver,
            "latest": latest_payload,
            "update_available": available,
        }

    @router.get("/api/system/installer-info")
    async def installer_info():
        """No-auth — tells the public Download page whether a native
        Windows installer (.exe) is available and how to label the
        download button (size, version, filename).

        Returns:
          {
            "kind": "native-exe" | "legacy-zip",
            "version": "1.0.5",
            "url": null,            # never exposed — must go through /api/license/download-installer/{key}
            "size_bytes": ...,      # optional, only when admin set it
            "min_windows": "Windows 10 64-bit",
          }
        """
        # Cloud VPS deploy always updates backend/VERSION — that is the
        # download-page source of truth (CDN *-latest.exe mirrors match).
        file_ver = current_version().strip().lstrip("vV")
        if file_ver and file_ver != "0.0.0":
            size_bytes = None
            released_at = None
            try:
                if _db is not None:
                    rel = await _db.app_releases.find_one(
                        {"published": True, "version": file_ver},
                        projection={
                            "_id": 0,
                            "installer_size_bytes": 1,
                            "created_at": 1,
                            "updated_at": 1,
                        },
                    )
                    if rel:
                        size_bytes = rel.get("installer_size_bytes") or None
                        released_at = rel.get("updated_at") or rel.get("created_at")
            except Exception:  # noqa: BLE001
                pass
            return {
                "kind": "native-exe",
                "version": file_ver,
                "size_bytes": size_bytes,
                "min_windows": "Windows 10 64-bit",
                "released_at": released_at,
            }
        # Legacy fallback when VERSION missing (should not happen on cloud).
        try:
            rel = await _db.app_releases.find_one(
                {"published": True, "download_url": {"$regex": r"\.exe(\?|$)"}},
                sort=[("created_at", -1)],
                projection={"_id": 0, "version": 1, "installer_size_bytes": 1, "created_at": 1},
            )
        except Exception:  # noqa: BLE001
            rel = None
        if rel:
            return {
                "kind": "native-exe",
                "version": rel.get("version") or "1.0.0",
                "size_bytes": rel.get("installer_size_bytes") or None,
                "min_windows": "Windows 10 64-bit",
                "released_at": rel.get("created_at"),
            }
        local = await _displayed_current_version()
        return {
            "kind": "legacy-zip",
            "version": local or "1.0.0",
            "size_bytes": None,
            "min_windows": "Windows 10 64-bit",
            "released_at": None,
        }

    @router.post("/api/system/sync-deploy-release")
    async def sync_deploy_release(request: Request):
        """Internal — called by VPS deploy after health check.

        Localhost-only so the public internet cannot forge release rows.
        """
        client = (request.client.host if request.client else "") or ""
        allowed = client in ("127.0.0.1", "::1", "localhost") or client.startswith(
            ("172.", "10.", "192.168.")
        )
        if not allowed:
            raise HTTPException(403, "sync-deploy-release is localhost-only")
        return await sync_deployed_release_record()

    @router.post("/api/system/install-update")
    async def trigger_update(request: Request, user: dict = Depends(get_user_dep)):
        """Customer clicks Update → flag is written so the host updater
        rebuilds containers.

        Three modes:
          - LOCAL install: writes flag directly (original behaviour)
          - CLOUD edge (krexion.com): bridges the call to the user's local
            PC via the bridge_module, so the customer never has to leave
            krexion.com or open localhost.
          - LOCAL receiving a bridge-relayed call: writes flag directly
            (recognised via X-Krexion-Bridge-Job header).
        """
        mode = (os.environ.get("KREXION_MODE") or "local").lower()
        is_bridge_relay = bool(request.headers.get("X-Krexion-Bridge-Job"))

        # 2026-07 fix — the admin check used to only happen on the LOCAL
        # execution path, so a non-admin sub-user on krexion.com could
        # trigger a container rebuild on their parent's PC by hitting
        # this endpoint (cloud bridge relay bypassed the admin gate).
        # We now enforce is_admin BEFORE the bridge relay too.
        if not user.get("is_admin"):
            raise HTTPException(403, "Only the admin user can trigger updates")

        if mode != "local" and not is_bridge_relay:
            # We're on the cloud edge. Bridge the call to the user's local PC.
            try:
                from bridge_module import enqueue_bridge_job  # local import to avoid circular load
            except Exception:
                raise HTTPException(503, "Self-update bridge unavailable on this server")
            return await enqueue_bridge_job(
                user, "system/self-update", {},
                wait_for_result=True, wait_timeout=25,
            )

        try:
            UPDATE_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "requested_at": _now_iso(),
                "requested_by": user.get("email") or user.get("id"),
                "current_version": current_version(),
                "via_bridge": is_bridge_relay,
            }
            UPDATE_FLAG_FILE.write_text(json.dumps(payload), encoding="utf-8")
            logger.info(f"[update] flag written: {UPDATE_FLAG_FILE} by {payload['requested_by']} bridge={is_bridge_relay}")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"Could not write update flag: {e}")
        return {
            "ok": True,
            "flag_path": str(UPDATE_FLAG_FILE),
            "message": (
                "Update requested. The host updater will pull the new release "
                "and rebuild containers within 60 seconds. Krexion will be "
                "briefly unavailable during the swap."
            ),
        }

    return router
