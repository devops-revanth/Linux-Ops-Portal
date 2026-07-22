#!/usr/bin/env bash
# =============================================================================
# LOP — Dependency detection and installation
# Source this file; do not execute it directly.
# =============================================================================

# ── Individual dependency checks ─────────────────────────────────────────────

# _check_dep_version <found_ver> <min_ver>
# Compares two dotted version strings. Returns 0 if found >= min.
_check_dep_version() {
    local found="$1" min="$2"
    # Use sort -V if available (GNU coreutils)
    if command -v sort &>/dev/null; then
        local lowest
        lowest=$(printf '%s\n%s' "$found" "$min" | sort -V | head -1)
        [[ "$lowest" == "$min" ]]
    else
        # Fallback: compare first two components numerically
        local f1 f2 m1 m2
        IFS=. read -r f1 f2 _ <<< "$found"
        IFS=. read -r m1 m2 _ <<< "$min"
        (( f1 > m1 )) || { (( f1 == m1 )) && (( ${f2:-0} >= ${m2:-0} )); }
    fi
}

# check_git
check_git() {
    if cmd_exists git; then
        local ver
        ver=$(git --version 2>/dev/null | awk '{print $3}')
        log_success "git: found ${ver}"
        return 0
    fi
    log_warn "git: not found — installing..."
    pkg_install git
}

# check_curl
check_curl() {
    if cmd_exists curl; then
        local ver
        ver=$(curl --version 2>/dev/null | head -1 | awk '{print $2}')
        log_success "curl: found ${ver}"
        return 0
    fi
    log_warn "curl: not found — installing..."
    pkg_install curl
}

# check_openssl
check_openssl() {
    if cmd_exists openssl; then
        local ver
        ver=$(openssl version 2>/dev/null | awk '{print $2}')
        log_success "openssl: found ${ver}"
        return 0
    fi
    log_warn "openssl: not found — installing..."
    case "$OS_FAMILY" in
        rhel)   pkg_install openssl openssl-devel ;;
        debian) pkg_install openssl libssl-dev ;;
    esac
}

# check_systemd
check_systemd() {
    if cmd_exists systemctl; then
        log_success "systemd: found"
        return 0
    fi
    abort "systemd not found. LOP requires systemd for service management.
If this system uses a different init system (SysV, OpenRC), service
installation must be done manually. Refer to docs/ARCHITECTURE.md."
}

# check_postgres_client
# Checks that psql (client) is available. The server is handled by postgres.sh.
check_postgres_client() {
    if cmd_exists psql; then
        local ver
        ver=$(psql --version 2>/dev/null | awk '{print $3}')
        log_success "psql client: found ${ver}"
        return 0
    fi
    log_warn "psql client: not found — installing..."
    case "$OS_FAMILY" in
        rhel)   pkg_install postgresql ;;
        debian) pkg_install postgresql-client ;;
    esac
}

# check_nodejs  (OPTIONAL)
# Does not abort if missing — Node.js is not required for current LOP.
check_nodejs() {
    if cmd_exists node; then
        local ver
        ver=$(node --version 2>/dev/null | tr -d 'v')
        log_success "Node.js: found v${ver} (optional)"
        return 0
    fi
    log_warn "Node.js: not found (optional — not required for current LOP version)"
    return 0
}

# check_pnpm  (OPTIONAL)
check_pnpm() {
    if cmd_exists pnpm; then
        local ver
        ver=$(pnpm --version 2>/dev/null)
        log_success "pnpm: found ${ver} (optional)"
        return 0
    fi
    log_warn "pnpm: not found (optional — not required for current LOP version)"
    return 0
}

# ── Required system packages for building Python C extensions ────────────────
check_build_deps() {
    log_step "Checking build dependencies..."
    case "$OS_FAMILY" in
        rhel)
            local pkgs_needed=()
            pkg_installed gcc          || pkgs_needed+=(gcc)
            pkg_installed libpq-devel  || pkgs_needed+=(libpq-devel)
            pkg_installed libffi-devel || pkgs_needed+=(libffi-devel)
            pkg_installed openssl-devel || pkgs_needed+=(openssl-devel)
            if [[ ${#pkgs_needed[@]} -gt 0 ]]; then
                log_warn "Missing build deps: ${pkgs_needed[*]} — installing..."
                pkg_install "${pkgs_needed[@]}"
            else
                log_success "Build dependencies: all present"
            fi
            ;;
        debian)
            local pkgs_needed=()
            pkg_installed gcc           || pkgs_needed+=(gcc)
            pkg_installed libpq-dev     || pkgs_needed+=(libpq-dev)
            pkg_installed libffi-dev    || pkgs_needed+=(libffi-dev)
            pkg_installed libssl-dev    || pkgs_needed+=(libssl-dev)
            if [[ ${#pkgs_needed[@]} -gt 0 ]]; then
                log_warn "Missing build deps: ${pkgs_needed[*]} — installing..."
                pkg_install "${pkgs_needed[@]}"
            else
                log_success "Build dependencies: all present"
            fi
            ;;
    esac
}

# ── Full dependency verification ─────────────────────────────────────────────
verify_all_deps() {
    log_section "Dependency Verification"
    check_systemd
    check_git
    check_curl
    check_openssl
    check_build_deps
    check_postgres_client
    check_nodejs   # optional
    check_pnpm     # optional
    log_success "All required dependencies satisfied."
}
