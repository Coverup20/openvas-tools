# Scripts index

## Existing scripts

| Script | Path | Description | Status |
|---|---|---|---|
| `deploy-greenbone.sh` | `install/deploy-greenbone.sh` | Safe Greenbone deployment framework | Development (v0.0.4 — audit, dry-run, deploy, update-feed, change-admin-password modes) |
| `test-deploy-greenbone.sh` | `tests/test-deploy-greenbone.sh` | Test suite for deploy-greenbone.sh | Development (update-feed + change-admin-password tests added) |

## Backup scripts (v0.0.5)

| Script | Path | Description | Status |
|---|---|---|---|
| `greenbone_backup.py` | `scripts/backup_restore/greenbone_backup.py` | Complete Greenbone backup with DB dump + volume + config | Development (v0.0.5) |
| `greenbone_manage_job00_daily.py` | `scripts/backup_restore/greenbone_manage_job00_daily.py` | Daily backup retention management | Development (v0.0.5) |
| `greenbone_manage_job01_weekly.py` | `scripts/backup_restore/greenbone_manage_job01_weekly.py` | Weekly backup retention management | Development (v0.0.5) |
| `greenbone_rclone_spaces.py` | `scripts/backup_restore/greenbone_rclone_spaces.py` | DigitalOcean Spaces rclone sync | Development (v0.0.5) |
| `greenbone_restore.py` | `scripts/backup_restore/greenbone_restore.py` | Greenbone restore from backup | Development (v0.0.5) |
| `greenbone_setup_do.py` | `scripts/backup_restore/greenbone_setup_do.py` | DigitalOcean Spaces setup | Development (v0.0.5) |
| `install-greenbone-backup.sh` | `scripts/backup_restore/install-greenbone-backup.sh` | Install Greenbone backup system | Development (v0.0.5) |
| `install-greenbone-backup.sh` | `install-greenbone-backup.sh` | Root-level install script wrapper | Development (v0.0.5) |

## Systemd units (v0.0.5)

| Unit | Path | Description | Status |
|---|---|---|---|
| `greenbone-backup-full.service` | `scripts/backup_restore/systemd/greenbone-backup-full.service` | Full backup service | Development (v0.0.5) |
| `greenbone-backup-full.timer` | `scripts/backup_restore/systemd/greenbone-backup-full.timer` | Full backup timer (weekly) | Development (v0.0.5) |
| `greenbone-backup-job00.service` | `scripts/backup_restore/systemd/greenbone-backup-job00.service` | Daily backup service | Development (v0.0.5) |
| `greenbone-backup-job00.timer` | `scripts/backup_restore/systemd/greenbone-backup-job00.timer` | Daily backup timer | Development (v0.0.5) |

## Documentation (v0.0.5)

| File | Path | Description | Status |
|---|---|---|---|
| `greenbone-backup.md` | `docs/greenbone-backup.md` | Greenbone backup system documentation | Development (v0.0.5) |

## Example files (v0.0.5)

| File | Path | Description | Status |
|---|---|---|---|
| `greenbone-backup.env.example` | `examples/greenbone-backup.env.example` | Example environment configuration | Development (v0.0.5) |

## Planned scripts (not yet created)

| Script | Path | Description |
|---|---|---|
| `setup-host.sh` | `install/setup-host.sh` | Ubuntu host preparation (Docker, dependencies) |
| `deploy-stack.sh` | `install/deploy-stack.sh` | Greenbone stack deployment and user creation |
| `backup-gvmd-db.sh` | `backup/backup-gvmd-db.sh` | PostgreSQL database dump for gvmd |
| `export-reports.py` | `reports/export/export-reports.py` | GMP-based report export automation |
| `transform-xml.py` | `reports/transform/transform-xml.py` | XML transformation to intermediate format |
| `generate-odt.py` | `reports/transform/generate-odt.py` | ODT report generation from transformed data |
| `health-check.sh` | `tests/health-check.sh` | Container health check and readiness probe |

## Legacy files (audited, not distributed)

| File | Source | Notes |
|---|---|---|
| `openvas.sh` | Desktop download | Audited — REQUIRES CORRECTION BEFORE TESTING. See audit report. |
