# Safe Greenbone deployment design

## Scope

This document defines the architecture for a safe, auditable and reversible
Greenbone Community Containers deployment installer. The installer is designed
for:

- Ubuntu VM preparation (prerequisite verification only, no package installation)
- Docker Engine verification (presence and daemon state, no installation)
- Docker Compose plugin verification (availability check, no installation)
- Greenbone Community Containers deployment from official sources
- Official Compose file retrieval with integrity verification
- Source-integrity recording (checksums, image digests)
- Controlled startup with readiness polling
- Rollback metadata capture
- Data-Safe logging (no secrets in logs)

## Non-goals for this version

The following are explicitly out of scope for the current development version:

- Automatic production deployment
- Automatic destructive removal
- Automatic database restore
- Report XML export
- ODT generation
- Cloud backup
- Target creation
- Scan execution
- Credentials creation (passwords must be set interactively)

## Execution modes

The installer supports these modes, each with a defined safety contract:

| Mode | Idempotent | Read-only | Implements |
|---|---|---|---|
| `audit` | Yes | Yes | **Phase 1** — system readiness check |
| `dry-run` | Yes | Yes | **Phase 1** — planned execution preview |
| `status` | Yes | Yes | **Phase 1** — current stack state |
| `deploy` | TBD | No | **Future** — full deployment |
| `backup` | TBD | No | **Future** — database and config backup |
| `remove` | N/A | No | **Future** — safe teardown with backup gate |

### Phase 1 implementation

- `audit` — fully functional, read-only
- `dry-run` — fully functional, no side effects
- `status` — partially functional, read-only
- `deploy` — refuses execution with "not implemented" message
- `backup` — refuses execution with "not implemented" message
- `remove` — refuses execution with "not implemented" message

## Safety model

### Root requirements

- Root or sudo access is verified only when needed (deploy mode in future)
- Audit and dry-run modes work without root
- No destructive command runs without explicit confirmation

### Prohibited patterns

The installer must never contain:

- `docker stop $(docker ps ...)` — global container operations
- `docker volume rm` without project-scoped safety
- `docker system prune` or `docker volume prune`
- `docker compose down -v` — volume destruction without backup gate
- `chown -R` on Docker or system directories
- `chmod -R 777`
- `curl ... | bash` or `wget ... | sh` — pipe-to-shell
- Hardcoded credentials of any kind
- Hardcoded IP addresses, hostnames or ports

### Mandatory safety features

- Timestamped logging to a configurable log directory
- Audit trail of all operations
- Pre-change backup for future deploy mode
- Explicit confirmation gates for future destructive operations
- Data-Safe output (no secrets in console or log output)
- Error trap with cleanup
- Cleanup trap for temporary files

## Configuration model

All configuration is provided through environment variables or CLI options.
No guessed production values are hardcoded.

| Variable / Option | Purpose | Default |
|---|---|---|
| `GREENBONE_PROJECT_DIR` | Base directory for Compose files and runtime data | (required) |
| `GREENBONE_COMPOSE_URL` | URL of the official Compose file | (required) |
| `GREENBONE_COMPOSE_FILE` | Local path to the Compose file | `$GREENBONE_PROJECT_DIR/compose.yaml` |
| `GREENBONE_RELEASE_REF` | Release reference for rollback metadata | (optional) |
| `LOG_DIR` | Directory for log files | `./logs` |
| `DRY_RUN` | Enable dry-run mode | `false` |
| `NON_INTERACTIVE` | Skip confirmation prompts | `false` |
| `--project-dir` | CLI override for project directory | — |
| `--compose-url` | CLI override for Compose URL | — |
| `--compose-file` | CLI override for Compose file path | — |
| `--log-dir` | CLI override for log directory | — |
| `--non-interactive` | CLI flag for non-interactive mode | — |
| `--verbose` | CLI flag for verbose output | — |

## Official source policy

### Compose file retrieval

- The active Greenbone Community Containers release must be verified from
  official sources (`greenbone.github.io/docs/latest/`)
- The downloaded Compose file must be checksummed immediately after download
- The checksum must be recorded before any deployment step

### Service name discovery

- Service names must never be hardcoded
- Active service names must be discovered using:
  `docker compose config --services`
- Image references and digests must be recorded before deployment:
  `docker compose images --digests`

### No pipe-to-shell

- No downloaded content may be piped directly to a shell (`curl ... | bash`)
- All downloaded files must be saved to disk, verified, and only then executed
  through explicit invocation

## Rollback metadata

Before any deployment step that modifies state, the installer must record:

- Current Compose file checksum
- Image names and digests (if already pulled)
- Greenbone version from `gvmd --version` (if already running)
- Timestamp and deployment mode identifier

## Logging

- All output must be written to a timestamped log file
- Logs must never contain passwords, tokens or secrets
- Console output may be reduced in non-verbose mode
- Log retention is the responsibility of the operator

## Future mode contracts

These contracts define the behavior of modes not yet implemented:

### deploy (future)

- Full stack deployment from official sources
- User confirmation before any system modification
- Rollback metadata capture before deployment
- Readiness polling after startup
- Post-deployment validation (scanner registration, feed age)

### remove (future)

- Full backup gate: requires a recent backup before teardown
- Project-scoped container and volume operations only
- No global Docker commands
- Confirmation at multiple levels (mode + final prompt)

### backup (future)

- PostgreSQL database dump (discover DB user and name at runtime)
- Compose file and configuration backup
- Image digest and version metadata capture
- Checksums for all backup artifacts
