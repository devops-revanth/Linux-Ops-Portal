#!/usr/bin/env bash
# =============================================================================
# LOP — systemd service management
# Source this file; do not execute it directly.
# =============================================================================

readonly LOP_BACKEND_UNIT="/etc/systemd/system/lop-backend.service"

# systemd_write_backend
# Generates the lop-backend.service unit file.
# The service file uses the venv's gunicorn directly — no Python path hardcoding.
systemd_write_backend() {
    log_step "Writing systemd unit: ${LOP_BACKEND_UNIT}..."

    # APScheduler runs embedded inside the Flask/Gunicorn process.
    # With multiple workers each worker spawns its own scheduler instance,
    # causing duplicate job execution (double VMware syncs, double Ansible runs).
    # Default to 1 worker; operators who need concurrency must set LOP_WORKERS
    # in /etc/lop/lop.env AND configure a database-backed APScheduler job store
    # to prevent duplicate job fires.
    local workers="${LOP_WORKERS:-1}"
    local timeout="${LOP_TIMEOUT:-60}"

    cat > "$LOP_BACKEND_UNIT" <<EOF
# lop-backend.service — Linux Operations Portal backend
# Managed by the LOP installer. Changes to this file may be overwritten
# by sudo lop install or sudo lop update. Edit /etc/lop/lop.env instead.
[Unit]
Description=Linux Operations Portal Backend
Documentation=https://github.com/devops-revanth/Linux-Ops-Portal
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User=lop
Group=lop
WorkingDirectory=${LOP_APP_DIR}
EnvironmentFile=${LOP_CONF_FILE}
EnvironmentFile=-${LOP_RUNTIME_FILE}

ExecStart=${LOP_VENV_DIR}/bin/gunicorn \\
    --bind 0.0.0.0:5000 \\
    --workers ${workers} \\
    --worker-class sync \\
    --timeout ${timeout} \\
    --access-logfile ${LOP_LOG_DIR}/app/access.log \\
    --error-logfile  ${LOP_LOG_DIR}/app/error.log  \\
    --log-level info \\
    run:app

ExecReload=/bin/kill -HUP \$MAINPID

Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${LOP_LOG_DIR} ${LOP_DATA_DIR}

StandardOutput=journal
StandardError=journal
SyslogIdentifier=lop-backend

[Install]
WantedBy=multi-user.target
EOF

    chmod 644 "$LOP_BACKEND_UNIT"
    track_change "Written systemd unit: ${LOP_BACKEND_UNIT}"
    log_success "Service unit written: lop-backend.service"
}

# systemd_reload
systemd_reload() {
    systemctl daemon-reload >> "$LOG_FILE" 2>&1 \
        || log_warn "systemctl daemon-reload failed (non-fatal)."
}

# systemd_enable_start <service>
systemd_enable_start() {
    local svc="$1"
    log_step "Enabling and starting ${svc}..."
    systemctl enable "$svc" >> "$LOG_FILE" 2>&1 \
        || log_warn "Failed to enable ${svc} (may already be enabled)."
    systemctl start "$svc" >> "$LOG_FILE" 2>&1 \
        || abort "Failed to start ${svc}.
Check: sudo systemctl status ${svc}
Journal: sudo journalctl -u ${svc} --no-pager -n 50
Log: ${LOG_FILE}"
    log_success "${svc} started."
}

# systemd_restart <service>
systemd_restart() {
    local svc="$1"
    log_step "Restarting ${svc}..."
    systemctl restart "$svc" >> "$LOG_FILE" 2>&1 \
        || abort "Failed to restart ${svc}.
Check: sudo systemctl status ${svc}
Journal: sudo journalctl -u ${svc} --no-pager -n 50"
    log_success "${svc} restarted."
}

# systemd_stop <service>
systemd_stop() {
    local svc="$1"
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        log_step "Stopping ${svc}..."
        systemctl stop "$svc" >> "$LOG_FILE" 2>&1 || log_warn "Could not stop ${svc}."
    fi
}

# systemd_is_active <service>
# Returns 0 if the service is active, 1 otherwise.
systemd_is_active() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

# systemd_service_exists <service>
systemd_service_exists() {
    systemctl cat "$1" &>/dev/null
}

# systemd_disable_remove <service>
# Stops, disables, and removes the unit file.
systemd_disable_remove() {
    local svc="$1" unit_file="$2"
    systemd_stop "$svc"
    systemctl disable "$svc" >> "$LOG_FILE" 2>&1 || true
    if [[ -n "$unit_file" ]] && [[ -f "$unit_file" ]]; then rm -f "$unit_file"; fi
    systemd_reload
    log_info "Removed service: ${svc}"
}

# systemd_setup_lop
# Full orchestration: write service → reload → enable → start.
systemd_setup_lop() {
    # Ensure lop system user exists
    if ! id lop &>/dev/null; then
        log_step "Creating 'lop' system user..."
        useradd --system --home-dir "$LOP_APP_DIR" --shell /sbin/nologin \
                --comment "Linux Operations Portal" lop \
            || abort "Failed to create 'lop' system user."
        track_change "Created system user 'lop'"
    fi

    # Set ownership on directories the service writes to
    chown -R lop:lop "$LOP_APP_DIR" "$LOP_LOG_DIR" "$LOP_DATA_DIR" 2>/dev/null || true
    chmod 750 "$LOP_CONF_DIR"
    chown -R root:lop "$LOP_CONF_DIR" 2>/dev/null || true
    chmod 640 "$LOP_CONF_FILE" "$LOP_RUNTIME_FILE" 2>/dev/null || true

    systemd_write_backend
    systemd_reload
    systemd_enable_start "$LOP_BACKEND_SERVICE"
}
