#!/usr/bin/env bash
# =============================================================================
# LOP — Uninstall script
# Usage: sudo ./uninstall.sh [--preserve-data] [--preserve-config] [--yes]
#
#   --preserve-data    keep /etc/lop and PostgreSQL database
#   --preserve-config  keep /etc/lop only, drop database
#   (no flags)         full removal after confirmation
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/tmp/lop_uninstall.log"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/os.sh"
source "$SCRIPT_DIR/lib/postgres.sh"
source "$SCRIPT_DIR/lib/systemd.sh"
source "$SCRIPT_DIR/lib/version.sh"

PRESERVE_DATA=false
PRESERVE_CONFIG=false

parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    case "$arg" in
        --preserve-data)   PRESERVE_DATA=true  ;;
        --preserve-config) PRESERVE_CONFIG=true ;;
    esac
done

# =============================================================================
main() {
    require_root "$@"

    touch "$LOG_FILE"

    log_section "LOP Uninstall"

    local version="unknown"
    if [[ -f "$LOP_APP_DIR/VERSION" ]]; then
        version=$(grep '^APP_VERSION=' "$LOP_APP_DIR/VERSION" | cut -d= -f2)
    fi

    log_warn "This will remove Linux Operations Portal version ${version}."

    # ── Show what will be removed ─────────────────────────────────────────────
    printf "\nThe following will be removed:\n"
    printf "  • Application:   %s\n" "$LOP_APP_DIR"
    printf "  • Virtual env:   %s/venv\n" "$LOP_APP_DIR"
    printf "  • Service:       lop-backend.service\n"
    printf "  • CLI symlink:   /usr/local/bin/lop\n"

    if [[ "$PRESERVE_DATA" == "true" ]]; then
        printf "\nThe following will be PRESERVED (--preserve-data):\n"
        printf "  • Configuration: %s\n" "$LOP_CONF_DIR"
        printf "  • Database:      lop_db (PostgreSQL)\n"
        printf "  • Logs:          %s\n" "$LOP_LOG_DIR"
        printf "  • Backups:       %s\n" "$LOP_BACKUP_DIR"
    elif [[ "$PRESERVE_CONFIG" == "true" ]]; then
        printf "\nThe following will be PRESERVED (--preserve-config):\n"
        printf "  • Configuration: %s\n" "$LOP_CONF_DIR"
        printf "\nThe following will also be removed:\n"
        printf "  • Database:      lop_db (PostgreSQL)\n"
    else
        printf "  • Configuration: %s\n" "$LOP_CONF_DIR"
        printf "  • Database:      lop_db (PostgreSQL)\n"
        printf "\nOptionally removed (asked separately):\n"
        printf "  • Logs:          %s\n" "$LOP_LOG_DIR"
        printf "  • Backups:       %s\n" "$LOP_BACKUP_DIR"
        printf "  • Runtime data:  %s\n" "$LOP_DATA_DIR"
    fi

    printf "\n"
    confirm "Proceed with uninstallation?" \
        || abort "Uninstall cancelled by user."

    # Create a safety backup before removing anything (non-fatal if it fails)
    if [[ -f "$LOP_CONF_FILE" ]] && [[ -d "$LOP_APP_DIR" ]]; then
        log_info "Creating pre-uninstall safety backup..."
        if "$SCRIPT_DIR/backup.sh" --quiet >> "$LOG_FILE" 2>&1; then
            log_success "Pre-uninstall backup saved to ${LOP_BACKUP_DIR}"
        else
            log_warn "Pre-uninstall backup failed (non-fatal). Proceeding with uninstall."
        fi
    fi

    detect_os

    # ── 1. Stop and disable service ───────────────────────────────────────────
    log_step "Stopping and disabling lop-backend..."
    systemd_stop "$LOP_BACKEND_SERVICE"
    if systemd_service_exists "$LOP_BACKEND_SERVICE" 2>/dev/null; then
        systemctl disable "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 || true
        rm -f "$LOP_BACKEND_UNIT"
        log_info "Removed service unit: lop-backend.service"
    fi
    systemctl daemon-reload >> "$LOG_FILE" 2>&1 || true

    # ── 2. Remove CLI symlink ─────────────────────────────────────────────────
    if [[ -L /usr/local/bin/lop ]]; then
        rm -f /usr/local/bin/lop
        log_info "Removed CLI symlink: /usr/local/bin/lop"
    fi

    # ── 3. Remove application directory ──────────────────────────────────────
    if [[ -d "$LOP_APP_DIR" ]]; then
        rm -rf "$LOP_APP_DIR"
        log_success "Removed application: ${LOP_APP_DIR}"
    fi

    # ── 4. Database removal ───────────────────────────────────────────────────
    if [[ "$PRESERVE_DATA" != "true" ]]; then
        local remove_db=true
        if [[ "$PRESERVE_CONFIG" != "true" ]]; then
            # Full uninstall — confirm DB drop explicitly
            if [[ "$YES_ALL" != "true" ]]; then
                printf "\n%sWARNING: This will permanently delete the LOP database.%s\n" \
                    "$CLR_RED" "$CLR_RESET"
                confirm "Drop the PostgreSQL database (lop_db) and user (lop_user)?" \
                    || remove_db=false
            fi
        fi

        if [[ "$remove_db" == "true" ]]; then
            if pg_detect 2>/dev/null && pg_ensure_service 2>/dev/null; then
                local db_name
                db_name=$(grep '^LOP_DB_NAME=' "$LOP_CONF_FILE" 2>/dev/null \
                    | cut -d= -f2 || echo "lop_db")
                local db_user
                db_user=$(grep '^LOP_DB_USER=' "$LOP_CONF_FILE" 2>/dev/null \
                    | cut -d= -f2 || echo "lop_user")

                pg_execute "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db_name}';" \
                    2>/dev/null || true
                if pg_execute "DROP DATABASE IF EXISTS ${db_name};" 2>/dev/null; then
                    log_success "Dropped database: ${db_name}"
                else
                    log_warn "Could not drop database '${db_name}' (may require manual cleanup)."
                fi
                if pg_execute "DROP ROLE IF EXISTS ${db_user};" 2>/dev/null; then
                    log_success "Dropped role: ${db_user}"
                else
                    log_warn "Could not drop role '${db_user}' (may require manual cleanup)."
                fi
            else
                log_warn "PostgreSQL not running — skipping database drop."
            fi
        fi
    fi

    # ── 5. Configuration removal ──────────────────────────────────────────────
    if [[ "$PRESERVE_DATA" != "true" ]] && [[ "$PRESERVE_CONFIG" != "true" ]]; then
        if [[ -d "$LOP_CONF_DIR" ]]; then
            rm -rf "$LOP_CONF_DIR"
            log_success "Removed configuration: ${LOP_CONF_DIR}"
        fi
    fi

    # ── 6. Optional: logs, backups, runtime data ──────────────────────────────
    if [[ "$PRESERVE_DATA" != "true" ]]; then
        local remove_logs=false remove_backups=false remove_data=false

        if [[ "$YES_ALL" == "true" ]]; then
            remove_logs=true; remove_backups=true; remove_data=true
        else
            confirm "Remove application logs (${LOP_LOG_DIR})?" && remove_logs=true || true
            confirm "Remove backup archives (${LOP_BACKUP_DIR})?" && remove_backups=true || true
            confirm "Remove runtime data (${LOP_DATA_DIR})?" && remove_data=true || true
        fi

        if [[ "$remove_logs" == "true" ]]; then
            rm -rf "$LOP_LOG_DIR"
            log_success "Removed logs: ${LOP_LOG_DIR}"
        fi
        if [[ "$remove_backups" == "true" ]]; then
            rm -rf "$LOP_BACKUP_DIR"
            log_success "Removed backups: ${LOP_BACKUP_DIR}"
        fi
        if [[ "$remove_data" == "true" ]]; then
            rm -rf "$LOP_DATA_DIR"
            log_success "Removed runtime data: ${LOP_DATA_DIR}"
        fi
    fi

    # ── 7. Remove lop system user ─────────────────────────────────────────────
    if id lop &>/dev/null; then
        userdel lop >> "$LOG_FILE" 2>&1 && log_info "Removed system user: lop"
    fi

    # ── 8. Summary ────────────────────────────────────────────────────────────
    log_section "Uninstall Complete"
    log_success "Linux Operations Portal ${version} has been removed."

    if [[ "$PRESERVE_DATA" == "true" ]]; then
        log_info "Configuration and database preserved at: ${LOP_CONF_DIR}"
        log_info "To reinstall and reuse your data: sudo ./install.sh"
    fi
    printf "\n"
}

main "$@"
