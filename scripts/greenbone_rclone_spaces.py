#!/usr/bin/env python3
"""
greenbone_rclone_spaces.py - Rclone validation/helper for Spaces/S3

Read-only safe helper to:
- validate rclone is installed
- list configured remotes (names only)
- test a remote access with rclone lsd (no secrets printed)

Optional interactive setup mode may be added later; when added, it must
use hidden input and never echo secrets. This first version does NOT write
credentials and only validates existing configuration.

Usage examples:
  greenbone_rclone_spaces.py --list-remotes
  greenbone_rclone_spaces.py --test-remote do:bucket

Version: 0.1.0
"""

import argparse
import shutil
import subprocess
import sys
from typing import List


VERSION = "0.1.0"


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def discover_greenbone_backups() -> int:
    """List Greenbone backup directories on all configured rclone remotes.

    Read-only: never modifies rclone.conf.  Never asks for credentials.
    Returns 0 if at least one Greenbone backup path was found, 1 otherwise.
    """
    remotes_r = run(["rclone", "listremotes"])
    remotes_text = (remotes_r.stdout or "").strip()
    if not remotes_text:
        print("No rclone remotes configured")
        return 2 if remotes_r.returncode != 0 else 1
    remotes = [r.strip().rstrip(":") for r in remotes_text.splitlines() if r.strip()]

    found_any = False
    for rm in remotes:
        # Probe for greenbone-backups/ under the remote
        for base in ("greenbone-backups",):
            ls_r = run(["rclone", "lsd", f"{rm}:{base}"])
            if ls_r.returncode != 0:
                continue
            subdirs = [(ls_r.stdout or "").strip().splitlines()]
            lines = []
            for line in subdirs[0]:
                parts = line.split()
                if parts:
                    lines.append(parts[-1])
            if not lines:
                continue
            found_any = True
            for sub in lines:
                full_path = f"{rm}:{base}/{sub}"
                print(full_path)
    if not found_any:
        # Check if remote itself is accessible
        for rm in remotes:
            test_r = run(["rclone", "lsd", f"{rm}:"])
            if test_r.returncode != 0:
                err_msg = (test_r.stderr or "").strip()
                if "SignatureDoesNotMatch" in err_msg or "AccessDenied" in err_msg:
                    print(f"REMOTE CONFIG INVALID: {rm}: — credentials invalid or expired")
                else:
                    print(f"REMOTE NOT ACCESSIBLE: {rm}: — {err_msg[:120]}")
            else:
                print(f"NO GREENBONE BACKUPS: {rm}: — remote accessible but no greenbone-backups/ found")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate rclone configuration (safe)")
    ap.add_argument("--list-remotes", action="store_true", help="List configured rclone remotes (names only)")
    ap.add_argument("--test-remote", default="", help="Test a remote with 'rclone lsd <remote>:'")
    ap.add_argument("--list-backups", action="store_true", help="List Greenbone backup directories")
    args = ap.parse_args()

    if shutil.which("rclone") is None:
        print("rclone is not installed or not in PATH")
        return 1

    if args.list_remotes:
        r = run(["rclone", "listremotes"])
        print((r.stdout or "").strip())

    if args.test_remote:
        remote = args.test_remote
        if ":" not in remote:
            print("Remote must be in the form 'name:bucket' or 'name:'")
            return 1
        r = run(["rclone", "lsd", remote])
        if r.returncode == 0:
            print(f"Remote test OK: {remote}")
        else:
            print(f"Remote test failed ({remote}): {(r.stderr or r.stdout).strip()}")

    if args.list_backups:
        return discover_greenbone_backups()

    return 0


if __name__ == "__main__":
    sys.exit(main())
