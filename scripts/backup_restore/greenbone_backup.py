#!/usr/bin/env python3
"""
greenbone_backup.py - Greenbone/OpenVAS Configuration Backup Tool

Produces a lightweight configuration/inventory snapshot for Greenbone
Community Containers (Docker Compose). Includes compose file, project files,
service inventory, metadata JSON, SHA256 checksum, and restore instructions.

This is a CONFIGURATION backup only (fast, small, daily).
For full DR, use Timeshift local snapshots (database, volumes, feeds).

Upload via rclone is disabled by default and gated behind explicit flags.

Defaults (override via CLI args or env):
  GREENBONE_DIR=/opt/greenbone-community
  COMPOSE_FILE=/opt/greenbone-community/compose.yaml
  BACKUP_BASE_DIR=/opt/greenbone-backup
  TMP_DIR=/opt/greenbone-backup/tmp
  RCLONE_REMOTE=do:testmonbck
  RCLONE_PATH=greenbone-backups/job00-daily

Safety:
  - Does NOT stop containers.
  - Does NOT modify Docker resources.
  - Volume data is NOT included.
  - Upload disabled unless --upload AND GREENBONE_BACKUP_UPLOAD=1.

Version: 0.2.0
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


VERSION = "0.2.0"

ENV_DEFAULTS = {
    "GREENBONE_DIR": "/opt/greenbone-community",
    "COMPOSE_FILE": "/opt/greenbone-community/compose.yaml",
    "BACKUP_BASE_DIR": "/opt/greenbone-backup",
    "TMP_DIR": "/opt/greenbone-backup/tmp",
    "RCLONE_REMOTE": "do:testmonbck",
    "RCLONE_PATH": "greenbone-backups/job00-daily",
}


def env_or_default(name: str) -> str:
    return os.environ.get(name, ENV_DEFAULTS[name])


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%F %T')}] {msg}")


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def docker_version() -> str:
    try:
        r = run(["docker", "--version"], check=False)
        return (r.stdout or r.stderr or "").strip()
    except Exception:
        return "unavailable"


def compose_version() -> str:
    try:
        r = run(["docker", "compose", "version"], check=False)
        return (r.stdout or r.stderr or "").strip()
    except Exception:
        return "unavailable"


def docker_compose_config_services(compose_file: Path) -> List[str]:
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "config", "--services"], check=False)
        if r.returncode == 0 and r.stdout:
            return [s.strip() for s in r.stdout.splitlines() if s.strip()]
    except Exception:
        pass
    return []


def docker_ps_all(compose_file: Path) -> str:
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "ps", "--all"], check=False)
        return (r.stdout or r.stderr or "").strip()
    except Exception:
        return ""


def docker_images() -> List[str]:
    try:
        r = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"], check=False)
        if r.returncode == 0 and r.stdout:
            return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def docker_volumes_inventory() -> List[Dict[str, str]]:
    try:
        r = run(["docker", "volume", "ls", "--format", "{{.Name}} {{.Driver}}"], check=False)
        vols: List[Dict[str, str]] = []
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                parts = line.split()
                if not parts:
                    continue
                vols.append({"name": parts[0], "driver": parts[1] if len(parts) > 1 else "unknown"})
        return vols
    except Exception:
        return []


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def collect_os_pretty_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "unknown"


def build_restore_instructions(archive_name: str, checksum: str, project_dir: Path, compose_file: Path, full: bool = False) -> str:
    if full:
        return "\n".join([
            "=== Greenbone/OpenVAS Restore Instructions (Full DR Backup) ===",
            "",
            "This is a FULL backup including:",
            "  - PostgreSQL database dump (gvmd-database.sql)",
            "  - Docker volume data archives (*.tar.gz)",
            "  - Compose file and project configuration",
            "  - Service inventory snapshot",
            "",
            "PREREQUISITES:",
            "  - Docker and Docker Compose plugin installed",
            f"  - Project directory: {project_dir}",
            f"  - Compose file: {compose_file}",
            "",
            "RESTORE:",
            f"  1) Ensure project directory exists: mkdir -p {project_dir}",
            f"  2) Extract archive: tar xzf {archive_name} -C /",
            "  3) Restore PostgreSQL database:",
            "     docker compose -f {0} up -d pg-gvm".format(compose_file),
            "     sleep 15",
            "     cat gvmd-database.sql | docker compose -f {0} exec -T pg-gvm psql -U gvm -d gvmd".format(compose_file),
            "  4) Start full stack:",
            f"     cd {project_dir} && docker compose up -d --remove-orphans",
            "  5) Validate: docker compose ps --all",
            "",
            f"Checksum (SHA256): {checksum}",
        ]) + "\n"
    return "\n".join([
        "=== Greenbone/OpenVAS Restore Instructions (Config Backup) ===",
        "",
        "This is a configuration/inventory backup only.",
        "For full DR, use the weekly job01-full backup or Timeshift.",
        "",
        "CONTENTS:",
        "  - Compose file and project configuration",
        "  - Service inventory snapshot",
        "",
        "PREREQUISITES:",
        "  - Docker and Docker Compose plugin installed",
        f"  - Project directory: {project_dir}",
        f"  - Compose file: {compose_file}",
        "",
        "RESTORE:",
        f"  1) Ensure project directory exists: mkdir -p {project_dir}",
        f"  2) Extract archive: tar xzf {archive_name} -C /",
        "  3) Start stack and validate",
        "",
        f"Checksum (SHA256): {checksum}",
    ]) + "\n"


def backup_database(compose_file: Path, tmpdir: Path):
    """pg_dump the gvmd database."""
    log("Backing up PostgreSQL database (pg_dump)...")
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
                 "pg_dump", "-U", "gvmd", "-d", "gvmd", "--clean", "--if-exists"], check=False)
        if r.returncode == 0 and len(r.stdout or "") > 100:
            p = tmpdir / "gvmd-database.sql"
            p.write_text(r.stdout, encoding="utf-8")
            log(f"  DB dump: {len(r.stdout)} bytes")
            return p
        log(f"  pg_dump failed (exit={r.returncode})")
    except Exception as e:
        log(f"  pg_dump error: {e}")
    return None


def backup_volume(volume_name: str, tmpdir: Path):
    """Tar a Docker volume."""
    out_name = volume_name.replace("/", "_") + ".tar.gz"
    out_path = tmpdir / out_name
    log(f"  Backing up volume: {volume_name} ...")
    try:
        r = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{volume_name}:/volume:ro",
             "-v", f"{tmpdir}:/backup",
             "docker.io/busybox:latest", "tar", "czf", f"/backup/{out_name}", "-C", "/volume", "."],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        if r.returncode == 0 and out_path.exists():
            log(f"    -> {out_path.stat().st_size} bytes")
            return out_path
        log(f"    failed: {r.stderr[:200]}")
    except Exception as e:
        log(f"    error: {e}")
    return None


def volume_names_from_compose(compose_file: Path):
    """Get named volumes from compose config."""
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "config", "--volumes"], check=False)
        if r.returncode == 0 and r.stdout:
            return [v.strip() for v in r.stdout.splitlines() if v.strip()]
    except Exception:
        pass
    return []


def build_metadata(
    archive_path: Path, checksum: str, project_dir: Path, compose_file: Path,
    services: List[str], images: List[str], volumes: List[Dict[str, str]],
    upload_enabled: bool, rclone_remote: str, rclone_path: str,
    full: bool = False, db_dump_size: int = 0, vol_count: int = 0,
) -> Dict[str, Any]:
    stat = archive_path.stat() if archive_path.exists() else None
    bt = "full_dr" if full else "config_inventory"
    md = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": os.uname().nodename,
        "os_pretty_name": collect_os_pretty_name(),
        "kernel": os.uname().release,
        "script_version": VERSION,
        "backup_type": bt,
        "greenbone_project_dir": str(project_dir),
        "compose_file": str(compose_file),
        "docker_version": docker_version(),
        "docker_compose_version": compose_version(),
        "containers": services,
        "images": images,
        "volumes": volumes,
        "archive_name": archive_path.name,
        "archive_size_bytes": stat.st_size if stat else 0,
        "sha256": checksum,
        "upload_enabled": upload_enabled,
    }
    if full:
        md["db_dump_size_bytes"] = db_dump_size
        md["volume_archives_count"] = vol_count
        md["note"] = "Full DR backup with PostgreSQL dump + Docker volumes"
    else:
        md["full_dr_method"] = "Timeshift local snapshot or job01-bi-weekly"
    if upload_enabled:
        md["rclone_remote"] = rclone_remote
        md["rclone_path"] = rclone_path
    return md


def create_archive(tmpdir: Path, project_dir: Path, compose_file: Path, name_prefix: str, full: bool = False):
    ensure_dir(tmpdir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    hostname = os.uname().nodename
    archive_name = f"{name_prefix}-{hostname}-{ts}.tar.gz"
    archive_path = tmpdir / archive_name
    db_dump = None
    vol_archives = []
    files_to_add = []

    # Phase 1: Config files
    log("Phase 1: Collecting configuration...")
    if compose_file.exists():
        files_to_add.append((str(compose_file), compose_file))
    if project_dir.exists():
        for child in project_dir.iterdir():
            if child.is_file() and not child.name.lower().endswith(".env") and "secret" not in child.name.lower():
                files_to_add.append((str(child), child))
    try:
        ps_out = docker_ps_all(compose_file)
        snap = tmpdir / "compose-ps.txt"
        snap.write_text(ps_out + "\n", encoding="utf-8")
        files_to_add.append(("/opt/greenbone-backup/compose-ps.txt", snap))
    except Exception:
        pass

    if full:
        # Phase 2: PostgreSQL dump
        log("Phase 2: Backing up PostgreSQL database...")
        db_dump = backup_database(compose_file, tmpdir)
        if db_dump and db_dump.exists():
            files_to_add.append((str(db_dump), db_dump))

        # Phase 3: Docker volumes
        log("Phase 3: Backing up Docker volumes (best-effort)...")
        for vol in volume_names_from_compose(compose_file):
            if "pg-gvm" in vol.lower():
                log(f"  Skipping {vol} (handled via pg_dump)")
                continue
            va = backup_volume(vol, tmpdir)
            if va:
                vol_archives.append(va)
                files_to_add.append((str(va), va))

    # Phase 4: Create archive with all collected files
    log(f"Phase 4: Creating archive ({len(files_to_add)} items)...")
    with tarfile.open(archive_path, mode="w:gz") as tar:
        for arcname, src in files_to_add:
            try:
                tar.add(str(src), arcname=arcname)
            except Exception:
                pass

    return archive_path, db_dump, vol_archives


def maybe_upload(archive: Path, metadata_file: Path, checksum_file: Path, *,
                 upload: bool, env_gate_ok: bool, rclone_remote: str, rclone_path: str, dry_run: bool) -> None:
    if not upload or not env_gate_ok:
        return
    if dry_run:
        print(f"[DRY-RUN] Would upload to {rclone_remote}/{rclone_path}")
        return
    up_dir = Path(tempfile.mkdtemp(prefix="gb-upload-"))
    try:
        for src in [archive, metadata_file, checksum_file]:
            if src.exists():
                (up_dir / src.name).write_bytes(src.read_bytes())
        log(f"Uploading to {rclone_remote}/{rclone_path}/ ...")
        cb = run(["rclone", "copy", str(up_dir) + "/", f"{rclone_remote}/{rclone_path}/"], check=False)
        if cb.returncode == 0:
            log("Upload complete.")
        else:
            log(f"Upload FAILED: {cb.stderr.strip()}")
    finally:
        shutil.rmtree(up_dir, ignore_errors=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Greenbone/OpenVAS backup (config or full DR)")
    p.add_argument("--greenbone-dir", default=env_or_default("GREENBONE_DIR"))
    p.add_argument("--compose-file", default=env_or_default("COMPOSE_FILE"))
    p.add_argument("--backup-base-dir", default=env_or_default("BACKUP_BASE_DIR"))
    p.add_argument("--tmp-dir", default=env_or_default("TMP_DIR"))
    p.add_argument("--rclone-remote", default=env_or_default("RCLONE_REMOTE"))
    p.add_argument("--rclone-path", default=env_or_default("RCLONE_PATH"))
    p.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    p.add_argument("--no-upload", action="store_true", help="Skip upload")
    p.add_argument("--upload", action="store_true", help="Enable upload (gated by env)")
    p.add_argument("--full", action="store_true", help="Full DR backup (includes DB dump + volumes)")
    args = p.parse_args()

    project_dir = Path(args.greenbone_dir)
    compose_file = Path(args.compose_file)
    backup_base = Path(args.backup_base_dir)
    tmpdir = Path(args.tmp_dir)
    ensure_dir(backup_base)
    ensure_dir(tmpdir)

    services = docker_compose_config_services(compose_file)
    images = docker_images()
    volumes = docker_volumes_inventory()

    prefix = "greenbone-full" if args.full else "greenbone-dr"
    bt = "FULL DR" if args.full else "config"
    log(f"Creating {bt} backup...")
    archive, db_dump, vol_archives = create_archive(tmpdir, project_dir, compose_file, name_prefix=prefix, full=args.full)
    checksum = sha256sum(archive)
    log(f"Archive: {archive.name} ({archive.stat().st_size} bytes)")

    dest_archive = backup_base / archive.name
    if args.dry_run:
        print(f"[DRY-RUN] Would save to {dest_archive}")
    else:
        shutil.move(str(archive), str(dest_archive))

    base_name = dest_archive.name.replace(".tar.gz", "")

    checksum_file = backup_base / f"{base_name}.sha256"
    metadata_file = backup_base / f"{base_name}.metadata.json"
    restore_file = backup_base / f"{base_name}.restore.md"

    db_size = db_dump.stat().st_size if db_dump and db_dump.exists() else 0
    vc = len([v for v in vol_archives if v and v.exists()])

    md = build_metadata(
        dest_archive if not args.dry_run else archive, checksum,
        project_dir, compose_file, services, images, volumes,
        upload_enabled=(args.upload and not args.no_upload and os.environ.get("GREENBONE_BACKUP_UPLOAD") == "1"),
        rclone_remote=args.rclone_remote, rclone_path=args.rclone_path,
        full=args.full, db_dump_size=db_size, vol_count=vc,
    )

    if args.dry_run:
        print("[DRY-RUN] Metadata:", json.dumps(md, indent=2))
        print(f"[DRY-RUN] Would write: {checksum_file}, {metadata_file}, {restore_file}")
    else:
        checksum_file.write_text(f"{checksum}  {dest_archive.name}\n", encoding="utf-8")
        metadata_file.write_text(json.dumps(md, indent=2) + "\n", encoding="utf-8")
        restore_file.write_text(
            build_restore_instructions(dest_archive.name, checksum, project_dir, compose_file, full=args.full),
            encoding="utf-8",
        )

    env_gate = os.environ.get("GREENBONE_BACKUP_UPLOAD") == "1"
    upload_flag = (args.upload and not args.no_upload)
    maybe_upload(dest_archive, metadata_file, checksum_file,
                 upload=upload_flag, env_gate_ok=env_gate,
                 rclone_remote=args.rclone_remote, rclone_path=args.rclone_path,
                 dry_run=args.dry_run)

    log("Backup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
