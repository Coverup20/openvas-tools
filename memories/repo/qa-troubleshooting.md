# Q&A Troubleshooting

## 2026-06-22 — gvmd --get-scanners fails with System V semaphore permission denied

### Question

Why does `gvmd --get-scanners` (or --get-users, --get-tasks, etc.) fail with `init_semaphore_set: Permission denied` when called via `docker compose exec`?

### Context

- Repository/component: openvas-tools, Greenbone Community Containers
- Symptom: Running `docker compose exec gvmd gvmd --get-scanners` returns WARNING messages about semaphore set and sql_open failure instead of scanner output
- Wrong command: `docker compose exec gvmd gvmd --get-scanners` (or with `-T`)
- Wrong command: `docker compose exec -T gvmd gvmd --get-scanners` (also fails)
- Root cause: The gvmd daemon process creates System V semaphores (`semget`/`semop`) as the container user `gvmd` (UID 1001). When you exec a new process as `root` (the `docker compose exec` default), the new process cannot access the semaphore set created by the `gvmd` user. This causes `sql_open` to fail because gvmd uses semaphores to coordinate database connections.

### Solution

Use the `-u gvmd` flag to run the gvmd CLI command under the same user as the daemon:

```bash
docker compose exec -u gvmd gvmd gvmd --get-scanners
docker compose exec -u gvmd gvmd gvmd --get-users
docker compose exec -u gvmd gvmd gvmd --get-tasks
```

The `-u gvmd` flag matches the container user defined in the Dockerfile/Compose service, giving the exec'd process access to the daemon's semaphore set.

### Diagnosis commands

```bash
# Fails (any of these):
docker compose exec gvmd gvmd --get-scanners 2>&1 | grep -i semaphore
docker compose exec -T gvmd gvmd --get-scanners 2>&1 | grep -i semaphore

# Works:
docker compose exec -u gvmd gvmd gvmd --get-scanners 2>&1
```

### Key lesson

Always check the container user before running CLI commands against a running daemon that uses System V IPC. For gvmd administrative commands via `docker compose exec`, always add `-u gvmd`. The same pattern applies to any containerized service that uses semaphores or POSIX shared memory — identify the daemon's runtime user first.

### Prevention rule

Add `-u gvmd` to ALL gvmd administrative commands executed via `docker compose exec`. Never assume the default exec user (root) can access the daemon's IPC resources.

---

## 2026-06-22 — deploy-greenbone.sh: dual DEPLOY confirmation with low disk space

### Question

Why does `deploy-greenbone.sh` fail with "Disk space confirmation failed" even after typing `DEPLOY`?

### Context

- Repository/component: openvas-tools, install/deploy-greenbone.sh
- Symptom: First `DEPLOY` prompt accepted, second "continue despite low disk space" prompt not answered → abort with exit code 2
- Root cause: Script requires TWO separate typed `DEPLOY` confirmations when disk space is below 40GB

### Solution

Either:
1. Use pipe input: `printf "DEPLOY\nDEPLOY\n" | bash deploy-greenbone.sh deploy --deploy-confirmed --project-dir /opt/greenbone-community`
2. Or respond to both interactive prompts with `DEPLOY`

### Key lesson

Always check for secondary confirmation prompts in the script logic. The low-disk-space confirmation is a separate gate. When automating, use `printf` to pre-feed both inputs. Avoid SSH `-tt` for automated deploys — pipe input is more reliable (SIGHUP on terminal kill terminates the remote process).

## 2026-06-22 — GSA web endpoint unreachable on first boot

### Question

Why does curl return exit code 35 or 000 when testing `https://127.0.0.1:9392` after deploy?

### Context

- Repository/component: openvas-tools, install/deploy-greenbone.sh
- Symptom: `curl -sk https://127.0.0.1:9392` returns HTTP 000 or exit 35
- Root cause: GSA/nginx/gvmd need time to initialize after first boot. Feed data sync also needs to complete. The TLS handshake fails early because the stack is still starting up.

### Solution

Wait 2-5 minutes after deploy, then retry. The readiness polling (Step 13) confirms all containers are running and healthy. GSA web interface becomes available after gvmd finishes initializing and the first feed sync completes.

### Key lesson

HTTP 000 or curl exit 35 is expected on first boot. The deploy script's Step 15 catches this gracefully (WARN, not ERROR). Check with `docker compose -f /opt/greenbone-community/compose.yaml logs gvmd --tail 20` to monitor initialization progress.

---

## 2026-06-19 - deploy-greenbone.sh test issue: stderr not captured by test harness

### Question

Why did tests 17 and 19 fail initially when checking error messages?

### Context

- Repository/host/component: openvas-tools, tests/test-deploy-greenbone.sh
- Symptom: `assert_output_contains` and `assert_exit_code` used `2>/dev/null`, discarding stderr output
- Root cause: The test helper functions redirected stderr to `/dev/null`, but the installer script writes error messages to stderr

### Solution

Changed `2>/dev/null` to `2>&1` in `assert_output_contains` and `assert_output_not_contains` to capture both stdout and stderr. For `assert_exit_code`, `2>/dev/null` is acceptable because only the exit code matters, but changed to `2>&1 >/dev/null` for consistency.

### Key lesson

When testing CLI scripts that write errors to stderr, always capture `2>&1` in test assertions, not `2>/dev/null`.

---

## 2026-06-19 - Initial audit of openvas.sh downloaded script

### Question

What are the critical issues found in the downloaded `openvas.sh` script from the Desktop?

### Context

- Repository/host/component: Desktop file, not in any repository
- Symptom: Script contains 3 hardcoded passwords, inconsistent docker-compose syntax, destructive `remove` mode, unsafe `chown`
- Root cause: Script is a custom wrapper around Greenbone Community Containers, not an official Greenbone release script

### Solutions

1. Remove all hardcoded passwords from active code paths (lines 93, 96, 99).
2. Replace `docker stop $(docker ps -a -q)` with project-scoped `docker compose down`.
3. Remove `chown :openvas /var/lib/docker/` — this breaks Docker permissions.
4. Fix `docker-compose` vs `docker compose` inconsistency.
5. Replace hardcoded `sleep 50` with health-check polling.

### Key lesson

Always audit downloaded infrastructure scripts for hardcoded credentials, destructive commands, and Docker Compose version assumptions before any execution. See the full audit report in the conversation history.

---

## 2026-06-22 - Accidental Docker image pull during test execution

### Question

Why did the test suite pull Greenbone Docker images and start containers?

### Context

- Repository: Coverup20/openvas-tools
- Component: tests/test-deploy-greenbone.sh
- Symptom: Running `test_deploy_confirmed_flag()` caused `docker compose pull` and `docker compose up -d`
- Root cause: The test called `bash deploy-greenbone.sh --non-interactive deploy` which satisfied all safety gates (flag present, non-interactive skipped typed confirmation, disk in warn range but non-interactive skipped prompt). The deploy function proceeded to download the compose file, pull images, and start the stack.

### Solution

1. Tests that validate deploy flag parsing now use ONLY `--help` output — never call deploy mode.
2. Added `DRY_RUN=true` support: when set, all `docker compose` commands are printed but not executed.
3. Added a DRY_RUN deploy test (`DRY_RUN=true bash deploy-greenbone.sh --non-interactive deploy`) that validates the command sequence without Docker side effects.
4. All `docker compose` commands in `cmd_deploy()` now go through the `dry_run_cmd` wrapper.
5. `poll_readiness()` early-exits when `DRY_RUN=true`.

### Prevention rule

Tests must never call `deploy` mode with flags that could trigger real execution. Use `DRY_RUN=true` for any test that needs to validate the deploy code path. For flag parsing validation, use `--help` output only.

---

## 2026-06-19 - Repository initialization

### Question

What is the correct local path and Git setup for openvas-tools?

### Context

- Repository: Coverup20/openvas-tools (not yet created on GitHub)
- Local path: C:\Users\Marzio\Desktop\OpenVAS\openvas-tools
- WSL path: /mnt/c/Users/Marzio/Desktop/OpenVAS/openvas-tools

### Solution

- `git init && git branch -m main`
- No remote configured until GitHub repo is created
- Follow git-push-policy.md for commit/tag/release workflow
