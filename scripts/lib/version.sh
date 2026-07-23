#!/usr/bin/env bash
# =============================================================================
# LOP — Version tracking and checksum helpers
# Source this file; do not execute it directly.
# =============================================================================

# version_get <key> [file]
# Reads a key=value from the VERSION file.
# Searches installed app first, then the source repo (for pre-install use).
version_get() {
    local key="$1"
    local file="${2:-}"

    if [[ -z "$file" ]]; then
        # Try installed location first
        if [[ -f "${LOP_APP_DIR}/VERSION" ]]; then
            file="${LOP_APP_DIR}/VERSION"
        else
            # Fall back to source repo (script is in scripts/lib/)
            local src_dir
            src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
            file="${src_dir}/VERSION"
        fi
    fi

    [[ -f "$file" ]] || { echo "unknown"; return 0; }
    local val
    # grep exits 1 when the key is absent; || true prevents set -e + pipefail
    # from silently aborting the caller.  The ${val:-unknown} fallback handles
    # the empty-string result when the key is missing.
    val=$(grep "^${key}=" "$file" | cut -d= -f2- | tr -d '[:space:]' || true)
    echo "${val:-unknown}"
}

# version_set <key> <value> [file]
# Updates (or inserts) a key in the VERSION file.
version_set() {
    local key="$1" value="$2" file="${3:-${LOP_APP_DIR}/VERSION}"
    [[ -f "$file" ]] || touch "$file"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# alembic_current
# Returns the current deployed Alembic revision for the running DB.
#
# Implementation: queries the alembic_version table directly via psql — this
# is faster, has no Flask startup cost, and works even when the application
# venv or config is partially set up.  Falls back to the Flask/Alembic CLI
# only when psql is unavailable or the direct query fails.
alembic_current() {
    # Prefer a direct database query when the config and psql are available.
    if [[ -f "$LOP_CONF_FILE" ]] && cmd_exists psql; then
        local db_url result
        # Use cut -d= -f2- so that '=' characters inside the URL are preserved.
        # || true prevents set -e + pipefail from silently aborting when grep
        # finds no match (DATABASE_URL absent from the config file).
        db_url=$(grep '^DATABASE_URL=' "$LOP_CONF_FILE" | cut -d= -f2- || true)
        if [[ -n "$db_url" ]]; then
            result=$(psql -tAq "$db_url" \
                -c "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1;" \
                2>/dev/null | tr -d '[:space:]' || true)
            if [[ -n "$result" ]]; then
                echo "$result"
                return 0
            fi
        fi
    fi
    # Fallback: use Flask/Alembic CLI (requires venv and full app dependencies).
    lop_flask db current 2>/dev/null \
        | grep -oP '[0-9a-f]{12}' | awk 'NR==1{print}' \
        || echo "unknown"
}

# alembic_head
# Returns the latest revision available in the codebase.
alembic_head() {
    lop_flask db heads 2>/dev/null \
        | grep -oP '[0-9a-f]{12}' | awk 'NR==1{print}' \
        || echo "unknown"
}

# alembic_needs_upgrade
# Returns 0 (true) if the DB is behind the codebase head, or if the current
# revision is unknown (empty alembic_version table = fresh DB that needs its
# first migration run).
alembic_needs_upgrade() {
    local current head
    current=$(alembic_current)
    head=$(alembic_head)
    # "unknown" current means the alembic_version table is empty or
    # unreachable — either way, we should attempt an upgrade.
    [[ "$current" == "unknown" ]] && return 0
    [[ "$current" != "$head"  ]] && return 0
    return 1
}

# ── Automatic migration runner ────────────────────────────────────────────────
#
# MIGRATION_APPLIED — set to "true" by run_migrations_verbose when at least
# one revision was actually applied; "false" when already at head.
MIGRATION_APPLIED=false

# MIGRATION_BACKUP_FILE — set to the absolute path of the pre-migration
# database backup file by _migrate_pre_backup(); empty when no backup was made.
# Callers (update.sh abort handler, error messages) read this to tell
# administrators where to find the recovery point.
MIGRATION_BACKUP_FILE=""

# run_migrations_verbose
# Self-contained, idempotent database migration runner for use by both
# install.sh and update.sh.  Performs these steps in order:
#
#   1. Verify the virtual environment / Flask binary exists.
#   2. Confirm the database is reachable (via psql if available).
#   3. Read the current Alembic revision from the database.
#   4. Read the codebase head from migration files.
#   5. Short-circuit with success if already at head (idempotent).
#   6. Create a pre-migration database backup (only when migrations are pending).
#   7. Write the pending migration history to the log.
#   8. Run `flask db upgrade` and capture full output.
#   9. Classify failures with specific, actionable error messages.
#  10. Confirm the post-migration revision.
#  11. Set MIGRATION_APPLIED=true if new revisions were applied.
#
# Returns 0 on success (including already-at-head), non-zero on failure.
# On failure the caller is responsible for rollback / abort.
run_migrations_verbose() {
    MIGRATION_APPLIED=false
    MIGRATION_BACKUP_FILE=""

    local flask_bin="$LOP_VENV_DIR/bin/flask"

    log_section "Database Migrations"

    # ── 1. Verify the virtual environment is installed ────────────────────────
    if [[ ! -x "$flask_bin" ]]; then
        log_error "Flask binary not found at: ${flask_bin}"
        log_error "The LOP virtual environment is not installed or is broken."
        log_error ""
        log_error "Fix:  sudo lop repair"
        return 1
    fi

    # ── 2. Verify database connectivity ──────────────────────────────────────
    log_step "Checking database connectivity..."
    local db_url db_host
    db_url=$(grep '^DATABASE_URL=' "${LOP_CONF_FILE}" 2>/dev/null | cut -d= -f2- || true)

    if [[ -z "$db_url" ]]; then
        log_error "DATABASE_URL is not set in ${LOP_CONF_FILE}."
        log_error "The configuration file may be missing or incomplete."
        log_error ""
        log_error "Fix:  sudo lop repair"
        return 1
    fi

    # Extract host for display (mask credentials)
    db_host=$(printf '%s' "$db_url" | grep -oP '@[^/:]+' | head -1 | tr -d '@' || echo "unknown")

    if cmd_exists psql; then
        local pg_rc=0
        psql -tAq "$db_url" -c "SELECT 1;" >/dev/null 2>&1 || pg_rc=$?
        if (( pg_rc != 0 )); then
            log_error "Cannot connect to the database (host: ${db_host})."
            log_error ""
            log_error "Possible causes:"
            log_error "  • PostgreSQL is not running:"
            log_error "      sudo systemctl status postgresql"
            log_error "      sudo systemctl start  postgresql"
            log_error "  • Wrong credentials — verify DATABASE_URL in ${LOP_CONF_FILE}"
            log_error "  • Host/port unreachable — check network or firewall rules"
            return 1
        fi
        log_success "Database connection verified (host: ${db_host})."
    else
        log_warn "psql not available — skipping pre-flight connectivity check."
        log_warn "If the database is unreachable, the upgrade step will fail below."
    fi

    # ── 3. Read the current DB revision ──────────────────────────────────────
    log_step "Reading Alembic revision..."
    local pre_rev
    pre_rev=$(alembic_current 2>/dev/null || echo "unknown")
    log_info "  Current DB revision : ${pre_rev}"

    # ── 4. Read the codebase head ─────────────────────────────────────────────
    local head_rev
    head_rev=$(alembic_head 2>/dev/null || echo "unknown")
    log_info "  Codebase head       : ${head_rev}"

    # ── 5. Short-circuit when already at head (idempotent) ────────────────────
    if [[ "$pre_rev" == "$head_rev" ]] && [[ "$pre_rev" != "unknown" ]]; then
        log_success "Database schema is already at head (${pre_rev}) — no migrations needed."
        return 0
    fi

    if [[ "$pre_rev" == "unknown" ]] && [[ "$head_rev" == "unknown" ]]; then
        log_warn "Cannot determine Alembic revision — attempting upgrade anyway."
    fi

    # ── 6. Pre-migration database backup ─────────────────────────────────────
    # Only taken when migrations are actually pending (step 5 did not return).
    # Non-fatal: a backup failure emits a warning but does not block the migration.
    _migrate_pre_backup "$db_url" "$pre_rev"

    # ── 7. Write pending migration history to log ─────────────────────────────
    log_step "Pending migrations: ${pre_rev} → ${head_rev}"
    {
        printf "\n=== Pending migration history (pre-upgrade) ===\n"
        (
            cd "$LOP_APP_DIR"
            load_lop_env
            FLASK_APP=run.py FLASK_ENV=production "$flask_bin" db history \
                --rev-range "${pre_rev}:${head_rev}" 2>&1 || true
        )
        printf "=== end pending migrations ===\n\n"
    } >> "$LOG_FILE" 2>/dev/null || true

    # ── 8. Run flask db upgrade ───────────────────────────────────────────────
    log_step "Applying migrations..."
    local mig_out mig_rc=0
    mig_out=$(
        cd "$LOP_APP_DIR"
        load_lop_env
        FLASK_APP=run.py FLASK_ENV=production "$flask_bin" db upgrade 2>&1
    ) || mig_rc=$?

    # Always write full output to the log — admins can use `lop logs` to review
    {
        printf "\n=== flask db upgrade output (exit=%s) ===\n" "$mig_rc"
        printf "%s\n" "$mig_out"
        printf "=== end flask db upgrade ===\n\n"
    } >> "$LOG_FILE" 2>/dev/null || true

    # ── 9. Handle failure ─────────────────────────────────────────────────────
    if (( mig_rc != 0 )); then
        # "Already up to date" is not a real failure
        if echo "$mig_out" | grep -qiE 'already up.to.date|up to date'; then
            log_success "Database schema is already up to date."
            return 0
        fi
        _migrate_classify_error "$mig_out"
        return 1
    fi

    # ── 10. Confirm new revision ───────────────────────────────────────────────
    local post_rev
    post_rev=$(alembic_current 2>/dev/null || echo "unknown")
    log_info "  New DB revision     : ${post_rev}"

    # ── 11. Report and set MIGRATION_APPLIED ──────────────────────────────────
    if [[ "$post_rev" != "$pre_rev" ]]; then
        log_success "Migrations applied successfully."
        log_info "  Previous revision   : ${pre_rev}"
        log_info "  New revision        : ${post_rev}"
        [[ -n "$MIGRATION_BACKUP_FILE" ]] && \
            log_info "  Backup              : ${MIGRATION_BACKUP_FILE}"
        MIGRATION_APPLIED=true
    elif [[ "$pre_rev" == "unknown" ]]; then
        log_success "Migrations applied (revision now: ${post_rev})."
        [[ -n "$MIGRATION_BACKUP_FILE" ]] && \
            log_info "  Backup              : ${MIGRATION_BACKUP_FILE}"
        MIGRATION_APPLIED=true
    else
        log_success "Database schema is up to date (${post_rev})."
    fi

    return 0
}

# _migrate_pre_backup <db_url> <pre_rev>
# Creates a gzip-compressed pg_dump of the LOP database immediately before
# migrations are applied.  Only called when there are pending migrations.
#
# Sets MIGRATION_BACKUP_FILE to the backup path on success; leaves it empty
# on failure (backup failures are non-fatal — they emit a warning and continue).
#
# The backup is stored as:
#   $LOP_BACKUP_DIR/pre_migration_<YYYYMMDD_HHMMSS>_<rev8>.sql.gz
# and is chmod 600 (root-readable only, because it may contain data).
_migrate_pre_backup() {
    local db_url="$1" pre_rev="$2"

    # Require pg_dump on PATH
    if ! cmd_exists pg_dump; then
        log_warn "pg_dump not found — skipping pre-migration backup."
        log_warn "Install the postgresql-client package to enable automatic backups."
        return 0
    fi

    ensure_dir "$LOP_BACKUP_DIR" "root:root" "750"

    local ts rev_tag backup_file
    ts=$(date +%Y%m%d_%H%M%S)
    rev_tag="${pre_rev:0:8}"
    [[ "$rev_tag" == "unknown" ]] && rev_tag="initial"
    backup_file="${LOP_BACKUP_DIR}/pre_migration_${ts}_${rev_tag}.sql.gz"

    log_step "Creating pre-migration database backup..."

    # pg_dump accepts a connection URI (PostgreSQL 9.2+); credentials are
    # extracted from the URL, avoiding PGPASSWORD in the environment.
    # stderr goes to the log; stdout is piped through gzip into a temp file
    # that is atomically renamed on success so a partial write is never visible.
    local dump_rc=0
    pg_dump "$db_url" 2>> "$LOG_FILE" \
        | gzip > "${backup_file}.tmp" \
        || dump_rc=$?

    if (( dump_rc != 0 )) || [[ ! -s "${backup_file}.tmp" ]]; then
        rm -f "${backup_file}.tmp" 2>/dev/null || true
        log_warn "Pre-migration backup FAILED (pg_dump exit code: ${dump_rc})."
        log_warn "The migration will proceed without a backup."
        log_warn "Consider running 'sudo lop backup' manually before retrying."
        {
            printf "\n[WARN] Pre-migration pg_dump failed (exit=%s) for URL: %s\n" \
                "$dump_rc" "${db_url%%:*}://...(masked)"
        } >> "$LOG_FILE" 2>/dev/null || true
        return 0   # Non-fatal
    fi

    mv "${backup_file}.tmp" "$backup_file"
    chmod 600 "$backup_file"

    local size
    size=$(du -sh "$backup_file" 2>/dev/null | cut -f1 || echo "?")
    MIGRATION_BACKUP_FILE="$backup_file"

    log_success "Pre-migration backup created:"
    log_info "  File    : ${backup_file}"
    log_info "  Size    : ${size}"
    log_info "  Schema  : ${pre_rev}"
    log_info "  Restore : sudo lop restore ${backup_file}"
}

# _migrate_classify_error <output_string>
# Internal helper: parse migration failure output and emit a specific,
# actionable error message for each known failure mode.
_migrate_classify_error() {
    local out="$1"

    log_error "Database migration FAILED."
    log_error ""

    if echo "$out" | grep -qiE 'could not connect|connection refused|no route to host|network.*unreachable|the connection.*closed'; then
        log_error "Cause: database connection lost during upgrade."
        log_error ""
        log_error "Verify PostgreSQL is running and accepting connections:"
        log_error "  sudo systemctl status postgresql"
        log_error "  sudo journalctl -u postgresql -n 30"

    elif echo "$out" | grep -qiE 'authentication failed|password authentication|role.*does not exist|access denied'; then
        log_error "Cause: database authentication rejected."
        log_error ""
        log_error "Check DATABASE_URL credentials in: ${LOP_CONF_FILE}"
        log_error "Ensure the LOP database user exists and has access:"
        log_error "  sudo -u postgres psql -c \"\\du\""

    elif echo "$out" | grep -qiE 'multiple.*heads|more than one.*head|detected two heads|use.*merge'; then
        log_error "Cause: conflicting migration heads — two branches diverged."
        log_error ""
        log_error "To resolve, create a merge migration in the source checkout:"
        log_error "  flask db merge heads -m 'merge diverged branches'"
        log_error "Commit the resulting file, then re-deploy."

    elif echo "$out" | grep -qiE 'FileNotFoundError|No such file or directory|can.t find.*script|no migration file'; then
        log_error "Cause: migration script file is missing from the deployment."
        log_error ""
        log_error "Ensure app/migrations/versions/ was fully synced to ${LOP_APP_DIR}."
        log_error "Re-run the update:  sudo lop update"

    elif echo "$out" | grep -qiE 'ProgrammingError|relation.*already exists|column.*already exists|duplicate.*object'; then
        log_error "Cause: schema conflict — the database contains objects that"
        log_error "       conflict with what the migration expects to create."
        log_error ""
        log_error "This can occur after a partially-applied previous migration."
        log_error "Inspect the database to resolve the conflict, then retry."
        log_error "Log details: ${LOG_FILE}"

    elif echo "$out" | grep -qiE 'OperationalError.*disk|disk.*full|no space left'; then
        log_error "Cause: disk full — the database ran out of storage during migration."
        log_error ""
        log_error "Free disk space and retry:  sudo lop update"

    else
        log_error "Cause: unknown (see full output below)."
    fi

    log_error ""
    log_error "── Full migration output ─────────────────────────────────"
    while IFS= read -r line; do
        log_error "  ${line}"
    done <<< "$out"
    log_error "──────────────────────────────────────────────────────────"
    log_error "Full log: ${LOG_FILE}"
    if [[ -n "${MIGRATION_BACKUP_FILE:-}" ]]; then
        log_error ""
        log_error "Pre-migration backup: ${MIGRATION_BACKUP_FILE}"
        log_error "Restore:  sudo lop restore ${MIGRATION_BACKUP_FILE}"
    fi
}

# ── Checksum helpers ──────────────────────────────────────────────────────────

# checksum_save <file_path> <name>
# Saves the md5 of <file_path> to $LOP_CHECKSUMS_DIR/<name>.md5
checksum_save() {
    local file="$1" name="$2"
    ensure_dir "$LOP_CHECKSUMS_DIR" "root:root" "700"
    if [[ -f "$file" ]]; then
        md5sum "$file" > "${LOP_CHECKSUMS_DIR}/${name}.md5"
    fi
}

# checksum_changed <file_path> <name>
# Returns 0 (true) if the file has changed since the last save, or no saved checksum exists.
checksum_changed() {
    local file="$1" name="$2"
    local saved="${LOP_CHECKSUMS_DIR}/${name}.md5"
    [[ -f "$saved" ]] || return 0   # no record → treat as changed
    [[ -f "$file"  ]] || return 0   # file missing → treat as changed
    # md5sum --check compares stored digest to current file
    md5sum --check --status "$saved" 2>/dev/null
    local rc=$?
    [[ $rc -ne 0 ]]   # rc=0 means match; invert: return 0 if changed
}

# checksums_save_all
# Saves checksums for all tracked files.
checksums_save_all() {
    checksum_save "${LOP_APP_DIR}/requirements.txt"  "requirements"
    local pkg_json="${LOP_APP_DIR}/package.json"
    if [[ -f "$pkg_json" ]]; then checksum_save "$pkg_json" "package_json"; fi
    # Save current alembic head
    ensure_dir "$LOP_CHECKSUMS_DIR" "root:root" "700"
    alembic_head > "${LOP_CHECKSUMS_DIR}/alembic_head.txt" 2>/dev/null || true
}

# alembic_head_changed
# Returns 0 (true) if new migration files exist since last save.
alembic_head_changed() {
    local saved="${LOP_CHECKSUMS_DIR}/alembic_head.txt"
    [[ -f "$saved" ]] || return 0
    local saved_head
    saved_head=$(cat "$saved")
    local current_head
    current_head=$(alembic_head)
    [[ "$saved_head" != "$current_head" ]]
}

# ── Install metadata ──────────────────────────────────────────────────────────

# install_info_write
# Writes installation metadata to $LOP_INSTALL_INFO (key=value format).
install_info_write() {
    ensure_dir "$LOP_DATA_DIR" "root:root" "755"
    local mode="${1:-fresh}"
    local source="${INSTALL_SOURCE:-unknown}"
    local source_url="${INSTALL_SOURCE_URL:-unknown}"
    local source_branch="${INSTALL_SOURCE_BRANCH:-unknown}"
    local version
    version=$(version_get "APP_VERSION")

    cat > "$LOP_INSTALL_INFO" <<EOF
# LOP installation metadata — do not edit manually
install_mode=${mode}
install_source=${source}
install_source_url=${source_url}
install_source_branch=${source_branch}
install_source_dir=${INSTALL_SOURCE_DIR}
install_version=${version}
install_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)
install_host=$(hostname -f 2>/dev/null || hostname)
install_user=${SUDO_USER:-root}
EOF
    chmod 644 "$LOP_INSTALL_INFO"
}

# install_info_read <key>
# Reads a value from $LOP_INSTALL_INFO.
install_info_read() {
    local key="$1"
    [[ -f "$LOP_INSTALL_INFO" ]] || { echo "unknown"; return 0; }
    # grep exits 1 when the key is absent (e.g. older installs that predate a
    # new metadata field).  || true prevents set -e + pipefail from silently
    # killing the caller.  ${val:-unknown} handles the empty-string result.
    local val
    val=$(grep "^${key}=" "$LOP_INSTALL_INFO" | cut -d= -f2- | tr -d '[:space:]' || true)
    echo "${val:-unknown}"
}

# install_info_update <key> <value>
install_info_update() {
    local key="$1" value="$2"
    [[ -f "$LOP_INSTALL_INFO" ]] || return 0
    if grep -q "^${key}=" "$LOP_INSTALL_INFO"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$LOP_INSTALL_INFO"
    else
        echo "${key}=${value}" >> "$LOP_INSTALL_INFO"
    fi
}

# ── Install source detection ─────────────────────────────────────────────────

INSTALL_SOURCE=""
INSTALL_SOURCE_URL=""
INSTALL_SOURCE_BRANCH=""
INSTALL_SOURCE_DIR=""

# detect_install_source <directory>
# Determines how the app was installed. Sets INSTALL_SOURCE, INSTALL_SOURCE_URL,
# INSTALL_SOURCE_BRANCH.
detect_install_source() {
    local dir="$1"

    # Always record the filesystem path of the source checkout so that
    # update.sh can locate it for rsync even when the git remote URL is
    # stored as install_source_url.
    INSTALL_SOURCE_DIR="$(realpath "$dir" 2>/dev/null || echo "$dir")"

    if [[ -d "${dir}/.git" ]]; then
        INSTALL_SOURCE="git"
        INSTALL_SOURCE_URL=$(git -C "$dir" remote get-url origin 2>/dev/null || echo "unknown")
        INSTALL_SOURCE_BRANCH=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    elif [[ -f "${dir}/.lop-archive-source" ]]; then
        INSTALL_SOURCE="archive"
        INSTALL_SOURCE_URL=$(cat "${dir}/.lop-archive-source" 2>/dev/null || echo "unknown")
        INSTALL_SOURCE_BRANCH=""
    else
        INSTALL_SOURCE="local"
        INSTALL_SOURCE_URL="$(realpath "$dir" 2>/dev/null || echo "$dir")"
        INSTALL_SOURCE_BRANCH=""
    fi

    log_info "Install source: ${INSTALL_SOURCE} (${INSTALL_SOURCE_URL})"
}
