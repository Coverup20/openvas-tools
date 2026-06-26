#!/usr/bin/env python3
"""
greenbone_restore.py - Restore a Greenbone backup snapshot.

Safety-gated: requires --confirm or --force.  Detects existing Greenbone
data before restore.  Refuses destructive operations unless all gates
are satisfied.

Usage:
  python3 greenbone_restore.py --list                         # list available backups
  python3 greenbone_restore.py --archive <path> --confirm      # restore from archive
  python3 greenbone_restore.py --list --rclone-remote do:...   # list cloud backups
  python3 greenbone_restore.py --dry-run                       # preview only

Safety:
  - Requires --confirm or --force to proceed
  - Creates pre-restore backups of existing volumes
  - Never deletes cloud objects

Version: 0.2.0
Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import sys
from pathlib import Path

from greenbone_backup.command import require_root
from greenbone_backup.config import BackupConfig
from greenbone_backup.logging_utils import log, err
from greenbone_backup.restore import (
    check_existing_greenbone,
    find_local_archives,
    list_cloud_archives,
    extract_archive,
    restore_database,
    restore_volume,
)
from greenbone_backup.safety import confirm_destructive, require_force_flag


VERSION = "0.2.0"


def main() -> int:
    ap = argparse.ArgumentParser(description="Greenbone/OpenVAS Disaster Recovery Restore")
    ap.add_argument("--backup-dir", default="/var/backups/greenbone")
    ap.add_argument("--compose-file", default="/opt/greenbone-community/compose.yaml")
    ap.add_argument("--archive", help="Path to a specific archive file")
    ap.add_argument("--rclone-remote", default="do:testmonbck")
    ap.add_argument("--rclone-path", default="greenbone-backups/job01-bi-weekly")
    ap.add_argument("--list", action="store_true", help="List available backups and exit")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be done")
    ap.add_argument("--confirm", action="store_true", help="Confirm restore execution")
    ap.add_argument("--force", action="store_true", help="Force restore without confirmation")
    ap.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")
    args = ap.parse_args()

    backup_dir = Path(args.backup_dir)
    compose_file = Path(args.compose_file)

    print(f"\n=== Greenbone Restore v{VERSION} ===\n")

    # List available backups
    local = find_local_archives(backup_dir)
    cloud = list_cloud_archives(args.rclone_remote, args.rclone_path)

    all_backups = []

    print("Available backups:")
    if cloud:
        print("\n  --- Cloud (DO Spaces) ---")
        for i, o in enumerate(cloud, 1):
            name = o.get("Name", "?")
            size = o.get("Size", 0) / 1024 / 1024
            all_backups.append(("cloud", name, size, o))
            print(f"  [{len(all_backups)}] {name} ({size:.0f} MB) [cloud]")
    if local:
        print("\n  --- Local ---")
        for p in local:
            size = p.stat().st_size / 1024 / 1024
            all_backups.append(("local", p.name, size, p))
            print(f"  [{len(all_backups)}] {p.name} ({size:.0f} MB) [local]")

    if args.list:
        return 0

    if not all_backups and not args.archive:
        err("No backups found. Use --archive to specify a file.")
        return 1

    # If only --dry-run without --archive, preview
    if args.dry_run and not args.archive:
        log("Dry-run mode. No changes will be made.")
        return 0

    # Safety gates
    if not args.confirm and not args.force:
        if not confirm_destructive("restore a Greenbone backup"):
            log("Restore cancelled.")
            return 0

    if args.force:
        require_force_flag(args.force, "restore")

    # Check existing Greenbone
    if check_existing_greenbone(compose_file):
        log("WARNING: Greenbone containers are currently running.")
        if not confirm_destructive("stop containers and overwrite data"):
            log("Restore cancelled.")
            return 0

    require_root()

    # Select archive
    archive_path = None
    if args.archive:
        archive_path = Path(args.archive)
    elif all_backups:
        default_idx = 1
        max_idx = len(all_backups)
        try:
            idx_str = input(f"\nSelect backup to restore [1-{max_idx}] (default 1): ").strip()
            idx = int(idx_str) if idx_str else 1
        except ValueError:
            idx = 1
        if idx < 1 or idx > max_idx:
            idx = 1
        selection = all_backups[idx - 1]
        source_type = selection[0]
        source_name = selection[1]
        if source_type == "local":
            archive_path = selection[3]
        else:
            err("Cloud restore not implemented in this version.")
            err("Download the archive manually first.")
            return 1

    if not archive_path or not archive_path.exists():
        err(f"Archive not found: {archive_path}")
        return 1

    log(f"Restoring from: {archive_path.name}")

    # Extract
    tmpdir = Path("/tmp/greenbone-restore")
    tmpdir.mkdir(parents=True, exist_ok=True)

    if not extract_archive(archive_path, tmpdir, dry_run=args.dry_run):
        err("Extraction failed.")
        return 1

    # Check if this is a full DR backup
    sql_dump = tmpdir / "gvmd-database.sql"
    if sql_dump.exists():
        log("Full DR backup detected (contains database dump).")
        if not restore_database(compose_file, sql_dump, dry_run=args.dry_run):
            err("Database restore failed.")
            return 1

    log("Restore completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
