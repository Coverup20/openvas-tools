#!/usr/bin/env python3
"""greenbone_setup_do.py - Interactive rclone remote setup for Greenbone backups

Adapted from the Checkmk backup model (backup_restore/checkmk_rclone_space_dyn.py).
See: https://github.com/nethesis/checkmk-tools

Interactive setup for an S3-compatible rclone remote (DigitalOcean Spaces or AWS).
Configures credentials via hidden input, creates/updates the remote, and tests it.

Usage:
  python3 scripts/backup_restore/greenbone_setup_do.py [--remote NAME:BUCKET]
  python3 scripts/backup_restore/greenbone_setup_do.py [--remote NAME:BUCKET] \\
      --rclone-config /path/to/rclone.conf

Safety:
  - Secrets are never printed or logged.
  - No backup or upload is performed.
  - Uses getpass for sensitive input.

Defaults:
  --remote do:testmonbck

Version: 0.1.0
"""

import argparse
import datetime as dt
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List


VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%F %T')}] {msg}")


def err(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%F %T')}] ERROR: {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    err(msg)
    raise SystemExit(code)


def warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def prompt_default(prompt_text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt_text}{suffix}: ").strip()
    return value or default


def prompt_secret(prompt_text: str) -> str:
    return getpass.getpass(f"{prompt_text}: ").strip()


def confirm_default_no(prompt_text: str) -> bool:
    value = input(f"{prompt_text} [y/N]: ").strip().lower()
    return value == "y"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


# ---------------------------------------------------------------------------
# Rclone operations
# ---------------------------------------------------------------------------
def remote_exists(rclone_config: Path, remote_name: str) -> bool:
    """Check if an rclone remote exists in the given config file."""
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    result = subprocess.run(
        ["rclone", "config", "show", remote_name],
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.returncode == 0


def create_or_update_remote_s3(
    rclone_config: Path,
    remote_name: str,
    provider: str,
    access_key: str,
    secret_key: str,
    region: str,
    endpoint: str,
) -> None:
    """Create or update an S3-compatible rclone remote."""
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    cmd = [
        "rclone", "config", "create", remote_name, "s3",
        f"provider={provider}",
        "env_auth=false",
        f"access_key_id={access_key}",
        f"secret_access_key={secret_key}",
        f"region={region}",
        f"endpoint={endpoint}",
        "acl=private",
        "--obscure",
    ]
    result = subprocess.run(cmd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        die(f"Failed to create/update remote '{remote_name}': {result.stderr.strip()}")


def test_remote(rclone_config: Path, remote_full: str) -> bool:
    """Test rclone remote access."""
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(rclone_config)
    log(f"Testing remote: {remote_full}")
    test = subprocess.run(
        ["rclone", "lsd", f"{remote_full}"],
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if test.returncode == 0:
        log("Remote test OK.")
        return True
    else:
        warn(f"Remote test failed: {test.stderr.strip()}")
        return False


# ---------------------------------------------------------------------------
# Main setup logic (adapted from checkmk_rclone_space_dyn.py)
# ---------------------------------------------------------------------------
def ensure_remote_configured(rclone_config: Path, remote_full: str) -> None:
    """Interactive rclone remote setup."""
    if ":" not in remote_full:
        die(f"Remote must be in form name:bucket. Got: {remote_full}")

    remote_name = remote_full.split(":", 1)[0]

    # Check if remote already exists
    if remote_exists(rclone_config, remote_name):
        log(f"Remote '{remote_name}' already exists in {rclone_config}.")
        if confirm_default_no(f"Reconfigure remote '{remote_name}'?"):
            log(f"Reconfiguring existing remote '{remote_name}'.")
        else:
            log(f"Remote '{remote_name}' already configured. Testing access...")
            test_remote(rclone_config, remote_full)
            return
    else:
        log(f"Remote '{remote_name}' not found in {rclone_config}. Will create it now.")

    # Provider selection
    mode = prompt_default("Remote type (do/aws)", "do")
    access_key = prompt_default("S3 Access Key ID", "")
    if not access_key:
        die("Access Key ID cannot be empty.")
    secret_key = prompt_secret("S3 Secret Access Key")
    if not secret_key:
        die("Secret Access Key cannot be empty.")

    if mode == "do":
        region = prompt_default("DO Spaces region (e.g. nyc3, fra1, ams3)", "ams3")
        endpoint = prompt_default("DO Spaces endpoint URL", f"https://{region}.digitaloceanspaces.com")
        provider = "DigitalOcean"
    else:
        region = prompt_default("AWS region (e.g. eu-west-1)", "eu-west-1")
        endpoint = prompt_default("AWS S3 endpoint URL (leave default for AWS)", f"https://s3.{region}.amazonaws.com")
        provider = "AWS"

    log(f"Creating/updating rclone remote '{remote_name}' in {rclone_config} ...")
    create_or_update_remote_s3(rclone_config, remote_name, provider, access_key, secret_key, region, endpoint)

    # Test the remote
    if test_remote(rclone_config, remote_full):
        log(f"Remote '{remote_name}' ready. Greenbone cloud path: {remote_full}/greenbone-backups/job00-daily")
    else:
        warn(f"Remote test failed. Verify manually: RCLONE_CONFIG={rclone_config} rclone lsd {remote_full}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive rclone remote setup for Greenbone backups")
    ap.add_argument("--remote", default="do:testmonbck",
                    help="Remote name and bucket, e.g. 'do:testmonbck' (default: do:testmonbck)")
    ap.add_argument("--rclone-config",
                    help="Path to rclone.conf (default: auto-detected)")
    args = ap.parse_args()

    rclone_config = args.rclone_config
    if rclone_config:
        rclone_config = Path(rclone_config)
    else:
        rclone_config = Path("~/.config/rclone/rclone.conf").expanduser()
        if not rclone_config.parent.exists():
            rclone_config = Path("/root/.config/rclone/rclone.conf")

    print(f"\n=== greenbone_setup_do.py v{VERSION} ===")
    print(f"Adapted from the Checkmk backup model")
    print(f"Reference: backup_restore/checkmk_rclone_space_dyn.py\n")
    log(f"Remote:      {args.remote}")
    log(f"Config path: {rclone_config}\n")

    # Ensure rclone is available
    if not command_exists("rclone"):
        warn("rclone not found.")
        if confirm_default_no("rclone is required. Install it now?"):
            log("Installing rclone from rclone.org...")
            inst = run(["bash", "-c", "curl -fsSL https://rclone.org/install.sh | bash"], check=False)
            if inst.returncode != 0:
                die("rclone installation failed. Install manually: curl https://rclone.org/install.sh | sudo bash")
            log("rclone installed.")
        else:
            die("rclone is required. Install it and re-run this script.")
    else:
        ver = run(["rclone", "--version"], check=False)
        version_line = (ver.stdout or "").splitlines()[0] if ver.stdout else "version unknown"
        log(f"rclone: {version_line}")

    # Ensure config directory exists
    rclone_config.parent.mkdir(parents=True, exist_ok=True)

    # Run interactive setup
    ensure_remote_configured(rclone_config, args.remote)

    return 0


if __name__ == "__main__":
    sys.exit(main())
