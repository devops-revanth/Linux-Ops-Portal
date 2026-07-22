---
name: Lifecycle management framework
description: Enterprise installer/updater/backup/health scripts added in scripts/ and lop CLI.
---

# LOP Lifecycle Management Framework

## What was built
Complete enterprise lifecycle management for bare-metal Linux deployment.

## File layout
```
scripts/
  install.sh       — fresh / upgrade (→ update.sh) / repair mode auto-detection
  update.sh        — intelligent update with rollback
  backup.sh        — timestamped DB+config archives
  restore.sh       — full or selective restore
  health.sh        — PASS/WARN/FAIL report (exit 0/1/2)
  diagnostics.sh   — full troubleshooting bundle (lop_diagnostics_YYYYMMDD.tar.gz)
  uninstall.sh     — teardown with optional data preservation
  lib/
    common.sh      — logging, abort, confirm, change tracking
    os.sh          — OS detection, pkg manager abstraction
    python.sh      — Python 3.10+ detection/install/venv
    deps.sh        — per-dependency check/install/abort
    postgres.sh    — PG detection, setup, dump, restore
    systemd.sh     — lop-backend.service generation
    version.sh     — VERSION file, alembic helpers, checksums
lop              — CLI dispatcher at repo root (symlinked to /usr/local/bin/lop)
VERSION          — APP_VERSION, INSTALLER_VERSION, BUILD_DATE, MIN_PYTHON
plugins/README.md — reserved for future VMware/Ansible/Azure/LDAP plugins
```

## App code changes (additive)
- `app/config.py`: `APP_VERSION` now read from `VERSION` file via `_read_version_file_key()`
- `app/blueprints/main/routes.py`: `/health` returns structured JSON (db, schema, python, memory, disk, uptime)

## Filesystem layout on target server
```
/opt/lop/           — application + venv
/etc/lop/           — lop.env, runtime.env, initial_credentials
/var/log/lop/       — install.log, update.log, health.log, app/
/var/backups/lop/   — timestamped .tar.gz archives
/var/lib/lop/       — checksums/, install.info
/tmp/lop/           — ephemeral working dir
```

## Key rules
**Why:** Config always lives outside /opt/lop so `update.sh` never overwrites it.
**How to apply:** Never write user settings to /opt/lop. Read from /etc/lop/lop.env.

**Why:** Python is never hardcoded. Selected interpreter written to /etc/lop/runtime.env.
**How to apply:** All scripts use `$LOP_VENV_DIR/bin/gunicorn` and `$LOP_VENV_DIR/bin/flask` — never `python3` or `python3.12`.

**Why:** Update source stored in /var/lib/lop/install.info (git/archive/local).
**How to apply:** `update.sh` reads `install_source` and branches accordingly. Never assume `git pull`.

**Why:** Checksums in /var/lib/lop/checksums/ make updates intelligent.
**How to apply:** pip/pnpm/migrations only run when their inputs changed.

## Supported OS
RHEL 9, Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04+, Debian 12+
