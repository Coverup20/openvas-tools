#!/usr/bin/env python3
"""
greenbone_manage_job01_weekly.py - Weekly full DR backup manager (job01)

Creates a full Greenbone/OpenVAS backup with PostgreSQL dump and Docker
volumes, then uploads to cloud via rclone. Enforces local and cloud
retention.

Usage:
  python3 greenbone_manage_job01_weekly.py [--full] [--upload] [--dry-run]

Defaults:
  BACKUP_DIR=/var/backups/greenbone
  RETENTION_LOCAL=4
  RETENTION_CLOUD=4
  RCLONE_REMOTE=do:testmonbck
  RCLONE_PATH=greenbone-backups/job01-bi-weekly

Version: 0.1.0
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List


VERSION = "0.1.0"


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}")


def err(msg: str) -> None:
    print(f"[{ts()}] ERROR: {msg}", file=sys.stderr)


def discover_backups(backup_dir: Path) -> List[Path]:
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("greenbone-full-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)


def local_retention(backup_dir: Path, keep: int, dry_run: bool) -> None:
    backups = discover_backups(backup_dir)
    if not backups:
        return
    delete = backups[keep:]
    log(f"Local retention: keep={min(len(backups), keep)} delete={len(delete)}")
    for p in delete:
        if dry_run:
            log(f"  [DRY-RUN] Would delete: {p.name}")
        else:
            p.unlink(missing_ok=True)
            for ext in (".metadata.json", ".sha256", ".restore.md"):
                side = p.with_suffix("")
                side = side.with_suffix(ext)
                side.unlink(missing_ok=True)


def cloud_retention(remote_full: str, keep: int, dry_run: bool) -> None:
    r = run(["rclone", "lsjson", remote_full])
    if r.returncode != 0 or not r.stdout:
        return
    try:
        items = json.loads(r.stdout)
    except Exception:
        return
    objs = [o for o in items if isinstance(o, dict) and o.get("Name", "").startswith("greenbone-full-")]
    objs.sort(key=lambda o: o.get("ModTime", ""), reverse=True)
    delete = objs[keep:]
    log(f"Cloud retention: keep={min(len(objs), keep)} delete={len(delete)}")
    for o in delete:
        name = o.get("Name")
        if not name:
            continue
        if dry_run:
            log(f"  [DRY-RUN] Would delete: {remote_full}/{name}")
        else:
            run(["rclone", "deletefile", f"{remote_full}/{name}"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly full DR backup manager (job01)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--full", action="store_true", default=True)
    ap.add_argument("--backup-dir", default=os.environ.get("BACKUP_DIR", "/var/backups/greenbone"))
    ap.add_argument("--retention-local", type=int, default=int(os.environ.get("RETENTION_LOCAL", "2")))
    ap.add_argument("--retention-cloud", type=int, default=int(os.environ.get("RETENTION_CLOUD", "2")))
    ap.add_argument("--rclone-remote", default=os.environ.get("RCLONE_REMOTE", "do:testmonbck"))
    ap.add_argument("--rclone-path", default=os.environ.get("RCLONE_PATH", "greenbone-backups/job01-bi-weekly"))
    args = ap.parse_args()

    backup_dir = Path(args.backup_dir)
    remote_full = f"{args.rclone_remote}/{args.rclone_path}"

    # Invoke core backup with --full
    script = Path(__file__).with_name("greenbone_backup.py")
    if not script.exists():
        err(f"Core script not found: {script}")
        return 1

    cmd = [str(script), "--backup-base-dir", str(backup_dir), "--full",
           "--rclone-remote", args.rclone_remote, "--rclone-path", args.rclone_path]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.upload:
        cmd.append("--upload")
    if args.no_upload:
        cmd.append("--no-upload")

    log("Running full DR backup...")
    r = run(cmd)
    if r.returncode != 0:
        err(f"Backup failed: {r.stderr.strip()}")
        return 1
    log("Backup completed.")

    # Retention
    local_retention(backup_dir, args.retention_local, args.dry_run)

    if args.upload and not args.no_upload and os.environ.get("GREENBONE_BACKUP_UPLOAD") == "1":
        cloud_retention(remote_full, args.retention_cloud, args.dry_run)
    else:
        log("Cloud retention: skipped (upload gate disabled)")

    log("Job01 weekly manager completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
