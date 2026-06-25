"""docker_compose.py - Docker Compose inspection helpers.

Read-only operations only.  Never modifies Docker resources.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .command import run, CommandError


def compose_services(compose_file: Path) -> List[str]:
    """Return the service names from 'docker compose config --services'."""
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "config", "--services"],
                check=False, timeout=30)
        if r.returncode == 0 and r.stdout:
            return [s.strip() for s in r.stdout.splitlines() if s.strip()]
    except Exception:
        pass
    return []


def compose_volumes(compose_file: Path) -> List[str]:
    """Return the named volumes from 'docker compose config --volumes'."""
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "config", "--volumes"],
                check=False, timeout=30)
        if r.returncode == 0 and r.stdout:
            return [v.strip() for v in r.stdout.splitlines() if v.strip()]
    except Exception:
        pass
    return []


def compose_ps(compose_file: Path) -> str:
    """Return full 'docker compose ps --all' output."""
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "ps", "--all"],
                check=False, timeout=30)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def docker_version_info() -> str:
    """Return Docker version string."""
    try:
        r = run(["docker", "--version"], check=False, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return "unavailable"


def compose_version_info() -> str:
    """Return Docker Compose version string."""
    try:
        r = run(["docker", "compose", "version"], check=False, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return "unavailable"


def docker_images_list() -> List[str]:
    """Return list of image repo:tag combinations."""
    try:
        r = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                check=False, timeout=30)
        if r.returncode == 0 and r.stdout:
            return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    return []


def docker_volumes_inventory() -> List[Dict[str, str]]:
    """Return list of {name, driver} dicts for all Docker volumes."""
    try:
        r = run(["docker", "volume", "ls", "--format", "{{.Name}} {{.Driver}}"],
                check=False, timeout=30)
        vols: List[Dict[str, str]] = []
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                parts = line.split()
                if not parts:
                    continue
                vols.append({"name": parts[0], "driver": parts[1] if len(parts) > 1 else "unknown"})
        return vols
    except Exception:
        return []


def compose_project_name(compose_file: Path) -> Optional[str]:
    """Return the project name from compose file, if any."""
    try:
        r = run(["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
                check=False, timeout=30)
        if r.returncode == 0 and r.stdout:
            data = json.loads(r.stdout)
            return data.get("name")
    except Exception:
        pass
    return None
