# Greenbone/OpenVAS Backup (Docker Compose)

This backup system is adapted from the verified Checkmk backup architecture.
Reference files in the Checkmk project:
- `backup_restore/checkmk_backup.py`
- `backup_restore/checkmk_manage_job00_daily.py`
- `backup_restore/checkmk_rclone_space_dyn.py`
- `backup_restore/checkmk_backup_cleanup.py`

Greenbone-specific values differ (paths, service names, cloud prefix), but the
logic for metadata, retention, rclone upload, and systemd scheduling follows the
same model.

Goals:
- Safe, read-only-friendly snapshot (no container stop)
- Single archive with metadata JSON, SHA256, and restore notes
- Rclone upload support (disabled by default; gated)
- Local and cloud retention
- Systemd service/timer templates for daily job00

## Components

- scripts/backup_restore/greenbone_backup.py
  - Core configuration/inventory backup. Collects compose/services/images/volumes inventory, creates archive, writes metadata.json, .sha256, .restore.md
  - Does not stop containers; does NOT back up volume data.
  - Consistency marked as `config_inventory_only` in metadata.
  - Upload is disabled unless `--upload` AND `GREENBONE_BACKUP_UPLOAD=1`.

- scripts/backup_restore/greenbone_manage_job00_daily.py
  - Daily manager: invokes `greenbone_backup.py`, enforces local retention, optionally cloud retention via rclone.

- scripts/backup_restore/greenbone_rclone_spaces.py
  - Safe read-only helper: validates rclone, lists remotes, tests a remote with `rclone lsd`. Does not print secrets or write credentials.

- scripts/backup_restore/greenbone_setup_do.py
  - Interactive DO/AWS rclone remote setup (adapted from Checkmk `checkmk_rclone_space_dyn.py`).
  - Prompts for credentials (hidden input), creates/updates remote, tests access.
  - Supports `--remote NAME:BUCKET` and `--rclone-config PATH`.
  - No secrets printed. No backup/upload performed.

- scripts/greenbone_install_backup.py
  - Python-native installer: creates directories, copies scripts, writes env and systemd units.
  - Timers disabled by default. Upload disabled by default.

## Defaults

- GREENBONE_DIR=/opt/greenbone-community
- COMPOSE_FILE=/opt/greenbone-community/compose.yaml
- BACKUP_BASE_DIR=/opt/greenbone-backup (core script)
- BACKUP_DIR=/var/backups/greenbone (daily manager)
- TMP_DIR=/opt/greenbone-backup/tmp
- LOG_FILE=/var/log/greenbone-backup-job00.log
- RCLONE_REMOTE=do:testmonbck
- RCLONE_PATH=*(not set - each manager uses own default: job00→job00-daily, job01→job01-bi-weekly)*
- RETENTION_DAYS=30
- GREENBONE_BACKUP_UPLOAD=0

## Dry-run and No-Upload

- `--dry-run` prints planned actions and writes nothing to cloud.
- `--no-upload` disables any upload preparation.
- `--upload` enables upload only when `GREENBONE_BACKUP_UPLOAD=1` is set in the environment.

## Rclone Configuration

- Configure rclone for the backup user (usually root or a dedicated user with Docker access).
- Use `greenbone_rclone_spaces.py --list-remotes` and `--test-remote <name:bucket>` to validate.
- Do not store credentials in this repository; use `~/.config/rclone/rclone.conf`.

## Retention

- Local retention: keep newest N local archives (plus their sidecar files).
- Cloud retention: keep newest N remote objects under the configured prefix; only objects matching Greenbone backup names are considered.

## Restore Concept

- This is a **configuration/inventory backup only** (`consistency: config_inventory_only`).
- Docker volume data (PostgreSQL database, GVM feed data, Redis state) is NOT included.
- For a full recovery you must also:
  - Re-sync GVM feeds (may take hours)
  - Rebuild or restore the PostgreSQL database
  - Recreate Redis state
- Restore steps (high-level): extract archive, review compose/env, start stack with
  `docker compose up -d`, validate with `docker compose ps`, then re-sync feeds
  and restore databases as needed.

## Deployment on openvas-greenbone

Use the Python installer:

```bash
sudo python3 scripts/greenbone_install_backup.py --install
```

This creates directories, installs Python scripts under `/opt/greenbone-backup/scripts/`,
installs systemd units, and creates the env file. Upload is disabled
by default (`GREENBONE_BACKUP_UPLOAD=0`). Timers are disabled by default.

### Configure rclone credentials (primary path — interactive DO/AWS setup)

Run the interactive setup script (adapted from Checkmk `checkmk_rclone_space_dyn.py`):

```bash
sudo python3 /opt/greenbone-backup/scripts/greenbone_setup_do.py --remote do:testmonbck
```

This will:
- Check if rclone is installed (prompt to install if missing)
- Check for existing `do:` remote
- Prompt for credentials (hidden input, never echoed)
- Supports DigitalOcean Spaces (default) or AWS S3
- Create/update the remote
- Test the remote with `rclone lsd`

After completion, verify:

```bash
python3 /opt/greenbone-backup/scripts/greenbone_rclone_spaces.py --test-remote do:testmonbck
```

**Fallback** (manual rclone config, only if interactive setup is not suitable):

```bash
# Only if greenbone_setup_do.py cannot be used:
mkdir -p ~/.config/rclone
# Then copy or manually create rclone.conf with a 'do:' remote
```

### Enable timer (optional)

```bash
sudo systemctl enable --now greenbone-backup-job00.timer
```

Or re-run the Python installer:

```bash
sudo python3 scripts/greenbone_install_backup.py --install --enable-timers
```

### Test local backup (no upload)

```bash
sudo python3 /opt/greenbone-backup/scripts/greenbone_manage_job00_daily.py --dry-run --no-upload
```

### Enable upload (after approval)

1. Edit `/etc/greenbone-backup/greenbone-backup.env`:
   - Set `GREENBONE_BACKUP_UPLOAD=1`
   - Verify `RCLONE_REMOTE` and `RCLONE_PATH` are correct
2. Test with dry-run:
   ```bash
   sudo python3 /opt/greenbone-backup/scripts/greenbone_manage_job00_daily.py --upload --dry-run
   ```
3. When ready for real upload, run without `--dry-run`:
   ```bash
   sudo python3 /opt/greenbone-backup/scripts/greenbone_manage_job00_daily.py --upload
   ```

## Validate Without Upload

From the repo root (local testing):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/backup_restore/greenbone_backup.py --dry-run
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/backup_restore/greenbone_manage_job00_daily.py --dry-run --no-upload
```

From the deployed VM (after install):

```bash
sudo python3 /opt/greenbone-backup/scripts/greenbone_backup.py --dry-run
sudo python3 /opt/greenbone-backup/scripts/greenbone_manage_job00_daily.py --dry-run --no-upload
```

## Enable Upload (after approval)

```bash
# Edit /etc/greenbone-backup/greenbone-backup.env
# Set GREENBONE_BACKUP_UPLOAD=1 and ensure RCLONE_REMOTE/RCLONE_PATH are correct.
# Then restart the service (timer will trigger routinely):
sudo systemctl restart greenbone-backup-job00.service
```

## Restore Note Location

Each backup produces a `.restore.md` file alongside the archive in the backup
directory (`/var/backups/greenbone/`). This file contains the SHA256 checksum
and step-by-step restore instructions.

## Do Not

- Do not run `docker compose down -v`.
- Do not prune Docker system/volumes for backups.
- Do not use native Ubuntu Greenbone services in this deployment model.
- Do not print or commit secrets.
