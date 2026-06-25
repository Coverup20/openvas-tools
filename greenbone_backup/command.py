"""command.py - Safe subprocess execution for backup tooling.

Wraps subprocess.run with consistent error handling, timeout, and return-code
checking.  Never uses shell=True.  Never exposes secrets in command logging.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import subprocess
import sys
from typing import List, Optional


class CommandError(Exception):
    """Raised when a subprocess returns a non-zero exit code."""

    def __init__(self, cmd: List[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Command failed (exit={returncode}): {' '.join(cmd)[:200]}")


def run(
    cmd: List[str],
    check: bool = True,
    timeout: Optional[int] = None,
    input_data: Optional[str] = None,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Execute a command safely and return the CompletedProcess.

    Args:
        cmd: Command as a list of strings (never shell=True).
        check: If True, raise CommandError on non-zero exit.
        timeout: Optional timeout in seconds.
        input_data: Optional string to pass as stdin.
        env: Optional environment dict. If None, inherits from parent.

    Returns:
        subprocess.CompletedProcess with stdout/stderr captured as text.

    Raises:
        CommandError: If check=True and returncode != 0.
        subprocess.TimeoutExpired: If timeout is reached.
    """
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise CommandError(cmd, -1, "", f"Command timed out after {timeout}s")

    if check and result.returncode != 0:
        raise CommandError(cmd, result.returncode, result.stdout or "", result.stderr or "")

    return result


def run_assert_zero(
    cmd: List[str],
    timeout: Optional[int] = None,
    input_data: Optional[str] = None,
) -> None:
    """Run a command and assert exit code 0, raising CommandError otherwise."""
    run(cmd, check=True, timeout=timeout, input_data=input_data)


def require_root() -> None:
    """Exit with error if not running as root."""
    try:
        if sys.platform != "win32" and __import__("os").geteuid() != 0:
            print("ERROR: This tool must be run as root.", file=sys.stderr)
            sys.exit(1)
    except AttributeError:
        pass  # Windows or non-standard platform
