"""metadata.py - Backup metadata JSON, SHA256 checksum, and restore instructions.

Produces the Checkmk-style metadata/state/snapshot triplet:
  - <archive_name>.metadata.json   (structured metadata)
  - <archive_name>.sha256           (SHA256 checksum)
  - <archive_name>.restore.md       (human-readable restore instructions)

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import hostname_short


def sha256sum(path: Path) -> str:
    """Compute SHA256 of a file, reading in 1MB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_os_pretty_name() -> str:
    """Read PRETTY_NAME from /etc/os-release."""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "unknown"


def kernel_version() -> str:
    """Return kernel release string."""
    return os.uname().release


def build_metadata(
    archive_name: str,
    archive_size_bytes: int,
    checksum: str,
    backup_type: str,
    compose_file: Path,
    greenbone_dir: Path,
    services: List[str],
    images: List[str],
    volumes: List[Dict[str, str]],
    upload_enabled: bool,
    rclone_remote: Optional[str] = None,
    rclone_path: Optional[str] = None,
    db_dump_size: int = 0,
    volume_archives_count: int = 0,
    script_version: str = "0.2.0",
) -> Dict[str, Any]:
    """Build a structured metadata dictionary for the backup archive.

    This follows the Checkmk-style model: the result is serialised as JSON
    and stored alongside the archive as a sidecar file.
    """
    md: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "os_pretty_name": collect_os_pretty_name(),
        "kernel": kernel_version(),
        "script_version": script_version,
        "backup_type": backup_type,
        "greenbone_project_dir": str(greenbone_dir),
        "compose_file": str(compose_file),
        "docker_version": _get_docker_version(),
        "docker_compose_version": _get_compose_version(),
        "containers": services,
        "images": images,
        "volumes": volumes,
        "archive_name": archive_name,
        "archive_size_bytes": archive_size_bytes,
        "sha256": checksum,
        "upload_enabled": upload_enabled,
    }

    if backup_type == "full_dr":
        md["db_dump_size_bytes"] = db_dump_size
        md["volume_archives_count"] = volume_archives_count
        md["note"] = "Full DR backup with PostgreSQL dump + Docker volumes"
    else:
        md["note"] = "Configuration/inventory snapshot (fast, daily)"

    if upload_enabled and rclone_remote:
        md["rclone_remote"] = rclone_remote
        md["rclone_path"] = rclone_path or ""

    return md


def write_metadata(archive_path: Path, metadata: Dict[str, Any]) -> Path:
    """Write metadata JSON sidecar file next to the archive."""
    path = archive_path.with_suffix(archive_path.suffix + ".metadata.json")
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return path


def write_checksum(archive_path: Path, checksum: str) -> Path:
    """Write SHA256 checksum sidecar file next to the archive."""
    path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    return path


def write_restore_instructions(archive_path: Path, checksum: str, compose_file: Path,
                                greenbone_dir: Path, backup_type: str) -> Path:
    """Write human-readable restore instructions sidecar file."""
    content = _restore_instructions_text(archive_path.name, checksum,
                                          compose_file, greenbone_dir, backup_type)
    path = archive_path.with_suffix(archive_path.suffix + ".restore.md")
    path.write_text(content, encoding="utf-8")
    return path


def _restore_instructions_text(archive_name: str, checksum: str,
                                compose_file: Path, greenbone_dir: Path,
                                backup_type: str) -> str:
    if backup_type == "full_dr":
        return f"""=== Greenbone/OpenVAS Restore Instructions (Full DR Backup) ===

Archive: {archive_name}
Checksum (SHA256): {checksum}

This is a FULL backup including:
  - PostgreSQL database dump (gvmd-database.sql)
  - Docker volume data archives (*.tar.gz)
  - Compose file and project configuration
  - Service inventory snapshot

PREREQUISITES:
  - Docker and Docker Compose plugin installed
  - Project directory: {greenbone_dir}
  - Compose file: {compose_file}

RESTORE:
  1) Ensure project directory exists: mkdir -p {greenbone_dir}
  2) Extract archive: tar xzf {archive_name} -C /
  3) Restore PostgreSQL database:
     docker compose -f {compose_file} up -d pg-gvm
     sleep 15
     cat gvmd-database.sql | docker compose -f {compose_file} exec -T pg-gvm psql -U gvmd -d gvmd
  4) Start full stack:
     cd {greenbone_dir} && docker compose up -d --remove-orphans
  5) Validate: docker compose ps --all
"""

    return f"""=== Greenbone/OpenVAS Restore Instructions (Config Backup) ===

Archive: {archive_name}
Checksum (SHA256): {checksum}

This is a configuration/inventory backup only.
For full DR, use the weekly job01-full backup or Timeshift.

CONTENTS:
  - Compose file and project configuration
  - Service inventory snapshot

PREREQUISITES:
  - Docker and Docker Compose plugin installed
  - Project directory: {greenbone_dir}
  - Compose file: {compose_file}

RESTORE:
  1) Ensure project directory exists: mkdir -p {greenbone_dir}
  2) Extract archive: tar xzf {archive_name} -C /
  3) Start stack and validate:
     cd {greenbone_dir} && docker compose up -d --remove-orphans
     docker compose ps --all
"""


def _get_docker_version() -> str:
    try:
        from .command import run
        r = run(["docker", "--version"], check=False, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return "unavailable"


def _get_compose_version() -> str:
    try:
        from .command import run
        r = run(["docker", "compose", "version"], check=False, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return "unavailable"
