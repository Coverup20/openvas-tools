# backup/

Backup and disaster recovery scripts for Greenbone Community Edition.

## Backup levels

| Level | Contents | Restore capability |
|---|---|---|
| 1 — Report only | Raw XML exports, generated reports | Reports only. Full platform loss. |
| 2 — Configuration | Compose files, `.env`, secrets, custom scripts | Rebuild stack. Reports and targets may survive if DB is intact. |
| 3 — Database | PostgreSQL dump via `pg_dump` | Full gvmd state: configs, targets, tasks, credentials, reports. Feeds must be re-synced. |
| 4 — Volume | Docker volume backups | Full platform recovery. Requires compatible image versions. |
| 5 — DR | VM snapshot + all of the above | Complete disaster recovery. |

## Policy

- Always run a Level 3 backup before any stack update.
- Do not rely on XML-only backups for platform recovery.
- All backup scripts must accept a destination path parameter.
- Full backup procedure: see `docs/DISASTER-RECOVERY.md`.
