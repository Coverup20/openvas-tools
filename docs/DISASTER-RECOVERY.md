# Disaster recovery

Backup, restore and disaster recovery procedures for Greenbone Community Edition.

## Backup levels

### Level 1 — Report-only backup

```bash
# Export all reports via GMP
# Scripts in backup/ provide automation for this
```

**Restores:** Reports only.
**Cannot restore:** Platform configuration, targets, tasks, credentials, users.

### Level 2 — Configuration backup

```bash
tar czf backup/config-<DATE>.tar.gz \
  compose/docker-compose.yml \
  compose/.env \
  backup/secrets/
```

**Restores:** Stack configuration + custom scripts.
**Cannot restore:** Database, scan history.

### Level 3 — Database backup (recommended minimum)

```bash
# Database discovery required:
docker compose exec -T pg-gvm pg_dump -U gvm -d gvmd -F c \
  > backup/gvmd-db-<DATE>.dump
```

**Restores:** Full gvmd state — configs, targets, tasks, credentials, reports metadata.
**Cannot restore:** Feed data (must be re-synced), Docker volumes configuration.

### Level 4 — Volume backup

```bash
docker run --rm -v gvmd_data_vol:/source -v $(pwd)/backup:/dest \
  alpine tar czf /dest/gvmd-data-<DATE>.tar.gz -C /source .
```

Repeat for each named volume.
**Restores:** Complete platform including feeds.
**Requires:** Same or compatible Greenbone image versions.

### Level 5 — Full disaster recovery

```bash
# VM snapshot + all Level 3/4 backups + Level 2 configuration
```

**Restores:** Complete platform on new VM.

## Pre-update procedure

1. Level 3 database backup.
2. Level 2 configuration backup.
3. Record current image digests: `docker compose images --digests`
4. Note Greenbone version: `gvmd --version`
5. Proceed with update.

## Recovery procedure

```bash
# 1. Stop stack (do NOT remove volumes)
docker compose down

# 2. If DB backup exists:
docker compose up -d pg-gvm
sleep 15
docker compose exec -T pg-gvm pg_restore -U gvm -d gvmd -F c -c \
  < backup/gvmd-db-<DATE>.dump

# 3. Start stack
docker compose up -d

# 4. Verify
docker compose ps
docker compose exec -u gvmd gvmd gvmd --get-scanners
docker compose exec -u gvmd gvmd gvmd --get-feeds
```

## Cannot be restored from backup

- Active scan state (in-progress scans are lost)
- Redis cache data (regenerated on next scan)
- MOSQUITTO/Notus runtime state (regenerated on restart)
- Feed updates since last backup (re-synced automatically)
