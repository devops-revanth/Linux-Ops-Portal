#!/usr/bin/env bash
# =============================================================================
# LOP — Diagnostics bundle
# Usage: sudo ./diagnostics.sh [--output-dir <dir>]
#
# Collects everything needed for troubleshooting into a single archive.
#
# PRIVACY NOTE
# ────────────
# The bundle is designed to be safe to share with support personnel:
#   • All secret values in configuration files are masked before inclusion
#     (DATABASE_URL passwords, SECRET_KEY, bind passwords, API tokens, and
#     any KEY= / PASSWORD= / SECRET= / TOKEN= patterns).
#   • python_info.txt contains installed pip package names and versions —
#     no credentials or secret values.
#   • postgres_info.txt contains PostgreSQL version, service status, and
#     cluster configuration — no database contents or passwords.
#   • Application log tails (app_logs/) are included verbatim.  Ensure
#     your logging configuration does not write plaintext passwords to logs.
#
# Never add password retrieval, private-key export, or umasked config dumps
# to this script.
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/dev/null"   # diagnostics writes its own output

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/version.sh"

OUTPUT_DIR="/var/log/lop"

parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    case "$arg" in
        --output-dir=*) OUTPUT_DIR="${arg#--output-dir=}" ;;
        --output-dir)   : ;;   # next arg captured below
    esac
done

# =============================================================================
main() {
    require_root "$@"

    local ts
    ts="$(date +%Y%m%d_%H%M%S)"
    local bundle_name="lop_diagnostics_${ts}"
    local work_dir="$LOP_TMP_DIR/${bundle_name}"
    local archive="${OUTPUT_DIR}/${bundle_name}.tar.gz"

    mkdir -p "$work_dir"
    # Clean up on exit
    trap "rm -rf '$work_dir'" EXIT

    log_info "Collecting diagnostics..."

    # ── 1. Systemd service status ─────────────────────────────────────────────
    {
        echo "=== systemctl status lop-backend ==="
        systemctl status "$LOP_BACKEND_SERVICE" --no-pager -l 2>&1 || echo "(not found)"
        echo ""
        echo "=== systemctl list-units lop* ==="
        systemctl list-units 'lop*' --no-pager 2>&1 || true
        echo ""
        echo "=== Unit file ==="
        systemctl cat "$LOP_BACKEND_SERVICE" 2>/dev/null || echo "(not found)"
    } > "$work_dir/systemd_status.txt" 2>&1

    # ── 2. Journal logs (last 7 days) ─────────────────────────────────────────
    journalctl -u "$LOP_BACKEND_SERVICE" --since "7 days ago" --no-pager \
        > "$work_dir/journalctl.log" 2>&1 || echo "(no journal)" > "$work_dir/journalctl.log"

    # ── 3. Application logs ───────────────────────────────────────────────────
    mkdir -p "$work_dir/app_logs"
    if [[ -d "$LOP_LOG_DIR" ]]; then
        while IFS= read -r f; do
            # Tail each log to 2000 lines; base computed outside pipeline to avoid
            # `local` inside subshell which is valid but misleading in some shells
            tail -2000 "$f" > "$work_dir/app_logs/$(basename "$f")" 2>/dev/null || true
        done < <(find "$LOP_LOG_DIR" -name "*.log" -type f 2>/dev/null)
    else
        echo "(no log directory)" > "$work_dir/app_logs/note.txt"
    fi

    # ── 4. Python version info ────────────────────────────────────────────────
    {
        echo "=== System Python ==="
        python3 --version 2>&1 || echo "not found"
        echo ""
        echo "=== Selected Python (runtime.env) ==="
        if [[ -f "$LOP_RUNTIME_FILE" ]]; then
            cat "$LOP_RUNTIME_FILE"
        else
            echo "(not found)"
        fi
        echo ""
        echo "=== Virtual Environment Python ==="
        if [[ -x "$LOP_VENV_DIR/bin/python" ]]; then
            "$LOP_VENV_DIR/bin/python" --version 2>&1
        else
            echo "(not found)"
        fi
        echo ""
        echo "=== Installed pip packages ==="
        if [[ -x "$LOP_VENV_DIR/bin/pip" ]]; then
            "$LOP_VENV_DIR/bin/pip" list 2>&1
        else
            echo "(venv not found)"
        fi
    } > "$work_dir/python_info.txt" 2>&1

    # ── 5. PostgreSQL info ────────────────────────────────────────────────────
    {
        echo "=== PostgreSQL version ==="
        if cmd_exists psql; then
            psql --version 2>&1
        else
            echo "psql not found"
        fi
        echo ""
        echo "=== Service status ==="
        systemctl status postgresql --no-pager -l 2>&1 \
            || systemctl status postgresql@*-main --no-pager -l 2>&1 \
            || echo "postgresql service not found"
        echo ""
        echo "=== Cluster info ==="
        if cmd_exists pg_lsclusters; then
            pg_lsclusters 2>&1 || true
        fi
    } > "$work_dir/postgres_info.txt" 2>&1

    # ── 6. Database migration version ────────────────────────────────────────
    {
        echo "=== Alembic current (deployed) ==="
        alembic_current 2>&1 || echo "cannot determine"
        echo ""
        echo "=== Alembic head (codebase) ==="
        alembic_head 2>&1 || echo "cannot determine"
    } > "$work_dir/db_migration.txt" 2>&1

    # ── 7. Application version ────────────────────────────────────────────────
    {
        echo "=== VERSION file ==="
        [[ -f "$LOP_APP_DIR/VERSION" ]] && cat "$LOP_APP_DIR/VERSION" || echo "(not found)"
        echo ""
        echo "=== Install info ==="
        [[ -f "$LOP_INSTALL_INFO" ]] && cat "$LOP_INSTALL_INFO" || echo "(not found)"
        echo ""
        echo "=== Git log (last 10 commits) ==="
        git -C "$LOP_APP_DIR" log --oneline -10 2>&1 || echo "not a git repo"
        echo ""
        echo "=== Git status ==="
        git -C "$LOP_APP_DIR" status --short 2>&1 || true
    } > "$work_dir/version.txt" 2>&1

    # ── 8. Disk usage ─────────────────────────────────────────────────────────
    {
        echo "=== Disk usage ==="
        df -h 2>&1
        echo ""
        echo "=== LOP directory sizes ==="
        for d in "$LOP_APP_DIR" "$LOP_LOG_DIR" "$LOP_BACKUP_DIR" "$LOP_DATA_DIR"; do
            [[ -d "$d" ]] && du -sh "$d" 2>&1 || echo "(not found) $d"
        done
    } > "$work_dir/disk_usage.txt" 2>&1

    # ── 9. Memory usage ───────────────────────────────────────────────────────
    {
        echo "=== Memory ==="
        free -h 2>&1 || echo "free not available"
        echo ""
        echo "=== Top processes ==="
        ps aux --sort=-%mem 2>/dev/null | head -20 || true
    } > "$work_dir/memory.txt" 2>&1

    # ── 10. Operating system ──────────────────────────────────────────────────
    {
        echo "=== OS Release ==="
        cat /etc/os-release 2>/dev/null || echo "not found"
        echo ""
        echo "=== Kernel ==="
        uname -a 2>&1
        echo ""
        echo "=== Hostname ==="
        hostname -f 2>/dev/null || hostname
        echo ""
        echo "=== Uptime ==="
        uptime 2>&1 || true
    } > "$work_dir/os_info.txt" 2>&1

    # ── 11. Network (basic) ───────────────────────────────────────────────────
    {
        echo "=== Listening ports ==="
        ss -tlnp 2>/dev/null | grep -E '5000|8080|5432' || \
            netstat -tlnp 2>/dev/null | grep -E '5000|8080|5432' || \
            echo "ss/netstat not available"
        echo ""
        echo "=== Health check response ==="
        curl -s --max-time 5 http://localhost:5000/health 2>&1 || echo "no response"
    } > "$work_dir/network.txt" 2>&1

    # ── 12. Configuration (masked) ────────────────────────────────────────────
    {
        echo "=== /etc/lop/lop.env (secrets masked) ==="
        if [[ -f "$LOP_CONF_FILE" ]]; then
            mask_secrets "$LOP_CONF_FILE"
        else
            echo "(not found)"
        fi
    } > "$work_dir/config_masked.txt" 2>&1

    # ── 13. Checksums / update state ─────────────────────────────────────────
    {
        echo "=== Checksums ==="
        [[ -d "$LOP_CHECKSUMS_DIR" ]] && ls -la "$LOP_CHECKSUMS_DIR" || echo "(not found)"
        echo ""
        echo "=== Alembic head checksum ==="
        [[ -f "$LOP_CHECKSUMS_DIR/alembic_head.txt" ]] \
            && cat "$LOP_CHECKSUMS_DIR/alembic_head.txt" || echo "(not found)"
    } > "$work_dir/update_state.txt" 2>&1

    # ── 14. Integration & scheduler status ───────────────────────────────────
    # Queries integration config from the database (status strings only —
    # all credentials are Fernet-encrypted in the DB and are NOT included here).
    {
        # Load env so we can get DATABASE_URL
        if [[ -f "$LOP_CONF_FILE" ]]; then
            set -a; source "$LOP_CONF_FILE"; set +a 2>/dev/null || true
        fi
        local _db_url
        _db_url="${DATABASE_URL:-}"

        echo "=== Scheduler (APScheduler — embedded in Flask/gunicorn) ==="
        if cmd_exists systemctl; then
            if systemctl is-active --quiet lop-backend 2>/dev/null; then
                echo "APScheduler: RUNNING (backend service is active)"
            else
                echo "APScheduler: NOT RUNNING (backend service is inactive)"
            fi
        else
            echo "APScheduler: unknown (systemctl not available)"
        fi

        echo ""
        echo "=== VMware vCenter Integration (multi-vCenter — vmware_connections) ==="
        if cmd_exists psql && [[ -n "$_db_url" ]]; then
            psql -tA "$_db_url" 2>/dev/null <<'EOSQL' || echo "(table not found — migration may be pending)"
SELECT
  '--- vCenter id: ' || id::text || ' ---',
  'enabled:          ' || enabled::text,
  'vcenter_host:     ' || COALESCE(vcenter_host, '(not set)'),
  'port:             ' || COALESCE(port::text, '443'),
  'connection_status:' || COALESCE(connection_status, 'Not Tested'),
  'last_test_at:     ' || COALESCE(last_test_at::text, 'never'),
  'last_sync_at:     ' || COALESCE(last_sync_at::text, 'never'),
  'last_sync_ok_at:  ' || COALESCE(last_sync_ok_at::text, 'never'),
  'last_sync_fail_at:' || COALESCE(last_sync_fail_at::text, 'never')
FROM vmware_connections
ORDER BY id;
EOSQL
        else
            echo "(psql not available or DATABASE_URL not set)"
        fi

        echo ""
        echo "=== Ansible Integration ==="
        if cmd_exists psql && [[ -n "$_db_url" ]]; then
            psql -tA "$_db_url" 2>/dev/null <<'EOSQL' || echo "(table not found — migration may be pending)"
SELECT
  'enabled:             ' || enabled::text,
  'control_node:        ' || COALESCE(control_node, '(not set)'),
  'port:                ' || port::text,
  'auth_method:         ' || COALESCE(auth_method, '—'),
  'connection_status:   ' || COALESCE(connection_status, 'Not Tested'),
  'ansible_version:     ' || COALESCE(ansible_version, '—'),
  'python_version:      ' || COALESCE(python_version, '—'),
  'last_inventory_hosts:' || last_inventory_hosts::text,
  'last_playbooks_found:' || last_playbooks_found::text,
  'last_connected_at:   ' || COALESCE(last_connected_at::text, 'never'),
  'last_validation_at:  ' || COALESCE(last_validation_at::text, 'never')
FROM ansible_config
LIMIT 1;
EOSQL
        else
            echo "(psql not available or DATABASE_URL not set)"
        fi

        echo ""
        echo "=== FreeIPA / LDAP Integration ==="
        if cmd_exists psql && [[ -n "$_db_url" ]]; then
            psql -tA "$_db_url" 2>/dev/null <<'EOSQL' || echo "(table not found)"
SELECT
  'enabled:           ' || enabled::text,
  'ldap_uri:          ' || COALESCE(ldap_uri, '(not set)'),
  'connection_status: ' || COALESCE(connection_status, 'Not Tested'),
  'last_connected_at: ' || COALESCE(last_connected_at::text, 'never')
FROM directory_config
LIMIT 1;
EOSQL
        else
            echo "(psql not available or DATABASE_URL not set)"
        fi

    } > "$work_dir/integrations.txt" 2>&1

    # ── Create archive ────────────────────────────────────────────────────────
    mkdir -p "$OUTPUT_DIR"
    tar -czf "$archive" -C "$LOP_TMP_DIR" "$bundle_name" 2>/dev/null \
        || abort "Failed to create diagnostics archive."
    chmod 600 "$archive"

    local archive_size
    archive_size=$(du -sh "$archive" | cut -f1)

    printf "\n%s%sDiagnostics bundle created%s\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"
    printf "  Path: %s\n" "$archive"
    printf "  Size: %s\n\n" "$archive_size"
    printf "Contents:\n"
    printf "  systemd_status.txt    — service status and unit file\n"
    printf "  journalctl.log        — service journal (7 days)\n"
    printf "  app_logs/             — application log files\n"
    printf "  python_info.txt       — Python runtime and installed pip package versions\n"
    printf "  postgres_info.txt     — PostgreSQL version and status\n"
    printf "  db_migration.txt      — Alembic schema versions\n"
    printf "  version.txt           — app version, git log\n"
    printf "  disk_usage.txt        — disk space\n"
    printf "  memory.txt            — memory and process info\n"
    printf "  os_info.txt           — OS, kernel, uptime\n"
    printf "  network.txt           — ports and health check\n"
    printf "  config_masked.txt     — configuration (secrets masked)\n"
    printf "  update_state.txt      — checksum/update state\n"
    printf "  integrations.txt      — VMware, Ansible, LDAP integration status (no credentials)\n"
    printf "\nShare this file when requesting support.\n\n"
}

main "$@"
