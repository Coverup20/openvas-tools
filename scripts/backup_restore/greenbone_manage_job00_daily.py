#!/usr/bin/env python3
"""
greenbone_manage_job00_daily.py - Daily compressed backup manager (job00)

Manages daily Greenbone/OpenVAS backups by:
- invoking greenbone_backup.py to create DR archives
- enforcing local retention (keep newest N)
- optionally uploading to cloud via rclone (gated and disabled by default)
- optionally enforcing cloud retention (keep newest N objects under a prefix)

Defaults (override via CLI or env):
  BACKUP_DIR=/var/backups/greenbone
  BACKUP_PATTERN=*job00-complete*   (name tag used when compressing or categorizing)
  RETENTION_LOCAL=90
  RETENTION_CLOUD=90
  TMP_DIR=/opt/greenbone-backup/tmp
  RCLONE_REMOTE=do:testmonbck
  RCLONE_PATH=greenbone-backups/job00-daily
  LOG_FILE=/var/log/greenbone-backup-job00.log

Upload is executed only if BOTH are true:
  --upload flag is passed AND GREENBONE_BACKUP_UPLOAD=1 in the environment.

Version: 0.1.0
"""

import argparse
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List


VERSION = "0.1.0"


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def iso_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{iso_ts()}] {msg}")


def err(msg: str) -> None:
    print(f"[{iso_ts()}] ERROR: {msg}")


@dataclass
class Conf:
    backup_dir: Path
    backup_pattern: str
    retention_local: int
    retention_cloud: int
    tmp_dir: Path
    rclone_remote: str
    rclone_path: str
    log_file: Path
    greenbone_dir: Path
    compose_file: Path


def env_or(name: str, default: str) -> str:
    return os.environ.get(name, default)


def build_conf(args: argparse.Namespace) -> Conf:
    return Conf(
        backup_dir=Path(args.backup_dir),
        backup_pattern=args.backup_pattern,
        retention_local=args.retention_local,
        retention_cloud=args.retention_cloud,
        tmp_dir=Path(args.tmp_dir),
        rclone_remote=args.rclone_remote,
        rclone_path=args.rclone_path,
        log_file=Path(args.log_file),
        greenbone_dir=Path(args.greenbone_dir),
        compose_file=Path(args.compose_file),
    )


def discover_backups(conf: Conf) -> List[Path]:
    if not conf.backup_dir.exists():
        return []
    # Only match job00 config backups, not job01 full backups
    return sorted(conf.backup_dir.glob("greenbone-dr-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)


def keep_newest(paths: List[Path], keep: int) -> (List[Path], List[Path]):
    return paths[:keep], paths[keep:]


def local_retention(conf: Conf, dry_run: bool) -> None:
    backups = discover_backups(conf)
    if not backups:
        log("No backups found for local retention.")
        return
    keep, delete = keep_newest(backups, conf.retention_local)
    log(f"Local retention: keep={len(keep)} delete={len(delete)} (limit={conf.retention_local})")
    for p in delete:
        if dry_run:
            log(f"[DRY-RUN] Would delete local backup: {p}")
        else:
            try:
                p.unlink(missing_ok=True)
                # also remove sidecar files (metadata/sha/restore) if present
                base = p.name.replace(".tar.gz", "")
                for ext in (".metadata.json", ".sha256", ".restore.md"):
                    side = p.parent / f"{base}{ext}"
                    side.unlink(missing_ok=True)
            except Exception as e:
                err(f"Unable to delete {p}: {e}")


def cloud_retention(conf: Conf, dry_run: bool) -> None:
    # Best-effort: list remote objects under the configured prefix and trim to newest N
    # We must not print secrets; rclone config is assumed pre-configured.
    cmd = ["rclone", "lsjson", f"{conf.rclone_remote}/{conf.rclone_path}"]
    r = run(cmd, check=False)
    if r.returncode != 0 or not r.stdout:
        log("Cloud retention: unable to list remote objects (skipping).")
        return
    try:
        import json as _json
        objects = _json.loads(r.stdout)
    except Exception:
        log("Cloud retention: invalid JSON from rclone lsjson (skipping).")
        return

    # Filter objects that look like our job00 config backups (greenbone-dr- prefix)
    items = [o for o in objects if isinstance(o, dict) and o.get("Name", "").startswith("greenbone-dr-")]
    # Sort newest first by ModTime or name fallback
    try:
        items.sort(key=lambda o: o.get("ModTime", ""), reverse=True)
    except Exception:
        items.sort(key=lambda o: o.get("Name", ""), reverse=True)

    keep = items[: conf.retention_cloud]
    delete = items[conf.retention_cloud :]
    log(f"Cloud retention under {conf.rclone_remote}/{conf.rclone_path}: keep={len(keep)} delete={len(delete)} (limit={conf.retention_cloud})")
    for o in delete:
        name = o.get("Name")
        if not name:
            continue
        del_cmd = [
            "rclone",
            "deletefile",
            f"{conf.rclone_remote}/{conf.rclone_path}/{name}",
        ]
        if dry_run:
            log(f"[DRY-RUN] Would delete remote object: {conf.rclone_remote}/{conf.rclone_path}/{name}")
        else:
            rr = run(del_cmd, check=False)
            if rr.returncode != 0:
                err(f"Unable to delete remote object {name}: {rr.stderr.strip()}")


def run_backup(conf: Conf, dry_run: bool, upload: bool, no_upload: bool) -> None:
    # Delegate to greenbone_backup.py for archive + metadata + checksum + restore
    script = Path(__file__).with_name("greenbone_backup.py")
    if not script.exists():
        err(f"Missing core backup script: {script}")
        return
    cmd = [
        str(script),
        "--greenbone-dir", str(conf.greenbone_dir),
        "--compose-file", str(conf.compose_file),
        "--backup-base-dir", str(conf.backup_dir),
        "--tmp-dir", str(conf.tmp_dir),
        "--rclone-remote", conf.rclone_remote,
        "--rclone-path", conf.rclone_path,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if upload:
        cmd.append("--upload")
    if no_upload:
        cmd.append("--no-upload")

    log("Invoking core backup script (safe mode)...")
    r = run(cmd, check=False)
    if r.returncode != 0:
        err(f"Backup script failed: {r.stderr.strip()}")
    else:
        log("Backup script finished.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily job00 manager for Greenbone backups")
    ap.add_argument("--dry-run", action="store_true", help="Do not delete or upload; print planned actions")
    ap.add_argument("--no-upload", action="store_true", help="Skip any upload operations")
    ap.add_argument("--upload", action="store_true", help="Enable upload (still gated by env)")

    ap.add_argument("--backup-dir", default=env_or("BACKUP_DIR", "/var/backups/greenbone"))
    ap.add_argument("--backup-pattern", default=env_or("BACKUP_PATTERN", "*job00-complete*"))
    ap.add_argument("--retention-local", type=int, default=int(env_or("RETENTION_LOCAL", "90")))
    ap.add_argument("--retention-cloud", type=int, default=int(env_or("RETENTION_CLOUD", "90")))
    ap.add_argument("--tmp-dir", default=env_or("TMP_DIR", "/opt/greenbone-backup/tmp"))
    ap.add_argument("--rclone-remote", default=env_or("RCLONE_REMOTE", "do:testmonbck"))
    ap.add_argument("--rclone-path", default=env_or("RCLONE_PATH", "greenbone-backups/job00-daily"))
    ap.add_argument("--log-file", default=env_or("LOG_FILE", "/var/log/greenbone-backup-job00.log"))
    ap.add_argument("--greenbone-dir", default=env_or("GREENBONE_DIR", "/opt/greenbone-community"))
    ap.add_argument("--compose-file", default=env_or("COMPOSE_FILE", "/opt/greenbone-community/compose.yaml"))

    args = ap.parse_args()
    conf = build_conf(args)

    # 1) Create a fresh DR backup (safe)
    run_backup(conf, dry_run=args.dry_run, upload=args.upload, no_upload=args.no_upload)

    # 2) Enforce local retention
    local_retention(conf, dry_run=args.dry_run)

    # 3) Optional cloud retention if upload gate is open
    if args.upload and not args.no_upload and os.environ.get("GREENBONE_BACKUP_UPLOAD") == "1":
        cloud_retention(conf, dry_run=args.dry_run)
    else:
        log("Cloud retention: skipped (upload gate disabled or not requested).")

    log("Job00 daily manager completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
