#!/usr/bin/env python3
"""
greenbone_audit_reference.py - Read-only audit of the reference Greenbone VM.

Inspects the working Greenbone installation (VM 202) and produces a JSON/Markdown
report with the backup, rclone, systemd, and state layout for use as installation
reference.

Usage:
  python3 greenbone_audit_reference.py --reference-host <hostname-or-ip>
  python3 greenbone_audit_reference.py --local

Options:
  --local                Inspect the local host
  --reference-host HOST  SSH to the reference host and inspect (read-only)
  --output FILE          Write report to file (default: stdout)
  --json                 Output in JSON instead of Markdown

Safety:
  - Read-only: never modifies the inspected host
  - No secrets: credentials are masked in the report

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION = "0.1.0"


def run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}] {msg}")


def err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def cat(path: str) -> Optional[str]:
    try:
        r = run(["cat", path])
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return None


def mask_secrets(text: str) -> str:
    """Mask access_key_id and secret_access_key values in rclone config."""
    import re
    result = text
    for key in ("access_key_id", "secret_access_key"):
        result = re.sub(
            rf"({key}\s*=\s*)(\S+)",
            lambda m: m.group(1) + "[REDACTED]",
            result,
        )
    return result


def collect_local() -> Dict[str, Any]:
    """Collect backup system state from the local host."""
    report: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": os.uname().nodename,
        "sections": {},
    }

    # Backup directories
    for dir_path in ["/opt/greenbone-backup", "/var/backups/greenbone", "/etc/greenbone-backup"]:
        p = Path(dir_path)
        if p.exists():
            items = []
            for child in sorted(p.iterdir()):
                try:
                    items.append({
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else 0,
                        "mode": oct(child.stat().st_mode)[-3:],
                    })
                except Exception:
                    pass
            report["sections"][dir_path] = items

    # Env file
    env_file = "/etc/greenbone-backup/greenbone-backup.env"
    env_content = cat(env_file)
    if env_content:
        report["sections"]["env_file"] = env_content.strip()

    # Rclone config
    rclone_conf = "/root/.config/rclone/rclone.conf"
    rclone_raw = cat(rclone_conf)
    if rclone_raw:
        report["sections"]["rclone_config"] = mask_secrets(rclone_raw.strip())
    else:
        report["sections"]["rclone_config"] = "NOT FOUND"

    # Rclone remotes
    r = run(["rclone", "listremotes"], timeout=10)
    report["sections"]["rclone_remotes"] = (r.stdout or "").strip() or "NONE"

    # Systemd
    for unit_file in sorted(Path("/etc/systemd/system").glob("greenbone-backup*")):
        content = cat(str(unit_file))
        if content:
            report.setdefault("sections", {}).setdefault("systemd_units", {})[unit_file.name] = content.strip()

    # Timer status
    r = run(["systemctl", "list-timers", "--no-pager"], timeout=10)
    timer_lines = [ln for ln in (r.stdout or "").splitlines() if "greenbone-backup" in ln]
    report["sections"]["timer_status"] = timer_lines

    # Backup archives
    backup_dir = Path("/var/backups/greenbone")
    if backup_dir.exists():
        archives = []
        for f in sorted(backup_dir.glob("greenbone-*.tar.gz"), reverse=True)[:10]:
            md = backup_dir / f.name.replace(".tar.gz", ".tar.gz.metadata.json")
            meta = None
            if md.exists():
                try:
                    meta = json.loads(md.read_text())
                except Exception:
                    pass
            archives.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                "metadata": meta,
            })
        report["sections"]["backup_archives"] = archives

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only audit of Greenbone reference VM")
    ap.add_argument("--local", action="store_true", help="Inspect local host")
    ap.add_argument("--reference-host", help="SSH to reference host (read-only)")
    ap.add_argument("--output", help="Write report to file")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of Markdown")
    args = ap.parse_args()

    if args.reference_host:
        err("Remote inspection not implemented in this version.")
        err("Use --local or SSH manually and run with --local on the target.")
        return 1

    log(f"greenbone_audit_reference.py v{VERSION}")
    log("Inspecting local host...")

    report = collect_local()

    if args.output:
        output_path = Path(args.output)
        if args.json:
            output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        else:
            output_path.write_text(_to_markdown(report), encoding="utf-8")
        log(f"Report written to: {output_path}")
    else:
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(_to_markdown(report))

    return 0


def _to_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# Greenbone Reference Audit Report",
        f"",
        f"**Hostname:** {report.get('hostname', 'unknown')}",
        f"**Timestamp:** {report.get('timestamp_utc', 'unknown')}",
        f"",
    ]
    for section, data in report.get("sections", {}).items():
        lines.append(f"## {section}")
        lines.append("")
        if isinstance(data, str):
            lines.append("```")
            lines.append(data)
            lines.append("```")
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    lines.append(f"- **{item.get('name', '?')}**  ")
                    for k, v in item.items():
                        if k != "name":
                            lines.append(f"  - {k}: {v}")
                else:
                    lines.append(f"- {item}")
        elif isinstance(data, dict):
            for k, v in data.items():
                lines.append(f"### {k}")
                lines.append("")
                lines.append("```")
                lines.append(str(v))
                lines.append("```")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
