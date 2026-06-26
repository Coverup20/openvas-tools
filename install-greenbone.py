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

VERSION = "0.1.0"
RAW = "https://raw.githubusercontent.com/Coverup20/openvas-tools/feat/greenbone-deploy-mode"


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
    """Run a command, show output in real-time, return CompletedProcess."""
    kwargs.setdefault('text', True)
    # Default: show live output; set capture=True to suppress
    if not kwargs.pop('capture', False):
        return subprocess.run(cmd, **kwargs)
    kwargs['capture_output'] = True
    return subprocess.run(cmd, **kwargs)


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
        arch = run(["dpkg", "--print-architecture"]).stdout.strip() or "amd64"
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
    r = run(["docker", "--version"], check=False)
    return r.stdout.strip() if r.returncode == 0 else "NOT INSTALLED"


def _compose_version():
    r = run(["docker", "compose", "version"], check=False)
    return r.stdout.strip() if r.returncode == 0 else "NOT INSTALLED"


def _read_sysctl(key):
    r = run(["sysctl", "-n", key], check=False)
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

def deploy():
    check_root()
    if not confirm("Deploy Greenbone Community Containers?"):
        return
    script = download("install/deploy-greenbone.sh")
    info("Starting deployment …")
    r = run([script, "deploy", "--deploy-confirmed", "--non-interactive",
             "--project-dir", "/opt/greenbone-community"], capture=True)
    os.unlink(script)
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
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + ":" + env.get("PYTHONPATH", "")
    r = run([sys.executable, str(local_script), "--install"], env=env)
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
    """Interactive DO Spaces configuration."""
    print()
    info("DigitalOcean Spaces backup configuration")
    print("(leave empty to skip)")
    print()

    remote = input("Remote type (do/aws) [do]: ").strip() or "do"
    if remote not in ("do", "aws"):
        warn("Invalid remote type, skipping")
        return

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

    # Configure rclone — pass credentials via environment variables
    # instead of CLI arguments to avoid exposing secrets in process list.
    info("Configuring rclone …")
    config_dir = Path("/root/.config/rclone")
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "rclone.conf"

    remote_upper = "DO"
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(config_file)
    env[f"RCLONE_CONFIG_{remote_upper}_ACCESS_KEY_ID"] = access_key
    env[f"RCLONE_CONFIG_{remote_upper}_SECRET_ACCESS_KEY"] = secret_key

    r = run(["rclone", "config", "create", "do", "s3",
             f"provider={provider}",
             "env_auth=false",
             f"region={region}",
             f"endpoint={endpoint}",
             "acl=private",
             "--obscure"],
            env=env, check=False)
    if r.returncode != 0:
        warn(f"Rclone config failed: {r.stderr.strip()}")
        return

    # Test
    r2 = run(["rclone", "lsd", "do:testmonbck"], env=env, check=False)
    if r2.returncode == 0:
        ok("DO Spaces connection OK")
        # Enable upload
        if confirm("Enable upload and run test backup?"):
            _enable_upload()
    else:
        warn(f"Connection test failed: {r2.stderr.strip()}")
        warn("Check credentials and bucket name, then run: rclone config")


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
        info("Run: rclone copy do:testmonbck/greenbone-backups/ /tmp/restore/")
    else:
        return


# ── MANAGEMENT ─────────────────────────────────────────────────────────

def run_mode(mode: str, *args):
    """Run a deploy sub-command via downloaded deploy-greenbone.sh."""
    script = download("install/deploy-greenbone.sh")
    cmd = [script, mode] + list(args) + ["--project-dir", "/opt/greenbone-community"]
    info(f"Running: {' '.join(cmd)}")
    r = run(cmd, capture=True)
    os.unlink(script)
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
    parser = argparse.ArgumentParser(description="Greenbone installer v" + VERSION)
    parser.add_argument("mode", nargs="?", default="menu",
                        choices=["setup-host", "deploy", "install-backup", "restore",
                                 "status", "update-feed", "change-password", "audit", "menu"],
                        help="Operation mode (default: interactive menu)")
    args = parser.parse_args()

    modes = {
        "setup-host": setup_host,
        "deploy": deploy,
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
