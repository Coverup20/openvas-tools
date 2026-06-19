# GitHub Copilot Instructions - openvas-tools

## MANDATORY PRELIMINARY RULE

**BEFORE STARTING ANY WORK:**

- Always read this file at the beginning of every conversation.
- Always consult this file before starting any task.
- This file contains all rules, workflows and mandatory procedures.
- Do not start work without reading and understanding the instructions.

**MANDATORY: At the start of every conversation, use the memory tool to read these repository memory files:**
- `memories/repo/git-push-policy.md` — Git commit format, versioning (v0.0.x), tag + release workflow
- `memories/repo/hosts-access.md` — SSH access methods per host
- `memories/repo/scripts-index.md` — Index of all scripts and their purpose

---

## Repository Information

**Repository:** `Coverup20/openvas-tools`
**Type:** Owned repository (not a fork)
**Purpose:** OpenVAS / Greenbone Community Edition tools, automation and documentation

---

## MANDATORY GENERAL RULES

### File language

- All text in files must be in English: comments, docstrings, log messages, README, documentation.
- New files: write directly in English.
- Modified existing files: translate the touching parts into English.
- Chat communications remain in Italian.

### No personal names or brand names in files

- Never include names of people, usernames, GitHub handles, internal brand names, customer names, or project codenames.
- Use generic references.

### No hardcoded environment data in files

- Never hardcode IP addresses, hostnames, domain names, ports, URLs, credentials, tokens, API keys.
- Use environment variables, config files, or parameters passed at runtime.

---

## Python-First Policy

- All new scripts must be written in Python.
- Python is the official language for new automation, tools and checks.
- Bash only for minimal bootstrap wrappers or justified exceptional cases.

---

## Greenbone / OpenVAS safety rules

- Never touch Greenbone database or feed files directly.
- Never inject unvalidated GMP XML into gvmd.
- Never expose GMP, PostgreSQL, or SMTP credentials.
- Never edit production container configuration files directly.
- Never execute destructive commands without explicit user approval.
- Never start a scan without confirmed written or verbal authorization.

---

## Workflow

**Every change requires:**
1. Syntax validation.
2. Functional test on test host or isolated VM.
3. Commit with format: `type(scope): component v0.0.x - lowercase description`
4. Tag with same version: `git tag v0.0.x`
5. Push: `git push && git push origin --tags`
6. Release: `gh release create v0.0.x --title "v0.0.x" --notes "Uppercase description..."`

---

## MANDATORY POST-JOB RETROSPECTIVE

After every completed task involving non-trivial troubleshooting, create or update an entry in `memories/repo/qa-troubleshooting.md` with the exact symptom, root cause, solution and commands. Update `memories/repo/scripts-index.md` for new scripts or tools. Never skip this step.

---

## Data Safe Policy

The agent applies Data Safe redaction for all reports, tickets, documentation and shared output. Full diagnostics remain visible during investigation; secrets and sensitive identifiers are replaced with `[REDACTED]` at the sharing boundary.
