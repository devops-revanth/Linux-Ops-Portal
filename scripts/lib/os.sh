#!/usr/bin/env bash
# =============================================================================
# LOP — OS detection and package manager abstraction
# Source this file; do not execute it directly.
# =============================================================================

# Populated by detect_os()
OS_ID=""
OS_VERSION=""
OS_FAMILY=""
OS_NAME=""
PKG_MGR=""
PG_SERVICE="postgresql"
PG_DATA_DIR=""
PG_HBA_CONF=""

detect_os() {
    if [[ ! -f /etc/os-release ]]; then
        abort "Cannot detect operating system: /etc/os-release not found.
LOP requires a supported enterprise Linux distribution."
    fi

    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_VERSION="${VERSION_ID:-0}"
    OS_NAME="${PRETTY_NAME:-unknown}"

    case "${OS_ID}" in
        rhel|rocky|almalinux|centos)
            local major="${OS_VERSION%%.*}"
            if (( major < 8 )); then
                abort "Unsupported OS: ${OS_NAME}
RHEL/Rocky/AlmaLinux version 8 or newer is required."
            fi
            OS_FAMILY="rhel"
            PKG_MGR="dnf"
            PG_SERVICE="postgresql"
            PG_DATA_DIR="/var/lib/pgsql/data"
            PG_HBA_CONF="/var/lib/pgsql/data/pg_hba.conf"
            ;;
        ubuntu)
            local major="${OS_VERSION%%.*}"
            if (( major < 20 )); then
                abort "Unsupported OS: ${OS_NAME}
Ubuntu 20.04 or newer is required."
            fi
            OS_FAMILY="debian"
            PKG_MGR="apt-get"
            PG_SERVICE="postgresql"
            # Debian/Ubuntu use versioned data dirs; resolved after PG is installed
            PG_DATA_DIR="/var/lib/postgresql"
            ;;
        debian)
            local major="${OS_VERSION%%.*}"
            if (( major < 11 )); then
                abort "Unsupported OS: ${OS_NAME}
Debian 11 or newer is required."
            fi
            OS_FAMILY="debian"
            PKG_MGR="apt-get"
            PG_SERVICE="postgresql"
            PG_DATA_DIR="/var/lib/postgresql"
            ;;
        *)
            abort "Unsupported operating system: ${OS_NAME}
Supported: RHEL 8+, Rocky Linux 8+, AlmaLinux 8+, Ubuntu 20.04+, Debian 11+"
            ;;
    esac

    log_success "Detected OS: ${OS_NAME} (family=${OS_FAMILY}, pkg=${PKG_MGR})"
}

# pkg_install <package...>
# Installs one or more packages using the detected package manager.
# Returns 0 on success; calls abort() on network/repo failure.
pkg_install() {
    local pkgs=("$@")
    log_step "Installing packages: ${pkgs[*]}"

    case "$PKG_MGR" in
        dnf)
            if ! dnf install -y "${pkgs[@]}" >> "$LOG_FILE" 2>&1; then
                abort "Failed to install: ${pkgs[*]}
Possible causes:
  • No network access or repository unavailable
  • Package name differs on this OS version
Manual fix: sudo dnf install ${pkgs[*]}
Then re-run: sudo $0"
            fi
            ;;
        apt-get)
            # Refresh index only if it is stale (older than 1 hour)
            local cache_age
            cache_age=$(find /var/cache/apt/pkgcache.bin -mmin +60 2>/dev/null | wc -l)
            if (( cache_age > 0 )); then
                apt-get update -qq >> "$LOG_FILE" 2>&1 || true
            fi
            if ! DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}" >> "$LOG_FILE" 2>&1; then
                abort "Failed to install: ${pkgs[*]}
Possible causes:
  • No network access or repository unavailable
  • Package name differs on this OS version
Manual fix: sudo apt-get install ${pkgs[*]}
Then re-run: sudo $0"
            fi
            ;;
        *)
            abort "No package manager available. Cannot install: ${pkgs[*]}"
            ;;
    esac

    log_success "Installed: ${pkgs[*]}"
}

# pkg_installed <package>
# Returns 0 if the package is installed, 1 otherwise.
pkg_installed() {
    local pkg="$1"
    case "$PKG_MGR" in
        dnf)   rpm -q "$pkg" &>/dev/null ;;
        apt-get) dpkg -s "$pkg" &>/dev/null 2>&1 ;;
        *)     return 1 ;;
    esac
}

# pg_package_names
# Echoes the correct PostgreSQL package names for this OS.
pg_package_names() {
    case "$OS_FAMILY" in
        rhel)  echo "postgresql-server postgresql-contrib" ;;
        debian) echo "postgresql postgresql-contrib" ;;
    esac
}

# python_package_name <version>
# Echoes the correct Python package name for a given minor version.
python_package_name() {
    local minor="$1"   # e.g. "12" for 3.12
    case "$OS_FAMILY" in
        rhel)   echo "python3.${minor}" ;;
        debian) echo "python3.${minor} python3.${minor}-venv python3.${minor}-dev" ;;
    esac
}
