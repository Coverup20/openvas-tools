"""backup.py - Core backup logic for Greenbone.

Creates Checkmk-style backup snapshots:
  - Local archive (tar.gz) with compose file, project files, inventory
  - For full DR: PostgreSQL dump + Docker volume archives
  - Metadata JSON, SHA256 checksum, restore instructions sidecar files
  - Optional cloud upload via rclone (gated)

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .command import run, CommandError
from .config import BackupConfig
from .docker_compose import (
    compose_services,
    compose_volumes,
    compose_ps,
    docker_images_list,
    docker_volumes_inventory,
)
from .logging_utils import log, err
from .metadata import (
    build_metadata,
    sha256sum,
    write_checksum,
    write_metadata,
    write_restore_instructions,
)
from .rclone import validate_rclone_config, test_remote


# --- Progress reporting helpers ---


def _format_size(bytes_val: int) -> str:
    """Return human-readable size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val //= 1024
    return f"{bytes_val:.1f} PB"


def _format_elapsed(seconds: float) -> str:
    """Return HH:MM:SS from seconds."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _monitor_file_progress(filepath: Path, stop_event: threading.Event,
                           label: str, interval: float = 30.0,
                           estimate_bytes: Optional[int] = None) -> None:
    """Log file size growth every `interval` seconds until stop_event is set."""
    start = time.time()
    while not stop_event.wait(interval):
        if stop_event.is_set():
            break
        if filepath.exists():
            size = filepath.stat().st_size
            elapsed = time.time() - start
            pct = ""
            if estimate_bytes and estimate_bytes > 0:
                p = min(100.0, size / estimate_bytes * 100)
                pct = f", {p:.0f}%"
            log(f"[PROGRESS] {label}: {_format_size(size)} written, "
                f"elapsed {_format_elapsed(elapsed)}{pct}")


# --- Archive creation ---


def create_archive(
    tmpdir: Path,
    greenbone_dir: Path,
    compose_file: Path,
    name_prefix: str,
    full: bool = False,
) -> Tuple[Path, Optional[Path], List[Path]]:
    """Create the backup archive and return (archive_path, db_dump, vol_archives).

    For full backups, also produces a PostgreSQL dump and volume archives.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    host = _hostname()
    archive_name = f"{name_prefix}-{host}-{ts}.tar.gz"
    archive_path = tmpdir / archive_name

    files_to_add: List[Tuple[str, Path]] = []

    # Phase 1: Config files
    log("Phase 1: Collecting configuration...")
    if compose_file.exists():
        files_to_add.append((str(compose_file), compose_file))
    if greenbone_dir.exists():
        for child in greenbone_dir.iterdir():
            if child.is_file() and not child.name.lower().endswith(".env") and "secret" not in child.name.lower():
                files_to_add.append((str(child), child))

    # Service inventory snapshot (Checkmk-style state tracking)
    try:
        ps_out = compose_ps(compose_file)
        snap = tmpdir / "compose-ps.txt"
        snap.write_text(ps_out + "\n", encoding="utf-8")
        files_to_add.append(("/opt/greenbone-backup/compose-ps.txt", snap))
    except Exception:
        pass

    db_dump: Optional[Path] = None
    vol_archives: List[Path] = []

    if full:
        # Phase 2: PostgreSQL dump
        log("Phase 2: Backing up PostgreSQL database...")
        db_dump = _backup_database(compose_file, tmpdir)
        if db_dump and db_dump.exists():
            files_to_add.append((str(db_dump), db_dump))

        # Phase 3: Docker volumes (all volumes, matching VM 202 model)
        volumes = compose_volumes(compose_file)
        total_vols = len(volumes)
        log(f"Phase 3: Backing up Docker volumes ({total_vols} total, best-effort)...")
        for i, vol in enumerate(volumes, 1):
            log(f"[PROGRESS] volume backup: {i}/{total_vols} {vol}")
            va = _backup_volume(vol, tmpdir)
            if va:
                vol_archives.append(va)
                files_to_add.append((str(va), va))

    # Phase 4: Create archive (streaming gzip to .tmp, atomic rename)
    # The .tmp suffix prevents corrupt final archives if the process is interrupted.
    log(f"Phase 4: Creating archive ({len(files_to_add)} items)...")
    tmp_path = archive_path.with_name(archive_path.name + ".tmp")
    stop_event = threading.Event()
    monitor = threading.Thread(
        target=_monitor_file_progress,
        args=(tmp_path, stop_event, "archive", 30.0, None),
        daemon=True,
    )
    archive_start = time.time()
    try:
        monitor.start()
        with tarfile.open(tmp_path, mode="w:gz") as tar:
            for arcname, src in files_to_add:
                try:
                    tar.add(str(src), arcname=arcname)
                except Exception as e:
                    log(f"  Warning: failed to add {src}: {e}")
        stop_event.set()
        monitor.join(timeout=5)
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            tmp_path.rename(archive_path)  # Atomic rename to final name
            elapsed = time.time() - archive_start
            log(f"[PROGRESS] archive completed: {archive_path.name} "
                f"({_format_size(archive_path.stat().st_size)}), "
                f"elapsed {_format_elapsed(elapsed)}")
        else:
            log("  Warning: archive is empty or missing")
    except Exception as e:
        log(f"  Archive creation error: {e}")
        tmp_path.unlink(missing_ok=True)
        archive_path.unlink(missing_ok=True)
    finally:
        stop_event.set()

    return archive_path, db_dump, vol_archives


def run_backup(cfg: BackupConfig, full: bool = False) -> int:
    """Run the full backup workflow using the given config.

    Returns 0 on success, 1 on failure.
    """
    cfg.tmp_dir.mkdir(parents=True, exist_ok=True)
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)

    services = compose_services(cfg.compose_file)
    images = docker_images_list()
    volumes = docker_volumes_inventory()

    prefix = "greenbone-full" if full else "greenbone-dr"
    bt = "full_dr" if full else "config_inventory"
    log(f"Creating {bt} backup ({prefix})...")

    # In dry-run mode, skip heavy operations (pg_dump, volume tar)
    if cfg.dry_run:
        if full:
            log("[DRY-RUN] Would create full DR backup with: compose.yaml, compose-ps.txt, gvmd-database.sql, all Docker volumes")
            log("[DRY-RUN] Would apply retention: local=2, cloud=2")
        else:
            log("[DRY-RUN] Would create config backup with: compose.yaml, compose-ps.txt")
        log("[DRY-RUN] Return early (dry-run).")
        return 0

    archive, db_dump, vol_archives = create_archive(
        cfg.tmp_dir, cfg.greenbone_dir, cfg.compose_file,
        name_prefix=prefix, full=full,
    )

    checksum = sha256sum(archive)
    log(f"Archive: {archive.name} ({archive.stat().st_size} bytes)")

    dest_archive = cfg.backup_dir / archive.name
    if cfg.dry_run:
        print(f"[DRY-RUN] Would save to {dest_archive}")
        return 0

    shutil.move(str(archive), str(dest_archive))

    # Write sidecar files
    metadata = build_metadata(
        archive_name=dest_archive.name,
        archive_size_bytes=dest_archive.stat().st_size,
        checksum=checksum,
        backup_type=bt,
        compose_file=cfg.compose_file,
        greenbone_dir=cfg.greenbone_dir,
        services=services,
        images=images,
        volumes=volumes,
        upload_enabled=cfg.upload_enabled,
        rclone_remote=cfg.rclone_remote if cfg.upload_enabled else None,
        rclone_path=cfg.rclone_path if cfg.upload_enabled else None,
        db_dump_size=db_dump.stat().st_size if db_dump and db_dump.exists() else 0,
        volume_archives_count=len([v for v in vol_archives if v and v.exists()]),
    )

    write_checksum(dest_archive, checksum)
    write_metadata(dest_archive, metadata)
    write_restore_instructions(dest_archive, checksum, cfg.compose_file,
                                cfg.greenbone_dir, bt)
    log("Sidecar files written.")

    # Upload stage
    if cfg.upload_enabled:
        _maybe_upload(dest_archive, cfg)

    log("Backup complete.")
    return 0


def _backup_database(compose_file: Path, tmpdir: Path) -> Optional[Path]:
    """pg_dump the gvmd database, streaming output to disk (not in memory).

    Returns path to SQL dump or None on failure.
    Reports progress every 30s via background thread.
    """
    p = tmpdir / "gvmd-database.sql"
    cmd = [
        "docker", "compose", "-f", str(compose_file), "exec", "-T", "pg-gvm",
        "pg_dump", "-U", "gvmd", "-d", "gvmd", "--clean", "--if-exists",
    ]
    start = time.time()
    stop_event = threading.Event()
    monitor = threading.Thread(
        target=_monitor_file_progress,
        args=(p, stop_event, "pg_dump", 30.0, None),
        daemon=True,
    )
    try:
        with open(p, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.PIPE, text=True)
            monitor.start()
            try:
                proc.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
        stop_event.set()
        monitor.join(timeout=5)
        elapsed = time.time() - start
        if proc.returncode == 0 and p.stat().st_size > 100:
            log(f"  DB dump: {_format_size(p.stat().st_size)} (streamed to disk), "
                f"elapsed {_format_elapsed(elapsed)}")
            return p
        stderr_output = proc.stderr.read() if proc.stderr else ""
        log(f"  pg_dump failed (exit={proc.returncode}): {stderr_output[:200]}")
        p.unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        log("  pg_dump timed out after 1800s")
        p.unlink(missing_ok=True)
    except Exception as e:
        log(f"  pg_dump error: {e}")
        p.unlink(missing_ok=True)
    finally:
        stop_event.set()
    return None


def _backup_volume(volume_name: str, tmpdir: Path) -> Optional[Path]:
    """Tar a Docker volume into tmpdir.  Returns path to archive or None."""
    out_name = volume_name.replace("/", "_") + ".tar.gz"
    out_path = tmpdir / out_name
    log(f"  Backing up volume: {volume_name} ...")
    try:
        r = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{volume_name}:/volume:ro",
             "-v", f"{tmpdir}:/backup",
             "docker.io/busybox:latest",
             "tar", "czf", f"/backup/{out_name}", "-C", "/volume", "."],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=1800,
        )
        if r.returncode == 0 and out_path.exists():
            log(f"    -> {out_path.stat().st_size} bytes")
            return out_path
        log(f"    failed: {r.stderr[:200]}")
    except Exception as e:
        log(f"    error: {e}")
    return None


def _maybe_upload(archive: Path, cfg: BackupConfig) -> None:
    """Upload archive and sidecar files to DO Spaces via rclone.

    This is called only when upload_enabled is True.
    An additional runtime validation check is performed before upload.
    """
    remote_name = cfg.rclone_remote.split(":")[0] if ":" in cfg.rclone_remote else ""

    # Validate that rclone config is actually present before upload
    rclone_conf = Path("/root/.config/rclone/rclone.conf")
    if not rclone_conf.exists() or not validate_rclone_config(rclone_conf, remote_name, cfg.rclone_remote):
        err("Upload skipped: rclone config is missing or invalid.")
        err("Set GREENBONE_BACKUP_UPLOAD=0 or fix rclone configuration.")
        raise SystemExit(1)

    up_dir = Path(tempfile.mkdtemp(prefix="gb-upload-"))
    try:
        for suffix in (".tar.gz", ".metadata.json", ".sha256", ".restore.md"):
            base = archive.name.replace(".tar.gz", "")
            src = archive.parent / f"{base}{suffix}"
            if src.exists():
                (up_dir / src.name).write_bytes(src.read_bytes())

        target = f"{cfg.rclone_remote}/{cfg.rclone_path}/"
        env = {**__import__("os").environ, "RCLONE_CONFIG": str(rclone_conf)}
        log(f"Uploading to {cfg.rclone_remote}/{cfg.rclone_path}/ ...")
        r = run(["rclone", "copy", str(up_dir) + "/", target], env=env, check=False, timeout=600)
        if r.returncode == 0:
            log("Upload complete.")
        else:
            err(f"Upload FAILED: {r.stderr.strip()}")
            raise SystemExit(1)
    finally:
        shutil.rmtree(up_dir, ignore_errors=True)


def _hostname() -> str:
    import socket
    return socket.gethostname().split(".")[0]
