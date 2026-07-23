#!/usr/bin/env bash
# =============================================================================
# LOP — Service management
# Usage: sudo ./scripts/service.sh <command>
#
# Commands:
#   start    Start all LOP services in order (PostgreSQL → lop-backend → nginx)
#   stop     Stop lop-backend and nginx gracefully (PostgreSQL is not stopped)
#   restart  Restart nginx (if config changed) then lop-backend; verify both active
#   reload   Reload nginx configuration and reload the systemd daemon
#   status   Show a concise status summary for all LOP services
#   health   Run HTTP health checks against nginx and the application endpoint
#   logs     Show recent logs from lop-backend and nginx via journalctl
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/var/log/lop/service.log"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/systemd.sh"
source "$SCRIPT_DIR/lib/nginx.sh"

# ── PostgreSQL service name detection ─────────────────────────────────────────
# Probes systemd for the exact unit name without sourcing the full postgres.sh.
# Naming conventions by distro:
#   Rocky / RHEL  → postgresql-16 (or -15, -14, -13)
#   Debian/Ubuntu → postgresql@16-main  (or postgresql)
_detect_pg_service() {
    # First: check running/loaded units (catches the common case instantly)
    local unit
    unit=$(systemctl list-units --type=service --all --no-legend 2>/dev/null \
           | awk '{print $1}' \
           | { grep -E '^postgresql' || true; } \
           | awk 'NR==1{print}')
    [[ -n "$unit" ]] && { echo "$unit"; return 0; }

    # Second: check unit files (catches enabled-but-not-yet-started units)
    unit=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
           | awk '{print $1}' \
           | { grep -E '^postgresql' || true; } \
           | awk 'NR==1{print}')
    [[ -n "$unit" ]] && { echo "$unit"; return 0; }

    # Third: probe versioned names explicitly
    local ver
    for ver in 16 15 14 13; do
        if systemctl cat "postgresql-${ver}" &>/dev/null 2>&1; then
            echo "postgresql-${ver}"; return 0
        fi
    done

    # Fallback — may not exist; callers check with _svc_state
    echo "postgresql"
}

_PG_SERVICE=""
_pg_service() {
    [[ -z "$_PG_SERVICE" ]] && _PG_SERVICE=$(_detect_pg_service)
    echo "$_PG_SERVICE"
}

# ── Service state query ────────────────────────────────────────────────────────
# Returns one of: running | stopped | not-installed
_svc_state() {
    local svc="$1"
    if ! systemctl cat "$svc" &>/dev/null 2>&1; then
        echo "not-installed"
    elif systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "running"
    else
        echo "stopped"
    fi
}

# ── Status display helpers ─────────────────────────────────────────────────────
_status_row() {
    local label="$1" state="$2"
    local colour
    case "$state" in
        running)       colour="${CLR_GREEN}${CLR_BOLD}"  ;;
        not-installed) colour="${CLR_YELLOW}${CLR_BOLD}" ;;
        *)             colour="${CLR_RED}${CLR_BOLD}"    ;;
    esac
    printf "  %-20s %s%-14s%s\n" "$label :" "$colour" "$state" "$CLR_RESET"
}

_health_row() {
    local label="$1" result="$2"
    local colour
    [[ "$result" == "OK" ]] && colour="${CLR_GREEN}${CLR_BOLD}" || colour="${CLR_RED}${CLR_BOLD}"
    printf "  %-20s %s%-14s%s\n" "$label :" "$colour" "$result" "$CLR_RESET"
}

# =============================================================================
# ── COMMANDS ──────────────────────────────────────────────────────────────────
# =============================================================================

# ── start ─────────────────────────────────────────────────────────────────────
cmd_start() {
    log_section "Starting LOP Services"

    # 1. PostgreSQL — must be up before the application connects
    local pg_svc; pg_svc=$(_pg_service)
    local pg_state; pg_state=$(_svc_state "$pg_svc")
    case "$pg_state" in
        running)
            log_info "PostgreSQL (${pg_svc}): already running."
            ;;
        not-installed)
            log_warn "PostgreSQL service '${pg_svc}' not found — skipping."
            log_warn "Ensure PostgreSQL is managed by LOP or start it manually before"
            log_warn "starting lop-backend."
            ;;
        stopped)
            log_step "Starting PostgreSQL (${pg_svc})..."
            systemctl start "$pg_svc" >> "$LOG_FILE" 2>&1 \
                || abort "Failed to start PostgreSQL (${pg_svc}).
Check:   sudo systemctl status ${pg_svc}
Journal: sudo journalctl -u ${pg_svc} -n 50 --no-pager
Log:     ${LOG_FILE}"
            log_success "PostgreSQL started."
            ;;
    esac

    # 2. lop-backend
    local be_state; be_state=$(_svc_state "$LOP_BACKEND_SERVICE")
    case "$be_state" in
        running)
            log_info "${LOP_BACKEND_SERVICE}: already running."
            ;;
        not-installed)
            abort "${LOP_BACKEND_SERVICE} service unit not found.
Is LOP installed? Run: sudo ./scripts/install.sh"
            ;;
        stopped)
            log_step "Starting ${LOP_BACKEND_SERVICE}..."
            systemctl start "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 \
                || abort "Failed to start ${LOP_BACKEND_SERVICE}.
Check:   sudo systemctl status ${LOP_BACKEND_SERVICE}
Journal: sudo journalctl -u ${LOP_BACKEND_SERVICE} -n 50 --no-pager
Log:     ${LOG_FILE}"
            log_success "${LOP_BACKEND_SERVICE} started."
            ;;
    esac

    # 3. nginx
    local ng_state; ng_state=$(_svc_state "$LOP_NGINX_SERVICE")
    case "$ng_state" in
        running)
            log_info "${LOP_NGINX_SERVICE}: already running."
            ;;
        not-installed)
            log_warn "nginx not installed — skipping."
            log_warn "Run 'sudo ./scripts/install.sh' or 'sudo ./scripts/update.sh'"
            log_warn "to install and configure nginx."
            ;;
        stopped)
            # Validate config before starting
            if nginx -t >> "$LOG_FILE" 2>&1; then
                log_step "Starting ${LOP_NGINX_SERVICE}..."
                systemctl start "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
                    || abort "Failed to start nginx.
Check:   sudo systemctl status nginx
Journal: sudo journalctl -u nginx -n 50 --no-pager
Log:     ${LOG_FILE}"
                log_success "nginx started."
            else
                log_error "nginx configuration test failed — nginx not started."
                log_error "Run 'sudo nginx -t' for details."
                exit 1
            fi
            ;;
    esac

    log_success "All LOP services started."
}

# ── stop ──────────────────────────────────────────────────────────────────────
cmd_stop() {
    log_section "Stopping LOP Services"
    log_info "PostgreSQL will NOT be stopped. Stop it explicitly if needed:"
    log_info "  sudo systemctl stop \$(\$SCRIPT_DIR/scripts/service.sh _pg_name)"

    # Stop nginx first to drain connections before the backend stops
    local ng_state; ng_state=$(_svc_state "$LOP_NGINX_SERVICE")
    if [[ "$ng_state" == "running" ]]; then
        log_step "Stopping ${LOP_NGINX_SERVICE}..."
        systemctl stop "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
            || log_warn "Could not stop nginx."
        log_success "nginx stopped."
    else
        log_info "nginx: not running (state: ${ng_state})."
    fi

    # Stop lop-backend (gunicorn shuts down workers gracefully on SIGTERM)
    local be_state; be_state=$(_svc_state "$LOP_BACKEND_SERVICE")
    if [[ "$be_state" == "running" ]]; then
        log_step "Stopping ${LOP_BACKEND_SERVICE}..."
        systemctl stop "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 \
            || log_warn "Could not stop ${LOP_BACKEND_SERVICE}."
        log_success "${LOP_BACKEND_SERVICE} stopped."
    else
        log_info "${LOP_BACKEND_SERVICE}: not running (state: ${be_state})."
    fi

    log_success "Application services stopped."
}

# ── restart ───────────────────────────────────────────────────────────────────
cmd_restart() {
    log_section "Restarting LOP Services"

    # 1. Validate and restart nginx first so incoming connections are drained
    #    before the backend goes away, then come back up after it does.
    local ng_state; ng_state=$(_svc_state "$LOP_NGINX_SERVICE")
    if [[ "$ng_state" != "not-installed" ]]; then
        log_step "Testing nginx configuration..."
        if nginx -t >> "$LOG_FILE" 2>&1; then
            log_step "Restarting ${LOP_NGINX_SERVICE}..."
            systemctl restart "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
                || abort "Failed to restart nginx.
Check:   sudo systemctl status nginx
Journal: sudo journalctl -u nginx -n 50 --no-pager
Log:     ${LOG_FILE}"
            log_success "nginx restarted."
        else
            log_error "nginx configuration test failed — nginx NOT restarted."
            log_error "Run 'sudo nginx -t' for details."
            exit 1
        fi
    else
        log_warn "nginx not installed — skipping nginx restart."
    fi

    # 2. Restart lop-backend
    if ! systemctl cat "$LOP_BACKEND_SERVICE" &>/dev/null 2>&1; then
        abort "${LOP_BACKEND_SERVICE} service unit not found.
Is LOP installed? Run: sudo ./scripts/install.sh"
    fi
    log_step "Restarting ${LOP_BACKEND_SERVICE}..."
    systemctl restart "$LOP_BACKEND_SERVICE" >> "$LOG_FILE" 2>&1 \
        || abort "Failed to restart ${LOP_BACKEND_SERVICE}.
Check:   sudo systemctl status ${LOP_BACKEND_SERVICE}
Journal: sudo journalctl -u ${LOP_BACKEND_SERVICE} -n 50 --no-pager
Log:     ${LOG_FILE}"
    log_success "${LOP_BACKEND_SERVICE} restarted."

    # 3. Verify both services are active
    local failures=0
    if ! systemctl is-active --quiet "$LOP_BACKEND_SERVICE" 2>/dev/null; then
        log_error "${LOP_BACKEND_SERVICE} is NOT active after restart."
        failures=$(( failures + 1 ))
    else
        log_success "${LOP_BACKEND_SERVICE}: active."
    fi
    if [[ "$ng_state" != "not-installed" ]]; then
        if ! systemctl is-active --quiet "$LOP_NGINX_SERVICE" 2>/dev/null; then
            log_error "nginx is NOT active after restart."
            failures=$(( failures + 1 ))
        else
            log_success "nginx: active."
        fi
    fi

    if (( failures > 0 )); then
        log_error "One or more services failed to become active."
        log_error "Run: sudo ./scripts/service.sh logs"
        exit 1
    fi

    log_success "All services restarted and active."
}

# ── reload ────────────────────────────────────────────────────────────────────
cmd_reload() {
    log_section "Reloading LOP Configuration"

    # Always reload the systemd daemon first — picks up any unit file changes
    log_step "Reloading systemd daemon..."
    systemctl daemon-reload >> "$LOG_FILE" 2>&1 \
        || log_warn "systemctl daemon-reload failed (non-fatal)."
    log_success "systemd daemon reloaded."

    # Reload nginx if it is installed
    local ng_state; ng_state=$(_svc_state "$LOP_NGINX_SERVICE")
    case "$ng_state" in
        running)
            log_step "Testing nginx configuration..."
            if nginx -t >> "$LOG_FILE" 2>&1; then
                log_step "Reloading nginx (zero-downtime)..."
                systemctl reload "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 || {
                    log_warn "nginx reload returned non-zero — attempting full restart..."
                    systemctl restart "$LOP_NGINX_SERVICE" >> "$LOG_FILE" 2>&1 \
                        || {
                            log_error "nginx restart also failed."
                            exit 1
                        }
                }
                log_success "nginx configuration reloaded."
            else
                log_error "nginx configuration test FAILED — nginx not reloaded."
                log_error "Run 'sudo nginx -t' for details."
                exit 1
            fi
            ;;
        stopped)
            log_warn "nginx is installed but not running."
            log_warn "Start it with: sudo ./scripts/service.sh start"
            ;;
        not-installed)
            log_warn "nginx not installed — skipping nginx reload."
            ;;
    esac

    log_success "Reload complete."
}

# ── status ────────────────────────────────────────────────────────────────────
cmd_status() {
    # Disable set -e for this function: we check multiple services and must
    # report all states even when some are stopped.
    set +e

    local pg_svc; pg_svc=$(_pg_service)
    local pg_state;  pg_state=$(_svc_state "$pg_svc")
    local be_state;  be_state=$(_svc_state "$LOP_BACKEND_SERVICE")
    local ng_state;  ng_state=$(_svc_state "$LOP_NGINX_SERVICE")

    # Quick HTTP health probe (1 attempt, no retries — status should be instant)
    local health_result="UNREACHABLE"
    if curl -sf --max-time 5 "http://localhost/" &>/dev/null \
        || curl -sf --max-time 5 "http://localhost:5000/health" &>/dev/null; then
        health_result="OK"
    fi

    printf "\n%s%s LOP Service Status%s\n" "$CLR_BOLD" "$CLR_WHITE" "$CLR_RESET"
    printf "%s─────────────────────────────────────%s\n" "$CLR_WHITE" "$CLR_RESET"
    _status_row "LOP Backend"  "$be_state"
    _status_row "nginx"        "$ng_state"
    _status_row "PostgreSQL"   "$pg_state"
    printf "%s─────────────────────────────────────%s\n" "$CLR_WHITE" "$CLR_RESET"
    _health_row "Health"       "$health_result"
    printf "\n"

    # Exit non-zero if any critical service is not running
    local rc=0
    [[ "$be_state"  == "running" ]] || rc=1
    # nginx not-installed is not a failure (installer may not have run yet);
    # nginx stopped is a failure.
    [[ "$ng_state" == "running" ]] || [[ "$ng_state" == "not-installed" ]] || rc=1

    set -e
    return $rc
}

# ── health ────────────────────────────────────────────────────────────────────
cmd_health() {
    # Disable set -e: we must probe both endpoints and report all results.
    set +e

    log_section "LOP Health Check"
    local overall_rc=0

    # ── Check 1: nginx reverse proxy (port 80) ──────────────────────────────
    log_step "Probing http://localhost/ (nginx → lop-backend)..."
    local nginx_code
    nginx_code=$(curl -s -o /dev/null -w "%{http_code}" \
                      --max-time 10 "http://localhost/" 2>/dev/null)
    [[ -z "$nginx_code" ]] && nginx_code="000"

    case "$nginx_code" in
        200|301|302)
            log_success "http://localhost/              HTTP ${nginx_code}   [PASS]"
            ;;
        000)
            log_error   "http://localhost/              no response          [FAIL]"
            log_error   "nginx may be down or not installed."
            log_error   "Check: sudo systemctl status nginx"
            overall_rc=1
            ;;
        *)
            log_warn    "http://localhost/              HTTP ${nginx_code}   [WARN — unexpected]"
            ;;
    esac

    # ── Check 2: application health endpoint ────────────────────────────────
    log_step "Probing http://localhost/health (application)..."
    local health_code
    health_code=$(curl -s -o /dev/null -w "%{http_code}" \
                       --max-time 10 "http://localhost/health" 2>/dev/null)
    [[ -z "$health_code" ]] && health_code="000"

    case "$health_code" in
        200)
            log_success "http://localhost/health        HTTP ${health_code}   [PASS]"
            ;;
        000)
            # nginx is down — try Gunicorn directly as a diagnostic
            log_warn    "http://localhost/health        no response          [FAIL]"
            log_step    "Falling back to direct Gunicorn check (http://localhost:5000/health)..."
            local direct_code
            direct_code=$(curl -s -o /dev/null -w "%{http_code}" \
                               --max-time 10 "http://localhost:5000/health" 2>/dev/null)
            [[ -z "$direct_code" ]] && direct_code="000"
            if [[ "$direct_code" == "200" ]]; then
                log_warn "http://localhost:5000/health   HTTP ${direct_code}   [PASS via Gunicorn]"
                log_warn "Application is running but nginx is not proxying — check nginx:"
                log_warn "  sudo systemctl status nginx"
                log_warn "  sudo journalctl -u nginx -n 50 --no-pager"
            else
                log_error "http://localhost:5000/health  HTTP ${direct_code}   [FAIL]"
                log_error "lop-backend does not appear to be running."
                log_error "Check: sudo systemctl status lop-backend"
                overall_rc=1
            fi
            ;;
        *)
            log_warn    "http://localhost/health        HTTP ${health_code}   [WARN — unexpected]"
            ;;
    esac

    # ── Summary ─────────────────────────────────────────────────────────────
    printf "\n"
    if (( overall_rc == 0 )); then
        log_success "Health check: PASS"
    else
        log_error   "Health check: FAIL"
        log_error   "Investigate: sudo ./scripts/service.sh logs"
        log_error   "Log file:    ${LOG_FILE}"
    fi

    set -e
    return $overall_rc
}

# ── logs ──────────────────────────────────────────────────────────────────────
cmd_logs() {
    printf "\n%s%s══  lop-backend — last 50 lines  ══%s\n\n" \
        "$CLR_BOLD" "$CLR_CYAN" "$CLR_RESET"
    journalctl -u "$LOP_BACKEND_SERVICE" -n 50 --no-pager 2>/dev/null \
        || log_warn "${LOP_BACKEND_SERVICE} journal not available \
(service may not exist or journald is not running)."

    printf "\n%s%s══  nginx — last 50 lines  ══%s\n\n" \
        "$CLR_BOLD" "$CLR_CYAN" "$CLR_RESET"
    journalctl -u "$LOP_NGINX_SERVICE" -n 50 --no-pager 2>/dev/null \
        || log_warn "nginx journal not available \
(nginx may not be installed or journald is not running)."
}

# ── usage ─────────────────────────────────────────────────────────────────────
usage() {
    printf "\n%s%sLOP Service Manager%s\n" "$CLR_BOLD" "$CLR_WHITE" "$CLR_RESET"
    printf "Usage: %ssudo %s <command>%s\n\n" "$CLR_BOLD" "$0" "$CLR_RESET"
    printf "Commands:\n"
    printf "  %s%-10s%s  Start all LOP services in order:\n" \
        "$CLR_CYAN" "start" "$CLR_RESET"
    printf "              PostgreSQL → lop-backend → nginx\n"
    printf "  %s%-10s%s  Stop lop-backend and nginx gracefully\n" \
        "$CLR_CYAN" "stop" "$CLR_RESET"
    printf "              (PostgreSQL is NOT stopped)\n"
    printf "  %s%-10s%s  Restart nginx (after config test) then lop-backend;\n" \
        "$CLR_CYAN" "restart" "$CLR_RESET"
    printf "              verify both services become active\n"
    printf "  %s%-10s%s  Reload nginx configuration; reload systemd daemon\n" \
        "$CLR_CYAN" "reload" "$CLR_RESET"
    printf "  %s%-10s%s  Show a concise status summary for all LOP services\n" \
        "$CLR_CYAN" "status" "$CLR_RESET"
    printf "  %s%-10s%s  Run HTTP health checks (nginx + application endpoint)\n" \
        "$CLR_CYAN" "health" "$CLR_RESET"
    printf "  %s%-10s%s  Show last 50 log lines from lop-backend and nginx\n" \
        "$CLR_CYAN" "logs" "$CLR_RESET"
    printf "\nExamples:\n"
    printf "  sudo ./scripts/service.sh status\n"
    printf "  sudo ./scripts/service.sh restart\n"
    printf "  sudo ./scripts/service.sh health\n"
    printf "  sudo ./scripts/service.sh logs\n\n"
}

# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================

require_root "$@"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    reload)  cmd_reload  ;;
    status)  cmd_status  ;;
    health)  cmd_health  ;;
    logs)    cmd_logs    ;;
    "")
        usage
        exit 1
        ;;
    *)
        log_error "Unknown command: '${COMMAND}'"
        usage
        exit 1
        ;;
esac
