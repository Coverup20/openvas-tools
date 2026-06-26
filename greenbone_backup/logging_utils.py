"""logging_utils.py - Logging, timestamping, and secret redaction.

All backup tool output must go through the functions here,
so secrets are never accidentally written to logs or stdout.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import re
import sys
from datetime import datetime, timezone
from typing import List


# Patterns that look like secrets in command output or logs.
# Used by redact() to scrub before printing.
_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r"(secret_access_key|access_key_id|token|password)\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"(?i)(s3_secret_key|s3_access_key|aws_secret|aws_key)\s*[:=]\s*\S+"),
    re.compile(r"https://[^@\s]+@[^\s]+"),  # URL-embedded credentials
]


def timestamp() -> str:
    """Return ISO-8601 UTC timestamp for log prefix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def redact(text: str) -> str:
    """Replace known secret patterns with [REDACTED] in the given text."""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda m: re.sub(r"=\S+", "=[REDACTED]", m.group(0)), result)
    return result


def log(msg: str, *args, stream=None) -> None:
    """Print a timestamped log message (secrets redacted)."""
    out = stream or sys.stdout
    full = f"[{timestamp()}] {msg}"
    if args:
        full = full % args
    print(redact(full), file=out, flush=True)


def err(msg: str, *args) -> None:
    """Print a timestamped error to stderr (secrets redacted)."""
    full = f"[{timestamp()}] ERROR: {msg}"
    if args:
        full = full % args
    print(redact(full), file=sys.stderr, flush=True)


def warn(msg: str, *args) -> None:
    """Print a timestamped warning to stderr (secrets redacted)."""
    full = f"[{timestamp()}] WARN: {msg}"
    if args:
        full = full % args
    print(redact(full), file=sys.stderr, flush=True)
