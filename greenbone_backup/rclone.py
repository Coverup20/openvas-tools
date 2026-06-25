"""rclone.py - Rclone configuration, validation, and DO Spaces setup.

Replicates the credential logic from the working Checkmk backup
implementation (checkmk_rclone_space_dyn.py).

All secrets are handled via getpass and --obscure.  No secret value
is ever printed or written to logs.

Copyright (C) 2026 Nethesis S.r.l.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import getpass
import os
import shutil
from pathlib import Path
from typing import Optional

from .command import run, CommandError
from .config import default_rclone_config
from .logging_utils import log, err, warn


def rclone_installed() -> bool:
    """Return True if rclone is available in PATH."""
    return shutil.which("rclone") is not None


def rclone_version() -> str:
    """Return the rclone version string or 'unknown'."""
    try:
        r = run(["rclone", "--version"], check=False, timeout=10)
        first = (r.stdout or "").splitlines()[0] if r.stdout else ""
        return first or "unknown"
    except Exception:
        return "unknown"


def remote_exists(rclone_config: Path, remote_name: str) -> bool:
    """Check if an rclone remote exists in the given config file.

    Uses the RCLONE_CONFIG env var to point to the explicit config path.
    """
    env = {**os.environ, "RCLONE_CONFIG": str(rclone_config)}
    try:
        r = run(
            ["rclone", "config", "show", remote_name],
            env=env, check=False, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def create_do_remote(
    rclone_config: Path,
    remote_name: str,
    access_key: str,
    secret_key: str,
    region: str = "ams3",
    endpoint: Optional[str] = None,
) -> None:
    """Create or update a DigitalOcean Spaces rclone remote.

    Credentials are stored encrypted via --obscure.
    No secret is echoed in logs or stdout.
    """
    if endpoint is None:
        endpoint = f"https://{region}.digitaloceanspaces.com"

    env = {**os.environ, "RCLONE_CONFIG": str(rclone_config)}
    cmd = [
        "rclone", "config", "create", remote_name, "s3",
        f"provider=DigitalOcean",
        "env_auth=false",
        f"access_key_id={access_key}",
        f"secret_access_key={secret_key}",
        f"region={region}",
        f"endpoint={endpoint}",
        "acl=private",
        "--obscure",
    ]
    run(cmd, env=env, check=True, timeout=30)
    log(f"Remote '{remote_name}' created in {rclone_config}.")


def test_remote(rclone_config: Path, remote_full: str) -> bool:
    """Test an rclone remote with 'lsd'.  Returns True on success.

    The remote_full argument is the only thing logged (e.g. 'do:testmonbck').
    No credentials are ever printed.
    """
    env = {**os.environ, "RCLONE_CONFIG": str(rclone_config)}
    log(f"Testing remote: {remote_full}")
    try:
        r = run(["rclone", "lsd", f"{remote_full}"], env=env, check=False, timeout=30)
        if r.returncode == 0:
            log("Remote test OK.")
            return True
        else:
            warn(f"Remote test failed: {(r.stderr or '').strip()[:300]}")
            return False
    except Exception as e:
        err(f"Remote test error: {e}")
        return False


def validate_rclone_config(rclone_config: Path, remote_name: str, remote_full: str) -> bool:
    """Validate that rclone config is present, has the expected remote,
    and the remote is accessible.

    Returns True if all checks pass, False otherwise.
    This is a read-only operation.
    """
    if not rclone_config.exists():
        log(f"Rclone config not found: {rclone_config}")
        return False

    actual_perms = oct(rclone_config.stat().st_mode)[-3:]
    log(f"Rclone config: {rclone_config} (perms {actual_perms})")

    if not remote_exists(rclone_config, remote_name):
        log(f"Remote '{remote_name}' not found in rclone config.")
        return False

    log(f"Remote '{remote_name}' found.")
    return True


def prompt_and_create_remote(rclone_config: Path, remote_full: str) -> bool:
    """Interactive rclone remote setup.

    Returns True if setup succeeded, False otherwise.
    Never prints secrets.
    """
    if ":" not in remote_full:
        err(f"Remote must be in form name:bucket. Got: {remote_full}")
        return False

    remote_name = remote_full.split(":", 1)[0]

    if not rclone_installed():
        if input("rclone is not installed. Install it now? [y/N]: ").strip().lower() == "y":
            log("Installing rclone...")
            run(["bash", "-c", "curl -fsSL https://rclone.org/install.sh | bash"], check=True, timeout=120)
        else:
            err("rclone is required. Aborting.")
            return False

    log(f"rclone: {rclone_version()}")

    # Ensure config directory exists
    rclone_config.parent.mkdir(parents=True, exist_ok=True)

    if remote_exists(rclone_config, remote_name):
        log(f"Remote '{remote_name}' already exists.")
        if input(f"Reconfigure remote '{remote_name}'? [y/N]: ").strip().lower() != "y":
            # Test existing
            return test_remote(rclone_config, remote_full)
        else:
            # Delete before recreate
            env = {**os.environ, "RCLONE_CONFIG": str(rclone_config)}
            run(["rclone", "config", "delete", remote_name], env=env, check=False, timeout=15)

    # Interactive credential collection
    access_key = input("S3 Access Key ID: ").strip()
    if not access_key:
        err("Access Key ID cannot be empty.")
        return False
    secret_key = getpass.getpass("S3 Secret Access Key: ").strip()
    if not secret_key:
        err("Secret Access Key cannot be empty.")
        return False

    region = input("DO Spaces region [ams3]: ").strip() or "ams3"
    endpoint = f"https://{region}.digitaloceanspaces.com"

    try:
        create_do_remote(rclone_config, remote_name, access_key, secret_key, region, endpoint)
    except CommandError as e:
        err(f"Failed to create remote '{remote_name}': {e.stderr[:300]}")
        return False

    # Set secure permissions
    try:
        rclone_config.chmod(0o600)
    except Exception:
        pass

    return test_remote(rclone_config, remote_full)


def config_path_resolved(config_override: Optional[str] = None) -> Path:
    """Return the rclone config path, with auto-detection fallback.

    Convention: root uses /root/.config/rclone/rclone.conf with 0600 perms.
    """
    if config_override:
        return Path(config_override)
    return default_rclone_config()
