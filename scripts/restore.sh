#!/usr/bin/env bash
# =============================================================================
# LOP — Restore script
# Usage: sudo ./restore.sh <backup.tar.gz> [--yes] [--config-only] [--db-only]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/var/log/lop/install.log"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/os.sh"
source "$SCRIPT_DIR/lib/postgres.sh"
source "$SCRIPT_DIR/lib/version.sh"
source "$SCRIPT_DIR/lib/systemd.sh"

parse_common_flags "$@"

CONFIG_ONLY=false
DB_ONLY=false
BACKUP_FILE=""

for arg in "${REMAINING_ARGS[@]:-}"; do
    case "$arg" in
        --config-only) CONFIG_ONLY=true ;;
        --db-only)     DB_ONLY=true ;;
        *.tar.gz|*.tgz) BACKUP_FILE="$arg" ;;
        *)             [[ -f "$arg" ]] && BACKUP_FILE="$arg" ;;
    esac
done

# =============================================================================
main() {
    require_root "$@"

    mkdir -p "$(dirname "$LOG_FILE")" "$LOP_TMP_DIR"
    setup_tmp_dir

    # ── Validate input ────────────────────────────────────────────────────────
    if [[ -z "$BACKUP_FILE" ]]; then
        printf "Usage: sudo ./restore.sh <backup.tar.gz> [--yes] [--config-only] [--db-only]\n\n"
        printf "Available backups:\n"
        ls -lht "$LOP_BACKUP_DIR"/*.tar.gz 2>/dev/null \
            | awk '{print "  " $NF " (" $5 ")"}'  \
            || printf "  No backups found in %s\n" "$LOP_BACKUP_DIR"
        exit 1
    fi

    [[ -f "$BACKUP_FILE" ]] \
        || abort "Backup file not found: ${BACKUP_FILE}"

    detect_os

    # ── Extract and inspect ───────────────────────────────────────────────────
    local work_dir="$LOP_TMP_DIR/restore_$$"
    mkdir -p "$work_dir"

    tar -xzf "$BACKUP_FILE" -C "$work_dir" --strip-components=1 >> "$LOG_FILE" 2>&1 \
        || abort "Failed to extract backup archive. File may be corrupt."

    # Validate contents
    for required in database.sql lop.env version.txt; do
        [[ -f "$work_dir/$required" ]] \
            || abort "Backup archive is missing required file: ${required}"
    done

    # ── Show what will be restored ────────────────────────────────────────────
    log_section "Restore Plan"
    printf "  Backup file:   %s\n" "$BACKUP_FILE"
    printf "  Backup date:   %s\n" "$(grep '^backup_date=' "$work_dir/version.txt" | cut -d= -f2)"
    printf "  App version:   %s\n" "$(grep '^app_version=' "$work_dir/version.txt" | cut -d= -f2)"
    printf "  DB schema:     %s\n" "$(grep '^db_schema=' "$work_dir/version.txt" | cut -d= -f2)"
    printf "  Git hash:      %s\n" "$(grep '^git_hash=' "$work_dir/version.txt" | cut -d= -f2 | head -c 8)"
    printf "\n"

    if [[ "$CONFIG_ONLY" == "true" ]]; then
        printf "  Restore scope: CONFIGURATION ONLY (database will not be touched)\n\n"
    elif [[ "$DB_ONLY" == "true" ]]; then
        printf "  Restore scope: DATABASE ONLY (configuration will not be touched)\n\n"
    else
        printf "  Restore scope: FULL (database + configuration)\n\n"
        printf "  %sWARNING: The current database will be replaced.%s\n\n" "$CLR_YELLOW" "$CLR_RESET"
    fi

    confirm "Proceed with restore?" \
        || abort "Restore cancelled by user."

    # ── Stop service ──────────────────────────────────────────────────────────
    log_step "Stopping lop-backend..."
    systemd_stop "$LOP_BACKEND_SERVICE"

    # ── Restore configuration ─────────────────────────────────────────────────
    if [[ "$DB_ONLY" != "true" ]]; then
        log_step "Restoring configuration..."
        cp "$work_dir/lop.env" "$LOP_CONF_FILE"
        chmod 640 "$LOP_CONF_FILE"
        [[ -f "${LOP_CONF_DIR}/runtime.env" ]] && chmod 640 "${LOP_CONF_DIR}/runtime.env" || true
        chown root:lop "$LOP_CONF_FILE" 2>/dev/null || chown root:root "$LOP_CONF_FILE"
        track_change "Restored configuration from backup"
        log_success "Configuration restored."
    fi

    # ── Restore database ──────────────────────────────────────────────────────
    if [[ "$CONFIG_ONLY" != "true" ]]; then
        load_lop_env
        pg_ensure_service

        local db_name
        db_name=$(grep '^LOP_DB_NAME=' "$LOP_CONF_FILE" | cut -d= -f2 || echo "lop_db")

        log_step "Restoring database '${db_name}'..."
        pg_restore_db "$db_name" "$work_dir/database.sql"
    fi

    # ── Restart service ───────────────────────────────────────────────────────
    log_step "Starting lop-backend..."
    systemctl start "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 \
        || log_warn "Service failed to start. Check: sudo journalctl -u lop-backend -n 50"

    # ── Health check ──────────────────────────────────────────────────────────
    log_step "Verifying restore health (waiting up to 60s)..."
    if health_check "http://localhost:5000/health" 12 5; then
        log_success "Health check passed."
    else
        log_warn "Health check failed. Application may need attention."
        log_warn "Check: sudo journalctl -u lop-backend -n 50"
    fi

    # ── Summary ───────────────────────────────────────────────────────────────
    log_section "Restore Complete"
    summary_line "Restored from:"   "$BACKUP_FILE"
    summary_line "App version:"     "$(grep '^app_version=' "$work_dir/version.txt" | cut -d= -f2)"
    summary_line "DB schema:"       "$(grep '^db_schema=' "$work_dir/version.txt" | cut -d= -f2)"
    printf "\n"
    log_success "Restore finished. Log: ${LOG_FILE}"
}

main "$@"
