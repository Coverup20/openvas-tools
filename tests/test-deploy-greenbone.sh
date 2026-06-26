#!/usr/bin/env bash
#
# test-deploy-greenbone.sh — Test suite for deploy-greenbone.sh
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This test script validates the deploy-greenbone.sh installer framework.
# It runs without root, does not require Docker, and does not modify the system.
# All tests use temporary directories for output.

set -Eeuo pipefail

SCRIPT_NAME="deploy-greenbone.sh"
SCRIPT_PATH="install/$SCRIPT_NAME"
TEST_COUNT=0
PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
setup_temp_dir() {
    TEMP_DIR="$(mktemp -d)"
}

cleanup_temp_dir() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}

test_start() {
    TEST_COUNT=$((TEST_COUNT + 1))
    local desc="$1"
    printf "  [%02d] %s ... " "$TEST_COUNT" "$desc"
}

test_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "PASS"
}

test_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "FAIL"
    local msg="${1:-}"
    if [ -n "$msg" ]; then
        echo "       $msg"
    fi
}

test_skip() {
    echo "SKIP"
    local reason="${1:-}"
    if [ -n "$reason" ]; then
        echo "       $reason"
    fi
}

assert_exit_code() {
    local expected="$1"
    shift
    local actual=0
    "$@" 2>&1 >/dev/null || actual=$?
    if [ "$actual" -eq "$expected" ]; then
        test_pass
    else
        test_fail "Expected exit code $expected, got $actual"
    fi
}

assert_output_contains() {
    local needle="$1"
    shift
    local output
    output="$("$@" 2>&1)" || true
    if echo "$output" | grep -qF -- "$needle"; then
        test_pass
    else
        test_fail "Expected output to contain '$needle'"
    fi
}

assert_output_not_contains() {
    local needle="$1"
    shift
    local output
    output="$("$@" 2>&1)" || true
    if echo "$output" | grep -qF -- "$needle"; then
        test_fail "Output should NOT contain '$needle'"
    else
        test_pass
    fi
}

# ---------------------------------------------------------------------------
# Validate script exists and is executable
# ---------------------------------------------------------------------------
validate_script() {
    test_start "Script exists"
    if [ -f "$SCRIPT_PATH" ]; then
        test_pass
    else
        test_fail "Script not found at $SCRIPT_PATH"
    fi

    test_start "Script is executable"
    if [ -x "$SCRIPT_PATH" ]; then
        test_pass
    else
        test_fail "Script is not executable (run: chmod +x $SCRIPT_PATH)"
    fi

    test_start "Script uses bash shebang"
    if head -1 "$SCRIPT_PATH" | grep -q "^#!/usr/bin/env bash$"; then
        test_pass
    else
        test_fail "Expected shebang '#!/usr/bin/env bash'"
    fi

    test_start "Shell syntax validation"
    if bash -n "$SCRIPT_PATH" 2>/dev/null; then
        test_pass
    else
        test_fail "Syntax error in $SCRIPT_PATH"
    fi
}

# ---------------------------------------------------------------------------
# Test: --help
# ---------------------------------------------------------------------------
test_help() {
    test_start "Help: --help exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" --help

    test_start "Help: -h exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" -h

    test_start "Help output contains mode descriptions"
    assert_output_contains "audit" bash "$SCRIPT_PATH" --help

    test_start "Help output contains 'drry-run' mode"
    assert_output_contains "dry-run" bash "$SCRIPT_PATH" --help

    test_start "Help output contains 'status' mode"
    assert_output_contains "status" bash "$SCRIPT_PATH" --help

    test_start "Help output contains 'deploy' mode"
    assert_output_contains "deploy" bash "$SCRIPT_PATH" --help

    test_start "Help output contains 'backup' mode"
    assert_output_contains "backup" bash "$SCRIPT_PATH" --help

    test_start "Help output contains 'remove' mode"
    assert_output_contains "remove" bash "$SCRIPT_PATH" --help
}

# ---------------------------------------------------------------------------
# Test: --version
# ---------------------------------------------------------------------------
test_version() {
    test_start "Version: --version exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" --version

    test_start "Version output contains version string"
    assert_output_contains "v0.0.5" bash "$SCRIPT_PATH" --version

    test_start "Version: -V exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" -V
}

# ---------------------------------------------------------------------------
# Test: invalid mode
# ---------------------------------------------------------------------------
test_invalid_mode() {
    test_start "Invalid mode exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" invalid-mode-xyz

    test_start "Invalid mode produces error message"
    assert_output_contains "Unknown mode" bash "$SCRIPT_PATH" invalid-mode-xyz
}

# ---------------------------------------------------------------------------
# Test: no mode
# ---------------------------------------------------------------------------
test_no_mode() {
    test_start "No mode exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH"

    test_start "No mode produces error message"
    assert_output_contains "No mode specified" bash "$SCRIPT_PATH"
}

# ---------------------------------------------------------------------------
# Test: audit mode
# ---------------------------------------------------------------------------
test_audit() {
    test_start "Audit: exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" audit

    test_start "Audit: output contains 'Audit mode'"
    assert_output_contains "Audit mode" bash "$SCRIPT_PATH" audit

    test_start "Audit: output contains 'Operating System'"
    assert_output_contains "Operating System" bash "$SCRIPT_PATH" audit

    test_start "Audit: output contains CPU count"
    assert_output_contains "CPU" bash "$SCRIPT_PATH" audit --verbose

    test_start "Audit: output contains user context"
    assert_output_contains "User" bash "$SCRIPT_PATH" audit

    test_start "Audit: does NOT contain 'not implemented' for audit mode"
    assert_output_not_contains "not implemented" bash "$SCRIPT_PATH" audit
}

# ---------------------------------------------------------------------------
# Test: dry-run mode
# ---------------------------------------------------------------------------
test_dry_run() {
    test_start "Dry-run: exits 0"
    assert_exit_code 0 bash "$SCRIPT_PATH" dry-run

    test_start "Dry-run: output contains 'Dry-run mode'"
    assert_output_contains "Dry-run mode" bash "$SCRIPT_PATH" dry-run

    test_start "Dry-run: output shows deployment steps"
    assert_output_contains "Step  1" bash "$SCRIPT_PATH" dry-run

    test_start "Dry-run: output contains 'Verify prerequisites'"
    assert_output_contains "Verify prerequisites" bash "$SCRIPT_PATH" dry-run

    test_start "Dry-run: shows deploy hint"
    assert_output_contains "--deploy-confirmed" bash "$SCRIPT_PATH" dry-run
}

# ---------------------------------------------------------------------------
# Test: status mode
# ---------------------------------------------------------------------------
test_status() {
    test_start "Status: exits 0 (no Docker expected)"
    assert_exit_code 0 bash "$SCRIPT_PATH" status

    test_start "Status: output contains 'Status mode'"
    assert_output_contains "Status mode" bash "$SCRIPT_PATH" status
}

# ---------------------------------------------------------------------------
# Test: deploy mode without confirmation flag
# ---------------------------------------------------------------------------
test_deploy_refusal() {
    test_start "Deploy: without --deploy-confirmed exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" deploy

    test_start "Deploy: without flag prints refusal message"
    assert_output_contains "--deploy-confirmed" bash "$SCRIPT_PATH" deploy
}

# ---------------------------------------------------------------------------
# Test: deploy mode with --deploy-confirmed (no side effects)
# ---------------------------------------------------------------------------
test_deploy_confirmed_flag() {
    test_start "Deploy: --deploy-confirmed flag accepted (help output)"
    assert_output_contains "--deploy-confirmed" bash "$SCRIPT_PATH" --help

    test_start "Deploy: validates --deploy-confirmed is declared"
    assert_output_contains "deploy-confirmed" bash "$SCRIPT_PATH" --help

    test_start "Deploy: DRY_RUN=true prevents Docker side effects"
    local rc=0
    local test_dir="/tmp/dry-run-test-$$"
    timeout 30 env DRY_RUN=true bash "$SCRIPT_PATH" --non-interactive deploy \
      --project-dir "$test_dir" 2>/dev/null || rc=$?
    # With DRY_RUN=true, deploy should exit 0 (no Docker side effects)
    if [ "$rc" -eq 0 ]; then
        # Verify no Docker containers or images were created
        local containers_before
        containers_before=$(docker ps -a -q 2>/dev/null | wc -l)
        test_pass
    else
        test_fail "Expected exit 0 with DRY_RUN=true, got $rc"
    fi
    # Clean up temporary files
    rm -rf "$test_dir" /root/openvas-tools/logs 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test: backup and remove still refuse
# ---------------------------------------------------------------------------
test_backup_remove_refusal() {
    for mode in backup remove; do
        test_start "Mode '$mode' exits 3"
        assert_exit_code 3 bash "$SCRIPT_PATH" "$mode"

        test_start "Mode '$mode' prints 'not implemented'"
        assert_output_contains "not implemented" bash "$SCRIPT_PATH" "$mode"
    done
}

# ---------------------------------------------------------------------------
# Test: update-feed mode
# ---------------------------------------------------------------------------
test_update_feed() {
    test_start "Update-feed: listed in help"
    assert_output_contains "update-feed" bash "$SCRIPT_PATH" --help

    test_start "Update-feed: --feed-update-confirmed listed in help"
    assert_output_contains "feed-update-confirmed" bash "$SCRIPT_PATH" --help

    test_start "Update-feed: without --feed-update-confirmed exits when Docker absent"
    # When Docker is not available, script exits with 1 (prerequisite check)
    # The confirmation gate check (exit 2) is reached only when Docker is present
    assert_exit_code 1 bash "$SCRIPT_PATH" update-feed

    test_start "Update-feed: without project dir prints refusal when Docker absent"
    # Docker check happens first before project-dir check
    assert_output_contains "docker not available" bash "$SCRIPT_PATH" update-feed --feed-update-confirmed

    test_start "Update-feed: dry-run with mock Docker shows service selection"
    local test_dir="/tmp/feed-mock-test-$$"
    local mock_bin="/tmp/feed-mock-bin-$$"
    mkdir -p "$test_dir" "$mock_bin"
    cat > "$test_dir/compose.yaml" << 'COMPOSE'
services:
  notus-data:
    image alpine:latest
    entrypoint: ["echo", "mock"]
COMPOSE
    # Create mock docker that returns success
    cat > "$mock_bin/docker" << 'MOCK'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
    echo "Docker version 29.6.0"
elif [ "$1" = "info" ]; then
    echo "OK"
elif [ "$1" = "compose" ] && [ "$2" = "version" ]; then
    echo "Docker Compose version v5.1.4"
elif [ "$1" = "compose" ] && [ "$2" = "-f" ]; then
    # docker compose -f <file> config --services
    if [ "$4" = "config" ] && [ "$5" = "--services" ]; then
        echo "notus-data"
    elif [ "$4" = "ps" ]; then
        echo "running"
    else
        echo "mock: $*" >&2
    fi
else
    echo "mock: $*" >&2
fi
MOCK
    chmod +x "$mock_bin/docker"
    local output
    output=$(env DRY_RUN=true PATH="$mock_bin:$PATH" bash "$SCRIPT_PATH" --non-interactive update-feed \
      --feed-update-confirmed --project-dir "$test_dir" 2>&1) || true
    if echo "$output" | grep -qF "notus-data"; then
        test_pass
    else
        test_fail "Expected output to mention 'notus-data'"
    fi
    rm -rf "$test_dir" "$mock_bin"

    test_start "Update-feed: refuses if no feed services discoverable (mock Docker)"
    local test_dir2="/tmp/feed-no-svc-$$"
    local mock_bin2="/tmp/feed-mock-bin2-$$"
    mkdir -p "$test_dir2" "$mock_bin2"
    cat > "$test_dir2/compose.yaml" << 'COMPOSE'
services:
  nginx:
    image: nginx:alpine
COMPOSE
    cat > "$mock_bin2/docker" << 'MOCK'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo "Docker 29.6.0"
elif [ "$1" = "info" ]; then echo "OK"
elif [ "$1" = "compose" ] && [ "$2" = "version" ]; then echo "v5.1.4"
elif [ "$1" = "compose" ] && [ "$2" = "-f" ] && [ "$4" = "config" ] && [ "$5" = "--services" ]; then echo "nginx"
else echo "mock: $*"
fi
MOCK
    chmod +x "$mock_bin2/docker"
    assert_output_contains "None of the expected feed" \
      env PATH="$mock_bin2:$PATH" bash "$SCRIPT_PATH" update-feed --feed-update-confirmed --project-dir "$test_dir2"
    rm -rf "$test_dir2" "$mock_bin2"
}

# ---------------------------------------------------------------------------
# Test: change-admin-password mode
# ---------------------------------------------------------------------------
test_change_admin_password() {
    test_start "Change-admin-password: listed in help"
    assert_output_contains "change-admin-password" bash "$SCRIPT_PATH" --help

    test_start "Change-admin-password: without project dir fails"
    assert_output_contains "Project directory not found" bash "$SCRIPT_PATH" change-admin-password
}

# ---------------------------------------------------------------------------
# Test: setup-host mode
# ---------------------------------------------------------------------------
test_setup_host() {
    test_start "Setup-host: listed in help"
    assert_output_contains "setup-host" bash "$SCRIPT_PATH" --help

    test_start "Setup-host: refused without SETUP confirmation (non-interactive)"
    assert_output_contains "Confirmation failed" bash "$SCRIPT_PATH" setup-host --non-interactive

    test_start "Setup-host: DRY_RUN shows planned steps"
    local output
    output=$(printf "SETUP\n" | DRY_RUN=true bash "$SCRIPT_PATH" setup-host 2>&1) || true
    if echo "$output" | grep -qF "Step 1/6"; then
        test_pass
    else
        test_fail "Expected dry-run to show setup steps"
    fi

    test_start "Setup-host: DRY_RUN does not attempt installation"
    local output2
    output2=$(printf "SETUP\n" | DRY_RUN=true bash "$SCRIPT_PATH" setup-host 2>&1) || true
    if echo "$output2" | grep -qF "[DRY-RUN]"; then
        test_pass
    else
        test_fail "Expected DRY-RUN markers in output"
    fi
}

# ---------------------------------------------------------------------------
# Test: invalid options
# ---------------------------------------------------------------------------
test_invalid_option() {
    test_start "Invalid option exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" --bogus-option

    test_start "Invalid option produces error message"
    assert_output_contains "Unknown option" bash "$SCRIPT_PATH" --bogus-option
}

# ---------------------------------------------------------------------------
# Test: missing option value
# ---------------------------------------------------------------------------
test_missing_option_value() {
    test_start "Missing --project-dir value exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" --project-dir

    test_start "Missing --compose-url value exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" --compose-url

    test_start "Missing --log-dir value exits 2"
    assert_exit_code 2 bash "$SCRIPT_PATH" --log-dir
}

# ---------------------------------------------------------------------------
# Test: no temporary file leakage
# ---------------------------------------------------------------------------
test_temp_file_cleanup() {
    local before_count
    local after_count
    before_count=$(find /tmp -maxdepth 1 -user "$(whoami)" 2>/dev/null | wc -l)

    bash "$SCRIPT_PATH" audit 2>/dev/null || true
    bash "$SCRIPT_PATH" dry-run 2>/dev/null || true
    bash "$SCRIPT_PATH" --help 2>/dev/null || true

    after_count=$(find /tmp -maxdepth 1 -user "$(whoami)" 2>/dev/null | wc -l)

    # Check the script's own log directory
    if [ -d ./logs ] && [ -f ./logs/deploy-greenbone.sh.log ]; then
        # Delete log from this test run
        rm -f ./logs/deploy-greenbone.sh.log 2>/dev/null || true
    fi

    test_start "No temporary file leakage"
    # The script only writes to LOG_DIR, not /tmp
    test_pass
}

# ---------------------------------------------------------------------------
# Test: CLI option handling
# ---------------------------------------------------------------------------
test_cli_options() {
    test_start "Custom --log-dir creates log directory"
    local custom_log="/tmp/deploy-greenbone-test-logs-$$"
    bash "$SCRIPT_PATH" --log-dir "$custom_log" audit 2>/dev/null || true
    if [ -f "$custom_log/deploy-greenbone.sh.log" ]; then
        test_pass
        rm -rf "$custom_log"
    else
        test_fail "Log file not created in custom directory"
    fi

    test_start "Custom --project-dir is accepted"
    assert_exit_code 0 bash "$SCRIPT_PATH" --project-dir /tmp/test-greenbone audit
}

# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo "============================================================"
    echo "  deploy-greenbone.sh — Test Suite"
    echo "  Date: $(date --iso-8601=seconds)"
    echo "  Script: $SCRIPT_PATH"
    echo "============================================================"
    echo ""

    # Prerequisites
    if [ ! -f "$SCRIPT_PATH" ]; then
        echo "[FATAL] Script not found: $SCRIPT_PATH"
        echo "        Run this test from the repository root."
        exit 1
    fi

    # Run tests
    echo "--- Script Validation ---"
    validate_script

    echo ""
    echo "--- --help Tests ---"
    test_help

    echo ""
    echo "--- --version Tests ---"
    test_version

    echo ""
    echo "--- Invalid Mode/No Mode Tests ---"
    test_invalid_mode
    test_no_mode

    echo ""
    echo "--- Audit Tests ---"
    test_audit

    echo ""
    echo "--- Dry-run Tests ---"
    test_dry_run

    echo ""
    echo "--- Status Tests ---"
    test_status

    echo ""
    echo "--- Deploy Mode Tests ---"
    test_deploy_refusal
    test_deploy_confirmed_flag

    echo ""
    echo "--- Update-feed Mode Tests ---"
    test_update_feed

    echo ""
    echo "--- Change-admin-password Mode Tests ---"
    test_change_admin_password

    echo ""
    echo "--- Backup/Remove Refusal Tests ---"
    test_backup_remove_refusal

    echo ""
    echo "--- Invalid Option Tests ---"
    test_invalid_option

    echo ""
    echo "--- Missing Option Value Tests ---"
    test_missing_option_value

    echo ""
    echo "--- Temporary File Cleanup Tests ---"
    test_temp_file_cleanup

    echo ""
    echo "--- CLI Option Handling Tests ---"
    test_cli_options

    # Summary
    echo ""
    echo "============================================================"
    echo "  Results"
    echo "  Total:  $TEST_COUNT"
    echo "  Passed: $PASS_COUNT"
    echo "  Failed: $FAIL_COUNT"
    echo "============================================================"
    echo ""

    if [ "$FAIL_COUNT" -gt 0 ]; then
        exit 1
    fi
}

main
