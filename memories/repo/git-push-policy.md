# Git push policy

## Remote

- `origin` = `git@github.com:Coverup20/openvas-tools.git`

## Commit format

```
type(scope): tool_name v0.0.X - lowercase description
```

Where:
- `type`: feat, fix, docs, refactor, test, chore
- `scope`: install, compose, reports, backup, docs, tests
- `v0.0.X`: PATCH-increment version (X increments numerically:
  v0.0.1 → v0.0.2 → ... → v0.0.9 → v0.0.10 → v0.0.11)

## MANDATORY VERSION CLASSIFICATION AND PATCH PROGRESSION

For fixes, maintenance changes, policy updates, documentation corrections,
backward-compatible refactors, validation improvements, and internal
operational hardening, increment PATCH only.

Required sequence:
v1.0.0 → v1.0.1 → ... → v1.0.9 → v1.0.10 → v1.0.11

Do not increment MINOR unless a real new backward-compatible feature has
been explicitly classified and approved as a MINOR release.

Never abbreviate v1.0.10 as v1.10.

## Versioning

- All tags use `vMAJOR.MINOR.PATCH` format (three-component SemVer).
- Increment PATCH by 1 from the highest existing version tag.
- Never abbreviate: `v1.0.10` is correct; `v1.10` is wrong.
- Only increment MINOR for a real explicitly classified and approved new
  backward-compatible feature.
- Only increment MAJOR for an explicitly approved breaking change.
- Do not switch versioning scheme without explicit confirmation.

## Tag + release workflow (mandatory)

```bash
git tag v<PATCH_VERSION>
git push origin main
git push origin --tags
gh release create v<PATCH_VERSION> --title "v<PATCH_VERSION>" --notes "Release notes..."
```

## Release note style

- Title: `v<MAJOR>.<MINOR>.<PATCH> - short summary`
- Sections: `Added:`, `Changed:`, `Fixed:`, `Removed:` (only when applicable)
- Bullet: `• component/file vX.Y.Z: concise description`

## Safety rules

- Never push to `upstream` (no upstream defined for this repo).
- Always review `git --no-pager diff` before committing.
- Verify `git status --short` before any push.
- Do not force push without explicit confirmation.
- Do not delete existing tags without explicit confirmation.
