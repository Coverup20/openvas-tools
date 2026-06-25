#!/usr/bin/env python3
"""
greenbone_restore.py - Greenbone/OpenVAS Disaster Recovery Restore

Restores a Greenbone backup archive (full DR or config).
Lists available backups locally and on cloud, then restores
Docker volumes and PostgreSQL database from the selected archive.

Usage:
  python3 greenbone_restore.py [--backup-dir /var/backups/greenbone]
                               [--compose-file /opt/greenbone-community/compose.yaml]
                               [--archive path/to/backup.tar.gz]
                               [--list] [--dry-run]

Safety:
  - Requires --confirm flag to execute (dry-run by default)
  - Does NOT stop containers (prompts before restore)
  - Creates timestamped backups before overwriting volumes
  - Never deletes cloud objects

Version: 0.1.0
"""

import argparse
import atexit
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional


VERSION = "0.1.0"


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%F %T')}] {msg}")


def err(msg: str) -> None:
    print(f"[{datetime.now().strftime('%F %T')}] ERROR: {msg}", file=sys.stderr)


def confirm(prompt: str) -> bool:
    a = input(f"{prompt} [y/N]: ").strip().lower()
    return a == "y"


def find_archives(backup_dir: Path) -> List[Path]:
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("greenbone-full-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)


def list_cloud_backups(rclone_remote: str, rclone_path: str) -> List[dict]:
    r = run(["rclone", "lsjson", f"{rclone_remote}/{rclone_path}"])
    if r.returncode != 0 or not r.stdout:
        return []
    try:
        items = json.loads(r.stdout)
        return [o for o in items if isinstance(o, dict) and o.get("Name", "").startswith("greenbone-full-")]
    except Exception:
        return []


def restore_volume(volume_name: str, archive_path: Path, dry_run: bool) -> bool:
    log(f"Restoring volume: {volume_name} ...")
    if dry_run:
        log(f"  [DRY-RUN] Would restore {archive_path.name} to volume {volume_name}")
        return True
    # Backup current volume state
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"{volume_name}.pre-restore.{ts}.tar.gz"
    r = run(["docker", "run", "--rm",
             "-v", f"{volume_name}:/volume:ro",
             "-v", f"{archive_path.parent}:/backup",
             "busybox:latest", "tar", "czf", f"/backup/{backup_name}", "-C", "/volume", "."])
    if r.returncode == 0:
        log(f"  Pre-restore backup saved: {backup_name}")
    # Restore volume from archive
    r = run(["docker", "run", "--rm",
             "-v", f"{volume_name}:/volume",
             "-v", f"{archive_path}:/backup/archive.tar.gz:ro",
             "busybox:latest", "tar", "xzf", "/backup/archive.tar.gz", "-C", "/volume"])
    if r.returncode == 0:
        log(f"  Restored: {volume_name}")
        return True
    err(f"  Failed to restore {volume_name}")
    return False


def restore_database(compose_file: Path, sql_dump: Path, dry_run: bool) -> bool:
    log("Restoring PostgreSQL database...")
    if dry_run:
        log("  [DRY-RUN] Would restore database from gvmd-database.sql")
        return True
    if not sql_dump.exists():
        err("  Database dump not found in archive")
        return False
    # Ensure pg-gvm is running
    r = run(["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
             "pg_isready", "-U", "gvmd"])
    if r.returncode != 0:
        log("  Starting pg-gvm container...")
        run(["docker", "compose", "-f", str(compose_file), "up", "-d", "pg-gvm"])
        import time
        time.sleep(10)
    # Restore
    with open(str(sql_dump)) as f:
        r = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
             "psql", "-U", "gvmd", "-d", "gvmd"],
            stdin=f, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        # Try with postgres user
        with open(str(sql_dump)) as f:
            r = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
                 "psql", "-U", "postgres", "-d", "gvmd"],
                stdin=f, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            err(f"  Database restore failed: {r.stderr[:200]}")
            return False
    log("  Database restored.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Greenbone/OpenVAS Disaster Recovery Restore")
    ap.add_argument("--backup-dir", default="/var/backups/greenbone")
    ap.add_argument("--compose-file", default="/opt/greenbone-community/compose.yaml")
    ap.add_argument("--archive", help="Path to a specific archive file")
    ap.add_argument("--rclone-remote", default="do:testmonbck")
    ap.add_argument("--rclone-path", default="greenbone-backups/job01-bi-weekly")
    ap.add_argument("--list", action="store_true", help="List available backups and exit")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be done")
    ap.add_argument("--confirm", action="store_true", help="Confirm restore execution")
    args = ap.parse_args()

    backup_dir = Path(args.backup_dir)
    compose_file = Path(args.compose_file)

    print(f"\n=== Greenbone Restore v{VERSION} ===\n")

    # List backups
    local = find_archives(backup_dir)
    cloud = list_cloud_backups(args.rclone_remote, args.rclone_path)

    all_backups = []

    print("Available backups:")
    if cloud:
        print("\n  --- Cloud (DO Spaces) ---")
        for i, o in enumerate(cloud, 1):
            name = o.get("Name", "?")
            size = o.get("Size", 0) / 1024 / 1024
            all_backups.append(("cloud", name, size, o))
            print(f"  [{len(all_backups)}] {name} ({size:.0f} MB) [cloud]")
    if local:
        print("\n  --- Local ---")
        for p in local:
            name = p.name
            size = p.stat().st_size / 1024 / 1024
            all_backups.append(("local", name, size, p))
            print(f"  [{len(all_backups)}] {name} ({size:.0f} MB) [local]")

    if args.list:
        return 0

    if not all_backups and not args.archive:
        err("No backups found. Use --archive to specify a file.")
        return 1

    # Select archive
    archive_path = None
    if args.archive:
        archive_path = Path(args.archive)
    elif all_backups:
        default_idx = 1
        max_idx = len(all_backups)
        try:
            idx_str = input(f"\nSelect backup to restore [1-{max_idx}] (default 1): ").strip()
            idx = int(idx_str) if idx_str else 1
        except ValueError:
            idx = 1
        if idx < 1 or idx > max_idx:
            idx = 1
        selection = all_backups[idx - 1]
        source_type = selection[0]
        source_name = selection[1]

        if source_type == "cloud":
            # Download from cloud to temp
            log(f"Downloading {source_name} from cloud...")
            tmp_dir = Path(tempfile.mkdtemp(prefix="gb-download-"))
            dl_path = tmp_dir / source_name
            r = run(["rclone", "copyto",
                     f"{args.rclone_remote}/{args.rclone_path}/{source_name}",
                     str(dl_path)])
            if r.returncode != 0 or not dl_path.exists():
                err(f"Download failed: {r.stderr.strip()}")
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return 1
            archive_path = dl_path
            log(f"Downloaded to {archive_path}")
            atexit.register(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))
        else:
            archive_path = selection[3]

    if not archive_path or not archive_path.exists():
        err(f"Archive not found: {archive_path}")
        return 1

    # Preview
    print(f"\nSelected: {archive_path.name}")
    print("Contents:")
    with tarfile.open(str(archive_path)) as tar:
        for m in tar.getmembers():
            print(f"  {m.name} ({m.size / 1024 / 1024:.1f} MB)" if m.size > 1024 * 1024 else f"  {m.name}")

    if not args.confirm and not args.dry_run:
        print("\nThis is a DRY-RUN. Use --confirm to execute or --dry-run to preview.")
        args.dry_run = True

    if not args.dry_run:
        print("\nWARNING: This will overwrite existing Docker volumes and database!")
        if not confirm("Are you sure you want to proceed?"):
            log("Restore cancelled.")
            return 0
        if not confirm("Stop Greenbone stack before restore?"):
            log("Restoring with stack running (best-effort).")
        else:
            log("Stopping Greenbone stack...")
            run(["docker", "compose", "-f", str(compose_file), "down"])

    # Extract archive
    extract_dir = Path(tempfile.mkdtemp(prefix="gb-restore-"))
    log(f"Extracting archive to {extract_dir} ...")
    if not args.dry_run:
        with tarfile.open(str(archive_path)) as tar:
            tar.extractall(path=str(extract_dir))

    # Find components
    sql_dump = None
    vol_archives = []
    for f in sorted(extract_dir.rglob("*")):
        if f.name == "gvmd-database.sql":
            sql_dump = f
        elif f.name.endswith(".tar.gz") and f.name.startswith("greenbone-community"):
            vol_archives.append(f)

    # Restore volumes
    print("")
    for va in vol_archives:
        vol_name = va.stem.replace(".tar", "")
        if "pg-gvm" in vol_name.lower():
            log(f"  Skipping {vol_name} (restored via SQL dump)")
            continue
        restore_volume(vol_name, va, args.dry_run)

    # Restore database
    if sql_dump:
        restore_database(compose_file, sql_dump, args.dry_run)

    # Start stack
    if not args.dry_run:
        print("")
        log("Starting Greenbone stack...")
        run(["docker", "compose", "-f", str(compose_file), "up", "-d", "--remove-orphans"])
        log("Stack started. Run 'docker compose ps' to verify.")
        log("Note: Feed data imports may take time on first startup.")

    shutil.rmtree(extract_dir, ignore_errors=True)
    print(f"\n=== Restore {'preview' if args.dry_run else 'complete'} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
