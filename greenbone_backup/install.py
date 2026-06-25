"""install.py - Greenbone backup system installer.

Python-native installer for the Greenbone backup system.
Creates directories, writes scripts, env file, and systemd units.
Never enables timers by default.  Never sets UPLOAD=1 unless validated.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from .command import run, require_root
from .config import BackupConfig, default_rclone_config
from .logging_utils import log, err, warn
from .rclone import validate_rclone_config, remote_exists
from .systemd import all_units, install_units, enable_timer


SCRIPTS_DST = Path("/opt/greenbone-backup/scripts")
ETC_DIR = Path("/etc/greenbone-backup")
ENV_FILE = ETC_DIR / "greenbone-backup.env"


def install(
    dry_run: bool = False,
    configure_rclone: bool = False,
    enable_timers: bool = False,
    repo_root: Optional[Path] = None,
    script_source_dir: Optional[Path] = None,
) -> int:
    """Install the Greenbone backup system on the target host.

    Returns 0 on success, 1 on failure.
    """
    require_root()

    log("=== greenbone_install_backup.py ===")

    if repo_root is None:
        repo_root = Path("/root/openvas-tools") if Path("/root/openvas-tools").exists() else Path.cwd()

    # Determine script source
    # Try new-style scripts/ first, fall back to scripts/backup_restore/
    new_style = repo_root / "scripts"
    if new_style.exists() and (new_style / "greenbone_install_backup.py").exists():
        local_scripts = new_style
    else:
        local_scripts = repo_root / "scripts" / "backup_restore"
    if script_source_dir:
        local_scripts = Path(script_source_dir)

    # 1. Create directories
    dirs = [
        Path("/opt/greenbone-backup"),
        Path("/opt/greenbone-backup/tmp"),
        Path("/opt/greenbone-backup/logs"),
        SCRIPTS_DST,
        ETC_DIR,
        Path("/var/backups/greenbone"),
    ]
    for d in dirs:
        if dry_run:
            print(f"[DRY-RUN] mkdir -p {d}")
        else:
            d.mkdir(parents=True, exist_ok=True)
            log(f"Directory: {d}")

    # 2. Install Python scripts and package
    scripts_to_install = [
        "greenbone_do_backup.py",
        "greenbone_manage_job00_daily.py",
        "greenbone_manage_job01_weekly.py",
        "greenbone_restore.py",
        "greenbone_rclone_spaces.py",
        "greenbone_setup_do.py",
        "greenbone_install_backup.py",
    ]

    if not local_scripts.exists():
        warn(f"Script source directory not found: {local_scripts}")
        warn("Scripts will need to be copied manually.")
    else:
        for script_name in scripts_to_install:
            src = local_scripts / script_name
            dst = SCRIPTS_DST / script_name
            if dry_run:
                print(f"[DRY-RUN] Install: {src} -> {dst}")
                continue
            if src.exists():
                shutil.copy2(str(src), str(dst))
                dst.chmod(0o755)
                log(f"Installed: {dst}")
            else:
                warn(f"Script not found: {src}")

    # Install the greenbone_backup package alongside scripts
    pkg_src = repo_root / "greenbone_backup"
    pkg_dst = SCRIPTS_DST / "greenbone_backup"
    if pkg_src.exists() and pkg_src.is_dir():
        if dry_run:
            print(f"[DRY-RUN] Install package: {pkg_src} -> {pkg_dst}")
        else:
            if pkg_dst.exists():
                shutil.rmtree(pkg_dst)
            shutil.copytree(pkg_src, pkg_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            log(f"Installed package: {pkg_dst}")

    # 3. Create env file
    cfg = BackupConfig.from_env()
    # Force safe default: upload is always 0 on install
    cfg.upload_enabled = False

    if dry_run:
        print(f"[DRY-RUN] Would write: {ENV_FILE}")
        print(cfg.to_env_lines())
    else:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text(cfg.to_env_lines(), encoding="utf-8")
        ENV_FILE.chmod(0o644)
        log(f"Env file: {ENV_FILE}")

    # 4. Create systemd units
    install_units(dry_run=dry_run)

    # 5. Enable timers only if explicitly requested
    if enable_timers:
        enable_timer("greenbone-backup-job00.timer", dry_run=dry_run)
        enable_timer("greenbone-backup-full.timer", dry_run=dry_run)

    # 6. Configure rclone if requested
    if configure_rclone:
        _configure_rclone_interactive(dry_run=dry_run)

    log("Installation complete.")
    log(f"  Scripts:        {SCRIPTS_DST}/")
    log(f"  Config:         {ENV_FILE}")
    log(f"  Backups:        /var/backups/greenbone/")
    log(f"  Systemd units:  /etc/systemd/system/greenbone-backup-*.{{service,timer}}")
    log("")
    log("Timers are DISABLED by default.")
    log("Enable when ready: systemctl enable --now greenbone-backup-job00.timer")
    log("Upload is DISABLED by default.")
    log("Enable: set GREENBONE_BACKUP_UPLOAD=1 in the env file (after rclone is configured).")

    return 0


def upgrade_env_file(dry_run: bool = False) -> bool:
    """Upgrade an existing env file to ensure UPLOAD=0 if rclone is invalid.

    This fixes the bug where UPLOAD=1 was written when rclone config
    was missing or invalid.
    """
    if not ENV_FILE.exists():
        log(f"No env file found at {ENV_FILE} — nothing to upgrade.")
        return True

    content = ENV_FILE.read_text(encoding="utf-8")
    original = content

    # Check if rclone config is valid
    rclone_cfg = default_rclone_config()
    remote_name = "do"  # default remote name
    rclone_ok = rclone_cfg.exists() and remote_exists(rclone_cfg, remote_name)

    # If rclone is not valid, force UPLOAD=0
    if not rclone_ok and "GREENBONE_BACKUP_UPLOAD=1" in content:
        content = content.replace("GREENBONE_BACKUP_UPLOAD=1", "GREENBONE_BACKUP_UPLOAD=0")
        log("Fixed: GREENBONE_BACKUP_UPLOAD set to 0 (rclone config invalid)")

    if content == original:
        log("Env file already correct.")
        return True

    if dry_run:
        print("[DRY-RUN] Would update env file:")
        print(content)
        return True

    ENV_FILE.write_text(content, encoding="utf-8")
    log(f"Env file updated: {ENV_FILE}")
    return True


def _configure_rclone_interactive(dry_run: bool = False) -> None:
    """Interactively configure rclone for DO Spaces.

    Never sets UPLOAD=1 unless configuration succeeds.
    """
    from .rclone import prompt_and_create_remote, create_do_remote, test_remote, config_path_resolved

    rclone_cfg = default_rclone_config()
    remote_full = "do:testmonbck"
    remote_name = "do"

    log("Configuring rclone for DO Spaces...")
    success = prompt_and_create_remote(rclone_cfg, remote_full)

    if not success:
        warn("rclone configuration failed or was cancelled.")
        warn("Upload will remain disabled.")
        return

    # Only now ask about enabling upload
    log("rclone configuration successful.")
    answer = input("Enable upload (GREENBONE_BACKUP_UPLOAD=1)? [y/N]: ").strip().lower()
    if answer == "y" and not dry_run:
        _set_upload_enabled(True)
        log("Upload enabled.")
    elif answer == "y" and dry_run:
        print("[DRY-RUN] Would set GREENBONE_BACKUP_UPLOAD=1")
    else:
        log("Upload not enabled. Edit the env file later to enable.")


def _set_upload_enabled(enabled: bool) -> None:
    """Set GREENBONE_BACKUP_UPLOAD in the env file."""
    if not ENV_FILE.exists():
        warn(f"Env file not found: {ENV_FILE}")
        return
    content = ENV_FILE.read_text(encoding="utf-8")
    val = "1" if enabled else "0"
    if "GREENBONE_BACKUP_UPLOAD=" in content:
        lines = []
        for line in content.splitlines():
            if line.startswith("GREENBONE_BACKUP_UPLOAD="):
                lines.append(f"GREENBONE_BACKUP_UPLOAD={val}")
            else:
                lines.append(line)
        content = "\n".join(lines) + "\n"
    else:
        content += f"\nGREENBONE_BACKUP_UPLOAD={val}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    log(f"GREENBONE_BACKUP_UPLOAD set to {val} in {ENV_FILE}")
