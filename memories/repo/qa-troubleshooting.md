# Q&A Troubleshooting

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
