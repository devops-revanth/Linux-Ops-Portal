#!/usr/bin/env bash
# =============================================================================
# LOP — Common utilities shared by all lifecycle scripts
# Source this file; do not execute it directly.
# =============================================================================

# ── Filesystem layout constants ──────────────────────────────────────────────
readonly LOP_APP_DIR="/opt/lop"
readonly LOP_VENV_DIR="/opt/lop/venv"
readonly LOP_CONF_DIR="/etc/lop"
readonly LOP_CONF_FILE="/etc/lop/lop.env"
readonly LOP_RUNTIME_FILE="/etc/lop/runtime.env"
readonly LOP_CREDENTIALS_FILE="/etc/lop/initial_credentials"
readonly LOP_LOG_DIR="/var/log/lop"
readonly LOP_BACKUP_DIR="/var/backups/lop"
readonly LOP_DATA_DIR="/var/lib/lop"
readonly LOP_CHECKSUMS_DIR="/var/lib/lop/checksums"
readonly LOP_INSTALL_INFO="/var/lib/lop/install.info"
readonly LOP_TMP_DIR="/tmp/lop"
readonly LOP_PLUGINS_DIR="/opt/lop/plugins"
readonly LOP_BACKEND_SERVICE="lop-backend"

# Callers set LOG_FILE before sourcing this library.
# Default to /dev/null so log calls never fail if not set.
LOG_FILE="${LOG_FILE:-/dev/null}"

# Track whether destructive changes have been made (for abort messages)
CHANGES_MADE=()

# Honour a global --yes / YES_ALL flag for non-interactive use
YES_ALL="${YES_ALL:-false}"

# ── Terminal colours (disabled when not a tty) ────────────────────────────────
if [[ -t 1 ]] && command -v tput &>/dev/null; then
    CLR_RESET="$(tput sgr0)"
    CLR_BOLD="$(tput bold)"
    CLR_RED="$(tput setaf 1)"
    CLR_GREEN="$(tput setaf 2)"
    CLR_YELLOW="$(tput setaf 3)"
    CLR_BLUE="$(tput setaf 4)"
    CLR_CYAN="$(tput setaf 6)"
    CLR_WHITE="$(tput setaf 7)"
else
    CLR_RESET="" CLR_BOLD="" CLR_RED="" CLR_GREEN=""
    CLR_YELLOW="" CLR_BLUE="" CLR_CYAN="" CLR_WHITE=""
fi

# ── Logging ───────────────────────────────────────────────────────────────────
_log() {
    local level="$1" colour="$2" label="$3"
    shift 3
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    local msg="$*"
    # Colour to terminal
    printf "%s%s[%s]%s %s\n" "$colour" "$CLR_BOLD" "$label" "$CLR_RESET" "$msg"
    # Plain to log file
    printf "[%s] [%s] %s\n" "$ts" "$level" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

log_info()    { _log "INFO"    "$CLR_BLUE"   "INFO"    "$@"; }
log_success() { _log "OK"      "$CLR_GREEN"  "OK"      "$@"; }
log_warn()    { _log "WARN"    "$CLR_YELLOW" "WARN"    "$@"; }
log_error()   { _log "ERROR"   "$CLR_RED"    "ERROR"   "$@"; }
log_step()    { _log "STEP"    "$CLR_CYAN"   "STEP"    "$@"; }
log_section() {
    local ts; ts="$(date '+%Y-%m-%d %H:%M:%S')"
    printf "\n%s%s══  %s  ══%s\n" "$CLR_BOLD" "$CLR_WHITE" "$*" "$CLR_RESET"
    printf "\n[%s] ══  %s  ══\n" "$ts" "$*" >> "$LOG_FILE" 2>/dev/null || true
}
log_header() {
    printf "\n%s%s%s%s\n" "$CLR_BOLD" "$CLR_CYAN" "$*" "$CLR_RESET"
    printf "\n%s\n" "$*" >> "$LOG_FILE" 2>/dev/null || true
}

# ── Root check ────────────────────────────────────────────────────────────────
require_root() {
    if [[ "$EUID" -ne 0 ]]; then
        log_error "This script must be run as root."
        log_error "Try: sudo $0 $*"
        exit 1
    fi
}

# ── Change tracking ───────────────────────────────────────────────────────────
# Call track_change "description of what was done" after each destructive step
track_change() {
    CHANGES_MADE+=("$*")
}

# ── Clean abort (with partial-change report) ─────────────────────────────────
abort() {
    local reason="$*"
    printf "\n%s%s[ABORT]%s %s\n\n" "$CLR_BOLD" "$CLR_RED" "$CLR_RESET" "$reason"
    printf "\n[ABORT] %s\n" "$reason" >> "$LOG_FILE" 2>/dev/null || true

    if [[ "${#CHANGES_MADE[@]}" -gt 0 ]]; then
        log_warn "The following changes were made before the abort:"
        for change in "${CHANGES_MADE[@]}"; do
            log_warn "  • $change"
        done
        log_warn "Review and clean up manually if needed."
        log_warn "Log file: $LOG_FILE"
    else
        log_info "No changes were applied. System is unchanged."
    fi

    # Clean up temp dir if it exists
    [[ -d "$LOP_TMP_DIR" ]] && rm -rf "$LOP_TMP_DIR" 2>/dev/null || true

    exit 1
}

# ── Confirmation prompt ───────────────────────────────────────────────────────
# confirm "Destroy the database?" → exits 0 (yes) or 1 (no)
confirm() {
    local prompt="$*"
    if [[ "$YES_ALL" == "true" ]]; then
        log_info "Auto-confirmed (--yes): $prompt"
        return 0
    fi
    printf "%s%s%s [y/N] " "$CLR_YELLOW" "$prompt" "$CLR_RESET"
    local ans
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

# ── Command existence check ───────────────────────────────────────────────────
cmd_exists() { command -v "$1" &>/dev/null; }

# ── Parse script flags ────────────────────────────────────────────────────────
# Call parse_common_flags "$@" at the top of each script.
# Sets YES_ALL=true if --yes is present; strips --yes from remaining args.
parse_common_flags() {
    local args=()
    for arg in "$@"; do
        case "$arg" in
            --yes|-y) YES_ALL=true ;;
            *) args+=("$arg") ;;
        esac
    done
    # Re-export remaining args as positional parameters (caller uses eval)
    REMAINING_ARGS=("${args[@]}")
}

# ── Ensure a directory exists with correct ownership ─────────────────────────
ensure_dir() {
    local dir="$1" owner="${2:-root:root}" mode="${3:-755}"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        log_info "Created directory: $dir"
    fi
    chown "$owner" "$dir"
    chmod "$mode" "$dir"
}

# ── Source /etc/lop/lop.env safely ───────────────────────────────────────────
load_lop_env() {
    if [[ ! -f "$LOP_CONF_FILE" ]]; then
        abort "Configuration file not found: $LOP_CONF_FILE
Is LOP installed? Try: sudo ./install.sh"
    fi
    set -a
    # shellcheck disable=SC1090
    source "$LOP_CONF_FILE"
    set +a
    [[ -f "$LOP_RUNTIME_FILE" ]] && { set -a; source "$LOP_RUNTIME_FILE"; set +a; } || true
}

# ── Run a Flask management command in the LOP app context ────────────────────
lop_flask() {
    local flask_bin="$LOP_VENV_DIR/bin/flask"
    [[ -x "$flask_bin" ]] || abort "Flask not found at $flask_bin. Run install first."
    (
        cd "$LOP_APP_DIR"
        load_lop_env
        FLASK_APP=run.py FLASK_ENV=production "$flask_bin" "$@"
    )
}

# ── Health check via HTTP ─────────────────────────────────────────────────────
# health_check <url> <max_retries> <sleep_seconds>
health_check() {
    local url="$1" retries="${2:-12}" delay="${3:-5}"
    local i=0
    while (( i < retries )); do
        if curl -sf --max-time 5 "$url" &>/dev/null; then
            return 0
        fi
        i=$(( i + 1 ))
        if [[ $i -lt $retries ]]; then sleep "$delay"; fi
    done
    return 1
}

# ── Mask secrets in a file (for diagnostics/display) ─────────────────────────
mask_secrets() {
    local file="$1"
    sed -E \
        -e 's|(DATABASE_URL=(postgresql|postgres)://[^:]+:)[^@]*(@)|\1*** (masked)\3|' \
        -e 's/(PASSWORD|SECRET|KEY|TOKEN|PASS|BIND_PASSWORD|FREEIPA_BIND)([[:space:]]*=[[:space:]]*).*/\1\2*** (masked)/' \
        "$file"
}

# ── Ensure temp dir exists and is cleaned on exit ────────────────────────────
setup_tmp_dir() {
    mkdir -p "$LOP_TMP_DIR"
    # shellcheck disable=SC2064
    trap "rm -rf '$LOP_TMP_DIR'" EXIT
}

# ── Print a key=value summary line ───────────────────────────────────────────
summary_line() {
    local label="$1" value="$2"
    printf "  %-30s %s%s%s\n" "$label" "$CLR_CYAN" "$value" "$CLR_RESET"
}
