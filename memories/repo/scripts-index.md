# Scripts index

## Existing scripts

| Script | Path | Description | Status |
|---|---|---|---|
| `deploy-greenbone.sh` | `install/deploy-greenbone.sh` | Safe Greenbone deployment framework | Development (v0.0.2 — audit, dry-run, deploy modes) |
| `test-deploy-greenbone.sh` | `tests/test-deploy-greenbone.sh` | Test suite for deploy-greenbone.sh | Development (49 tests) |

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
