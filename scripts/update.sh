#!/usr/bin/env bash
# =============================================================================
# LOP — Intelligent update script
# Usage: sudo ./update.sh [--yes] [--skip-backup]
#
# Detects what actually changed and only runs the necessary steps.
# Automatically rolls back on failure.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Parent of scripts/ — the source checkout the operator is running update.sh
# from.  Identical in structure to how install.sh defines REPO_DIR so that
# both scripts use the same source directory as the rsync origin.
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export LOG_FILE="/var/log/lop/update.log"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/os.sh"
source "$SCRIPT_DIR/lib/python.sh"
source "$SCRIPT_DIR/lib/deps.sh"
source "$SCRIPT_DIR/lib/postgres.sh"
source "$SCRIPT_DIR/lib/systemd.sh"
source "$SCRIPT_DIR/lib/nginx.sh"
source "$SCRIPT_DIR/lib/version.sh"

# ── Flags ─────────────────────────────────────────────────────────────────────
SKIP_BACKUP=false
parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    if [[ "$arg" == "--skip-backup" ]]; then SKIP_BACKUP=true; fi
done

# ── Pre-flight state ──────────────────────────────────────────────────────────
PRE_UPDATE_HASH=""
PRE_UPDATE_ALEMBIC=""
PRE_UPDATE_VERSION=""
RESTART_NEEDED=false
BACKUP_PATH=""

# Flags for what ran (used in rollback)
DEPS_UPGRADED=false
MIGRATIONS_RAN=false

# ── Pre-flight checks ─────────────────────────────────────────────────────────
preflight_checks() {
    log_section "Pre-flight Checks"

    # ── Require a Git source checkout ────────────────────────────────────────
    # update.sh must always run from the Git source checkout so that REPO_DIR
    # (derived from BASH_SOURCE[0]) points to the directory containing .git.
    #
    # When invoked via 'lop update', the lop CLI reads install metadata,
    # resolves the source checkout path, and cd's there before exec'ing this
    # script — so REPO_DIR is always correct.
    #
    # If someone runs /opt/lop/scripts/update.sh directly, REPO_DIR resolves
    # to /opt/lop (no .git).  Abort with a clear message rather than silently
    # failing later.
    if ! git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null 2>&1; then
        abort "update.sh is not running from a Git source checkout.

  REPO_DIR : ${REPO_DIR}

Run the update through the management CLI instead:

    sudo lop update

Or change into the source checkout and run the script directly:

    cd /path/to/Linux-Ops-Portal
    sudo ./scripts/update.sh"
    fi

    [[ -d "$LOP_APP_DIR" ]] \
        || abort "LOP application not found at ${LOP_APP_DIR}.
Is LOP installed? Try: sudo lop install"

    [[ -f "$LOP_CONF_FILE" ]] \
        || abort "Configuration file not found: ${LOP_CONF_FILE}
Is LOP installed? Try: sudo ./install.sh"

    [[ -f "$LOP_INSTALL_INFO" ]] \
        || abort "Install metadata not found: ${LOP_INSTALL_INFO}
Cannot determine how LOP was installed. Try: sudo ./install.sh --force"

    load_lop_env

    # Detect OS for package manager
    detect_os

    # Record pre-update state.
    # The source checkout ($REPO_DIR) is where .git lives; $LOP_APP_DIR
    # is the rsync destination and never contains .git.
    PRE_UPDATE_HASH=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")
    PRE_UPDATE_ALEMBIC=$(alembic_current 2>/dev/null || echo "unknown")
    PRE_UPDATE_VERSION=$(version_get "APP_VERSION" "$LOP_APP_DIR/VERSION")

    log_success "Pre-flight checks passed."
    log_info "Current version: ${PRE_UPDATE_VERSION} (${PRE_UPDATE_HASH:0:8})"
    log_info "Current DB schema: ${PRE_UPDATE_ALEMBIC}"
}

# ── Pre-update backup ─────────────────────────────────────────────────────────
run_pre_update_backup() {
    if [[ "$SKIP_BACKUP" == "true" ]]; then
        log_warn "Pre-update backup skipped (--skip-backup)."
        return 0
    fi
    log_step "Creating pre-update backup..."
    BACKUP_PATH=$("$SCRIPT_DIR/backup.sh" --quiet 2>&1 | tail -1) || {
        log_warn "Backup failed. Continuing with update (use --skip-backup to suppress this warning)."
        BACKUP_PATH=""
    }
    if [[ -n "$BACKUP_PATH" ]]; then log_success "Backup: ${BACKUP_PATH}"; fi
}

# ── Pull latest code ──────────────────────────────────────────────────────────
pull_latest_code() {
    log_section "Code Update"

    local source
    source=$(install_info_read "install_source")
    local source_url
    source_url=$(install_info_read "install_source_url")
    local source_branch
    source_branch=$(install_info_read "install_source_branch")
    source_branch="${source_branch:-main}"

    log_info "Install source type: ${source}"

    case "$source" in
        git)
            # ── Installer-based rsync deployment model ────────────────────────
            # The installer copies application files from the source checkout
            # (REPO_DIR) to the deployed directory (LOP_APP_DIR) via rsync,
            # intentionally excluding .git.  LOP_APP_DIR therefore never
            # contains .git — it is NOT a git repository.
            #
            # The correct update sequence is:
            #   1. git pull in the SOURCE CHECKOUT (REPO_DIR)
            #   2. rsync REPO_DIR → LOP_APP_DIR  (same as copy_application()
            #      in install.sh)
            #
            # update.sh is expected to be run from the source checkout, so
            # REPO_DIR = $(dirname SCRIPT_DIR) is the right directory.
            # ─────────────────────────────────────────────────────────────────

            # Guard: REPO_DIR must be a git repository.  If update.sh was
            # somehow invoked from /opt/lop/scripts/ (the deployed copy) rather
            # than from the source checkout, REPO_DIR won't have .git and we
            # cannot proceed safely.
            if ! git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null; then
                abort "update.sh is not running from a git source checkout.
update.sh is in: ${REPO_DIR}/scripts
This directory does not contain a .git folder.

The git-based update path requires update.sh to be run from within
the source checkout (the git clone, not the deployed /opt/lop copy).

Correct usage:
  cd /opt/Linux-Ops-Portal   # or wherever the source checkout lives
  git pull origin ${source_branch}
  sudo lop update"
            fi

            log_step "Fetching latest commits from ${source_url}..."

            # Capture stdout+stderr together so the real git message is shown
            # in any abort.  Never redirect both to the log file only — that
            # hides the error from the operator.
            local _git_out _git_rc=0
            _git_out=$(git -C "$REPO_DIR" fetch origin 2>&1) || _git_rc=$?
            printf "%s\n" "$_git_out" >> "$LOG_FILE"
            if (( _git_rc != 0 )); then
                abort "git fetch failed in ${REPO_DIR} (exit ${_git_rc}).
Git output: ${_git_out}
Remote:     ${source_url}
Possible causes:
  • No network access to the remote
  • Remote URL changed
  • Authentication required (SSH key or token missing)

If you have already pulled manually, ensure you are running update.sh
from within the source checkout, then retry."
            fi

            # Check for uncommitted local modifications in the source checkout.
            # grep -v exits 1 when there are no matching lines (clean tree) —
            # '|| true' prevents pipefail from aborting on a clean checkout.
            local dirty
            dirty=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null \
                    | { grep -v '^??' || true; } \
                    | wc -l)
            if (( dirty > 0 )); then
                log_warn "Local modifications detected in ${REPO_DIR}."
                confirm "Stash local changes and continue?" \
                    || abort "Update cancelled. Commit or stash local changes first."
                git -C "$REPO_DIR" stash >> "$LOG_FILE" 2>&1 || true
            fi

            # Pull the fetched commits into the source checkout.
            _git_rc=0
            _git_out=$(git -C "$REPO_DIR" pull --ff-only origin "$source_branch" 2>&1) || _git_rc=$?
            printf "%s\n" "$_git_out" >> "$LOG_FILE"
            if (( _git_rc != 0 )); then
                abort "git pull failed in ${REPO_DIR} (exit ${_git_rc}).
Git output: ${_git_out}
Branch: ${source_branch}
Tip: if you already ran 'git pull' manually before update.sh, this
is harmless — 'Already up to date.' exits 0 and is not a failure."
            fi

            local _new_hash
            _new_hash=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
            log_success "Source checkout at ${source_branch} (${_new_hash})."

            # Sync updated source files to the deployed directory.
            # Excludes mirror copy_application() in install.sh — keep in sync.
            log_step "Syncing files to ${LOP_APP_DIR}..."
            rsync -a --delete \
                --exclude='.git' \
                --exclude='__pycache__' \
                --exclude='*.pyc' \
                --exclude='.env' \
                --exclude='venv/' \
                --exclude='lop/' \
                --exclude='artifacts/' \
                --exclude='/lib/' \
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
                || abort "rsync from ${REPO_DIR} to ${LOP_APP_DIR} failed. Check ${LOG_FILE}."

            log_success "Files synced to ${LOP_APP_DIR} (${_new_hash})."
            ;;

        archive)
            log_warn "This installation was deployed from a release archive."
            printf "\nTo update, provide the path to a new release archive:\n"
            printf "Example: sudo ./update.sh --source /tmp/lop-2.0.0.tar.gz\n\n"

            # Rollback limitation: archive-based installs have no git history.
            # If this update fails, automatic code rollback is NOT possible.
            # The pre-update backup (taken in preflight) is the only recovery path.
            log_warn "IMPORTANT: code rollback is not available for archive-based installs."
            log_warn "If this update fails, recovery requires restoring the pre-update backup."
            if [[ -z "${BACKUP_PATH:-}" ]]; then
                log_warn "No pre-update backup was recorded. Proceeding without a rollback path."
                confirm "No backup available. Continue with the update anyway?" \
                    || abort "Update cancelled. Run 'sudo ./backup.sh' first, then retry."
            else
                log_info "Pre-update backup available at: ${BACKUP_PATH}"
            fi

            # Check for --source flag in REMAINING_ARGS
            local archive_path="" prev_arg=""
            for arg in "${REMAINING_ARGS[@]:-}"; do
                if [[ "$arg" == --source=* ]]; then archive_path="${arg#--source=}"; fi
                if [[ "$prev_arg" == "--source" ]]; then archive_path="$arg"; fi
                prev_arg="$arg"
            done

            if [[ -z "$archive_path" ]]; then
                abort "No archive path provided.
Usage: sudo ./update.sh --source /path/to/lop-<version>.tar.gz"
            fi

            [[ -f "$archive_path" ]] \
                || abort "Archive not found: ${archive_path}"

            log_step "Extracting archive: ${archive_path}..."
            local tmp_extract="$LOP_TMP_DIR/update_extract"
            mkdir -p "$tmp_extract"
            tar -xzf "$archive_path" -C "$tmp_extract" --strip-components=1 >> "$LOG_FILE" 2>&1 \
                || abort "Failed to extract archive. Check ${LOG_FILE}."

            rsync -a --delete \
                --exclude='.git' \
                --exclude='__pycache__' \
                --exclude='*.pyc' \
                --exclude='venv/' \
                --exclude='/etc/' \
                --exclude='artifacts/' \
                --exclude='/lib/' \
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
                "$tmp_extract/" "$LOP_APP_DIR/" >> "$LOG_FILE" 2>&1 \
                || abort "Failed to sync extracted archive. Check ${LOG_FILE}."

            log_success "Code updated from archive."
            ;;

        local)
            log_warn "This installation was deployed from a local directory (${source_url})."
            log_warn "Ensure you have updated the source directory before running update."

            # Rollback limitation: local-directory installs have no git history.
            # If this update fails, code rollback is NOT possible automatically.
            log_warn "IMPORTANT: code rollback is not available for local-directory installs."
            if [[ -n "${BACKUP_PATH:-}" ]]; then
                log_info "Pre-update backup available at: ${BACKUP_PATH}"
            else
                log_warn "No pre-update backup was recorded. Recovery will require"
                log_warn "manually re-syncing the previous source directory version."
            fi

            confirm "Source directory updated and ready to sync?" \
                || abort "Update cancelled."

            [[ -d "$source_url" ]] \
                || abort "Source directory not found: ${source_url}"

            rsync -a --delete \
                --exclude='.git' \
                --exclude='__pycache__' \
                --exclude='*.pyc' \
                --exclude='venv/' \
                --exclude='artifacts/' \
                --exclude='/lib/' \
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
                "$source_url/" "$LOP_APP_DIR/" >> "$LOG_FILE" 2>&1 \
                || abort "rsync from local source failed. Check ${LOG_FILE}."

            log_success "Code synced from local source."
            ;;

        *)
            abort "Unknown install source type: '${source}'.
Cannot determine update mechanism. Re-install with: sudo lop install"
            ;;
    esac
}

# ── Change detection and conditional steps ────────────────────────────────────
apply_changes() {
    log_section "Applying Changes"

    local new_version
    new_version=$(version_get "APP_VERSION" "$LOP_APP_DIR/VERSION")
    log_info "New version: ${new_version}"

    # ── Python runtime check ─────────────────────────────────────────────────
    local min_minor
    min_minor=$(grep '^MIN_PYTHON=' "$LOP_APP_DIR/VERSION" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' | cut -d. -f2)
    source "$SCRIPT_DIR/lib/python.sh"   # re-source for fresh globals
    if python_find_compatible; then
        log_info "Python runtime: ${SELECTED_PYTHON} (${SELECTED_PYTHON_VERSION}) — OK"
        # Ensure headers match the current interpreter before any venv/pip work.
        # Handles the case where the system Python was upgraded (e.g. 3.11 → 3.12)
        # between updates and the old devel headers no longer match.
        python_install_devel_headers
    else
        log_warn "No compatible Python found — attempting installation..."
        python_install_best_available
        python_find_compatible || abort "Python installation failed."
        # Install matching devel headers BEFORE creating the venv.
        # python_install_best_available already installs them via python_package_name(),
        # but calling again makes the ordering guarantee explicit and is idempotent.
        python_install_devel_headers
        python_create_venv --force
        RESTART_NEEDED=true
    fi

    # ── Dependencies ─────────────────────────────────────────────────────────
    if checksum_changed "$LOP_APP_DIR/requirements.txt" "requirements"; then
        log_step "requirements.txt changed — updating Python dependencies..."

        # Verify the full native build toolchain is present before recompiling.
        # A system update or a new requirement (e.g. cryptography needing cargo)
        # may have introduced new native dependencies since the last install.
        check_build_deps

        # Check if venv needs rebuild (Python changed)
        python_create_venv
        python_install_deps
        checksum_save "$LOP_APP_DIR/requirements.txt" "requirements"
        DEPS_UPGRADED=true
        RESTART_NEEDED=true
        log_success "Python dependencies updated."
    else
        log_info "requirements.txt unchanged — skipping pip install."
    fi

    # ── Node.js packages (optional) ──────────────────────────────────────────
    local pkg_json="$LOP_APP_DIR/package.json"
    if [[ -f "$pkg_json" ]] && checksum_changed "$pkg_json" "package_json"; then
        if cmd_exists pnpm; then
            log_step "package.json changed — updating Node.js dependencies..."
            (cd "$LOP_APP_DIR" && pnpm install) >> "$LOG_FILE" 2>&1 || log_warn "pnpm install failed (non-fatal)."
            checksum_save "$pkg_json" "package_json"
            log_success "Node.js dependencies updated."
        else
            log_warn "package.json changed but pnpm not installed (optional — skipping)."
        fi
    else
        log_info "package.json unchanged or not present — skipping pnpm install."
    fi

    # ── Database migrations ───────────────────────────────────────────────────
    if alembic_head_changed; then
        log_step "New database migrations detected — running upgrade..."
        lop_flask db upgrade >> "$LOG_FILE" 2>&1 \
            || {
                log_error "Database migration failed — initiating rollback."
                do_rollback
                exit 1
            }
        MIGRATIONS_RAN=true
        RESTART_NEEDED=true
        log_success "Database migrations applied."
    else
        log_info "No new database migrations — skipping."
    fi

    # ── Service restart ───────────────────────────────────────────────────────
    if [[ "$RESTART_NEEDED" == "true" ]]; then
        log_step "Restarting lop-backend..."

        # Re-write service file in case venv path or config changed
        systemd_write_backend
        systemd_reload
        systemctl restart "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 \
            || {
                log_error "Service restart failed — initiating rollback."
                do_rollback
                exit 1
            }
        log_success "Service restarted."

    else
        log_info "No code or dependency changes — service restart not required."
    fi
    # nginx is handled unconditionally in setup_nginx(), called after apply_changes().
}

# ── nginx setup (always run, idempotent) ─────────────────────────────────────
# nginx_setup() is called unconditionally on every update so that nginx is
# installed and running regardless of whether it was present before.
# nginx_verify() is only called AFTER setup — never before.
setup_nginx() {
    # nginx_setup() orchestrates: install → SELinux boolean → firewall rule →
    # write vhost → nginx -t → systemctl enable → start/reload.
    # It aborts if the configuration test fails or the service cannot start,
    # so errors are never silently swallowed.
    nginx_setup

    # After nginx_setup() returns, confirm nginx is actually serving traffic.
    # If nginx_verify() fails, capture full diagnostics into the log and to
    # stdout so the operator can act without hunting for log files.
    if ! nginx_verify; then
        log_warn "nginx is not responding after setup — capturing diagnostics:"
        {
            printf "\n=== systemctl status nginx ===\n"
            systemctl status nginx --no-pager 2>&1 || true
            printf "\n=== journalctl -u nginx (last 50 lines) ===\n"
            journalctl -u nginx -n 50 --no-pager 2>&1 || true
        } | tee -a "$LOG_FILE"
        log_warn "nginx diagnostics written to ${LOG_FILE}."
        # Do not abort — the application may still be reachable via Gunicorn
        # on port 5000.  The health check below will make the final call.
    fi
}

# ── Post-update health check ──────────────────────────────────────────────────
# nginx_verify() is safe to call here because setup_nginx() has already run.
post_update_health_check() {
    log_step "Verifying application health via nginx (http://localhost/)..."
    if nginx_verify; then
        log_success "Health check passed — nginx is proxying correctly."
        return 0
    fi

    # nginx_verify failed (or timed out).  Diagnostics were already captured
    # in setup_nginx().  Fall back to a direct Gunicorn check so a nginx-only
    # problem does not trigger a full rollback of application code.
    log_warn "nginx health check failed — falling back to direct Gunicorn check..."
    if health_check "http://localhost:5000/health" 6 5; then
        log_warn "Gunicorn is running but nginx is not proxying traffic."
        log_warn "The application is accessible on port 5000 only."
        log_warn "Investigate nginx: sudo systemctl status nginx"
        log_warn "                   sudo journalctl -u nginx -n 50"
        # Return success: the app itself is healthy; nginx is a proxy issue.
        return 0
    fi

    log_error "Both nginx and Gunicorn health checks failed — initiating rollback."
    do_rollback
    exit 1
}

# ── Rollback ──────────────────────────────────────────────────────────────────
do_rollback() {
    log_section "ROLLBACK"
    log_warn "Rolling back to: ${PRE_UPDATE_VERSION} (${PRE_UPDATE_HASH:0:8})"

    # 1. Code rollback
    # For git+rsync installs: revert the source checkout to the pre-update
    # commit, then re-sync to the deployed directory.
    # For archive/local installs: rely on the pre-update backup.
    if [[ "$PRE_UPDATE_HASH" != "unknown" ]] \
        && git -C "$REPO_DIR" rev-parse --git-dir &>/dev/null 2>&1; then

        git -C "$REPO_DIR" checkout "$PRE_UPDATE_HASH" -- . >> "$LOG_FILE" 2>&1 \
            || log_warn "Code rollback in source checkout failed — manual intervention may be needed."

        # Re-sync the rolled-back source to the deployed directory.
        rsync -a --delete \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='.env' \
            --exclude='venv/' \
            --exclude='lop/' \
            --exclude='artifacts/' \
            --exclude='/lib/' \
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
            || log_warn "rsync rollback sync failed — deployed files may be inconsistent."

        log_info "Code rolled back to ${PRE_UPDATE_HASH:0:8} and re-synced to ${LOP_APP_DIR}."
    else
        log_warn "Code rollback is not available (archive, local-directory, or non-git install)."
        log_warn "The application code cannot be automatically restored."
        if [[ -n "${BACKUP_PATH:-}" ]]; then
            log_info "Restore from backup to recover the previous state:"
            log_info "  sudo lop restore ${BACKUP_PATH}"
        else
            log_warn "No pre-update backup was taken. Manual recovery required."
            log_warn "Re-extract the previous version archive and re-run the installer."
        fi
    fi

    # 2. Schema rollback
    if [[ "$MIGRATIONS_RAN" == "true" ]] && [[ "$PRE_UPDATE_ALEMBIC" != "unknown" ]]; then
        log_step "Rolling back database schema to ${PRE_UPDATE_ALEMBIC}..."
        lop_flask db downgrade "$PRE_UPDATE_ALEMBIC" >> "$LOG_FILE" 2>&1 \
            || log_warn "Schema rollback failed. Manual DB restore may be required."
        log_info "Database schema rolled back."
    fi

    # 3. Reinstall previous deps
    if [[ "$DEPS_UPGRADED" == "true" ]]; then
        python_install_deps >> "$LOG_FILE" 2>&1 || log_warn "Dep rollback failed."
    fi

    # 4. Restart service
    systemctl restart "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 || true

    # 5. Verify rollback
    log_step "Verifying rollback health..."
    if health_check "http://localhost:5000/health" 6 5; then
        log_success "ROLLBACK SUCCESSFUL — LOP is running ${PRE_UPDATE_VERSION}."
        if [[ -n "$BACKUP_PATH" ]]; then
            log_info "Pre-update backup is available at: ${BACKUP_PATH}"
        fi
    else
        printf "\n%s%s[CRITICAL] Rollback health check failed.%s\n" "$CLR_BOLD" "$CLR_RED" "$CLR_RESET"
        printf "LOP may be in an inconsistent state. Manual intervention required.\n\n"
        printf "Recovery steps:\n"
        printf "  1. Check logs:     sudo journalctl -u lop-backend -n 100\n"
        printf "  2. Check log file: %s\n" "$LOG_FILE"
        if [[ -n "$BACKUP_PATH" ]]; then
            printf "  3. Restore backup: sudo ./restore.sh %s\n" "$BACKUP_PATH"
        fi
    fi
}

# ── Save post-update state ────────────────────────────────────────────────────
save_update_state() {
    checksums_save_all
    local new_version
    new_version=$(version_get "APP_VERSION" "$LOP_APP_DIR/VERSION")
    install_info_update "install_version" "$new_version"
    install_info_update "last_update" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    install_info_update "previous_version" "$PRE_UPDATE_VERSION"
}

# ── Print update summary ──────────────────────────────────────────────────────
print_update_summary() {
    local new_version new_hash
    new_version=$(version_get "APP_VERSION" "$LOP_APP_DIR/VERSION")
    new_hash=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null | head -c 8 || echo "unknown")

    printf "\n%s%s╔══════════════════════════════════════════════╗%s\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"
    printf "%s%s║         LOP Update Complete                  ║%s\n"   "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"
    printf "%s%s╚══════════════════════════════════════════════╝%s\n\n" "$CLR_BOLD" "$CLR_GREEN" "$CLR_RESET"

    summary_line "Previous version:"    "${PRE_UPDATE_VERSION}"
    summary_line "New version:"         "${new_version} (${new_hash})"
    summary_line "DB schema:"           "$(alembic_current 2>/dev/null || echo 'unknown')"
    summary_line "Dependencies updated:" "$([[ $DEPS_UPGRADED == true ]] && echo yes || echo no)"
    summary_line "Migrations applied:"  "$([[ $MIGRATIONS_RAN  == true ]] && echo yes || echo no)"
    summary_line "Service restarted:"   "$([[ $RESTART_NEEDED  == true ]] && echo yes || echo no)"
    if [[ -n "$BACKUP_PATH" ]]; then summary_line "Pre-update backup:" "$BACKUP_PATH"; fi
    printf "\n"
    summary_line "Log:" "$LOG_FILE"
    printf "\n"
}

# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================
main() {
    require_root "$@"

    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"

    log_header "LOP Update — $(date)"

    preflight_checks
    run_pre_update_backup
    pull_latest_code
    apply_changes
    setup_nginx           # install + configure + start nginx (always, idempotent)
    post_update_health_check
    save_update_state
    print_update_summary
}

main "$@"
