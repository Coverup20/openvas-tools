#!/usr/bin/env bash
#
# install-greenbone-backup.sh — Install Greenbone backup system on target VM
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Usage:
#   sudo bash install-greenbone-backup.sh [--enable-timer] [--install-do-backend]
#                                         [--install-timeshift]
#
# Options:
#   --enable-timer        Enable and start greenbone-backup-job00.timer
#   --enable-full-timer   Enable and start greenbone-backup-full.timer (bi-weekly)
#   --install-do-backend  Run greenbone_setup_do.py to configure DO Spaces/S3 (interactive)
#   --install-timeshift   Install and configure Timeshift RSYNC snapshots
#   --help                Show this help and exit
#
# Safety:
#   - Does NOT run backups
#   - Does NOT upload anything
#   - Does NOT create Timeshift snapshots (only installs/configures)
#   - GREENBONE_BACKUP_UPLOAD=0 by default
#   - Will not overwrite existing config without timestamped backup
#   - Requires root

set -Eeuo pipefail

VERSION="0.1.0"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# REPO_ROOT is the same as SCRIPT_DIR when script is at repo root
# Also check /root/openvas-tools (common when run via install-greenbone.sh from /tmp)
if [ -f "$SCRIPT_DIR/scripts/backup_restore/greenbone_backup.py" ]; then
  REPO_ROOT="$SCRIPT_DIR"
elif [ -d "/root/openvas-tools" ]; then
  REPO_ROOT="/root/openvas-tools"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd 2>/dev/null || echo "")"
fi

# GitHub raw URL for curl fallback when repo is not cloned locally
REPO_BASE_URL="https://raw.githubusercontent.com/Coverup20/openvas-tools/feat/greenbone-deploy-mode"

BACKUP_DIR="/opt/greenbone-backup"
SCRIPTS_DIR="$BACKUP_DIR/scripts"
ETC_DIR="/etc/greenbone-backup"
LIB_DIR="/opt/greenbone-backup/scripts"
SYSTEMD_DIR="/etc/systemd/system"

ENV_FILE="$ETC_DIR/greenbone-backup.env"
ENV_EXAMPLE="$REPO_ROOT/examples/greenbone-backup.env.example"

SERVICE_SRC="$REPO_ROOT/scripts/backup_restore/systemd/greenbone-backup-job00.service"
TIMER_SRC="$REPO_ROOT/scripts/backup_restore/systemd/greenbone-backup-job00.timer"

FULL_SERVICE_SRC="$REPO_ROOT/scripts/backup_restore/systemd/greenbone-backup-full.service"
FULL_TIMER_SRC="$REPO_ROOT/scripts/backup_restore/systemd/greenbone-backup-full.timer"

SCRIPTS_TO_INSTALL=(
  "greenbone_backup.py"
  "greenbone_manage_job00_daily.py"
  "greenbone_manage_job01_weekly.py"
  "greenbone_restore.py"
  "greenbone_rclone_spaces.py"
  "greenbone_setup_do.py"
)

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
ENABLE_TIMER=false
ENABLE_FULL_TIMER=false
INSTALL_DO_BACKEND=false
INSTALL_TIMESHIFT=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    error "This script must be run as root."
    exit 1
  fi
}

timestamped_backup() {
  local src="$1"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  cp -a "$src" "${src}.backup_${ts}"
  info "Backed up $src -> ${src}.backup_${ts}"
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
usage() {
  cat >&2 <<USAGEEOF
Usage: $(basename "$0") [options]

If no flags are given, runs in interactive mode and prompts for each step.

Options:
  --enable-timer        Enable and start greenbone-backup-job00.timer (daily config)
  --enable-full-timer   Enable and start greenbone-backup-full.timer (bi-weekly full DR)
  --install-do-backend  Configure DO Spaces/S3 rclone backend (interactive)
  --install-timeshift   Install Timeshift and configure RSYNC snapshots (interactive)
  --help, -h            Show this help and exit

Interactive mode (no flags):
  - Installs all scripts (config + full DR), env file, systemd units
  - Prompts: configure cloud backup?
  - Prompts: install Timeshift for local snapshots?
  - Prompts: enable daily config timer? enable bi-weekly full DR timer?
USAGEEOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-timer) ENABLE_TIMER=true; shift ;;
    --enable-full-timer) ENABLE_FULL_TIMER=true; shift ;;
    --install-do-backend) INSTALL_DO_BACKEND=true; shift ;;
    --install-timeshift) INSTALL_TIMESHIFT=true; shift ;;
    --help|-h) usage ;;
    *) error "Unknown option: $1"; usage ;;
  esac
done

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
require_root

info "=== install-greenbone-backup.sh v$VERSION ==="
info "Repository root: $REPO_ROOT"
info "Target backup dir: $BACKUP_DIR"
info "Target config dir: $ETC_DIR"

# 1. Create directories
mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/tmp"
mkdir -p "$BACKUP_DIR/logs"
mkdir -p "$ETC_DIR"
mkdir -p "$LIB_DIR"
info "Directories created."

# 2. Install Python scripts under /opt/greenbone-backup/scripts/
info "Installing scripts to $LIB_DIR ..."
for script in "${SCRIPTS_TO_INSTALL[@]}"; do
  src="$SCRIPT_DIR/$script"
  dst="$LIB_DIR/$script"

  # Try local first, then curl from GitHub
  if [ ! -f "$src" ]; then
    info "  Downloading $script from GitHub..."
    if curl -fsSL "$REPO_BASE_URL/scripts/backup_restore/$script" -o "$dst" 2>/dev/null; then
      chmod 755 "$dst"
      info "    Downloaded: $dst"
      continue
    else
      warn "  Failed to download $script — skipping"
      continue
    fi
  fi

  if [ -f "$dst" ]; then
    if diff -q "$src" "$dst" &>/dev/null; then
      info "Script $script unchanged — skipping"
      continue
    else
      timestamped_backup "$dst"
    fi
  fi
  cp "$src" "$dst"
  chmod 755 "$dst"
  info "  Installed: $dst"
done

# Also download env example if not found locally
if [ ! -f "$ENV_EXAMPLE" ]; then
  info "  Downloading env example from GitHub..."
  mkdir -p "$(dirname "$ENV_EXAMPLE")"
  curl -fsSL "$REPO_BASE_URL/examples/greenbone-backup.env.example" -o "$ENV_EXAMPLE" 2>/dev/null || true
fi

# 3. Install env file if missing or create from example
if [ -f "$ENV_FILE" ]; then
  info "Env file exists: $ENV_FILE (not overwritten)"
else
  if [ -f "$ENV_EXAMPLE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    chmod 644 "$ENV_FILE"
    info "Created: $ENV_FILE (from example, GREENBONE_BACKUP_UPLOAD=0 by default)"
  else
    warn "Env example not found: $ENV_EXAMPLE"
    # Create minimal env file
    cat > "$ENV_FILE" <<-EOF
GREENBONE_DIR=/opt/greenbone-community
COMPOSE_FILE=/opt/greenbone-community/compose.yaml
BACKUP_DIR=/var/backups/greenbone
TMP_DIR=/opt/greenbone-backup/tmp
LOG_FILE=/var/log/greenbone-backup-job00.log
RCLONE_REMOTE=do:testmonbck
RCLONE_PATH=greenbone-backups/job00-daily
GREENBONE_BACKUP_UPLOAD=0
RETENTION_LOCAL=90
RETENTION_CLOUD=90
EOF
    chmod 644 "$ENV_FILE"
    info "Created minimal env file: $ENV_FILE"
  fi
fi

# 4. Install systemd services and timers
ALL_UNITS=("$SERVICE_SRC" "$TIMER_SRC" "$FULL_SERVICE_SRC" "$FULL_TIMER_SRC")
for unit_src in "${ALL_UNITS[@]}"; do
  unit_name="$(basename "$unit_src")"
  unit_dst="$SYSTEMD_DIR/$unit_name"

  if [ ! -f "$unit_src" ]; then
    # Try download via curl (unit path inside repo)
    unit_rel="systemd/$unit_name"
    info "  Downloading $unit_name from GitHub..."
    if curl -fsSL "$REPO_BASE_URL/scripts/backup_restore/$unit_rel" -o "$unit_dst" 2>/dev/null; then
      chmod 644 "$unit_dst"
      info "    Downloaded: $unit_dst"
      continue
    else
      warn "  Failed to download $unit_name — skipping"
      continue
    fi
  fi

  if [ -f "$unit_dst" ]; then
    timestamped_backup "$unit_dst"
  fi
  cp "$unit_src" "$unit_dst"
  chmod 644 "$unit_dst"
  info "Installed: $unit_dst"
done

systemctl daemon-reload
info "Systemd daemon reloaded."

# 5. Enable timers if requested
if "$ENABLE_TIMER"; then
  systemctl enable --now greenbone-backup-job00.timer
  info "Daily config timer enabled: greenbone-backup-job00.timer"
fi
if "$ENABLE_FULL_TIMER"; then
  systemctl enable --now greenbone-backup-full.timer
  info "Full DR timer enabled: greenbone-backup-full.timer (bi-weekly)"
fi
if ! "$ENABLE_TIMER" && ! "$ENABLE_FULL_TIMER"; then
  info "No timer enabled (use --enable-timer and/or --enable-full-timer to activate)."
fi

# 6. Install Timeshift if requested
if "$INSTALL_TIMESHIFT"; then
  info "--- Timeshift RSYNC snapshot setup ---"
  if command -v timeshift &>/dev/null; then
    info "Timeshift already installed: $(timeshift --version 2>&1 | head -1)"
  else
    if apt-get install -y -qq timeshift 2>&1 | tail -1; then
      info "Timeshift installed."
    else
      warn "Timeshift installation failed. Try: apt-get install timeshift"
    fi
  fi
  if command -v timeshift &>/dev/null; then
    ROOT_DEV=""
    if [ -d /sys/block/vda ]; then ROOT_DEV="/dev/vda1"
    elif [ -d /sys/block/sda ]; then ROOT_DEV="/dev/sda1"
    elif [ -d /sys/block/nvme0n1 ]; then ROOT_DEV="/dev/nvme0n1p1"
    fi
    if [ -n "$ROOT_DEV" ]; then
      info "Configuring Timeshift RSYNC mode on $ROOT_DEV ..."
      timeshift --rsync 2>/dev/null || true
      timeshift --snapshot-device "$ROOT_DEV" 2>/dev/null || true
      info "Timeshift configured (RSYNC mode, no snapshots created)."
    else
      warn "Could not detect root device. Configure manually."
    fi
    SNAP_COUNT=$(timeshift --list 2>/dev/null | grep -c "^[0-9]" || true)
    if [ "$SNAP_COUNT" -eq 0 ] && [ -t 0 ]; then
      read -r -p "Create initial Timeshift snapshot now? [y/N]: " ANS_SNAP
      if [ "$ANS_SNAP" = "y" ] || [ "$ANS_SNAP" = "Y" ]; then
        info "Creating initial snapshot..."
        timeshift --create --comments "initial-$(date +%F)" 2>&1 | tail -3
      fi
    fi
  fi
  info "--- Timeshift setup complete ---"
fi

# 7. Install DO backend if requested
if "$INSTALL_DO_BACKEND"; then
  info "--- DO/S3 backend installation ---"

  if [ -f "$LIB_DIR/greenbone_setup_do.py" ]; then
    info "Running interactive DO Spaces setup..."
    python3 "$LIB_DIR/greenbone_setup_do.py"
    DO_EXIT=$?
    if [ $DO_EXIT -eq 0 ]; then
      info "DO Spaces setup completed successfully."
      echo ""

      # Verify remote
      python3 "$LIB_DIR/greenbone_rclone_spaces.py" --test-remote "do:testmonbck" || true
      echo ""

      # Ask to enable upload and run test
      read -r -p "Enable upload and run a test backup? [y/N]: " ANSWER
      if [ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ]; then
        info "Enabling upload in env file..."
        sed -i 's/^GREENBONE_BACKUP_UPLOAD=0/GREENBONE_BACKUP_UPLOAD=1/' "$ENV_FILE"
        info "Running test backup (dry-run first)..."
        export GREENBONE_BACKUP_UPLOAD=1
        python3 "$LIB_DIR/greenbone_backup.py" --upload --dry-run 2>&1 | tail -5
        echo ""
        read -r -p "Run real backup with upload now? [y/N]: " ANSWER2
        if [ "$ANSWER2" = "y" ] || [ "$ANSWER2" = "Y" ]; then
          info "Running real backup with upload..."
          python3 "$LIB_DIR/greenbone_manage_job00_daily.py" --upload 2>&1 | tail -10
          echo ""
          info "Verifying cloud upload..."
          rclone ls "do:testmonbck/greenbone-backups/job00-daily/" 2>&1 | tail -5
          echo ""

          # Ask to enable timers
          read -r -p "Enable daily config timer (job00)? [y/N]: " ANS_TIMER
          if [ "$ANS_TIMER" = "y" ] || [ "$ANS_TIMER" = "Y" ]; then
            systemctl enable --now greenbone-backup-job00.timer
            info "Daily config timer enabled."
          fi
          read -r -p "Enable bi-weekly full DR timer (full backup)? [y/N]: " ANS_FULL
          if [ "$ANS_FULL" = "y" ] || [ "$ANS_FULL" = "Y" ]; then
            systemctl enable --now greenbone-backup-full.timer
            info "Full DR timer enabled (bi-weekly)."
          fi
        else
          info "Real backup skipped. Run manually:"
          info "  export GREENBONE_BACKUP_UPLOAD=1"
          info "  python3 $LIB_DIR/greenbone_manage_job00_daily.py --upload"
        fi
      else
        info "Upload not enabled. Edit $ENV_FILE later to set GREENBONE_BACKUP_UPLOAD=1"
      fi
    else
      warn "DO Spaces setup exited with code $DO_EXIT."
      warn "You can re-run manually: python3 $LIB_DIR/greenbone_setup_do.py"
    fi
  else
    warn "Interactive DO setup script not found: $LIB_DIR/greenbone_setup_do.py"
    ls -1 "$LIB_DIR"/greenbone_rclone*.py "$LIB_DIR"/greenbone_setup*.py 2>/dev/null || true
  fi

  info "--- DO/S3 backend installation complete ---"
fi

# ---------------------------------------------------------------------------
# Interactive mode (only if no flags given and stdin is a terminal)
# ---------------------------------------------------------------------------
if ! "$ENABLE_TIMER" && ! "$ENABLE_FULL_TIMER" && ! "$INSTALL_DO_BACKEND" && ! "$INSTALL_TIMESHIFT" && [ -t 0 ]; then
  echo ""
  echo "=== Interactive Setup ==="
  echo ""

  # Cloud backup
  read -r -p "Configure DO Spaces cloud backup? [y/N]: " ANS_DO
  if [ "$ANS_DO" = "y" ] || [ "$ANS_DO" = "Y" ]; then
    INSTALL_DO_BACKEND=true
  fi

  # Timeshift
  read -r -p "Install Timeshift for local system snapshots? [y/N]: " ANS_TS
  if [ "$ANS_TS" = "y" ] || [ "$ANS_TS" = "Y" ]; then
    INSTALL_TIMESHIFT=true
  fi

  # Re-run with flags
  FLAGS=""
  $INSTALL_DO_BACKEND && FLAGS="$FLAGS --install-do-backend"
  $INSTALL_TIMESHIFT && FLAGS="$FLAGS --install-timeshift"
  if [ -n "$FLAGS" ]; then
    exec bash "$0" $FLAGS
  fi
fi

# ---------------------------------------------------------------------------
# Post-install: ask about DR restore (only in interactive mode, after all installs)
# ---------------------------------------------------------------------------
if [ -t 0 ] && [ -f "$LIB_DIR/greenbone_restore.py" ]; then
  echo ""
  echo "=== Disaster Recovery ==="
  echo "If you have an existing Greenbone backup, you can restore it now."
  echo ""
  python3 "$LIB_DIR/greenbone_restore.py" --list 2>&1 | head -20
  echo ""
  read -r -p "Run Disaster Recovery restore now? [y/N]: " ANS_DR
  if [ "$ANS_DR" = "y" ] || [ "$ANS_DR" = "Y" ]; then
    read -r -p "Enter archive path (or leave empty to select from list): " ARCHIVE_PATH
    if [ -n "$ARCHIVE_PATH" ]; then
      python3 "$LIB_DIR/greenbone_restore.py" --archive "$ARCHIVE_PATH" --confirm 2>&1
    else
      python3 "$LIB_DIR/greenbone_restore.py" --confirm 2>&1
    fi
  fi
fi

echo ""
info "=== Installation complete ==="
info "Scripts:        $LIB_DIR/"
info "Config:         $ENV_FILE"
info "Systemd units:  $SYSTEMD_DIR/greenbone-backup-job00.{service,timer}"
info "                 $SYSTEMD_DIR/greenbone-backup-full.{service,timer}"
echo ""
info "Next steps:"
info "  1) Verify env file: $ENV_FILE"
info "     - Set GREENBONE_BACKUP_UPLOAD=0 (default, safe)"
info "  2) Test config backup (daily):"
info "     sudo python3 $LIB_DIR/greenbone_manage_job00_daily.py --dry-run --no-upload"
info "  3) Test full DR backup (bi-weekly):"
info "     sudo python3 $LIB_DIR/greenbone_manage_job01_weekly.py --full --dry-run --no-upload"
info "  4) Enable upload when ready:"
info "     - Set GREENBONE_BACKUP_UPLOAD=1 in $ENV_FILE"
info "     - Run: sudo python3 $LIB_DIR/greenbone_manage_job00_daily.py --upload"
info "  5) Enable timers:"
info "     sudo systemctl enable --now greenbone-backup-job00.timer"
info "     sudo systemctl enable --now greenbone-backup-full.timer"
info "  6) Disaster Recovery:"
info "     sudo python3 $LIB_DIR/greenbone_restore.py --list"
info "     sudo python3 $LIB_DIR/greenbone_restore.py --archive /var/backups/greenbone/greenbone-full-...tar.gz --confirm"
