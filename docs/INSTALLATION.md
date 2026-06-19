# Installation

Greenbone Community Edition deployment on Ubuntu using Docker Compose.

## Prerequisites

- Ubuntu 22.04 (Jammy) or 24.04 (Noble)
- Minimum 4 GB RAM, 2 CPU cores, 40 GB disk
- Docker Engine 24+ with Compose plugin v2
- Root or sudo access

## Step 1 — Host preparation

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Install Docker Engine (if not present)
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

## Step 2 — Deploy the stack

```bash
# Clone the repository
git clone https://github.com/Coverup20/openvas-tools.git /opt/openvas-tools
cd /opt/openvas-tools

# Download the official Compose file
curl -f -O -L https://greenbone.github.io/docs/latest/_static/compose.yaml \
  --output-dir compose/

# Pull images
docker compose -f compose/compose.yaml pull

# Start the stack
docker compose -f compose/compose.yaml up -d

# Monitor startup
docker compose -f compose/compose.yaml logs --tail=20 gvmd
```

## Step 3 — Set admin password

```bash
# Replace <PASSWORD> with a strong, unique password
docker compose -f compose/compose.yaml \
  exec -u gvmd gvmd gvmd --user=admin --new-password=<PASSWORD>
```

## Step 4 — Access the web interface

Open `https://127.0.0.1:9392` in a browser.

Accept the self-signed certificate warning (default setup).

## Step 5 — Verify feed sync

```bash
docker compose -f compose/compose.yaml exec -u gvmd gvmd gvmd --get-feeds
```

The NVT count should be non-zero. If zero, wait for feed data containers to finish loading.

## Post-installation

- Configure TLS with valid certificates (see nginx configuration).
- Create additional users with restricted roles as needed.
- Set up scheduled backups (see `backup/`).
- Configure scan alerts and notification targets.
