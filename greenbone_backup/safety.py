"""safety.py - Safety gates for backup, restore, and destructive operations.

Every destructive operation must pass through the gates here.
Gates check preconditions, user confirmation, and environment state.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import sys
from typing import List


def confirm_destructive(operation: str, detail: str = "") -> bool:
    """Require interactive user confirmation for a destructive operation.

    Returns True only if user explicitly types 'yes'.
    """
    prompt = f"Are you sure you want to {operation}?"
    if detail:
        prompt += f"\n  {detail}"
    prompt += "\nType 'yes' to confirm: "
    answer = input(prompt).strip().lower()
    return answer == "yes"


def require_force_flag(force: bool, operation: str) -> None:
    """Exit with error unless --force is set.

    Use for operations that should never be automated without explicit flag.
    """
    if not force:
        print(f"ERROR: {operation} requires --force flag to proceed.", file=sys.stderr)
        print("  This safety gate prevents accidental destructive operations.", file=sys.stderr)
        sys.exit(1)


def check_upload_gates(upload_flag: bool, env_gate_ok: bool, rclone_valid: bool) -> bool:
    """Check all upload safety gates.

    Upload is allowed only when ALL of the following are true:
      1. upload_flag is True (user passed --upload)
      2. env_gate_ok is True (GREENBONE_BACKUP_UPLOAD=1 in env/config)
      3. rclone_valid is True (rclone config exists and has the remote)

    Returns True if upload is permitted.
    """
    if not upload_flag:
        return False
    if not env_gate_ok:
        return False
    if not rclone_valid:
        return False
    return True


def forbid_docker_destructive(commands: List[str]) -> None:
    """Check that none of the given commands include destructive Docker operations.

    Raises SystemExit if a forbidden pattern is found.
    """
    forbidden = [
        "docker system prune",
        "docker volume prune",
        "docker volume rm",
        "docker compose down -v",
        "docker rm",
        "docker rmi",
        "docker stop",
    ]
    for cmd in commands:
        for pattern in forbidden:
            if pattern in cmd:
                print(f"ERROR: Forbidden Docker command detected: {pattern}", file=sys.stderr)
                print(f"  Full command: {cmd[:200]}", file=sys.stderr)
                sys.exit(1)
