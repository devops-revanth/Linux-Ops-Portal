#!/usr/bin/env bash
# =============================================================================
# LOP — Python runtime detection and virtual environment management
# Source this file; do not execute it directly.
# =============================================================================

# Populated by python_select()
SELECTED_PYTHON=""
SELECTED_PYTHON_VERSION=""

# Minimum version (read from VERSION file if available, else hard default)
_py_min_minor() {
    local ver_file="${LOP_APP_DIR}/VERSION"
    # Also check the source repo dir (before install)
    [[ ! -f "$ver_file" ]] && ver_file="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/VERSION"
    if [[ -f "$ver_file" ]]; then
        local min
        min=$(grep '^MIN_PYTHON=' "$ver_file" | cut -d= -f2 | tr -d '[:space:]')
        echo "${min#*.}"   # strip "3." → "10"
        return
    fi
    echo "10"   # fallback: 3.10
}

PYTHON_MIN_MAJOR=3
# shellcheck disable=SC2034
PYTHON_MIN_MINOR=""   # set lazily in python_version_ok

# Candidate interpreter paths (highest version first)
PYTHON_CANDIDATES=(
    /usr/bin/python3.13
    /usr/local/bin/python3.13
    /usr/bin/python3.12
    /usr/local/bin/python3.12
    /usr/bin/python3.11
    /usr/local/bin/python3.11
    /usr/bin/python3.10
    /usr/local/bin/python3.10
    # RHEL Software Collections / AppStream
    /opt/rh/python313/root/usr/bin/python3.13
    /opt/rh/python312/root/usr/bin/python3.12
    /opt/rh/python311/root/usr/bin/python3.11
    /opt/rh/python310/root/usr/bin/python3.10
)

# python_get_version <executable>
# Outputs "major.minor.patch" or returns 1 if not a valid Python.
python_get_version() {
    local py="$1"
    [[ -x "$py" ]] || return 1
    "$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null
}

# python_version_ok <version_string>
# Returns 0 if version >= MIN_PYTHON (3.10 by default).
python_version_ok() {
    local version="$1"
    local major minor
    major="${version%%.*}"
    minor="${version#*.}"; minor="${minor%%.*}"
    local min_minor
    min_minor="$(_py_min_minor)"
    if (( major > PYTHON_MIN_MAJOR )); then
        return 0
    elif (( major == PYTHON_MIN_MAJOR )) && (( minor >= min_minor )); then
        return 0
    fi
    return 1
}

# python_version_newer <v1> <v2>
# Returns 0 if v1 is strictly newer than v2.
python_version_newer() {
    local v1="$1" v2="$2"
    local maj1 min1 pat1 maj2 min2 pat2
    IFS=. read -r maj1 min1 pat1 <<< "$v1"
    IFS=. read -r maj2 min2 pat2 <<< "$v2"
    pat1="${pat1:-0}"; pat2="${pat2:-0}"
    if (( maj1 > maj2 )); then return 0
    elif (( maj1 == maj2 )) && (( min1 > min2 )); then return 0
    elif (( maj1 == maj2 )) && (( min1 == min2 )) && (( pat1 > pat2 )); then return 0
    fi
    return 1
}

# python_find_compatible
# Scans PYTHON_CANDIDATES for the highest compatible interpreter.
# Sets SELECTED_PYTHON and SELECTED_PYTHON_VERSION on success.
python_find_compatible() {
    SELECTED_PYTHON=""
    SELECTED_PYTHON_VERSION=""

    for py in "${PYTHON_CANDIDATES[@]}"; do
        [[ -x "$py" ]] || continue
        local ver
        ver=$(python_get_version "$py") || continue
        if python_version_ok "$ver"; then
            if [[ -z "$SELECTED_PYTHON_VERSION" ]] || python_version_newer "$ver" "$SELECTED_PYTHON_VERSION"; then
                SELECTED_PYTHON="$py"
                SELECTED_PYTHON_VERSION="$ver"
            fi
        fi
    done

    [[ -n "$SELECTED_PYTHON" ]]
}

# python_install_best_available
# Attempts to install the best available Python via the OS package manager.
# Tries 3.13 → 3.12 → 3.11 → 3.10 in order, stops at first success.
python_install_best_available() {
    local min_minor
    min_minor="$(_py_min_minor)"
    local try_minors=(13 12 11)
    # Only try minors >= the minimum
    local candidates=()
    for m in "${try_minors[@]}"; do
        (( m >= min_minor )) && candidates+=("$m")
    done
    # Ensure min_minor itself is included
    candidates+=("$min_minor")

    log_step "Attempting to install Python 3.x via ${PKG_MGR}..."
    for minor in "${candidates[@]}"; do
        local pkgs
        pkgs=$(python_package_name "$minor")
        log_info "Trying Python 3.${minor} (packages: ${pkgs})..."
        case "$PKG_MGR" in
            dnf)
                # Try without aborting
                if dnf install -y ${pkgs} >> "$LOG_FILE" 2>&1; then
                    log_success "Installed Python 3.${minor}"
                    return 0
                fi
                ;;
            apt-get)
                apt-get update -qq >> "$LOG_FILE" 2>&1 || true
                if DEBIAN_FRONTEND=noninteractive apt-get install -y ${pkgs} >> "$LOG_FILE" 2>&1; then
                    log_success "Installed Python 3.${minor}"
                    return 0
                fi
                ;;
        esac
        log_warn "Python 3.${minor} not available via package manager."
    done

    local min_minor_str
    min_minor_str="$(_py_min_minor)"
    abort "Cannot install Python 3.${min_minor_str}+ automatically.
The system package manager could not install a compatible Python version.
This usually means:
  • No network access or repository unavailable
  • Python 3.${min_minor_str}+ packages not in enabled repositories

Manual fix (RHEL/Rocky/Alma):
  sudo dnf install python3.12 python3.12-devel
  
Manual fix (Ubuntu/Debian):
  sudo add-apt-repository ppa:deadsnakes/ppa
  sudo apt-get install python3.12 python3.12-venv python3.12-dev

After installing Python manually, re-run:  sudo $0"
}

# python_select
# Full orchestration: find compatible → install if needed → confirm selection.
python_select() {
    log_section "Python Runtime Selection"

    # Show what the system currently has
    local sys_py sys_ver
    sys_py=$(command -v python3 2>/dev/null || echo "none")
    if [[ "$sys_py" != "none" ]]; then
        sys_ver=$(python_get_version "$sys_py" 2>/dev/null || echo "unknown")
    else
        sys_ver="not found"
    fi
    log_info "System Python : ${sys_py} (${sys_ver})"

    if python_find_compatible; then
        log_success "Selected Python: ${SELECTED_PYTHON} (${SELECTED_PYTHON_VERSION})"
    else
        log_warn "No compatible Python (3.$(_py_min_minor)+) found. Attempting installation..."
        python_install_best_available
        # Re-scan after installation
        if ! python_find_compatible; then
            abort "Python installation reported success but no compatible interpreter found.
Check ${LOG_FILE} for details."
        fi
        log_success "Selected Python: ${SELECTED_PYTHON} (${SELECTED_PYTHON_VERSION})"
    fi

    # Write to runtime.env so update.sh and systemd can reference it
    _python_write_runtime_env
}

_python_write_runtime_env() {
    ensure_dir "$LOP_CONF_DIR" "root:root" "750"
    cat > "$LOP_RUNTIME_FILE" <<EOF
# LOP Runtime environment — generated by installer, do not edit manually.
# Re-generated on each install or Python change.
LOP_PYTHON=${SELECTED_PYTHON}
LOP_PYTHON_VERSION=${SELECTED_PYTHON_VERSION}
LOP_VENV=${LOP_VENV_DIR}
EOF
    chmod 640 "$LOP_RUNTIME_FILE"
    log_info "Runtime configuration written to ${LOP_RUNTIME_FILE}"
}

# python_create_venv [--force]
# Creates or updates /opt/lop/venv using the selected interpreter.
# Skips creation if the venv exists and Python/deps have not changed.
python_create_venv() {
    local force=false
    [[ "${1:-}" == "--force" ]] && force=true

    [[ -n "$SELECTED_PYTHON" ]] || abort "SELECTED_PYTHON is not set. Call python_select() first."

    local venv_python="$LOP_VENV_DIR/bin/python"
    local needs_rebuild=false

    if [[ ! -x "$venv_python" ]]; then
        log_info "Virtual environment does not exist — creating."
        needs_rebuild=true
    elif [[ "$force" == "true" ]]; then
        log_info "Forced venv rebuild requested."
        needs_rebuild=true
    else
        # Check if venv uses the same Python interpreter
        local venv_python_real
        venv_python_real=$(readlink -f "$venv_python" 2>/dev/null || true)
        local selected_real
        selected_real=$(readlink -f "$SELECTED_PYTHON" 2>/dev/null || "$SELECTED_PYTHON")
        if [[ "$venv_python_real" != "$selected_real" ]]; then
            log_warn "Venv Python (${venv_python_real}) differs from selected (${selected_real}) — rebuilding."
            needs_rebuild=true
        fi
    fi

    if [[ "$needs_rebuild" == "true" ]]; then
        log_step "Creating virtual environment at ${LOP_VENV_DIR}..."
        [[ -d "$LOP_VENV_DIR" ]] && rm -rf "$LOP_VENV_DIR"
        "$SELECTED_PYTHON" -m venv "$LOP_VENV_DIR" >> "$LOG_FILE" 2>&1 \
            || abort "Failed to create virtual environment using ${SELECTED_PYTHON}.
Check that python3-venv / python3.x-venv is installed."
        track_change "Created Python virtual environment at ${LOP_VENV_DIR}"
        log_success "Virtual environment created."
    else
        log_info "Virtual environment is up to date — reusing."
    fi
}

# python_install_deps [--upgrade]
# Installs or upgrades pip dependencies from requirements.txt.
python_install_deps() {
    local upgrade="${1:-}"
    local pip="$LOP_VENV_DIR/bin/pip"
    [[ -x "$pip" ]] || abort "pip not found at ${pip}. Virtual environment may be broken."

    log_step "Installing Python dependencies..."
    local req_file="$LOP_APP_DIR/requirements.txt"
    [[ -f "$req_file" ]] || abort "requirements.txt not found at ${req_file}."

    local pip_args=(install --quiet -r "$req_file")
    [[ "$upgrade" == "--upgrade" ]] && pip_args+=(--upgrade)

    if ! "$pip" "${pip_args[@]}" >> "$LOG_FILE" 2>&1; then
        # Distinguish network error from other failures
        if grep -qiE 'network|connect|timeout|unreachable' "$LOG_FILE" 2>/dev/null; then
            abort "pip install failed: network or repository unreachable.
The required Python packages cannot be downloaded.
If this server has no internet access, set up a local PyPI mirror and
configure pip to use it, then re-run: sudo $0"
        else
            abort "pip install failed. Check ${LOG_FILE} for details."
        fi
    fi
    log_success "Python dependencies installed."
}
