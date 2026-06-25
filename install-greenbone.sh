#!/usr/bin/env bash
#
# install-greenbone.sh — Greenbone installer, manager and DR tool
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Coverup20/openvas-tools/feat/greenbone-deploy-mode/install-greenbone.sh | bash
#   bash install-greenbone.sh              ← interactive menu
#   bash install-greenbone.sh deploy       ← non-interactive mode
#
# Fully self-contained. On-board tools (apt, docker) are installed locally.
# Complex sub-scripts (deploy, backup) are fetched via curl at runtime.
# No local repository required.

set -Eeuo pipefail
VERSION="1.0.0"
RAW="https://raw.githubusercontent.com/Coverup20/openvas-tools/feat/greenbone-deploy-mode"

info()  { echo -e "\e[1;34m[INFO]\e[0m  $*"; }
ok()    { echo -e "\e[1;32m[ OK ]\e[0m  $*"; }
warn()  { echo -e "\e[1;33m[WARN]\e[0m  $*" >&2; }
fail()  { echo -e "\e[1;31m[FAIL]\e[0m  $*" >&2; }
hr()    { echo "──────────────────────────────────────────────────────"; }
confirm() { local a; echo -n "$1 [y/N] "; read -r a; [[ "$a" =~ ^[yY] ]]; }

# ── Download a sub‑script from GitHub via curl ─────────────────────────
fetch() {
    local path="$1"
    local tmp; tmp=$(mktemp)
    if curl -fsSL "$RAW/$path" -o "$tmp" 2>/dev/null; then
        chmod +x "$tmp"
        echo "$tmp"
        return 0
    fi
    rm -f "$tmp"
    return 1
}

# ── 1. SETUP HOST (self‑contained, no external deps) ───────────────────
setup_host() {
    hr
    echo "  1/6  OS … $(. /etc/os-release 2>/dev/null && echo "$ID $VERSION_ID" || uname -s)"
    echo "  2/6  Docker … $(docker --version 2>/dev/null || echo 'NOT INSTALLED')"
    echo "  3/6  Compose … $(docker compose version 2>/dev/null || echo 'NOT INSTALLED')"
    echo "  4/6  Kernel … vm.max_map_count = $(cat /proc/sys/vm/max_map_count 2>/dev/null || echo ?)"
    echo "  5/6  Swap … $(free -h | awk '/^Swap:/{print $2}')"
    echo "  6/6  User greenbone … $(id greenbone 2>/dev/null && echo 'exists' || echo 'missing')"
    hr
    confirm "Proceed with host setup?" || { info "Skipped."; return 0; }

    info "Installing system packages …"
    apt-get update -qq && apt-get install -y -qq ca-certificates curl gnupg git openssh-server qemu-guest-agent

    if ! docker --version &>/dev/null; then
        info "Installing Docker …"
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture 2>/dev/null || echo amd64) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
        apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        systemctl enable --now docker
    fi
    ok "Docker $(docker --version)"
    ok "Compose $(docker compose version)"

    if [ "$(cat /proc/sys/vm/max_map_count 2>/dev/null || echo 0)" -lt 262144 ]; then
        echo "vm.max_map_count = 262144" > /etc/sysctl.d/99-greenbone.conf
        sysctl -p /etc/sysctl.d/99-greenbone.conf && ok "Kernel parameters set"
    fi
    if [ "$(free -m | awk '/^Swap:/{print $2}')" -lt 1024 ]; then
        dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
        chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile >/dev/null
        echo "/swapfile none swap sw 0 0" >> /etc/fstab && ok "Swap 4G created"
    fi
    if ! id greenbone &>/dev/null; then
        adduser --gecos "" --disabled-password greenbone
        usermod -aG sudo greenbone && ok "User greenbone created"
    fi
    mkdir -p /etc/ssh/sshd_config.d
    echo "PermitRootLogin yes" > /etc/ssh/sshd_config.d/99-root-login.conf
    systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true
    systemctl enable --now ssh 2>/dev/null || true
    ok "Root SSH login enabled"
    ok "Host setup finished"
}

# ── 2. DEPLOY ──────────────────────────────────────────────────────────
deploy_stack() {
    local s
    s=$(fetch "install/deploy-greenbone.sh") || { fail "Cannot download deploy-greenbone.sh"; return 1; }
    confirm "Deploy Greenbone Community Containers?" || return 0
    "$s" deploy --deploy-confirmed --non-interactive --project-dir /opt/greenbone-community
    rm -f "$s"
}

# ── 3. INSTALL BACKUP ──────────────────────────────────────────────────
install_backup() {
    local s
    s=$(fetch "install/install-backup.sh") || { fail "Cannot download install-backup.sh"; return 1; }
    confirm "Install backup system?" || return 0
    bash "$s"
    rm -f "$s"
}

# ── 4. RESTORE ─────────────────────────────────────────────────────────
do_restore() {
    hr; echo "  Restore Greenbone from backup"; hr
    echo "  1) From local archive"
    echo "  2) From Do Spaces cloud"
    echo "  3) Manual steps"
    echo "  0) Back"; hr
    read -r -p "Choice [0-3]: " a
    case "$a" in
        1) read -r -p "Archive path: " p; [ -f "$p" ] && tar -xzf "$p" -C / || fail "Not found" ;;
        2) info "Run: rclone copy do:testmonbck/greenbone-backups/ /tmp/restore/" ;;
        3|0) return ;;
    esac
}

# ── MANAGEMENT (deploy sub‑commands via curl) ──────────────────────────
run_mode() {
    local mode="$1"; shift
    local s
    s=$(fetch "install/deploy-greenbone.sh") || { fail "Cannot download deploy-greenbone.sh"; return 1; }
    "$s" "$mode" "$@"
    rm -f "$s"
}

# ── MENU ────────────────────────────────────────────────────────────────
menu() {
    while true; do
        clear 2>/dev/null || true
        echo ""; hr
        echo "  GREENBONE INSTALLER v$VERSION"
        hr
        echo "  1) Full install (host setup + deploy + backup)"
        echo "  2) Setup host only (Docker, OS config)"
        echo "  3) Deploy Greenbone only"
        echo "  4) Install backup system"
        echo "  5) Restore from backup"
        echo "  6) Stack status"
        echo "  7) Update feed data"
        echo "  8) Change admin password"
        echo "  9) System audit"
        echo "  0) Exit"
        hr
        read -r -p "Select [0-9]: " a
        case "$a" in
            1) setup_host;   echo; deploy_stack;   echo; install_backup ;;
            2) setup_host ;;
            3) deploy_stack ;;
            4) install_backup ;;
            5) do_restore ;;
            6) run_mode status --project-dir /opt/greenbone-community ;;
            7) confirm "Pull updated feed images?" && run_mode update-feed --feed-update-confirmed --non-interactive --project-dir /opt/greenbone-community ;;
            8) run_mode change-admin-password --project-dir /opt/greenbone-community ;;
            9) run_mode audit --project-dir /opt/greenbone-community ;;
            0) ok "Bye."; exit 0 ;;
        esac
        echo; echo -n "Press Enter …"; read -r
    done
}

# ── MAIN ────────────────────────────────────────────────────────────────
main() {
    case "${1:-}" in
        --help|-h)     echo "install-greenbone.sh v$VERSION — modes: setup-host, deploy, install-backup, restore, status, update-feed, change-password, audit"; exit 0 ;;
        --version|-V)  echo "v$VERSION"; exit 0 ;;
        setup-host)    setup_host ;;
        deploy)        deploy_stack ;;
        install-backup) install_backup ;;
        restore)       do_restore ;;
        status)        run_mode status --project-dir /opt/greenbone-community ;;
        update-feed)   run_mode update-feed --feed-update-confirmed --non-interactive --project-dir /opt/greenbone-community ;;
        change-password) run_mode change-admin-password --project-dir /opt/greenbone-community ;;
        audit)         run_mode audit --project-dir /opt/greenbone-community ;;
        "")            menu ;;
        *)             fail "Unknown mode: $1"; exit 1 ;;
    esac
}

main "$@"
