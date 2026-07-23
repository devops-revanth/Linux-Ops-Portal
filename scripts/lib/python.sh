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
    local try_minors=(13 12 11 10)
    # Only try minors >= the minimum
    local candidates=()
    for m in "${try_minors[@]}"; do
        (( m >= min_minor )) && candidates+=("$m")
    done
    # Ensure min_minor itself is included
    candidates+=("$min_minor")

    log_step "Attempting to install Python 3.x via ${PKG_MGR}..."
    for minor in "${candidates[@]}"; do
        local pkgs_str pkgs=()
        pkgs_str=$(python_package_name "$minor")
        IFS=' ' read -ra pkgs <<< "$pkgs_str"
        log_info "Trying Python 3.${minor} (packages: ${pkgs[*]})..."
        case "$PKG_MGR" in
            dnf)
                if dnf install -y "${pkgs[@]}" >> "$LOG_FILE" 2>&1; then
                    log_success "Installed Python 3.${minor}"
                    return 0
                fi
                ;;
            apt-get)
                apt-get update -qq >> "$LOG_FILE" 2>&1 || true
                if DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}" >> "$LOG_FILE" 2>&1; then
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

    # Install the development headers that exactly match the selected interpreter.
    # This must run after python_find_compatible() so the minor version is known.
    # On Rocky/RHEL 9 the generic 'python3-devel' installs Python 3.9 headers;
    # we need python3.11-devel (or python3.12-devel, etc.) to match the binary.
    python_install_devel_headers

    # Write to runtime.env so update.sh and systemd can reference it
    _python_write_runtime_env
}

# ── Python development headers ────────────────────────────────────────────────

# python_devel_package_name [version]
# Returns the OS-specific package name for the Python C development headers
# that exactly match the given (or currently selected) interpreter version.
#
#   python3.11.13 → "python3.11-devel"  (RHEL/Rocky/AlmaLinux)
#   python3.12.4  → "python3.12-devel"  (RHEL/Rocky/AlmaLinux)
#   python3.11.13 → "python3.11-dev"    (Ubuntu/Debian)
#
# The generic 'python3-devel' is NEVER returned — on Rocky Linux 9 it installs
# Python 3.9 headers even when the selected interpreter is python3.11 or newer.
python_devel_package_name() {
    local version="${1:-${SELECTED_PYTHON_VERSION:-}}"
    local minor
    minor="${version#*.}"    # "3.11.13" → "11.13"
    minor="${minor%%.*}"     # "11.13"   → "11"
    if [[ -z "$minor" ]]; then
        echo ""
        return 1
    fi
    case "${OS_FAMILY:-}" in
        rhel)   echo "python3.${minor}-devel" ;;
        debian) echo "python3.${minor}-dev" ;;
        *)      echo "" ;;
    esac
}

# python_verify_headers
# Confirms that Python.h exists for the selected interpreter.
# Aborts with a clear, actionable message if the headers are missing so that
# operators see a helpful error instead of a confusing compile failure inside pip.
python_verify_headers() {
    # Called defensively before pip — skip gracefully if not yet selected.
    [[ -n "${SELECTED_PYTHON:-}" ]] || return 0

    local include_dir
    include_dir=$("$SELECTED_PYTHON" -c \
        "from sysconfig import get_paths; print(get_paths()['include'])" \
        2>/dev/null || echo "")

    if [[ -z "$include_dir" ]]; then
        abort "Cannot determine the Python include directory for ${SELECTED_PYTHON}.
The interpreter may be incomplete or broken.
Try: sudo $SELECTED_PYTHON -c \"from sysconfig import get_paths; print(get_paths()['include'])\""
    fi

    if [[ ! -f "${include_dir}/Python.h" ]]; then
        local minor
        minor="${SELECTED_PYTHON_VERSION#*.}"; minor="${minor%%.*}"
        abort "Python.h not found: ${include_dir}/Python.h
The development headers for ${SELECTED_PYTHON} (${SELECTED_PYTHON_VERSION}) are not installed.
psycopg2 and other C extensions cannot be compiled without them.

Install the matching headers and re-run:
  RHEL/Rocky/AlmaLinux:  sudo dnf install python3.${minor}-devel
  Ubuntu/Debian:          sudo apt-get install python3.${minor}-dev"
    fi

    log_info "Python headers verified: ${include_dir}/Python.h"
}

# python_install_devel_headers
# Installs the development headers (Python.h) that exactly match the selected
# interpreter. Must be called after python_select() / python_find_compatible()
# so that SELECTED_PYTHON_VERSION is known.
#
# Why this is necessary
# ─────────────────────
# On Rocky Linux 9, 'python3-devel' (the generic package) installs headers for
# Python 3.9 — the OS-default python3 — regardless of which python3.x binary
# is actually selected.  When the installer picks python3.11, compiling
# psycopg2 fails immediately with:
#   fatal error: Python.h: No such file or directory
# because /usr/include/python3.9 exists but /usr/include/python3.11 does not.
# The fix is always installing the version-specific package:
#   python3.11 → python3.11-devel
#   python3.12 → python3.12-devel
#   python3.13 → python3.13-devel
python_install_devel_headers() {
    [[ -n "${SELECTED_PYTHON:-}" ]] || \
        abort "SELECTED_PYTHON is not set. Call python_select() first."

    local devel_pkg
    devel_pkg=$(python_devel_package_name)

    if [[ -z "$devel_pkg" ]]; then
        log_warn "Unsupported OS family '${OS_FAMILY:-unknown}' — cannot determine Python header package."
        log_warn "Ensure Python.h is present for ${SELECTED_PYTHON} before running pip."
        return 0
    fi

    log_info "Selected Python            : ${SELECTED_PYTHON_VERSION}"
    log_step "Installing matching headers: ${devel_pkg}"

    if pkg_installed "$devel_pkg"; then
        log_success "Python headers already present: ${devel_pkg}"
    else
        pkg_install "$devel_pkg"
        track_change "Installed Python development headers: ${devel_pkg}"
    fi

    # Always verify after install — catches silent failures and
    # cases where the package installed but to a non-standard path.
    python_verify_headers
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
        # Move the old venv aside so it can be restored if creation fails
        local _venv_backup="${LOP_VENV_DIR}.old.$$"
        [[ -d "$LOP_VENV_DIR" ]] && mv "$LOP_VENV_DIR" "$_venv_backup"
        if ! "$SELECTED_PYTHON" -m venv "$LOP_VENV_DIR" >> "$LOG_FILE" 2>&1; then
            # Restore the previous working venv on failure
            rm -rf "$LOP_VENV_DIR" 2>/dev/null || true
            [[ -d "$_venv_backup" ]] && mv "$_venv_backup" "$LOP_VENV_DIR" || true
            abort "Failed to create virtual environment using ${SELECTED_PYTHON}.
Check that python3-venv / python3.x-venv is installed."
        fi
        rm -rf "$_venv_backup" 2>/dev/null || true
        track_change "Created Python virtual environment at ${LOP_VENV_DIR}"
        log_success "Virtual environment created."
    else
        log_info "Virtual environment is up to date — reusing."
    fi
}

# python_bootstrap_toolchain
# Upgrades pip, setuptools, and wheel to current versions inside the venv.
# Must be called after python_create_venv().
#
# Rationale: fresh venvs ship with the pip version bundled into the Python
# installation, which may be years out of date.  An old pip cannot resolve
# newer wheel metadata formats (PEP 658 / 643) and may not recognise
# manylinux wheel tags for the current glibc.  Upgrading before installing
# requirements.txt prevents silent fallbacks to source compilation.
python_bootstrap_toolchain() {
    local pip="$LOP_VENV_DIR/bin/pip"
    [[ -x "$pip" ]] || abort "pip not found at ${pip}. Virtual environment may be broken."

    log_step "Bootstrapping pip toolchain..."

    # Verify pip responds at all before attempting an upgrade
    if ! "$pip" --version >> "$LOG_FILE" 2>&1; then
        abort "pip is not functional in the virtual environment at ${LOP_VENV_DIR}.
Try removing the venv and re-running: sudo $0 --repair"
    fi

    if ! "$pip" install --quiet --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1; then
        abort "Failed to upgrade pip/setuptools/wheel.
This is usually a network issue or a broken PyPI mirror.
Check ${LOG_FILE} for details."
    fi

    local pip_ver setuptools_ver wheel_ver
    pip_ver=$("$pip" show pip 2>/dev/null | awk '/^Version:/{print $2}')
    setuptools_ver=$("$pip" show setuptools 2>/dev/null | awk '/^Version:/{print $2}')
    wheel_ver=$("$pip" show wheel 2>/dev/null | awk '/^Version:/{print $2}')

    log_success "pip         ${pip_ver}"
    log_success "setuptools  ${setuptools_ver}"
    log_success "wheel       ${wheel_ver}"
}

# python_verify_imports
# Imports every critical LOP module to confirm all C extensions compiled
# successfully.  Stops immediately if any import fails, naming the package.
python_verify_imports() {
    local venv_python="$LOP_VENV_DIR/bin/python"
    [[ -x "$venv_python" ]] || abort "Venv Python not found at ${venv_python}."

    log_step "Verifying Python module imports..."

    local modules=(flask sqlalchemy alembic psycopg2 ldap3 cryptography pyVmomi paramiko apscheduler)
    local failed=()

    for mod in "${modules[@]}"; do
        if "$venv_python" -c "import ${mod}" >> "$LOG_FILE" 2>&1; then
            log_success "${mod}"
        else
            log_error "FAILED to import: ${mod}"
            failed+=("$mod")
        fi
    done

    if [[ ${#failed[@]} -gt 0 ]]; then
        abort "Python module import verification failed.
The following packages did not import successfully:
$(printf '  • %s\n' "${failed[@]}")

This usually means a C extension failed to compile (check ${LOG_FILE} for the
pip build output), or a native library is missing (libpq, libffi, openssl,
cargo/rustc for the cryptography package).
Re-run after resolving the above: sudo $0"
    fi

    log_success "All Python modules verified."
}

# python_runtime_report
# Prints a complete runtime verification table after a successful install.
python_runtime_report() {
    local venv_python="$LOP_VENV_DIR/bin/python"
    local pip="$LOP_VENV_DIR/bin/pip"

    local py_ver pip_ver include_dir header_status compiler pg_lib
    py_ver=$("$venv_python" --version 2>/dev/null || echo "unknown")
    pip_ver=$("$pip" --version 2>/dev/null | awk '{print $2}' || echo "unknown")
    include_dir=$("$venv_python" -c \
        "from sysconfig import get_paths; print(get_paths()['include'])" \
        2>/dev/null || echo "unknown")

    if [[ -f "${include_dir}/Python.h" ]]; then
        header_status="present (${include_dir}/Python.h)"
    else
        header_status="MISSING — ${include_dir}/Python.h not found"
    fi

    if cmd_exists gcc; then
        compiler="$(command -v gcc) ($(gcc --version 2>/dev/null | awk 'NR==1{print $NF}'))"
    else
        compiler="not found"
    fi

    pg_lib="not found"
    if cmd_exists pg_config; then
        pg_lib="$(pg_config --libdir 2>/dev/null || echo 'pg_config present')"
    elif [[ -d /usr/lib64/pgsql ]] || [[ -d /usr/lib/postgresql ]]; then
        pg_lib="found via filesystem"
    fi

    log_section "Runtime Verification"
    summary_line "Virtual Environment:" "$LOP_VENV_DIR"
    summary_line "Python Version:"      "$py_ver"
    summary_line "pip Version:"         "$pip_ver"
    summary_line "Header Location:"     "$include_dir"
    summary_line "Python.h:"            "$header_status"
    summary_line "Compiler:"            "$compiler"
    summary_line "PostgreSQL libs:"     "$pg_lib"
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

    # Verify Python.h is present before attempting compilation.
    # psycopg2 (and cryptography) compile C extensions and will fail immediately
    # with "fatal error: Python.h: No such file or directory" if the devel headers
    # for the selected interpreter are missing.  Checking here gives a clear,
    # actionable error instead of a confusing compile traceback inside pip.
    python_verify_headers

    # Upgrade pip/setuptools/wheel to the latest versions in the venv before
    # processing requirements.txt — an outdated pip may fall back to source
    # compilation when a pre-built wheel is available.
    python_bootstrap_toolchain

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

    # Verify every critical module can actually be imported.
    # This catches silent compile failures that pip reports as success.
    python_verify_imports

    # Print the full runtime verification table.
    python_runtime_report
}
