# Architecture

Greenbone Community Edition container stack architecture reference.

## Core components

| Component | Role | Image |
|---|---|---|
| **gvmd** | Greenbone Vulnerability Manager Daemon — central manager, GMP API, task scheduling, report generation | `gvmd:stable` |
| **ospd-openvas** | OSP protocol bridge — manages scanner processes for each target | `ospd-openvas:stable` |
| **openvas-scanner** | NVT execution engine — runs vulnerability tests | `openvas-scanner:stable` |
| **openvasd** | Newer scanner daemon — handles Notus and lightweight scans | `openvas-scanner:stable` |
| **Notus Scanner** | Local vulnerability detection based on product metadata (via openvasd) | (part of openvas-scanner) |
| **GSA / gsad** | Greenbone Security Assistant — web UI on port 9392 | `gsa:stable-slim`, `gsad:stable` |
| **pg-gvm** | PostgreSQL database — stores configs, targets, tasks, results | `pg-gvm:stable` |
| **redis-server** | Cache and IPC for openvas-scanner (NVT metadata, scan progress) | `redis-server` |
| **nginx** | Reverse proxy for GSA with TLS termination | `nginx:latest` |

## Feed data containers

| Container | Data |
|---|---|
| `vulnerability-tests` | NVTs (NASL scripts) |
| `notus-data` | Notus advisory data |
| `scap-data` | SCAP content |
| `cert-bund-data` | German CERT-Bund data |
| `dfn-cert-data` | DFN-CERT data |
| `data-objects` | GMP data objects |
| `report-formats` | Report format definitions |
| `gpg-data` | GPG keys for feed verification |

## Communication flow

```
User → GSA (port 9392) → gsad → gvmd (GMP/Unix socket)
                                        │
                                        ├── PostgreSQL (gvmd database)
                                        │
                                        └── ospd-openvas (OSP)
                                                │
                                                ├── redis-server (cache)
                                                │
                                                └── openvas-scanner (NVTs)
                                                │
                                                └── openvasd / Notus
```

## Ports

| Port | Service | Binding | Protocol |
|---|---|---|---|
| 9392 | GSA (nginx) | 127.0.0.1 | HTTPS |
| 443 | GSA (nginx) | 127.0.0.1 | HTTPS |
| 9390 | GMP (gvmd) | Internal only | TLS |
| 5432 | PostgreSQL | Internal only | TCP |
| 6379 | Redis | Internal only | TCP |

## Volumes

All data is stored in Docker named volumes (see `compose/docker-compose.yml` for the full list). The volumes persist across container restarts but are destroyed on `docker compose down -v`.

## Feed synchronization

Feed data is provided by dedicated containers (`vulnerability-tests`, `notus-data`, etc.) that run with `KEEP_ALIVE=1`. On startup, these containers load data into shared volumes. There is no separate feed sync daemon inside the gvmd container.
