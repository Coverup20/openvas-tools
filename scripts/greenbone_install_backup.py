#!/usr/bin/env python3
"""
greenbone_install_backup.py - Install the Greenbone backup system on a target host.

Python-native installer for the Greenbone backup system.
No Bash code paths remain.

Usage:
  python3 greenbone_install_backup.py --dry-run
  python3 greenbone_install_backup.py --install
  python3 greenbone_install_backup.py --install --configure-rclone
  python3 greenbone_install_backup.py --install --enable-timers
  python3 greenbone_install_backup.py --install --run-test-backup
  python3 greenbone_install_backup.py --install --run-test-backup --upload
  python3 greenbone_install_backup.py --upgrade-env

Default behavior (safe):
  - No timer enable
  - No backup run
  - No upload
  - No restore
  - No scan

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import sys
from pathlib import Path

from greenbone_backup.command import require_root
from greenbone_backup.install import install, upgrade_env_file
from greenbone_backup.logging_utils import log, err


VERSION = "0.2.0"


def parse_args(argv: argparse.Namespace) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Install Greenbone backup system (Python-native)",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s v{VERSION}")

    # Action flags
    ap.add_argument("--dry-run", action="store_true",
                    help="Print actions without making changes")
    ap.add_argument("--install", action="store_true",
                    help="Install/update the backup system")
    ap.add_argument("--upgrade-env", action="store_true",
                    help="Upgrade env file (fix UPLOAD gate)")

    # Install modifiers
    ap.add_argument("--configure-rclone", action="store_true",
                    help="Interactive rclone DO Spaces configuration")
    ap.add_argument("--enable-timers", action="store_true",
                    help="Enable and start systemd timers")
    ap.add_argument("--run-test-backup", action="store_true",
                    help="Run a test backup after install")
    ap.add_argument("--upload", action="store_true",
                    help="Allow upload during test backup")
    ap.add_argument("--repo-root", type=Path, default=None,
                    help="Path to the openvas-tools repository root")

    return ap.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])

    log(f"greenbone_install_backup.py v{VERSION}")

    if args.upgrade_env:
        log("Checking env file upload gate...")
        upgrade_env_file(dry_run=args.dry_run)
        return 0

    if not args.install:
        print("No action specified. Use --install, --upgrade-env, or --help.")
        return 0

    require_root()

    # Run test backup if requested (after install)
    if args.run_test_backup:
        # First install
        rc = install(
            dry_run=args.dry_run,
            configure_rclone=args.configure_rclone,
            enable_timers=args.enable_timers,
            repo_root=args.repo_root,
        )
        if rc != 0:
            return rc

        # Then run test backup
        log("Running test backup (dry-run, no upload)...")
        test_cmd = [sys.executable, str(Path(__file__).parent / "greenbone_manage_job00_daily.py"),
                     "--dry-run", "--no-upload"]
        if args.upload:
            test_cmd.extend(["--upload"])
        from greenbone_backup.command import run
        r = run(test_cmd, check=False, timeout=120)
        if r.returncode == 0:
            log("Test backup completed successfully.")
        else:
            err(f"Test backup failed: {r.stderr[:300]}")
            return 1
        return 0

    # Standard install
    return install(
        dry_run=args.dry_run,
        configure_rclone=args.configure_rclone,
        enable_timers=args.enable_timers,
        repo_root=args.repo_root,
    )


if __name__ == "__main__":
    sys.exit(main())
