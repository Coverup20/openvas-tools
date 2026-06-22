# install/

Deployment and preparation scripts for Greenbone Community Edition.

## Contents

| Path | Description | Status |
|---|---|---|
| `deploy-greenbone.sh` | Safe Greenbone deployment framework | **Development** — audit and dry-run modes functional |
| `setup-host.sh` | Ubuntu host preparation (Docker, dependencies, kernel params) | Planned |
| `deploy-stack.sh` | Greenbone stack deployment and initial configuration | Planned |

## Current development — `deploy-greenbone.sh`

The safe deployment framework is under active development on branch
`feat/safe-greenbone-deployment`. See `docs/SAFE-DEPLOYMENT-DESIGN.md` for the
full architecture.

### Safe modes (functional)

| Mode | Description |
|---|---|
| `audit` | Read-only system readiness check |
| `dry-run` | Planned deployment sequence without execution |
| `status` | Read-only current stack state |

### Unimplemented modes (refuse execution)

| Mode | Expected exit code |
|---|---|
| `deploy` | 3 |
| `backup` | 3 |
| `remove` | 3 |

### Usage

```bash
# Run from repository root
bash install/deploy-greenbone.sh audit
bash install/deploy-greenbone.sh dry-run
bash install/deploy-greenbone.sh --help
```

### Prerequisites

- Bash 4+
- `curl`, `sha256sum`
- Docker and Docker Compose plugin (for full functionality; audit mode works
  without them)

### No-production warning

This script is under development. Do not use for production deployments.
Always test in an isolated VM first.

## Safety

- All scripts must be reviewed before execution.
- Hardcoded credentials are strictly prohibited — use interactive prompts or environment variables.
- Test only in isolated VMs first.
