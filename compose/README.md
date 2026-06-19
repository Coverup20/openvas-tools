# compose/

Docker Compose configurations for Greenbone Community Edition.

## Contents

| File | Description |
|---|---|
| `docker-compose.yml` | Base Compose file from official Greenbone Community Containers |
| `docker-compose.override.yml` | Local overrides (gitignored — not committed) |

## Source

The Compose files are derived from the official Greenbone repository:
`https://github.com/greenbone/community-containers/`

## Policy

- Always reference image digests in production — never use floating `:latest` tags alone.
- Do not commit `.env` files or credentials.
- Document any deviation from the official upstream configuration.
