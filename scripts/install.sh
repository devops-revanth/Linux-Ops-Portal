#!/usr/bin/env bash
# =============================================================================
# LOP — Installation script
# Usage: sudo ./install.sh [--yes] [--force] [--repair]
#
# Modes (auto-detected, or forced with flags):
#   fresh   — first-time installation
#   upgrade — existing healthy install (delegates to update.sh)
#   repair  — existing broken install (re-applies service/deps/venv)
#
# --repair   Force repair mode regardless of health check outcome.
#            Use this via 'sudo lop repair' when the install is healthy
#            but you still want to re-apply dependencies / the service unit.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/var/log/lop/install.log"

# Trap ERR so that any command exiting non-zero under set -e prints the exact
# source file, function, line number, and failing command before the script
# exits.  Without this, set -e exits silently — impossible to debug.
trap 'printf "\n[ABORT] Unexpected error in %s:%s():%s\n  command: %s\n  exit code: %s\n" \
    "${BASH_SOURCE[0]}" "${FUNCNAME[0]:-main}" "${LINENO}" "${BASH_COMMAND}" "$?" >&2' ERR

# Source libraries (order matters)
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/os.sh
source "$SCRIPT_DIR/lib/os.sh"
# shellcheck source=lib/python.sh
source "$SCRIPT_DIR/lib/python.sh"
# shellcheck source=lib/deps.sh
source "$SCRIPT_DIR/lib/deps.sh"
# shellcheck source=lib/postgres.sh
source "$SCRIPT_DIR/lib/postgres.sh"
# shellcheck source=lib/systemd.sh
source "$SCRIPT_DIR/lib/systemd.sh"
# shellcheck source=lib/version.sh
source "$SCRIPT_DIR/lib/version.sh"

# ── Flags ─────────────────────────────────────────────────────────────────────
FORCE_REINSTALL=false
FORCE_REPAIR=false
parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    if [[ "$arg" == "--force"  ]]; then FORCE_REINSTALL=true; fi
    if [[ "$arg" == "--repair" ]]; then FORCE_REPAIR=true; fi
done

# ── Source repo directory (parent of scripts/) ───────────────────────────────
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Bootstrap: ensure log directory exists before anything else ──────────────
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chmod 640 "$LOG_FILE"

# ── Banner ────────────────────────────────────────────────────────────────────
print_banner() {
    cat <<'BANNER'

  ██╗      ██████╗ ██████╗
  ██║     ██╔═══██╗██╔══██╗
  ██║     ██║   ██║██████╔╝
  ██║     ██║   ██║██╔═══╝
  ███████╗╚██████╔╝██║
  ╚══════╝ ╚═════╝ ╚═╝   Linux Operations Portal
BANNER
    printf "\n  Installer v%s\n\n" "$(version_get INSTALLER_VERSION "$REPO_DIR/VERSION" 2>/dev/null || echo '1.0.0')"
}

# ── Mode detection ────────────────────────────────────────────────────────────
detect_install_mode() {
    INSTALL_MODE="fresh"

    if [[ -d "$LOP_APP_DIR" ]] && systemd_service_exists "$LOP_BACKEND_SERVICE" 2>/dev/null; then
        if health_check "http://localhost:5000/health" 3 2; then
            INSTALL_MODE="upgrade"
        else
            INSTALL_MODE="repair"
        fi
    elif [[ -d "$LOP_APP_DIR" ]]; then
        # Application directory exists but the service was never registered.
        # This indicates a previous installation that was interrupted or failed
        # before the systemd unit was written — offer the operator a choice
        # instead of silently entering repair mode.
        INSTALL_MODE="incomplete"
    fi

    if [[ "$FORCE_REINSTALL" == "true" ]]; then
        INSTALL_MODE="fresh"
    fi
    # --repair forces repair mode even when the health check passes (e.g. to
    # re-apply dependencies or the service unit on a healthy installation).
    if [[ "$FORCE_REPAIR" == "true" ]]; then
        INSTALL_MODE="repair"
    fi
}

# ── Configuration file generation ────────────────────────────────────────────
generate_lop_env() {
    if [[ -f "$LOP_CONF_FILE" ]] && [[ "$FORCE_REINSTALL" != "true" ]]; then
        log_info "Configuration file already exists — preserving ${LOP_CONF_FILE}"
        return 0
    fi

    log_step "Generating configuration file..."
    ensure_dir "$LOP_CONF_DIR" "root:root" "750"

    # Generate secure values
    local secret_key
    secret_key=$(openssl rand -hex 32)
    local db_pass
    db_pass=$(openssl rand -base64 24 | tr -d '=/+' | head -c 24)
    local admin_pass
    admin_pass=$(openssl rand -base64 18 | tr -d '=/+' | head -c 20)

    cat > "$LOP_CONF_FILE" <<EOF
# LOP Configuration — /etc/lop/lop.env
# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Updates will NEVER overwrite this file.
# Modify this file to change application settings.

# ── Flask ──────────────────────────────────────────────────────────────────
FLASK_ENV=production
FLASK_APP=run.py
LOG_LEVEL=INFO

# ── Security ───────────────────────────────────────────────────────────────
SECRET_KEY=${secret_key}

# ── Database ───────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://lop_user:${db_pass}@localhost:5432/lop_db
LOP_DB_NAME=lop_db
LOP_DB_USER=lop_user
LOP_DB_PASS=${db_pass}

# ── Application ────────────────────────────────────────────────────────────
APP_BASE_URL=http://$(hostname -f 2>/dev/null || hostname):5000
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${admin_pass}

# ── Runtime paths ───────────────────────────────────────────────────────────
# LOP_LOG_DIR tells the application where to write rotating log files.
# The application installation tree (/opt/lop) is read-only in the systemd
# unit (ProtectSystem=strict); all log output must go here instead.
LOP_LOG_DIR=/var/log/lop

# ── FreeIPA / LDAP Authentication (optional) ───────────────────────────────
# Set FREEIPA_ENABLED=true and fill in the remaining vars to activate.
# See docs/FREEIPA.md for details.
FREEIPA_ENABLED=false
FREEIPA_URI=ldaps://ipa.corp.example.com
FREEIPA_BASE_DN=dc=corp,dc=example,dc=com
FREEIPA_BIND_DN=uid=svc-lop,cn=users,cn=accounts,dc=corp,dc=example,dc=com
FREEIPA_BIND_PASSWORD=change-me
FREEIPA_CA_CERT=/etc/ipa/ca.crt
FREEIPA_VERIFY_CERT=true
EOF

    chmod 640 "$LOP_CONF_FILE"
    track_change "Generated ${LOP_CONF_FILE}"
    log_success "Configuration file created."

    # Store admin password for display at end
    GENERATED_ADMIN_PASS="$admin_pass"
    GENERATED_DB_PASS="$db_pass"
}

# ── Application copy ──────────────────────────────────────────────────────────
copy_application() {
    detect_install_source "$REPO_DIR"

    if [[ "$(realpath "$REPO_DIR")" == "$(realpath "$LOP_APP_DIR")" ]]; then
        log_info "Source directory is the install directory — skipping copy."
        return 0
    fi

    log_step "Copying application to ${LOP_APP_DIR}..."
    ensure_dir "$LOP_APP_DIR" "root:root" "755"

    # rsync preserves permissions; only production-runtime files are copied.
    # Development-only artifacts, Replit infrastructure, build tooling, and
    # Docker/test/documentation files are explicitly excluded.
    if cmd_exists rsync; then
        rsync -a --delete \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='.env' \
            --exclude='venv/' \
            --exclude='lop/' \
            --exclude='artifacts/' \
            --exclude='lib/' \
            --exclude='node_modules/' \
            --exclude='.local/' \
            --exclude='.agents/' \
            --exclude='.cache/' \
            --exclude='.pythonlibs/' \
            --exclude='.replit' \
            --exclude='.replitignore' \
            --exclude='.flaskenv' \
            --exclude='.npmrc' \
            --exclude='pnpm-lock.yaml' \
            --exclude='pnpm-workspace.yaml' \
            --exclude='package.json' \
            --exclude='tsconfig.json' \
            --exclude='tsconfig.base.json' \
            --exclude='docker/' \
            --exclude='Dockerfile' \
            --exclude='docker-compose.yml' \
            --exclude='tests/' \
            --exclude='attached_assets/' \
            --exclude='logs/' \
            --exclude='*.docx' \
            --exclude='*.xlsx' \
            "$REPO_DIR/" "$LOP_APP_DIR/" >> "$LOG_FILE" 2>&1 \
            || abort "rsync failed. Check ${LOG_FILE}."
    else
        # Fallback: copy only production directories/files one level at a time
        local _dev_dirs=(
            .git __pycache__ .env venv lop artifacts lib node_modules
            .local .agents .cache .pythonlibs .replit .replitignore .flaskenv
            .npmrc pnpm-lock.yaml pnpm-workspace.yaml package.json
            tsconfig.json tsconfig.base.json docker Dockerfile
            docker-compose.yml tests attached_assets logs
        )
        local _excl_args=()
        for _d in "${_dev_dirs[@]}"; do
            _excl_args+=( ! -name "$_d" )
        done
        find "$REPO_DIR" -maxdepth 1 -mindepth 1 \
            "${_excl_args[@]}" \
            ! -name '*.docx' ! -name '*.xlsx' \
            -exec cp -rp {} "$LOP_APP_DIR/" \; 2>> "$LOG_FILE" \
            || abort "File copy failed. Check ${LOG_FILE}."
    fi

    track_change "Copied application to ${LOP_APP_DIR}"
    log_success "Application files copied."
}

# ── Credentials file ──────────────────────────────────────────────────────────
write_credentials_file() {
    local admin_user admin_pass
    admin_user=$(grep '^ADMIN_USERNAME=' "$LOP_CONF_FILE" | cut -d= -f2)
    admin_pass=$(grep '^ADMIN_PASSWORD=' "$LOP_CONF_FILE" | cut -d= -f2)
    local app_url
    app_url=$(grep '^APP_BASE_URL=' "$LOP_CONF_FILE" | cut -d= -f2)

    cat > "$LOP_CREDENTIALS_FILE" <<EOF
# LOP Initial Credentials — $(date -u +%Y-%m-%dT%H:%M:%SZ)
# This file is readable only by root.
# CHANGE YOUR PASSWORD AFTER FIRST LOGIN.
admin_url=${app_url}
admin_username=${admin_user}
admin_password=${admin_pass}
EOF
    chmod 600 "$LOP_CREDENTIALS_FILE"
    chown root:root "$LOP_CREDENTIALS_FILE"
    track_change "Wrote credentials to ${LOP_CREDENTIALS_FILE}"
}

# ── Run database migrations ───────────────────────────────────────────────────
run_migrations() {
    log_step "Running database migrations..."
    lop_flask db upgrade >> "$LOG_FILE" 2>&1 \
        || abort "Database migrations failed. Check ${LOG_FILE}."
    track_change "Ran database migrations"
    log_success "Database migrations complete."
}

# ── Print installation summary ────────────────────────────────────────────────
print_summary() {
    local admin_user admin_pass app_url app_version
    admin_user=$(grep '^ADMIN_USERNAME=' "$LOP_CONF_FILE" 2>/dev/null | cut -d= -f2 || echo "admin")
    admin_pass=$(grep '^ADMIN_PASSWORD=' "$LOP_CONF_FILE" 2>/dev/null | cut -d= -f2 || echo "(see ${LOP_CREDENTIALS_FILE})")
    app_url=$(grep '^APP_BASE_URL=' "$LOP_CONF_FILE" 2>/dev/null | cut -d= -f2 || echo "http://localhost:5000")
    app_version=$(version_get "APP_VERSION" "$LOP_APP_DIR/VERSION" 2>/dev/null || echo "unknown")

    printf "\n%s%s╔══════════════════════════════════════════════════╗%s\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"
    printf "%s%s║        LOP Installation Complete                 ║%s\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"
    printf "%s%s╚══════════════════════════════════════════════════╝%s\n\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"

    log_section "Access Information"
    summary_line "URL:"           "$app_url"
    summary_line "Username:"      "$admin_user"
    summary_line "Password:"      "$admin_pass"
    printf "\n"

    log_section "Version Information"
    summary_line "Application:"    "$app_version"
    summary_line "Database schema:" "$(alembic_current 2>/dev/null || echo 'see logs')"
    summary_line "Install mode:"   "$INSTALL_MODE"
    printf "\n"

    log_section "Python Runtime"
    summary_line "System Python:"  "$(command -v python3 2>/dev/null || echo 'none') ($(python_get_version "$(command -v python3 2>/dev/null || echo /dev/null)" 2>/dev/null || echo 'n/a'))"
    summary_line "Selected Python:" "$SELECTED_PYTHON ($SELECTED_PYTHON_VERSION)"
    summary_line "Virtual Env:"    "$LOP_VENV_DIR"
    printf "\n"

    log_section "Filesystem"
    summary_line "Application:"    "$LOP_APP_DIR"
    summary_line "Configuration:"  "$LOP_CONF_FILE"
    summary_line "Credentials:"    "$LOP_CREDENTIALS_FILE (root-readable only)"
    summary_line "Logs:"           "$LOP_LOG_DIR"
    printf "\n"

    printf "%s⚠  Please change your admin password after first login.%s\n\n" "$CLR_YELLOW" "$CLR_RESET"
    printf "   Credentials also saved to: %s\n\n" "$LOP_CREDENTIALS_FILE"
}

# =============================================================================
# ── FRESH INSTALL ─────────────────────────────────────────────────────────────
# =============================================================================
do_fresh_install() {
    log_section "Fresh Installation"

    # 1. OS detection
    detect_os

    # 2. Dependencies
    verify_all_deps

    # 3. Python runtime
    python_select

    # 4. Directory structure
    log_step "Creating directory structure..."
    ensure_dir "$LOP_APP_DIR"      "root:root" "755"
    ensure_dir "$LOP_CONF_DIR"     "root:root" "750"
    ensure_dir "$LOP_LOG_DIR"      "root:root" "755"
    ensure_dir "$LOP_LOG_DIR/app"  "root:root" "755"
    ensure_dir "$LOP_BACKUP_DIR"   "root:root" "750"
    ensure_dir "$LOP_DATA_DIR"     "root:root" "755"
    ensure_dir "$LOP_CHECKSUMS_DIR" "root:root" "700"
    ensure_dir "$LOP_TMP_DIR"      "root:root" "1777"
    ensure_dir "$LOP_PLUGINS_DIR"  "root:root" "755"

    # 5. Copy application
    copy_application

    # Firewalld: if the system uses firewalld, port 5000 must be opened manually.
    # We do not run firewall-cmd automatically to avoid unexpected policy changes.
    if cmd_exists firewall-cmd && firewall-cmd --state &>/dev/null 2>&1; then
        log_warn "firewalld is active. Open port 5000 manually if external access is needed:"
        log_warn "  sudo firewall-cmd --permanent --add-port=5000/tcp && sudo firewall-cmd --reload"
    fi

    # Restore SELinux file contexts after copying (non-fatal; only active on enforcing systems)
    if cmd_exists restorecon; then
        log_step "Restoring SELinux file contexts..."
        restorecon -Rv "$LOP_APP_DIR" "$LOP_CONF_DIR" \
                      "$LOP_LOG_DIR" "$LOP_BACKUP_DIR" "$LOP_DATA_DIR" \
                      >> "$LOG_FILE" 2>&1 || true
        log_info "SELinux file contexts restored."
    fi

    # 6. Generate configuration (before DB so we have the DB password)
    generate_lop_env

    # 7. Virtual environment + pip
    python_create_venv
    python_install_deps

    # 8. PostgreSQL
    load_lop_env
    pg_setup "$LOP_DB_NAME" "$LOP_DB_USER" "$LOP_DB_PASS"

    # 9. Migrations
    run_migrations

    # 10. Save checksums
    checksums_save_all

    # 11. Systemd service
    systemd_setup_lop

    # 12. Health check
    log_step "Verifying installation health (waiting up to 60s)..."
    if health_check "http://localhost:5000/health" 12 5; then
        log_success "Health check passed."
    else
        log_warn "Health check failed. Check: sudo journalctl -u lop-backend -n 50"
        log_warn "Installation may still be functional — check ${LOG_FILE}."
    fi

    # 13. Install CLI symlink
    install_cli_symlink

    # 14. Credentials file
    write_credentials_file

    # 15. Install metadata
    install_info_write "fresh"

    print_summary
}

# =============================================================================
# ── REPAIR ───────────────────────────────────────────────────────────────────
# =============================================================================
do_repair() {
    log_section "Repair Installation"
    log_info "Existing installation found at ${LOP_APP_DIR}."
    log_info "Repair will re-apply: venv, dependencies, service. Config and DB are untouched."

    detect_os

    # Reload existing config
    load_lop_env

    # Ensure PostgreSQL is running before attempting migrations.
    # Without this, run_migrations() will fail with an opaque connection error
    # rather than a clear "database is down" message.
    log_step "Ensuring PostgreSQL is running..."
    pg_ensure_service \
        || log_warn "PostgreSQL may not be running — migrations will fail if the DB is unreachable."

    # Re-select Python (may have changed)
    python_select

    # Rebuild venv if needed
    python_create_venv
    python_install_deps

    # Ensure migrations are at head
    run_migrations

    # Recreate/fix service
    log_step "Repairing systemd service..."
    systemd_setup_lop

    # Health check
    log_step "Verifying health..."
    if health_check "http://localhost:5000/health" 12 5; then
        log_success "Repair complete — LOP is healthy."
    else
        log_warn "Health check failed after repair. Check: sudo journalctl -u lop-backend -n 50"
    fi

    install_info_update "install_mode" "repair"
    install_info_update "install_date" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    log_success "Repair finished. Log: ${LOG_FILE}"
}

# =============================================================================
# ── INCOMPLETE INSTALLATION RECOVERY ─────────────────────────────────────────
# =============================================================================

# do_wipe_incomplete
# Removes the application directory, systemd unit, and runtime files left by a
# failed or interrupted install.
#
# Intentionally preserves:
#   /etc/lop/lop.env       — operator configuration (SECRET_KEY, DB passwords)
#   /etc/lop/initial_credentials
#   /var/backups/lop       — backup archives
#   PostgreSQL database    — contains data, never removed without explicit flag
#
do_wipe_incomplete() {
    log_section "Removing Incomplete Installation"

    # Stop and disable service if it somehow exists (defensive — normally absent
    # for incomplete installs, but uninstall.sh may have left a partial unit).
    if systemd_service_exists "$LOP_BACKEND_SERVICE" 2>/dev/null; then
        log_step "Stopping and disabling ${LOP_BACKEND_SERVICE}..."
        systemctl stop    "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 || true
        systemctl disable "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 || true
    fi

    # Remove systemd unit file and reload daemon
    local unit_file="/etc/systemd/system/${LOP_BACKEND_SERVICE}.service"
    if [[ -f "$unit_file" ]]; then
        rm -f "$unit_file"
        systemctl daemon-reload >> "$LOG_FILE" 2>&1 || true
        log_success "Removed systemd unit: ${unit_file}"
    fi

    # Remove application directory — includes the venv at ${LOP_VENV_DIR}
    if [[ -d "$LOP_APP_DIR" ]]; then
        rm -rf "$LOP_APP_DIR"
        track_change "Removed application directory: ${LOP_APP_DIR}"
        log_success "Removed: ${LOP_APP_DIR}"
    fi

    # Remove runtime configuration (regenerated on fresh install)
    # Do NOT remove lop.env — it contains the database credentials
    if [[ -f "$LOP_RUNTIME_FILE" ]]; then
        rm -f "$LOP_RUNTIME_FILE"
        log_info "Removed runtime env: ${LOP_RUNTIME_FILE}"
    fi

    # Remove install state and checksums (outside LOP_APP_DIR in /var/lib/lop)
    if [[ -f "$LOP_INSTALL_INFO" ]]; then
        rm -f "$LOP_INSTALL_INFO"
        log_info "Removed install metadata: ${LOP_INSTALL_INFO}"
    fi
    if [[ -d "$LOP_CHECKSUMS_DIR" ]]; then
        rm -rf "$LOP_CHECKSUMS_DIR"
        log_info "Removed checksums: ${LOP_CHECKSUMS_DIR}"
    fi

    log_success "Incomplete installation cleaned up."
    log_info "Preserved: ${LOP_CONF_DIR}  (configuration and credentials)"
    log_info "Preserved: ${LOP_BACKUP_DIR} (backup archives)"
    log_info "Preserved: PostgreSQL database (untouched)"
}

# handle_incomplete_install
# Displays a recovery menu when a previous incomplete installation is detected.
handle_incomplete_install() {
    printf "\n%s%s╔══════════════════════════════════════════════════╗%s\n" \
        "$CLR_BOLD" "$CLR_YELLOW" "$CLR_RESET"
    printf "%s%s║  ⚠  Previous Incomplete Installation Detected   ║%s\n" \
        "$CLR_BOLD" "$CLR_YELLOW" "$CLR_RESET"
    printf "%s%s╚══════════════════════════════════════════════════╝%s\n\n" \
        "$CLR_BOLD" "$CLR_YELLOW" "$CLR_RESET"

    printf "  %s was found but the service was never registered.\n" "$LOP_APP_DIR"
    printf "  A previous installation was likely interrupted or failed.\n\n"

    printf "  Choose an option:\n\n"
    printf "  %s1)%s Repair  — re-apply dependencies, virtual environment,\n" \
        "$CLR_BOLD" "$CLR_RESET"
    printf "       and systemd service. Preserves all existing files and\n"
    printf "       the database.\n\n"
    printf "  %s2)%s Clean reinstall  — remove the incomplete installation\n" \
        "$CLR_BOLD" "$CLR_RESET"
    printf "       and perform a fresh install.\n"
    printf "       Preserves: %s/lop.env, database, backups.\n\n" "$LOP_CONF_DIR"

    local choice
    if [[ "$YES_ALL" == "true" ]]; then
        log_info "Auto-selected: Repair (--yes mode)."
        choice=1
    else
        printf "  Enter choice [1]: "
        read -r choice
        choice="${choice:-1}"
    fi

    case "$choice" in
        1)
            INSTALL_MODE="repair"
            confirm "Proceed with repair? (Configuration and database will not be touched)" \
                || abort "Repair cancelled by user."
            do_repair
            ;;
        2)
            log_warn "This will remove ${LOP_APP_DIR}, the systemd unit, and runtime files."
            log_warn "Preserved: ${LOP_CONF_DIR} (config), database, ${LOP_BACKUP_DIR} (backups)."
            confirm "Remove incomplete installation and perform a fresh install?" \
                || abort "Reinstall cancelled by user."
            do_wipe_incomplete
            INSTALL_MODE="fresh"
            confirm "Proceed with fresh installation?" \
                || abort "Installation cancelled by user."
            do_fresh_install
            ;;
        *)
            abort "Invalid choice '${choice}'. Run the installer again and select 1 or 2."
            ;;
    esac
}

# ── CLI symlink ───────────────────────────────────────────────────────────────
install_cli_symlink() {
    local lop_bin="$LOP_APP_DIR/lop"
    if [[ -f "$lop_bin" ]]; then
        chmod +x "$lop_bin"
        ln -sf "$lop_bin" /usr/local/bin/lop 2>/dev/null \
            && log_success "CLI installed: 'lop' command available system-wide." \
            || log_warn "Could not install 'lop' to /usr/local/bin (non-fatal)."
    fi
}

# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================
main() {
    require_root "$@"
    print_banner

    detect_install_mode
    log_info "Install mode: ${INSTALL_MODE}"

    case "$INSTALL_MODE" in
        fresh)
            if [[ -d "$LOP_APP_DIR" ]] && [[ "$FORCE_REINSTALL" != "true" ]]; then
                # Directory exists but --force was not passed — this can happen
                # if FORCE_REINSTALL was set externally; treat as repair.
                log_warn "Directory ${LOP_APP_DIR} already exists but no healthy service found."
                log_warn "Running in repair mode. Use --force to force a full reinstall."
                INSTALL_MODE="repair"
                do_repair
            else
                confirm "Proceed with fresh installation?" || abort "Installation cancelled by user."
                do_fresh_install
            fi
            ;;
        upgrade)
            log_info "Existing healthy installation detected — delegating to update.sh."
            exec "$SCRIPT_DIR/update.sh" "${REMAINING_ARGS[@]:-}"
            ;;
        repair)
            confirm "Proceed with repair? (Config and database will not be touched)" \
                || abort "Repair cancelled by user."
            do_repair
            ;;
        incomplete)
            handle_incomplete_install
            ;;
    esac
}

main "$@"
