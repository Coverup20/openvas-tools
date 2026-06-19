# openvas-tools

Tools, automation and documentation for Greenbone Community Edition
(OpenVAS) vulnerability scanning platform deployment and operation.

## Repository purpose

| Area | Description |
|---|---|
| [install/](install/) | Deployment and preparation scripts for Greenbone on Ubuntu |
| [compose/](compose/) | Docker Compose configurations and overrides |
| [reports/](reports/) | XML export, transformation and ODT report generation |
| [backup/](backup/) | Backup and disaster recovery scripts |
| [docs/](docs/) | Architecture and operational documentation |
| [tests/](tests/) | Validation and integration tests |

## Quick start (isolated VM only)

```bash
# Prerequisites: Ubuntu 22.04+, Docker, Docker Compose plugin
cd /opt/openvas-tools
sudo bash install/setup-host.sh          # Host preparation
sudo docker compose -f compose/docker-compose.yml up -d   # Deploy stack
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for detailed instructions.

## Safety requirements

- **Never execute this stack on production or internet-facing hosts.**
- All Greenbone containers expose the web interface on localhost port 9392 only.
- Target scanning requires explicit written authorization.
- Always create a full backup before stack updates.

## License

GNU General Public License v3.0 or later.
