#!/usr/bin/env bash
# =============================================================================
# LOP — Health check script
# Usage: sudo ./health.sh [--json] [--quiet]
#
# Reports PASS / WARN / FAIL for every component.
# Exit codes: 0=all pass, 1=warnings, 2=failures
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOG_FILE="/var/log/lop/health.log"

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/version.sh"

OUTPUT_JSON=false
QUIET=false

parse_common_flags "$@"
for arg in "${REMAINING_ARGS[@]:-}"; do
    case "$arg" in
        --json)  OUTPUT_JSON=true ;;
        --quiet) QUIET=true ;;
    esac
done

# ── Result tracking ───────────────────────────────────────────────────────────
declare -i PASS_COUNT=0 WARN_COUNT=0 FAIL_COUNT=0
declare -A RESULTS  # key → "PASS|WARN|FAIL:message"

record() {
    local key="$1" status="$2" message="$3"
    RESULTS["$key"]="${status}:${message}"
    case "$status" in
        PASS) (( PASS_COUNT++ )) ;;
        WARN) (( WARN_COUNT++ )) ;;
        FAIL) (( FAIL_COUNT++ )) ;;
    esac
}

print_result() {
    local key="$1"
    local raw="${RESULTS[$key]:-FAIL:not checked}"
    local status="${raw%%:*}" message="${raw#*:}"
    local colour
    case "$status" in
        PASS) colour="$CLR_GREEN" ;;
        WARN) colour="$CLR_YELLOW" ;;
        FAIL) colour="$CLR_RED" ;;
        *)    colour="$CLR_WHITE" ;;
    esac
    printf "  %-32s %s%s%-6s%s %s\n" \
        "$key" "$CLR_BOLD" "$colour" "$status" "$CLR_RESET" "$message"
}

# ── Individual checks ─────────────────────────────────────────────────────────

check_service() {
    local svc="$LOP_BACKEND_SERVICE"
    if ! cmd_exists systemctl; then
        record "Service: lop-backend" "WARN" "systemctl not available"
        return
    fi
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        local uptime
        uptime=$(systemctl show "$svc" --property=ActiveEnterTimestamp \
            | cut -d= -f2 | sed 's/n\/a/unknown/' 2>/dev/null || echo "unknown")
        record "Service: lop-backend" "PASS" "active since ${uptime}"
    else
        local state
        state=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
        record "Service: lop-backend" "FAIL" "state=${state}"
    fi
}

check_backend_api() {
    local url="http://localhost:5000/health"
    local start_ms end_ms elapsed_ms
    start_ms=$(date +%s%3N 2>/dev/null || echo 0)

    local response http_code body
    response=$(curl -s --max-time 5 -w "\n%{http_code}" "$url" 2>/dev/null || true)
    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -1)

    end_ms=$(date +%s%3N 2>/dev/null || echo 0)
    elapsed_ms=$(( end_ms - start_ms ))

    if [[ "$http_code" == "200" ]]; then
        record "Backend API: GET /health" "PASS" "HTTP ${http_code} (${elapsed_ms}ms)"
        # Store body for version extraction
        HEALTH_RESPONSE_BODY="$body"
    elif [[ -z "$http_code" ]] || [[ "$http_code" == "000" ]]; then
        record "Backend API: GET /health" "FAIL" "no response (service may be down)"
    else
        record "Backend API: GET /health" "FAIL" "HTTP ${http_code}"
    fi
}

check_database() {
    # Try psql connectivity
    if ! cmd_exists psql; then
        record "Database: connectivity" "WARN" "psql not available for direct check"
        return
    fi

    local db_url
    db_url=$(grep '^DATABASE_URL=' "$LOP_CONF_FILE" 2>/dev/null | cut -d= -f2 || true)
    if [[ -z "$db_url" ]]; then
        record "Database: connectivity" "WARN" "DATABASE_URL not found in config"
        return
    fi

    if PGPASSWORD="" psql "$db_url" -c "SELECT 1" &>/dev/null 2>&1; then
        record "Database: connectivity" "PASS" "connected"
    else
        record "Database: connectivity" "FAIL" "cannot connect to database"
    fi
}

check_schema_versions() {
    if [[ ! -d "$LOP_APP_DIR" ]]; then
        record "Database: deployed schema" "FAIL" "LOP not installed"
        record "Database: codebase schema" "FAIL" "LOP not installed"
        return
    fi

    load_lop_env 2>/dev/null || true

    local deployed head
    deployed=$(alembic_current 2>/dev/null || echo "unknown")
    head=$(alembic_head 2>/dev/null || echo "unknown")

    record "Database: deployed schema" \
        "$(  [[ "$deployed" != "unknown" ]] && echo PASS || echo WARN)" \
        "$deployed"

    if [[ "$deployed" == "$head" ]] && [[ "$deployed" != "unknown" ]]; then
        record "Database: schema vs codebase" "PASS" "up to date (${head:0:8})"
    elif [[ "$head" == "unknown" ]]; then
        record "Database: schema vs codebase" "WARN" "cannot read codebase head"
    else
        record "Database: schema vs codebase" "WARN" \
            "behind — deployed=${deployed:0:8} head=${head:0:8} — run: sudo lop update"
    fi
}

check_python_runtime() {
    if [[ -f "$LOP_RUNTIME_FILE" ]]; then
        local sel_py sel_ver
        sel_py=$(grep '^LOP_PYTHON=' "$LOP_RUNTIME_FILE" | cut -d= -f2)
        sel_ver=$(grep '^LOP_PYTHON_VERSION=' "$LOP_RUNTIME_FILE" | cut -d= -f2)
        record "Python: selected interpreter" "PASS" "${sel_py} (${sel_ver})"
    else
        record "Python: selected interpreter" "WARN" "runtime.env not found"
    fi

    if [[ -x "$LOP_VENV_DIR/bin/python" ]]; then
        local venv_ver
        venv_ver=$("$LOP_VENV_DIR/bin/python" --version 2>/dev/null | awk '{print $2}')
        record "Python: virtual environment" "PASS" "${LOP_VENV_DIR} (${venv_ver})"
    else
        record "Python: virtual environment" "FAIL" "not found at ${LOP_VENV_DIR}"
    fi
}

check_versions() {
    local app_ver installer_ver build_date db_schema git_hash
    if [[ -f "$LOP_APP_DIR/VERSION" ]]; then
        app_ver=$(grep '^APP_VERSION=' "$LOP_APP_DIR/VERSION" | cut -d= -f2)
        installer_ver=$(grep '^INSTALLER_VERSION=' "$LOP_APP_DIR/VERSION" | cut -d= -f2)
        build_date=$(grep '^BUILD_DATE=' "$LOP_APP_DIR/VERSION" | cut -d= -f2)
    else
        app_ver="unknown"; installer_ver="unknown"; build_date="unknown"
    fi
    git_hash=$(git -C "$LOP_APP_DIR" rev-parse HEAD 2>/dev/null | head -c 8 || echo "unknown")

    record "Version: application"   "PASS" "${app_ver}"
    record "Version: installer"     "PASS" "${installer_ver}"
    record "Version: build date"    "PASS" "${build_date}"
    record "Version: git commit"    "PASS" "${git_hash}"
}

check_disk() {
    local paths=("$LOP_APP_DIR" "$LOP_LOG_DIR" "$LOP_BACKUP_DIR")
    for path in "${paths[@]}"; do
        [[ -d "$path" ]] || continue
        local pct_used free_human
        pct_used=$(df "$path" 2>/dev/null | awk 'NR==2{gsub(/%/,""); print $5}')
        free_human=$(df -h "$path" 2>/dev/null | awk 'NR==2{print $4}')
        local pct_free=$(( 100 - ${pct_used:-0} ))
        local status="PASS"
        [[ $pct_free -lt 20 ]] && status="WARN"
        [[ $pct_free -lt 5  ]] && status="FAIL"
        record "Disk: ${path}" "$status" \
            "${pct_free}% free (${free_human} available, ${pct_used}% used)"
    done
}

check_memory() {
    if cmd_exists free; then
        local total_kb used_kb free_kb
        total_kb=$(free | awk '/^Mem:/{print $2}')
        used_kb=$(free  | awk '/^Mem:/{print $3}')
        free_kb=$(free  | awk '/^Mem:/{print $4}')
        local total_mb=$(( total_kb / 1024 ))
        local used_mb=$(( used_kb  / 1024 ))
        local free_mb=$(( free_kb  / 1024 ))
        local pct_used=$(( used_mb * 100 / (total_mb > 0 ? total_mb : 1) ))
        local status="PASS"
        [[ $pct_used -gt 85 ]] && status="WARN"
        [[ $pct_used -gt 95 ]] && status="FAIL"
        record "Memory" "$status" \
            "${used_mb}MB / ${total_mb}MB used (${pct_used}%)"
    else
        record "Memory" "WARN" "free command not available"
    fi
}

# ── Text output ───────────────────────────────────────────────────────────────
print_text_report() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"

    printf "\n%s%s LOP Health Report  —  %s%s\n\n" \
        "$CLR_BOLD" "$CLR_WHITE" "$ts" "$CLR_RESET"

    local sections=(
        "Service"
        "Backend API"
        "Database"
        "Python"
        "Version"
        "Disk"
        "Memory"
    )

    for section in "${sections[@]}"; do
        local found=false
        for key in "${!RESULTS[@]}"; do
            [[ "$key" == "${section}"* ]] || continue
            if [[ "$found" == "false" ]]; then
                printf "  %s%s%s\n" "$CLR_BOLD" "$section" "$CLR_RESET"
                found=true
            fi
            print_result "$key"
        done
        [[ "$found" == "true" ]] && printf "\n"
    done

    # Overall
    local overall_colour="$CLR_GREEN" overall_status="PASS"
    (( FAIL_COUNT > 0 )) && { overall_colour="$CLR_RED";    overall_status="FAIL"; }
    (( FAIL_COUNT == 0 && WARN_COUNT > 0 )) && \
                           { overall_colour="$CLR_YELLOW"; overall_status="WARN"; }

    printf "  %s%s%-32s %s%-6s%s (%d pass, %d warn, %d fail)%s\n\n" \
        "$CLR_BOLD" "$CLR_WHITE" "Overall" \
        "$overall_colour" "$overall_status" "$CLR_RESET" \
        "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT" "$CLR_RESET"
}

# ── JSON output ───────────────────────────────────────────────────────────────
print_json_report() {
    printf '{\n'
    printf '  "timestamp": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "overall": "%s",\n' \
        "$( (( FAIL_COUNT > 0 )) && echo FAIL || \
            (( WARN_COUNT > 0 )) && echo WARN || echo PASS)"
    printf '  "counts": {"pass": %d, "warn": %d, "fail": %d},\n' \
        "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
    printf '  "checks": {\n'
    local first=true
    for key in "${!RESULTS[@]}"; do
        local raw="${RESULTS[$key]}" status="${RESULTS[$key]%%:*}" message="${RESULTS[$key]#*:}"
        [[ "$first" == "false" ]] && printf ',\n'
        printf '    "%s": {"status": "%s", "message": "%s"}' \
            "$key" "$status" "$message"
        first=false
    done
    printf '\n  }\n}\n'
}

# =============================================================================
main() {
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"

    # Load config (non-fatal if not installed)
    [[ -f "$LOP_CONF_FILE" ]] && { load_lop_env 2>/dev/null || true; }

    # Run all checks
    check_service
    check_backend_api
    check_database
    check_schema_versions
    check_python_runtime
    check_versions
    check_disk
    check_memory

    # Output
    if [[ "$OUTPUT_JSON" == "true" ]]; then
        print_json_report
    elif [[ "$QUIET" != "true" ]]; then
        print_text_report
    fi

    # Log summary
    printf "[%s] Health check: %d pass, %d warn, %d fail\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT" \
        >> "$LOG_FILE" 2>/dev/null || true

    # Exit code
    (( FAIL_COUNT > 0 )) && exit 2
    (( WARN_COUNT > 0 )) && exit 1
    exit 0
}

main "$@"
