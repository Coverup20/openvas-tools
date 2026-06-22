# install/

Deployment and preparation scripts for Greenbone Community Edition.

## Contents

| Path | Description | Status |
|---|---|---|
| `deploy-greenbone.sh` | Safe Greenbone deployment framework | Development (v0.0.2 — audit, dry-run, deploy modes functional) |
| `setup-host.sh` | Ubuntu host preparation (Docker, dependencies, kernel params) | Planned |
| `deploy-stack.sh` | Greenbone stack deployment and initial configuration | Planned |

## Current development — `deploy-greenbone.sh`

Development is on branch `feat/greenbone-deploy-mode`. See `docs/SAFE-DEPLOYMENT-DESIGN.md`.

### Modes

| Mode | Description | Exit |
|---|---|---|
| `audit` | Read-only system readiness check | 0 |
| `dry-run` | Planned deployment sequence without execution | 0 |
| `status` | Read-only current stack state | 0 |
| `deploy` | Full deploy (requires `--deploy-confirmed` + typed confirmation) | 0 |
| `backup` | NOT IMPLEMENTED | 3 |
| `remove` | NOT IMPLEMENTED | 3 |

### Confirmation gates

Deploy mode requires BOTH:
- `--deploy-confirmed` flag (or `--non-interactive` which implies it)
- Typed `DEPLOY` confirmation (skipped if `--non-interactive`)

### Disk thresholds

| Free space | Behavior |
|---|---|
| < 20GB | ❌ Fail before deployment |
| 20–40GB | ⚠️ Warn + require confirmation |
| ≥ 40GB | ✅ Pass |

### Usage

```bash
# Run from repository root
bash install/deploy-greenbone.sh audit
bash install/deploy-greenbone.sh dry-run
bash install/deploy-greenbone.sh deploy --deploy-confirmed --project-dir /opt/greenbone-community
```

### Prerequisites

- Bash 4+, `curl`, `sha256sum`
- Docker and Docker Compose plugin
- Root or sudo access (for deploy mode)
- Minimum 20GB free disk (40GB recommended)

### No-production warning

This script is under development. Do not use for production deployments.
Always test in an isolated VM first.

## Safety

- All scripts must be reviewed before execution.
- Hardcoded credentials are strictly prohibited — use interactive prompts or environment variables.
- Test only in isolated VMs first.
