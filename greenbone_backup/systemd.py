"""systemd.py - Generate systemd service and timer unit files in Python.

No Bash.  All unit content is rendered from Python templates.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from pathlib import Path
from typing import List, Tuple

from .logging_utils import log

# Default install paths for backup scripts
SCRIPTS_DIR = Path("/opt/greenbone-backup/scripts")
SYSTEMD_DIR = Path("/etc/systemd/system")

# Python interpreter to use in ExecStart
PYTHON = "/usr/bin/python3"


def _job00_service_content() -> str:
    """Content for greenbone-backup-job00.service."""
    return f"""[Unit]
Description=Greenbone Job00 Daily Config Backup
Documentation=https://github.com/Coverup20/openvas-tools
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
User=root
EnvironmentFile=-/etc/greenbone-backup/greenbone-backup.env
Environment=PYTHONPATH={SCRIPTS_DIR}
ExecStart={PYTHON} {SCRIPTS_DIR / 'greenbone_manage_job00_daily.py'} --upload
StandardOutput=journal
StandardError=journal
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
"""


def _job00_timer_content() -> str:
    return """[Unit]
Description=Run Greenbone Job00 Daily Backup

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
"""


def _job01_service_content() -> str:
    """Content for greenbone-backup-full.service."""
    return f"""[Unit]
Description=Greenbone Full DR Backup (bi-weekly)
Documentation=https://github.com/Coverup20/openvas-tools
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
User=root
EnvironmentFile=-/etc/greenbone-backup/greenbone-backup.env
Environment=PYTHONPATH={SCRIPTS_DIR}
ExecStart={PYTHON} {SCRIPTS_DIR / 'greenbone_manage_job01_weekly.py'} --upload
StandardOutput=journal
StandardError=journal
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
"""


def _job01_timer_content() -> str:
    return """[Unit]
Description=Run Greenbone Full DR Backup (bi-weekly)

[Timer]
OnCalendar=Mon *-*-1,15 05:00:00
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
"""


def all_units() -> List[Tuple[str, str]]:
    """Return list of (filename, content) for all systemd units."""
    return [
        ("greenbone-backup-job00.service", _job00_service_content()),
        ("greenbone-backup-job00.timer", _job00_timer_content()),
        ("greenbone-backup-full.service", _job01_service_content()),
        ("greenbone-backup-full.timer", _job01_timer_content()),
    ]


def install_units(dry_run: bool = False) -> List[Path]:
    """Write all systemd unit files to SYSTEMD_DIR.

    Units are written but NOT enabled.  Returns list of written paths.
    """
    written: List[Path] = []
    for fname, content in all_units():
        dst = SYSTEMD_DIR / fname
        if dry_run:
            print(f"[DRY-RUN] Would write: {dst} ({len(content)} bytes)")
            written.append(dst)
            continue
        dst.write_text(content, encoding="utf-8")
        dst.chmod(0o644)
        log(f"Wrote: {dst}")
        written.append(dst)
    if not dry_run:
        import subprocess
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
        log("Systemd daemon reloaded.")
    return written


def enable_timer(timer_name: str, dry_run: bool = False) -> None:
    """Enable and start a systemd timer by name."""
    import subprocess
    if dry_run:
        print(f"[DRY-RUN] Would enable --now: {timer_name}")
        return
    subprocess.run(["systemctl", "enable", "--now", timer_name], check=True, timeout=30)
    log(f"Timer enabled: {timer_name}")


def disable_timer(timer_name: str, dry_run: bool = False) -> None:
    """Disable and stop a systemd timer by name."""
    import subprocess
    if dry_run:
        print(f"[DRY-RUN] Would disable --now: {timer_name}")
        return
    subprocess.run(["systemctl", "disable", "--now", timer_name], check=False, timeout=30)
    log(f"Timer disabled: {timer_name}")
