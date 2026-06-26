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


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate rclone configuration (safe)")
    ap.add_argument("--list-remotes", action="store_true", help="List configured rclone remotes (names only)")
    ap.add_argument("--test-remote", default="", help="Test a remote with 'rclone lsd <remote>:'")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
