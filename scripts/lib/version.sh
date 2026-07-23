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
# Returns 0 (true) if the DB is behind the codebase head.
alembic_needs_upgrade() {
    local current head
    current=$(alembic_current)
    head=$(alembic_head)
    [[ "$current" != "$head" ]] && [[ "$current" != "unknown" ]]
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
