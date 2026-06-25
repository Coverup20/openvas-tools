#!/usr/bin/env python3
"""
greenbone_do_backup.py - Create a Greenbone backup snapshot (config or full DR).

Creates a Checkmk-style backup with:
  - Local archive (tar.gz) with compose file, project files, inventory
  - Metadata JSON, SHA256 checksum, restore instructions sidecar files
  - Optional cloud upload via rclone (double-gated)

Usage:
  python3 greenbone_do_backup.py                          # config backup (no upload)
  python3 greenbone_do_backup.py --dry-run                # preview only
  python3 greenbone_do_backup.py --upload                 # with upload (gated by env)
  python3 greenbone_do_backup.py --full                   # full DR (DB dump + volumes)
  python3 greenbone_do_backup.py --full --upload           # full DR with upload

Upload gates:
  1. CLI flag: --upload must be passed
  2. Env gate: GREENBONE_BACKUP_UPLOAD=1 must be set
  3. Rclone gate: rclone config must exist and have valid remote

Version: 0.2.0
Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import os
import sys

from greenbone_backup.backup import run_backup
from greenbone_backup.command import require_root
from greenbone_backup.config import BackupConfig
from greenbone_backup.logging_utils import log
from greenbone_backup.rclone import validate_rclone_config, default_rclone_config


VERSION = "0.2.0"


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Greenbone/OpenVAS backup (config or full DR)")
    ap.add_argument("--dry-run", action="store_true", help="Print actions, no changes")
    ap.add_argument("--no-upload", action="store_true", help="Skip upload even if gated open")
    ap.add_argument("--upload", action="store_true", help="Enable upload (gated by env + rclone)")
    ap.add_argument("--full", action="store_true", help="Full DR backup (includes DB dump + Docker volumes)")
    ap.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")

    # Config overrides
    ap.add_argument("--greenbone-dir", default=None)
    ap.add_argument("--compose-file", default=None)
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--rclone-remote", default=None)
    ap.add_argument("--rclone-path", default=None)
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])

    # Build config from env, with CLI overrides
    overrides = {}
    if args.greenbone_dir:
        overrides["GREENBONE_DIR"] = args.greenbone_dir
    if args.compose_file:
        overrides["COMPOSE_FILE"] = args.compose_file
    if args.backup_dir:
        overrides["BACKUP_DIR"] = args.backup_dir
    if args.rclone_remote:
        overrides["RCLONE_REMOTE"] = args.rclone_remote
    if args.rclone_path:
        overrides["RCLONE_PATH"] = args.rclone_path

    cfg = BackupConfig.from_env(overrides=overrides if overrides else None)
    cfg.dry_run = args.dry_run

    # Upload gate logic
    should_upload = args.upload and not args.no_upload
    env_gate = os.environ.get("GREENBONE_BACKUP_UPLOAD", "") == "1" or cfg.upload_enabled

    if should_upload:
        if not env_gate:
            log("Upload requested but GREENBONE_BACKUP_UPLOAD is not set to 1.")
            log("Skipping upload. Set GREENBONE_BACKUP_UPLOAD=1 in env file to enable.")
            should_upload = False
        else:
            # Additional rclone validation gate before upload
            remote_name = cfg.rclone_remote.split(":")[0] if ":" in cfg.rclone_remote else "do"
            rclone_cfg = default_rclone_config()
            if not rclone_cfg.exists() or not validate_rclone_config(rclone_cfg, remote_name, cfg.rclone_remote):
                log("Rclone validation FAILED. Upload is disabled.")
                log(f"  Config: {rclone_cfg} (exists={rclone_cfg.exists()})")
                log(f"  Remote: {remote_name}")
                should_upload = False

    cfg.upload_enabled = should_upload

    log(f"greenbone_backup.py v{VERSION}")
    log(f"Backup type: {'full_dr' if args.full else 'config_inventory'}")
    log(f"Upload: {'enabled' if should_upload else 'disabled'}")

    require_root()
    return run_backup(cfg, full=args.full)


if __name__ == "__main__":
    sys.exit(main())
