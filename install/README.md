# install/

Deployment and preparation scripts for Greenbone Community Edition.

## Contents

| Path | Description |
|---|---|
| `setup-host.sh` | Ubuntu host preparation (Docker, dependencies, kernel params) |
| `deploy-stack.sh` | Greenbone stack deployment and initial configuration |
| `legacy/` | Original or reference scripts preserved for audit |

## Safety

- All scripts must be reviewed before execution.
- Hardcoded credentials are strictly prohibited — use interactive prompts or environment variables.
- Test only in isolated VMs first.
