#!/usr/bin/env bash
# =============================================================================
# LOP — PostgreSQL detection, setup, and management helpers
# Source this file; do not execute it directly.
# =============================================================================

PG_FOUND_VERSION=""
PG_FOUND_SERVICE=""
PG_MIN_VERSION=14

# _pg_probe_version_from_system
# Called when the detected service name has no embedded version number
# (i.e. "postgresql" rather than "postgresql-16").  Tries multiple sources
# to determine the installed major version.
_pg_probe_version_from_system() {
    local raw=""

    # Binary in PATH (OS-default packages place postgres in /usr/bin)
    if cmd_exists postgres; then
        raw=$(postgres --version 2>/dev/null | grep -oP '\d+\.\d+' | awk 'NR==1{print}')
    fi

    # psql when postgres binary is not in PATH
    if [[ -z "$raw" ]] && cmd_exists psql; then
        raw=$(psql --version 2>/dev/null | grep -oP '\d+\.\d+' | awk 'NR==1{print}')
    fi

    # RPM database (RHEL/Rocky/AlmaLinux)
    if [[ -z "$raw" ]] && cmd_exists rpm; then
        local rpm_ver
        rpm_ver=$(rpm -q postgresql-server 2>/dev/null | grep -oP '\d+\.\d+' | awk 'NR==1{print}')
        [[ -n "$rpm_ver" ]] && raw="$rpm_ver"
    fi

    # dpkg (Ubuntu/Debian)
    if [[ -z "$raw" ]] && cmd_exists dpkg; then
        local dpkg_ver
        dpkg_ver=$(dpkg -l 'postgresql-[0-9]*' 2>/dev/null \
                     | awk '/^ii/{print $2; exit}' \
                     | grep -oP '(?<=-)\d+$')
        [[ -n "$dpkg_ver" ]] && raw="${dpkg_ver}.0"
    fi

    # PG_VERSION file in the known data directory (last resort)
    if [[ -z "$raw" ]] && [[ -f "${PG_DATA_DIR}/PG_VERSION" ]]; then
        local pg_major
        pg_major=$(cat "${PG_DATA_DIR}/PG_VERSION" 2>/dev/null | tr -d '[:space:]')
        [[ -n "$pg_major" ]] && raw="${pg_major}.0"
    fi

    if [[ -n "$raw" ]]; then
        PG_FOUND_VERSION="${raw%%.*}"
        # Debian/Ubuntu versioned data directory layout
        if [[ -d "/var/lib/postgresql/${PG_FOUND_VERSION}/main" ]]; then
            PG_DATA_DIR="/var/lib/postgresql/${PG_FOUND_VERSION}/main"
            PG_HBA_CONF="/etc/postgresql/${PG_FOUND_VERSION}/main/pg_hba.conf"
        fi
    fi
}

# pg_detect
# Detects an installed PostgreSQL server and populates:
#   PG_FOUND_SERVICE  — the exact systemd service name  (e.g. postgresql-16)
#   PG_FOUND_VERSION  — the installed major version      (e.g. 16)
#   PG_SERVICE        — alias kept in sync with PG_FOUND_SERVICE
#   PG_DATA_DIR / PG_HBA_CONF — updated for versioned layouts
#
# Detection order:
#   1. systemd unit-file scan — catches OS-default AND PGDG versioned packages
#      without relying on the PostgreSQL binaries being in PATH.
#   2. pg_lsclusters — Debian/Ubuntu cluster manager.
#   3. postgres binary in PATH — legacy fallback.
#   4. pg_ctl binary in PATH — last resort.
pg_detect() {
    PG_FOUND_VERSION=""
    PG_FOUND_SERVICE=""

    # ── Method 1: systemd unit-file scan ─────────────────────────────────────
    # 'systemctl list-unit-files' shows ALL registered units regardless of
    # whether they are active.  This is the only method that reliably finds
    # PGDG versioned packages (e.g. postgresql-16) whose binaries live in
    # /usr/pgsql-16/bin/ and are NOT added to the system PATH by default.
    local svc_candidates=(
        postgresql      # OS-default on Rocky/RHEL AppStream and Ubuntu/Debian
        postgresql-17   # PGDG versioned — check newest first
        postgresql-16
        postgresql-15
        postgresql-14
        postgresql-13
    )
    for svc in "${svc_candidates[@]}"; do
        if systemctl list-unit-files "${svc}.service" 2>/dev/null \
                | grep -q "^${svc}\.service"; then
            PG_FOUND_SERVICE="$svc"
            PG_SERVICE="$svc"

            if [[ "$svc" =~ ^postgresql-([0-9]+)$ ]]; then
                # Versioned PGDG service — version is in the name
                PG_FOUND_VERSION="${BASH_REMATCH[1]}"
                if [[ -d "/var/lib/pgsql/${PG_FOUND_VERSION}/data" ]]; then
                    PG_DATA_DIR="/var/lib/pgsql/${PG_FOUND_VERSION}/data"
                    PG_HBA_CONF="/var/lib/pgsql/${PG_FOUND_VERSION}/data/pg_hba.conf"
                fi
            else
                # 'postgresql' (no version suffix) — probe version separately
                _pg_probe_version_from_system
            fi
            return 0
        fi
    done

    # ── Method 2: pg_lsclusters (Debian/Ubuntu) ───────────────────────────────
    if cmd_exists pg_lsclusters; then
        local ver_line
        ver_line=$(pg_lsclusters 2>/dev/null | awk 'NR>1 {print $1; exit}')
        if [[ -n "$ver_line" ]]; then
            PG_FOUND_VERSION="$ver_line"
            PG_FOUND_SERVICE="postgresql@${ver_line}-main"
            PG_SERVICE="$PG_FOUND_SERVICE"
            PG_DATA_DIR="/var/lib/postgresql/${ver_line}/main"
            PG_HBA_CONF="/etc/postgresql/${ver_line}/main/pg_hba.conf"
            return 0
        fi
    fi

    # ── Method 3: postgres binary in PATH ────────────────────────────────────
    if cmd_exists postgres; then
        local raw
        raw=$(postgres --version 2>/dev/null | grep -oP '\d+\.\d+' | awk 'NR==1{print}')
        PG_FOUND_VERSION="${raw%%.*}"
        if [[ -n "$PG_FOUND_VERSION" ]] && \
           [[ -d "/var/lib/pgsql/${PG_FOUND_VERSION}/data" ]]; then
            PG_DATA_DIR="/var/lib/pgsql/${PG_FOUND_VERSION}/data"
            PG_HBA_CONF="/var/lib/pgsql/${PG_FOUND_VERSION}/data/pg_hba.conf"
            PG_FOUND_SERVICE="postgresql-${PG_FOUND_VERSION}"
            PG_SERVICE="$PG_FOUND_SERVICE"
        fi
        PG_FOUND_SERVICE="${PG_FOUND_SERVICE:-$PG_SERVICE}"
        return 0
    fi

    # ── Method 4: pg_ctl binary in PATH ──────────────────────────────────────
    if cmd_exists pg_ctl; then
        local raw
        raw=$(pg_ctl --version 2>/dev/null | grep -oP '\d+\.\d+' | awk 'NR==1{print}')
        PG_FOUND_VERSION="${raw%%.*}"
        if [[ -n "$PG_FOUND_VERSION" ]] && \
           [[ -d "/var/lib/pgsql/${PG_FOUND_VERSION}/data" ]]; then
            PG_DATA_DIR="/var/lib/pgsql/${PG_FOUND_VERSION}/data"
            PG_HBA_CONF="/var/lib/pgsql/${PG_FOUND_VERSION}/data/pg_hba.conf"
            PG_FOUND_SERVICE="postgresql-${PG_FOUND_VERSION}"
            PG_SERVICE="$PG_FOUND_SERVICE"
        fi
        PG_FOUND_SERVICE="${PG_FOUND_SERVICE:-$PG_SERVICE}"
        return 0
    fi

    return 1
}

# pg_version_ok
# Returns 0 if PG_FOUND_VERSION >= PG_MIN_VERSION.
pg_version_ok() {
    [[ -n "$PG_FOUND_VERSION" ]] || return 1
    (( ${PG_FOUND_VERSION%%.*} >= PG_MIN_VERSION ))
}

# pg_ensure_installed
# Verifies PostgreSQL is installed and compatible; installs if missing.
# Never replaces an existing compatible installation.
pg_ensure_installed() {
    log_section "PostgreSQL"

    if pg_detect; then
        if pg_version_ok; then
            log_success "PostgreSQL ${PG_FOUND_VERSION} detected (service: ${PG_FOUND_SERVICE}) — meets minimum (${PG_MIN_VERSION}+)."
            return 0
        else
            abort "PostgreSQL ${PG_FOUND_VERSION} is installed (service: ${PG_FOUND_SERVICE}) but LOP requires PostgreSQL ${PG_MIN_VERSION}+.
On Rocky/RHEL, enable a newer AppStream module and reinstall:
  sudo dnf module enable postgresql:16 -y
  sudo dnf install postgresql-server -y
  sudo $0
On Ubuntu/Debian:
  sudo apt-get install postgresql-16
  sudo $0"
        fi
    fi

    log_warn "PostgreSQL server not found — installing..."

    # On RHEL/Rocky/AlmaLinux, prefer the newest AppStream module available
    # (postgresql:16) over the default (postgresql:13 on Rocky 9) so we meet
    # the PG_MIN_VERSION=14 requirement out of the box.
    case "$OS_FAMILY" in
        rhel)
            log_step "Enabling postgresql:16 AppStream module (if available)..."
            dnf module enable postgresql:16 -y >> "$LOG_FILE" 2>&1 || \
            dnf module enable postgresql:15 -y >> "$LOG_FILE" 2>&1 || true
            ;;
    esac

    local pkgs_str
    pkgs_str=$(pg_package_names)
    IFS=' ' read -ra _pg_pkgs <<< "$pkgs_str"
    pkg_install "${_pg_pkgs[@]}"
    track_change "Installed PostgreSQL packages: ${pkgs_str}"

    # Re-detect after install — pg_detect now uses systemd unit scan so it
    # will find the newly registered service without needing binaries in PATH.
    if ! pg_detect; then
        abort "PostgreSQL installation appeared to succeed but no service unit was registered.
Check ${LOG_FILE} for details."
    fi
    if ! pg_version_ok; then
        abort "Installed PostgreSQL ${PG_FOUND_VERSION} does not meet the minimum requirement (${PG_MIN_VERSION}+).
Enable a newer AppStream module manually:
  sudo dnf module enable postgresql:16 -y
  sudo dnf install postgresql-server -y
  sudo $0"
    fi
    log_success "PostgreSQL ${PG_FOUND_VERSION} installed (service: ${PG_FOUND_SERVICE})."
}

# pg_init_cluster
# Initialises the PostgreSQL data directory if not already done (RHEL-style).
# Handles both OS-default packages (postgresql-setup in PATH) and PGDG
# versioned packages whose setup script lives in /usr/pgsql-<ver>/bin/.
pg_init_cluster() {
    case "$OS_FAMILY" in
        rhel)
            if [[ ! -f "${PG_DATA_DIR}/PG_VERSION" ]]; then
                log_step "Initialising PostgreSQL data directory (${PG_DATA_DIR})..."

                local setup_bin=""

                # PGDG versioned packages ship a version-specific setup script
                # at /usr/pgsql-<ver>/bin/postgresql-<ver>-setup
                if [[ -n "${PG_FOUND_VERSION:-}" ]]; then
                    local pgdg_setup="/usr/pgsql-${PG_FOUND_VERSION}/bin/postgresql-${PG_FOUND_VERSION}-setup"
                    if [[ -x "$pgdg_setup" ]]; then
                        setup_bin="$pgdg_setup"
                    fi
                fi

                # OS-default AppStream package: postgresql-setup is in PATH
                if [[ -z "$setup_bin" ]] && cmd_exists postgresql-setup; then
                    setup_bin="postgresql-setup"
                fi

                if [[ -n "$setup_bin" ]]; then
                    "$setup_bin" --initdb >> "$LOG_FILE" 2>&1 \
                        || abort "PostgreSQL initdb failed.
Command: ${setup_bin} --initdb
Check: ${LOG_FILE}"
                else
                    # Direct initdb invocation — search all known binary locations
                    local initdb_bin
                    initdb_bin=$(find /usr/pgsql-*/bin /usr/bin /usr/lib/postgresql/*/bin \
                                     -name initdb 2>/dev/null -print -quit)
                    [[ -n "$initdb_bin" ]] \
                        || abort "initdb not found. PostgreSQL installation may be incomplete.
Check: ${LOG_FILE}"
                    ensure_dir "$PG_DATA_DIR" "postgres:postgres" "700"
                    "$initdb_bin" -D "$PG_DATA_DIR" >> "$LOG_FILE" 2>&1 \
                        || abort "initdb -D ${PG_DATA_DIR} failed. Check ${LOG_FILE}."
                fi

                track_change "Initialised PostgreSQL data directory at ${PG_DATA_DIR}"
                log_success "PostgreSQL cluster initialised."
            else
                log_info "PostgreSQL data directory already initialised (${PG_DATA_DIR})."
            fi
            ;;
        debian)
            # Debian/Ubuntu auto-initialise on package install; nothing to do.
            log_info "PostgreSQL cluster auto-managed by Debian/Ubuntu packaging."
            ;;
    esac
}

# pg_ensure_service
# Enables and starts the PostgreSQL service.
pg_ensure_service() {
    local svc="${PG_FOUND_SERVICE:-${PG_SERVICE}}"
    log_step "Ensuring PostgreSQL service is running (${svc})..."
    systemctl enable "$svc" >> "$LOG_FILE" 2>&1 || true
    if ! systemctl is-active --quiet "$svc"; then
        systemctl start "$svc" >> "$LOG_FILE" 2>&1 \
            || abort "Failed to start PostgreSQL service (${svc}).
Check: sudo systemctl status ${svc}
Log:   ${LOG_FILE}"
    fi
    log_success "PostgreSQL service is running."
}

# pg_escape_literal <string>
# Returns the value with every single-quote doubled for safe SQL string literal
# embedding, per the SQL standard (ISO 9075, §5.3).  Always wrap the result in
# surrounding single quotes when constructing the SQL statement.
#
# Safety guarantee: the escaped value is passed to psql via stdin (pg_execute),
# which means the shell never re-interprets it.  The only transformation that
# occurs is bash parameter expansion of the known, controlled SQL string —
# there is no command substitution, no eval, and no further shell processing
# of the password value itself.
#
# Covers all valid password characters including: ' " ` \ ; $ ! ( ) spaces,
# and high-byte UTF-8 sequences.
pg_escape_literal() {
    printf '%s' "${1//\'/\'\'}"
}

# pg_execute <sql>
# Executes a SQL command as the postgres system user.
# SQL is passed via stdin to avoid shell-quoting injection.
pg_execute() {
    local sql="$1"
    echo "$sql" | su -s /bin/bash postgres -c "psql -q" >> "$LOG_FILE" 2>&1
}

# pg_execute_check <sql>
# Like pg_execute but returns the output (for existence checks).
# SQL is passed via stdin to avoid shell-quoting injection.
pg_execute_check() {
    local sql="$1"
    echo "$sql" | su -s /bin/bash postgres -c "psql -tAq" 2>/dev/null
}

# pg_db_exists <dbname>
pg_db_exists() {
    local db="$1"
    local db_esc result
    db_esc="$(pg_escape_literal "$db")"
    result=$(pg_execute_check "SELECT 1 FROM pg_database WHERE datname='${db_esc}';")
    [[ "$result" == "1" ]]
}

# pg_user_exists <username>
pg_user_exists() {
    local user="$1"
    local user_esc result
    user_esc="$(pg_escape_literal "$user")"
    result=$(pg_execute_check "SELECT 1 FROM pg_roles WHERE rolname='${user_esc}';")
    [[ "$result" == "1" ]]
}

# pg_create_user <username> <password>
# Passwords may contain any valid character — see pg_escape_literal above.
pg_create_user() {
    local user="$1" pass="$2"
    # Escape for SQL string literal embedding (each ' → '' per SQL standard).
    local pass_esc
    pass_esc="$(pg_escape_literal "$pass")"
    if pg_user_exists "$user"; then
        log_info "PostgreSQL user '${user}' already exists — updating password."
        pg_execute "ALTER USER \"${user}\" WITH ENCRYPTED PASSWORD '${pass_esc}';" || true
        return 0
    fi
    log_step "Creating PostgreSQL user '${user}'..."
    pg_execute "CREATE USER \"${user}\" WITH ENCRYPTED PASSWORD '${pass_esc}';" \
        || abort "Failed to create PostgreSQL user '${user}'. Check ${LOG_FILE}."
    track_change "Created PostgreSQL user '${user}'"
    log_success "Created PostgreSQL user '${user}'."
}

# pg_create_db <dbname> <owner>
pg_create_db() {
    local db="$1" owner="$2"
    if pg_db_exists "$db"; then
        log_info "Database '${db}' already exists — skipping creation."
        return 0
    fi
    log_step "Creating database '${db}' owned by '${owner}'..."
    pg_execute "CREATE DATABASE ${db} OWNER ${owner};" \
        || abort "Failed to create database '${db}'. Check ${LOG_FILE}."
    track_change "Created PostgreSQL database '${db}'"
    log_success "Created database '${db}'."
}

# pg_setup <dbname> <dbuser> <dbpass>
# Full orchestration: install → init → start → handle existing DB → create user/db.
pg_setup() {
    local db_name="$1" db_user="$2" db_pass="$3"

    pg_ensure_installed
    pg_init_cluster
    pg_ensure_service

    # ── Handle existing database ──────────────────────────────────────────────
    if pg_db_exists "$db_name"; then
        log_warn "Database '${db_name}' already exists."
        printf "\n%sOptions:%s\n" "$CLR_BOLD" "$CLR_RESET"
        printf "  [R] Reuse the existing database (recommended — preserves all data)\n"
        printf "  [N] Create a new database with a different name\n"
        printf "  [A] Abort installation\n\n"

        if [[ "$YES_ALL" == "true" ]]; then
            log_info "Auto-selected: Reuse existing database (--yes mode)."
            # Just ensure user exists and has access
            pg_create_user "$db_user" "$db_pass"
            pg_execute "GRANT ALL PRIVILEGES ON DATABASE ${db_name} TO ${db_user};" || true
            return 0
        fi

        local choice
        printf "%sChoice [R/N/A]:%s " "$CLR_YELLOW" "$CLR_RESET"
        read -r choice
        case "${choice^^}" in
            R)
                log_info "Reusing existing database '${db_name}'."
                pg_create_user "$db_user" "$db_pass"
                pg_execute "GRANT ALL PRIVILEGES ON DATABASE ${db_name} TO ${db_user};" || true
                return 0
                ;;
            N)
                printf "%sEnter new database name:%s " "$CLR_YELLOW" "$CLR_RESET"
                read -r db_name
                [[ -n "$db_name" ]] || abort "Database name cannot be empty."
                # Update the config with the new name
                sed -i "s|lop_db|${db_name}|g" "$LOP_CONF_FILE" 2>/dev/null || true
                log_info "Using new database name: '${db_name}'"
                ;;
            *)
                abort "Installation aborted by user."
                ;;
        esac
    fi

    pg_create_user "$db_user" "$db_pass"
    pg_create_db "$db_name" "$db_user"
    pg_execute "GRANT ALL PRIVILEGES ON DATABASE ${db_name} TO ${db_user};" || true
    log_success "Database setup complete: ${db_name}@localhost"
}

# pg_dump_db <dbname> <output_file>
pg_dump_db() {
    local db="$1" out="$2"
    log_step "Dumping database '${db}' to ${out}..."
    su -s /bin/bash postgres -c "pg_dump --no-password '${db}'" > "$out" 2>> "$LOG_FILE" \
        || abort "pg_dump failed for '${db}'. Check ${LOG_FILE}."
    log_success "Database dump written to ${out} ($(du -sh "$out" | cut -f1))."
}

# pg_restore_db <dbname> <input_file>
pg_restore_db() {
    local db="$1" inp="$2"
    log_step "Restoring database '${db}' from ${inp}..."

    # Validate dump file is non-empty before touching the live database
    [[ -s "$inp" ]] || abort "Database dump file is empty or missing: ${inp}"

    # Terminate active connections then drop and recreate the database
    pg_execute "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}';" || true
    pg_execute "DROP DATABASE IF EXISTS \"${db}\";"
    pg_execute "CREATE DATABASE \"${db}\";"

    # Restore via stdin redirect (avoids further shell-quoting issues)
    su -s /bin/bash postgres -c "psql -q -d \"${db}\"" < "$inp" >> "$LOG_FILE" 2>&1 \
        || abort "Database restore failed for '${db}'. Check ${LOG_FILE}."

    # Re-grant access to the LOP database user (dump ownership metadata may differ)
    local db_user
    db_user=$(grep '^LOP_DB_USER=' "$LOP_CONF_FILE" 2>/dev/null | cut -d= -f2 || true)
    if [[ -n "$db_user" ]]; then
        pg_execute "GRANT ALL PRIVILEGES ON DATABASE \"${db}\" TO \"${db_user}\";" || true
    fi

    log_success "Database '${db}' restored."
}
