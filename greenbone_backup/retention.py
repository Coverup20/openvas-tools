"""retention.py - Local and cloud retention policy enforcement.

Keeps the newest N backup archives locally and/or in cloud storage.
Deletes older entries beyond the retention limit.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
from pathlib import Path
from typing import List

from .command import run, CommandError
from .logging_utils import log, err


def discover_local_backups(backup_dir: Path, glob_pattern: str) -> List[Path]:
    """Return backup archives sorted newest-first."""
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(glob_pattern),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def apply_local_retention(backup_dir: Path, glob_pattern: str,
                           keep: int, dry_run: bool = False) -> None:
    """Delete all but the newest `keep` backup archives locally.

    Also removes sidecar files (.metadata.json, .sha256, .restore.md).
    """
    backups = discover_local_backups(backup_dir, glob_pattern)
    if not backups:
        log("No backups found for local retention.")
        return

    to_keep = backups[:keep]
    to_delete = backups[keep:]
    log(f"Local retention: keep={len(to_keep)} delete={len(to_delete)} (limit={keep})")

    for p in to_delete:
        if dry_run:
            log(f"[DRY-RUN] Would delete local backup: {p.name}")
            continue
        try:
            p.unlink(missing_ok=True)
            # Remove sidecar files
            base = p.name
            # Strip .tar.gz or .tar suffix
            for ext in (".tar.gz", ".tar"):
                if base.endswith(ext):
                    base = base[: -len(ext)]
                    break
            for side_ext in (".metadata.json", ".sha256", ".restore.md"):
                sidecar = p.parent / f"{base}{side_ext}"
                sidecar.unlink(missing_ok=True)
            log(f"Deleted: {p.name}")
        except Exception as e:
            err(f"Unable to delete {p.name}: {e}")


def list_cloud_objects(rclone_remote: str, rclone_path: str) -> List[dict]:
    """List objects under the remote path using rclone lsjson.

    Returns empty list on any failure.
    """
    remote_full = f"{rclone_remote}/{rclone_path}"
    try:
        r = run(["rclone", "lsjson", remote_full], check=False, timeout=30)
        if r.returncode != 0 or not r.stdout:
            return []
        return json.loads(r.stdout)
    except Exception:
        return []


def apply_cloud_retention(rclone_remote: str, rclone_path: str,
                           prefix: str, keep: int,
                           dry_run: bool = False) -> None:
    """Delete all but the newest `keep` remote objects under a prefix.

    The prefix filters objects that belong to this backup series
    (e.g. 'greenbone-dr-' for config backups, 'greenbone-full-' for full).
    """
    remote_full = f"{rclone_remote}/{rclone_path}"
    objects = list_cloud_objects(rclone_remote, rclone_path)
    if not objects:
        log("Cloud retention: unable to list remote objects (skipping).")
        return

    # Filter by prefix
    items = [o for o in objects if isinstance(o, dict) and o.get("Name", "").startswith(prefix)]
    # Sort newest first
    items.sort(key=lambda o: o.get("ModTime", ""), reverse=True)

    to_keep = items[:keep]
    to_delete = items[keep:]
    log(f"Cloud retention under {remote_full}: keep={len(to_keep)} delete={len(to_delete)} (limit={keep})")

    for obj in to_delete:
        name = obj.get("Name")
        if not name:
            continue
        target = f"{remote_full}/{name}"
        if dry_run:
            log(f"[DRY-RUN] Would delete remote: {target}")
            continue
        try:
            r = run(["rclone", "deletefile", target], check=False, timeout=30)
            if r.returncode == 0:
                log(f"Deleted remote: {name}")
            else:
                err(f"Unable to delete remote {name}: {r.stderr.strip()[:200]}")
        except Exception as e:
            err(f"Unable to delete remote {name}: {e}")
