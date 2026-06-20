# Legacy script audit

## Source

| Field | Value |
|---|---|
| **Filename** | `openvas.sh` |
| **Source path** | Desktop download (outside repository) |
| **SHA-256** | `0b90ff58f9ff44d64ec90331f56d007610ba45c06dd4be4cb4461be07945d161` |
| **Audit date** | 2026-06-19 |
| **Result** | **REQUIRES CORRECTION BEFORE TESTING** |

## Summary

This script is a custom wrapper around the official Greenbone Community Containers
deployment workflow. It was downloaded from an external source and has been audited
for safety, correctness and suitability before any execution. The script contains
multiple critical and high-severity issues that make it unsafe to execute in its
current form.

## Critical findings

### 1. Hardcoded credentials

The script contains three hardcoded passwords embedded in the code:

- **Line 93**: `--new-password=[REDACTED]` (admin user)
- **Line 96**: `--password=[REDACTED]` (report user)
- **Line 99**: `--password=[REDACTED]` (redteam user)

Hardcoded credentials are a security vulnerability. Anyone with read access to the
script can compromise the Greenbone installation. Passwords must be provided
interactively, through environment variables, or via a secure secrets file.

### 2. Stops and removes ALL Docker containers

```bash
docker stop $(docker ps -a -q) && docker rm $(docker ps -a -q)
```

This command operates on **all** Docker containers on the system, not only those
belonging to the Greenbone project. On a shared or production Docker host, this
would destroy unrelated workloads. The correct approach is project-scoped
`docker compose down`.

### 3. Destructive volume deletion

```bash
docker volume rm $(docker volume ls -q| grep greenbone)
```

Volumes containing scan results, configuration and database data are deleted
without any backup or confirmation gate. The script has no backup mode and no
recovery path.

### 4. Unsafe ownership modification of the Docker data directory

```bash
chown :openvas /var/lib/docker/
```

Changing the group ownership of the entire Docker data directory can break Docker
permissions for all containers and images on the system. This may render Docker
non-functional or cause permission-denied errors for other containers.

### 5. Assumption of a nonexistent local report user

```bash
su - report -c "..."
```

The script assumes a local Unix user `report` exists on the system, creates a
matching Greenbone user, and attempts to execute GMP commands as that local user.
No `report` user is created by the script or by a standard Greenbone installation.
This command will fail with `su: user report does not exist`.

### 6. No backup or recovery path

The `remove` mode destroys all Greenbone data (containers, images, volumes,
network) without offering any backup option. There is no `backup` mode, no database
dump, and no volume export. Recovery from this operation requires a complete
reinstallation and loss of all scan history and configuration.

## High findings

### 7. Inconsistent `docker-compose` and `docker compose`

The script uses `docker-compose` (legacy standalone binary) in one location
(line 46) and `docker compose` (Compose plugin) everywhere else. On systems that
only have the plugin, the legacy command will fail with `command not found`.

### 8. Floating image tags / unverified release URL

The script accepts a user-supplied release URL with no verification. Downloaded
Compose files are not checksummed. There is no mechanism to verify the integrity
or authenticity of the downloaded content before execution.

### 9. No Compose-file integrity verification

After downloading the Compose file, the script does not calculate or verify any
checksum. A compromised or truncated download would be used without warning.

### 10. Incomplete shell safety

The script uses `set -e` but does not include `set -u` (fail on undefined
variables), `set -E` (inherit error traps in functions), or `set -o pipefail`.
An undefined variable or silent pipe failure could cause unexpected behavior.

### 11. No rollback or cleanup trap

There is no `trap` for cleanup on error or interruption. If the script fails partway
through deployment, containers, partial downloads or incomplete state may be left
behind with no automatic recovery.

## Legacy script must not be executed

**The legacy script must not be executed.** It contains hardcoded credentials,
destructive global Docker commands, unsafe system modifications, and no safety
guards. A complete replacement following the safe deployment design is required
before any Greenbone deployment.

## References

- `docs/SAFE-DEPLOYMENT-DESIGN.md` — replacement architecture
- `install/deploy-greenbone.sh` — safe installer framework
- `scripts-index.md` — legacy script registry entry
