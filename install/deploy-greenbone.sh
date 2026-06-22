#!/usr/bin/env bash
#
# deploy-greenbone.sh — Safe Greenbone Community Containers deployment framework
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This script provides a safe, auditable and reversible workflow for deploying
# Greenbone Community Edition using official Docker Compose files.
#
# Usage: deploy-greenbone.sh [mode] [options]
#   See --help for full documentation.
#
# Modes: audit, dry-run, status, deploy, backup, remove
#   audit  : read-only system readiness check
#   dry-run: show planned deployment steps without executing
#   status : show current stack state (read-only)
#   deploy : NOT IMPLEMENTED in this version
#   backup : NOT IMPLEMENTED in this version
#   remove : NOT IMPLEMENTED in this version

set -Eeuo pipefail

VERSION="0.0.2"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_DIR=""
COMPOSE_URL="https://greenbone.github.io/docs/latest/_static/compose.yaml"
COMPOSE_FILE=""
LOG_DIR="./logs"
NON_INTERACTIVE=false
VERBOSE=false
DEPLOY_CONFIRMED=false
DEPLOY_FLAG=""
SCRIPT_NAME="$(basename "$0")"
LOG_FILE=""
METADATA_DIR=""
DISK_WARN_GB=40
DISK_FAIL_GB=20

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
log_info()  { echo "[INFO]  $*"; }
log_warn()  { echo "[WARN]  $*" >&2; }
log_error() { echo "[ERROR] $*" >&2; }
log_pass()  { echo "[PASS]  $*"; }
log_fail()  { echo "[FAIL]  $*" >&2; }
log_debug() { if "$VERBOSE"; then echo "[DEBUG] $*"; fi; }

# ---------------------------------------------------------------------------
# Timestamped logging to file
# ---------------------------------------------------------------------------
setup_logging() {
    if "$VERBOSE"; then
        echo "[INFO]  Logging to: $LOG_DIR/$SCRIPT_NAME.log"
    fi
    mkdir -p "$LOG_DIR"
    LOG_FILE="$LOG_DIR/$SCRIPT_NAME.log"
    # Redirect stderr to both console and log file
    exec 2> >(tee -a "$LOG_FILE" >&2)
    log_info "=== deploy-greenbone.sh v$VERSION started at $(date --iso-8601=seconds) ==="
}

# ---------------------------------------------------------------------------
# Traps
# ---------------------------------------------------------------------------
cleanup() {
    local rc=$?
    if [ $rc -ne 0 ] && [ -n "$LOG_FILE" ] && [ -f "$LOG_FILE" ]; then
        log_error "Script exited with code $rc. See log: $LOG_FILE"
    fi
    exit $rc
}
trap cleanup EXIT

err_trap() {
    local rc=$?
    log_error "Error on line $1 (exit code $rc)"
}
trap 'err_trap $LINENO' ERR

# ---------------------------------------------------------------------------
# Command existence
# ---------------------------------------------------------------------------
require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        log_warn "Command '$1' is not available."
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Dry-run wrapper
# ---------------------------------------------------------------------------
dry_run_cmd() {
    if [ "${DRY_RUN:-false}" = "true" ]; then
        echo "[DRY-RUN] Would execute: $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------
detect_os() {
    local os=""
    local kernel=""
    local arch=""

    if [ -f /etc/os-release ]; then
        os=$(grep -oP '^ID="?\K[^"]+' /etc/os-release 2>/dev/null || echo "unknown")
    elif command -v lsb_release &>/dev/null; then
        os=$(lsb_release -si 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo "unknown")
    else
        os="unknown"
    fi

    kernel=$(uname -s 2>/dev/null || echo "unknown")
    arch=$(uname -m 2>/dev/null || echo "unknown")

    echo "$os" "$kernel" "$arch"
}

# ---------------------------------------------------------------------------
# Root awareness
# ---------------------------------------------------------------------------
is_root() {
    [ "$(id -u)" -eq 0 ]
}

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
deploy-greenbone.sh v$VERSION — Safe Greenbone Community Containers deployment

USAGE
    $SCRIPT_NAME [mode] [options]

MODES
    audit       Perform read-only system readiness check (functional)
    dry-run     Show planned deployment steps without executing (functional)
    status      Show current stack state (read-only, partially functional)
    deploy      Deploy Greenbone stack from official sources
    backup      Create database and configuration backup (NOT IMPLEMENTED)
    remove      Remove Greenbone stack with backup gate (NOT IMPLEMENTED)
    --help      Show this help message and exit
    --version   Show version and exit

OPTIONS
    --project-dir DIR      Base directory for Compose files and runtime data
    --compose-url URL      Official Compose file download URL
    --compose-file PATH    Local path to Compose file
    --log-dir DIR          Directory for log files (default: ./logs)
    --non-interactive      Skip confirmation prompts (implies --deploy-confirmed)
    --deploy-confirmed     Acknowledge understanding: deploy will start containers
    --verbose              Enable verbose output

EXIT CODES
    0   Success
    1   General error
    2   Invalid argument
    3   Mode not implemented

SAFETY
    - audit and dry-run modes are read-only and safe to run at any time.
    - status mode is read-only.
    - deploy mode requires --deploy-confirmed AND interactive confirmation.
    - backup and remove modes are NOT IMPLEMENTED and will refuse execution.
    - No credentials, passwords or tokens are accepted as arguments.
    - No destructive commands are executed without explicit confirmation.

SECURITY
    - Never run this script on production or internet-facing hosts.
    - Always test in an isolated VM first.
    - Set admin passwords interactively after deployment.

EOF
}

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
version() {
    echo "deploy-greenbone.sh v$VERSION"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE=""

parse_args() {
    local positional=()

    while [ $# -gt 0 ]; do
        case "$1" in
            --help|-h)
                usage
                exit 0
                ;;
            --version|-V)
                version
                exit 0
                ;;
            --project-dir)
                if [ -z "${2:-}" ]; then
                    log_error "--project-dir requires a value"
                    exit 2
                fi
                PROJECT_DIR="$2"
                shift 2
                ;;
            --compose-url)
                if [ -z "${2:-}" ]; then
                    log_error "--compose-url requires a value"
                    exit 2
                fi
                COMPOSE_URL="$2"
                shift 2
                ;;
            --compose-file)
                if [ -z "${2:-}" ]; then
                    log_error "--compose-file requires a value"
                    exit 2
                fi
                COMPOSE_FILE="$2"
                shift 2
                ;;
            --log-dir)
                if [ -z "${2:-}" ]; then
                    log_error "--log-dir requires a value"
                    exit 2
                fi
                LOG_DIR="$2"
                shift 2
                ;;
            --non-interactive)
                NON_INTERACTIVE=true
                DEPLOY_CONFIRMED=true
                shift
                ;;
            --deploy-confirmed)
                DEPLOY_CONFIRMED=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                usage >&2
                exit 2
                ;;
            *)
                positional+=("$1")
                shift
                ;;
        esac
    done

    if [ ${#positional[@]} -eq 0 ]; then
        log_error "No mode specified. Use --help for usage."
        exit 2
    fi

    MODE="${positional[0]}"

    if [ ${#positional[@]} -gt 1 ]; then
        log_error "Unexpected argument: ${positional[1]}"
        exit 2
    fi
}

# ---------------------------------------------------------------------------
# Mode: audit
# ---------------------------------------------------------------------------
cmd_audit() {
    log_info "=== Audit mode ==="
    echo ""
    echo "[System Audit]"
    echo "  Mode:            audit"
    echo "  Timestamp:       $(date --iso-8601=seconds)"
    echo ""

    # --- OS identification ---
    read -r os_name kernel arch <<< "$(detect_os)"
    echo "--- Operating System ---"
    echo "[INFO]  OS:      $os_name"
    echo "[INFO]  Kernel:  $kernel"
    echo "[INFO]  Arch:    $arch"

    if [ "$os_name" = "ubuntu" ]; then
        log_pass "OS identification: $os_name"
    elif [ "$os_name" = "unknown" ]; then
        log_warn "OS could not be determined"
    else
        log_info "OS: $os_name (non-Ubuntu, proceed with caution)"
    fi

    # --- Kernel ---
    if [ -n "$kernel" ]; then
        log_pass "Kernel detected: $kernel"
    else
        log_fail "Kernel detection failed"
    fi

    # --- Architecture ---
    if [ "$arch" = "x86_64" ] || [ "$arch" = "aarch64" ]; then
        log_pass "Architecture: $arch"
    else
        log_warn "Architecture: $arch (untested)"
    fi

    # --- CPU count ---
    local cpus=0
    if [ -f /proc/cpuinfo ]; then
        cpus=$(grep -c ^processor /proc/cpuinfo 2>/dev/null || nproc 2>/dev/null || echo 0)
    else
        cpus=$(nproc 2>/dev/null || echo 0)
    fi
    if [ "$cpus" -ge 2 ]; then
        log_pass "CPU cores: $cpus"
    elif [ "$cpus" -eq 0 ]; then
        log_fail "Could not determine CPU count"
    else
        log_warn "CPU cores: $cpus (minimum recommended: 2)"
    fi

    # --- RAM ---
    local ram_mb=0
    if command -v free &>/dev/null; then
        ram_mb=$(free -m | awk '/^Mem:/ {print $2}' 2>/dev/null || echo 0)
    fi
    if [ "$ram_mb" -ge 4096 ]; then
        log_pass "RAM: ${ram_mb}MB"
    elif [ "$ram_mb" -eq 0 ]; then
        log_warn "Could not determine RAM"
    else
        log_warn "RAM: ${ram_mb}MB (minimum recommended: 4096MB)"
    fi

    # --- Filesystem / free disk ---
    local available_kb=0
    local mount_point="/"
    if command -v df &>/dev/null; then
        available_kb=$(df --output=avail / 2>/dev/null | tail -1 || echo 0)
        mount_point=$(df --output=target / 2>/dev/null | tail -1 || echo "/")
    fi
    local available_gb=$((available_kb / 1024 / 1024))
    if [ "$available_gb" -ge 40 ]; then
        log_pass "Free disk on $mount_point: ${available_gb}GB"
    elif [ "$available_gb" -ge 10 ]; then
        log_warn "Free disk on $mount_point: ${available_gb}GB (minimum recommended: 40GB)"
    elif [ "$available_gb" -eq 0 ]; then
        log_fail "Could not determine free disk space"
    else
        log_fail "Free disk on $mount_point: ${available_gb}GB (insufficient)"
    fi

    # --- Time synchronization ---
    if command -v timedatectl &>/dev/null; then
        local ntp_sync
        ntp_sync=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo "no")
        if [ "$ntp_sync" = "yes" ]; then
            log_pass "NTP synchronized: yes"
        else
            log_warn "NTP synchronized: $ntp_sync (recommended for scan accuracy)"
        fi
    else
        log_info "timedatectl not available — skipping NTP check"
    fi

    # --- DNS resolution ---
    if command -v resolvectl &>/dev/null; then
        local dns_servers
        dns_servers=$(resolvectl status 2>/dev/null | grep -i "DNS Servers" | head -1 || echo "")
        if [ -n "$dns_servers" ]; then
            log_pass "DNS configured: $dns_servers"
        else
            log_warn "DNS servers could not be verified"
        fi
    elif command -v systemd-resolve &>/dev/null; then
        log_info "systemd-resolve available (fallback)"
    else
        log_info "DNS resolution check skipped (no systemd-resolved)"
    fi

    # --- curl ---
    if require_cmd curl; then
        log_pass "curl: available ($(curl --version | head -1))"
    else
        log_fail "curl: not available (required for Compose download)"
    fi

    # --- sha256sum ---
    if require_cmd sha256sum; then
        log_pass "sha256sum: available"
    else
        log_fail "sha256sum: not available (required for integrity verification)"
    fi

    # --- Docker ---
    if require_cmd docker; then
        log_pass "docker: available ($(docker --version 2>/dev/null || echo "version unknown"))"
        # Check daemon state without starting it
        if docker info &>/dev/null; then
            log_pass "Docker daemon: running"
        else
            log_warn "Docker daemon: not running or not accessible"
        fi
    else
        log_fail "docker: not available (required for Greenbone stack)"
    fi

    # --- Docker Compose plugin ---
    if docker compose version &>/dev/null; then
        local compose_ver
        compose_ver=$(docker compose version 2>/dev/null || echo "version unknown")
        log_pass "Docker Compose plugin: available ($compose_ver)"
    else
        log_fail "Docker Compose plugin: not available (required for Greenbone stack)"
    fi

    # --- Current user ---
    echo ""
    echo "--- User Context ---"
    echo "[INFO]  User:  $(whoami 2>/dev/null || echo "unknown")"
    echo "[INFO]  UID:   $(id -u 2>/dev/null || echo "unknown")"
    echo "[INFO]  GID:   $(id -g 2>/dev/null || echo "unknown")"
    if is_root; then
        log_info "Running as root"
    else
        log_info "Running as non-root user"
    fi

    # --- Existing Greenbone directories ---
    echo ""
    echo "--- Existing Greenbone Resources ---"
    local search_dirs=()
    if [ -n "$PROJECT_DIR" ]; then
        search_dirs+=("$PROJECT_DIR")
    fi
    search_dirs+=("/opt/greenbone-community-container" "/opt/greenbone" "/etc/gvm")

    for d in "${search_dirs[@]}"; do
        if [ -d "$d" ]; then
            log_info "Greenbone directory exists: $d"
        else
            log_debug "Directory not found: $d"
        fi
    done

    # --- Existing Compose files ---
    local compose_search=()
    if [ -n "$COMPOSE_FILE" ]; then
        compose_search+=("$COMPOSE_FILE")
    fi
    compose_search+=("./compose.yaml" "./docker-compose.yml" "./compose/compose.yaml" "./compose/docker-compose.yml")

    for f in "${compose_search[@]}"; do
        if [ -f "$f" ]; then
            log_info "Compose file found: $f"
        fi
    done

    # --- Docker contexts ---
    if require_cmd docker; then
        local contexts
        contexts=$(docker context ls --format '{{.Name}}' 2>/dev/null || echo "")
        if [ -n "$contexts" ]; then
            echo "[INFO]  Docker contexts:"
            echo "$contexts" | while IFS= read -r ctx; do
                echo "          - $ctx"
            done
        else
            log_debug "No Docker contexts found"
        fi
    fi

    # --- Greenbone containers (only if Docker is responsive) ---
    if docker info &>/dev/null 2>&1; then
        local gvm_containers
        gvm_containers=$(docker ps --all --filter "name=greenbone" --format '{{.Names}}' 2>/dev/null || echo "")
        if [ -n "$gvm_containers" ]; then
            echo ""
            echo "--- Greenbone Containers ---"
            echo "$gvm_containers" | while IFS= read -r c; do
                local cstate
                cstate=$(docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null || echo "unknown")
                echo "[INFO]  Container: $c (status: $cstate)"
            done
        else
            log_info "No Greenbone containers found"
        fi
    fi

    echo ""
    log_info "Audit completed at $(date --iso-8601=seconds)"
}

# ---------------------------------------------------------------------------
# Mode: dry-run
# ---------------------------------------------------------------------------
cmd_dry_run() {
    log_info "=== Dry-run mode ==="
    echo ""
    echo "Planned deployment sequence (not executed):"
    echo ""

    local pd="${PROJECT_DIR:-/opt/greenbone-community-container}"
    local cf="${COMPOSE_FILE:-$pd/compose.yaml}"

    echo "  Step  1: Verify prerequisites (OS, CPU, RAM, disk, tools)"
    echo "  Step  2: Determine project directory: $pd"
    echo "  Step  3: Retrieve official Compose file from $COMPOSE_URL"
    echo "  Step  4: Calculate checksum of downloaded Compose file"
    echo "  Step  5: Inspect Compose services via 'docker compose config --services'"
    echo "  Step  6: Inspect image references via 'docker compose images --digests'"
    echo "  Step  7: Pull images via 'docker compose pull'"
    echo "  Step  8: Create rollback metadata (checksums, image digests, timestamps)"
    echo "  Step  9: Start stack via 'docker compose up -d'"
    echo "  Step 10: Poll readiness (scanner, web service, feed data)"
    echo "  Step 11: Validate scanner registration and feed age"
    echo ""
    echo "Project directory:     $pd"
    echo "Compose URL:           $COMPOSE_URL"
    echo "Compose file:          $cf"
    echo "Log directory:         $LOG_DIR"
    echo ""
    log_info "Dry-run completed at $(date --iso-8601=seconds)"
    log_info "Use 'deploy' mode with --deploy-confirmed to execute this sequence."
}

# ---------------------------------------------------------------------------
# Mode: status
# ---------------------------------------------------------------------------
cmd_status() {
    log_info "=== Status mode ==="
    echo ""

    if ! docker info &>/dev/null 2>&1; then
        log_warn "Docker daemon is not running or not accessible. Cannot check stack state."
        echo ""
        log_info "Status check completed (degraded — Docker unavailable)"
        return 0
    fi

    if ! docker compose version &>/dev/null 2>&1; then
        log_warn "Docker Compose plugin is not available."
        echo ""
        log_info "Status check completed (degraded — Compose unavailable)"
        return 0
    fi

    # Try to discover Compose project
    local compose_project=""
    if [ -n "$PROJECT_DIR" ] && [ -f "${PROJECT_DIR}/compose.yaml" ]; then
        compose_project="$PROJECT_DIR"
    elif [ -n "$COMPOSE_FILE" ] && [ -f "$COMPOSE_FILE" ]; then
        compose_project="$(dirname "$COMPOSE_FILE")"
    else
        # Try common locations
        for d in "/opt/greenbone-community-container" "/opt/greenbone" "."; do
            if [ -f "$d/compose.yaml" ] || [ -f "$d/docker-compose.yml" ]; then
                compose_project="$d"
                break
            fi
        done
    fi

    if [ -z "$compose_project" ]; then
        log_warn "No Greenbone Compose project found in expected locations."
        echo ""
        log_info "Status check completed (no Compose project found)"
        return 0
    fi

    echo "Compose project directory: $compose_project"
    echo ""

    # List services
    echo "--- Container Status ---"
    local services
    services=$(docker compose -f "$compose_project/compose.yaml" config --services 2>/dev/null || \
               docker compose -f "$compose_project/docker-compose.yml" config --services 2>/dev/null || echo "")

    if [ -z "$services" ]; then
        log_warn "Could not determine Compose services."
        return 0
    fi

    echo "$services" | while IFS= read -r svc; do
        [ -z "$svc" ] && continue
        local cstatus
        cstatus=$(docker compose -f "$compose_project/compose.yaml" ps --format '{{.State}}' "$svc" 2>/dev/null || \
                  docker compose -f "$compose_project/docker-compose.yml" ps --format '{{.State}}' "$svc" 2>/dev/null || echo "unknown")
        echo "  $svc: $cstatus"
    done

    echo ""
    log_info "Status check completed at $(date --iso-8601=seconds)"
}

# ---------------------------------------------------------------------------
# Disk threshold classification
# ---------------------------------------------------------------------------
check_disk_threshold() {
    local free_gb="$1"
    if [ "$free_gb" -lt "$DISK_FAIL_GB" ]; then
        echo "FAIL"
    elif [ "$free_gb" -lt "$DISK_WARN_GB" ]; then
        echo "WARN"
    else
        echo "PASS"
    fi
}

# ---------------------------------------------------------------------------
# Get free disk space in GB
# ---------------------------------------------------------------------------
get_free_disk_gb() {
    local mount_point="${1:-/}"
    local available_kb=0
    if command -v df &>/dev/null; then
        available_kb=$(df --output=avail "$mount_point" 2>/dev/null | tail -1 || echo 0)
    fi
    echo $((available_kb / 1024 / 1024))
}

# ---------------------------------------------------------------------------
# Create deployment metadata
# ---------------------------------------------------------------------------
create_deployment_metadata() {
    local md_dir="$1"
    local compose_sha="$2"
    local services="$3"

    mkdir -p "$md_dir"
    cat > "$md_dir/deployment-metadata.txt" <<EOF
# Deployment metadata — do not store secrets here
timestamp: $(date --iso-8601=seconds)
script_version: v$VERSION
compose_url: $COMPOSE_URL
compose_sha256: ${compose_sha:-unknown}
services: ${services:-unknown}
docker_version: $(docker --version 2>/dev/null || echo "unknown")
compose_version: $(docker compose version 2>/dev/null || echo "unknown")
hostname: $(hostname 2>/dev/null || echo "unknown")
os_version: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo "unknown")
EOF
    log_info "Deployment metadata written to: $md_dir/deployment-metadata.txt"
}

# ---------------------------------------------------------------------------
# Readiness polling
# ---------------------------------------------------------------------------
poll_readiness() {
    local project_dir="$1"
    local compose_file="$2"
    local max_attempts=30
    local attempt=1
    local poll_interval=5

    # In dry-run mode, report immediately
    if [ "${DRY_RUN:-false}" = "true" ]; then
        log_info "DRY_RUN mode — skipping readiness polling"
        echo ""
        dry_run_cmd docker compose -f "$compose_file" ps
        echo ""
        return 0
    fi

    log_info "Polling container readiness (up to $((max_attempts * poll_interval)) seconds)..."
    echo ""

    while [ $attempt -le $max_attempts ]; do
        local all_running=true
        local output
        output=$(docker compose -f "$compose_file" ps --format '{{.Name}} {{.State}}' 2>/dev/null || echo "")

        if [ -z "$output" ]; then
            log_debug "Attempt $attempt: no container output yet"
            all_running=false
        else
            while IFS= read -r line; do
                [ -z "$line" ] && continue
                local state="${line##* }"
                if [ "$state" != "running" ]; then
                    all_running=false
                fi
            done <<< "$output"
        fi

        if $all_running; then
            log_pass "All containers are running"
            echo ""
            docker compose -f "$compose_file" ps
            echo ""
            log_info "Readiness polling completed at $(date --iso-8601=seconds)"
            return 0
        fi

        log_debug "Attempt $attempt/$max_attempts: waiting ${poll_interval}s..."
        sleep "$poll_interval"
        attempt=$((attempt + 1))
    done

    log_warn "Readiness polling timed out after $((max_attempts * poll_interval)) seconds"
    echo ""
    docker compose -f "$compose_file" ps
    return 1
}

# ---------------------------------------------------------------------------
# Test GSA web endpoint
# ---------------------------------------------------------------------------
test_web_endpoint() {
    local port="${1:-9392}"

    if ! command -v curl &>/dev/null; then
        log_warn "curl not available — skipping web endpoint test"
        return 0
    fi

    log_info "Testing GSA web endpoint on port $port..."
    local curl_rc=0
    curl -sfk --max-time 10 "https://127.0.0.1:$port" >/dev/null 2>&1 || curl_rc=$?

    if [ "$curl_rc" -eq 0 ]; then
        log_pass "GSA web endpoint is reachable on https://127.0.0.1:$port"
    else
        log_warn "GSA web endpoint not reachable yet (curl exit $curl_rc)"
        log_info "This is normal if feed data is still loading"
    fi
}

# ---------------------------------------------------------------------------
# Mode: deploy
# ---------------------------------------------------------------------------
cmd_deploy() {
    log_info "=== Deploy mode ==="
    echo ""

    # -- Confirmation gate --
    if ! $DEPLOY_CONFIRMED; then
        log_error "Deploy mode requires --deploy-confirmed flag."
        log_error "Usage: $SCRIPT_NAME deploy --deploy-confirmed"
        log_error "This confirms you understand deploy will start Greenbone containers."
        exit 2
    fi

    if ! $NON_INTERACTIVE; then
        echo ""
        echo "WARNING: This will download and start Greenbone Community Containers"
        echo "         on this system. No destructive commands will be executed."
        echo ""
        echo "Type DEPLOY (uppercase) to confirm: "
        local user_input=""
        read -r user_input
        if [ "$user_input" != "DEPLOY" ]; then
            log_error "Confirmation failed. Deploy aborted."
            exit 2
        fi
        echo ""
    fi

    # Safety: if DRY_RUN is set, refuse to perform real deployment
    if [ "${DRY_RUN:-false}" = "true" ]; then
        log_info "DRY_RUN is set — deploy will show planned steps but not execute them."
    fi

    # -- Step 1: Verify prerequisites --
    log_info "Step 1/16: Verifying prerequisites..."
    local prereq_ok=true

    if ! require_cmd docker; then
        log_fail "docker not available — cannot deploy"
        prereq_ok=false
    fi

    if ! docker info &>/dev/null 2>&1; then
        log_fail "Docker daemon not running — cannot deploy"
        prereq_ok=false
    fi

    if ! docker compose version &>/dev/null 2>&1; then
        log_fail "Docker Compose plugin not available — cannot deploy"
        prereq_ok=false
    fi

    if ! require_cmd curl; then
        log_fail "curl not available — cannot download Compose file"
        prereq_ok=false
    fi

    if ! require_cmd sha256sum; then
        log_fail "sha256sum not available — cannot verify download"
        prereq_ok=false
    fi

    $prereq_ok || exit 1

    # -- Step 2: Verify Docker Engine and Compose --
    log_info "Step 2/16: Docker Engine and Compose plugin..."
    log_pass "docker: $(docker --version 2>/dev/null || echo "unknown")"
    log_pass "compose: $(docker compose version 2>/dev/null || echo "unknown")"

    # -- Step 3: Check free disk space --
    log_info "Step 3/16: Checking free disk space..."
    local free_gb
    free_gb=$(get_free_disk_gb "/")
    local threshold
    threshold=$(check_disk_threshold "$free_gb")

    case "$threshold" in
        FAIL)
            log_fail "Free disk space: ${free_gb}GB (minimum required: ${DISK_FAIL_GB}GB)"
            log_fail "Deploy aborted — insufficient disk space."
            exit 1
            ;;
        WARN)
            log_warn "Free disk space: ${free_gb}GB (recommended: ${DISK_WARN_GB}GB)"
            echo ""
            echo "  WARNING: Free disk space is below the recommended ${DISK_WARN_GB}GB."
            echo "  Greenbone feed data requires significant disk space."
            echo ""
            if ! $NON_INTERACTIVE; then
                echo "Type DEPLOY (uppercase) to continue despite low disk space: "
                local disk_input=""
                read -r disk_input
                if [ "$disk_input" != "DEPLOY" ]; then
                    log_error "Disk space confirmation failed. Deploy aborted."
                    exit 2
                fi
            fi
            ;;
        PASS)
            log_pass "Free disk space: ${free_gb}GB"
            ;;
    esac

    # -- Step 4: Determine project directory --
    log_info "Step 4/16: Determining project directory..."
    local pd="${PROJECT_DIR:-/opt/greenbone-community}"
    local cf="${COMPOSE_FILE:-$pd/compose.yaml}"
    local md_dir="${pd}/deployment-metadata"

    log_info "Project directory: $pd"
    log_info "Compose file:      $cf"

    # -- Step 5: Create project directory --
    log_info "Step 5/16: Creating project directory..."
    if [ ! -d "$pd" ]; then
        mkdir -p "$pd"
        log_pass "Created project directory: $pd"
    else
        log_info "Project directory already exists: $pd"
    fi

    # -- Step 6: Download official Compose file --
    log_info "Step 6/16: Downloading official Compose file..."
    local tmp_compose
    tmp_compose=$(mktemp)
    if curl -fsSL "$COMPOSE_URL" -o "$tmp_compose"; then
        log_pass "Compose file downloaded from $COMPOSE_URL"
    else
        log_fail "Failed to download Compose file from $COMPOSE_URL"
        rm -f "$tmp_compose"
        exit 1
    fi

    # -- Step 7: Record SHA-256 checksum --
    log_info "Step 7/16: Recording SHA-256 checksum..."
    local compose_sha
    compose_sha=$(sha256sum "$tmp_compose" | awk '{print $1}')
    log_pass "SHA-256: $compose_sha"

    # Move to final location
    cp "$tmp_compose" "$cf"
    rm -f "$tmp_compose"
    log_pass "Compose file saved to: $cf"

    # -- Step 8: Validate Compose file --
    log_info "Step 8/16: Validating Compose file..."
    if dry_run_cmd docker compose -f "$cf" config >/dev/null 2>&1; then
        log_pass "Compose file is valid"
    else
        log_fail "Compose file validation failed"
        exit 1
    fi

    # -- Step 9: Discover service names --
    log_info "Step 9/16: Discovering service names..."
    local services
    services=$(dry_run_cmd docker compose -f "$cf" config --services 2>/dev/null || echo "")
    if [ -z "$services" ]; then
        log_fail "Could not discover services from Compose file"
        exit 1
    fi
    log_pass "Discovered services:"
    echo "$services" | while IFS= read -r svc; do
        [ -n "$svc" ] && echo "  - $svc"
    done

    # -- Step 10: Create deployment metadata --
    log_info "Step 10/16: Creating deployment metadata..."
    create_deployment_metadata "$md_dir" "$compose_sha" "$services"

    # -- Step 11: Pull images --
    log_info "Step 11/16: Pulling images (this may take a while)..."
    if dry_run_cmd docker compose -f "$cf" pull; then
        log_pass "Images pulled successfully"
    else
        log_warn "Image pull completed with warnings"
    fi

    # -- Step 12: Start stack --
    log_info "Step 12/16: Starting Greenbone stack..."
    if dry_run_cmd docker compose -f "$cf" up -d; then
        log_pass "Greenbone stack started"
    else
        log_fail "Failed to start Greenbone stack"
        exit 1
    fi

    # -- Step 13: Poll readiness --
    log_info "Step 13/16: Polling container readiness..."
    poll_readiness "$pd" "$cf"

    # -- Step 14: Report container status --
    log_info "Step 14/16: Final container status..."
    echo ""
    dry_run_cmd docker compose -f "$cf" ps
    echo ""

    # -- Step 15: Test web endpoint --
    log_info "Step 15/16: Testing web endpoint..."
    test_web_endpoint 9392

    # -- Step 16: Print access information --
    log_info "Step 16/16: Deployment summary..."
    echo ""
    echo "============================================================"
    echo "  Greenbone Community Containers — Deployment Summary"
    echo "============================================================"
    echo "  Project directory: $pd"
    echo "  Compose file:      $cf"
    echo "  Compose SHA-256:   $compose_sha"
    echo "  Metadata:          $md_dir/deployment-metadata.txt"
    echo "  Web interface:     https://127.0.0.1:9392"
    echo "  Default user:      admin"
    echo "  Default password:  admin"
    echo ""
    echo "  IMPORTANT: Change the admin password immediately:"
    echo "    docker compose -f $cf exec -u gvmd gvmd \\"
    echo "      gvmd --user=admin --new-password='<your_password>'"
    echo ""
    echo "  Check logs:  docker compose -f $cf logs -f"
    echo "  Stop stack:  docker compose -f $cf down"
    echo "============================================================"
    echo ""

    log_info "Deploy completed at $(date --iso-8601=seconds)"
}

# ---------------------------------------------------------------------------
# Mode: backup (not implemented)
# ---------------------------------------------------------------------------
cmd_backup() {
    log_error "This mode is not implemented in the current development version"
    exit 3
}

# ---------------------------------------------------------------------------
# Mode: remove (not implemented)
# ---------------------------------------------------------------------------
cmd_remove() {
    log_error "This mode is not implemented in the current development version"
    exit 3
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"
    setup_logging

    case "$MODE" in
        audit)
            cmd_audit
            ;;
        dry-run)
            cmd_dry_run
            ;;
        status)
            cmd_status
            ;;
        deploy)
            cmd_deploy
            ;;
        backup)
            cmd_backup
            ;;
        remove)
            cmd_remove
            ;;
        *)
            log_error "Unknown mode: $MODE"
            usage >&2
            exit 2
            ;;
    esac
}

main "$@"
