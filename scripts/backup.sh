#!/usr/bin/env bash
# =============================================================================
# LOP — Backup script
# Usage: sudo ./backup.sh [--quiet] [--retention <days>]
#
# Creates a timestamped archive containing:
#   - PostgreSQL database dump
#   - Configuration (/etc/lop/lop.env)
#   - Version and schema metadata
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/var/log/lop/install.log"   # Append backup events to install log

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/os.sh"
source "$SCRIPT_DIR/lib/postgres.sh"
source "$SCRIPT_DIR/lib/version.sh"

QUIET=false
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    case "$arg" in
        --quiet)           QUIET=true ;;
        --retention)       : ;;   # next arg handled below
        --retention=*)     RETENTION_DAYS="${arg#--retention=}" ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
_info() { [[ "$QUIET" != "true" ]] && log_info "$@" || true; }
_success() { [[ "$QUIET" != "true" ]] && log_success "$@" || true; }

# =============================================================================
main() {
    require_root "$@"

    mkdir -p "$LOP_BACKUP_DIR" "$LOP_TMP_DIR"
    setup_tmp_dir

    # Verify LOP is installed
    [[ -f "$LOP_CONF_FILE" ]] \
        || abort "LOP configuration not found. Is LOP installed?"

    load_lop_env
    detect_os

    local ts
    ts="$(date +%Y-%m-%d_%H-%M-%S)"
    local work_dir="$LOP_TMP_DIR/backup_${ts}"
    local archive_name="lop_backup_${ts}.tar.gz"
    local archive_path="$LOP_BACKUP_DIR/${archive_name}"

    mkdir -p "$work_dir"
    _info "Creating backup: ${archive_name}"

    # ── 1. Database dump ──────────────────────────────────────────────────────
    pg_ensure_service
    local db_name
    db_name=$(grep '^LOP_DB_NAME=' "$LOP_CONF_FILE" | cut -d= -f2 || echo "lop_db")
    pg_dump_db "$db_name" "$work_dir/database.sql"

    # ── 2. Configuration ──────────────────────────────────────────────────────
    cp "$LOP_CONF_FILE" "$work_dir/lop.env"
    chmod 600 "$work_dir/lop.env"
    _info "Configuration backed up."

    # ── 3. Version metadata ───────────────────────────────────────────────────
    {
        echo "backup_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "app_version=$(version_get APP_VERSION "$LOP_APP_DIR/VERSION" 2>/dev/null || echo unknown)"
        echo "installer_version=$(version_get INSTALLER_VERSION "$LOP_APP_DIR/VERSION" 2>/dev/null || echo unknown)"
        echo "db_schema=$(alembic_current 2>/dev/null || echo unknown)"
        echo "git_hash=$(git -C "$LOP_APP_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
        echo "hostname=$(hostname -f 2>/dev/null || hostname)"
    } > "$work_dir/version.txt"

    # ── 4. Install info ───────────────────────────────────────────────────────
    [[ -f "$LOP_INSTALL_INFO" ]] && cp "$LOP_INSTALL_INFO" "$work_dir/install.info"

    # ── 5. Create archive ─────────────────────────────────────────────────────
    tar -czf "$archive_path" -C "$LOP_TMP_DIR" "backup_${ts}" 2>> "$LOG_FILE" \
        || abort "Failed to create backup archive. Check ${LOG_FILE}."
    chmod 600 "$archive_path"

    local archive_size
    archive_size=$(du -sh "$archive_path" | cut -f1)
    _success "Backup created: ${archive_path} (${archive_size})"

    # ── 6. Retention policy ───────────────────────────────────────────────────
    local deleted=0
    while IFS= read -r old_backup; do
        rm -f "$old_backup"
        (( deleted++ ))
    done < <(find "$LOP_BACKUP_DIR" -name 'lop_backup_*.tar.gz' \
                -mtime "+${RETENTION_DAYS}" -type f 2>/dev/null || true)

    (( deleted > 0 )) && _info "Pruned ${deleted} backup(s) older than ${RETENTION_DAYS} days."

    # Print the path for callers (update.sh captures this)
    echo "$archive_path"
}

main "$@"
