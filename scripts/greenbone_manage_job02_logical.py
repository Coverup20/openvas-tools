#!/usr/bin/env python3
"""
greenbone_manage_job02_logical.py - Logical GMP XML backup manager (job02).

Exports Greenbone application objects (tasks, targets, configs, etc.) via
raw GMP XML over the gvmd Unix socket using socat.  Complements job01 full
infrastructure DR — this is NOT a full DR replacement.

What this backs up:
  - GMP object definitions (tasks, targets, port lists, scan configs,
    schedules, alerts) as XML
  - Scan reports (latest per task) as XML
  - GMP version and metadata

What this does NOT back up:
  - PostgreSQL database state (feed data, internal caches)
  - Docker volumes (scanner state, Notus data, logs)
  - Credential secrets (passwords, SSH keys, SNMP strings)
  - User accounts
  - Container/service configuration outside GMP

Usage:
  python3 greenbone_manage_job02_logical.py                         # logical backup, no upload
  python3 greenbone_manage_job02_logical.py --upload                 # + upload (gated)
  python3 greenbone_manage_job02_logical.py --dry-run                # preview only
  python3 greenbone_manage_job02_logical.py --help

Upload gates:
  --upload flag AND GREENBONE_BACKUP_UPLOAD=1 in env or .env

Environment variables for GMP credentials:
  GREENBONE_GMP_USERNAME  (default: admin)
  GREENBONE_GMP_PASSWORD  (required, no default — must be set via env)

Credentials must never be hardcoded in this file.
Credentials are never printed, logged, or included in metadata.
If GREENBONE_GMP_PASSWORD is unset or empty, the script fails safely.

Version: 0.1.0
Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "0.1.0"
BACKUP_PROFILE = "job02-logical"

# Default GMP credential env-var names
ENV_GMP_USERNAME = "GREENBONE_GMP_USERNAME"
ENV_GMP_PASSWORD = "GREENBONE_GMP_PASSWORD"

# Default compose and socket paths
DEFAULT_COMPOSE_FILE = "/opt/greenbone-community/compose.yaml"
DEFAULT_GMP_SOCKET = "/run/gvmd/gvmd.sock"

# Retention defaults for job02 (logical backups are small)
DEFAULT_RETENTION_LOCAL = 30
DEFAULT_RETENTION_CLOUD = 30


# ─────────────────────────────────────────────
# Helper: subprocess with safe defaults
# ─────────────────────────────────────────────


def _run(cmd: List[str], timeout: int = 60, input_data: Optional[str] = None,
         check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess with consistent settings."""
    try:
        r = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"[ERROR] Command not found: {cmd[0]}", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Command timed out after {timeout}s: {' '.join(cmd)}",
              file=sys.stderr)
        raise SystemExit(1)
    if check and r.returncode != 0:
        print(f"[ERROR] Command failed (exit={r.returncode}): {' '.join(cmd)}",
              file=sys.stderr)
        if r.stderr:
            print(f"  stderr: {r.stderr.strip()[:500]}", file=sys.stderr)
        raise SystemExit(1)
    return r


# ─────────────────────────────────────────────
# GMP-over-socat helpers
# ─────────────────────────────────────────────


def _gmp_request(xml_payload: str, compose_file: Path,
                 socket_path: str = DEFAULT_GMP_SOCKET,
                 timeout: int = 120) -> str:
    """Send raw GMP XML over the gvmd Unix socket via socat.

    Returns the full XML response as a string.
    """
    cmd = [
        "docker", "compose", "-f", str(compose_file),
        "exec", "-T", "gvmd",
        "socat", "-", f"UNIX-CONNECT:{socket_path}",
    ]
    r = _run(cmd, timeout=timeout, input_data=xml_payload,
             check=False)
    if r.returncode != 0 or not r.stdout:
        err_msg = r.stderr.strip() if r.stderr else "empty response"
        print(f"[ERROR] GMP request failed: {err_msg[:300]}", file=sys.stderr)
        # If we got a partial response, include it for debugging
        if r.stdout:
            print(f"  partial response: {r.stdout[:200]}", file=sys.stderr)
        return ""
    return r.stdout


def _gmp_authenticated_request(gmp_username: str, gmp_password: str,
                                gmp_command: str, compose_file: Path,
                                socket_path: str = DEFAULT_GMP_SOCKET,
                                timeout: int = 120) -> str:
    """Authenticate and send a single GMP command.

    Prepends an <authenticate> element to the XML payload.
    Returns the response XML or empty string on failure.
    """
    auth_xml = (
        f"<authenticate>"
        f"<credentials>"
        f"<username>{gmp_username}</username>"
        f"<password>{gmp_password}</password>"
        f"</credentials>"
        f"</authenticate>\n"
    )
    full_xml = auth_xml + gmp_command
    return _gmp_request(full_xml, compose_file, socket_path, timeout)


def _extract_status(response_xml: str) -> str:
    """Extract the status_text from the first response element."""
    import re
    m = re.search(r'status_text="([^"]+)"', response_xml)
    return m.group(1) if m else "unknown"


def _check_response_ok(response_xml: str, label: str) -> bool:
    """Log and return True if the GMP response status is OK."""
    status = _extract_status(response_xml)
    if status == "OK":
        return True
    print(f"  [WARN] {label} returned status={status}", file=sys.stderr)
    return False


# ─────────────────────────────────────────────
# GMP export functions (read-only)
# ─────────────────────────────────────────────


def export_gmp_version(gmp_username: str, gmp_password: str,
                        compose_file: Path) -> str:
    """Export GMP protocol version."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        "<get_version/>",
        compose_file,
    )


def export_tasks(gmp_username: str, gmp_password: str,
                  compose_file: Path) -> str:
    """Export all tasks with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_tasks details="1"/>',
        compose_file,
    )


def export_targets(gmp_username: str, gmp_password: str,
                    compose_file: Path) -> str:
    """Export all targets with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_targets details="1"/>',
        compose_file,
    )


def export_port_lists(gmp_username: str, gmp_password: str,
                       compose_file: Path) -> str:
    """Export all port lists with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_port_lists details="1"/>',
        compose_file,
    )


def export_scan_configs(gmp_username: str, gmp_password: str,
                         compose_file: Path) -> str:
    """Export all scan configs with full details.

    Uses details="0" because details="1" (NVT selections, families, preferences)
    produces a very large XML payload that may time out over the Unix socket.
    Full NVT selections are rebuilt from feed data after restore.
    """
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_configs details="0"/>',
        compose_file,
    )


def export_schedules(gmp_username: str, gmp_password: str,
                      compose_file: Path) -> str:
    """Export all schedules with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_schedules details="1"/>',
        compose_file,
    )


def export_alerts(gmp_username: str, gmp_password: str,
                   compose_file: Path) -> str:
    """Export all alerts with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_alerts details="1"/>',
        compose_file,
    )


def export_reports(gmp_username: str, gmp_password: str,
                    compose_file: Path) -> str:
    """Export all reports with full details."""
    return _gmp_authenticated_request(
        gmp_username, gmp_password,
        '<get_reports details="1"/>',
        compose_file,
    )


# ─────────────────────────────────────────────
# Export orchestrator
# ─────────────────────────────────────────────


EXPORT_DEFINITIONS: List[Tuple[str, str, Any]] = [
    ("gmp-version.xml",    "GMP version",         export_gmp_version),
    ("tasks.xml",          "Tasks",               export_tasks),
    ("targets.xml",        "Targets",             export_targets),
    ("port-lists.xml",     "Port lists",          export_port_lists),
    ("scan-configs.xml",   "Scan configs",        export_scan_configs),
    ("schedules.xml",      "Schedules",           export_schedules),
    ("alerts.xml",         "Alerts",              export_alerts),
    ("reports.xml",        "Reports",             export_reports),
]


def run_exports(export_dir: Path, gmp_username: str, gmp_password: str,
                compose_file: Path, dry_run: bool = False) -> Dict[str, int]:
    """Execute all GMP exports and write XML files to export_dir.

    Returns a dict mapping filename -> size_bytes for successfully written files.
    """
    written: Dict[str, int] = {}

    for filename, label, export_func in EXPORT_DEFINITIONS:
        fpath = export_dir / filename
        if dry_run:
            print(f"  [DRY-RUN] Would export {label} -> {fpath.name}")
            continue

        print(f"  Exporting {label}...", end=" ")
        sys.stdout.flush()
        response_xml = export_func(gmp_username, gmp_password, compose_file)

        if not response_xml:
            print("FAILED (empty response)")
            continue

        ok = _check_response_ok(response_xml, label)
        if ok:
            fpath.write_text(response_xml, encoding="utf-8")
            size = fpath.stat().st_size
            written[filename] = size
            gmp_version_label = ""
            if filename == "gmp-version.xml":
                import re
                m = re.search(r'<version>([^<]+)</version>', response_xml)
                if m:
                    gmp_version_label = f" (GMP protocol {m.group(1)})"
            print(f"OK ({size} bytes){gmp_version_label}")
        else:
            print(f"WARN (status not OK, saving partial)")
            fpath.write_text(response_xml, encoding="utf-8")
            written[filename] = fpath.stat().st_size

    return written


# ─────────────────────────────────────────────
# Archive creation
# ─────────────────────────────────────────────


def create_archive(export_dir: Path, archive_path: Path) -> Optional[Path]:
    """Create a streaming .tar.gz archive from export_dir.

    Uses streaming gzip to avoid intermediate uncompressed tar.
    Writes to .tmp first, then atomically renames to final path.
    """
    tmp_path = archive_path.with_name(archive_path.name + ".tmp")
    try:
        with tarfile.open(tmp_path, mode="w:gz") as tar:
            for child in sorted(export_dir.iterdir()):
                if child.is_file():
                    tar.add(str(child), arcname=child.name)
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            tmp_path.rename(archive_path)
            return archive_path
        print("  [WARN] Archive is empty or missing", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"  [ERROR] Archive creation failed: {e}", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
    return None


def sha256sum(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_os_info() -> Dict[str, str]:
    """Collect host OS info."""
    info = {
        "hostname": socket.gethostname().split(".")[0],
        "fqdn": socket.gethostname(),
    }
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["os_pretty_name"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
    try:
        info["kernel"] = os.uname().release
    except Exception:
        pass
    return info


def build_metadata(archive_name: str, archive_size_bytes: int,
                    checksum: str, hostname_short: str,
                    files_written: Dict[str, int],
                    gmp_version_response: str,
                    dry_run: bool = False) -> Dict[str, Any]:
    """Build metadata dict for the job02 backup."""
    import re
    gmp_protocol = ""
    if gmp_version_response:
        m = re.search(r'<version>([^<]+)</version>', gmp_version_response)
        if m:
            gmp_protocol = m.group(1)

    os_info = collect_os_info()

    md: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": hostname_short,
        "os_pretty_name": os_info.get("os_pretty_name", "unknown"),
        "kernel": os_info.get("kernel", "unknown"),
        "script_version": VERSION,
        "backup_profile": BACKUP_PROFILE,
        "backup_type": "logical_gmp_export",
        "compose_file": str(DEFAULT_COMPOSE_FILE),
        "archive_name": archive_name,
        "archive_size_bytes": archive_size_bytes,
        "sha256": checksum,
        "gmp_protocol_version": gmp_protocol,
        "exported_files": {fname: size for fname, size in sorted(files_written.items())},
        "exported_count": len(files_written),
        "note": (
            "LOGICAL-ONLY backup. This is NOT a full DR replacement. "
            "Credentials, feed data (NVTs/SCAP/CERT), PostgreSQL full state, "
            "Docker volumes, and service configuration are NOT included."
        ),
        "credentials_included": False,
        "credential_warning": (
            "GMP credentials are NOT exportable with secrets. "
            "After restore, all credentials (passwords, SSH keys, SNMP strings) "
            "must be re-entered manually via GSA or GMP."
        ),
        "post_restore_required": [
            "Re-enter all credentials manually",
            "Re-create user accounts manually",
            "Allow feed sync to complete (NVTs, SCAP, CERT)",
            "Re-verify scanners and targets",
        ],
    }
    return md


def write_sidecars(archive_path: Path, metadata: Dict[str, Any],
                    checksum: str) -> None:
    """Write .metadata.json, .sha256, and .restore.md sidecars."""
    # metadata.json
    meta_path = archive_path.with_name(archive_path.name + ".metadata.json")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"  Sidecar: {meta_path.name} ({meta_path.stat().st_size} bytes)")

    # sha256
    sha_path = archive_path.with_name(archive_path.name + ".sha256")
    sha_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    print(f"  Sidecar: {sha_path.name} ({sha_path.stat().st_size} bytes)")

    # restore.md
    restore_md = _restore_instructions_text(
        archive_path.name, checksum,
        metadata.get("hostname", "unknown"),
    )
    restore_path = archive_path.with_name(archive_path.name + ".restore.md")
    restore_path.write_text(restore_md, encoding="utf-8")
    print(f"  Sidecar: {restore_path.name} ({restore_path.stat().st_size} bytes)")


def _restore_instructions_text(archive_name: str, checksum: str,
                                 hostname: str) -> str:
    return f"""=== Greenbone/OpenVAS Restore Instructions (Logical XML Backup) ===

Archive: {archive_name}
Host: {hostname}
Checksum (SHA256): {checksum}
Profile: {BACKUP_PROFILE}

This is a LOGICAL-ONLY backup containing GMP object definitions and reports.
It is NOT a full DR backup.

CONTENTS:
  - Task definitions (XML)
  - Target definitions (XML)
  - Port list definitions (XML)
  - Scan config definitions (XML)
  - Schedule definitions (XML)
  - Alert definitions (XML)
  - Scan reports (XML, latest per task)
  - GMP protocol version

NOT INCLUDED (must be provisioned separately):
  @ Credentials (passwords, SSH keys, SNMP strings) — must be re-entered manually
  @ User accounts — must be re-created manually
  @ Feed data (NVTs, SCAP, CERT) — requires feed sync after deploy
  @ PostgreSQL database full state
  @ Docker volumes (scanner state, caches)
  @ Service configuration outside GMP

RESTORE PREREQUISITES:
  - Docker and Docker Compose plugin installed
  - Fresh Greenbone Community Containers deployment
  - Feed sync completed (wait for NVTs, SCAP, CERT to import)
  - Admin account available in GSA/GMP

RESTORE STEPS:
  1) Deploy fresh Greenbone stack:
     docker compose -f /opt/greenbone-community/compose.yaml up -d

  2) Wait for feed synchronization to complete:
     docker compose -f /opt/greenbone-community/compose.yaml logs gvmd --tail 50
     (Look for NVT, SCAP, and CERT import completion)

  3) Re-enter all credentials manually via GSA or GMP create_credential

  4) Re-create user accounts manually via GSA or GMP create_user

  5) Import scan configs from XML:
     (Use GMP import_scan_config for each scan-configs.xml entry)

  6) Create port lists, schedules, alerts, targets, tasks via GMP create_*

  7) Import reports via GMP import_report (XML format)

  8) Verify: docker compose ps --all
     Verify: GSA web interface at https://<host>:9392

LIMITATIONS:
  - This backup does NOT preserve credential secrets.
    After restore, all credentials must be re-entered.
  - Task/target/config UUIDs may change on re-import.
    Cross-references between objects must be re-established.
  - Report history beyond the last backup cycle is not preserved.
"""


# ─────────────────────────────────────────────
# Retention
# ─────────────────────────────────────────────


def apply_local_retention(backup_dir: Path, prefix: str, keep: int,
                           dry_run: bool = False) -> None:
    """Remove older archives beyond the retention count.

    Considers archives matching ``{backup_dir}/{prefix}*.tar.gz``.
    Sidecar files (.sha256, .metadata.json, .restore.md) are removed together.
    """
    archives = sorted(backup_dir.glob(f"{prefix}*.tar.gz"))
    if len(archives) <= keep:
        return

    to_remove = archives[:-keep]
    for arc in to_remove:
        if dry_run:
            print(f"  [DRY-RUN] Would remove: {arc.name}")
        else:
            arc.unlink(missing_ok=True)
        for suffix in (".sha256", ".metadata.json", ".restore.md"):
            sidecar = arc.with_name(arc.name + suffix)
            if sidecar.exists():
                if dry_run:
                    print(f"  [DRY-RUN] Would remove sidecar: {sidecar.name}")
                else:
                    sidecar.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Dry-run validation
# ─────────────────────────────────────────────


def validate_dry_run(compose_file: Path, socket_path: str,
                      gmp_username: str) -> bool:
    """Validate prerequisites without running a backup.

    Returns True if all checks pass, False otherwise.
    """
    all_ok = True

    # 1. Compose file exists
    if not compose_file.exists():
        print(f"[FAIL] Compose file not found: {compose_file}", file=sys.stderr)
        all_ok = False
    else:
        print(f"[OK]   Compose file: {compose_file}")

    # 2. Docker compose can see gvmd container
    if compose_file.exists():
        try:
            # docker compose ps -q <service> returns container ID if running
            r = _run(
                ["docker", "compose", "-f", str(compose_file),
                 "ps", "-q", "gvmd"],
                timeout=30, check=False,
            )
            if r.returncode == 0 and r.stdout and r.stdout.strip():
                print(f"[OK]   gvmd container is running")
            else:
                print("[FAIL] gvmd container not found or not running",
                      file=sys.stderr)
                all_ok = False
        except Exception as e:
            print(f"[FAIL] Cannot check gvmd container: {e}", file=sys.stderr)
            all_ok = False

    # 3. socat exists inside gvmd container
    if compose_file.exists():
        try:
            r = _run(
                ["docker", "compose", "-f", str(compose_file),
                 "exec", "-T", "gvmd", "which", "socat"],
                timeout=15, check=False,
            )
            if r.returncode == 0 and r.stdout and "socat" in r.stdout:
                print(f"[OK]   socat available inside gvmd container")
            else:
                print("[FAIL] socat not found inside gvmd container",
                      file=sys.stderr)
                all_ok = False
        except Exception as e:
            print(f"[FAIL] Cannot check socat: {e}", file=sys.stderr)
            all_ok = False

    # 4. GMP socket exists inside container
    if compose_file.exists():
        try:
            r = _run(
                ["docker", "compose", "-f", str(compose_file),
                 "exec", "-T", "gvmd", "ls", "-la", socket_path],
                timeout=15, check=False,
            )
            if r.returncode == 0 and "gvmd.sock" in (r.stdout or ""):
                print(f"[OK]   GMP socket: {socket_path}")
            else:
                print(f"[FAIL] GMP socket not found: {socket_path}",
                      file=sys.stderr)
                all_ok = False
        except Exception as e:
            print(f"[FAIL] Cannot check socket: {e}", file=sys.stderr)
            all_ok = False

    # 5. Credentials present (check only presence, do not print)
    if gmp_username:
        print(f"[OK]   GMP username configured")
    else:
        print("[FAIL] GMP username not configured", file=sys.stderr)
        all_ok = False

    pwd_env = os.environ.get(ENV_GMP_PASSWORD, "")
    if pwd_env:
        print(f"[OK]   GMP password configured (from {ENV_GMP_PASSWORD})")
    else:
        print(f"[FAIL] GMP password not configured (set {ENV_GMP_PASSWORD})",
              file=sys.stderr)
        all_ok = False

    # 6. Optional: test GMP get_version (safe, read-only)
    if all_ok and gmp_username and pwd_env:
        try:
            print("  Testing GMP connection (get_version)...", end=" ")
            sys.stdout.flush()
            resp = export_gmp_version(
                gmp_username, pwd_env, compose_file
            )
            if resp and _check_response_ok(resp, "get_version"):
                import re
                m = re.search(r'<version>([^<]+)</version>', resp)
                ver = m.group(1) if m else "unknown"
                print(f"OK (GMP protocol {ver})")
            else:
                print("FAILED", file=sys.stderr)
                all_ok = False
        except Exception as e:
            print(f"FAILED: {e}", file=sys.stderr)
            all_ok = False

    return all_ok


# ─────────────────────────────────────────────
# Upload (gated, same pattern as job00/job01)
# ─────────────────────────────────────────────


def _validate_rclone(rclone_remote: str) -> bool:
    """Validate rclone config without printing secrets."""
    rclone_conf = Path("/root/.config/rclone/rclone.conf")
    if not rclone_conf.exists():
        print("[FAIL] rclone config not found", file=sys.stderr)
        return False

    remote_name = rclone_remote.split(":")[0] if ":" in rclone_remote else "do"
    # Check config has the remote section
    try:
        content = rclone_conf.read_text(encoding="utf-8")
        if f"[{remote_name}]" in content:
            print(f"[OK]   rclone remote '{remote_name}' configured")
            return True
        print(f"[FAIL] rclone remote '{remote_name}' not found in config",
              file=sys.stderr)
    except Exception as e:
        print(f"[FAIL] Cannot read rclone config: {e}", file=sys.stderr)
    return False


def _upload_archive(archive_path: Path, rclone_remote: str,
                     rclone_path: str, dry_run: bool = False) -> None:
    """Upload archive and sidecars to cloud storage."""
    if dry_run:
        print(f"  [DRY-RUN] Would upload to {rclone_remote}/{rclone_path}/")
        return

    target = f"{rclone_remote}/{rclone_path}/"
    print(f"  Uploading to {target}...", end=" ")
    sys.stdout.flush()
    try:
        r = _run(
            ["rclone", "copy", str(archive_path.parent) + "/",
             target, "--include", f"{archive_path.name}*"],
            timeout=300, check=False,
        )
        if r.returncode == 0:
            print("OK")
        else:
            print(f"FAILED: {r.stderr.strip()[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Logical GMP XML backup manager (job02)"
    )
    ap.add_argument("--dry-run", action="store_true",
                     help="Print actions without making changes")
    ap.add_argument("--no-upload", action="store_true",
                     help="Skip any upload operations")
    ap.add_argument("--upload", action="store_true",
                     help="Enable upload (gated by env + rclone)")
    ap.add_argument("--backup-dir", default=None,
                     help="Override backup directory")
    ap.add_argument("--rclone-remote", default=None,
                     help="Override rclone remote (e.g. do:testmonbck)")
    ap.add_argument("--retention-local", type=int, default=None,
                     help=f"Override local retention (default: {DEFAULT_RETENTION_LOCAL})")
    ap.add_argument("--retention-cloud", type=int, default=None,
                     help=f"Override cloud retention (default: {DEFAULT_RETENTION_CLOUD})")
    ap.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE,
                     help=f"Override compose file (default: {DEFAULT_COMPOSE_FILE})")
    ap.add_argument("--gmp-socket", default=DEFAULT_GMP_SOCKET,
                     help=f"Override GMP socket path inside container (default: {DEFAULT_GMP_SOCKET})")
    ap.add_argument("--version", action="version",
                     version=f"%(prog)s v{VERSION}")
    args = ap.parse_args()

    # ── Root check ──
    if os.geteuid() != 0:
        print("[ERROR] This tool must be run as root.", file=sys.stderr)
        return 1

    # ── Load GMP credentials from env ──
    gmp_username = os.environ.get(ENV_GMP_USERNAME, "admin")
    gmp_password = os.environ.get(ENV_GMP_PASSWORD, "")
    if not gmp_password:
        print(f"[ERROR] {ENV_GMP_PASSWORD} environment variable is not set or is empty.",
              file=sys.stderr)
        print(f"[ERROR] Set {ENV_GMP_PASSWORD} to the GMP admin password and retry.",
              file=sys.stderr)
        return 1

    # ── Compose file ──
    compose_file = Path(args.compose_file)

    # ── Backup dir ──
    backup_dir = Path(args.backup_dir) if args.backup_dir \
        else Path("/var/backups/greenbone")

    # ── Dry-run validation ──
    if args.dry_run:
        print(f"greenbone_manage_job02_logical.py v{VERSION}  [DRY-RUN]")
        print(f"Backup profile: {BACKUP_PROFILE}")
        print()

        valid = validate_dry_run(compose_file, args.gmp_socket, gmp_username)
        if valid:
            print()
            print("[DRY-RUN] All prerequisites satisfied.")
            print("[DRY-RUN] Would export: tasks, targets, port lists, scan configs, schedules, alerts, reports")
            print("[DRY-RUN] Would save to: greenbone-logical-<host>-<ts>.tar.gz")
            print(f"[DRY-RUN] Local retention: {args.retention_local or DEFAULT_RETENTION_LOCAL}")
            print(f"[DRY-RUN] Cloud upload: {'would check gates' if args.upload else 'disabled'}")
        else:
            print()
            print("[DRY-RUN] Some checks FAILED. See messages above.", file=sys.stderr)
            return 1
        return 0

    # ── Real backup ──
    print(f"greenbone_manage_job02_logical.py v{VERSION}")
    print(f"Backup profile: {BACKUP_PROFILE}")

    # Create export directory
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    host_short = socket.gethostname().split(".")[0]
    export_rel = f"job02-logical/{ts}"
    export_dir = backup_dir / export_rel
    export_dir.mkdir(parents=True, exist_ok=True)
    print(f"Export directory: {export_dir}")

    # Run exports
    print("Exporting GMP objects...")
    files_written = run_exports(
        export_dir, gmp_username, gmp_password, compose_file,
        dry_run=False,
    )

    if not files_written:
        print("[ERROR] No files were exported. Aborting.", file=sys.stderr)
        return 1

    print(f"Exported {len(files_written)} object file(s).")

    # Build archive
    archive_name = f"greenbone-logical-{host_short}-{ts}.tar.gz"
    archive_path = export_dir.parent / archive_name

    print("Creating archive...")
    result = create_archive(export_dir, archive_path)
    if not result:
        print("[ERROR] Archive creation failed.", file=sys.stderr)
        return 1

    archive_size = archive_path.stat().st_size
    print(f"Archive: {archive_path.name} ({archive_size} bytes)")

    # Move archive to backup_dir root (alongside job00/job01 archives)
    dest_archive = backup_dir / archive_name
    shutil.move(str(archive_path), str(dest_archive))
    archive_path = dest_archive

    # Checksum
    checksum = sha256sum(archive_path)
    print(f"SHA256: {checksum}")

    # Metadata
    gmp_version_xml = ""
    gmp_version_path = export_dir / "gmp-version.xml"
    if gmp_version_path.exists():
        gmp_version_xml = gmp_version_path.read_text(encoding="utf-8")

    metadata = build_metadata(
        archive_name=archive_path.name,
        archive_size_bytes=archive_size,
        checksum=checksum,
        hostname_short=host_short,
        files_written=files_written,
        gmp_version_response=gmp_version_xml,
    )

    # Sidecars
    write_sidecars(archive_path, metadata, checksum)

    # Upload gate
    should_upload_flag = args.upload and not args.no_upload
    env_gate = os.environ.get("GREENBONE_BACKUP_UPLOAD", "") == "1"

    should_upload = should_upload_flag and env_gate
    if should_upload_flag and not env_gate:
        print("Upload requested but GREENBONE_BACKUP_UPLOAD is not set to 1. Skipping upload.")

    rclone_remote = args.rclone_remote or "do:testmonbck"
    rclone_path = "greenbone-backups/job02-logical"

    if should_upload:
        if _validate_rclone(rclone_remote):
            _upload_archive(archive_path, rclone_remote, rclone_path)
        else:
            print("rclone validation FAILED. Upload disabled.")

    # Local retention
    retention_local = args.retention_local or DEFAULT_RETENTION_LOCAL
    print(f"Applying local retention (keep={retention_local})...")
    apply_local_retention(backup_dir, "greenbone-logical-*.tar.gz",
                           retention_local)

    print("Job02 logical backup completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
