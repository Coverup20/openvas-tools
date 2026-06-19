# Git push policy

## Remote

- `origin` = `git@github.com:Coverup20/openvas-tools.git`

## Commit format

```
type(scope): tool_name v0.0.x - lowercase description
```

Where:
- `type`: feat, fix, docs, refactor, test, chore
- `scope`: install, compose, reports, backup, docs, tests

## Versioning

- All tags use `v0.0.X` format.
- Increment X by 1 from the highest existing `v0.0.X` tag.
- Do not switch versioning scheme without explicit confirmation.

## Tag + release workflow (mandatory)

```bash
git tag v0.0.X
git push origin main
git push origin --tags
gh release create v0.0.X --title "v0.0.X" --notes "Release notes..."
```

## Release note style

- Title: `v0.0.X - short summary`
- Sections: `Added:`, `Changed:`, `Fixed:`, `Removed:` (only when applicable)
- Bullet: `• component/file vX.Y.Z: concise description`

## Safety rules

- Never push to `upstream` (no upstream defined for this repo).
- Always review `git --no-pager diff` before committing.
- Verify `git status --short` before any push.
- Do not force push without explicit confirmation.
- Do not delete existing tags without explicit confirmation.
