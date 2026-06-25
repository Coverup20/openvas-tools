#!/usr/bin/env python3
"""
greenbone_manage_job01_weekly.py - Weekly full DR backup manager (job01).

Orchestrates weekly full Greenbone DR backups:
  1. Invokes shared backup logic with --full (DB dump + Docker volumes)
  2. Applies local retention
  3. Optionally uploads to cloud (gated)
  4. Applies cloud retention

Usage:
  python3 greenbone_manage_job01_weekly.py                          # full backup, no upload
  python3 greenbone_manage_job01_weekly.py --upload                  # full backup + upload (gated)
  python3 greenbone_manage_job01_weekly.py --dry-run                 # preview only
  python3 greenbone_manage_job01_weekly.py --no-upload               # force no upload

Upload gates:
  --upload flag AND GREENBONE_BACKUP_UPLOAD=1 in env

Version: 0.2.0
Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import os
import sys
from pathlib import Path

from greenbone_backup.backup import run_backup
from greenbone_backup.command import require_root
from greenbone_backup.config import BackupConfig
from greenbone_backup.logging_utils import log, err
from greenbone_backup.retention import apply_local_retention, apply_cloud_retention
from greenbone_backup.rclone import validate_rclone_config, default_rclone_config


VERSION = "0.2.0"


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly full DR backup manager (job01)")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without making changes")
    ap.add_argument("--no-upload", action="store_true", help="Skip any upload operations")
    ap.add_argument("--upload", action="store_true", help="Enable upload (gated by env + rclone)")
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--rclone-remote", default=None)
    ap.add_argument("--retention-local", type=int, default=None)
    ap.add_argument("--retention-cloud", type=int, default=None)
    ap.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")
    args = ap.parse_args()

    require_root()

    overrides = {
        "RCLONE_PATH": "greenbone-backups/job01-bi-weekly",
        "RETENTION_LOCAL": "2",
        "RETENTION_CLOUD": "2",
    }
    if args.backup_dir:
        overrides["BACKUP_DIR"] = args.backup_dir
    if args.rclone_remote:
        overrides["RCLONE_REMOTE"] = args.rclone_remote
    if args.retention_local is not None:
        overrides["RETENTION_LOCAL"] = str(args.retention_local)
    if args.retention_cloud is not None:
        overrides["RETENTION_CLOUD"] = str(args.retention_cloud)

    cfg = BackupConfig.from_env(overrides=overrides)
    cfg.dry_run = args.dry_run

    # Upload gate
    should_upload = args.upload and not args.no_upload
    env_gate = os.environ.get("GREENBONE_BACKUP_UPLOAD", "") == "1" or cfg.upload_enabled

    if should_upload:
        if not env_gate:
            log("Upload requested but GREENBONE_BACKUP_UPLOAD is not set to 1. Skipping upload.")
            should_upload = False
        else:
            remote_name = cfg.rclone_remote.split(":")[0] if ":" in cfg.rclone_remote else "do"
            rclone_cfg = default_rclone_config()
            if not rclone_cfg.exists() or not validate_rclone_config(rclone_cfg, remote_name, cfg.rclone_remote):
                log("Rclone validation FAILED. Upload disabled.")
                should_upload = False

    cfg.upload_enabled = should_upload
    log(f"greenbone_manage_job01_weekly.py v{VERSION}")
    log(f"Upload: {'enabled' if should_upload else 'disabled'}")

    # Run the full backup
    rc = run_backup(cfg, full=True)
    if rc != 0:
        return rc

    # Local retention
    apply_local_retention(cfg.backup_dir, "greenbone-full-*.tar.gz",
                          cfg.retention_local, dry_run=args.dry_run)

    # Cloud retention
    if should_upload:
        apply_cloud_retention(cfg.rclone_remote, cfg.rclone_path,
                              prefix="greenbone-full-", keep=cfg.retention_cloud,
                              dry_run=args.dry_run)

    log("Job01 weekly manager completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
