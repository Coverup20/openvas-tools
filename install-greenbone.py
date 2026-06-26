#!/usr/bin/env python3
"""
install-greenbone.py — Unified Greenbone installer, manager and DR tool

Usage:
  python3 install-greenbone.py              ← interactive menu
  python3 install-greenbone.py setup-host   ← non-interactive mode

Self-contained. Sub-scripts (deploy) are fetched via curl.
"""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

VERSION = "0.2.19"
RAW = "https://raw.githubusercontent.com/Coverup20/openvas-tools/main"


# ── Helpers ─────────────────────────────────────────────────────────────

def info(msg):  print(f"\033[1;34m[INFO]\033[0m  {msg}")
def ok(msg):    print(f"\033[1;32m[ OK ]\033[0m  {msg}")
def warn(msg):  print(f"\033[1;33m[WARN]\033[0m  {msg}", file=sys.stderr)
def fail(msg):  print(f"\033[1;31m[FAIL]\033[0m  {msg}", file=sys.stderr)


def confirm(prompt: str) -> bool:
    """Ask yes/no. Returns True for y/Y."""
    while True:
        a = input(f"{prompt} [y/N]: ").strip().lower()
        if a in ('y', 'yes'): return True
        if a in ('', 'n', 'no'): return False


def run(cmd, **kwargs):
    """Run a command, return CompletedProcess with stdout/stderr captured.

    By default, output is captured (stdout/stderr available on result).
    Pass ``live=True`` to show output in real-time (stdout/stderr will be None).
    ``capture=True`` is accepted for backward compatibility (redundant).
    """
    kwargs.setdefault('text', True)
    kwargs.pop('capture', None)  # legacy, always captured by default now
    if kwargs.pop('live', False):
        return subprocess.run(cmd, **kwargs)
    kwargs.setdefault('capture_output', True)
    return subprocess.run(cmd, **kwargs)


def _safe_text(value):
    """Return stripped text or empty string if value is None."""
    return (value or "").strip()


def _safe_lines(value):
    """Yield non-empty stripped lines from a string or None."""
    text = _safe_text(value)
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield line


def check_root():
    if os.geteuid() != 0:
        fail("Must be run as root (sudo).")
        sys.exit(1)


def download(path: str) -> str:
    """Download a sub-script from GitHub, return temp path."""
    import tempfile
    import urllib.request
    url = f"{RAW}/{path}"
    tmp = tempfile.mktemp()
    try:
        urllib.request.urlretrieve(url, tmp)
        os.chmod(tmp, 0o755)
        return tmp
    except Exception as e:
        os.unlink(tmp)
        fail(f"Cannot download {url}: {e}")
        sys.exit(1)


# ── 1. SETUP HOST ──────────────────────────────────────────────────────

def setup_host():
    check_root()
    header("HOST SETUP")
    info(f"OS: {_detect_os()}")
    info(f"Docker: {_docker_version()}")
    info(f"Compose: {_compose_version()}")
    info(f"vm.max_map_count: {_read_sysctl('vm.max_map_count')}")
    info(f"Swap: {_swap_size()}")
    info(f"User greenbone: {'exists' if _user_exists('greenbone') else 'missing'}")

    if not confirm("Proceed with host setup?"):
        return

    # Packages
    info("Installing system packages …")
    run(["apt-get", "update", "-qq"], capture=True, check=False)
    run(["apt-get", "install", "-y", "-qq", "ca-certificates", "curl",
         "gnupg", "git", "openssh-server", "qemu-guest-agent"],
        capture=True, check=False)

    # Docker
    if not shutil.which("docker") or not _docker_version():
        info("Installing Docker …")
        os.makedirs("/etc/apt/keyrings", exist_ok=True)
        run(["curl", "-fsSL", "https://download.docker.com/linux/ubuntu/gpg",
             "-o", "/etc/apt/keyrings/docker.asc"], check=False)
        os.chmod("/etc/apt/keyrings/docker.asc", 0o644)
        arch = run(["dpkg", "--print-architecture"], capture=True).stdout.strip() or "amd64"
        with open("/etc/apt/sources.list.d/docker.list", "w") as f:
            f.write(f"deb [arch={arch} signed-by=/etc/apt/keyrings/docker.asc] "
                    f"https://download.docker.com/linux/ubuntu noble stable\n")
        run(["apt-get", "update", "-qq"], capture=True, check=False)
        run(["apt-get", "install", "-y", "-qq", "docker-ce", "docker-ce-cli",
             "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"],
            capture=True, check=False)
        run(["systemctl", "enable", "--now", "docker"], check=False)
    ok(f"Docker {_docker_version()}")
    ok(f"Compose {_compose_version()}")

    # Kernel
    if int(_read_sysctl('vm.max_map_count') or 0) < 262144:
        with open("/etc/sysctl.d/99-greenbone.conf", "w") as f:
            f.write("vm.max_map_count = 262144\n")
        run(["sysctl", "-p", "/etc/sysctl.d/99-greenbone.conf"])
        ok("Kernel parameters set")

    # Swap
    if _swap_mb() < 1024:
        run(["dd", "if=/dev/zero", "of=/swapfile", "bs=1M", "count=4096",
             "status=none"])
        run(["chmod", "600", "/swapfile"])
        run(["mkswap", "/swapfile"])
        run(["swapon", "/swapfile"])
        with open("/etc/fstab", "a") as f:
            f.write("/swapfile none swap sw 0 0\n")
        ok("Swap 4G created")

    # greenbone user
    if not _user_exists("greenbone"):
        run(["adduser", "--gecos", "", "--disabled-password", "greenbone"],
            check=False)
        run(["usermod", "-aG", "sudo", "greenbone"], check=False)
        ok("User greenbone created")

    # SSH
    os.makedirs("/etc/ssh/sshd_config.d", exist_ok=True)
    with open("/etc/ssh/sshd_config.d/99-root-login.conf", "w") as f:
        f.write("PermitRootLogin yes\n")
    run(["systemctl", "restart", "ssh"], check=False)
    run(["systemctl", "enable", "--now", "ssh"], check=False)
    ok("Root SSH login enabled")

    ok("Host setup finished")


def _detect_os():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except: pass
    return "unknown"


def _docker_version():
    r = run(["docker", "--version"], capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else "NOT INSTALLED"


def _compose_version():
    r = run(["docker", "compose", "version"], capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else "NOT INSTALLED"


def _read_sysctl(key):
    r = run(["sysctl", "-n", key], capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else "0"


def _swap_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("SwapTotal:"):
                    return int(line.split()[1]) // 1024
    except: pass
    return 0


def _swap_size():
    mb = _swap_mb()
    return f"{mb}MB" if mb else "none"


def _user_exists(name):
    r = run(["id", name], check=False)
    return r.returncode == 0


# ── 2. DEPLOY ──────────────────────────────────────────────────────────

def deploy(non_interactive=False):
    check_root()
    if not non_interactive and not confirm("Deploy Greenbone Community Containers?"):
        return
    # Use local deploy-greenbone.sh from the repository
    script = Path(__file__).resolve().parent / "install" / "deploy-greenbone.sh"
    if not script.exists():
        fail(f"Local deploy script not found: {script}")
        return
    info("Starting deployment using local script ...")
    try:
        os.chdir("/")
    except OSError:
        pass
    r = run([str(script), "deploy", "--deploy-confirmed", "--non-interactive",
             "--project-dir", "/opt/greenbone-community"], live=True)
    if r.returncode == 0:
        ok("Greenbone deployed successfully")
    else:
        fail(f"Deploy failed (exit {r.returncode})")


# ── 3. INSTALL BACKUP ──────────────────────────────────────────────────

def install_backup():
    check_root()
    if not confirm("Install backup system?"):
        return

    # Use the local copy of greenbone_install_backup.py from the repo,
    # not a downloaded one, because it depends on the greenbone_backup package.
    # The repo root is the directory containing this script.
    repo_root = Path(__file__).resolve().parent
    local_script = repo_root / "scripts" / "greenbone_install_backup.py"

    if not local_script.exists():
        fail("Local greenbone_install_backup.py not found at %s" % local_script)
        return

    info("Running local backup installer (PYTHONPATH includes repo)...")
    # CWD may be invalid after setup_host() — ensure valid directory before subprocess
    try:
        os.chdir("/")
    except OSError:
        pass
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + ":" + env.get("PYTHONPATH", "")
    r = run([sys.executable, str(local_script), "--install", "--repo-root", str(repo_root)], env=env, live=True)
    if r.returncode != 0:
        fail("Backup installation failed")
        return
    ok("Backup system installed")

    # DO Spaces (interactive, pure Python)
    if confirm("Configure DigitalOcean Spaces for cloud backup?"):
        _configure_do()

    # Timeshift
    if confirm("Install Timeshift for local snapshots?"):
        _install_timeshift()

    # Timers
    if confirm("Enable daily config backup timer?"):
        run(["systemctl", "enable", "--now", "greenbone-backup-job00.timer"])
        ok("Daily timer enabled")
    if confirm("Enable bi-weekly full DR timer?"):
        run(["systemctl", "enable", "--now", "greenbone-backup-full.timer"])
        ok("Full DR timer enabled")

    ok("Backup setup completed")


def _configure_do():
    """Interactive DO Spaces configuration.

    Writes rclone config directly to /root/.config/rclone/rclone.conf
    with 0600 permissions.  Credentials are stored in plain text
    (rclone accepts plain secret_access_key in the config file).
    """
    print()
    info("DigitalOcean Spaces backup configuration")
    print("(leave empty to skip)")
    print()

    remote = input("Remote type (do/aws) [do]: ").strip() or "do"
    if remote not in ("do", "aws"):
        warn("Invalid remote type, skipping")
        return

    bucket_name = input("Space name (bucket) [testmonbck]: ").strip() or "testmonbck"

    access_key = input("Access Key ID: ").strip()
    if not access_key:
        info("Skipped — no Access Key provided")
        return
    secret_key = getpass.getpass("Secret Access Key: ").strip()
    if not secret_key:
        info("Skipped — no Secret Key provided")
        return

    if remote == "do":
        region = input("Region (nyc3/fra1/ams3) [ams3]: ").strip() or "ams3"
        endpoint = input(f"Endpoint [https://{region}.digitaloceanspaces.com]: ").strip() \
                   or f"https://{region}.digitaloceanspaces.com"
        provider = "DigitalOcean"
    else:
        region = input("AWS region [eu-west-1]: ").strip() or "eu-west-1"
        endpoint = input(f"Endpoint [https://s3.{region}.amazonaws.com]: ").strip() \
                   or f"https://s3.{region}.amazonaws.com"
        provider = "AWS"

    info("Configuring rclone …")
    config_dir = Path("/root/.config/rclone")
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "rclone.conf"

    # Write config directly — no env vars, no rclone config create CLI.
    # Plain-text secret_access_key is safe with 0600 perms.
    header = "[do]\n"
    body = (
        f"type = s3\n"
        f"provider = {provider}\n"
        f"env_auth = false\n"
        f"access_key_id = {access_key}\n"
        f"secret_access_key = {secret_key}\n"
        f"region = {region}\n"
        f"endpoint = {endpoint}\n"
        f"acl = private\n"
    )
    config_file.write_text(header + body, encoding="utf-8")
    config_file.chmod(0o600)
    info(f"rclone config written: {config_file} (remote: do, bucket: {bucket_name})")

    # Test connection: list the configured bucket on the remote.
    test_path = f"do:{bucket_name}"
    test_cmd = ["rclone", "lsd", test_path]
    info(f"Testing: {' '.join(test_cmd)}")
    r = run(test_cmd, check=False)
    if r.returncode == 0:
        ok(f"Remote do: (bucket {bucket_name}) is accessible")
        for line in _safe_lines(r.stdout):
            print(f"  {line}")
        if confirm("Enable upload and run test backup?"):
            _enable_upload()
    else:
        err_msg = _safe_text(r.stderr)
        warn(f"Remote do: (bucket {bucket_name}) not accessible")
        warn(f"Error: {err_msg[:200]}")


def _enable_upload():
    env_file = Path("/etc/greenbone-backup/greenbone-backup.env")
    if env_file.exists():
        text = env_file.read_text().replace("GREENBONE_BACKUP_UPLOAD=0",
                                             "GREENBONE_BACKUP_UPLOAD=1")
        env_file.write_text(text)
        ok("Upload enabled in config")
    else:
        warn("Env file not found, enable manually in /etc/greenbone-backup/greenbone-backup.env")


def _install_timeshift():
    if shutil.which("timeshift"):
        ok("Timeshift already installed")
        return
    info("Installing Timeshift …")
    run(["apt-get", "install", "-y", "-qq", "timeshift"], check=False)
    if shutil.which("timeshift"):
        # Configure
        for dev in ("/dev/vda1", "/dev/sda1", "/dev/nvme0n1p1"):
            if Path(dev).exists():
                run(["timeshift", "--rsync"], check=False)
                run(["timeshift", "--snapshot-device", dev], check=False)
                ok(f"Timeshift configured (RSYNC, device {dev})")
                break
        if confirm("Create initial snapshot now?"):
            run(["timeshift", "--create", "--comments", "initial"])
            ok("Initial snapshot created")
    else:
        warn("Timeshift installation failed, install manually: apt-get install timeshift")


# ── 4. RESTORE ─────────────────────────────────────────────────────────

def do_restore():
    print()
    print("  Restore Greenbone from backup")
    print("  1) From local archive")
    print("  2) From DO Spaces cloud")
    print("  3) Manual (I do it myself)")
    print("  0) Back")
    a = input("Choice [0-3]: ").strip()
    if a == "1":
        p = input("Archive path: ").strip()
        if Path(p).exists():
            run(["tar", "-xzf", p, "-C", "/"])
            ok("Archive extracted")
        else:
            fail("File not found")
    elif a == "2":
        if not shutil.which("rclone"):
            fail("rclone not installed — cannot restore from cloud")
            return
        # Discover Greenbone backup paths on configured rclone remotes
        remotes_r = run(["rclone", "listremotes"], capture=True, check=False)
        if remotes_r.returncode != 0 or not remotes_r.stdout.strip():
            fail("No rclone remotes configured")
            return
        remotes = [r.strip().rstrip(":") for r in remotes_r.stdout.strip().splitlines() if r.strip()]
        choices = []
        for rm in remotes:
            # Try to list top-level directories (buckets / spaces) on this remote
            top_r = run(["rclone", "lsd", f"{rm}:"], capture=True, check=False)
            bucket_candidates = []
            if top_r.returncode == 0:
                for line in top_r.stdout.strip().splitlines():
                    parts = line.split()
                    if parts:
                        bucket_candidates.append(parts[-1])
            else:
                # lsd on root failed (e.g. 403 AccessDenied — no ListBuckets permission).
                # Try common bucket paths and ask user if needed.
                for guess in ["greenbone-backups", "testmonbck"]:
                    probe = run(["rclone", "lsd", f"{rm}:{guess}"], capture=True, check=False)
                    if probe.returncode == 0:
                        # Found a valid bucket — use it to discover backup paths
                        bucket_candidates.append(guess)
                        break
                if not bucket_candidates:
                    # Ask user for the bucket/space name
                    info("Remote is configured but no buckets were detected automatically.")
                    bucket = input(f"Enter bucket/space name for remote '{rm}' (or leave empty to skip): ").strip()
                    if bucket:
                        bucket_candidates.append(bucket)

            # For each bucket, look for greenbone-backups/ inside
            for bucket in bucket_candidates:
                ls_r = run(["rclone", "lsd", f"{rm}:{bucket}/greenbone-backups"], capture=True, check=False)
                if ls_r.returncode != 0:
                    continue
                for line in ls_r.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 1:
                        name = parts[-1]
                        path = f"{rm}:{bucket}/greenbone-backups/{name}"
                        label = f"{rm}:{bucket}/greenbone-backups/{name}"
                        choices.append((path, label))
            # Also probe without bucket: remote:greenbone-backups/
            ls_r = run(["rclone", "lsd", f"{rm}:greenbone-backups"], capture=True, check=False)
            if ls_r.returncode == 0:
                for line in ls_r.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 1:
                        name = parts[-1]
                        path = f"{rm}:greenbone-backups/{name}"
                        label = f"{rm}:greenbone-backups/{name}"
                        choices.append((path, label))
        if not choices:
            fail("No Greenbone backup directories found on any rclone remote")
            info("Verify that a 'greenbone-backups' directory exists in the configured bucket.")
            info("Check the bucket/space name in your DO Spaces account.")
            return
        print("\nGreenbone backup locations found:")
        for i, (path, label) in enumerate(choices, 1):
            print(f"  {i}) {label}")
        print(f"  0) Cancel")
        pick = input(f"\nSelect [1-{len(choices)}]: ").strip()
        if not pick.isdigit() or int(pick) < 1 or int(pick) > len(choices):
            info("Restore cancelled")
            return
        remote_path = choices[int(pick) - 1][0]
        dest = input("Local restore directory [/tmp/restore]: ").strip() or "/tmp/restore"
        if Path(dest).exists():
            if not confirm(f"Directory {dest} exists. Continue?"):
                return
        info(f"Listing contents of {remote_path} ...")
        r = run(["rclone", "lsf", remote_path], capture=True, check=False)
        if r.returncode != 0:
            fail(f"Cannot list {remote_path} — check rclone config and remote path")
            return
        print(r.stdout)
        if confirm(f"Copy all backups from {remote_path} to {dest}?"):
            Path(dest).mkdir(parents=True, exist_ok=True)
            run(["rclone", "copy", "--progress", remote_path, dest], live=True)
            ok(f"Backups downloaded to {dest}")
        else:
            info("Download skipped. Archives may already be present in " + dest)

        # ── Full restore (extract + database + volumes) ──────────────
        archives = sorted(Path(dest).glob("greenbone-full-*.tar.gz"))
        if not archives:
            info("No full backup archives found in " + dest)
            info("Extract manually: tar -xzf <archive> -C /tmp/restore")
            return
        info(f"Found {len(archives)} backup archive(s) in {dest}")
        for a in archives:
            print(f"  {a.name}  ({a.stat().st_size / 1024 / 1024:.0f} MB)")
        if not confirm("Extract and restore the downloaded backup?"):
            info("Restore cancelled after download.")
            return

        compose_file = Path("/opt/greenbone-community/compose.yaml")
        if not compose_file.exists():
            warn("Compose file not found at /opt/greenbone-community/compose.yaml")
            warn("Cannot restore database automatically — extract the archives manually.")
            return

        # Check if Greenbone containers are running
        ps_r = run(["docker", "compose", "-f", str(compose_file), "ps", "--all"],
                   capture=True, check=False)
        running_containers = sum(1 for ln in ps_r.stdout.splitlines() if "Up" in ln) if ps_r.returncode == 0 else 0
        if running_containers > 0:
            warn(f"{running_containers} Greenbone container(s) are currently running.")
            if not confirm("Stop containers and overwrite data?"):
                info("Restore cancelled. Archives are in " + dest)
                return

        # Stop the stack before restore
        info("Stopping Greenbone stack ...")
        run(["docker", "compose", "-f", str(compose_file), "down"], live=True, check=False)
        ok("Stack stopped")

        for archive in archives:
            info(f"Processing: {archive.name}")

            # Extract
            extract_dir = Path(dest) / archive.name.replace(".tar.gz", ".extracted")
            extract_dir.mkdir(parents=True, exist_ok=True)
            run(["tar", "-xzf", str(archive), "-C", str(extract_dir)], live=True, check=False)
            ok(f"Extracted: {archive.name}")

            # Restore database
            for sql_file in extract_dir.rglob("*.sql"):
                info(f"Found database dump: {sql_file.name}")
                if confirm("Restore PostgreSQL database?"):
                    # Start only pg-gvm for restore
                    run(["docker", "compose", "-f", str(compose_file), "up", "-d", "pg-gvm"],
                        live=True, check=False)
                    # Wait for pg-gvm to be ready
                    import time
                    for attempt in range(12):
                        pg_r = run(["docker", "compose", "-f", str(compose_file),
                                    "exec", "-T", "pg-gvm", "pg_isready", "-U", "gvmd"],
                                   capture=True, check=False)
                        if pg_r.returncode == 0:
                            break
                        time.sleep(5)
                    # Restore via psql
                    sql_text = sql_file.read_text(encoding="utf-8")
                    run(["docker", "compose", "-f", str(compose_file),
                         "exec", "-T", "pg-gvm", "psql", "-U", "gvmd", "-d", "gvmd"],
                        input=sql_text, live=True, check=False)
                    ok("Database restored")
                break  # only first .sql file

            # Restore Docker volumes from tar inside archive
            for vol_tar in extract_dir.glob("*.tar.gz"):
                vol_name = vol_tar.stem.replace(".tar", "")
                info(f"Found volume archive: {vol_name}")
                if confirm(f"Restore volume '{vol_name}'?"):
                    run(["docker", "run", "--rm",
                         "-v", f"{vol_name}:/volume",
                         "-v", f"{vol_tar}:/backup/archive.tar.gz:ro",
                         "busybox:latest",
                         "tar", "xzf", "/backup/archive.tar.gz", "-C", "/volume"],
                        live=True, check=False)
                    ok(f"Volume {vol_name} restored")

        # Start the stack
        if confirm("Start the Greenbone stack now?"):
            info("Starting Greenbone stack ...")
            run(["docker", "compose", "-f", str(compose_file), "up", "-d"], live=True, check=False)
            # Wait for gvmd to be running (dependencies may take time)
            info("Waiting for gvmd to be ready ...")
            import time
            for attempt in range(30):
                st_r = run(["docker", "compose", "-f", str(compose_file), "ps",
                            "--format", "{{.State}}", "gvmd"], capture=True, check=False)
                state = st_r.stdout.strip() if st_r.returncode == 0 else ""
                if state == "running":
                    ok("gvmd is running")
                    break
                time.sleep(4)
            else:
                warn(f"gvmd state after 120s: '{state}' — not fully running yet.")
                warn("Run menu option 6 to check stack status later.")
            ok("Greenbone stack started")
            info("Run menu option 6 to verify stack status.")

        ok("Restore completed")
    else:
        return


# ── MANAGEMENT ─────────────────────────────────────────────────────────

def run_mode(mode: str, *args):
    """Run a deploy sub-command using local deploy-greenbone.sh."""
    script = Path(__file__).resolve().parent / "install" / "deploy-greenbone.sh"
    if not script.exists():
        fail(f"Local deploy script not found: {script}")
        return
    cmd = [str(script), mode] + list(args) + ["--project-dir", "/opt/greenbone-community"]
    info(f"Running: {' '.join(cmd)}")
    r = run(cmd, live=True)
    if r.returncode != 0:
        fail(f"Command failed (exit {r.returncode})")


# ── MENU ────────────────────────────────────────────────────────────────

def header(title):
    print(f"\n── {title} {'─' * (50 - len(title) - 4)}\n")


def menu():
    while True:
        os.system("clear 2>/dev/null || cls 2>/dev/null || true")
        print(f"""
╔══════════════════════════════════════════════╗
║      GREENBONE INSTALLER v{VERSION}          ║
╠══════════════════════════════════════════════╣
║  1) Full install (host + deploy + backup)   ║
║  2) Setup host only                         ║
║  3) Deploy Greenbone only                   ║
║  4) Install backup system                   ║
║  5) Restore from backup                     ║
║  6) Stack status                            ║
║  7) Update feed data                        ║
║  8) Change admin password                   ║
║  9) System audit                            ║
║  0) Exit                                    ║
╚══════════════════════════════════════════════╝
""")
        a = input("Select [0-9]: ").strip()
        if a == "1":    setup_host();          print(); deploy();        print(); install_backup()
        elif a == "2":  setup_host()
        elif a == "3":  deploy()
        elif a == "4":  install_backup()
        elif a == "5":  do_restore()
        elif a == "6":  run_mode("status")
        elif a == "7":  run_mode("update-feed", "--feed-update-confirmed", "--non-interactive") if confirm("Pull updated feed images?") else None
        elif a == "8":  run_mode("change-admin-password")
        elif a == "9":  run_mode("audit")
        elif a == "0":  ok("Bye."); break
        input("\nPress Enter …")


# ── MAIN ───────────────────────────────────────────────────────────────

def main():
    # Ensure CWD is valid for the entire process lifetime.
    # setup_host() may delete the original working directory,
    # causing fatal errors in subprocess calls and input().
    try:
        os.chdir("/")
    except OSError:
        pass

    parser = argparse.ArgumentParser(description="Greenbone installer v" + VERSION)
    parser.add_argument("mode", nargs="?", default="menu",
                        choices=["setup-host", "deploy", "install-backup", "restore",
                                 "status", "update-feed", "change-password", "audit", "menu"],
                        help="Operation mode (default: interactive menu)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip all confirmation prompts (for automation)")
    args = parser.parse_args()
    ni = args.non_interactive

    modes = {
        "setup-host": lambda: setup_host() if not ni else (check_root(), setup_host()),
        "deploy": lambda: deploy(non_interactive=ni),
        "install-backup": install_backup,
        "restore": do_restore,
        "status": lambda: run_mode("status"),
        "update-feed": lambda: run_mode("update-feed", "--feed-update-confirmed", "--non-interactive"),
        "change-password": lambda: run_mode("change-admin-password"),
        "audit": lambda: run_mode("audit"),
    }
    if args.mode == "menu":
        menu()
    else:
        modes[args.mode]()


if __name__ == "__main__":
    main()
