#!/usr/bin/env python3
"""
greenbone_setup_do.py - Configure and validate DigitalOcean Spaces rclone remote.

Adapted from the Checkmk backup model (checkmk_rclone_space_dyn.py).
Validates that rclone config exists, remote 'do' is configured, and
target 'do:testmonbck' is accessible.  Never prints secrets.
Returns non-zero if validation fails.

Usage:
  python3 greenbone_setup_do.py                           # interactive
  python3 greenbone_setup_do.py --validate                 # read-only check
  python3 greenbone_setup_do.py --validate --remote do:bucket

Safety:
  - Secrets are never printed or logged.
  - No backup or upload is performed.

Version: 0.2.0
Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import sys

from greenbone_backup.command import run
from greenbone_backup.config import default_rclone_config
from greenbone_backup.logging_utils import log, err
from greenbone_backup.rclone import (
    config_path_resolved,
    rclone_installed,
    rclone_version,
    validate_rclone_config,
    test_remote,
    prompt_and_create_remote,
)


VERSION = "0.2.0"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Configure and validate DigitalOcean Spaces rclone remote",
    )
    ap.add_argument("--remote", default="do:testmonbck",
                    help="Remote name and bucket (default: do:testmonbck)")
    ap.add_argument("--rclone-config", default=None,
                    help="Path to rclone.conf (default: auto-detect)")
    ap.add_argument("--validate", action="store_true",
                    help="Read-only validation (no interactive setup)")
    ap.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")
    args = ap.parse_args()

    rclone_config = config_path_resolved(args.rclone_config)
    remote_name = args.remote.split(":", 1)[0] if ":" in args.remote else "do"

    print(f"\n=== greenbone_setup_do.py v{VERSION} ===")
    print(f"Remote: {args.remote}")
    print(f"Config: {rclone_config}\n")

    if not rclone_installed():
        err("rclone is not installed.")
        err("Install: curl https://rclone.org/install.sh | sudo bash")
        return 1

    log(f"rclone: {rclone_version()}")
    rclone_config.parent.mkdir(parents=True, exist_ok=True)

    if args.validate:
        # Read-only validation mode
        log("Running read-only validation...")
        valid = validate_rclone_config(rclone_config, remote_name, args.remote)

        if not rclone_config.exists():
            err("FAIL: rclone config not found.")
            return 1

        if not validate_rclone_config(rclone_config, remote_name, args.remote):
            err("FAIL: rclone remote validation failed.")
            return 1

        if not test_remote(rclone_config, args.remote):
            err("FAIL: remote access test failed.")
            return 1

        log("PASS: All rclone checks passed.")
        return 0

    # Interactive setup mode
    success = prompt_and_create_remote(rclone_config, args.remote)

    if not success:
        err("FAIL: rclone setup did not complete successfully.")
        err("Upload gate remains disabled.")
        return 1

    log("PASS: rclone setup completed successfully.")
    log(f"Upload target: {args.remote}/greenbone-backups/job00-daily")
    log("")
    log("To enable upload, set GREENBONE_BACKUP_UPLOAD=1 in /etc/greenbone-backup/greenbone-backup.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
