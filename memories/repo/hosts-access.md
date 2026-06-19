# Hosts access

## OpenVAS / Greenbone test hosts

| Alias | Host | Port | Auth | Purpose |
|---|---|---|---|---|
| (TBD) | (TBD) | (TBD) | (TBD) | Isolated VM for Greenbone testing |

## Rules

- Always test in an isolated VM before any production deployment.
- Do not deploy Greenbone on shared or multi-tenant infrastructure.
- Document each host's SSH authentication method and OS version.
- Record image digests deployed on each host for reproducibility.
