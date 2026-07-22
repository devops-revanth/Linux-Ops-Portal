"""
Ansible Fact Collection Service.

Connects to the Ansible control node via a SINGLE SSH session,
runs ansible ad-hoc modules with --tree output (one JSON file per host),
reads and parses the results, then bulk-updates the LOP database.

Architecture:
  1. One paramiko SSH session is opened to the control node.
  2. A temp directory is created on the control node (mktemp).
  3. ansible -m setup, package_facts, service_facts, and yum (updates)
     are run sequentially in the same session using --tree output.
  4. Files are read back in batches of BATCH_SIZE hosts.
  5. Each batch is processed in-memory then committed to DB.
  6. The temp directory is cleaned up in a finally block.

This module is READ-ONLY — it never executes playbooks, never issues
shell commands that modify Linux systems, and never modifies managed hosts.

Data ownership:
  Ansible owns: os/hardware/network fields, packages, services, filesystems.
  VMware owns:  vmware_vm_uuid, vmware_meta (never touched here).
  LOP owns:     environment, location, notes, compliance, status.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Generator

import threading
import time

logger = logging.getLogger(__name__)

# ── Thread-safe progress state ────────────────────────────────────────────── #
# Updated during collection so the /collect-status endpoint can report live.
_progress: dict = {
    "running":      False,
    "total":        0,
    "done":         0,
    "current_host": "",
    "started_at":   None,
}
_progress_lock = threading.Lock()


def get_progress() -> dict:
    """Return a snapshot of the current collection progress (thread-safe)."""
    with _progress_lock:
        return dict(_progress)


def _reset_progress(total: int) -> None:
    with _progress_lock:
        _progress.update({
            "running":      True,
            "total":        total,
            "done":         0,
            "current_host": "",
            "started_at":   time.monotonic(),
        })


def _update_progress(hostname: str) -> None:
    with _progress_lock:
        _progress["current_host"] = hostname
        _progress["done"] = _progress["done"] + 1


def _finish_progress() -> None:
    with _progress_lock:
        _progress["running"] = False
        _progress["current_host"] = ""


# ── Error sanitizer ───────────────────────────────────────────────────────── #
_SANITIZE_MAP = [
    ("Permission denied", "Permission denied"),
    ("Authentication failed", "Authentication failed"),
    ("timed out", "Timeout"),
    ("Connection refused", "Connection refused"),
    ("No route to host", "Host unreachable"),
    ("unreachable", "Host unreachable"),
    ("python", "Python not found on remote host"),
    ("MODULE FAILURE", "Ansible module failure"),
]


def _sanitize_error(exc_or_msg) -> str:
    """
    Return a short, user-facing error string.
    Never exposes stack traces, credentials, or internal paths.
    """
    msg = str(exc_or_msg) if exc_or_msg else ""
    for marker, friendly in _SANITIZE_MAP:
        if marker.lower() in msg.lower():
            return friendly
    # Generic fallback — take only the first 120 chars of the first line
    first_line = msg.splitlines()[0] if msg else "Unknown error"
    return first_line[:120]


# ── Filesystem types to skip (virtual / pseudo fs) ────────────────────────── #
_SKIP_FSTYPES: set[str] = {
    "tmpfs", "proc", "sysfs", "devtmpfs", "overlay", "cgroup", "cgroup2",
    "pstore", "securityfs", "debugfs", "tracefs", "configfs", "fusectl",
    "hugetlbfs", "mqueue", "devpts", "ramfs", "squashfs", "aufs",
}

BATCH_SIZE = 50       # hosts per batch read
DEFAULT_FORKS = 20    # ansible parallelism (-f flag)


# ── Public entry point ────────────────────────────────────────────────────── #

def collect_facts(cfg, app, triggered_by: str = "manual") -> dict[str, Any]:
    """
    Orchestrate a complete fact collection run.

    Opens ONE SSH session to the control node, runs all ansible modules,
    parses results, and bulk-updates the LOP database.  One AnsibleSyncJob
    row is created and updated throughout.

    Returns a summary dict:
      status          str   (completed | failed | partial)
      servers_total   int
      servers_ok      int
      servers_failed  int
      packages_synced int
      error           str | None
      job_id          int | None
    """
    from ..models.ansible_facts import AnsibleSyncJob
    from ..extensions import db
    from ..audit import commit_audit
    from ..services.ansible_service import AnsibleService, AnsibleConnectionError

    summary: dict[str, Any] = {
        "status":          "failed",
        "servers_total":   0,
        "servers_ok":      0,
        "servers_failed":  0,
        "packages_synced": 0,
        "error":           None,
        "job_id":          None,
    }

    # Create sync job record
    job = AnsibleSyncJob(
        triggered_by = triggered_by,
        status       = "running",
        started_at   = datetime.now(timezone.utc),
    )
    with app.app_context():
        db.session.add(job)
        db.session.commit()
        summary["job_id"] = job.id

    commit_audit(
        "ansible.facts.collect.start",
        details=f"triggered_by={triggered_by}",
        result="success",
    )

    svc    = AnsibleService.from_config(cfg)
    client = None
    tmpdir = None

    try:
        # ── 1. Connect ────────────────────────────────────────────────── #
        client = svc._connect()

        # ── 2. Create remote temp directory ──────────────────────────── #
        out, _, _ = AnsibleService._exec(client, "mktemp -d /tmp/lop_facts_XXXXXXXXXX")
        tmpdir = out.strip()
        if not tmpdir or not tmpdir.startswith("/tmp/"):
            raise RuntimeError(f"Unexpected temp dir path: {tmpdir!r}")

        inv = svc.inventory_path
        forks = DEFAULT_FORKS

        # ── 3. Run ansible modules (read-only) ────────────────────────── #
        # setup: OS, hardware, network, filesystems, timezone, SELinux
        _run_module(client, svc, "setup", inv, f"{tmpdir}/setup", forks)
        # package_facts: installed packages
        _run_module(client, svc, "package_facts", inv, f"{tmpdir}/packages", forks)
        # service_facts: service states
        _run_module(client, svc, "service_facts", inv, f"{tmpdir}/services", forks)
        # yum list=updates: available updates (RHEL family; skip on others)
        _run_yum_updates(client, svc, inv, f"{tmpdir}/yum_updates", forks)
        # yum repolist: enabled repos (RHEL family)
        _run_yum_repolist(client, svc, inv, f"{tmpdir}/yum_repos", forks)

        # ── 4. Get host list from setup tree ─────────────────────────── #
        hosts = _list_tree(client, f"{tmpdir}/setup")
        summary["servers_total"] = len(hosts)

        if not hosts:
            summary["status"] = "completed"
            summary["error"]  = "No hosts returned facts. Check inventory connectivity."
            _finalize_job(job, summary, app)
            return summary

        # ── 5. Initialize live progress counter ───────────────────────── #
        _reset_progress(len(hosts))

        # ── 6. Process in batches ─────────────────────────────────────── #
        with app.app_context():
            _server_map = _build_server_map()       # {hostname: server, fqdn: server}
            _package_map = _build_package_map()     # {name: package_id}

            for batch in _chunked(hosts, BATCH_SIZE):
                batch_data = _read_batch(client, tmpdir, batch)
                _persist_batch(batch_data, _server_map, _package_map, summary)
                db.session.commit()

        summary["status"] = "completed" if summary["servers_failed"] == 0 else "partial"

    except Exception as exc:  # includes AnsibleConnectionError
        summary["status"] = "failed"
        summary["error"]  = str(exc) if isinstance(exc, Exception.__class__) else (
            f"{type(exc).__name__}: {exc}"
        )
        logger.exception("Ansible fact collection failed")
    finally:
        _finish_progress()
        if tmpdir and client:
            try:
                AnsibleService._exec(client, f"rm -rf {tmpdir}", timeout=30)
            except Exception:
                pass
        if client:
            try:
                client.close()
            except Exception:
                pass

    _finalize_job(job, summary, app)

    commit_audit(
        "ansible.facts.collect.complete",
        details=(
            f"status={summary['status']} "
            f"ok={summary['servers_ok']} "
            f"failed={summary['servers_failed']} "
            f"packages={summary['packages_synced']}"
        ),
        result="success" if summary["status"] in ("completed", "partial") else "failure",
    )

    return summary


# ── Ansible command helpers ───────────────────────────────────────────────── #

def _run_module(client, svc, module: str, inv: str, tree_dir: str, forks: int) -> None:
    """Run an ansible ad-hoc module with --tree output. Failures are logged, not raised."""
    from ..services.ansible_service import AnsibleService, _q
    cmd = (
        f"ansible -m {module} -i {_q(inv)} all -f {forks} "
        f"--tree {_q(tree_dir)} 2>/dev/null; "
        f"mkdir -p {_q(tree_dir)}"  # ensure dir exists even if no hosts succeeded
    )
    AnsibleService._exec(client, cmd, timeout=600)


def _run_yum_updates(client, svc, inv: str, tree_dir: str, forks: int) -> None:
    """
    Gather available yum/dnf updates via 'ansible -m yum -a list=updates'.
    Non-RHEL hosts will produce errors that land in the tree files — they are
    detected during parsing and silently skipped.
    """
    from ..services.ansible_service import AnsibleService, _q
    cmd = (
        f"ansible -m yum -a 'list=updates' -i {_q(inv)} all -f {forks} "
        f"--tree {_q(tree_dir)} 2>/dev/null; "
        f"mkdir -p {_q(tree_dir)}"
    )
    AnsibleService._exec(client, cmd, timeout=600)


def _run_yum_repolist(client, svc, inv: str, tree_dir: str, forks: int) -> None:
    """
    Collect enabled repo list via shell command (read-only; yum repolist never
    modifies the system).  The command module is NOT the shell module — it runs
    the binary directly without a shell interpreter.
    """
    from ..services.ansible_service import AnsibleService, _q
    cmd = (
        f"ansible -m command -a 'yum repolist -q 2>/dev/null' "
        f"-i {_q(inv)} all -f {forks} "
        f"--tree {_q(tree_dir)} 2>/dev/null; "
        f"mkdir -p {_q(tree_dir)}"
    )
    AnsibleService._exec(client, cmd, timeout=600)


def _list_tree(client, dirpath: str) -> list[str]:
    """Return a list of filenames (hostnames) in a --tree output directory."""
    from ..services.ansible_service import AnsibleService, _q
    out, _, code = AnsibleService._exec(
        client,
        f"ls {_q(dirpath)} 2>/dev/null || echo ''",
        timeout=10,
    )
    return [f.strip() for f in out.splitlines() if f.strip()]


def _read_batch(client, tmpdir: str, hosts: list[str]) -> dict[str, dict]:
    """
    Read all tree files for a batch of hosts in a single SSH exec call.
    Returns: {hostname: {setup, packages, services, yum_updates, yum_repos}}
    """
    from ..services.ansible_service import AnsibleService, _q

    result: dict[str, dict] = {h: {} for h in hosts}

    for module, subdir in (
        ("setup",       "setup"),
        ("packages",    "packages"),
        ("services",    "services"),
        ("yum_updates", "yum_updates"),
        ("yum_repos",   "yum_repos"),
    ):
        parts = []
        for h in hosts:
            fpath = f"{tmpdir}/{subdir}/{h}"
            parts.append(
                f"printf '===HOST:{h}===\\n'; "
                f"cat {_q(fpath)} 2>/dev/null || printf '{{}}'; "
                f"printf '\\n===END===\\n'"
            )
        if not parts:
            continue

        batch_cmd = "; ".join(parts)
        out, _, _ = AnsibleService._exec(client, batch_cmd, timeout=120)

        current_host = None
        current_lines: list[str] = []

        for line in out.splitlines():
            if line.startswith("===HOST:") and line.endswith("==="):
                if current_host and current_lines:
                    _store_module(result, current_host, module, "\n".join(current_lines))
                current_host = line[8:-3]
                current_lines = []
            elif line == "===END===":
                if current_host and current_lines:
                    _store_module(result, current_host, module, "\n".join(current_lines))
                current_host = None
                current_lines = []
            elif current_host is not None:
                current_lines.append(line)

    return result


def _store_module(
    result: dict[str, dict], host: str, module: str, raw: str
) -> None:
    """Safely parse a JSON blob and store it under result[host][module]."""
    raw = raw.strip()
    if not raw or raw == "{}":
        return
    try:
        data = json.loads(raw)
        if host not in result:
            result[host] = {}
        result[host][module] = data
    except json.JSONDecodeError:
        logger.debug("Could not parse %s JSON for host %r", module, host)


# ── DB helpers ────────────────────────────────────────────────────────────── #

def _build_server_map() -> dict[str, Any]:
    """
    Load all Server rows into two lookup dicts (hostname → server, fqdn → server).
    Returns a single merged dict for O(1) lookup.
    """
    from ..models.server import Server
    servers = Server.query.all()
    m: dict[str, Any] = {}
    for s in servers:
        if s.hostname:
            m[s.hostname.lower()] = s
        if s.fqdn:
            m[s.fqdn.lower()] = s
    return m


def _build_package_map() -> dict[str, int]:
    """Load all Package rows: {name → id}."""
    from ..models.package import Package
    rows = Package.query.with_entities(Package.id, Package.name).all()
    return {r.name: r.id for r in rows}


def _persist_batch(
    batch_data: dict[str, dict],
    server_map: dict[str, Any],
    package_map: dict[str, int],
    summary: dict[str, Any],
) -> None:
    """
    Persist collected facts for a batch of hosts.

    For each host:
    - Match to an existing Server record (fqdn → hostname priority).
    - Update Ansible-owned Server fields (never touch VMware / LOP fields).
    - Replace ServerPackage records.
    - Replace AnsibleFilesystem records.
    - Replace AnsibleServerService records.
    - Replace AnsibleRepository records.
    - Update Patching.pending_updates if patching record exists.
    """
    from ..extensions import db
    from ..models.server import Server
    from ..models.package import Package, ServerPackage
    from ..models.patching import Patching
    from ..models.ansible_facts import (
        AnsibleFilesystem, AnsibleServerService, AnsibleRepository,
        TRACKED_SERVICES, _canonical_service,
    )
    from ..audit import log_action

    now = datetime.now(timezone.utc)

    for hostname, data in batch_data.items():
        # Live progress update: which host are we on right now?
        _update_progress(hostname)
        host_start = time.monotonic()

        setup = data.get("setup", {})
        unreachable = setup.get("unreachable") or setup.get("failed")
        if not setup or unreachable:
            summary["servers_failed"] += 1
            logger.debug("Host %r: setup facts not available", hostname)
            # Try to set status on matching server even when unreachable
            raw_err = setup.get("msg") or ("Host unreachable" if unreachable else "No setup facts returned")
            _set_server_status(hostname, None, server_map, "failed", 0, _sanitize_error(raw_err))
            continue

        facts = setup.get("ansible_facts", {})
        if not facts:
            summary["servers_failed"] += 1
            _set_server_status(hostname, None, server_map, "failed", 0, "No ansible_facts in response")
            continue

        # ── Find matching server ────────────────────────────────────── #
        server = _match_server(hostname, facts, server_map)
        if server is None:
            logger.debug("Host %r not found in LOP inventory — skipping", hostname)
            summary["servers_skipped"] = summary.get("servers_skipped", 0) + 1
            continue

        try:
            # ── Update Server (Ansible-owned fields only) ───────────── #
            _update_server_fields(server, facts, now)

            # ── Filesystems ─────────────────────────────────────────── #
            AnsibleFilesystem.query.filter_by(server_id=server.id).delete()
            for fs_row in _parse_filesystems(facts):
                db.session.add(AnsibleFilesystem(server_id=server.id, **fs_row))

            # ── Services ─────────────────────────────────────────────── #
            svc_data = data.get("services", {})
            if svc_data and not svc_data.get("failed") and not svc_data.get("unreachable"):
                services_facts = svc_data.get("ansible_facts", {}).get("services", {})
                AnsibleServerService.query.filter_by(server_id=server.id).delete()
                for svc_name, svc_info in services_facts.items():
                    if svc_name in TRACKED_SERVICES:
                        db.session.add(AnsibleServerService(
                            server_id = server.id,
                            name      = _canonical_service(svc_name),
                            state     = svc_info.get("state"),
                            enabled   = svc_info.get("status"),
                            synced_at = now,
                        ))

            # ── Packages ─────────────────────────────────────────────── #
            pkg_data = data.get("packages", {})
            if pkg_data and not pkg_data.get("failed") and not pkg_data.get("unreachable"):
                pkgs_facts = pkg_data.get("ansible_facts", {}).get("packages", {})
                updates_map = _parse_yum_updates(data.get("yum_updates", {}))

                new_pkg_rows, new_packages = _build_package_rows(
                    server.id, pkgs_facts, updates_map, package_map, now
                )
                if new_packages:
                    db.session.bulk_insert_mappings(Package, new_packages)
                    db.session.flush()
                    for p in new_packages:
                        fresh = Package.query.filter_by(name=p["name"]).first()
                        if fresh:
                            package_map[fresh.name] = fresh.id

                resolved = []
                for row in new_pkg_rows:
                    pid = row.get("package_id") or package_map.get(row.pop("_pkg_name", ""))
                    if pid:
                        row["package_id"] = pid
                        resolved.append(row)

                ServerPackage.query.filter_by(server_id=server.id).delete()
                if resolved:
                    db.session.bulk_insert_mappings(ServerPackage, resolved)
                    summary["packages_synced"] += len(resolved)

                update_count = sum(1 for r in resolved if r.get("update_available"))
                _update_patching(server, update_count, now)

            # ── Repositories ─────────────────────────────────────────── #
            repo_data = data.get("yum_repos", {})
            if repo_data and not repo_data.get("failed") and not repo_data.get("unreachable"):
                repo_rows = _parse_yum_repolist(repo_data)
                AnsibleRepository.query.filter_by(server_id=server.id).delete()
                for r in repo_rows:
                    db.session.add(AnsibleRepository(server_id=server.id, **r))

            # ── Per-server sync status ─────────────────────────────────── #
            duration = int(time.monotonic() - host_start)
            server.ansible_fact_status       = "success"
            server.ansible_fact_duration_secs = duration
            server.ansible_fact_error        = None

            log_action(
                "ansible.facts.server.update",
                target=server.hostname,
                details="source=ansible facts_collected=True",
            )
            summary["servers_ok"] += 1

        except Exception as exc:
            db.session.rollback()
            duration = int(time.monotonic() - host_start)
            err_msg  = _sanitize_error(exc)
            logger.warning("Failed to persist facts for host %r: %s", hostname, err_msg)
            # Update per-server status even on failure
            try:
                if server and server.id:
                    server.ansible_fact_status        = "failed"
                    server.ansible_fact_duration_secs = duration
                    server.ansible_fact_error         = err_msg
                    db.session.add(server)
                    db.session.commit()
            except Exception:
                pass
            summary["servers_failed"] += 1


# ── Parsing helpers ───────────────────────────────────────────────────────── #

def _match_server(hostname: str, facts: dict, server_map: dict) -> Any | None:
    """
    Match a collected hostname to a LOP Server record.
    Priority: ansible_fqdn → ansible_hostname → inventory hostname
    """
    fqdn = facts.get("ansible_fqdn", "")
    an_hn = facts.get("ansible_hostname", "")

    for candidate in (fqdn, an_hn, hostname):
        if candidate:
            s = server_map.get(candidate.lower())
            if s:
                return s
    return None


def _update_server_fields(server, facts: dict, now: datetime) -> None:
    """
    Write Ansible-owned fields to the Server row.
    Never touches: environment_id, location_id, owner_id, status,
                   vmware_vm_uuid, source (unless it was 'manual').
    """
    distro    = facts.get("ansible_distribution", "")
    version   = facts.get("ansible_distribution_version", "")
    release   = facts.get("ansible_distribution_release", "")

    if distro:
        server.operating_system = f"{distro} {version}".strip()
        server.os_version       = version or release or None

    kernel = facts.get("ansible_kernel")
    if kernel:
        server.kernel_version = kernel

    arch = facts.get("ansible_architecture")
    if arch:
        server.architecture = arch

    cpu_count = facts.get("ansible_processor_vcpus") or facts.get("ansible_processor_count")
    if cpu_count is not None:
        server.cpu_count = int(cpu_count)

    processors = facts.get("ansible_processor", [])
    if processors and len(processors) >= 3:
        # ansible_processor is [socket_count, vendor, model, ...]
        server.cpu_model = processors[2] if len(processors) > 2 else processors[-1]

    mem_mb = facts.get("ansible_memtotal_mb")
    if mem_mb is not None:
        server.ram_gb = round(mem_mb / 1024, 2)

    swap_mb = facts.get("ansible_swaptotal_mb")
    if swap_mb is not None:
        server.swap_gb = round(swap_mb / 1024, 2)

    ipv4 = facts.get("ansible_default_ipv4", {})
    if ipv4.get("address"):
        server.ip_address = ipv4["address"]
    if ipv4.get("gateway"):
        server.default_gateway = ipv4["gateway"]
    if ipv4.get("interface"):
        server.primary_interface = ipv4["interface"]
    if ipv4.get("macaddress"):
        server.mac_address = ipv4["macaddress"]

    dns = facts.get("ansible_dns", {})
    nameservers = dns.get("nameservers", [])
    if nameservers:
        server.dns_servers = ", ".join(str(ns) for ns in nameservers[:4])

    tz = facts.get("ansible_date_time", {}).get("tz")
    if tz:
        server.timezone = tz

    uptime = facts.get("ansible_uptime_seconds")
    if uptime is not None:
        server.uptime_seconds = int(uptime)

    selinux = facts.get("ansible_selinux", {})
    if isinstance(selinux, dict):
        server.selinux_status = selinux.get("status") or selinux.get("mode")
    elif isinstance(selinux, bool) and not selinux:
        server.selinux_status = "disabled"

    virt_type = facts.get("ansible_virtualization_type")
    virt_role = facts.get("ansible_virtualization_role")
    if virt_type and virt_role:
        server.virtualization_type = f"{virt_type}/{virt_role}"
    elif virt_type:
        server.virtualization_type = virt_type

    fqdn = facts.get("ansible_fqdn")
    if fqdn and not server.fqdn:
        server.fqdn = fqdn

    hn = facts.get("ansible_hostname")
    if hn and not server.hostname:
        server.hostname = hn

    server.last_ansible_sync = now


def _parse_filesystems(facts: dict) -> list[dict]:
    """
    Parse ansible_mounts into rows for AnsibleFilesystem.
    Skips virtual/pseudo filesystem types.
    """
    rows = []
    now = datetime.now(timezone.utc)
    for m in facts.get("ansible_mounts", []):
        fstype = m.get("fstype", "")
        if fstype in _SKIP_FSTYPES:
            continue
        device = m.get("device", "")
        mount  = m.get("mount", "")
        if not mount:
            continue
        size_b  = m.get("size_total", 0) or 0
        used_b  = size_b - (m.get("size_available", 0) or 0)
        avail_b = m.get("size_available", 0) or 0
        if size_b > 0:
            use_pct = int(used_b / size_b * 100)
        else:
            use_pct = 0
        rows.append({
            "mount":    mount,
            "device":   device,
            "fstype":   fstype,
            "size_gb":  round(size_b  / 1073741824, 2),
            "used_gb":  round(used_b  / 1073741824, 2),
            "avail_gb": round(avail_b / 1073741824, 2),
            "use_pct":  use_pct,
            "synced_at": now,
        })
    return rows


def _parse_yum_updates(yum_data: dict) -> dict[str, dict]:
    """
    Parse `ansible -m yum -a 'list=updates'` output.
    Returns {pkg_name: {available_version, repository, update_type}}.
    update_type heuristic: "security" if name contains "security" in repo, else "bugfix".
    """
    if not yum_data or yum_data.get("failed") or yum_data.get("unreachable"):
        return {}

    updates: dict[str, dict] = {}

    # yum module returns a 'results' list of text lines
    results = yum_data.get("results", [])
    for line in results:
        line = line.strip()
        if not line or line.startswith("Loaded") or line.startswith("Last"):
            continue
        # Format: "package-name.arch  version  repo"
        parts = line.split()
        if len(parts) >= 3:
            pkg_arch = parts[0]
            version  = parts[1]
            repo     = parts[2]
            # Strip arch suffix: "bash.x86_64" → "bash"
            pkg_name = pkg_arch.rsplit(".", 1)[0] if "." in pkg_arch else pkg_arch
            update_type = "security" if "security" in repo.lower() else "bugfix"
            updates[pkg_name] = {
                "available_version": version,
                "repository":        repo,
                "update_type":       update_type,
            }
    return updates


def _build_package_rows(
    server_id: int,
    pkgs_facts: dict,
    updates_map: dict[str, dict],
    package_map: dict[str, int],
    now: datetime,
) -> tuple[list[dict], list[dict]]:
    """
    Build ServerPackage insert rows and any new Package master rows needed.

    Returns (server_package_rows, new_packages_to_insert).
    """
    sp_rows: list[dict] = []
    new_pkgs: list[dict] = []
    seen_names: set[str] = set()  # dedup within this server

    for pkg_name, versions in pkgs_facts.items():
        if not versions or pkg_name in seen_names:
            continue
        seen_names.add(pkg_name)

        v_info = versions[0] if isinstance(versions, list) else {}
        version  = str(v_info.get("version", "") or "")
        if v_info.get("release"):
            version = f"{version}-{v_info['release']}" if version else v_info["release"]

        pkg_id = package_map.get(pkg_name)
        if not pkg_id:
            new_pkgs.append({"name": pkg_name, "display_name": pkg_name})

        upd = updates_map.get(pkg_name, {})
        sp_rows.append({
            "_pkg_name":       pkg_name,
            "package_id":      pkg_id,   # may be None — resolved after insert
            "server_id":       server_id,
            "version":         version or None,
            "collected_at":    now,
            "update_available": bool(upd),
            "available_version": upd.get("available_version"),
            "update_type":     upd.get("update_type"),
            "repository":      v_info.get("source") or upd.get("repository"),
        })

    return sp_rows, new_pkgs


def _parse_yum_repolist(repo_data: dict) -> list[dict]:
    """
    Parse `ansible -m command -a 'yum repolist -q'` output.
    Returns list of {repo_id, repo_name, enabled, synced_at}.
    """
    rows = []
    now = datetime.now(timezone.utc)
    stdout = repo_data.get("stdout", "")
    if not stdout:
        return rows

    # yum repolist -q output:
    # repo id                    repo name
    # rhel-9-baseos              Red Hat Enterprise Linux 9 BaseOS (RPMs)
    in_list = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("repo id"):
            in_list = True
            continue
        if not in_list:
            continue
        # Split on 2+ spaces to separate id from name
        parts = re.split(r"\s{2,}", line, maxsplit=1)
        if parts:
            repo_id = parts[0].strip()
            repo_name = parts[1].strip() if len(parts) > 1 else repo_id
            if repo_id:
                rows.append({
                    "repo_id":   repo_id,
                    "repo_name": repo_name,
                    "enabled":   True,
                    "baseurl":   None,
                    "synced_at": now,
                })
    return rows


def _set_server_status(
    hostname: str,
    facts: dict | None,
    server_map: dict,
    status: str,
    duration: int,
    error: str | None,
) -> None:
    """
    Update ansible_fact_status / duration / error on a matched server.
    Used when the host setup facts are not available (unreachable / failed).
    """
    try:
        from ..extensions import db
        server = _match_server(hostname, facts or {}, server_map)
        if server is None:
            return
        server.ansible_fact_status        = status
        server.ansible_fact_duration_secs = duration
        server.ansible_fact_error         = error
        db.session.add(server)
    except Exception:
        pass


def _update_patching(server, update_count: int, now: datetime) -> None:
    """Update the Patching record's pending_updates count from Ansible data."""
    from ..extensions import db
    from ..models.patching import Patching
    p = Patching.query.filter_by(server_id=server.id).first()
    if p is None:
        p = Patching(server_id=server.id, pending_updates=0)
        db.session.add(p)
    p.pending_updates = update_count


# ── Sync job finalization ─────────────────────────────────────────────────── #

def _finalize_job(job, summary: dict, app) -> None:
    """Write final stats to the AnsibleSyncJob row and update AnsibleConfig."""
    from ..extensions import db
    from ..models.ansible_config import AnsibleConfig

    try:
        with app.app_context():
            j = type(job).query.get(job.id)
            if j:
                j.status          = summary["status"]
                j.completed_at    = datetime.now(timezone.utc)
                j.servers_total   = summary["servers_total"]
                j.servers_ok      = summary["servers_ok"]
                j.servers_failed  = summary["servers_failed"]
                j.packages_synced = summary["packages_synced"]
                j.error_message   = summary.get("error")
                db.session.add(j)

            cfg = AnsibleConfig.query.first()
            if cfg:
                cfg.last_fact_sync_at     = datetime.now(timezone.utc)
                cfg.last_fact_sync_status = summary["status"]
                cfg.last_fact_sync_ok     = summary["servers_ok"]
                cfg.last_fact_sync_failed = summary["servers_failed"]
                db.session.add(cfg)

            db.session.commit()
    except Exception as exc:
        logger.warning("Failed to finalize sync job: %s", exc)


# ── Utility ───────────────────────────────────────────────────────────────── #

def _chunked(lst: list, n: int) -> Generator[list, None, None]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
