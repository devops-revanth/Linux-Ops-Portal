#!/usr/bin/env bash
# =============================================================================
# LOP — nginx reverse proxy management
# Source this file; do not execute it directly.
# =============================================================================

readonly LOP_NGINX_CONF="/etc/nginx/conf.d/lop.conf"
readonly LOP_NGINX_SERVICE="nginx"

# nginx_install
# Installs nginx if not already present.
nginx_install() {
    if cmd_exists nginx; then
        local ver
        ver=$(nginx -v 2>&1 | awk -F'/' '{print $2}')
        log_success "nginx: found ${ver}"
        return 0
    fi
    log_step "Installing nginx..."
    case "$OS_FAMILY" in
        rhel)   pkg_install nginx ;;
        debian) pkg_install nginx ;;
        *)      abort "Cannot install nginx: unknown OS family '${OS_FAMILY}'." ;;
    esac
    log_success "nginx installed."
}

# nginx_write_vhost
# Writes the LOP nginx virtual host to /etc/nginx/conf.d/lop.conf.
# Uses 'default_server' so our block takes precedence over any existing
# server block in nginx.conf (e.g. Rocky Linux 9's welcome page) without
# modifying the distro-managed nginx.conf file.
nginx_write_vhost() {
    log_step "Writing nginx virtual host: ${LOP_NGINX_CONF}..."
    cat > "$LOP_NGINX_CONF" <<'NGINXEOF'
# LOP nginx reverse proxy
# Managed by the LOP installer. Changes may be overwritten by lop install/update.
# Edit /etc/lop/lop.env or re-run 'sudo lop install' to regenerate.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    access_log /var/log/nginx/lop-access.log;
    error_log  /var/log/nginx/lop-error.log  warn;

    # Increase buffer sizes for large API responses / file uploads
    client_max_body_size 32m;
    proxy_buffer_size    16k;
    proxy_buffers        8 16k;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;

        # Preserve real client information
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Timeouts — must be >= gunicorn --timeout (60s default)
        proxy_connect_timeout 10s;
        proxy_read_timeout    90s;
        proxy_send_timeout    90s;
    }
}
NGINXEOF
    chmod 644 "$LOP_NGINX_CONF"
    log_success "nginx virtual host written."
}

# nginx_enable_selinux
# On SELinux-enforcing systems (Rocky/RHEL) nginx cannot connect to
# localhost:5000 by default because it is a non-standard port.
# httpd_can_network_connect allows nginx to make arbitrary TCP connections.
nginx_enable_selinux() {
    if ! cmd_exists getenforce; then return 0; fi
    local mode
    mode=$(getenforce 2>/dev/null || echo "Disabled")
    if [[ "$mode" == "Disabled" ]] || [[ "$mode" == "Permissive" ]]; then
        return 0
    fi
    log_step "Enabling SELinux boolean httpd_can_network_connect for nginx proxy..."
    setsebool -P httpd_can_network_connect 1 >> "$LOG_FILE" 2>&1 \
        || log_warn "setsebool failed — nginx may not be able to proxy to Gunicorn under SELinux."
    log_success "SELinux: httpd_can_network_connect enabled."
}

# nginx_open_firewall
# Opens port 80 via firewalld (if active).  Replaces the previous port-5000
# warning — Gunicorn is no longer directly exposed to users.
nginx_open_firewall() {
    if ! cmd_exists firewall-cmd; then return 0; fi
    if ! firewall-cmd --state &>/dev/null 2>&1; then return 0; fi

    log_step "Opening port 80/tcp in firewalld..."
    firewall-cmd --permanent --add-service=http >> "$LOG_FILE" 2>&1 || true
    firewall-cmd --reload >> "$LOG_FILE" 2>&1 || true
    log_success "firewalld: port 80 (http) opened."
}

# nginx_setup
# Full orchestration: install → SELinux → vhost → test → enable → start.
# Idempotent: safe to call on reinstall, repair, or update.
nginx_setup() {
    log_section "nginx Reverse Proxy"

    nginx_install
    nginx_enable_selinux
    nginx_open_firewall
    nginx_write_vhost

    # Validate configuration before touching the service
    nginx -t >> "$LOG_FILE" 2>&1 \
        || abort "nginx configuration test failed.
Check: sudo nginx -t
Log:   ${LOG_FILE}"

    systemctl enable "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 || true

    if systemctl is-active --quiet "$LOP_NGINX_SERVICE" 2>/dev/null; then
        log_step "Reloading nginx..."
        systemctl reload "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
            || systemctl restart "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
            || abort "Failed to reload nginx. Check: sudo journalctl -u nginx -n 30"
    else
        log_step "Starting nginx..."
        systemctl start "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
            || abort "Failed to start nginx.
Check: sudo systemctl status nginx
       sudo journalctl -u nginx -n 50
Log:   ${LOG_FILE}"
    fi

    log_success "nginx running — routing http://localhost/ → Gunicorn :5000"
}

# nginx_verify
# Confirms that nginx is proxying requests correctly.
# Accepts HTTP 200 or 302 (login redirect) as success.
# Returns 1 (non-fatal) if the check times out — install still succeeds.
nginx_verify() {
    log_step "Verifying nginx proxy (curl http://localhost/)..."
    local retries=12 interval=5
    for (( i=1; i<=retries; i++ )); do
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
                         --max-time 5 http://localhost/ 2>/dev/null || echo "0")
        case "$http_code" in
            200|302|301)
                log_success "nginx proxy verified: HTTP ${http_code}"
                return 0
                ;;
        esac
        log_info "  Attempt ${i}/${retries} — HTTP ${http_code} — retrying in ${interval}s..."
        sleep "$interval"
    done
    log_warn "nginx proxy did not respond within timeout."
    log_warn "Check: sudo systemctl status nginx && sudo journalctl -u lop-backend -n 30"
    return 1
}
