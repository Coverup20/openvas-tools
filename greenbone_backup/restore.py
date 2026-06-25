"""restore.py - Restore logic for Greenbone backup archives.

Safety-gated: requires explicit --confirm or --force.  Detects existing
Greenbone data before restore.  Refuses destructive operations unless
all gates are satisfied.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import subprocess
import tarfile
import time
from pathlib import Path
from typing import List, Optional

from .command import run, CommandError
from .logging_utils import log, err, warn


def find_local_archives(backup_dir: Path, pattern: str = "greenbone-full-*.tar.gz") -> List[Path]:
    """Return sorted list of backup archives (newest first)."""
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob(pattern),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def list_cloud_archives(rclone_remote: str, rclone_path: str,
                         prefix: str = "greenbone-full-") -> List[dict]:
    """List backup archives in DO Spaces via rclone lsjson.

    Returns empty list if rclone is not available or remote fails.
    """
    try:
        r = run(["rclone", "lsjson", f"{rclone_remote}/{rclone_path}"],
                check=False, timeout=30)
        if r.returncode != 0 or not r.stdout:
            return []
        items = json.loads(r.stdout)
        return [o for o in items if isinstance(o, dict) and o.get("Name", "").startswith(prefix)]
    except Exception:
        return []


def check_existing_greenbone(compose_file: Path) -> bool:
    """Check if Greenbone is already deployed and running.

    Returns True if docker compose ps shows running containers.
    This is used to warn before destructive restore.
    """
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "ps", "--all"],
                check=False, timeout=30)
        if r.returncode == 0 and r.stdout:
            lines = [ln for ln in r.stdout.splitlines() if "Up" in ln]
            return len(lines) > 0
    except Exception:
        pass
    return False


def restore_volume(volume_name: str, archive_path: Path, dry_run: bool = False) -> bool:
    """Restore a Docker volume from a tar archive.

    Creates a pre-restore backup of the current volume state.
    """
    log(f"Restoring volume: {volume_name} ...")
    if dry_run:
        log(f"  [DRY-RUN] Would restore {archive_path.name} to volume {volume_name}")
        return True

    # Pre-restore backup
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_name = f"{volume_name}.pre-restore.{ts}.tar.gz"
    r = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{volume_name}:/volume:ro",
         "-v", f"{archive_path.parent}:/backup",
         "busybox:latest", "tar", "czf", f"/backup/{backup_name}", "-C", "/volume", "."],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300,
    )
    if r.returncode == 0:
        log(f"  Pre-restore backup saved: {backup_name}")

    # Restore
    r = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{volume_name}:/volume",
         "-v", f"{archive_path}:/backup/archive.tar.gz:ro",
         "busybox:latest", "tar", "xzf", "/backup/archive.tar.gz", "-C", "/volume"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300,
    )
    if r.returncode == 0:
        log(f"  Restored: {volume_name}")
        return True
    err(f"  Failed to restore {volume_name}: {r.stderr[:200]}")
    return False


def restore_database(compose_file: Path, sql_dump: Path, dry_run: bool = False) -> bool:
    """Restore the gvmd PostgreSQL database from a SQL dump."""
    log("Restoring PostgreSQL database...")
    if dry_run:
        log("  [DRY-RUN] Would restore database from gvmd-database.sql")
        return True
    if not sql_dump.exists():
        err("  Database dump not found in archive")
        return False

    # Ensure pg-gvm is running
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
                 "pg_isready", "-U", "gvmd"], check=False, timeout=30)
        if r.returncode != 0:
            log("  Starting pg-gvm container...")
            run(["docker", "compose", "-f", str(compose_file), "up", "-d", "pg-gvm"],
                check=True, timeout=120)
            time.sleep(10)
    except Exception as e:
        err(f"  Database connection check failed: {e}")
        return False

    # Restore via psql
    sql_text = sql_dump.read_text(encoding="utf-8")
    for user in ("gvmd", "postgres"):
        try:
            r = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
                 "psql", "-U", user, "-d", "gvmd"],
                input=sql_text, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=600,
            )
            if r.returncode == 0:
                log("  Database restored.")
                return True
            log(f"  psql as {user} failed (trying next user...): {r.stderr[:200]}")
        except Exception as e:
            log(f"  psql as {user} error: {e}")

    err("  Database restore failed after trying all users.")
    return False


def extract_archive(archive_path: Path, dest_dir: Path, dry_run: bool = False) -> bool:
    """Extract a backup archive to a destination directory."""
    if dry_run:
        log(f"  [DRY-RUN] Would extract {archive_path.name} to {dest_dir}")
        return True
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=dest_dir)
        log(f"  Extracted: {archive_path.name} -> {dest_dir}")
        return True
    except Exception as e:
        err(f"  Extraction failed: {e}")
        return False
